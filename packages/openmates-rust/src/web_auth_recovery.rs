//! Recovery-key login (the "Login with recovery key" form), sans-IO like the
//! password step. One `POST /v1/auth/login` with the deployed field order, then
//! the PBKDF2 unwrap of the master key with the recovery key.
use super::{HttpReply, HttpRequest, LOGIN_HEADERS, MAX_EMAIL_BYTES, PasswordOutcome, legacy_unwrap, ordered, text, truthy};
use crate::crypto;
use crate::error::{Error, Result};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use zeroize::Zeroizing;

const MAX_RECOVERY_KEY_BYTES: usize = 1024;

pub struct RecoveryKeyLoginInput {
    pub email: String,
    pub recovery_key: Zeroizing<String>,
    pub session_id: String,
    /// Base64 email salt from the email-step lookup.
    pub user_email_salt: String,
    pub email_encryption_key: Option<String>,
    pub stay_logged_in: bool,
}

pub struct RecoveryKeyLogin { input: RecoveryKeyLoginInput }

impl RecoveryKeyLogin {
    /// Validates the input and returns the login request.
    pub fn start(input: RecoveryKeyLoginInput) -> Result<(Self, HttpRequest)> {
        if input.email.is_empty() || input.email.len() > MAX_EMAIL_BYTES || input.recovery_key.is_empty()
            || input.recovery_key.len() > MAX_RECOVERY_KEY_BYTES || uuid::Uuid::parse_str(&input.session_id).is_err() {
            return Err(Error::Invalid("recovery_login_input"));
        }
        let salt = Zeroizing::new(STANDARD.decode(&input.user_email_salt).map_err(|_| Error::Invalid("user_email_salt"))?);
        let body = ordered(&[
            ("hashed_email", json!(crypto::hash_email(&input.email))),
            ("lookup_hash", json!(crypto::hash_key(&input.recovery_key, &salt)?)),
            ("email_encryption_key", input.email_encryption_key.as_ref().map_or(Value::Null, |key| json!(key))),
            ("login_method", json!("recovery_key")),
            ("session_id", json!(input.session_id)),
            ("stay_logged_in", json!(input.stay_logged_in)),
        ]);
        Ok((Self { input }, HttpRequest::post("/v1/auth/login", LOGIN_HEADERS, Some(body))))
    }

    /// Classifies the reply and unwraps the master key on success. A non-JSON
    /// body is an error, as `response.json()` was in the deployed form.
    pub async fn finish(self, reply: HttpReply) -> Result<PasswordOutcome> {
        let status = reply.status;
        let data = reply.body.ok_or(Error::Invalid("login_response"))?;
        if !reply_ok(status) || !truthy(data.get("success")) {
            return Ok(PasswordOutcome::Response { status, data });
        }
        let Some(user) = data.get("user").filter(|user| !user.is_null()) else {
            return Ok(PasswordOutcome::UnlockFailed { status, data, code: "login_failed" });
        };
        let (Some(encrypted), Some(salt)) = (text(user, "encrypted_key").filter(|v| !v.is_empty()), text(user, "salt").filter(|v| !v.is_empty())) else {
            return Ok(PasswordOutcome::UnlockFailed { status, data, code: "login_failed" });
        };
        let iv = text(user, "key_iv").unwrap_or("").to_owned();
        let (encrypted, salt) = (encrypted.to_owned(), salt.to_owned());
        Ok(match legacy_unwrap(&self.input.recovery_key, &encrypted, &salt, &iv).await {
            Ok(master) => PasswordOutcome::Unlocked { status, data, master, credential_version: 1 },
            Err(_) => PasswordOutcome::UnlockFailed { status, data, code: "unwrap_failed" },
        })
    }
}

fn reply_ok(status: u16) -> bool { (200..300).contains(&status) }
