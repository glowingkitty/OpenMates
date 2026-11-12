//! WebSocket side of assistant-initiated Project creation
//! (`openmates.project_create_request` v1, shared core; every shell reuses it).
//!
//! The saved-turn receive loop hands `project_create_requested`,
//! `project_create_confirmed` and `project_create_error` frames of its chat to
//! this module. The REST/crypto work is `work::Projects::create_for_request`.
//! Invariants: one report per request id (duplicate events are ignored); every
//! request that is not created ends in a `failed` report with an error code; a
//! server error after creation rolls the Project back before reporting `failed`.
//! Contract: `docs/plans/cloud-project-development/contracts/project-create-request.md`.
use super::plaintext::Wipe;
use super::transport::{Socket, send};
use super::*;
use crate::work::{
    CreatedProjectRecord, ProjectCreateLocation, ProjectCreateRefusal, ProjectCreateRequest,
    ProjectFilters,
};

#[path = "project_create_machine.rs"]
mod machine;
pub use machine::MachineProjectDecision;

/// WebSocket and turn capability that opts into `project_create_requested`.
pub(super) const PROJECT_CREATE_CAPABILITY: &str = "project_create_requests";

/// Requests tracked per turn; the server allows one pending request per chat.
const MAX_REQUESTS: usize = 8;

/// Terminal state of one request as the shells render it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Status {
    Created,
    Failed,
    Undone,
    /// Machine request waiting for the user's decision; nothing exists yet.
    ConfirmationRequired,
    /// The user declined creating the Project on their machine.
    Declined,
}

impl Status {
    fn wire(self) -> &'static str {
        match self {
            Self::Created => "created",
            Self::Failed => "failed",
            Self::Undone => "undone",
            Self::ConfirmationRequired => "confirmation_required",
            Self::Declined => "declined",
        }
    }
}

#[derive(Clone, Debug)]
struct Entry {
    status: Status,
    record: Option<CreatedProjectRecord>,
    error_code: Option<String>,
    confirmed: bool,
    // A `failed` report follows a server error at most once, so a rejected
    // failure report can never start a loop.
    failure_reported: bool,
    /// The chat's encrypted active focus now names this Project's default focus.
    focus_persisted: bool,
    /// The validated machine request, kept until the user decides.
    request: Option<ProjectCreateRequest>,
    /// Folder created on the machine (`sourceId`, `path`, `folderName`).
    machine: Option<Value>,
}

impl Entry {
    fn new(status: Status) -> Self {
        Self {
            status,
            record: None,
            error_code: None,
            confirmed: false,
            failure_reported: false,
            focus_persisted: false,
            request: None,
            machine: None,
        }
    }
}

/// Requests handled during one send, keyed by request id (idempotency).
#[derive(Clone, Debug, Default)]
pub(super) struct ProjectCreateState {
    entries: BTreeMap<String, Entry>,
    /// Assistant Project file jobs of this turn (`project_file_jobs`).
    pub(super) file_jobs: super::project_file_jobs::FileJobState,
    /// Embed adoption reports of this turn (P11, `project_embed_adoption`).
    adoptions: Vec<Value>,
    /// Assistant Memory write jobs of this turn (`memory_write_jobs`).
    pub(super) memory_jobs: super::memory_write_jobs::MemoryJobState,
    /// The shell's answer to a machine confirmation card of this turn.
    pub(super) machine_decision: Option<MachineProjectDecision>,
}

impl ProjectCreateState {
    /// The "created Project" cards of this turn, camelCase JSON for the shells.
    pub(super) fn cards(&self) -> Vec<Value> {
        self.entries
            .iter()
            .map(|(request_id, entry)| {
                let mut card = entry
                    .record
                    .as_ref()
                    .and_then(|record| serde_json::to_value(record).ok())
                    .unwrap_or_else(|| json!({"requestId": request_id}));
                if let Some(request) = &entry.request {
                    card["name"] = json!(request.name);
                    card["kind"] = json!(request.kind);
                    card["chatId"] = json!(request.chat_id);
                    card["location"] = json!("machine");
                    card["machineHint"] = json!(request.machine_hint);
                }
                if let Some(machine) = &entry.machine {
                    card["machine"] = machine.clone();
                }
                card["status"] = json!(entry.status.wire());
                card["confirmed"] = json!(entry.confirmed);
                if let Some(code) = &entry.error_code {
                    card["errorCode"] = json!(code);
                }
                card["undoAvailable"] =
                    json!(entry.status == Status::Created && entry.machine.is_none());
                card["focusPersisted"] = json!(entry.focus_persisted);
                card
            })
            .collect()
    }

    /// Mark the created card whose default focus the chat now persists.
    ///
    /// Call only after `persist_focus_event` sent `update_encrypted_active_focus_id`
    /// for a `focus_mode_activated` frame. That frame, which the server publishes
    /// after verifying a `created` report, is the single writer of the chat's
    /// active focus for an assistant-created Project; creation itself never
    /// writes it, so there is no second write to race with.
    pub(super) fn mark_focus_persisted(&mut self, focus_id: &str) {
        for entry in self.entries.values_mut() {
            if entry.status == Status::Created
                && entry
                    .record
                    .as_ref()
                    .is_some_and(|record| record.focus_id == focus_id)
            {
                entry.focus_persisted = true;
            }
        }
    }
}

