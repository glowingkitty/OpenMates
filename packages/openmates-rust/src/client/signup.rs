//! Password-account signup and first security setup, mirroring the npm CLI
//! client (requestSignupEmailCode, verifySignupEmailCode, setupPasswordAccount,
//! the 2FA setup calls and createAndConfirmRecoveryKey). Key material is made
//! locally by `crypto::signup`; only hashes and wrapped/encrypted values leave.
//! Callers own prompts, confirmations and credential persistence.
use super::*;
use crate::crypto::signup::{
    RecoveryKeyMaterial, SignupAccount, SignupError, recovery_key_material, signup_material,
};
use zeroize::Zeroizing;

type SignupResult<T> = std::result::Result<T, SignupError>;

fn rejected(value: &Value, fallback: &str) -> SignupError {
    SignupError::Rejected(
        value
            .get("message")
            .and_then(Value::as_str)
            .filter(|message| !message.is_empty())
            .unwrap_or(fallback)
            .to_owned(),
    )
}

impl Client {
    /// One legacy signup/security call. `strict` requires `success: true`;
    /// otherwise only an explicit `success: false` is a rejection.
    async fn signup_call(
        &mut self,
        method: Method,
        path: &str,
        body: Option<Value>,
        strict: bool,
        fallback: &str,
    ) -> SignupResult<Value> {
        let value = self.request(method, path, body).await?;
        let success = value.get("success");
        if success == Some(&Value::Bool(false)) || strict && success != Some(&Value::Bool(true)) {
            return Err(rejected(&value, fallback));
        }
        Ok(value)
    }

    fn signup_without_session(&self) -> SignupResult<()> {
        if self.session.is_some() {
            return Err(SignupError::Core(Error::Invalid(
                "Log out of this profile before creating another account.",
            )));
        }
        Ok(())
    }

    pub async fn request_signup_email_code(
        &mut self,
        email: &str,
        invite_code: &str,
        language: &str,
    ) -> SignupResult<Value> {
        self.signup_without_session()?;
        let email = email.trim().to_lowercase();
        let body = json!({"email":email,"hashed_email":crypto::hash_email(&email),
            "invite_code":invite_code,"language":language,"darkmode":false});
        self.signup_call(
            Method::POST,
            "/v1/auth/request_confirm_email_code",
            Some(body),
            false,
            "Email code request failed.",
        )
        .await
    }

    /// Returns the server response, including `signup_transaction_token`.
    pub async fn verify_signup_email_code(
        &mut self,
        email: &str,
        username: &str,
        invite_code: &str,
        code: &str,
        language: &str,
    ) -> SignupResult<Value> {
        self.signup_without_session()?;
        let body = json!({"code":code,"email":email.trim().to_lowercase(),"username":username,
            "invite_code":invite_code,"language":language,"darkmode":false});
        self.signup_call(
            Method::POST,
            "/v1/auth/check_confirm_email_code",
            Some(body),
            false,
            "Email code verification failed.",
        )
        .await
    }

    /// Create the password account and install its new session in this Client.
    /// Returns `{"message", "user"}` from the server.
    pub async fn setup_password_account(
        &mut self,
        account: SignupAccount<'_>,
        transaction_token: Option<&str>,
    ) -> SignupResult<Value> {
        self.signup_without_session()?;
        let material = signup_material(account.email, account.password)?;
        let body = json!({
            "hashed_email":material.hashed_email,
            "encrypted_email":material.encrypted_email,
            "user_email_salt":material.user_email_salt,
            "username":account.username,
            "invite_code":account.invite_code,
            "encrypted_master_key":material.encrypted_master_key,
            "key_iv":material.key_iv,
            "salt":material.salt,
            "credential_version":material.credential_version,
            "password_auth_key":material.password_auth_key.as_str(),
            "signup_transaction_token":transaction_token,
            "language":account.language,
            "darkmode":false,
        });
        let response = self
            .signup_call(
                Method::POST,
                "/v1/auth/setup_password",
                Some(body),
                true,
                "Password signup failed.",
            )
            .await?;
        let user = response.get("user").cloned().unwrap_or(Value::Null);
        let session = Session {
            api_url: self.base.to_string().trim_end_matches('/').to_owned(),
            session_id: uuid::Uuid::new_v4().to_string(),
            cookies: self.cookies.clone(),
            ws_token: None,
            master_key: material.master_key,
            hashed_email: material.hashed_email,
            user_email_salt: material.user_email_salt,
            email_encryption_key: Some(material.email_encryption_key.to_string()),
            created_at: now_ms(),
            paired_session_expires_at: None,
            active_team_id: None,
        };
        self.install_new_session(
            session,
            if user.is_object() {
                user.clone()
            } else {
                json!({})
            },
        );
        Ok(
            json!({"message":response.get("message").cloned().unwrap_or(json!("Account created.")),"user":user}),
        )
    }

