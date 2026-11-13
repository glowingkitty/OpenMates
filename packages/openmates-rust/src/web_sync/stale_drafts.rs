//! Stale local draft reconciliation on reconnect (shared core, served to the web
//! shell by the `sync` Worker unit). A device closed while drafts were deleted
//! elsewhere never hears about it once the server tombstones expire, so Phase 2
//! carries a bounded probe of idle local drafts and the server answers which of
//! them it recorded as deleted (positive evidence at a version >= the probed
//! one; a merely missing server draft is never reported). This module decides
//! which rows are probed and what the answer may change locally. Spec: `architecture.drafts`
//! (drafts.sync.version-authoritative, drafts.draft-only.lifecycle).
use serde_json::{json, Value};

use super::{field, num, number, parse, truthy, PROTOCOL};

/// Most ids one reconnect probes; the server enforces the same cap.
pub const PROBE_LIMIT: usize = 200;
/// A draft saved less than this many seconds ago may still be on its way to the
/// server (or the server may not have persisted it yet), so it is never probed.
pub const MIN_IDLE_SECONDS: f64 = 600.0;

/// Fields that make a chat more than a draft-only shell (`isDraftOnlyChatSurface`).
const GENERATED_METADATA: [&str; 7] = [
    "title",
    "encrypted_title",
    "chat_summary",
    "encrypted_chat_summary",
    "icon",
    "encrypted_icon",
    "encrypted_category",
];

fn canonical_uuid(id: &str) -> bool {
    uuid::Uuid::parse_str(id).is_ok_and(|u| u.hyphenated().to_string() == id)
}

fn has_draft_cipher(row: &Value) -> bool {
    field(row, "encrypted_draft_md")
        .and_then(Value::as_str)
        .is_some_and(|md| !md.is_empty() && md != "null")
}

/// Newest finite local timestamp (seconds) of the row; `None` keeps the row.
fn last_touched(row: &Value) -> Option<f64> {
    ["updated_at", "last_edited_overall_timestamp", "created_at"]
        .iter()
        .map(|key| num(field(row, key)))
        .filter(|t| t.is_finite())
        .reduce(f64::max)
}

/// `isDraftOnlyChatSurface` without the live-editor flag.
fn draft_only(row: &Value) -> bool {
    let zero = |key: &str| {
        let value = num(field(row, key));
        value.is_nan() || value == 0.0
    };
    zero("messages_v")
        && zero("title_v")
        && !GENERATED_METADATA.iter().any(|key| truthy(field(row, key)))
        && !truthy(field(row, "category"))
        && !truthy(field(row, "ideabucket_triggered_at"))
}

/// Whether one local row may be probed. Invariant: unsent local work is never
/// probed, because a brand-new local draft the server has not received yet
/// looks exactly like a deleted one. Kept: queued offline changes, Team rows and
/// Team pending intents, direct/anonymous/incognito/hidden chats, demo ids and
/// drafts touched within `MIN_IDLE_SECONDS`.
fn eligible(row: &Value, pending: &[&str], now: f64) -> Option<(String, f64, f64)> {
    let chat_id = field(row, "chat_id").and_then(Value::as_str)?;
    if !canonical_uuid(chat_id) || pending.contains(&chat_id) {
        return None;
    }
    let excluded = [
        "team_id",
        "team_draft_pending_sync",
        "team_chat_pending_commit",
        "is_incognito",
        "is_anonymous",
        "is_hidden_candidate",
    ];
    if excluded.iter().any(|key| truthy(field(row, key)))
        || field(row, "chat_visibility").and_then(Value::as_str) == Some("direct")
    {
        return None;
    }
    let draft_v = num(field(row, "draft_v"));
    if !(draft_v.is_finite() && draft_v > 0.0) || !has_draft_cipher(row) {
        return None;
    }
    let touched = last_touched(row)?;
    // Future timestamps (clock skew, millisecond values) count as fresh.
    if now - touched < MIN_IDLE_SECONDS {
        return None;
    }
    Some((chat_id.to_string(), draft_v, touched))
}

fn string_list<'a>(input: &'a Value, key: &str) -> Result<Vec<&'a str>, String> {
    match field(input, key) {
        Some(Value::Array(items)) => items
            .iter()
            .map(|item| item.as_str().ok_or_else(|| PROTOCOL.to_string()))
            .collect(),
        _ => Err(PROTOCOL.to_string()),
    }
}

