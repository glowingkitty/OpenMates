//! New empty documents, sheets, slide decks and code files in a Project for
//! view-model shells: a thin wrapper over `Projects::create_document` that
//! binds the operation to the caller's cancellation. Spec:
//! `projects.items.create-documents`.
use super::actor_host::ViewHost;
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
    work::{CreatedProjectDocument, ProjectDocumentKind, ProjectFilters},
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// Create a new empty Project file of `kind` (`document`, `sheet`, `slides`,
/// `code`) named `name` in `folder_id` (Project root when `None`).
/// `team_id` scopes a Team Project; `None` is a Personal Project.
///
/// # Errors
/// `Invalid` for an unknown kind, empty name or malformed id; `Forbidden`;
/// transport errors; `Cancelled`.
pub fn create_project_document<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    project_id: String,
    team_id: Option<String>,
    kind: String,
    name: String,
    folder_id: Option<String>,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<CreatedProjectDocument>> {
    Box::pin(async move {
        let kind = ProjectDocumentKind::from_wire(&kind)
            .ok_or(Error::Invalid("Unknown Project file kind."))?;
        host.core_mut().begin_client_operation(cancel);
        let filters = ProjectFilters {
            personal: team_id.is_none(),
            team_id,
            include_archived: None,
        };
        let created = host
            .core_mut()
            .client_mut()
            .projects()
            .with_filters(filters)
            .create_document(&project_id, kind, &name, folder_id.as_deref())
            .await?;
        host.core_mut().persist().await?;
        Ok(created)
    })
}
