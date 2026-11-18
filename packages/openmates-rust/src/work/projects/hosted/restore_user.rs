//! Project-side inputs of the user (GUI) whole-commit restore.
//!
//! Exposes the commit plan with the Project's current hosted-file paths and the
//! head version reads that `Client::restore_project_commit` needs, and a thin
//! `restore_commit_as_user` entry for shells that only hold a `Projects`
//! service (CLI). Spec: `projects.history.native-commits`.
use super::*;

impl Projects<'_> {
    /// Restore a commit as the signed-in user, without a chat: every changed
    /// file is written as a user revision in Project scope, files unlinked
    /// after the commit are relinked, then the restore commit is recorded.
    ///
    /// # Errors
    /// Cookie sessions only; the errors of `Client::restore_project_commit`.
    pub async fn restore_commit_as_user(
        &mut self,
        selector: &str,
        commit_id: &str,
        message: Option<String>,
        operation_id: Option<String>,
    ) -> Result<crate::client::ProjectCommitUserRestore> {
        let team = self.filters.team_id.clone();
        self.hosted_client()?
            .restore_project_commit(selector, team.as_deref(), commit_id, message, operation_id)
            .await
    }
}
