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

use super::dispatch::{self, FilesystemSourceAdapter, Handled, HostedSource};
use super::reads::HostRoot;
use crate::client::{Client, SourceHostOptions, SourceHostPoll, SourceHostSession};
use crate::error::{Error, Result};
use crate::session::Session;
use std::path::PathBuf;
use std::sync::Arc;
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

async fn bind(client: &mut Client, run: &SourceHostRun, cancel: &CancellationToken) -> Result<SourceHostSession> {
    let mut bindings = Vec::with_capacity(run.sources.len());
    for source in &run.sources {
        let filters = crate::work::ProjectFilters {
            personal: source.team_id.is_none(),
            team_id: source.team_id.clone(),
            ..Default::default()
        };
        bindings.push(
            client
                .projects()
                .with_filters(filters)
                .source_host_binding(&source.project_id, &source.source_id, Arc::new(FilesystemSourceAdapter))
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

/// Serve the sources until `cancel` fires.
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
    let hosted: Vec<HostedSource> = run
        .sources
        .iter()
        .map(|s| HostedSource {
            project_id: s.project_id.clone(),
            source_id: s.source_id.clone(),
            team_id: s.team_id.clone(),
            root: HostRoot {
                root: s.root.clone(),
                state_dir: run.state_dir.clone(),
                policy_source: None,
            },
            // The per-source target-branch setting is not stored yet; chat
            // worktrees default to the branch checked out in the source root.
            target_branch: None,
        })
        .collect();
    on_event(SourceHostEvent::Connecting { attempt: 0 });
    let mut host = bind(client, &run, &cancel).await?;
    on_event(SourceHostEvent::Connected);
    let mut attempt = 0u32;
    loop {
        let error = match serve(client, &mut host, &hosted, &cancel, on_event).await {
            Ok(()) => return Ok(()),
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
            let next = match client.prepare_source_host_reconnect(&mut host, cancel.child_token()).await {
                Ok(start) => start.connect().await,
                Err(error) => Err(error),
            };
            match next {
                Ok(session) => {
                    host = session;
                    attempt = 0;
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
    cancel: &CancellationToken,
    on_event: &mut (dyn FnMut(SourceHostEvent) + Send),
) -> Result<()> {
    loop {
        if cancel.is_cancelled() {
            // One bounded best-effort disconnect; the server times the lease out otherwise.
            let _ = host.disconnect(&CancellationToken::new()).await;
            on_event(SourceHostEvent::Disconnected);
            return Ok(());
        }
        // Poll with a private token so cancellation is observed here, before
        // the session closes, and the disconnect frame can still be sent.
        let read = match host.poll(&CancellationToken::new()).await? {
            SourceHostPoll::Idle => continue,
            SourceHostPoll::Read(read) => read,
        };
        let request = client.finish_source_host_read(host, read)?;
        let summary = match dispatch::handle(client, host, request, hosted, cancel).await? {
            Handled::Answered(summary) => summary,
            Handled::Discovery => "routing_discovery ok".to_owned(),
            Handled::Dropped => "request dropped".to_owned(),
        };
        on_event(SourceHostEvent::Request { summary });
    }
}
