//! Applied-change preview of a hosted Project sandbox commit (shared core).
//! The server's `embed_revision_committed` event (`source: project_sandbox`)
//! carries only ids; this device reads the committed head with its own Project
//! key and returns the path and text the shell shows as an applied change, like
//! a device-path write. Spec: `projects.files.write-policy-enforcement` (Apply
//! and show changes presents the resulting changes), `projects.sandbox.write-back`.
use super::hosted::io::{HostedIo, ProjectIo};
use super::*;

/// The committed file of one sandbox revision, decrypted on this device.
/// Plaintext stays in memory for the shell's change card; it is never logged.
pub(crate) struct SandboxChange {
    /// Project path of the file's link.
    pub(crate) path: String,
    /// Full text of the committed revision.
    pub(crate) content: String,
}

impl Projects<'_> {
    /// Decrypts the current head of `embed_id` in `project_id` with `key`.
    /// `None` when the embed is not (or no longer) a linked file of the Project,
    /// e.g. after a later delete.
    ///
    /// # Errors
    /// Transport, cancellation and authorization failures of the core; executor
    /// refusals (missing key wrapper, unsupported content) as `Error::Invalid(code)`.
    pub(crate) async fn sandbox_change(
        &mut self,
        project_id: &str,
        key: Key,
        embed_id: &str,
    ) -> Result<Option<SandboxChange>> {
        let mut io = ProjectIo {
            projects: self,
            project_id: project_id.to_owned(),
            key,
        };
        let files = io.list_files().await.map_err(core_error)?;
        let Some(file) = files.into_iter().find(|file| file.embed_id == embed_id) else {
            return Ok(None);
        };
        let head = io.read_head(embed_id).await.map_err(core_error)?;
        let content = head.text().map_err(core_error)?.to_owned();
        Ok(Some(SandboxChange {
            path: file.path,
            content,
        }))
    }
}

/// Maps the executor's error onto the core error the bindings carry.
pub(super) fn core_error(error: HostedFileError) -> Error {
    match error {
        HostedFileError::Core(error) => error,
        HostedFileError::Refused(code) => Error::Invalid(code),
        // A read never commits, so a server commit rejection here is a protocol break.
        HostedFileError::Rejected(_) => Error::Protocol,
    }
}
