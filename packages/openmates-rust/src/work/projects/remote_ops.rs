//! Requester side of the write-class remote-access operations `run_command`,
//! `git_status`, `git_commit` and `git_land` (shared core; the CLI, TUI and
//! apps call these, never re-implement the digest or the envelope).
//!
//! Transport is the existing requester of `remote_files.rs` (`source_call`):
//! Project-key sealed envelope, authenticated handshake, relay polling. A
//! write-class call first stores the approval (`POST .../write-approvals`)
//! under the keyed proposal digest, then sends the request carrying chat id,
//! operation id and digest. The digest formulas mirror the host's
//! `source_host/commands.rs::digest` and `source_host/git_ops.rs::digest`.
//! spec: specifications/features/projects (chat worktrees), code-run remote.

use super::*;
use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::time::Duration;

const PROTOCOL_TIMEOUT: Duration = Duration::from_secs(45);
const COMMAND_DOMAIN: &str = "openmates-remote-command-proposal-v1";
const GIT_DOMAIN: &str = "openmates-remote-git-proposal-v1";
const CREATE_SOURCE_DOMAIN: &str = "openmates-remote-create-source-proposal-v1";

/// One approved-operation proposal; owns the exact digest and wire shape.
#[derive(Clone, Debug)]
pub(super) enum WriteProposal {
    Command {
        operation_id: String,
        argv: Vec<String>,
        cwd: String,
        timeout_ms: u64,
        max_output_bytes: Option<u64>,
    },
    Git {
        operation: &'static str,
        operation_id: String,
        message: Option<String>,
    },
    /// Create a new Project folder on the machine bound to a placeholder
    /// source (host `source_host/create_source.rs`).
    CreateSource {
        operation_id: String,
        project_name: String,
    },
}

/// One sealed relay call: operation, arguments, required source capability
/// and, for write-class operations, the chat and proposal to approve.
pub(super) struct WireCall {
    pub(super) name: &'static str,
    pub(super) arguments: Value,
    pub(super) capability: Option<&'static str>,
    /// Chat id sent beside the envelope (reads resolve the worktree from it).
    pub(super) chat: Option<String>,
    pub(super) write: Option<(String, WriteProposal)>,
}

impl WriteProposal {
    pub(super) fn operation_id(&self) -> &str {
        match self {
            Self::Command { operation_id, .. }
            | Self::Git { operation_id, .. }
            | Self::CreateSource { operation_id, .. } => operation_id,
        }
    }
    /// HMAC-SHA256(projectKey, JSON tuple), lower-case hex, byte-identical to
    /// the host's recomputation.
    ///
    /// # Errors
    /// `Invalid` for an empty project or chat id; `Crypto` for a bad key.
    pub(crate) fn digest(&self, key: &[u8; 32], project: &str, chat: &str) -> Result<String> {
        if project.is_empty() || chat.is_empty() {
            return Err(Error::Invalid("remote_operation_identity_incomplete"));
        }
        let tuple = match self {
            Self::Command {
                operation_id,
                argv,
                cwd,
                timeout_ms,
                max_output_bytes,
            } => json!([
                COMMAND_DOMAIN,
                project,
                chat,
                "run_command",
                operation_id,
                argv,
                cwd,
                timeout_ms,
                max_output_bytes
            ]),
            Self::Git {
                operation,
                operation_id,
                message,
            } => json!([GIT_DOMAIN, project, chat, operation, operation_id, message]),
            Self::CreateSource {
                operation_id,
                project_name,
            } => json!([
                CREATE_SOURCE_DOMAIN,
                project,
                chat,
                "create_source",
                operation_id,
                project_name
            ]),
        };
        let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key).map_err(|_| Error::Crypto)?;
        mac.update(tuple.to_string().as_bytes());
        Ok(mac
            .finalize()
            .into_bytes()
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect())
    }
    pub(super) fn arguments(&self, chat: &str) -> Value {
        match self {
            Self::CreateSource {
                operation_id,
                project_name,
            } => json!({"chat_id":chat,"create":{"operation_id":operation_id,"project_name":project_name}}),
            Self::Command {
                operation_id,
                argv,
                cwd,
                timeout_ms,
                max_output_bytes,
            } => {
                let mut command = json!({"operation_id":operation_id,"argv":argv,"cwd":cwd,"timeout_ms":timeout_ms});
                if let Some(bytes) = max_output_bytes {
                    command["max_output_bytes"] = json!(bytes);
                }
                json!({"chat_id":chat,"command":command})
            }
            Self::Git {
                operation_id,
                message,
                ..
            } => {
                let mut git = json!({"operation_id":operation_id});
                if let Some(message) = message {
                    git["message"] = json!(message);
                }
                json!({"chat_id":chat,"git":git})
            }
        }
    }
}

