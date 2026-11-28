use super::actor_host::ViewHost;
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use serde_json::{Value, json};
use tokio_util::sync::CancellationToken;

/// Largest page of Specifications or revisions a call returns.
const LIST_LIMIT: u8 = 100;

/// The Specifications of a Project, one decrypted `show` view each
/// (`specification` head and current `revision` with its document).
/// `team_id` scopes a Team Project (`None`: Personal).
///
/// # Errors
/// `Forbidden`; `Invalid` for a malformed id; `Conflict` when a document no
/// longer matches its commitment; transport errors; `Cancelled`.
pub fn project_specifications_list<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    project_id: String,
    team_id: Option<String>,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<Vec<Value>>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let mut specs = host.core_mut().client_mut().specifications().with_team(team_id);
        let heads = specs.list(&project_id, LIST_LIMIT, None).await?;
        let mut views = Vec::with_capacity(heads.len());
        for head in &heads {
            let id = head["specification_id"].as_str().ok_or(Error::Protocol)?;
            views.push(specs.show(&project_id, id, None).await?);
        }
        host.core_mut().persist().await?;
        Ok(views)
    })
}

/// One Specification at a revision (default: the current one) with its
/// revision history: `{specification, revision, revisions}`.
///
/// # Errors
/// `Forbidden`; `Invalid`; `Conflict` on a commitment mismatch; transport
/// errors; `Cancelled`.
pub fn project_specification_open<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    project_id: String,
    team_id: Option<String>,
    specification_id: String,
    revision_id: Option<String>,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<Value>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let mut specs = host.core_mut().client_mut().specifications().with_team(team_id);
        let shown = specs
            .show(&project_id, &specification_id, revision_id.as_deref())
            .await?;
        let revisions = specs
            .revisions(&project_id, &specification_id, LIST_LIMIT, None)
            .await?;
        host.core_mut().persist().await?;
        Ok(json!({
            "specification": shown["specification"],
            "revision": shown["revision"],
            "revisions": revisions,
        }))
    })
}

/// Approves exactly one revision. Refuses with `Conflict` when `content_hash`
/// is not the commitment the core verified for that revision.
///
/// # Errors
/// `Conflict`; `Forbidden`; `Invalid`; transport errors; `Cancelled`.
pub fn project_specification_approve<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    project_id: String,
    team_id: Option<String>,
    specification_id: String,
    revision_id: String,
    content_hash: String,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<()>> {
    Box::pin(async move {
        host.core_mut().begin_client_operation(cancel);
        let mut specs = host.core_mut().client_mut().specifications().with_team(team_id);
        let shown = specs
            .show(&project_id, &specification_id, Some(&revision_id))
            .await?;
        if shown["revision"]["content_hash"].as_str() != Some(content_hash.as_str()) {
            return Err(Error::Conflict);
        }
        specs
            .approve(&project_id, &specification_id, &revision_id)
            .await?;
        host.core_mut().persist().await?;
        Ok(())
    })
}
