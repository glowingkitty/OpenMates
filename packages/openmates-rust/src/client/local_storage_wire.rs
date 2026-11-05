//! Maintained IndexedDB ciphertext row addressing for local reads only.
//! These identifiers are selectors under existing owner/key admission, not grants.
//! Canonical/local message selectors share a bounded predicate, not authority.
//! Bound the complete raw packet before selecting/decrypting at most twenty rows.
//! Preserve storage and client aliases; do not normalize or rewrite stored data.
//! Current-window compression follows deployed latest-checkpoint timestamp rules.
use super::super::*;
use super::super::message_window::{MessageWindowDirection, MessageWindowOptions};
use super::super::plaintext::Plain;
use std::collections::BTreeSet;

pub(super) const MAX_LOCAL_ROWS: usize = 1024;
const MAX_CHECKPOINTS: usize = 128;
const MAX_PUBLIC_INTEGER: i64 = 9_007_199_254_740_991;

pub(in crate::client) fn storage_id(value: &str) -> Result<()> {
    // Existing local message IDs are opaque string keys. Do not strip
    // chat suffixes or prefer a UUID merely because another alias is present.
    if !super::super::message_window::valid_message_id(value) {
        return Err(Error::Protocol);
    }
    Ok(())
}
/// IndexedDB string keys compare UTF-16 code units, unlike canonical server
/// COLLATE "C" / Rust UTF-8 byte ordering. This is physical-key order only;
/// maintained TS localeCompare cursor filtering is a separate legacy contract.
pub(in crate::client) fn idb_key_cmp(a: &str, b: &str) -> std::cmp::Ordering {
    a.encode_utf16().cmp(b.encode_utf16())
}
pub(in crate::client) fn position_cmp(a: (i64, &str), b: (i64, &str)) -> std::cmp::Ordering {
    a.0.cmp(&b.0).then_with(|| idb_key_cmp(a.1, b.1))
}
fn timestamp(row: &Value, field: &str) -> Result<i64> {
    row[field].as_i64().filter(|n| (0..=MAX_PUBLIC_INTEGER).contains(n)).ok_or(Error::Protocol)
}
pub(in crate::client) fn position(row: &Value) -> Result<(i64, &str)> {
    let id = ["message_id", "id"].into_iter()
        .find_map(|field| row[field].as_str().filter(|v| !v.is_empty()))
        .ok_or(Error::Protocol)?;
    storage_id(id)?;
    Ok((timestamp(row, "created_at")?, id))
}
pub(in crate::client) fn validate_options(options: &MessageWindowOptions, id: &str, scope: &str) -> Result<()> {
    if super::super::monitor::cached_view::bounded_bytes(options, super::super::message_window::MAX_MESSAGE_BYTES).is_none() {
        return Err(Error::Protocol);
    }
    if !(1..=super::super::message_window::MAX_MESSAGES).contains(&options.limit) {
        return Err(Error::Invalid("Message window limit must be between 1 and 20."));
    }
    let paging = matches!(options.direction, MessageWindowDirection::Before | MessageWindowDirection::After);
    if paging != options.cursor.is_some()
        || (options.direction == MessageWindowDirection::Around) != options.anchor_message_id.is_some() {
        return Err(Error::Invalid("Local window requires its exact cursor or anchor."));
    }
    if let Some(cursor) = &options.cursor {
        storage_id(&cursor.message_id)?;
        if !(0..=MAX_PUBLIC_INTEGER).contains(&cursor.created_at) || cursor.scope.len() != 64
            || !cursor.scope.bytes().all(|v| v.is_ascii_hexdigit()) { return Err(Error::Protocol); }
        if cursor.chat_id != id || cursor.scope != scope { return Err(Error::Conflict); }
    }
    if let Some(anchor) = &options.anchor_message_id { storage_id(anchor)?; }
    Ok(())
}
pub(in crate::client) fn message_rows(input: &[Value], chat_id: &str) -> Result<Vec<Value>> {
    if input.len() > MAX_LOCAL_ROWS
        || crate::client::monitor::cached_view::bounded_bytes(&input, super::super::message_window::MAX_MESSAGE_BYTES).is_none() {
        return Err(Error::Protocol);
    }
    let mut rows = Plain::new(Vec::with_capacity(input.len()));
    let mut storage_seen = BTreeSet::new();
    let mut logical_seen = BTreeSet::new();
    let mut previous: Option<(i64, String)> = None;
    for source in input {
        let raw = Plain::new(if let Some(encoded) = source.as_str() { serde_json::from_str(encoded)? } else { source.clone() });
        if !raw.is_object() { return Err(Error::Protocol); }
        if raw.get("chat_id").is_some_and(|value| value.as_str() != Some(chat_id)) { return Err(Error::Forbidden); }
        let (created_at, physical_id) = position(&raw)?;
        let logical_id = ["client_message_id", "message_id", "id"].into_iter()
            .find_map(|field| raw[field].as_str().filter(|v| !v.is_empty())).ok_or(Error::Protocol)?;
        for field in ["id", "message_id", "client_message_id"] {
            if let Some(value) = raw.get(field).filter(|v| !v.is_null()) { storage_id(value.as_str().ok_or(Error::Protocol)?)?; }
        }
        let current = (created_at, physical_id.to_owned());
        if !storage_seen.insert(physical_id.to_owned()) || !logical_seen.insert(logical_id.to_owned())
            || previous.as_ref().is_some_and(|p| !position_cmp((p.0, p.1.as_str()), (current.0, current.1.as_str())).is_lt()) { return Err(Error::Protocol); }
        previous = Some(current);
        let role = required(&raw, "role")?;
        if role.is_empty() || role.len() > 32 { return Err(Error::Protocol); }
        for field in ["encrypted_content", "encrypted_sender_name", "encrypted_category", "encrypted_model_name",
            "encrypted_thinking_content", "encrypted_thinking_signature", "encrypted_pii_mappings"] {
            if raw.get(field).filter(|v| !v.is_null()).is_some_and(|v| !v.is_string()) { return Err(Error::Protocol); }
        }
        if let Some(reference) = raw.get("large_payload").filter(|v| !v.is_null()) {
            let size = reference["size_bytes"].as_u64().ok_or(Error::Protocol)?;
            let checksum = required(reference, "checksum")?;
            if size == 0 || size > super::super::saved_chat_read::MAX_EXACT_BYTES as u64
                || checksum.len() != 64 || !checksum.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)) {
                return Err(Error::Protocol);
            }
            required(reference, "object_key")?;
        }
        rows.push(raw.into_inner());
    }
    Ok(rows.into_inner())
}

