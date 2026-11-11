#[path = "browser_recovery_port.rs"]
mod recovery_port;
pub use recovery_port::{BrowserRecoveryBootstrap,BrowserRecoveryRestoredClient,BrowserOriginalRecoveryPort,capture_original_recovery_bootstrap};
#[path = "browser_draft.rs"]
mod draft_operation;
pub use draft_operation::{BrowserDraftWriteHandle,BrowserDraftControlHandle,BrowserDraftPublicationHandle};
#[path = "browser_send.rs"]
mod send_operation;
pub use send_operation::{BrowserPreparedSend, BrowserSendTerminal, BrowserSendControl, BrowserSendEvents, BrowserOwnedPreparedSend,BrowserOwnedSendDriver,BrowserOwnedSendStep,BrowserOwnedSendResume};
use openmates_sdk::{Client, client::{BrowserPersistence, BrowserProfileKey, message_window::{ChatMessageWindow, MessageWindowDirection, MessageWindowOptions}}, crypto};
use wasm_bindgen::{JsCast, prelude::*};
use zeroize::Zeroizing;

fn worker_only() -> Result<(), JsValue> {
    js_sys::global().dyn_into::<web_sys::DedicatedWorkerGlobalScope>()
        .map(|_| ()).map_err(|_| JsValue::from_str("unavailable"))
}

fn prior_email_hash(encrypted_email: &str, master: &[u8; 32]) -> openmates_sdk::Result<Zeroizing<String>> {
    if encrypted_email.is_empty() || encrypted_email.len() > 8192 {
        return Err(openmates_sdk::Error::Authentication);
    }
    let plaintext = crypto::decrypt_bytes(encrypted_email, master)?;
    // Reject invalid UTF-8 rather than adopting TextDecoder replacement text as
    // a different identity. Valid browser TextEncoder plaintext is exact UTF-8.
    let email = std::str::from_utf8(&plaintext).map_err(|_| openmates_sdk::Error::Authentication)?;
    if email.is_empty() { return Err(openmates_sdk::Error::Authentication); }
    Ok(Zeroizing::new(crypto::hash_email(email)))
}

/// One-use fresh-login resource. It cannot be built from host JSON or a key label.
/// The caller closes its fresh Worker after take(), performs ordinary page IO,
/// then admits a NEW saved-read Worker from the resulting genuine profile.
#[wasm_bindgen]
pub struct BrowserOrdinaryLoginRetention{operation:openmates_sdk::client::BrowserOrdinaryKeyRetention,handle:String,generation:f64,principal:String}
#[wasm_bindgen]
impl BrowserOrdinaryLoginRetention{
 pub fn take(self,client:&BrowserCoreClient)->Result<JsValue,JsValue>{
  let status=client.status(&self.handle,self.generation)?;
  if status.principal()!=self.principal{return Err(JsValue::from_str("session_expired"));}
  let effect=self.operation.effect_json(&client.client).map_err(|_|JsValue::from_str("session_expired"))?;
  let key=self.operation.take_key(&client.client).map_err(|_|JsValue::from_str("session_expired"))?.dyn_into::<web_sys::CryptoKey>().map_err(|_|JsValue::from_str("unavailable"))?;
  super::browser_crypto::BrowserMasterCrypto::new(key.clone()).map_err(|_|JsValue::from_str("unavailable"))?;
  client.status(&self.handle,self.generation)?;
  let output=js_sys::Object::new();js_sys::Reflect::set(&output,&JsValue::from_str("effect"),&JsValue::from_str(&effect)).map_err(|_|JsValue::from_str("unavailable"))?;
  js_sys::Reflect::set(&output,&JsValue::from_str("key"),&key).map_err(|_|JsValue::from_str("unavailable"))?;Ok(output.into())
 }
}

/// Worker-local, one-use profile. No field getters, Debug or serialization.
#[wasm_bindgen]
pub struct PreparedBrowserProfile { profile: BrowserProfileKey }
#[cfg(feature="browser-metadata-prototype")]
#[path="browser_first_session_restore.rs"]
mod first_session_restore;
#[cfg(feature="browser-metadata-prototype")]
pub use first_session_restore::{BrowserPreparedFirstSession,BrowserFirstSessionControlHandle,BrowserFirstSessionReceiptHandle};

#[wasm_bindgen]
impl PreparedBrowserProfile {
    /// Explicit legacy-profile handoff. Unknown optional metadata never forces
    /// email decryption, enrollment, or reauthentication. This is not owner proof.
    pub fn from_existing_key(principal: &str, key: web_sys::CryptoKey,
        hashed_email: Option<String>, user_email_salt: Option<String>, persisted: bool,
    ) -> Result<PreparedBrowserProfile, JsValue> {
        use openmates_sdk::crypto::master::MasterCapability;
        worker_only()?;
        let port=super::browser_crypto::BrowserMasterCrypto::new(key).map_err(|_|JsValue::from_str("unavailable"))?;
        let master=MasterCapability::from_browser_port(std::rc::Rc::new(port));
        let persistence=if persisted {BrowserPersistence::Persisted}else{BrowserPersistence::MemoryOnly};
        let profile=BrowserProfileKey::from_existing_browser_profile(principal,master,
            hashed_email.as_deref().unwrap_or(""),user_email_salt.as_deref().unwrap_or(""),persistence)
            .map_err(|_|JsValue::from_str("unavailable"))?;
        Ok(Self {profile})
    }

