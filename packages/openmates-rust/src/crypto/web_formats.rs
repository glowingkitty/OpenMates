//! Readers for existing web-client encryption formats that had no Rust reader:
//! passkey (PRF) master wrapping, hidden-chat key wrapping, chat/embed share key
//! blobs, short share URLs and stored media payloads. Each reader mirrors the
//! deployed TypeScript reader byte-for-byte (see tests/crypto_fixtures/
//! ts_web_formats.json, produced by the actual TS modules). Every path requires
//! an authenticated AES-GCM tag; no reader falls back to another layout after a
//! selected candidate fails.
use super::*;

pub use super::media::MEDIA_ENCRYPTION_V2;
use super::share::{self, SHARE_PBKDF2_ITERATIONS, pbkdf2_key};

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
pub fn unwrap_passkey_master_key(
    prf_output: &[u8],
    email_salt: &[u8],
    ciphertext: &str,
    iv: &str,
) -> Result<Key> {
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
    Ok(pbkdf2_key(
        encoded.as_bytes(),
        salt,
        LEGACY_PASSWORD_ITERATIONS,
    ))
}

/// Opens a hidden chat's `encrypted_chat_key` (IV-prefixed, no OM header).
pub fn unwrap_hidden_chat_key(encrypted_chat_key: &str, secret: &[u8; 32]) -> Result<Key> {
    let raw = open_iv_prefixed(&master::decode_browser_base64(encrypted_chat_key)?, secret)?;
    exact_key(&raw)
}

// ── Share links (shareEncryption.ts / embedShareEncryption.ts) ──
// Format logic lives in `crypto::share`; these are the synchronous readers.

pub use super::share::ShareKeyRefusal;
use super::share::{ShareKind, ShareNext};

fn read_share(
    kind: ShareKind,
    id: &str,
    encrypted_blob: &str,
    server_time: i64,
    password: Option<&str>,
) -> Result<std::result::Result<Zeroizing<String>, ShareKeyRefusal>> {
    let id_key = pbkdf2_key(id.as_bytes(), share::SHARE_ID_SALT, SHARE_PBKDF2_ITERATIONS);
    let plain = share::open_iv_prefixed(encrypted_blob, &id_key)?;
    Ok(
        match share::share_next(
            kind,
            share::parse_share_blob(kind, &plain),
            server_time,
            password,
        ) {
            ShareNext::Key(value) => Ok(value),
            ShareNext::Refused(refusal) => Err(refusal),
            ShareNext::OpenWithPassword { value, password } => {
                let key = pbkdf2_key(
                    password.as_bytes(),
                    share::password_salt(id).as_bytes(),
                    SHARE_PBKDF2_ITERATIONS,
                );
                share::open_iv_prefixed(&value, &key)
                    .map(|plain| Zeroizing::new(String::from_utf8_lossy(&plain).into_owned()))
                    .map_err(|_| ShareKeyRefusal::InvalidPassword)
            }
        },
    )
}

/// `decryptShareKeyBlob`: returns the shared chat key string (base64) exactly as
/// stored. Order matches TS: password requirement, then expiry, then password.
pub fn decrypt_chat_share_key_blob(
    chat_id: &str,
    encrypted_blob: &str,
    server_time: i64,
    password: Option<&str>,
) -> Result<std::result::Result<Zeroizing<String>, ShareKeyRefusal>> {
    read_share(
        ShareKind::Chat,
        chat_id,
        encrypted_blob,
        server_time,
        password,
    )
}

/// `decryptEmbedShareKeyBlob`: expiry precedes the password requirement and the
/// embed key is decoded with strict-alphabet `atob` (any length, as in TS).
pub fn decrypt_embed_share_key_blob(
    embed_id: &str,
    encrypted_blob: &str,
    server_time: i64,
    password: Option<&str>,
) -> Result<std::result::Result<Zeroizing<Vec<u8>>, ShareKeyRefusal>> {
    match read_share(
        ShareKind::Embed,
        embed_id,
        encrypted_blob,
        server_time,
        password,
    )? {
        Ok(encoded) => Ok(Ok(share::decode_embed_share_key(&encoded)?)),
        Err(refusal) => Ok(Err(refusal)),
    }
}

/// `decryptShareUrl`: PBKDF2(shortKey, "omts-v1-" + token, 200k), base64url(IV||ct).
pub fn decrypt_short_url(encrypted_url: &str, token: &str, short_key: &str) -> Result<String> {
    let plain = share::open_iv_prefixed(encrypted_url, &share::short_url_key(short_key, token))?;
    Ok(String::from_utf8_lossy(&plain).into_owned())
}

// ── Media payloads (encryption/mediaEncryption.ts decryptMediaPayload) ──
// Layout policy lives in `crypto::media`.

pub use super::media::MediaEncryption;

pub fn decrypt_media_payload(
    data: &[u8],
    aes_key_b64: &str,
    meta: &MediaEncryption<'_>,
) -> Result<Zeroizing<Vec<u8>>> {
    super::media::decrypt_media(data, aes_key_b64, meta).map_err(|_| Error::Crypto)
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "web_formats_tests.rs"]
mod tests;
