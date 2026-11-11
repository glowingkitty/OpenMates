//! Adopt an existing chat embed into a Project (shared core, P11):
//! `POST /v1/projects/{project_id}/items/adopt-embed`. The embed keeps its
//! chat-key wrapper; the client adds a Project-key wrapper of the SAME embed
//! key and a client-encrypted `project_items` link, so every Project member
//! can read it. Contract:
//! `docs/plans/cloud-project-development/contracts/project-embed-adoption.md`.
use super::adopt_plan::{self, TurnEmbed};
use super::job::seal;
use super::*;

/// Kind of a Project link created by adoption (contract `kind`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AdoptEmbedKind {
    /// A code embed linked as a Project file.
    File,
    /// An application embed linked as its Project folder.
    Application,
    /// A test-result embed linked to the Project.
    TestResult,
}

impl AdoptEmbedKind {
    /// Wire value of the kind.
    pub fn wire(self) -> &'static str {
        match self {
            Self::File => "file",
            Self::Application => "application",
            Self::TestResult => "test_result",
        }
    }

    /// The kind an embed type adopts as (`None` for other embed types).
    pub(crate) fn of_embed_type(embed_type: &str) -> Option<Self> {
        match embed_type {
            "code" | "code-code" => Some(Self::File),
            "application" | "code-application" | "app-application" => Some(Self::Application),
            "test_result" | "code-test-result" => Some(Self::TestResult),
            _ => None,
        }
    }
}

/// Why an adoption did not happen. The server variants carry the contract's
/// stable codes; `Refused` is a client-side refusal with its own stable code.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ProjectEmbedAdoptError {
    /// `project_not_found`.
    ProjectNotFound,
    /// `forbidden`: the caller may not write the Project or own the embed.
    Forbidden,
    /// `embed_not_found`.
    EmbedNotFound,
    /// `embed_already_linked`: the embed has a link with another item id.
    EmbedAlreadyLinked,
    /// `path_conflict`: the Project path is linked to another embed.
    PathConflict,
    /// `invalid_request`.
    InvalidRequest,
    /// A client refusal (`invalid_path`, `path_required`,
    /// `unsupported_embed_kind`, `embed_key_unavailable`, …).
    Refused(&'static str),
    /// A transport, crypto or authorization failure of the core.
    Core(Error),
}

impl ProjectEmbedAdoptError {
    /// The server error of one stable contract code.
    pub(crate) fn from_code(code: &str) -> Option<Self> {
        Some(match code {
            "project_not_found" => Self::ProjectNotFound,
            "forbidden" => Self::Forbidden,
            "embed_not_found" => Self::EmbedNotFound,
            "embed_already_linked" => Self::EmbedAlreadyLinked,
            "path_conflict" => Self::PathConflict,
            "invalid_request" => Self::InvalidRequest,
            _ => return None,
        })
    }

    /// The stable code (contract codes for server refusals).
    pub fn code(&self) -> &str {
        match self {
            Self::ProjectNotFound => "project_not_found",
            Self::Forbidden => "forbidden",
            Self::EmbedNotFound => "embed_not_found",
            Self::EmbedAlreadyLinked => "embed_already_linked",
            Self::PathConflict => "path_conflict",
            Self::InvalidRequest => "invalid_request",
            Self::Refused(code) => code,
            Self::Core(Error::Cancelled) => "cancelled",
            Self::Core(Error::Offline) => "protocol_timeout",
            Self::Core(Error::Forbidden) => "forbidden",
            Self::Core(_) => "client_execution_failed",
        }
    }
}

impl From<HostedFileError> for ProjectEmbedAdoptError {
    fn from(error: HostedFileError) -> Self {
        match error {
            HostedFileError::Core(error) => Self::Core(error),
            HostedFileError::Refused(code) => Self::Refused(code),
            // Server codes outside the typed contract set (`operation_payload_mismatch`,
            // `project_item_not_found`, `embed_key_ambiguous`) keep their stable code.
            HostedFileError::Rejected(code) => Self::from_code(&code).unwrap_or_else(|| {
                Self::Refused(
                    crate::client::project_item_error::known_code(&code)
                        .unwrap_or("adopt_rejected"),
                )
            }),
        }
    }
}

impl From<Error> for ProjectEmbedAdoptError {
    fn from(error: Error) -> Self {
        Self::Core(error)
    }
}

