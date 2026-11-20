//! Socket-frame ingest and chat admission for the shared core `Client`.
//!
//! The page keeps the WebSocket (transport row "the socket stays in the shell")
//! and forwards raw chat frames here; the core owns the resulting chat rows
//! (`Client::chats`) and ciphertext history (`Client::history`). Frame types
//! come from `view_model::socket_frames` (the core-owned list); chat
//! content is sealed with the chat key before it is stored, exactly as the
//! HTTP window path stores it. Spec: `specifications/architecture/sync`.
//!
//! Ordering contract: frames apply strictly in the order given and every
//! applied frame increments `Client::frame_applied_seq`, so a later Worker op
//! can check the core has caught up with the page.
use super::*;
use crate::view_model::{SocketEventOwner, classify_socket_event};

/// Server receipts that advance a chat's `messages_v`; the call and system
/// receipts may also carry their stored ciphertext row (`upsert_receipt_row`).
///
/// Their features (calls, system messages, queued follow-ups, message deletion)
/// are still shell-owned, so [`classify_socket_event`] names them `Shell` and the
/// socket keeps forwarding them to the shell. The core still applies their
/// version so a turn it commits next uses the current baseline. The first three
/// carry the authoritative chat version in `messages_v` only (a call's
/// per-message `revision` is no substitute); `recovery_job_persisted` (the
/// page persisted an assistant reply through browser recovery) carries
/// `committed_messages_v` and, when terminal, the sender's stored row; the rest
/// use `versions.messages_v`, `new_messages_v` or `messages_v`.
pub(crate) const VERSION_RECEIPT_FRAMES: &[&str] = &[
    "call_message_confirmed",
    "call_message_changed",
    "system_message_confirmed",
    "message_deleted",
    "message_queued",
    "queued_message_status",
    "queued_message_updated",
    "recovery_job_persisted",
    // The page persists an assistant reply itself (`ai_response_completed`)
    // with a messages_v this core never computed; its durable confirmation
    // carries that version so the next core-built turn is not refused.
    "ai_response_storage_confirmed",
];

/// Optional ciphertext/link fields a call or system receipt row may carry.
const RECEIPT_ROW_FIELDS: &[&str] = &[
    "encrypted_category",
    "encrypted_model_name",
    "encrypted_sender_name",
    "user_message_id",
];

/// One chat whose row or history changed while ingesting frames.
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ChangedChat {
    /// Full chat id.
    pub chat_id: String,
    /// Highest `messages_v` the core now holds for the chat, when known.
    pub messages_v: Option<u64>,
}

/// Result of `Client::ingest_socket_frames`, shaped for the page event.
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FrameIngestSummary {
    /// The core's applied-frame counter after this batch (monotonic).
    pub applied_seq: u64,
    /// Chats changed by applied frames, in first-change order.
    pub changed_chats: Vec<ChangedChat>,
    /// Frames not applied: unknown or shell-owned types, streaming chunks,
    /// and frames of another principal or team. The shell keeps handling them.
    pub ignored: u32,
}

/// Result of `Client::admit_chat`.
#[derive(Clone, Debug, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ChatAdmission {
    /// Full chat id; the row is now in `Client::chats`.
    pub chat_id: String,
    /// `messages_v` of the loaded row.
    pub messages_v: u64,
    /// Number of history rows now held for the chat.
    pub history_rows: usize,
}

/// Fixed, typed refusal of `Client::admit_chat` (never a raw error text).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AdmitChatError {
    /// The id is not a full chat uuid.
    InvalidChatId,
    /// The Client is a local read-only profile; admission needs the server.
    LocalProfileReadOnly,
    /// Another principal or team owns the chat, or the scope differs.
    Forbidden,
    /// The server does not know the chat.
    ChatUnknown,
    /// The row loaded but its chat key could not be opened.
    ChatKeyUnavailable,
    /// The session ended; sign in again.
    SessionExpired,
    /// Network or server unavailable.
    Unavailable,
}

