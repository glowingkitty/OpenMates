//! Chat orchestration jobs of the device (`chat_orchestration_jobs` capability).
//!
//! Sans-IO core of "any chat can spawn and coordinate other main chats": it
//! validates `chat_orchestration_job_available` payloads, builds the claim and
//! result frames, plans what the shell must do ([`Effect`]), owns the
//! `chat_orchestration` system-event content and its one-line rendering, and
//! bounds what `read_chat` returns. Shells (web Worker, CLI/TUI, Apple) only
//! perform the effects (create chat, send message, store event, read messages)
//! and post the frames. Wire contract: `docs/plans/chat-orchestration-main-chats/
//! plan.yml` (`protocol`); spec `specifications/features/chat-orchestration`.
use serde_json::{Value, json};

/// Capability name the server advertises for these jobs.
pub const CHAT_ORCHESTRATION_JOBS_CAPABILITY: &str = "chat_orchestration_jobs";
/// Frame types (server to client).
pub const FRAME_JOB_AVAILABLE: &str = "chat_orchestration_job_available";
/// Server answer to a claim.
pub const FRAME_CLAIM_RESULT: &str = "chat_orchestration_job_claim_result";
/// Server answer to a result.
pub const FRAME_RESULT_ACK: &str = "chat_orchestration_job_result_ack";
/// Frame types (client to server).
pub const FRAME_CLAIM: &str = "chat_orchestration_job_claim";
/// Result frame sent after the effect ran.
pub const FRAME_RESULT: &str = "chat_orchestration_job_result";
/// `type` literal of the system-event content.
pub const EVENT_TYPE: &str = "chat_orchestration";
/// Refusal code when the local chat did not spawn the target chat.
pub const ERR_NOT_SPAWNED: &str = "not_spawned_by_this_chat";
/// Generic failure code.
pub const ERR_JOB_FAILED: &str = "job_failed";
/// Code for an expired job.
pub const ERR_JOB_EXPIRED: &str = "job_expired";
const ERROR_CODES: [&str; 9] = [
    "not_spawned_by_this_chat",
    "device_offline",
    "user_active",
    "spawn_limit_reached",
    "chain_too_deep",
    "not_eligible",
    "no_creator",
    "job_failed",
    "job_expired",
];
const MAX_TITLE: usize = 200;
const MAX_BRIEF: usize = 8000;
const MAX_TEXT: usize = 2000;
const MAX_LIMIT: u64 = 20;
const MAX_READ_TOTAL: usize = 12_000;
const MAX_ID: usize = 128;
const SENDER_PREFIX: &str = "chat:";

/// Why a payload, frame or event was refused.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OrchestrationError {
    /// Malformed or out-of-bounds payload.
    Invalid,
    /// `expires_at` is not after the current time.
    Expired,
}

impl OrchestrationError {
    /// Stable wire code reported in a failed result frame.
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => ERR_JOB_FAILED,
            Self::Expired => ERR_JOB_EXPIRED,
        }
    }
}

/// Job kinds of the protocol.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JobKind {
    /// Create a spawned main chat.
    StartChat,
    /// Store an event in the creator chat.
    CreatorEvent,
    /// Read the spawned chat's messages.
    ReadChat,
    /// Send a user message into the spawned chat.
    SendMessage,
}

impl JobKind {
    fn parse(raw: &str) -> Option<Self> {
        Some(match raw {
            "start_chat" => Self::StartChat,
            "creator_event" => Self::CreatorEvent,
            "read_chat" => Self::ReadChat,
            "send_message" => Self::SendMessage,
            _ => return None,
        })
    }

    /// Wire name of the kind.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::StartChat => "start_chat",
            Self::CreatorEvent => "creator_event",
            Self::ReadChat => "read_chat",
            Self::SendMessage => "send_message",
        }
    }
}

/// Action of a `chat_orchestration` event.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    /// The creator started the chat.
    Started,
    /// The spawned chat reported back.
    Report,
    /// The spawned chat finished.
    Finished,
    /// The spawned chat waits for the user.
    WaitingForUser,
    /// The user wrote in the spawned chat.
    UserWrote,
}

