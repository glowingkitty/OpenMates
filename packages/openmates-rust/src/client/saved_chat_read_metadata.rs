//! Closed authoritative read metadata. No cache authority, raw ciphertext or keys.
use super::super::plaintext::Plain;
use super::super::sync::decrypt_optional;
use super::{SavedChatMessageMetadata, SavedChatReadMetadata};
use crate::{Error, Result, model::Message};
use serde_json::Value;
const MAX_METADATA_BYTES: usize = 256 * 1024;
const MAX_PUBLIC_INTEGER: u64 = 9_007_199_254_740_991;
const MAX_FIELD_BYTES: usize = 64 * 1024;
pub(in crate::client) fn string(row: &Value, name: &str) -> Result<Option<String>> {
    match row.get(name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) if value.len() <= MAX_FIELD_BYTES => Ok(Some(value.clone())),
        _ => Err(Error::Protocol),
    }
}
pub(in crate::client) fn boolean(row: &Value, name: &str) -> Result<Option<bool>> {
    match row.get(name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Bool(v)) => Ok(Some(*v)),
        _ => Err(Error::Protocol),
    }
}
pub(in crate::client) fn unsigned(row: &Value, name: &str) -> Result<Option<u64>> {
    match row.get(name) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => v
            .as_u64()
            .filter(|v| *v <= MAX_PUBLIC_INTEGER)
            .map(Some)
            .ok_or(Error::Protocol),
    }
}
// The metadata route explicitly serializes source timestamps as decimal strings.
// Accept exact nonnegative integers only, never a clock or floating-point fallback.
pub(in crate::client) fn timestamp(row: &Value, name: &str) -> Result<Option<i64>> {
    match row.get(name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value))
            if !value.is_empty() && value.bytes().all(|v| v.is_ascii_digit()) =>
        {
            value
                .parse::<i64>()
                .ok()
                .filter(|v| *v >= 0 && (*v as u64) <= MAX_PUBLIC_INTEGER)
                .map(Some)
                .ok_or(Error::Protocol)
        }
        Some(value) => value
            .as_i64()
            .filter(|v| *v >= 0 && (*v as u64) <= MAX_PUBLIC_INTEGER)
            .map(Some)
            .ok_or(Error::Protocol),
    }
}
pub(in crate::client) fn encrypted(row: &Value, name: &str, key: &[u8; 32]) -> Result<Option<String>> {
    let value = Plain::new(decrypt_optional(row, name, key)?);
    if value.len() > MAX_FIELD_BYTES {
        return Err(Error::Protocol);
    }
    if row
        .get(name)
        .and_then(Value::as_str)
        .is_some_and(|v| !v.is_empty())
    {
        Ok(Some(value.into_inner()))
    } else {
        Ok(None)
    }
}
/// Optional display field semantics shared by selected rich read projection.
/// Missing/nonstring/empty or authentication-failed optional display ciphertext
/// is null, matching the maintained raw TS reader. Mandatory key/owner/source
/// admission is still checked separately; legacy saved-read strictness stays.
pub(in crate::client) fn projection_encrypted(row:&Value,name:&str,key:&[u8;32])->Result<Option<String>> {
    projection_text(row,name,key,Some(MAX_FIELD_BYTES))
}
pub(in crate::client) fn projection_message_text(row:&Value,name:&str,key:&[u8;32])->Result<Option<String>> {
    projection_text(row,name,key,None)
}
fn projection_text(row:&Value,name:&str,key:&[u8;32],max:Option<usize>)->Result<Option<String>> {
    if row.get(name).and_then(Value::as_str).is_none_or(str::is_empty){return Ok(None);}
    let plain=Plain::new(match decrypt_optional(row,name,key){Ok(value)=>value,Err(Error::Crypto)=>return Ok(None),Err(error)=>return Err(error)});
    if max.is_some_and(|max|plain.len()>max){return Err(Error::Protocol);}
    Ok(Some(plain.into_inner()))
}
pub(in crate::client) fn strings(row: &Value, name: &str) -> Result<Option<Vec<String>>> {
    match row.get(name) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Array(values)) if values.len() <= 1024 => {
            let mut output = Plain::new(Vec::<String>::new());
            for value in values {
                output.push(
                    value
                        .as_str()
                        .filter(|s| s.len() <= MAX_FIELD_BYTES)
                        .ok_or(Error::Protocol)?
                        .to_owned(),
                );
            }
            Ok(Some(output.into_inner()))
        }
        _ => Err(Error::Protocol),
    }
}
/// The optional exact slug uses the SAME authenticated metadata field decoder as
/// saved reads. No selector/title-derived fallback or plaintext metadata cache.
pub(in crate::client) fn chat_slug(row: &Value, id: &str, key: &[u8; 32]) -> Result<Option<String>> {
    if crate::client::monitor::cached_view::bounded_bytes(row, MAX_METADATA_BYTES).is_none() {
        return Err(Error::Protocol);
    }
    if row.get("id").and_then(Value::as_str) != Some(id) { return Err(Error::Forbidden); }
    encrypted(row, "encrypted_slug", key)
}
pub(in crate::client) fn chat(
    row: &Value,
    id: &str,
    key: &[u8; 32],
) -> Result<SavedChatReadMetadata> {
    if crate::client::monitor::cached_view::bounded_bytes(row, MAX_METADATA_BYTES).is_none() {
        return Err(Error::Protocol);
    }
    if row.get("id").and_then(Value::as_str) != Some(id) {
        return Err(Error::Forbidden);
    }
    let suggestions = {
        let plain = Plain::new(encrypted(
            row,
            "encrypted_follow_up_request_suggestions",
            key,
        )?);
        Plain::new(match plain.as_ref() {
            None => None,
            Some(plain) => {
                let values = Plain::new(serde_json::from_str::<Vec<String>>(plain)?);
                if values.len() > 256 || values.iter().any(|value| value.len() > 2048) {
                    return Err(Error::Protocol);
                }
                Some(values.into_inner())
            }
        })
    };
    let has_draft = match row.get("encrypted_draft_md") {
        None | Some(Value::Null) => None,
        Some(Value::String(v)) => Some(!v.is_empty()),
        _ => return Err(Error::Protocol),
    };
    let mut metadata = Plain::new(SavedChatReadMetadata {
        id: Default::default(),
        title: Default::default(),
        summary: Default::default(),
        category: Default::default(),
        slug: Default::default(),
        active_focus_id: Default::default(),
        created_at: Default::default(),
        last_edited_at: Default::default(),
        metadata_updated_at: Default::default(),
        parent_id: Default::default(),
        is_sub_chat: Default::default(),
        is_hidden: Default::default(),
        pinned: Default::default(),
        chat_visibility: Default::default(),
        participant_user_hashes: Default::default(),
        has_draft: Default::default(),
        follow_up_suggestions: Default::default(),
    });
    metadata.id = id.into();
    metadata.title = encrypted(row, "encrypted_title", key)?;
    metadata.summary = encrypted(row, "encrypted_chat_summary", key)?;
    metadata.category = encrypted(row, "encrypted_category", key)?;
    metadata.slug = encrypted(row, "encrypted_slug", key)?;
    metadata.active_focus_id = encrypted(row, "encrypted_active_focus_id", key)?;
    metadata.created_at = timestamp(row, "created_at")?;
    metadata.last_edited_at = timestamp(row, "last_edited_overall_timestamp")?;
    metadata.metadata_updated_at = timestamp(row, "updated_at")?;
    metadata.parent_id = string(row, "parent_id")?;
    metadata.is_sub_chat = boolean(row, "is_sub_chat")?;
    metadata.is_hidden = boolean(row, "is_hidden")?;
    metadata.pinned = boolean(row, "pinned")?;
    metadata.chat_visibility = string(row, "chat_visibility")?;
    metadata.participant_user_hashes = strings(row, "participant_user_hashes")?;
    metadata.has_draft = has_draft;
    metadata.follow_up_suggestions = suggestions.into_inner();
    if crate::client::monitor::cached_view::bounded_bytes(&*metadata, MAX_METADATA_BYTES).is_none() {
        return Err(Error::Protocol);
    }
    Ok(metadata.into_inner())
}
pub(in crate::client) fn message(
    row: &Value,
    message: &Message,
    chat_id: &str,
    key: &[u8; 32],
) -> Result<SavedChatMessageMetadata> {
    message_projection(row, message, chat_id, key, false)
}
/// Only for the unchanged row and Message returned by the strict canonical
/// decoder in this page read. Its sender has already authenticated successfully.
pub(in crate::client) fn message_from_decoded(
    row: &Value, message: &Message, chat_id: &str, key: &[u8; 32],
) -> Result<SavedChatMessageMetadata> {
    message_projection(row, message, chat_id, key, true)
}
fn message_projection(
    row: &Value, message: &Message, chat_id: &str, key: &[u8; 32],
    decoded_sender: bool,
) -> Result<SavedChatMessageMetadata> {
    // The canonical decoder already authenticated content/chat/ID/ordering; retain
    // the source timestamp it validated instead of throwing it away in projection.
    let created_at = row
        .get("created_at")
        .and_then(Value::as_i64)
        .filter(|v| *v >= 0 && (*v as u64) <= MAX_PUBLIC_INTEGER)
        .ok_or(Error::Protocol)?;
    if row
        .get("chat_id")
        .filter(|v| !v.is_null())
        .is_some_and(|v| v.as_str() != Some(chat_id))
    {
        return Err(Error::Forbidden);
    }
    let mut metadata = Plain::new(SavedChatMessageMetadata {
        id: Default::default(),
        storage_id: Default::default(),
        source_message_id: Default::default(),
        client_message_id: Default::default(),
        chat_id: Default::default(),
        created_at: Default::default(),
        raw_status: Default::default(),
        sender_name: Default::default(),
        category: Default::default(),
        model_name: Default::default(),
        thinking_signature: Default::default(),
        has_thinking: Default::default(),
        thinking_token_count: Default::default(),
        hashed_user_id: Default::default(),
        user_message_id: Default::default(),
        key_version: Default::default(),
        queue_revision: Default::default(),
        queue_mode: Default::default(),
        queue_dispatch_status: Default::default(),
        queue_dispatch_mode: Default::default(),
        queue_dispatch_task_id: Default::default(),
        embed_ids: Default::default(),
    });
    metadata.id = message.id.clone();
    metadata.storage_id = string(row, "id")?;
    metadata.source_message_id = string(row, "message_id")?;
    metadata.client_message_id = string(row, "client_message_id")?;
    metadata.chat_id = chat_id.into();
    metadata.created_at = created_at;
    metadata.raw_status = string(row, "status")?;
    metadata.sender_name = if decoded_sender {
        // Keep metadata's size cap and ciphertext-presence semantics. Empty
        // plaintext in a nonempty valid envelope is Some(""); absent/null/empty
        // ciphertext is None. Shape/authentication already failed in decoding.
        if message.sender.len() > MAX_FIELD_BYTES {
            return Err(Error::Protocol);
        }
        row.get("encrypted_sender_name").and_then(Value::as_str)
            .filter(|value| !value.is_empty()).map(|_| message.sender.clone())
    } else {
        encrypted(row, "encrypted_sender_name", key)?
    };
    metadata.category = encrypted(row, "encrypted_category", key)?;
    metadata.model_name = encrypted(row, "encrypted_model_name", key)?;
    metadata.thinking_signature = encrypted(row, "encrypted_thinking_signature", key)?;
    metadata.has_thinking = boolean(row, "has_thinking")?;
    metadata.thinking_token_count = unsigned(row, "thinking_token_count")?;
    metadata.hashed_user_id = string(row, "hashed_user_id")?;
    metadata.user_message_id = string(row, "user_message_id")?;
    metadata.key_version = unsigned(row, "key_version")?;
    metadata.queue_revision = unsigned(row, "queue_revision")?;
    metadata.queue_mode = string(row, "queue_mode")?;
    metadata.queue_dispatch_status = string(row, "queue_dispatch_status")?;
    metadata.queue_dispatch_mode = string(row, "queue_dispatch_mode")?;
    metadata.queue_dispatch_task_id = string(row, "queue_dispatch_task_id")?;
    metadata.embed_ids = None;
    if crate::client::monitor::cached_view::bounded_bytes(&*metadata, MAX_METADATA_BYTES).is_none() {
        return Err(Error::Protocol);
    }
    Ok(metadata.into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    const CHAT: &str = "22222222-2222-4222-8222-222222222222";
    const MESSAGE: &str = "10000000-0000-4000-8000-000000000001";
    fn presentation() -> Message {
        Message {
            id: MESSAGE.into(),
            role: "assistant".into(),
            ..Default::default()
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[test]
    fn exact_zero_and_unknown_source_metadata_are_distinct_from_display_fallbacks() {
        let row = json!({"id":"storage-row","client_message_id":MESSAGE,"chat_id":CHAT,"created_at":0,"queue_revision":0,"key_version":0,"has_thinking":false,"status":"queued","encrypted_sender_name":crate::crypto::encrypt_combined("",&[7;32]).unwrap()});
        let value = message(&row, &presentation(), CHAT, &[7; 32]).unwrap();
        assert_eq!(value.id, MESSAGE);
        assert_eq!(value.storage_id.as_deref(), Some("storage-row"));
        assert_eq!(value.created_at, 0);
        assert_eq!(value.queue_revision, Some(0));
        assert_eq!(value.key_version, Some(0));
        assert_eq!(value.sender_name.as_deref(), Some(""));
        assert_eq!(value.raw_status.as_deref(), Some("queued"));
        assert_eq!(value.has_thinking, Some(false));
        assert!(value.embed_ids.is_none());
        assert!(value.model_name.is_none());
        assert!(
            serde_json::to_value(value)
                .unwrap()
                .get("displayStatus")
                .is_none()
        );
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[test]
    fn missing_malformed_and_unsafe_source_times_never_use_a_clock() {
        for time in [
            Value::Null,
            json!("1700000000"),
            json!(-1),
            json!(9007199254740992u64),
        ] {
            let row = json!({"created_at":time});
            assert!(message(&row, &presentation(), CHAT, &[7; 32]).is_err());
        }
        assert!(message(&json!({}), &presentation(), CHAT, &[7; 32]).is_err());
        for revision in [
            json!(-1),
            json!(1.5),
            json!(true),
            json!(9007199254740992u64),
        ] {
            assert!(
                message(
                    &json!({"created_at":1,"queue_revision":revision}),
                    &presentation(),
                    CHAT,
                    &[7; 32]
                )
                .is_err()
            );
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[test]
    fn header_projects_only_typed_public_fields_and_preserves_unknowns() {
        let raw = json!({"id":CHAT,"created_at":"1700000000","updated_at":0,"encrypted_chat_key":"PRIVATE_KEY_CANARY","cookies":"PRIVATE_COOKIE_CANARY","session":"PRIVATE_SESSION_CANARY"});
        let result = chat(&raw, CHAT, &[7; 32]).unwrap();
        assert_eq!(result.created_at, Some(1700000000));
        assert_eq!(result.metadata_updated_at, Some(0));
        assert!(result.follow_up_suggestions.is_none());
        assert!(result.title.is_none());
        let output = serde_json::to_string(&result).unwrap();
        for forbidden in ["PRIVATE_", "encrypted_chat_key", "cookies", "session"] {
            assert!(!output.contains(forbidden));
        }
        for time in [
            json!("now"),
            json!("9007199254740992"),
            json!(true),
            json!(-1),
        ] {
            assert!(chat(&json!({"id":CHAT,"created_at":time}), CHAT, &[7; 32]).is_err());
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[test]
    fn projected_header_exact_boundary_and_one_over_are_enforced() {
        let mut values = vec!["x".repeat(MAX_FIELD_BYTES); 3];
        values.push(String::new());
        let mut row = json!({"id":CHAT,"participant_user_hashes":values});
        let baseline = chat(&row, CHAT, &[7; 32]).unwrap();
        let remaining = MAX_METADATA_BYTES - serde_json::to_vec(&baseline).unwrap().len();
        assert!(remaining <= MAX_FIELD_BYTES);
        row["participant_user_hashes"][3] = json!("x".repeat(remaining));
        assert!(serde_json::to_vec(&row).unwrap().len() <= MAX_METADATA_BYTES);
        let exact = chat(&row, CHAT, &[7; 32]).unwrap();
        assert_eq!(
            serde_json::to_vec(&exact).unwrap().len(),
            MAX_METADATA_BYTES
        );
        row["participant_user_hashes"][3] = json!("x".repeat(remaining + 1));
        assert!(serde_json::to_vec(&row).unwrap().len() <= MAX_METADATA_BYTES);
        assert!(matches!(chat(&row, CHAT, &[7; 32]), Err(Error::Protocol)));
    }
}
