//! Test-only seed of a chosen chat list for the Apple UI-test fixtures. The
//! Swift fixtures describe their sidebar rows (id, title, times, pin, unread,
//! draft, messages) as JSON; this module seals them as a server sync would and
//! writes them through the core's real cache path (`view_fixture::write_cache`),
//! so `ViewModelCore.start` emits them as the cached `ChatList`. Swift reaches
//! it through the C entry in `view_fixture_ffi`. Compiled only for tests and
//! with the `test-support` feature. Plan `apple-client-core-migration` (A4).
use crate::CoreError;
use crate::view_fixture::{sealed, synthetic_session, write_cache};
use openmates_sdk::crypto::{Key, encrypt_bytes, random_key};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;

/// Most chats one seed writes (the shell performance fixture asks for up to 2000).
const MAX_CHATS: usize = 2_000;
/// Most messages of one seeded chat.
const MAX_MESSAGES: usize = 200;
/// Longest seeded text (title, summary, draft, message).
const MAX_TEXT: usize = 4_096;
/// Longest chat id.
const MAX_ID: usize = 128;

/// Request keys; anything else is refused so a typo never seeds a silent default.
const REQUEST_KEYS: &[&str] = &[
    "api_url",
    "cache_container",
    "cache_directory_name",
    "chats",
];
const CHAT_KEYS: &[&str] = &[
    "id",
    "title",
    "summary",
    "category",
    "icon",
    "app_id",
    "created_at",
    "updated_at",
    "last_message_at",
    "last_edited_at",
    "pinned",
    "unread_count",
    "draft",
    "messages",
];
const MESSAGE_KEYS: &[&str] = &["role", "content", "created_at"];

fn invalid(message: &str) -> CoreError {
    CoreError::Invalid {
        message: message.to_owned(),
    }
}

fn object<'a>(
    value: &'a Value,
    keys: &[&str],
    what: &str,
) -> Result<&'a Map<String, Value>, CoreError> {
    let map = value
        .as_object()
        .ok_or_else(|| invalid(&format!("The {what} must be a JSON object.")))?;
    if let Some(unknown) = map.keys().find(|key| !keys.contains(&key.as_str())) {
        return Err(invalid(&format!("Unknown {what} field `{unknown}`.")));
    }
    Ok(map)
}

/// A present string of at most `MAX_TEXT` bytes; `None` when absent or null.
fn text<'a>(map: &'a Map<String, Value>, key: &str) -> Result<Option<&'a str>, CoreError> {
    match map.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) if value.len() <= MAX_TEXT => Ok(Some(value)),
        Some(_) => Err(invalid(&format!(
            "`{key}` must be a string of at most 4096 bytes."
        ))),
    }
}

fn required_text<'a>(map: &'a Map<String, Value>, key: &str) -> Result<&'a str, CoreError> {
    text(map, key)?
        .filter(|value| !value.is_empty())
        .ok_or_else(|| invalid(&format!("`{key}` is required.")))
}

/// A non-negative unix time in seconds (the server's unit for chat rows).
fn seconds(map: &Map<String, Value>, key: &str) -> Result<Option<i64>, CoreError> {
    match map.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(value) => value
            .as_i64()
            .filter(|seconds| (0..100_000_000_000).contains(seconds))
            .map(Some)
            .ok_or_else(|| invalid(&format!("`{key}` must be unix seconds."))),
    }
}

/// One user or assistant message row sealed with the chat key.
fn message_row(chat: &str, index: usize, value: &Value, key: &Key) -> Result<Value, CoreError> {
    let map = object(value, MESSAGE_KEYS, "message")?;
    let role = required_text(map, "role")?;
    if role != "user" && role != "assistant" {
        return Err(invalid("A message `role` is `user` or `assistant`."));
    }
    let content = text(map, "content")?.unwrap_or_default();
    let created_at =
        seconds(map, "created_at")?.ok_or_else(|| invalid("`created_at` is required."))?;
    let id = format!("{chat}-message-{}", index + 1);
    Ok(json!({
        "id": id, "client_message_id": id, "chat_id": chat, "role": role,
        "created_at": created_at, "status": "synced",
        "encrypted_content": sealed(content, key)?,
    }))
}

