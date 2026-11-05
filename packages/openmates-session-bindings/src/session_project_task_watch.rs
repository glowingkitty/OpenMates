//! PRIVATE DRAFT: not integrated, compiled, tested or releasable.
//! One actor owns each core Watch. No plaintext queue, CLI or profile discovery.
use super::*;
use openmates_sdk::{
    client::{ProjectTaskPublication, ProjectTaskWatch, ProjectTaskWatchPoll},
    project_task_sync::{TaskSyncCheckpoint, TaskSyncCommit},
    work::ProjectFilters,
};
use std::sync::Weak;
use tokio::sync::{Notify, oneshot, watch};
use tokio::time::{Duration, timeout};
use zeroize::Zeroize;
const CAP: usize = 16;
const FINISH_LANE: Duration = Duration::from_millis(25);
const RETRY: Duration = Duration::from_millis(250);
const INPUT_LIMIT: usize = 16 * 1024 * 1024;
const OUTPUT_LIMIT: usize = 64 * 1024 * 1024;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    source_id: String,
    checkpoint: Option<TaskSyncCheckpoint>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Filters {
    personal: Option<bool>,
    team_id: Option<String>,
}
#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
enum Phase {
    Starting,
    Reconnecting,
    Connected,
    Revoked,
    Expired,
    Closed,
    Failed,
}
#[derive(Clone, Serialize)]
struct Status {
    kind: &'static str,
    state: Phase,
    cursor: Option<String>,
}
impl Status {
    fn terminal(&self) -> bool {
        matches!(
            self.state,
            Phase::Revoked | Phase::Expired | Phase::Closed | Phase::Failed
        )
    }
}
struct Control {
    status: Status,
    tx: watch::Sender<Status>,
}
struct Commit {
    receipt: TaskSyncCommit,
    ack: oneshot::Sender<Result<()>>,
}
struct Sealed {
    publication: ProjectTaskPublication,
    epoch: u64,
}
#[cfg(test)]
#[derive(Default)]
struct SerializeBarrier {
    started: Notify,
    resume: (Mutex<bool>, std::sync::Condvar),
}
#[cfg(test)]
#[derive(Default)]
struct ReturnBarrier {
    completed: Notify,
    resume: Notify,
}
struct Handle {
    epoch: u64,
    cancel: CancellationToken,
    suspend: Notify,
    control: Mutex<Control>,
    status: AsyncMutex<watch::Receiver<Status>>,
    publications: AsyncMutex<mpsc::Receiver<Sealed>>,
    commits: mpsc::Sender<Commit>,
    #[cfg(test)]
    return_barrier: Mutex<Option<Arc<ReturnBarrier>>>,
    #[cfg(test)]
    status_barrier: Mutex<Option<Arc<ReturnBarrier>>>,
    #[cfg(test)]
    serialize_barrier: Mutex<Option<Arc<SerializeBarrier>>>,
    #[cfg(test)]
    hold_commits: AtomicBool,
    #[cfg(test)]
    commits_paused: Notify,
    #[cfg(test)]
    last_error: Mutex<Option<&'static str>>,
}
impl Handle {
    fn transition(&self, state: Phase, cursor: Option<String>) {
        if let Ok(mut control) = self.control.lock() {
            if control.status.terminal() {
                return;
            }
            let status = Status {
                kind: "state",
                state,
                cursor,
            };
            control.status = status.clone();
            control.tx.send_replace(status);
        } else {
            self.cancel.cancel();
        }
    }
    fn stop(&self, state: Phase) {
        self.transition(state, None);
        self.cancel.cancel();
    }
    fn terminal(&self) -> bool {
        self.control
            .lock()
            .map(|c| c.status.terminal())
            .unwrap_or(true)
    }
}
#[derive(Default)]
pub(super) struct Registry(Mutex<BTreeMap<String, Arc<Handle>>>);
impl Registry {
    pub(super) fn close_all(&self) {
        if let Ok(entries) = self.0.lock() {
            for handle in entries.values() {
                handle.stop(Phase::Closed);
            }
        }
    }
    fn get(&self, id: &str) -> Result<Arc<Handle>> {
        self.0
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .get(id)
            .cloned()
            .ok_or_else(|| Error::Cancelled.into())
    }
}
impl Drop for Registry {
    fn drop(&mut self) {
        self.close_all();
    }
}
fn now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}
fn decode<T: serde::de::DeserializeOwned>(encoded: String) -> Result<T> {
    let encoded = Zeroizing::new(encoded);
    if encoded.len() > INPUT_LIMIT {
        return Err(Error::Invalid("Project Task watch input exceeds its limit.").into());
    }
    serde_json::from_str(&encoded)
        .map_err(|_| Error::Invalid("Invalid typed Project Task watch input.").into())
}
fn same_epoch(state: &State, epoch: u64, cancel: &CancellationToken) -> Result<()> {
    if state.closed.load(Ordering::Acquire)
        || state.identity_epoch.load(Ordering::Acquire) != epoch
        || cancel.is_cancelled()
    {
        Err(Error::Cancelled.into())
    } else {
        Ok(())
    }
}

