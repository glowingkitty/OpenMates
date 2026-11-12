//! Password v1→v2 key migration owned by the shared core, run by a native
//! shell right after a legacy (v1) password login while it still holds the
//! password. Mirrors the web's `migrateUnlockedLegacyPassword`
//! (`frontend/packages/ui/src/services/passwordV2.ts`) and the server routes in
//! `backend/core/api/app/routes/auth_routes/auth_password_v2.py`:
//! capabilities → staged-challenge probe (resume) or migrate → verify-staged →
//! local round-trip check → confirm-migration. Native only (web keeps its TS
//! path for now).
//!
//! Resumability: the server is the only state. A staged migration keeps the
//! v1 credential valid, so the next v1 login probes `staged-challenge` and
//! resumes; nothing is persisted locally (never the password or derived keys).
use super::*;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;

/// Result of one migration attempt. Every variant except `Completed` leaves
/// the v1 credential working; only `PendingConfirmation` has staged state on
/// the server, which the next legacy login resumes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PasswordMigrationOutcome {
    /// The server retired the v1 credential: the v2 credential is live.
    Completed,
    /// The server installed v2 but keeps the legacy credential.
    LegacyRetained,
    /// v2 is staged but not confirmed yet; the next legacy login resumes it.
    PendingConfirmation,
    /// The account's legacy credentials are untyped (may include recovery
    /// keys); the server defers migration until they are bound. Nothing staged.
    DeferredLegacyCredentials,
    /// The server requires a recent strong verification (for example a
    /// second factor) before it installs or confirms v2.
    DeferredRecentVerification,
    /// The server requires a fresh legacy password login for this session.
    DeferredFreshLogin,
    /// The server does not offer the staged migration protocol (a lagging
    /// self-hosted server); nothing was attempted.
    Unsupported,
}

/// The staged protocol version this client implements.
const STAGED_PROTOCOL: u64 = 2;

impl Client {
    /// Migrate the signed-in account's legacy (v1) password credential to v2,
    /// using `password` from the login that just unlocked it. Runs on a
    /// scratch client sharing this session's cookies, so a server denial on a
    /// migration route never signs this client out; the session itself is
    /// unchanged (the master key stays the same).
    ///
    /// # Errors
    /// `Authentication` without a session; `Crypto` when a wrapper does not
    /// round-trip to this session's master key (nothing is confirmed then);
    /// `Protocol` for malformed replies; transport errors (`Offline`, …).
    /// Callers treat any error as "not migrated": the login stands.
    pub async fn migrate_legacy_password(
        &self,
        password: &str,
    ) -> Result<PasswordMigrationOutcome> {
        let session = self.session.as_ref().ok_or(Error::Authentication)?.clone();
        if password.is_empty() {
            return Err(Error::Authentication);
        }
        let mut scratch =
            Client::with_options(self.base.as_str(), Some(session), self.options.clone())?;
        scratch.run_password_migration(password).await
    }

    async fn run_password_migration(&mut self, password: &str) -> Result<PasswordMigrationOutcome> {
        let capabilities = self
            .request(
                Method::GET,
                "/v1/auth/password-v2/migration-capabilities",
                None,
            )
            .await?;
        // An older server's migrate route retires v1 immediately; only the
        // staged, confirm-required protocol is safe to drive.
        if capabilities.get("staged_protocol").and_then(Value::as_u64) != Some(STAGED_PROTOCOL)
            || capabilities.get("confirm_required") != Some(&json!(true))
        {
            return Ok(PasswordMigrationOutcome::Unsupported);
        }
        let session = self.session.as_ref().ok_or(Error::Authentication)?;
        let salt_text = session.user_email_salt.clone();
        let salt = STANDARD.decode(&salt_text).map_err(|_| Error::Protocol)?;
        let (auth, wrap) = crypto::derive_password_keys_v2(password, &salt)?;
        // A prior attempt may have staged v2 and stopped before confirmation:
        // a successful probe is the only resume signal (as the web).
        let challenge = match self
            .migration_post("/v1/auth/password-v2/staged-challenge", json!({}))
            .await
        {
            Ok(challenge) => challenge,
            Err((Some(409), _)) => {
                if let Some(outcome) = self
                    .stage_password_v2(password, &salt, &salt_text, &auth, &wrap)
                    .await?
                {
                    return Ok(outcome);
                }
                match self
                    .migration_post("/v1/auth/password-v2/staged-challenge", json!({}))
                    .await
                {
                    Ok(challenge) => challenge,
                    Err(_) => return Ok(PasswordMigrationOutcome::PendingConfirmation),
                }
            }
            Err((status, error)) => return deferred(status).ok_or(error),
        };
        self.confirm_staged_password(&challenge, &salt_text, &auth, &wrap)
            .await
    }

