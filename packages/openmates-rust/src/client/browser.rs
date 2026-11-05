//! Explicit first-party browser authority. None of these types serialize keys,
//! cookies or tokens; the browser binding must keep them in its owning worker.
#[path = "browser_local_cursor.rs"]
mod local_cursor;
#[path="browser_ordinary_retention.rs"]
mod ordinary_retention;
pub use ordinary_retention::BrowserOrdinaryKeyRetention;
#[path = "browser_cache_metadata.rs"]
mod cache_metadata;
#[doc(hidden)]
pub use cache_metadata::BrowserProfileCacheReadiness;
#[doc(hidden)]
pub use cache_metadata::OwnedBrowserProfileCacheAbsence;
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
#[path="browser_first_session_restore.rs"]
mod first_session_restore;
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
#[doc(hidden)]
pub use first_session_restore::{PreparedBrowserFirstSession,BrowserFirstSessionControl,BrowserFirstSessionReceipt};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
#[doc(hidden)]
pub use first_session_restore::{PreparedBrowserFirstSessionData,BrowserFirstSessionDataControl,BrowserFirstSessionData};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(in crate::client) use first_session_restore::prepare_normal_data;
pub use cache_metadata::{BrowserMetadataCacheMode,BrowserMetadataCacheScope};
#[doc(hidden)]
pub use cache_metadata::{OriginalHintRefreshAdmission,OriginalHintRefreshBatch,OriginalHintRowSeed,OriginalHintRowMetadataAdmission,OriginalHintRowMetadataPublication,OriginalHintMetadataApplied,OriginalHintDraftInventoryPrerequisite,OriginalHintDraftInventoryTicket,UntrustedDraftInventoryPageData,UntrustedDraftInventoryRereadData,OwnedOriginalHintWindowPreparation,OwnedOriginalHintWindowCompletion,OriginalHintWindowBatch,OwnedBrowserReadDriver,OwnedBrowserReadStep,OwnedBrowserReadPhase,OwnedBrowserReadIO,OwnedBrowserReadPublication,OwnedBrowserMetadataContinuation,OwnedBrowserReadControl,OwnedBrowserMetadataPublication,OriginalHintRecoveryHandoff,OwnedBrowserReadTerminalObserver,OwnedBrowserReadTerminal,BrowserOriginalHintRecoveryDriver,BrowserOriginalHintRecoveryStep,BrowserOriginalHintRecoveryApply,BrowserOriginalHintRecoveryIo,BrowserOriginalHintRecoveryResume,BrowserOriginalHintRecoveryControl,BrowserOriginalHintRecoveryAdoption,BrowserOriginalHintRecoveryProgress,BrowserOriginalHintRecoveryPendingPersistence,BrowserOriginalHintRecoveryDeferred,BrowserOriginalHintRecoveryCheckpointPreparation,BrowserOriginalHintRecoveryCheckpointCrypto,BrowserOriginalHintRecoveryCheckpointWrite,BrowserOriginalHintRecoveryPersistenceFailure};
pub(super) use cache_metadata::BrowserMetadataOwnedTransition;
#[path="browser_message_policy.rs"]
mod message_policy;
pub use message_policy::browser_message_merge_policy_json;
use super::*;
#[cfg(any(test,all(target_arch="wasm32",feature="browser-metadata-prototype")))]
#[path="browser_configured_native.rs"]
pub(in crate::client) mod configured_native;
use zeroize::Zeroize;
#[path = "browser_snapshot.rs"]
mod snapshot;
#[path = "browser_local_json.rs"]
mod local_json;
pub(super) fn validate_local_json(encoded:&str)->Result<()> {local_json::validate(encoded)}
pub use snapshot::{BrowserSealedCredentials,BrowserCredentialCasScope,BrowserCredentialCasEffect,BrowserCredentialCasIoReceipt,BrowserCredentialCasOperation,BrowserPreparedCredentialCas,BrowserCredentialCasValidation};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BrowserPersistence {
    MemoryOnly,
    Persisted,
}

/// Existing browser profile evidence accompanying a worker-local master key.
/// The caller supplies the existing profile record, never a validated-owner flag.
/// Construction validates shape only; fresh server authentication below is the
/// sole authority that admits this evidence. No Serialize/Deserialize or Debug.
#[cfg_attr(not(target_arch = "wasm32"), allow(dead_code))]
pub struct BrowserProfileKey {
    principal: String,
    master: crypto::master::MasterCapability,
    hashed_email: String,
    user_email_salt: String,
    persistence: BrowserPersistence,
    paired_session_expires_at: Option<u64>,
}
impl BrowserProfileKey {
    pub fn from_existing_profile(
        principal: &str,
        master: Key,
        hashed_email: &str,
        user_email_salt: &str,
        persistence: BrowserPersistence,
    ) -> Result<Self> {
        uuid::Uuid::parse_str(principal).map_err(|_| Error::Authentication)?;
        if hashed_email.is_empty()
            || hashed_email.len() > 512
            || user_email_salt.is_empty()
            || user_email_salt.len() > 512
        {
            return Err(Error::Authentication);
        }
        Ok(Self {
            principal: principal.into(),
            master: crypto::master::MasterCapability::from_browser_raw(master),
            hashed_email: hashed_email.into(),
            user_email_salt: user_email_salt.into(),
            persistence,
            paired_session_expires_at: None,
        })
    }
    #[cfg(target_arch = "wasm32")]
    pub fn from_existing_browser_profile(principal:&str,master:crypto::master::MasterCapability,hashed_email:&str,user_email_salt:&str,persistence:BrowserPersistence)->Result<Self> {
        uuid::Uuid::parse_str(principal).map_err(|_|Error::Authentication)?;
        // Existing browser profile metadata may be absent in legacy storage;
        // an AES resource plus explicit local profile is not a key-owner proof.
        // Missing optional hash/salt cannot force new auth/enrollment.
        if hashed_email.len()>512||user_email_salt.len()>512 {return Err(Error::Authentication);}
        master.ensure_current()?;
        Ok(Self {principal:principal.into(),master,hashed_email:hashed_email.into(),user_email_salt:user_email_salt.into(),persistence,paired_session_expires_at:None})
    }
    /// Carry only an already-known paired deadline from the caller's existing
    /// profile/credential metadata. Absence creates no expiry/owner assertion.
    pub fn with_existing_paired_deadline(mut self, deadline: Option<u64>) -> Result<Self> {
        self.paired_session_expires_at=match(self.paired_session_expires_at,deadline){(Some(old),Some(next))=>Some(old.min(next)),(Some(old),None)=>Some(old),(None,next)=>next};
        self.current()?;Ok(self)
    }
    fn current(&self)->Result<()> {
        self.master.ensure_current()?;
        if self.paired_session_expires_at.is_some_and(|deadline|deadline<=now_ms()) {
            self.master.invalidate();return Err(Error::Expired);
        }
        Ok(())
    }

}
impl Drop for BrowserProfileKey {
    fn drop(&mut self) {
        self.principal.zeroize();
        self.hashed_email.zeroize();
        self.user_email_salt.zeroize();
    }
}
pub(super) struct BrowserAuthority {
    pub(super) principal: String,
    pub(super) persistence: BrowserPersistence,
    pub(super) owner_guards: bool,
}
/// Public, non-secret profile/session context. This cannot be used to import
/// authority. `local_read_only == false` is not a server-authentication grant:
/// cancelled refresh can retain the key/profile while all transport is revoked.
/// Every server operation still requires live credentials and owner guards.
pub struct BrowserSessionStatus {
    principal: String,
    generation: u64,
    persistence: BrowserPersistence,
    local_read_only: bool,
}
impl BrowserSessionStatus {
    /// True means explicit cached-profile access only, NOT server auth or key
    /// association. Network/stream/strong persistence requires fresh validation.
    pub fn is_local_read_only(&self)->bool {self.local_read_only}
    pub fn principal(&self) -> &str {
        &self.principal
    }
    pub fn generation(&self) -> u64 {
        self.generation
    }
    pub fn persistence(&self) -> BrowserPersistence {
        self.persistence
    }
}
// Admission proof is deliberately internal. A local email envelope alone is
// insufficient: it must agree with the authenticated account's canonical data.
// Legacy accounts without a canonical envelope retain only hash/salt evidence;
// that does not prove key ownership or solve cross-tab owner/key association.
#[cfg_attr(not(target_arch = "wasm32"), allow(dead_code))]
fn validate_browser_account_profile(profile: &BrowserProfileKey, account: &Value) -> Result<()> {
    if account["user_id"].as_str() != Some(profile.principal.as_str())
        || account["hashed_email"].as_str() != Some(profile.hashed_email.as_str())
        || account["user_email_salt"].as_str() != Some(profile.user_email_salt.as_str())
    {
        return Err(Error::Authentication);
    }
    match account.get("encrypted_email_with_master_key") {
        None | Some(Value::Null) => Ok(()),
        Some(Value::String(encrypted)) if !encrypted.is_empty() && encrypted.len() <= 8192 => {
            let plaintext = crypto::decrypt_bytes(encrypted, profile.master.native_key().map_err(|_|Error::Authentication)?)
                .map_err(|_| Error::Authentication)?;
            let email = std::str::from_utf8(&plaintext).map_err(|_| Error::Authentication)?;
            if email.is_empty() {
                return Err(Error::Authentication);
            }
            let hash = zeroize::Zeroizing::new(crypto::hash_email(email));
            if hash.as_str() != profile.hashed_email {
                return Err(Error::Authentication);
            }
            Ok(())
        }
        _ => Err(Error::Authentication),
    }
}

