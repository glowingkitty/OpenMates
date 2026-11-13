//! Stored media payloads (encryption/mediaEncryption.ts), sans IO. The layout
//! planner is shared by the synchronous reader in `web_formats` and the browser
//! WebCrypto binding; unknown markers and missing nonces fail closed.
use super::*;

/// mediaEncryption.ts MEDIA_ENCRYPTION_V2 marker: nonce || ciphertext || tag.
pub const MEDIA_ENCRYPTION_V2: &str = "aes-gcm-nonce-prefixed-v1";

/// Stored-media metadata as read by the TS reader. `legacy_nonce` distinguishes
/// absent (`None`, TS null) from the explicit empty legacy marker (`Some("")`).
pub struct MediaEncryption<'a> {
    pub encryption: Option<&'a str>,
    pub aes_nonce: Option<&'a str>,
    pub legacy_nonce: Option<&'a str>,
}

/// Failure stage, matching `MediaEncryptionError.stage`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MediaStage {
    Metadata,
    ImportKey,
    Decrypt,
}

/// Where the 12-byte nonce comes from and where the sealed body starts.
pub struct MediaLayout {
    pub nonce: [u8; 12],
    pub body_offset: usize,
}

fn truthy(value: Option<&str>) -> Option<&str> {
    value.filter(|v| !v.is_empty())
}

fn prefixed(data: &[u8]) -> std::result::Result<MediaLayout, MediaStage> {
    if data.len() < 12 + 16 {
        return Err(MediaStage::Metadata);
    }
    Ok(MediaLayout {
        nonce: data[..12].try_into().map_err(|_| MediaStage::Metadata)?,
        body_offset: 12,
    })
}

pub fn media_key(aes_key_b64: &str) -> std::result::Result<Key, MediaStage> {
    let raw = Zeroizing::new(
        master::decode_browser_base64(aes_key_b64).map_err(|_| MediaStage::Metadata)?,
    );
    if raw.len() != 32 {
        return Err(MediaStage::Metadata);
    }
    let mut key = Zeroizing::new([0u8; 32]);
    key.copy_from_slice(&raw);
    Ok(key)
}

pub fn media_layout(
    data: &[u8],
    meta: &MediaEncryption<'_>,
) -> std::result::Result<MediaLayout, MediaStage> {
    match truthy(meta.encryption) {
        Some(MEDIA_ENCRYPTION_V2) => prefixed(data),
        Some(_) => Err(MediaStage::Metadata),
        None => match truthy(meta.aes_nonce).or(truthy(meta.legacy_nonce)) {
            Some(external) => {
                let nonce =
                    master::decode_browser_base64(external).map_err(|_| MediaStage::Metadata)?;
                Ok(MediaLayout {
                    nonce: nonce
                        .as_slice()
                        .try_into()
                        .map_err(|_| MediaStage::Metadata)?,
                    body_offset: 0,
                })
            }
            // Existing PDF and screenshot artifacts predate the explicit marker.
            None if meta.legacy_nonce == Some("") => prefixed(data),
            None => Err(MediaStage::Metadata),
        },
    }
}

/// Synchronous reader.
pub fn decrypt_media(
    data: &[u8],
    aes_key_b64: &str,
    meta: &MediaEncryption<'_>,
) -> std::result::Result<Zeroizing<Vec<u8>>, MediaStage> {
    let key = media_key(aes_key_b64)?;
    let layout = media_layout(data, meta)?;
    decrypt_aead(&data[layout.body_offset..], &key, &layout.nonce, &[])
        .map_err(|_| MediaStage::Decrypt)
}

/// v2 writer: random nonce || ciphertext || tag, labelled MEDIA_ENCRYPTION_V2.
pub fn encrypt_media_v2(plaintext: &[u8], key: &[u8; 32]) -> Result<Vec<u8>> {
    let nonce = super::share::random_iv();
    let sealed = encrypt_aead(plaintext, key, &nonce, &[])?;
    let mut out = Vec::with_capacity(12 + sealed.len());
    out.extend_from_slice(&nonce);
    out.extend_from_slice(&sealed);
    Ok(out)
}
