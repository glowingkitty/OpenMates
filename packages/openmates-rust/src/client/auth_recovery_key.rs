//! Native recovery-key sign-in on `Client` (shared core, used by the Apple
//! binding and any native shell). The request body, reply classification and
//! PBKDF2 unwrap are the web's sans-IO `web_auth::RecoveryKeyLogin` (mirrors
//! `EnterRecoveryKey.svelte`); this module only performs its IO and installs
//! the session like the password login. Native only: the web keeps driving the
//! sans-IO step from its shell. Spec: `specifications/features/auth`.
use super::*;
use crate::web_auth::{HttpReply, PasswordOutcome, RecoveryKeyLogin, RecoveryKeyLoginInput};

impl Client {
    /// Sign in with email and recovery key. The server bypasses the second
    /// factor for this method; the master key is unwrapped from the
    /// recovery-key wrapper the reply returns. The previous credentials are
    /// restored after any failure (as the password login). `recovery_key`
    /// is copied into a zeroizing buffer and never logged.
    ///
    /// # Errors
    /// `Authentication` for a malformed email or a refused key (the server
    /// answers the same for an unknown account); `Invalid` for an oversized
    /// key; `Crypto` when the returned wrapper does not open with the key
    /// (the new server session is then logged out); `Protocol` for a reply
    /// without the wrapper, the refresh cookie or the matching email salt;
    /// transport errors (`Offline`, …) unchanged.
    pub async fn login_recovery_key(
        &mut self,
        email: &str,
        recovery_key: &str,
        options: PasswordLoginOptions,
    ) -> Result<()> {
        let backup = self.begin_signin();
        let result = self.recovery_key_inner(email, recovery_key, options).await;
        self.finish_signin(backup, result.is_ok())?;
        result
    }

    async fn recovery_key_inner(
        &mut self,
        email: &str,
        recovery_key: &str,
        options: PasswordLoginOptions,
    ) -> Result<()> {
        if recovery_key.is_empty() {
            return Err(Error::Authentication);
        }
        let lookup = self.login_lookup(email).await?;
        let session_id = uuid::Uuid::new_v4().to_string();
        let (login, request) = RecoveryKeyLogin::start(RecoveryKeyLoginInput {
            email: lookup.email.clone(),
            recovery_key: zeroize::Zeroizing::new(recovery_key.to_owned()),
            session_id: session_id.clone(),
            user_email_salt: lookup.user_email_salt.clone(),
            email_encryption_key: Some(lookup.email_key.clone()),
            stay_logged_in: options.stay_logged_in,
        })?;
        // The sans-IO body holds the lookup hash, never the key itself.
        let body: Value = serde_json::from_str(request.body.as_deref().ok_or(Error::Protocol)?)
            .map_err(|_| Error::Protocol)?;
        // The native transport maps every non-2xx reply to a typed error, so
        // a reply that reaches the classification is a 2xx one.
        let reply = self.request(Method::POST, request.path, Some(body)).await?;
        let outcome = login
            .finish(HttpReply {
                status: 200,
                body: Some(reply),
            })
            .await?;
        let (data, master) = match outcome {
            PasswordOutcome::Response { .. } => return Err(Error::Authentication),
            PasswordOutcome::UnlockFailed { code, .. } => {
                self.revoke_unlocked_login().await;
                return Err(if code == "unwrap_failed" {
                    Error::Crypto
                } else {
                    Error::Protocol
                });
            }
            PasswordOutcome::Unlocked { data, master, .. } => (data, master),
        };
        let user = data.get("user").ok_or(Error::Protocol)?;
        if let Err(error) = self.check_login_owner(user, &lookup.user_email_salt) {
            self.revoke_unlocked_login().await;
            return Err(error);
        }
        self.admit_login(&data, lookup, session_id, master)
    }
}