async fn validate_browser_account_profile_async(profile:&BrowserProfileKey,account:&Value)->Result<()> {
    if account["user_id"].as_str()!=Some(profile.principal.as_str())||account["hashed_email"].as_str()!=Some(profile.hashed_email.as_str())||account["user_email_salt"].as_str()!=Some(profile.user_email_salt.as_str()){return Err(Error::Authentication);}
    match account.get("encrypted_email_with_master_key") {
        None|Some(Value::Null)=>Ok(()),
        Some(Value::String(encrypted)) if !encrypted.is_empty()&&encrypted.len()<=8192=>{
            let plaintext=profile.master.decrypt_bytes(encrypted).await.map_err(|error| if matches!(error,Error::Cancelled){error}else{Error::Authentication})?;
            let email=std::str::from_utf8(&plaintext).map_err(|_|Error::Authentication)?;
            if email.is_empty()||crypto::hash_email(email)!=profile.hashed_email{return Err(Error::Authentication);}
            profile.master.ensure_current()?;Ok(())
        },
        _=>Err(Error::Authentication),
    }
}

pub(super) fn browser_restore_network_unavailable(error:Error,status:Option<u16>)->bool {
    matches!(error,Error::Offline)&&matches!(status,None|Some(200|429|500..=599))
}

pub(super) fn expected_principal_mismatch(bytes:&[u8])->bool {
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Detail<'a>{#[serde(borrow)] error:&'a str}
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Closed<'a>{#[serde(borrow)] detail:Detail<'a>}
    bytes.len()<=4096&&serde_json::from_slice::<Closed<'_>>(bytes).is_ok_and(|value|value.detail.error=="session_principal_mismatch")
}

impl Client {
    fn browser_canonical_json_current(&self,principal:&str)->Result<()> {
        self.require_canonical_read_profile()?;
        if !self.browser_transport || !uuid::Uuid::parse_str(principal).is_ok_and(|value|value.to_string()==principal)
            || !self.browser_authority.as_ref().is_some_and(|authority|authority.principal==principal)
            || self.user["id"].as_str()!=Some(principal){return Err(Error::Forbidden);}
        Ok(())
    }
    /// Single browser viewing page: existing canonical SDK auth/crypto/selectors,
    /// with an owned JSON handoff. This confers no complete history or durable ACK.
    pub async fn browser_saved_chat_read_json(&mut self,principal:&str,id:&str,
        options:saved_chat_read::SavedChatReadOptions)->Result<zeroize::Zeroizing<String>> {
        self.browser_canonical_json_current(principal)?;
        if !(1..=message_window::MAX_MESSAGES).contains(&options.limit)||options.max_pages!=1
            ||options.content_mode!=saved_chat_read::SavedChatContentMode::PageLocal{
            return Err(Error::Invalid("Browser saved read requires one bounded page-local view."));
        }
        let admission=sync_capability::AsyncCryptoScope::begin(self)?;admission.check_chat(self,id)?;
        // A successful public view is guarded before ANY post-await refusal.
        let output=self.saved_chat_read(id,options).await.map(plaintext::Plain::new);
        admission.check_chat(self,id)?;self.browser_canonical_json_current(principal)?;
        let output=output?;
        if output.window.chat.id!=id||output.chat_metadata.id!=id||output.window.history_complete
            ||output.window.pii_restoration!="page_local"||output.pages_read!=1
            ||output.content_mode!=saved_chat_read::SavedChatContentMode::PageLocal
            ||output.message_metadata.len()!=output.window.chat.messages.len(){return Err(Error::Protocol);}
        let page=&output.window;
        if page.chat.title.len()>4096||page.chat.messages.len()>message_window::MAX_MESSAGES
            ||page.payload_bytes>message_window::MAX_MESSAGE_BYTES
            ||page.chat.messages.iter().any(|message|!message_window::valid_message_id(&message.id)||message.role.is_empty()
                ||message.role.len()>32||message.content.len()>64*1024)
            ||output.message_metadata.iter().zip(&page.chat.messages).any(|(metadata,message)|metadata.id!=message.id||metadata.chat_id!=id||metadata.created_at<0){
            return Err(Error::Protocol);
        }
        const BROWSER_FRAME_RESERVE:usize=8192;
        if crate::client::monitor::cached_view::bounded_bytes(&*output,message_window::MAX_MESSAGE_BYTES-BROWSER_FRAME_RESERVE).is_none(){return Err(Error::Protocol);}
        let encoded=zeroize::Zeroizing::new(serde_json::to_string(&*output)?);
        if encoded.len()+BROWSER_FRAME_RESERVE>message_window::MAX_MESSAGE_BYTES{return Err(Error::Protocol);}
        admission.check_chat(self,id)?;self.browser_canonical_json_current(principal)?;
        Ok(encoded)
    }