impl AdmitChatError {
    /// Stable code surfaced to the Worker and page.
    pub fn code(self) -> &'static str {
        match self {
            Self::InvalidChatId => "invalid_chat_id",
            Self::LocalProfileReadOnly => "local_profile_read_only",
            Self::Forbidden => "forbidden",
            Self::ChatUnknown => "chat_unknown",
            Self::ChatKeyUnavailable => "chat_key_unavailable",
            Self::SessionExpired => "session_expired",
            Self::Unavailable => "unavailable",
        }
    }
    fn from_error(error: Error) -> Self {
        match error {
            Error::Forbidden => Self::Forbidden,
            Error::Invalid(_) => Self::ChatUnknown,
            Error::Crypto => Self::ChatKeyUnavailable,
            Error::Expired | Error::Authentication => Self::SessionExpired,
            Error::Unavailable {
                code: "local_profile_read_only",
                ..
            } => Self::LocalProfileReadOnly,
            _ => Self::Unavailable,
        }
    }
}

/// Frame types whose final message content is stored in history.
fn is_message_frame(kind: &str, payload: &Value) -> bool {
    match kind {
        "new_chat_message" | "chat_message_added" | "team_chat_message_created" => true,
        // Streaming chunks are never stored; only the final one carries the text.
        "ai_message_update" | "ai_message_ready" => {
            kind == "ai_message_ready" || payload["is_final_chunk"] == true
        }
        _ => false,
    }
}

fn frame_parts(frame: &Value) -> Option<(&str, &Value)> {
    let kind = frame["type"].as_str().or_else(|| frame["event"].as_str())?;
    // Legacy envelope keeps the fields beside `event`.
    Some((kind, frame.get("payload").unwrap_or(frame)))
}

fn raise_version(row: &mut Value, field: &str, version: Option<u64>) {
    if let Some(version) = version
        && row[field].as_u64().is_none_or(|known| version > known)
    {
        row[field] = json!(version);
    }
}

impl Client {
    /// Current frame-apply counter. A Worker op compares it with the `appliedSeq`
    /// the page announced to know the core has caught up.
    pub fn frame_applied_seq(&self) -> u64 {
        self.frame_applied_seq
    }

    /// Apply already-received socket frames to the chat rows and history, in
    /// the order given, and report what changed.
    ///
    /// Applies final user and assistant messages, `messages_v` bumps (send
    /// confirmation, turn admit ACK), chat title/metadata updates and chat
    /// deletion. Each applied frame increments the applied counter. Frames of
    /// other types, streaming chunks, and frames naming another user or team
    /// are ignored and counted, never an error.
    ///
    /// # Errors
    /// `Error::Protocol` for a malformed chat frame of a handled type;
    /// frames before it stay applied (and counted). Crypto errors when the chat
    /// key cannot seal plaintext content.
    pub async fn ingest_socket_frames(&mut self, frames: &[Value]) -> Result<FrameIngestSummary> {
        self.require_credentials()?;
        let mut changed: Vec<ChangedChat> = vec![];
        let mut ignored = 0u32;
        for frame in frames {
            let Some((kind, payload)) = frame_parts(frame) else {
                ignored += 1;
                continue;
            };
            let receipt = VERSION_RECEIPT_FRAMES.contains(&kind);
            if (!receipt && classify_socket_event(kind) == SocketEventOwner::Shell)
                || !self.frame_in_scope(payload)
            {
                ignored += 1;
                continue;
            }
            match self.apply_frame(kind, payload).await? {
                Some(chat) => {
                    self.frame_applied_seq += 1;
                    let version = self
                        .chats
                        .get(&chat)
                        .and_then(|row| row["messages_v"].as_u64());
                    match changed.iter_mut().find(|entry| entry.chat_id == chat) {
                        Some(entry) => entry.messages_v = version,
                        None => changed.push(ChangedChat {
                            chat_id: chat,
                            messages_v: version,
                        }),
                    }
                }
                None => ignored += 1,
            }
        }
        Ok(FrameIngestSummary {
            applied_seq: self.frame_applied_seq,
            changed_chats: changed,
            ignored,
        })
    }

    /// A frame of another user or team than this Client's principal is refused.
    fn frame_in_scope(&self, payload: &Value) -> bool {
        if let Some(user) = payload["user_id"].as_str()
            && self.user["id"].as_str().is_some_and(|own| own != user)
        {
            return false;
        }
        let team = payload.get("team_id").and_then(Value::as_str);
        match (team, self.team().ok().flatten()) {
            (None, None) => true,
            (Some(frame), Some(own)) => frame == own,
            _ => false,
        }
    }

