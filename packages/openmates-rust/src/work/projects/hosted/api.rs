//! Public hosted Project file operations on [`Projects`]: resolve the Project
//! and its write policy, enforce the chat-focus gate and the always-ask
//! approval for writes, then run the shared executor. This is the npm CLI
//! `resolve`/`approve` half of `registerCliProjectFileExecutor`; the policy
//! decision itself stays server-enforced on commit.
use super::io::ProjectIo;
use super::job::{self, HostedContext};
use super::*;

/// The Project's write policy (`settings.write_mode`, `None` until chosen).
fn write_mode(settings: &Value) -> Option<ProjectWriteMode> {
    if settings["selection_required"] == true {
        return None;
    }
    match settings["write_mode"].as_str() {
        Some("apply_and_show") => Some(ProjectWriteMode::ApplyAndShow),
        Some("always_ask") => Some(ProjectWriteMode::AlwaysAsk),
        _ => None,
    }
}

/// npm `projectPrivatePaths`: `file_access.private_paths` of the decrypted settings.
fn private_paths(settings: &Value) -> HostedResult<Vec<String>> {
    let Some(access) = settings["settings"].get("file_access") else {
        return Ok(Vec::new());
    };
    let Some(paths) = access.as_object().map(|a| a.get("private_paths")) else {
        return refused("protected_path");
    };
    let Some(paths) = paths else {
        return Ok(Vec::new());
    };
    paths
        .as_array()
        .and_then(|rows| {
            rows.iter()
                .map(|p| p.as_str().map(str::to_owned))
                .collect::<Option<Vec<_>>>()
        })
        .ok_or(HostedFileError::Refused("protected_path"))
}

/// The always-ask approval callback: receives the exact mutation (path,
/// operation, content or patch) and answers whether the user approved this
/// proposal. `Ok(false)` leaves the file unchanged with `write_approval_required`.
pub type HostedApproval<'f> = &'f mut (dyn FnMut(&HostedFileMutation) -> HostedResult<bool> + Send);

/// One mutation job as the executor will run it: the exact proposal, its
/// commitment digest (the `proposal_commitment` of the job result) and whether
/// the Project's write policy asks the user first.
pub struct HostedProposal {
    /// The exact proposal the user approves.
    pub mutation: HostedFileMutation,
    /// Its keyed commitment (`proposal_commitment`).
    pub digest: String,
    /// Whether the always-ask policy needs the user's approval first.
    pub requires_approval: bool,
}

/// The mutation of a create/update/rename/delete job (`None` for reads). The
/// server issues the tool arguments verbatim (`{path, new_path}` for a
/// rename, `{path}` for a delete; contract "Job payloads").
pub(super) fn job_mutation(job: &HostedFileJob) -> HostedResult<Option<HostedFileMutation>> {
    if !job.operation.is_mutation() {
        return Ok(None);
    }
    let mut fields = job.arguments.clone();
    if !fields.is_object() {
        return refused("invalid_file_mutation");
    }
    fields["operation"] = json!(job.operation.wire());
    fields["operation_id"] = json!(job.operation_id);
    serde_json::from_value(fields)
        .map(Some)
        .map_err(|_| HostedFileError::Refused("invalid_file_mutation"))
}