// The registered original watch owns cancellation even before its actor polls.
struct QueuedWatchDelivery {
    state: Weak<State>, id: String, handle: Arc<Handle>, delivered: bool,
}
impl Drop for QueuedWatchDelivery {
    fn drop(&mut self) {
        if self.delivered { return; }
        self.handle.stop(Phase::Closed);
        if let Some(state) = self.state.upgrade() {
            if let Ok(mut entries) = state.project_task_watches.0.lock() {
                if entries.get(&self.id).is_some_and(|value| Arc::ptr_eq(value, &self.handle)) {
                    entries.remove(&self.id);
                }
            }
        }
    }
}
struct QueuedWatchStart {
    state: Arc<State>, delivery: QueuedWatchDelivery,
    project: Zeroizing<String>, input_json: Zeroizing<String>, filters_json: Zeroizing<String>,
    publication_tx: mpsc::Sender<Sealed>, commit_rx: mpsc::Receiver<Commit>,
}
impl QueuedWatchStart {
    async fn run(self) -> Result<String> {
        let Self {state, mut delivery, mut project, mut input_json, mut filters_json, publication_tx, commit_rx} = self;
        same_epoch(&state, delivery.handle.epoch, &delivery.handle.cancel)?;
        let project = std::mem::take(&mut *project);
        if project.is_empty() || project.len() > 256 || project.chars().any(char::is_control) {
            return Err(Error::Invalid("Supply an exact Project selector.").into());
        }
        let input: Input = decode(std::mem::take(&mut *input_json))?;
        let filters: Filters = decode(std::mem::take(&mut *filters_json))?;
        work::scope(filters.personal == Some(true), filters.team_id.as_deref())?;
        if input.source_id.is_empty()
            || input.source_id.len() > 128
            || input.source_id.chars().any(char::is_control)
        {
            return Err(Error::Invalid("Supply an exact Project source ID.").into());
        }
        let filters = ProjectFilters {
            personal: filters.personal == Some(true),
            team_id: filters.team_id,
            ..Default::default()
        };
        same_epoch(&state, delivery.handle.epoch, &delivery.handle.cancel)?;
        tokio::spawn(actor(Arc::downgrade(&state), delivery.handle.clone(), project, input, filters, publication_tx, commit_rx));
        same_epoch(&state, delivery.handle.epoch, &delivery.handle.cancel)?;
        let output = serde_json::to_string(&json!({"id":delivery.id})).map_err(|_| BindingError::from(Error::Protocol))?;
        delivery.delivered = true;
        Ok(output)
    }
}
impl SessionBridge {
    /// Returns an owned watch immediately; setup failures become terminal states.
    pub async fn project_task_watch_open(
        &self,
        project: String,
        input_json: String,
        filters_json: String,
    ) -> Result<String> {
        self.capture_project_task_watch_open(project, input_json, filters_json).await
    }
    fn prepare_project_task_watch_open(&self, project:String, input_json:String, filters_json:String) -> Result<QueuedWatchStart> {
        let project = Zeroizing::new(project);
        let input_json = Zeroizing::new(input_json);
        let filters_json = Zeroizing::new(filters_json);
        // Auth successor serializes this original admission with pending identity
        // transitions. Never keep its non-Send mutex guard across a future/await.
        let identity = self.identity_admission()?;
        let status = Status {
            kind: "state",
            state: Phase::Starting,
            cursor: None,
        };
        let (tx, rx) = watch::channel(status.clone());
        let (publication_tx, publication_rx) = mpsc::channel(1);
        let (commit_tx, commit_rx) = mpsc::channel(4);
        let epoch = self.state.identity_epoch.load(Ordering::Acquire);
        let handle = Arc::new(Handle {
            epoch,
            cancel: CancellationToken::new(),
            suspend: Notify::new(),
            control: Mutex::new(Control { status, tx }),
            status: AsyncMutex::new(rx),
            publications: AsyncMutex::new(publication_rx),
            commits: commit_tx,
            #[cfg(test)]
            return_barrier: Mutex::new(None),
            #[cfg(test)]
            status_barrier: Mutex::new(None),
            #[cfg(test)]
            serialize_barrier: Mutex::new(None),
            #[cfg(test)]
            hold_commits: AtomicBool::new(false),
            #[cfg(test)]
            commits_paused: Notify::new(),
            #[cfg(test)]
            last_error: Mutex::new(None),
        });
        let id = uuid::Uuid::new_v4().to_string();
        {
            let mut entries = self
                .state
                .project_task_watches
                .0
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            entries.retain(|_, entry| !entry.terminal());
            if entries.len() >= CAP {
                return Err(Error::Conflict.into());
            }
            entries.insert(id.clone(), handle.clone());
        }
        let delivery = QueuedWatchDelivery {state:Arc::downgrade(&self.state),id,handle,delivered:false};
        same_epoch(&self.state, epoch, &delivery.handle.cancel)?;
        drop(identity);
        Ok(QueuedWatchStart {state:self.state.clone(),delivery,project,input_json,filters_json,publication_tx,commit_rx})
    }
    pub(crate) fn capture_project_task_watch_open(&self, project:String, input_json:String, filters_json:String) -> impl Future<Output=Result<String>> + Send + 'static {
        let prepared = self.prepare_project_task_watch_open(project,input_json,filters_json);
        async move {prepared?.run().await}
    }

    pub fn project_task_watch_close(&self, id: String) -> Result<()> {
        let handle = self
            .state
            .project_task_watches
            .0
            .lock()
            .map_err(|_| BindingError::from(Error::Protocol))?
            .remove(&id);
        if let Some(handle) = handle {
            handle.stop(Phase::Closed);
        }
        Ok(())
    }
    pub async fn project_task_watch_commit(&self, id: String, receipt_json: String) -> Result<()> {
        let handle = self.state.project_task_watches.get(&id)?;
        let receipt: TaskSyncCommit = decode(receipt_json)?;
        let (ack, wait) = oneshot::channel();
        tokio::select! {biased;
            _=handle.cancel.cancelled()=>return Err(Error::Cancelled.into()),
            result=handle.commits.send(Commit{receipt,ack})=>result.map_err(|_|BindingError::from(Error::Cancelled))?,
        }
        tokio::select! {biased;
            _=handle.cancel.cancelled()=>Err(Error::Cancelled.into()),
            result=wait=>result.map_err(|_|BindingError::from(Error::Cancelled))?,
        }
    }
    pub async fn project_task_watch_next(&self, id: String) -> Result<String> {
        let handle = self.state.project_task_watches.get(&id)?;
        // No Client lane is held while waiting, serializing or calling consumers.
        let mut status = handle.status.lock().await;
        let mut publications = handle.publications.lock().await;
        if status.has_changed().unwrap_or(false) || status.borrow().terminal() {
            let _ = status.borrow_and_update();
            return encode_status(&self.state, &handle);
        }
        tokio::select! {biased;
            _=handle.cancel.cancelled()=>{
                let _=status.borrow_and_update();
                encode_status(&self.state,&handle)
            },
            changed=status.changed()=>{
                changed.map_err(|_|BindingError::from(Error::Cancelled))?;
                // changed() marks this version seen. Return it here instead
                // of looping past a live nonterminal transition.
                let _=status.borrow_and_update();
                #[cfg(test)]
                {
                    let barrier={handle.status_barrier.lock().map_err(|_|BindingError::from(Error::Protocol))?.take()};
                    if let Some(barrier)=barrier{barrier.completed.notify_one();barrier.resume.notified().await;}
                }
                encode_status(&self.state,&handle)
            },
            publication=publications.recv()=>{
                let sealed=publication.ok_or_else(||BindingError::from(Error::Cancelled))?;
                let state=Arc::downgrade(&self.state);
                let owner=handle.clone();
                let result=tokio::task::spawn_blocking(move||serialize_publication(sealed,&state,&owner)).await.map_err(|_|BindingError::from(Error::Protocol))?;
                #[cfg(test)]
                if result.is_ok(){
                    // Private deterministic actor-fixture seam; never a
                    // public API, environment option or production hook.
                    let barrier={handle.return_barrier.lock().map_err(|_|BindingError::from(Error::Protocol))?.take()};
                    if let Some(barrier)=barrier{barrier.completed.notify_one();barrier.resume.notified().await;}
                }
                // Worker completion is not the foreign return boundary:
                // a terminal transition may occur while this task is queued.
                let result=result.and_then(|mut serialized|release_encoded(&mut serialized.encoded,||{
                    serialized.sealed.publication.snapshot().map_err(BindingError::from)?;
                    same_epoch(&self.state,serialized.sealed.epoch,&handle.cancel)
                }));
                if result.is_err(){handle.suspend.notify_one();}
                result
            }
        }
    }
}

