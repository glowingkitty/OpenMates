//! Local tombstones for chats this client deleted.
//!
//! The server acknowledges `delete_chat` (and tombstones its cache) at once,
//! but durable removal runs in a background task, so an immediate phased sync
//! can still return the chat. Like the web/TS clients, hide a chat this client
//! deleted from the moment the server acknowledged the deletion. Tombstones are
//! display state only (never deletion authority) and expire after one day.
use super::*;
pub(super) const SNAPSHOT_FIELD: &str = "deleted_chat_tombstones_v1";
const TTL_SECONDS: u64 = 24 * 60 * 60;
const MAX_TOMBSTONES: usize = 1000;

fn now_seconds() -> u64 {
    crate::platform::unix_ms() / 1000
}

/// Restore unexpired, well-formed tombstones; anything else is dropped.
pub(super) fn restore(value: Option<&Value>) -> BTreeMap<String, u64> {
    let now = now_seconds();
    value
        .and_then(Value::as_object)
        .into_iter()
        .flatten()
        .filter_map(|(id, at)| Some((id.clone(), at.as_u64()?)))
        .filter(|(id, at)| !id.is_empty() && id.len() <= 128 && *at <= now && now - at < TTL_SECONDS)
        .take(MAX_TOMBSTONES)
        .collect()
}

impl Client {
    pub(super) fn record_deleted_chat(&mut self, id: &str) {
        let now = now_seconds();
        self.deleted_chats.retain(|_, at| now.saturating_sub(*at) < TTL_SECONDS);
        if self.deleted_chats.len() >= MAX_TOMBSTONES
            && let Some(oldest) = self.deleted_chats.iter().min_by_key(|(_, at)| **at).map(|(id, _)| id.clone())
        {
            self.deleted_chats.remove(&oldest);
        }
        self.deleted_chats.insert(id.to_owned(), now);
    }
    pub(super) fn is_deleted_chat(&self, id: &str) -> bool {
        self.deleted_chats.contains_key(id)
    }
    /// Drop locally deleted chats from a freshly synced inventory.
    pub(super) fn drop_deleted_chats(
        &self,
        chats: &mut BTreeMap<String, Value>,
        order: &mut Vec<String>,
    ) {
        if self.deleted_chats.is_empty() {
            return;
        }
        chats.retain(|id, _| !self.is_deleted_chat(id));
        order.retain(|id| !self.is_deleted_chat(id));
    }
    pub(super) fn deleted_chats_snapshot(&self) -> Option<Value> {
        (!self.deleted_chats.is_empty()).then(|| json!(self.deleted_chats))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn restore_keeps_only_fresh_well_formed_tombstones() {
        let now = now_seconds();
        let restored = restore(Some(&json!({
            "fresh": now - 10, "expired": now - TTL_SECONDS - 1, "future": now + 100, "bad": "x", "": now
        })));
        assert_eq!(restored.keys().collect::<Vec<_>>(), vec!["fresh"]);
        assert!(restore(None).is_empty());
    }
    // contract-test: supporting surface=sdks.rust assertions=chats.local-state.precedence
    #[test]
    fn a_synced_inventory_hides_a_chat_this_client_deleted() {
        let mut client = Client::new("https://api.example.org", None).unwrap();
        client.record_deleted_chat("gone");
        let mut chats: BTreeMap<String, Value> =
            [("gone".to_owned(), json!({})), ("kept".to_owned(), json!({}))].into();
        let mut order = vec!["gone".to_owned(), "kept".to_owned()];
        client.drop_deleted_chats(&mut chats, &mut order);
        assert_eq!(chats.keys().collect::<Vec<_>>(), vec!["kept"]);
        assert_eq!(order, vec!["kept"]);
        let snapshot = client.deleted_chats_snapshot().unwrap();
        assert!(restore(Some(&snapshot)).contains_key("gone"));
    }
}
