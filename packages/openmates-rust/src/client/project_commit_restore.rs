//! User (GUI) restore of a whole Project commit, without a chat (shared core;
//! spec `projects.history.native-commits`, `projects.files.rename-delete`).
//!
//! Every changed file is rebuilt from its committed encrypted history rows and
//! written as a new revision through the Project-scope user-revision route
//! (`RevisionScope::Project`, action `restore`), so it is attributed to the
//! user. A file whose link was deleted after the commit is relinked at its
//! committed path first (the `adopt-embed` operation). The restore is recorded
//! as a new commit (author user, `restored_from`). History is never rewritten.
//! The commit/file orchestration is generic over [`RestoreIo`] so it is tested
//! without a network; [`ClientRestoreIo`] is the real implementation.
use super::Client;
use super::embed_user_revision::restore::restore_request;
use super::embed_user_revision::{RevisionScope, UserRevisionError};
use crate::crypto;
use crate::error::{Error, Result};
use crate::work::{
    ProjectCommit, ProjectCommitAuthor, ProjectCommitCreate, ProjectCommitFile, ProjectFilters,
    ReplayError,
};
use serde::{Deserialize, Serialize};
use zeroize::Zeroizing;

/// What happened to one file of the restored commit.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "outcome", rename_all = "snake_case")]
pub enum ProjectCommitFileOutcome {
    /// Written as a new user revision; `version` is the new head.
    Restored { version: u64 },
    /// The head already was the committed version; nothing written.
    Unchanged,
    /// The deleted link was recreated at the committed path; `version` is the
    /// head afterwards (a new revision when the content differed).
    Relinked { version: u64 },
    /// Not restored; `reason` is a stable code (`path_conflict`,
    /// `embed_missing`, `path_missing`, `embed_chat_unavailable`, or the
    /// revision route's refusal code). Other files continue.
    Refused { reason: String },
}

/// Per-file result row of a user restore.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProjectCommitFileRestore {
    /// Committed Project path, when the commit carried one.
    pub path: Option<String>,
    /// Hashed Project item id the commit stores for the file.
    pub target_id_hash: String,
    /// What the restore did with it.
    #[serde(flatten)]
    pub outcome: ProjectCommitFileOutcome,
}

/// Result of [`Client::restore_project_commit`].
#[derive(Clone, Serialize)]
pub struct ProjectCommitUserRestore {
    /// The commit that was restored.
    pub source_commit_id: String,
    /// One row per file of the source commit.
    pub files: Vec<ProjectCommitFileRestore>,
    /// The new commit; lists only restored, relinked and unchanged files.
    pub commit: ProjectCommit,
}

/// A failed step of one file: `Refused` skips the file, `Fatal` aborts.
pub(crate) enum StepError {
    /// Deterministic refusal with a stable code; the next file continues.
    Refused(String),
    /// Transport, crypto or session failure; nothing further is attempted.
    Fatal(Error),
}

impl From<Error> for StepError {
    fn from(error: Error) -> Self {
        Self::Fatal(error)
    }
}

impl From<UserRevisionError> for StepError {
    fn from(error: UserRevisionError) -> Self {
        match error {
            UserRevisionError::Transport(error) => Self::Fatal(error),
            other => Self::Refused(other.code().to_owned()),
        }
    }
}

impl From<ReplayError> for StepError {
    fn from(error: ReplayError) -> Self {
        match error {
            ReplayError::Core(error) => Self::Fatal(error),
            ReplayError::InvalidPatch => Self::Refused("invalid_patch".to_owned()),
        }
    }
}

/// The IO the restore needs; see [`ClientRestoreIo`].
pub(crate) trait RestoreIo {
    /// Plan, commit message and current links of the commit.
    async fn inputs(&mut self, commit_id: &str) -> Result<crate::work::UserRestoreInputs>;
    /// The embed id whose hash is `target_id_hash`, when this client knows it.
    fn resolve_embed(&self, target_id_hash: &str) -> Option<String>;
    /// Recreate the Project link of `embed_id` at `path`.
    async fn relink(&mut self, embed_id: &str, path: &str) -> std::result::Result<(), StepError>;
    /// Write committed `version` of `embed_id` as the new head; returns it.
    async fn write_version(
        &mut self,
        embed_id: &str,
        version: u64,
    ) -> std::result::Result<u64, StepError>;
    /// Current head version of a linked embed.
    async fn head_version(&mut self, embed_id: &str) -> Result<u64>;
    /// Record the restore commit.
    async fn record(&mut self, source: &str, input: ProjectCommitCreate) -> Result<ProjectCommit>;
}