// Status is not plaintext, but an old watch must never report an expired
// identity over a newer session. Read the authoritative sticky terminal state
// after the receiver wake; no watch borrow or Client guard crosses an await.
fn encode_status(state: &State, handle: &Handle) -> Result<String> {
    let control = handle
        .control
        .lock()
        .map_err(|_| BindingError::from(Error::Protocol))?;
    let value = control.status.clone();
    let encoded = serde_json::to_string(&value).map_err(|_| BindingError::from(Error::Protocol))?;
    if state.identity_epoch.load(Ordering::Acquire) != handle.epoch
        || state.closed.load(Ordering::Acquire)
        || (handle.cancel.is_cancelled() && !value.terminal())
    {
        return Err(Error::Cancelled.into());
    }
    Ok(encoded)
}

// JSON output is bounded before each writer append and wiped on invalidation.
struct Output(Vec<u8>);
impl Drop for Output {
    fn drop(&mut self) {
        self.0.zeroize();
    }
}
impl std::io::Write for Output {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > OUTPUT_LIMIT.saturating_sub(self.0.len()) {
            return Err(std::io::Error::other("Watch output exceeds its limit."));
        }
        self.0.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
struct SerializedPublication {
    sealed: Sealed,
    encoded: Zeroizing<String>,
}
fn release_encoded(encoded: &mut String, check: impl FnOnce() -> Result<()>) -> Result<String> {
    if let Err(error) = check() {
        encoded.zeroize();
        return Err(error);
    }
    Ok(std::mem::take(encoded))
}
fn serialize_publication(
    sealed: Sealed,
    state: &Weak<State>,
    handle: &Handle,
) -> Result<SerializedPublication> {
    let state = state
        .upgrade()
        .ok_or_else(|| BindingError::from(Error::Cancelled))?;
    same_epoch(&state, sealed.epoch, &handle.cancel)?;
    let snapshot = sealed.publication.snapshot().map_err(BindingError::from)?;
    let receipt = sealed.publication.receipt().map_err(BindingError::from)?;
    let checkpoint = sealed
        .publication
        .checkpoint()
        .map_err(BindingError::from)?;
    #[derive(Serialize)]
    struct Task<'a> {
        task_id: &'a str,
        task: &'a Value,
    }
    #[derive(Serialize)]
    struct Event<'a> {
        kind: &'static str,
        scope: &'a openmates_sdk::project_task_sync::TaskSyncScope,
        cursor: Option<&'a str>,
        tasks: Vec<Task<'a>>,
        receipt: &'a TaskSyncCommit,
        checkpoint: &'a TaskSyncCheckpoint,
    }
    let event = Event {
        kind: "snapshot",
        scope: snapshot.scope,
        cursor: snapshot.cursor,
        tasks: snapshot
            .tasks
            .iter()
            .map(|(id, task)| Task {
                task_id: id,
                task: task.decrypted(),
            })
            .collect(),
        receipt,
        checkpoint: &checkpoint,
    };
    #[cfg(test)]
    {
        let barrier = {
            handle
                .serialize_barrier
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?
                .take()
        };
        if let Some(barrier) = barrier {
            barrier.started.notify_one();
            let mut resumed = barrier
                .resume
                .0
                .lock()
                .map_err(|_| BindingError::from(Error::Protocol))?;
            while !*resumed {
                resumed = barrier
                    .resume
                    .1
                    .wait(resumed)
                    .map_err(|_| BindingError::from(Error::Protocol))?;
            }
        }
    }
    let mut output = Output(Vec::new());
    serde_json::to_writer(&mut output, &event).map_err(|_| BindingError::from(Error::Protocol))?;
    // A queued view can be revoked during serde. Never return its plaintext.
    sealed.publication.snapshot().map_err(BindingError::from)?;
    same_epoch(&state, sealed.epoch, &handle.cancel)?;
    let encoded = String::from_utf8(std::mem::take(&mut output.0))
        .map_err(|_| BindingError::from(Error::Protocol))?;
    drop(event);
    drop(checkpoint);
    Ok(SerializedPublication {
        sealed,
        encoded: Zeroizing::new(encoded),
    })
}

