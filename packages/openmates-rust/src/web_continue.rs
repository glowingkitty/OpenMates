//! Continue-carousel priority decisions of the web `chatState` unit op `continueDecide`.
//!
//! spec: specifications/features/continue-carousel#continue-carousel.chat.reminder-gated
//!
//! Twin of the half of `frontend/packages/ui/src/services/continueCarouselService.ts`
//! that the welcome screen's async `loadPriorityContinueItems` calls:
//! `getReminderByTargetChatId` (best reminder per target chat, first-seen order,
//! the earlier reminder wins a tie) and `sortContinuePriorityItems` (a stable
//! sort by reason rank, then distance to now). Classification, comparison and
//! the `Reminder in 5m` label reuse the shared overview rules
//! (`client::overview::reminder_priority`, `compare_priority`,
//! `cards::relative_label`), so no second copy of them exists.
//!
//! Not here, and staying TypeScript: saved-item classification
//! (`getSavedFlagContinueCandidates`; it parses item times with JavaScript
//! `Date`, whose non-ISO formats and per-instant local offsets the shared
//! fixed-offset ISO parser does not reproduce) and the CLI home, whose callers
//! are synchronous. Inputs are reminder trigger times, statuses and target chat
//! IDs; no keys and no chat content enter this module.

use crate::client::overview::cards::relative_label;
use crate::client::overview::{DuePriority, DueReason, ReminderInput, compare_priority, reminder_priority};
use crate::web_guest::is_js_space;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::cmp::Ordering;
use std::collections::HashMap;

/// One reminder reduced to the fields the chat index reads.
#[derive(Deserialize)]
struct ReminderRow {
    /// Unix seconds (an integer on the reminder listing wire); null classifies nothing.
    #[serde(default)]
    trigger_at: Value,
    #[serde(default)]
    status: Value,
    #[serde(default)]
    target_chat_id: Value,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ReminderByChatInput {
    reminders: Vec<ReminderRow>,
    now_ms: i64,
}

/// A carousel priority as the page holds it (`ContinuePriority` without its label).
#[derive(Clone, Copy, Deserialize)]
struct PriorityKey {
    reason: DueReason,
    timestamp: i64,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct SortInput {
    priorities: Vec<PriorityKey>,
    now_ms: i64,
}

/// `ContinuePriority` (`reason`, `label`, `timestamp`).
#[derive(Serialize)]
struct PriorityOut {
    reason: DueReason,
    label: String,
    timestamp: i64,
}

/// One `getReminderByTargetChatId` map entry; `reminderIndex` points into the input.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct ChatReminderOut {
    chat_id: String,
    reminder_index: usize,
    priority: PriorityOut,
}

/// `asString`: a string trimmed like JavaScript `trim`, anything else empty
/// (an absent target is not an error in TS either: the reminder is skipped).
fn js_trimmed(value: &Value) -> &str {
    value.as_str().map(|text| text.trim_matches(is_js_space)).unwrap_or_default()
}

/// `buildReminderPriority` on the wire row.
fn row_priority(row: &ReminderRow, now_ms: i64) -> Result<Option<DuePriority>, String> {
    let trigger_at = match &row.trigger_at {
        Value::Null => return Ok(None),
        value => value.as_i64().ok_or("trigger_at_not_integer")?,
    };
    let input = ReminderInput {
        trigger_at,
        // Only `status === 'pending'` is read; a missing or non-string status is "not pending" in TS too.
        status: row.status.as_str().unwrap_or_default().to_owned(),
        ..ReminderInput::default()
    };
    Ok(reminder_priority(&input, now_ms))
}

fn reminder_by_chat(input: &ReminderByChatInput) -> Result<Vec<ChatReminderOut>, String> {
    let mut order: Vec<(String, usize, DuePriority)> = vec![];
    let mut position: HashMap<String, usize> = HashMap::new();
    for (index, row) in input.reminders.iter().enumerate() {
        let chat_id = js_trimmed(&row.target_chat_id);
        if chat_id.is_empty() {
            continue;
        }
        let Some(priority) = row_priority(row, input.now_ms)? else { continue };
        match position.get(chat_id) {
            // Map.set on an existing key keeps its first-insertion position.
            Some(&slot) => {
                if compare_priority(&priority, &order[slot].2, input.now_ms) == Ordering::Less {
                    order[slot] = (chat_id.to_owned(), index, priority);
                }
            }
            None => {
                position.insert(chat_id.to_owned(), order.len());
                order.push((chat_id.to_owned(), index, priority));
            }
        }
    }
    Ok(order
        .into_iter()
        .map(|(chat_id, reminder_index, priority)| ChatReminderOut {
            chat_id,
            reminder_index,
            priority: PriorityOut {
                reason: priority.reason,
                label: relative_label("Reminder", priority.timestamp_ms, input.now_ms),
                timestamp: priority.timestamp_ms,
            },
        })
        .collect())
}

/// `sortContinuePriorityItems` as an index permutation (stable, like `Array.prototype.sort`).
fn sort_order(input: &SortInput) -> Vec<usize> {
    let keys: Vec<DuePriority> = input
        .priorities
        .iter()
        .map(|key| DuePriority { reason: key.reason, timestamp_ms: key.timestamp })
        .collect();
    let mut order: Vec<usize> = (0..keys.len()).collect();
    order.sort_by(|&a, &b| compare_priority(&keys[a], &keys[b], input.now_ms));
    order
}

/// Runs one named continue-carousel decision on a JSON document.
///
/// Ops: `reminderByChat` (`{reminders, nowMs}` → `{entries}`) and
/// `sortPriorities` (`{priorities, nowMs}` → `{order}`).
///
/// # Errors
/// An unknown op, a malformed document or a non-integer `trigger_at` answers its
/// error text; the Worker adapter turns every error into the `protocol` code.
pub fn run_json(op: &str, input_json: &str) -> Result<String, String> {
    let answer = match op {
        "reminderByChat" => {
            let input: ReminderByChatInput = serde_json::from_str(input_json).map_err(|e| e.to_string())?;
            serde_json::json!({ "entries": reminder_by_chat(&input)? })
        }
        "sortPriorities" => {
            let input: SortInput = serde_json::from_str(input_json).map_err(|e| e.to_string())?;
            serde_json::json!({ "order": sort_order(&input) })
        }
        other => return Err(format!("unknown_op:{other}")),
    };
    Ok(answer.to_string())
}