    /// The thin Worker passes the existing structured-cloned CryptoKey itself.
    /// No export, persistence, wrapping or account authority is supplied by JS.
    pub async fn from_crypto_key(
        principal: &str, key: web_sys::CryptoKey, encrypted_email: &str,
        user_email_salt: &str, persisted: bool,
    ) -> Result<PreparedBrowserProfile, JsValue> {
        use openmates_sdk::crypto::master::MasterCapability;
        worker_only()?;
        if encrypted_email.is_empty() || encrypted_email.len() > 8192 {
            return Err(JsValue::from_str("reauthentication_required"));
        }
        let port = super::browser_crypto::BrowserMasterCrypto::new(key)
            .map_err(|_| JsValue::from_str("reauthentication_required"))?;
        let master = MasterCapability::from_browser_port(std::rc::Rc::new(port));
        let plaintext = master.decrypt_bytes(encrypted_email).await
            .map_err(|_| JsValue::from_str("reauthentication_required"))?;
        let email = std::str::from_utf8(&plaintext)
            .map_err(|_| JsValue::from_str("reauthentication_required"))?;
        if email.is_empty() { return Err(JsValue::from_str("reauthentication_required")); }
        let hashed_email = Zeroizing::new(crypto::hash_email(email));
        let persistence = if persisted { BrowserPersistence::Persisted } else { BrowserPersistence::MemoryOnly };
        let profile = BrowserProfileKey::from_existing_browser_profile(principal, master, &hashed_email,
            user_email_salt, persistence)
            .map_err(|_| JsValue::from_str("reauthentication_required"))?;
        Ok(Self { profile })
    }

    /// Synchronous copy into Zeroizing memory. The caller must erase the JS
    /// export buffer immediately on return, before any network await.
    pub fn from_bytes(
        principal: &str, raw: Vec<u8>, encrypted_email: &str, user_email_salt: &str,
        persisted: bool,
    ) -> Result<PreparedBrowserProfile, JsValue> {
        // Own and erase wasm-bindgen's WASM-memory transfer copy as well as the
        // retained fixed-size key; a borrowed slice would leave the copy behind.
        let raw = Zeroizing::new(raw);
        worker_only()?;
        if raw.len() != 32 { return Err(JsValue::from_str("reauthentication_required")); }
        let mut master = Zeroizing::new([0u8; 32]);
        master.copy_from_slice(&raw);
        // Legacy browser envelope is base64(12-byte IV || AES-GCM ciphertext
        // and tag), authenticated with this exact captured master key, no AAD.
        // SDK decrypt_bytes supports that envelope and owns zeroized plaintext.
        let hashed_email = prior_email_hash(encrypted_email, &master)
            .map_err(|_| JsValue::from_str("reauthentication_required"))?;
        let persistence = if persisted { BrowserPersistence::Persisted } else { BrowserPersistence::MemoryOnly };
        let profile = BrowserProfileKey::from_existing_profile(principal, master, &hashed_email,
            user_email_salt, persistence)
            .map_err(|_| JsValue::from_str("reauthentication_required"))?;
        Ok(Self { profile })
    }
}

