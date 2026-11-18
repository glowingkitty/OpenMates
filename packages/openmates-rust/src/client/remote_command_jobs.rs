//! Origin side of assistant remote commands during a turn (`code.run` on a
//! Project folder of one of the user's machines): review -> approval ->
//! sealed `remote_command_prepare`, then the host's encrypted events are folded
//! into one origin completion the server resumes the turn with. Shared core;
//! the review policy, digest and output rules live in `remote_command_review`.
//! Mirrors the web `browserRemoteCommandClient.ts` (review/event/response).
//! spec: specifications/features/projects (projects.creation.machine-folder).
use super::plaintext::Wipe;
use crate::crypto::{self, Key};
use crate::remote_command_review::{self as review, OutputState, RemoteCommandReview};
use crate::{Error, Result};
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// Socket capability that makes the server deliver remote command reviews
/// and events to this connection and accept its decisions.
pub(super) const REMOTE_COMMAND_JOBS_CAPABILITY: &str = "remote_command_jobs";

/// Server frames this executor handles during a turn.
pub(super) fn is_frame(kind: &str) -> bool {
    matches!(
        kind,
        "remote_command_review_required"
            | "remote_command_event"
            | "remote_command_prepared"
            | "remote_command_rejected"
            | "remote_command_error"
    )
}

/// One approved or pending command of this turn. The Project key opens the
/// host's events; it is zeroized when the run is dropped.
struct Run {
    review: RemoteCommandReview,
    output: OutputState,
    key: Key,
    completed: bool,
}

/// Remote commands of one turn, keyed by execution id.
#[derive(Default)]
pub(super) struct RemoteCommandState {
    /// The user approved commands for this turn (`--auto-approve`); without
    /// it every review is rejected, never run silently.
    pub(super) approve: bool,
    runs: BTreeMap<String, Run>,
    notices: Vec<String>,
}

impl std::fmt::Debug for RemoteCommandState {
    // Runs hold the Project key and command text: only counts are shown.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RemoteCommandState")
            .field("approve", &self.approve)
            .field("runs", &self.runs.len())
            .field("notices", &self.notices.len())
            .finish()
    }
}

impl Clone for RemoteCommandState {
    // A cloned turn observation never carries keys or runs of the original.
    fn clone(&self) -> Self {
        Self {
            approve: self.approve,
            runs: BTreeMap::new(),
            notices: self.notices.clone(),
        }
    }
}

impl RemoteCommandState {
    /// Status lines for the shell since the last call.
    pub(super) fn take_notices(&mut self) -> Vec<String> {
        std::mem::take(&mut self.notices)
    }
}

impl Wipe for RemoteCommandState {
    fn wipe(&mut self) {
        self.runs.clear();
        self.notices.clear();
    }
}

/// What the executor needs from the client: the Project key of a Project in
/// the chat's focus scope.
pub(super) trait CommandKeys {
    /// The key of Project `project_id` as seen from chat `chat`'s focus.
    async fn command_project_key(&mut self, chat: &str, project_id: &str) -> Result<Key>;
}

fn text<'a>(value: &'a Value, key: &str) -> &'a str {
    value.get(key).and_then(Value::as_str).unwrap_or("")
}

/// The frames to send for one server frame of chat `chat` at `now` (unix
/// seconds). A review of another chat, an expired one or one beyond the open
/// window is ignored like the web client does.
///
/// # Errors
/// `Protocol` for an event that does not match its run or fails to open
/// (wrong key, identity mismatch); core errors while reading the Project key.
pub(super) async fn command_frames<K: CommandKeys>(
    keys: &mut K,
    kind: &str,
    event: &Value,
    chat: &str,
    now: u64,
    state: &mut RemoteCommandState,
) -> Result<Vec<(&'static str, Value)>> {
    match kind {
        "remote_command_review_required" => review_frames(keys, event, chat, now, state).await,
        "remote_command_event" => event_frames(event, state),
        _ => {
            response_notice(kind, event, state);
            Ok(Vec::new())
        }
    }
}

