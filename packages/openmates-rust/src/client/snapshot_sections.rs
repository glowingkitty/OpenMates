//! Sectioned layout of the native ciphertext cache snapshot.
//!
//! A full `Client::ciphertext_snapshot()` splits into:
//! - an index section: exactly the Chat-list inputs (rows, arrival order, key
//!   wrappers, Team wrapped key), the list-freshness receipt and tombstones;
//! - one section per Chat: its history, sync window, selected first page and
//!   the embeds/embed keys whose `hashed_chat_id` is that Chat's SHA-256;
//! - one shared section: everything else (unbound embeds/keys, saved-embed
//!   order and any future top-level field).
//!
//! `assemble` is the inverse up to `embed_keys` order (grouped by section),
//! which no reader treats as meaningful. Splitting is pure data handling: it
//! decrypts nothing and grants no freshness, authorization or durability.
//! Adapters own encryption, owner/Team scoping and atomic publication.
use super::{chat_arrival_order, chat_list_freshness, chat_tombstones, selected_first_page, sync_windows};
use crate::error::{Error, Result};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};

/// Top-level snapshot fields that form the Chat-list index section.
pub fn index_fields() -> [&'static str; 6] {
    [
        "chats",
        "wrappers",
        "team_wrapped_key",
        chat_arrival_order::SNAPSHOT_FIELD,
        chat_list_freshness::SNAPSHOT_FIELD,
        chat_tombstones::SNAPSHOT_FIELD,
    ]
}
/// Top-level snapshot field carrying the protected list-freshness receipt.
pub const CHAT_LIST_FRESHNESS_FIELD: &str = chat_list_freshness::SNAPSHOT_FIELD;
/// Per-Chat maps keyed by Chat ID; their value moves into that Chat's section.
fn per_chat_maps() -> [&'static str; 3] {
    ["history", sync_windows::SNAPSHOT_FIELD, selected_first_page::SNAPSHOT_FIELD]
}

#[derive(Debug, Default, Clone, PartialEq)]
pub struct SnapshotSections {
    pub index: Map<String, Value>,
    pub shared: Map<String, Value>,
    /// Only Chats with any cached content; an absent entry means no content.
    pub chats: BTreeMap<String, Map<String, Value>>,
}

fn hex_sha256(value: &str) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(value.as_bytes()).iter().map(|byte| format!("{byte:02x}")).collect()
}

/// Consume a snapshot into sections without cloning its content.
pub fn split(snapshot: Value) -> Result<SnapshotSections> {
    let Value::Object(mut root) = snapshot else {
        return Err(Error::Protocol);
    };
    let mut sections = SnapshotSections::default();
    for field in index_fields() {
        if let Some(value) = root.remove(field) {
            sections.index.insert(field.to_owned(), value);
        }
    }
    for field in per_chat_maps() {
        match root.remove(field) {
            None | Some(Value::Null) => {}
            Some(Value::Object(rows)) => {
                for (chat, value) in rows {
                    sections.chats.entry(chat).or_default().insert(field.to_owned(), value);
                }
            }
            Some(_) => return Err(Error::Protocol),
        }
    }
    // Embed rows/keys bind to a Chat only through hashed_chat_id. Resolve it
    // against every Chat this snapshot knows; anything else stays shared.
    let mut known: BTreeSet<String> = sections.chats.keys().cloned().collect();
    if let Some(Value::Object(rows)) = sections.index.get("chats") {
        known.extend(rows.keys().cloned());
    }
    let by_hash: BTreeMap<String, String> =
        known.into_iter().map(|chat| (hex_sha256(&chat), chat)).collect();
    let owner_of = |row: &Value| {
        row.get("hashed_chat_id")
            .and_then(Value::as_str)
            .and_then(|hash| by_hash.get(hash))
            .cloned()
    };
    match root.remove("embeds") {
        None | Some(Value::Null) => {}
        Some(Value::Object(rows)) => {
            let mut shared = Map::new();
            for (id, row) in rows {
                match owner_of(&row) {
                    Some(chat) => {
                        let section = sections.chats.entry(chat).or_default();
                        let embeds = section
                            .entry("embeds")
                            .or_insert_with(|| Value::Object(Map::new()));
                        embeds.as_object_mut().ok_or(Error::Protocol)?.insert(id, row);
                    }
                    None => {
                        shared.insert(id, row);
                    }
                }
            }
            sections.shared.insert("embeds".into(), Value::Object(shared));
        }
        Some(_) => return Err(Error::Protocol),
    }
    match root.remove("embed_keys") {
        None | Some(Value::Null) => {}
        Some(Value::Array(rows)) => {
            let mut shared = Vec::new();
            for row in rows {
                match owner_of(&row) {
                    Some(chat) => {
                        let section = sections.chats.entry(chat).or_default();
                        let keys = section
                            .entry("embed_keys")
                            .or_insert_with(|| Value::Array(Vec::new()));
                        keys.as_array_mut().ok_or(Error::Protocol)?.push(row);
                    }
                    None => shared.push(row),
                }
            }
            sections.shared.insert("embed_keys".into(), Value::Array(shared));
        }
        Some(_) => return Err(Error::Protocol),
    }
    // Any remaining (including future) field is shared, never silently lost.
    sections.shared.extend(root);
    Ok(sections)
}

