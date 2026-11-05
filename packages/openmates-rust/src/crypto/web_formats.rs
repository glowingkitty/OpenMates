//! Readers for existing web-client encryption formats that had no Rust reader:
//! passkey (PRF) master wrapping, hidden-chat key wrapping, chat/embed share key
//! blobs, short share URLs and stored media payloads. Each reader mirrors the
//! deployed TypeScript reader byte-for-byte (see tests/crypto_fixtures/
//! ts_web_formats.json, produced by the actual TS modules). Every path requires
//! an authenticated AES-GCM tag; no reader falls back to another layout after a
//! selected candidate fails.
use super::*;

/// frontend/.../shareEncryption.ts and embedShareEncryption.ts work factor.
const SHARE_PBKDF2_ITERATIONS: u32 = 100_000;
/// frontend/.../shortUrlEncryption.ts work factor.
const SHORT_URL_PBKDF2_ITERATIONS: u32 = 200_000;
/// frontend/.../encryption/mediaEncryption.ts MEDIA_ENCRYPTION_V2 marker.
pub const MEDIA_ENCRYPTION_V2: &str = "aes-gcm-nonce-prefixed-v1";

fn pbkdf2_key(secret: &[u8], salt: &[u8], iterations: u32) -> Key {
    let mut key = Zeroizing::new([0u8; 32]);
    pbkdf2::pbkdf2_hmac::<Sha256>(secret, salt, iterations, key.as_mut());
    key
}

/// base64(12-byte IV || ciphertext || tag) after browser base64 preprocessing.
fn open_iv_prefixed(bytes: &[u8], key: &[u8; 32]) -> Result<Zeroizing<Vec<u8>>> {
    if bytes.len() < 12 + 16 {
        return Err(Error::Crypto);
    }
    decrypt_aead(&bytes[12..], key, &bytes[..12], &[])
}

fn exact_key(raw: &[u8]) -> Result<Key> {
    if raw.len() != 32 {
        return Err(Error::Crypto);
    }
    let mut key = Zeroizing::new([0u8; 32]);
    key.copy_from_slice(raw);
    Ok(key)
}

// ── Passkey PRF master wrapping (cryptoService.deriveWrappingKeyFromPRF) ──

/// HKDF-SHA256(salt = user_email_salt, ikm = PRF output, info = "masterkey_wrapping").
pub fn passkey_wrapping_key(prf_output: &[u8], email_salt: &[u8]) -> Result<Key> {
    // getPRFSignatureFromCredential rejects PRF outputs outside 16..=64 bytes.
    if !(16..=64).contains(&prf_output.len()) {
        return Err(Error::Crypto);
    }
    hkdf_sha256(prf_output, email_salt, b"masterkey_wrapping")
}

/// Unwraps the passkey-wrapped master key (`encrypted_master_key` + `key_iv`).
pub fn unwrap_passkey_master_key(prf_output: &[u8], email_salt: &[u8], ciphertext: &str, iv: &str) -> Result<Key> {
    let wrapping = passkey_wrapping_key(prf_output, email_salt)?;
    unwrap_master_key_with_wrapping_key(ciphertext, iv, &wrapping)
}

// ── Hidden chats (hiddenChatService.deriveCombinedSecret) ──

/// PBKDF2-SHA256(base64(master || code), user_email_salt[0..16], 100k).
pub fn hidden_chat_secret(master: &[u8; 32], code: &str, email_salt: &[u8]) -> Result<Key> {
    let units = code.encode_utf16().count();
    if !(4..=30).contains(&units) || email_salt.is_empty() {
        return Err(Error::Crypto);
    }
    let mut combined = Zeroizing::new(master.to_vec());
    combined.extend_from_slice(code.as_bytes());
    let encoded = Zeroizing::new(STANDARD.encode(combined.as_slice()));
    let salt = &email_salt[..email_salt.len().min(16)];
    Ok(pbkdf2_key(encoded.as_bytes(), salt, LEGACY_PASSWORD_ITERATIONS))
}

