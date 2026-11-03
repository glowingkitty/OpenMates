//! Native authenticated protocol client. All mutable operations are serialized by
//! `&mut self`; private ciphertext is decrypted only into in-memory view models.
use crate::{
    crypto::{self, Key},
    error::{Error, Result},
    model::{Chat, Item, Message, Mutation, StreamUpdate, Workspace},
    session::Session,
};
use reqwest::Method;
use serde_json::{Value, json};
use std::{collections::BTreeMap, time::Duration};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;
mod actions;
mod apps;
mod travel_booking;
pub mod learning_mode;
pub mod new_chat_suggestions;
pub use apps::DirectAppSkillAdmission;
mod auth;
mod session_response;
pub use auth::PasswordLoginOptions;
mod auth_handoff;
pub use auth_handoff::FreshSessionHandoff;
mod browser;
#[doc(hidden)]
pub use browser::BrowserProfileCacheReadiness;
#[doc(hidden)]
pub use browser::OwnedBrowserProfileCacheAbsence;
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
#[doc(hidden)]
pub use browser::{PreparedBrowserFirstSession,BrowserFirstSessionControl,BrowserFirstSessionReceipt};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
#[doc(hidden)]
pub use browser::{PreparedBrowserFirstSessionData,BrowserFirstSessionDataControl,BrowserFirstSessionData};
pub use browser::{
    browser_message_merge_policy_json,
    BrowserRetainedCachePublication, BrowserCandidateFailures, BrowserMetadataCacheMode, BrowserMetadataCacheScope,
    BrowserOrdinaryKeyRetention, BrowserPersistence, BrowserProfileKey, BrowserSessionStatus, BrowserSealedCredentials,
    BrowserCredentialCasScope, BrowserCredentialCasEffect, BrowserCredentialCasIoReceipt,
    BrowserCredentialCasOperation, BrowserPreparedCredentialCas, BrowserCredentialCasValidation,
};
#[doc(hidden)]
pub use browser::{OriginalHintRefreshAdmission,OriginalHintRefreshBatch,OriginalHintRowSeed,OriginalHintRowMetadataAdmission,OriginalHintRowMetadataPublication,OriginalHintMetadataApplied,OriginalHintDraftInventoryPrerequisite,OriginalHintDraftInventoryTicket,UntrustedDraftInventoryPageData,UntrustedDraftInventoryRereadData,OwnedOriginalHintWindowPreparation,OwnedOriginalHintWindowCompletion,OriginalHintWindowBatch,OwnedBrowserReadDriver,OwnedBrowserReadStep,OwnedBrowserReadPhase,OwnedBrowserReadIO,OwnedBrowserReadPublication,OwnedBrowserMetadataContinuation,OwnedBrowserReadControl,OwnedBrowserMetadataPublication,OriginalHintRecoveryHandoff,OwnedBrowserReadTerminalObserver,OwnedBrowserReadTerminal,BrowserOriginalHintRecoveryDriver,BrowserOriginalHintRecoveryStep,BrowserOriginalHintRecoveryApply,BrowserOriginalHintRecoveryIo,BrowserOriginalHintRecoveryResume,BrowserOriginalHintRecoveryControl,BrowserOriginalHintRecoveryAdoption,BrowserOriginalHintRecoveryProgress,BrowserOriginalHintRecoveryPendingPersistence,BrowserOriginalHintRecoveryDeferred,BrowserOriginalHintRecoveryCheckpointPreparation,BrowserOriginalHintRecoveryCheckpointCrypto,BrowserOriginalHintRecoveryCheckpointWrite,BrowserOriginalHintRecoveryPersistenceFailure};
mod consent;
mod selected_first_page;
mod context;
mod direct;
mod docs;
mod browser_draft;
pub use browser_draft::{BrowserDraftAdmission, BrowserDraftControl, BrowserDraftPublication, BrowserDraftWrite};
mod draft_clear;
pub mod draft_preview;
mod draft_read;
pub use draft_read::DraftReadAdmission;
mod embed;
pub mod embed_version;
pub mod saved_embed;
mod saved_embed_selector;
mod focus;
mod incognito;
// Private owned-driver foundation; entrypoints are wired by the distinct driver successor.
#[allow(dead_code)]
mod owned_operation;
mod owned_saved_send;
mod owned_apps_inventory;
#[doc(hidden)]
pub use owned_apps_inventory::{PreparedOwnedAppsInventory,OwnedAppsInventoryHeaders,OwnedAppsInventoryBody,CompletedOwnedAppsInventory,OwnedAppsInventoryControl,AppsInventoryPublication};
#[doc(hidden)]
pub use owned_saved_send::{PreparedOwnedSavedSend,OwnedClientPhase,OwnedSavedSendResume,OwnedSavedSendStep,OwnedSavedSendTerminal,OwnedSavedSendDriver,OwnedSavedSendControl,OwnedSavedSendDisposition,OwnedSavedSendReturnedRefusal,OwnedSavedSendRefusalReason};

mod monitor;
pub use monitor::{PreparedInitialSync,InitialSyncControl,InitialSyncRead,InitialSyncMetadataBatch};
#[doc(hidden)]
pub use monitor::{PreparedOwnedChatMonitor,OwnedChatMonitorStartStep,OwnedChatMonitorStartApply,OwnedChatMonitorReady,OwnedChatMonitorStartControl,OwnedChatMonitorStartTerminal};
pub use monitor::cached_view::{CacheSettlementCandidate, CacheSettlementPublication, ChatFirstPageCandidate, ChatFirstPagePublication, ChatFirstPageSink, CanonicalChatCandidate, CanonicalChatPublication, CachedChatPublication, CachedChatViews, CachedChatWindow, ChatViewRead};
pub use monitor::{
    ChatInvalidation, ChatModels, ChatMonitor, ChatMonitorAccessDenial, ChatPublication,
    ChatRefresh, ChatRefreshDurableReceipt, ChatSelectionUpdate,
};
mod pair;
mod patch;
pub(crate) fn apply_embed_version_patch(content: &str, diff: &str) -> Result<String> {
    patch::apply(content, diff)
}
mod persistence;
mod project_task_watch;
mod source_host;
pub(crate) use source_host::SourceHostScope;
pub use source_host::{
    SourceHostAdapter, SourceHostBinding, SourceHostHandshake, SourceHostOperation,
    SourceHostOptions, SourceHostPoll, SourceHostRead, SourceHostRemoteCrypto, SourceHostRequest,
    SourceHostRequestFrame, SourceHostRoutingIdentity, SourceHostSession, SourceHostStart,
};
mod completion_recovery;
pub(crate) use completion_recovery::{OriginalRecoveryCheckpointIoTicket,BrowserRecoveryPortRoot};
#[cfg(target_arch = "wasm32")]
#[doc(hidden)]
pub use crate::platform::browser_recovery_port::{CapturedBrowserRecoveryPort,OriginalBrowserRecoveryPort,NativeRecoveryPortPending,NativeRecoveryPortDelivery};

mod recovery;
pub use completion_recovery::{
    CompletionRecoveryAdmission, CompletionRecoveryCheckpoint, CompletionRecoveryDurableReceipt,
    CompletionRecoveryJob, CompletionRecoveryKind, CompletionRecoveryReceipt,
    CompletionRecoveryStage,
};
pub use project_task_watch::{
    ProjectTaskBinding, ProjectTaskOwnerAuthority, ProjectTaskPublication, ProjectTaskWatch,
    ProjectTaskWatchPoll, ProjectTaskWatchRead, ProjectTaskWatchReconnect, ProjectTaskWatchStart,
};
mod credentials;
mod cache_policy;
mod chat_details_cache;
pub use cache_policy::CachedContentLoader;
pub mod snapshot_sections;
mod chat_list_freshness;
mod chat_arrival_order;
mod chat_tombstones;
// architecture.sync@2 overview order and incremental chat sync feed.
pub mod overview;
mod sync_feed;
mod mention_context;
mod search;
mod send;
mod send_observations;
mod send_options;
mod sync;
mod sync_windows;
mod sync_capability;
mod project_source_name_read;
mod settings_read;
mod plaintext;
mod local_cached_read;
pub mod message_window;
pub mod saved_chat_read;
pub mod full_chat_read;
pub mod chat_details;
pub use chat_list_freshness::CacheClockEvidence;
pub use sync::FreshChatInventory;
mod task_job_payload;
mod task_jobs;
mod team;
mod toon;
pub(crate) mod transport;
#[cfg(not(target_arch = "wasm32"))] pub mod upload;
#[cfg(not(target_arch = "wasm32"))] pub mod profile_upload;
#[cfg(not(target_arch = "wasm32"))] pub use transport::binary_stream::{BinaryResponse, SseMessage, SseOpen, SseParser, SseStream, parse_sse_message};
mod transport_owned_start;
mod workflow_delivery;
mod workspaces;
pub use docs::{
    compose_wikipedia_article, DocsFile, DocsFolder, DocsSearchResult, DocsTree, WikipediaLearningBundle,
    WikipediaRelatedArticle, WikipediaSearchResult, validate_doc_slug,
};
pub use pair::PairChallenge;
pub use send_options::{
    SendConsentPolicy, SendMemoryRequest, SendOptions, SendOutcome, SendQueueMode, SendStatus,
};