/// One planned adoption: what to link and the plaintext the client encrypts.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct AdoptionTarget {
    pub(crate) chat_id: String,
    pub(crate) embed_id: String,
    pub(crate) kind: AdoptEmbedKind,
    /// Normalized Project path: the file path, or the application folder.
    pub(crate) path: Option<String>,
    pub(crate) display_name: String,
    /// Metadata plaintext (contract "Metadata plaintext by kind").
    pub(crate) metadata: Value,
}

/// The link id of an adoption. A file's id is the hosted-file item identity
/// of its path (so the hosted writer addresses it like a created file); an
/// application or test result is keyed by its embed, since it has no file path.
///
/// # Errors
/// The hosted path refusals for a file path.
pub(crate) fn project_item_id(
    project_key: &[u8; 32],
    target: &AdoptionTarget,
) -> HostedResult<String> {
    match (target.kind, &target.path) {
        (AdoptEmbedKind::File, Some(path)) => {
            hosted_file_identity(project_key, path, HostedIdentityKind::Item)
        }
        (AdoptEmbedKind::File, None) => refused("path_required"),
        (kind, _) => keyed_uuid(
            project_key,
            &json!([
                "openmates-project-embed-link-v1",
                kind.wire(),
                target.embed_id
            ]),
        ),
    }
}

/// Idempotency key of an adoption: keyed by the Project key over (Project,
/// embed, path), so a retry of the same adoption replays the first result and
/// the server never learns the path from the id.
///
/// # Errors
/// Only a construction failure of [`keyed_uuid`].
pub(crate) fn operation_id(
    project_key: &[u8; 32],
    project_id: &str,
    target: &AdoptionTarget,
) -> HostedResult<String> {
    keyed_uuid(
        project_key,
        &json!([
            "openmates-adopt-embed-v1",
            project_id,
            target.embed_id,
            target.path.as_deref().unwrap_or_default()
        ]),
    )
}

/// The `adopt-embed` request body. Every Project-visible field is sealed with
/// the Project key; `project_key_wrapper` wraps the embed's existing key (the
/// wrapper format of a created hosted file's `project` wrapper).
///
/// # Errors
/// Path refusals and encryption failures.
pub(crate) fn adoption_body(
    project_key: &[u8; 32],
    project_id: &str,
    team_id: Option<&str>,
    target: &AdoptionTarget,
    embed_key: &[u8; 32],
) -> HostedResult<Value> {
    let metadata = serde_json::to_string(&target.metadata).map_err(Error::from)?;
    let mut body = json!({
        "operation_id": operation_id(project_key, project_id, target)?,
        "chat_id": target.chat_id,
        "embed_id": target.embed_id,
        "project_item_id": project_item_id(project_key, target)?,
        "kind": target.kind.wire(),
        "target_id_encrypted": seal(&target.embed_id, project_key)?,
        "encrypted_display_name": seal(&target.display_name, project_key)?,
        "encrypted_metadata": seal(&metadata, project_key)?,
        "project_key_wrapper": crypto::server_fields::encrypt_bytes(embed_key, project_key, &[])?,
    });
    if let Some(team) = team_id {
        body["team_id"] = json!(team);
    }
    Ok(body)
}

/// The embed key of a turn row: the key of its root ancestor among the turn's
/// rows, derived from the chat key exactly as `persist_stream_artifacts` does.
///
/// # Errors
/// `embed_key_unavailable` when the parent chain leaves the turn or loops.
pub(crate) fn turn_embed_key(
    embeds: &[TurnEmbed],
    embed_id: &str,
    chat_key: &[u8; 32],
) -> HostedResult<Key> {
    let mut current = embed_id;
    for _ in 0..8 {
        let row = embeds
            .iter()
            .find(|e| e.embed_id == current)
            .ok_or(HostedFileError::Refused("embed_key_unavailable"))?;
        match row.parent_embed_id.as_deref() {
            Some(parent) => current = parent,
            None => return Ok(crypto::derive_embed_key(chat_key, current)?),
        }
    }
    refused("embed_key_unavailable")
}

fn report(
    target: &AdoptionTarget,
    outcome: &std::result::Result<Value, ProjectEmbedAdoptError>,
) -> Value {
    let mut row =
        json!({"embed_id": target.embed_id, "kind": target.kind.wire(), "path": target.path});
    match outcome {
        Ok(_) => row["status"] = json!("adopted"),
        Err(error) => {
            row["status"] = json!("failed");
            row["code"] = json!(error.code());
        }
    }
    row
}

