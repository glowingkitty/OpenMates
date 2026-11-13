//! The `embed_updated` chat system event of user-made embed versions (shared
//! client core; spec `feature.embed-user-edits`, assertions `event.chat-notice`,
//! `event.project-edit-reaches-chat`, `event.collapse`).
//! Owns the payload codec (validated exactly like the server reader
//! `backend/apps/ai/processing/embed_update_history.py`), the idempotent writer,
//! the reconcile of `GET /v1/chats/{id}/pending-embed-notices` and the pure
//! grouping of event runs that shells render as "<Type> updated, N changes".
use crate::error::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeSet;

/// `type` of the event payload.
pub const EMBED_UPDATED_TYPE: &str = "embed_updated";
/// Only payload schema the client writes and the server reads.
pub const EMBED_UPDATED_SCHEMA_VERSION: u32 = 1;
/// Content longer than this is dropped by the server reader
/// (`MAX_EVENT_CONTENT_CHARS`), so the writer refuses it.
pub const MAX_EVENT_CONTENT_CHARS: usize = 4096;
/// Highest version the server reader accepts (`MAX_VERSION`).
pub const MAX_EVENT_VERSION: i64 = 1_000_000;
/// Notices handled per reconcile; the server returns at most 100 per page.
pub const MAX_NOTICES: usize = 100;

/// Embed kinds a user can edit; the wire value is the snake-case name.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EmbedKind {
    /// `images/generated_image` and `images/upload`.
    Image,
    /// `diagrams/html`.
    Diagram,
    /// `slides/deck`.
    Slides,
    /// `sheets/sheet`.
    Sheet,
    /// `docs/document`.
    Document,
}

impl EmbedKind {
    /// Kind of an embed from its `app_id`/`skill_id`; mirrors
    /// `USER_EDITABLE_TYPES` of the `embed-version-transaction` extension.
    /// `None` for every embed type the server refuses to edit.
    pub fn from_app_skill(app_id: &str, skill_id: &str) -> Option<Self> {
        match (app_id, skill_id) {
            ("images", "generated_image" | "upload") => Some(Self::Image),
            ("diagrams", "html") => Some(Self::Diagram),
            ("slides", "deck") => Some(Self::Slides),
            ("sheets", "sheet") => Some(Self::Sheet),
            ("docs", "document") => Some(Self::Document),
            _ => None,
        }
    }
}

/// What the user did to make the version. Same values as `revision_action`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EmbedUpdateAction {
    /// A content edit (document editor, sheet, diagram source, slide).
    Edit,
    /// An image Enhance result.
    Enhance,
    /// A copy of an earlier version (`restored_from`).
    Restore,
    /// A client-produced cropped image.
    Crop,
}

impl EmbedUpdateAction {
    /// Wire value (`edit`, `enhance`, `restore`, `crop`).
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Edit => "edit",
            Self::Enhance => "enhance",
            Self::Restore => "restore",
            Self::Crop => "crop",
        }
    }

    /// Parse a wire value; `None` for anything else.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "edit" => Some(Self::Edit),
            "enhance" => Some(Self::Enhance),
            "restore" => Some(Self::Restore),
            "crop" => Some(Self::Crop),
            _ => None,
        }
    }
}

/// Where the edit was made.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EmbedUpdateSurface {
    /// In the embed's own chat.
    Chat,
    /// In the Projects workspace.
    Project,
}

