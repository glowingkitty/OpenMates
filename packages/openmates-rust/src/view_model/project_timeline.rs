//! Project timeline and whole-commit restore for view-model shells: thin
//! wrappers over `Projects::timeline` and `Client::restore_project_commit` that
//! bind the operation to the caller's cancellation. Plan `project-timeline`.
use super::actor_host::ViewHost;
use crate::{
    error::Result,
    local_cache::ByteStore,
    client::ProjectCommitUserRestore,
    work::{ProjectFilters, ProjectTimelinePage},
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// One page of the Project timeline, newest first. `before` is the previous
/// page's cursor; `team_id` scopes a Team Project (`None`: Personal).
///
/// # Errors
/// `Invalid` for a page size outside 1..=100; `Forbidden`; transport errors;
/// `Cancelled`.
pub fn project_timeline<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    project_id: String,
    team_id: Option<String>,
    limit: Option<u64>,
    before: Option<String>,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<ProjectTimelinePage>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let filters = ProjectFilters {
            personal: team_id.is_none(),
            team_id,
            include_archived: Some(true),
        };
        let page = host
            .core_mut()
            .client_mut()
            .projects()
            .with_filters(filters)
            .timeline(&project_id, limit, before)
            .await?;
        host.core_mut().persist().await?;
        Ok(page)
    })
}

/// Restore every file of `commit_id` as new versions and record a restore
/// commit authored by the user. `operation_id` (a UUID) makes it idempotent.
///
/// # Errors
/// `Invalid` when no file could be restored; `Forbidden`; transport errors;
/// `Cancelled`.
pub fn restore_project_commit<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    project_id: String,
    team_id: Option<String>,
    commit_id: String,
    operation_id: String,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<ProjectCommitUserRestore>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let restored = host
            .core_mut()
            .client_mut()
            .restore_project_commit(
                &project_id,
                team_id.as_deref(),
                &commit_id,
                None,
                Some(operation_id),
            )
            .await?;
        host.core_mut().persist().await?;
        Ok(restored)
    })
}
