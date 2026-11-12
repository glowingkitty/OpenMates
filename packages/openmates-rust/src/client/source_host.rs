//! PRIVATE DRAFT: detached opaque source-host routing, never filesystem permission.
use super::{project_task_watch::WatchAuthority, transport, *};
use crate::platform::time::Instant;
use crate::work::ProjectSourceCapability;
use serde::{Deserialize, Serialize};
use std::{
    collections::{BTreeMap, VecDeque},
    sync::Arc,
};
const MAX_REQUESTS: usize = 4;
const MAX_ENVELOPE: usize = 256 * 1024;
const ACK_TIMEOUT: Duration = Duration::from_secs(20);
const HEARTBEAT_INTERVAL: Duration = Duration::from_secs(15);
const HEARTBEAT_MIN: Duration = Duration::from_secs(10);
const LEASE: Duration = Duration::from_secs(45);
#[derive(Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceHostOperation {
    List,
    Search,
    ReadText,
    ReadImageChunk,
    ReadFileChunk,
    CreateFile,
    UpdateFile,
    CopyEntries,
    MoveEntries,
    /// One confined argv command in the request root (needs the
    /// `run_command` capability and, like a write, chat/operation/digest).
    RunCommand,
    /// Read-only state of the chat worktree (needs `read`).
    GitStatus,
    /// Stage everything in the chat worktree and commit (needs
    /// `write_request`; chat/operation/digest like a write).
    GitCommit,
    /// Rebase the chat's commits onto the target branch and fast-forward it
    /// locally (needs `write_request`; chat/operation/digest like a write).
    GitLand,
}
impl SourceHostOperation {
    fn capability(self) -> ProjectSourceCapability {
        match self {
            Self::Search => ProjectSourceCapability::Search,
            Self::CreateFile
            | Self::UpdateFile
            | Self::CopyEntries
            | Self::MoveEntries
            | Self::GitCommit
            | Self::GitLand => ProjectSourceCapability::WriteRequest,
            Self::RunCommand => ProjectSourceCapability::RunCommand,
            _ => ProjectSourceCapability::Read,
        }
    }
}
/// Explicit adapter implementation evidence. This callback checks implementation
/// support only; it must not execute requests or infer filesystem permission.
pub trait SourceHostAdapter: Send + Sync {
    fn implemented_capabilities(&self) -> Vec<ProjectSourceCapability>;
    fn supports_operation(&self, operation: SourceHostOperation) -> bool;
}
#[derive(Clone)]
pub(crate) struct SourceHostScope {
    pub(crate) api: String,
    pub(crate) owner: String,
    pub(crate) team: Option<String>,
    pub(crate) project: String,
    pub(crate) source: String,
    pub(crate) key_epoch: u64,
}
pub struct SourceHostBinding {
    scope: SourceHostScope,
    key: Key,
    adapter: Arc<dyn SourceHostAdapter>,
    capabilities: Vec<ProjectSourceCapability>,
    authority: Arc<WatchAuthority>,
    expires_at: Option<u64>,
}
pub struct SourceHostOptions {
    pub source_session_id: String,
    pub confirmed_takeover: bool,
}
pub struct SourceHostStart {
    socket: transport::SourceHostSocketRequest,
    bindings: Vec<SourceHostBinding>,
    options: SourceHostOptions,
    lifetime: CancellationToken,
}
pub struct SourceHostSession {
    socket: Option<transport::Socket>,
    bindings: Vec<SourceHostBinding>,
    options: SourceHostOptions,
    lifetime: CancellationToken,
    handles: CancellationToken,
    identity: Arc<()>,
    lease: Option<Instant>,
    heartbeat_sent: Instant,
    pending: BTreeMap<String, Arc<()>>,
    queued: VecDeque<SourceHostRequestFrame>,
    terminal: bool,
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceHostRoutingIdentity {
    pub context_type: String,
    pub context_id_hash: String,
    pub host_member_hash: String,
    pub host_device_fingerprint_hash: String,
    pub requester_member_hash: String,
    pub requester_device_fingerprint_hash: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceHostRequestFrame {
    pub request_id: String,
    pub project_id: String,
    pub source_id: String,
    pub source_session_id: String,
    pub requesting_client_id: String,
    pub operation: SourceHostOperation,
    pub key_epoch: u64,
    pub encrypted_envelope: String,
    pub chat_id: Option<String>,
    pub operation_id: Option<String>,
    pub proposal_digest: Option<String>,
    pub user_initiated: Option<bool>,
    pub routing_identity: Option<SourceHostRoutingIdentity>,
    /// Workspace chat (the root parent chat of the requesting chat, resolved
    /// by the backend). Selects the chat worktree of a Git source; optional so
    /// older backends that omit it keep live source-root edits.
    #[serde(default)]
    pub workspace_chat_id: Option<String>,
}
pub enum SourceHostPoll {
    Idle,
    Read(SourceHostRead),
}
/// No plaintext or permission getter before current Client authority fencing.
pub struct SourceHostRead {
    frame: Box<SourceHostRequestFrame>,
    identity: Arc<()>,
    authority: Arc<WatchAuthority>,
    lifetime: CancellationToken,
    nonce: Arc<()>,
}
/// Provisional routing only; adapter still authenticates encryption and performs
/// fresh per-source, platform/root and operation-specific authorization.
pub struct SourceHostRequest {
    frame: Box<SourceHostRequestFrame>,
    identity: Arc<()>,
    authority: Arc<WatchAuthority>,
    lifetime: CancellationToken,
    nonce: Arc<()>,
    expires_at: Option<u64>,
    lease: Instant,
}
/// Negative-fenced wrapper around existing SDK crypto, never an execution grant.
pub struct SourceHostHandshake {
    state: crate::remote_access_crypto::HandshakeState,
    fence: SourceHostCryptoFence,
}
pub struct SourceHostRemoteCrypto {
    state: crate::remote_access_crypto::RemoteSession,
    fence: SourceHostCryptoFence,
}
struct SourceHostCryptoFence {
    authority: Arc<WatchAuthority>,
    lifetime: CancellationToken,
    expires_at: Option<u64>,
    lease: Instant,
    request_id: String,
}
impl SourceHostCryptoFence {
    fn check(&self) -> Result<()> {
        if self.authority.cancel.is_cancelled() || self.lifetime.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if self.expires_at.is_some_and(|at| at <= now_ms()) {
            return Err(Error::Expired);
        }
        if self.lease <= Instant::now() {
            return Err(Error::Offline);
        }
        Ok(())
    }
}
impl SourceHostHandshake {
    pub fn handshake(&self) -> Result<crate::remote_access_crypto::Handshake> {
        self.fence.check()?;
        let handshake = self.state.handshake();
        self.fence.check()?;
        Ok(handshake)
    }
    pub fn finish(
        self,
        remote: &crate::remote_access_crypto::Handshake,
    ) -> Result<SourceHostRemoteCrypto> {
        self.fence.check()?;
        let state = self.state.finish(remote)?;
        self.fence.check()?;
        Ok(SourceHostRemoteCrypto {
            state,
            fence: self.fence,
        })
    }
}
impl SourceHostRemoteCrypto {
    pub fn seal(&mut self, plaintext: &[u8]) -> Result<crate::remote_access_crypto::Envelope> {
        self.fence.check()?;
        let envelope = self.state.seal(&self.fence.request_id, plaintext)?;
        self.fence.check()?;
        Ok(envelope)
    }
    pub fn open(
        &mut self,
        envelope: &crate::remote_access_crypto::Envelope,
    ) -> Result<zeroize::Zeroizing<Vec<u8>>> {
        self.fence.check()?;
        let plaintext = self.state.open(&self.fence.request_id, envelope)?;
        self.fence.check()?;
        Ok(plaintext)
    }
}
impl SourceHostRequest {
    pub fn provisional_envelope(&self) -> Result<&SourceHostRequestFrame> {
        self.check()?;
        Ok(&self.frame)
    }
    pub fn server_acknowledgement_required(&self) -> bool {
        true
    }
    fn check(&self) -> Result<()> {
        if self.authority.cancel.is_cancelled() || self.lifetime.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if self.expires_at.is_some_and(|v| v <= now_ms()) {
            return Err(Error::Expired);
        }
        if self.lease <= Instant::now() {
            return Err(Error::Offline);
        }
        Ok(())
    }
}
impl Client {
    pub(crate) fn bind_source_host(
        &self,
        scope: SourceHostScope,
        key: Key,
        adapter: Arc<dyn SourceHostAdapter>,
        capabilities: Vec<ProjectSourceCapability>,
    ) -> Result<SourceHostBinding> {
        let session = self.require_credentials()?;
        if scope.api != self.base.as_str().trim_end_matches('/')
            || Some(scope.owner.as_str())
                != self.user()["id"]
                    .as_str()
                    .or_else(|| self.user()["user_id"].as_str())
        {
            return Err(Error::Forbidden);
        }
        Ok(SourceHostBinding {
            scope,
            key,
            adapter,
            capabilities,
            authority: self.task_watch_authority.clone(),
            expires_at: session.paired_session_expires_at,
        })
    }
    fn check_source_host(&self, bindings: &[SourceHostBinding]) -> Result<()> {
        self.require_credentials()?;
        for binding in bindings {
            if binding.authority.cancel.is_cancelled()
                || !Arc::ptr_eq(&binding.authority, &self.task_watch_authority)
            {
                return Err(Error::Cancelled);
            }
            if binding.scope.api != self.base.as_str().trim_end_matches('/')
                || Some(binding.scope.owner.as_str())
                    != self.user()["id"]
                        .as_str()
                        .or_else(|| self.user()["user_id"].as_str())
            {
                return Err(Error::Forbidden);
            }
            if binding.expires_at.is_some_and(|v| v <= now_ms()) {
                return Err(Error::Expired);
            }
        }
        Ok(())
    }
    pub fn prepare_source_host(
        &self,
        bindings: Vec<SourceHostBinding>,
        options: SourceHostOptions,
        cancel: CancellationToken,
    ) -> Result<SourceHostStart> {
        self.check_source_host(&bindings)?;
        identifier(&options.source_session_id)?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if bindings.is_empty() || bindings.len() > 16 {
            return Err(Error::Invalid("Supply 1 to 16 explicit host bindings."));
        }
        let first = &bindings[0].scope;
        let mut seen = std::collections::BTreeSet::new();
        for b in &bindings {
            if b.scope.owner != first.owner
                || b.scope.team != first.team
                || b.scope.api != first.api
                || !seen.insert((&b.scope.project, &b.scope.source))
            {
                return Err(Error::Forbidden);
            }
        }
        Ok(SourceHostStart {
            socket: self.prepare_source_host_socket()?,
            bindings,
            options,
            lifetime: cancel.child_token(),
        })
    }
    pub fn finish_source_host_read(
        &mut self,
        host: &SourceHostSession,
        read: SourceHostRead,
    ) -> Result<SourceHostRequest> {
        self.check_source_host(&host.bindings)?;
        host.check()?;
        if !Arc::ptr_eq(&host.identity, &read.identity)
            || read.lifetime.is_cancelled()
            || !Arc::ptr_eq(&read.authority, &self.task_watch_authority)
        {
            return Err(Error::Cancelled);
        }
        Ok(SourceHostRequest {
            frame: read.frame,
            identity: read.identity,
            authority: read.authority,
            lifetime: read.lifetime,
            nonce: read.nonce,
            expires_at: host.bindings.iter().filter_map(|b| b.expires_at).min(),
            lease: host.lease.ok_or(Error::Offline)?,
        })
    }
    /// Explicit reconnect reauthorizes every source using current credentials.
    /// Old requests are fenced before the first canonical HTTP await.
    pub async fn prepare_source_host_reconnect(
        &mut self,
        host: &mut SourceHostSession,
        cancel: CancellationToken,
    ) -> Result<SourceHostStart> {
        self.check_source_host(&host.bindings)?;
        let originals = host
            .bindings
            .iter()
            .map(|b| (b.scope.clone(), b.adapter.clone(), b.expires_at))
            .collect::<Vec<_>>();
        let options = SourceHostOptions {
            source_session_id: host.options.source_session_id.clone(),
            confirmed_takeover: host.options.confirmed_takeover,
        };
        host.close();
        let mut bindings = Vec::new();
        for (scope, adapter, original_expiry) in originals {
            let filters = crate::work::ProjectFilters {
                personal: scope.team.is_none(),
                team_id: scope.team.clone(),
                ..Default::default()
            };
            let mut binding = self
                .projects()
                .with_filters(filters)
                .source_host_binding(&scope.project, &scope.source, adapter)
                .await?;
            binding.expires_at = [binding.expires_at, original_expiry]
                .into_iter()
                .flatten()
                .min();
            bindings.push(binding);
        }
        self.prepare_source_host(bindings, options, cancel)
    }
    /// Apply a detached Expired failure only to this exact original Client epoch.
    pub fn finish_source_host_failure(
        &mut self,
        host: &SourceHostSession,
        error: Error,
    ) -> Result<()> {
        self.check_source_host(&host.bindings)?;
        if error == Error::Expired {
            self.forget_session();
        }
        Err(error)
    }
}
fn identifier(v: &str) -> Result<()> {
    if v.is_empty() || v.len() > 128 || v.chars().any(char::is_control) {
        Err(Error::Protocol)
    } else {
        Ok(())
    }
}
fn canonical_hash(v: &str) -> bool {
    v.len() == 64
        && v.bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
fn error_code(code: &str) -> Error {
    match code {
        "takeover_confirmation_required" | "request_already_completed" => Error::Conflict,
        "source_not_found"
        | "source_host_mismatch"
        | "source_capability_denied"
        | "team_membership_required"
        | "session_scope_mismatch"
        | "request_scope_mismatch"
        | "source_session_changed" => Error::Forbidden,
        "source_offline" => Error::Offline,
        _ => Error::Protocol,
    }
}
/// One boundary covers every await in an operation, including handshake,
/// lifecycle/control writes, and ACK reads. No send phase starts a fresh budget.
async fn bounded_host_io<T>(
    budget: Duration,
    cancel: &CancellationToken,
    owner: &CancellationToken,
    lifetime: &CancellationToken,
    expires_at: Option<u64>,
    lease: Option<Instant>,
    operation: impl std::future::Future<Output = Result<T>>,
) -> Result<T> {
    let mut deadline = Instant::now() + budget;
    if let Some(lease) = lease {
        deadline = deadline.min(lease)
    }
    if let Some(expiry) = expires_at {
        if expiry <= now_ms() {
            return Err(Error::Expired);
        }
        deadline =
            deadline.min(Instant::now() + Duration::from_millis(expiry.saturating_sub(now_ms())));
    }
    let result = tokio::select! {biased;
        _=cancel.cancelled()=>Err(Error::Cancelled),
        _=owner.cancelled()=>Err(Error::Cancelled),
        _=lifetime.cancelled()=>Err(Error::Cancelled),
        result=crate::platform::time::timeout_at(deadline,operation)=>match result {
            Ok(result)=>result,
            Err(_)=>Err(if expires_at.is_some_and(|at|at<=now_ms()){Error::Expired}else{Error::Offline}),
        }
    };
    if cancel.is_cancelled() || owner.is_cancelled() || lifetime.is_cancelled() {
        return Err(Error::Cancelled);
    }
    if expires_at.is_some_and(|at| at <= now_ms()) {
        return Err(Error::Expired);
    }
    if lease.is_some_and(|at| at <= Instant::now()) {
        return Err(Error::Offline);
    }
    result
}
impl SourceHostStart {
    pub async fn connect(self) -> Result<SourceHostSession> {
        if self
            .bindings
            .iter()
            .any(|b| b.expires_at.is_some_and(|at| at <= now_ms()))
        {
            return Err(Error::Expired);
        }
        let socket = bounded_host_io(
            Duration::from_secs(10),
            &self.lifetime,
            &self.bindings[0].authority.cancel,
            &self.lifetime,
            self.bindings.iter().filter_map(|b| b.expires_at).min(),
            None,
            transport::connect_source_host_socket(self.socket),
        )
        .await?;
        let handles = self.lifetime.child_token();
        let mut host = SourceHostSession {
            socket: Some(socket),
            bindings: self.bindings,
            options: self.options,
            lifetime: self.lifetime,
            handles,
            identity: Arc::new(()),
            lease: None,
            heartbeat_sent: Instant::now(),
            pending: BTreeMap::new(),
            queued: VecDeque::new(),
            terminal: false,
        };
        let payload = host.registration();
        if let Err(error) = host
            .exchange(
                "project_remote_access_register",
                payload,
                "project_remote_access_registered",
                &CancellationToken::new(),
            )
            .await
        {
            host.close();
            return Err(error);
        }
        Ok(host)
    }
}
impl SourceHostSession {
    fn lifecycle(&self) -> Value {
        let mut v = json!({"source_session_id":self.options.source_session_id});
        if let Some(team) = &self.bindings[0].scope.team {
            v["team_id"] = json!(team)
        }
        v
    }
    fn registration(&self) -> Value {
        let mut v = self.lifecycle();
        v["confirmed_takeover"] = json!(self.options.confirmed_takeover);
        v["bindings"] = Value::Array(
            self.bindings
                .iter()
                .map(|b| {
                    // npm advertises `import` with `read`: imports are plain
                    // reads on the host, gated by the backend capability.
                    let mut capabilities = b.capabilities.clone();
                    if capabilities.contains(&ProjectSourceCapability::Read)
                        && !capabilities.contains(&ProjectSourceCapability::Import)
                    {
                        capabilities.insert(
                            capabilities
                                .iter()
                                .position(|c| *c == ProjectSourceCapability::WriteRequest)
                                .unwrap_or(capabilities.len()),
                            ProjectSourceCapability::Import,
                        );
                    }
                    json!({"project_id":b.scope.project,"source_id":b.scope.source,"key_epoch":b.scope.key_epoch,"capabilities":capabilities})
                })
                .collect(),
        );
        v
    }
    fn check(&self) -> Result<()> {
        if self.terminal
            || self.lifetime.is_cancelled()
            || self
                .bindings
                .iter()
                .any(|b| b.authority.cancel.is_cancelled())
        {
            return Err(Error::Cancelled);
        }
        if self
            .bindings
            .iter()
            .any(|b| b.expires_at.is_some_and(|at| at <= now_ms()))
        {
            return Err(Error::Expired);
        }
        if self.lease.is_some_and(|at| at <= Instant::now()) {
            return Err(Error::Offline);
        }
        Ok(())
    }
    fn queue_request(&mut self, value: Value) -> Result<()> {
        let frame: SourceHostRequestFrame = serde_json::from_value(value)?;
        for id in [
            &frame.request_id,
            &frame.project_id,
            &frame.source_id,
            &frame.source_session_id,
            &frame.requesting_client_id,
        ] {
            identifier(id)?
        }
        if frame.source_session_id != self.options.source_session_id
            || frame.encrypted_envelope.is_empty()
            || frame.encrypted_envelope.len() > MAX_ENVELOPE
        {
            return Err(Error::Forbidden);
        }
        let binding = self
            .bindings
            .iter()
            .find(|b| {
                b.scope.project == frame.project_id
                    && b.scope.source == frame.source_id
                    && b.scope.key_epoch == frame.key_epoch
            })
            .ok_or(Error::Forbidden)?;
        if !binding.capabilities.contains(&frame.operation.capability())
            || !binding.adapter.supports_operation(frame.operation)
        {
            return Err(Error::Forbidden);
        }
        if matches!(
            frame.operation,
            SourceHostOperation::CreateFile
                | SourceHostOperation::UpdateFile
                | SourceHostOperation::RunCommand
                | SourceHostOperation::GitCommit
                | SourceHostOperation::GitLand
        ) {
            identifier(frame.chat_id.as_deref().ok_or(Error::Protocol)?)?;
            identifier(frame.operation_id.as_deref().ok_or(Error::Protocol)?)?;
            if !frame.proposal_digest.as_deref().is_some_and(canonical_hash) {
                return Err(Error::Protocol);
            }
        }
        if let Some(workspace) = frame.workspace_chat_id.as_deref() {
            identifier(workspace)?;
        }
        if matches!(
            frame.operation,
            SourceHostOperation::CopyEntries | SourceHostOperation::MoveEntries
        ) && frame.user_initiated != Some(true)
        {
            return Err(Error::Forbidden);
        }
        if let Some(team) = &binding.scope.team {
            let routing = frame.routing_identity.as_ref().ok_or(Error::Forbidden)?;
            let context = crate::work::hash(team);
            if routing.context_type != "team"
                || routing.context_id_hash != context
                || routing.host_member_hash
                    != crate::work::hash(&format!(
                        "{context}:{}",
                        crate::work::hash(&binding.scope.owner)
                    ))
                || ![
                    &routing.host_device_fingerprint_hash,
                    &routing.requester_member_hash,
                    &routing.requester_device_fingerprint_hash,
                ]
                .iter()
                .all(|v| canonical_hash(v))
            {
                return Err(Error::Forbidden);
            }
        } else if frame.routing_identity.is_some() {
            return Err(Error::Forbidden);
        }
        if self.pending.len() >= MAX_REQUESTS || self.pending.contains_key(&frame.request_id) {
            return Err(Error::Conflict);
        }
        self.pending.insert(frame.request_id.clone(), Arc::new(()));
        self.queued.push_back(frame);
        Ok(())
    }
    async fn read_wire(&mut self, cancel: &CancellationToken) -> Result<Option<(String, Value)>> {
        self.check()?;
        let socket = self.socket.as_mut().ok_or(Error::Offline)?;
        tokio::select! {biased; _=self.lifetime.cancelled()=>Err(Error::Cancelled), _=self.bindings[0].authority.cancel.cancelled()=>Err(Error::Cancelled),_=cancel.cancelled()=>Err(Error::Cancelled),result=crate::platform::time::timeout(Duration::from_millis(250),transport::receive_source_host(socket))=>match result {Ok(value)=>value.map(Some),Err(_)=>Ok(None)}}
    }
    async fn exchange(
        &mut self,
        kind: &str,
        payload: Value,
        ack: &str,
        cancel: &CancellationToken,
    ) -> Result<()> {
        self.check()?;
        let lifetime = self.lifetime.clone();
        let owner = self.bindings[0].authority.cancel.clone();
        let expires_at = self.bindings.iter().filter_map(|b| b.expires_at).min();
        let lease = self.lease;
        let result=bounded_host_io(ACK_TIMEOUT,cancel,&owner,&lifetime,expires_at,lease,async {
            tokio::select! {biased;_=self.lifetime.cancelled()=>return Err(Error::Cancelled),_=self.bindings[0].authority.cancel.cancelled()=>return Err(Error::Cancelled),_=cancel.cancelled()=>return Err(Error::Cancelled),result=transport::send(self.socket.as_mut().ok_or(Error::Offline)?,kind,payload.clone())=>result?}
            loop {
                let Some((received,value))=self.read_wire(cancel).await? else{continue};
                if received=="project_remote_access_request" {self.queue_request(value)?;continue}
                if received=="error" {return Err(error_code(value["code"].as_str().unwrap_or("")))}
                if received!=ack {if received.starts_with("project_remote_access_"){return Err(Error::Protocol)}continue}
                match ack {
                    "project_remote_access_registered"=>{if value["source_session_id"]!=self.options.source_session_id||value["heartbeat_interval_seconds"]!=15{return Err(Error::Protocol)}match value.get("replaced_session_id") {Some(Value::Null)=>{},Some(Value::String(id))=>identifier(id)?,_=>return Err(Error::Protocol)}self.accept_deadline(&value)?;self.heartbeat_sent=Instant::now();},
                    "project_remote_access_heartbeat_ack"=>{if value["accepted"]!=true{return Err(Error::Protocol)}self.accept_deadline(&value)?;},
                    "project_remote_access_completion_ack"=>{if value["accepted"]!=true||value["request_id"]!=payload["request_id"]{return Err(Error::Protocol)}},
                    "project_remote_access_disconnected"=>{if !value["accepted"].is_boolean(){return Err(Error::Protocol)}},_=>return Err(Error::Protocol)
                } self.check()?; return Ok(())
            }
        }).await;
        if result.is_err() {
            self.close()
        }
        result
    }
    fn accept_deadline(&mut self, value: &Value) -> Result<()> {
        let deadline = value["deadline_at"].as_u64().ok_or(Error::Protocol)?;
        let now = now_ms() / 1000;
        if deadline <= now || deadline > now.saturating_add(45) {
            return Err(Error::Protocol);
        }
        self.lease = Some(Instant::now() + Duration::from_secs(deadline - now).min(LEASE));
        Ok(())
    }
    pub async fn poll(&mut self, cancel: &CancellationToken) -> Result<SourceHostPoll> {
        self.check()?;
        // Prioritize wire/control processing even when a provisional item waits.
        match self.read_wire(cancel).await {
            Ok(Some((kind, value))) if kind == "project_remote_access_request" => {
                if let Err(error) = self.queue_request(value) {
                    self.close();
                    return Err(error);
                }
            }
            Ok(Some((kind, value))) if kind == "error" => {
                let error = error_code(value["code"].as_str().unwrap_or(""));
                self.close();
                return Err(error);
            }
            Err(error) => {
                self.close();
                return Err(error);
            }
            _ => {}
        }
        if self.heartbeat_sent.elapsed() >= HEARTBEAT_INTERVAL {
            self.heartbeat(cancel).await?
        }
        let Some(frame) = self.queued.pop_front() else {
            return Ok(SourceHostPoll::Idle);
        };
        let nonce = self
            .pending
            .get(&frame.request_id)
            .ok_or(Error::Protocol)?
            .clone();
        Ok(SourceHostPoll::Read(SourceHostRead {
            frame: Box::new(frame),
            identity: self.identity.clone(),
            authority: self.bindings[0].authority.clone(),
            lifetime: self.handles.clone(),
            nonce,
        }))
    }
    pub async fn heartbeat(&mut self, cancel: &CancellationToken) -> Result<()> {
        self.check()?;
        if self.heartbeat_sent.elapsed() < HEARTBEAT_MIN {
            return Err(Error::Invalid("Source heartbeat is too early."));
        }
        self.heartbeat_sent = Instant::now();
        self.exchange(
            "project_remote_access_heartbeat",
            self.lifecycle(),
            "project_remote_access_heartbeat_ack",
            cancel,
        )
        .await
    }
    /// Reuse the SDK's authenticated Personal-v1 / Team-v2 handshake. This
    /// authenticates encrypted peers only; it grants no filesystem authority.
    pub fn source_handshake(&self, request: &SourceHostRequest) -> Result<SourceHostHandshake> {
        self.check()?;
        request.check()?;
        if !Arc::ptr_eq(&request.identity, &self.identity)
            || !self
                .pending
                .get(&request.frame.request_id)
                .is_some_and(|nonce| Arc::ptr_eq(nonce, &request.nonce))
        {
            return Err(Error::Forbidden);
        }
        let frame = &request.frame;
        let binding = self
            .bindings
            .iter()
            .find(|b| {
                b.scope.project == frame.project_id
                    && b.scope.source == frame.source_id
                    && b.scope.key_epoch == frame.key_epoch
            })
            .ok_or(Error::Forbidden)?;
        let routing = frame.routing_identity.as_ref();
        let identity = crate::remote_access_crypto::Identity {
            owner_id: routing
                .map(|r| r.context_id_hash.clone())
                .unwrap_or_else(|| binding.scope.owner.clone()),
            context_type: routing.map(|_| crate::remote_access_crypto::ContextType::Team),
            context_id: routing.map(|r| r.context_id_hash.clone()),
            project_id: frame.project_id.clone(),
            source_id: frame.source_id.clone(),
            source_session_id: self.options.source_session_id.clone(),
            requesting_client_id: frame.requesting_client_id.clone(),
            key_epoch: frame.key_epoch,
            host_member_id: routing.map(|r| r.host_member_hash.clone()),
            host_device_id: routing.map(|r| r.host_device_fingerprint_hash.clone()),
            requester_member_id: routing.map(|r| r.requester_member_hash.clone()),
            requester_device_id: routing.map(|r| r.requester_device_fingerprint_hash.clone()),
        };
        let state = crate::remote_access_crypto::HandshakeState::new(
            &binding.key,
            identity,
            crate::remote_access_crypto::Role::Source,
        )?;
        self.check()?;
        request.check()?;
        Ok(SourceHostHandshake {
            state,
            fence: SourceHostCryptoFence {
                authority: request.authority.clone(),
                lifetime: request.lifetime.clone(),
                expires_at: request.expires_at,
                lease: request.lease,
                request_id: frame.request_id.clone(),
            },
        })
    }
    /// The Project key of this request's binding, for the legacy bootstrap
    /// envelope and the proposal digest. Only the core host dispatcher uses
    /// it; the key never leaves the crate.
    ///
    /// # Errors
    /// `Forbidden` when the request does not belong to this session.
    pub(crate) fn request_key(&self, request: &SourceHostRequest) -> Result<Key> {
        self.check()?;
        request.check()?;
        if !Arc::ptr_eq(&request.identity, &self.identity)
            || !self
                .pending
                .get(&request.frame.request_id)
                .is_some_and(|nonce| Arc::ptr_eq(nonce, &request.nonce))
        {
            return Err(Error::Forbidden);
        }
        let frame = &request.frame;
        self.bindings
            .iter()
            .find(|b| {
                b.scope.project == frame.project_id
                    && b.scope.source == frame.source_id
                    && b.scope.key_epoch == frame.key_epoch
            })
            .map(|b| b.key.clone())
            .ok_or(Error::Forbidden)
    }
    /// Drop a request without completing it (npm fails closed silently on an
    /// invalid bootstrap). Frees its pending slot; the relay times it out.
    pub fn abandon(&mut self, request: SourceHostRequest) {
        if Arc::ptr_eq(&request.identity, &self.identity) {
            self.pending.remove(&request.frame.request_id);
        }
    }
    pub async fn complete(
        &mut self,
        request: SourceHostRequest,
        encrypted_envelope: String,
        cancel: &CancellationToken,
    ) -> Result<()> {
        self.check()?;
        request.check()?;
        if !Arc::ptr_eq(&request.identity, &self.identity)
            || !self
                .pending
                .get(&request.frame.request_id)
                .is_some_and(|nonce| Arc::ptr_eq(nonce, &request.nonce))
            || encrypted_envelope.is_empty()
            || encrypted_envelope.len() > MAX_ENVELOPE
        {
            return Err(Error::Forbidden);
        }
        let frame = &request.frame;
        let mut payload = self.lifecycle();
        for (field, value) in [
            ("project_id", json!(frame.project_id)),
            ("source_id", json!(frame.source_id)),
            ("request_id", json!(frame.request_id)),
            ("key_epoch", json!(frame.key_epoch)),
            ("encrypted_envelope", json!(encrypted_envelope)),
        ] {
            payload[field] = value;
        }
        // Remove before sending: uncertain/lost ACK must not enable a retry.
        self.pending.remove(&frame.request_id);
        self.exchange(
            "project_remote_access_complete",
            payload,
            "project_remote_access_completion_ack",
            cancel,
        )
        .await
    }
    pub async fn disconnect(&mut self, cancel: &CancellationToken) -> Result<()> {
        // Fence handles before any awaited disconnect, but retain the socket's
        // private control ability long enough for one bounded best-effort send.
        self.handles.cancel();
        self.identity = Arc::new(());
        self.pending.clear();
        self.queued.clear();
        let result = self
            .exchange(
                "project_remote_access_disconnect",
                self.lifecycle(),
                "project_remote_access_disconnected",
                cancel,
            )
            .await;
        self.close();
        result
    }
    pub fn close(&mut self) {
        self.handles.cancel();
        self.lifetime.cancel();
        self.socket = None;
        self.pending.clear();
        self.queued.clear();
        self.terminal = true;
        self.identity = Arc::new(())
    }
}
impl Drop for SourceHostSession {
    fn drop(&mut self) {
        self.close()
    }
}

#[cfg(test)]
mod tests;