impl Action {
    fn parse(raw: &str) -> Option<Self> {
        Some(match raw {
            "started" => Self::Started,
            "report" => Self::Report,
            "finished" => Self::Finished,
            "waiting_for_user" => Self::WaitingForUser,
            "user_wrote" => Self::UserWrote,
            _ => return None,
        })
    }

    /// Wire name of the action.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Started => "started",
            Self::Report => "report",
            Self::Finished => "finished",
            Self::WaitingForUser => "waiting_for_user",
            Self::UserWrote => "user_wrote",
        }
    }
}

/// A validated job; `payload` keeps the wire object (checked for its kind).
#[derive(Debug, Clone, PartialEq)]
pub struct Job {
    /// Server job id (uuid).
    pub job_id: String,
    /// Job kind.
    pub kind: JobKind,
    /// Validated payload object.
    pub payload: Value,
    /// Unix seconds.
    pub created_at: i64,
    /// Unix seconds; the job is dead from this moment on.
    pub expires_at: i64,
}

impl Job {
    /// The job in its wire shape `{job_id, kind, payload, created_at, expires_at}`.
    pub fn to_value(&self) -> Value {
        json!({"job_id": self.job_id, "kind": self.kind.as_str(), "payload": self.payload,
            "created_at": self.created_at, "expires_at": self.expires_at})
    }
}

/// One `chat_orchestration` system event.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OrchestrationEvent {
    /// What happened.
    pub action: Action,
    /// The spawned chat.
    pub chat_id: String,
    /// Label of the spawned chat.
    pub title: Option<String>,
    /// Report text (`report` only).
    pub text: Option<String>,
    /// Stable id (also the system message id).
    pub event_id: String,
    /// Unix seconds.
    pub created_at: i64,
}

/// An event the shell stores as an encrypted system message of `chat_id`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StoreEvent {
    /// Chat that receives the message (the creator chat).
    pub chat_id: String,
    /// System message id.
    pub message_id: String,
    /// Event JSON string ([`build_event`]).
    pub content: String,
    /// Unix seconds.
    pub created_at: i64,
}

impl StoreEvent {
    fn to_value(&self) -> Value {
        json!({"kind": "store_event", "chat_id": self.chat_id, "message_id": self.message_id,
            "content": self.content, "created_at": self.created_at})
    }
}

/// What the shell must do for a job.
#[derive(Debug, Clone, PartialEq)]
pub enum Effect {
    /// Create the chat with a new key, send the brief as first user message,
    /// then store `started_event`.
    StartChat {
        /// New chat id.
        chat_id: String,
        /// Creator chat id.
        creator_chat_id: String,
        /// Chat title.
        title: String,
        /// First user message.
        brief: String,
        /// Sender name of the brief (`chat:<creator>`).
        sender_name: String,
        /// Job id for `orchestration_job_id`.
        job_id: String,
        /// Event for the creator chat.
        started_event: StoreEvent,
    },
    /// Store an event in the creator chat.
    StoreEvent(StoreEvent),
    /// Read the last `limit` messages and bound them with [`bound_read_result`].
    ReadChat {
        /// Spawned chat.
        chat_id: String,
        /// Message count (1..=20).
        limit: usize,
        /// Job id.
        job_id: String,
    },
    /// Send `text` as a user message into the spawned chat.
    SendMessage {
        /// Spawned chat.
        chat_id: String,
        /// Message text.
        text: String,
        /// Sender name (`chat:<creator>`).
        sender_name: String,
        /// Job id for `orchestration_job_id`.
        job_id: String,
    },
    /// Answer with a failed result frame.
    Reject {
        /// Job id.
        job_id: String,
        /// Protocol error code.
        error_code: &'static str,
    },
}

