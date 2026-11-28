use super::actor_host::ViewHost;
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use serde_json::Value;
use tokio_util::sync::CancellationToken;

/// Largest page of Checks the list returns.
const LIST_LIMIT: u8 = 100;

/// The Checks of a Project as full decrypted views (`check`, `revision`,
/// `latest_run`, see [`project_check_show`]), one `show` per listed Check.
/// `team_id` scopes a Team Project (`None`: Personal).
///
/// # Errors
/// `Forbidden`; `Invalid` for a malformed id; transport errors; `Cancelled`.
pub fn project_checks_list<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    project_id: String,
    team_id: Option<String>,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<Vec<Value>>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let mut checks = host.core_mut().client_mut().checks().with_team(team_id);
        let heads = checks.list(Some(&project_id), None, LIST_LIMIT).await?;
        let mut views = Vec::with_capacity(heads.len());
        for head in &heads {
            let id = head["check_id"].as_str().ok_or(Error::Protocol)?;
            views.push(checks.show(id, Some(&project_id), None).await?);
        }
        host.core_mut().persist().await?;
        Ok(views)
    })
}

/// One Check with its current revision, latest run and source results, as the
/// core's decrypted view (`check`, `revision`, `latest_run` with `stale`).
///
/// # Errors
/// `Forbidden`; `Invalid`; `Conflict` when the definition hash mismatches;
/// transport errors; `Cancelled`.
pub fn project_check_show<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    project_id: String,
    team_id: Option<String>,
    check_id: String,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<Value>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let view = host
            .core_mut()
            .client_mut()
            .checks()
            .with_team(team_id)
            .show(&check_id, Some(&project_id), None)
            .await?;
        host.core_mut().persist().await?;
        Ok(view)
    })
}

/// Starts a run on the Check's current revision and returns the new run id.
///
/// # Errors
/// `Forbidden`; `Invalid`; `Protocol` when the answer has no run id; transport
/// errors; `Cancelled`.
pub fn project_check_start_run<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    project_id: String,
    team_id: Option<String>,
    check_id: String,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<String>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let started = host
            .core_mut()
            .client_mut()
            .checks()
            .with_team(team_id)
            .start_run(&check_id, None, None, Some(&project_id))
            .await?;
        host.core_mut().persist().await?;
        started["run"]["run_id"]
            .as_str()
            .map(str::to_owned)
            .ok_or(Error::Protocol)
    })
}

/// Records the human decision (`confirmed`, `rejected`, `blocked`, `waived`)
/// of one pending human source, with an optional encrypted note.
///
/// # Errors
/// `Invalid` for an unknown decision or source; `Forbidden`; transport errors;
/// `Cancelled`.
#[allow(clippy::too_many_arguments)]
pub fn project_check_confirm_human<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    project_id: String,
    team_id: Option<String>,
    check_id: String,
    run_id: String,
    binding_id: String,
    decision: String,
    note: Option<String>,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let note_pair = note.as_deref().map(|n| (check_id.as_str(), n));
        host.core_mut()
            .client_mut()
            .checks()
            .with_team(team_id)
            .confirm_human(
                &run_id,
                &binding_id,
                &decision,
                note_pair,
                Some(&project_id),
            )
            .await?;
        host.core_mut().persist().await?;
        Ok(())
    })
}
