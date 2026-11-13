//! Project agentic-coding operations on `ViewModelCore`: undo the Project an
//! assistant turn created, run a confined command on a Project source, and
//! read, commit or land the chat worktree. Bindings only marshal over
//! `openmates_sdk::view_model::project_ops`; a refusal of the source host
//! with a stable code is a `Refused` outcome, other failures are `CoreError`.
//! Plan TASK-1089 (Apple agentic coding parity); spec `client-core`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use openmates_sdk::view_model::{self, RemoteRefusal};
use openmates_sdk::work::{
    CreatedProjectRecord as CoreCreated, GitChangedFile, GitCommitResult, GitLandOutcome,
    GitStatusResult, RemoteCommand, RemoteCommandResult,
};
use std::sync::Arc;

/// The Project an assistant turn created for a chat.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct CreatedProjectRecord {
    /// Request that produced the Project.
    pub request_id: String,
    /// Chat the Project was created for.
    pub chat_id: String,
    /// New Project id.
    pub project_id: String,
    /// Default focus id that was activated.
    pub focus_id: String,
    /// Decrypted Project name.
    pub name: String,
    /// `web_app` or `native_app`.
    pub kind: String,
    /// Folder the application's files go to.
    pub subfolder: String,
    /// Team of the Project, nil for a personal Project.
    pub team_id: Option<String>,
    /// True while the Project exists and can be undone.
    pub undo_available: bool,
}

impl From<CoreCreated> for CreatedProjectRecord {
    fn from(record: CoreCreated) -> Self {
        Self {
            request_id: record.request_id,
            chat_id: record.chat_id,
            project_id: record.project_id,
            focus_id: record.focus_id,
            name: record.name,
            kind: record.kind,
            subfolder: record.subfolder,
            team_id: record.team_id,
            undo_available: record.undo_available,
        }
    }
}

/// A refusal of the Project source host or relay.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct RemoteRefusalRecord {
    /// Stable wire code (`no_worktree`, `nothing_to_commit`,
    /// `write_authorization_denied`, ...).
    pub code: String,
    /// English reason from the host.
    pub message: String,
}

impl From<RemoteRefusal> for RemoteRefusalRecord {
    fn from(refusal: RemoteRefusal) -> Self {
        Self {
            code: refusal.code,
            message: refusal.message,
        }
    }
}

/// A command to run on a Project source: a program and arguments, never a
/// shell string.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct RemoteCommandRecord {
    /// Program and arguments (1 to 128 entries).
    pub argv: Vec<String>,
    /// Root-relative working directory; nil runs in the root.
    #[uniffi(default = None)]
    pub cwd: Option<String>,
    /// Wall-clock limit in milliseconds (100 ms to 30 minutes).
    pub timeout_ms: u64,
    /// Per-stream output cap in bytes (1 KiB to 96 KiB); nil: host default.
    #[uniffi(default = None)]
    pub max_output_bytes: Option<u64>,
}

impl From<RemoteCommandRecord> for RemoteCommand {
    fn from(record: RemoteCommandRecord) -> Self {
        Self {
            argv: record.argv,
            cwd: record.cwd,
            timeout_ms: record.timeout_ms,
            max_output_bytes: record.max_output_bytes,
        }
    }
}

/// The host's answer to a remote command.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct RemoteCommandResultRecord {
    /// Exit code; nil when a signal ended the command.
    pub exit_code: Option<i32>,
    /// Terminating signal, if any.
    pub signal: Option<i32>,
    /// The time limit ended the command.
    pub timed_out: bool,
    /// Wall-clock duration in milliseconds.
    pub duration_ms: u64,
    /// Captured standard output.
    pub stdout: String,
    /// Captured standard error.
    pub stderr: String,
    /// Standard output was cut at the cap.
    pub stdout_truncated: bool,
    /// Standard error was cut at the cap.
    pub stderr_truncated: bool,
    /// The confinement the host used.
    pub sandbox: String,
    /// The root the command ran under.
    pub root: String,
    /// The working directory the command ran in.
    pub cwd: String,
}

impl From<RemoteCommandResult> for RemoteCommandResultRecord {
    fn from(result: RemoteCommandResult) -> Self {
        Self {
            exit_code: result.exit_code,
            signal: result.signal,
            timed_out: result.timed_out,
            duration_ms: result.duration_ms,
            stdout: result.stdout,
            stderr: result.stderr,
            stdout_truncated: result.stdout_truncated,
            stderr_truncated: result.stderr_truncated,
            sandbox: result.sandbox,
            root: result.root,
            cwd: result.cwd,
        }
    }
}

