//! Cache-then-delta record for the selected rich chat read (`chats show`).
//!
//! Ciphertext only: the validated raw message rows, their boundary cursors, the
//! server `messages_v` they were read at and the embed inventory derived from
//! the first embeds page. A cached read still sends one concurrent round (the
//! metadata batch, a tail delta after the last cached message and the first
//! embeds page) and decodes through the same code as a fresh read; any
//! inconsistency (version, gap, validation, key, bounds) is a cache miss and
//! takes the unchanged fresh path. The record grants no freshness or authority.
use super::*;
use serde::{Deserialize, Serialize};

const MAX_RECORD_BYTES: usize = 4 * 1024 * 1024;
const MAX_ROWS: usize = 2000;
pub(super) const TAIL_LIMIT: usize = 100;
pub const SNAPSHOT_FIELD: &str = "chat_details_v1";

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Tail {
    pub created_at: i64,
    pub message_id: String,
}
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ChatDetailsCache {
    pub version: u8,
    /// `respect_compression_boundary` of the read that produced the rows.
    pub bounded: bool,
    pub messages_v: u64,
    pub has_more_before: bool,
    pub rows: Vec<Value>,
    pub tail: Tail,
    /// Digest of the first embeds page this inventory was derived from.
    pub embeds_sig: String,
    pub embed_ids: BTreeMap<String, Vec<String>>,
}
impl ChatDetailsCache {
    pub(super) fn bounded_size(&self) -> Option<usize> {
        let rows = self.rows.iter().try_fold(0usize, |total, row| {
            monitor::cached_view::bounded_bytes(row, 256 * 1024).and_then(|n| total.checked_add(n))
        })?;
        let embeds = self.embed_ids.iter().map(|(k, v)| k.len() + v.iter().map(String::len).sum::<usize>()).sum::<usize>();
        rows.checked_add(embeds).filter(|n| *n <= MAX_RECORD_BYTES)
    }
    fn valid(&self) -> bool {
        self.version == 1
            && !self.rows.is_empty()
            && self.rows.len() <= MAX_ROWS
            && self.bounded_size().is_some()
            && !self.tail.message_id.is_empty()
    }
}
/// Digest of exactly what decides whether the embed inventory changed.
pub(super) fn embeds_signature(page: &Value) -> Option<String> {
    let embeds = page.get("embeds")?;
    let more = page.get("has_more_before")?;
    Some(sha256(&serde_json::to_string(&(embeds, more)).ok()?))
}
pub(super) fn restore(value: Option<&Value>) -> BTreeMap<String, ChatDetailsCache> {
    let Some(object) = value.and_then(Value::as_object) else {
        return BTreeMap::new();
    };
    object
        .iter()
        .filter(|(id, _)| uuid::Uuid::parse_str(id).is_ok_and(|u| u.hyphenated().to_string() == **id))
        .filter_map(|(id, raw)| {
            serde_json::from_value::<ChatDetailsCache>(raw.clone())
                .ok()
                .filter(ChatDetailsCache::valid)
                .map(|record| (id.clone(), record))
        })
        .collect()
}
impl Client {
    pub(super) fn chat_details_tail_path(&self, id: &str, tail: &Tail, bounded: bool) -> Result<String> {
        let mut url = self.url(&format!("/v1/chats/{}/messages/window", segment(id)))?;
        url.query_pairs_mut()
            .append_pair("direction", "after")
            .append_pair("limit", &TAIL_LIMIT.to_string())
            .append_pair("respect_compression_boundary", if bounded { "true" } else { "false" })
            .append_pair("after_timestamp", &tail.created_at.to_string())
            .append_pair("after_message_id", &tail.message_id);
        self.scoped(&format!("{}?{}", self.request_route_path(&url)?, url.query().unwrap_or("")))
    }
    pub(super) fn cached_chat_details(&self, id: &str, bounded: bool) -> Option<ChatDetailsCache> {
        self.chat_details_cache
            .get(id)
            .filter(|record| record.bounded == bounded && self.task_watch_authority.cached_chat_allowed(id))
            .cloned()
    }
    pub(super) fn store_chat_details_cache(&mut self, id: &str, record: Option<ChatDetailsCache>) {
        match record.filter(ChatDetailsCache::valid) {
            Some(record) => {
                self.chat_details_cache.insert(id.to_owned(), record);
            }
            None => {
                self.chat_details_cache.remove(id);
            }
        }
    }
    pub(super) fn chat_details_snapshot(&self) -> Option<Value> {
        let rows: BTreeMap<_, _> = self
            .chat_details_cache
            .iter()
            .filter(|(id, _)| self.task_watch_authority.cached_chat_allowed(id) && self.chats.contains_key(*id))
            .collect();
        (!rows.is_empty()).then(|| json!(rows))
    }
}

#[cfg(test)]
#[path = "chat_details_cache_tests.rs"]
mod tests;
