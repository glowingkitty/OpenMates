//! Frame protocol of assistant Project file jobs: see `project_file_jobs`.
//! Rename and delete jobs (P11) use the same envelope, policy and approval.
use super::super::*;
use super::FileJobState;
use crate::work::{
    HostedFileError, HostedFileJob, HostedFileMutation, HostedProposal, HostedResult,
};
use std::time::Duration;

/// Finished operation ids remembered per turn (idempotency of repeated frames).
const MAX_FINISHED: usize = 256;
/// Largest `lease_expires_at` skew we accept (the server lease is 90 seconds).
const MAX_LEASE_SECONDS: u64 = 600;
const OPERATIONS: [&str; 7] = [
    "list",
    "search",
    "read_text",
    "create_file",
    "update_file",
    "rename_file",
    "delete_file",
];

/// The chat's active Project focus: the authority a job is resolved against.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct Focus {
    pub(super) project_id: String,
    pub(super) team_id: Option<String>,
}

/// What the job runner can do; the real implementation is [`Client`], tests use
/// an in-memory runner.
pub(super) trait JobRunner {
    /// The chat's active Project focus, if any.
    async fn focus(&mut self, chat: &str) -> Result<Option<Focus>>;
    /// The exact proposal and digest of a mutation job (`None` for reads).
    async fn proposal(
        &mut self,
        focus: &Focus,
        job: &HostedFileJob,
    ) -> HostedResult<Option<HostedProposal>>;
    /// Execute the job; `approved` answers the always-ask question.
    async fn execute(
        &mut self,
        focus: &Focus,
        job: HostedFileJob,
        approved: bool,
    ) -> HostedResult<Value>;
}

impl FileJobState {
    fn finish(&mut self, operation: &str) {
        if self.finished.len() < MAX_FINISHED {
            self.finished.insert(operation.to_owned());
        }
    }
}

/// A job frame with a valid identity (`protocol_version` 1, known operation,
/// bounded ids) for this turn's chat.
fn identity<'a>(event: &'a Value, chat: &str) -> Option<&'a Value> {
    let id = |key: &str| {
        event[key]
            .as_str()
            .filter(|v| !v.is_empty() && v.len() <= 128)
    };
    let known = event["operation"]
        .as_str()
        .is_some_and(|op| OPERATIONS.contains(&op));
    (event["protocol_version"] == 1
        && known
        && id("operation_id").is_some()
        && id("project_id").is_some()
        && id("chat_id") == Some(chat))
    .then_some(event)
}

fn scope(job: &Value) -> Value {
    json!({"protocol_version": 1, "operation_id": job["operation_id"],
        "chat_id": job["chat_id"], "project_id": job["project_id"]})
}

fn result_frame(job: &Value, status: &str, body: Value) -> (&'static str, Value) {
    let mut payload = scope(job);
    payload["lease_token"] = job["lease_token"].clone();
    payload["lease_generation"] = job["lease_generation"].clone();
    payload["status"] = json!(status);
    payload["result"] = body;
    ("project_file_operation_result", payload)
}

/// `waiting_for_executor` takes a bounded reason; others carry the safe code.
/// A `conflict` carries it as both `code` and `reason` (contract "Job
/// payloads": a rename onto a linked path is `reason: "path_conflict"`).
fn error_frame(job: &Value, error: &HostedFileError) -> (&'static str, Value) {
    let (status, code) = (error.status(), error.code());
    let body = match status {
        "waiting_for_executor" => json!({"reason": code}),
        "conflict" => json!({"code": code, "reason": code}),
        _ => json!({"code": code}),
    };
    result_frame(job, status, body)
}

/// A validated job request: the lease fields are present and well formed.
fn valid_lease(job: &Value) -> bool {
    job["lease_token"]
        .as_str()
        .is_some_and(|t| t.len() >= 16 && t.len() <= 256)
        && job["lease_generation"].as_u64().is_some_and(|g| g >= 1)
        && job["lease_expires_at"].is_number()
        && job["arguments"].is_object()
}

fn job_of(event: &Value) -> Option<HostedFileJob> {
    Some(HostedFileJob {
        operation_id: event["operation_id"].as_str()?.to_owned(),
        chat_id: event["chat_id"].as_str()?.to_owned(),
        operation: serde_json::from_value(event["operation"].clone()).ok()?,
        arguments: event["arguments"].clone(),
    })
}

/// One-line notice of an applied write (`renamed` names both paths).
fn applied_notice(mutation: &HostedFileMutation, created: bool) -> String {
    let path = &mutation.path;
    match (mutation.operation, &mutation.new_path) {
        (crate::work::HostedFileOperation::RenameFile, Some(target)) => {
            format!("Project file renamed: {path} -> {target}")
        }
        (crate::work::HostedFileOperation::DeleteFile, _) => {
            format!("Project file deleted: {path}")
        }
        _ => format!(
            "Project file {}: {path}",
            if created { "created" } else { "updated" }
        ),
    }
}

