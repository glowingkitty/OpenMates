//! Native account/chat crypto, wire-compatible with the CLI and browser.
//! Keys and decrypted binary material are zeroized and never implement Debug here.
use crate::error::{Error, Result};
use aes_gcm::{
    Aes256Gcm, KeyInit, Nonce,
    aead::{Aead, Payload},
};
use argon2::{Algorithm, Argon2, Params, Version};
use base64::{
    Engine as _,
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
};
use hkdf::Hkdf;
use hmac::{Hmac, Mac};
use rand::{RngCore, rngs::OsRng};
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

pub type Key = Zeroizing<[u8; 32]>;
pub mod master;
pub(crate) mod server_fields;
pub mod web_formats;
pub mod share;
pub mod media;
pub mod chat_key_policy;
pub mod aead;
mod password_master;
pub mod signup;
pub(crate) use password_master::{LEGACY_PASSWORD_ITERATIONS, password_master_envelope, password_master_from_plaintext};
#[cfg(target_arch = "wasm32")]
pub(crate) mod browser_legacy;

pub fn decode_key(value: &str) -> Result<Key> {
    let raw = Zeroizing::new(
        STANDARD
            .decode(value)
            .or_else(|_| URL_SAFE_NO_PAD.decode(value))
            .map_err(|_| Error::Crypto)?,
    );
    let mut key = Zeroizing::new([0u8; 32]);
    if raw.len() != 32 {
        return Err(Error::Crypto);
    }
    key.copy_from_slice(&raw);
    Ok(key)
}

pub fn random_key() -> Key {
    let mut key = Zeroizing::new([0u8; 32]);
    OsRng.fill_bytes(key.as_mut());
    key
}

pub fn encode_key(key: &[u8; 32]) -> String {
    STANDARD.encode(key)
}

pub fn hash_email(email: &str) -> String {
    STANDARD.encode(Sha256::digest(email.as_bytes()))
}

pub fn hash_key(password: &str, salt: &[u8]) -> Result<String> {
    let mut hash = Sha256::new();
    hash.update(password.as_bytes());
    hash.update(salt);
    Ok(STANDARD.encode(hash.finalize()))
}

pub fn hkdf_sha256(input: &[u8], salt: &[u8], info: &[u8]) -> Result<Key> {
    let mut key = Zeroizing::new([0u8; 32]);
    Hkdf::<Sha256>::new(Some(salt), input)
        .expand(info, key.as_mut())
        .map_err(|_| Error::Crypto)?;
    Ok(key)
}

pub fn derive_password_keys_v2(password: &str, salt: &[u8]) -> Result<(Key, Key)> {
    if password.is_empty() || salt.len() < 16 {
        return Err(Error::Crypto);
    }
    let params = Params::new(65_536, 3, 1, Some(32)).map_err(|_| Error::Crypto)?;
    let mut blocks = Zeroizing::new(vec![argon2::Block::default(); params.block_count()]);
    let mut material = Zeroizing::new([0u8; 32]);
    Argon2::new(Algorithm::Argon2id, Version::V0x13, params)
        .hash_password_into_with_memory(
            password.as_bytes(),
            salt,
            material.as_mut(),
            blocks.as_mut_slice(),
        )
        .map_err(|_| Error::Crypto)?;
    Ok((
        hkdf_sha256(material.as_ref(), &[], b"openmates/password-v2/auth")?,
        hkdf_sha256(material.as_ref(), &[], b"openmates/password-v2/wrap")?,
    ))
}

pub fn password_proof_v2(auth: &[u8; 32], nonce: &str, purpose: &str) -> Result<String> {
    if purpose.is_empty()
        || !purpose
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_')
    {
        return Err(Error::Crypto);
    }
    let nonce = decode_url(nonce, 32)?;
    if nonce.len() != 32 {
        return Err(Error::Crypto);
    }
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(auth).map_err(|_| Error::Crypto)?;
    mac.update(b"openmates/password-v2/proof\0");
    mac.update(purpose.as_bytes());
    mac.update(b"\0");
    mac.update(&nonce);
    Ok(URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes()))
}

pub fn unwrap_password_master_key(
    password: &str,
    version: u8,
    ciphertext: &str,
    salt: &str,
    iv: &str,
) -> Result<Key> {
    let salt = STANDARD.decode(salt).map_err(|_| Error::Crypto)?;
    let wrapping_key = match version {
        2 => derive_password_keys_v2(password, &salt)?.1,
        0 | 1 => {
            let mut key = Zeroizing::new([0u8; 32]);
            pbkdf2::pbkdf2_hmac::<Sha256>(password.as_bytes(), &salt, LEGACY_PASSWORD_ITERATIONS, key.as_mut());
            key
        }
        _ => return Err(Error::Crypto),
    };
    unwrap_master_key_with_wrapping_key(ciphertext, iv, &wrapping_key)
}