/// Builds the Phase 2 probe for `{now, rows, pendingChatIds}`: `rows` are the
/// local Personal chat rows that carry a draft, `pendingChatIds` every chat id
/// with a queued offline change or pending deletion. Returns
/// `{wire: [{chat_id, draft_v}], probe: [{chatId, draftV, draftOnly}]}`; `wire`
/// is sent as `stale_draft_probe`, `probe` is kept for [`plan_json`]. Oldest
/// drafts first, at most [`PROBE_LIMIT`].
///
/// # Errors
/// `protocol` when `now`, `rows` or `pendingChatIds` are missing or mistyped.
pub fn probe_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let now = field(&input, "now")
        .and_then(Value::as_f64)
        .filter(|n| n.is_finite())
        .ok_or_else(|| PROTOCOL.to_string())?;
    let rows = field(&input, "rows")
        .and_then(Value::as_array)
        .ok_or_else(|| PROTOCOL.to_string())?;
    let pending = string_list(&input, "pendingChatIds")?;
    let mut picked: Vec<(String, f64, f64, bool)> = Vec::new();
    for row in rows {
        let Some((chat_id, draft_v, touched)) = eligible(row, &pending, now) else {
            continue;
        };
        if picked.iter().any(|(id, ..)| *id == chat_id) {
            continue;
        }
        picked.push((chat_id, draft_v, touched, draft_only(row)));
    }
    picked.sort_by(|a, b| a.2.total_cmp(&b.2).then_with(|| a.0.cmp(&b.0)));
    picked.truncate(PROBE_LIMIT);
    let wire: Vec<Value> = picked
        .iter()
        .map(|(id, v, ..)| json!({"chat_id": id, "draft_v": number(*v)}))
        .collect();
    let probe: Vec<Value> = picked
        .iter()
        .map(|(id, v, _, only)| json!({"chatId": id, "draftV": number(*v), "draftOnly": only}))
        .collect();
    Ok(json!({"wire": wire, "probe": probe}).to_string())
}

/// Local actions for `{probe, result}` where `probe` is the [`probe_json`] list
/// that was sent and `result` the server's `stale_draft_probe_result`
/// (`{absent_chat_ids, draft_absent_chat_ids}`, or null/absent when the server
/// could not answer). Returns `[{chatId, action, draftV}]`:
/// - `delete_draft_only`: a draft-only row whose draft the server recorded as
///   deleted and that has no chat row;
/// - `clear_draft`: a recorded-deleted draft on a chat that has (or may have)
///   content. A reported delete never removes a chat that has local content.
///
/// Ids the server names that were not probed are ignored. `draftV` is the probed
/// version: the shell must apply the action only while the stored draft is
/// still at that version (an edit since the probe wins).
///
/// # Errors
/// `protocol` when `probe` or a present `result` is mistyped.
pub fn plan_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let probe = field(&input, "probe")
        .and_then(Value::as_array)
        .ok_or_else(|| PROTOCOL.to_string())?;
    let result = match field(&input, "result") {
        None | Some(Value::Null) => return Ok("[]".to_string()),
        Some(result @ Value::Object(_)) => result,
        Some(_) => return Err(PROTOCOL.to_string()),
    };
    let absent = string_list(result, "absent_chat_ids")?;
    let draft_absent = string_list(result, "draft_absent_chat_ids")?;
    let mut plan = Vec::new();
    for entry in probe {
        let chat_id = field(entry, "chatId")
            .and_then(Value::as_str)
            .ok_or_else(|| PROTOCOL.to_string())?;
        let draft_v = field(entry, "draftV")
            .filter(|v| v.is_number())
            .ok_or_else(|| PROTOCOL.to_string())?;
        let only = field(entry, "draftOnly")
            .and_then(Value::as_bool)
            .ok_or_else(|| PROTOCOL.to_string())?;
        let action = if absent.contains(&chat_id) {
            if only {
                "delete_draft_only"
            } else {
                "clear_draft"
            }
        } else if draft_absent.contains(&chat_id) {
            "clear_draft"
        } else {
            continue;
        };
        plan.push(json!({"chatId": chat_id, "action": action, "draftV": draft_v}));
    }
    Ok(Value::Array(plan).to_string())
}

#[cfg(test)]
#[path = "stale_drafts_tests.rs"]
mod tests;