    /// `POST /migrate`: wrap this session's master key with the v2 wrapping
    /// key, prove the wrapper opens locally, then send it. `None` means staged
    /// (`pending_confirmation`): continue with the confirmation.
    async fn stage_password_v2(
        &mut self,
        password: &str,
        salt: &[u8],
        salt_text: &str,
        auth: &Key,
        wrap: &Key,
    ) -> Result<Option<PasswordMigrationOutcome>> {
        let master = &self
            .session
            .as_ref()
            .ok_or(Error::Authentication)?
            .master_key;
        let (wrapped, iv) = crypto::wrap_master_key_with_wrapping_key(master, wrap)?;
        let checked = crypto::unwrap_master_key_with_wrapping_key(&wrapped, &iv, wrap)?;
        if !same_key(&checked, master) {
            return Err(Error::Crypto);
        }
        let body = json!({
            "old_lookup_hash": crypto::hash_key(password, salt)?,
            "password_auth_key": URL_SAFE_NO_PAD.encode(auth.as_ref()),
            "encrypted_master_key": wrapped,
            "salt": salt_text,
            "key_iv": iv,
        });
        let reply = match self
            .migration_post("/v1/auth/password-v2/migrate", body)
            .await
        {
            Ok(reply) => reply,
            // The only 409 of this route: untyped legacy hashes, nothing written.
            Err((Some(409), _)) => {
                return Ok(Some(PasswordMigrationOutcome::DeferredLegacyCredentials));
            }
            Err((status, error)) => return deferred(status).map(Some).ok_or(error),
        };
        match reply.get("migration_status").and_then(Value::as_str) {
            Some("pending_confirmation") => Ok(None),
            Some("legacy_retained") => Ok(Some(PasswordMigrationOutcome::LegacyRetained)),
            _ => Err(Error::Protocol),
        }
    }

    /// Prove the password for the staged wrapper, check that it opens to this
    /// session's master key, then confirm the retirement of v1.
    async fn confirm_staged_password(
        &mut self,
        challenge: &Value,
        salt_text: &str,
        auth: &Key,
        wrap: &Key,
    ) -> Result<PasswordMigrationOutcome> {
        let proof = crypto::password_proof_v2(auth, required(challenge, "nonce")?, "migration")?;
        let body =
            json!({"challenge_id": required(challenge, "challenge_id")?, "password_proof": proof});
        let Ok(wrapper) = self
            .migration_post("/v1/auth/password-v2/verify-staged", body)
            .await
        else {
            return Ok(PasswordMigrationOutcome::PendingConfirmation);
        };
        if wrapper.get("credential_version").and_then(Value::as_u64) != Some(2)
            || text(&wrapper, "salt") != salt_text
        {
            return Err(Error::Protocol);
        }
        let unlocked = crypto::unwrap_master_key_with_wrapping_key(
            required(&wrapper, "encrypted_key")?,
            required(&wrapper, "key_iv")?,
            wrap,
        )?;
        let master = &self
            .session
            .as_ref()
            .ok_or(Error::Authentication)?
            .master_key;
        if !same_key(&unlocked, master) {
            // Never retire v1 for a wrapper of another key.
            return Err(Error::Crypto);
        }
        match self
            .migration_post("/v1/auth/password-v2/confirm-migration", json!({}))
            .await
        {
            Ok(reply) if text(&reply, "migration_status") == "typed_retired" => {
                Ok(PasswordMigrationOutcome::Completed)
            }
            Err((Some(428), _)) => Ok(PasswordMigrationOutcome::DeferredRecentVerification),
            _ => Ok(PasswordMigrationOutcome::PendingConfirmation),
        }
    }

    /// One migration request; a failure keeps its HTTP status so the caller
    /// can tell the server's typed refusals apart.
    async fn migration_post(
        &mut self,
        path: &str,
        body: Value,
    ) -> std::result::Result<Value, (Option<u16>, Error)> {
        let mut status = None;
        self.request_task_headers_observed(
            Method::POST,
            path,
            Some(body),
            None,
            None,
            None,
            &mut status,
        )
        .await
        .map_err(|error| (status, error))
    }
}

/// The server's typed postponements shared by the migrate and probe routes.
fn deferred(status: Option<u16>) -> Option<PasswordMigrationOutcome> {
    match status {
        Some(428) => Some(PasswordMigrationOutcome::DeferredRecentVerification),
        Some(401) => Some(PasswordMigrationOutcome::DeferredFreshLogin),
        _ => None,
    }
}

/// Equality of two keys without an early exit on the first differing byte.
fn same_key(first: &[u8; 32], second: &[u8; 32]) -> bool {
    first
        .iter()
        .zip(second.iter())
        .fold(0u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

#[cfg(test)]
#[path = "password_migration_tests.rs"]
mod tests;