/// The shared decoder currently clones its argument into an ordinary Value.
/// Only closed ciphertext/addressing fields may cross that ownership boundary;
/// all rich source extensions stay inside the caller's Plain-owned row vector.
pub(in crate::client) fn decode_projection(row: &Value) -> Result<Value> {
    let mut closed = serde_json::Map::new();
    for field in ["id", "message_id", "client_message_id", "chat_id", "created_at", "role",
        "encrypted_content", "encrypted_sender_name", "encrypted_category", "encrypted_model_name",
        "encrypted_thinking_content", "encrypted_thinking_signature", "encrypted_pii_mappings"] {
        if let Some(value) = row.get(field).filter(|v| !v.is_null()) { closed.insert(field.into(), value.clone()); }
    }
    if let Some(reference) = row.get("large_payload").filter(|v| !v.is_null()) {
        let mut descriptor = serde_json::Map::new();
        for field in ["object_key", "checksum", "size_bytes"] {
            descriptor.insert(field.into(), reference.get(field).ok_or(Error::Protocol)?.clone());
        }
        closed.insert("large_payload".into(), Value::Object(descriptor));
    }
    Ok(Value::Object(closed))
}

pub(in crate::client) fn compression_timestamp(checkpoints: &[Value], chat_id: &str) -> Result<Option<i64>> {
    if checkpoints.len() > MAX_CHECKPOINTS
        || crate::client::monitor::cached_view::bounded_bytes(&checkpoints, super::super::message_window::MAX_MESSAGE_BYTES).is_none() {
        return Err(Error::Protocol);
    }
    let mut ids = BTreeSet::new();
    let mut latest: Option<(i64, &str, i64)> = None;
    for row in checkpoints {
        if !row.is_object() || required(row, "chat_id")? != chat_id { return Err(Error::Forbidden); }
        let id = required(row, "id")?; storage_id(id)?;
        if !ids.insert(id) { return Err(Error::Protocol); }
        let created = timestamp(row, "created_at")?;
        let boundary = timestamp(row, "compressed_up_to_timestamp")?;
        row["compressed_message_count"].as_u64().filter(|v| *v <= MAX_PUBLIC_INTEGER as u64).ok_or(Error::Protocol)?;
        if let Some(value) = row.get("compressed_up_to_message_id").filter(|v| !v.is_null()) { storage_id(value.as_str().ok_or(Error::Protocol)?)?; }
        if let Some(value) = row.get("covered_message_ids").filter(|v| !v.is_null()) {
            let values = value.as_array().ok_or(Error::Protocol)?;
            if values.len() > MAX_LOCAL_ROWS { return Err(Error::Protocol); }
            for value in values { storage_id(value.as_str().ok_or(Error::Protocol)?)?; }
        }
        if row.get("encrypted_summary").filter(|v| !v.is_null()).is_some_and(|v| !v.is_string()) { return Err(Error::Protocol); }
        // getAll(chat_id_created_at) + stable descending created_at sort picks
        // the first primary key at an equal timestamp; preserve that tie rule.
        if latest.is_none_or(|(time, key, _)| created > time || created == time && idb_key_cmp(id, key).is_lt()) {
            latest = Some((created, id, boundary));
        }
    }
    Ok(latest.map(|(_, _, timestamp)| timestamp))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn local_packet_caps_refuse_whole_input_without_truncating() {
        let row = json!({"id":"local-row","role":"user","created_at":1});
        assert!(message_rows(&vec![row; MAX_LOCAL_ROWS + 1], "chat").is_err());
        let checkpoint = json!({"id":"checkpoint"});
        assert!(compression_timestamp(&vec![checkpoint; MAX_CHECKPOINTS + 1], "chat").is_err());
        let oversized = json!({"id":"row","role":"user","created_at":1,"encrypted_content":"x".repeat(256*1024)});
        assert!(message_rows(&[oversized], "chat").is_err());
    }
    #[test]
    fn equal_created_checkpoint_tie_matches_existing_idb_stable_sort() {
        let a = json!({"id":"a","chat_id":"chat","created_at":2,"compressed_up_to_timestamp":10,"compressed_message_count":1});
        let b = json!({"id":"b","chat_id":"chat","created_at":2,"compressed_up_to_timestamp":20,"compressed_message_count":1});
        assert_eq!(compression_timestamp(&[b,a],"chat").unwrap(),Some(10));
    }
}