/// Reuse an already-derived ephemeral key only after the caller validates its
/// canonical credential version/salt. This never derives or caches key material.
pub(crate) fn unwrap_master_key_with_wrapping_key(ciphertext:&str,iv:&str,wrapping_key:&[u8;32])->Result<Key>{
    let envelope = password_master_envelope(ciphertext, iv)?;
    let raw = decrypt_aead(&envelope.ciphertext, wrapping_key, &envelope.iv, &[])?;
    password_master_from_plaintext(&raw)
}

/// Wrap a master key with an already-derived password wrapping key under a
/// fresh random IV: base64 ciphertext+tag and base64 IV, the exact inverse of
/// [`unwrap_master_key_with_wrapping_key`] (TS `cryptoService.encryptKey`).
/// Used by the v1→v2 password migration; the caller zeroizes both keys.
pub(crate) fn wrap_master_key_with_wrapping_key(master: &[u8; 32], wrapping_key: &[u8; 32]) -> Result<(String, String)> {
    signup::wrap_raw_key(master, wrapping_key, &mut signup::os_fill)
}

pub fn derive_email_key(email: &str, salt_b64: &str) -> Result<String> {
    hash_key(
        email,
        &STANDARD.decode(salt_b64).map_err(|_| Error::Crypto)?,
    )
}

pub fn encrypt_combined(text: &str, key: &[u8; 32]) -> Result<String> {
    encrypt_bytes(text.as_bytes(), key)
}
pub fn decrypt_combined(ciphertext: &str, key: &[u8; 32]) -> Result<String> {
    let raw = decrypt_bytes(ciphertext, key)?;
    // Match TextDecoder's replacement behavior on invalid UTF-8; binary keys use decrypt_bytes.
    Ok(String::from_utf8_lossy(&raw).into_owned())
}

pub fn encrypt_bytes(plaintext: &[u8], key: &[u8; 32]) -> Result<String> {
    let mut nonce = [0u8; 12];
    OsRng.fill_bytes(&mut nonce);
    let mut combined = b"OM".to_vec();
    combined.extend_from_slice(&key_fingerprint(key));
    combined.extend_from_slice(&nonce);
    combined.extend(encrypt_aead(plaintext, key, &nonce, &[])?);
    Ok(STANDARD.encode(combined))
}

pub fn key_fingerprint(key: &[u8; 32]) -> [u8; 4] {
    key.iter()
        .fold(0x811c9dc5u32, |h, byte| {
            (h ^ u32::from(*byte)).wrapping_mul(0x01000193)
        })
        .to_be_bytes()
}

pub fn decrypt_bytes(ciphertext: &str, key: &[u8; 32]) -> Result<Zeroizing<Vec<u8>>> {
    let combined = STANDARD.decode(ciphertext).map_err(|_| Error::Crypto)?;
    if combined.len() < 12 + 16 {
        return Err(Error::Crypto);
    }
    if combined.len() >= 6 + 12 + 16
        && combined.starts_with(b"OM")
        && (combined[2..6] == key_fingerprint(key) || combined[2..6] == [1, 0, 0, 0])
    {
        // A valid framed candidate wins, including the precise historical
        // Python marker. Its plaintext must authenticate before it is returned.
        if let Ok(plaintext) = decrypt_aead(&combined[18..], key, &combined[6..18], &[]) {
            return Ok(plaintext);
        }
    }
    // A legacy random IV can begin OM and any apparent fingerprint. Try the
    // complete legacy buffer only after the framed candidate is ruled out;
    // this fallback also requires a valid AES-GCM tag, never header trust.
    decrypt_aead(&combined[12..], key, &combined[..12], &[])
}

pub fn derive_embed_key(chat_key: &[u8; 32], embed_id: &str) -> Result<Key> {
    hkdf_sha256(chat_key, b"openmates-embed-key-v1", embed_id.as_bytes())
}

/// The caller normalizes the slug with the canonical NFKD slug rules before hashing.
pub fn object_slug_lookup_hash(slug: &str, lookup_key: &[u8; 32]) -> Result<String> {
    let index_key = hkdf_sha256(lookup_key, &[], b"openmates-object-slug-index-v1")?;
    let mut mac =
        <Hmac<Sha256> as Mac>::new_from_slice(index_key.as_ref()).map_err(|_| Error::Crypto)?;
    mac.update(slug.as_bytes());
    Ok(hex(&mac.finalize().into_bytes()))
}

