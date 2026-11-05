//! Task-only authenticated socket. No profile, generic I/O or execution surface.
//! One reducer owns committed and staged state. Durable callers commit explicitly.
use super::{transport, *};
use crate::platform::time::Instant;
use crate::project_task_sync::{
    ProjectTaskSync, TaskSyncCheckpoint, TaskSyncCommit, TaskSyncConnection, TaskSyncEvent,
    TaskSyncPublication, TaskSyncScope, TaskSyncSnapshot, TaskSyncWorkspace,
};
use std::sync::Arc;
const READ_SLICE: Duration = Duration::from_millis(250);
const REAUTHORIZE_AFTER: Duration = Duration::from_secs(45);
const PUBLICATION_DEADLINE: Duration = Duration::from_secs(5);

pub(super) struct WatchAuthority {
    pub(super) cancel: CancellationToken,
    cached_denials: Arc<std::sync::RwLock<CachedChatDenials>>,
    // Negative wake only, shared with the SAME retained denial ledger. Neither
    // notification nor silence attests read/effect/publication authority.
    denial_changed:Arc<tokio::sync::Notify>,
}
impl WatchAuthority {
    pub(super) fn new() -> Self {
        Self {
            cancel: CancellationToken::new(),
            cached_denials: Arc::new(std::sync::RwLock::new(CachedChatDenials::default())),
            denial_changed:Arc::new(tokio::sync::Notify::new()),
        }
    }
    // Replacing only the server transport grant must not forget authoritative
    // same-owner resource denials. Even a late negative observation from the
    // retired transport fences its replacement; old recovery cannot clear it.
    pub(super) fn revoke_transport_grant(&self) -> Self {
        self.cancel.cancel();
        Self { cancel: CancellationToken::new(), cached_denials: self.cached_denials.clone(),denial_changed:self.denial_changed.clone() }
    }
}
// Negative observations only: no credentials, cache freshness or access grant.
// An overflow remains closed until the actual owner/key epoch is replaced.
#[derive(Default)]
struct CachedChatDenials {
    revision: u64,
    scope: bool,
    overflow: bool,
    chats: std::collections::BTreeSet<String>,
}
const MAX_RETAINED_CACHED_CHAT_DENIALS: usize = 4096;
impl WatchAuthority {
    pub(super) fn deny_cached_chat(&self, id: Option<&str>) -> Result<()> {
        let mut state = self.cached_denials.write().map_err(|_| Error::Cancelled)?;
        let Some(revision) = state.revision.checked_add(1) else {
            self.cancel.cancel(); return Err(Error::Cancelled);
        };
        state.revision = revision;
        if let Some(id) = id {
            if state.chats.len() >= MAX_RETAINED_CACHED_CHAT_DENIALS && !state.chats.contains(id) {
                state.overflow = true;
            } else {
                state.chats.insert(id.to_owned());
            }
        } else { state.scope = true; }
        drop(state);self.denial_changed.notify_waiters();
        Ok(())
    }
    pub(super) async fn cached_denial_changed(&self,expected:u64){
        loop {
            let changed=self.denial_changed.notified();tokio::pin!(changed);changed.as_mut().enable();
            if self.cancel.is_cancelled()||self.cached_denial_revision().ok()!=Some(expected){return}
            tokio::select!{biased;_=self.cancel.cancelled()=>return,_=&mut changed=>{}}
        }
    }
    pub(super) fn cached_chat_allowed(&self, id: &str) -> bool {
        !self.cancel.is_cancelled() && self.cached_denials.read().is_ok_and(|state|
            !state.scope && !state.overflow && !state.chats.contains(id))
    }
    /// Negative-only lookup for a selected source whose wire identity may be a
    /// hash. Independent of cached chat presence and bounded by the retained
    /// denial ledger. Unknown/oversized denial identities fail closed.
    pub(super) fn cached_chat_hash_allowed(&self, source_hash: &str) -> bool {
        !self.cancel.is_cancelled() && self.cached_denials.read().is_ok_and(|state| {
            !state.scope && !state.overflow && state.chats.iter().all(|id| {
                if id.len() > 256 { return false; }
                if sha256(id) == source_hash { return false; }
                // Chat IDs have canonical UUID authority; accept no alias grant.
                // A differently-cased observed denial still restricts that UUID.
                !uuid::Uuid::parse_str(id).is_ok_and(|value| sha256(&value.to_string()) == source_hash)
            })
        })
    }
    /// Read-only observers may overlap; a pending/exclusive denial transition
    /// or poison still refuses without waiting during foreign allocation.
    pub(super) fn try_cached_denial_revision(&self) -> Result<u64> {
        Ok(self.cached_denials.try_read().map_err(|_| Error::Cancelled)?.revision)
    }
    pub(super) fn cached_denial_revision(&self) -> Result<u64> {
        Ok(self.cached_denials.read().map_err(|_| Error::Cancelled)?.revision)
    }
    // Only the sealed canonical commit path calls this after exact durable ACK.
    // Holding the same lock prevents erasing a newer independently seen denial.
    pub(super) fn commit_cached_chat_recovery(&self, id: &str, team: bool, revision: u64) -> Result<()> {
        let mut state = self.cached_denials.write().map_err(|_| Error::Cancelled)?;
        if self.cancel.is_cancelled() || state.revision != revision || state.overflow {
            return Err(Error::Cancelled);
        }
        state.chats.remove(id);
        if team { state.scope = false; }
        Ok(())
    }
}
/// Read-only negative fencing signal, retained across binding/watch transfer.
/// Validity never grants Project/source access, Task mutation or replay rights.
/// Source denial, socket failure and watch close cannot invalidate this owner.
#[derive(Clone)]
pub struct ProjectTaskOwnerAuthority {
    authority: Arc<WatchAuthority>,
    expires_at: Option<u64>,
}
impl ProjectTaskOwnerAuthority {
    pub fn is_valid(&self) -> bool {
        !self.authority.cancel.is_cancelled() && self.expires_at.is_none_or(|at| at > now_ms())
    }
}
/// Opaque authorization. No Debug/serde, caller-controlled owner or key getters.
pub struct ProjectTaskBinding {
    scope: TaskSyncScope,
    key: Key,
    authority: Arc<WatchAuthority>,
    expires_at: Option<u64>,
}
impl ProjectTaskBinding {
    pub fn scope(&self) -> &TaskSyncScope {
        &self.scope
    }
    /// Capture before transferring this binding into a watch. This observer
    /// carries no credentials and cannot authorize or extend a session.
    pub fn owner_authority(&self) -> ProjectTaskOwnerAuthority {
        ProjectTaskOwnerAuthority {
            authority: self.authority.clone(),
            expires_at: self.expires_at,
        }
    }
    /// Restore encrypted state once, outside the shared Client lane.
    pub fn new_sync(
        &self,
        checkpoint: Option<TaskSyncCheckpoint>,
        now_seconds: u64,
    ) -> Result<ProjectTaskSync> {
        if self.authority.cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if self.expires_at.is_some_and(|at| at <= now_ms()) {
            return Err(Error::Expired);
        }
        let mut sync = ProjectTaskSync::new(self.scope.clone(), self.key.clone());
        if let Some(checkpoint) = checkpoint {
            sync.restore(checkpoint, now_seconds)?;
        }
        if self.authority.cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok(sync)
    }
}
/// Prepared request contains credentials; deliberately not Debug/serde.
pub struct ProjectTaskWatchStart {
    socket: transport::TaskSocketRequest,
    binding: ProjectTaskBinding,
    sync: ProjectTaskSync,
    lifetime: CancellationToken,
}
pub struct ProjectTaskWatchReconnect {
    socket: transport::TaskSocketRequest,
    authority: Arc<WatchAuthority>,
    scope: TaskSyncScope,
}
pub struct ProjectTaskWatch {
    socket: Option<transport::Socket>,
    binding: ProjectTaskBinding,
    sync: ProjectTaskSync,
    lifetime: CancellationToken,
    connected_at: Instant,
    pending_at: Option<Instant>,
    pending_expiry: Option<u64>,
    sequence: u64,
    identity: Arc<()>,
}
pub enum ProjectTaskWatchPoll {
    Idle,
    Read(ProjectTaskWatchRead),
}
/// An opaque completion, bound to exactly one watch and one current authority.
/// It carries no plaintext getter before Client checks current identity.
pub struct ProjectTaskWatchRead {
    authority: Arc<WatchAuthority>,
    watch_lifetime: CancellationToken,
    sequence: u64,
    identity: Arc<()>,
    scope: Box<TaskSyncScope>,
    result: Result<Option<TaskSyncPublication>>,
    connection: TaskSyncConnection,
    valid_until: Instant,
    expires_at: Option<u64>,
}
/// Sealed view; crypto has already happened once outside Client. Every access
/// checks the owner epoch and pending candidate lease, including queued updates.
pub struct ProjectTaskPublication {
    authority: Arc<WatchAuthority>,
    lifetime: CancellationToken,
    publication: TaskSyncPublication,
    valid_until: Instant,
    expires_at: Option<u64>,
}
impl ProjectTaskPublication {
    pub fn snapshot(&self) -> Result<TaskSyncSnapshot<'_>> {
        self.check()?;
        self.publication.snapshot()
    }
    pub fn receipt(&self) -> Result<&TaskSyncCommit> {
        self.check()?;
        self.publication.snapshot()?;
        Ok(self.publication.receipt())
    }
    pub fn checkpoint(&self) -> Result<TaskSyncCheckpoint> {
        self.check()?;
        self.publication.checkpoint()
    }
    fn check(&self) -> Result<()> {
        if self.authority.cancel.is_cancelled()
            || self.lifetime.is_cancelled()
            || Instant::now() >= self.valid_until
            || self.expires_at.is_some_and(|at| at <= now_ms())
        {
            Err(Error::Cancelled)
        } else {
            Ok(())
        }
    }
}
impl Client {
    fn task_watch_owner(&self) -> Result<&str> {
        self.require_session()?;
        self.user["id"]
            .as_str()
            .filter(|s| !s.is_empty())
            .or_else(|| self.user["user_id"].as_str().filter(|s| !s.is_empty()))
            .ok_or(Error::Authentication)
    }
    pub(crate) fn bind_project_task_source(
        &self,
        workspace: TaskSyncWorkspace,
        project: &str,
        source: &str,
        key: Key,
    ) -> Result<ProjectTaskBinding> {
        Ok(ProjectTaskBinding {
            scope: TaskSyncScope::new(
                self.base.as_str(),
                self.task_watch_owner()?,
                workspace,
                project,
                source,
            )?,
            key,
            authority: self.task_watch_authority.clone(),
            expires_at: self.require_session()?.paired_session_expires_at,
        })
    }
    fn check_task_watch(&self, binding: &ProjectTaskBinding) -> Result<()> {
        if binding.authority.cancel.is_cancelled()
            || !Arc::ptr_eq(&self.task_watch_authority, &binding.authority)
        {
            return Err(Error::Cancelled);
        }
        if binding.scope.account_id() != self.task_watch_owner()?
            || binding.scope.api_url() != self.base.as_str().trim_end_matches('/')
        {
            return Err(Error::Forbidden);
        }
        Ok(())
    }
    /// O(1) authority/key binding check and request preparation. Call connect
    /// after releasing the application Client lane; no socket wait occurs here.
    pub fn prepare_project_task_watch(
        &self,
        binding: ProjectTaskBinding,
        sync: ProjectTaskSync,
        cancel: CancellationToken,
    ) -> Result<ProjectTaskWatchStart> {
        self.check_task_watch(&binding)?;
        if cancel.is_cancelled()
            || sync.snapshot().scope != &binding.scope
            || !sync.key_matches(&binding.key)
            || sync.snapshot().connection == TaskSyncConnection::Revoked
        {
            return Err(Error::Forbidden);
        }
        Ok(ProjectTaskWatchStart {
            socket: self.prepare_task_socket()?,
            binding,
            sync,
            lifetime: cancel.child_token(),
        })
    }
    /// Brief synchronous publication fence. No socket wait, crypto, JSON
    /// serialization, queue backpressure or durable cache I/O belongs here.
    pub fn finish_project_task_watch_read(
        &mut self,
        watch: &ProjectTaskWatch,
        read: ProjectTaskWatchRead,
    ) -> Result<Option<ProjectTaskPublication>> {
        self.check_task_watch(&watch.binding)?;
        if !Arc::ptr_eq(&read.authority, &watch.binding.authority)
            || *read.scope != watch.binding.scope
            || read.sequence != watch.sequence
            || !Arc::ptr_eq(&read.identity, &watch.identity)
            || read.watch_lifetime.is_cancelled()
            || watch.lifetime.is_cancelled()
        {
            return Err(Error::Cancelled);
        }
        match read.result {
            Err(Error::Expired) => {
                self.forget_session();
                Err(Error::Expired)
            }
            Err(error) => Err(error),
            Ok(Some(publication)) => Ok(Some(ProjectTaskPublication {
                authority: read.authority,
                lifetime: read.watch_lifetime,
                publication,
                valid_until: read.valid_until,
                expires_at: read.expires_at,
            })),
            Ok(None) if read.connection == TaskSyncConnection::Revoked => Err(Error::Forbidden),
            Ok(None) => Ok(None),
        }
    }
    /// Reauthorize through canonical typed scope/source lookup. No socket read
    /// or connect is performed while the application borrows the Client.
    pub async fn prepare_project_task_watch_reconnect(
        &mut self,
        watch: &mut ProjectTaskWatch,
    ) -> Result<ProjectTaskWatchReconnect> {
        self.check_task_watch(&watch.binding)?;
        if watch.lifetime.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // Reauthorization itself is a boundary: a caller may proactively ask
        // while holding a valid pending publication. Discard it before any
        // awaited permission/key lookup, including on denial/transient error.
        // Preserve the durable cursor and this watch's recoverable lifetime.
        watch.suspend();
        let filters = match watch.binding.scope.workspace() {
            TaskSyncWorkspace::Personal => crate::work::ProjectFilters {
                personal: true,
                ..Default::default()
            },
            TaskSyncWorkspace::Team(team) => crate::work::ProjectFilters {
                team_id: Some(team.clone()),
                ..Default::default()
            },
        };
        let binding = self
            .projects()
            .with_filters(filters)
            .task_source(
                watch.binding.scope.project_id(),
                watch.binding.scope.source_id(),
            )
            .await?;
        self.check_task_watch(&watch.binding)?;
        if binding.scope != watch.binding.scope || !watch.sync.key_matches(&binding.key) {
            return Err(Error::Forbidden);
        }
        Ok(ProjectTaskWatchReconnect {
            socket: self.prepare_task_socket()?,
            authority: binding.authority,
            scope: binding.scope,
        })
    }
}
impl ProjectTaskWatchStart {
    /// The single state owner is transferred, never cloned, into the watch.
    pub async fn connect(self) -> Result<ProjectTaskWatch> {
        let authority = self.binding.authority.cancel.clone();
        let cancel = self.lifetime.clone();
        let socket = tokio::select! { biased;
            _ = authority.cancelled() => return Err(Error::Cancelled),
            _ = cancel.cancelled() => return Err(Error::Cancelled),
            socket = transport::connect_task_socket(self.socket) => socket?,
        };
        let mut watch = ProjectTaskWatch {
            socket: Some(socket),
            binding: self.binding,
            sync: self.sync,
            lifetime: self.lifetime,
            connected_at: Instant::now(),
            pending_at: None,
            pending_expiry: None,
            sequence: 0,
            identity: Arc::new(()),
        };
        watch.subscribe().await?;
        Ok(watch)
    }
}
impl ProjectTaskWatch {
    /// False only for lost original account/context authority or its absolute
    /// paired-session deadline, never for a source-only error or local close.
    pub fn owner_authority_valid(&self) -> bool {
        !self.binding.authority.cancel.is_cancelled()
            && self.binding.expires_at.is_none_or(|at| at > now_ms())
    }
    pub fn scope(&self) -> &TaskSyncScope {
        &self.binding.scope
    }
    pub fn committed_cursor(&self) -> Option<&str> {
        self.sync.snapshot().cursor
    }
    pub fn connection(&self) -> TaskSyncConnection {
        self.sync.snapshot().connection
    }
    fn check(&self) -> Result<()> {
        if self.binding.authority.cancel.is_cancelled() || self.lifetime.is_cancelled() {
            Err(Error::Cancelled)
        } else if self.binding.expires_at.is_some_and(|at| at <= now_ms()) {
            Err(Error::Expired)
        } else {
            Ok(())
        }
    }
    async fn subscribe(&mut self) -> Result<()> {
        self.check()?;
        let mut payload = json!({"bindings":[{"project_id":self.binding.scope.project_id(),
            "source_id":self.binding.scope.source_id(),"cursor":self.sync.snapshot().cursor}]});
        if let TaskSyncWorkspace::Team(team) = self.binding.scope.workspace() {
            payload["team_id"] = json!(team);
        }
        let socket = self.socket.as_mut().ok_or(Error::Offline)?;
        crate::platform::time::timeout(
            Duration::from_secs(5),
            transport::send(socket, "project_task_sync_subscribe", payload),
        )
        .await
        .map_err(|_| Error::Offline)??;
        self.check()
    }
    /// Read/decrypt outside Client. Poll at most one bounded interval, including
    /// while awaiting commit: callers must keep polling control frames.
    /// Another data batch while staged fails closed instead of growing a queue.
    pub async fn poll(
        &mut self,
        cancel: &CancellationToken,
        now_seconds: u64,
    ) -> Result<ProjectTaskWatchPoll> {
        self.check()?;
        if cancel.is_cancelled() {
            self.close();
            return Err(Error::Cancelled);
        }
        if self.connected_at.elapsed() >= REAUTHORIZE_AFTER
            || self
                .pending_at
                .is_some_and(|at| at.elapsed() >= PUBLICATION_DEADLINE)
        {
            self.disconnect();
            return Err(Error::Offline);
        }
        let socket = self.socket.as_mut().ok_or(Error::Offline)?;
        let read = tokio::select! { biased;
            _ = self.binding.authority.cancel.cancelled() => Err(Error::Cancelled),
            _ = self.lifetime.cancelled() => Err(Error::Cancelled),
            _ = cancel.cancelled() => Err(Error::Cancelled),
            result = crate::platform::time::timeout(READ_SLICE, transport::receive(socket)) => match result {
                Err(_) => return Ok(ProjectTaskWatchPoll::Idle), Ok(result) => result },
        };
        self.sequence = self.sequence.wrapping_add(1);
        let result = match read {
            Ok((kind, payload))
                if matches!(
                    kind.as_str(),
                    "project_task_sync" | "project_task_sync_error"
                ) =>
            {
                serde_json::to_vec(&json!({"type":kind,"payload":payload}))
                    .map_err(Error::from)
                    .and_then(|bytes| TaskSyncEvent::parse(&bytes))
                    .and_then(|event| self.sync.stage(&self.binding.scope, event, now_seconds))
            }
            // Initial server capabilities and unrelated notifications carry no
            // Task authority. They are never buffered or exposed as data.
            Ok(_) => return Ok(ProjectTaskWatchPoll::Idle),
            Err(error) => Err(error),
        };
        if result.is_err() || self.sync.snapshot().connection == TaskSyncConnection::Revoked {
            if matches!(result, Err(Error::Cancelled)) {
                self.lifetime.cancel();
            }
            self.disconnect();
        } else if let Ok(Some(publication)) = &result {
            self.pending_at = Some(Instant::now());
            self.pending_expiry = publication
                .expires_at()
                .map(|seconds| seconds.saturating_mul(1000));
        }
        let read = ProjectTaskWatchRead {
            authority: self.binding.authority.clone(),
            watch_lifetime: self.lifetime.clone(),
            sequence: self.sequence,
            identity: self.identity.clone(),
            scope: Box::new(self.binding.scope.clone()),
            result,
            connection: self.sync.snapshot().connection,
            valid_until: self.pending_at.unwrap_or_else(Instant::now) + PUBLICATION_DEADLINE,
            expires_at: [self.binding.expires_at, self.pending_expiry]
                .into_iter()
                .flatten()
                .min(),
        };
        Ok(ProjectTaskWatchPoll::Read(read))
    }
    /// Advance only after exact final batch/cursor has been durably published.
    pub fn commit(&mut self, receipt: &TaskSyncCommit) -> Result<()> {
        self.check()?;
        if self
            .pending_at
            .is_none_or(|at| at.elapsed() >= PUBLICATION_DEADLINE)
            || self.pending_expiry.is_some_and(|at| at <= now_ms())
        {
            self.disconnect();
            return Err(Error::Conflict);
        }
        self.sync.commit(receipt)?;
        self.pending_at = None;
        self.pending_expiry = None;
        Ok(())
    }
    pub async fn reconnect(
        &mut self,
        prepared: ProjectTaskWatchReconnect,
        cancel: &CancellationToken,
    ) -> Result<()> {
        self.check()?;
        if prepared.scope != self.binding.scope
            || !Arc::ptr_eq(&prepared.authority, &self.binding.authority)
        {
            return Err(Error::Forbidden);
        }
        self.disconnect();
        self.socket = Some(tokio::select! { biased;
            _ = self.binding.authority.cancel.cancelled() => return Err(Error::Cancelled),
            _ = self.lifetime.cancelled() => return Err(Error::Cancelled),
            _ = cancel.cancelled() => return Err(Error::Cancelled),
            socket = transport::connect_task_socket(prepared.socket) => socket?,
        });
        self.connected_at = Instant::now();
        self.subscribe().await
    }
    fn disconnect(&mut self) {
        self.socket = None;
        self.pending_at = None;
        self.pending_expiry = None;
        self.sync.reconnecting();
    }
    /// Recoverable admission/backpressure pause. Drop any outstanding Read,
    /// fence application cache readiness, then reauthorize and reconnect when
    /// the Client lane is available. Never turn lock contention into logout or
    /// reuse the abandoned candidate. The last durable cursor is preserved.
    pub fn suspend(&mut self) {
        self.sequence = self.sequence.wrapping_add(1);
        self.disconnect();
    }
    /// Synchronous close invalidates queued plaintext views immediately. It
    /// cancels only this watch's child, never the caller's token or other work.
    pub fn close(&mut self) {
        self.lifetime.cancel();
        self.disconnect();
    }
}
impl Drop for ProjectTaskWatch {
    fn drop(&mut self) {
        self.close();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn client() -> Client {
        let mut client = Client::new(
            "https://example.invalid",
            Some(Session {
                api_url: "https://example.invalid".into(),
                session_id: "synthetic-session".into(),
                cookies: BTreeMap::from([("auth_refresh_token".into(), "synthetic-only".into())]),
                ws_token: Some("synthetic-ws".into()),
                master_key: zeroize::Zeroizing::new([3; 32]),
                hashed_email: "synthetic-hash".into(),
                user_email_salt: "".into(),
                email_encryption_key: None,
                created_at: now_ms(),
                paired_session_expires_at: None,
                active_team_id: None,
            }),
        )
        .unwrap();
        client.user = json!({"id":"user"});
        client.credentials_changed();
        client
    }
    fn watch(client: &Client) -> ProjectTaskWatch {
        let binding = client
            .bind_project_task_source(
                TaskSyncWorkspace::Personal,
                "project",
                "source",
                zeroize::Zeroizing::new([3; 32]),
            )
            .unwrap();
        let sync = binding.new_sync(None, 1000).unwrap();
        ProjectTaskWatch {
            socket: None,
            binding,
            sync,
            lifetime: CancellationToken::new(),
            connected_at: Instant::now(),
            pending_at: None,
            pending_expiry: None,
            sequence: 0,
            identity: Arc::new(()),
        }
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn cookie_rotation_preserves_watch_but_reset_team_logout_invalidate_authority() {
        let mut client = client();
        let first = watch(&client);
        client
            .cookies
            .insert("auth_refresh_token".into(), "rotated-synthetic".into());
        client.credentials_changed();
        assert!(first.check().is_ok());
        client.set_team(None).unwrap();
        assert!(matches!(first.check(), Err(Error::Cancelled)));
        let second = watch(&client);
        client.forget_session();
        assert!(matches!(second.check(), Err(Error::Cancelled)));
        assert!(second.sync.snapshot().tasks.is_empty());
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn late_old_force_logout_never_clears_a_newer_identity() {
        let mut client = client();
        let old = watch(&client);
        let read = ProjectTaskWatchRead {
            authority: old.binding.authority.clone(),
            watch_lifetime: old.lifetime.clone(),
            sequence: 0,
            identity: old.identity.clone(),
            scope: Box::new(old.scope().clone()),
            result: Err(Error::Expired),
            connection: TaskSyncConnection::Reconnecting,
            valid_until: Instant::now() + PUBLICATION_DEADLINE,
            expires_at: None,
        };
        client.invalidate_task_watches();
        assert!(matches!(
            client.finish_project_task_watch_read(&old, read),
            Err(Error::Cancelled)
        ));
        assert!(client.require_session().is_ok());
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn receipt_cannot_cross_even_identically_scoped_watches() {
        let mut client = client();
        let one = watch(&client);
        let two = watch(&client);
        let read = ProjectTaskWatchRead {
            authority: one.binding.authority.clone(),
            watch_lifetime: one.lifetime.clone(),
            sequence: 0,
            identity: one.identity.clone(),
            scope: Box::new(one.scope().clone()),
            result: Ok(None),
            connection: TaskSyncConnection::Reconnecting,
            valid_until: Instant::now() + PUBLICATION_DEADLINE,
            expires_at: None,
        };
        assert!(matches!(
            client.finish_project_task_watch_read(&two, read),
            Err(Error::Cancelled)
        ));
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn closing_watch_never_cancels_caller_or_other_watch() {
        let client = client();
        let parent = CancellationToken::new();
        let mut one = watch(&client);
        one.lifetime = parent.child_token();
        let two = watch(&client);
        one.close();
        assert!(!parent.is_cancelled());
        assert!(two.check().is_ok());
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn owner_observer_survives_source_revoke_suspend_close_but_not_original_client_loss() {
        let mut owner = client();
        let mut source = watch(&owner);
        let observer = source.binding.owner_authority();
        source
            .sync
            .stage(
                &source.binding.scope,
                TaskSyncEvent::AccessRevoked {
                    project_id: Some("project".into()),
                },
                1000,
            )
            .unwrap();
        assert!(source.owner_authority_valid());
        assert!(observer.is_valid());
        source.suspend();
        source.close();
        assert!(source.owner_authority_valid());
        assert!(observer.is_valid());
        owner.forget_session();
        assert!(!source.owner_authority_valid());
        assert!(!observer.is_valid());
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn owner_observer_rejects_same_owner_reset_team_switch_and_client_drop() {
        for action in 0..3 {
            let mut owner = client();
            let source = watch(&owner);
            let observer = source.binding.owner_authority();
            match action {
                0 => {
                    let session = owner.session().cloned();
                    owner.reset("https://example.invalid", session).unwrap();
                }
                1 => owner.set_team(None).unwrap(),
                _ => drop(owner),
            }
            assert!(!source.owner_authority_valid());
            assert!(!observer.is_valid());
        }
    }
    // contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
    #[test]
    fn bound_owner_expiry_uses_current_clock_and_never_extends_with_cookie_rotation() {
        let mut owner = client();
        let mut source = watch(&owner);
        source.binding.expires_at = Some(now_ms() - 1);
        let observer = source.binding.owner_authority();
        owner.session.as_mut().unwrap().paired_session_expires_at = Some(now_ms() + 60_000);
        owner
            .cookies
            .insert("auth_refresh_token".into(), "new-synthetic-cookie".into());
        owner.credentials_changed();
        assert!(owner.require_session().is_ok());
        assert!(!source.owner_authority_valid());
        assert!(!observer.is_valid());
    }
}

#[cfg(test)]
#[path = "project_task_watch_protocol_tests.rs"]
mod protocol_tests;

#[cfg(all(test,not(target_arch="wasm32")))]
mod original_denial_wake_tests {
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.authoritative-enforcement
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
    #[test]
    fn retained_denial_revision_shares_reads_but_refuses_exclusive_transition() {
        let authority = WatchAuthority::new();
        let expected = authority.cached_denial_revision().expect("actual ledger");
        let read = authority.cached_denials.read().expect("read-only observation");
        std::thread::scope(|threads| {
            let checked = threads.spawn(|| authority.try_cached_denial_revision());
            assert!(checked.join().expect("observer joined").is_ok_and(|value| value == expected));
        });
        drop(read);
        let refused = std::thread::scope(|threads| {
            let write = authority.cached_denials.write().expect("exclusive transition");
            let (send, receive) = std::sync::mpsc::channel();
            let original = &authority;
            threads.spawn(move || { let _ = send.send(original.try_cached_denial_revision()); });
            let observed = receive.recv_timeout(Duration::from_secs(1));
            drop(write);
            observed
        });
        assert!(matches!(refused, Ok(Err(Error::Cancelled))));
        assert_eq!(authority.try_cached_denial_revision().expect("same original"), expected);
        authority.deny_cached_chat(None).expect("actual authoritative denial");
        assert_ne!(authority.try_cached_denial_revision().expect("denied revision"), expected);
        assert!(!authority.cached_chat_allowed("original-A"));
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
    #[test]
    fn poisoned_denial_transition_never_returns_a_trusted_revision() {
        let authority = WatchAuthority::new();
        std::thread::scope(|threads| {
            let state = &authority.cached_denials;
            assert!(threads.spawn(move || {
                let _write = state.write().expect("exclusive transition");
                panic!("intentional denial ledger poison");
            }).join().is_err());
        });
        assert!(matches!(authority.try_cached_denial_revision(), Err(Error::Cancelled)));
        assert!(!authority.cached_chat_allowed("original-A"));
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
    #[tokio::test]
    async fn actual_denial_revision_wakes_registered_original_wait_without_new_grant(){
        let authority=WatchAuthority::new();let revision=authority.cached_denial_revision().expect("actual ledger");
        let waiting=authority.cached_denial_changed(revision);tokio::pin!(waiting);
        assert!(futures_util::poll!(waiting.as_mut()).is_pending());
        authority.deny_cached_chat(Some("original-A")).expect("actual denial");
        tokio::time::timeout(Duration::from_secs(1),waiting).await.expect("notification watchdog only");
        assert_ne!(authority.cached_denial_revision().expect("ledger"),revision);
        assert!(!authority.cached_chat_allowed("original-A"));
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
    #[tokio::test]
    async fn retired_transport_denial_wakes_same_original_ledger_in_replacement(){
        let old=WatchAuthority::new();let replacement=old.revoke_transport_grant();
        let revision=replacement.cached_denial_revision().expect("retained ledger");
        let waiting=replacement.cached_denial_changed(revision);tokio::pin!(waiting);
        assert!(futures_util::poll!(waiting.as_mut()).is_pending());
        old.deny_cached_chat(Some("original-A")).expect("late authoritative negative");
        tokio::time::timeout(Duration::from_secs(1),waiting).await.expect("notification watchdog only");
        assert!(!replacement.cancel.is_cancelled());
        assert!(!replacement.cached_chat_allowed("original-A"));
    }
}