/// Decrypted content of one `embed_updated` system message. Field order and
/// names are the wire contract read by `embed_update_history.py`; optional
/// fields are omitted when absent (the server treats absent and null alike).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct EmbedUpdatedEvent {
    /// Always [`EMBED_UPDATED_SCHEMA_VERSION`].
    pub schema_version: u32,
    /// Always [`EMBED_UPDATED_TYPE`].
    #[serde(rename = "type")]
    pub event_type: String,
    /// Embed id (`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`).
    pub embed_id: String,
    /// The embed's `embed_ref` slug (`^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$`).
    pub embed_ref: String,
    /// Kind shown as "<Type> updated".
    pub embed_kind: EmbedKind,
    /// The version the user made (N+1).
    pub version: i64,
    /// The version it was made from (N).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub base_version: Option<i64>,
    /// What the user did.
    pub action: EmbedUpdateAction,
    /// Version a restore copied; required for `restore`, absent otherwise.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub restored_from: Option<i64>,
    /// Where the edit was made.
    pub surface: EmbedUpdateSurface,
    /// Unix seconds of the commit (the notice's `created_at` on reconcile).
    pub created_at: i64,
}

/// Inputs of an event other than the version facts: who the embed is.
/// Deserializes from `{embed_ref, embed_kind}` (binding input); the ref is
/// checked when the event is built.
#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EmbedEventIdentity {
    /// The embed's `embed_ref` slug.
    pub embed_ref: String,
    /// Its kind.
    pub embed_kind: EmbedKind,
}

impl EmbedEventIdentity {
    /// Identity of an embed from its decrypted content (`embed_ref`, `app_id`,
    /// `skill_id`, `type`); `None` when the ref is invalid or the type is not
    /// user-editable.
    ///
    /// The server classifies by the embed row's plaintext `app_id/skill_id`.
    /// A generated picture's row takes its `skill_id` from the content `type`
    /// (`generated_image`, `generated_media_graph.py`), while the content's
    /// `skill_id` names the skill that ran (`generate`, `generate_draft`). So
    /// the kind is read from `skill_id`, else from `type`, as the row has it.
    pub(crate) fn from_content(content: &Value) -> Option<Self> {
        let field = |key: &str| content.get(key).and_then(Value::as_str).unwrap_or("");
        let app_id = field("app_id");
        let embed_kind = EmbedKind::from_app_skill(app_id, field("skill_id"))
            .or_else(|| EmbedKind::from_app_skill(app_id, field("type")))?;
        let embed_ref = field("embed_ref");
        valid_embed_ref(embed_ref).then(|| Self {
            embed_ref: embed_ref.to_owned(),
            embed_kind,
        })
    }
}

impl EmbedUpdatedEvent {
    /// A schema-1 event; validate with [`build_embed_updated_event`].
    #[allow(clippy::too_many_arguments)] // Mirrors the flat wire payload one to one.
    pub fn new(
        embed_id: &str,
        identity: &EmbedEventIdentity,
        version: i64,
        base_version: Option<i64>,
        action: EmbedUpdateAction,
        restored_from: Option<i64>,
        surface: EmbedUpdateSurface,
        created_at: i64,
    ) -> Self {
        Self {
            schema_version: EMBED_UPDATED_SCHEMA_VERSION,
            event_type: EMBED_UPDATED_TYPE.into(),
            embed_id: embed_id.into(),
            embed_ref: identity.embed_ref.clone(),
            embed_kind: identity.embed_kind,
            version,
            base_version,
            action,
            restored_from,
            surface,
            created_at,
        }
    }

    /// Deterministic message id of this event (see [`embed_updated_message_id`]).
    pub fn message_id(&self) -> String {
        embed_updated_message_id(&self.embed_id, self.version)
    }
}

/// `embed-updated-<embed_id>-v<version>`: the id the server's pending notice
/// names and clears when a system message with it is stored. Deterministic so
/// every device writing the same event writes the same row (duplicates are
/// skipped by persistence).
pub fn embed_updated_message_id(embed_id: &str, version: i64) -> String {
    format!("embed-updated-{embed_id}-v{version}")
}

fn slug(value: &str, max_rest: usize, extra: &[u8]) -> bool {
    let bytes = value.as_bytes();
    let Some((first, rest)) = bytes.split_first() else {
        return false;
    };
    first.is_ascii_alphanumeric()
        && rest.len() <= max_rest
        && rest
            .iter()
            .all(|b| b.is_ascii_alphanumeric() || extra.contains(b))
}

