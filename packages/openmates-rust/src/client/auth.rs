//! Account authentication on `Client` (shared core): session validation, password
//! sign-in with an OTP or backup-code second factor, recovery-key sign-in
//! (`auth_recovery_key.rs`), native passkey sign-in and passkey device
//! verification (`auth_passkey.rs`) and the v1→v2 password migration
//! (`password_migration.rs`). Spec: `specifications/features/auth`.
use super::*;
#[path = "session_validation.rs"]
mod session_validation;
pub(super) use session_validation::ActualSessionValidationTransition;
pub(in crate::client) use session_validation::BeforeSessionValidation;
#[path = "owned_session_validation.rs"]
mod owned_session_validation;
#[path = "signup.rs"]
mod signup;
#[path = "auth_recovery_key.rs"]
mod auth_recovery_key;
// Native shells only: the web keeps its own passkey flow in the shell for now.
#[cfg(not(target_arch = "wasm32"))]
#[path = "auth_passkey.rs"]
mod auth_passkey;
#[cfg(not(target_arch = "wasm32"))]
pub use auth_passkey::{
    PASSKEY_OTHER_REQUEST, PASSKEY_PRF_UNAVAILABLE, PASSKEY_WRONG_ACCOUNT, PasskeyChallenge,
    PasskeyContinuation,
};
#[path = "password_migration.rs"]
mod password_migration;
pub use password_migration::PasswordMigrationOutcome;
pub(in crate::client) use owned_session_validation::{PreparedOwnedSessionValidation, OwnedSessionValidationHeaders,
    OwnedSessionValidationBody, CompletedOwnedSessionValidation, OwnedSessionValidationReceipt,
    send_owned_session_validation_headers, send_owned_session_validation_headers_with_negative, drive_owned_session_validation_body};

use base64::{Engine, engine::general_purpose::STANDARD};
fn unwrap_login_master_key(password:&str,version:u8,account_salt:&[u8],v2_wrap:&Key,user:&Value)->Result<Key>{
    let ciphertext=required(user,"encrypted_key")?;
    let salt=required(user,"salt")?;
    let iv=required(user,"key_iv")?;
    if version==2 {
        if salt!=STANDARD.encode(account_salt){return Err(Error::Protocol);}
        crypto::unwrap_master_key_with_wrapping_key(ciphertext,iv,v2_wrap)
    }else{
        crypto::unwrap_password_master_key(password,version,ciphertext,salt,iv)
    }
}

// A fresh password transaction has no admitted master yet, so AsyncCryptoScope
// cannot be constructed. Capture the original login lifetime before credentials
// are temporarily removed; never start a replacement scope after WebCrypto IO.
struct PasswordUnwrapScope {
    operation: CancellationToken,
    authority: std::sync::Arc<project_task_watch::WatchAuthority>,
    denial_revision: u64,
    generation: u64,
    context: String,
    expires_at: Option<u64>,
}
impl PasswordUnwrapScope {
    fn context(client: &Client) -> Result<String> {
        Ok(sha256(&serde_json::to_string(&(client.base.as_str(), &client.options.app_url,
            &client.user["id"], &client.user["user_id"], &client.browser_password_transport,
            &client.browser_password_stay_logged_in, &client.browser_transport))?))
    }
    fn begin(client: &Client) -> Result<Self> {
        client.check_browser_credential_deadline()?;
        let scope = Self {
            operation: client.operation_cancel.clone(), authority: client.task_watch_authority.clone(),
            denial_revision: client.task_watch_authority.cached_denial_revision()?, generation: client.generation,
            context: Self::context(client)?,
            expires_at: client.browser_credentials.as_ref().and_then(|v| v.paired_session_expires_at)
                .or_else(|| client.session.as_ref().and_then(|v| v.paired_session_expires_at)),
        };
        scope.check(client)?; Ok(scope)
    }
    fn check(&self, client: &Client) -> Result<()> {
        if self.expires_at.is_some_and(|deadline| deadline <= now_ms()) { return Err(Error::Expired); }
        client.browser_operation_current(&self.operation)?;
        if self.authority.cancel.is_cancelled()
            || !std::sync::Arc::ptr_eq(&self.authority, &client.task_watch_authority)
            || self.denial_revision != client.task_watch_authority.cached_denial_revision()?
            || self.generation != client.generation || self.context != Self::context(client)? {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}

/// Reuse window for a native client's own successful session validation.
const VALIDATION_REUSE_WINDOW: std::time::Duration = std::time::Duration::from_secs(20);
/// (session id, credential revision, operation epoch) at a successful validation.
pub(super) struct RecentValidation {
    at: crate::platform::time::Instant,
    key: (String, u64, u64),
}

/// Server cookie lifetime preference only. This does not select local key storage.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct PasswordLoginOptions {
    pub stay_logged_in: bool,
}

/// What a successful password sign-in reports besides the installed session.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PasswordLoginReport {
    /// Password wrapper version that unlocked the master key: `1` is the
    /// legacy PBKDF2 credential (a candidate for
    /// [`Client::migrate_legacy_password`]), `2` the Argon2id credential.
    pub credential_version: u8,
    /// Backup codes left after a backup-code login (server
    /// `remaining_backup_codes`); `None` for other second factors.
    pub remaining_backup_codes: Option<u32>,
}