    /// Private-migration browser adapter for caller-owned encrypted local rows.
    /// This tagged, incomplete view confers no remote authority or persistence ACK.
    /// The current existing-key profile must already be admitted in local mode.
    pub async fn browser_local_message_window_json(
        &self, expected_principal: &str, id: &str,
        options: message_window::MessageWindowOptions, encrypted_rows_json: &str,
    ) -> Result<zeroize::Zeroizing<String>> {
        let scope = self.browser_local_read_scope(expected_principal, id)?;
        let input = self.browser_local_read_input(encrypted_rows_json)?;
        let output = self.local_cached_message_window(id, options, input).await?;
        scope.check_chat(self, id)?;
        self.browser_local_read_scope(expected_principal, id)?;
        let encoded = zeroize::Zeroizing::new(serde_json::to_string(&output)?);
        if encoded.len() > 256 * 1024 { return Err(Error::Protocol); }
        scope.check_chat(self, id)?;
        self.browser_local_read_scope(expected_principal, id)?;
        Ok(encoded)
    }
    /// Same local operation with saved metadata and per-message mappings.
    /// Stored/page-local interpretation remains entirely in the shared helper.
    pub async fn browser_local_saved_chat_read_json(
        &self, expected_principal: &str, id: &str,
        options: saved_chat_read::SavedChatReadOptions, encrypted_rows_json: &str,
    ) -> Result<zeroize::Zeroizing<String>> {
        let scope = self.browser_local_read_scope(expected_principal, id)?;
        let input = self.browser_local_read_input(encrypted_rows_json)?;
        let output = self.local_cached_saved_chat_read(id, options, input).await?;
        scope.check_chat(self, id)?;
        self.browser_local_read_scope(expected_principal, id)?;
        let encoded = zeroize::Zeroizing::new(serde_json::to_string(&output)?);
        if encoded.len() > 256 * 1024 { return Err(Error::Protocol); }
        scope.check_chat(self, id)?;
        self.browser_local_read_scope(expected_principal, id)?;
        Ok(encoded)
    }
    fn browser_local_read_scope(
        &self,
        expected_principal: &str,
        id: &str,
    ) -> Result<sync_capability::AsyncCryptoScope> {
        self.browser_cached_view_scope(
            expected_principal,
            id,
            local_cached_read::CachedViewMode::LocalProfile,
        )
    }
    /// Same retained-row guard for either explicit cached view mode. The mode is
    /// fixed per operation and rechecked at every await, so a mode change refuses.
    pub(super) fn browser_cached_view_scope(
        &self,
        expected_principal: &str,
        id: &str,
        view: local_cached_read::CachedViewMode,
    ) -> Result<sync_capability::AsyncCryptoScope> {
        if !uuid::Uuid::parse_str(expected_principal)
            .is_ok_and(|v| v.to_string() == expected_principal)
            || !self.cached_view_admitted(view)
            || !self
                .browser_authority
                .as_ref()
                .is_some_and(|a| a.principal == expected_principal)
            || self.user["id"].as_str() != Some(expected_principal)
        {
            return Err(Error::Forbidden);
        }
        let scope = sync_capability::AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, id)?;
        Ok(scope)
    }
    fn browser_local_read_input(&self, encoded: &str) -> Result<local_cached_read::LocalEncryptedWindowInput> {
        local_json::validate(encoded)?;
        let mut value = plaintext::Plain::new(serde_json::from_str::<Value>(encoded)?);
        let object = value.as_object_mut().ok_or(Error::Protocol)?;
        if object.keys().any(|key| !["chat_metadata", "messages", "wrappers", "boundary", "compression_checkpoints"].contains(&key.as_str()))
            || !object.contains_key("chat_metadata")
            || !object.get("messages").is_some_and(Value::is_array)
            || !object.get("wrappers").is_some_and(Value::is_array) { return Err(Error::Protocol); }
        // Validate primitive-only boundary before moving any owned row values;
        // malformed extra fields stay inside the guarded input Value.
        let boundary = serde::Deserialize::deserialize(object.get("boundary").unwrap_or(&Value::Null))?;
        if object.get("compression_checkpoints").is_some_and(|value| !value.is_array()) { return Err(Error::Protocol); }
        let compression_checkpoints = object.get_mut("compression_checkpoints")
            .map(|value| std::mem::take(value.as_array_mut().unwrap())).unwrap_or_default();
        let chat_metadata = object.get_mut("chat_metadata").unwrap().take();
        let messages = std::mem::take(object.get_mut("messages").unwrap().as_array_mut().unwrap());
        let wrappers = std::mem::take(object.get_mut("wrappers").unwrap().as_array_mut().unwrap());
        Ok(local_cached_read::LocalEncryptedWindowInput { chat_metadata, messages, wrappers, boundary, compression_checkpoints })
    }
    #[cfg(test)]
    async fn verify_browser_account_profile(&mut self, profile: &BrowserProfileKey) -> Result<()> {
        let account = self
            .request(Method::GET, "/v1/auth/pair/v2/account-check", None)
            .await?;
        validate_browser_account_profile_async(profile, &account).await
    }
    pub fn browser_session_status(&self) -> Option<BrowserSessionStatus> {
        let authority = self.browser_authority.as_ref()?;
        self.require_credentials().ok()?;
        Some(BrowserSessionStatus {
            principal: authority.principal.clone(),
            generation: self.generation,
            persistence: authority.persistence,
            local_read_only: self.browser_local_read_only,
        })
    }
    pub(super) fn expected_request_principal(&self) -> Result<Option<String>> {
        let owner=self.browser_authority.as_ref().map(|a|a.principal.as_str()).or_else(||{
            self.require_credentials().ok()?;
            self.user["id"].as_str().filter(|v|!v.is_empty()).or_else(||self.user["user_id"].as_str().filter(|v|!v.is_empty()))
        });
        match owner {
            Some(owner) if uuid::Uuid::parse_str(owner).is_ok_and(|v|v.to_string()==owner)=>Ok(Some(owner.into())),
            Some(_) if self.browser_authority.is_some()=>Err(Error::Authentication),
            _=>Ok(None), // explicit native jar remains compatible with legacy fixture identity strings
        }
    }
    pub(super) fn require_browser_owner_guards(&self) -> Result<()> {
        self.check_browser_credential_deadline()?;
        if self.browser_cookies() && !self.browser_authority.as_ref().is_some_and(|a| a.owner_guards) {
            return Err(Error::Unavailable {code:"browser_owner_consistency_unsupported",reason:"BROWSER_OWNER_CONSISTENCY_REQUIRES_SERVER_CAPABILITIES"});
        }
        Ok(())
    }
    pub(super) fn observe_browser_owner_guards(&mut self, response:&Value) {
        if let Some(authority)=self.browser_authority.as_mut() {
            let caps=response.get("client_security_capabilities").and_then(Value::as_array);
            authority.owner_guards=caps.is_some_and(|v|v.len()<=16&&v.iter().all(|v|v.as_str().is_some_and(|v|v.len()<=64))
                &&["expected-principal-v1","ws-dual-principal-v1"].iter().all(|cap|v.iter().any(|v|v.as_str()==Some(*cap))));
        }
    }
    pub(super) fn browser_cookies(&self) -> bool {
        self.browser_transport || self.browser_password_transport || self.browser_authority.is_some()
    }

    /// Fresh first-party password login in its owning DedicatedWorker. This
    /// returns memory-only authority; it neither imports nor overwrites a legacy
    /// profile, exports credentials, acknowledges durability or requires an
    /// encrypted-email envelope. Hold the host refresh lock through this call.
    #[cfg(target_arch = "wasm32")]
    pub async fn browser_password_session(
        api_url: &str, app_origin: &str, session_id: &str,
        email: &str, password: &str, tfa: Option<&str>,
    ) -> Result<Self> {
        Self::browser_password_session_with_options(api_url,app_origin,session_id,email,password,tfa,PasswordLoginOptions::default()).await
    }
    /// Cookie preference does not change the memory-only local key policy.
    #[cfg(target_arch = "wasm32")]
    pub async fn browser_password_session_with_options(
        api_url: &str, app_origin: &str, session_id: &str,
        email: &str, password: &str, tfa: Option<&str>, options: PasswordLoginOptions,
    ) -> Result<Self> {
        use wasm_bindgen::JsCast;
        let worker=js_sys::global().dyn_into::<web_sys::DedicatedWorkerGlobalScope>()
            .map_err(|_|Error::Forbidden)?;
        if transport::validate_app_origin(&worker.location().origin())?
            != transport::validate_app_origin(app_origin)? { return Err(Error::Forbidden); }
        let mut client=Self::with_options(api_url,None,ClientOptions {
            app_url:Some(app_origin.into()), ..Default::default()
        })?;
        client.base=transport::validate_browser_base(api_url)?;
        client.browser_password_transport=true;
        client.browser_password_stay_logged_in=Some(options.stay_logged_in);
        client.browser_transport=true;
        client.login_password_context_with_options(email,password,tfa,Some(session_id),options).await?;
        client.finish_browser_password_session().await?;
        Ok(client)
    }

    // Only reached after the existing authenticated login response's password
    // wrapper was successfully unwrapped. No caller-supplied principal/key flag.
    #[cfg(any(target_arch = "wasm32", test))]
    async fn finish_browser_password_session(&mut self) -> Result<()> {
        if !self.browser_password_transport || !self.cookies.is_empty() {
            self.forget_session(); return Err(Error::Authentication);
        }
        let principal=required(&self.user,"id")?.to_owned();
        if !uuid::Uuid::parse_str(&principal).is_ok_and(|v|v.to_string()==principal) {
            self.forget_session(); return Err(Error::Authentication);
        }
        let native=self.session.take().ok_or(Error::Authentication)?;
        self.browser_credentials=Some(credentials::BrowserCredentials::from_native_session(native));
        self.browser_authority=Some(BrowserAuthority {
            principal, persistence:BrowserPersistence::MemoryOnly, owner_guards:false,
        });
        // Existing session protocol validates the actual ambient cookie owner
        // and fresh WebSocket token before this client can escape the factory.
        if let Err(error)=self.validate_session().await {
            self.forget_session(); return Err(error);
        }
        Ok(())
    }

    /// Restore an existing browser profile under the host's shared
    /// `openmates:auth-session-refresh` Web Lock. The worker owns the admitted
    /// master resource, including a legitimate nonextractable CryptoKey. Existing
    /// Cookie+key restore does not require optional remote association/enrollment;
    /// stronger persistence proof and backend compatibility remain separate.
    #[cfg(target_arch = "wasm32")]
    pub async fn browser_session(
        api_url: &str,
        app_origin: &str,
        session_id: &str,
        profile: BrowserProfileKey,
    ) -> Result<Self> {
        use wasm_bindgen::JsCast;
        let worker = js_sys::global()
            .dyn_into::<web_sys::DedicatedWorkerGlobalScope>()
            .map_err(|_| Error::Forbidden)?;
        if transport::validate_app_origin(&worker.location().origin())?
            != transport::validate_app_origin(app_origin)?
        {
            return Err(Error::Forbidden);
        }
        Self::restore_browser_credentials_inner(api_url,app_origin,session_id,profile).await
    }
    /// Local-only admission of the existing TS profile key, with no server call:
    /// exactly the state a network-unavailable `browser_session` restore builds
    /// (cached-profile reads only; no WebSocket token, capability, ACK or
    /// HTTP beyond `/v1/auth/session`/logout). Callers must still run the normal
    /// server-checked `browser_session` before any mutation, stream or socket.
    #[cfg(target_arch = "wasm32")]
    pub fn browser_session_local(
        api_url: &str,
        app_origin: &str,
        session_id: &str,
        profile: BrowserProfileKey,
    ) -> Result<Self> {
        use wasm_bindgen::JsCast;
        let worker = js_sys::global()
            .dyn_into::<web_sys::DedicatedWorkerGlobalScope>()
            .map_err(|_| Error::Forbidden)?;
        if transport::validate_app_origin(&worker.location().origin())?
            != transport::validate_app_origin(app_origin)?
        {
            return Err(Error::Forbidden);
        }
        Self::restore_browser_local_inner(api_url, app_origin, session_id, profile)
    }
    #[cfg(any(target_arch = "wasm32", test))]
    fn restore_browser_local_inner(
        api_url: &str,
        app_origin: &str,
        session_id: &str,
        profile: BrowserProfileKey,
    ) -> Result<Self> {
        let client =
            Self::prepare_browser_restore_client(api_url, app_origin, session_id, &profile)?;
        Self::admit_browser_restore_client(client, session_id, profile, None)
    }
    #[cfg(any(target_arch = "wasm32", test))]
    async fn restore_browser_credentials_inner(
        api_url: &str,
        app_origin: &str,
        session_id: &str,
        profile: BrowserProfileKey,
    ) -> Result<Self> {
        let mut client =
            Self::prepare_browser_restore_client(api_url, app_origin, session_id, &profile)?;
        let mut failure_status = None;
        let response = client
            .auth_session_request_observed(json!({"session_id":session_id}), &mut failure_status)
            .await;
        Self::finish_browser_restore_client(client, session_id, profile, response, failure_status)
    }
    #[cfg(any(target_arch="wasm32",test))]
    fn prepare_browser_restore_client(api_url:&str,app_origin:&str,session_id:&str,profile:&BrowserProfileKey)->Result<Self> {
        profile.current()?;
        uuid::Uuid::parse_str(session_id).map_err(|_| Error::Authentication)?;
        // Browser origin is actual host authority, not a forged request header.
        // The binding admits this only in its DedicatedWorker, never on the UI.
        let options = ClientOptions {
            app_url: Some(app_origin.into()),
            ..Default::default()
        };
        let mut client = Self::with_options(api_url, None, options)?;
        // Browser cookies are host scoped. Keep the validated first-party host
        // for both credentialed Fetch and derived WebSocket URLs; native client
        // construction retains its existing localhost-to-literal normalization.
        client.base = transport::validate_browser_base(api_url)?;
        client.browser_transport=true;
        client.browser_authority = Some(BrowserAuthority {
            principal: profile.principal.clone(),
            persistence: profile.persistence,
            owner_guards: false,
        });
        Ok(client)
    }
    #[cfg(any(target_arch="wasm32",test))]
    fn finish_browser_restore_client(mut client:Self,session_id:&str,mut profile:BrowserProfileKey,response:Result<Value>,failure_status:Option<u16>)->Result<Self> {
        profile.current()?;
        let server = match response {
            Ok(response) => {
                if !session_response::succeeded(&response)
                    || text(&response["user"], "id") != profile.principal
                {
                    profile.master.invalidate();
                    client.forget_session();
                    return Err(Error::Authentication);
                }
                let token=match session_response::websocket_token(&response) {
                    Ok(token)=>token.to_owned(),
                    Err(error)=>{profile.master.invalidate();client.forget_session();return Err(error);},
                };
                client.observe_browser_owner_guards(&response);
                Some((token, response["user"].clone()))
            }
            // Explicit local profile+key only. No server response, WebSocket
            // token, capability advertisement, complete cache or ACK minted.
            Err(error) if browser_restore_network_unavailable(error, failure_status) => None,
            Err(error) => {
                profile.master.invalidate();
                client.forget_session();
                return Err(error);
            }
        };
        Self::admit_browser_restore_client(client, session_id, profile, server)
    }
    /// `server` is the validated (WebSocket token, server user) pair; `None`
    /// admits the explicit local-read-only profile with no transport grant.
    #[cfg(any(target_arch = "wasm32", test))]
    fn admit_browser_restore_client(
        mut client: Self,
        session_id: &str,
        mut profile: BrowserProfileKey,
        server: Option<(String, Value)>,
    ) -> Result<Self> {
        profile.current()?;
        let local_read_only = server.is_none();
        let (token, server_user) = match server {
            Some((token, user)) => (Some(token), user),
            None => (None, json!({"id":profile.principal.as_str()})),
        };
        client.user = server_user;
        client.browser_local_read_only = local_read_only;
        client.browser_credentials = Some(credentials::BrowserCredentials {
            api_url: client.base.to_string().trim_end_matches('/').into(),
            session_id: session_id.into(),
            cookies: BTreeMap::new(),
            ws_token: token,
            master: profile.master.clone(),
            hashed_email: std::mem::take(&mut profile.hashed_email),
            user_email_salt: std::mem::take(&mut profile.user_email_salt),
            email_encryption_key: None,
            created_at: now_ms(),
            paired_session_expires_at: profile.paired_session_expires_at,
            active_team_id: None,
        });
        client.generation = client.generation.wrapping_add(1);
        client.credentials_changed();
        Ok(client)
    }
}

