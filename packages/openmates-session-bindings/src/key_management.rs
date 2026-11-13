//! Stateless key-management primitives for foreign SDKs (npm WASM entry first).
//! Bindings only marshal: every operation calls `openmates_sdk::crypto` (encode/
//! decode key, FNV-1a32 OM fingerprint, email/key hashes, OM-framed AES-GCM
//! combined ciphertext). Mirrors Python `openmates.key_management`; vectors live in
//! `tests/sdk-conformance/fixtures/sdk-key-management.json`.
use crate::BindingError;
use openmates_sdk::{Error, crypto};
use serde::Deserialize;
use serde_json::{Value, json};
use zeroize::Zeroizing;

/// Raw keys and salts cross the JSON boundary as byte arrays so the foreign
/// adapter never re-implements base64 or key validation.
#[derive(Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
enum Input {
    RandomKey,
    EncodeKey { key: Vec<u8> },
    DecodeKey { value: String },
    KeyFingerprint { key: Vec<u8> },
    HashEmail { email: String },
    HashKey { password: String, salt: Vec<u8> },
    EncryptCombined { text: String, key: Vec<u8> },
    DecryptCombined { ciphertext: String, key: Vec<u8> },
}

fn key(bytes: Vec<u8>) -> Result<Zeroizing<[u8; 32]>, BindingError> {
    let bytes = Zeroizing::new(bytes);
    let mut key = Zeroizing::new([0u8; 32]);
    if bytes.len() != key.len() {
        return Err(Error::Invalid("A 32-byte key is required.").into());
    }
    key.copy_from_slice(&bytes);
    Ok(key)
}

/// Run one key-management operation from its JSON envelope.
///
/// # Errors
/// `invalid_argument` for malformed input or keys that are not 32 bytes, `crypto`
/// when a key string or ciphertext does not decode/authenticate. Errors never
/// echo key material, plaintext or ciphertext.
pub fn key_management_json(encoded: String) -> Result<String, BindingError> {
    let encoded = Zeroizing::new(encoded);
    if encoded.len() > 16 * 1024 * 1024 {
        return Err(Error::Invalid("Key-management input exceeds the supported limit.").into());
    }
    let input: Input = serde_json::from_str(&encoded)
        .map_err(|_| Error::Invalid("Invalid typed key-management input."))?;
    let output: Value = match input {
        Input::RandomKey => json!({"key": crypto::random_key().to_vec()}),
        Input::EncodeKey { key: raw } => json!({"value": crypto::encode_key(&*key(raw)?)}),
        Input::DecodeKey { value } => {
            let value = Zeroizing::new(value);
            json!({"key": crypto::decode_key(&value)?.to_vec()})
        }
        Input::KeyFingerprint { key: raw } => {
            json!({"fingerprint": crypto::key_fingerprint(&*key(raw)?).to_vec()})
        }
        Input::HashEmail { email } => json!({"hash": crypto::hash_email(&email)}),
        Input::HashKey { password, salt } => {
            let password = Zeroizing::new(password);
            json!({"hash": crypto::hash_key(&password, &salt)?})
        }
        Input::EncryptCombined { text, key: raw } => {
            let text = Zeroizing::new(text);
            json!({"ciphertext": crypto::encrypt_combined(&text, &*key(raw)?)?})
        }
        Input::DecryptCombined {
            ciphertext,
            key: raw,
        } => {
            json!({"text": crypto::decrypt_combined(&ciphertext, &*key(raw)?)?})
        }
    };
    serde_json::to_string(&output).map_err(|_| Error::Protocol.into())
}

#[cfg(test)]
#[path = "key_management_tests.rs"]
mod tests;
