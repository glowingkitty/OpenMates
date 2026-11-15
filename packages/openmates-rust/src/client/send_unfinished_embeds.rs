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
    let removed: HashSet<String> = rows
        .iter()
        .filter(|(_, row)| row.get("status").and_then(Value::as_str) == Some("processing"))
        .map(|(id, _)| id.clone())
        .collect();
    drop_with_descendants(rows, removed);
}

/// Remove rows of another turn of this chat, and their descendants: a row
/// that names no task and belongs to a message other than `message` (the
/// turn's assistant message). The server re-delivers such rows to every new
/// socket of the owner until some client stores them, e.g. the outputs a
/// turn produced after its client went offline. They are that turn's output,
/// recovered through its own replay, so this turn never persists them under
/// its receipt. A row naming a task is left in place: persistence still
/// refuses one that names another task.
pub(in crate::client) fn drop_other_turns(rows: &mut BTreeMap<String, Value>, message: &str) {
    let text = |row: &Value, key: &str| {
        row.get(key)
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned()
    };
    let removed: HashSet<String> = rows
        .iter()
        .filter(|(_, row)| {
            let owner = text(row, "message_id");
            text(row, "task_id").is_empty() && !owner.is_empty() && owner != message
        })
        .map(|(id, _)| id.clone())
        .collect();
    drop_with_descendants(rows, removed);
}

/// Remove `removed` and every row below one of them (a child is keyed by its
/// parent, so it cannot be persisted without it).
fn drop_with_descendants(rows: &mut BTreeMap<String, Value>, mut removed: HashSet<String>) {
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