/// Fixed SDK identity used by authorization and device-access policy.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum ClientIdentity {
    #[default]
    Rust,
    Npm,
    Pip,
    Cli,
}
impl ClientIdentity {
    pub(crate) fn header(self) -> &'static str {
        match self {
            Self::Rust => "rust",
            Self::Npm => "npm",
            Self::Pip => "pip",
            Self::Cli => "cli",
        }
    }
}

/// Explicit client policy. Defaults use deterministic Rust privacy detection;
/// enhanced semantic privacy must be supplied by a future supported engine.
#[derive(Clone, Default)]
pub struct ClientOptions {
    pub identity: ClientIdentity,
    /// Human presence is opt-in and applies only to an explicit CLI identity.
    pub interactive: bool,
    /// Explicit web application origin for custom installations. This becomes
    /// the auth Origin header and pairing destination; no environment is read.
    pub app_url: Option<String>,
    pub privacy: crate::privacy::PrivacyOptions,
    /// Optional caller policy, checked before private inference or skill input.
    /// The SDK does not discover profiles or install this callback implicitly.
    pub private_operation_gate: Option<std::sync::Arc<dyn Fn() -> Result<()> + Send + Sync>>,
}
/// Caller-owned credentials paired with an exact persistence revision.
/// Intentionally has no Debug implementation.
pub struct CredentialSnapshot {
    pub revision: u64,
    pub session: Session,
}
/// Updates are delivered without performing persistence or prompting.
/// Intentionally has no Debug implementation because Updated contains secrets.
pub enum CredentialEvent {
    Updated(Box<CredentialSnapshot>),
    Cleared { revision: u64 },
}

