//! Fixed read-only command port for ONE original passive monitor socket.
//! A single actor owns receive/send; queued data never grants auth or cache IO.
//! Every command captures the caller's genuine original owned negative scope.
//! Epochs correlate only existing phased messages, never recovery/inventory.
//! Uncorrelated draft responses require an exclusive actual response slot.
//! Abandoning dispatched work retires THIS socket instead of reusing ambiguity.
//! Foreground recovery remains the existing explicit stage/commit workflow.
use super::*;
use crate::client::owned_operation::{OwnedOperationObserver, OwnedOperationScope};
use crate::client::plaintext::Wipe;
use std::sync::atomic::AtomicU64;
use tokio::sync::oneshot;

const QUEUE_CAPACITY: usize = 4;
const MAX_CONTEXT_EPOCH: u64 = (1u64 << 53) - 1;
const MAX_DRAFT_IDS: usize = 10_000;
const MAX_READ_FRAMES: usize = 4096;
const MAX_READ_BYTES: usize = 4 * transport::MAX_BODY;
const SYNC_READ_TIMEOUT: Duration = Duration::from_secs(120);
const DRAFT_READ_TIMEOUT: Duration = Duration::from_secs(90);

pub(in crate::client) enum MonitorReadRequest {
    RecentSync,
    // Distinct initial-sync operation intent, never inferred from a hint or
    // selected-open request. Only the first actual command may dispatch it.
    InitialStartup(Vec<String>),
    // Explicit opt-in only. No selected-open/CLI/default caller selects this:
    // retained pending.refresh alone is not legitimate startup request intent.
    RecentSyncWithExpandedMetadata(Vec<String>),
    DraftVersions(Vec<(String, u64)>),
    DraftMetadata(Option<String>),
}
impl MonitorReadRequest {
    fn validate(&self, team: Option<&str>) -> Result<()> {
        let valid_id = |id: &str| uuid::Uuid::parse_str(id).is_ok_and(|value| value.to_string() == id);
        match self {
            Self::RecentSync => Ok(()),
            Self::InitialStartup(ids) | Self::RecentSyncWithExpandedMetadata(ids) => {
                if ids.len() > MAX_DRAFT_IDS { return Err(Error::Protocol); }
                let mut seen = BTreeSet::new();
                if ids.iter().any(|id| !valid_id(id) || !seen.insert(id)) { return Err(Error::Protocol); }
                Ok(())
            },
            Self::DraftVersions(rows) => {
                if team.is_some() || rows.len() > MAX_DRAFT_IDS { return Err(Error::Forbidden); }
                let mut seen = BTreeSet::new();
                if rows.iter().any(|(id, _)| !valid_id(id) || !seen.insert(id)) { return Err(Error::Protocol); }
                Ok(())
            }
            Self::DraftMetadata(target) => {
                if team.is_some() { return Err(Error::Forbidden); }
                if target.as_deref().is_some_and(|id| !valid_id(id)) { return Err(Error::Protocol); }
                Ok(())
            }
        }
    }
}
pub(in crate::client) struct MonitorDraftVersions {
    pub(in crate::client) versions: BTreeMap<String, u64>,
    pub(in crate::client) tombstones: BTreeMap<String, u64>,
}
impl Wipe for MonitorDraftVersions {
    fn wipe(&mut self) {
        for map in [&mut self.versions, &mut self.tombstones] {
            for (mut id, mut version) in std::mem::take(map) { id.wipe(); zeroize::Zeroize::zeroize(&mut version); }
        }
    }
}
pub(in crate::client) enum MonitorReadData {
    RecentSync(Plain<super::super::sync::SyncPhaseReadData>),
    DraftVersions(Plain<MonitorDraftVersions>),
    DraftMetadata(Plain<BTreeMap<String, Value>>),
}
#[derive(Clone)]
pub(super) struct MonitorReadPort {
    sender: mpsc::Sender<Command>,
    identity: Arc<()>,
    next_epoch: Arc<AtomicU64>,
}
pub(super) struct MonitorReadReceiver {
    receiver: mpsc::Receiver<Command>,
    // Identity-only handle to SAME resource; it NEVER receives or sends.
    // Dropped with this original actor before optional error reporting.
    original_socket: Socket,
    identity: Arc<()>,
    startup: Option<Plain<Value>>,
    dispatched_epoch: u64,
}
pub(super) struct Command {
    request: MonitorReadRequest,
    epoch: u64,
    original_child: CancellationToken,
    abandoned: CancellationToken,
    observer: OwnedOperationObserver,
    fence: Arc<MonitorFence>,
    response: oneshot::Sender<Result<MonitorReadReceipt>>,
}
impl Command {
    fn check(&self) -> Result<()> {
        self.observer.check_release()?;
        if self.original_child.is_cancelled() || self.abandoned.is_cancelled()
            || self.response.is_closed() || !self.fence.valid() { return Err(Error::Cancelled); }
        Ok(())
    }
}
// Non-Clone, nonserializable operation intent. Created only immediately after
// this actor's actual successful initial phased_sync_request dispatch. It grants
// no authentication, key, native IO, inventory completeness or full-hint ACK.
struct DispatchedInitialSyncIntent {
    identity:Arc<()>, original_socket:Socket, fence:Arc<MonitorFence>,
    observer:OwnedOperationObserver, original_child:CancellationToken, epoch:u64,
}
impl DispatchedInitialSyncIntent {
    fn after_actual_dispatch(actor:&MonitorReadReceiver,command:&Command,socket:&Socket)->Result<Self>{
        command.check()?;
        if !matches!(&command.request,MonitorReadRequest::InitialStartup(_))
            || !actor.original_socket.same_original_socket(socket) {return Err(Error::Cancelled)}
        Ok(Self{identity:actor.identity.clone(),original_socket:socket.original_phase_handle(),fence:command.fence.clone(),
            observer:command.observer.clone(),original_child:command.original_child.clone(),epoch:command.epoch})
    }
    // Consuming the actual resource is the one-use boundary. Count selects
    // existing work only; no scalar/caller boolean creates this intent.
    fn into_metadata_request(self,actor:&MonitorReadReceiver,command:&Command,socket:&Socket,
        read:&super::super::sync::ReadOnlySyncPhase,total:Option<u64>,existing:&[String])->Result<Option<Value>> {
        self.observer.check_release()?;command.check()?;
        if !Arc::ptr_eq(&self.identity,&actor.identity)||!Arc::ptr_eq(&self.fence,&command.fence)
            ||self.original_child!=command.original_child||self.epoch!=command.epoch
            ||!self.original_socket.same_original_socket(socket)||!actor.original_socket.same_original_socket(socket)
            ||!read.terminal_markers_received(){return Err(Error::Cancelled)}
        self.observer.check_release()?;command.check()?;
        if !total.is_some_and(|count|count>100){return Ok(None)}
        let mut payload=json!({"existing_chat_ids":existing,"context_epoch":self.epoch});
        if let Some(team)=&self.fence.team{payload["team_id"]=json!(team)}
        Ok(Some(payload))
    }
}
/// Genuine actor completion tied to its original caller/socket. Non-Clone and
/// non-serializable; no booleans/host DTO can construct or import this receipt.
/// Taking DATA still requires the same full original Client/scope/monitor.
pub(in crate::client) struct MonitorReadReceipt {
    identity: Arc<()>, fence: Arc<MonitorFence>, observer: OwnedOperationObserver,
    original_child: CancellationToken, epoch: u64, data: MonitorReadData,
}
impl MonitorReadReceipt {
    pub(in crate::client) fn take(self, client: &Client, monitor: &ChatMonitor, original: &OwnedOperationScope) -> Result<MonitorReadData> {
        if original.child() != self.original_child || !Arc::ptr_eq(&self.fence, &monitor.fence) { return Err(Error::Cancelled); }
        original.check(client)?;
        let identity = monitor.changes.read_port.lock().map_err(|_| Error::Protocol)?
            .as_ref().map(|port| port.identity.clone()).ok_or(Error::Cancelled)?;
        if !Arc::ptr_eq(&identity, &self.identity) || self.epoch == 0 { return Err(Error::Cancelled); }
        client.check_chat_monitor_fence(&self.fence)?;
        self.observer.check_release()?;
        client.check_chat_monitor_fence(&self.fence)?;
        Ok(self.data)
    }
}
/// Cancellation/drop targets only this ticket. It cannot cancel a later B.
pub(in crate::client) struct PreparedMonitorRead {
    response: oneshot::Receiver<Result<MonitorReadReceipt>>, abandoned: CancellationToken,
}
impl PreparedMonitorRead {
    pub(in crate::client) async fn wait(mut self) -> Result<MonitorReadReceipt> {
        (&mut self.response).await.map_err(|_| Error::Cancelled)?
    }
}
impl Drop for PreparedMonitorRead { fn drop(&mut self) { self.abandoned.cancel(); } }

