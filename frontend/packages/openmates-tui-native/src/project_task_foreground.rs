//! Internal application driver for explicitly approved Project/source watches.
//! No source discovery/registration, terminal host identity or execution is implied.
//! The retained remote-access adapter may use this after its native host migration.
use crate::{
    client::{Client, ProjectTaskWatch, ProjectTaskWatchPoll},
    error::{Error, Result},
    project_task_cache::ProjectTaskCache,
    runtime_store::RuntimeStore,
    task_delivery::{CookieJournalContext, Journal},
};
use openmates_sdk::project_task_sync::{TaskSyncCommit, TaskSyncConnection};
use std::{
    collections::BTreeSet,
    path::PathBuf,
    sync::{Arc, Mutex as SyncMutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::{sync::Mutex, task::JoinHandle};
use tokio_util::sync::CancellationToken;

const MAX_WATCHES: usize = 16;
// Finish is synchronous once admitted. Suspend on bounded Client contention:
// invalidate the candidate, release the socket and recover from durable cursor.
// No socket control processing waits behind a long HTTP mutation operation.
const FINISH_ADMISSION: Duration = Duration::from_millis(50);
const SETUP_DEADLINE: Duration = Duration::from_secs(20);

type SharedClient = Arc<Mutex<Client>>;
type Cache = Arc<SyncMutex<ProjectTaskCache>>;
type Writer = JoinHandle<Result<TaskSyncCommit>>;

/// Supplied by the foreground source owner after explicit approval. Selectors are
/// resolved freshly through the authenticated SDK; input does not confer access.
pub struct ApprovedTaskSource {
    pub project: String,
    pub source_id: String,
}

struct GateState {
    ready: Vec<bool>,
    lease: CancellationToken,
}
/// Lifecycle fence only. TaskDelivery and its original caller remain authority.
struct Readiness(SyncMutex<GateState>);
impl Readiness {
    fn new(count: usize) -> Result<Self> {
        if count == 0 || count > MAX_WATCHES {
            return Err(Error::Invalid(
                "Select one to sixteen approved Project sources.",
            ));
        }
        Ok(Self(SyncMutex::new(GateState {
            ready: vec![false; count],
            lease: CancellationToken::new(),
        })))
    }
    fn set(&self, index: usize, ready: bool) -> Result<()> {
        let mut state = self.0.lock().map_err(|_| Error::Io)?;
        if !ready {
            state.lease.cancel();
            state.lease = CancellationToken::new();
        }
        *state.ready.get_mut(index).ok_or(Error::Protocol)? = ready;
        Ok(())
    }
    fn lease(&self) -> Result<Option<CancellationToken>> {
        let state = self.0.lock().map_err(|_| Error::Io)?;
        Ok(state
            .ready
            .iter()
            .all(|ready| *ready)
            .then(|| state.lease.child_token()))
    }
    fn stop(&self) {
        if let Ok(mut state) = self.0.lock() {
            state.ready.fill(false);
            state.lease.cancel();
        }
    }
}

/// Run until caller cancellation or a fail-closed terminal error. The explicit
/// client/store/cache root must belong to the same foreground application owner.
/// No credentials, directories or profiles are discovered by this function.
pub async fn run(
    client: SharedClient,
    store: &RuntimeStore,
    cache_root: PathBuf,
    selected: Vec<ApprovedTaskSource>,
    cancel: CancellationToken,
) -> Result<()> {
    let gate = Arc::new(Readiness::new(selected.len())?);
    let lifetime = cancel.child_token();
    let context = Arc::new({
        let client = client.lock().await;
        CookieJournalContext::capture(&client)?
    });
    let journal = context.journal(store)?;
    let mut actors = tokio::task::JoinSet::new();
    let mut setup_caches = Vec::new();
    let mut setup_index = 0;
    let setup = async {
        let mut projects = BTreeSet::new();
        let mut prepared = Vec::new();
        for (index, selected) in selected.into_iter().enumerate() {
            setup_index = index;
            let lookup = async {
                let mut client = client.lock().await;
                context.check(&client)?;
                client.set_operation_cancel(lifetime.clone());
                client
                    .projects()
                    .with_filters(context.project_filters())
                    .task_source(&selected.project, &selected.source_id)
                    .await
            };
            let binding = tokio::select! { biased;
                _ = cancel.cancelled() => return Err(Error::Cancelled),
                result = tokio::time::timeout(SETUP_DEADLINE, lookup) => result.unwrap_or(Err(Error::Offline))?,
            };
            context.check_scope(binding.scope())?;
            // Baseline selects one source per Project; do not race two writers
            // against the same reader snapshot with different source identities.
            if !projects.insert(binding.scope().project_id().to_owned()) {
                return Err(Error::Conflict);
            }
            let scope = binding.scope().clone();
            let cleanup_scope = scope.clone();
            let authority = binding.owner_authority();
            let sync = binding.new_sync(None, now())?;
            let root = cache_root.clone();
            let owner = context.hashed_email().to_owned();
            let (cache, sync) = tokio::task::spawn_blocking(move || {
                let mut cache =
                    ProjectTaskCache::open_with_sync(&root, scope, &owner, sync, now())?;
                let sync = cache.take_sync()?;
                Ok::<_, Error>((Arc::new(SyncMutex::new(cache)), sync))
            })
            .await
            .map_err(|_| Error::Io)??;
            setup_caches.push((index, cache.clone(), cleanup_scope, authority));
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            let start = {
                let client = tokio::select! { biased;
                    _ = cancel.cancelled() => return Err(Error::Cancelled),
                    client = client.lock() => client,
                };
                context.check(&client)?;
                client.prepare_project_task_watch(binding, sync, lifetime.clone())?
            };
            // Detached connect must never borrow the shared Client lane.
            let watch = tokio::select! { biased;
                _ = cancel.cancelled() => return Err(Error::Cancelled),
                result = tokio::time::timeout(SETUP_DEADLINE, start.connect()) => result.unwrap_or(Err(Error::Offline))?,
            };
            prepared.push((index, watch, cache));
        }
        Ok::<_, Error>(prepared)
    };
    // Cache restore uses a blocking descriptor transaction and must be drained;
    // never detach it by dropping an outer timeout future. Network waits above
    // remain independently bounded/cancellable.
    let prepared_result = setup.await;
    let mut outcome = match prepared_result {
        Ok(prepared) => {
            for (index, watch, cache) in prepared {
                actors.spawn(watch_actor(
                    index,
                    client.clone(),
                    context.clone(),
                    watch,
                    cache,
                    gate.clone(),
                    lifetime.clone(),
                ));
            }
            Ok(())
        }
        Err(error) => {
            // Failed setup has no actor owner yet. Close/fence each opened
            // cache explicitly rather than dropping a restored plaintext view.
            let mut failure = error;
            for (index, cache, scope, authority) in setup_caches {
                let revoke = setup_revoke_cache(authority.is_valid(), index, setup_index, error);
                if let Err(error) = cache_state(cache, revoke, true, scope).await {
                    failure = error;
                }
            }
            Err(failure)
        }
    };
    if outcome.is_ok() {
        actors.spawn(replay_actor(
            client,
            context,
            journal,
            gate.clone(),
            lifetime.clone(),
        ));
        outcome = tokio::select! { biased;
            _ = cancel.cancelled() => Ok(()),
            result = actors.join_next() => match result {
                Some(Ok(result)) => result,
                _ => Err(Error::Io),
            },
        };
    }
    // Cancel first so pending sealed writes lose authority before awaiting fsync.
    gate.stop();
    lifetime.cancel();
    while let Some(result) = actors.join_next().await {
        match result {
            Ok(Ok(())) => {}
            Ok(Err(Error::Cancelled)) if cancel.is_cancelled() => {}
            Ok(Err(error)) if outcome.is_ok() => outcome = Err(error),
            Err(_) if outcome.is_ok() => outcome = Err(Error::Io),
            _ => {}
        }
    }
    if cancel.is_cancelled() && matches!(outcome, Err(Error::Cancelled)) {
        Ok(())
    } else {
        outcome
    }
}

async fn replay_actor(
    client: SharedClient,
    context: Arc<CookieJournalContext>,
    journal: Journal,
    gate: Arc<Readiness>,
    cancel: CancellationToken,
) -> Result<()> {
    let mut timer = tokio::time::interval(Duration::from_secs(5));
    timer.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
    loop {
        tokio::select! { biased; _ = cancel.cancelled() => return Ok(()), _ = timer.tick() => {} }
        // Bound work per tick; global journal FIFO/cooldown owns admission.
        for _ in 0..3 {
            let Some(lease) = gate.lease()? else {
                break;
            };
            let result = replay_head(&client, &context, &journal, &lease, &cancel).await;
            match result {
                Ok(true) => {}
                Ok(false) => break,
                Err(error) if crate::cli::task_queue::retryable(&error) => break,
                Err(crate::cli::CliError::Client(Error::Cancelled)) if lease.is_cancelled() => {
                    break;
                }
                Err(crate::cli::CliError::PendingTask {
                    source: Error::Cancelled,
                    ..
                }) if lease.is_cancelled() => break,
                // Unknown caller/FIFO provenance or terminal rejection retains
                // the journal and stops the driver; never skip the global head.
                Err(error) => {
                    return Err(match error {
                        crate::cli::CliError::Client(error) => error,
                        _ => Error::Unavailable {
                            code: "task_delivery_replay_stopped",
                            reason: "RETAINED_HEAD_REQUIRES_REVIEW",
                        },
                    });
                }
            }
        }
    }
}

async fn replay_head(
    client: &SharedClient,
    context: &CookieJournalContext,
    journal: &Journal,
    lease: &CancellationToken,
    cancel: &CancellationToken,
) -> std::result::Result<bool, crate::cli::CliError> {
    // Every descriptor/fsync operation happens before or after the Client lane.
    let Some(prepared) = crate::cli::task_queue::prepare_replay(journal, lease).await? else {
        return Ok(false);
    };
    let result = {
        let mut client = tokio::select! { biased;
            _ = cancel.cancelled() => return Err(Error::Cancelled.into()),
            _ = lease.cancelled() => return Err(Error::Cancelled.into()),
            client = client.lock() => client,
        };
        // Original cookie context and aggregate readiness are checked again
        // after durable admission and immediately before exact SDK dispatch.
        crate::cli::task_queue::send_replay(&mut client, context, &prepared, lease).await
    }; // Client guard dropped before acknowledge/defer and private journal IO.
    crate::cli::task_queue::finish_replay(journal, prepared, result).await?;
    Ok(true)
}

enum Event {
    Cancel,
    Written(std::result::Result<Result<TaskSyncCommit>, tokio::task::JoinError>),
    Poll(Result<ProjectTaskWatchPoll>),
}
async fn writer_result(
    writer: &mut Option<Writer>,
) -> std::result::Result<Result<TaskSyncCommit>, tokio::task::JoinError> {
    match writer {
        Some(writer) => writer.await,
        None => std::future::pending().await,
    }
}
async fn watch_actor(
    index: usize,
    client: SharedClient,
    context: Arc<CookieJournalContext>,
    mut watch: ProjectTaskWatch,
    cache: Cache,
    gate: Arc<Readiness>,
    cancel: CancellationToken,
) -> Result<()> {
    let mut source_denied = false;
    let mut writer: Option<Writer> = None;
    let outcome = async {
        loop {
            let event = tokio::select! { biased;
                _ = cancel.cancelled() => Event::Cancel,
                // Read/control before finished publication: revoke wins over a
                // concurrently completed fsync. No queue of plaintext batches.
                read = watch.poll(&cancel, now()) => Event::Poll(read),
                written = writer_result(&mut writer) => Event::Written(written),
            };
            match event {
                Event::Cancel => return Ok(()),
                Event::Written(result) => {
                    writer = None;
                    let receipt = result.map_err(|_| Error::Io)??;
                    if cancel.is_cancelled() { return Ok(()); }
                    watch.commit(&receipt)?;
                    gate.set(index, true)?;
                },
                Event::Poll(Ok(ProjectTaskWatchPoll::Idle)) => {},
                Event::Poll(read) => {
                    // Typed revocation is visible before Client admission.
                    if watch.connection() == TaskSyncConnection::Revoked {
                        source_denied = true;
                        gate.set(index, false)?;
                        watch.close();
                        return Err(Error::Forbidden);
                    }
                    let publication = match read {
                        Ok(ProjectTaskWatchPoll::Read(read)) => {
                            let admitted = tokio::select! { biased;
                                _ = cancel.cancelled() => return Ok(()),
                                result = tokio::time::timeout(FINISH_ADMISSION, client.lock()) => result,
                            };
                            match admitted {
                                Ok(mut client) => {
                                    context.check(&client)?;
                                    client.finish_project_task_watch_read(&watch, read)
                                },
                                Err(_) => {
                                    // Discard before suspension; it must never
                                    // be finished against the next connection.
                                    drop(read);
                                    gate.set(index, false)?;
                                    Err(Error::Offline)
                                },
                            }
                        },
                        Err(error) => Err(error),
                        _ => unreachable!(),
                    };
                    match publication {
                        Ok(Some(publication)) => {
                            if writer.is_some() { return Err(Error::Conflict); }
                            let cache = cache.clone();
                            writer = Some(tokio::task::spawn_blocking(move || {
                                cache.lock().map_err(|_| Error::Io)?.publish_validated(&publication, now())
                            }));
                        },
                        Ok(None) => {},
                        Err(Error::Offline | Error::Protocol | Error::Conflict) => {
                            gate.set(index, false)?;
                            // A finish/transport error cannot leave a staged
                            // candidate eligible while we wait for Client.
                            // Preserve committed cursor, not pending plaintext.
                            watch.suspend();
                            // Drain the sole invalidated writer before cache mutation.
                            if let Some(writer) = writer.take() { let _ = writer.await; }
                            cache_state(cache.clone(), false, false, watch.scope().clone()).await?;
                            loop {
                                let attempt = async {
                                    let prepared = {
                                        let mut client = client.lock().await;
                                        context.check(&client)?;
                                        client.set_operation_cancel(cancel.clone());
                                        client.prepare_project_task_watch_reconnect(&mut watch).await?
                                    };
                                    watch.reconnect(prepared, &cancel).await
                                };
                                let result = tokio::select! { biased;
                                    _ = cancel.cancelled() => return Ok(()),
                                    result = tokio::time::timeout(SETUP_DEADLINE, attempt) => result.unwrap_or(Err(Error::Offline)),
                                };
                                match result {
                                    Ok(()) => break,
                                    Err(Error::Offline | Error::Protocol) => {
                                        tokio::select! { biased; _ = cancel.cancelled() => return Ok(()),
                                            _ = tokio::time::sleep(Duration::from_secs(2)) => {} }
                                    },
                                    Err(error) => {
                                        // This denial is from fresh canonical
                                        // authorization of this exact source.
                                        source_denied = error == Error::Forbidden;
                                        return Err(error);
                                    },
                                }
                            }
                        },
                        Err(error) => return Err(error),
                    }
                },
            }
        }
    }.await;
    // Invalidate every queued sealed view synchronously before awaiting writer.
    let _ = gate.set(index, false);
    let scope = watch.scope().clone();
    watch.close();
    if let Some(writer) = writer {
        let _ = writer.await;
    }
    // The negative owner signal is independent of source/socket/lifetime
    // state and generic errors. Source denial erases only this cache; actual
    // Client epoch/paired-owner loss is observed separately by every sibling.
    let revoke = revoke_cache(watch.owner_authority_valid(), source_denied);
    let cleanup = cache_state(cache, revoke, true, scope).await;
    cleanup.and(outcome)
}

fn setup_revoke_cache(
    owner_authority_valid: bool,
    opened_index: usize,
    failed_index: usize,
    error: Error,
) -> bool {
    revoke_cache(
        owner_authority_valid,
        error == Error::Forbidden && opened_index == failed_index,
    )
}
fn revoke_cache(owner_authority_valid: bool, source_denied: bool) -> bool {
    !owner_authority_valid || source_denied
}

async fn cache_state(
    cache: Cache,
    revoke: bool,
    stopped: bool,
    scope: openmates_sdk::project_task_sync::TaskSyncScope,
) -> Result<()> {
    tokio::task::spawn_blocking(move || {
        let mut cache = cache.lock().map_err(|_| Error::Io)?;
        if revoke {
            cache.revoke_watch(&scope, now())
        } else if stopped {
            cache.stopped()
        } else {
            cache.reconnecting()
        }
    })
    .await
    .map_err(|_| Error::Io)?
}
fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

#[cfg(test)]
#[path = "project_task_foreground_tests.rs"]
mod tests;