impl Effect {
    /// JSON shape handed to the web Worker (`kind` discriminates).
    pub fn to_value(&self) -> Value {
        match self {
            Self::StartChat {
                chat_id,
                creator_chat_id,
                title,
                brief,
                sender_name,
                job_id,
                started_event,
            } => json!({
                "kind": "start_chat", "chat_id": chat_id, "creator_chat_id": creator_chat_id, "title": title,
                "brief": brief, "sender_name": sender_name, "job_id": job_id, "started_event": started_event.to_value()}),
            Self::StoreEvent(event) => event.to_value(),
            Self::ReadChat {
                chat_id,
                limit,
                job_id,
            } => {
                json!({"kind": "read_chat", "chat_id": chat_id, "limit": limit, "job_id": job_id})
            }
            Self::SendMessage {
                chat_id,
                text,
                sender_name,
                job_id,
            } => json!({"kind": "send_message",
                "chat_id": chat_id, "text": text, "sender_name": sender_name, "job_id": job_id}),
            Self::Reject { job_id, error_code } => {
                json!({"kind": "reject", "job_id": job_id, "error_code": error_code})
            }
        }
    }
}

fn is_uuid(value: &str) -> bool {
    uuid::Uuid::parse_str(value).is_ok()
}

fn uuid_field(object: &Value, key: &str) -> Result<String, OrchestrationError> {
    match object.get(key).and_then(Value::as_str) {
        Some(value) if is_uuid(value) => Ok(value.to_owned()),
        _ => Err(OrchestrationError::Invalid),
    }
}

/// Non-blank string of at most `max` characters.
fn text_field(object: &Value, key: &str, max: usize) -> Result<String, OrchestrationError> {
    match object.get(key).and_then(Value::as_str) {
        Some(value) if !value.trim().is_empty() && value.chars().count() <= max => {
            Ok(value.to_owned())
        }
        _ => Err(OrchestrationError::Invalid),
    }
}

fn opt_text_field(
    object: &Value,
    key: &str,
    max: usize,
) -> Result<Option<String>, OrchestrationError> {
    match object.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(_) => text_field(object, key, max).map(Some),
    }
}

fn id_field(object: &Value, key: &str) -> Result<String, OrchestrationError> {
    text_field(object, key, MAX_ID)
}

fn seconds_field(object: &Value, key: &str) -> Result<i64, OrchestrationError> {
    match object.get(key).and_then(Value::as_i64) {
        Some(value) if value >= 0 => Ok(value),
        _ => Err(OrchestrationError::Invalid),
    }
}

fn check_payload(kind: JobKind, payload: &Value) -> Result<(), OrchestrationError> {
    if !payload.is_object() {
        return Err(OrchestrationError::Invalid);
    }
    uuid_field(payload, "spawned_chat_id")?;
    uuid_field(payload, "creator_chat_id")?;
    match kind {
        JobKind::StartChat => {
            text_field(payload, "title", MAX_TITLE)?;
            text_field(payload, "brief", MAX_BRIEF)?;
            id_field(payload, "event_message_id")?;
        }
        JobKind::CreatorEvent => {
            let action = payload
                .get("action")
                .and_then(Value::as_str)
                .and_then(Action::parse);
            let action = action.ok_or(OrchestrationError::Invalid)?;
            opt_text_field(payload, "title", MAX_TITLE)?;
            let text = opt_text_field(payload, "text", MAX_TEXT)?;
            if (action == Action::Report) != text.is_some() {
                return Err(OrchestrationError::Invalid);
            }
            id_field(payload, "event_message_id")?;
            seconds_field(payload, "created_at")?;
        }
        JobKind::ReadChat => match payload.get("limit").and_then(Value::as_u64) {
            Some(limit) if (1..=MAX_LIMIT).contains(&limit) => {}
            _ => return Err(OrchestrationError::Invalid),
        },
        JobKind::SendMessage => {
            text_field(payload, "text", MAX_TEXT)?;
        }
    }
    Ok(())
}