    /// Apply one in-scope frame; `Some(chat_id)` when it changed state.
    async fn apply_frame(&mut self, kind: &str, payload: &Value) -> Result<Option<String>> {
        let chat = match payload["chat_id"].as_str() {
            Some(id) => id.to_owned(),
            None if kind == "team_chat_created" => payload["chat"]["id"]
                .as_str()
                .ok_or(Error::Protocol)?
                .to_owned(),
            None => return Ok(None),
        };
        uuid::Uuid::parse_str(&chat).map_err(|_| Error::Protocol)?;
        let versions = payload.get("versions").unwrap_or(payload);
        match kind {
            "chat_deleted" => {
                self.history.remove(&chat);
                self.sync_message_windows.remove(&chat);
                self.selected_first_pages.remove(&chat);
                Ok(self.remove_chat_row(&chat).map(|_| chat))
            }
            "chat_message_confirmed" | "chat_turn_preflight_ack" | "chat_turn_admit" => {
                let version = ["new_messages_v", "committed_messages_v", "messages_v"]
                    .iter()
                    .find_map(|field| payload[*field].as_u64());
                let Some(row) = self.chats.get_mut(&chat) else {
                    return Ok(None);
                };
                if version.is_none() {
                    return Ok(None);
                }
                raise_version(row, "messages_v", version);
                Ok(Some(chat))
            }
            k if VERSION_RECEIPT_FRAMES.contains(&k) => {
                let direct = matches!(
                    k,
                    "call_message_confirmed" | "call_message_changed" | "system_message_confirmed"
                );
                // A reply the page persisted through browser recovery: the
                // receipt carries the committed version and the sender's row.
                let recovered = k == "recovery_job_persisted";
                let version = if direct {
                    payload["messages_v"].as_u64()
                } else if recovered {
                    payload["committed_messages_v"].as_u64()
                } else {
                    versions["messages_v"]
                        .as_u64()
                        .or_else(|| payload["new_messages_v"].as_u64())
                        .or_else(|| payload["messages_v"].as_u64())
                };
                let (Some(row), Some(_)) = (self.chats.get_mut(&chat), version) else {
                    return Ok(None);
                };
                raise_version(row, "messages_v", version);
                if direct || recovered {
                    self.upsert_receipt_row(&chat, payload);
                }
                Ok(Some(chat))
            }
            "chat_title_updated" | "encrypted_chat_metadata" => {
                let Some(row) = self.chats.get_mut(&chat) else {
                    return Ok(None);
                };
                let data = payload.get("data").unwrap_or(payload);
                for (field, value) in data.as_object().into_iter().flatten() {
                    if field.starts_with("encrypted_") && value.is_string() {
                        row[field.as_str()] = value.clone();
                    }
                }
                raise_version(row, "metadata_v", versions["metadata_v"].as_u64());
                // `title_v` decides `chat_has_title` of the next turn the core builds.
                raise_version(row, "title_v", versions["title_v"].as_u64());
                raise_version(row, "messages_v", versions["messages_v"].as_u64());
                Ok(Some(chat))
            }
            super::answer_withdrawal::EVENT_KIND => {
                self.apply_withdrawal_event(&chat, payload).await
            }
            "assistant_message_replaced" => {
                let message = payload["message_id"].as_str().ok_or(Error::Protocol)?;
                let sealed = payload["encrypted_content"]
                    .as_str()
                    .ok_or(Error::Protocol)?;
                Ok(self
                    .replace_history_content(&chat, message, sealed)
                    .then_some(chat))
            }
            k if is_message_frame(k, payload) => self.apply_message(&chat, payload).await,
            _ => Ok(None),
        }
    }

    /// A call or system receipt that carries the stored ciphertext row (the
    /// server sends it for a newly settled row, also to the device that wrote
    /// it through the page) puts that row into the history, so the AI history of
    /// the next turn the core builds holds every message the server counts.
    /// Upsert by message id: a later call revision replaces the ciphertext and
    /// attribution of the known row. Version-only receipts add nothing.
    fn upsert_receipt_row(&mut self, chat: &str, payload: &Value) {
        let (Some(message), Some(role), Some(encrypted)) = (
            payload["message_id"].as_str(),
            payload["role"].as_str(),
            payload["encrypted_content"].as_str(),
        ) else {
            return;
        };
        let mut stored = json!({"message_id": message, "chat_id": chat, "role": role,
            "encrypted_content": encrypted, "created_at": payload["created_at"].clone()});
        for field in RECEIPT_ROW_FIELDS {
            if let Some(value) = payload[*field].as_str() {
                stored[*field] = json!(value);
            }
        }
        let rows = self.history.entry(chat.to_owned()).or_default();
        match rows
            .iter_mut()
            .find(|row| row["message_id"] == message || row["client_message_id"] == message)
        {
            Some(row) => {
                row["encrypted_content"] = stored["encrypted_content"].take();
                for field in RECEIPT_ROW_FIELDS {
                    if !stored[*field].is_null() {
                        row[*field] = stored[*field].take();
                    }
                }
            }
            None => rows.push(stored),
        }
    }