/// A command to run in the chat worktree (or the live source root when the
/// chat has none). `argv` is a program and arguments, never a shell string.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RemoteCommand {
    /// Program and arguments (1 to 128 entries, non-empty, no NUL).
    pub argv: Vec<String>,
    /// Root-relative working directory; `None` runs in the root (`.`).
    pub cwd: Option<String>,
    /// Wall-clock limit, 100 ms to 30 minutes (host range).
    pub timeout_ms: u64,
    /// Per-stream output cap in bytes (1 KiB to 96 KiB); `None`: host default.
    pub max_output_bytes: Option<u64>,
}

/// The host's `run_command` answer. `exit_code` is `None` when a signal ended
/// the command (always after a timeout).
#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct RemoteCommandResult {
    pub exit_code: Option<i32>,
    pub signal: Option<i32>,
    pub timed_out: bool,
    pub duration_ms: u64,
    pub stdout: String,
    pub stderr: String,
    pub stdout_truncated: bool,
    pub stderr_truncated: bool,
    /// Confinement tier that ran the command.
    pub sandbox: String,
    /// `"worktree"` or `"source"`.
    pub root: String,
    pub cwd: String,
}

/// One changed file of a worktree status (`status` is the porcelain code).
#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct GitChangedFile {
    pub path: String,
    pub status: String,
}

/// The host's `git_status` answer for the chat worktree.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct GitStatusResult {
    /// `false` (all other fields default) when the chat has no worktree yet.
    pub exists: bool,
    #[serde(default)]
    pub head: Option<String>,
    #[serde(default)]
    pub target_branch: Option<String>,
    #[serde(default)]
    pub ahead: u64,
    #[serde(default)]
    pub dirty: bool,
    #[serde(default)]
    pub landed: bool,
    #[serde(default)]
    pub changed_files: Vec<GitChangedFile>,
    #[serde(default)]
    pub truncated: bool,
}

/// The host's `git_commit` answer.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct GitCommitResult {
    pub commit: String,
    pub ahead: u64,
    pub target_branch: String,
}

/// Outcome of `git_land`. A rebase conflict is an answer, not an error: the
/// host aborted the rebase and the worktree is unchanged.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum GitLandOutcome {
    /// The target branch moved (`commits == 0` when already landed).
    Landed {
        landed: bool,
        commit: String,
        commits: u64,
        target_branch: String,
        checked_out: bool,
    },
    /// `code == "land_conflict"`; resolve in the worktree and retry.
    Conflict {
        landed: bool,
        code: String,
        conflicting_paths: Vec<String>,
    },
}

/// Stable host and relay codes of these operations.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RemoteOpCode {
    InvalidRequest,
    NoWorktree,
    ConfinementUnavailable,
    LaunchFailed,
    OperationFailed,
    NothingToCommit,
    IdentityMissing,
    WorktreeDirty,
    TargetBranchUnavailable,
    TargetCheckedOutDirty,
    LandFailed,
    WriteAuthorizationDenied,
    SourceCapabilityDenied,
    SourceOffline,
    ProtocolTimeout,
    SourceSessionChanged,
    SourceNotFound,
    SourceSelectionRequired,
    /// The machine has no new-Projects folder configured.
    CreationNotConfigured,
    /// The Project name cannot become a folder name.
    InvalidProjectName,
    /// The configured new-Projects folder is missing or not writable.
    CreationFolderUnavailable,
    /// A folder or file with the derived name already exists.
    TargetExists,
    /// The folder exists but the backend could not finish the source (the
    /// machine keeps the folder and retries completion on its next discovery).
    CreationCompletionFailed,
    /// A code this client does not know; the wire text is kept.
    Other(String),
}

