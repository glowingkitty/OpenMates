//! Whole-commit restore of hosted Project files (`projects.history.native-commits`).
//!
//! Reconstructs each committed revision from its encrypted history rows, writes
//! every file whose head differs as a new revision (an exact replacement patch
//! against the current head, so the write policy, focus gate and stale-base
//! checks apply as for any update), then records the restore as a new commit
//! with `restored_from`. History is never rewritten.
use super::super::commits::{
    ProjectCommit, ProjectCommitAuthor, ProjectCommitCreate, ProjectCommitFile,
    ProjectCommitRestorePlan,
};
use super::api::HostedApproval;
use super::io::{HostedIo, ProjectIo};
use super::*;
use std::collections::BTreeMap;

/// Outcome of an applied restore: the plan, one write result per changed file
/// (`path`, `revision`, `expected_base`, …) and the recorded restore commit.
#[derive(Clone, Serialize)]
pub struct ProjectCommitRestoreResult {
    /// The comparison the restore applied.
    pub plan: ProjectCommitRestorePlan,
    /// Write results of the files that got a new revision.
    pub written: Vec<Value>,
    /// The new commit pointing at the restored revisions.
    pub commit: ProjectCommit,
}

/// Replay decrypted history rows to the text of their last version: the first
/// row must carry a snapshot, later snapshots restart the chain and patches
/// apply with the stored-version diff rules (`applyVersionPatch`).
///
/// # Errors
/// `Protocol` for a gapped or empty chain, `Crypto` for a row the embed key
/// does not open, `invalid_patch` for a patch that does not apply.
pub(crate) fn replay_rows(
    rows: &[Value],
    embed_key: &[u8; 32],
    version: u64,
) -> HostedResult<Zeroizing<String>> {
    let mut content: Option<Zeroizing<String>> = None;
    let mut expected = None;
    for row in rows {
        let number = row["version_number"]
            .as_u64()
            .filter(|v| *v >= 1)
            .ok_or(HostedFileError::Core(Error::Protocol))?;
        if expected.is_some_and(|e| e != number) {
            return Err(HostedFileError::Core(Error::Protocol));
        }
        expected = Some(number + 1);
        content = Some(
            match (
                row["encrypted_snapshot"].as_str().filter(|s| !s.is_empty()),
                &content,
            ) {
                (Some(snapshot), _) => Zeroizing::new(crypto::server_fields::decrypt_text(
                    snapshot,
                    embed_key,
                    &[],
                )?),
                (None, Some(previous)) => {
                    let cipher = row["encrypted_patch"]
                        .as_str()
                        .ok_or(HostedFileError::Core(Error::Protocol))?;
                    let patch = Zeroizing::new(crypto::server_fields::decrypt_text(
                        cipher,
                        embed_key,
                        &[],
                    )?);
                    Zeroizing::new(
                        crate::embed_read::patch::apply_version_patch(previous, &patch)
                            .map_err(|_| HostedFileError::Refused("invalid_patch"))?,
                    )
                }
                (None, None) => return Err(HostedFileError::Core(Error::Protocol)),
            },
        );
    }
    if expected != Some(version + 1) {
        return Err(HostedFileError::Core(Error::Protocol));
    }
    content.ok_or(HostedFileError::Core(Error::Protocol))
}