    fn signup_email_key(&self) -> SignupResult<String> {
        self.require_session()?
            .email_encryption_key
            .clone()
            .ok_or(SignupError::Core(Error::Unavailable {
                code: "email_encryption_key_missing",
                reason: "Email encryption key is missing. Run `openmates login` again to refresh your local encryption keys.",
            }))
    }

    /// `{"secret","otpauth_url",...}` for the new account's authenticator.
    pub async fn start_totp_setup(&mut self) -> SignupResult<Value> {
        let key = Zeroizing::new(self.signup_email_key()?);
        self.signup_call(
            Method::POST,
            "/v1/auth/2fa/setup/initiate",
            Some(json!({"email_encryption_key":key.as_str()})),
            true,
            "2FA setup failed.",
        )
        .await
    }

    pub async fn verify_totp_setup(&mut self, code: &str) -> SignupResult<Value> {
        self.require_session()?;
        self.signup_call(
            Method::POST,
            "/v1/auth/2fa/setup/verify-signup",
            Some(json!({"code":code})),
            false,
            "2FA verification failed.",
        )
        .await
    }

    pub async fn set_totp_provider(&mut self, provider: &str) -> SignupResult<Value> {
        self.require_session()?;
        self.signup_call(
            Method::POST,
            "/v1/auth/2fa/setup/provider",
            Some(json!({"provider":provider})),
            false,
            "2FA provider save failed.",
        )
        .await
    }

    /// The one-time backup codes; never logged or cached by the SDK.
    pub async fn request_backup_codes(&mut self) -> SignupResult<Vec<Zeroizing<String>>> {
        self.require_session()?;
        let value = self
            .signup_call(
                Method::GET,
                "/v1/auth/2fa/setup/request-backup-codes",
                None,
                true,
                "Backup-code request failed.",
            )
            .await?;
        value["backup_codes"]
            .as_array()
            .ok_or(SignupError::Core(Error::Protocol))?
            .iter()
            .map(|code| code.as_str().map(|code| Zeroizing::new(code.to_owned())))
            .collect::<Option<Vec<_>>>()
            .ok_or(SignupError::Core(Error::Protocol))
    }

    pub async fn confirm_backup_codes_stored(&mut self) -> SignupResult<Value> {
        self.require_session()?;
        self.signup_call(
            Method::POST,
            "/v1/auth/2fa/setup/confirm-codes-stored",
            Some(json!({"confirmed":true})),
            false,
            "Backup-code confirmation failed.",
        )
        .await
    }

    /// Generate a recovery key locally, store only its wrapped master key.
    pub async fn create_and_confirm_recovery_key(&mut self) -> SignupResult<RecoveryKeyMaterial> {
        let session = self.require_session()?;
        let material = recovery_key_material(&session.master_key, &session.user_email_salt)?;
        self.signup_call(
            Method::POST,
            "/v1/auth/recovery-key/confirm-stored",
            Some(json!({"confirmed":true,"lookup_hash":material.lookup_hash,
                "wrapped_master_key":material.wrapped_master_key,"key_iv":material.key_iv,"salt":material.salt})),
            false,
            "Recovery-key confirmation failed.",
        )
        .await?;
        Ok(material)
    }
}

#[cfg(test)]
#[path = "signup_tests.rs"]
mod tests;
