//! Requester side of assistant Project file jobs aimed at a remote source (a
//! Project folder on one of the user's machines): `list`, `search`,
//! `read_text`, `create_file`, `update_file` and `commit` (`git_commit`) go to the source host through
//! the sealed requester transport of `remote_files.rs` (`source_call`).
//! Mirrors the web executor (`browserProjectFileExecutor.ts` ->
//! `requestProjectRemoteAccess`); host contract `source_host/dispatch.rs`.
//! The chat id travels with every call, so writes land in the chat's worktree
//! on the machine and later reads see them (like `run_command`).
//! spec: specifications/features/projects (projects.creation.machine-folder).
use super::remote_ops::{FileMutationProposal, RemoteOpError, WireCall, WriteProposal};
use super::*;

/// Upper bound of one relayed file job; the job lease bounds it again.
const PROTOCOL_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(45);

/// Stable code of a job operation the remote host does not implement.
pub(crate) const REMOTE_OPERATION_UNSUPPORTED: &str = "unsupported_operation";

/// The relay call of one file job; `None` when the host has no such operation
/// (rename/delete exist only for hosted Project files).
fn file_job_call(
    chat: &str,
    operation: HostedFileOperation,
    arguments: &Value,
    mutation: Option<HostedFileMutation>,
) -> Option<WireCall> {
    let read = |name: &'static str, capability: Option<&'static str>| WireCall {
        name,
        arguments: arguments.clone(),
        capability,
        chat: Some(chat.to_owned()),
        write: None,
    };
    match (operation, mutation) {
        (HostedFileOperation::List, _) => Some(read("list", None)),
        // A content search reads file text, so it also needs `read`.
        (HostedFileOperation::Search, _) => Some(read(
            "search",
            (arguments["include_content"] == true).then_some("read"),
        )),
        (HostedFileOperation::ReadText, _) => Some(read("read_text", Some("read"))),
        (
            operation @ (HostedFileOperation::CreateFile | HostedFileOperation::UpdateFile),
            Some(mutation),
        ) => {
            let proposal = WriteProposal::FileMutation(FileMutationProposal(mutation));
            Some(WireCall {
                name: operation.wire(),
                arguments: proposal.arguments(chat),
                capability: Some("write_request"),
                chat: Some(chat.to_owned()),
                write: Some((chat.to_owned(), proposal)),
            })
        }
        _ => None,
    }
}

impl Projects<'_> {
    /// Run one assistant file job on the remote source `source_id` of Project
    /// `project_id` for chat `chat` and return the host's result. Reads pass
    /// the job arguments through; a create/update sends the validated
    /// `mutation`, approved under its proposal digest (`source_call` stores
    /// the approval for `always_ask` Projects).
    ///
    /// # Errors
    /// [`ProjectRequesterError::Remote`] with the relay or host code
    /// (`source_offline`, `source_capability_denied`, `protocol_timeout`,
    /// [`REMOTE_OPERATION_UNSUPPORTED`], host write codes); core transport
    /// errors as [`ProjectRequesterError::Core`].
    pub(crate) async fn remote_file_job(
        &mut self,
        project_id: &str,
        source_id: &str,
        chat: &str,
        operation: HostedFileOperation,
        arguments: &Value,
        mutation: Option<HostedFileMutation>,
    ) -> std::result::Result<Value, ProjectRequesterError> {
        let Some(call) = file_job_call(chat, operation, arguments, mutation) else {
            return Err(ProjectRequesterError::Remote {
                code: REMOTE_OPERATION_UNSUPPORTED.to_owned(),
                message: "This Project source does not support this file operation.".to_owned(),
            });
        };
        let (_, _, result) = self
            .source_call(project_id, Some(source_id), call, PROTOCOL_TIMEOUT)
            .await?;
        Ok(result)
    }

    /// Run an assistant `commit` job on the remote source: the host commits
    /// every change of chat `chat`'s worktree (`git_commit`, approved under
    /// the job's `operation_id`). The result mirrors the hosted commit job
    /// (`commit_id`, `message`) plus the host's `ahead` / `target_branch`.
    ///
    /// # Errors
    /// [`ProjectRequesterError::Remote`] with the host code
    /// (`nothing_to_commit`, `identity_missing`, `no_worktree`,
    /// `source_offline`, ...); core errors as [`ProjectRequesterError::Core`].
    pub(crate) async fn remote_commit_job(
        &mut self,
        project_id: &str,
        source_id: &str,
        chat: &str,
        operation_id: &str,
        message: &str,
    ) -> std::result::Result<Value, ProjectRequesterError> {
        match self
            .git_commit(project_id, Some(source_id), chat, operation_id, message)
            .await
        {
            Ok(commit) => Ok(json!({
                "commit_id": commit.commit,
                "message": message,
                "ahead": commit.ahead,
                "target_branch": commit.target_branch,
            })),
            Err(RemoteOpError::Core(error)) => Err(ProjectRequesterError::Core(error)),
            Err(RemoteOpError::Host { code, message }) => Err(ProjectRequesterError::Remote {
                code: code.wire().to_owned(),
                message,
            }),
        }
    }

    /// The Project key of `project_id` in the current scope, for the origin
    /// side of a remote command (sealing the approved request, opening the
    /// host's events). It never leaves the core.
    ///
    /// # Errors
    /// Resolution errors (`NotFound`, `Forbidden`, transport, `Crypto`).
    pub(crate) async fn project_key_for_command(&mut self, project_id: &str) -> Result<Key> {
        Ok(self.resolve(project_id).await?.key)
    }
}

#[cfg(test)]
#[path = "remote_file_jobs_tests.rs"]
mod tests;
