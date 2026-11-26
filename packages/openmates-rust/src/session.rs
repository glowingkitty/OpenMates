//! Explicit caller-owned credentials. This module performs no I/O.
use crate::crypto::Key;
use base64::{Engine, engine::general_purpose::STANDARD};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use zeroize::{Zeroize, Zeroizing};
/// Unix timestamps are milliseconds, matching the server and existing CLI.
/// Deliberately has no Debug implementation: cookies and keys are credentials.
#[derive(Clone, Serialize, Deserialize)]
pub struct Session {
    pub api_url: String,
    pub session_id: String,
    pub cookies: BTreeMap<String, String>,
    pub ws_token: Option<String>,
    #[serde(with = "key_serde")]
    pub master_key: Key,
    pub hashed_email: String,
    pub user_email_salt: String,
    pub email_encryption_key: Option<String>,
    pub created_at: u64,
    pub paired_session_expires_at: Option<u64>,
    pub active_team_id: Option<String>,
}
impl Session {
    /// Whether the active native client and protected storage still describe
    /// the same credential payload. A mismatch requires a fresh client bind.
    pub fn matches_stored_session(&self, stored: &Self) -> bool {
        self.api_url == stored.api_url
            && self.session_id == stored.session_id
            && self.hashed_email == stored.hashed_email
            && self.active_team_id == stored.active_team_id
            && self.created_at == stored.created_at
            && self.paired_session_expires_at == stored.paired_session_expires_at
            && *self.master_key == *stored.master_key
            && self.user_email_salt == stored.user_email_salt
            && self.email_encryption_key == stored.email_encryption_key
            && self.cookies == stored.cookies
            && self.ws_token == stored.ws_token
    }

    pub fn is_expired(&self) -> bool {
        self.paired_session_expires_at
            .is_some_and(|deadline| deadline <= crate::client::now_ms())
    }
}
impl Drop for Session {
    fn drop(&mut self) {
        self.api_url.zeroize();
        self.session_id.zeroize();
        self.hashed_email.zeroize();
        self.active_team_id.zeroize();
        for value in self.cookies.values_mut() {
            value.zeroize();
        }
        self.ws_token.zeroize();
        self.email_encryption_key.zeroize();
        self.user_email_salt.zeroize();
    }
}
mod key_serde {
    use super::*;
    pub fn serialize<S: serde::Serializer>(
        key: &Key,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        let encoded = Zeroizing::new(STANDARD.encode(key.as_ref()));
        serializer.serialize_str(&encoded)
    }
    pub fn deserialize<'de, D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Key, D::Error> {
        let encoded = Zeroizing::new(String::deserialize(deserializer)?);
        let decoded = Zeroizing::new(
            STANDARD
                .decode(encoded.as_bytes())
                .map_err(serde::de::Error::custom)?,
        );
        if decoded.len() != 32 {
            return Err(serde::de::Error::custom("Invalid key length"));
        }
        let mut key = Zeroizing::new([0; 32]);
        key.copy_from_slice(&decoded);
        Ok(key)
    }
}
