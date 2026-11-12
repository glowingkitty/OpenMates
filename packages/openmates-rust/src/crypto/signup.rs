//! Password-account signup and recovery-key material, byte-compatible with the
//! npm CLI (`createSignupCryptoMaterial`, `createRecoveryKeyMaterial`,
//! `generateSecureRecoveryKey`). The master key is generated locally and only
//! leaves the process wrapped; the password itself never leaves the process.
//! Randomness is injectable so shared fixed-byte vectors prove compatibility.
use super::{
    Key, LEGACY_PASSWORD_ITERATIONS, derive_email_key, derive_password_keys_v2, encrypt_aead,
    hash_email, hash_key,
};
use crate::error::{Error, Result};
use base64::{
    Engine,
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
};
use rand::{RngCore, rngs::OsRng};
use sha2::Sha256;
use zeroize::Zeroizing;

const EMAIL_SALT_LENGTH: usize = 16;
const AES_GCM_IV_LENGTH: usize = 12;
const NACL_NONCE_LENGTH: usize = 24;

/// Everything `/v1/auth/setup_password` needs plus the local session secrets.
pub struct SignupMaterial {
    pub hashed_email: String,
    pub encrypted_email: String,
    pub encrypted_email_with_master_key: String,
    pub user_email_salt: String,
    pub email_encryption_key: Zeroizing<String>,
    pub master_key: Key,
    pub encrypted_master_key: String,
    pub key_iv: String,
    pub salt: String,
    pub credential_version: u8,
    pub password_auth_key: Zeroizing<String>,
}

/// A generated recovery key and the wrapped master key the server stores.
pub struct RecoveryKeyMaterial {
    pub recovery_key: Zeroizing<String>,
    pub lookup_hash: String,
    pub wrapped_master_key: String,
    pub key_iv: String,
    pub salt: String,
}

/// Explicit signup identity inputs. The password is used only locally.
pub struct SignupAccount<'a> {
    pub email: &'a str,
    pub username: &'a str,
    pub password: &'a str,
    pub invite_code: &'a str,
    pub language: &'a str,
}

/// A signup/2FA/recovery step failure: a typed transport error, or the
/// server's own `success: false` message, which the CLI prints verbatim.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SignupError {
    Core(Error),
    Rejected(String),
}
impl std::fmt::Display for SignupError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Core(error) => std::fmt::Display::fmt(error, f),
            Self::Rejected(message) => f.write_str(message),
        }
    }
}
impl std::error::Error for SignupError {}
impl From<Error> for SignupError {
    fn from(error: Error) -> Self {
        Self::Core(error)
    }
}

/// Web Crypto `getRandomValues` equivalent; `nacl` is TweetNaCl's PRNG.
pub(crate) struct Randomness<'a> {
    pub web: &'a mut dyn FnMut(&mut [u8]),
    pub nacl: &'a mut dyn FnMut(&mut [u8]),
}

pub(super) fn os_fill(bytes: &mut [u8]) {
    OsRng.fill_bytes(bytes);
}

/// AES-GCM raw-key wrap (`encryptRawKeyWithAesGcm`): base64 ciphertext+tag, base64 IV.
pub(super) fn wrap_raw_key(
    raw: &[u8; 32],
    wrapping: &[u8; 32],
    random: &mut dyn FnMut(&mut [u8]),
) -> Result<(String, String)> {
    let mut iv = [0u8; AES_GCM_IV_LENGTH];
    random(&mut iv);
    let wrapped = encrypt_aead(raw, wrapping, &iv, &[])?;
    Ok((STANDARD.encode(wrapped), STANDARD.encode(iv)))
}

/// npm `encryptWithAesGcmCombined`: base64(IV || ciphertext+tag).
fn encrypt_iv_combined(
    text: &str,
    key: &[u8; 32],
    random: &mut dyn FnMut(&mut [u8]),
) -> Result<String> {
    let mut iv = [0u8; AES_GCM_IV_LENGTH];
    random(&mut iv);
    let mut combined = iv.to_vec();
    combined.extend(encrypt_aead(text.as_bytes(), key, &iv, &[])?);
    Ok(STANDARD.encode(combined))
}

/// npm `encryptEmail`: NaCl secretbox, base64(nonce || tag || ciphertext).
fn encrypt_email(email: &str, key: &[u8; 32], random: &mut dyn FnMut(&mut [u8])) -> Result<String> {
    use crypto_secretbox::{KeyInit, XSalsa20Poly1305, aead::Aead};
    let mut nonce = [0u8; NACL_NONCE_LENGTH];
    random(&mut nonce);
    let sealed = XSalsa20Poly1305::new(key.into())
        .encrypt((&nonce).into(), email.as_bytes())
        .map_err(|_| Error::Crypto)?;
    let mut combined = nonce.to_vec();
    combined.extend(sealed);
    Ok(STANDARD.encode(combined))
}