impl ProjectCreateState {
    /// Record one embed adoption report (adopted or failed, with its code).
    #[cfg_attr(not(all(feature = "workflow-yaml", unix)), allow(dead_code))]
    pub(super) fn push_adoption(&mut self, row: Value) {
        self.adoptions.push(row);
    }

    /// The embed adoption reports of this turn, for the send outcome.
    pub(super) fn adoptions(&self) -> Vec<Value> {
        self.adoptions.clone()
    }
}

impl Wipe for ProjectCreateState {
    fn wipe(&mut self) {
        // Records hold the decrypted Project name; reports hold Project paths.
        self.entries.clear();
        self.machine_decision = None;
        self.file_jobs.clear();
        self.adoptions.clear();
        self.memory_jobs.clear();
    }
}

/// `error_code` for the report: contract pattern `^[A-Z0-9_]{1,64}$`.
fn failure_code(error: Error) -> &'static str {
    match error {
        Error::Crypto => "PROJECT_KEY_WRAP_FAILED",
        Error::Forbidden => "PROJECT_CREATE_FORBIDDEN",
        Error::Offline => "PROJECT_CREATE_OFFLINE",
        Error::Authentication | Error::Expired => "PROJECT_CREATE_UNAUTHENTICATED",
        _ => "PROJECT_CREATE_FAILED",
    }
}

/// Server error codes are echoed into `error_code` only when well formed.
fn echo_code(code: &str) -> String {
    let valid = !code.is_empty()
        && code.len() <= 64
        && code
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_');
    if valid {
        code.to_owned()
    } else {
        "PROJECT_CREATE_FAILED".to_owned()
    }
}

fn report(chat: &str, request: &str, status: Status, code: Option<&str>) -> Value {
    let mut payload = json!({"chat_id": chat, "request_id": request, "status": status.wire()});
    if let Some(code) = code {
        payload["error_code"] = json!(code);
    }
    payload
}

impl Client {
    /// Route one request/reply frame of the turn's chat and send what follows.
    ///
    /// # Errors
    /// Socket failures and more than [`MAX_REQUESTS`] distinct requests.
    pub(super) async fn project_create_event(
        &mut self,
        ws: &mut Socket,
        kind: &str,
        event: &Value,
        chat: &str,
        state: &mut ProjectCreateState,
    ) -> Result<()> {
        #[cfg(all(feature = "workflow-yaml", unix))]
        if kind.starts_with("project_file_operation_") {
            return self
                .project_file_job_event(ws, kind, event, chat, &mut state.file_jobs)
                .await;
        }
        #[cfg(all(feature = "workflow-yaml", unix))]
        if kind == super::project_embed_adoption::TURN_ADOPTION_KIND {
            return self.adopt_turn_embeds(event, chat, state).await;
        }
        // Memory write jobs share this turn phase so the owned driver needs no new call.
        if super::memory_write_jobs::is_job_frame(kind) {
            // Boxed: keeps this rare path out of every send future's stack frame.
            return Box::pin(self.memory_write_job_event(
                ws,
                kind,
                event,
                chat,
                &mut state.memory_jobs,
            ))
            .await;
        }
        let outgoing = self
            .project_create_report(kind, event, chat, now_ms() / 1000, state)
            .await?;
        if let Some(payload) = outgoing {
            send(ws, "project_create_result", payload).await?;
        }
        Ok(())
    }

    /// The `project_create_result` payload to send for `event`, if any.
    ///
    /// `project_create_requested` creates the Project and activates its focus
    /// (`created`), or reports `failed` with a code; a duplicate request id
    /// returns `None`. `project_create_confirmed` marks the card confirmed.
    /// `project_create_error` rolls a created Project back and reports `failed`
    /// with the server's code, except for expiry/stale which the server would
    /// reject again.
    pub(super) async fn project_create_report(
        &mut self,
        kind: &str,
        event: &Value,
        chat: &str,
        now_s: u64,
        state: &mut ProjectCreateState,
    ) -> Result<Option<Value>> {
        match kind {
            "project_create_requested" => {
                self.project_create_requested(event, chat, now_s, state)
                    .await
            }
            "project_create_confirmed" => {
                if let Some(entry) = state.entries.get_mut(text(event, "request_id")) {
                    entry.confirmed = true;
                }
                Ok(None)
            }
            "project_create_error" => self.project_create_rejected(event, chat, state).await,
            _ => Ok(None),
        }
    }

