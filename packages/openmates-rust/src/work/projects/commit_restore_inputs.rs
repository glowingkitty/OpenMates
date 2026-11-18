//! Reads a user commit restore needs before it writes (native and browser):
//! the plan, the original message and the current hosted-file links.

use super::*;

/// Everything the user restore reads before it writes.
pub(crate) struct UserRestoreInputs {
    /// Resolved Project id.
    pub(crate) project_id: String,
    /// The comparison of the commit with the current heads.
    pub(crate) plan: ProjectCommitRestorePlan,
    /// Decrypted message of the commit being restored.
    pub(crate) message: String,
    /// Current hosted-file links as (embed id, Project path).
    pub(crate) linked: Vec<(String, String)>,
}

impl Projects<'_> {
    /// Plan, original message and current links of a commit restore.
    ///
    /// # Errors
    /// The commit read, plan and Project listing errors.
    pub(crate) async fn user_restore_inputs(
        &mut self,
        selector: &str,
        commit_id: &str,
    ) -> Result<UserRestoreInputs> {
        let message = self.show_commit(selector, commit_id).await?.message;
        let plan = self.restore_commit_plan(selector, commit_id).await?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let linked = self.project_hosted_files(&project_id, &project.key).await?;
        Ok(UserRestoreInputs {
            project_id,
            plan,
            message,
            linked,
        })
    }

    /// Current head version of one linked embed of the Project.
    ///
    /// # Errors
    /// The history read errors.
    pub(crate) async fn user_restore_head_version(
        &mut self,
        project_id: &str,
        embed_id: &str,
    ) -> Result<u64> {
        self.head_version(project_id, embed_id).await
    }
}