fn refuse(path: Option<String>, hash: String, reason: &str) -> ProjectCommitFileRestore {
    ProjectCommitFileRestore {
        path,
        target_id_hash: hash,
        outcome: ProjectCommitFileOutcome::Refused {
            reason: reason.to_owned(),
        },
    }
}

/// Refusal codes a restore can surface as the error code when no file was
/// restored; anything else becomes `restore_refused`.
const SURFACED_REFUSALS: &[&str] = &[
    "path_conflict",
    "path_missing",
    "embed_missing",
    "embed_chat_unavailable",
    "key_unavailable",
    "invalid_patch",
];

/// Error of a restore that wrote nothing. The first file's refusal code is
/// kept (as `Unavailable.code`) so a shell can say why instead of a bare
/// "could not restore"; a commit without file rows stays `Invalid`.
fn nothing_restored(rows: &[ProjectCommitFileRestore]) -> Error {
    let first = rows.iter().find_map(|row| match &row.outcome {
        ProjectCommitFileOutcome::Refused { reason } => Some(reason.as_str()),
        _ => None,
    });
    match first {
        Some(reason) => Error::Unavailable {
            code: SURFACED_REFUSALS
                .iter()
                .find(|code| **code == reason)
                .copied()
                .unwrap_or("restore_refused"),
            reason: "PROJECT_COMMIT_NOTHING_RESTORED",
        },
        None => Error::Invalid("No file of this commit could be restored."),
    }
}

/// Restore every file of `commit_id` through `io` (see module docs).
///
/// # Errors
/// Fatal IO errors, and [`nothing_restored`] when no file could be restored
/// (nothing to record). Files written before a fatal error stay as ordinary new
/// revisions; rerunning converges because unchanged files are skipped.
pub(crate) async fn run_restore<I: RestoreIo>(
    io: &mut I,
    commit_id: &str,
    message: Option<String>,
    commit_uuid: Option<String>,
) -> Result<ProjectCommitUserRestore> {
    let inputs = io.inputs(commit_id).await?;
    let mut linked = inputs.linked.clone();
    let mut rows = Vec::with_capacity(inputs.plan.files.len());
    let mut entries: Vec<ProjectCommitFile> = Vec::new();
    for file in &inputs.plan.files {
        let hash = file.target_id_hash.clone();
        let (embed, path, relinked) = match &file.target_id {
            Some(embed) => {
                let path = linked
                    .iter()
                    .find(|(target, _)| target == embed)
                    .map(|(_, path)| path.clone())
                    .or_else(|| file.path.clone());
                let Some(path) = path else {
                    rows.push(refuse(None, hash, "path_missing"));
                    continue;
                };
                (embed.clone(), path, false)
            }
            None => {
                let Some(path) = file.path.clone() else {
                    rows.push(refuse(None, hash, "path_missing"));
                    continue;
                };
                // The committed path is taken by another file: never replace it.
                if linked.iter().any(|(_, taken)| *taken == path) {
                    rows.push(refuse(Some(path), hash, "path_conflict"));
                    continue;
                }
                // Manifest v2 commits carry the embed id; older ones fall back
                // to the embeds this client has cached.
                let Some(embed) = file
                    .committed_target_id
                    .clone()
                    .or_else(|| io.resolve_embed(&hash))
                else {
                    rows.push(refuse(Some(path), hash, "embed_missing"));
                    continue;
                };
                match io.relink(&embed, &path).await {
                    Ok(()) => linked.push((embed.clone(), path.clone())),
                    Err(StepError::Refused(reason)) => {
                        rows.push(refuse(Some(path), hash, &reason));
                        continue;
                    }
                    Err(StepError::Fatal(error)) => return Err(error),
                }
                (embed, path, true)
            }
        };
        let current = match (&file.target_id, file.unchanged) {
            (Some(_), true) => Some(file.current_version.unwrap_or(file.restore_version)),
            (Some(_), false) => None,
            (None, _) => {
                let head = io.head_version(&embed).await?;
                (head == file.restore_version).then_some(head)
            }
        };
        let (version, outcome) = match current {
            Some(version) if !relinked => (version, ProjectCommitFileOutcome::Unchanged),
            Some(version) => (version, ProjectCommitFileOutcome::Relinked { version }),
            None => match io.write_version(&embed, file.restore_version).await {
                Ok(version) if relinked => {
                    (version, ProjectCommitFileOutcome::Relinked { version })
                }
                Ok(version) => (version, ProjectCommitFileOutcome::Restored { version }),
                Err(StepError::Refused(reason)) => {
                    rows.push(refuse(Some(path), hash, &reason));
                    continue;
                }
                Err(StepError::Fatal(error)) => return Err(error),
            },
        };
        entries.push(ProjectCommitFile {
            target_id: embed,
            path: path.clone(),
            embed_version: version,
        });
        rows.push(ProjectCommitFileRestore {
            path: Some(path),
            target_id_hash: hash,
            outcome,
        });
    }
    if entries.is_empty() {
        return Err(nothing_restored(&rows));
    }
    let input = ProjectCommitCreate {
        message: message.unwrap_or_else(|| format!("Restore \"{}\"", inputs.message)),
        author: ProjectCommitAuthor::User,
        chat_id: None,
        files: entries,
        commit_id: commit_uuid,
        created_at: None,
    };
    let commit = io.record(commit_id, input).await?;
    Ok(ProjectCommitUserRestore {
        source_commit_id: commit_id.to_owned(),
        files: rows,
        commit,
    })
}