    async fn project_create_requested(
        &mut self,
        event: &Value,
        chat: &str,
        now_s: u64,
        state: &mut ProjectCreateState,
    ) -> Result<Option<Value>> {
        let request = match ProjectCreateRequest::parse(event, chat, now_s) {
            Ok(request) => request,
            Err((Some(id), refusal)) => return Self::refused(&id, chat, refusal, state),
            // Without a usable request id there is nothing to report against.
            Err((None, _)) => return Ok(None),
        };
        if state.entries.contains_key(&request.request_id) {
            return Ok(None);
        }
        if state.entries.len() >= MAX_REQUESTS {
            return Err(Error::Protocol);
        }
        if request.location == ProjectCreateLocation::Machine {
            return self.machine_request_received(request, chat, state).await;
        }
        let filters = ProjectFilters {
            personal: request.team_id.is_none(),
            team_id: request.team_id.clone(),
            include_archived: None,
        };
        let created = self
            .projects()
            .with_filters(filters)
            .create_for_request(&request)
            .await;
        let entry = match created {
            Ok(record) => Entry {
                record: Some(record),
                ..Entry::new(Status::Created)
            },
            Err(Error::Cancelled) => return Err(Error::Cancelled),
            Err(error) => Entry {
                error_code: Some(failure_code(error).to_owned()),
                failure_reported: true,
                ..Entry::new(Status::Failed)
            },
        };
        let payload = match (&entry.record, &entry.error_code) {
            (Some(record), _) => {
                let mut payload = report(chat, &request.request_id, Status::Created, None);
                payload["project_id"] = json!(record.project_id);
                payload["focus_id"] = json!(record.focus_id);
                payload
            }
            (None, code) => report(chat, &request.request_id, Status::Failed, code.as_deref()),
        };
        state.entries.insert(request.request_id, entry);
        Ok(Some(payload))
    }

    fn refused(
        id: &str,
        chat: &str,
        refusal: ProjectCreateRefusal,
        state: &mut ProjectCreateState,
    ) -> Result<Option<Value>> {
        if state.entries.contains_key(id) {
            return Ok(None);
        }
        if state.entries.len() >= MAX_REQUESTS {
            return Err(Error::Protocol);
        }
        state.entries.insert(
            id.to_owned(),
            Entry {
                error_code: Some(refusal.code().to_owned()),
                failure_reported: true,
                ..Entry::new(Status::Failed)
            },
        );
        Ok(Some(report(chat, id, Status::Failed, Some(refusal.code()))))
    }

    async fn project_create_rejected(
        &mut self,
        event: &Value,
        chat: &str,
        state: &mut ProjectCreateState,
    ) -> Result<Option<Value>> {
        let request = text(event, "request_id").to_owned();
        let code = echo_code(text(event, "code"));
        let Some(entry) = state.entries.get_mut(&request) else {
            return Ok(None);
        };
        if entry.failure_reported || entry.status != Status::Created {
            return Ok(None);
        }
        entry.failure_reported = true;
        // The server did not accept the Project: remove it so no orphan stays,
        // then let the turn answer in the chat via a `failed` report.
        let record = entry.record.take();
        entry.status = Status::Failed;
        entry.error_code = Some(code.clone());
        if let Some(record) = record {
            let filters = ProjectFilters {
                personal: record.team_id.is_none(),
                team_id: record.team_id.clone(),
                include_archived: None,
            };
            self.projects()
                .with_filters(filters)
                .undo_created(&record.chat_id)
                .await?;
        }
        if matches!(
            code.as_str(),
            "PROJECT_CREATE_REQUEST_EXPIRED" | "PROJECT_CREATE_REQUEST_STALE"
        ) {
            return Ok(None);
        }
        Ok(Some(report(chat, &request, Status::Failed, Some(&code))))
    }

    /// The report that undoes a Project whose request is still open: deletes the
    /// Project and returns the `undone` payload. A confirmed request needs no
    /// message (the server cleared it), so callers then use
    /// `Projects::undo_created` alone and this returns `None`.
    ///
    /// # Errors
    /// Transport failures of the undo calls.
    // Interactive shells undo while their turn is open; the one-shot CLI undoes
    // after the turn through `Projects::undo_created`, so only tests call it today.
    #[cfg_attr(not(test), allow(dead_code))]
    pub(super) async fn project_create_undo_report(
        &mut self,
        chat: &str,
        request_id: &str,
        state: &mut ProjectCreateState,
    ) -> Result<Option<Value>> {
        let Some(entry) = state.entries.get_mut(request_id) else {
            return Ok(None);
        };
        let Some(record) = entry
            .record
            .clone()
            .filter(|_| entry.status == Status::Created && entry.machine.is_none())
        else {
            return Ok(None);
        };
        let filters = ProjectFilters {
            personal: record.team_id.is_none(),
            team_id: record.team_id.clone(),
            include_archived: None,
        };
        self.projects()
            .with_filters(filters)
            .undo_created(&record.chat_id)
            .await?;
        entry.status = Status::Undone;
        entry.record = Some(CreatedProjectRecord {
            undo_available: false,
            ..record
        });
        let reported = !entry.confirmed;
        Ok(reported.then(|| report(chat, request_id, Status::Undone, None)))
    }
}

#[cfg(test)]
#[path = "project_create_request_tests.rs"]
mod tests;