/// The frames to send for one `project_file_operation_available` /
/// `project_file_operation_request` frame of the turn's chat `chat`.
///
/// Malformed or unknown frames yield nothing (the server's lease expires and
/// re-offers them); an expired lease answers `failed` / `lease_expired`.
///
/// # Errors
/// Only cancellation: executor refusals become result frames.
pub(super) async fn job_frames<R: JobRunner>(
    runner: &mut R,
    kind: &str,
    event: &Value,
    chat: &str,
    now_s: u64,
    state: &mut FileJobState,
) -> Result<Vec<(&'static str, Value)>> {
    let Some(job) = identity(event, chat) else {
        return Ok(Vec::new());
    };
    let operation = job["operation_id"].as_str().unwrap_or_default().to_owned();
    if state.finished.contains(&operation) {
        return Ok(Vec::new());
    }
    if kind == "project_file_operation_available" {
        return Ok(vec![("project_file_operation_claim", scope(job))]);
    }
    let expires = job["lease_expires_at"].as_f64().unwrap_or_default();
    if !valid_lease(job) || expires > (now_s + MAX_LEASE_SECONDS) as f64 {
        return Ok(Vec::new());
    }
    if expires <= now_s as f64 {
        state.finish(&operation);
        return Ok(vec![result_frame(
            job,
            "failed",
            json!({"code": "lease_expired"}),
        )]);
    }
    let remaining = Duration::from_secs((expires as u64).saturating_sub(now_s));
    if job["source_id"].as_str().is_some() {
        return Ok(vec![result_frame(
            job,
            "waiting_for_executor",
            json!({"reason": "source_offline"}),
        )]);
    }
    let Some(hosted) = job_of(job) else {
        return Ok(Vec::new());
    };
    let focus = match runner.focus(chat).await {
        Ok(Some(focus)) if focus.project_id == job["project_id"].as_str().unwrap_or_default() => {
            focus
        }
        Ok(_) => {
            state.finish(&operation);
            return Ok(vec![result_frame(
                job,
                "failed",
                json!({"code": "project_focus_required"}),
            )]);
        }
        Err(Error::Cancelled) => return Err(Error::Cancelled),
        Err(error) => return Ok(vec![error_frame(job, &HostedFileError::Core(error))]),
    };
    let proposal = match runner.proposal(&focus, &hosted).await {
        Ok(proposal) => proposal,
        Err(HostedFileError::Core(Error::Cancelled)) => return Err(Error::Cancelled),
        Err(error) => {
            state.finish(&operation);
            return Ok(vec![error_frame(job, &error)]);
        }
    };
    if let Some(proposal) = proposal
        .as_ref()
        .filter(|p| p.requires_approval && !state.approve_writes)
    {
        // Awaiting approval first (the server only accepts a reject from that
        // state), then the explicit decline; the file stays unchanged.
        state.finish(&operation);
        state.notices.push(format!(
            "Project file write not applied (approval required, use --auto-approve): {} {}",
            proposal.mutation.operation.wire(),
            proposal.mutation.path
        ));
        let shown = serde_json::to_value(&proposal.mutation).map_err(Error::from)?;
        return Ok(vec![
            result_frame(
                job,
                "awaiting_approval",
                json!({"proposal_commitment": proposal.digest, "proposal": shown}),
            ),
            ("project_file_operation_reject", scope(job)),
        ]);
    }
    let outcome = crate::platform::time::timeout(
        remaining,
        runner.execute(&focus, hosted, state.approve_writes),
    )
    .await;
    state.finish(&operation);
    let output = match outcome {
        Err(_) => {
            return Ok(vec![result_frame(
                job,
                "failed",
                json!({"code": "lease_expired"}),
            )]);
        }
        Ok(Err(HostedFileError::Core(Error::Cancelled))) => return Err(Error::Cancelled),
        Ok(Err(error)) => return Ok(vec![error_frame(job, &error)]),
        Ok(Ok(output)) => output,
    };
    let mut body = match output {
        Value::Object(map) => map,
        other => serde_json::Map::from_iter([("value".to_owned(), other)]),
    };
    body.insert("source_id".into(), Value::Null);
    if let Some(proposal) = &proposal {
        body.insert("proposal_commitment".into(), json!(proposal.digest));
        let created = body
            .get("created")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        state
            .notices
            .push(applied_notice(&proposal.mutation, created));
    }
    Ok(vec![result_frame(job, "completed", Value::Object(body))])
}

impl JobRunner for Client {
    async fn focus(&mut self, chat: &str) -> Result<Option<Focus>> {
        let focus = self.projects().active_focus(chat).await?;
        Ok(focus["project_id"].as_str().map(|project| Focus {
            project_id: project.to_owned(),
            team_id: focus["team_id"].as_str().map(str::to_owned),
        }))
    }

    async fn proposal(
        &mut self,
        focus: &Focus,
        job: &HostedFileJob,
    ) -> HostedResult<Option<HostedProposal>> {
        self.projects()
            .with_filters(filters(focus))
            .hosted_job_proposal(&focus.project_id, job)
            .await
    }

    async fn execute(
        &mut self,
        focus: &Focus,
        job: HostedFileJob,
        approved: bool,
    ) -> HostedResult<Value> {
        let mut approve = move |_: &HostedFileMutation| Ok(approved);
        self.projects()
            .with_filters(filters(focus))
            .execute_hosted_file_job(&focus.project_id, job, &mut approve, false)
            .await
    }
}

fn filters(focus: &Focus) -> crate::work::ProjectFilters {
    crate::work::ProjectFilters {
        personal: focus.team_id.is_none(),
        team_id: focus.team_id.clone(),
        include_archived: None,
    }
}

impl Client {
    /// Handle one job frame of the turn and send every frame that follows.
    ///
    /// # Errors
    /// Socket failures and cancellation.
    pub(in crate::client) async fn project_file_job_event(
        &mut self,
        ws: &mut super::super::transport::Socket,
        kind: &str,
        event: &Value,
        chat: &str,
        state: &mut FileJobState,
    ) -> Result<()> {
        let frames = job_frames(self, kind, event, chat, now_ms() / 1000, state).await?;
        for (name, payload) in frames {
            super::super::transport::send(ws, name, payload).await?;
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "project_file_jobs_tests.rs"]
mod tests;