impl RemoteOpCode {
    /// Map a wire code to its variant.
    pub fn from_wire(code: &str) -> Self {
        match code {
            "invalid_request" => Self::InvalidRequest,
            "no_worktree" => Self::NoWorktree,
            "confinement_unavailable" => Self::ConfinementUnavailable,
            "launch_failed" => Self::LaunchFailed,
            "operation_failed" => Self::OperationFailed,
            "nothing_to_commit" => Self::NothingToCommit,
            "identity_missing" => Self::IdentityMissing,
            "worktree_dirty" => Self::WorktreeDirty,
            "target_branch_unavailable" => Self::TargetBranchUnavailable,
            "target_checked_out_dirty" => Self::TargetCheckedOutDirty,
            "land_failed" => Self::LandFailed,
            "write_authorization_denied" => Self::WriteAuthorizationDenied,
            "source_capability_denied" => Self::SourceCapabilityDenied,
            "source_offline" => Self::SourceOffline,
            "protocol_timeout" => Self::ProtocolTimeout,
            "source_session_changed" => Self::SourceSessionChanged,
            "source_not_found" => Self::SourceNotFound,
            "source_selection_required" => Self::SourceSelectionRequired,
            "creation_not_configured" => Self::CreationNotConfigured,
            "invalid_project_name" => Self::InvalidProjectName,
            "creation_folder_unavailable" => Self::CreationFolderUnavailable,
            "target_exists" => Self::TargetExists,
            "creation_completion_failed" => Self::CreationCompletionFailed,
            other => Self::Other(other.to_owned()),
        }
    }
}

/// A typed failure of a remote command or Git operation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RemoteOpError {
    /// Transport, crypto, authentication or local validation failure.
    Core(Error),
    /// The host or relay refused with a stable code.
    Host { code: RemoteOpCode, message: String },
}

impl std::fmt::Display for RemoteOpError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Core(error) => std::fmt::Display::fmt(error, f),
            Self::Host { message, .. } => f.write_str(message),
        }
    }
}
impl std::error::Error for RemoteOpError {}
impl From<Error> for RemoteOpError {
    fn from(error: Error) -> Self {
        Self::Core(error)
    }
}
impl From<ProjectRequesterError> for RemoteOpError {
    fn from(error: ProjectRequesterError) -> Self {
        match error {
            ProjectRequesterError::Core(error) => Self::Core(error),
            ProjectRequesterError::Remote { code, message } => Self::Host {
                code: RemoteOpCode::from_wire(&code),
                message,
            },
        }
    }
}

fn check_operation_id(id: &str) -> Result<()> {
    let valid = (1..=128).contains(&id.len())
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b':' | b'-'));
    valid
        .then_some(())
        .ok_or(Error::Invalid("remote_operation_id_invalid"))
}

fn decode<T: serde::de::DeserializeOwned>(value: Value) -> std::result::Result<T, RemoteOpError> {
    serde_json::from_value(value).map_err(|_| RemoteOpError::Core(Error::Protocol))
}

