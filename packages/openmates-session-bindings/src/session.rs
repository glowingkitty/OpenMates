use openmates_sdk::{
    Client, ClientIdentity, ClientOptions, Error, Session,
    model::{StreamUpdate, Workspace},
    privacy::PrivacyOptions,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    future::Future,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
};
use tokio::sync::{Mutex as AsyncMutex, mpsc};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;
#[path = "session_anonymous.rs"]
pub(crate) mod anonymous;
#[path = "session_essential.rs"]
mod essential;
pub use essential::{PreparedInitialSyncOperation, InitialSyncOperationControl, InitialSyncMetadata};
#[path = "session_embed_version.rs"]
mod embed_versions;
#[path = "session_embed_share.rs"]
mod embed_share;
#[path = "session_drafts.rs"]
mod drafts;
pub use drafts::SessionDraftReadOptions;
#[path = "session_app_skill.rs"]
mod app_skill;
pub(crate) use app_skill::DirectSkillOutput;
#[path = "session_chat_details.rs"]
mod chat_details;
pub(crate) use chat_details::ChatDetailsOutput;
#[path = "session_saved_stream.rs"]
mod saved_stream;
#[path="session_apps_inventory.rs"]
mod apps_inventory;
pub(crate) use apps_inventory::{AppsInventoryOutput,PreparedAppsInventory};
pub(crate) use saved_stream::SavedStreamOutput;
#[path = "session_full_read.rs"]
mod full_read;
pub(crate) use full_read::FullChatOutput;
#[path = "session_saved_read.rs"]
mod saved_read;
#[path = "session_cache_settlement.rs"]
mod cache_settlement;
#[path = "session_first_page.rs"]
mod first_page;
#[path = "session_plans_workflows.rs"]
mod plans_workflows;
#[path = "session_project_task_watch.rs"]
mod project_task_watch;
#[path="session_workflow_files.rs"]
mod workflow_files;
pub(crate) use workflow_files::WorkflowFileSyncInput;
#[path = "session_work.rs"]
mod work;
#[path = "session_settings_reminders.rs"]
mod settings_reminders;
pub(crate) use settings_reminders::{PreparedSettingsReminders,SettingsRemindersOutput,SettingsRemindersControl};
#[cfg(any(feature = "napi-bindings", feature = "python-bindings"))]
pub(crate) use work::Request as WorkRequest;
#[cfg(any(feature = "napi-bindings", feature = "python-bindings"))]
pub(crate) use work::ProjectUnlinkInput;

#[cfg(any(feature = "napi-bindings", feature = "python-bindings", test))]
pub(crate) fn decode_input<T: serde::de::DeserializeOwned>(encoded: String) -> Result<T> {
    let encoded = Zeroizing::new(encoded);
    if encoded.len() > 1024 * 1024 {
        return Err(Error::Invalid("Work input exceeds the supported size.").into());
    }
    serde_json::from_str(&encoded).map_err(|_| Error::Invalid("Invalid typed work input.").into())
}

