//! Reconnecting run loop of the filesystem host (npm `runRemoteAccessBridge`).
//!
//! Binds every source through the backend, registers one host session, then
//! polls requests and answers them one at a time until cancelled. Transport
//! loss reconnects with `min(30 s, 1 s * 2^(n-1))` +-20 % jitter and fresh
//! per-source re-authorization; a takeover conflict, revoked access or an
//! expired session ends the run so the shell can prompt or re-login.
//! Deviation from npm: requests are served sequentially (npm overlaps them);
//! the session keeps at most four pending, so a slow search delays the next
//! request but never drops it.

use super::creation_host::{self, HostState};
use super::dispatch::{self, Handled, HostedSource};
use crate::client::{Client, SourceHostOptions, SourceHostPoll, SourceHostSession};
use crate::error::{Error, Result};
use crate::session::Session;
use std::path::PathBuf;
use std::time::Duration;
use tokio_util::sync::CancellationToken;

/// One source to serve.
#[derive(Clone, Debug)]
pub struct SourceHostRunSource {
    /// Project the source belongs to.
    pub project_id: String,
    /// Backend source ID.
    pub source_id: String,
    /// Team context, or `None` for a personal Project.
    pub team_id: Option<String>,
    /// Approved local root (canonicalized again on every request).
    pub root: PathBuf,
}

/// Inputs of one host run.
#[derive(Clone, Debug)]
pub struct SourceHostRun {
    /// Sources to serve (1 to 16, one owner and context).
    pub sources: Vec<SourceHostRunSource>,
    /// Stable session ID for this process; reused across reconnects.
    pub source_session_id: String,
    /// The user confirmed taking over sources owned by another process.
    pub confirmed_takeover: bool,
    /// OpenMates (npm) state directory holding private policy state.
    pub state_dir: PathBuf,
    /// Shell hook returning credentials another process rotated and stored
    /// since this host last loaded or saved them, called before every
    /// reconnect so a stale rotated refresh cookie is never reused.
    pub credential_sync: Option<CredentialSync>,
}

/// Future returned by a [`CredentialSync`] call.
pub type CredentialSyncFuture =
    std::pin::Pin<Box<dyn std::future::Future<Output = Result<Option<Session>>> + Send>>;

/// Shell-provided lookup of newer stored credentials (see `SourceHostRun`).
#[derive(Clone)]
pub struct CredentialSync(pub std::sync::Arc<dyn Fn() -> CredentialSyncFuture + Send + Sync>);

impl std::fmt::Debug for CredentialSync {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("CredentialSync")
    }
}

/// Adopt newer stored credentials, if the shell reports any, before a reconnect.
async fn sync_credentials(client: &mut Client, sync: Option<&CredentialSync>) -> Result<()> {
    if let Some(CredentialSync(lookup)) = sync {
        if let Some(stored) = lookup().await? {
            client.adopt_stored_credentials(&stored)?;
        }
    }
    Ok(())
}

/// Lifecycle notifications for the shell (npm `remote_access_lifecycle`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SourceHostEvent {
    /// Opening the first connection or a reconnect attempt.
    Connecting { attempt: u32 },
    /// Registered and serving.
    Connected,
    /// Waiting before the next attempt.
    Reconnecting { attempt: u32, delay_ms: u64 },
    /// Cleanly disconnected after cancellation.
    Disconnected,
    /// One request was handled (`"<operation> <ok|error code>"`, or discovery/dropped).
    Request { summary: String },
}

fn reconnect_delay(attempt: u32) -> Duration {
    use rand::Rng;
    let base = 30_000f64.min(1_000.0 * 2f64.powi(attempt.saturating_sub(1) as i32));
    let jitter = rand::thread_rng().gen_range(0.8..1.2);
    Duration::from_millis((base * jitter).round() as u64)
}

/// Errors that end the run instead of reconnecting.
fn terminal(error: &Error) -> bool {
    matches!(
        error,
        Error::Conflict
            | Error::Forbidden
            | Error::Authentication
            | Error::Expired
            | Error::Invalid(_)
            | Error::Cancelled
    )
}

/// How often a host that may create folders re-checks for new placeholders
/// while it idles (placeholders are also discovered at start and on reconnect).
const RESCAN_INTERVAL: Duration = Duration::from_secs(20);

/// Why [`serve`] returned without an error.
enum Served {
    /// Cancelled; the session was disconnected.
    Finished,
    /// A `create_source` request was answered; serve the new folder.
    Created(HostedSource),
    /// The idle rescan interval elapsed.
    Rescan,
}