/// Credentials of the signed-in account set aside while a new sign-in runs,
/// so a failed sign-in restores (and a successful one zeroizes) them.
pub(super) struct SigninBackup {
    cookies: BTreeMap<String, String>,
    session: Option<Session>,
    browser_credentials: Option<credentials::BrowserCredentials>,
}

/// Results of the unauthenticated `/v1/auth/lookup` step shared by the
/// password and recovery-key sign-ins.
pub(super) struct LoginLookup {
    pub(super) email: String,
    pub(super) hashed_email: String,
    pub(super) user_email_salt: String,
    pub(super) salt: Vec<u8>,
    pub(super) email_key: String,
}

impl Client {
    /// Ordinary and detached validation share the exact fixed auth algorithm.
    /// Always contacts the server (sockets, recovery and browser lanes).
    pub async fn validate_session(&mut self) -> Result<()> {
        self.validate_session_with_server().await
    }
    /// For HTTP command handlers only (app skills, workspace reads): a native
    /// client reuses its own successful validation for a few seconds while
    /// the session, credential revision and operation epoch are unchanged, so
    /// one command does not re-validate before every request. Sockets and
    /// recovery admission keep `validate_session`; the server still enforces
    /// owner, Team and expiry on every authenticated request.
    pub(crate) async fn validate_session_for_request(&mut self) -> Result<()> {
        if self.reusable_validation() {
            return Ok(());
        }
        self.validate_session_with_server().await
    }
    pub(super) async fn validate_session_with_server(&mut self) -> Result<()> {
        self.recent_validation = None;
        let prepared=self.prepare_session_validation(None)?;
        let headers=send_owned_session_validation_headers(prepared).await;
        let body=self.apply_owned_session_validation_headers(headers)?;
        let completed=drive_owned_session_validation_body(body).await;
        self.finish_session_validation(completed)?;
        self.recent_validation = self.native_validation_key().map(|key| RecentValidation {
            at: crate::platform::time::Instant::now(),
            key,
        });
        Ok(())
    }
    fn native_validation_key(&self) -> Option<(String, u64, u64)> {
        if self.browser_cookies() || self.browser_authority.is_some() || self.browser_credentials.is_some() {
            return None;
        }
        let session = self.session.as_ref()?;
        session.ws_token.as_ref()?;
        Some((session.session_id.clone(), self.credential_revision, self.fresh_auth.operation_epoch()))
    }
    fn reusable_validation(&self) -> bool {
        !self.operation_cancel.is_cancelled()
            && self.recent_validation.as_ref().is_some_and(|recent| {
                recent.at.elapsed() < VALIDATION_REUSE_WINDOW
                    && self.native_validation_key().as_ref() == Some(&recent.key)
            })
    }
    fn begin_session_validation(&self, original: Option<&std::sync::Arc<owned_operation::OwnedOperationScope>>) -> Result<owned_session_validation::ValidationContext> {
        let browser=self.browser_cookies();
        if browser{self.check_browser_credential_deadline()?;}
        let was_local=self.browser_local_read_only;
        let operation=browser.then(|| match original {
            Some(scope)=>owned_session_validation::ValidationOperation::Owned(scope.clone()),
            None=>owned_session_validation::ValidationOperation::Ordinary(self.operation_cancel.clone()),
        });
        if let Some(token)=operation.as_ref(){token.check(self)?;}
        Ok(owned_session_validation::ValidationContext::new(self, browser, was_local, operation))
    }
    fn apply_session_validation_body(
        &mut self,
        received: Result<super::plaintext::Plain<Value>>,
        observed_status: &mut Option<u16>,
        operation: Option<&owned_session_validation::ValidationOperation>,
        validation_before: Result<BeforeSessionValidation>,
        transition_out: &mut Option<ActualSessionValidationTransition>,
    ) -> Result<()> {
        // A verification request holds only until the next answer.
        self.session_verification = None;
        // Observe known denial before cancellation can mask it. Native callers
        // retain their existing typed transport behavior.
        if matches!(*observed_status,Some(401|403))&&received.is_err(){
            let error=Error::Expired;
            if self.browser_authority.is_some()||self.browser_credentials.is_some()||self.session.is_some(){self.forget_session();}
            return Err(error);
        }
        if let Some(token)=operation{token.check_dispatched(self)?;}
        let response=match received {
            Err(Error::Expired|Error::Forbidden)=>{self.forget_session();return Err(Error::Expired);},
            other=>other?,
        };
        if !session_response::succeeded(&response) {
            // Device verification or re-auth: the server kept the session, so
            // the native client keeps it (and its stored credentials) too.
            if self.hold_for_verification(&response) {
                return Err(Error::VerificationRequired);
            }
            self.forget_session();
            return Err(Error::Expired);
        }
        if self
            .browser_authority
            .as_ref()
            .is_some_and(|authority| text(&response["user"], "id") != authority.principal)
        {
            self.forget_session();
            return Err(Error::Expired);
        }
        let token = session_response::websocket_token(&response)?.to_owned();
        if let Some(token)=operation{token.check_dispatched(self)?;}
        self.user = session_response::user(&response)?.clone();
        if session_response::principal(&self.user).is_err() {
            return Err(Error::Protocol);
        }
        self.refresh_transport_token(token)?;
        self.observe_browser_owner_guards(&response);
        self.credentials_changed();
        // Mint only after the existing success/principal/body validation AND real
        // credential publication. Unverifiable live originals are revoked by the
        // registry; ordinary auth with a truly empty registry stays compatible.
        match validation_before.and_then(|before| before.finish(self)) {
            Ok(transition) => {
                self.record_actual_session_validation_transition(&transition)?;
                *transition_out = Some(transition);
            },
            Err(_) => self.refuse_unverifiable_owned_session_validation_lineage()?,
        }
        if let Some(token)=operation{token.check_dispatched(self)?;}
        Ok(())
    }
    fn finish_session_validation_wrapper(
        &mut self, context: &owned_session_validation::ValidationContext, result: Result<()>,
    ) -> Result<()> {
        let browser=context.browser;
        let was_local=context.was_local;
        let operation=&context.operation;
        let observed_status=context.observed_status;
        // A malformed body can already have replaced user before the existing
        // Protocol return. Revoke unreadable live lineage now, even for direct
        // callers, while retaining the original error and real merged headers.
        if result.is_err() && self.fresh_auth_binding().is_err() {
            self.revoke_unreadable_owned_session_validation_lineage();
        }
        if browser {
            if matches!(observed_status,Some(401|403))&&result.is_err(){
                let error=Error::Expired;
                if self.browser_authority.is_some()||self.browser_credentials.is_some()||self.session.is_some(){self.forget_session();}
                return Err(error);
            }
            if self.check_browser_credential_deadline().is_err(){
                self.clear_browser_transport_grant();
                return Err(Error::Expired);
            }
            // Core revocation replaces/cancels the operation token too. Preserve
            // that authoritative typed denial instead of masking it as caller
            // cancellation after the credentials have already been forgotten.
            if matches!(result,Err(Error::Expired|Error::Authentication|Error::Forbidden))&&self.browser_credentials.is_none()&&self.session.is_none(){return result;}
            if let Some(token)=operation.as_ref() && token.check_dispatched(self).is_err(){
                self.clear_browser_transport_grant();self.browser_local_read_only=was_local;
                return Err(Error::Cancelled);
            }
            match result {
                Ok(())=>self.browser_local_read_only=false,
                Err(error) if browser::browser_restore_network_unavailable(error,observed_status)=>{
                    if self.browser_credentials.is_some()||self.session.is_some(){self.enter_browser_local_read_only();}
                },
                Err(Error::Cancelled)=>{self.clear_browser_transport_grant();self.browser_local_read_only=was_local;},
                Err(_)=>{if self.browser_authority.is_some()||self.browser_credentials.is_some()||self.session.is_some(){self.forget_session();}},
            }
        }
        result
    }
    pub async fn login_password(
        &mut self,
        email: &str,
        password: &str,
        tfa: Option<&str>,
    ) -> Result<()> {
        self.login_password_context(email, password, tfa, None).await
    }
    pub async fn login_password_with_options(
        &mut self, email: &str, password: &str, tfa: Option<&str>, options: PasswordLoginOptions,
    ) -> Result<()> {
        self.login_password_context_with_options(email, password, tfa, None, options).await
    }
    pub(super) async fn login_password_context(
        &mut self, email: &str, password: &str, tfa: Option<&str>, routing_session_id: Option<&str>,
    ) -> Result<()> {
        self.login_password_context_with_options(email,password,tfa,routing_session_id,PasswordLoginOptions::default()).await
    }
    pub(super) async fn login_password_context_with_options(
        &mut self, email: &str, password: &str, tfa: Option<&str>, routing_session_id: Option<&str>,
        options: PasswordLoginOptions,
    ) -> Result<()> {
        let tfa = tfa.map(|code| (code, crate::web_auth::TfaCodeType::Otp));
        self.login_password_transaction(email, password, tfa, routing_session_id, options).await.map(|_| ())
    }
    /// Password sign-in with an OTP or a backup code as second factor; reports
    /// the unlocking credential version (for the v1→v2 migration) and the
    /// backup codes left.
    ///
    /// # Errors
    /// As [`Client::login_password_with_options`]. With a backup code, a
    /// refused code is `Authentication`, never `TwoFactorRequired`: the
    /// caller already supplied the second factor.
    pub async fn login_password_second_factor(
        &mut self, email: &str, password: &str, tfa: Option<(&str, crate::web_auth::TfaCodeType)>,
        options: PasswordLoginOptions,
    ) -> Result<PasswordLoginReport> {
        self.login_password_transaction(email, password, tfa, None, options).await
    }
    async fn login_password_transaction(
        &mut self, email: &str, password: &str, tfa: Option<(&str, crate::web_auth::TfaCodeType)>,
        routing_session_id: Option<&str>, options: PasswordLoginOptions,
    ) -> Result<PasswordLoginReport> {
        // A new sign-in is an isolated credential transaction. An existing
        // account's refresh token must not be rotated or published as the new
        // account while its challenge is still unverified.
        // Only the WASM legacy branch uses this scope. Native and v2 KDF paths
        // remain synchronous and keep their existing transaction behavior.
        let unwrap_scope = if cfg!(target_arch = "wasm32") && self.browser_password_transport {
            Some(PasswordUnwrapScope::begin(self)?)
        } else { None };
        let backup = self.begin_signin();
        let result = self.password_inner(email, password, tfa, routing_session_id, options, unwrap_scope.as_ref()).await;
        self.finish_signin(backup, result.is_ok())?;
        result
    }
    /// Set the current account's credentials aside for a new sign-in.
    pub(super) fn begin_signin(&mut self) -> SigninBackup {
        SigninBackup {
            cookies: std::mem::take(&mut self.cookies),
            session: self.session.take(),
            browser_credentials: self.browser_credentials.take(),
        }
    }
    /// End a sign-in begun by [`Client::begin_signin`]: restore the previous
    /// credentials after a failure, zeroize them after a success.
    pub(super) fn finish_signin(&mut self, backup: SigninBackup, succeeded: bool) -> Result<()> {
        let SigninBackup { cookies: mut previous, session, browser_credentials } = backup;
        if !succeeded {
            self.cookies = previous;
            self.session = session;
            self.browser_credentials = browser_credentials;
            self.credentials_changed();
            return Ok(());
        }
        if self.browser_authority.is_some() {
            let session=self.session.take().ok_or(Error::Protocol)?;
            self.browser_credentials=Some(credentials::BrowserCredentials::from_native_session(session));
        }
        drop((session, browser_credentials));
        for value in previous.values_mut() {
            zeroize::Zeroize::zeroize(value);
        }
        Ok(())
    }
    /// The unauthenticated email lookup: normalized email, its hash, the
    /// account email salt (bounded) and the derived email encryption key.
    pub(super) async fn login_lookup(&mut self, email: &str) -> Result<LoginLookup> {
        let email = email.trim().to_lowercase();
        if email.len() > 512 || !email.contains('@') {
            return Err(Error::Authentication);
        }
        let hashed_email = crypto::hash_email(&email);
        let lookup = self
            .request(
                Method::POST,
                "/v1/auth/lookup",
                Some(json!({"hashed_email":hashed_email})),
            )
            .await?;
        let user_email_salt = required(&lookup, "user_email_salt")?.to_owned();
        let salt = STANDARD
            .decode(&user_email_salt)
            .map_err(|_| Error::Protocol)?;
        if salt.len() < 16 || salt.len() > 128 {
            return Err(Error::Protocol);
        }
        let email_key = crypto::derive_email_key(&email, &user_email_salt)?;
        Ok(LoginLookup { email, hashed_email, user_email_salt, salt, email_key })
    }
    /// Owner guards every authenticated login reply must pass before its
    /// master key is unwrapped: the account email salt matches the lookup,
    /// the user has an id and (native) the refresh cookie arrived.
    pub(super) fn check_login_owner(&self, user: &Value, user_email_salt: &str) -> Result<()> {
        if text(user, "user_email_salt") != user_email_salt
            || (!self.browser_cookies() && !self.cookies.contains_key("auth_refresh_token"))
        {
            return Err(Error::Protocol);
        }
        required(user, "id")?;
        Ok(())
    }
    /// Install the session of an authenticated, unlocked login reply.
    pub(super) fn admit_login(&mut self, login: &Value, lookup: LoginLookup, session_id: String, master: Key) -> Result<()> {
        let user = login.get("user").ok_or(Error::Protocol)?.clone();
        let LoginLookup { hashed_email, user_email_salt, email_key, .. } = lookup;
        let session = Session {
            api_url: self.base.to_string().trim_end_matches('/').to_owned(),
            session_id,
            cookies: self.cookies.clone(),
            ws_token: login
                .get("ws_token")
                .and_then(Value::as_str)
                .map(str::to_owned),
            master_key: master,
            hashed_email,
            user_email_salt,
            email_encryption_key: Some(email_key),
            created_at: now_ms(),
            paired_session_expires_at: None,
            active_team_id: None,
        };
        self.install_new_session(session, user);
        Ok(())
    }
    /// Revoke the server session of a login whose local unlock failed
    /// (native only: browser cookies may belong to another account).
    pub(super) async fn revoke_unlocked_login(&mut self) {
        if !self.browser_cookies() {
            // Best effort: the unlock error is what the caller reports.
            let _ = self.request(Method::POST, "/v1/auth/logout", Some(json!({}))).await;
        }
    }
    async fn password_inner(
        &mut self,
        email: &str,
        password: &str,
        tfa: Option<(&str, crate::web_auth::TfaCodeType)>,
        routing_session_id: Option<&str>,
        options: PasswordLoginOptions,
        _unwrap_scope: Option<&PasswordUnwrapScope>,
    ) -> Result<PasswordLoginReport> {
        if password.is_empty() {
            return Err(Error::Authentication);
        }
        let session_id = match routing_session_id {
            Some(id) if uuid::Uuid::parse_str(id).is_ok_and(|v|v.to_string()==id) => id.to_owned(),
            Some(_) => return Err(Error::Authentication),
            None => uuid::Uuid::new_v4().to_string(),
        };
        let lookup = self.login_lookup(email).await?;
        let (hashed_email, email_key, salt) = (&lookup.hashed_email, &lookup.email_key, &lookup.salt);
        let challenge = self
            .request(
                Method::POST,
                "/v1/auth/password-v2/challenge",
                Some(
                    json!({"hashed_email":hashed_email,"session_id":session_id,"purpose":"login"}),
                ),
            )
            .await?;
        let (auth, wrap) = crypto::derive_password_keys_v2(password, salt)?;
        let proof = crypto::password_proof_v2(&auth, required(&challenge, "nonce")?, "login")?;
        drop(auth); // auth proof is complete; never retain an unused derived auth key.
        let mut body = json!({"hashed_email":hashed_email,"session_id":session_id,"login_method":"password","stay_logged_in":options.stay_logged_in,"email_encryption_key":email_key,"credential_version":2,"challenge_id":required(&challenge,"challenge_id")?,"password_proof":proof});
        if let Some((code, kind)) = tfa {
            body["tfa_code"] = json!(code);
            body["code_type"] = json!(kind.wire())
        }
        let backup = matches!(tfa, Some((_, crate::web_auth::TfaCodeType::Backup)));
        let mut login = self
            .request(Method::POST, "/v1/auth/login", Some(body.clone()))
            .await?;
        let mut version = 2;
        if login.get("success") != Some(&json!(true))
            || login.get("tfa_required") == Some(&json!(true))
        {
            let v2_tfa = login.get("tfa_required") == Some(&json!(true));
            // The server explicitly permits v1 lookup only after the v2 proof;
            // a v2 account cannot be downgraded through this compatibility path.
            body.as_object_mut()
                .ok_or(Error::Protocol)?
                .remove("password_proof");
            body.as_object_mut()
                .ok_or(Error::Protocol)?
                .remove("challenge_id");
            body["credential_version"] = json!(1);
            body["lookup_hash"] = json!(crypto::hash_key(password, salt)?);
            let legacy = self
                .request(Method::POST, "/v1/auth/login", Some(body))
                .await?;
            if legacy.get("success") == Some(&json!(true))
                && legacy.get("tfa_required") != Some(&json!(true))
            {
                login = legacy;
                version = 1
            } else if !backup && (v2_tfa || legacy.get("tfa_required") == Some(&json!(true))) {
                // A refused backup code is a wrong credential: the caller
                // already gave the second factor (web `tfa_invalid`).
                return Err(Error::TwoFactorRequired);
            } else {
                return Err(Error::Authentication);
            }
        }
        let user = login.get("user").ok_or(Error::Protocol)?;
        if user.get("credential_version").and_then(Value::as_u64) != Some(version as u64) {
            return Err(Error::Protocol);
        }
        self.check_login_owner(user, &lookup.user_email_salt)?;
        #[cfg(target_arch = "wasm32")]
        let unwrapped = if self.browser_password_transport && version == 1 {
            let scope = _unwrap_scope.ok_or(Error::Cancelled)?;
            // Canonical version/email-salt/server response checks above still
            // precede primitive admission. The wrapper salt retains v1 semantics.
            let result = crypto::browser_legacy::unwrap(password, version,
                required(user, "encrypted_key")?, required(user, "salt")?, required(user, "key_iv")?,
                || scope.check(self)).await;
            scope.check(self)?;
            result
        } else { unwrap_login_master_key(password,version,&lookup.salt,&wrap,user) };
        #[cfg(not(target_arch = "wasm32"))]
        let unwrapped = unwrap_login_master_key(password,version,&lookup.salt,&wrap,user);
        drop(wrap); // no persistent/cache state; release before any failure cleanup await.
        let master = match unwrapped {
            Ok(v) => v,
            Err(e) => {
                // Fetch cookies cannot be rolled back. Before fresh owner proof,
                // an ambient cookie may already belong to a different account.
                // Never issue blind browser logout as local unwrap cleanup.
                self.revoke_unlocked_login().await;
                return Err(e);
            }
        };
        let remaining_backup_codes = if backup {
            login.get("remaining_backup_codes").and_then(Value::as_u64).and_then(|n| u32::try_from(n).ok())
        } else { None };
        self.admit_login(&login, lookup, session_id, master)?;
        Ok(PasswordLoginReport { credential_version: version, remaining_backup_codes })
    }
    /// Shared by password login and signup: replace every account-scoped
    /// cache and credential authority with the freshly established session.
    pub(super) fn install_new_session(&mut self, session: Session, user: Value) {
        self.clear_account_cache();
        self.session = Some(session);
        self.session_verification = None;
        self.generation = self.generation.wrapping_add(1);
        self.user = user;
        self.clear_chat_rows();
        self.wrappers.clear();
        self.team_key = None;
        self.credentials_changed();
    }
}

