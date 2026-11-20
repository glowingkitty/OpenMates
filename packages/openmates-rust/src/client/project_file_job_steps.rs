//! Public step/decide API of the Project file-job protocol for shells that own
//! their WebSocket (the web Worker binding). Shared client core; state is kept
//! per chat and bounded, frames are returned instead of sent on the core's own
//! socket. Native turns keep using `project_file_job_event`.
use super::super::*;
use super::frames::job_frames;
use super::ProjectFilePrivacyBlob;
use serde::Serialize;

/// One frame the shell must send over its WebSocket.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct ProjectFileJobFrame {
    /// Event name, e.g. `project_file_operation_result`.
    pub name: String,
    /// Event payload.
    pub payload: Value,
}

/// Outcome of one job step or decision.
///
/// `prompts` are `{kind:"write", operation_id, chat_id, project_id,
/// proposal_commitment, mutation}` or `{kind:"read", operation_id, chat_id,
/// project_id, source_id, path}`; `applied` are `{project_id, chat_id,
/// operation, path, new_path?, mutation}` (the restored mutation for the
/// local diff card; it never leaves the device).
#[derive(Clone, Debug, Default, Serialize, PartialEq)]
pub struct ProjectFileJobStep {
    /// Frames to send, in order.
    pub frames: Vec<ProjectFileJobFrame>,
    /// Approval prompts for the user.
    pub prompts: Vec<Value>,
    /// Completed changes the shell should record and refresh.
    pub applied: Vec<Value>,
    /// One-line text notices.
    pub notices: Vec<String>,
    /// Sealed privacy mappings minted by this step. The shell MUST store the
    /// ciphertext (web: localStorage key `PROJECT_FILE_PRIVACY_PREFIX +
    /// JSON.stringify([chat_id, project_id])`) BEFORE it sends `frames`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub privacy: Option<ProjectFilePrivacyBlob>,
}

fn frame((name, payload): (&'static str, Value)) -> ProjectFileJobFrame {
    ProjectFileJobFrame {
        name: name.to_owned(),
        payload,
    }
}

impl Client {
    /// Handle one `project_file_operation_available` / `_request` frame without
    /// sending anything. `interactive` makes always-ask writes and ignored reads
    /// wait for [`Client::project_file_job_decide`]. Malformed frames yield an
    /// empty step.
    ///
    /// Interactive (web) steps fail closed: without a privacy layer installed by
    /// [`Client::project_file_job_set_privacy`] for this chat, nothing runs, so
    /// a shell that forgot it or a Client that dropped the chat can never send
    /// unredacted file contents.
    ///
    /// # Errors
    /// `pii_mapping_unavailable` for an interactive step without a privacy
    /// layer; cancellation. Executor refusals become result frames.
    pub async fn project_file_job_step(
        &mut self,
        kind: &str,
        event: &Value,
        interactive: bool,
    ) -> Result<ProjectFileJobStep> {
        let Some(chat) = event["chat_id"].as_str().map(str::to_owned) else {
            return Ok(ProjectFileJobStep::default());
        };
        let mut state = self.file_job_chats.take(&chat, interactive);
        if interactive && state.privacy.is_none() {
            self.file_job_chats.put(&chat, state);
            return Err(Error::Unavailable {
                code: "pii_mapping_unavailable",
                reason: "The chat's Project file privacy layer is not installed.",
            });
        }
        let frames = job_frames(self, kind, event, &chat, now_ms() / 1000, &mut state).await;
        let step = frames.map(|frames| {
            let mut frames: Vec<ProjectFileJobFrame> = frames.into_iter().map(frame).collect();
            let privacy = state
                .privacy
                .as_mut()
                .and_then(|layer| layer.redact_frames(&mut frames));
            ProjectFileJobStep {
                frames,
                prompts: state.approvals.take_prompts(),
                applied: state.approvals.take_applied(),
                notices: state.take_notices(),
                privacy,
            }
        });
        self.file_job_chats.put(&chat, state);
        step
    }

    /// Apply the user's answer to a pending prompt. Accept returns a `claim`
    /// (a new lease is mandatory), decline a `reject`; an unknown operation
    /// yields an empty step.
    ///
    /// # Errors
    /// None today; kept fallible for the binding contract.
    pub async fn project_file_job_decide(
        &mut self,
        chat_id: &str,
        operation_id: &str,
        accept: bool,
    ) -> Result<ProjectFileJobStep> {
        let mut state = self.file_job_chats.take(chat_id, true);
        let mut step = ProjectFileJobStep::default();
        if let Some((name, scope_value, finished)) = state.approvals.decide(operation_id, accept) {
            if finished {
                state.finish(operation_id);
            }
            step.frames.push(frame((name, scope_value)));
        }
        self.file_job_chats.put(chat_id, state);
        Ok(step)
    }

    /// Set the chat's privacy mappings used to restore file writes.
    pub fn project_file_job_set_mappings(&mut self, chat_id: &str, mappings: &[Value]) {
        let mut state = self.file_job_chats.take(chat_id, true);
        state.set_mappings(mappings);
        self.file_job_chats.put(chat_id, state);
    }

    /// Turns on web-mode privacy for a chat's Project. The chat key is resolved
    /// by the core itself (never passed in, never logged). `sealed` is the blob
    /// the shell stored from an earlier step; `memories` are the user's privacy
    /// settings. Known chat mappings (see [`Client::project_file_job_set_mappings`])
    /// are merged in.
    ///
    /// # Errors
    /// `pii_mapping_unavailable` (undecryptable blob or one of another
    /// chat/project), `pii_mapping_limit`, or the chat-key resolution errors.
    /// On error no layer is installed: the shell must stop (fail closed) and not
    /// feed this chat's file jobs, or results would not be redacted.
    pub async fn project_file_job_set_privacy(
        &mut self,
        chat_id: &str,
        project_id: &str,
        enabled: bool,
        memories: Vec<Value>,
        sealed: Option<&str>,
    ) -> Result<()> {
        let key = self.work_chat_key(chat_id).await?;
        let mut state = self.file_job_chats.take(chat_id, true);
        let layer = super::privacy::PrivacyLayer::open(
            chat_id,
            project_id,
            enabled,
            memories,
            sealed,
            &state.mappings.0,
            key,
        );
        let outcome = layer.map(|layer| state.privacy = Some(layer));
        self.file_job_chats.put(chat_id, state);
        outcome
    }
}