// Projection bounds only: SDK owns owner scope, key resolution, decryption,
// one-page selection and plaintext interpretation. Oversize pages are refused whole.
const MAX_CHAT_MESSAGES: usize = 20;
const MAX_CHAT_UTF8_BYTES: usize = 256 * 1024;
async fn host_local_packet(request:String,host_effect:&js_sys::Function,guard:&impl Fn()->openmates_sdk::Result<()>)->openmates_sdk::Result<String>{
    guard()?;
    let invoked=host_effect.call1(&JsValue::UNDEFINED,&JsValue::from_str(&request)).map_err(|_|openmates_sdk::Error::Io)?;
    let value=wasm_bindgen_futures::JsFuture::from(js_sys::Promise::resolve(&invoked)).await;
    let value=value.map_err(|_|openmates_sdk::Error::Io).and_then(|value|value.as_string().map(Zeroizing::new).ok_or(openmates_sdk::Error::Protocol));
    guard()?;let mut value=value?;if value.len()>MAX_CHAT_UTF8_BYTES{return Err(openmates_sdk::Error::Protocol);}
    Ok(std::mem::take(&mut *value))
}
/// Fixed error-variant name only (never content) for a cache-first miss, so a
/// miss that falls back to the server read stays diagnosable in the Worker log.
fn log_cached_view_miss(error: &openmates_sdk::Error) {
    use openmates_sdk::Error as E;
    let code = match error {
        E::Invalid(_) => "invalid",
        E::Crypto => "crypto",
        E::Authentication => "authentication",
        E::Unavailable { .. } => "unavailable",
        E::Locked => "locked",
        E::Offline => "offline",
        E::Forbidden => "forbidden",
        E::Expired => "expired",
        E::Cancelled => "cancelled",
        E::Io => "io",
        E::Protocol => "protocol",
        E::Conflict => "conflict",
        _ => "other",
    };
    let console = js_sys::Reflect::get(&js_sys::global(), &JsValue::from_str("console")).ok();
    let info = console
        .as_ref()
        .and_then(|c| js_sys::Reflect::get(c, &JsValue::from_str("info")).ok())
        .and_then(|f| f.dyn_into::<js_sys::Function>().ok());
    if let (Some(console), Some(info)) = (console, info) {
        let _ = info.call2(
            &console,
            &JsValue::from_str("[RustCore] online cached view miss:"),
            &JsValue::from_str(code),
        );
    }
}
fn saved_page_options(selector_json:&str)->Result<openmates_sdk::client::saved_chat_read::SavedChatReadOptions,JsValue>{
    use openmates_sdk::client::saved_chat_read::{SavedChatContentMode,SavedChatReadOptions};
    if selector_json.len()>2048{return Err(JsValue::from_str("invalid_request"));}
    let selector:MessageWindowOptions=serde_json::from_str(selector_json).map_err(|_|JsValue::from_str("invalid_request"))?;
    if !(1..=MAX_CHAT_MESSAGES).contains(&selector.limit)
        ||matches!(selector.direction,MessageWindowDirection::Before|MessageWindowDirection::After)!=selector.cursor.is_some()
        ||(selector.direction==MessageWindowDirection::Around)!=selector.anchor_message_id.is_some(){return Err(JsValue::from_str("invalid_request"));}
    Ok(SavedChatReadOptions{limit:selector.limit,max_pages:1,content_mode:SavedChatContentMode::PageLocal,
        before:if selector.direction==MessageWindowDirection::Before{selector.cursor.clone()}else{None},
        after:if selector.direction==MessageWindowDirection::After{selector.cursor.clone()}else{None},
        anchor_message_id:selector.anchor_message_id,respect_compression_boundary:selector.respect_compression_boundary,..Default::default()})
}
fn chat_projection_allowed(chat: &openmates_sdk::model::Chat) -> bool {
    uuid::Uuid::parse_str(&chat.id).is_ok() && chat.title.len() <= 4096
        && !chat.messages.is_empty() && chat.messages.len() <= MAX_CHAT_MESSAGES
        && chat.messages.iter().all(|message| openmates_sdk::client::message_window::valid_message_id(&message.id)
            && !message.role.is_empty() && message.role.len() <= 32 && message.content.len() <= 64 * 1024)
        && chat.messages.iter().map(|message| message.id.len() + message.role.len() + message.content.len())
            .sum::<usize>() + chat.id.len() + chat.title.len() + 8192 <= MAX_CHAT_UTF8_BYTES
}
fn chat_projection(window: ChatMessageWindow) -> Result<JsValue, JsValue> {
    // A viewing page is never a complete-history/cache replacement, even when
    // terminal. Rust owns page-local PII restoration; omitted mappings stay literal.
    if window.history_complete || window.pii_restoration != "page_local" {
        return Err(JsValue::from_str("chat_unavailable"));
    }
    let chat = window.chat;
    if !chat_projection_allowed(&chat) { return Err(JsValue::from_str("chat_unavailable")); }
    let object = js_sys::Object::new();
    let set = |object: &js_sys::Object, key: &str, value: &JsValue| {
        js_sys::Reflect::set(object, &JsValue::from_str(key), value)
            .map(|_| ()).map_err(|_| JsValue::from_str("chat_unavailable"))
    };
    set(&object, "id", &JsValue::from_str(&chat.id))?;
    set(&object, "title", &JsValue::from_str(&chat.title))?;
    let messages = js_sys::Array::new();
    for message in chat.messages {
        let row = js_sys::Object::new();
        set(&row, "id", &JsValue::from_str(&message.id))?;
        set(&row, "role", &JsValue::from_str(&message.role))?;
        set(&row, "content", &JsValue::from_str(&message.content))?;
        messages.push(&row);
    }
    set(&object, "messages", &messages)?;
    set(&object, "historyComplete", &JsValue::FALSE)?;
    set(&object, "piiRestoration", &JsValue::from_str("page_local"))?;
    set(&object, "hasMoreBefore", &JsValue::from_bool(window.has_more_before))?;
    set(&object, "hasMoreAfter", &JsValue::from_bool(window.has_more_after))?;
    Ok(object.into())
}

/// Deliberately carries only a handle and non-secret SDK-authoritative status.
#[wasm_bindgen]
pub struct BrowserCoreStatus {
    handle: String,
    principal: String,
    generation: f64,
    persisted: bool,
    local_read_only: bool,
}
#[wasm_bindgen]
impl BrowserCoreStatus {
    #[wasm_bindgen(getter)] pub fn handle(&self) -> String { self.handle.clone() }
    #[wasm_bindgen(getter)] pub fn principal(&self) -> String { self.principal.clone() }
    #[wasm_bindgen(getter)] pub fn generation(&self) -> f64 { self.generation }
    #[wasm_bindgen(getter)] pub fn persisted(&self) -> bool { self.persisted }
    #[wasm_bindgen(getter)] pub fn local_read_only(&self) -> bool { self.local_read_only }
}

#[wasm_bindgen]
pub struct BrowserCoreClient { client: Client, handle: String, cache:cache_operations::BrowserCacheSession,
    #[cfg(feature="browser-metadata-prototype")]
    initial_sync_store:Option<openmates_sdk::client::BoundInitialSyncStore>,
}