/// `EMBED_ID_PATTERN` of the server reader.
pub(crate) fn valid_embed_id(value: &str) -> bool {
    slug(value, 63, b"_-")
}

/// `EMBED_REF_PATTERN` of the server reader.
pub fn valid_embed_ref(value: &str) -> bool {
    slug(value, 79, b"._-")
}

fn valid_version(value: i64) -> bool {
    (1..=MAX_EVENT_VERSION).contains(&value)
}

/// The exact `_validated_event` rules of `embed_update_history.py`, plus the
/// writer-side facts the server cannot check (`created_at` not negative,
/// `base_version` below `version`).
fn valid_event(event: &EmbedUpdatedEvent) -> bool {
    let restore_ok = match event.action {
        EmbedUpdateAction::Restore => event.restored_from.is_some_and(valid_version),
        _ => event.restored_from.is_none(),
    };
    event.schema_version == EMBED_UPDATED_SCHEMA_VERSION
        && event.event_type == EMBED_UPDATED_TYPE
        && valid_embed_id(&event.embed_id)
        && valid_embed_ref(&event.embed_ref)
        && valid_version(event.version)
        && event
            .base_version
            .is_none_or(|base| valid_version(base) && base < event.version)
        && restore_ok
        && event.created_at >= 0
}

/// Serialize a validated event as the system message content.
///
/// # Errors
/// `Error::Invalid` when a field breaks the server reader's rules (the server
/// would silently drop the event from inference) or the content exceeds
/// [`MAX_EVENT_CONTENT_CHARS`].
pub fn build_embed_updated_event(event: &EmbedUpdatedEvent) -> Result<String> {
    if !valid_event(event) {
        return Err(Error::Invalid("The embed update event is malformed."));
    }
    let content = serde_json::to_string(event).map_err(|_| Error::Protocol)?;
    if content.chars().count() > MAX_EVENT_CONTENT_CHARS {
        return Err(Error::Invalid("The embed update event is too long."));
    }
    Ok(content)
}

/// Parse system message content; `None` for anything that is not a valid
/// `embed_updated` event (other events, plain text, invalid fields), the same
/// rows the server reader drops.
pub fn parse_embed_updated_event(content: &str) -> Option<EmbedUpdatedEvent> {
    if content.chars().count() > MAX_EVENT_CONTENT_CHARS || !content.contains(EMBED_UPDATED_TYPE) {
        return None;
    }
    serde_json::from_str::<EmbedUpdatedEvent>(content)
        .ok()
        .filter(valid_event)
}

/// JSON form of [`parse_embed_updated_event`] for bindings: the event or `null`.
pub fn parse_embed_updated_event_json(content: &str) -> String {
    parse_embed_updated_event(content)
        .and_then(|event| serde_json::to_string(&event).ok())
        .unwrap_or_else(|| "null".into())
}

/// True for system events that are presentation-only and never reach the AI
/// history (`withoutPresentationOnlyEvents` on web): `context_entry` Memory
/// notices. `embed_updated` events are deliberately NOT presentation-only:
/// the server turns them into a note so the assistant knows the current
/// version (`embed-user-edits.assistant.knows-current-version`).
pub fn is_presentation_only_event(content: &str) -> bool {
    super::recommendations::parse_context_entry_event(content).is_some()
}

/// The transport of one chat-key encrypted system message. The production
/// sink is the signed-in client (`chat_system_message_added`, then
/// `system_message_confirmed`); tests use an in-memory fake.
#[allow(async_fn_in_trait)] // Crate-internal seam; callers are generic, never `dyn`.
pub trait SystemEventSink {
    /// Encrypt `content` with the chat key, send it as `role: "system"` with
    /// `message_id` and `created_at` (unix seconds), and wait for the
    /// server's confirmation.
    ///
    /// # Errors
    /// Key, socket and confirmation-timeout errors.
    async fn write_system_message(
        &mut self,
        chat_id: &str,
        message_id: &str,
        content: &str,
        created_at: i64,
    ) -> Result<()>;
}