/// Opens a hidden chat's `encrypted_chat_key` (IV-prefixed, no OM header).
pub fn unwrap_hidden_chat_key(encrypted_chat_key: &str, secret: &[u8; 32]) -> Result<Key> {
    let raw = open_iv_prefixed(&master::decode_browser_base64(encrypted_chat_key)?, secret)?;
    exact_key(&raw)
}

// ── Share links (shareEncryption.ts / embedShareEncryption.ts) ──

/// Non-success results the TS readers report distinctly from authentication
/// failure (`Err(Error::Crypto)` corresponds to TS `decryption_failed`).
#[derive(Debug, PartialEq, Eq)]
pub enum ShareKeyRefusal {
    Expired,
    PasswordRequired,
    InvalidPassword,
}

struct ShareBlob {
    key: Zeroizing<String>,
    generated_at: f64,
    duration_seconds: f64,
    pwd: f64,
}

/// JS `parseInt(value, 10)`: leading whitespace, optional sign, digit prefix; NaN otherwise.
fn js_parse_int(value: &str) -> f64 {
    let trimmed = value.trim_start();
    let (sign, rest) = match trimmed.as_bytes().first() {
        Some(b'-') => (-1.0, &trimmed[1..]),
        Some(b'+') => (1.0, &trimmed[1..]),
        _ => (1.0, trimmed),
    };
    let digits: &str = &rest[..rest.bytes().take_while(u8::is_ascii_digit).count()];
    if digits.is_empty() { f64::NAN } else { sign * digits.parse::<f64>().unwrap_or(f64::NAN) }
}

fn open_share_blob(id: &str, encrypted_blob: &str, key_field: &str) -> Result<ShareBlob> {
    let id_key = pbkdf2_key(id.as_bytes(), b"openmates-share-v1", SHARE_PBKDF2_ITERATIONS);
    let plain = open_iv_prefixed(&master::decode_browser_base64(encrypted_blob)?, &id_key)?;
    let serialized = Zeroizing::new(String::from_utf8_lossy(&plain).into_owned());
    // URLSearchParams.get returns the first value; `|| "0"` maps missing/empty to "0".
    let get = |name: &str| -> Zeroizing<String> {
        Zeroizing::new(url::form_urlencoded::parse(serialized.as_bytes())
            .find(|(k, _)| k == name).map(|(_, v)| v.into_owned()).unwrap_or_default())
    };
    let number = |name: &str| { let v = get(name); js_parse_int(if v.is_empty() { "0" } else { v.as_str() }) };
    Ok(ShareBlob { key: get(key_field), generated_at: number("generated_at"), duration_seconds: number("duration_seconds"), pwd: number("pwd") })
}

fn share_password_open(id: &str, password: &str, value: &str) -> std::result::Result<Zeroizing<String>, ShareKeyRefusal> {
    let key = pbkdf2_key(password.as_bytes(), format!("openmates-pwd-{id}").as_bytes(), SHARE_PBKDF2_ITERATIONS);
    let bytes = master::decode_browser_base64(value).map_err(|_| ShareKeyRefusal::InvalidPassword)?;
    let plain = open_iv_prefixed(&bytes, &key).map_err(|_| ShareKeyRefusal::InvalidPassword)?;
    Ok(Zeroizing::new(String::from_utf8_lossy(&plain).into_owned()))
}

fn expired(blob: &ShareBlob, server_time: i64) -> bool {
    blob.duration_seconds > 0.0 && (server_time as f64) > blob.generated_at + blob.duration_seconds
}

/// `decryptShareKeyBlob`: returns the shared chat key string (base64) exactly as
/// stored. Order matches TS: password requirement, then expiry, then password.
pub fn decrypt_chat_share_key_blob(
    chat_id: &str,
    encrypted_blob: &str,
    server_time: i64,
    password: Option<&str>,
) -> Result<std::result::Result<Zeroizing<String>, ShareKeyRefusal>> {
    let blob = open_share_blob(chat_id, encrypted_blob, "chat_encryption_key")?;
    let password = password.filter(|value| !value.is_empty());
    if blob.pwd == 1.0 && password.is_none() {
        return Ok(Err(ShareKeyRefusal::PasswordRequired));
    }
    if expired(&blob, server_time) {
        return Ok(Err(ShareKeyRefusal::Expired));
    }
    match (blob.pwd == 1.0, password) {
        (true, Some(password)) => Ok(share_password_open(chat_id, password, &blob.key)),
        _ => Ok(Ok(blob.key)),
    }
}