pub(super) fn channel(socket: &Socket) -> (MonitorReadPort, MonitorReadReceiver) {
    let (sender, receiver) = mpsc::channel(QUEUE_CAPACITY);
    let identity = Arc::new(());
    (MonitorReadPort { sender, identity: identity.clone(), next_epoch: Arc::new(AtomicU64::new(0)) },
     MonitorReadReceiver { receiver, original_socket: socket.original_phase_handle(), identity, startup: None, dispatched_epoch: 0 })
}
impl Client {
    /// Synchronous short Client phase BEFORE queueing. No new admission is
    /// minted: only the supplied genuine original scope can restrict this read.
    pub(in crate::client) fn prepare_monitor_read(&self, monitor: &ChatMonitor, original: &OwnedOperationScope, request: MonitorReadRequest) -> Result<PreparedMonitorRead> {
        original.check(self)?;
        self.check_chat_monitor_fence(&monitor.fence)?;
        request.validate(monitor.fence.team.as_deref())?;
        let port = monitor.changes.read_port.lock().map_err(|_| Error::Protocol)?
            .as_ref().cloned().ok_or(Error::Offline)?;
        let epoch = port.next_epoch.fetch_update(Ordering::AcqRel, Ordering::Acquire, |old| old.checked_add(1).filter(|next| *next <= MAX_CONTEXT_EPOCH))
            .map_err(|_| Error::Conflict)? + 1;
        let observer = original.observer();
        let original_child = original.child();
        let abandoned = CancellationToken::new();
        let (response, receiver) = oneshot::channel();
        let command = Command { request, epoch, original_child, abandoned: abandoned.clone(), observer, fence: monitor.fence.clone(), response };
        command.check()?;
        self.check_chat_monitor_fence(&monitor.fence)?;
        port.sender.try_send(command).map_err(|error| match error { mpsc::error::TrySendError::Full(_) => Error::Conflict, mpsc::error::TrySendError::Closed(_) => Error::Offline })?;
        Ok(PreparedMonitorRead { response: receiver, abandoned })
    }
}