/// Result of writing one event.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EventWrite {
    /// The message was sent and confirmed.
    Written,
    /// A message with this id is already in the chat or was written by this writer.
    AlreadyWritten,
}

/// Idempotent writer of `embed_updated` messages. Idempotency key: the
/// deterministic message id. A writer remembers what it confirmed; callers
/// also pass the ids already in the chat history, so a reopened chat never
/// writes the same event twice from this device.
#[derive(Clone, Debug, Default)]
pub struct EmbedUpdatedWriter {
    written: BTreeSet<String>,
}

impl EmbedUpdatedWriter {
    /// An empty writer.
    pub fn new() -> Self {
        Self::default()
    }

    /// Write `event` to `chat_id` unless its message id is in `known` or was
    /// already confirmed by this writer.
    ///
    /// # Errors
    /// [`build_embed_updated_event`] validation and the sink's errors; on
    /// error nothing is remembered, so a retry writes again.
    pub async fn write<S: SystemEventSink>(
        &mut self,
        sink: &mut S,
        chat_id: &str,
        event: &EmbedUpdatedEvent,
        known: &BTreeSet<String>,
    ) -> Result<EventWrite> {
        let message_id = event.message_id();
        if known.contains(&message_id) || self.written.contains(&message_id) {
            return Ok(EventWrite::AlreadyWritten);
        }
        let content = build_embed_updated_event(event)?;
        sink.write_system_message(chat_id, &message_id, &content, event.created_at)
            .await?;
        self.written.insert(message_id);
        Ok(EventWrite::Written)
    }
}

/// One row of `GET /v1/chats/{chat_id}/pending-embed-notices`: a committed
/// user version whose chat event is still unwritten. Content-free.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PendingEmbedNotice {
    /// Embed of the version.
    pub embed_id: String,
    /// Committed version (N+1).
    pub version: i64,
    /// What the user did.
    pub action: EmbedUpdateAction,
    /// Unix seconds of the commit; becomes the event's `created_at`.
    pub created_at: i64,
    /// `embed-updated-<embed_id>-v<version>`, checked against the fields.
    pub message_id: String,
    /// Version a restore copied: present exactly when `action` is `restore`
    /// (stored on the notice row at commit time).
    #[serde(default)]
    pub restored_from: Option<i64>,
    /// Scope the commit was made in, stored on the notice row at commit time.
    pub surface: EmbedUpdateSurface,
}

/// Parse the pending-notices response of `chat_id`.
///
/// # Errors
/// `Error::Protocol` for another chat, a malformed row (including a missing
/// `surface`), a message id that does not match its fields, a restore without
/// a valid `restored_from` below its version, `restored_from` on another
/// action, or more than [`MAX_NOTICES`] rows.
pub fn parse_pending_notices(chat_id: &str, response: &Value) -> Result<Vec<PendingEmbedNotice>> {
    if response.get("chat_id").and_then(Value::as_str) != Some(chat_id) {
        return Err(Error::Protocol);
    }
    let rows = response
        .get("notices")
        .and_then(Value::as_array)
        .filter(|rows| rows.len() <= MAX_NOTICES)
        .ok_or(Error::Protocol)?;
    rows.iter()
        .map(|row| {
            let notice: PendingEmbedNotice =
                serde_json::from_value(row.clone()).map_err(|_| Error::Protocol)?;
            if !valid_embed_id(&notice.embed_id)
                || !valid_version(notice.version)
                || notice.created_at < 0
                || notice.message_id != embed_updated_message_id(&notice.embed_id, notice.version)
                || !valid_notice_restore(&notice)
            {
                return Err(Error::Protocol);
            }
            Ok(notice)
        })
        .collect()
}