/// `decryptEmbedShareKeyBlob`: expiry precedes the password requirement and the
/// embed key is decoded with strict-alphabet `atob` (any length, as in TS).
pub fn decrypt_embed_share_key_blob(
    embed_id: &str,
    encrypted_blob: &str,
    server_time: i64,
    password: Option<&str>,
) -> Result<std::result::Result<Zeroizing<Vec<u8>>, ShareKeyRefusal>> {
    let blob = open_share_blob(embed_id, encrypted_blob, "embed_encryption_key")?;
    if expired(&blob, server_time) {
        return Ok(Err(ShareKeyRefusal::Expired));
    }
    let encoded = if blob.pwd == 1.0 {
        match password.filter(|value| !value.is_empty()) {
            None => return Ok(Err(ShareKeyRefusal::PasswordRequired)),
            Some(password) => match share_password_open(embed_id, password, &blob.key) {
                Ok(value) => value,
                Err(refusal) => return Ok(Err(refusal)),
            },
        }
    } else {
        blob.key
    };
    if encoded.contains(['-', '_']) {
        return Err(Error::Crypto);
    }
    Ok(Ok(Zeroizing::new(master::decode_browser_base64(&encoded)?)))
}

/// `decryptShareUrl`: PBKDF2(shortKey, "omts-v1-" + token, 200k), base64url(IV||ct).
pub fn decrypt_short_url(encrypted_url: &str, token: &str, short_key: &str) -> Result<String> {
    let key = pbkdf2_key(short_key.as_bytes(), format!("omts-v1-{token}").as_bytes(), SHORT_URL_PBKDF2_ITERATIONS);
    let plain = open_iv_prefixed(&master::decode_browser_base64(encrypted_url)?, &key)?;
    Ok(String::from_utf8_lossy(&plain).into_owned())
}

// ── Media payloads (encryption/mediaEncryption.ts decryptMediaPayload) ──

/// Stored-media metadata as read by the TS reader. `legacy_nonce` distinguishes
/// absent (`None`, TS null) from the explicit empty legacy marker (`Some("")`).
pub struct MediaEncryption<'a> {
    pub encryption: Option<&'a str>,
    pub aes_nonce: Option<&'a str>,
    pub legacy_nonce: Option<&'a str>,
}

pub fn decrypt_media_payload(data: &[u8], aes_key_b64: &str, meta: &MediaEncryption<'_>) -> Result<Zeroizing<Vec<u8>>> {
    let key = exact_key(&Zeroizing::new(master::decode_browser_base64(aes_key_b64)?))?;
    let (nonce, ciphertext): (Vec<u8>, &[u8]) = match meta.encryption.filter(|v| !v.is_empty()) {
        Some(MEDIA_ENCRYPTION_V2) => {
            if data.len() < 12 + 16 { return Err(Error::Crypto); }
            (data[..12].to_vec(), &data[12..])
        }
        Some(_) => return Err(Error::Crypto),
        None => match truthy(meta.aes_nonce).or(truthy(meta.legacy_nonce)) {
            Some(external) => (master::decode_browser_base64(external)?, data),
            None if meta.legacy_nonce == Some("") => {
                if data.len() < 12 + 16 { return Err(Error::Crypto); }
                (data[..12].to_vec(), &data[12..])
            }
            None => return Err(Error::Crypto),
        },
    };
    if nonce.len() != 12 {
        return Err(Error::Crypto);
    }
    decrypt_aead(ciphertext, &key, &nonce, &[])
}

/// JS truthiness for optional metadata strings (`""` and null are falsy).
fn truthy(value: Option<&str>) -> Option<&str> {
    value.filter(|v| !v.is_empty())
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "web_formats_tests.rs"]
mod tests;
