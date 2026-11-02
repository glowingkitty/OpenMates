//! Idle account and Team revocation monitoring. Spawned tasks own a socket and
//! public context hash, never account Sessions, master keys, or wrapping keys.
use super::transport::{self, Socket};
use super::plaintext::Plain;
use super::sync_capability::AsyncCryptoScope;
use super::*;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};
use tokio::sync::Notify;
#[path = "cached_view.rs"]
pub mod cached_view;
#[path = "monitor_actor.rs"]
mod actor;
#[path="initial_sync.rs"]
mod initial_sync;
pub use initial_sync::{PreparedInitialSync,InitialSyncControl,InitialSyncRead,InitialSyncMetadataBatch};
#[path="monitor_start_owned.rs"]
mod owned_start;
pub use owned_start::{PreparedOwnedChatMonitor,OwnedChatMonitorStartStep,OwnedChatMonitorStartApply,OwnedChatMonitorReady,OwnedChatMonitorStartControl,OwnedChatMonitorStartTerminal};
pub(in crate::client) use actor::{MonitorReadRequest,MonitorReadData,MonitorDraftVersions,PreparedMonitorRead,MonitorReadReceipt};
const MAX_HINTS: usize = 100;

#[path="monitor_hint_work.rs"]
mod hint_work;
pub(in crate::client) use hint_work::{RecoveryHintKind,RecoveryHintManifest};
use hint_work::RecoveryHintJobs;