/// Project filters of a restore: Personal, or the given Team.
pub(crate) fn restore_filters(team_id: Option<&str>) -> ProjectFilters {
    ProjectFilters {
        personal: team_id.is_none(),
        team_id: team_id.map(str::to_owned),
        include_archived: None,
    }
}

/// The user-revision scope of a Project file write.
pub(crate) fn restore_scope(project_id: &str, team_id: Option<&str>) -> RevisionScope {
    RevisionScope::Project {
        project_id: project_id.to_owned(),
        team_id: team_id.map(str::to_owned),
    }
}

/// A stable UUID derived from the caller's `operation_id` and a label, so one
/// operation id makes every request of the restore idempotent.
pub(crate) fn derived_uuid(operation_id: &str, label: &str) -> String {
    use sha2::{Digest, Sha256};
    let digest = Sha256::digest(format!(
        "openmates-commit-restore-v1|{operation_id}|{label}"
    ));
    let mut bytes = [0u8; 16];
    bytes.copy_from_slice(&digest[..16]);
    uuid::Builder::from_random_bytes(bytes)
        .into_uuid()
        .to_string()
}

/// Real IO: the Project reads/relink through `Projects`, the writes through
/// the user-revision route.
struct ClientRestoreIo<'a> {
    client: &'a mut Client,
    project_id: String,
    team_id: Option<String>,
    operation_id: Option<String>,
}

impl ClientRestoreIo<'_> {
    fn projects(&mut self) -> crate::work::Projects<'_> {
        let filters = restore_filters(self.team_id.as_deref());
        self.client.projects().with_filters(filters)
    }
}

