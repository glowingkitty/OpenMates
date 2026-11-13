//! Share-link, embed-share and short-URL formats, sans IO. Mirrors
//! shareEncryption.ts, embedShareEncryption.ts and shortUrlEncryption.ts:
//! PBKDF2-SHA256 derived AES-GCM keys, base64url(IV || ciphertext || tag) and
//! the URLSearchParams key blob. The synchronous writers here serve native and
//! tests; the browser binding runs the same steps on WebCrypto. Readers live in
//! `web_formats` and use the shared parsing/decision helpers below.
use super::*;
use rand::Rng;

/// shareEncryption.ts / embedShareEncryption.ts work factor.
pub const SHARE_PBKDF2_ITERATIONS: u32 = 100_000;
/// shortUrlEncryption.ts work factor.
pub const SHORT_URL_PBKDF2_ITERATIONS: u32 = 200_000;
pub const SHARE_ID_SALT: &[u8] = b"openmates-share-v1";
const BASE62: &[u8; 62] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
pub const SHORT_URL_TOKEN_LENGTH: usize = 8;
pub const SHORT_URL_KEY_LENGTH: usize = 22;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ShareKind {
    Chat,
    Embed,
}

impl ShareKind {
    pub fn key_field(self) -> &'static str {
        match self {
            Self::Chat => "chat_encryption_key",
            Self::Embed => "embed_encryption_key",
        }
    }
}

/// Non-success results the TS readers report distinctly from authentication
/// failure (`Err(Error::Crypto)` corresponds to TS `decryption_failed`).
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum ShareKeyRefusal {
    Expired,
    PasswordRequired,
    InvalidPassword,
}

impl ShareKeyRefusal {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Expired => "expired",
            Self::PasswordRequired => "password_required",
            Self::InvalidPassword => "invalid_password",
        }
    }
}

pub fn password_salt(id: &str) -> String {
    format!("openmates-pwd-{id}")
}

pub fn short_url_salt(token: &str) -> String {
    format!("omts-v1-{token}")
}

pub fn pbkdf2_key(secret: &[u8], salt: &[u8], iterations: u32) -> Key {
    let mut key = Zeroizing::new([0u8; 32]);
    pbkdf2::pbkdf2_hmac::<Sha256>(secret, salt, iterations, key.as_mut());
    key
}

// ── Framing: base64url(IV || ciphertext || tag) ──

/// TS `base64UrlEncode`: URL alphabet, padding stripped.
pub fn encode_iv_prefixed(iv: &[u8; 12], sealed: &[u8]) -> String {
    let mut combined = Vec::with_capacity(12 + sealed.len());
    combined.extend_from_slice(iv);
    combined.extend_from_slice(sealed);
    URL_SAFE_NO_PAD.encode(combined)
}

/// Decodes a TS `base64UrlDecode` value; the caller splits at 12.
pub fn decode_iv_prefixed(value: &str) -> Result<Zeroizing<Vec<u8>>> {
    let bytes = Zeroizing::new(master::decode_browser_base64(value)?);
    if bytes.len() < 12 + 16 {
        return Err(Error::Crypto);
    }
    Ok(bytes)
}

pub fn random_iv() -> [u8; 12] {
    let mut iv = [0u8; 12];
    OsRng.fill_bytes(&mut iv);
    iv
}

pub(crate) fn seal_iv_prefixed(plaintext: &[u8], key: &[u8; 32]) -> Result<String> {
    let iv = random_iv();
    Ok(encode_iv_prefixed(
        &iv,
        &encrypt_aead(plaintext, key, &iv, &[])?,
    ))
}

pub(crate) fn open_iv_prefixed(value: &str, key: &[u8; 32]) -> Result<Zeroizing<Vec<u8>>> {
    let bytes = decode_iv_prefixed(value)?;
    decrypt_aead(&bytes[12..], key, &bytes[..12], &[])
}

// ── Key blob (URLSearchParams) ──

/// TS `serializeKeyBlob` / `serializeEmbedKeyBlob`: WHATWG form encoding in
/// the fixed field order.
pub fn serialize_share_blob(
    kind: ShareKind,
    key_value: &str,
    generated_at: i64,
    duration_seconds: u64,
    pwd: bool,
) -> Zeroizing<String> {
    let mut out = url::form_urlencoded::Serializer::new(String::new());
    out.append_pair(kind.key_field(), key_value)
        .append_pair("generated_at", &generated_at.to_string())
        .append_pair("duration_seconds", &duration_seconds.to_string())
        .append_pair("pwd", if pwd { "1" } else { "0" });
    Zeroizing::new(out.finish())
}

pub struct ShareBlob {
    pub key: Zeroizing<String>,
    pub generated_at: f64,
    pub duration_seconds: f64,
    pub pwd: f64,
}

/// JS `parseInt(value, 10)`: leading whitespace, optional sign, digit prefix; NaN otherwise.
pub fn js_parse_int(value: &str) -> f64 {
    let trimmed = value.trim_start();
    let (sign, rest) = match trimmed.as_bytes().first() {
        Some(b'-') => (-1.0, &trimmed[1..]),
        Some(b'+') => (1.0, &trimmed[1..]),
        _ => (1.0, trimmed),
    };
    let digits: &str = &rest[..rest.bytes().take_while(u8::is_ascii_digit).count()];
    if digits.is_empty() {
        f64::NAN
    } else {
        sign * digits.parse::<f64>().unwrap_or(f64::NAN)
    }
}