/// Validates a `chat_orchestration_job_available` payload.
///
/// `now_s` enables the expiry check; pass `None` when re-parsing a job that was
/// already accepted. Bounds: ids are uuids, title <= 200, brief <= 8000, text
/// <= 2000 characters, limit 1..=20, report text exactly on `report` events.
///
/// # Errors
/// [`OrchestrationError::Invalid`] for any malformed field,
/// [`OrchestrationError::Expired`] when `expires_at <= now_s`.
pub fn parse_job(value: &Value, now_s: Option<i64>) -> Result<Job, OrchestrationError> {
    let job_id = uuid_field(value, "job_id")?;
    let kind = value
        .get("kind")
        .and_then(Value::as_str)
        .and_then(JobKind::parse)
        .ok_or(OrchestrationError::Invalid)?;
    let payload = value.get("payload").ok_or(OrchestrationError::Invalid)?;
    check_payload(kind, payload)?;
    let created_at = seconds_field(value, "created_at")?;
    let expires_at = seconds_field(value, "expires_at")?;
    if now_s.is_some_and(|now| expires_at <= now) {
        return Err(OrchestrationError::Expired);
    }
    Ok(Job {
        job_id,
        kind,
        payload: payload.clone(),
        created_at,
        expires_at,
    })
}

/// Payload of a `chat_orchestration_job_claim` frame.
pub fn claim_frame(job_id: &str) -> Value {
    json!({"job_id": job_id})
}

/// Payload of a `chat_orchestration_job_result` frame. A failed result carries
/// a known `error_code` (unknown or missing -> `job_failed`); a successful one
/// carries the optional `result`.
pub fn result_frame(
    job_id: &str,
    ok: bool,
    error_code: Option<&str>,
    result: Option<&Value>,
) -> Value {
    let mut frame = json!({"job_id": job_id, "ok": ok});
    if ok {
        if let Some(result) = result {
            frame["result"] = result.clone();
        }
    } else {
        let code = error_code
            .filter(|code| ERROR_CODES.contains(code))
            .unwrap_or(ERR_JOB_FAILED);
        frame["error_code"] = json!(code);
    }
    frame
}

/// Parsed `chat_orchestration_job_claim_result`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClaimResult {
    /// Job id.
    pub job_id: String,
    /// True when this device may run the job.
    pub granted: bool,
    /// Refusal reason.
    pub reason: Option<String>,
}

/// Parses a claim-result payload.
///
/// # Errors
/// [`OrchestrationError::Invalid`] for a bad job id or a non-boolean `granted`.
pub fn parse_claim_result(value: &Value) -> Result<ClaimResult, OrchestrationError> {
    Ok(ClaimResult {
        job_id: uuid_field(value, "job_id")?,
        granted: value
            .get("granted")
            .and_then(Value::as_bool)
            .ok_or(OrchestrationError::Invalid)?,
        reason: value
            .get("reason")
            .and_then(Value::as_str)
            .map(str::to_owned),
    })
}

/// Parsed `chat_orchestration_job_result_ack`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResultAck {
    /// Job id.
    pub job_id: String,
    /// True when the server accepted the result.
    pub accepted: bool,
    /// Rejection reason.
    pub reason: Option<String>,
}

/// Parses a result-ack payload.
///
/// # Errors
/// [`OrchestrationError::Invalid`] for a bad job id or a non-boolean `accepted`.
pub fn parse_result_ack(value: &Value) -> Result<ResultAck, OrchestrationError> {
    Ok(ResultAck {
        job_id: uuid_field(value, "job_id")?,
        accepted: value
            .get("accepted")
            .and_then(Value::as_bool)
            .ok_or(OrchestrationError::Invalid)?,
        reason: value
            .get("reason")
            .and_then(Value::as_str)
            .map(str::to_owned),
    })
}

/// Sender name carried by messages one chat sends to another.
pub fn creator_sender_name(creator_chat_id: &str) -> String {
    format!("{SENDER_PREFIX}{creator_chat_id}")
}