// Native monitor fixtures still use the same private authenticated restore;
// keep the production factory private and expose no additional SDK authority.
#[cfg(all(test, not(target_arch = "wasm32")))]
pub(super) async fn restore_monitor_test_profile(api_url:&str,app_origin:&str,session_id:&str,profile:BrowserProfileKey)->Result<Client> {
    Client::restore_browser_credentials_inner(api_url,app_origin,session_id,profile).await
}

#[cfg(all(test, not(target_arch = "wasm32")))]
mod tests {
    use super::*;
    const OWNER: &str = "11111111-1111-4111-8111-111111111111";
    const OTHER: &str = "22222222-2222-4222-8222-222222222222";
    fn profile() -> Session {
        Session {
            api_url: "http://127.0.0.1".into(),
            session_id: OWNER.into(),
            cookies: BTreeMap::new(),
            ws_token: Some("synthetic-token".into()),
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic-hash".into(),
            user_email_salt: "synthetic-salt".into(),
            email_encryption_key: None,
            created_at: now_ms(),
            paired_session_expires_at: None,
            active_team_id: None,
        }
    }
    fn browser_authority() -> BrowserAuthority {
        BrowserAuthority {
            principal: OWNER.into(),
            persistence: BrowserPersistence::MemoryOnly,
            owner_guards: false,
        }
    }
    pub(super) fn evidence(key: u8) -> BrowserProfileKey {
        BrowserProfileKey::from_existing_profile(
            OWNER,
            zeroize::Zeroizing::new([key; 32]),
            &crypto::hash_email("synthetic-a@example.invalid"),
            "synthetic-salt",
            BrowserPersistence::Persisted,
        ).unwrap()
    }
    fn account() -> Value {
        json!({"user_id":OWNER,"hashed_email":crypto::hash_email("synthetic-a@example.invalid"),
            "user_email_salt":"synthetic-salt",
            "encrypted_email_with_master_key":crypto::encrypt_bytes(b"synthetic-a@example.invalid", &[7;32]).unwrap()})
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn browser_account_proof_matches_server_identity_and_canonical_key() {
        let canonical = account();
        assert!(validate_browser_account_profile(&evidence(7), &canonical).is_ok());
        // A coherent local envelope can still derive A's hash under another key;
        // the canonical server envelope must reject that unrelated key.
        assert!(matches!(validate_browser_account_profile(&evidence(8), &canonical), Err(Error::Authentication)));
        for field in ["user_id", "hashed_email", "user_email_salt"] {
            for replacement in [Value::Null, json!("different"), json!(7)] {
                let mut changed = canonical.clone(); changed[field] = replacement;
                assert!(matches!(validate_browser_account_profile(&evidence(7), &changed), Err(Error::Authentication)));
            }
        }
        let mut changed = canonical;
        changed["encrypted_email_with_master_key"] = json!(crypto::encrypt_bytes(b"synthetic-b@example.invalid", &[7;32]).unwrap());
        assert!(matches!(validate_browser_account_profile(&evidence(7), &changed), Err(Error::Authentication)));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn browser_account_proof_accepts_existing_legacy_browser_ciphertext() {
        // Same immutable synthetic vector as the browser binding's local reader.
        let mut profile = evidence(7);
        profile.hashed_email = "HcPZoawjluHJY3h0YbECfh6IHEqFEsMrROvh/GosMi4=".into();
        let canonical = json!({"user_id":OWNER,"hashed_email":profile.hashed_email,
            "user_email_salt":"synthetic-salt",
            "encrypted_email_with_master_key":"AwMDAwMDAwMDAwMDVYzMZTNEO28cKTsoniWaTIhEgYLE+fFeRrDx0I+MJL/9zswusDIXve+TJj77LrY="});
        assert!(validate_browser_account_profile(&profile, &canonical).is_ok());
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn browser_account_proof_rejects_malformed_canonical_envelopes_without_fallback() {
        for encrypted in [json!(""), json!("invalid"), json!("x".repeat(8193)), json!(false),
            json!(crypto::encrypt_bytes(b"", &[7;32]).unwrap()),
            json!(crypto::encrypt_bytes(&[0xff], &[7;32]).unwrap())] {
            let mut changed = account(); changed["encrypted_email_with_master_key"] = encrypted;
            assert!(matches!(validate_browser_account_profile(&evidence(7), &changed), Err(Error::Authentication)));
        }
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn legacy_account_hash_matching_is_explicitly_not_key_ownership_proof() {
        for missing in [false, true] {
            let mut legacy = account();
            if missing { legacy.as_object_mut().unwrap().remove("encrypted_email_with_master_key"); }
            else { legacy["encrypted_email_with_master_key"] = Value::Null; }
            assert!(validate_browser_account_profile(&evidence(7), &legacy).is_ok());
            // Document the remaining boundary instead of claiming key proof.
            assert!(validate_browser_account_profile(&evidence(8), &legacy).is_ok());
            legacy["hashed_email"] = json!("different");
            assert!(validate_browser_account_profile(&evidence(7), &legacy).is_err());
        }
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn stronger_browser_account_proof_reads_existing_route_when_explicit() {
        let (url, peer) = server(account()).await;
        let mut client = Client::new(&url, None).unwrap();
        client.browser_authority = Some(browser_authority());
        crate::platform::time::timeout(Duration::from_secs(3), client.verify_browser_account_profile(&evidence(7)))
            .await.unwrap().unwrap();
        assert!(client.session.is_none());
        let request = crate::platform::time::timeout(Duration::from_secs(3), peer).await.unwrap().unwrap();
        assert!(request.starts_with("GET /v1/auth/pair/v2/account-check "));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn ordinary_stored_key_restore_does_not_require_remote_email_association() {
        let (url,peer)=server(json!({"success":true,"user":{"id":OWNER},"ws_token":"synthetic-websocket-token"})).await;
        let client=Client::restore_browser_credentials_inner(&url,"https://app.example.invalid","66666666-6666-4666-8666-666666666666",evidence(7)).await.unwrap();
        let request=peer.await.unwrap();assert!(request.starts_with("POST /v1/auth/session "));assert!(!request.contains("account-check"));
        assert_eq!(client.browser_session_status().unwrap().principal(),OWNER);
        assert!(client.session.is_none());assert!(client.session().is_none());assert!(client.credential_snapshot().is_none());assert_eq!(client.credential_ack,0);
        // Ordinary profile restore succeeds while unsupported strong transport/
        // persistence consistency remains an explicit backend activation gate.
        assert!(matches!(client.require_browser_owner_guards(),Err(Error::Unavailable{..})));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn profile_import_refuses_missing_owner_and_metadata_before_authentication() {
        for (owner, hash, salt) in [
            ("", "hash", "salt"),
            (OWNER, "", "salt"),
            (OWNER, "hash", ""),
        ] {
            assert!(
                BrowserProfileKey::from_existing_profile(
                    owner,
                    zeroize::Zeroizing::new([7; 32]),
                    hash,
                    salt,
                    BrowserPersistence::Persisted
                )
                .is_err()
            );
        }
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn browser_authority_never_projects_native_credentials_and_native_exports_are_unchanged() {
        let mut client = Client::new("http://127.0.0.1", Some(profile())).unwrap();
        assert!(client.session().is_some());
        assert!(client.clone_session().is_some());
        assert!(client.credential_snapshot().is_some());
        client.browser_authority = Some(browser_authority());
        assert!(client.session().is_none());
        assert!(client.clone_session().is_none());
        assert!(client.take_session().is_none());
        assert!(client.credential_snapshot().is_none());
        assert_eq!(client.browser_session_status().unwrap().principal(), OWNER);
        client.forget_session();
        assert!(client.browser_session_status().is_none());
        assert!(client.session.is_none());
    }
    pub(super) async fn server(body: Value) -> (String, tokio::task::JoinHandle<String>) {
        server_with_status(body,200).await
    }
    pub(super) async fn server_with_status(body: Value, status:u16) -> (String, tokio::task::JoinHandle<String>) {
        server_raw_response(body.to_string(),status).await
    }
    pub(super) async fn server_raw_response(body:String,status:u16)->(String,tokio::task::JoinHandle<String>){
        let (url, peer) = server_raw_responses(vec![(body, status)]).await;
        let task = tokio::spawn(async move {
            let mut requests = peer.await.unwrap();
            assert_eq!(requests.len(), 1);
            requests.pop().unwrap()
        });
        (url, task)
    }
    pub(super) async fn server_raw_responses(responses:Vec<(String,u16)>)->(String,tokio::task::JoinHandle<Vec<String>>){
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let task = tokio::spawn(async move {
            let mut requests = Vec::new();
            for (body, status) in responses {
                let (mut stream, _) = listener.accept().await.unwrap();
                let mut bytes = Vec::new();
                loop {
                    let mut part = [0u8; 1024];
                    let size = stream.read(&mut part).await.unwrap();
                    assert!(size > 0);
                    bytes.extend_from_slice(&part[..size]);
                    if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                        let head = std::str::from_utf8(&bytes[..end]).unwrap();
                        let length = head
                            .lines()
                            .find_map(|line| {
                                line.to_lowercase()
                                    .strip_prefix("content-length:")
                                    .map(str::trim)
                                    .map(str::to_owned)
                            })
                            .map(|value| value.parse::<usize>().unwrap())
                            .unwrap_or(0);
                        if bytes.len() >= end + 4 + length {
                            break;
                        }
                    }
                    assert!(bytes.len() < 8192);
                }
                stream.write_all(format!("HTTP/1.1 {status} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",if status==200{"OK"}else{"Forbidden"}, body.len()).as_bytes()).await.unwrap();
                requests.push(String::from_utf8(bytes).unwrap());
            }
            requests
        });
        (url, task)
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn refresh_principal_change_clears_browser_authority_before_return() {
        let (url, peer) =
            server(json!({"success":true,"user":{"id":OTHER},"ws_token":"synthetic-new-token"}))
                .await;
        let mut session = profile();
        session.api_url = url.clone();
        let mut client = Client::new(&url, Some(session)).unwrap();
        client.browser_authority = Some(browser_authority());
        client.chats.insert(OWNER.into(), json!({"id":OWNER}));
        assert!(matches!(
            crate::platform::time::timeout(Duration::from_secs(3), client.validate_session())
                .await
                .unwrap(),
            Err(Error::Expired)
        ));
        assert!(
            client.browser_authority.is_none()
                && client.session.is_none()
                && client.chats.is_empty()
        );
        let request = crate::platform::time::timeout(Duration::from_secs(3), peer)
            .await
            .unwrap()
            .unwrap();
        assert!(request.starts_with("POST /v1/auth/session "));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn browser_logout_does_not_skip_cookie_managed_revocation_or_forge_cookie_header() {
        let (url, peer) = server_raw_responses(vec![
            (json!({"success":true,"user":{"id":OWNER},"ws_token":"synthetic-fresh-token",
                "client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]}).to_string(), 200),
            (json!({"success":true}).to_string(), 200),
        ]).await;
        let mut session = profile();
        session.api_url = url.clone();
        let mut client = Client::new(&url, Some(session)).unwrap();
        client.browser_authority = Some(browser_authority());
        assert!(client.require_browser_owner_guards().is_err());
        // Learn support from an actual fresh response, never a fabricated local grant.
        crate::platform::time::timeout(Duration::from_secs(3), client.validate_session())
            .await
            .unwrap()
            .unwrap();
        assert!(client.require_browser_owner_guards().is_ok());
        crate::platform::time::timeout(Duration::from_secs(3), client.logout())
            .await
            .unwrap()
            .unwrap();
        assert!(client.browser_authority.is_none() && client.session.is_none());
        let mut requests = crate::platform::time::timeout(Duration::from_secs(3), peer)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(requests.len(), 2);
        let admission = requests.remove(0);
        assert!(admission.starts_with("POST /v1/auth/session "));
        assert!(!admission.to_lowercase().contains("\r\ncookie:"));
        assert!(admission.to_lowercase().contains(&format!("x-openmates-expected-principal: {}", OWNER)));
        let request = requests.pop().unwrap();
        assert!(request.starts_with("POST /v1/auth/logout "));
        assert!(!request.to_lowercase().contains("\r\ncookie:"));
        assert!(request.to_lowercase().contains(&format!("x-openmates-expected-principal: {}", OWNER)));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn browser_requires_positive_complete_guard_advertisement_but_native_stays_compatible(){
        let mut c=Client::new("http://127.0.0.1",Some(profile())).unwrap();
        assert!(c.require_browser_owner_guards().is_ok());
        c.user=json!({"id":OWNER});assert_eq!(c.expected_request_principal().unwrap().as_deref(),Some(OWNER));
        c.browser_authority=Some(browser_authority());
        for response in [json!({}),json!({"client_security_capabilities":["expected-principal-v1"]}),json!({"client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1",null]})]{
            c.observe_browser_owner_guards(&response);
            assert!(matches!(c.require_browser_owner_guards(),Err(Error::Unavailable{code:"browser_owner_consistency_unsupported",..})));
        }
        c.observe_browser_owner_guards(&json!({"client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]}));
        assert!(c.require_browser_owner_guards().is_ok());assert!(c.credential_snapshot().is_none());assert_eq!(c.credential_ack,0);
        // A later old/partial response cannot retain a previous positive grant.
        c.observe_browser_owner_guards(&json!({}));assert!(c.require_browser_owner_guards().is_err());
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn old_server_cannot_open_browser_socket_before_unsupported_refusal(){
        let (url,request)=server(json!({"success":true,"user":{"id":OWNER},"ws_token":"synthetic"})).await;
        let mut session=profile();session.api_url=url.clone();let mut c=Client::new(&url,Some(session)).unwrap();
        c.browser_authority=Some(browser_authority());c.user=json!({"id":OWNER});
        let result=crate::platform::time::timeout(Duration::from_secs(3),c.passive_chat_monitor_socket()).await.unwrap();
        assert!(matches!(result,Err(Error::Unavailable{code:"browser_owner_consistency_unsupported",..})));
        let request=request.await.unwrap();assert!(request.starts_with("POST /v1/auth/session "));
        assert!(request.to_lowercase().contains(&format!("x-openmates-expected-principal: {}",OWNER)));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn old_server_browser_mutation_and_remote_logout_refuse_before_network(){
        let mut session=profile();session.api_url="http://127.0.0.1:9".into();
        let mut c=Client::new("http://127.0.0.1:9",Some(session)).unwrap();c.browser_authority=Some(browser_authority());c.user=json!({"id":OWNER});
        assert!(matches!(c.request(Method::POST,"/v1/projects",Some(json!({}))).await,Err(Error::Unavailable{code:"browser_owner_consistency_unsupported",..})));
        assert!(matches!(c.logout().await,Err(Error::Unavailable{code:"browser_owner_consistency_unsupported",..})));
        assert!(c.session.is_none());assert!(c.credential_snapshot().is_none());
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn canonical_native_owner_header_is_retained_on_explicit_logout(){
        let (url,request)=server(json!({"success":true})).await;
        let mut session=profile();session.api_url=url.clone();session.cookies.insert("auth_refresh_token".into(),"synthetic-owned-cookie".into());
        let mut c=Client::new(&url,Some(session)).unwrap();c.user=json!({"id":OWNER});c.logout().await.unwrap();
        let request=request.await.unwrap();assert!(request.starts_with("POST /v1/auth/logout "));
        assert!(request.to_lowercase().contains(&format!("x-openmates-expected-principal: {}",OWNER)));
        assert!(c.session.is_none());
    }

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn only_closed_expected_owner_denial_qualifies_for_context_revocation(){
        assert!(expected_principal_mismatch(br#"{"detail":{"error":"session_principal_mismatch"}}"#));
        for body in [br#"{"detail":"Forbidden"}"#.as_slice(),br#"{"detail":{"error":"session_principal_mismatch","owner":"private"}}"#.as_slice(),br#"{"detail":{"error":"other"}}"#.as_slice(),b"invalid".as_slice()]{assert!(!expected_principal_mismatch(body));}
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn matching_owner_denial_revokes_current_context_and_never_publishes_credentials(){
        for closed in [false,true]{
            let body=if closed{json!({"detail":{"error":"session_principal_mismatch"}})}else{json!({"detail":"Forbidden"})};
            let(url,peer)=server_with_status(body,403).await;let mut session=profile();session.api_url=url.clone();
            let mut c=Client::new(&url,Some(session)).unwrap();c.user=json!({"id":OWNER});c.browser_authority=Some(browser_authority());
            c.chats.insert(OWNER.into(),json!({"id":OWNER}));c.history.insert(OWNER.into(),vec![json!({"encrypted_content":"synthetic"})]);
            let operation=c.operation_cancel.clone();let(tx,mut events)=mpsc::unbounded_channel();c.set_credential_updates(tx);let _=events.try_recv();
            let result=c.request(Method::GET,"/v1/projects",None).await;
            assert_eq!(result.unwrap_err(),if closed{Error::Expired}else{Error::Forbidden});
            if closed{assert!(c.session.is_none()&&c.browser_authority.is_none()&&c.chats.is_empty()&&c.history.is_empty());assert!(operation.is_cancelled());assert!(matches!(events.try_recv(),Ok(CredentialEvent::Cleared{..})));}
            else{assert!(c.session.is_some()&&c.browser_authority.is_some());assert!(!operation.is_cancelled());}
            peer.await.unwrap();
        }
    }

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn failed_fresh_validation_cannot_retain_or_install_prior_browser_capability(){
        let caps=json!(["expected-principal-v1","ws-dual-principal-v1"]);
        let cases=[
            ("not-json".to_owned(),false),
            (json!({"success":true,"user":{"id":OWNER},"ws_token":"synthetic"}).to_string(),true),
            (json!({"success":true,"user":{"id":OWNER},"client_security_capabilities":caps}).to_string(),false),
        ];
        for (body,success) in cases{
            let(url,peer)=server_raw_response(body,200).await;
            let mut session=profile();session.api_url=url.clone();let mut c=Client::new(&url,Some(session)).unwrap();
            c.browser_authority=Some(browser_authority());c.browser_authority.as_mut().unwrap().owner_guards=true;c.user=json!({"id":OWNER});
            assert_eq!(c.validate_session().await.is_ok(),success);peer.await.unwrap();
            assert!(matches!(c.require_browser_owner_guards(),Err(Error::Unavailable{code:"browser_owner_consistency_unsupported",..})));
            // A mutable operation must refuse before another connection; the
            // existing old-server socket case proves the same transport gate.
            assert!(matches!(c.request(Method::POST,"/v1/projects",Some(json!({}))).await,Err(Error::Unavailable{..})));
        }
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn failed_fresh_transport_revokes_prior_browser_capability(){
        let mut session=profile();session.api_url="http://127.0.0.1:9".into();let mut c=Client::new("http://127.0.0.1:9",Some(session)).unwrap();
        c.browser_authority=Some(browser_authority());c.browser_authority.as_mut().unwrap().owner_guards=true;c.user=json!({"id":OWNER});
        assert!(c.validate_session().await.is_err());
        assert!(matches!(c.require_browser_owner_guards(),Err(Error::Unavailable{..})));
        assert!(matches!(c.request(Method::POST,"/v1/projects",Some(json!({}))).await,Err(Error::Unavailable{..})));
    }

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn pending_browser_password_transport_cannot_export_native_credentials() {
        let api="http://127.0.0.1:9";
        let mut session=profile();session.api_url=api.into();
        let mut c=Client::new(api,Some(session)).unwrap();
        c.browser_password_transport=true;
        assert!(c.browser_cookies());
        assert!(c.browser_session_status().is_none());
        assert!(c.session().is_none());assert!(c.clone_session().is_none());
        assert!(c.take_session().is_none());assert!(c.credential_snapshot().is_none());
        assert!(c.session.is_some());
        c.forget_session();
        assert!(c.browser_cookies()); // no fallback to manual-cookie mode after revocation
        assert!(c.browser_session_status().is_none());
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn fresh_password_uses_existing_wrapper_and_cookie_owner_session_without_email_envelope() {
        fresh_password_keeps_memory_only(None).await;
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn checked_server_cookie_preference_keeps_browser_keys_memory_only() {
        fresh_password_keeps_memory_only(Some(PasswordLoginOptions { stay_logged_in:true })).await;
    }
    async fn fresh_password_keeps_memory_only(options:Option<PasswordLoginOptions>) {
        let f:Value=serde_json::from_str(include_str!("../../tests/crypto_fixtures/account.json")).unwrap();
        let login=json!({"success":true,"user":{"id":OWNER,"credential_version":2,
            "user_email_salt":f["password_v2_salt"],"salt":f["password_v2_salt"],
            "encrypted_key":f["password_v2_wrapped_master"],"key_iv":f["iv"]}});
        let fresh=json!({"success":true,"user":{"id":OWNER},"ws_token":"synthetic-fresh",
            "client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]});
        let(url,peer)=server_raw_responses(vec![
            (json!({"user_email_salt":f["password_v2_salt"]}).to_string(),200),
            (json!({"nonce":f["nonce_v2"],"challenge_id":"synthetic"}).to_string(),200),
            (login.to_string(),200),(fresh.to_string(),200),
        ]).await;
        let mut c=Client::new(&url,None).unwrap();c.browser_password_transport=true;
        let sid="66666666-6666-4666-8666-666666666666";
        match options {
            Some(options)=>c.login_password_context_with_options(f["email"].as_str().unwrap(),f["password_v2"].as_str().unwrap(),None,Some(sid),options).await,
            None=>c.login_password_context(f["email"].as_str().unwrap(),f["password_v2"].as_str().unwrap(),None,Some(sid)).await,
        }.unwrap();
        assert!(c.browser_session_status().is_none());
        c.finish_browser_password_session().await.unwrap();
        let status=c.browser_session_status().unwrap();
        assert_eq!(status.principal(),OWNER);assert_eq!(status.persistence(),BrowserPersistence::MemoryOnly);
        assert!(c.cookies.is_empty());assert!(c.credential_snapshot().is_none());
        assert_eq!(c.require_credentials().unwrap().session_id.as_str(),sid);
        let requests=peer.await.unwrap();assert_eq!(requests.len(),4);
        for request in &requests {assert!(!request.to_lowercase().contains("\r\ncookie:"));}
        assert!(requests[0].starts_with("POST /v1/auth/lookup "));
        assert!(requests[1].contains(sid));assert!(requests[2].contains(f["login_proof_v2"].as_str().unwrap()));
        let login_body:Value=serde_json::from_str(requests[2].split("\r\n\r\n").nth(1).unwrap()).unwrap();
        assert_eq!(login_body["stay_logged_in"],json!(options.unwrap_or_default().stay_logged_in));
        assert!(requests[3].starts_with("POST /v1/auth/session "));
        assert!(requests[3].to_lowercase().contains(&format!("x-openmates-expected-principal: {}",OWNER)));
        // This native protocol peer proves shared sequencing, not actual Fetch credentials.
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn fresh_password_finalization_refuses_changed_cookie_owner_and_missing_token() {
        for response in [
            json!({"success":true,"user":{"id":"77777777-7777-4777-8777-777777777777"},"ws_token":"other"}),
            json!({"success":true,"user":{"id":OWNER}}),
        ] {
            let(url,peer)=server_raw_response(response.to_string(),200).await;
            let mut session=profile();session.api_url=url.clone();
            let mut c=Client::new(&url,Some(session)).unwrap();
            c.browser_password_transport=true;c.user=json!({"id":OWNER});c.cookies.clear();
            assert!(c.finish_browser_password_session().await.is_err());peer.await.unwrap();
            assert!(c.session.is_none());assert!(c.browser_session_status().is_none());
            assert!(c.credential_snapshot().is_none());
        }
    }

}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_local_restore_tests.rs"]
mod local_restore_tests;

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_local_read_glue_tests.rs"]
mod local_read_glue_tests;

#[cfg(test)]
#[path="browser_saved_json_tests.rs"]
mod saved_json_tests;

pub(crate) use cache_metadata::{BrowserRetainedMessageCache, BrowserRetainedMessageReadback};

pub use cache_metadata::BrowserCandidateFailures;

pub use cache_metadata::BrowserRetainedCachePublication;

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="completion_recovery/original_result_tests.rs"]
mod original_result_tests;

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="completion_recovery/owned_phase_tests.rs"]
pub(in crate::client) mod owned_recovery_phase_tests;

#[cfg(target_arch="wasm32")]
#[doc(hidden)]
pub use cache_metadata::{BrowserOriginalHintRecoveryCheckpointReadiness,BrowserOriginalHintRecoveryCheckpointRead,BrowserOriginalHintRecoveryCheckpointReadResult,BrowserOriginalHintRecoveryCheckpointNativeWrite,BrowserOriginalHintRecoveryCheckpointNativeWriteResult,BrowserOriginalHintRecoveryCheckpointReadbackCrypto,BrowserOriginalHintRecoveryCheckpointVerified,BrowserOriginalHintRecoveryCheckpointDurable};

#[path="browser_original_draft_bounds.rs"]
pub(in crate::client) mod original_draft_bounds;

#[cfg(target_arch="wasm32")]
#[doc(hidden)]
pub use cache_metadata::OriginalPhysicalDraftInventory;

#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use cache_metadata::{BrowserMetadataBootstrap,MetadataOpaqueStored,MetadataNativeIoTicket,close_native_metadata_io_only,CapturedInitialSyncStore,BoundInitialSyncStore,StartupMetadataStoreDriver,StartupMetadataStored,StartupMetadataNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use cache_metadata::{BrowserMetadataRecoveryFinalize,BrowserMetadataRecoveryLocalStored,BrowserMetadataRecoveryNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use cache_metadata::{BrowserMainMetadataStore,BrowserMainMetadataStored,BrowserMainMetadataNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use cache_metadata::{BrowserRecoveredReplyStore,BrowserRecoveredReplyControl,BrowserRecoveredReplyStored,BrowserRecoveredReplyNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use cache_metadata::{BrowserMainCodeEmbedStore,BrowserMainCodeEmbedControl,BrowserMainCodeEmbedStored,BrowserMainCodeEmbedNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(in crate::client) use cache_metadata::MetadataRecoveryPhysicalProof;