impl Projects<'_> {
    /// Encrypted rows that rebuild `version`: the bounded window from the
    /// nearest snapshot, or the full chain when the server answers that the
    /// window has no snapshot yet (`409 snapshot_required`).
    async fn version_rows(
        &mut self,
        project_id: &str,
        embed_id: &str,
        version: u64,
    ) -> HostedResult<Vec<Value>> {
        let base = format!("/v1/embeds/{embed_id}/versions/{version}");
        let bounded = self.path(
            &base,
            &[
                ("project_id".into(), project_id.into()),
                ("capability".into(), "bounded-v1".into()),
            ],
        );
        let response = match self
            .backend
            .request(Method::GET, &bounded, None, None)
            .await
        {
            Err(Error::Conflict) => {
                let full = self.path(&base, &[("project_id".into(), project_id.into())]);
                self.backend.request(Method::GET, &full, None, None).await?
            }
            other => other?,
        };
        if response["embed_id"] != embed_id || response["version_number"].as_u64() != Some(version)
        {
            return Err(HostedFileError::Core(Error::Forbidden));
        }
        response["rows"]
            .as_array()
            .cloned()
            .ok_or(HostedFileError::Core(Error::Protocol))
    }

    /// Restore every file of a commit as new revisions written from `chat_id`
    /// (its active focus must be in this Project), then record the restore as
    /// a new commit. Files whose head already equals the committed text are
    /// not rewritten. A file unlinked since the commit refuses the whole
    /// restore before anything is written (`restore_target_missing`).
    ///
    /// # Errors
    /// The update refusals (`project_focus_required`, `write_policy_required`,
    /// `write_approval_required`, `stale_base`, `revision_conflict`, …), history
    /// read failures and the commit record errors. Files written before a
    /// failure stay as ordinary new revisions; rerunning the restore converges.
    pub async fn restore_commit(
        &mut self,
        selector: &str,
        commit_id: &str,
        chat_id: &str,
        message: Option<&str>,
        approve: HostedApproval<'_>,
    ) -> HostedResult<ProjectCommitRestoreResult> {
        let plan = self.restore_commit_plan(selector, commit_id).await?;
        if plan.files.iter().any(|file| file.target_id.is_none()) {
            return refused("restore_target_missing");
        }
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let linked: BTreeMap<String, String> = self
            .project_hosted_files(&project_id, &project.key)
            .await?
            .into_iter()
            .collect();
        let mut written = Vec::new();
        for file in plan.files.iter().filter(|file| !file.unchanged) {
            let target = file
                .target_id
                .as_deref()
                .ok_or(HostedFileError::Refused("restore_target_missing"))?;
            let path = linked
                .get(target)
                .cloned()
                .ok_or(HostedFileError::Refused("restore_target_missing"))?;
            let head = ProjectIo {
                projects: self,
                project_id: project_id.clone(),
                key: project.key.clone(),
            }
            .read_head(target)
            .await?;
            let current = Zeroizing::new(head.text()?.to_owned());
            let rows = self
                .version_rows(&project_id, target, file.restore_version)
                .await?;
            let restored = replay_rows(&rows, &head.embed_key, file.restore_version)?;
            if *current == *restored {
                continue;
            }
            let patch = Zeroizing::new(replacement_patch(&path, &current, &restored));
            let result = self
                .hosted_file_update(
                    selector,
                    chat_id,
                    &path,
                    &content_hash(&current),
                    &patch,
                    &mut *approve,
                )
                .await?;
            written.push(result);
        }
        let mut files = Vec::with_capacity(plan.files.len());
        for file in &plan.files {
            let target = file
                .target_id
                .clone()
                .ok_or(HostedFileError::Refused("restore_target_missing"))?;
            let path = linked
                .get(&target)
                .cloned()
                .ok_or(HostedFileError::Refused("restore_target_missing"))?;
            let embed_version = self.head_version(&project_id, &target).await?;
            files.push(ProjectCommitFile {
                target_id: target,
                path,
                embed_version,
            });
        }
        let input = ProjectCommitCreate {
            message: message.map_or_else(|| format!("Restore commit {commit_id}"), str::to_owned),
            author: ProjectCommitAuthor::User,
            chat_id: Some(chat_id.to_owned()),
            files,
            commit_id: None,
            created_at: None,
        };
        let commit = self
            .record_commit_restore(selector, commit_id, input)
            .await?;
        Ok(ProjectCommitRestoreResult {
            plan,
            written,
            commit,
        })
    }
}