pub fn normalize_object_slug(value: &str) -> Result<String> {
    use unicode_normalization::UnicodeNormalization;
    let decomposed: String = value
        .nfkd()
        .filter(|c| !('\u{0300}'..='\u{036f}').contains(c))
        .collect();
    let mut slug = String::new();
    for c in decomposed.to_lowercase().trim().chars() {
        if c == '\'' {
            continue;
        }
        if c.is_ascii_alphanumeric() {
            slug.push(c);
        } else if !slug.is_empty() && !slug.ends_with('-') {
            slug.push('-');
        }
    }
    slug.truncate(slug.len().min(80)); // ASCII only, so this always falls at a character boundary.
    let slug = slug.trim_end_matches('-').to_owned();
    if slug.is_empty() {
        return Err(Error::Invalid(
            "Object slug must contain a letter or number.",
        ));
    }
    Ok(slug)
}

pub struct RecoveryKeypair {
    pub private_key: Key,
    pub public_key: String,
}
pub struct RecoveryIdentity {
    pub owner_id: String,
    pub chat_id: String,
    pub turn_id: String,
    pub job_id: String,
    pub assistant_message_id: String,
    pub key_version: u32,
}

fn canonical_uuid(value: &str) -> Result<&[u8]> {
    if value.len() != 36
        || !value.bytes().enumerate().all(|(index, c)| {
            if matches!(index, 8 | 13 | 18 | 23) {
                c == b'-'
            } else {
                c.is_ascii_digit() || (b'a'..=b'f').contains(&c)
            }
        })
    {
        return Err(Error::Crypto);
    }
    Ok(value.as_bytes())
}

fn length_prefix(output: &mut Vec<u8>, value: &[u8]) -> Result<()> {
    output.extend(
        u32::try_from(value.len())
            .map_err(|_| Error::Crypto)?
            .to_be_bytes(),
    );
    output.extend(value);
    Ok(())
}

pub fn recovery_keypair(
    chat_key: &[u8; 32],
    chat_id: &str,
    key_version: u32,
) -> Result<RecoveryKeypair> {
    if key_version == 0 {
        return Err(Error::Crypto);
    }
    let salt = Sha256::digest(b"openmates:chat-recovery:v1");
    let mut info = Vec::new();
    length_prefix(&mut info, canonical_uuid(chat_id)?)?;
    info.extend(key_version.to_be_bytes());
    let private_key = hkdf_sha256(chat_key, &salt, &info)?;
    let secret = x25519_dalek::StaticSecret::from(*private_key);
    let public = x25519_dalek::PublicKey::from(&secret);
    Ok(RecoveryKeypair {
        private_key,
        public_key: URL_SAFE_NO_PAD.encode(public.as_bytes()),
    })
}

pub fn recovery_associated_data(identity: &RecoveryIdentity) -> Result<Vec<u8>> {
    if identity.key_version == 0 {
        return Err(Error::Crypto);
    }
    let mut aad = b"OMCR1".to_vec();
    for value in [
        &identity.owner_id,
        &identity.chat_id,
        &identity.turn_id,
        &identity.job_id,
        &identity.assistant_message_id,
    ] {
        length_prefix(&mut aad, canonical_uuid(value)?)?;
    }
    aad.extend(identity.key_version.to_be_bytes());
    Ok(aad)
}

pub fn open_recovery_envelope(
    envelope: &serde_json::Value,
    private_key: &[u8; 32],
    identity: &RecoveryIdentity,
) -> Result<Zeroizing<Vec<u8>>> {
    open_recovery_with_aad(
        envelope,
        private_key,
        &recovery_associated_data(identity)?,
        1,
        16 * 1024 * 1024,
    )
}

pub fn open_recovery_with_aad(
    envelope: &serde_json::Value,
    private_key: &[u8; 32],
    aad: &[u8],
    version: u8,
    max_payload: usize,
) -> Result<Zeroizing<Vec<u8>>> {
    let object = envelope.as_object().ok_or(Error::Crypto)?;
    if object.len() != 4
        || envelope.get("v").and_then(serde_json::Value::as_u64) != Some(u64::from(version))
    {
        return Err(Error::Crypto);
    }
    let field = |name: &str| {
        envelope
            .get(name)
            .and_then(serde_json::Value::as_str)
            .ok_or(Error::Crypto)
    };
    let epk = decode_url(field("epk")?, 32)?;
    let nonce = decode_url(field("nonce")?, 12)?;
    let ciphertext = decode_url(
        field("ciphertext")?,
        max_payload.checked_add(16).ok_or(Error::Crypto)?,
    )?;
    if epk.len() != 32 || nonce.len() != 12 || ciphertext.len() < 16 {
        return Err(Error::Crypto);
    }
    let ephemeral_bytes: [u8; 32] = epk.as_slice().try_into().map_err(|_| Error::Crypto)?;
    let secret = x25519_dalek::StaticSecret::from(*private_key);
    let shared = secret.diffie_hellman(&x25519_dalek::PublicKey::from(ephemeral_bytes));
    if !shared.was_contributory() {
        return Err(Error::Crypto);
    }
    let salt = Sha256::digest(b"openmates:chat-recovery-envelope:v1");
    let info = Sha256::digest(aad);
    let key = hkdf_sha256(shared.as_bytes(), &salt, &info)?;
    decrypt_aead(&ciphertext, &key, &nonce, aad)
}