/// Outcome of a remote command.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum RemoteCommandOutcomeRecord {
    /// The command ran (any exit code).
    Done {
        /// The host's answer.
        result: RemoteCommandResultRecord,
    },
    /// The host refused to run it.
    Refused {
        /// The refusal.
        refusal: RemoteRefusalRecord,
    },
}

/// One changed file of a worktree status.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct GitChangedFileRecord {
    /// Root-relative path.
    pub path: String,
    /// Porcelain status code.
    pub status: String,
}

impl From<GitChangedFile> for GitChangedFileRecord {
    fn from(file: GitChangedFile) -> Self {
        Self {
            path: file.path,
            status: file.status,
        }
    }
}

/// The chat worktree state.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct GitStatusRecord {
    /// False when the chat has no worktree yet (other fields default).
    pub exists: bool,
    /// Worktree head commit.
    pub head: Option<String>,
    /// Branch the worktree lands on.
    pub target_branch: Option<String>,
    /// Commits ahead of the target branch.
    pub ahead: u64,
    /// Uncommitted changes exist.
    pub dirty: bool,
    /// Everything is already on the target branch.
    pub landed: bool,
    /// Changed files (possibly truncated).
    pub changed_files: Vec<GitChangedFileRecord>,
    /// The file list was cut.
    pub truncated: bool,
}

impl From<GitStatusResult> for GitStatusRecord {
    fn from(status: GitStatusResult) -> Self {
        Self {
            exists: status.exists,
            head: status.head,
            target_branch: status.target_branch,
            ahead: status.ahead,
            dirty: status.dirty,
            landed: status.landed,
            changed_files: status.changed_files.into_iter().map(Into::into).collect(),
            truncated: status.truncated,
        }
    }
}

/// Outcome of a worktree status read.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum GitStatusOutcomeRecord {
    /// The status.
    Done {
        /// Worktree state.
        status: GitStatusRecord,
    },
    /// The host refused (for example `no_worktree`).
    Refused {
        /// The refusal.
        refusal: RemoteRefusalRecord,
    },
}

/// The commit a `git commit` made.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct GitCommitRecord {
    /// New commit id.
    pub commit: String,
    /// Commits ahead of the target branch.
    pub ahead: u64,
    /// Branch the worktree lands on.
    pub target_branch: String,
}

impl From<GitCommitResult> for GitCommitRecord {
    fn from(commit: GitCommitResult) -> Self {
        Self {
            commit: commit.commit,
            ahead: commit.ahead,
            target_branch: commit.target_branch,
        }
    }
}

/// Outcome of a worktree commit.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum GitCommitOutcomeRecord {
    /// The commit was made.
    Done {
        /// The commit.
        commit: GitCommitRecord,
    },
    /// The host refused (`nothing_to_commit`, `identity_missing`, ...).
    Refused {
        /// The refusal.
        refusal: RemoteRefusalRecord,
    },
}

/// What landing the worktree did.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum GitLandResultRecord {
    /// The target branch moved (`commits` is 0 when already landed).
    Landed {
        /// Landed commit id.
        commit: String,
        /// Number of commits landed.
        commits: u64,
        /// Branch that moved.
        target_branch: String,
        /// The target branch is checked out on the machine.
        checked_out: bool,
    },
    /// A rebase conflict; the worktree is unchanged.
    Conflict {
        /// Stable code (`land_conflict`).
        code: String,
        /// Paths in conflict.
        conflicting_paths: Vec<String>,
    },
}

impl From<GitLandOutcome> for GitLandResultRecord {
    fn from(outcome: GitLandOutcome) -> Self {
        match outcome {
            GitLandOutcome::Landed {
                commit,
                commits,
                target_branch,
                checked_out,
                ..
            } => Self::Landed {
                commit,
                commits,
                target_branch,
                checked_out,
            },
            GitLandOutcome::Conflict {
                code,
                conflicting_paths,
                ..
            } => Self::Conflict {
                code,
                conflicting_paths,
            },
        }
    }
}