/// Explicit caller policy. Credentials and keys deliberately have no Debug.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BindingOptions {
    pub api_url: String,
    pub app_url: Option<String>,
    pub enhanced_privacy: bool,
    pub allow_private_operations: bool,
}
#[path = "api_key.rs"]
mod api_key;
pub use api_key::{ApiKeyBridge, ApiKeyRequest, ApiKeyOutput};
pub use crate::error::BindingError;
type Result<T> = std::result::Result<T, BindingError>;
type ConsentResponse = (String, Vec<String>);
type ConsentSender = mpsc::UnboundedSender<ConsentResponse>;
struct Active {
    id: String,
    cancel: CancellationToken,
}
enum EventReceiver {
    Anonymous(mpsc::Receiver<Value>),
    Saved(saved_stream::SavedStreamReceiver),
}
struct Events {
    id: String,
    receiver: EventReceiver,
}
struct WorkflowWait {
    run: String,
    cancel: CancellationToken,
}
#[path = "session_auth_transition.rs"]
mod auth_transition;
// Compatibility operations still replace Client's ordinary cancellation lane.
// Keep them behind an owned saved driver until each operation is ported. The
// actual safe owned read path may use state.client directly with its own scope.
struct LegacyClient<'a> {
    client: tokio::sync::MutexGuard<'a, Client>,
    _lane: tokio::sync::MutexGuard<'a, ()>,
}
impl std::ops::Deref for LegacyClient<'_> { type Target=Client; fn deref(&self)->&Client { &self.client } }
impl std::ops::DerefMut for LegacyClient<'_> { fn deref_mut(&mut self)->&mut Client { &mut self.client } }
struct State {
    client: AsyncMutex<Client>,
    legacy_client_lane: AsyncMutex<()>,
    saved_driver: Mutex<Option<Arc<saved_stream::SavedStreamScope>>>,
    endpoint: String,
    active: Mutex<Option<Active>>,
    events: AsyncMutex<Option<Events>>,
    consent: Mutex<Option<ConsentSender>>,
    pending_consent: Mutex<BTreeMap<String, BTreeSet<String>>>,
    closed: AtomicBool,
    work_operations: Mutex<BTreeMap<String, CancellationToken>>,
    identity_epoch: AtomicU64,
    identity_transitions: Mutex<auth_transition::IdentityTransitions>,
    workflow_waits: Mutex<BTreeMap<String, WorkflowWait>>,
    project_task_watches: project_task_watch::Registry,
    essential: essential::Registry,
    #[cfg(test)]
    draft_return_barrier: Mutex<Option<Arc<drafts::DraftReturnBarrier>>>,
    #[cfg(test)]
    saved_read_return_barrier: Mutex<Option<Arc<saved_read::SavedReadReturnBarrier>>>,
    #[cfg(test)]
    work_return_barrier: Mutex<Option<Arc<work::WorkReturnBarrier>>>,
}
/// Cloneable handle; every async SDK operation runs to its transaction boundary
/// even if a foreign-language Future is abandoned. Cancellation is cooperative.
#[derive(Clone)]
pub struct SessionBridge {
    state: Arc<State>,
}
impl SessionBridge {
    pub fn new(options_json: &str) -> Result<Self> {
        Self::with_identity(options_json, ClientIdentity::Rust)
    }
    pub fn with_identity(options_json: &str, identity: ClientIdentity) -> Result<Self> {
        let options: BindingOptions = serde_json::from_str(options_json)
            .map_err(|_| BindingError::from(Error::Invalid("options")))?;
        let privacy = PrivacyOptions {
            enhanced: options.enhanced_privacy,
        };
        privacy.verify().map_err(BindingError::from)?;
        let allow = options.allow_private_operations;
        let client = Client::with_options(
            &options.api_url,
            None,
            ClientOptions {
                identity,
                interactive: false,
                app_url: options.app_url,
                privacy,
                private_operation_gate: Some(Arc::new(move || {
                    if allow { Ok(()) } else { Err(Error::Forbidden) }
                })),
            },
        )
        .map_err(BindingError::from)?;
        Ok(Self {
            state: Arc::new(State {
                client: AsyncMutex::new(client),
                legacy_client_lane: AsyncMutex::new(()),
                saved_driver: Mutex::new(None),
                endpoint: options.api_url,
                active: Mutex::new(None),
                events: AsyncMutex::new(None),
                consent: Mutex::new(None),
                pending_consent: Mutex::new(BTreeMap::new()),
                closed: AtomicBool::new(false),
                work_operations: Mutex::new(BTreeMap::new()),
                identity_epoch: AtomicU64::new(0),
                identity_transitions: Mutex::new(auth_transition::IdentityTransitions::default()),
                workflow_waits: Mutex::new(BTreeMap::new()),
                project_task_watches: project_task_watch::Registry::default(),
                essential: essential::Registry::default(),
                #[cfg(test)]
                draft_return_barrier: Mutex::new(None),
                #[cfg(test)]
                saved_read_return_barrier: Mutex::new(None),
                #[cfg(test)]
                work_return_barrier: Mutex::new(None),
            }),
        })
    }
    fn available(&self) -> Result<()> {
        let _identity = self.identity_admission()?;
        Ok(())
    }
    async fn live_client(state: &State) -> Result<LegacyClient<'_>> {
        loop {
            Self::drain_saved_driver(state).await?;
            let lane = state.legacy_client_lane.lock().await;
            // A new original may have registered while this call queued for
            // the lane. A dropped/panicked task never fabricates settlement.
            let pending={
                let original=state.saved_driver.lock().map_err(|_|BindingError::from(Error::Protocol))?;
                original.as_ref().is_some_and(|scope|!scope.is_settled())
            };
            if pending { drop(lane); continue; }
            let client = state.client.lock().await;
            if state.closed.load(Ordering::Acquire) { return Err(Error::Cancelled.into()); }
            return Ok(LegacyClient { client, _lane: lane });
        }
    }

    fn try_live_client(state:&State)->Result<LegacyClient<'_>> {
        let original=state.saved_driver.lock().map_err(|_|BindingError::from(Error::Protocol))?;
        if original.as_ref().is_some_and(|scope|!scope.is_settled()) { return Err(Error::Conflict.into()); }
        let lane=state.legacy_client_lane.try_lock().map_err(|_|BindingError::from(Error::Conflict))?;
        let client=state.client.try_lock().map_err(|_|BindingError::from(Error::Conflict))?;
        if state.closed.load(Ordering::Acquire) { return Err(Error::Cancelled.into()); }
        Ok(LegacyClient { client, _lane:lane })
    }

    async fn transaction<T, F>(&self, future: F) -> Result<T>
    where
        T: Send + 'static,
        F: Future<Output = Result<T>> + Send + 'static,
    {
        self.available()?;
        // Dropping a foreign future detaches this task; it never drops a
        // credential rotation or committed HTTP operation partway through.
        tokio::spawn(future)
            .await
            .map_err(|_| BindingError::from(Error::Protocol))?
    }
    pub async fn login_password(
        &self,
        email: String,
        password: String,
        tfa: Option<String>,
    ) -> Result<String> {
        self.login_password_with_options(email,password,tfa,openmates_sdk::PasswordLoginOptions::default()).await
    }
    pub async fn login_password_with_options(
        &self, email: String, password: String, tfa: Option<String>,
        options: openmates_sdk::PasswordLoginOptions,
    ) -> Result<String> {
        self.prepare_login_password(email,password,tfa,options)?.run_string().await
    }
    pub async fn import_session(&self, session_json: String) -> Result<()> {
        self.prepare_import_session(session_json)?.run_unit().await
    }
    pub async fn export_session(&self, include_secrets: bool) -> Result<String> {
        if !include_secrets {
            return Err(Error::Forbidden.into());
        }
        let state = self.state.clone();
        self.transaction(async move {
            let client = Self::live_client(&state).await?;
            let snapshot = client
                .credential_snapshot()
                .ok_or(Error::Authentication)
                .map_err(BindingError::from)?;
            serde_json::to_string(&json!({"revision":snapshot.revision,"session":snapshot.session}))
                .map_err(|_| Error::Protocol.into())
        })
        .await
    }
    pub async fn validate_session(&self) -> Result<()> {
        let state = self.state.clone();
        self.transaction(async move {
            Self::live_client(&state)
                .await?
                .validate_session()
                .await
                .map_err(BindingError::from)
        })
        .await
    }
    pub async fn list(&self, workspace: String) -> Result<String> {
        if workspace=="apps" { return self.apps_inventory_prepare().await?.release_json(); }
        let workspace: Workspace = serde_json::from_value(Value::String(workspace))
            .map_err(|_| BindingError::from(Error::Invalid("workspace")))?;
        let state = self.state.clone();
        self.transaction(async move {
            let items = Self::live_client(&state)
                .await?
                .list(workspace)
                .await
                .map_err(BindingError::from)?;
            serde_json::to_string(&items).map_err(|_| Error::Protocol.into())
        })
        .await
    }
    pub async fn open_chat(&self, id: String) -> Result<String> {
        self.full_chat_read_transaction(id).await
    }
    pub async fn set_team(&self, id: Option<String>) -> Result<()> {
        self.prepare_set_team(id)?.run_unit().await
    }
    pub fn cancel(&self) -> Result<()> {
        self.state.essential.close_all();
        self.state.project_task_watches.close_all();
        for token in self
            .state
            .work_operations
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .values()
        {
            token.cancel();
        }
        if let Some(active) = self
            .state
            .active
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .as_ref()
        {
            active.cancel.cancel()
        };
        Ok(())
    }
    pub fn consent(&self, request_id: String, approved: Vec<String>) -> Result<()> {
        self.available()?;
        let mut pending = self
            .state
            .pending_consent
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?;
        let allowed = pending
            .get(&request_id)
            .ok_or(Error::Forbidden)
            .map_err(BindingError::from)?;
        let unique = approved.iter().collect::<BTreeSet<_>>();
        if unique.len() != approved.len() || approved.iter().any(|id| !allowed.contains(id)) {
            return Err(Error::Forbidden.into());
        }
        self.state
            .consent
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .as_ref()
            .ok_or(Error::Cancelled)
            .map_err(BindingError::from)?
            .send((request_id.clone(), approved))
            .map_err(|_| BindingError::from(Error::Cancelled))?;
        pending.remove(&request_id);
        Ok(())
    }
    pub async fn start_send(&self, text: String, chat_id: Option<String>) -> Result<String> {
        self.start_saved_stream(text,chat_id).await
    }
    pub async fn next_event(&self, id: String) -> Result<String> {
        self.next_event_prepare(id).await?.release_json()
    }
    pub async fn logout(&self) -> Result<()> {
        self.prepare_logout()?.run_unit().await
    }
    pub async fn close(&self) -> Result<()> {
        self.prepare_close()?.run().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn cancelled_consent_never_reaches_a_later_turn_with_a_reused_request_id() {
        let bridge = SessionBridge::new(r#"{"api_url":"https://api.example.invalid","app_url":null,"enhanced_privacy":false,"allow_private_operations":false}"#).unwrap_or_else(|_|panic!("construct"));
        let first = bridge
            .start_send("Synthetic".into(), None)
            .await
            .unwrap_or_else(|_| panic!("first"));
        bridge
            .state
            .pending_consent
            .lock()
            .unwrap()
            .insert("reused-id".into(), BTreeSet::from(["item".into()]));
        bridge
            .consent("reused-id".into(), vec!["item".into()])
            .unwrap_or_else(|_| panic!("consent"));
        bridge.cancel().unwrap_or_else(|_| panic!("cancel"));
        bridge
            .next_event(first)
            .await
            .unwrap_or_else(|_| panic!("first event"));
        assert!(bridge.state.consent.lock().unwrap().is_none());
        let second = bridge
            .start_send("Next".into(), None)
            .await
            .unwrap_or_else(|_| panic!("second"));
        assert_eq!(
            bridge
                .consent("reused-id".into(), vec!["item".into()])
                .err()
                .map(|e| e.code),
            Some("forbidden")
        );
        bridge
            .next_event(second)
            .await
            .unwrap_or_else(|_| panic!("second event"));
        assert!(bridge.state.consent.lock().unwrap().is_none());
        bridge.close().await.unwrap_or_else(|_| panic!("close"));
    }
    #[tokio::test]
    async fn close_fences_operations_already_queued_on_the_serialized_client() {
        let bridge = SessionBridge::new(r#"{"api_url":"https://api.example.invalid","app_url":null,"enhanced_privacy":false,"allow_private_operations":false}"#).unwrap_or_else(|_|panic!("construct"));
        let held = bridge.state.client.lock().await;
        let reader = bridge.clone();
        let queued = tokio::spawn(async move { reader.export_session(true).await });
        tokio::task::yield_now().await;
        let closer = bridge.clone();
        let closing = tokio::spawn(async move { closer.close().await });
        tokio::time::timeout(std::time::Duration::from_secs(1), async {
            while !bridge.state.closed.load(Ordering::Acquire) {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        drop(held);
        assert_eq!(
            queued.await.unwrap().err().map(|e| e.code),
            Some("cancelled")
        );
        assert!(closing.await.unwrap().is_ok());
    }
}

// Shared recursive wiping policy for privately owned binding plaintext values.