/// Creator chat id of a `chat:<uuid>` sender name; `None` for anything else.
pub fn creator_from_sender_name(sender_name: Option<&str>) -> Option<String> {
    let id = sender_name?.strip_prefix(SENDER_PREFIX)?;
    is_uuid(id).then(|| id.to_owned())
}

/// Serializes an event as system message content.
///
/// # Errors
/// [`OrchestrationError::Invalid`] when the event breaks the bounds of [`parse_event`].
pub fn build_event(event: &OrchestrationEvent) -> Result<String, OrchestrationError> {
    if !event_valid(event) {
        return Err(OrchestrationError::Invalid);
    }
    let mut value = json!({"schema_version": 1, "type": EVENT_TYPE, "action": event.action.as_str(),
        "chat_id": event.chat_id, "event_id": event.event_id, "created_at": event.created_at});
    if let Some(title) = &event.title {
        value["title"] = json!(title);
    }
    if let Some(text) = &event.text {
        value["text"] = json!(text);
    }
    Ok(value.to_string())
}

fn event_valid(event: &OrchestrationEvent) -> bool {
    let bounded = |value: &Option<String>, max: usize| {
        value
            .as_ref()
            .is_none_or(|v| !v.trim().is_empty() && v.chars().count() <= max)
    };
    is_uuid(&event.chat_id)
        && !event.event_id.trim().is_empty()
        && event.event_id.chars().count() <= MAX_ID
        && event.created_at >= 0
        && bounded(&event.title, MAX_TITLE)
        && bounded(&event.text, MAX_TEXT)
        && (event.action == Action::Report) == event.text.is_some()
}

/// Parses system message content; `None` for other system events, plain text,
/// wrong schema, an unknown action or any bound violation.
pub fn parse_event(content: &str) -> Option<OrchestrationEvent> {
    let value: Value = serde_json::from_str(content).ok()?;
    if value.get("schema_version")?.as_u64()? != 1 || value.get("type")?.as_str()? != EVENT_TYPE {
        return None;
    }
    let event = OrchestrationEvent {
        action: Action::parse(value.get("action")?.as_str()?)?,
        chat_id: value.get("chat_id")?.as_str()?.to_owned(),
        title: opt_text_field(&value, "title", MAX_TITLE).ok()?,
        text: opt_text_field(&value, "text", MAX_TEXT).ok()?,
        event_id: value.get("event_id")?.as_str()?.to_owned(),
        created_at: value.get("created_at")?.as_i64()?,
    };
    event_valid(&event).then_some(event)
}

/// English one-line summary of an event. `resolved_title` is the spawned chat's
/// current title; it wins over the title stored in the event.
pub fn event_line(event: &OrchestrationEvent, resolved_title: Option<&str>) -> String {
    let title = resolved_title
        .filter(|t| !t.trim().is_empty())
        .or(event.title.as_deref())
        .unwrap_or("a chat");
    match event.action {
        Action::Started => format!("Started chat {title}"),
        Action::Report => format!(
            "Report from {title}: {}",
            event.text.as_deref().unwrap_or("")
        ),
        Action::Finished => format!("{title} finished"),
        Action::WaitingForUser => format!("{title} is waiting for you"),
        Action::UserWrote => format!("You wrote in {title}"),
    }
}

/// One decrypted message handed to [`bound_read_result`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReadMessage {
    /// `user`, `assistant` or `system`; other roles are dropped.
    pub role: String,
    /// Plain text.
    pub content: String,
    /// Unix seconds.
    pub created_at: i64,
}

fn truncate_chars(value: &str, max: usize) -> &str {
    match value.char_indices().nth(max) {
        Some((index, _)) => &value[..index],
        None => value,
    }
}