impl Projects<'_> {
    /// Send one adoption for an already resolved Project.
    ///
    /// # Errors
    /// The contract codes as typed variants, client refusals and core errors.
    pub(crate) async fn adopt_resolved(
        &mut self,
        project_id: &str,
        project_key: &[u8; 32],
        target: &AdoptionTarget,
        embed_key: &[u8; 32],
    ) -> std::result::Result<Value, ProjectEmbedAdoptError> {
        uuid(&target.chat_id)?;
        uuid(&target.embed_id)?;
        let team = self.filters.team_id.clone();
        let body = adoption_body(project_key, project_id, team.as_deref(), target, embed_key)?;
        let route = self.path(&format!("/v1/projects/{project_id}/items/adopt-embed"), &[]);
        let response = self.item_link_request(Method::POST, &route, body).await?;
        Ok(
            json!({"project_id": project_id, "embed_id": target.embed_id, "kind": target.kind.wire(),
            "path": target.path, "project_item_id": project_item_id(project_key, target)?,
            "result": response}),
        )
    }

    /// Adopt the application, file and test-result embeds of one finished turn
    /// of `chat_id` into the chat's focused Project and return one report row
    /// per planned adoption (`status` `adopted`/`failed`, `code`). Failures
    /// never stop the following adoptions; only cancellation propagates.
    ///
    /// # Errors
    /// Cancellation, and failures to resolve the Project or its listing.
    pub(crate) async fn adopt_turn(
        &mut self,
        project_id: &str,
        chat_id: &str,
        chat_key: &[u8; 32],
        embeds: &[TurnEmbed],
    ) -> std::result::Result<Vec<Value>, ProjectEmbedAdoptError> {
        let (project_id, key, _) = self.hosted_project(project_id).await?;
        let route = self.path(&format!("/v1/projects/{project_id}"), &[]);
        let listing = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        if listing["project"]["project_id"] != project_id.as_str() {
            return Err(ProjectEmbedAdoptError::Core(Error::Forbidden));
        }
        let existing = adopt_plan::application_folders(&listing["items"], &key)?;
        let mut rows = Vec::new();
        for planned in adopt_plan::plan_turn(chat_id, embeds, &existing) {
            let target = match planned {
                Ok(target) => target,
                Err(error) => {
                    rows.push(json!({"status": "failed", "code": ProjectEmbedAdoptError::from(error).code()}));
                    continue;
                }
            };
            let outcome = match turn_embed_key(embeds, &target.embed_id, chat_key) {
                Ok(embed_key) => {
                    self.adopt_resolved(&project_id, &key, &target, &embed_key)
                        .await
                }
                Err(error) => Err(error.into()),
            };
            if matches!(outcome, Err(ProjectEmbedAdoptError::Core(Error::Cancelled))) {
                return Err(ProjectEmbedAdoptError::Core(Error::Cancelled));
            }
            rows.push(report(&target, &outcome));
        }
        Ok(rows)
    }

    /// Explicit repair: adopt one existing embed of `chat_id` into a Project.
    /// The kind follows the embed's type (code file, application, test
    /// result). `path` is the full Project file path for a file and the folder
    /// for an application; a test result needs none. Idempotent: the same
    /// (Project, embed, path) replays the first result.
    ///
    /// # Errors
    /// `path_required`, `unsupported_embed_kind`, the hosted path refusals,
    /// the contract codes and core errors (cookie sessions only).
    pub async fn adopt_embed(
        &mut self,
        selector: &str,
        chat_id: &str,
        embed_id: &str,
        path: Option<&str>,
    ) -> std::result::Result<Value, ProjectEmbedAdoptError> {
        uuid(chat_id)?;
        uuid(embed_id)?;
        let (project_id, key, _) = self.hosted_project(selector).await?;
        let (embed_key, embed_type, content) = self
            .hosted_client()?
            .adoption_embed_source(chat_id, embed_id)
            .await?;
        let kind = AdoptEmbedKind::of_embed_type(&embed_type)
            .ok_or(ProjectEmbedAdoptError::Refused("unsupported_embed_kind"))?;
        let record = TurnEmbed::from_row(embed_id, &json!({"type": embed_type}), &content);
        let target = adopt_plan::repair_target(chat_id, &record, kind, path)?;
        self.adopt_resolved(&project_id, &key, &target, &embed_key)
            .await
    }
}