pub fn signup_material(email: &str, password: &str) -> Result<SignupMaterial> {
    signup_material_with(
        email,
        password,
        Randomness {
            web: &mut os_fill,
            nacl: &mut os_fill,
        },
    )
}

pub(crate) fn signup_material_with(
    email: &str,
    password: &str,
    random: Randomness<'_>,
) -> Result<SignupMaterial> {
    let email = email.trim().to_lowercase();
    if email.is_empty() || email.len() > 512 || password.is_empty() {
        return Err(Error::Invalid("Signup requires an email and a password."));
    }
    let mut salt = [0u8; EMAIL_SALT_LENGTH];
    (random.web)(&mut salt);
    let mut master = Zeroizing::new([0u8; 32]);
    (random.web)(master.as_mut());
    let salt_b64 = STANDARD.encode(salt);
    let email_key_b64 = Zeroizing::new(derive_email_key(&email, &salt_b64)?);
    let mut email_key = Zeroizing::new([0u8; 32]);
    let decoded = Zeroizing::new(
        STANDARD
            .decode(email_key_b64.as_bytes())
            .map_err(|_| Error::Crypto)?,
    );
    if decoded.len() != 32 {
        return Err(Error::Crypto);
    }
    email_key.copy_from_slice(&decoded);
    let (auth, wrap) = derive_password_keys_v2(password, &salt)?;
    let (encrypted_master_key, key_iv) = wrap_raw_key(&master, &wrap, random.web)?;
    drop(wrap);
    let password_auth_key = Zeroizing::new(URL_SAFE_NO_PAD.encode(auth.as_ref()));
    drop(auth);
    Ok(SignupMaterial {
        hashed_email: hash_email(&email),
        encrypted_email: encrypt_email(&email, &email_key, random.nacl)?,
        encrypted_email_with_master_key: encrypt_iv_combined(&email, &master, random.web)?,
        user_email_salt: salt_b64.clone(),
        email_encryption_key: email_key_b64,
        master_key: master,
        encrypted_master_key,
        key_iv,
        salt: salt_b64,
        credential_version: 2,
        password_auth_key,
    })
}

/// npm `secureRandomIndex`: rejection-sampled single random bytes.
fn random_index(upper: usize, random: &mut dyn FnMut(&mut [u8])) -> usize {
    let max = (256 / upper) * upper;
    loop {
        let mut byte = [0u8; 1];
        random(&mut byte);
        if (byte[0] as usize) < max {
            return byte[0] as usize % upper;
        }
    }
}

/// npm `generateSecureRecoveryKey(24)`: one of each class, then a Fisher-Yates shuffle.
fn recovery_key(random: &mut dyn FnMut(&mut [u8])) -> Zeroizing<String> {
    const SETS: [&str; 4] = [
        "ABCDEFGHJKLMNPQRSTUVWXYZ",
        "abcdefghijkmnopqrstuvwxyz",
        "23456789",
        "#-=+_&%$",
    ];
    let all = SETS.concat().into_bytes();
    let mut result = Zeroizing::new(Vec::with_capacity(24));
    for set in SETS {
        result.push(set.as_bytes()[random_index(set.len(), random)]);
    }
    while result.len() < 24 {
        result.push(all[random_index(all.len(), random)]);
    }
    for index in (1..result.len()).rev() {
        let swap = random_index(index + 1, random);
        result.swap(index, swap);
    }
    Zeroizing::new(String::from_utf8(result.to_vec()).expect("ASCII recovery alphabet"))
}

pub fn recovery_key_material(
    master: &[u8; 32],
    user_email_salt: &str,
) -> Result<RecoveryKeyMaterial> {
    recovery_key_material_with(master, user_email_salt, &mut os_fill)
}

pub(crate) fn recovery_key_material_with(
    master: &[u8; 32],
    user_email_salt: &str,
    random: &mut dyn FnMut(&mut [u8]),
) -> Result<RecoveryKeyMaterial> {
    let email_salt = STANDARD
        .decode(user_email_salt)
        .map_err(|_| Error::Crypto)?;
    let recovery = recovery_key(random);
    let mut wrapping_salt = [0u8; EMAIL_SALT_LENGTH];
    random(&mut wrapping_salt);
    let mut wrapping = Zeroizing::new([0u8; 32]);
    pbkdf2::pbkdf2_hmac::<Sha256>(
        recovery.as_bytes(),
        &wrapping_salt,
        LEGACY_PASSWORD_ITERATIONS,
        wrapping.as_mut(),
    );
    let (wrapped_master_key, key_iv) = wrap_raw_key(master, &wrapping, random)?;
    Ok(RecoveryKeyMaterial {
        lookup_hash: hash_key(&recovery, &email_salt)?,
        recovery_key: recovery,
        wrapped_master_key,
        key_iv,
        salt: STANDARD.encode(wrapping_salt),
    })
}

#[cfg(test)]
#[path = "signup_tests.rs"]
mod tests;
