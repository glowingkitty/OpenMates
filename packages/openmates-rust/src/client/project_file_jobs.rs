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
use serde_json::Value;
use std::collections::BTreeSet;
use std::fmt;

/// WebSocket and turn capability that opts into Project file jobs.
pub(super) const PROJECT_FILE_JOBS_CAPABILITY: &str = "project_file_jobs";

/// Every core with `workflow-yaml` owns the hosted-file executor; others never advertise.
pub(super) const PROJECT_FILE_JOBS_AVAILABLE: bool = cfg!(feature = "workflow-yaml");

/// Per-turn state of the file-job protocol, carried with the Project state.
#[derive(Clone, Debug, Default)]
pub(super) struct FileJobState {
    /// Whether the shell approves always-ask writes (`--auto-approve`).
    pub(super) approve_writes: bool,
    pub(super) finished: BTreeSet<String>,
    pub(super) notices: Vec<String>,
    /// The chat's privacy mappings; file writes restore placeholders with them.
    pub(super) mappings: FileJobMappings,
    /// Interactive approvals, pending prompts and applied events.
    pub(super) approvals: approvals::Approvals,
    /// Web-mode privacy (restore before running, redact before sending).
    /// Only cores with `workflow-yaml` run file jobs, so only they carry it.
    #[cfg(feature = "workflow-yaml")]
    pub(super) privacy: Option<privacy::PrivacyLayer>,
}

/// The chat's privacy mappings: wiped on drop and never printed.
#[derive(Clone, Default)]
pub(super) struct FileJobMappings(pub(super) Vec<Value>);

impl fmt::Debug for FileJobMappings {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "FileJobMappings({})", self.0.len())
    }
}

impl Drop for FileJobMappings {
    fn drop(&mut self) {
        for mapping in &mut self.0 {
            crate::model::zeroize_json(mapping);
        }
    }
}

impl FileJobState {
    /// Remember the chat's privacy mappings; later file writes restore with them.
    pub(super) fn set_mappings(&mut self, mappings: &[Value]) {
        self.mappings = FileJobMappings(mappings.to_vec());
        #[cfg(feature = "workflow-yaml")]
        if let Some(layer) = &mut self.privacy {
            layer.add_mappings(mappings);
        }
    }

    /// One-line summaries for the shell (applied or rejected file changes).
    pub(super) fn take_notices(&mut self) -> Vec<String> {
        std::mem::take(&mut self.notices)
    }

    pub(super) fn clear(&mut self) {
        self.finished.clear();
        self.notices.clear();
        self.mappings = FileJobMappings::default();
        self.approvals = approvals::Approvals::default();
        #[cfg(feature = "workflow-yaml")]
        {
            self.privacy = None;
        }
    }
}

impl Wipe for FileJobState {
    fn wipe(&mut self) {
        self.clear();
    }
}

#[cfg(feature = "workflow-yaml")]
#[path = "project_file_job_frames.rs"]
mod frames;

#[cfg(feature = "workflow-yaml")]
#[path = "project_file_job_snapshot.rs"]
mod snapshot;

#[path = "project_file_job_approvals.rs"]
mod approvals;
#[cfg(feature = "workflow-yaml")]
#[path = "project_file_job_privacy.rs"]
mod privacy;
pub(in crate::client) use approvals::FileJobChats;
#[cfg(feature = "workflow-yaml")]
pub use privacy::ProjectFilePrivacyBlob;

#[cfg(feature = "workflow-yaml")]
#[path = "project_file_job_steps.rs"]
mod steps;
#[cfg(feature = "workflow-yaml")]
pub use steps::{ProjectFileJobFrame, ProjectFileJobStep};

#[cfg(all(test, feature = "workflow-yaml"))]
#[path = "project_file_job_approvals_tests.rs"]
mod approvals_tests;

#[cfg(all(test, feature = "workflow-yaml"))]
#[path = "project_file_job_privacy_tests.rs"]
mod privacy_tests;

#[cfg(all(test, feature = "workflow-yaml"))]
#[path = "project_file_job_web_privacy_tests.rs"]
mod web_privacy_tests;
