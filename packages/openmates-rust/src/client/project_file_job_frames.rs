//! Frame protocol of assistant Project file jobs: see `project_file_jobs`.
//! Rename and delete jobs (P11) use the same envelope, policy and approval.
use super::super::*;
use super::FileJobState;
use crate::work::{
    HostedFileError, HostedFileJob, HostedFileMutation, HostedProposal, HostedResult,
    ProjectRequesterError,
};
use std::time::Duration;

/// Finished operation ids remembered per turn (idempotency of repeated frames).
const MAX_FINISHED: usize = 256;
/// Largest `lease_expires_at` skew we accept (the server lease is 90 seconds).
const MAX_LEASE_SECONDS: u64 = 600;
/// Wire name of the commit job (`project_commit`): not a file mutation, it
/// records a native Project commit with [`JobRunner::commit`].
const COMMIT_OPERATION: &str = "commit";
/// Longest accepted commit message of the assistant tool (one line).
const COMMIT_MESSAGE_MAX_CHARS: usize = 200;
/// Wire name of the read-only `snapshot` job: all text files of the Project,
/// see [`super::snapshot`].
const SNAPSHOT_OPERATION: &str = "snapshot";
const OPERATIONS: [&str; 10] = [
    "list",
    "search",
    "read_text",
    "create_file",
    "update_file",
    "rename_file",
    "delete_file",
    "apply_changes",
    COMMIT_OPERATION,
    SNAPSHOT_OPERATION,
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
        ignored_read_approved: bool,
    ) -> HostedResult<Value>;
    /// Record a native Project commit authored by the assistant for `chat`.
    async fn commit(&mut self, focus: &Focus, chat: &str, message: String) -> HostedResult<Value>;
    /// Read-only snapshot (decrypted text and revision) of the Project's
    /// hosted text files under `prefix`; the body of [`super::snapshot`].
    async fn snapshot(&mut self, focus: &Focus, prefix: Option<String>) -> HostedResult<Value>;
    /// Relay the job to the remote source `source_id` (a Project folder on a
    /// machine); `mutation` is the validated proposal of a create/update.
    async fn execute_remote(
        &mut self,
        focus: &Focus,
        source_id: &str,
        job: &HostedFileJob,
        mutation: Option<HostedFileMutation>,
    ) -> std::result::Result<Value, ProjectRequesterError>;
    /// Commit the chat's worktree on the remote source `source_id`.
    async fn commit_remote(
        &mut self,
        focus: &Focus,
        source_id: &str,
        chat: &str,
        operation_id: &str,
        message: &str,
    ) -> std::result::Result<Value, ProjectRequesterError>;
}

/// The validated one-line message of a `commit` job.
///
/// # Errors
/// `invalid_commit_arguments` unless `arguments` is exactly `{message}` with a
/// non-empty single-line string of at most 200 characters.
pub(super) fn commit_message(arguments: &Value) -> HostedResult<String> {
    let invalid = || HostedFileError::Refused("invalid_commit_arguments");
    let object = arguments.as_object().ok_or_else(invalid)?;
    let message = object
        .get("message")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|m| {
            !m.is_empty()
                && m.chars().count() <= COMMIT_MESSAGE_MAX_CHARS
                && !m.chars().any(char::is_control)
        })
        .ok_or_else(invalid)?;
    if object.len() != 1 {
        return Err(invalid());
    }
    Ok(message.to_owned())
}

/// Result frames of a `commit` job: commit id, message and file count.
async fn commit_frames<R: JobRunner>(
    runner: &mut R,
    job: &Value,
    focus: &Focus,
    chat: &str,
    remaining: Duration,
    state: &mut FileJobState,
) -> Result<Vec<(&'static str, Value)>> {
    let operation = job["operation_id"].as_str().unwrap_or_default().to_owned();
    let message = match commit_message(&job["arguments"]) {
        Ok(message) => message,
        Err(error) => {
            state.finish(&operation);
            return Ok(vec![error_frame(job, &error)]);
        }
    };
    let outcome =
        crate::platform::time::timeout(remaining, runner.commit(focus, chat, message)).await;
    state.finish(&operation);
    match outcome {
        Err(_) => Ok(vec![result_frame(
            job,
            "failed",
            json!({"code": "lease_expired"}),
        )]),
        Ok(Err(HostedFileError::Core(Error::Cancelled))) => Err(Error::Cancelled),
        Ok(Err(error)) => Ok(vec![error_frame(job, &error)]),
        Ok(Ok(mut body)) => {
            body["source_id"] = Value::Null;
            state.notices.push(format!(
                "Project commit recorded: {}",
                body["message"].as_str().unwrap_or_default()
            ));
            Ok(vec![result_frame(job, "completed", body)])
        }
    }
}