async fn review_frames<K: CommandKeys>(
    keys: &mut K,
    event: &Value,
    chat: &str,
    now: u64,
    state: &mut RemoteCommandState,
) -> Result<Vec<(&'static str, Value)>> {
    let Ok(parsed) = review::parse_review(&event.to_string()) else {
        return Ok(Vec::new());
    };
    if parsed
        .check_acceptable(chat, now, state.runs.len())
        .is_err()
        || state.runs.contains_key(&parsed.execution_id)
    {
        return Ok(Vec::new());
    }
    let shown = parsed.command.argv.join(" ");
    if !state.approve {
        state.notices.push(format!(
            "Machine command not run (needs approval, use --auto-approve): {shown}"
        ));
        return Ok(vec![("remote_command_reject", parsed.reject_payload())]);
    }
    let key = keys.command_project_key(chat, &parsed.project_id).await?;
    let canonical = parsed.canonical_portable_request();
    let digest = review::request_digest(&canonical, &key[..]).map_err(|_| Error::Crypto)?;
    let sealed = crypto::encrypt_combined(&canonical, &key)?;
    let payload = parsed.prepare_payload(&sealed, &digest);
    state
        .notices
        .push(format!("Running on the machine: {shown}"));
    state.runs.insert(
        parsed.execution_id.clone(),
        Run {
            review: parsed,
            output: OutputState::new(),
            key,
            completed: false,
        },
    );
    Ok(vec![("remote_command_prepare", payload)])
}

fn event_frames(
    event: &Value,
    state: &mut RemoteCommandState,
) -> Result<Vec<(&'static str, Value)>> {
    let Some(run) = state.runs.get_mut(text(event, "execution_id")) else {
        return Ok(Vec::new());
    };
    let r = &run.review;
    if text(event, "chat_id") != r.chat_id
        || text(event, "project_id") != r.project_id
        || text(event, "source_id") != r.source_id
    {
        return Err(Error::Protocol);
    }
    let sequence = event["sequence"].as_i64().ok_or(Error::Protocol)?;
    let (kind, status) = (text(event, "event_kind"), text(event, "status"));
    let opened = crypto::decrypt_combined(text(event, "encrypted_event"), &run.key)
        .map_err(|_| Error::Protocol)?;
    let payload: Value = serde_json::from_str(&opened).map_err(|_| Error::Protocol)?;
    // The sealed body must name the same execution, sequence, kind and status
    // as the routing envelope, so the server cannot relabel host output.
    if text(&payload, "execution_id") != r.execution_id
        || payload["sequence"].as_i64() != Some(sequence)
        || text(&payload, "event_kind") != kind
        || text(&payload, "status") != status
    {
        return Err(Error::Protocol);
    }
    let output = payload
        .get("text")
        .or_else(|| payload.get("error_message"))
        .and_then(Value::as_str);
    if run
        .output
        .apply_event(kind, status, sequence, output)
        .is_err()
    {
        // A replayed or stale sequence changes nothing.
        return Ok(Vec::new());
    }
    if kind != "terminal" || run.completed {
        return Ok(Vec::new());
    }
    run.completed = true;
    let completion = run.output.completion(&run.review);
    state.notices.push(format!("Machine command {status}"));
    Ok(vec![("remote_command_origin_completion", completion)])
}

fn response_notice(kind: &str, event: &Value, state: &mut RemoteCommandState) {
    if !state.runs.contains_key(text(event, "execution_id")) {
        return;
    }
    match kind {
        "remote_command_error" => {
            let code = text(event, "code");
            state.notices.push(format!(
                "Machine command failed: {}",
                if code.is_empty() {
                    "remote_command_failed"
                } else {
                    code
                }
            ));
        }
        "remote_command_rejected" => state.notices.push("Machine command rejected".into()),
        _ => {}
    }
}

// Native only, like the remote file jobs it shares the Project resolver with.
#[cfg(all(feature = "workflow-yaml", unix))]
impl CommandKeys for super::Client {
    async fn command_project_key(&mut self, chat: &str, project_id: &str) -> Result<Key> {
        let focus = self.projects().active_focus(chat).await?;
        // Only the Project the chat is focused on may receive a command.
        if focus["project_id"].as_str() != Some(project_id) {
            return Err(Error::Forbidden);
        }
        let filters = crate::work::ProjectFilters {
            personal: focus["team_id"].as_str().is_none(),
            team_id: focus["team_id"].as_str().map(str::to_owned),
            include_archived: None,
        };
        self.projects()
            .with_filters(filters)
            .project_key_for_command(project_id)
            .await
    }
}

// Native only, like the remote file jobs it shares the Project resolver with.
#[cfg(all(feature = "workflow-yaml", unix))]
impl super::Client {
    /// Handle one remote command frame of the turn and send what follows.
    ///
    /// # Errors
    /// Socket failures and the errors of [`command_frames`].
    pub(super) async fn remote_command_event(
        &mut self,
        ws: &mut super::transport::Socket,
        kind: &str,
        event: &Value,
        chat: &str,
        state: &mut RemoteCommandState,
    ) -> Result<()> {
        let now = super::now_ms() / 1000;
        for (name, payload) in command_frames(self, kind, event, chat, now, state).await? {
            super::transport::send(ws, name, payload).await?;
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "remote_command_jobs_tests.rs"]
mod tests;
