//! Fallible conversions from the shapes the core produces today (`Item`,
//! `Message`, `Chat`, `CachedChatWindow`, `StreamUpdate`) into view-model
//! records. Required fields are never defaulted; flags the server omits when
//! false (`pinned`, `archived`, `has_draft`, `unread_count`) are the only
//! documented defaults, and a present value of the wrong type is an error.
use super::error::ViewModelError;
use super::metadata::{ChatRowMetadata, MessageMetadata};
use super::records::{
    ChatListRow, ChatRowStatus, ChatWindowRecord, ChatWindowSource, EmbedRef, MessageRecord,
    MessageRole, MessageStatus, PiiRestoration, StreamEvent,
};
use crate::client::CachedChatWindow;
use crate::model::{Chat, Item, Message, StreamUpdate};
use serde_json::Value;

const ROW: &str = "chat_row";
const EMBED: &str = "embed";
const MESSAGE: &str = "message";
const WINDOW: &str = "chat_window";

fn required_id(id: &str, record: &'static str) -> Result<String, ViewModelError> {
    if id.is_empty() {
        return Err(ViewModelError::MissingField {
            record,
            field: "id",
        });
    }
    Ok(id.to_owned())
}

/// Absent or null yields `None`; any other type is an error.
fn optional_i64(fields: &Value, field: &'static str) -> Result<Option<i64>, ViewModelError> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(value) => value
            .as_i64()
            .map(Some)
            .ok_or(ViewModelError::InvalidField { record: ROW, field }),
    }
}

fn optional_u64(fields: &Value, field: &'static str) -> Result<Option<u64>, ViewModelError> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(value) => value
            .as_u64()
            .map(Some)
            .ok_or(ViewModelError::InvalidField { record: ROW, field }),
    }
}

/// The server omits a false flag, so absent or null means `false`.
fn flag(fields: &Value, field: &'static str) -> Result<bool, ViewModelError> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(false),
        Some(value) => value
            .as_bool()
            .ok_or(ViewModelError::InvalidField { record: ROW, field }),
    }
}

fn optional_text(fields: &Value, field: &'static str) -> Result<Option<String>, ViewModelError> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(text)) => Ok(Some(text.clone())),
        Some(_) => Err(ViewModelError::InvalidField { record: ROW, field }),
    }
}

/// Convert a chat inventory item into a list row.
///
/// # Errors
/// `MissingField` for an empty id, `InvalidField` for a mistyped metadata
/// field, `UnknownVariant` for a status other than empty, `draft` or `locked`.
pub fn chat_list_row_from_item(item: &Item) -> Result<ChatListRow, ViewModelError> {
    let fields = &item.fields;
    let status = match item.status.as_str() {
        "" => ChatRowStatus::Ready,
        "draft" => ChatRowStatus::Draft,
        "locked" => ChatRowStatus::Locked,
        _ => {
            return Err(ViewModelError::UnknownVariant {
                record: ROW,
                field: "status",
            });
        }
    };
    Ok(ChatListRow {
        id: required_id(&item.id, ROW)?,
        title: item.title.clone(),
        chat_list_title: optional_text(fields, "chat_list_title")?,
        summary: item.description.clone(),
        category: item.category.clone(),
        status,
        created_at: optional_i64(fields, "created_at")?,
        updated_at: optional_i64(fields, "updated_at")?,
        messages_v: optional_u64(fields, "messages_v")?,
        unread_count: optional_u64(fields, "unread_count")?.unwrap_or(0),
        pinned: flag(fields, "pinned")?,
        archived: flag(fields, "archived")?,
        has_draft: flag(fields, "has_draft")?,
        footer: optional_text(fields, "footer")?,
        is_saved_item: item.id.starts_with(super::arrange::SAVED_ITEM_ID_PREFIX),
        metadata: ChatRowMetadata::default(),
    })
}

/// First non-empty string among `keys` in an embed's metadata, like the TUI's
/// `from_meta`; empty when none is set.
fn first_text(fields: &Value, keys: &[&str]) -> String {
    keys.iter()
        .filter_map(|key| fields.get(*key).and_then(Value::as_str))
        .find(|text| !text.is_empty())
        .unwrap_or("")
        .to_owned()
}

/// Convert an embed item into a reference.
///
/// # Errors
/// `MissingField` for an empty id, `InvalidField` when the metadata cannot be
/// serialized to `data_json`.
pub fn embed_ref_from_item(item: &Item) -> Result<EmbedRef, ViewModelError> {
    let fields = &item.fields;
    let kind = first_text(fields, &["type"]);
    let title = first_text(fields, &["title", "name", "filename"]);
    let status = first_text(fields, &["status"]);
    Ok(EmbedRef {
        id: required_id(&item.id, EMBED)?,
        kind: if kind.is_empty() {
            item.category.clone()
        } else {
            kind
        },
        app_id: first_text(fields, &["app_id", "app"]),
        skill_id: first_text(fields, &["skill_id", "skill"]),
        title: if title.is_empty() {
            item.title.clone()
        } else {
            title
        },
        description: item.description.clone(),
        status: if status.is_empty() {
            item.status.clone()
        } else {
            status
        },
        data_json: serde_json::to_string(fields).map_err(|_| ViewModelError::InvalidField {
            record: EMBED,
            field: "fields",
        })?,
    })
}