/// The server reader's restore rule on a notice: `restored_from` names an
/// earlier version for a restore and is absent for every other action.
fn valid_notice_restore(notice: &PendingEmbedNotice) -> bool {
    match (notice.action, notice.restored_from) {
        (EmbedUpdateAction::Restore, Some(from)) => valid_version(from) && from < notice.version,
        (EmbedUpdateAction::Restore, None) => false,
        (_, restored_from) => restored_from.is_none(),
    }
}

/// The event a notice stands for, with the notice's own `surface`,
/// `restored_from` and `created_at`, so a restore made in the Projects
/// workspace is written as a complete event. `None` only for a notice that
/// breaks the reader's rules (not produced by [`parse_pending_notices`]).
pub fn event_from_notice(
    notice: &PendingEmbedNotice,
    identity: &EmbedEventIdentity,
) -> Option<EmbedUpdatedEvent> {
    if !valid_notice_restore(notice) {
        return None;
    }
    let base = notice.version - 1;
    let event = EmbedUpdatedEvent::new(
        &notice.embed_id,
        identity,
        notice.version,
        (base >= 1).then_some(base),
        notice.action,
        notice.restored_from,
        notice.surface,
        notice.created_at,
    );
    valid_event(&event).then_some(event)
}

/// Outcome of one reconcile.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize)]
pub struct NoticeReconcileReport {
    /// Events written and confirmed now.
    pub written: usize,
    /// Notices whose message is already in the chat history (the server
    /// clears them once it stored that message).
    pub already_present: usize,
    /// Notices left pending because the embed's identity is not available on
    /// this device; they stay on the server and the next reconcile retries them.
    pub unresolved: Vec<String>,
    /// Set when the reconcile did not run now (offline, Team chat, refused
    /// read); every notice stays pending on the server for the next open.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub deferred: Option<&'static str>,
}

impl NoticeReconcileReport {
    /// A report of a reconcile that did not run, with its reason code.
    pub fn deferred(code: &'static str) -> Self {
        Self {
            deferred: Some(code),
            ..Self::default()
        }
    }
}

/// Write the missing events of `notices` in order (oldest first).
///
/// `identity` resolves an embed id to its ref and kind (`None`: not resolvable
/// here). `known` holds the message ids already in the chat's history.
///
/// # Errors
/// The first sink error; events written before it stay written.
pub async fn reconcile_notices<S, F>(
    sink: &mut S,
    writer: &mut EmbedUpdatedWriter,
    chat_id: &str,
    notices: &[PendingEmbedNotice],
    known: &BTreeSet<String>,
    mut identity: F,
) -> Result<NoticeReconcileReport>
where
    S: SystemEventSink,
    F: FnMut(&str) -> Option<EmbedEventIdentity>,
{
    let mut report = NoticeReconcileReport::default();
    for notice in notices {
        if known.contains(&notice.message_id) {
            report.already_present += 1;
            continue;
        }
        let Some(event) = identity(&notice.embed_id).and_then(|id| event_from_notice(notice, &id))
        else {
            report.unresolved.push(notice.message_id.clone());
            continue;
        };
        match writer.write(sink, chat_id, &event, known).await? {
            EventWrite::Written => report.written += 1,
            EventWrite::AlreadyWritten => report.already_present += 1,
        }
    }
    Ok(report)
}

/// One chat history row as the grouping reads it (decrypted content).
#[derive(Clone, Copy, Debug)]
pub struct HistoryRow<'a> {
    /// Message id.
    pub message_id: &'a str,
    /// `user`, `assistant` or `system`.
    pub role: &'a str,
    /// Decrypted content.
    pub content: &'a str,
}