impl Projects<'_> {
    async fn remote_op(
        &mut self,
        selector: &str,
        source: Option<&str>,
        call: WireCall,
    ) -> std::result::Result<Value, RemoteOpError> {
        let (_, _, result) = self
            .source_call(selector, source, call, PROTOCOL_TIMEOUT)
            .await?;
        Ok(result)
    }

    /// Run one confined command on a Project source for `chat_id`. Stores the
    /// single-use approval first; `operation_id` binds approval and request.
    ///
    /// # Errors
    /// [`RemoteOpError::Host`] with the stable host code (for example
    /// `confinement_unavailable`, `write_authorization_denied`);
    /// [`RemoteOpError::Core`] for transport or invalid local input.
    pub async fn run_remote_command(
        &mut self,
        selector: &str,
        source: Option<&str>,
        chat_id: &str,
        operation_id: &str,
        command: &RemoteCommand,
    ) -> std::result::Result<RemoteCommandResult, RemoteOpError> {
        check_operation_id(operation_id)?;
        if command.argv.is_empty() {
            return Err(Error::Invalid("remote_command_argv_required").into());
        }
        let proposal = WriteProposal::Command {
            operation_id: operation_id.to_owned(),
            argv: command.argv.clone(),
            cwd: command.cwd.clone().unwrap_or_else(|| ".".to_owned()),
            timeout_ms: command.timeout_ms,
            max_output_bytes: command.max_output_bytes,
        };
        let call = WireCall {
            name: "run_command",
            arguments: proposal.arguments(chat_id),
            capability: Some("run_command"),
            chat: Some(chat_id.to_owned()),
            write: Some((chat_id.to_owned(), proposal)),
        };
        decode(self.remote_op(selector, source, call).await?)
    }

    /// Read the chat worktree state (`git_status`, no approval). The chat id
    /// travels in the relay body, as the host resolves the worktree from it.
    ///
    /// # Errors
    /// `no_worktree` when the chat has no worktree; transport errors.
    pub async fn git_status(
        &mut self,
        selector: &str,
        source: Option<&str>,
        chat_id: &str,
    ) -> std::result::Result<GitStatusResult, RemoteOpError> {
        let call = WireCall {
            name: "git_status",
            arguments: json!({"chat_id":chat_id}),
            capability: None,
            chat: Some(chat_id.to_owned()),
            write: None,
        };
        decode(self.remote_op(selector, source, call).await?)
    }

    /// Commit every change of the chat worktree (`git_commit`, approved).
    ///
    /// # Errors
    /// `nothing_to_commit`, `identity_missing`, `no_worktree`, approval codes.
    pub async fn git_commit(
        &mut self,
        selector: &str,
        source: Option<&str>,
        chat_id: &str,
        operation_id: &str,
        message: &str,
    ) -> std::result::Result<GitCommitResult, RemoteOpError> {
        check_operation_id(operation_id)?;
        if message.trim().is_empty() {
            return Err(Error::Invalid("remote_git_message_required").into());
        }
        let proposal = WriteProposal::Git {
            operation: "git_commit",
            operation_id: operation_id.to_owned(),
            message: Some(message.to_owned()),
        };
        decode(
            self.remote_op(selector, source, git_call("git_commit", chat_id, proposal))
                .await?,
        )
    }

    /// Land the chat worktree on its target branch (`git_land`, approved). A
    /// rebase conflict returns [`GitLandOutcome::Conflict`], not an error.
    ///
    /// # Errors
    /// `worktree_dirty`, `target_branch_unavailable`,
    /// `target_checked_out_dirty`, `land_failed`, approval codes.
    pub async fn git_land(
        &mut self,
        selector: &str,
        source: Option<&str>,
        chat_id: &str,
        operation_id: &str,
    ) -> std::result::Result<GitLandOutcome, RemoteOpError> {
        check_operation_id(operation_id)?;
        let proposal = WriteProposal::Git {
            operation: "git_land",
            operation_id: operation_id.to_owned(),
            message: None,
        };
        decode(
            self.remote_op(selector, source, git_call("git_land", chat_id, proposal))
                .await?,
        )
    }
}

fn git_call(name: &'static str, chat_id: &str, proposal: WriteProposal) -> WireCall {
    WireCall {
        name,
        arguments: proposal.arguments(chat_id),
        capability: None,
        chat: Some(chat_id.to_owned()),
        write: Some((chat_id.to_owned(), proposal)),
    }
}

#[cfg(test)]
#[path = "remote_ops_tests.rs"]
mod tests;