/// Result frames of a `commit` job of a remote source: the host commits the
/// chat's worktree; the same waiting/failed mapping as other relayed jobs.
async fn remote_commit_frames<R: JobRunner>(
    runner: &mut R,
    job: &Value,
    focus: &Focus,
    chat: &str,
    source: &str,
    remaining: Duration,
    state: &mut FileJobState,
) -> Result<Vec<(&'static str, Value)>> {
    let operation = job["operation_id"].as_str().unwrap_or_default().to_owned();
    let message = match commit_message(&job["arguments"]) {
        Ok(message) => message,
        Err(error) => {
            state.finish(&operation);
            return Ok(vec![error_frame(job, &error)]);
        }
    };
    let outcome = crate::platform::time::timeout(
        remaining,
        runner.commit_remote(focus, source, chat, &operation, &message),
    )
    .await;
    let frames = remote_frames(job, source, outcome, None, state, &operation)?;
    if frames
        .first()
        .is_some_and(|(_, frame)| frame["status"] == "completed")
    {
        state
            .notices
            .push(format!("Project commit recorded on the machine: {message}"));
    }
    Ok(frames)
}

/// Result frames of a `snapshot` job: the bounded plaintext files.
async fn snapshot_frames<R: JobRunner>(
    runner: &mut R,
    job: &Value,
    focus: &Focus,
    remaining: Duration,
    state: &mut FileJobState,
) -> Result<Vec<(&'static str, Value)>> {
    let operation = job["operation_id"].as_str().unwrap_or_default().to_owned();
    let prefix = match super::snapshot::snapshot_prefix(&job["arguments"]) {
        Ok(prefix) => prefix,
        Err(error) => {
            state.finish(&operation);
            return Ok(vec![error_frame(job, &error)]);
        }
    };
    let outcome = crate::platform::time::timeout(remaining, runner.snapshot(focus, prefix)).await;
    state.finish(&operation);
    match outcome {
        Err(_) => Ok(vec![result_frame(
            job,
            "failed",
            json!({"code": "lease_expired"}),
        )]),
        Ok(Err(HostedFileError::Core(Error::Cancelled))) => Err(Error::Cancelled),
        Ok(Err(error)) => Ok(vec![error_frame(job, &error)]),
        Ok(Ok(body)) => Ok(vec![result_frame(job, "completed", body)]),
    }
}

impl FileJobState {
    pub(super) fn finish(&mut self, operation: &str) {
        if self.finished.len() < MAX_FINISHED {
            self.finished.insert(operation.to_owned());
        }
    }
}