pub(crate) fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

pub(crate) fn decode_url(value: &str, max: usize) -> Result<Zeroizing<Vec<u8>>> {
    if value.is_empty() || value.len() > (max * 4).div_ceil(3) + 2 {
        return Err(Error::Crypto);
    }
    let bytes = Zeroizing::new(URL_SAFE_NO_PAD.decode(value).map_err(|_| Error::Crypto)?);
    if bytes.len() > max || URL_SAFE_NO_PAD.encode(&bytes) != value {
        return Err(Error::Crypto);
    }
    Ok(bytes)
}

pub(crate) fn encrypt_aead(data: &[u8], key: &[u8; 32], iv: &[u8], aad: &[u8]) -> Result<Vec<u8>> {
    if iv.len() != 12 {
        return Err(Error::Crypto);
    }
    Aes256Gcm::new_from_slice(key)
        .map_err(|_| Error::Crypto)?
        .encrypt(Nonce::from_slice(iv), Payload { msg: data, aad })
        .map_err(|_| Error::Crypto)
}

pub(crate) fn decrypt_aead(
    data: &[u8],
    key: &[u8; 32],
    iv: &[u8],
    aad: &[u8],
) -> Result<Zeroizing<Vec<u8>>> {
    if iv.len() != 12 {
        return Err(Error::Crypto);
    }
    let plaintext = Aes256Gcm::new_from_slice(key)
        .map_err(|_| Error::Crypto)?
        .decrypt(Nonce::from_slice(iv), Payload { msg: data, aad })
        .map_err(|_| Error::Crypto)?;
    Ok(Zeroizing::new(plaintext))
}

#[cfg(test)]
mod ephemeral_wrap_reuse_tests {
    use super::*;
    fn fixture()->serde_json::Value{serde_json::from_str(include_str!("../tests/crypto_fixtures/account.json")).unwrap()}
    #[test]
    fn existing_v2_wrap_vector_unlocks_exact_master_without_a_password_kdf(){
        // contract-test: supporting surface=cli assertions=auth.password.versioned-protection
        let f=fixture();let wrap=decode_key(f["wrap_key_v2"].as_str().unwrap()).unwrap();
        let master:Key=unwrap_master_key_with_wrapping_key(f["password_v2_wrapped_master"].as_str().unwrap(),f["iv"].as_str().unwrap(),&wrap).unwrap();
        assert_eq!(encode_key(&master),f["legacy_master"].as_str().unwrap());
        let auth=decode_key(f["auth_key_v2"].as_str().unwrap()).unwrap();
        assert!(unwrap_master_key_with_wrapping_key(f["password_v2_wrapped_master"].as_str().unwrap(),f["iv"].as_str().unwrap(),&auth).is_err());
    }
    #[test]
    fn reused_wrap_refuses_tamper_invalid_iv_and_non_master_plaintext_lengths(){
        let f=fixture();let wrap=decode_key(f["wrap_key_v2"].as_str().unwrap()).unwrap();let iv=[7u8;12];
        for length in [0,31,33]{let raw=Zeroizing::new(vec![9u8;length]);let wrapped=STANDARD.encode(encrypt_aead(&raw,&wrap,&iv,&[]).unwrap());assert!(unwrap_master_key_with_wrapping_key(&wrapped,&STANDARD.encode(iv),&wrap).is_err());}
        assert!(unwrap_master_key_with_wrapping_key("invalid-base64",f["iv"].as_str().unwrap(),&wrap).is_err());
        assert!(unwrap_master_key_with_wrapping_key(f["password_v2_wrapped_master"].as_str().unwrap(),&STANDARD.encode([1u8;11]),&wrap).is_err());
    }
}

#[cfg(test)]
#[path = "crypto/legacy_password_tests.rs"]
mod legacy_password_tests;