/// The stored chat row and its message rows. A chat with a draft, no title
/// and no messages is a draft-only chat: like a never-sent new chat it has no
/// chat key, and the core shows its draft preview as the row title.
fn chat_rows(value: &Value, master: &Key) -> Result<(String, Value, Vec<Value>), CoreError> {
    let map = object(value, CHAT_KEYS, "chat")?;
    let id = required_text(map, "id")?;
    if id.len() > MAX_ID || id.starts_with("embed:") {
        return Err(invalid(
            "A chat `id` has at most 128 bytes and is not a saved-item id.",
        ));
    }
    let created_at =
        seconds(map, "created_at")?.ok_or_else(|| invalid("`created_at` is required."))?;
    let updated_at = seconds(map, "updated_at")?.unwrap_or(created_at);
    let title = text(map, "title")?.filter(|title| !title.is_empty());
    let draft = text(map, "draft")?.filter(|draft| !draft.is_empty());
    let messages = match map.get("messages") {
        None | Some(Value::Null) => &[][..],
        Some(Value::Array(messages)) if messages.len() <= MAX_MESSAGES => messages.as_slice(),
        Some(_) => return Err(invalid("`messages` is an array of at most 200 messages.")),
    };
    let pinned = match map.get("pinned") {
        None | Some(Value::Null) => false,
        Some(Value::Bool(pinned)) => *pinned,
        Some(_) => return Err(invalid("`pinned` must be a boolean.")),
    };
    let unread = match map.get("unread_count") {
        None | Some(Value::Null) => 0,
        Some(value) => value
            .as_u64()
            .ok_or_else(|| invalid("`unread_count` must be a non-negative integer."))?,
    };
    let mut row = json!({
        "id": id, "created_at": created_at, "updated_at": updated_at,
        "last_edited_overall_timestamp": seconds(map, "last_edited_at")?.unwrap_or(updated_at),
        "last_message_timestamp": seconds(map, "last_message_at")?,
        "messages_v": messages.len(), "pinned": pinned, "unread_count": unread,
        "draft_v": u64::from(draft.is_some()),
    });
    if let Some(app_id) = text(map, "app_id")? {
        row["app_id"] = json!(app_id);
    }
    if let Some(draft) = draft {
        // Drafts are sealed with the master key, as the draft sync stores them.
        row["encrypted_draft_md"] = json!(sealed(draft, master)?);
        row["encrypted_draft_preview"] = json!(sealed(draft, master)?);
    }
    if draft.is_some() && title.is_none() && messages.is_empty() {
        return Ok((id.to_owned(), row, Vec::new()));
    }
    let key = random_key();
    row["encrypted_chat_key"] = json!(encrypt_bytes(key.as_slice(), master)?);
    for (field, name) in [
        ("encrypted_title", title),
        ("encrypted_chat_summary", text(map, "summary")?),
        ("encrypted_category", text(map, "category")?),
        ("encrypted_icon", text(map, "icon")?),
    ] {
        if let Some(name) = name {
            row[field] = json!(sealed(name, &key)?);
        }
    }
    let history = messages
        .iter()
        .enumerate()
        .map(|(index, message)| message_row(id, index, message, &key))
        .collect::<Result<Vec<_>, _>>()?;
    Ok((id.to_owned(), row, history))
}

/// Seed the chat list described by the JSON `request` (`api_url`,
/// `cache_container`, `cache_directory_name`, `chats`: rows with `id`,
/// `created_at` in unix seconds and optional `title`, `summary`, `category`,
/// `icon`, `app_id`, `updated_at`, `last_message_at`, `last_edited_at`,
/// `pinned`, `unread_count`, `draft`, `messages` of `role`/`content`/
/// `created_at`) into a fresh synthetic account's encrypted cache and return
/// that account's credential payload. Started with that payload and the same
/// cache pair, `ViewModelCore.start` emits `Session(Restored)` and
/// `ChatList(Cached)` with these rows in the core's own order. The account
/// exists on no server; use an unreachable `api_url`. Blocks the calling
/// thread; never call it from an async context.
///
/// # Errors
/// `Invalid` for malformed JSON, an unknown field, a missing id or time, a
/// duplicate id, zero or more than 2000 chats, more than 200 messages per
/// chat, oversized text, or a bad cache path; cache write and encryption errors.
pub(crate) fn seed_chat_list(request: &[u8]) -> Result<Vec<u8>, CoreError> {
    let request: Value =
        serde_json::from_slice(request).map_err(|_| invalid("The seed request is not JSON."))?;
    let map = object(&request, REQUEST_KEYS, "seed request")?;
    let chats = match map.get("chats") {
        Some(Value::Array(chats)) if !chats.is_empty() && chats.len() <= MAX_CHATS => chats,
        _ => return Err(invalid("Seed 1 to 2000 chats.")),
    };
    let session = synthetic_session(required_text(map, "api_url")?.to_owned());
    let (mut rows, mut history, mut ids) = (Map::new(), Map::new(), BTreeSet::new());
    for chat in chats {
        let (id, row, messages) = chat_rows(chat, &session.master_key)?;
        if !ids.insert(id.clone()) {
            return Err(invalid("Chat ids must be unique."));
        }
        rows.insert(id.clone(), row);
        if !messages.is_empty() {
            history.insert(id, Value::Array(messages));
        }
    }
    let snapshot = json!({"chats": rows, "wrappers": [], "history": history,
        "embeds": {}, "embed_keys": [], "team_wrapped_key": null});
    write_cache(
        &session,
        required_text(map, "cache_container")?,
        required_text(map, "cache_directory_name")?,
        &snapshot,
    )
}