/// Outcome of landing the worktree.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum GitLandOutcomeRecord {
    /// The host answered (landed or conflict).
    Done {
        /// What landing did.
        result: GitLandResultRecord,
    },
    /// The host refused (`worktree_dirty`, `land_failed`, ...).
    Refused {
        /// The refusal.
        refusal: RemoteRefusalRecord,
    },
}

#[uniffi::export]
impl ViewModelCore {
    /// Undo the Project an assistant turn created for `chat_id`: removes the
    /// chat's focus and the Project; the chat stays. Runs on the actor.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Forbidden` when the chat has no
    /// assistant-created Project; `Offline`; `Cancelled`.
    pub async fn undo_created_project(
        &self,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<CreatedProjectRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let record = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::undo_created_project(host, chat_id, cancel)
                })
                .await?;
            Ok::<_, openmates_sdk::error::Error>(record.into())
        })
        .await
    }

    /// Run a confined command on the source of Project `project` for
    /// `chat_id`. `operation_id` binds the single-use approval to the request
    /// (a fresh lowercase UUID per run). Runs on the actor.
    ///
    /// # Errors
    /// `Authentication`; `Invalid` for a malformed operation id or empty
    /// argv; `Offline`; `Cancelled`. Host refusals are `Refused`.
    pub async fn run_remote_command(
        &self,
        project: String,
        source: Option<String>,
        chat_id: String,
        operation_id: String,
        command: RemoteCommandRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<RemoteCommandOutcomeRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        let command = command.into();
        self.run(async move {
            let outcome = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::run_remote_command(
                        host,
                        project,
                        source,
                        chat_id,
                        operation_id,
                        command,
                        cancel,
                    )
                })
                .await?;
            Ok::<_, openmates_sdk::error::Error>(match outcome {
                Ok(result) => RemoteCommandOutcomeRecord::Done {
                    result: result.into(),
                },
                Err(refusal) => RemoteCommandOutcomeRecord::Refused {
                    refusal: refusal.into(),
                },
            })
        })
        .await
    }

    /// Read the Git state of the chat worktree on the Project source.
    ///
    /// # Errors
    /// `Authentication`; `Offline`; `Cancelled`. A missing worktree is
    /// `Refused` (`no_worktree`).
    pub async fn git_status(
        &self,
        project: String,
        source: Option<String>,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<GitStatusOutcomeRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let outcome = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::git_status(host, project, source, chat_id, cancel)
                })
                .await?;
            Ok::<_, openmates_sdk::error::Error>(match outcome {
                Ok(status) => GitStatusOutcomeRecord::Done {
                    status: status.into(),
                },
                Err(refusal) => GitStatusOutcomeRecord::Refused {
                    refusal: refusal.into(),
                },
            })
        })
        .await
    }

    /// Commit every change of the chat worktree (approved on the device by
    /// `operation_id`).
    ///
    /// # Errors
    /// `Authentication`; `Invalid` for a malformed operation id or empty
    /// message; `Offline`; `Cancelled`. Host refusals are `Refused`.
    pub async fn git_commit(
        &self,
        project: String,
        source: Option<String>,
        chat_id: String,
        operation_id: String,
        message: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<GitCommitOutcomeRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let outcome = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::git_commit(
                        host,
                        project,
                        source,
                        chat_id,
                        operation_id,
                        message,
                        cancel,
                    )
                })
                .await?;
            Ok::<_, openmates_sdk::error::Error>(match outcome {
                Ok(commit) => GitCommitOutcomeRecord::Done {
                    commit: commit.into(),
                },
                Err(refusal) => GitCommitOutcomeRecord::Refused {
                    refusal: refusal.into(),
                },
            })
        })
        .await
    }

    /// Land the chat worktree on its target branch; a rebase conflict is the
    /// `Conflict` result.
    ///
    /// # Errors
    /// `Authentication`; `Invalid` for a malformed operation id; `Offline`;
    /// `Cancelled`. Host refusals are `Refused`.
    pub async fn git_land(
        &self,
        project: String,
        source: Option<String>,
        chat_id: String,
        operation_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<GitLandOutcomeRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let outcome = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::git_land(host, project, source, chat_id, operation_id, cancel)
                })
                .await?;
            Ok::<_, openmates_sdk::error::Error>(match outcome {
                Ok(result) => GitLandOutcomeRecord::Done {
                    result: result.into(),
                },
                Err(refusal) => GitLandOutcomeRecord::Refused {
                    refusal: refusal.into(),
                },
            })
        })
        .await
    }
}