// Policy/parser return categories are NOT authenticated denial evidence.
// Only receive_monitor's force-logout result and the shared native monitor
// notification selector can select the original negative-reporting path.
pub(super) struct ActorFailure { error: Error, authenticated_negative: bool }
impl From<Error> for ActorFailure {
    fn from(error: Error) -> Self { Self { error, authenticated_negative: false } }
}
impl ActorFailure {
    fn socket(error: Error) -> Self { Self { error, authenticated_negative: error == Error::Expired } }
    fn observed(error: Error) -> Self { Self { error, authenticated_negative: matches!(error, Error::Expired | Error::Forbidden) } }
    pub(super) fn monitor_error(self) -> Error {
        if !self.authenticated_negative && matches!(self.error, Error::Expired | Error::Forbidden) { Error::Protocol } else { self.error }
    }
}
pub(super) type ActorResult<T> = std::result::Result<T, ActorFailure>;
impl MonitorReadReceiver {
    pub(super) async fn next(&mut self) -> Option<Command> { self.receiver.recv().await }
    pub(super) fn observe_startup(&mut self, kind: &str, payload: &Value) -> Result<()> {
        if kind != "recovery_outputs_discovery_complete" { return Ok(()); }
        // Validate the real connection marker using the maintained parser.
        // Reusing this actual DATA is not fresh request discovery or recovery.
        let mut ignored = BTreeMap::new();
        if super::super::recovery::capture(kind, payload, &mut ignored)? != Some(true) { return Err(Error::Protocol); }
        if cached_view::bounded_bytes(payload, 4096).is_none() { return Err(Error::Protocol); }
        if self.startup.as_ref().is_some_and(|old| &**old != payload) { return Err(Error::Protocol); }
        if self.startup.is_none() { self.startup = Some(Plain::new(payload.clone())); }
        Ok(())
    }
    pub(super) async fn execute(&mut self, command: Command, socket: &mut Socket,
        changes: Option<&Arc<Changes>>, team_hash: Option<&str>, lifecycle: &Value,
        heartbeat: &mut crate::platform::time::Interval, events: &mpsc::Sender<Error>,
    ) -> ActorResult<()> {
        if !self.original_socket.same_original_socket(socket) {
            let _ = command.response.send(Err(Error::Protocol));
            return Err(Error::Protocol.into());
        }
        // A cancelled queued command made no wire request. Leave the original
        // socket usable; after any dispatch failure it is retired by caller.
        if let Err(error) = command.check() { let _ = command.response.send(Err(error)); return Ok(()); }
        if command.epoch <= self.dispatched_epoch { let _ = command.response.send(Err(Error::Conflict)); return Ok(()); }
        // A selected/draft/manual read already used this connection's initial
        // command boundary. It cannot later relabel that socket as startup.
        if matches!(&command.request,MonitorReadRequest::InitialStartup(_)) && self.dispatched_epoch!=0 {
            let _=command.response.send(Err(Error::Conflict));return Ok(());
        }
        self.dispatched_epoch = command.epoch;
        let result = self.drive(&command, socket, changes, team_hash, lifecycle, heartbeat, events).await;
        match result {
            Ok(data) => {
                command.check()?;
                if !self.original_socket.same_original_socket(socket) { return Err(Error::Protocol.into()); }
                let receipt = MonitorReadReceipt { identity: self.identity.clone(), fence: command.fence.clone(), observer: command.observer.clone(), original_child: command.original_child.clone(), epoch: command.epoch, data };
                let _ = command.response.send(Ok(receipt));
                Ok(())
            }
            Err(error) => { let _ = command.response.send(Err(error.error)); Err(error) }
        }
    }
    async fn drive(&mut self, command: &Command, socket: &mut Socket,
        changes: Option<&Arc<Changes>>, team_hash: Option<&str>, lifecycle: &Value,
        heartbeat: &mut crate::platform::time::Interval, events: &mpsc::Sender<Error>,
    ) -> ActorResult<MonitorReadData> {
        let deadline = crate::platform::time::Instant::now() + if matches!(&command.request, MonitorReadRequest::RecentSync | MonitorReadRequest::InitialStartup(_) | MonitorReadRequest::RecentSyncWithExpandedMetadata(_)) { SYNC_READ_TIMEOUT } else { DRAFT_READ_TIMEOUT };
        let mut budget = ReadBudget { frames: 0, bytes: 0 };
        match &command.request {
            MonitorReadRequest::RecentSync | MonitorReadRequest::InitialStartup(_) | MonitorReadRequest::RecentSyncWithExpandedMetadata(_) => {
                // Discovery terminal belongs to the ORIGINAL connection only.
                while self.startup.is_none() {
                    self.frame(command, socket, changes, team_hash, lifecycle, heartbeat, deadline, &mut budget, events).await?;
                }
                let mut read = super::super::sync::ReadOnlySyncPhase::new(command.epoch)?;
                read.accept("recovery_outputs_discovery_complete", self.startup.as_ref().ok_or(Error::Protocol)?, command.fence.team.as_deref())?;
                let mut payload = json!({"phase":"all","context_epoch":command.epoch,"client_chat_versions":{},"client_chat_ids":[],"client_embed_ids":[]});
                if let Some(team) = &command.fence.team { payload["team_id"] = json!(team); }
                checked_send(command, socket, "phased_sync_request", payload, deadline, events).await?;
                let initial_intent=if matches!(&command.request,MonitorReadRequest::InitialStartup(_)) {
                    Some(DispatchedInitialSyncIntent::after_actual_dispatch(self,command,socket)?)
                }else{None};
                let mut startup_total_count = None;
                while !read.terminal_markers_received() {
                    let (kind, payload) = self.frame(command, socket, changes, team_hash, lifecycle, heartbeat, deadline, &mut budget, events).await?;
                    if correlated(&kind, &payload, command)? {
                        read.accept(&kind, &payload, command.fence.team.as_deref())?;
                        if kind == "phase_2_last_20_chats_ready" { startup_total_count = payload["total_chat_count"].as_u64(); }
                    }
                }
                // Existing web policy runs expanded metadata AFTER startup.
                // Count only chooses work, never account/inventory authority.
                // Ordinary RecentSync/CLI/selected opens remain unchanged.
                let metadata_payload=match (&command.request,initial_intent) {
                    (MonitorReadRequest::InitialStartup(existing),Some(intent))=>intent.into_metadata_request(self,command,socket,&read,startup_total_count,existing)?,
                    (MonitorReadRequest::RecentSyncWithExpandedMetadata(existing),None) if startup_total_count.is_some_and(|count|count>100)=>{
                        let mut payload=json!({"existing_chat_ids":existing,"context_epoch":command.epoch});
                        if let Some(team)=&command.fence.team{payload["team_id"]=json!(team)}Some(payload)
                    },
                    (MonitorReadRequest::InitialStartup(_),None)=>return Err(Error::Protocol.into()),
                    _=>None,
                };
                if let Some(payload)=metadata_payload {
                    checked_send(command,socket,"sync_metadata_chats",payload,deadline,events).await?;
                    loop {
                        let(kind,payload)=self.frame(command,socket,changes,team_hash,lifecycle,heartbeat,deadline,&mut budget,events).await?;
                        if correlated(&kind,&payload,command)?&&kind=="sync_metadata_chats_response" {
                            read.accept_post_startup_expanded_metadata(&payload,command.fence.team.as_deref())?;break;
                        }
                    }
                }
                command.check()?;
                Ok(MonitorReadData::RecentSync(read.finish()?))
            }
            MonitorReadRequest::DraftVersions(requested) => {
                let mut read = super::super::draft_read::DraftVersionsRead::new(requested);
                while let Some(chunk) = read.next_chunk() {
                    let payload = json!({"chats":chunk.iter().map(|(id,version)|json!({"chat_id":id,"client_draft_v":version})).collect::<Vec<_>>()});
                    checked_send(command, socket, "get_draft_versions", payload, deadline, events).await?;
                    loop {
                        let (kind, payload) = self.frame(command, socket, changes, team_hash, lifecycle, heartbeat, deadline, &mut budget, events).await?;
                        if kind == "draft_versions_response" { read.accept(&payload)?; break; }
                    }
                }
                let (versions, tombstones) = read.finish()?;
                Ok(MonitorReadData::DraftVersions(Plain::new(MonitorDraftVersions { versions, tombstones })))
            }
            MonitorReadRequest::DraftMetadata(target) => {
                let mut payload = json!({"phase":"phase2","context_epoch":command.epoch,"client_chat_versions":{},"client_chat_ids":[],"client_embed_ids":[]});
                if let Some(target) = target { payload["refresh_chat_ids"] = json!([target]); }
                checked_send(command, socket, "phased_sync_request", payload, deadline, events).await?;
                let mut read = super::super::draft_read::DraftMetadataRead::new(command.epoch);
                while !read.terminal() {
                    let (kind, payload) = self.frame(command, socket, changes, team_hash, lifecycle, heartbeat, deadline, &mut budget, events).await?;
                    if correlated(&kind, &payload, command)? {
                        if !matches!(kind.as_str(), "phase_2_last_20_chats_ready" | "phased_sync_complete") { return Err(Error::Protocol.into()); }
                        read.accept(&kind, &payload)?;
                    }
                }
                command.check()?;
                Ok(MonitorReadData::DraftMetadata(read.finish()?))
            }
        }
    }
    #[allow(clippy::too_many_arguments)] // Fixed original actor resources, never generic RPC.
    async fn frame(&mut self, command: &Command, socket: &mut Socket,
        changes: Option<&Arc<Changes>>, team_hash: Option<&str>, lifecycle: &Value,
        heartbeat: &mut crate::platform::time::Interval, deadline: crate::platform::time::Instant,
        budget: &mut ReadBudget, events: &mpsc::Sender<Error>,
    ) -> ActorResult<(String, Plain<Value>)> {
        loop {
            command.check()?;
            // On a tick/cancel, select drops the pending receive owner BEFORE
            // a heartbeat send or caller return. No second receiver is spawned.
            let frame = tokio::select! { biased;
                _ = command.fence.cancel.cancelled() => return Err(Error::Cancelled.into()),
                _ = command.fence.owner.cancel.cancelled() => return Err(Error::Cancelled.into()),
                _ = command.original_child.cancelled() => return Err(Error::Cancelled.into()),
                // The original request token is not linked to the lease child.
                _ = command.observer.cancelled() => return Err(Error::Cancelled.into()),
                _ = command.abandoned.cancelled() => return Err(Error::Cancelled.into()),
                _ = events.closed() => return Err(Error::Cancelled.into()),
                _ = heartbeat.tick() => None,
                result = crate::platform::time::timeout_at(deadline, transport::receive_monitor(socket)) => {
                    let (kind, payload) = result.map_err(|_| Error::Offline)?.map_err(ActorFailure::socket)?;
                    Some((kind, Plain::new(payload)))
                },
            };
            let Some((kind, payload)) = frame else {
                command.check()?;
                checked_send(command, socket, "native_client_lifecycle", lifecycle.clone(), deadline, events).await?;
                continue;
            };
            // This frame already belongs to the ORIGINAL socket. Process its
            // authenticated negatives before request-only callbacks/budgets can
            // refuse A. No private DATA or continuation is released by this
            // callback-free selector; the original request check still follows.
            observe_frame(&kind, &payload, changes, Some(&command.fence), team_hash).map_err(ActorFailure::observed)?;
            command.check()?;
            budget.observe(&payload)?;
            self.observe_startup(&kind, &payload)?;
            command.check()?;
            return Ok((kind, payload));
        }
    }
}
struct ReadBudget { frames: usize, bytes: usize }
impl ReadBudget {
    fn observe(&mut self, payload: &Value) -> Result<()> {
        self.frames = self.frames.checked_add(1).ok_or(Error::Protocol)?;
        let size = cached_view::bounded_bytes(payload, transport::MAX_BODY).ok_or(Error::Protocol)?;
        self.bytes = self.bytes.checked_add(size).ok_or(Error::Protocol)?;
        if self.frames > MAX_READ_FRAMES || self.bytes > MAX_READ_BYTES { return Err(Error::Protocol); }
        Ok(())
    }
}
fn correlated(kind: &str, payload: &Value, command: &Command) -> Result<bool> {
    if !matches!(kind, "phase_1_last_chat_ready" | "phase_1b_chat_content_ready" | "phase_1b_last_chat_messages_ready" | "phase_2_last_20_chats_ready" | "phase_3_chunk_ready" | "phased_sync_complete" | "sync_metadata_chats_response" | "load_more_chats_response") { return Ok(false); }
    let epoch = payload.get("context_epoch").and_then(Value::as_u64).ok_or(Error::Protocol)?;
    if epoch != command.epoch { return Ok(false); }
    if payload.get("team_id").and_then(Value::as_str) != command.fence.team.as_deref()
        || (command.fence.team.is_none() && !payload.get("team_id").is_some_and(Value::is_null)) { return Err(Error::Forbidden); }
    Ok(true)
}
async fn checked_send(command: &Command, socket: &mut Socket, kind: &'static str, payload: Value,
    deadline: crate::platform::time::Instant, events: &mpsc::Sender<Error>,
) -> ActorResult<()> {
    command.check()?;
    if events.is_closed() { return Err(Error::Cancelled.into()); }
    let send_deadline = (crate::platform::time::Instant::now() + Duration::from_secs(10)).min(deadline);
    tokio::select! { biased;
        _ = command.fence.cancel.cancelled() => return Err(Error::Cancelled.into()),
        _ = command.fence.owner.cancel.cancelled() => return Err(Error::Cancelled.into()),
        _ = command.original_child.cancelled() => return Err(Error::Cancelled.into()),
        _ = command.abandoned.cancelled() => return Err(Error::Cancelled.into()),
        _ = events.closed() => return Err(Error::Cancelled.into()),
        result = crate::platform::time::timeout_at(send_deadline, transport::send(socket,kind,payload)) => result.map_err(|_| Error::Offline)??,
    }
    command.check().map_err(Into::into)
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "monitor_actor_tests.rs"]
mod tests;