/// Reassemble an index, an optional shared section and per-Chat sections into
/// one snapshot accepted by `Client::restore_ciphertext_snapshot`.
pub fn assemble(
    index: Map<String, Value>,
    shared: Option<Map<String, Value>>,
    chats: impl IntoIterator<Item = (String, Map<String, Value>)>,
) -> Result<Value> {
    let mut root = index;
    let mut embeds = Map::new();
    let mut embed_keys = Vec::new();
    let mut maps: BTreeMap<&'static str, Map<String, Value>> = BTreeMap::new();
    if let Some(shared) = shared {
        for (field, value) in shared {
            match (field.as_str(), value) {
                ("embeds", Value::Object(rows)) => embeds.extend(rows),
                ("embed_keys", Value::Array(rows)) => embed_keys.extend(rows),
                ("embeds" | "embed_keys", _) => return Err(Error::Protocol),
                (_, value) => {
                    root.insert(field, value);
                }
            }
        }
    }
    for (chat, section) in chats {
        merge_chat_section(&chat, section, &mut maps, &mut embeds, &mut embed_keys)?;
    }
    for (field, rows) in maps {
        root.insert(field.to_owned(), Value::Object(rows));
    }
    root.insert("embeds".into(), Value::Object(embeds));
    root.insert("embed_keys".into(), Value::Array(embed_keys));
    root.entry("history").or_insert_with(|| Value::Object(Map::new()));
    root.entry("wrappers").or_insert_with(|| Value::Array(Vec::new()));
    root.entry("chats").or_insert_with(|| Value::Object(Map::new()));
    Ok(Value::Object(root))
}

fn merge_chat_section(
    chat: &str,
    section: Map<String, Value>,
    maps: &mut BTreeMap<&'static str, Map<String, Value>>,
    embeds: &mut Map<String, Value>,
    embed_keys: &mut Vec<Value>,
) -> Result<()> {
    for (field, value) in section {
        match field.as_str() {
            "embeds" => match value {
                Value::Object(rows) => embeds.extend(rows),
                _ => return Err(Error::Protocol),
            },
            "embed_keys" => match value {
                Value::Array(rows) => embed_keys.extend(rows),
                _ => return Err(Error::Protocol),
            },
            other => {
                let name = per_chat_maps()
                    .into_iter()
                    .find(|name| *name == other)
                    .ok_or(Error::Protocol)?;
                maps.entry(name).or_default().insert(chat.to_owned(), value);
            }
        }
    }
    Ok(())
}

/// A one-Chat partial snapshot (only content fields) for restore/merge.
pub(super) fn chat_partial_snapshot(chat: &str, section: &Value) -> Result<Value> {
    let section = section.as_object().ok_or(Error::Protocol)?.clone();
    let mut maps = BTreeMap::new();
    let mut embeds = Map::new();
    let mut embed_keys = Vec::new();
    merge_chat_section(chat, section, &mut maps, &mut embeds, &mut embed_keys)?;
    let mut root = Map::new();
    for (field, rows) in maps {
        root.insert(field.to_owned(), Value::Object(rows));
    }
    root.insert("embeds".into(), Value::Object(embeds));
    root.insert("embed_keys".into(), Value::Array(embed_keys));
    Ok(Value::Object(root))
}

#[cfg(test)]
#[path = "snapshot_sections_tests.rs"]
mod tests;