impl RestoreIo for ClientRestoreIo<'_> {
    async fn inputs(&mut self, commit_id: &str) -> Result<crate::work::UserRestoreInputs> {
        let selector = self.project_id.clone();
        let inputs = self
            .projects()
            .user_restore_inputs(&selector, commit_id)
            .await?;
        self.project_id = inputs.project_id.clone();
        Ok(inputs)
    }

    fn resolve_embed(&self, target_id_hash: &str) -> Option<String> {
        // The commit stores only hashed ids: match against embeds this client knows.
        self.client
            .embeds
            .keys()
            .find(|id| crate::work::hash(id) == target_id_hash)
            .cloned()
    }

    async fn relink(&mut self, embed_id: &str, path: &str) -> std::result::Result<(), StepError> {
        let head = self.client.embed_user_edit_head(embed_id).await;
        let chat = match head {
            Ok((_, chat)) => chat,
            Err(UserRevisionError::Transport(
                Error::Forbidden | Error::Protocol | Error::Invalid(_),
            )) => return Err(StepError::Refused("embed_missing".into())),
            Err(error) => return Err(error.into()),
        };
        let Some(chat) = chat else {
            return Err(StepError::Refused("embed_chat_unavailable".into()));
        };
        use crate::work::ProjectEmbedAdoptError;
        let project = self.project_id.clone();
        let adopted = self
            .projects()
            .adopt_embed(&project, &chat, embed_id, Some(path))
            .await;
        match adopted {
            Ok(_) => Ok(()),
            Err(ProjectEmbedAdoptError::Core(error)) => Err(StepError::Fatal(error)),
            Err(ProjectEmbedAdoptError::Refused(code)) => Err(StepError::Refused(code.into())),
            Err(other) => Err(StepError::Refused(other.code().into())),
        }
    }

    async fn write_version(
        &mut self,
        embed_id: &str,
        version: u64,
    ) -> std::result::Result<u64, StepError> {
        // The head row only: its key is opened below, so the browser's
        // master/chat key check of `embed_user_edit_head` must not refuse first.
        let (head, _) = self.client.project_file_edit_head(embed_id).await?;
        let project = self.project_id.clone();
        // The Project wrapper first: a browser session opens it with the
        // Project key and needs no cached chat; an older link without one
        // falls back to the master/chat/parent wrappers.
        let key = match self.projects().project_embed_key(&project, embed_id).await {
            Ok(Some(key)) => key,
            Ok(None) | Err(Error::Crypto) => self
                .client
                .edit_embed_key(embed_id)
                .await
                .map_err(|_| StepError::Refused("key_unavailable".into()))?,
            Err(error) => return Err(StepError::Fatal(error)),
        };
        let rows = self
            .projects()
            .version_rows(&project, embed_id, version)
            .await?;
        // History rows of a hosted file hold its text, while the head holds
        // the code object; the new head is that object around the old text,
        // and the history keeps texts so later hosted patches still apply.
        let team = self.team_id.as_deref();
        let text = crate::work::version_text(
            self.client
                .replay_stored_revision_history(team, embed_id, &rows, &key, version)
                .await?,
        );
        let framed_head = match team {
            Some(team) => {
                self.client
                    .open_team_revision_content(
                        team,
                        embed_id,
                        head.version,
                        &head.encrypted_content,
                    )
                    .await?
            }
            None => None,
        };
        let head_plain = match framed_head {
            Some(plain) => plain,
            None => Zeroizing::new(
                crypto::server_fields::decrypt_text(&head.encrypted_content, &key, &[])
                    .map_err(|_| StepError::Refused("key_unavailable".into()))?,
            ),
        };
        let next = u64::try_from(head.version + 1).map_err(|_| Error::Protocol)?;
        let content = crate::work::content_with_text(&head_plain, &text, next)
            .map_err(|_| StepError::Refused("unsupported_file_content".into()))?;
        let cipher = match team {
            Some(team) => {
                self.client
                    .team_revision_cipher(team, embed_id, None)
                    .await?
            }
            None => None,
        };
        let from = i64::try_from(version).map_err(|_| Error::Protocol)?;
        let scope = restore_scope(&self.project_id, self.team_id.as_deref());
        let mut request = restore_request(head, scope, from, content)?;
        if cipher.is_none() {
            request.history_text = Some((crate::work::version_text(head_plain), text));
        }
        request.operation_id = self
            .operation_id
            .as_deref()
            .map(|operation| derived_uuid(operation, embed_id));
        let outcome = self
            .client
            .commit_embed_user_revision_with_cipher(request, None, key, cipher)
            .await?;
        u64::try_from(outcome.commit.committed.version)
            .map_err(|_| StepError::Fatal(Error::Protocol))
    }

    async fn head_version(&mut self, embed_id: &str) -> Result<u64> {
        let project = self.project_id.clone();
        self.projects()
            .user_restore_head_version(&project, embed_id)
            .await
    }

    async fn record(&mut self, source: &str, input: ProjectCommitCreate) -> Result<ProjectCommit> {
        let project = self.project_id.clone();
        self.projects()
            .record_commit_restore(&project, source, input)
            .await
    }
}

impl Client {
    /// Restore a whole Project commit as the signed-in user, no chat needed.
    /// Changed files become new Project-scope user revisions (attributed to
    /// the user), files unlinked after the commit are relinked at their
    /// committed path, unchanged files are skipped, and a new commit with
    /// `restored_from = commit_id` (author user, default message
    /// `Restore "<original message>"`) lists the restored, relinked and
    /// unchanged files. A file whose path is taken, or whose embed is unknown
    /// to this client, is reported `Refused` and the others continue.
    /// `operation_id` (a UUID) makes the writes and the new commit idempotent.
    /// `team_id` is the Team of a Team Project.
    ///
    /// # Errors
    /// Cookie sessions only; transport, crypto and session failures;
    /// `Unavailable` with the first file's refusal code (`embed_missing`,
    /// `key_unavailable`, ..., else `restore_refused`) when no file could be
    /// restored, `Invalid` for a commit without files.
    pub async fn restore_project_commit(
        &mut self,
        project_id: &str,
        team_id: Option<&str>,
        commit_id: &str,
        message: Option<String>,
        operation_id: Option<String>,
    ) -> Result<ProjectCommitUserRestore> {
        let commit_uuid = operation_id
            .as_deref()
            .map(|operation| derived_uuid(operation, "commit"));
        let mut io = ClientRestoreIo {
            client: self,
            project_id: project_id.to_owned(),
            team_id: team_id.map(str::to_owned),
            operation_id,
        };
        run_restore(&mut io, commit_id, message, commit_uuid).await
    }
}

#[cfg(test)]
#[path = "project_commit_restore_tests.rs"]
mod tests;
