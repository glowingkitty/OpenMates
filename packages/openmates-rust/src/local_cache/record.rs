//! Encrypted cache record codec: bounded JSON encoding, AES-256-GCM sealing,
//! the `CacheRecord` wire shape, the AAD layout and cache file naming.
//!
//! Part of the shared client core (`local_cache`); moved unchanged from the
//! native TUI `storage.rs` so existing installs read their files without
//! migration. Spec: `client-core.cache` (on-disk format unchanged).
//! Invariants: file name `cache-<sha256(owner)>-<sha256(logical key)>.json`;
//! record JSON `{"version":1,"ciphertext":base64(nonce12 || ct || tag16)}`;
//! AAD is the JSON array `["openmates-rust-cache-v1", owner_hash, context,
//! expires_at, logical_key]` so a record opens only for its session context.
use super::MAX_LOCAL_RECORD_BYTES;
use crate::error::{Error, Result};
use aes_gcm::{
    Aes256Gcm, KeyInit,
    aead::{Aead, Payload},
};
use base64::{Engine, engine::general_purpose::STANDARD};
use rand::{RngCore, rngs::OsRng};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::io::Write;
use zeroize::Zeroizing;

/// Wire shape of one encrypted cache record file.
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CacheRecord {
    /// Record format version; only `1` exists.
    pub version: u8,
    /// Standard base64 of nonce (12 bytes) + ciphertext + GCM tag (16 bytes).
    pub ciphertext: String,
}

/// Lowercase hex SHA-256, the digest used for owner ids and file names.
pub fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

/// Stable id of a cache owner (hashed e-mail); the file-name prefix that
/// logout deletes by.
pub fn owner_hash(owner: &str) -> String {
    sha256_hex(owner.as_bytes())
}

/// File name of the record for `owner` and logical `cache_key`.
pub fn cache_file_name(owner: &str, cache_key: &str) -> String {
    format!(
        "cache-{}-{}.json",
        owner_hash(owner),
        sha256_hex(cache_key.as_bytes())
    )
}

/// AAD binding a record to its session: owner hash, session context hash,
/// optional pairing expiry (ms) and the logical key.
///
/// # Errors
/// JSON serialization errors (none are expected for these inputs).
pub fn cache_aad(
    owner_hash: &str,
    context: &str,
    expires_at: Option<u64>,
    cache_key: &str,
) -> Result<Vec<u8>> {
    Ok(serde_json::to_vec(&(
        "openmates-rust-cache-v1",
        owner_hash,
        context,
        expires_at,
        cache_key,
    ))?)
}

/// Exact `CacheRecord` JSON length for a plaintext of `checkpoint_json_bytes`,
/// without encrypting. Lets callers refuse optional previews that this store
/// could not read back (`MAX_LOCAL_RECORD_BYTES`).
///
/// # Errors
/// `Protocol` on arithmetic overflow.
pub fn cache_record_encoded_len(checkpoint_json_bytes: usize) -> Result<usize> {
    let combined = checkpoint_json_bytes
        .checked_add(28)
        .ok_or(Error::Protocol)?;
    let ciphertext = combined
        .checked_add(2)
        .ok_or(Error::Protocol)?
        .checked_div(3)
        .and_then(|value| value.checked_mul(4))
        .ok_or(Error::Protocol)?;
    let framing = record_framing_len()?;
    framing.checked_add(ciphertext).ok_or(Error::Protocol)
}

fn record_framing_len() -> Result<usize> {
    Ok(serde_json::to_vec(&CacheRecord {
        version: 1,
        ciphertext: String::new(),
    })?
    .len())
}