#[cfg(test)]
mod auth_transaction_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sync.access.first-party-authenticated,sync.client.shared-rust-policy
    #[tokio::test]
    async fn failed_new_signin_cannot_send_or_publish_previous_account_cookie() {
        failed_new_signin_preserves_previous(None).await;
    }
    // contract-test: supporting surface=sdks.rust assertions=sync.access.first-party-authenticated,sync.client.shared-rust-policy
    #[tokio::test]
    async fn checked_cookie_preference_cannot_send_or_publish_previous_account_cookie() {
        failed_new_signin_preserves_previous(Some(PasswordLoginOptions { stay_logged_in:true })).await;
    }
    async fn failed_new_signin_preserves_previous(options:Option<PasswordLoginOptions>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut raw = [0; 4096];
            let n = stream.read(&mut raw).await.unwrap();
            let request = String::from_utf8_lossy(&raw[..n]);
            assert!(!request.contains("old-secret"));
            assert!(!request.to_ascii_lowercase().contains("cookie:"));
            let body = r#"{"user_email_salt":"invalid base64"}"#;
            stream.write_all(format!("HTTP/1.1 200 OK\r\nSet-Cookie: auth_refresh_token=new-unverified\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        });
        let mut cookies = BTreeMap::new();
        cookies.insert("auth_refresh_token".into(), "old-secret".into());
        let session = Session {
            api_url: format!("http://{address}"),
            session_id: "old-session".into(),
            cookies,
            ws_token: None,
            master_key: zeroize::Zeroizing::new([3; 32]),
            hashed_email: "old-owner".into(),
            user_email_salt: "salt".into(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        let mut client = Client::new(&format!("http://{address}"), Some(session)).unwrap();
        let (tx, mut events) = mpsc::unbounded_channel();
        client.set_credential_updates(tx);
        let _ = events.try_recv();
        let result=match options {
            Some(options)=>client.login_password_with_options("synthetic@example.org","synthetic password",None,options).await,
            None=>client.login_password("synthetic@example.org","synthetic password",None).await,
        };
        assert!(result.is_err());
        assert_eq!(client.session().unwrap().session_id, "old-session");
        assert_eq!(
            client.cookies.get("auth_refresh_token").map(String::as_str),
            Some("old-secret")
        );
        let CredentialEvent::Updated(restored) = events.try_recv().unwrap() else {
            panic!("restored session event")
        };
        assert_eq!(restored.session.session_id, "old-session");
        assert_eq!(
            restored
                .session
                .cookies
                .get("auth_refresh_token")
                .map(String::as_str),
            Some("old-secret")
        );
        assert!(events.try_recv().is_err());
        server.await.unwrap();
    }
    fn password_fixture()->Value{serde_json::from_str(include_str!("../../tests/crypto_fixtures/account.json")).unwrap()}
    fn fixture_user(f:&Value)->Value{json!({"encrypted_key":f["password_v2_wrapped_master"],"salt":f["password_v2_salt"],"key_iv":f["iv"]})}
    // contract-test: supporting surface=sdks.rust assertions=auth.keys.independent-unlock,auth.keys.client-wrapped
    #[test]
    fn successful_v2_unwrap_reuses_ephemeral_wrap_and_never_rederives_password(){
        // Existing fixed crypto vector ties auth proof and wrapper key domains.
        let f=password_fixture();let salt=STANDARD.decode(f["password_v2_salt"].as_str().unwrap()).unwrap();let wrap=crypto::decode_key(f["wrap_key_v2"].as_str().unwrap()).unwrap();
        let master=unwrap_login_master_key("not-used-by-v2-unwrap",2,&salt,&wrap,&fixture_user(&f)).unwrap();
        assert_eq!(crypto::encode_key(&master),f["legacy_master"].as_str().unwrap());
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.keys.independent-unlock,auth.keys.client-wrapped
    #[test]
    fn v2_reuse_requires_exact_canonical_wrapper_salt(){
        let f=password_fixture();let salt=STANDARD.decode(f["password_v2_salt"].as_str().unwrap()).unwrap();let wrap=crypto::decode_key(f["wrap_key_v2"].as_str().unwrap()).unwrap();let mut user=fixture_user(&f);
        user["salt"]=json!(STANDARD.encode([8u8;16]));assert!(matches!(unwrap_login_master_key("unused",2,&salt,&wrap,&user),Err(Error::Protocol)));
        user["salt"]=json!(format!("{} ",f["password_v2_salt"].as_str().unwrap()));assert!(matches!(unwrap_login_master_key("unused",2,&salt,&wrap,&user),Err(Error::Protocol)));
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.keys.independent-unlock,auth.keys.client-wrapped
    #[test]
    fn v1_unwrap_still_uses_legacy_password_derivation_and_rejects_unknown_version(){
        let f=password_fixture();let salt=STANDARD.decode(f["legacy_salt"].as_str().unwrap()).unwrap();let unrelated_wrap=zeroize::Zeroizing::new([99u8;32]);
        let user=json!({"encrypted_key":f["legacy_wrapped_master"],"salt":f["legacy_salt"],"key_iv":f["iv"]});
        let master=unwrap_login_master_key(f["legacy_password"].as_str().unwrap(),1,&salt,&unrelated_wrap,&user).unwrap();assert_eq!(crypto::encode_key(&master),f["legacy_master"].as_str().unwrap());
        assert!(unwrap_login_master_key("wrong",1,&salt,&unrelated_wrap,&user).is_err());assert!(unwrap_login_master_key("unused",3,&salt,&unrelated_wrap,&user).is_err());
    }

}

#[cfg(test)]
mod legacy_unwrap_scope_tests {
    use super::*;
    fn client() -> Client { let mut c = Client::new("https://api.example.invalid", None).unwrap(); c.browser_password_transport = true; c.browser_transport = true; c }
    // contract-test: supporting surface=sdks.rust assertions=sync.access.first-party-authenticated,sync.client.shared-rust-policy
    #[test]
    fn original_precredential_scope_rejects_context_generation_cancel_and_denial_drift() {
        for change in 0..7 {
            let mut c = client(); let scope = PasswordUnwrapScope::begin(&c).unwrap();
            match change { 0 => c.operation_cancel.cancel(), 1 => c.generation += 1,
                2 => c.user = json!({"id":"different-owner"}),
                3 => c.options.app_url = Some("https://different.example.invalid".into()),
                4 => c.browser_password_stay_logged_in = Some(true),
                5 => { c.task_watch_authority.deny_cached_chat(None).unwrap(); },
                _ => c.operation_cancel = CancellationToken::new(), }
            assert!(scope.check(&c).is_err()); assert!(c.session.is_none());
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=sync.access.first-party-authenticated,sync.client.shared-rust-policy
    #[test]
    fn captured_absolute_deadline_cannot_be_reset_by_temporarily_absent_credentials() {
        let c = client(); let mut scope = PasswordUnwrapScope::begin(&c).unwrap();
        scope.expires_at = Some(now_ms().saturating_sub(1));
        assert!(matches!(scope.check(&c), Err(Error::Expired)));
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "session_validation_tests.rs"]
mod session_validation_tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "owned_session_validation_tests.rs"]
mod owned_session_validation_tests;

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "validation_reuse_tests.rs"]
mod validation_reuse_tests;
