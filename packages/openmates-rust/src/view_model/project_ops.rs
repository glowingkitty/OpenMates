//! Project agentic-coding operations for view-model shells: undo the Project
//! an assistant turn created, run a confined command on a Project source and
//! read, commit or land the chat worktree. Thin wrappers over
//! `Client::projects()` that bind the operation to the caller's cancellation,
//! so a shell marshals arguments and renders the result. Host refusals with a
//! stable code are data ([`RemoteRefusal`]), not errors.
use super::actor_host::ViewHost;
use crate::{
    client::Client,
    error::Result,
    local_cache::ByteStore,
    work::{
        CreatedProjectRecord, GitCommitResult, GitLandOutcome, GitStatusResult, Projects,
        RemoteCommand, RemoteCommandResult, RemoteOpError,
    },
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// A refusal of the Project source host or relay with its stable code
/// (`no_worktree`, `nothing_to_commit`, `write_authorization_denied`, ...).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RemoteRefusal {
    /// Stable lowercase wire code.
    pub code: String,
    /// Human-readable English reason from the host.
    pub message: String,
}

fn split<T>(
    result: std::result::Result<T, RemoteOpError>,
) -> Result<std::result::Result<T, RemoteRefusal>> {
    match result {
        Ok(value) => Ok(Ok(value)),
        Err(RemoteOpError::Core(error)) => Err(error),
        Err(RemoteOpError::Host { code, message }) => Ok(Err(RemoteRefusal {
            code: code.wire().to_owned(),
            message,
        })),
    }
}

fn projects(client: &mut Client) -> Projects<'_> {
    client.projects()
}

/// Undo the Project an assistant turn created for `chat_id`: deactivates the
/// chat focus and deletes the Project; the chat stays intact.
///
/// # Errors
/// `Forbidden` when the chat has no assistant-created Project; transport
/// errors; `Cancelled`.
pub fn undo_created_project<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    chat_id: String,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<CreatedProjectRecord>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let record = projects(host.core_mut().client_mut())
            .undo_created(&chat_id)
            .await?;
        host.core_mut().persist().await?;
        Ok(record)
    })
}

/// Run one confined command on the Project source of `selector` for `chat_id`
/// (`Projects::run_remote_command`); `operation_id` binds approval and request.
///
/// # Errors
/// `Invalid` for a malformed operation id or empty argv; transport errors.
/// A host refusal is `Ok(Err(RemoteRefusal))`.
pub fn run_remote_command<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    selector: String,
    source: Option<String>,
    chat_id: String,
    operation_id: String,
    command: RemoteCommand,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<std::result::Result<RemoteCommandResult, RemoteRefusal>>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let result = projects(host.core_mut().client_mut())
            .run_remote_command(
                &selector,
                source.as_deref(),
                &chat_id,
                &operation_id,
                &command,
            )
            .await;
        split(result)
    })
}

/// Read the chat worktree state (`Projects::git_status`).
///
/// # Errors
/// Transport errors; a host refusal (`no_worktree`) is `Ok(Err(..))`.
pub fn git_status<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    selector: String,
    source: Option<String>,
    chat_id: String,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<std::result::Result<GitStatusResult, RemoteRefusal>>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let result = projects(host.core_mut().client_mut())
            .git_status(&selector, source.as_deref(), &chat_id)
            .await;
        split(result)
    })
}

/// Commit every change of the chat worktree (`Projects::git_commit`).
///
/// # Errors
/// `Invalid` for a malformed operation id or empty message; transport errors.
pub fn git_commit<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    selector: String,
    source: Option<String>,
    chat_id: String,
    operation_id: String,
    message: String,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<std::result::Result<GitCommitResult, RemoteRefusal>>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let result = projects(host.core_mut().client_mut())
            .git_commit(
                &selector,
                source.as_deref(),
                &chat_id,
                &operation_id,
                &message,
            )
            .await;
        split(result)
    })
}

/// Land the chat worktree on its target branch (`Projects::git_land`); a
/// rebase conflict is the `Conflict` outcome, not an error.
///
/// # Errors
/// `Invalid` for a malformed operation id; transport errors.
pub fn git_land<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    selector: String,
    source: Option<String>,
    chat_id: String,
    operation_id: String,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<std::result::Result<GitLandOutcome, RemoteRefusal>>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let result = projects(host.core_mut().client_mut())
            .git_land(&selector, source.as_deref(), &chat_id, &operation_id)
            .await;
        split(result)
    })
}