/// Fail-closed answer of a shell whose privacy layer could not be installed:
/// claim an offered job (no content), then report the leased request as
/// `failed` with `pii_mapping_unavailable` instead of staying silent, so the
/// assistant learns within seconds that the file could not be read here.
pub(super) fn privacy_unavailable_frames(
    kind: &str,
    event: &Value,
    chat: &str,
    state: &mut FileJobState,
) -> Vec<(&'static str, Value)> {
    let Some(job) = identity(event, chat) else {
        return Vec::new();
    };
    let operation = job["operation_id"].as_str().unwrap_or_default().to_owned();
    if state.finished.contains(&operation) {
        return Vec::new();
    }
    if kind == "project_file_operation_available" {
        return vec![("project_file_operation_claim", scope(job))];
    }
    if !valid_lease(job) {
        return Vec::new();
    }
    state.finish(&operation);
    vec![result_frame(
        job,
        "failed",
        json!({"code": "pii_mapping_unavailable"}),
    )]
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

pub(super) fn scope(job: &Value) -> Value {
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

/// [`error_frame`] for a hosted job that failed, plus a local notice naming
/// the core error kind when the code alone (`client_execution_failed`) would
/// hide it. The kind is a fixed variant name (no path, content or server text),
/// so the shell may log it; it never goes on the wire.
fn failed_frame(
    job: &Value,
    error: &HostedFileError,
    state: &mut FileJobState,
) -> (&'static str, Value) {
    if let HostedFileError::Core(core) = error {
        state.notices.push(format!(
            "Project file {} failed: {} (core {:?})",
            job["operation"].as_str().unwrap_or("job"),
            error.code(),
            core
        ));
    }
    error_frame(job, error)
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

/// Restores placeholders with the chat's privacy layer (web) or, without one,
/// with the plain mappings of [`restore_write`] (CLI, unchanged).
fn restore_job(job: HostedFileJob, state: &FileJobState) -> Result<HostedFileJob> {
    match &state.privacy {
        Some(layer) => layer.restore(job),
        None => restore_write(job, &state.mappings.0),
    }
}

/// A created or updated Project file stores real details, like the web's
/// `projectFilePrivacy.restoreMutation`: the model only saw placeholders, so
/// every string argument except `path` is restored with the chat's mappings
/// (unknown tokens stay literal). A saved Project Memory is such a file.
/// Reads, renames and deletes are returned unchanged.
///
/// # Errors
/// `crate::privacy::restore_page` failures (conflicting or oversized mappings).
fn restore_write(mut job: HostedFileJob, mappings: &[Value]) -> Result<HostedFileJob> {
    let writes = matches!(job.operation.wire(), "create_file" | "update_file");
    if !writes || mappings.is_empty() {
        return Ok(job);
    }
    if let Value::Object(arguments) = &mut job.arguments {
        for (key, value) in arguments.iter_mut() {
            if key != "path" {
                restore_strings(value, mappings)?;
            }
        }
    }
    Ok(job)
}

fn restore_strings(value: &mut Value, mappings: &[Value]) -> Result<()> {
    match value {
        Value::String(text) => *text = crate::privacy::restore_page(text, mappings)?,
        Value::Array(items) => {
            for item in items {
                restore_strings(item, mappings)?;
            }
        }
        Value::Object(map) => {
            for item in map.values_mut() {
                restore_strings(item, mappings)?;
            }
        }
        _ => {}
    }
    Ok(())
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
    let remote_source = job["source_id"].as_str().map(str::to_owned);
    let is_commit = job["operation"] == COMMIT_OPERATION;
    let is_snapshot = job["operation"] == SNAPSHOT_OPERATION;
    if remote_source.is_some() && is_snapshot {
        // Snapshots of a machine source belong to its own executor.
        return Ok(vec![result_frame(
            job,
            "waiting_for_executor",
            json!({"reason": "source_offline"}),
        )]);
    }
    let hosted = if is_commit || is_snapshot {
        None
    } else {
        job_of(job)
    };
    let hosted = match hosted.map(|h| restore_job(h, state)) {
        Some(Err(error)) => {
            state.finish(&operation);
            // A privacy refusal keeps its own stable code (`pii_mapping_unavailable`,
            // `pii_mapping_ambiguous`, ...) instead of `client_execution_failed`.
            let refusal = match error {
                Error::Unavailable { code, .. } => HostedFileError::Refused(code),
                other => HostedFileError::Core(other),
            };
            return Ok(vec![error_frame(job, &refusal)]);
        }
        Some(Ok(h)) => Some(h),
        None => None,
    };
    if hosted.is_none() && !is_commit && !is_snapshot {
        return Ok(Vec::new());
    }
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
    let Some(hosted) = hosted else {
        if is_snapshot {
            return snapshot_frames(runner, job, &focus, remaining, state).await;
        }
        if let Some(source) = remote_source {
            return remote_commit_frames(runner, job, &focus, chat, &source, remaining, state)
                .await;
        }
        return commit_frames(runner, job, &focus, chat, remaining, state).await;
    };
    let proposal = match runner.proposal(&focus, &hosted).await {
        Ok(proposal) => proposal,
        Err(HostedFileError::Core(Error::Cancelled)) => return Err(Error::Cancelled),
        Err(error) => {
            state.finish(&operation);
            return Ok(vec![failed_frame(job, &error, state)]);
        }
    };
    let interactive = state.approvals.interactive;
    // Interactive shells: the user accepted exactly this proposal digest.
    let preapproved = interactive
        && proposal
            .as_ref()
            .is_some_and(|p| state.approvals.write_approved(&operation, &p.digest));
    if let Some(proposal) = proposal
        .as_ref()
        .filter(|p| p.requires_approval && !state.approve_writes && !preapproved)
    {
        if interactive {
            // Answer awaiting_approval only; the shell decides (see approvals).
            let shown = serde_json::to_value(&proposal.mutation).map_err(Error::from)?;
            state
                .approvals
                .prompt_write(job, scope(job), &proposal.digest, shown.clone());
            return Ok(vec![result_frame(
                job,
                "awaiting_approval",
                json!({"proposal_commitment": proposal.digest, "proposal": shown}),
            )]);
        }
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
    if let Some(source) = remote_source {
        let mutation = proposal.as_ref().map(|p| p.mutation.clone());
        let outcome = crate::platform::time::timeout(
            remaining,
            runner.execute_remote(&focus, &source, &hosted, mutation),
        )
        .await;
        return remote_frames(job, &source, outcome, proposal.as_ref(), state, &operation);
    }
    let read_key = (interactive && job["operation"] == "read_text")
        .then(|| hosted.arguments["path"].as_str())
        .flatten()
        .map(|path| (path.to_owned(), super::approvals::read_key(job, path)));
    let read_approved = read_key
        .as_ref()
        .is_some_and(|(_, key)| state.approvals.read_approved(key));
    // A cloud-command batch has no single proposal; its diff cards come from
    // the applied entries of the result (`record_batch_applied`).
    let batch = (hosted.operation == crate::work::HostedFileOperation::ApplyChanges)
        .then(|| hosted.clone());
    let outcome = crate::platform::time::timeout(
        remaining,
        runner.execute(
            &focus,
            hosted,
            state.approve_writes || preapproved,
            read_approved,
        ),
    )
    .await;
    if let (
        Ok(Err(HostedFileError::Refused("ignored_path_requires_approval"))),
        Some((path, key)),
    ) = (&outcome, read_key)
    {
        state
            .approvals
            .prompt_read(job, scope(job), key, path.as_str());
        return Ok(vec![result_frame(
            job,
            "awaiting_approval",
            json!({"reason": "ignored_path_requires_approval", "path": path}),
        )]);
    }
    state.finish(&operation);
    state.approvals.forget(&operation);
    let output = match outcome {
        Err(_) => {
            return Ok(vec![result_frame(
                job,
                "failed",
                json!({"code": "lease_expired"}),
            )]);
        }
        Ok(Err(HostedFileError::Core(Error::Cancelled))) => return Err(Error::Cancelled),
        Ok(Err(error)) => return Ok(vec![failed_frame(job, &error, state)]),
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
        state.approvals.record_applied(job, &proposal.mutation);
    }
    if let Some(batch) = &batch {
        record_batch_applied(job, batch, &body, state);
    }
    Ok(vec![result_frame(job, "completed", Value::Object(body))])
}

/// Record one applied notice and local diff card per file a cloud command's
/// `apply_changes` batch wrote (the shell shows them like assistant writes).
fn record_batch_applied(
    job: &Value,
    batch: &HostedFileJob,
    body: &serde_json::Map<String, Value>,
    state: &mut FileJobState,
) {
    let result = Value::Object(body.clone());
    for (mutation, created) in crate::work::applied_change_mutations(batch, &result) {
        state.notices.push(applied_notice(&mutation, created));
        state.approvals.record_applied(job, &mutation);
    }
}

/// The result frames of a job relayed to a remote source. An offline or
/// silent source keeps the job waiting (another executor, e.g. the web app,
/// or a later re-offer may run it); other refusals fail it with the host code.
fn remote_frames<T>(
    job: &Value,
    source: &str,
    outcome: std::result::Result<std::result::Result<Value, ProjectRequesterError>, T>,
    proposal: Option<&HostedProposal>,
    state: &mut FileJobState,
    operation: &str,
) -> Result<Vec<(&'static str, Value)>> {
    let output = match outcome {
        Err(_) => {
            state.finish(operation);
            return Ok(vec![result_frame(
                job,
                "failed",
                json!({"code": "lease_expired"}),
            )]);
        }
        Ok(Err(ProjectRequesterError::Core(Error::Cancelled))) => return Err(Error::Cancelled),
        Ok(Err(ProjectRequesterError::Remote { code, .. }))
            if code == "source_offline" || code == "protocol_timeout" =>
        {
            return Ok(vec![result_frame(
                job,
                "waiting_for_executor",
                json!({"reason": code}),
            )]);
        }
        Ok(Err(ProjectRequesterError::Remote { code, .. })) => {
            state.finish(operation);
            return Ok(vec![result_frame(
                job,
                "failed",
                json!({"code": remote_code(&code)}),
            )]);
        }
        Ok(Err(ProjectRequesterError::Core(error))) => {
            state.finish(operation);
            return Ok(vec![error_frame(job, &HostedFileError::Core(error))]);
        }
        Ok(Ok(output)) => output,
    };
    state.finish(operation);
    let mut body = match output {
        Value::Object(map) => map,
        other => serde_json::Map::from_iter([("value".to_owned(), other)]),
    };
    body.insert("source_id".into(), json!(source));
    if let Some(proposal) = proposal {
        body.insert("proposal_commitment".into(), json!(proposal.digest));
        let created = body
            .get("created")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        state
            .notices
            .push(applied_notice(&proposal.mutation, created));
        state.approvals.record_applied(job, &proposal.mutation);
    }
    Ok(vec![result_frame(job, "completed", Value::Object(body))])
}

/// A host code safe to forward as the job's failure code (bounded, ASCII).
fn remote_code(code: &str) -> &str {
    if !code.is_empty()
        && code.len() <= 64
        && code.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
    {
        code
    } else {
        "remote_operation_failed"
    }
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
        ignored_read_approved: bool,
    ) -> HostedResult<Value> {
        let mut approve = move |_: &HostedFileMutation| Ok(approved);
        self.projects()
            .with_filters(filters(focus))
            .execute_hosted_file_job(&focus.project_id, job, &mut approve, ignored_read_approved)
            .await
    }

    async fn commit(&mut self, focus: &Focus, chat: &str, message: String) -> HostedResult<Value> {
        use crate::work::{ProjectCommitAuthor, ProjectCommitCreate};
        let input = ProjectCommitCreate {
            message,
            author: ProjectCommitAuthor::Assistant,
            chat_id: Some(chat.to_owned()),
            files: Vec::new(),
            commit_id: None,
            created_at: None,
        };
        // An empty file list snapshots every hosted file at its current head.
        let commit = match self
            .projects()
            .with_filters(filters(focus))
            .create_commit(&focus.project_id, input)
            .await
        {
            Ok(commit) => commit,
            Err(Error::Invalid(_)) => return Err(HostedFileError::Refused("nothing_to_commit")),
            Err(error) => return Err(error.into()),
        };
        Ok(
            // `short_id` is the 7-character form the Project Timeline shows; the
            // tool description tells the model to quote only it to the user.
            json!({"commit_id": commit.commit_id, "short_id": short_commit_id(&commit.commit_id),
            "message": commit.message, "file_count": commit.files.len()}),
        )
    }

    async fn commit_remote(
        &mut self,
        focus: &Focus,
        source_id: &str,
        chat: &str,
        operation_id: &str,
        message: &str,
    ) -> std::result::Result<Value, ProjectRequesterError> {
        self.projects()
            .with_filters(filters(focus))
            .remote_commit_job(&focus.project_id, source_id, chat, operation_id, message)
            .await
    }

    async fn execute_remote(
        &mut self,
        focus: &Focus,
        source_id: &str,
        job: &HostedFileJob,
        mutation: Option<HostedFileMutation>,
    ) -> std::result::Result<Value, ProjectRequesterError> {
        self.projects()
            .with_filters(filters(focus))
            .remote_file_job(
                &focus.project_id,
                source_id,
                &job.chat_id,
                job.operation,
                &job.arguments,
                mutation,
            )
            .await
    }

    async fn snapshot(&mut self, focus: &Focus, prefix: Option<String>) -> HostedResult<Value> {
        let mut source = ClientSnapshot {
            client: self,
            focus,
        };
        super::snapshot::build_snapshot(&mut source, prefix.as_deref()).await
    }
}

/// [`super::snapshot::SnapshotSource`] over the real Project: listing and
/// reading reuse the hosted `list` and `read_text` paths (policy, decryption).
struct ClientSnapshot<'a> {
    client: &'a mut Client,
    focus: &'a Focus,
}

impl super::snapshot::SnapshotSource for ClientSnapshot<'_> {
    async fn paths(&mut self) -> HostedResult<Vec<String>> {
        let listed = self
            .client
            .projects()
            .with_filters(filters(self.focus))
            .hosted_files_list(&self.focus.project_id, None)
            .await?;
        Ok(listed["entries"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or_default()
            .iter()
            .filter(|entry| entry["kind"] == "file")
            .filter_map(|entry| entry["path"].as_str().map(str::to_owned))
            .collect())
    }

    async fn read(&mut self, path: &str) -> HostedResult<Option<(String, Value)>> {
        let read = self
            .client
            .projects()
            .with_filters(filters(self.focus))
            .hosted_file_read(&self.focus.project_id, path, false)
            .await;
        match read {
            Ok(file) => Ok(file["content"]
                .as_str()
                .map(|code| (code.to_owned(), file["revision"].clone()))),
            Err(HostedFileError::Refused("unsupported_file_content")) => Ok(None),
            Err(error) => Err(error),
        }
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

/// First 7 characters of a commit id (the Timeline's short form).
fn short_commit_id(commit_id: &str) -> String {
    commit_id.chars().take(7).collect()
}
