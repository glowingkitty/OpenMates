//! Create a new empty document, sheet, slide deck or code file in a Project
//! folder. The core builds the blank content, encrypts it and uploads the
//! embed with its Project link; Swift supplies only the Project, folder, kind
//! and name and opens the returned content. Spec
//! `projects.items.create-documents`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use openmates_sdk::view_model;
use openmates_sdk::work::CreatedProjectDocument;
use std::sync::Arc;

/// A Project file the core created.
#[derive(uniffi::Record)]
pub struct CreatedProjectDocumentRecord {
    /// The new embed id.
    pub embed_id: String,
    /// Embed type (`docs-doc`, `sheets-sheet`, `slides-deck`, `code-code`).
    pub embed_type: String,
    /// The Project item link id.
    pub project_item_id: String,
    /// Embed content as the JSON string the viewers decode.
    pub content_json: String,
}

impl From<CreatedProjectDocument> for CreatedProjectDocumentRecord {
    fn from(record: CreatedProjectDocument) -> Self {
        Self {
            embed_id: record.embed_id,
            embed_type: record.embed_type,
            project_item_id: record.project_item_id,
            content_json: record.content,
        }
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Create a new empty Project file of `kind` (`document`, `sheet`,
    /// `slides`, `code`) named `name` in `folder_id` (the Project root when
    /// `None`). `team_id` is the Team of a Team Project, `None` for Personal.
    /// Runs on the actor.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for an unknown kind or an
    /// empty name; `Forbidden`; `Offline`; `Cancelled`.
    pub async fn create_project_document(
        &self,
        project_id: String,
        team_id: Option<String>,
        kind: String,
        name: String,
        folder_id: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<CreatedProjectDocumentRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let record = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::create_project_document(
                        host, project_id, team_id, kind, name, folder_id, cancel,
                    )
                })
                .await?;
            Ok::<_, openmates_sdk::error::Error>(record.into())
        })
        .await
    }
}
