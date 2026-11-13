//! Which streamed embeds a turn may persist itself (shared core, send path).
//!
//! A `send_embed_data` frame with `status: "processing"` is a render
//! placeholder; web keeps it in memory only (`chatSyncServiceHandlersAI.ts`)
//! and so must the core. Persisting it would seal the placeholder as the
//! immutable finished version 1, and the server's final sealed recovery output
//! for that version could then never be stored (every replay of the chat fails
//! as a content mismatch). Spec: `completion-recovery`, `client-core.cache`.
use serde_json::Value;
use std::collections::{BTreeMap, HashSet};

/// Remove streamed rows that are still `processing`, and every descendant of a
/// removed row (its key comes from that parent). The sealed recovery outputs
/// of those embeds carry their final content and are replayed instead. A child
/// whose parent never streamed in this turn is kept, so persistence still
/// reports its missing parent key as before.
pub(in crate::client) fn drop_unfinished(rows: &mut BTreeMap<String, Value>) {
    let mut removed: HashSet<String> = rows
        .iter()
        .filter(|(_, row)| row.get("status").and_then(Value::as_str) == Some("processing"))
        .map(|(id, _)| id.clone())
        .collect();
    // Chains are short (persistence caps a turn at 100 rows); repeat until no
    // row hangs below a removed parent.
    loop {
        let before = removed.len();
        for (id, row) in rows.iter() {
            if row
                .get("parent_embed_id")
                .and_then(Value::as_str)
                .is_some_and(|parent| removed.contains(parent))
            {
                removed.insert(id.clone());
            }
        }
        if removed.len() == before {
            break;
        }
    }
    rows.retain(|id, _| !removed.contains(id));
}

#[cfg(test)]
#[path = "send_unfinished_embeds_tests.rs"]
mod tests;