/// A folded run of `embed_updated` events of one embed.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct EmbedUpdatedGroup {
    /// Embed of the run.
    pub embed_id: String,
    /// Its ref (for opening the embed).
    pub embed_ref: String,
    /// Kind shown as "<Type> updated".
    pub embed_kind: EmbedKind,
    /// Newest version of the run.
    pub latest_version: i64,
    /// Number of events in the run ("3 changes").
    pub change_count: usize,
    /// Action of the newest event.
    pub latest_action: EmbedUpdateAction,
    /// `created_at` of the newest event.
    pub latest_created_at: i64,
    /// Version the newest event restored; only when `latest_action` is
    /// `restore` (omitted from JSON otherwise).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub restored_from: Option<i64>,
    /// Where the newest event's edit was made (`chat` or `project`).
    pub surface: EmbedUpdateSurface,
    /// Message ids of the run, oldest first.
    pub message_ids: Vec<String>,
}

/// One item of the chat view: an ordinary row (by its index in the input) or
/// a folded `embed_updated` run.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ChatHistoryItem {
    /// Input row `index`, rendered as before.
    Message {
        /// Index into the grouped rows.
        index: usize,
    },
    /// A run of user edits of one embed.
    EmbedUpdated(EmbedUpdatedGroup),
}

/// Fold consecutive `embed_updated` system events of the same embed with no
/// other row between them into one [`EmbedUpdatedGroup`]
/// (`embed-user-edits.event.collapse`). Any other row, including an event of
/// another embed, ends the run. Invalid event payloads stay ordinary rows.
pub fn group_embed_updated_events(rows: &[HistoryRow<'_>]) -> Vec<ChatHistoryItem> {
    let mut items: Vec<ChatHistoryItem> = Vec::with_capacity(rows.len());
    for (index, row) in rows.iter().enumerate() {
        let event = (row.role == "system")
            .then(|| parse_embed_updated_event(row.content))
            .flatten();
        let Some(event) = event else {
            items.push(ChatHistoryItem::Message { index });
            continue;
        };
        if let Some(ChatHistoryItem::EmbedUpdated(group)) = items.last_mut()
            && group.embed_id == event.embed_id
        {
            group.change_count += 1;
            // Rows arrive in history order; the newest event names the state.
            group.latest_version = event.version;
            group.latest_action = event.action;
            group.latest_created_at = event.created_at;
            group.restored_from = event.restored_from;
            group.surface = event.surface;
            group.embed_ref = event.embed_ref;
            group.embed_kind = event.embed_kind;
            group.message_ids.push(row.message_id.to_owned());
            continue;
        }
        items.push(ChatHistoryItem::EmbedUpdated(EmbedUpdatedGroup {
            embed_id: event.embed_id,
            embed_ref: event.embed_ref,
            embed_kind: event.embed_kind,
            latest_version: event.version,
            change_count: 1,
            latest_action: event.action,
            latest_created_at: event.created_at,
            restored_from: event.restored_from,
            surface: event.surface,
            message_ids: vec![row.message_id.to_owned()],
        }));
    }
    items
}

#[derive(Deserialize)]
struct HistoryRowJson {
    message_id: String,
    role: String,
    content: String,
}

/// JSON form of [`group_embed_updated_events`] for bindings: input
/// `[{message_id, role, content}]` in history order, output the
/// [`ChatHistoryItem`] array (`{"kind":"message","index":i}` or
/// `{"kind":"embed_updated", ...group}`).
///
/// # Errors
/// `Error::Protocol` for malformed input JSON.
pub fn group_embed_updated_events_json(rows_json: &str) -> Result<String> {
    let rows: Vec<HistoryRowJson> = serde_json::from_str(rows_json).map_err(|_| Error::Protocol)?;
    let borrowed: Vec<HistoryRow<'_>> = rows
        .iter()
        .map(|row| HistoryRow {
            message_id: &row.message_id,
            role: &row.role,
            content: &row.content,
        })
        .collect();
    serde_json::to_string(&group_embed_updated_events(&borrowed)).map_err(|_| Error::Protocol)
}

#[cfg(test)]
#[path = "embed_updated_event_tests.rs"]
mod tests;