/// Result of a `read_chat` job: the newest `limit` messages (oldest first),
/// each cut to 2000 characters and 12000 characters in total (newest kept).
/// Cuts fall on char boundaries.
pub fn bound_read_result(messages: &[ReadMessage], limit: usize) -> Value {
    let limit = limit.clamp(1, MAX_LIMIT as usize);
    let mut budget = MAX_READ_TOTAL;
    let mut kept = Vec::new();
    for message in messages
        .iter()
        .filter(|m| matches!(m.role.as_str(), "user" | "assistant" | "system"))
        .rev()
        .take(limit)
    {
        if budget == 0 {
            break;
        }
        let content = truncate_chars(truncate_chars(&message.content, MAX_TEXT), budget);
        budget -= content.chars().count();
        kept.push(
            json!({"role": message.role, "content": content, "created_at": message.created_at}),
        );
    }
    kept.reverse();
    json!({"messages": kept})
}

/// Decides what the shell does for `job`. `local_creator_chat_id` is the
/// creator link the device holds for the spawned chat (from its encrypted chat
/// metadata); `read_chat` and `send_message` are refused unless it equals the
/// payload's `creator_chat_id`, so a chat only reaches chats it spawned.
pub fn plan_job(job: &Job, local_creator_chat_id: Option<&str>) -> Effect {
    let reject = |error_code| Effect::Reject {
        job_id: job.job_id.clone(),
        error_code,
    };
    let text = |key: &str| {
        job.payload
            .get(key)
            .and_then(Value::as_str)
            .map(str::to_owned)
    };
    let (Some(spawned), Some(creator)) = (text("spawned_chat_id"), text("creator_chat_id")) else {
        return reject(ERR_JOB_FAILED);
    };
    let linked = local_creator_chat_id == Some(creator.as_str());
    match job.kind {
        JobKind::StartChat => {
            let (Some(title), Some(brief), Some(message_id)) =
                (text("title"), text("brief"), text("event_message_id"))
            else {
                return reject(ERR_JOB_FAILED);
            };
            let event = OrchestrationEvent {
                action: Action::Started,
                chat_id: spawned.clone(),
                title: Some(title.clone()),
                text: None,
                event_id: message_id.clone(),
                created_at: job.created_at,
            };
            let Ok(content) = build_event(&event) else {
                return reject(ERR_JOB_FAILED);
            };
            Effect::StartChat {
                chat_id: spawned,
                sender_name: creator_sender_name(&creator),
                started_event: StoreEvent {
                    chat_id: creator.clone(),
                    message_id,
                    content,
                    created_at: job.created_at,
                },
                creator_chat_id: creator,
                title,
                brief,
                job_id: job.job_id.clone(),
            }
        }
        JobKind::CreatorEvent => {
            let (Some(message_id), Some(action), Some(created_at)) = (
                text("event_message_id"),
                job.payload
                    .get("action")
                    .and_then(Value::as_str)
                    .and_then(Action::parse),
                job.payload.get("created_at").and_then(Value::as_i64),
            ) else {
                return reject(ERR_JOB_FAILED);
            };
            let event = OrchestrationEvent {
                action,
                chat_id: spawned,
                title: text("title"),
                text: text("text"),
                event_id: message_id.clone(),
                created_at,
            };
            match build_event(&event) {
                Ok(content) => Effect::StoreEvent(StoreEvent {
                    chat_id: creator,
                    message_id,
                    content,
                    created_at,
                }),
                Err(_) => reject(ERR_JOB_FAILED),
            }
        }
        _ if !linked => reject(ERR_NOT_SPAWNED),
        JobKind::ReadChat => match job.payload.get("limit").and_then(Value::as_u64) {
            Some(limit) => Effect::ReadChat {
                chat_id: spawned,
                limit: limit as usize,
                job_id: job.job_id.clone(),
            },
            None => reject(ERR_JOB_FAILED),
        },
        JobKind::SendMessage => match text("text") {
            Some(text) => Effect::SendMessage {
                chat_id: spawned,
                text,
                sender_name: creator_sender_name(&creator),
                job_id: job.job_id.clone(),
            },
            None => reject(ERR_JOB_FAILED),
        },
    }
}

#[cfg(test)]
#[path = "chat_orchestration_tests.rs"]
mod tests;