/// Bind every source of `state` (placeholders with the creation adapter, the
/// rest with the filesystem adapter) and register one host session.
async fn bind(
    client: &mut Client,
    run: &SourceHostRun,
    state: &HostState,
    cancel: &CancellationToken,
) -> Result<SourceHostSession> {
    let mut bindings = Vec::with_capacity(state.sources.len());
    for source in &state.sources {
        let filters = crate::work::ProjectFilters {
            personal: source.team_id.is_none(),
            team_id: source.team_id.clone(),
            ..Default::default()
        };
        bindings.push(
            client
                .projects()
                .with_filters(filters)
                .source_host_binding(&source.project_id, &source.source_id, state.adapter(&source.source_id))
                .await?,
        );
    }
    let options = SourceHostOptions {
        source_session_id: run.source_session_id.clone(),
        confirmed_takeover: run.confirmed_takeover,
    };
    client
        .prepare_source_host(bindings, options, cancel.child_token())?
        .connect()
        .await
}

fn report_notes(notes: Vec<String>, on_event: &mut (dyn FnMut(SourceHostEvent) + Send)) {
    for summary in notes {
        on_event(SourceHostEvent::Request { summary });
    }
}

/// Replace the session with a fresh registration of the current `state`
/// (a created folder is served with the normal capabilities, newly found
/// placeholders are bound). `state.rebind_needed` stays set when the new
/// registration fails so the reconnect loop registers fresh instead of reusing
/// the stale bindings.
async fn reseat(
    client: &mut Client,
    run: &SourceHostRun,
    state: &mut HostState,
    host: &mut SourceHostSession,
    hosted: &mut Vec<HostedSource>,
    cancel: &CancellationToken,
    on_event: &mut (dyn FnMut(SourceHostEvent) + Send),
) -> Result<()> {
    *hosted = state.hosted(&run.state_dir);
    state.rebind_needed = true;
    host.close();
    on_event(SourceHostEvent::Connecting { attempt: 0 });
    *host = bind(client, run, state, cancel).await?;
    state.rebind_needed = false;
    on_event(SourceHostEvent::Connected);
    Ok(())
}

/// Look for placeholders and unfinished creations; reseat when any were found.
/// A transient discovery failure is reported and retried at the next rescan.
async fn rescan(
    client: &mut Client,
    run: &SourceHostRun,
    state: &mut HostState,
    host: &mut SourceHostSession,
    hosted: &mut Vec<HostedSource>,
    cancel: &CancellationToken,
    on_event: &mut (dyn FnMut(SourceHostEvent) + Send),
) -> Result<()> {
    match creation_host::discover(client, run, state).await {
        Ok(found) => {
            report_notes(found.notes, on_event);
            if found.changed {
                reseat(client, run, state, host, hosted, cancel, on_event).await?;
            }
            Ok(())
        }
        Err(error) if terminal(&error) => Err(error),
        Err(error) => {
            on_event(SourceHostEvent::Request {
                summary: format!("creation_discovery {error}"),
            });
            Ok(())
        }
    }
}

/// One serve step; `Ok(true)` when the run finished.
// The step threads the whole session state; a struct would only rename the arguments.
#[allow(clippy::too_many_arguments)]
async fn step(
    client: &mut Client,
    run: &SourceHostRun,
    state: &mut HostState,
    host: &mut SourceHostSession,
    hosted: &mut Vec<HostedSource>,
    pending_scan: &mut bool,
    cancel: &CancellationToken,
    on_event: &mut (dyn FnMut(SourceHostEvent) + Send),
) -> Result<bool> {
    if std::mem::take(pending_scan) {
        rescan(client, run, state, host, hosted, cancel, on_event).await?;
    }
    let rescan_enabled = creation_host::creation_configured(&run.state_dir);
    match serve(client, host, hosted, rescan_enabled, cancel, on_event).await? {
        Served::Finished => Ok(true),
        Served::Created(source) => {
            state.adopt(&source);
            reseat(client, run, state, host, hosted, cancel, on_event).await?;
            Ok(false)
        }
        Served::Rescan => {
            rescan(client, run, state, host, hosted, cancel, on_event).await?;
            Ok(false)
        }
    }
}