/// Bounded unresolved original attempts; admission refuses before new effects.
#[doc(hidden)]
pub const MAX_SCOPED_SAVED_SEND_QUARANTINES: usize = 100;
/// Same byte ceiling as native storage::MAX_LOCAL_RECORD_BYTES, used here as
/// aggregate in-memory resource backpressure, NOT durable storage or user quota.
#[doc(hidden)]
pub const MAX_SCOPED_SAVED_SEND_QUARANTINE_BYTES: usize = 32 * 1024 * 1024;
fn scoped_admission_size(value:&Value,limit:usize)->Result<usize> {scoped_serialized_size(value,limit)}
fn scoped_serialized_size<T:serde::Serialize+?Sized>(value:&T,limit:usize)->Result<usize> {
    struct Count {used:usize,limit:usize}
    impl std::io::Write for Count {
        fn write(&mut self,bytes:&[u8])->std::io::Result<usize>{
            let next=self.used.checked_add(bytes.len()).filter(|next|*next<=self.limit)
                .ok_or_else(||std::io::Error::other("saved send resource backpressure"))?;
            self.used=next;Ok(bytes.len())
        }
        fn flush(&mut self)->std::io::Result<()>{Ok(())}
    }
    let mut count=Count{used:0,limit};
    serde_json::to_writer(&mut count,value).map_err(|_|Error::Conflict)?;
    Ok(count.used)
}
/// One portable prepared saved-send. Caller cancellation is a negative request,
/// separate from the still-live original context parent. No Clone/serde/Debug.
#[doc(hidden)]
pub struct PreparedSavedSend {
    id: String,
    chat: Option<String>,
    request: CancellationToken,
    child: CancellationToken,
    publication: CancellationToken,
    parent: CancellationToken,
    scope: sync_capability::AsyncCryptoScope,
    epoch: u64,
    gate: std::sync::Arc<ScopedSendGate>,
    private_gate: Option<std::sync::Arc<dyn Fn() -> Result<()> + Send + Sync>>,
}
impl PreparedSavedSend {
    pub fn id(&self) -> &str { &self.id }
    pub fn cancellation_request(&self) -> CancellationToken { self.request.clone() }
    pub fn publication_guard(&self) -> SavedSendPublicationGuard {
        SavedSendPublicationGuard { id: self.id.clone(), child: self.child.clone(),
            parent: self.parent.clone(), publication: self.publication.clone(),
            resources: self.scope.negative_observer(), gate: self.gate.clone(),
            private_gate: self.private_gate.clone(), request:Some(self.request.clone()), owned_lease:None }
    }
}
/// Original negative release fence, usable while the mutable Client is borrowed.
/// It contains no credentials, identity selectors, decryption or effect authority.
#[derive(Clone)]
#[doc(hidden)]
pub struct SavedSendPublicationGuard {
    id: String,
    child: CancellationToken,
    parent: CancellationToken,
    publication: CancellationToken,
    resources: sync_capability::NegativeCryptoScope,
    request: Option<CancellationToken>,
    // Only a core-issued original owned operation supplies this identity.
    owned_lease:Option<owned_operation::OwnedOperationLease>,
    gate: std::sync::Arc<ScopedSendGate>,
    private_gate: Option<std::sync::Arc<dyn Fn() -> Result<()> + Send + Sync>>,
}
impl SavedSendPublicationGuard {
    pub fn check_release(&self) -> Result<()> {
        let original_negatives=||->Result<()> {
            if self.child.is_cancelled() || self.parent.is_cancelled() || self.publication.is_cancelled()
                || self.request.as_ref().is_some_and(CancellationToken::is_cancelled) {
                return Err(Error::Cancelled);
            }
            if let Some(owned)=&self.owned_lease{owned.check_original_negative()?;}
            self.resources.check_release()?;
            // Original opaque resource callbacks cannot hide token revocation.
            if self.child.is_cancelled() || self.parent.is_cancelled() || self.publication.is_cancelled()
                || self.request.as_ref().is_some_and(CancellationToken::is_cancelled) {return Err(Error::Cancelled)}
            if let Some(owned)=&self.owned_lease{owned.check_original_negative()?;}Ok(())
        };
        original_negatives()?;
        if let Some(gate) = &self.private_gate { gate()?; }
        self.gate.check_publication(&self.id, &self.publication)?;
        // The captured caller may synchronously cancel an original resource or
        // advance denial while returning Ok. Observe negatives after all hooks.
        original_negatives()
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[doc(hidden)]
pub enum SavedSendOutcome { Completed, Cancelled, Uncertain, Backpressure, SessionExpired, Unavailable }
/// Identifiers of the original attempt only; never a new-send retry instruction.
#[derive(Clone)]
#[doc(hidden)]
pub struct SavedSendRecoveryIdentity { chat: String, turn: String, message: String }
impl SavedSendRecoveryIdentity {
    pub fn chat_id(&self) -> &str { &self.chat }
    pub fn turn_id(&self) -> &str { &self.turn }
    pub fn message_id(&self) -> &str { &self.message }
}
#[derive(Default)]
struct ScopedSendObservation {
    identity: Option<SavedSendRecoveryIdentity>, attempted: bool,
    // Exact original encrypted admission fields AND private inference request.
    // Kept opaque/wiping in memory only for original-turn resolution; never
    // persisted/exported/reconstructed as a new request by an adapter.
    admission: Option<plaintext::Plain<Value>>,
    admission_bytes: usize,
}

struct ScopedSendExecution {
    request: CancellationToken,
    id: String,
    chat: Option<String>,
    parent: CancellationToken,
    child: CancellationToken,
    scope: sync_capability::AsyncCryptoScope,
    epoch: u64,
    gate: std::sync::Arc<ScopedSendGate>,
    private_gate: Option<std::sync::Arc<dyn Fn() -> Result<()> + Send + Sync>>,
    consumed: bool,
    publication: CancellationToken,
}
impl Drop for ScopedSendExecution {
    fn drop(&mut self) {
        if !self.consumed { self.child.cancel(); }
        if !self.consumed { self.gate.finish(&self.id, false); }
    }
}
/// Actual SDK future has returned. Only this Client can consume the original
/// terminal; dropping it cannot rearm cancellation or publish a private result.
#[doc(hidden)]
pub struct SavedSendTerminal {
    execution: Option<ScopedSendExecution>,
    result: Option<Result<plaintext::Plain<Chat>>>,
    outcome: SavedSendOutcome,
    recovery: Option<SavedSendRecoveryIdentity>,
}
impl SavedSendTerminal {
    pub fn outcome(&self) -> SavedSendOutcome { self.outcome }
}
/// One-use original terminal release. The original scope remains through any
/// final native/foreign string allocation; a reusable bool alone is no proof.
#[doc(hidden)]
pub struct SavedSendDisposition {
    execution: ScopedSendExecution,
    child: CancellationToken,
    epoch: u64,
    receipt: String,
    result: Option<Result<plaintext::Plain<Chat>>>,
    outcome: SavedSendOutcome,
    reusable: bool,
    cancelled_result: bool,
    recovery: Option<SavedSendRecoveryIdentity>,
}
impl SavedSendDisposition {
    pub fn operation_id(&self) -> &str { &self.execution.id }
    pub fn scope_epoch(&self) -> u64 { self.epoch }
    pub fn receipt_id(&self) -> &str { &self.receipt }
    pub fn outcome(&self) -> SavedSendOutcome { self.outcome }
    pub fn reusable(&self) -> bool { self.can_continue_parent() }
    pub fn can_continue_parent(&self) -> bool { self.reusable }
    /// A locally terminated pre-effect cancel has no admitted original turn.
    /// Uncertain never becomes settled merely because its parent can continue.
    pub fn original_turn_settled(&self) -> bool {
        matches!(self.outcome,SavedSendOutcome::Completed|SavedSendOutcome::Cancelled|SavedSendOutcome::Backpressure)
    }
    pub fn original_cancelled_result(&self) -> bool { self.cancelled_result }
    pub fn recovery_identity(&self, client: &Client) -> Result<Option<&SavedSendRecoveryIdentity>> {
        self.check_current(client)?;
        Ok(self.recovery.as_ref())
    }
    /// Separate terminal-output proof. Old live update guards retain their old
    /// child and cannot borrow this owned transition to release cancelled data.
    pub fn publication_guard(&self) -> SavedSendPublicationGuard {
        SavedSendPublicationGuard { id: self.execution.id.clone(), child: self.child.clone(),
            parent: self.execution.parent.clone(), publication: self.execution.publication.clone(),
            resources: self.execution.scope.negative_observer(), gate: self.execution.gate.clone(),
            private_gate: self.execution.private_gate.clone(),
            request:if matches!(self.outcome,SavedSendOutcome::Cancelled|SavedSendOutcome::Uncertain|SavedSendOutcome::Backpressure) {None}else{Some(self.execution.request.clone())},owned_lease:None }
    }
    pub fn check_current(&self, client: &Client) -> Result<()> {
        let original = &self.execution;
        client.verify_private_operation()?;
        if original.parent.is_cancelled() || original.parent != client.operation_parent
            || self.epoch != client.fresh_auth.operation_epoch()
            || !std::sync::Arc::ptr_eq(&original.gate, &client.scoped_send_gate)
            || !same_private_gate(&original.private_gate, &client.options.private_operation_gate) {
            return Err(Error::Cancelled);
        }
        if self.reusable {
            original.scope.check_owned_child_transition(client, &self.child)?;
        } else {
            original.scope.check_terminated_child_context(client)?;
        }
        if let Some(chat) = original.chat.as_deref() {
            if !client.task_watch_authority.cached_chat_allowed(chat) { return Err(Error::Forbidden); }
        }
        Ok(())
    }
    /// Retain the original wiping value until both serialization guards pass.
    pub fn encode_result_json(&mut self, client: &Client) -> Result<zeroize::Zeroizing<String>> {
        self.check_current(client)?; self.publication_guard().check_release()?;
        let value=self.result.take().ok_or(Error::Cancelled)??;
        let encoded=zeroize::Zeroizing::new(serde_json::to_string(&*value)?);
        self.check_current(client)?; self.publication_guard().check_release()?;
        Ok(encoded)
    }
    pub fn take_result(&mut self, client: &Client) -> Result<Chat> {
        self.check_current(client)?; self.publication_guard().check_release()?;
        self.result.take().ok_or(Error::Cancelled)?.map(plaintext::Plain::into_inner)
    }
}
fn same_private_gate(a: &Option<std::sync::Arc<dyn Fn() -> Result<()> + Send + Sync>>,
    b: &Option<std::sync::Arc<dyn Fn() -> Result<()> + Send + Sync>>) -> bool {
    match (a, b) { (None, None) => true, (Some(a), Some(b)) => std::sync::Arc::ptr_eq(a, b), _ => false }
}
#[derive(Default)]
struct ScopedSendGateState { active: Option<String>, refused: bool, publication: Option<(String, CancellationToken)> }
/// Keyless scheduling only, never account/key/publication authority.
#[derive(Default)]
pub(super) struct ScopedSendGate {
    state: std::sync::RwLock<ScopedSendGateState>,
    changed: tokio::sync::Notify,
}
impl ScopedSendGate {
    fn admit(&self) -> Result<()> {
        let state = self.state.read().map_err(|_| Error::Protocol)?;
        if state.refused { return Err(Error::Cancelled); }
        if state.active.is_some() { return Err(Error::Conflict); }
        Ok(())
    }
    fn start(&self, id: &str, publication: &CancellationToken) -> Result<()> {
        let mut state = self.state.write().map_err(|_| Error::Protocol)?;
        if state.refused { return Err(Error::Cancelled); }
        if state.active.is_some() { return Err(Error::Conflict); }
        if let Some((_, prior)) = state.publication.take() { prior.cancel(); }
        state.publication = Some((id.into(), publication.clone()));
        state.active = Some(id.into()); Ok(())
    }
    fn finish(&self, id: &str, reusable: bool) {
        if let Ok(mut state) = self.state.write() {
            // A stale original terminal A can never release/refuse successor B.
            if state.active.as_deref() != Some(id) { return; }
            state.active = None; state.refused = !reusable;
            if !reusable { if let Some((_, publication)) = &state.publication { publication.cancel(); } }
        }
        self.changed.notify_waiters();
    }
    fn close(&self) {
        if let Ok(mut state) = self.state.write() {
            state.refused = true;
            if let Some((_, publication)) = &state.publication { publication.cancel(); }
        }
        self.changed.notify_waiters();
    }
    fn invalidate_publications(&self) {
        if let Ok(state) = self.state.write() {
            if let Some((_, publication)) = &state.publication { publication.cancel(); }
        }
    }
    fn check_publication(&self, id: &str, publication: &CancellationToken) -> Result<()> {
        // Read-only original observers may overlap. An exclusive transition,
        // poison or unknown state still refuses without blocking allocation.
        let state = self.state.try_read().map_err(|_| Error::Cancelled)?;
        match &state.publication {
            Some((original, token)) if !state.refused && original == id && token == publication && !token.is_cancelled() => Ok(()),
            _ => Err(Error::Cancelled),
        }
    }
    async fn idle(&self) -> Result<()> {
        loop {
            let changed = self.changed.notified(); tokio::pin!(changed); changed.as_mut().enable();
            { let state = self.state.read().map_err(|_| Error::Protocol)?;
              if state.refused { return Err(Error::Cancelled); }
              if state.active.is_none() { return Ok(()); } }
            changed.await;
        }
    }
}

pub struct Client {
    options: ClientOptions,
    browser_authority: Option<browser::BrowserAuthority>,
    // Transport mode only. Grants no principal or mutable-operation authority.
    browser_password_transport: bool,
    browser_password_stay_logged_in: Option<bool>,
    credential_revision: u64,
    credential_ack: u64,
    fresh_auth: auth_handoff::FreshAuthState,
    // Revoked before every new shared transport operation. Never serialized.
    inventory_network: std::sync::Arc<std::sync::atomic::AtomicU64>,
    credential_updates: Option<mpsc::UnboundedSender<CredentialEvent>>,
    // Installed only by one exclusive live read; no credentials/URLs/body.
    monitor_read_audit: Option<monitor::MonitorReadAudit>,
    base: url::Url,
    http: crate::platform::http::Client,
    session: Option<Session>,
    browser_credentials: Option<credentials::BrowserCredentials>,
    browser_local_read_only: bool,
    browser_prepared_transport_cancel: CancellationToken,
    browser_transport: bool,
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    browser_configured_native:Option<std::rc::Rc<browser::configured_native::OriginalConfiguredBrowser>>,
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    browser_normal_data_native:Option<std::rc::Rc<browser::configured_native::OriginalNormalBrowser>>,
    cookies: BTreeMap<String, String>,
    generation: u64,
    task_watch_authority: std::sync::Arc<project_task_watch::WatchAuthority>,
    task_watch_owner: Option<String>,
    user: Value,
    chats: BTreeMap<String, Value>,
    original_physical_draft_bounds:BTreeMap<String,browser::original_draft_bounds::OriginalPhysicalDraftBounds>,
    chat_arrival_order: Option<Vec<String>>,
    chat_list_freshness: chat_list_freshness::ChatListFreshness,
    cache_clock: Option<std::sync::Arc<dyn Fn() -> Option<CacheClockEvidence> + Send + Sync>>,
    wrappers: Vec<Value>,
    history: BTreeMap<String, Vec<Value>>,
    sync_message_windows: BTreeMap<String, sync_windows::CiphertextMessageWindow>,
    selected_first_pages: BTreeMap<String, selected_first_page::SelectedFirstPage>,
    // Ephemeral cursor context only; never cache/recovery/persistence authority.
    message_window_nonce: String,
    embeds: BTreeMap<String, Value>,
    saved_embed_selectors:Option<std::sync::Arc<saved_embed_selector::SavedEmbedSelectors>>,
    saved_embed_cache:saved_embed_selector::SelectorCache,
    embed_keys: Vec<Value>,
    direct_identity: Option<direct::DirectIdentity>,
    team_key: Option<(String, Key)>,
    team_wrapped_key: Option<(String, String)>,
    pair: Option<pair::PairState>,
    active_chat: Option<String>,
    // Identifiers only: volatile transcripts never enter the durable caches.
    ephemeral_chats: std::collections::BTreeSet<String>,
    operation_cancel: CancellationToken,
    operation_parent: CancellationToken,
    owned_operations:std::sync::Arc<owned_operation::OwnedOperationRegistry>,
    active_owned_operation:Option<owned_operation::OwnedOperationLease>,
    scoped_send_gate: std::sync::Arc<ScopedSendGate>,
    scoped_send_observation: Option<std::sync::Arc<std::sync::Mutex<ScopedSendObservation>>>,
    // Opaque original attempts only; no retry/effect/publication API. Bound new
    // admissions before effects instead of overwriting an unresolved envelope.
    scoped_send_quarantine: BTreeMap<String,std::sync::Arc<std::sync::Mutex<ScopedSendObservation>>> ,
    scoped_send_quarantine_bytes: usize,
    pub(super) monitor_cancel: Option<CancellationToken>,
    consent: Option<mpsc::UnboundedReceiver<(String, Vec<String>)>>,
    completion_recovery_mode: Option<CancellationToken>,
    completion_recovery_jobs: BTreeMap<String, CompletionRecoveryJob>,
    metadata_recovery_jobs: BTreeMap<String, CompletionRecoveryJob>,
    /// Last successful native session validation (see auth.rs reuse rules).
    recent_validation: Option<auth::RecentValidation>,
    /// Chats this client deleted (chat_tombstones.rs); display state only.
    deleted_chats: BTreeMap<String, u64>,
    /// Partially restored native cache content (cache_policy.rs).
    cached_content: cache_policy::CachedContentState,
    /// Cache-then-delta records for selected rich reads (chat_details_cache.rs).
    feed_prefetch: Option<sync_feed::FeedPrefetch>,
    /// Selected read round sent before admission (chat_details_overlap.rs).
    chat_details_overlap: Option<chat_details::ChatDetailsOverlap>,
    chat_details_cache: BTreeMap<String, chat_details_cache::ChatDetailsCache>,
    /// Incremental chat sync feed cursor and overview inputs (sync_feed.rs).
    chat_sync_feed: sync_feed::FeedState,
    /// Display name cached in the index section for the first paint (sync.rs).
    display_name_hint: Option<String>,
}
impl Client {
    /// Explicit validated application origin selected for this client.
    pub fn application_url(&self) -> String {
        self.app_url()
    }
    /// Construct with an explicit endpoint and optional explicit credentials.
    /// This never reads environment variables, files, keyrings or CLI profiles.
    pub fn new(api_url: &str, session: Option<Session>) -> Result<Self> {
        Self::with_options(api_url, session, ClientOptions::default())
    }
    pub fn with_options(
        api_url: &str,
        session: Option<Session>,
        options: ClientOptions,
    ) -> Result<Self> {
        #[cfg(target_arch = "wasm32")]
        if session.is_some() {
            return Err(Error::Unavailable {
                code: "browser_session_admission_required",
                reason: "BROWSER_SESSION_REQUIRES_EXPLICIT_WORKER_ADMISSION",
            });
        }
        let base = transport::validate_base(api_url)?;
        if let Some(app) = &options.app_url {
            transport::validate_app_origin(app)?;
        }
        if let Some(s) = &session {
            if transport::validate_base(&s.api_url)? != base {
                return Err(Error::Forbidden);
            }
            if s.paired_session_expires_at.is_some_and(|v| v <= now_ms()) {
                return Err(Error::Expired);
            }
        }
        Self::from_validated_transport(base,session,options)
    }
    // Shared allocation only. Public construction above retains every generic
    // URL/session/origin validator; the other caller owns an original native
    // configured resource and supplies no native Session or caller URL grant.
    fn from_validated_transport(base:url::Url,session:Option<Session>,options:ClientOptions)->Result<Self>{
        let cookies = session
            .as_ref()
            .map(|s| s.cookies.clone())
            .unwrap_or_default();
        transport::cookie_header(&cookies)?;
        let http = crate::platform::http::client()?;
        let operation_parent = CancellationToken::new();
        Ok(Self {
            options,
            browser_authority: None,
            browser_password_transport: false,
            browser_password_stay_logged_in: None,
            credential_revision: 1,
            feed_prefetch: None,
            chat_details_overlap: None,
            credential_ack: 0,
            recent_validation: None,
            deleted_chats: BTreeMap::new(),
            cached_content: Default::default(),
            chat_details_cache: BTreeMap::new(),
            chat_sync_feed: Default::default(),
            display_name_hint: None,
            fresh_auth: Default::default(),
            inventory_network: std::sync::Arc::new(std::sync::atomic::AtomicU64::new(0)),
            credential_updates: None,
            monitor_read_audit: None,
            base,
            http,
            session,
            browser_credentials: None,
            browser_local_read_only: false,
            browser_prepared_transport_cancel: CancellationToken::new(),
            browser_transport: false,
            #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
            browser_configured_native:None,
            #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
            browser_normal_data_native:None,
            cookies,
            generation: 0,
            task_watch_authority: std::sync::Arc::new(project_task_watch::WatchAuthority::new()),
            task_watch_owner: None,
            user: Value::Null,
            chats: BTreeMap::new(),
            original_physical_draft_bounds:BTreeMap::new(),
            chat_arrival_order: None,
            chat_list_freshness: Default::default(),
            cache_clock: None,
            wrappers: vec![],
            history: BTreeMap::new(),
            sync_message_windows: BTreeMap::new(),
            selected_first_pages: BTreeMap::new(),
            message_window_nonce: uuid::Uuid::new_v4().to_string(),
            embeds: BTreeMap::new(),
            saved_embed_selectors:None,
            saved_embed_cache:saved_embed_selector::SelectorCache::Absent,
            embed_keys: vec![],
            direct_identity: None,
            team_key: None,
            team_wrapped_key: None,
            pair: None,
            active_chat: None,
            ephemeral_chats: Default::default(),
            operation_cancel: operation_parent.child_token(),
            operation_parent,
            owned_operations:Default::default(),
            active_owned_operation:None,
            scoped_send_gate: Default::default(),
            scoped_send_observation: None,
            scoped_send_quarantine: BTreeMap::new(),
            scoped_send_quarantine_bytes:0,
            monitor_cancel: None,
            consent: None,
            completion_recovery_mode: None,
            completion_recovery_jobs: BTreeMap::new(),
            metadata_recovery_jobs: BTreeMap::new(),
        })
    }
    pub fn reset(&mut self, api: &str, session: Option<Session>) -> Result<()> {
        let mut next = Self::with_options(api, session, self.options.clone())?;
        next.credential_revision = self.credential_revision;
        next.credential_updates = self.credential_updates.take();
        next.consent = self.consent.take();
        next.ephemeral_chats = std::mem::take(&mut self.ephemeral_chats);
        next.operation_parent = self.operation_parent.clone();
        next.operation_cancel = next.operation_parent.child_token();
        *self = next;
        self.credentials_changed();
        Ok(())
    }
    /// Volatile chat identifiers cannot be used for drafts or saved-chat writes.
    /// Applications must also exclude these identifiers from their own journals.
    pub fn is_ephemeral_chat(&self, id: &str) -> bool {
        self.ephemeral_chats.contains(id) || id.starts_with("anonymous-")
    }
    pub fn workflows(&mut self) -> crate::work::Workflows<'_> {
        let team = self.require_credentials().ok().and_then(|s| s.active_team_id.clone());
        crate::work::Workflows::cookie(self, team)
    }
    pub fn projects(&mut self) -> crate::work::Projects<'_> {
        let team = self.require_credentials().ok().and_then(|s| s.active_team_id.clone());
        let cancel = self.operation_cancel.clone();
        crate::work::Projects::cookie(self, team, cancel)
    }
    pub fn plans(&mut self) -> crate::work::Plans<'_> {
        let team = self.require_credentials().ok().and_then(|s| s.active_team_id.clone());
        crate::work::Plans::cookie(self, team)
    }
    pub(crate) async fn work_chat_key(&mut self, id: &str) -> Result<Key> {
        self.open_chat(id).await?;
        let wrapping = self.wrapping_key().await?;
        self.chat_key(self.chats.get(id).ok_or(Error::Protocol)?, &wrapping)
    }
    pub fn tasks(&mut self) -> crate::work::Tasks<'_> {
        let team = self.require_credentials().ok().and_then(|s| s.active_team_id.clone());
        crate::work::Tasks::cookie(self, team)
    }
    pub(crate) fn work_master_key(&self) -> Result<Key> {
        Ok(self.native_master_key()?.clone())
    }
    pub(crate) fn work_team(&self) -> Result<Option<String>> {
        Ok(self.team()?.map(str::to_owned))
    }
    pub(crate) fn work_origin(&self) -> String {
        self.base.origin().ascii_serialization()
    }
    pub fn session(&self) -> Option<&Session> {
        if self.browser_cookies() {
            return None;
        }
        self.session.as_ref()
    }
    pub fn clone_session(&self) -> Option<Session> {
        if self.browser_cookies() {
            return None;
        }
        self.session.clone()
    }
    pub fn user(&self) -> &Value {
        &self.user
    }
    /// The account display name: live user data, else the cached index hint.
    pub fn display_name_hint(&self) -> Option<String> {
        ["username", "display_name"]
            .into_iter()
            .filter_map(|key| self.user[key].as_str())
            .find(|name| !name.is_empty())
            .map(str::to_owned)
            .or_else(|| self.display_name_hint.clone())
    }
    /// Detach credentials and clear all client-owned account state.
    pub fn take_session(&mut self) -> Option<Session> {
        if self.browser_cookies() {
            return None;
        }
        let session = self.session.take();
        self.forget_session();
        session
    }
    pub fn options(&self) -> &ClientOptions {
        &self.options
    }
    pub fn set_interactive(&mut self, interactive: bool) {
        self.owned_operations.invalidate();
        self.scoped_send_gate.invalidate_publications();
        self.fresh_auth.advance_operation();
        self.options.interactive = interactive;
    }
    pub(super) fn lifecycle(&self) -> Value {
        let interactive = self.options.identity == ClientIdentity::Cli && self.options.interactive;
        // An active socket can finish encrypted recovery without representing a
        // human viewer. The CLI baseline announces both concepts separately.
        json!({"client_type":self.options.identity.header(),"is_foreground":true,"interactive":interactive})
    }
    pub fn set_identity(&mut self, identity: ClientIdentity) {
        self.owned_operations.invalidate();
        self.scoped_send_gate.invalidate_publications();
        self.fresh_auth.advance_operation();
        self.options.identity = identity;
    }
    pub fn set_private_operation_gate(
        &mut self,
        gate: Option<std::sync::Arc<dyn Fn() -> Result<()> + Send + Sync>>,
    ) {
        self.scoped_send_gate.invalidate_publications();
        self.fresh_auth.advance_operation();
        self.owned_operations.invalidate();
        self.options.private_operation_gate = gate;
    }
    pub fn set_app_origin(&mut self, origin: Option<String>) -> Result<()> {
        self.owned_operations.invalidate();
        self.scoped_send_gate.invalidate_publications();
        self.fresh_auth.advance_operation();
        if let Some(origin) = &origin {
            transport::validate_app_origin(origin)?;
        }
        self.options.app_url = origin;
        Ok(())
    }
    pub fn set_privacy_options(&mut self, privacy: crate::privacy::PrivacyOptions) {
        self.owned_operations.invalidate();
        self.scoped_send_gate.invalidate_publications();
        self.fresh_auth.advance_operation();
        self.options.privacy = privacy;
    }
    pub(crate) fn verify_private_operation(&self) -> Result<()> {
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if self.browser_normal_data_native.is_some(){return Err(Error::Forbidden)}
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if let Some(original)=&self.browser_configured_native{original.check_client(self)?;}
        self.options.privacy.verify()?;
        if let Some(gate) = &self.options.private_operation_gate {
            gate()?;
        }
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if let Some(original)=&self.browser_configured_native{original.check_client(self)?;}
        Ok(())
    }
    pub fn credential_snapshot(&self) -> Option<CredentialSnapshot> {
        if self.browser_cookies() {
            return None;
        }
        self.session.clone().map(|session| CredentialSnapshot {
            revision: self.credential_revision,
            session,
        })
    }
    /// Call only after the exact snapshot has been persisted successfully.
    pub fn acknowledge_credentials(&mut self, revision: u64) -> Result<()> {
        if self.browser_cookies(){return Err(Error::Forbidden);}
        self.require_session()?;
        if revision != self.credential_revision {
            return Err(Error::Cancelled);
        }
        self.credential_ack = revision;
        Ok(())
    }
    pub fn set_credential_updates(&mut self, updates: mpsc::UnboundedSender<CredentialEvent>) {
        self.credential_updates = Some(updates);
        self.publish_credentials();
    }
    fn invalidate_task_watches(&mut self) {
        self.task_watch_authority.cancel.cancel();
        self.task_watch_authority = std::sync::Arc::new(project_task_watch::WatchAuthority::new());
        self.task_watch_owner = None;
    }
    fn credentials_changed(&mut self) {
        let owner = self.user["id"]
            .as_str()
            .filter(|id| !id.is_empty())
            .or_else(|| self.user["user_id"].as_str().filter(|id| !id.is_empty()))
            .map(str::to_owned);
        if self
            .task_watch_owner
            .as_ref()
            .is_some_and(|previous| Some(previous) != owner.as_ref())
        {
            self.invalidate_task_watches();
        }
        self.task_watch_owner = owner;
        self.credential_revision = self.credential_revision.wrapping_add(1);
        self.credential_ack = 0;
        self.publish_credentials();
    }
    fn publish_credentials(&self) {
        if let Some(updates) = &self.credential_updates {
            let event = match self.credential_snapshot() {
                Some(snapshot) => CredentialEvent::Updated(Box::new(snapshot)),
                None => CredentialEvent::Cleared {
                    revision: self.credential_revision,
                },
            };
            let _ = updates.send(event);
        }
    }
    pub(crate) fn require_session(&self) -> Result<&Session> {
        let s = self.session.as_ref().ok_or_else(|| if self.browser_credentials.is_some() {
            Error::Unavailable { code:"native_session_required", reason:"THIS_OPERATION_REQUIRES_NATIVE_SESSION_MATERIAL" }
        } else { Error::Authentication })?;
        if s.paired_session_expires_at.is_some_and(|v| v <= now_ms()) {
            return Err(Error::Expired);
        }
        Ok(s)
    }
    pub fn set_team(&mut self, team: Option<&str>) -> Result<()> {
        if let Some(t) = &team {
            uuid::Uuid::parse_str(t).map_err(|_| Error::Invalid("Invalid Team ID."))?;
        }
        self.fresh_auth.advance_operation();
        self.chat_list_freshness.invalidate();
        if let Some(browser)=self.browser_credentials.as_mut() {
            browser.active_team_id=team.map(str::to_owned);
        } else {
            self.session.as_mut().ok_or(Error::Authentication)?.active_team_id=team.map(str::to_owned);
        }
        if let Some(cancel) = self.monitor_cancel.take() {
            cancel.cancel()
        }
        self.invalidate_task_watches();
        self.generation = self.generation.wrapping_add(1);
        self.operation_cancel.cancel();
        self.operation_cancel = self.operation_parent.child_token();
        self.active_chat = None;
        self.clear_chat_rows();
        self.wrappers.clear();
        self.history.clear();
        self.sync_message_windows.clear();
        self.selected_first_pages.clear();
        self.embeds.clear();
        self.saved_embed_selectors=None;
        self.saved_embed_cache=saved_embed_selector::SelectorCache::Legacy;
        self.embed_keys.clear();
        self.cached_content = Default::default();
        self.chat_details_cache.clear();
        self.direct_identity = None;
        self.team_key = None;
        self.team_wrapped_key = None;
        self.credentials_changed();
        Ok(())
    }
    fn team(&self) -> Result<Option<&str>> {
        Ok(self.require_credentials()?.active_team_id.as_deref())
    }
    fn scoped(&self, path: &str) -> Result<String> {
        let mut url = self.url(path)?;
        if let Some(team) = self.team()? {
            url.query_pairs_mut().append_pair("team_id", team);
        }
        Ok(format!(
            "{}{}",
            self.request_route_path(&url)?,
            url.query().map(|q| format!("?{q}")).unwrap_or_default()
        ))
    }
    /// Prepare only from an established actual original context. This does not
    /// grant server access or turn admission and never discovers credentials.
    #[doc(hidden)]
    pub fn prepare_scoped_saved_send(&self, chat: Option<&str>, request: CancellationToken) -> Result<PreparedSavedSend> {
        self.require_credentials()?; self.require_canonical_read_profile()?; self.verify_private_operation()?;
        if self.user["id"].as_str().filter(|id| !id.is_empty())
            .or_else(|| self.user["user_id"].as_str().filter(|id| !id.is_empty())).is_none()
            || self.operation_parent.is_cancelled() || self.operation_cancel.is_cancelled() { return Err(Error::Cancelled); }
        if let Some(chat) = chat { uuid::Uuid::parse_str(chat).map_err(|_| Error::Invalid("A full chat ID is required."))?; }
        self.scoped_send_gate.admit()?;
        let scope = sync_capability::AsyncCryptoScope::begin(self)?;
        if let Some(chat) = chat { scope.check_chat(self, chat)?; }
        Ok(PreparedSavedSend { id: uuid::Uuid::new_v4().to_string(), chat: chat.map(str::to_owned), request,
            child: self.operation_parent.child_token(), publication: CancellationToken::new(),
            parent: self.operation_parent.clone(), scope, epoch: self.fresh_auth.operation_epoch(),
            gate: self.scoped_send_gate.clone(), private_gate: self.options.private_operation_gate.clone() })
    }
    /// Imported native credentials may have no user yet. Establish that original
    /// identity through the existing real authentication before issuing a scope;
    /// never relabel an empty-owner scope after the send has already done IO.
    #[doc(hidden)]
    pub async fn prepare_validated_scoped_saved_send(&mut self, chat: Option<&str>, request: CancellationToken) -> Result<PreparedSavedSend> {
        self.verify_private_operation()?;
        if self.user["id"].as_str().filter(|id| !id.is_empty())
            .or_else(|| self.user["user_id"].as_str().filter(|id| !id.is_empty())).is_none() {
            if request.is_cancelled() { return Err(Error::Cancelled); }
            self.validate_session().await?;
        }
        self.prepare_scoped_saved_send(chat, request)
    }
    /// The shared driver owns the actual future to its terminal, including an
    /// uncertain admitted send. Request cancellation never drops that future or
    /// cancels the original context parent. No journal/cache reset or replay.
    #[doc(hidden)]
    pub async fn run_prepared_saved_send(&mut self, prepared: PreparedSavedSend, text: &str,
        updates: mpsc::Sender<StreamUpdate>) -> Result<SavedSendTerminal> {
        prepared.scope.check(self)?; self.verify_private_operation()?;
        if prepared.parent.is_cancelled() || prepared.parent != self.operation_parent
            || prepared.epoch != self.fresh_auth.operation_epoch()
            || !std::sync::Arc::ptr_eq(&prepared.gate, &self.scoped_send_gate)
            || !same_private_gate(&prepared.private_gate, &self.options.private_operation_gate) { return Err(Error::Cancelled); }
        prepared.gate.start(&prepared.id, &prepared.publication)?;
        let child = prepared.child;
        self.fresh_auth.advance_operation(); self.operation_cancel.cancel(); self.operation_cancel = child.clone();
        // Synchronous owned transition only: no auth/owner/key/context changes
        // or awaited work occur between the original check and this child scope.
        let scope = match sync_capability::AsyncCryptoScope::begin(self) {
            Ok(scope) => scope, Err(error) => { prepared.gate.finish(&prepared.id, false); child.cancel(); return Err(error); }
        };
        let execution = ScopedSendExecution { request:prepared.request.clone(), id: prepared.id, chat: prepared.chat, parent: prepared.parent,
            child: child.clone(), scope, epoch: self.fresh_auth.operation_epoch(), gate: prepared.gate,
            private_gate: prepared.private_gate, consumed: false, publication: prepared.publication };
        if prepared.request.is_cancelled() { child.cancel(); }
        let selected = execution.chat.clone();
        let observation = std::sync::Arc::new(std::sync::Mutex::new(ScopedSendObservation::default()));
        self.scoped_send_observation = Some(observation.clone());
        let result = if self.scoped_send_quarantine.len()>=MAX_SCOPED_SAVED_SEND_QUARANTINES
            || self.scoped_send_quarantine_bytes>=MAX_SCOPED_SAVED_SEND_QUARANTINE_BYTES {
            Err(Error::Conflict)
        } else {
            let running = self.send_message(selected.as_deref(), text, updates, child.clone());
            tokio::pin!(running);
            tokio::select! { biased;
                result = &mut running => result,
                _ = prepared.request.cancelled() => { child.cancel(); running.await }
            }
        };
        // The actual future returned. Keep original uncertain identity available
        // for existing recovery; no replay, journal clearing or new turn IDs.
        let (attempted, recovery) = {
            let observed = observation.lock().map_err(|_| Error::Cancelled)?;
            if observed.attempted && observed.admission.is_none() { return Err(Error::Protocol); }
            (observed.attempted, observed.identity.clone())
        };
        if !attempted || result.is_ok() { self.scoped_send_observation = None; }
        let result = result.map(plaintext::Plain::new);
        let outcome = match &result {
            Ok(chat) if selected.as_deref().is_none_or(|id| chat.id == id) => SavedSendOutcome::Completed,
            Ok(_) => SavedSendOutcome::SessionExpired,
            Err(Error::Conflict) if !attempted => SavedSendOutcome::Backpressure,
            Err(Error::Cancelled) if attempted => SavedSendOutcome::Uncertain,
            Err(Error::Cancelled) => SavedSendOutcome::Cancelled,
            Err(Error::Expired | Error::Authentication | Error::Forbidden) => SavedSendOutcome::SessionExpired,
            Err(_) if attempted => SavedSendOutcome::Uncertain,
            Err(_) => SavedSendOutcome::Unavailable,
        };
        Ok(SavedSendTerminal { execution: Some(execution), result: Some(result), outcome, recovery })
    }
    /// Consumes a terminal issued only after the SDK future returned. Validate
    /// BEFORE rearm, ignoring only this exact child's cancellation; root/policy/
    /// owner/key/reset/epoch/TTL/denial drift still refuses. Never uncancel it.
    #[doc(hidden)]
    pub fn take_scoped_saved_send_terminal(&mut self, mut terminal: SavedSendTerminal) -> Result<SavedSendDisposition> {
        let execution = terminal.execution.take().ok_or(Error::Cancelled)?;
        self.verify_private_operation()?;
        if execution.publication.is_cancelled() || execution.parent.is_cancelled() || execution.parent != self.operation_parent
            || execution.child != self.operation_cancel || execution.epoch != self.fresh_auth.operation_epoch()
            || !std::sync::Arc::ptr_eq(&execution.gate, &self.scoped_send_gate)
            || !same_private_gate(&execution.private_gate, &self.options.private_operation_gate) { return Err(Error::Cancelled); }
        execution.scope.check_terminated_child_context(self)?;
        if let Some(chat) = execution.chat.as_deref() {
            if !self.task_watch_authority.cached_chat_allowed(chat) { return Err(Error::Forbidden); }
        }
        let reusable = matches!(terminal.outcome, SavedSendOutcome::Completed | SavedSendOutcome::Cancelled | SavedSendOutcome::Uncertain | SavedSendOutcome::Backpressure);
        if terminal.outcome==SavedSendOutcome::Uncertain {
            if self.scoped_send_quarantine.contains_key(&execution.id)
                || self.scoped_send_quarantine.len()>=MAX_SCOPED_SAVED_SEND_QUARANTINES { return Err(Error::Conflict); }
            let observation=self.scoped_send_observation.as_ref().ok_or(Error::Cancelled)?;
            let original=observation.lock().map_err(|_|Error::Cancelled)?;
            if !original.attempted || original.admission.is_none()
                || original.identity.as_ref().map(|id|id.turn_id())!=terminal.recovery.as_ref().map(|id|id.turn_id()) {
                return Err(Error::Cancelled);
            }
            let bytes=self.scoped_send_quarantine_bytes.checked_add(original.admission_bytes)
                .filter(|total|*total<=MAX_SCOPED_SAVED_SEND_QUARANTINE_BYTES).ok_or(Error::Conflict)?;
            drop(original);
            // Original root/account/key/policy validation above authorizes only
            // continuation. This exact old attempt is neither replayed nor ACKed.
            self.scoped_send_quarantine.insert(execution.id.clone(),observation.clone());
            self.scoped_send_quarantine_bytes=bytes;
            self.scoped_send_observation=None;
        }
        let child = if reusable {
            let next = execution.parent.child_token();
            self.fresh_auth.advance_operation(); self.operation_cancel = next.clone();
            execution.scope.check_owned_child_transition(self, &next)?;
            next
        } else { execution.child.clone() };
        let mut disposition = SavedSendDisposition { epoch: self.fresh_auth.operation_epoch(), receipt: uuid::Uuid::new_v4().to_string(),
            child, cancelled_result:matches!(terminal.result.as_ref(),Some(Err(Error::Cancelled))), result: terminal.result.take(), outcome: terminal.outcome, reusable, recovery: terminal.recovery.take(), execution: {
                execution
            } };
        disposition.check_current(self)?;
        disposition.execution.consumed = true;
        disposition.execution.gate.finish(&disposition.execution.id, reusable);
        Ok(disposition)
    }
    fn current_operation_child(&self)->CancellationToken{
        self.active_owned_operation.as_ref().map(|operation|operation.child().clone()).unwrap_or_else(||self.operation_cancel.clone())
    }
    pub fn set_operation_cancel(&mut self, cancel: CancellationToken) {
        if self.operation_parent!=cancel || cancel.is_cancelled(){self.owned_operations.invalidate();}
        self.scoped_send_gate.invalidate_publications();
        // A live same-parent child replacement is plumbing, not cancellation.
        // An already cancelled child or a different caller starts a new epoch;
        // even an externally held one-use handoff cannot resurrect that work.
        if self.operation_cancel.is_cancelled()
            || self.operation_parent != cancel
            || cancel.is_cancelled()
        {
            self.fresh_auth.advance_operation();
        }
        self.operation_cancel.cancel();
        self.operation_cancel = cancel.child_token();
        self.operation_parent = cancel;
    }
    pub fn set_consent_receiver(
        &mut self,
        receiver: mpsc::UnboundedReceiver<(String, Vec<String>)>,
    ) {
        self.consent = Some(receiver)
    }
    pub(super) fn clear_account_cache(&mut self) {
        self.owned_operations.invalidate();
        self.fresh_auth.advance_operation();
        self.chat_list_freshness.invalidate();
        if let Some(mode) = self.completion_recovery_mode.take() {
            mode.cancel()
        }
        self.scoped_send_observation = None;
        self.scoped_send_quarantine.clear();
        self.scoped_send_quarantine_bytes=0;
        self.completion_recovery_jobs.clear();
        self.metadata_recovery_jobs.clear();
        if let Some(cancel) = self.monitor_cancel.take() {
            cancel.cancel()
        }
        self.operation_cancel.cancel();
        self.operation_cancel = self.operation_parent.child_token();
        self.active_chat = None;
        self.clear_chat_rows();
        self.wrappers.clear();
        self.history.clear();
        self.sync_message_windows.clear();
        self.selected_first_pages.clear();
        self.embeds.clear();
        self.embed_keys.clear();
        self.cached_content = Default::default();
        self.chat_details_cache.clear();
        self.display_name_hint = None;
        crate::model::zeroize_json(&mut self.user);
        self.saved_embed_selectors=None;
        self.saved_embed_cache=saved_embed_selector::SelectorCache::Legacy;
        self.user = Value::Null;
        self.direct_identity = None;
        self.team_key = None;
        self.team_wrapped_key = None;
        self.invalidate_task_watches();
        self.generation = self.generation.wrapping_add(1);
    }
    pub fn forget_session(&mut self) {
        self.retire_browser_prepared_transports();
        let browser_transport=self.browser_cookies();
        self.browser_transport |= browser_transport;
        self.browser_authority = None;
        self.session = None;
        self.browser_credentials = None;
        self.browser_local_read_only = false;
        for cookie in self.cookies.values_mut(){zeroize::Zeroize::zeroize(cookie);}
        self.cookies.clear();
        self.pair = None;
        self.clear_account_cache();
        self.credentials_changed();
    }
    pub async fn logout(&mut self) -> Result<()> {
        let browser = self.browser_cookies();
        let owner_guard=self.require_browser_owner_guards();
        let expected_principal=self.expected_request_principal()?;
        let cookie = zeroize::Zeroizing::new(transport::cookie_header(&self.cookies)?);
        let url = self.url("/v1/auth/logout")?;
        let origin = self.app_url();
        let http = self.http.clone();
        self.forget_session();
        owner_guard?; // unsupported browser remote effects refuse; explicit local forgetting already settled
        if cookie.is_empty() && !browser {
            return Ok(());
        }
        crate::platform::time::timeout(Duration::from_secs(3), async {
            let mut request = http
                .post(url)
                .header("Origin", origin)
                .header("X-OpenMates-SDK", self.options.identity.header())
                .json(&json!({}));
            if let Some(expected)=expected_principal.as_deref(){request=request.header("X-OpenMates-Expected-Principal",expected);}
            if !cookie.is_empty() {
                request = request.header("Cookie", cookie.as_str());
            }
            let mut response = crate::platform::http::browser_credentials(request, browser)
                .send()
                .await
                .map_err(|_| Error::Offline)?;
            let status = response.status();
            if matches!(status.as_u16(), 401 | 410) {
                return Ok(());
            }
            if !status.is_success() {
                return Err(if status.as_u16() == 403 || status.is_redirection() {
                    Error::Forbidden
                } else {
                    Error::Offline
                });
            }
            let mut bytes = Vec::new();
            while let Some(chunk) = response.chunk().await.map_err(|_| Error::Offline)? {
                if bytes.len() + chunk.len() > 65_536 {
                    return Err(Error::Protocol);
                }
                bytes.extend_from_slice(&chunk);
            }
            let result: Value = serde_json::from_slice(&bytes)?;
            if result["success"] != true {
                return Err(Error::Protocol);
            }
            Ok(())
        })
        .await
        .map_err(|_| Error::Offline)?
    }
}
pub(crate) fn now_ms() -> u64 {
    crate::platform::unix_ms()
}
fn text<'a>(value: &'a Value, key: &str) -> &'a str {
    value.get(key).and_then(Value::as_str).unwrap_or("")
}
fn required<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    let s = text(value, key);
    if s.is_empty() {
        Err(Error::Protocol)
    } else {
        Ok(s)
    }
}
fn segment(value: &str) -> String {
    url::form_urlencoded::byte_serialize(value.as_bytes()).collect()
}
fn sha256(value: &str) -> String {
    use sha2::{Digest, Sha256};
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
fn key_from_bytes(bytes: &[u8]) -> Result<Key> {
    let data: [u8; 32] = bytes.try_into().map_err(|_| Error::Crypto)?;
    Ok(zeroize::Zeroizing::new(data))
}

impl Drop for Client {
    fn drop(&mut self) {
        self.owned_operations.invalidate();
        self.scoped_send_gate.close();
        self.task_watch_authority.cancel.cancel();
        if let Some(cancel) = self.monitor_cancel.take() {
            cancel.cancel();
        }
        self.operation_cancel.cancel();
        for cookie in self.cookies.values_mut() {
            zeroize::Zeroize::zeroize(cookie);
        }
    }
}

#[cfg(test)]
mod sdk_boundary_tests {
    use super::*;
    pub(super) fn session() -> Session {
        Session {
            api_url: "https://api.example.org".into(),
            session_id: "fixture".into(),
            cookies: BTreeMap::new(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([1; 32]),
            hashed_email: "hash".into(),
            user_email_salt: "salt".into(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }
    }
    fn deny() -> Result<()> {
        Err(Error::Forbidden)
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn drop_and_reset_cancel_owned_lifecycle_tasks() {
        let mut client = Client::new("https://api.example.org", None).unwrap();
        let monitor = CancellationToken::new();
        let operation = client.operation_cancel.clone();
        client.monitor_cancel = Some(monitor.clone());
        client.set_private_operation_gate(Some(std::sync::Arc::new(deny)));
        client.reset("https://api.example.org", None).unwrap();
        assert!(monitor.is_cancelled());
        assert!(operation.is_cancelled());
        assert!(matches!(
            client.verify_private_operation(),
            Err(Error::Forbidden)
        ));
        let monitor = CancellationToken::new();
        let operation = client.operation_cancel.clone();
        client.monitor_cancel = Some(monitor.clone());
        drop(client);
        assert!(monitor.is_cancelled());
        assert!(operation.is_cancelled());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn caller_cancellation_is_downward_only_across_scope_reset_and_drop() {
        let parent = CancellationToken::new();
        let mut client = Client::new("https://api.example.org", Some(session())).unwrap();
        client.set_operation_cancel(parent.clone());
        let initial = client.operation_cancel.clone();
        client
            .set_team(Some("00000000-0000-0000-0000-000000000001"))
            .unwrap();
        assert!(initial.is_cancelled());
        assert!(!parent.is_cancelled());
        let scoped = client.operation_cancel.clone();
        client
            .reset("https://api.example.org", Some(session()))
            .unwrap();
        assert!(scoped.is_cancelled());
        assert!(!parent.is_cancelled());
        let reset = client.operation_cancel.clone();
        parent.cancel();
        assert!(reset.is_cancelled());
        let parent = CancellationToken::new();
        client.set_operation_cancel(parent.clone());
        let child = client.operation_cancel.clone();
        drop(client);
        assert!(child.is_cancelled());
        assert!(!parent.is_cancelled());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn cancelled_caller_prevents_request_dispatch_after_scope_change() {
        let parent = CancellationToken::new();
        let mut client = Client::new("https://api.example.org", Some(session())).unwrap();
        client.set_operation_cancel(parent.clone());
        client.set_team(None).unwrap();
        parent.cancel();
        assert_eq!(
            client.request(Method::GET, "/v1/user-tasks", None).await,
            Err(Error::Cancelled)
        );
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn credential_acknowledgement_is_bound_to_exact_snapshot() {
        let mut client = Client::new("https://api.example.org", Some(session())).unwrap();
        let (tx, mut rx) = mpsc::unbounded_channel();
        client.set_credential_updates(tx);
        let CredentialEvent::Updated(initial) = rx.try_recv().unwrap() else {
            panic!("snapshot")
        };
        client.acknowledge_credentials(initial.revision).unwrap();
        client
            .set_team(Some("00000000-0000-0000-0000-000000000001"))
            .unwrap();
        assert!(matches!(
            client.acknowledge_credentials(initial.revision),
            Err(Error::Cancelled)
        ));
        let CredentialEvent::Updated(updated) = rx.try_recv().unwrap() else {
            panic!("snapshot")
        };
        assert!(updated.revision > initial.revision);
        client.acknowledge_credentials(updated.revision).unwrap();
        client.forget_session();
        assert!(matches!(
            rx.try_recv().unwrap(),
            CredentialEvent::Cleared { .. }
        ));
        assert!(client.credential_snapshot().is_none());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn enabled_enhanced_privacy_and_explicit_policy_fail_before_dispatch() {
        let mut client = Client::with_options(
            "https://api.example.org",
            None,
            ClientOptions {
                privacy: crate::privacy::PrivacyOptions { enhanced: true },
                ..ClientOptions::default()
            },
        )
        .unwrap();
        let (tx, _) = mpsc::channel(1);
        assert!(matches!(
            client
                .send_message(None, "private input", tx, CancellationToken::new())
                .await,
            Err(Error::Invalid(_))
        ));
        client.set_privacy_options(crate::privacy::PrivacyOptions::default());
        client.set_private_operation_gate(Some(std::sync::Arc::new(deny)));
        assert!(matches!(
            client.run_app_skill(json!({})).await,
            Err(Error::Forbidden)
        ));
    }
}

#[cfg(test)]
mod lifecycle_tests {
    use super::*;
    use futures_util::{SinkExt, StreamExt};
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio_tungstenite::tungstenite::Message;
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation

    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn active_sockets_are_foreground_without_inventing_human_interactivity() {
        for identity in [
            ClientIdentity::Rust,
            ClientIdentity::Npm,
            ClientIdentity::Pip,
            ClientIdentity::Cli,
        ] {
            for interactive in [false, true] {
                let client = Client::with_options(
                    "https://never-contact.example.invalid",
                    None,
                    ClientOptions {
                        identity,
                        interactive,
                        ..ClientOptions::default()
                    },
                )
                .unwrap();
                let lifecycle = client.lifecycle();
                assert_eq!(lifecycle["client_type"], identity.header());
                assert_eq!(lifecycle["is_foreground"], true);
                assert_eq!(
                    lifecycle["interactive"],
                    identity == ClientIdentity::Cli && interactive
                );
            }
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation

    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn noninteractive_chat_sync_receives_foreground_recovery_fence_in_either_order() {
        for (identity, recovery_first) in
            [(ClientIdentity::Rust, true), (ClientIdentity::Cli, false)]
        {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let address = listener.local_addr().unwrap();
            let server = tokio::spawn(async move {
                let (mut http, _) = listener.accept().await.unwrap();
                let mut request = Vec::new();
                loop {
                    let mut buffer = [0; 2048];
                    let size = http.read(&mut buffer).await.unwrap();
                    assert!(size > 0);
                    request.extend_from_slice(&buffer[..size]);
                    assert!(request.len() < 16_384);
                    if let Some(end) = request.windows(4).position(|p| p == b"\r\n\r\n") {
                        let headers = std::str::from_utf8(&request[..end]).unwrap();
                        let length = headers
                            .lines()
                            .find_map(|line| {
                                line.to_ascii_lowercase()
                                    .strip_prefix("content-length:")
                                    .map(|v| v.trim().parse::<usize>().unwrap())
                            })
                            .unwrap_or(0);
                        if request.len() >= end + 4 + length {
                            assert_eq!(
                                headers.lines().next().unwrap(),
                                "POST /v1/auth/session HTTP/1.1"
                            );
                            break;
                        }
                    }
                }
                let body = json!({"success":true,"ws_token":"synthetic-token","user":{"id":"synthetic-owner"}}).to_string();
                http.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
                drop(http);
                let (stream, _) = listener.accept().await.unwrap();
                let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
                let lifecycle: Value =
                    serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                        .unwrap();
                assert_eq!(lifecycle["type"], "native_client_lifecycle");
                assert_eq!(lifecycle["payload"]["is_foreground"], true);
                assert_eq!(lifecycle["payload"]["interactive"], false);
                assert_eq!(lifecycle["payload"]["client_type"], identity.header());
                let sync: Value =
                    serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                        .unwrap();
                assert_eq!(sync["type"], "phased_sync_request");
                assert_eq!(sync["payload"]["phase"], "all");
                ws.send(Message::Text(
                    json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":[]}})
                        .to_string()
                        .into(),
                ))
                .await
                .unwrap();
                let recovery = json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"completed"}});
                let sync = json!({"type":"phased_sync_complete","payload":{"phase":"all"}});
                // The real backend starts this discovery only for foreground
                // sockets. Preserve both terminal fences rather than skipping
                // recovery when the SDK caller is not a human viewer.
                for frame in if recovery_first {
                    [recovery, sync]
                } else {
                    [sync, recovery]
                } {
                    ws.send(Message::Text(frame.to_string().into()))
                        .await
                        .unwrap();
                }
                assert!(matches!(
                    ws.next().await.unwrap().unwrap(),
                    Message::Close(_)
                ));
            });
            let base = format!("http://{address}");
            let mut session = super::sdk_boundary_tests::session();
            session.api_url = base.clone();
            let mut client = Client::with_options(
                &base,
                Some(session),
                ClientOptions {
                    identity,
                    ..ClientOptions::default()
                },
            )
            .unwrap();
            let result = crate::platform::time::timeout(
                Duration::from_secs(3),
                client.list(Workspace::Chats),
            )
            .await
            .unwrap()
            .unwrap();
            assert!(result.is_empty());
            server.await.unwrap();
        }
    }
}

pub use monitor::{BrowserMetadataMonitorRefresh, BrowserMetadataMonitorPublication};

pub use monitor::BrowserIncomingCachePublication;

#[cfg(all(test, not(target_arch="wasm32")))]
#[path="client/scoped_saved_send_tests.rs"]
mod scoped_saved_send_tests;

#[cfg(target_arch="wasm32")]
#[doc(hidden)]
pub use browser::{BrowserOriginalHintRecoveryCheckpointReadiness,BrowserOriginalHintRecoveryCheckpointRead,BrowserOriginalHintRecoveryCheckpointReadResult,BrowserOriginalHintRecoveryCheckpointNativeWrite,BrowserOriginalHintRecoveryCheckpointNativeWriteResult,BrowserOriginalHintRecoveryCheckpointReadbackCrypto,BrowserOriginalHintRecoveryCheckpointVerified,BrowserOriginalHintRecoveryCheckpointDurable};

#[cfg(target_arch="wasm32")]
#[doc(hidden)]
pub use browser::OriginalPhysicalDraftInventory;

#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
#[doc(hidden)]
pub use browser::{BrowserMetadataBootstrap,MetadataOpaqueStored,MetadataNativeIoTicket,close_native_metadata_io_only};

#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use browser::{CapturedInitialSyncStore,BoundInitialSyncStore,StartupMetadataStoreDriver,StartupMetadataStored,StartupMetadataNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use browser::{BrowserMetadataRecoveryFinalize,BrowserMetadataRecoveryLocalStored,BrowserMetadataRecoveryNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use browser::{BrowserMainMetadataStore,BrowserMainMetadataStored,BrowserMainMetadataNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use browser::{BrowserRecoveredReplyStore,BrowserRecoveredReplyControl,BrowserRecoveredReplyStored,BrowserRecoveredReplyNativeTerminal};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use browser::{BrowserMainCodeEmbedStore,BrowserMainCodeEmbedControl,BrowserMainCodeEmbedStored,BrowserMainCodeEmbedNativeTerminal};
#[cfg(any(test,all(target_arch="wasm32",feature="browser-metadata-prototype")))]
#[path="client/browser_main_code_embed_policy.rs"]
mod main_code_embed_policy;
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(crate) use completion_recovery::OriginalRecoveryRetirementTicket;

#[cfg(not(target_arch="wasm32"))]
pub mod ephemeral_metadata;