// No payload, credentials, keys, ciphertext, or plaintext enter this mailbox.
#[derive(Default)]
struct Pending {
    refresh: bool,
    chats: BTreeSet<String>,
    recovery: BTreeSet<String>,
    recovery_jobs: RecoveryHintJobs,
    versions: BTreeMap<String, VersionFloor>,
}
#[derive(Default, Clone, Copy)]
struct VersionFloor {
    messages_v: u64,
    metadata_v: u64,
    draft_v: u64,
}
fn version(value: &Value, field: &str) -> Result<u64> {
    match value.get(field) {
        None | Some(Value::Null) => Ok(0),
        Some(value) => value.as_u64().ok_or(Error::Protocol),
    }
}
fn data_version(row: &Value, field: &str) -> Result<u64> {
    Ok(version(row, field)?.max(version(&row["versions"], field)?))
}
fn metadata_version(row: &Value) -> Result<u64> {
    let metadata = data_version(row, "metadata_v")?;
    Ok(if metadata > 0 {
        metadata
    } else {
        data_version(row, "title_v")?
    })
}
fn active_draft(row: &Value) -> Result<bool> {
    let mut active = false;
    for field in ["encrypted_draft_md", "encrypted_draft_preview"] {
        match row.get(field) {
            None | Some(Value::Null) => {}
            Some(Value::String(value)) => active |= !value.is_empty(),
            Some(_) => return Err(Error::Protocol),
        }
    }
    Ok(active)
}
fn matches_revision_floor(row: &Value, floor: &VersionFloor) -> Result<bool> {
    // Canonical metadata omits a tombstone counter for authoritative no-draft.
    let draft_ok = !active_draft(row)? || data_version(row, "draft_v")? >= floor.draft_v;
    Ok(metadata_version(row)? >= floor.metadata_v && draft_ok)
}
fn matches_floor(row: &Value, floor: &VersionFloor) -> Result<bool> {
    Ok(data_version(row, "messages_v")? >= floor.messages_v && matches_revision_floor(row, floor)?)
}
#[derive(Default)]
struct Changes {
    read_port: Mutex<Option<actor::MonitorReadPort>>,
    send_lane: Option<Arc<super::ScopedSendGate>>,
    pending: Mutex<Pending>,
    wake: Notify,
}
struct MonitorFence {
    owner: Arc<super::project_task_watch::WatchAuthority>,
    generation: u64,
    team: Option<String>,
    expires_at: Option<u64>,
    cancel: CancellationToken,
    alive: AtomicBool,
    denial: Mutex<Option<ChatMonitorAccessDenial>>,
}
/// Negative observation from an exact authenticated read, never access authority.
#[derive(Clone)]
pub enum ChatMonitorAccessDenial {
    Expired,
    ScopeRevoked,
    ChatUnavailable { chat_id: String },
}
impl MonitorFence {
    fn valid(&self) -> bool {
        self.alive.load(Ordering::Acquire)
            && !self.cancel.is_cancelled()
            && !self.owner.cancel.is_cancelled()
            && self.expires_at.is_none_or(|at| at > now_ms())
    }
}
// Only an exclusive live read installs this audit. It records fixed route
// categories/status, never URLs, response bodies, cookies or arbitrary errors.
#[derive(Clone)]
pub(super) enum MonitorReadOrigin {
    Session,
    Team,
    Chat(String),
}
pub(super) struct MonitorReadAudit {
    fence: Arc<MonitorFence>,
    denial: Option<ChatMonitorAccessDenial>,
}
/// DATA only. No Session, credential revision/ACK, cookies, owner identity,
/// access-denial evidence, operation/lifetime tokens or native journal state.
struct LiveDataBackup {
    chats: BTreeMap<String, Value>,
    chat_arrival_order: Option<Vec<String>>,
    wrappers: Vec<Value>,
    history: BTreeMap<String, Vec<Value>>,
    sync_message_windows: BTreeMap<String, super::sync_windows::CiphertextMessageWindow>,
    selected_first_pages: BTreeMap<String, super::selected_first_page::SelectedFirstPage>,
    embeds: BTreeMap<String, Value>,
    embed_keys: Vec<Value>,
    team_wrapped_key: Option<(String, String)>,
    active_chat: Option<String>,
}
struct LiveReadTransaction<'a> {
    client: &'a mut Client,
    fence: Arc<MonitorFence>,
    backup: Option<LiveDataBackup>,
}
impl<'a> LiveReadTransaction<'a> {
    fn new(client: &'a mut Client, fence: Arc<MonitorFence>) -> Result<Self> {
        client.check_chat_monitor_fence(&fence)?;
        if client.monitor_read_audit.is_some() {
            return Err(Error::Conflict);
        }
        let backup = LiveDataBackup {
            chats: client.chats.clone(),
            chat_arrival_order: client.chat_arrival_order.clone(),
            wrappers: client.wrappers.clone(),
            history: client.history.clone(),
            sync_message_windows: client.sync_message_windows.clone(),
            selected_first_pages: client.selected_first_pages.clone(),
            embeds: client.embeds.clone(),
            embed_keys: client.embed_keys.clone(),
            team_wrapped_key: client.team_wrapped_key.clone(),
            active_chat: client.active_chat.clone(),
        };
        client.monitor_read_audit = Some(MonitorReadAudit {
            fence: fence.clone(),
            denial: None,
        });
        Ok(Self {
            client,
            fence,
            backup: Some(backup),
        })
    }
    fn denied(&self) -> Option<ChatMonitorAccessDenial> {
        self.client
            .monitor_read_audit
            .as_ref()
            .and_then(|audit| audit.denial.clone())
    }
    fn validate_candidate_versions(&self, confirmed_rewinds: &BTreeSet<String>) -> Result<()> {
        if let Some(backup) = &self.backup {
            for (id, prior) in &backup.chats {
                // Missing recent metadata is not a tombstone. Compare actual
                // returned rows only; strict selected absence is handled below.
                if let Some(candidate) = self.client.chats.get(id) {
                    let floor = VersionFloor {
                        messages_v: 0,
                        metadata_v: metadata_version(prior)?,
                        draft_v: data_version(prior, "draft_v")?,
                    };
                    if !matches_revision_floor(candidate, &floor)? {
                        return Err(Error::Offline);
                    }
                    // messages_v is a count: rewind intentionally reduces it.
                    // A lower count needs an exact fresh history replacement,
                    // not an unconditional cache-derived monotonic floor.
                    if data_version(candidate, "messages_v")? < data_version(prior, "messages_v")?
                        && !confirmed_rewinds.contains(id)
                    {
                        return Err(Error::Offline);
                    }
                }
            }
        }
        Ok(())
    }
    fn accept(&mut self) {
        self.backup.take();
    }
    fn same_authorized_owner(&self) -> bool {
        !self.fence.owner.cancel.is_cancelled()
            && Arc::ptr_eq(&self.client.task_watch_authority, &self.fence.owner)
            && self.client.generation == self.fence.generation
            && self.client.require_credentials().is_ok_and(|s| {
                s.active_team_id.as_ref() == self.fence.team.as_ref()
                    && s.paired_session_expires_at.is_none_or(|at| at > now_ms())
            })
            && self.fence.expires_at.is_none_or(|at| at > now_ms())
    }
}
impl std::ops::Deref for LiveReadTransaction<'_> {
    type Target = Client;
    fn deref(&self) -> &Client {
        self.client
    }
}
impl std::ops::DerefMut for LiveReadTransaction<'_> {
    fn deref_mut(&mut self) -> &mut Client {
        self.client
    }
}
impl Drop for LiveReadTransaction<'_> {
    fn drop(&mut self) {
        let fence = self.fence.clone();
        let denial = fence.denial.lock();
        let mut discarded = None;
        if denial.as_ref().is_ok_and(|value| value.is_none())
            && self.same_authorized_owner()
            && let Some(backup) = self.backup.take()
        {
            // Linearize against concurrent keyless security observations. Only
            // pointer/field moves happen under this short lock, never IO or
            // destruction of a potentially large rejected candidate cache.
            discarded = Some(LiveDataBackup {
                chats: std::mem::replace(&mut self.client.chats, backup.chats),
                chat_arrival_order: std::mem::replace(&mut self.client.chat_arrival_order, backup.chat_arrival_order),
                wrappers: std::mem::replace(&mut self.client.wrappers, backup.wrappers),
                history: std::mem::replace(&mut self.client.history, backup.history),
                sync_message_windows: std::mem::replace(&mut self.client.sync_message_windows, backup.sync_message_windows),
                selected_first_pages: std::mem::replace(&mut self.client.selected_first_pages, backup.selected_first_pages),
                embeds: std::mem::replace(&mut self.client.embeds, backup.embeds),
                embed_keys: std::mem::replace(&mut self.client.embed_keys, backup.embed_keys),
                team_wrapped_key: std::mem::replace(
                    &mut self.client.team_wrapped_key,
                    backup.team_wrapped_key,
                ),
                active_chat: std::mem::replace(&mut self.client.active_chat, backup.active_chat),
            });
            // No secret/auth cache is restored. Later Team reads must freshly
            // authorize/refetch any needed wrapping key.
            self.client.team_key = None;
        }
        drop(denial);
        drop(discarded);
        if self
            .client
            .monitor_read_audit
            .as_ref()
            .is_some_and(|audit| Arc::ptr_eq(&audit.fence, &self.fence))
        {
            self.client.monitor_read_audit = None;
        }
    }
}
/// One keyless socket instance. Waiting never borrows the mutable Client lane.
/// Dropping this handle closes only its selected monitor, never the account.
pub struct ChatMonitor {
    fence: Arc<MonitorFence>,
    changes: Arc<Changes>,
}
/// Opaque bounded invalidation. It grants no chat access or recovery lease.
pub struct ChatInvalidation {
    fence: Arc<MonitorFence>,
    pending: Pending,
}
/// Durable persisted view; cache settlement is explicitly distinct from canonical history.
pub enum ChatSelectionUpdate {
    Unchanged,
    Updated(Chat),
    /// Online authorized owned cache, never complete-history/recovery proof.
    CacheSettled(Chat),
    /// A strict authenticated selected-ID read no longer grants access. This
    /// hides the selected view; it does not delete encrypted history or drafts.
    Unavailable {
        chat_id: String,
    },
}
pub struct ChatModels {
    pub items: Vec<Item>,
    pub selection: ChatSelectionUpdate,
}
impl zeroize::Zeroize for ChatModels {
    fn zeroize(&mut self) { super::plaintext::Wipe::wipe(self); }
}
/// Captured BEFORE the interactive live read. This can only restrict that
/// original read across staging, exact ACK, commit and queued final release.
/// It never admits auth, freshness, cache writes, recovery or new operations.
struct CacheMonitorReadScope {
    crypto: AsyncCryptoScope,
    owner: Arc<super::project_task_watch::WatchAuthority>,
    operation: CancellationToken,
    parent: CancellationToken,
    denial_revision: u64,
    expires_at: Option<u64>,
    selected: Option<String>,
    private_gate: Option<Arc<dyn Fn() -> Result<()> + Send + Sync>>,
}
impl CacheMonitorReadScope {
    fn capture(client: &Client, selected: Option<&str>) -> Result<Self> {
        client.verify_private_operation()?;
        client.require_canonical_read_profile()?;
        let scope = Self {
            crypto: AsyncCryptoScope::begin(client)?,
            owner: client.task_watch_authority.clone(),
            operation: client.operation_cancel.clone(), parent: client.operation_parent.clone(),
            denial_revision: client.task_watch_authority.cached_denial_revision()?,
            expires_at: client.require_credentials()?.paired_session_expires_at,
            selected: selected.map(str::to_owned),
            private_gate: client.options.private_operation_gate.clone(),
        };
        scope.check(client)?;
        Ok(scope)
    }
    fn is_current(&self) -> bool {
        self.crypto.ensure_resource_current().is_ok()
            && !self.owner.cancel.is_cancelled() && !self.operation.is_cancelled()
            && !self.parent.is_cancelled()
            && self.expires_at.is_none_or(|deadline| deadline > now_ms())
            && self.owner.cached_denial_revision().is_ok_and(|revision| revision == self.denial_revision)
            && self.selected.as_deref().is_none_or(|id| self.owner.cached_chat_allowed(id))
            && self.private_gate.as_ref().is_none_or(|gate| gate().is_ok())
    }
    fn check(&self, client: &Client) -> Result<()> {
        client.verify_private_operation()?;
        client.require_canonical_read_profile()?;
        self.crypto.check(client)?;
        if self.operation != client.operation_cancel || self.parent != client.operation_parent
            || !Arc::ptr_eq(&self.owner, &client.task_watch_authority) || !self.is_current() {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
/// Plaintext stays private until caller attests durable cache+credential save.
pub struct ChatRefresh {
    confirmed_rewinds: BTreeSet<String>,
    fence: Arc<MonitorFence>,
    revision: u64,
    ciphertext: Value,
    models: Plain<ChatModels>,
    cache_scope: Option<CacheMonitorReadScope>,
}
/// Still sealed while queued to a UI or foreign language consumer.
pub struct ChatPublication {
    fence: Arc<MonitorFence>,
    cache_scope: Option<CacheMonitorReadScope>,
    revision: u64,
    ciphertext: Value,
    models: Plain<ChatModels>,
}
/// Caller attestation after exact durable cache+credential save. Foreign
/// adapters additionally require a CAS/serialized writer across staged saves.
#[derive(serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChatRefreshDurableReceipt {
    pub ciphertext_sha256: String,
    pub credential_revision: u64,
}
impl ChatRefresh {
    pub fn ciphertext_snapshot(&self) -> Result<&Value> {
        if !self.fence.valid() || self.cache_scope.as_ref().is_some_and(|scope| !scope.is_current()) {
            return Err(Error::Cancelled);
        }
        Ok(&self.ciphertext)
    }
    pub fn credential_revision(&self) -> u64 {
        self.revision
    }
    pub fn ciphertext_sha256(&self) -> Result<String> {
        self.ciphertext_snapshot()?;
        Ok(sha256(&serde_json::to_string(&self.ciphertext)?))
    }
}
impl ChatPublication {
    pub fn is_valid(&self) -> bool {
        self.fence.valid()
            && self.cache_scope.as_ref().is_none_or(CacheMonitorReadScope::is_current)
    }
    pub fn models(&self) -> Result<&ChatModels> {
        if !self.is_valid() {
            return Err(Error::Cancelled);
        }
        Ok(&self.models)
    }
    pub fn into_models(self) -> Result<ChatModels> {
        if !self.is_valid() {
            return Err(Error::Cancelled);
        }
        Ok(self.models.into_inner())
    }
}
impl ChatInvalidation {
    /// Schedule canonical recovery discovery; IDs are hints, never authority.
    pub fn recovery_chats(&self) -> impl Iterator<Item = &str> {
        self.pending.recovery.iter().map(String::as_str)
    }
    // Keyless identity coverage only, never a foreground recovery grant.
    pub(in crate::client) fn recovery_manifest(&self)->RecoveryHintManifest{
        self.pending.recovery_jobs.snapshot(&self.pending.recovery)
    }
}
impl MonitorFence {
    fn retain_cached_denial(&self, denial: &ChatMonitorAccessDenial) -> Result<()> {
        match denial {
            ChatMonitorAccessDenial::Expired => { self.owner.cancel.cancel(); Ok(()) },
            ChatMonitorAccessDenial::ScopeRevoked => self.owner.deny_cached_chat(None),
            ChatMonitorAccessDenial::ChatUnavailable { chat_id } => self.owner.deny_cached_chat(Some(chat_id)),
        }
    }
}
impl ChatMonitor {
    pub fn is_valid(&self) -> bool {
        self.fence.valid()
    }
    pub async fn changed(&self) -> Result<()> {
        loop {
            let wake = self.changes.wake.notified();
            tokio::pin!(wake);
            wake.as_mut().enable();
            if !self.is_valid() {
                return Err(Error::Cancelled);
            }
            let ready = {
                let pending = self.changes.pending.lock().map_err(|_| Error::Protocol)?;
                pending.refresh || !pending.recovery.is_empty()
            };
            if ready {
                if let Some(lane) = &self.changes.send_lane {
                    tokio::select! { biased;
                        _ = self.fence.cancel.cancelled() => return Err(Error::Cancelled),
                        _ = self.fence.owner.cancel.cancelled() => return Err(Error::Cancelled),
                        result = lane.idle() => result?,
                    }
                    if !self.is_valid() { return Err(Error::Cancelled); }
                }
                return Ok(());
            }
            tokio::select! {
                biased;
                _ = self.fence.cancel.cancelled() => return Err(Error::Cancelled),
                _ = self.fence.owner.cancel.cancelled() => return Err(Error::Cancelled),
                _ = &mut wake => {},
                _ = crate::platform::time::sleep(Duration::from_secs(1)) => {},
            }
        }
    }
    /// Keyless bounded platform poll, separate from the mutable Client lane.
    /// false is idle only, never socket/auth/ciphertext durability authority.
    pub async fn changed_or_idle(&self) -> Result<bool> {
        match crate::platform::time::timeout(Duration::from_secs(10),self.changed()).await {
            Ok(result)=>{result?;Ok(true)},
            Err(_)=>{if !self.is_valid(){return Err(Error::Cancelled)}Ok(false)},
        }
    }
    pub fn take_pending(&self) -> Result<Option<ChatInvalidation>> {
        if !self.is_valid() {
            return Err(Error::Cancelled);
        }
        let mut pending = self.changes.pending.lock().map_err(|_| Error::Protocol)?;
        if !pending.refresh && pending.recovery.is_empty() {
            return Ok(None);
        }
        Ok(Some(ChatInvalidation {
            fence: self.fence.clone(),
            pending: std::mem::take(&mut *pending),
        }))
    }
    /// Retry only an uncommitted read, never a write or recovery lease.
    pub fn requeue(&self, hint: ChatInvalidation) -> Result<()> {
        if !self.is_valid() || !Arc::ptr_eq(&self.fence, &hint.fence) {
            return Err(Error::Cancelled);
        }
        let mut pending = self.changes.pending.lock().map_err(|_| Error::Protocol)?;
        merge_pending(&mut pending, hint.pending)?;
        drop(pending);
        self.changes.wake.notify_one();
        Ok(())
    }
    pub fn access_denial(&self) -> Result<Option<ChatMonitorAccessDenial>> {
        Ok(self
            .fence
            .denial
            .lock()
            .map_err(|_| Error::Protocol)?
            .clone())
    }
    fn deny(&self, denial: ChatMonitorAccessDenial) -> Result<()> {
        self.fence.cancel.cancel();
        self.fence.retain_cached_denial(&denial)?;
        *self.fence.denial.lock().map_err(|_| Error::Protocol)? = Some(denial);
        self.close();
        Ok(())
    }
    pub fn close(&self) {
        self.fence.cancel.cancel();
        self.changes.wake.notify_waiters();
    }
}
impl Drop for ChatMonitor {
    fn drop(&mut self) {
        self.close();
    }
}
fn merge_pending(into: &mut Pending, from: Pending) -> Result<()> {
    into.refresh |= from.refresh;
    for id in from.chats {
        if into.chats.len() < MAX_HINTS {
            into.chats.insert(id);
        }
    }
    for id in from.recovery {
        if into.recovery.len() < MAX_HINTS {
            into.recovery.insert(id);
        }
    }
    for (id, floor) in from.versions {
        if into.versions.len() < MAX_HINTS || into.versions.contains_key(&id) {
            let current = into.versions.entry(id).or_default();
            current.messages_v = current.messages_v.max(floor.messages_v);
            current.metadata_v = current.metadata_v.max(floor.metadata_v);
            current.draft_v = current.draft_v.max(floor.draft_v);
        }
    }
    into.recovery_jobs.merge(from.recovery_jobs)?;
    Ok(())
}
fn chat_id(value: &Value, field: &str) -> Result<String> {
    let id = value[field].as_str().ok_or(Error::Protocol)?;
    uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
    Ok(id.to_owned())
}
fn record_change(changes: &Changes, kind: &str, value: &Value) -> Result<()> {
    let mut next = Pending::default();
    match kind {
        // Per-token plaintext is deliberately not retained or turned into HTTP.
        "ai_message_update" if value["is_final_chunk"] != true => return Ok(()),
        "chat_title_updated"
        | "chat_draft_updated"
        | "draft_deleted"
        | "new_chat_message"
        | "chat_deleted"
        | "ai_message_update"
        | "ai_background_response_completed"
        | "team_chat_message_created"
        | "team_ai_response_completed"
        | "team_chat_created" => {
            let id = if kind == "team_chat_created" {
                chat_id(&value["chat"], "id")?
            } else {
                chat_id(value, "chat_id")?
            };
            next.refresh = true;
            let versions = value.get("versions").unwrap_or(value);
            let floor = VersionFloor {
                messages_v: version(versions, "messages_v")?,
                metadata_v: version(versions, "metadata_v")?,
                draft_v: version(versions, "draft_v")?,
            };
            next.versions.insert(id.clone(), floor);
            next.chats.insert(id);
        }
        "recovery_jobs_available" | "metadata_jobs_available" => {
            let jobs = value["jobs"].as_array().ok_or(Error::Protocol)?;
            if jobs.len() > MAX_HINTS {
                return Err(Error::Protocol);
            }
            for job in jobs {
                let job_id=chat_id(job,"job_id")?;
                let chat=chat_id(job,"chat_id")?;
                let kind=if kind=="recovery_jobs_available"{RecoveryHintKind::Main}else{RecoveryHintKind::Metadata};
                next.recovery_jobs.record(kind,&job_id,&chat)?;
                next.recovery_jobs.record_actual_offer(if kind==RecoveryHintKind::Main{"recovery_jobs_available"}else{"metadata_jobs_available"},job)?;
                next.recovery.insert(chat);
            }
        }
        _ => return Ok(()),
    }
    let mut pending = changes.pending.lock().map_err(|_| Error::Protocol)?;
    merge_pending(&mut pending, next)?;
    drop(pending);
    changes.wake.notify_one();
    Ok(())
}

impl Client {
    pub async fn start_monitor(
        &mut self,
        cancel: CancellationToken,
        events: mpsc::Sender<Error>,
    ) -> Result<()> {
        self.start_monitor_inner(cancel, events, None)
            .await
            .map(|_| ())
    }
    pub async fn start_chat_monitor(
        &mut self,
        cancel: CancellationToken,
        errors: mpsc::Sender<Error>,
    ) -> Result<ChatMonitor> {
        let changes = Arc::new(Changes { send_lane: Some(self.scoped_send_gate.clone()), ..Changes::default() });
        let fence = self
            .start_monitor_inner(cancel, errors, Some(changes.clone()))
            .await?;
        // Refresh once per admitted connection/reconnect, not per sync frame.
        changes.pending.lock().map_err(|_| Error::Protocol)?.refresh = true;
        changes.wake.notify_one();
        Ok(ChatMonitor { fence, changes })
    }
    async fn start_monitor_inner(
        &mut self,
        cancel: CancellationToken,
        events: mpsc::Sender<Error>,
        changes: Option<Arc<Changes>>,
    ) -> Result<Arc<MonitorFence>> {
        let cancel = cancel.child_token();
        if let Some(previous) = self.monitor_cancel.take() {
            previous.cancel();
        }
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let team = self.team()?.map(str::to_owned);
        let generation = self.generation;
        // This can rotate cookies even if a later handshake/membership check
        // fails. Callers must persist the updated session on either outcome.
        let mut socket = self.passive_chat_monitor_socket().await?;
        if let Some(team) = &team {
            // The Team key cache is deliberately bypassed: ordinary membership
            // removal does not always emit a remote-access revocation event.
            let checked = self
                .request(Method::GET, &format!("/v1/teams/{}", segment(team)), None)
                .await;
            let result = match checked {
                Ok(result) => result,
                Err(error) => {
                    close(&mut socket).await;
                    return Err(error);
                }
            };
            if text(&result["team"], "team_id") != team {
                close(&mut socket).await;
                return Err(Error::Forbidden);
            }
        }
        if cancel.is_cancelled()
            || self.generation != generation
            || self.team()?.map(str::to_owned) != team
        {
            close(&mut socket).await;
            return Err(Error::Cancelled);
        }
        let team_hash = team.as_deref().map(sha256);
        let fence = Arc::new(MonitorFence {
            owner: self.task_watch_authority.clone(),
            generation,
            team,
            expires_at: self.require_credentials()?.paired_session_expires_at,
            cancel: cancel.clone(),
            alive: AtomicBool::new(true),
            denial: Mutex::new(None),
        });
        let read_commands = if let Some(changes) = &changes {
            let (port, receiver) = actor::channel(&socket);
            *changes.read_port.lock().map_err(|_| Error::Protocol)? = Some(port);
            Some(receiver)
        } else { None };
        self.monitor_cancel = Some(cancel.clone());
        crate::platform::spawn(monitor_socket_mode(
            socket,
            cancel,
            events,
            team_hash,
            self.lifecycle(),
            Duration::from_secs(25),
            changes,
            Some(fence.clone()),
            read_commands,
        ));
        Ok(fence)
    }
    pub(super) fn monitor_read_origin(
        &self,
        method: &Method,
        path: &str,
        body: Option<&Value>,
    ) -> Option<MonitorReadOrigin> {
        self.monitor_read_audit.as_ref()?;
        let url = self.url(path).ok()?;
        let path = self.request_route_path(&url).ok()?;
        if *method == Method::POST && path == "/v1/auth/session" {
            return Some(MonitorReadOrigin::Session);
        }
        if *method == Method::GET
            && path.strip_prefix("/v1/teams/").is_some_and(|id| {
                self.session
                    .as_ref()
                    .and_then(|s| s.active_team_id.as_deref())
                    == Some(id)
            })
        {
            return Some(MonitorReadOrigin::Team);
        }
        if *method == Method::POST && path == "/v1/chats/metadata/batch" {
            let ids = body?["chat_ids"].as_array()?;
            if ids.len() == 1 {
                let id = ids[0].as_str()?;
                uuid::Uuid::parse_str(id).ok()?;
                return Some(MonitorReadOrigin::Chat(id.to_owned()));
            }
        }
        if *method == Method::GET {
            let id = path
                .strip_prefix("/v1/chats/")
                .and_then(|tail| tail.split_once('/').map(|(id, _)| id))
                .or_else(|| path.strip_prefix("/v1/drafts/"));
            if let Some(id) = id.filter(|id| uuid::Uuid::parse_str(id).is_ok()) {
                return Some(MonitorReadOrigin::Chat(id.to_owned()));
            }
        }
        None
    }
    pub(super) fn note_monitor_http_denial(
        &mut self,
        status: u16,
        origin: Option<MonitorReadOrigin>,
    ) -> Result<bool> {
        let Some(audit) = self.monitor_read_audit.as_mut() else {
            return Ok(false);
        };
        let denial = match (status, origin) {
            (401, _) => ChatMonitorAccessDenial::Expired,
            (403, Some(MonitorReadOrigin::Session)) => ChatMonitorAccessDenial::Expired,
            (403, Some(MonitorReadOrigin::Team)) => ChatMonitorAccessDenial::ScopeRevoked,
            (403, Some(MonitorReadOrigin::Chat(_))) if audit.fence.team.is_some() => {
                ChatMonitorAccessDenial::ScopeRevoked
            }
            (403, Some(MonitorReadOrigin::Chat(chat_id))) => {
                ChatMonitorAccessDenial::ChatUnavailable { chat_id }
            }
            _ => return Ok(false),
        };
        audit.fence.cancel.cancel();
        audit.fence.retain_cached_denial(&denial)?;
        audit.denial = Some(denial.clone());
        // Invalidate even if internal diagnostic state were poisoned; no stale
        // publication can be exposed while a denied response is being handled.
        audit.fence.cancel.cancel();
        *audit.fence.denial.lock().map_err(|_| Error::Protocol)? = Some(denial);
        // Transport still finishes validated cookie header adoption, then
        // returns the existing Forbidden/Expired public error category.
        Ok(true)
    }
    fn check_chat_monitor_fence(&self, fence: &Arc<MonitorFence>) -> Result<()> {
        self.require_credentials()?;
        if !fence.valid()
            || self.operation_cancel.is_cancelled()
            || !Arc::ptr_eq(&self.task_watch_authority, &fence.owner)
            || self.generation != fence.generation
            || self.team()? != fence.team.as_deref()
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    /// Fresh account/Team authorization without replacing a healthy socket.
    /// Cookie rotation never extends the captured absolute paired-session TTL.
    pub async fn validate_chat_monitor(&mut self, monitor: &ChatMonitor) -> Result<()> {
        self.check_chat_monitor_fence(&monitor.fence)?;
        self.validate_session().await?;
        self.check_chat_monitor_fence(&monitor.fence)?;
        if let Some(team) = monitor.fence.team.as_ref() {
            let checked = self
                .request(Method::GET, &format!("/v1/teams/{}", segment(team)), None)
                .await;
            match checked {
                Ok(result) if text(&result["team"], "team_id") == team.as_str() => {}
                Ok(_) => {
                    monitor.deny(ChatMonitorAccessDenial::ScopeRevoked)?;
                    return Err(Error::Forbidden);
                }
                Err(error) => {
                    if matches!(error, Error::Expired | Error::Forbidden) {
                        monitor.deny(if error == Error::Expired {
                            ChatMonitorAccessDenial::Expired
                        } else {
                            ChatMonitorAccessDenial::ScopeRevoked
                        })?;
                    }
                    return Err(error);
                }
            }
        }
        self.check_chat_monitor_fence(&monitor.fence)
    }
    /// Strict live read. Offline cached fallbacks are intentionally not used.
    /// Recent-20 metadata absence is never interpreted as deletion.
    pub async fn refresh_chat_monitor(
        &mut self,
        monitor: &ChatMonitor,
        hint: &ChatInvalidation,
        selected_chat: Option<&str>,
    ) -> Result<ChatRefresh> {
        self.refresh_chat_monitor_policy(monitor, hint, selected_chat, false).await
    }
    /// Interactive refresh keeps cached older rows and fetches only the normal
    /// latest-20 page. Rewinds still require the existing strict history proof.
    pub async fn refresh_chat_monitor_prefer_cache(
        &mut self, monitor: &ChatMonitor, hint: &ChatInvalidation, selected_chat: Option<&str>,
    ) -> Result<ChatRefresh> {
        self.refresh_chat_monitor_policy(monitor, hint, selected_chat, true).await
    }
    async fn refresh_chat_monitor_policy(
        &mut self, monitor: &ChatMonitor, hint: &ChatInvalidation,
        selected_chat: Option<&str>, prefer_cache: bool,
    ) -> Result<ChatRefresh> {
        // Do not capture after IO or synthesize from a DTO at commit time.
        let cache_scope = if prefer_cache { Some(CacheMonitorReadScope::capture(self, selected_chat)?) } else { None };
        let mut transaction = LiveReadTransaction::new(self, monitor.fence.clone())?;
        let result = transaction
            .refresh_chat_monitor_inner(monitor, hint, selected_chat, prefer_cache, cache_scope)
            .await;
        if let Some(denial) = transaction.denied() {
            return Err(match denial {
                ChatMonitorAccessDenial::Expired => Error::Expired,
                _ => Error::Forbidden,
            });
        }
        if let Ok(refresh) = &result {
            if let Some(scope) = &refresh.cache_scope { scope.check(&transaction)?; }
            transaction.validate_candidate_versions(&refresh.confirmed_rewinds)?;
            transaction.check_chat_monitor_fence(&monitor.fence)?;
            transaction.accept();
        }
        result
    }
    async fn refresh_chat_monitor_inner(
        &mut self,
        monitor: &ChatMonitor,
        hint: &ChatInvalidation,
        selected_chat: Option<&str>,
        prefer_cache: bool,
        cache_scope: Option<CacheMonitorReadScope>,
    ) -> Result<ChatRefresh> {
        if !Arc::ptr_eq(&monitor.fence, &hint.fence) {
            return Err(Error::Cancelled);
        }
        self.check_chat_monitor_fence(&monitor.fence)?;
        if let Some(id) = selected_chat {
            uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        }
        let active = self.active_chat.clone();
        let prior_counts = self
            .chats
            .iter()
            .map(|(id, row)| Ok((id.clone(), data_version(row, "messages_v")?)))
            .collect::<Result<BTreeMap<_, _>>>()?;
        let mut confirmed_rewinds = BTreeSet::new();
        let mut superseded_counts = BTreeSet::new();
        let mut ids = hint.pending.chats.clone();
        if let Some(id) = selected_chat {
            ids.insert(id.to_owned());
        }
        // Preserve only bounded candidate ciphertext for existing Personal
        // synthetic drafts. The existing strict reader validates owner, scope,
        // keyless/no-history state, wrappers and authoritative draft version.
        let mut prior_drafts = BTreeMap::new();
        if self.team()?.is_none() {
            for id in &ids {
                if let Some(row) = self
                    .chats
                    .get(id)
                    .filter(|row| super::sync::draft_only(row))
                {
                    prior_drafts.insert(id.clone(), row.clone());
                }
            }
        }
        // An initial/reconnect snapshot is a bounded recent list, never a set
        // of tombstones. No volatile AI payload enters this transaction.
        if hint.pending.refresh {
            drop(Plain::new(self.sync_chats_for_monitor().await?));
        }
        self.check_chat_monitor_fence(&monitor.fence)?;
        let mut selection = Plain::new(ChatSelectionUpdate::Unchanged);
        // A reconnect can discover an authoritative rewind without a dedicated
        // event (the current backend emits none). Refresh its history as well.
        for (id, row) in &self.chats {
            if prior_counts
                .get(id)
                .is_some_and(|prior| data_version(row, "messages_v").is_ok_and(|now| now < *prior))
            {
                ids.insert(id.clone());
            }
        }
        if ids.len() > MAX_HINTS + 21 {
            return Err(Error::Protocol);
        }
        for id in ids {
            // Canonical batch endpoint raises404 if any member is absent, so
            // mixed changed/deleted IDs must use its existing exact-ID helper.
            // Requests are per coalesced persisted/reset ID (max121), never per token.
            let metadata = match self.request_chat_metadata(&id).await {
                Ok(metadata) => metadata,
                Err(error @ (Error::Expired | Error::Forbidden)) => {
                    // The exact Team metadata route raises403 only at current
                    // membership authorization. A Personal/single-chat403 is
                    // narrower and must not force whole-account logout.
                    let denial = if error == Error::Expired {
                        ChatMonitorAccessDenial::Expired
                    } else if monitor.fence.team.is_some() {
                        ChatMonitorAccessDenial::ScopeRevoked
                    } else {
                        ChatMonitorAccessDenial::ChatUnavailable {
                            chat_id: id.clone(),
                        }
                    };
                    monitor.deny(denial)?;
                    return Err(error);
                }
                Err(error) => return Err(error),
            };
            self.check_chat_monitor_fence(&monitor.fence)?;
            let row = match metadata {
                None => None,
                Some(value) => {
                    let rows = value["chats"].as_array().ok_or(Error::Protocol)?;
                    if rows.len() > 1 {
                        return Err(Error::Protocol);
                    }
                    let row = rows.first().cloned();
                    if let Some(row) = &row
                        && chat_id(row, "id")? != id
                    {
                        return Err(Error::Protocol);
                    }
                    row
                }
            };
            let first_count = row
                .as_ref()
                .map(|row| data_version(row, "messages_v"))
                .transpose()?;
            let mut selected_model = Plain::new(None::<Chat>);
            if let Some(row) = row {
                if let Some(floor) = hint.pending.versions.get(&id) {
                    if !matches_revision_floor(&row, floor)? {
                        return Err(Error::Offline);
                    }
                }
                self.insert_chat_row(id.clone(), row);
            } else {
                let draft_candidate = self.team()?.is_none()
                    && (prior_drafts.contains_key(&id)
                        || self.chats.get(&id).is_some_and(super::sync::draft_only));
                if draft_candidate {
                    if let Some(row) = prior_drafts.remove(&id) {
                        if !self.chats.contains_key(&id) { self.insert_chat_row(id.clone(), row); }
                    }
                    // A second exact metadata read inside open_chat_live admits
                    // the existing draft path only on404. A concurrently
                    // promoted saved row takes its normal independently keyed
                    // chat path instead; no master-key fallback is invented.
                    let opened = self.open_chat_live(&id).await.map(Plain::new);
                    self.active_chat = active.clone();
                    match opened {
                        Ok(chat) => selected_model = Plain::new(Some(chat.into_inner())),
                        Err(Error::Invalid("The requested draft is unavailable.")) => {
                            // The existing strict reader observed draft:null.
                        }
                        Err(error) => return Err(error),
                    }
                } else {
                    self.remove_chat_row(&id);
                    self.selected_first_pages.remove(&id);
                }
            }
            if let Some(row) = self.chats.get(&id) {
                if let Some(floor) = hint.pending.versions.get(&id) {
                    if !matches_revision_floor(row, floor)? {
                        return Err(Error::Offline);
                    }
                }
                let current_count = data_version(row, "messages_v")?;
                let prior_count = prior_counts.get(&id).copied().unwrap_or(0);
                let hint_count = hint
                    .pending
                    .versions
                    .get(&id)
                    .map_or(0, |floor| floor.messages_v);
                if selected_chat == Some(id.as_str())
                    || current_count < prior_count
                    || current_count < hint_count
                {
                    let (opened, cached) = match selected_model.take() {
                        Some(chat) => (Ok(chat), false),
                        None if prefer_cache && selected_chat == Some(id.as_str())
                            && current_count >= prior_count && current_count >= hint_count => {
                            match self.open_chat_cache_preferred(&id, true).await {
                                Ok(Some(chat)) => (Ok(chat), true),
                                Ok(None) => (self.open_chat_live(&id).await, false),
                                Err(error) => (Err(error), false),
                            }
                        },
                        None => (self.open_chat_live(&id).await, false),
                    };
                    self.active_chat = active.clone();
                    let opened = Plain::new(opened?);
                    self.check_chat_monitor_fence(&monitor.fence)?;
                    let final_count =
                        data_version(self.chats.get(&id).ok_or(Error::Protocol)?, "messages_v")?;
                    // Do not publish a selected second read that moved below
                    // the first count in this transaction (e.g.9→8). Retry a
                    // fresh consistent read rather than infer a new epoch.
                    if first_count.is_some_and(|first| final_count < first) {
                        return Err(Error::Offline);
                    }
                    let stable_history = !cached && first_count == Some(final_count)
                        && u64::try_from(opened.messages.len()).map_err(|_| Error::Protocol)?
                            == final_count;
                    if final_count < prior_count {
                        if !stable_history {
                            return Err(Error::Offline);
                        }
                        confirmed_rewinds.insert(id.clone());
                    }
                    if final_count < hint_count {
                        // Delayed pre-rewind count hints are not security
                        // versions. Exact stable canonical history supersedes
                        // them without permanently blocking a legitimate rewind.
                        if !stable_history {
                            return Err(Error::Offline);
                        }
                        superseded_counts.insert(id.clone());
                    }
                    if selected_chat == Some(id.as_str()) {
                        selection = Plain::new(if cached { ChatSelectionUpdate::CacheSettled(opened.into_inner()) }
                            else { ChatSelectionUpdate::Updated(opened.into_inner()) });
                    }
                }
            } else if selected_chat == Some(id.as_str()) {
                // Strict authenticated current-scope absence hides the selected
                // view only. Saved encrypted history remains recoverable.
                selection = Plain::new(ChatSelectionUpdate::Unavailable { chat_id: id });
            }
        }
        self.active_chat = active;
        // Nested selected reads replace the point metadata; validate the FINAL
        // state, including revision floors, before snapshot/model construction.
        for (id, floor) in &hint.pending.versions {
            if let Some(row) = self.chats.get(id) {
                let mut applicable = *floor;
                if superseded_counts.contains(id) {
                    applicable.messages_v = 0;
                }
                if !matches_floor(row, &applicable)? {
                    return Err(Error::Offline);
                }
            }
        }
        self.check_chat_monitor_fence(&monitor.fence)?;
        if let Some(scope) = &cache_scope { scope.check(self)?; }
        // Evaluation of fallible item decoding cannot strand selected plaintext.
        let items = Plain::new(self.cached_chat_items()?);
        Ok(ChatRefresh {
            cache_scope,
            confirmed_rewinds,
            fence: monitor.fence.clone(),
            revision: self.credential_revision,
            ciphertext: self.ciphertext_snapshot(),
            models: Plain::new(ChatModels {
                items: items.into_inner(),
                selection: selection.into_inner(),
            }),
        })
    }
    /// Call only after durable save of this exact ciphertext snapshot and its
    /// credentials. The SDK cannot verify a foreign caller's filesystem; this
    /// explicit method attests that cache write. Exact credential ACK is checked.
    pub fn validate_chat_refresh(&self, refresh: &ChatRefresh) -> Result<()> {
        if let Some(scope) = &refresh.cache_scope { scope.check(self)?; }
        self.check_chat_monitor_fence(&refresh.fence)?;
        if self.credential_revision != refresh.revision
            || self.ciphertext_snapshot() != refresh.ciphertext
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    pub fn commit_chat_refresh(
        &self,
        refresh: ChatRefresh,
        receipt: ChatRefreshDurableReceipt,
    ) -> Result<ChatPublication> {
        self.validate_chat_refresh(&refresh)?;
        if receipt.credential_revision != refresh.revision
            || receipt.ciphertext_sha256 != refresh.ciphertext_sha256()?
            || self.credential_ack != refresh.revision
        {
            return Err(Error::Cancelled);
        }
        Ok(ChatPublication {
            cache_scope: refresh.cache_scope,
            fence: refresh.fence,
            revision: refresh.revision,
            ciphertext: refresh.ciphertext,
            models: refresh.models,
        })
    }
    /// Short-lane revalidation before a foreign consumer serializes a delayed
    /// publication. A publication is an immutable committed read, not ongoing
    /// UI/mutation authority after another operation changes the cache.
    pub fn validate_chat_publication(&self, publication: &ChatPublication) -> Result<()> {
        if let Some(scope) = &publication.cache_scope { scope.check(self)?; }
        self.check_chat_monitor_fence(&publication.fence)?;
        if self.credential_revision != publication.revision
            || self.ciphertext_snapshot() != publication.ciphertext
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
#[cfg(test)]
async fn monitor_socket(
    socket: Socket,
    cancel: CancellationToken,
    events: mpsc::Sender<Error>,
    team_hash: Option<String>,
    lifecycle: Value,
    heartbeat_period: Duration,
) {
    monitor_socket_mode(
        socket,
        cancel,
        events,
        team_hash,
        lifecycle,
        heartbeat_period,
        None,
        None,
        None,
    )
    .await
}
#[allow(clippy::too_many_arguments)] // Internal transport configuration, no public generic I/O.
async fn monitor_socket_mode(
    mut socket: Socket,
    cancel: CancellationToken,
    events: mpsc::Sender<Error>,
    team_hash: Option<String>,
    lifecycle: Value,
    heartbeat_period: Duration,
    changes: Option<Arc<Changes>>,
    fence: Option<Arc<MonitorFence>>,
    mut read_commands: Option<actor::MonitorReadReceiver>,
) {
    let mut heartbeat = crate::platform::time::interval_at(
        crate::platform::time::Instant::now() + heartbeat_period,
        heartbeat_period,
    );
    heartbeat.set_missed_tick_behavior(crate::platform::time::MissedTickBehavior::Skip);
    let mut actor_retired = false;
    let failure = loop {
        tokio::select! {
            biased;
            _ = cancel.cancelled() => break None,
            _ = events.closed() => break None,
            result = async {
                if changes.is_some() { transport::receive_monitor(&mut socket).await }
                else { transport::receive(&mut socket).await }
            } => match result {
                Ok((kind,payload)) => {
                    if let Err(error) = observe_frame(&kind, &payload, changes.as_ref(), fence.as_ref(), team_hash.as_deref()) { break Some(error); }
                    if let Some(receiver) = &mut read_commands {
                        if let Err(error) = receiver.observe_startup(&kind, &payload) { break Some(error); }
                    }
                }
                Err(Error::Expired) => break Some(Error::Expired),
                Err(_) => break Some(Error::Offline),
            },
            command = async {
                match &mut read_commands { Some(receiver) => receiver.next().await, None => std::future::pending().await }
            } => {
                let Some(command) = command else { read_commands = None; continue; };
                if let Some(receiver) = &mut read_commands {
                    if let Err(failure) = receiver.execute(command, &mut socket, changes.as_ref(), team_hash.as_deref(), &lifecycle, &mut heartbeat, &events).await {
                        // A failed/abandoned read leaves no reusable response
                        // slot. Retire only THIS socket; retain negative event
                        // reporting after original denial resources are fenced.
                        actor_retired = true;
                        break Some(failure.monitor_error());
                    }
                }
            }
            _ = heartbeat.tick() => {
                if fence.as_ref().is_some_and(|f| !f.valid()) { break Some(Error::Expired); }
                let sent = tokio::select! {
                    biased;
                    _ = cancel.cancelled() => break None,
                    result = crate::platform::time::timeout(Duration::from_secs(10),transport::send(&mut socket,"native_client_lifecycle",lifecycle.clone())) => result,
                };
                if !matches!(sent,Ok(Ok(()))) { break Some(Error::Offline); }
            }
        }
    };
    // Fail all queued read tickets before any optional error-channel reporting.
    drop(read_commands);
    // Invalidate queued refresh/publication before independently reporting any
    // transport/security failure. Coalescer fullness never blocks socket reads.
    if let Some(error @ (Error::Expired | Error::Forbidden)) = failure
        && let Some(fence) = &fence
        && let Ok(mut denial) = fence.denial.lock()
    {
        *denial = Some(if error == Error::Expired {
            ChatMonitorAccessDenial::Expired
        } else {
            ChatMonitorAccessDenial::ScopeRevoked
        });
    }
    // Retain negative context independently of this optional/replaceable socket.
    if let Some(error @ (Error::Expired | Error::Forbidden)) = failure
        && let Some(fence) = &fence
    {
        let denial = if error == Error::Expired { ChatMonitorAccessDenial::Expired }
            else { ChatMonitorAccessDenial::ScopeRevoked };
        if fence.retain_cached_denial(&denial).is_err() { fence.owner.cancel.cancel(); }
    }
    // Known account/session expiry revokes the shared owner epoch as well as
    // this socket. A caller without this monitor cannot re-mint cached views.
    if matches!(failure, Some(Error::Expired)) && let Some(fence) = &fence {
        fence.owner.cancel.cancel();
    }
    if let Some(fence) = &fence {
        fence.alive.store(false, Ordering::Release);
    }
    if let Some(changes) = &changes {
        changes.wake.notify_waiters();
    }
    // A paused optional event consumer cannot delay actual original-socket
    // retirement. All denial/fence updates above still precede notification.
    if actor_retired { close(&mut socket).await; }
    if let Some(error) = failure {
        tokio::select! { biased; _ = cancel.cancelled() => {}, _ = events.send(error) => {} }
    }
    if !actor_retired { close(&mut socket).await; }
}
fn observe_frame(kind: &str, payload: &Value, changes: Option<&Arc<Changes>>, fence: Option<&Arc<MonitorFence>>, team_hash: Option<&str>) -> Result<()> {
    if fence.is_some_and(|f| !f.valid()) { return Err(Error::Expired); }
    if changes.is_some() && matches!(kind,
        "chat_title_updated"|"chat_draft_updated"|"draft_deleted"|"new_chat_message"|"chat_deleted"
        |"ai_message_update"|"ai_background_response_completed"|"team_chat_created"
        |"team_chat_message_created"|"team_ai_response_completed")
        && let Some(scope)=payload.get("team_id").filter(|value| !value.is_null()) {
        let scope=scope.as_str().filter(|id| uuid::Uuid::parse_str(id).is_ok()).ok_or(Error::Protocol)?;
        if fence.is_some_and(|bound| bound.team.as_deref()!=Some(scope)) { return Ok(()); }
    }
    if let Some(changes) = changes { record_change(changes, kind, payload)?; }
    if kind=="project_remote_access_revoked" && payload["context_type"]=="team"
        && team_hash.is_some_and(|team| payload["context_id_hash"].as_str()==Some(team)) { return Err(Error::Forbidden); }
    Ok(())
}
async fn close(socket: &mut Socket) {
    let _ = crate::platform::time::timeout(Duration::from_secs(2), socket.close(None)).await;
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures_util::{SinkExt, StreamExt};
    use tokio_tungstenite::tungstenite::Message as Frame;

    async fn monitor_frames(frames: Vec<Value>, team: Option<&str>) -> Error {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut socket = tokio_tungstenite::accept_async(stream).await.unwrap();
            for frame in frames {
                socket
                    .send(Frame::Text(frame.to_string().into()))
                    .await
                    .unwrap();
            }
            assert!(matches!(
                socket.next().await.unwrap().unwrap(),
                Frame::Close(_)
            ));
        });
        let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
            .await
            .unwrap();
        let socket = transport::test_socket(inner);
        let (events, mut receiver) = mpsc::channel(4);
        let task = tokio::spawn(monitor_socket(
            socket,
            CancellationToken::new(),
            events,
            team.map(sha256),
            json!({"client_type":"cli","is_foreground":true,"interactive":true}),
            Duration::from_secs(25),
        ));
        let error = crate::platform::time::timeout(Duration::from_secs(2), receiver.recv())
            .await
            .unwrap()
            .unwrap();
        task.await.unwrap();
        server.await.unwrap();
        error
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn force_logout_revokes_an_idle_client() {
        assert_eq!(
            monitor_frames(
                vec![json!({"type":"force_logout","payload":{"reason":"session_revoked"}})],
                None
            )
            .await,
            Error::Expired
        );
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn selected_team_revocation_requires_exact_context_type_and_hash() {
        let unrelated = vec![
            json!({"type":"project_remote_access_revoked","payload":{"context_type":"personal","context_id_hash":sha256("selected")}}),
            json!({"type":"project_remote_access_revoked","payload":{"context_type":"team","context_id_hash":sha256("other")}}),
            json!({"type":"force_logout","payload":{}}),
        ];
        assert_eq!(
            monitor_frames(unrelated, Some("selected")).await,
            Error::Expired
        );
        let selected = json!({"type":"project_remote_access_revoked","payload":{"context_type":"team","context_id_hash":sha256("selected")}});
        assert_eq!(
            monitor_frames(vec![selected], Some("selected")).await,
            Error::Forbidden
        );
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn cancellation_closes_cleanly_without_an_offline_event() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut socket = tokio_tungstenite::accept_async(stream).await.unwrap();
            assert!(matches!(
                socket.next().await.unwrap().unwrap(),
                Frame::Close(_)
            ));
        });
        let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
            .await
            .unwrap();
        let cancel = CancellationToken::new();
        cancel.cancel();
        let (events, mut receiver) = mpsc::channel(1);
        monitor_socket(
            transport::test_socket(inner),
            cancel,
            events,
            None,
            json!({"client_type":"cli","is_foreground":true,"interactive":true}),
            Duration::from_secs(25),
        )
        .await;
        assert_eq!(receiver.recv().await, None);
        server.await.unwrap();
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn idle_lifecycle_is_refreshed_and_disconnect_requests_reconnection() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut socket = tokio_tungstenite::accept_async(stream).await.unwrap();
            let frame = crate::platform::time::timeout(Duration::from_secs(2), socket.next())
                .await
                .unwrap()
                .unwrap()
                .unwrap();
            let message: Value = serde_json::from_str(&frame.into_text().unwrap()).unwrap();
            assert_eq!(
                message,
                json!({"type":"native_client_lifecycle","payload":{"client_type":"cli","is_foreground":true,"interactive":true}})
            );
            socket.close(None).await.unwrap();
        });
        let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
            .await
            .unwrap();
        let (events, mut receiver) = mpsc::channel(1);
        let task = tokio::spawn(monitor_socket(
            transport::test_socket(inner),
            CancellationToken::new(),
            events,
            None,
            json!({"client_type":"cli","is_foreground":true,"interactive":true}),
            Duration::from_millis(25),
        ));
        assert_eq!(
            crate::platform::time::timeout(Duration::from_secs(2), receiver.recv())
                .await
                .unwrap(),
            Some(Error::Offline)
        );
        task.await.unwrap();
        server.await.unwrap();
    }
}

#[cfg(test)]
mod membership_tests {
    use super::*;
    use crate::session::Session;
    use futures_util::StreamExt;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio_tungstenite::tungstenite::Message as Frame;

    async fn http_request(stream: &mut tokio::net::TcpStream) -> String {
        let mut bytes = Vec::new();
        loop {
            let mut buffer = [0; 2048];
            let length = stream.read(&mut buffer).await.unwrap();
            assert!(length > 0);
            bytes.extend_from_slice(&buffer[..length]);
            if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
                let length = headers
                    .lines()
                    .find_map(|line| {
                        line.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .map(|value| value.trim().parse::<usize>().unwrap())
                    })
                    .unwrap_or(0);
                if bytes.len() >= end + 4 + length {
                    return headers.lines().next().unwrap().to_owned();
                }
            }
        }
    }
    async fn http_response(stream: &mut tokio::net::TcpStream, status: &str, body: Value) {
        let body = body.to_string();
        stream.write_all(format!("HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn cached_team_key_cannot_bypass_fresh_membership_denial() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let team = "f8f07a31-04be-4835-8738-b372046f23f1";
        let server = tokio::spawn(async move {
            let (mut auth, _) = listener.accept().await.unwrap();
            assert_eq!(
                http_request(&mut auth).await,
                "POST /v1/auth/session HTTP/1.1"
            );
            http_response(
                &mut auth,
                "200 OK",
                json!({"success":true,"ws_token":"synthetic-token","user":{"id":"synthetic-user"}}),
            )
            .await;
            drop(auth);
            let (stream, _) = listener.accept().await.unwrap();
            let mut socket = tokio_tungstenite::accept_async(stream).await.unwrap();
            let lifecycle = socket.next().await.unwrap().unwrap().into_text().unwrap();
            assert_eq!(
                serde_json::from_str::<Value>(&lifecycle).unwrap()["type"],
                "native_client_lifecycle"
            );
            let (mut membership, _) = listener.accept().await.unwrap();
            assert_eq!(
                http_request(&mut membership).await,
                format!("GET /v1/teams/{team} HTTP/1.1")
            );
            http_response(
                &mut membership,
                "403 Forbidden",
                json!({"detail":"removed"}),
            )
            .await;
            assert!(matches!(
                socket.next().await.unwrap().unwrap(),
                Frame::Close(_)
            ));
        });
        let base = format!("http://{address}");
        let mut client = Client::new(
            &base,
            Some(Session {
                api_url: base.clone(),
                session_id: "synthetic-session".into(),
                cookies: BTreeMap::new(),
                ws_token: None,
                master_key: zeroize::Zeroizing::new([7; 32]),
                hashed_email: "synthetic-owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: Some(team.into()),
            }),
        )
        .unwrap();
        client.team_key = Some((team.into(), zeroize::Zeroizing::new([9; 32])));
        let previous = CancellationToken::new();
        client.monitor_cancel = Some(previous.clone());
        let (events, _receiver) = mpsc::channel(1);
        assert_eq!(
            client.start_monitor(CancellationToken::new(), events).await,
            Err(Error::Forbidden)
        );
        assert!(previous.is_cancelled());
        assert!(client.monitor_cancel.is_none());
        server.await.unwrap();
    }
}

#[cfg(test)]
#[path = "monitor_live_tests.rs"]
mod live_tests;

// Source-unit regression seam constructs the exact existing live fence without
// opening a product socket. No production authority import/API is introduced.
#[cfg(test)]
impl Client {
    pub(super) fn retain_browser_monitor_for_test(&mut self)->Result<ChatMonitor>{
        let cancel=CancellationToken::new();
        let fence=Arc::new(MonitorFence{owner:self.task_watch_authority.clone(),generation:self.generation,team:self.team()?.map(str::to_owned),expires_at:self.require_credentials()?.paired_session_expires_at,cancel:cancel.clone(),alive:AtomicBool::new(true),denial:Mutex::new(None)});
        self.monitor_cancel=Some(cancel);
        Ok(ChatMonitor{fence,changes:Arc::new(Changes::default())})
    }
}

#[cfg(test)]
#[path="selected_first_page_monitor_tests.rs"]
mod selected_first_page_monitor_tests;

#[path = "browser_monitor.rs"]
mod browser_monitor;
pub use browser_monitor::{BrowserMetadataMonitorRefresh, BrowserMetadataMonitorPublication};

pub(in crate::client) use browser_monitor::BrowserMonitorReadContext;
pub(in crate::client) use browser_monitor::{BrowserOwnedMonitorReadContext,OriginalLaterRecoveryHint,MAX_LATER_RECOVERY_HINTS};
pub(in crate::client) use browser_monitor::BrowserOwnedMetadataFloor;

pub use browser_monitor::BrowserIncomingCachePublication;