/// Serialize `value` to JSON, refusing early once the sealed record would pass
/// `MAX_LOCAL_RECORD_BYTES`. The buffer is zeroized on drop.
///
/// # Errors
/// `Invalid("The local record is too large.")` over the ceiling.
pub fn encode_bounded_json(value: &serde_json::Value) -> Result<Zeroizing<Vec<u8>>> {
    let framing = record_framing_len()?;
    // STANDARD base64 length is 4*ceil((plaintext+nonce12+tag16)/3).
    let limit = MAX_LOCAL_RECORD_BYTES
        .checked_sub(framing)
        .and_then(|n| (n / 4).checked_mul(3))
        .and_then(|n| n.checked_sub(28))
        .ok_or(Error::Protocol)?;
    struct Encoder {
        bytes: Zeroizing<Vec<u8>>,
        limit: usize,
        exceeded: bool,
    }
    impl Write for Encoder {
        fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
            if self
                .bytes
                .len()
                .checked_add(bytes.len())
                .is_none_or(|n| n > self.limit)
            {
                self.exceeded = true;
                return Err(std::io::Error::other("local cache capacity"));
            }
            self.bytes.extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut encoder = Encoder {
        bytes: Zeroizing::new(Vec::new()),
        limit,
        exceeded: false,
    };
    let serialized = serde_json::to_writer(&mut encoder, value);
    if encoder.exceeded {
        return Err(Error::Invalid("The local record is too large."));
    }
    serialized?;
    if cache_record_encoded_len(encoder.bytes.len())? > MAX_LOCAL_RECORD_BYTES {
        return Err(Error::Invalid("The local record is too large."));
    }
    Ok(encoder.bytes)
}

/// AES-256-GCM seal with a fresh random nonce; returns base64(nonce || ct).
///
/// # Errors
/// `Crypto` if the cipher rejects the key or input.
pub fn seal(key: &[u8; 32], plaintext: &[u8], aad: &[u8]) -> Result<String> {
    let cipher = Aes256Gcm::new_from_slice(key).map_err(|_| Error::Crypto)?;
    let mut nonce = [0; 12];
    OsRng.fill_bytes(&mut nonce);
    let encrypted = cipher
        .encrypt(
            (&nonce).into(),
            Payload {
                msg: plaintext,
                aad,
            },
        )
        .map_err(|_| Error::Crypto)?;
    let mut combined = nonce.to_vec();
    combined.extend_from_slice(&encrypted);
    Ok(STANDARD.encode(combined))
}

/// Inverse of [`seal`]; the plaintext is zeroized on drop.
///
/// # Errors
/// `Crypto` for bad base64, short input, wrong key or AAD, or tampering.
pub fn open(key: &[u8; 32], ciphertext: &str, aad: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
    let combined = STANDARD.decode(ciphertext).map_err(|_| Error::Crypto)?;
    if combined.len() < 28 {
        return Err(Error::Crypto);
    }
    let cipher = Aes256Gcm::new_from_slice(key).map_err(|_| Error::Crypto)?;
    cipher
        .decrypt(
            (&combined[..12]).into(),
            Payload {
                msg: &combined[12..],
                aad,
            },
        )
        .map(Zeroizing::new)
        .map_err(|_| Error::Crypto)
}

/// Seal `plaintext` and frame it as the exact bytes of a cache record file.
///
/// # Errors
/// `Crypto` from [`seal`]; `Protocol` if serialization fails.
pub fn encode_cache_record(key: &[u8; 32], plaintext: &[u8], aad: &[u8]) -> Result<Vec<u8>> {
    let record = CacheRecord {
        version: 1,
        ciphertext: seal(key, plaintext, aad)?,
    };
    Ok(serde_json::to_vec(&record)?)
}

/// Authenticate and decrypt the bytes of a cache record file; the plaintext is
/// zeroized on drop.
///
/// # Errors
/// `Protocol` for an unknown record version, `Crypto` when authentication
/// fails, JSON errors for a malformed frame.
pub fn decode_cache_record(bytes: &[u8], key: &[u8; 32], aad: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
    let record: CacheRecord = serde_json::from_slice(bytes)?;
    if record.version != 1 {
        return Err(Error::Protocol);
    }
    open(key, &record.ciphertext, aad)
}

/// [`decode_cache_record`] followed by JSON parsing of the plaintext.
///
/// # Errors
/// As [`decode_cache_record`]; JSON errors for a plaintext that is not JSON.
pub fn decode_cache_record_value(
    bytes: &[u8],
    key: &[u8; 32],
    aad: &[u8],
) -> Result<serde_json::Value> {
    Ok(serde_json::from_slice(&decode_cache_record(
        bytes, key, aad,
    )?)?)
}