async fn initial_watch(
    state: &Weak<State>,
    epoch: u64,
    handle: &Handle,
    project: &str,
    input: Input,
    filters: ProjectFilters,
) -> Result<ProjectTaskWatch> {
    let binding = {
        let state = state
            .upgrade()
            .ok_or_else(|| BindingError::from(Error::Cancelled))?;
        let mut client = tokio::select! {biased;_=handle.cancel.cancelled()=>return Err(Error::Cancelled.into()),guard=state.client.lock()=>guard};
        same_epoch(&state, epoch, &handle.cancel)?;
        client.set_operation_cancel(handle.cancel.clone());
        let result = client
            .projects()
            .with_filters(filters)
            .task_source(project, &input.source_id)
            .await;
        client.set_operation_cancel(CancellationToken::new());
        result.map_err(BindingError::from)?
    };
    let (binding, sync) = tokio::task::spawn_blocking(move || {
        let sync = binding.new_sync(input.checkpoint, now());
        (binding, sync)
    })
    .await
    .map_err(|_| BindingError::from(Error::Protocol))?;
    let sync = sync.map_err(BindingError::from)?;
    let start = {
        let state = state
            .upgrade()
            .ok_or_else(|| BindingError::from(Error::Cancelled))?;
        let client = tokio::select! {biased;_=handle.cancel.cancelled()=>return Err(Error::Cancelled.into()),guard=state.client.lock()=>guard};
        same_epoch(&state, epoch, &handle.cancel)?;
        client
            .prepare_project_task_watch(binding, sync, handle.cancel.clone())
            .map_err(BindingError::from)?
    };
    start.connect().await.map_err(BindingError::from)
}
async fn reconnect(
    state: &Weak<State>,
    epoch: u64,
    handle: &Handle,
    watch: &mut ProjectTaskWatch,
) -> Result<()> {
    let prepared = {
        let state = state
            .upgrade()
            .ok_or_else(|| BindingError::from(Error::Cancelled))?;
        let mut client = tokio::select! {biased;_=handle.cancel.cancelled()=>return Err(Error::Cancelled.into()),guard=state.client.lock()=>guard};
        same_epoch(&state, epoch, &handle.cancel)?;
        client.set_operation_cancel(handle.cancel.clone());
        let result = client.prepare_project_task_watch_reconnect(watch).await;
        client.set_operation_cancel(CancellationToken::new());
        result.map_err(BindingError::from)?
    };
    watch
        .reconnect(prepared, &handle.cancel)
        .await
        .map_err(BindingError::from)
}
fn terminal_error(handle: &Handle, error: &BindingError) -> bool {
    #[cfg(test)]
    if let Ok(mut observed) = handle.last_error.lock() {
        *observed = Some(error.code);
    }
    match error.code {
        "forbidden" => {
            handle.stop(Phase::Revoked);
            true
        }
        "expired" | "authentication" => {
            handle.stop(Phase::Expired);
            true
        }
        "cancelled" => {
            handle.stop(Phase::Closed);
            true
        }
        "offline" | "conflict" => false,
        _ => {
            handle.stop(Phase::Failed);
            true
        }
    }
}
const SOCKET_BURST: usize = 8;
enum ActorStep {
    Cancel,
    Suspend,
    Commit(Option<Commit>),
    Poll(std::result::Result<ProjectTaskWatchPoll, Error>),
}
async fn select_step<F>(
    prefer_commit: bool,
    cancel: &CancellationToken,
    suspend: &Notify,
    commits: &mut mpsc::Receiver<Commit>,
    poll: F,
) -> ActorStep
where
    F: Future<Output = std::result::Result<ProjectTaskWatchPoll, Error>>,
{
    if prefer_commit {
        tokio::select! {biased;
            _=cancel.cancelled()=>ActorStep::Cancel,
            _=suspend.notified()=>ActorStep::Suspend,
            command=commits.recv()=>ActorStep::Commit(command),
            result=poll=>ActorStep::Poll(result),
        }
    } else {
        tokio::select! {biased;
            _=cancel.cancelled()=>ActorStep::Cancel,
            _=suspend.notified()=>ActorStep::Suspend,
            result=poll=>ActorStep::Poll(result),
            command=commits.recv()=>ActorStep::Commit(command),
        }
    }
}
async fn actor(
    state: Weak<State>,
    handle: Arc<Handle>,
    project: String,
    input: Input,
    filters: ProjectFilters,
    publications: mpsc::Sender<Sealed>,
    mut commits: mpsc::Receiver<Commit>,
) {
    let epoch = handle.epoch;
    let mut watch = match initial_watch(&state, epoch, &handle, &project, input, filters).await {
        Ok(watch) => watch,
        Err(error) => {
            if !terminal_error(&handle, &error) {
                handle.stop(Phase::Failed);
            }
            return;
        }
    };
    let mut retry = false;
    let mut socket_burst = 0usize;
    #[cfg(test)]
    let (_paused_sender, mut paused_receiver) = mpsc::channel(1);
    loop {
        if retry {
            // Backpressure/contention must not spin canonical source lookups.
            tokio::select! {biased;_=handle.cancel.cancelled()=>break,_=tokio::time::sleep(RETRY)=>{}}
            handle.transition(
                Phase::Reconnecting,
                watch.committed_cursor().map(str::to_owned),
            );
            match reconnect(&state, epoch, &handle, &mut watch).await {
                Ok(()) => retry = false,
                Err(error) => {
                    if terminal_error(&handle, &error) {
                        break;
                    }
                    tokio::select! {biased;_=handle.cancel.cancelled()=>break,_=tokio::time::sleep(RETRY)=>{}}
                    continue;
                }
            }
        }
        // A private actor-fixture gate can leave the real bounded command
        // channel full while socket/control handling continues unchanged.
        #[cfg(test)]
        let active_commits = if handle.hold_commits.load(Ordering::Acquire) {
            handle.commits_paused.notify_one();
            &mut paused_receiver
        } else {
            &mut commits
        };
        #[cfg(not(test))]
        let active_commits = &mut commits;
        let step = select_step(
            socket_burst >= SOCKET_BURST,
            &handle.cancel,
            &handle.suspend,
            active_commits,
            watch.poll(&handle.cancel, now()),
        )
        .await;
        match step {
            ActorStep::Cancel => break,
            ActorStep::Suspend => {
                watch.suspend();
                retry = true;
                socket_burst = 0;
            }
            ActorStep::Poll(polled) => {
                socket_burst = socket_burst.saturating_add(1).min(SOCKET_BURST);

                let read = match polled {
                    Ok(ProjectTaskWatchPoll::Idle) => continue,
                    Ok(ProjectTaskWatchPoll::Read(read)) => read,
                    Err(error) => {
                        let error = BindingError::from(error);
                        if terminal_error(&handle, &error) {
                            break;
                        }
                        watch.suspend();
                        retry = true;
                        continue;
                    }
                };
                let Some(owner) = state.upgrade() else {
                    break;
                };
                let finished = {
                    let admitted = tokio::select! {biased;_=handle.cancel.cancelled()=>break,result=timeout(FINISH_LANE,owner.client.lock())=>result};
                    match admitted {
                        Ok(mut client) => {
                            if same_epoch(&owner, epoch, &handle.cancel).is_err() {
                                break;
                            }
                            client
                                .finish_project_task_watch_read(&watch, read)
                                .map_err(BindingError::from)
                        }
                        Err(_) => {
                            drop(read);
                            watch.suspend();
                            retry = true;
                            handle.transition(
                                Phase::Reconnecting,
                                watch.committed_cursor().map(str::to_owned),
                            );
                            continue;
                        }
                    }
                }; // Client guard gone before queue/serde waits.
                drop(owner);
                match finished {
                    Ok(Some(publication)) => {
                        // Never await a full data channel: retain at most one
                        // sealed candidate while polling controls/commit/cancel.
                        if publications
                            .try_send(Sealed { publication, epoch })
                            .is_err()
                        {
                            watch.suspend();
                            retry = true;
                        }
                    }
                    // Initial multipart partial frames legitimately retain a
                    // Reconnecting snapshot until final readiness. Keep reading;
                    // only a poll/finish error or explicit suspend reconnects.
                    Ok(None) => {}
                    Err(error) => {
                        if terminal_error(&handle, &error) {
                            break;
                        }
                        watch.suspend();
                        retry = true;
                    }
                }
            }
            ActorStep::Commit(commit) => {
                socket_burst = 0;

                let Some(commit) = commit else {
                    break;
                };
                let result = watch.commit(&commit.receipt).map_err(BindingError::from);
                if result.is_ok() {
                    handle.transition(
                        Phase::Connected,
                        watch.committed_cursor().map(str::to_owned),
                    );
                }
                let _ = commit.ack.send(result);
            }
        }
    }
    watch.close();
    handle.stop(Phase::Closed);
}

#[cfg(test)]
#[path = "session_project_task_watch_tests.rs"]
mod tests;