#[cfg(test)]
mod decode_projection_tests {
    use super::*;
    #[test]
    fn rich_plaintext_and_nested_reference_extensions_never_cross_decoder_boundary() {
        let row = json!({"message_id":"local-row","created_at":1,"role":"user",
            "encrypted_content":"ciphertext","content":"PRIVATE_CLEAR_SENTINEL",
            "summary":"PRIVATE_CLEAR_SENTINEL","extension":{"nested":"PRIVATE_CLEAR_SENTINEL"},
            "large_payload":{"object_key":"opaque","checksum":"a".repeat(64),"size_bytes":1,"summary":"PRIVATE_CLEAR_SENTINEL"}});
        let closed = decode_projection(&row).unwrap();
        assert_eq!(closed["encrypted_content"],"ciphertext");
        assert_eq!(closed["message_id"],"local-row");
        assert!(!closed.to_string().contains("PRIVATE_CLEAR_SENTINEL"));
        assert_eq!(closed["large_payload"].as_object().unwrap().len(),3);
    }
}

#[cfg(test)]
mod opaque_message_identity_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
    #[test]
    fn local_physical_cursor_and_logical_alias_remain_distinct() {
        let chat = "22222222-2222-4222-8222-222222222222";
        let logical = "2222222222-10000000-0000-4000-8000-000000000001";
        let row = json!({"id":"database-row-1","message_id":"physical-row-1","client_message_id":logical,
            "chat_id":chat,"created_at":1,"role":"user","encrypted_content":"ciphertext"});
        let rows = message_rows(&[row], chat).unwrap();
        assert_eq!(position(&rows[0]).unwrap(), (1, "physical-row-1"));
        assert_eq!(rows[0]["client_message_id"], logical);
        assert_eq!(decode_projection(&rows[0]).unwrap()["message_id"], "physical-row-1");
        for value in [logical, "legacy_msg_42", "MESSAGE_42-A"] {
            assert_eq!(storage_id(value).is_ok(), super::super::super::message_window::valid_message_id(value));
        }
    }
}


#[cfg(test)]
mod unicode_physical_order_tests {
    use super::*;
    #[test]
    fn idb_utf16_physical_keys_and_canonical_utf8_have_distinct_order() {
        let supplementary="\u{10000}";let bmp="\u{e000}";
        assert!(supplementary>bmp);assert!(idb_key_cmp(supplementary,bmp).is_lt());
        let row=|id:&str|json!({"message_id":id,"chat_id":"chat","created_at":1,"role":"user"});
        assert!(message_rows(&[row(supplementary),row(bmp)],"chat").is_ok());
        assert!(message_rows(&[row(bmp),row(supplementary)],"chat").is_err());
        assert!(crate::client::sync_windows::message_rows(&[row(bmp),row(supplementary)],"chat",256*1024).is_ok());
        assert!(crate::client::sync_windows::message_rows(&[row(supplementary),row(bmp)],"chat",256*1024).is_err());
        let cp=|id:&str,n|json!({"id":id,"chat_id":"chat","created_at":1,"compressed_up_to_timestamp":n,"compressed_message_count":1});
        assert_eq!(compression_timestamp(&[cp(bmp,2),cp(supplementary,1)],"chat").unwrap(),Some(1));
        assert!(storage_id("message \n雪😀").is_ok());assert!(storage_id(&"x".repeat(4096)).is_ok());assert!(storage_id("").is_err());
    }
}