impl Projects<'_> {
    /// The proposal of a mutation job and its digest, or `None` for reads. The
    /// job protocol layer needs the digest for the completed result and the
    /// `awaiting_approval` proposal before the always-ask decision.
    ///
    /// # Errors
    /// `invalid_file_mutation`, `write_policy_required` and core errors.
    pub async fn hosted_job_proposal(
        &mut self,
        selector: &str,
        job: &HostedFileJob,
    ) -> HostedResult<Option<HostedProposal>> {
        let Some(mutation) = job_mutation(job)? else {
            return Ok(None);
        };
        mutation.validate()?;
        let (project_id, key, settings) = self.hosted_project(selector).await?;
        let requires_approval = match write_mode(&settings) {
            None => return refused("write_policy_required"),
            Some(ProjectWriteMode::ApplyAndShow) => false,
            Some(ProjectWriteMode::AlwaysAsk) => true,
        };
        let digest = mutation.digest(&key, &project_id, &job.chat_id)?;
        Ok(Some(HostedProposal {
            mutation,
            digest,
            requires_approval,
        }))
    }

    /// Cookie-only resolution of one Project plus its decoded settings.
    pub(super) async fn hosted_project(
        &mut self,
        selector: &str,
    ) -> HostedResult<(String, Key, Value)> {
        self.hosted_client()?;
        self.scope()?;
        let project = self.resolve(selector).await?;
        let project_id = string(&project.raw, "project_id")?.to_owned();
        let route = self.path(&format!("/v1/projects/{project_id}/settings"), &[]);
        let data = self
            .backend
            .request(Method::GET, &route, None, None)
            .await?;
        let settings = super::super::decode_settings(&data["settings"], &project.key)?;
        Ok((project_id, project.key, settings))
    }

    async fn hosted_run(
        &mut self,
        selector: &str,
        job: HostedFileJob,
        mutation: Option<HostedFileMutation>,
        approval: Option<HostedApproval<'_>>,
        ignored_read_approved: bool,
    ) -> HostedResult<Value> {
        let (project_id, key, settings) = self.hosted_project(selector).await?;
        let private = private_paths(&settings)?;
        let mut chat_key = None;
        if let Some(mutation) = &mutation {
            mutation.validate()?;
            uuid(&job.chat_id)?;
            // projects.files.chat-focus-required: this chat's own active focus
            // must be in this Project (the server re-checks on commit).
            let route = path(
                "/v1/projects/focus/current",
                None,
                &[("chat_id".into(), job.chat_id.clone())],
            );
            let focus = self
                .backend
                .request(Method::GET, &route, None, None)
                .await?;
            if focus["focus"]["project_id"] != project_id.as_str() {
                return refused("project_focus_required");
            }
            match write_mode(&settings) {
                None => return refused("write_policy_required"),
                Some(ProjectWriteMode::ApplyAndShow) => {}
                Some(ProjectWriteMode::AlwaysAsk) => {
                    let approve =
                        approval.ok_or(HostedFileError::Refused("write_approval_required"))?;
                    if !approve(mutation)? {
                        return refused("write_approval_required");
                    }
                    let digest = mutation.digest(&key, &project_id, &job.chat_id)?;
                    let route =
                        self.path(&format!("/v1/projects/{project_id}/write-approvals"), &[]);
                    self.backend
                        .request(
                            Method::POST,
                            &route,
                            Some(
                                json!({"chat_id": job.chat_id, "operation_id": job.operation_id,
                                "proposal_digest": digest}),
                            ),
                            None,
                        )
                        .await?;
                }
            }
            chat_key = Some(
                self.hosted_client()?
                    .hosted_file_chat_key(&job.chat_id)
                    .await?,
            );
        }
        let team = self.filters.team_id.clone();
        let ctx = HostedContext {
            project_id: &project_id,
            project_key: &key,
            chat_key: chat_key.as_deref(),
            team_id: team.as_deref(),
            private_paths: &private,
            ignored_read_approved,
        };
        let mut io = ProjectIo {
            projects: self,
            project_id: project_id.clone(),
            key: key.clone(),
        };
        job::execute(&mut io, &ctx, &job, mutation.as_ref()).await
    }

    /// Visible hosted files under `path` (`project_list_files`), at most 500.
    ///
    /// # Errors
    /// `invalid_path`/`protected_path` for the directory, policy load refusals
    /// and core errors (API-key backends are unavailable).
    pub async fn hosted_files_list(
        &mut self,
        selector: &str,
        path: Option<&str>,
    ) -> HostedResult<Value> {
        let mut arguments = json!({});
        if let Some(path) = path {
            arguments["path"] = json!(path);
        }
        let job = HostedFileJob {
            operation_id: uuid::Uuid::new_v4().to_string(),
            chat_id: String::new(),
            operation: HostedFileOperation::List,
            arguments,
        };
        self.hosted_run(selector, job, None, None, false).await
    }

    /// Search hosted file names or text (`project_search_files`/`_text`); the
    /// arguments are the tool's (`query`, `target`, `path`, `glob`, …).
    ///
    /// # Errors
    /// The shared search refusals and core errors.
    pub async fn hosted_files_search(
        &mut self,
        selector: &str,
        arguments: Value,
    ) -> HostedResult<Value> {
        let job = HostedFileJob {
            operation_id: uuid::Uuid::new_v4().to_string(),
            chat_id: String::new(),
            operation: HostedFileOperation::Search,
            arguments,
        };
        self.hosted_run(selector, job, None, None, false).await
    }

    /// Read one hosted text file with its `expected_base` and revision. An
    /// ignored file is read only with `include_ignored` (the caller's explicit
    /// user grant for this exact read); private files never.
    ///
    /// # Errors
    /// `file_not_found`, `protected_path`, `ignored_path_requires_approval`,
    /// `unsupported_file_content`, `file_key_unavailable` and core errors.
    pub async fn hosted_file_read(
        &mut self,
        selector: &str,
        path: &str,
        include_ignored: bool,
    ) -> HostedResult<Value> {
        let job = HostedFileJob {
            operation_id: uuid::Uuid::new_v4().to_string(),
            chat_id: String::new(),
            operation: HostedFileOperation::ReadText,
            arguments: json!({"path": path}),
        };
        self.hosted_run(selector, job, None, None, include_ignored)
            .await
    }

    /// Create a hosted text file from `chat_id` (whose active focus must be in
    /// this Project). Fails with `file_exists` when the path is already linked.
    ///
    /// # Errors
    /// `project_focus_required`, `write_policy_required`,
    /// `write_approval_required`, `file_exists`, `file_too_large`, the server's
    /// commit rejection and core errors.
    pub async fn hosted_file_create(
        &mut self,
        selector: &str,
        chat_id: &str,
        path: &str,
        content: &str,
        approve: HostedApproval<'_>,
    ) -> HostedResult<Value> {
        let mutation = HostedFileMutation {
            operation: HostedFileOperation::CreateFile,
            operation_id: uuid::Uuid::new_v4().to_string(),
            path: path.to_owned(),
            expected_base: None,
            content: Some(content.to_owned()),
            patch: None,
            new_path: None,
        };
        self.hosted_mutate(selector, chat_id, mutation, approve)
            .await
    }

    /// Update a hosted text file by an exact one-file unified diff against
    /// `expected_base` (the SHA-256 of the text the patch was made from).
    ///
    /// # Errors
    /// As [`Projects::hosted_file_create`], plus `file_not_found`,
    /// `stale_base`, `invalid_patch` and `revision_conflict`.
    pub async fn hosted_file_update(
        &mut self,
        selector: &str,
        chat_id: &str,
        path: &str,
        expected_base: &str,
        patch: &str,
        approve: HostedApproval<'_>,
    ) -> HostedResult<Value> {
        let mutation = HostedFileMutation {
            operation: HostedFileOperation::UpdateFile,
            operation_id: uuid::Uuid::new_v4().to_string(),
            path: path.to_owned(),
            expected_base: Some(expected_base.to_owned()),
            content: None,
            patch: Some(patch.to_owned()),
            new_path: None,
        };
        self.hosted_mutate(selector, chat_id, mutation, approve)
            .await
    }

    /// Rename a hosted file from `chat_id` (whose active focus must be in this
    /// Project): the link moves to `new_path` under a re-derived item id, the
    /// embed and its revision history stay. Write policy and approval apply
    /// exactly as for create/update.
    ///
    /// # Errors
    /// As [`Projects::hosted_file_create`], plus `file_not_found` and
    /// `path_conflict` (local listing or server).
    pub async fn rename_hosted_file(
        &mut self,
        selector: &str,
        chat_id: &str,
        path: &str,
        new_path: &str,
        approve: HostedApproval<'_>,
    ) -> HostedResult<Value> {
        let mutation = HostedFileMutation {
            operation: HostedFileOperation::RenameFile,
            operation_id: uuid::Uuid::new_v4().to_string(),
            path: path.to_owned(),
            expected_base: None,
            content: None,
            patch: None,
            new_path: Some(new_path.to_owned()),
        };
        self.hosted_mutate(selector, chat_id, mutation, approve)
            .await
    }

    /// Remove a hosted file's link from the Project folder. The embed and its
    /// revisions stay, so a commit restore can relink the file.
    ///
    /// # Errors
    /// As [`Projects::hosted_file_create`], plus `file_not_found`.
    pub async fn delete_hosted_file(
        &mut self,
        selector: &str,
        chat_id: &str,
        path: &str,
        approve: HostedApproval<'_>,
    ) -> HostedResult<Value> {
        let mutation = HostedFileMutation {
            operation: HostedFileOperation::DeleteFile,
            operation_id: uuid::Uuid::new_v4().to_string(),
            path: path.to_owned(),
            expected_base: None,
            content: None,
            patch: None,
            new_path: None,
        };
        self.hosted_mutate(selector, chat_id, mutation, approve)
            .await
    }

    async fn hosted_mutate(
        &mut self,
        selector: &str,
        chat_id: &str,
        mutation: HostedFileMutation,
        approve: HostedApproval<'_>,
    ) -> HostedResult<Value> {
        let job = HostedFileJob {
            operation_id: mutation.operation_id.clone(),
            chat_id: chat_id.to_owned(),
            operation: mutation.operation,
            arguments: json!({"path": mutation.path}),
        };
        self.hosted_run(selector, job, Some(mutation), Some(approve), false)
            .await
    }

    /// Execute one server-issued Project file job for a hosted Project (the
    /// assistant's `project_*` file tools). For a mutation the arguments carry
    /// the proposal fields (`path`, `expected_base`, `content`/`patch`); the
    /// write policy, focus gate and approval apply exactly as for the CLI
    /// commands. Lease claim/result frames stay with the job protocol caller.
    ///
    /// # Errors
    /// Every executor refusal; [`HostedFileError::status`] maps it to the job
    /// result status (`conflict`, `failed`, `waiting_for_executor`).
    pub async fn execute_hosted_file_job(
        &mut self,
        selector: &str,
        job: HostedFileJob,
        approve: HostedApproval<'_>,
        ignored_read_approved: bool,
    ) -> HostedResult<Value> {
        let mutation = job_mutation(&job)?;
        let approval = if mutation.is_some() {
            Some(approve)
        } else {
            None
        };
        self.hosted_run(selector, job, mutation, approval, ignored_read_approved)
            .await
    }
}