#[wasm_bindgen]
impl BrowserCoreClient {
    /// CI/inactive fresh-login seam. Password is owned and wiped in WASM;
    /// no key/session getters or host persistence acknowledgement are exposed.
    pub async fn login_password(api_url: &str, app_origin: &str, session_id: &str,
        email: &str, password: String, tfa: Option<String>, stay_logged_in: Option<bool>) -> Result<BrowserCoreClient, JsValue> {
        let password=Zeroizing::new(password);
        let tfa=tfa.map(Zeroizing::new);
        worker_only()?;
        if email.len()>512 || password.len()>16*1024 || tfa.as_ref().is_some_and(|v|v.len()>128) {
            return Err(JsValue::from_str("authentication_failed"));
        }
        let client=Client::browser_password_session_with_options(api_url,app_origin,session_id,email,
            password.as_str(),tfa.as_ref().map(|v|v.as_str()),
            openmates_sdk::PasswordLoginOptions { stay_logged_in:stay_logged_in.unwrap_or(false) }).await
            .map_err(|error| JsValue::from_str(match error {
                openmates_sdk::Error::TwoFactorRequired => "two_factor_required",
                _ => "authentication_failed",
            }))?;
        Ok(Self {client,handle:uuid::Uuid::new_v4().to_string(),cache:Default::default(),#[cfg(feature="browser-metadata-prototype")] initial_sync_store:None})
    }

    /// Inactive ordinary retention preparation after genuine password admission.
    /// Existing restore stays nonmutating; no strong persistence ACK is exposed.
    pub async fn prepare_ordinary_login_retention(&self,handle:&str,generation:f64,stay_logged_in:bool,lifecycle_generation:f64)->Result<BrowserOrdinaryLoginRetention,JsValue>{
      let status=self.status(handle,generation)?;
      if !lifecycle_generation.is_finite()||lifecycle_generation.fract()!=0.0||lifecycle_generation<1.0||lifecycle_generation>9_007_199_254_740_991.0{return Err(JsValue::from_str("invalid_request"));}
      let operation=self.client.prepare_browser_ordinary_key_retention(stay_logged_in,lifecycle_generation as u64).await.map_err(|error|JsValue::from_str(match error{
        openmates_sdk::Error::Cancelled|openmates_sdk::Error::Expired|openmates_sdk::Error::Forbidden|openmates_sdk::Error::Authentication=>"session_expired",_=>"unavailable"}))?;
      self.status(handle,generation)?;
      Ok(BrowserOrdinaryLoginRetention{operation,handle:handle.into(),generation,principal:status.principal()})
    }

    pub async fn restore(api_url: &str, app_origin: &str, session_id: &str,
        prepared: PreparedBrowserProfile) -> Result<BrowserCoreClient, JsValue> {
        worker_only()?;
        let client = Client::browser_session(api_url, app_origin, session_id, prepared.profile)
            .await.map_err(|_| JsValue::from_str("reauthentication_required"))?;
        Ok(Self { client, handle: uuid::Uuid::new_v4().to_string(),cache:Default::default(),#[cfg(feature="browser-metadata-prototype")] initial_sync_store:None })
    }

    /// Local-only admission of the existing key (no server call): cached-profile
    /// reads only. The Worker later runs `restore` on the same Worker as the
    /// server check, which replaces (and frees) this client.
    pub fn restore_local(
        api_url: &str,
        app_origin: &str,
        session_id: &str,
        prepared: PreparedBrowserProfile,
    ) -> Result<BrowserCoreClient, JsValue> {
        worker_only()?;
        let client =
            Client::browser_session_local(api_url, app_origin, session_id, prepared.profile)
                .map_err(|_| JsValue::from_str("unavailable"))?;
        if !client
            .browser_session_status()
            .is_some_and(|status| status.is_local_read_only())
        {
            return Err(JsValue::from_str("unavailable"));
        }
        Ok(Self {
            client,
            handle: uuid::Uuid::new_v4().to_string(),
            cache: Default::default(),
            #[cfg(feature = "browser-metadata-prototype")]
            initial_sync_store: None,
        })
    }

    pub fn status(&self, handle: &str, generation: f64) -> Result<BrowserCoreStatus, JsValue> {
        worker_only()?;
        let status = self.client.browser_session_status().ok_or_else(|| JsValue::from_str("session_expired"))?;
        // JS cannot exactly represent arbitrary u64 generations. Refuse rather
        // than aliasing a stale session handle through numeric rounding.
        if status.generation() > 9_007_199_254_740_991 || handle != self.handle
            || generation != status.generation() as f64 {
            return Err(JsValue::from_str("session_expired"));
        }
        Ok(BrowserCoreStatus { handle: self.handle.clone(), principal: status.principal().into(),
            generation, persisted: status.persistence() == BrowserPersistence::Persisted, local_read_only:status.is_local_read_only() })
    }

    /// First authoritative status; there is no caller-supplied owner/generation.
    pub fn admitted_status(&self) -> Result<BrowserCoreStatus, JsValue> {
        let status = self.client.browser_session_status().ok_or_else(|| JsValue::from_str("session_expired"))?;
        self.status(&self.handle, status.generation() as f64)
    }

    /// Existing owned Worker resource, with Rust issuing bounded platform reads.
    /// The callback receives selectors only; it cannot enroll/export a master key.
    pub async fn read_local_saved_chat_cursor(&self, handle:&str, generation:f64,
        expected_principal:&str, chat_id:&str, selector_json:&str, host_effect:js_sys::Function) -> Result<String,JsValue> {
        let guard=|| -> openmates_sdk::Result<()> {
            let status=self.status(handle,generation).map_err(|_|openmates_sdk::Error::Cancelled)?;
            if !status.local_read_only||status.principal!=expected_principal||status.persisted{return Err(openmates_sdk::Error::Forbidden);}
            Ok(())
        };
        guard().map_err(|_|JsValue::from_str("session_expired"))?;
        let options=saved_page_options(selector_json)?;
        let result=self.client.browser_local_saved_chat_read_with_io_json(expected_principal,chat_id,options,|request|{
            host_local_packet(request,&host_effect,&guard)
        }).await;
        guard().map_err(|_|JsValue::from_str("session_expired"))?;
        let mut encoded=result.map_err(|error|JsValue::from_str(match error {
            openmates_sdk::Error::Cancelled|openmates_sdk::Error::Expired|openmates_sdk::Error::Authentication|openmates_sdk::Error::Forbidden=>"session_expired",
            _=>"chat_unavailable",
        }))?;
        guard().map_err(|_|JsValue::from_str("session_expired"))?;
        Ok(std::mem::take(&mut *encoded))
    }

    /// Online-session render of the existing retained IndexedDB rows (readonly
    /// plans, same shared local saved-read helper). The caller reconciles with
    /// the server separately; this confers no freshness, write or server IO.
    pub async fn read_online_cached_saved_chat(
        &self,
        handle: &str,
        generation: f64,
        expected_principal: &str,
        chat_id: &str,
        selector_json: &str,
        host_effect: js_sys::Function,
    ) -> Result<String, JsValue> {
        let guard = || -> openmates_sdk::Result<()> {
            let status = self
                .status(handle, generation)
                .map_err(|_| openmates_sdk::Error::Cancelled)?;
            if status.local_read_only || status.principal != expected_principal {
                return Err(openmates_sdk::Error::Forbidden);
            }
            Ok(())
        };
        guard().map_err(|_| JsValue::from_str("session_expired"))?;
        let options = saved_page_options(selector_json)?;
        let result = self
            .client
            .browser_online_cached_saved_chat_read_with_io_json(
                expected_principal,
                chat_id,
                options,
                |request| host_local_packet(request, &host_effect, &guard),
            )
            .await;
        if let Err(error) = &result {
            log_cached_view_miss(error);
        }
        guard().map_err(|_| JsValue::from_str("session_expired"))?;
        let mut encoded = result.map_err(|error| {
            JsValue::from_str(match error {
                openmates_sdk::Error::Cancelled
                | openmates_sdk::Error::Expired
                | openmates_sdk::Error::Authentication
                | openmates_sdk::Error::Forbidden => "session_expired",
                _ => "chat_unavailable",
            })
        })?;
        guard().map_err(|_| JsValue::from_str("session_expired"))?;
        Ok(std::mem::take(&mut *encoded))
    }

    /// Exact retained checkpoint presentation; the callback executes only the
    /// existing bounded metadata plan. No key export, PII lookup or remote read.
    /// Exact retained checkpoint presentation; the callback executes only the
    /// existing bounded metadata plan. No key export, PII lookup or remote read.
    pub async fn read_local_checkpoint_summary(&self,handle:&str,generation:f64,expected_principal:&str,chat_id:&str,checkpoint_id:&str,host_effect:js_sys::Function)->Result<String,JsValue>{
        let guard=|| -> openmates_sdk::Result<()> {
            let status=self.status(handle,generation).map_err(|_|openmates_sdk::Error::Cancelled)?;
            if !status.local_read_only||status.principal!=expected_principal||status.persisted{return Err(openmates_sdk::Error::Forbidden);}Ok(())
        };
        guard().map_err(|_|JsValue::from_str("session_expired"))?;
        let result=self.client.browser_local_checkpoint_summary_with_io_json(expected_principal,chat_id,checkpoint_id,|request|host_local_packet(request,&host_effect,&guard)).await;
        guard().map_err(|_|JsValue::from_str("session_expired"))?;
        let mut encoded=result.map_err(|error|JsValue::from_str(match error{
            openmates_sdk::Error::Cancelled|openmates_sdk::Error::Expired|openmates_sdk::Error::Authentication|openmates_sdk::Error::Forbidden=>"session_expired",_=>"chat_unavailable"}))?;
        Ok(std::mem::take(&mut *encoded))
    }

    /// Inactive explicit local-row bridge. No IDB IO or remote fallback occurs.
    pub async fn read_local_chat(&self, handle: &str, generation: f64,
        expected_principal: &str, chat_id: &str, encrypted_rows_json: &str,
        saved: bool) -> Result<String, JsValue> {
        let status = self.status(handle, generation)?;
        if !status.local_read_only || status.principal != expected_principal {
            return Err(JsValue::from_str("chat_unavailable"));
        }
        let mut encoded = if saved {
            use openmates_sdk::client::saved_chat_read::{SavedChatContentMode, SavedChatReadOptions};
            self.client.browser_local_saved_chat_read_json(expected_principal, chat_id,
                SavedChatReadOptions { limit: MAX_CHAT_MESSAGES, max_pages: 1,
                    content_mode: SavedChatContentMode::PageLocal, ..Default::default() }, encrypted_rows_json).await
        } else {
            self.client.browser_local_message_window_json(expected_principal, chat_id,
                MessageWindowOptions::default(), encrypted_rows_json).await
        }.map_err(|_| JsValue::from_str("chat_unavailable"))?;
        let current = self.status(handle, generation)?;
        if !current.local_read_only || current.principal != expected_principal {
            return Err(JsValue::from_str("chat_unavailable"));
        }
        // Ownership is released once, immediately to wasm-bindgen's return copy.
        Ok(std::mem::take(&mut *encoded))
    }

    /// One shared SDK latest viewing page, in the owning admitted Worker only.
    /// Caller IDs select a resource; they do not grant owner/key/session authority.
    pub async fn open_chat(&mut self, handle: &str, generation: f64, chat_id: &str) -> Result<JsValue, JsValue> {
        self.status(handle, generation)?;
        uuid::Uuid::parse_str(chat_id).map_err(|_| JsValue::from_str("chat_unavailable"))?;
        let window = self.client.chat_message_window(chat_id, MessageWindowOptions {
            direction: MessageWindowDirection::Latest, limit: MAX_CHAT_MESSAGES,
            ..MessageWindowOptions::default()
        }).await
            .map_err(|_| JsValue::from_str("chat_unavailable"))?;
        // Fresh network work must never publish into a replaced/expired admission.
        self.status(handle, generation)?;
        if window.chat.id != chat_id { return Err(JsValue::from_str("chat_unavailable")); }
        chat_projection(window)
    }

    /// One read-only passive WebSocket reconnection followed by a fresh bounded
    /// selected page. This is neither a complete sync nor durable publication.
    /// No send, recovery claim, cache replacement or host persistence is invoked.
    pub async fn reconnect_chat(&mut self, handle: &str, generation: f64, chat_id: &str) -> Result<JsValue, JsValue> {
        self.status(handle, generation)?;
        uuid::Uuid::parse_str(chat_id).map_err(|_| JsValue::from_str("chat_unavailable"))?;
        let cancel = tokio_util::sync::CancellationToken::new();
        let (errors, _errors) = tokio::sync::mpsc::channel(1);
        // ChatMonitor owns cancellation and closes on every return/error/drop.
        // Shared Rust selects the passive/no-recovery/no-active-chat socket mode.
        let monitor = self.client.start_chat_monitor(cancel, errors).await
            .map_err(|_| JsValue::from_str("session_expired"))?;
        self.client.validate_chat_monitor(&monitor).await
            .map_err(|_| JsValue::from_str("session_expired"))?;
        self.status(handle, generation)?;
        let window = self.client.chat_message_window(chat_id, MessageWindowOptions {
            direction: MessageWindowDirection::Latest, limit: MAX_CHAT_MESSAGES,
            ..MessageWindowOptions::default()
        }).await.map_err(|_| JsValue::from_str("chat_unavailable"))?;
        self.client.validate_chat_monitor(&monitor).await
            .map_err(|_| JsValue::from_str("session_expired"))?;
        self.status(handle, generation)?;
        if window.chat.id != chat_id { return Err(JsValue::from_str("chat_unavailable")); }
        monitor.close();
        chat_projection(window)
    }

    /// One bounded rich saved-chat view. All metadata/decryption stays in the
    /// shared SDK; JSON carries its closed public DTO, never native authority.
    pub async fn read_saved_chat(&mut self,handle:&str,generation:f64,chat_id:&str)->Result<String,JsValue>{
        self.read_saved_chat_page(handle,generation,chat_id,"{\"direction\":\"latest\"}").await
    }
    /// Browser selectors only; the existing shared operation owns all paging,
    /// canonical permission, denial, metadata, crypto and page-local PII policy.
    pub async fn read_saved_chat_page(&mut self,handle:&str,generation:f64,chat_id:&str,selector_json:&str)->Result<String,JsValue>{
        let status=self.status(handle,generation)?;
        if status.local_read_only{return Err(JsValue::from_str("chat_unavailable"));}
        let options=saved_page_options(selector_json)?;
        let result=self.client.browser_saved_chat_read_json(&status.principal,chat_id,options).await;
        let current=self.status(handle,generation);
        // Preserve the existing saved-read error contract; the SDK retains
        // denial/transport distinctions and every success is already guarded.
        let mut encoded=result.map_err(|_|JsValue::from_str("chat_unavailable"))?;
        current?;self.status(handle,generation)?;
        Ok(std::mem::take(&mut *encoded))
    }

    /// Prepare a separately callable cancellation/event handle before entering
    /// the mutable async Client lane. No network or turn admission occurs here.
    pub fn prepare_send(&self, handle: &str, generation: f64, chat_id: &str) -> Result<BrowserPreparedSend, JsValue> {
        let status = self.status(handle, generation)?;
        uuid::Uuid::parse_str(chat_id).map_err(|_| JsValue::from_str("chat_unavailable"))?;
        let prepared=self.client.prepare_scoped_saved_send(Some(chat_id),tokio_util::sync::CancellationToken::new())
            .map_err(|_|JsValue::from_str("session_expired"))?;
        Ok(send_operation::prepare(handle, generation, &status.principal, chat_id,prepared))
    }

    /// Existing saved-chat foreground send; shared Rust owns all encrypted
    /// admission, stream, cancellation and canonical server persistence policy.
    /// No browser credential/cache receipt is fabricated or acknowledged.
    pub async fn send_saved(&mut self, handle: &str, generation: f64,
        mut prepared: BrowserPreparedSend, text: &str) -> Result<BrowserSendTerminal, JsValue> {
        let status = self.status(handle, generation)?;
        prepared.check_client(handle, generation, &status.principal)?;
        if text.trim().is_empty() || text.len() > 8192 { return Err(JsValue::from_str("invalid_request")); }
        let sender=prepared.take_sender()?;
        let original=prepared.take_prepared()?;
        let terminal=self.client.run_prepared_saved_send(original,text,sender).await
            .map_err(|_|JsValue::from_str("session_expired"))?;
        Ok(prepared.terminal(terminal))
    }
    /// Called only after the original mutable WASM future released its borrow.
    /// Consumes the exact Rust terminal before any session reuse/publication.
    pub fn finish_send(&mut self,handle:&str,generation:f64,mut terminal:BrowserSendTerminal)->Result<String,JsValue>{
        let status=self.status(handle,generation)?;
        let original=terminal.take(handle,generation,&status.principal)?;
        let disposition=self.client.take_scoped_saved_send_terminal(original)
            .map_err(|_|JsValue::from_str("session_expired"))?;
        disposition.check_current(&self.client).map_err(|_|JsValue::from_str("session_expired"))?;
        let receipt=terminal.publish(&disposition)?;
        disposition.check_current(&self.client).map_err(|_|JsValue::from_str("session_expired"))?;
        Ok(receipt)
    }

    /// New opt-in ownership path; old methods remain the compatibility surface.
    pub fn prepare_owned_send(&self,handle:&str,generation:f64,chat_id:&str)->Result<BrowserOwnedPreparedSend,JsValue>{
        let status=self.status(handle,generation)?;
        uuid::Uuid::parse_str(chat_id).map_err(|_|JsValue::from_str("chat_unavailable"))?;
        let prepared=self.client.prepare_owned_saved_send(Some(chat_id),tokio_util::sync::CancellationToken::new()).map_err(|_|JsValue::from_str("session_expired"))?;
        send_operation::prepare_owned(handle,generation,&status.principal,chat_id,prepared)
    }
    pub fn start_owned_send(&mut self,handle:&str,generation:f64,mut prepared:BrowserOwnedPreparedSend,text:&str)->Result<BrowserOwnedSendDriver,JsValue>{
        let status=self.status(handle,generation)?;
        if text.trim().is_empty()||text.len()>8192{return Err(JsValue::from_str("invalid_request"))}
        prepared.start(&mut self.client,handle,generation,&status.principal,text)
    }
    pub async fn apply_owned_send(&mut self,handle:&str,generation:f64,mut step:BrowserOwnedSendStep)->Result<BrowserOwnedSendResume,JsValue>{
        let status=self.status(handle,generation)?;
        let result=step.apply(&mut self.client,handle,generation,&status.principal).await;
        self.status(handle,generation)?;result
    }
    pub fn finish_owned_send(&mut self,handle:&str,generation:f64,mut step:BrowserOwnedSendStep)->Result<String,JsValue>{
        let status=self.status(handle,generation)?;
        let receipt=step.finish(&mut self.client,handle,generation,&status.principal)?;
        self.status(handle,generation)?;Ok(receipt)
    }

    /// Browser-only encrypted host preparation, never native Session or ACK.
    pub async fn prepare_credentials(&mut self, handle: &str, generation: f64) -> Result<String, JsValue> {
        self.status(handle,generation)?;
        let snapshot=self.client.prepare_browser_credential_snapshot().await.map_err(|_|JsValue::from_str("reauthentication_required"))?;
        self.status(handle,generation)?;
        serde_json::to_string(&snapshot).map_err(|_|JsValue::from_str("unavailable"))
    }
    pub async fn validate_credentials(&self, handle: &str, generation: f64, encoded: &str) -> Result<String, JsValue> {
        self.status(handle,generation)?;
        if encoded.len()>16*1024 { return Err(JsValue::from_str("invalid_request")); }
        let snapshot:openmates_sdk::client::BrowserSealedCredentials=serde_json::from_str(encoded).map_err(|_|JsValue::from_str("invalid_request"))?;
        self.client.validate_browser_credential_snapshot_async(&snapshot).await.map_err(|_|JsValue::from_str("session_expired"))?;
        self.status(handle,generation)?;
        serde_json::to_string(&snapshot).map_err(|_|JsValue::from_str("unavailable"))
    }

    /// Dedicated inactive CAS lane. Worker owns one inherited platform lease;
    /// this Rust driver owns all sequencing and secret/predecessor decisions.
    pub async fn rotate_credentials(&mut self,handle:&str,generation:f64,scope_json:&str,host_effect:js_sys::Function)->Result<String,JsValue>{
        self.status(handle,generation)?;
        if scope_json.len()>1024{return Err(JsValue::from_str("invalid_request"));}
        let scope:openmates_sdk::client::BrowserCredentialCasScope=serde_json::from_str(scope_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let operation=self.client.begin_browser_credential_cas(scope).map_err(|_|JsValue::from_str("session_expired"))?;
        let read=credential_cas_effect(&host_effect,&operation.read_effect()).await?;
        self.status(handle,generation)?;
        let prepared=self.client.prepare_browser_credential_cas(operation,read).await.map_err(|_|JsValue::from_str("reauthentication_required"))?;
        self.status(handle,generation)?;
        let committed=credential_cas_effect(&host_effect,&prepared.effect()).await?;
        self.status(handle,generation)?;
        let readback=credential_cas_effect(&host_effect,&prepared.readback_effect()).await?;
        self.status(handle,generation)?;
        let validated=self.client.finish_browser_credential_cas_async(prepared,committed,readback).await.map_err(|_|JsValue::from_str("session_expired"))?;
        self.status(handle,generation)?;
        serde_json::to_string(&validated).map_err(|_|JsValue::from_str("unavailable"))
    }

    pub fn invalidate(&mut self) { self.cache.clear();self.client.forget_session(); }
}

// No caller error detail, raw credential or unbounded host JSON crosses Rust.
async fn credential_cas_effect(host:&js_sys::Function,effect:&openmates_sdk::client::BrowserCredentialCasEffect)->Result<openmates_sdk::client::BrowserCredentialCasIoReceipt,JsValue>{
    let encoded=serde_json::to_string(effect).map_err(|_|JsValue::from_str("unavailable"))?;
    if encoded.len()+1024>16*1024{return Err(JsValue::from_str("invalid_request"));}
    let result=host.call1(&JsValue::UNDEFINED,&JsValue::from_str(&encoded)).map_err(|_|JsValue::from_str("unavailable"))?;
    let value=wasm_bindgen_futures::JsFuture::from(js_sys::Promise::resolve(&result)).await.map_err(|value|JsValue::from_str(if value.as_string().as_deref()==Some("credential_conflict"){"credential_conflict"}else{"unavailable"}))?;
    let encoded=value.as_string().filter(|v|v.len()+1024<=16*1024).ok_or_else(||JsValue::from_str("invalid_request"))?;
    serde_json::from_str(&encoded).map_err(|_|JsValue::from_str("invalid_request"))
}

impl Drop for BrowserCoreClient {
    fn drop(&mut self) { self.cache.clear();self.client.forget_session(); }
}

#[cfg(test)]
mod tests {
    use super::*;
    // Pure synthetic legacy browser format: key [7;32], IV [3;12].
    const EMAIL: &str = "AwMDAwMDAwMDAwMDVYzMZTNEO28cKTsoniWaTIhEgYLE+fFeRrDx0I+MJL/9zswusDIXve+TJj77LrY=";
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn captured_legacy_email_derives_exact_utf8_sha256_base64() {
        let hash = prior_email_hash(EMAIL, &[7; 32]).unwrap_or_else(|_| panic!("synthetic legacy envelope"));
        assert_eq!(hash.as_str(), "HcPZoawjluHJY3h0YbECfh6IHEqFEsMrROvh/GosMi4=");
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn bounded_chat_projection_refuses_empty_oversize_and_malformed_pages() {
        use openmates_sdk::model::{Chat, Message};
        let mut chat = Chat { id: "11111111-1111-4111-8111-111111111111".into(), title: "Synthetic".into(),
            messages: vec![Message { id: "22222222-2222-4222-8222-222222222222".into(), role: "user".into(),
                content: "Synthetic content".into(), ..Message::default() }], ..Chat::default() };
        assert!(chat_projection_allowed(&chat));
        let message = chat.messages[0].clone();
        chat.messages = vec![message.clone(); 20];
        assert!(chat_projection_allowed(&chat));
        chat.messages.push(message);
        assert!(!chat_projection_allowed(&chat));
        chat.messages.truncate(1);
        chat.messages[0].content = "x".repeat(64 * 1024 + 1);
        assert!(!chat_projection_allowed(&chat));
        chat.messages.clear();
        assert!(!chat_projection_allowed(&chat));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn read_projection_matches_shared_opaque_message_identity_vectors_without_granting_chat_authority() {
        use openmates_sdk::model::{Chat,Message};
        let vectors:serde_json::Value=serde_json::from_str(include_str!("../tests/fixtures/message-id-compatibility.json")).unwrap();
        for case in vectors["cases"].as_array().unwrap(){
            let valid=case["valid"].as_bool().unwrap();
            let Some(id)=case["value"].as_str()else{assert!(!valid);continue;};
            let mut chat=Chat{id:"11111111-1111-4111-8111-111111111111".into(),title:"Synthetic".into(),
                messages:vec![Message{id:id.into(),role:"user".into(),content:"Synthetic".into(),..Default::default()}],..Default::default()};
            assert_eq!(chat_projection_allowed(&chat),valid,"{}",case["id"]);
            chat.id="opaque-chat-is-not-authority".into();assert!(!chat_projection_allowed(&chat));
        }
        for ending in ["\n","\r","\u{2028}","\u{2029}"]{
            assert!(openmates_sdk::client::message_window::valid_message_id(&format!("opaque{ending}")));
        }
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn mismatched_key_missing_corrupt_and_non_utf8_email_refuse() {
        assert!(prior_email_hash(EMAIL, &[8; 32]).is_err());
        for encrypted in ["", "not-base64", "AwMDAwMDAwMDAwMD2gDoQcPiMNGE1Fb86pUc9VtW"] {
            assert!(prior_email_hash(encrypted, &[7; 32]).is_err());
        }
    }
}

#[path = "browser_cache.rs"]
mod cache_operations;
pub use cache_operations::{BrowserCachedReadPublication,BrowserCacheMonitor,BrowserIncomingPublication};

#[path="browser_owned_message_read.rs"]
mod owned_message_read;
pub use owned_message_read::{BrowserOwnedMessageReadHandle,BrowserOwnedMessageReadControl,BrowserOwnedMessageReadStepHandle,BrowserOwnedMetadataContinuationHandle,BrowserOwnedReadTerminalHandle};

#[cfg(feature="browser-metadata-prototype")]
#[path="browser_metadata.rs"]
mod metadata_prototype;
#[cfg(feature="browser-metadata-prototype")]
pub use metadata_prototype::*;

#[path="browser_initial_sync.rs"]
mod initial_sync;
pub use initial_sync::{BrowserInitialSyncHandle,BrowserInitialSyncControl,BrowserInitialSyncMetadata};

#[cfg(feature="browser-metadata-prototype")]
pub use initial_sync::{BrowserInitialSyncStoreBootstrap,BrowserInitialSyncStoreDriver,BrowserInitialSyncNativeTerminal,BrowserInitialSyncStored,capture_initial_sync_store};

#[path="browser_embed_user_edit.rs"]
mod embed_user_edit;
pub use embed_user_edit::BrowserImageEnhanceWaker;