/// Convert a decrypted message; stored messages are always `Complete`.
///
/// # Errors
/// `MissingField` for an empty id, `UnknownVariant` for a role other than
/// `user`, `assistant` or `system`, plus any embed conversion error.
pub fn message_record_from_message(message: &Message) -> Result<MessageRecord, ViewModelError> {
    let role = match message.role.as_str() {
        "user" => MessageRole::User,
        "assistant" => MessageRole::Assistant,
        "system" => MessageRole::System,
        _ => {
            return Err(ViewModelError::UnknownVariant {
                record: MESSAGE,
                field: "role",
            });
        }
    };
    Ok(MessageRecord {
        id: required_id(&message.id, MESSAGE)?,
        role,
        status: MessageStatus::Complete,
        content: message.content.clone(),
        sender: message.sender.clone(),
        thinking: message.thinking.clone(),
        embeds: message
            .embeds
            .iter()
            .map(embed_ref_from_item)
            .collect::<Result<_, _>>()?,
        send_state: None,
        metadata: MessageMetadata::default(),
    })
}

/// Convert a decrypted chat plus the window facts the reader reported.
///
/// # Errors
/// `MissingField` for an empty chat id plus any message conversion error.
pub fn chat_window_from_chat(
    chat: &Chat,
    source: ChatWindowSource,
    has_more_before: Option<bool>,
    history_complete: bool,
    refreshing: bool,
    pii_restoration: PiiRestoration,
) -> Result<ChatWindowRecord, ViewModelError> {
    Ok(ChatWindowRecord {
        chat_id: required_id(&chat.id, WINDOW).map_err(|_| ViewModelError::MissingField {
            record: WINDOW,
            field: "chat_id",
        })?,
        title: chat.title.clone(),
        category: chat.category.clone(),
        messages: chat
            .messages
            .iter()
            .map(message_record_from_message)
            .collect::<Result<_, _>>()?,
        source,
        has_more_before,
        has_more_after: None,
        history_complete,
        refreshing,
        pii_restoration,
    })
}

/// Convert a window published by the cached reader.
///
/// # Errors
/// `UnknownVariant` for a `pii_restoration` word other than `page_local` or
/// `all_cached_user_rows`, plus any error of [`chat_window_from_chat`].
pub fn chat_window_from_cached(
    window: &CachedChatWindow,
    source: ChatWindowSource,
) -> Result<ChatWindowRecord, ViewModelError> {
    let pii = match window.pii_restoration {
        "page_local" => PiiRestoration::PageLocal,
        "all_cached_user_rows" => PiiRestoration::AllCachedUserRows,
        _ => {
            return Err(ViewModelError::UnknownVariant {
                record: WINDOW,
                field: "pii_restoration",
            });
        }
    };
    chat_window_from_chat(
        &window.chat,
        source,
        window.has_more_before,
        window.history_complete,
        window.refreshing,
        pii,
    )
}

/// Convert a core stream update.
///
/// # Errors
/// Only `Consent` can fail, when one of its items has no id.
pub fn stream_event_from_update(update: &StreamUpdate) -> Result<StreamEvent, ViewModelError> {
    Ok(match update {
        StreamUpdate::Consent { request_id, items } => StreamEvent::Consent {
            request_id: request_id.clone(),
            items: items
                .iter()
                .map(embed_ref_from_item)
                .collect::<Result<_, _>>()?,
        },
        StreamUpdate::Started {
            chat_id,
            message_id,
            expects_reply,
        } => StreamEvent::Started {
            chat_id: chat_id.clone(),
            message_id: message_id.clone(),
            expects_reply: *expects_reply,
        },
        StreamUpdate::Submitted {
            chat_id,
            message_id,
        } => StreamEvent::Submitted {
            chat_id: chat_id.clone(),
            message_id: message_id.clone(),
        },
        StreamUpdate::Admitted {
            chat_id,
            message_id,
        } => StreamEvent::Admitted {
            chat_id: chat_id.clone(),
            message_id: message_id.clone(),
        },
        StreamUpdate::Content {
            content,
            thinking,
            mate,
        } => StreamEvent::Content {
            content: content.clone(),
            thinking: thinking.clone(),
            mate: mate.clone(),
        },
        StreamUpdate::Completed {
            chat_id,
            message_id,
            content,
        } => StreamEvent::Completed {
            chat_id: chat_id.clone(),
            message_id: message_id.clone(),
            content: content.clone(),
        },
        StreamUpdate::Status(message) => StreamEvent::Status {
            message: message.clone(),
        },
    })
}