/// TS `deserializeKeyBlob` over the decrypted blob plaintext (TextDecoder lossy).
pub fn parse_share_blob(kind: ShareKind, plaintext: &[u8]) -> ShareBlob {
    let serialized = Zeroizing::new(String::from_utf8_lossy(plaintext).into_owned());
    // URLSearchParams.get returns the first value; `|| "0"` maps missing/empty to "0".
    let get = |name: &str| -> Zeroizing<String> {
        Zeroizing::new(
            url::form_urlencoded::parse(serialized.as_bytes())
                .find(|(k, _)| k == name)
                .map(|(_, v)| v.into_owned())
                .unwrap_or_default(),
        )
    };
    let number = |name: &str| {
        let v = get(name);
        js_parse_int(if v.is_empty() { "0" } else { v.as_str() })
    };
    ShareBlob {
        key: get(kind.key_field()),
        generated_at: number("generated_at"),
        duration_seconds: number("duration_seconds"),
        pwd: number("pwd"),
    }
}

pub fn share_expired(blob: &ShareBlob, server_time: i64) -> bool {
    blob.duration_seconds > 0.0 && (server_time as f64) > blob.generated_at + blob.duration_seconds
}

/// What a reader does after opening the blob with the id-derived key.
pub enum ShareNext {
    /// The stored key value (chat: base64 key string; embed: base64 to decode).
    Key(Zeroizing<String>),
    /// Open this base64url value with PBKDF2(password, password_salt(id)).
    OpenWithPassword {
        value: Zeroizing<String>,
        password: Zeroizing<String>,
    },
    Refused(ShareKeyRefusal),
}

/// Reader decision order. Chat: password requirement, expiry, password.
/// Embed: expiry, password requirement, password.
pub fn share_next(
    kind: ShareKind,
    blob: ShareBlob,
    server_time: i64,
    password: Option<&str>,
) -> ShareNext {
    let password = password.filter(|value| !value.is_empty());
    let needs_password = blob.pwd == 1.0;
    if kind == ShareKind::Chat && needs_password && password.is_none() {
        return ShareNext::Refused(ShareKeyRefusal::PasswordRequired);
    }
    if share_expired(&blob, server_time) {
        return ShareNext::Refused(ShareKeyRefusal::Expired);
    }
    match (needs_password, password) {
        (true, None) => ShareNext::Refused(ShareKeyRefusal::PasswordRequired),
        (true, Some(password)) => ShareNext::OpenWithPassword {
            value: blob.key,
            password: Zeroizing::new(password.to_owned()),
        },
        (false, _) => ShareNext::Key(blob.key),
    }
}

/// Embed key blobs store `btoa` output; TS decodes with strict-alphabet `atob`.
pub fn decode_embed_share_key(encoded: &str) -> Result<Zeroizing<Vec<u8>>> {
    if encoded.contains(['-', '_']) {
        return Err(Error::Crypto);
    }
    Ok(Zeroizing::new(master::decode_browser_base64(encoded)?))
}

// ── Writers (generateShareKeyBlob, generateEmbedShareKeyBlob, encryptShareUrl) ──

/// Plaintext key value stored in the blob for a chat (`chat_encryption_key` as given)
/// or an embed (`btoa(embedKey)`).
pub fn share_key_value(kind: ShareKind, key: &[u8]) -> Zeroizing<String> {
    match kind {
        ShareKind::Chat => Zeroizing::new(String::from_utf8_lossy(key).into_owned()),
        ShareKind::Embed => Zeroizing::new(STANDARD.encode(key)),
    }
}

/// Synchronous writer. `key_value` is the blob's key string (see `share_key_value`).
pub fn generate_share_key_blob(
    kind: ShareKind,
    id: &str,
    key_value: &str,
    duration_seconds: u64,
    password: Option<&str>,
    generated_at: i64,
) -> Result<String> {
    let (stored, pwd) = match password.filter(|value| !value.is_empty()) {
        Some(password) => {
            let key = pbkdf2_key(
                password.as_bytes(),
                password_salt(id).as_bytes(),
                SHARE_PBKDF2_ITERATIONS,
            );
            (
                Zeroizing::new(seal_iv_prefixed(key_value.as_bytes(), &key)?),
                true,
            )
        }
        None => (Zeroizing::new(key_value.to_owned()), false),
    };
    let serialized = serialize_share_blob(kind, &stored, generated_at, duration_seconds, pwd);
    let id_key = pbkdf2_key(id.as_bytes(), SHARE_ID_SALT, SHARE_PBKDF2_ITERATIONS);
    seal_iv_prefixed(serialized.as_bytes(), &id_key)
}

/// `generateShortUrlParts`: unbiased base62 token (8) and short key (22).
pub fn generate_short_url_parts() -> (String, Zeroizing<String>) {
    (
        base62(SHORT_URL_TOKEN_LENGTH),
        Zeroizing::new(base62(SHORT_URL_KEY_LENGTH)),
    )
}

fn base62(length: usize) -> String {
    let limit = (256 / BASE62.len() * BASE62.len()) as u8;
    let mut rng = OsRng;
    let mut out = String::with_capacity(length);
    while out.len() < length {
        let value: u8 = rng.r#gen();
        if value < limit {
            out.push(char::from(BASE62[usize::from(value) % BASE62.len()]));
        }
    }
    out
}

pub fn short_url_key(short_key: &str, token: &str) -> Key {
    pbkdf2_key(
        short_key.as_bytes(),
        short_url_salt(token).as_bytes(),
        SHORT_URL_PBKDF2_ITERATIONS,
    )
}

pub fn encrypt_short_url(full_url: &str, token: &str, short_key: &str) -> Result<String> {
    seal_iv_prefixed(full_url.as_bytes(), &short_url_key(short_key, token))
}