/// Serve the sources until `cancel` fires.
///
/// Before the first registration the host looks for new-Project placeholders
/// addressed to this device (only when a new-Projects folder is configured) and
/// binds them with the `create_source` capability; the same check runs after
/// every reconnect and periodically while idle. A created folder is served with
/// the normal capabilities in the running session.
///
/// # Errors
/// `Conflict` when another process owns a source and takeover was not
/// confirmed; `Forbidden`/`Authentication`/`Expired` when access ended;
/// binding errors from the backend. Transport failures reconnect instead.
pub async fn run_source_host(
    client: &mut Client,
    run: SourceHostRun,
    cancel: CancellationToken,
    on_event: &mut (dyn FnMut(SourceHostEvent) + Send),
) -> Result<()> {
    let mut state = HostState::new(&run);
    on_event(SourceHostEvent::Connecting { attempt: 0 });
    match creation_host::discover(client, &run, &mut state).await {
        Ok(found) => report_notes(found.notes, on_event),
        Err(error) if terminal(&error) => return Err(error),
        Err(error) => on_event(SourceHostEvent::Request {
            summary: format!("creation_discovery {error}"),
        }),
    }
    let mut hosted = state.hosted(&run.state_dir);
    let mut host = bind(client, &run, &state, &cancel).await?;
    on_event(SourceHostEvent::Connected);
    let mut attempt = 0u32;
    let mut pending_scan = false;
    loop {
        let error = match step(client, &run, &mut state, &mut host, &mut hosted, &mut pending_scan, &cancel, on_event).await {
            Ok(true) => return Ok(()),
            Ok(false) => continue,
            Err(error) => error,
        };
        if cancel.is_cancelled() {
            host.close();
            on_event(SourceHostEvent::Disconnected);
            return Ok(());
        }
        if error == Error::Expired {
            return client.finish_source_host_failure(&host, error);
        }
        if terminal(&error) {
            host.close();
            return Err(error);
        }
        loop {
            attempt += 1;
            let delay = reconnect_delay(attempt);
            on_event(SourceHostEvent::Reconnecting {
                attempt,
                delay_ms: delay.as_millis() as u64,
            });
            tokio::select! {
                _ = cancel.cancelled() => {
                    host.close();
                    on_event(SourceHostEvent::Disconnected);
                    return Ok(());
                }
                _ = tokio::time::sleep(delay) => {}
            }
            on_event(SourceHostEvent::Connecting { attempt });
            if let Err(error) = sync_credentials(client, run.credential_sync.as_ref()).await {
                host.close();
                return Err(error);
            }
            let next = if state.rebind_needed {
                bind(client, &run, &state, &cancel).await
            } else {
                match client.prepare_source_host_reconnect(&mut host, cancel.child_token()).await {
                    Ok(start) => start.connect().await,
                    Err(error) => Err(error),
                }
            };
            match next {
                Ok(session) => {
                    host = session;
                    state.rebind_needed = false;
                    attempt = 0;
                    pending_scan = true;
                    on_event(SourceHostEvent::Connected);
                    break;
                }
                Err(error) if terminal(&error) && !cancel.is_cancelled() => return Err(error),
                Err(_) if cancel.is_cancelled() => {
                    on_event(SourceHostEvent::Disconnected);
                    return Ok(());
                }
                Err(_) => continue,
            }
        }
    }
}

/// Poll and answer requests on one connected session.
async fn serve(
    client: &mut Client,
    host: &mut SourceHostSession,
    hosted: &[HostedSource],
    rescan: bool,
    cancel: &CancellationToken,
    on_event: &mut (dyn FnMut(SourceHostEvent) + Send),
) -> Result<Served> {
    let started = std::time::Instant::now();
    loop {
        if cancel.is_cancelled() {
            // One bounded best-effort disconnect; the server times the lease out otherwise.
            let _ = host.disconnect(&CancellationToken::new()).await;
            on_event(SourceHostEvent::Disconnected);
            return Ok(Served::Finished);
        }
        // Poll with a private token so cancellation is observed here, before
        // the session closes, and the disconnect frame can still be sent.
        let read = match host.poll(&CancellationToken::new()).await? {
            SourceHostPoll::Idle => {
                if rescan && started.elapsed() >= RESCAN_INTERVAL {
                    return Ok(Served::Rescan);
                }
                continue;
            }
            SourceHostPoll::Read(read) => read,
        };
        let request = client.finish_source_host_read(host, read)?;
        let (summary, created) = match dispatch::handle(client, host, request, hosted, cancel).await? {
            Handled::Answered(summary) => (summary, None),
            Handled::Created { summary, source } => (summary, Some(source)),
            Handled::Discovery => ("routing_discovery ok".to_owned(), None),
            Handled::Dropped => ("request dropped".to_owned(), None),
        };
        on_event(SourceHostEvent::Request { summary });
        if let Some(source) = created {
            return Ok(Served::Created(source));
        }
    }
}
