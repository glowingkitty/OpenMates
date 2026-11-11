//! Assistant Project file jobs of a saved turn (`project_file_jobs` capability).
//!
//! The server leases transient jobs (`list`, `search`, `read_text`,
//! `create_file`, `update_file`, `rename_file`, `delete_file`) to the client
//! that advertised the capability. Rename/delete arguments are `{path,
//! new_path}` and `{path}` in the same envelope as create/update.
//! This module owns the frame protocol exactly as the web and npm executors do:
//! `project_file_operation_available` -> `project_file_operation_claim`,
//! `project_file_operation_request` -> validate the lease -> execute with
//! [`crate::work::Projects::execute_hosted_file_job`] ->
//! `project_file_operation_result` (or `project_file_operation_reject` after a
//! refused always-ask write). Shells only choose the write policy and print the
//! notices returned by [`FileJobState::take_notices`].
//!
//! Jobs aimed at a remote source are not executed by this client; they are
//! answered `waiting_for_executor` (`source_offline`) so the server can hand
//! them to a source executor instead of failing the turn.
use super::plaintext::Wipe;
use std::collections::BTreeSet;

/// WebSocket and turn capability that opts into Project file jobs.
pub(super) const PROJECT_FILE_JOBS_CAPABILITY: &str = "project_file_jobs";

/// Only native cores own the hosted-file executor; other targets never advertise.
pub(super) const PROJECT_FILE_JOBS_AVAILABLE: bool = cfg!(all(feature = "workflow-yaml", unix));

/// Per-turn state of the file-job protocol, carried with the Project state.
#[derive(Clone, Debug, Default)]
pub(super) struct FileJobState {
    /// Whether the shell approves always-ask writes (`--auto-approve`).
    pub(super) approve_writes: bool,
    pub(super) finished: BTreeSet<String>,
    pub(super) notices: Vec<String>,
}

impl FileJobState {
    /// One-line summaries for the shell (applied or rejected file changes).
    pub(super) fn take_notices(&mut self) -> Vec<String> {
        std::mem::take(&mut self.notices)
    }

    pub(super) fn clear(&mut self) {
        self.finished.clear();
        self.notices.clear();
    }
}

impl Wipe for FileJobState {
    fn wipe(&mut self) {
        self.clear();
    }
}

#[cfg(all(feature = "workflow-yaml", unix))]
#[path = "project_file_job_frames.rs"]
mod frames;
