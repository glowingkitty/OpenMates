//! Exact MetadataEncryptor embed-key formats. Writers always emit
//! base64(12-byte IV || AES-256-GCM ciphertext || 128-bit tag); readers follow
//! `decryptWithEmbedKey`: forgiving browser base64, first 12 bytes are the IV,
//! never a native framed candidate. Keys are zeroized and never Debug.
use crate::crypto::{
    self, Key,
    master::{MasterCapability, decode_browser_base64},
};
use crate::error::{Error, Result};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use rand::{RngCore, rngs::OsRng};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

/// AES-GCM nonce supplier. Production uses [`OsNonces`]; vector tests replay
/// the IVs a TypeScript writer chose to prove byte-identical ciphertext.
pub trait NonceSource {
    fn next_nonce(&mut self) -> Result<[u8; 12]>;
}
/// Fresh CSPRNG nonce per seal (WebCrypto `getRandomValues` equivalent).
pub struct OsNonces;
impl NonceSource for OsNonces {
    fn next_nonce(&mut self) -> Result<[u8; 12]> {
        let mut iv = [0u8; 12];
        OsRng.fill_bytes(&mut iv);
        Ok(iv)
    }
}

/// `computeSHA256`: lowercase hex SHA-256 of the UTF-8 identifier.
pub fn hash_id(value: &str) -> String {
    crypto::hex(&Sha256::digest(value.as_bytes()))
}
/// `deriveEmbedKeyFromChatKey`: HKDF-SHA256(chat key, salt
/// "openmates-embed-key-v1", info = embed id). Existing embeds keep their keys.
pub fn derive_embed_key(chat_key: &[u8; 32], embed_id: &str) -> Result<Key> {
    crypto::derive_embed_key(chat_key, embed_id)
}
/// `generateEmbedKey`: 32 random bytes (legacy `embed_update` writer only).
pub fn generate_embed_key() -> Key {
    crypto::random_key()
}

pub(crate) fn seal(
    plaintext: &[u8],
    key: &[u8; 32],
    aad: &[u8],
    nonces: &mut impl NonceSource,
) -> Result<String> {
    let iv = nonces.next_nonce()?;
    let sealed = crypto::encrypt_aead(plaintext, key, &iv, aad)?;
    let mut combined = Vec::with_capacity(12 + sealed.len());
    combined.extend_from_slice(&iv);
    combined.extend_from_slice(&sealed);
    Ok(STANDARD.encode(combined))
}
pub(crate) fn open(ciphertext: &str, key: &[u8; 32], aad: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
    let combined = decode_browser_base64(ciphertext)?;
    if combined.len() < 12 + 16 {
        return Err(Error::Crypto);
    }
    crypto::decrypt_aead(&combined[12..], key, &combined[..12], aad)
}
/// `encryptWithEmbedKey(data, key, associatedData?)`; an empty AAD equals none.
pub fn encrypt_text(
    plaintext: &str,
    key: &[u8; 32],
    aad: Option<&str>,
    nonces: &mut impl NonceSource,
) -> Result<String> {
    seal(plaintext.as_bytes(), key, aad.unwrap_or("").as_bytes(), nonces)
}
/// `decryptWithEmbedKey`, with TextDecoder replacement semantics.
pub fn decrypt_text(ciphertext: &str, key: &[u8; 32], aad: Option<&str>) -> Result<Zeroizing<String>> {
    let plain = open(ciphertext, key, aad.unwrap_or("").as_bytes())?;
    Ok(Zeroizing::new(String::from_utf8_lossy(&plain).into_owned()))
}
pub(crate) fn key_from(bytes: &[u8]) -> Result<Key> {
    // Every deployed embed/chat key is AES-256; other lengths are refused.
    if bytes.len() != 32 {
        return Err(Error::Crypto);
    }
    let mut key = Zeroizing::new([0u8; 32]);
    key.copy_from_slice(bytes);
    Ok(key)
}
/// `wrapEmbedKeyWithChatKey` (also the child-by-parent-embed-key wrapper).
pub fn wrap_key(key: &[u8; 32], wrapping: &[u8; 32], nonces: &mut impl NonceSource) -> Result<String> {
    seal(key, wrapping, &[], nonces)
}
/// `unwrapEmbedKeyWithChatKey` / `unwrapEmbedKeyWithEmbedKey`.
pub fn unwrap_key(wrapped: &str, wrapping: &[u8; 32]) -> Result<Key> {
    key_from(&open(wrapped, wrapping, &[])?)
}
/// `wrapEmbedKeyWithMasterKey`: the master capability writes the deployed
/// IV-prefixed layout for native, raw-browser and opaque WebCrypto masters.
pub async fn wrap_key_with_master(key: &[u8; 32], master: &MasterCapability) -> Result<String> {
    master.encrypt_server_bytes(key).await
}
/// `unwrapEmbedKeyWithMasterKey` / `decryptChatKeyWithMasterKey`.
pub async fn unwrap_key_with_master(wrapped: &str, master: &MasterCapability) -> Result<Key> {
    key_from(&master.decrypt_bytes(wrapped).await?)
}