    /// Store one final message as a sealed history row and bump `messages_v`.
    ///
    /// The persisted-reply broadcast (`chat_message_added` from the AI
    /// persistence listener) nests the row under `message` and the version
    /// under `versions`; other message frames carry both at the top level.
    async fn apply_message(&mut self, chat: &str, payload: &Value) -> Result<Option<String>> {
        let version = payload["messages_v"]
            .as_u64()
            .or_else(|| payload["versions"]["messages_v"].as_u64());
        let payload_row = payload;
        let payload = payload
            .get("message")
            .filter(|row| row.is_object())
            .unwrap_or(payload);
        let message = payload["message_id"].as_str().ok_or(Error::Protocol)?;
        let role = payload["role"].as_str().unwrap_or("assistant");
        if let Some(key) = payload_row["encrypted_chat_key"]
            .as_str()
            .filter(|_| !self.chats.contains_key(chat))
        {
            self.insert_chat_row(
                chat.to_owned(),
                json!({"id": chat, "encrypted_chat_key": key, "messages_v": 0}),
            );
        }
        let encrypted = match payload["encrypted_content"].as_str() {
            Some(sealed) => sealed.to_owned(),
            None => {
                let content = payload["content"]
                    .as_str()
                    .or_else(|| payload["full_content_so_far"].as_str())
                    .ok_or(Error::Protocol)?;
                let row = self.chats.get(chat).cloned().ok_or(Error::Offline)?;
                let wrapping = self.wrapping_capability().await?;
                let key = self.chat_key_with_capability(&row, &wrapping).await?;
                crypto::encrypt_combined(content, &key)?
            }
        };
        let rows = self.history.entry(chat.to_owned()).or_default();
        let known = rows
            .iter()
            .any(|row| row["message_id"] == message || row["client_message_id"] == message);
        if !known {
            rows.push(json!({
                "message_id": message, "chat_id": chat, "role": role,
                "encrypted_content": encrypted,
                "created_at": payload["created_at"].clone(),
            }));
        }
        if let Some(row) = self.chats.get_mut(chat) {
            raise_version(row, "messages_v", version);
            raise_version(
                row,
                "last_edited_overall_timestamp",
                payload_row["last_edited_overall_timestamp"].as_u64(),
            );
        }
        Ok(Some(chat.to_owned()))
    }

    /// Load one chat the page already knows (for example created moments ago)
    /// into this Client: the chat row with its chat key, `messages_v` and
    /// draft-only flags, plus the bounded history window, cache first then the
    /// server window (`open_chat`). Mutates this same Client instance.
    ///
    /// Never an empty success: the row must be in `Client::chats` afterwards.
    ///
    /// # Errors
    /// Typed [`AdmitChatError`]: `local_profile_read_only` for a local
    /// profile, `forbidden` for another principal or team, `chat_unknown`,
    /// `chat_key_unavailable`, `session_expired`, `unavailable` for network.
    pub async fn admit_chat(
        &mut self,
        chat_id: &str,
        team_id: Option<&str>,
    ) -> std::result::Result<ChatAdmission, AdmitChatError> {
        uuid::Uuid::parse_str(chat_id).map_err(|_| AdmitChatError::InvalidChatId)?;
        self.require_canonical_read_profile()
            .map_err(AdmitChatError::from_error)?;
        let own = self.team().map_err(AdmitChatError::from_error)?;
        if own != team_id {
            return Err(AdmitChatError::Forbidden);
        }
        self.open_chat(chat_id)
            .await
            .map_err(AdmitChatError::from_error)?;
        let row = self.chats.get(chat_id).ok_or(AdmitChatError::ChatUnknown)?;
        Ok(ChatAdmission {
            chat_id: chat_id.to_owned(),
            messages_v: row["messages_v"].as_u64().unwrap_or(0),
            history_rows: self.history.get(chat_id).map_or(0, Vec::len),
        })
    }
}
