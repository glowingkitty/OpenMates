//! Shared sub-chat page validation decisions.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `loadSharedSubChatPage` in `sharedChatDetailsService.ts`: the cursor
//! input check, the bounded-metadata check, the oversized-row identity check and
//! the final contiguous-window check. The page does the fetches; messages equal
//! the TS `Error` texts.

use super::details::{cursor_not_before, strict_eq, truthy};
use super::{Decision, array, field, refusal, safe_int, str_field, utf16_cmp};
use serde_json::{Value, json};
use std::cmp::Ordering;

const MAX_PAGE_BYTES: i64 = 131_072;
const MAX_PAGE_ITEMS: usize = 20;

fn positive_int(value: Option<&Value>) -> Option<i64> {
    value.and_then(safe_int).filter(|n| *n > 0)
}

/// `validSharedSubChat`: a plain object with the parent id, sub-chat flag and a positive created_at.
fn valid_row(row: &Value, parent_id: &str) -> bool {
    let Some(object) = row.as_object() else { return false };
    matches!(object.get("id"), Some(Value::String(id)) if !id.is_empty())
        && object.get("parent_id") == Some(&json!(parent_id))
        && object.get("is_sub_chat") == Some(&json!(true))
        && positive_int(object.get("created_at")).is_some()
}

fn cursor_input_check(input: &Value) -> Decision {
    let chat_id = str_field(input, "chat_id")?;
    let bad_before = input.get("before").filter(|b| truthy(Some(b))).is_some_and(|before| {
        positive_int(before.get("timestamp")).is_none() || !truthy(before.get("id"))
    });
    Ok(if chat_id.is_empty() || bad_before {
        refusal("Invalid shared subchat cursor.")
    } else {
        json!({ "ok": true })
    })
}

/// Cursor of a page that carries a `start_cursor` (`null` when it has none).
fn start_cursor(page: &Value) -> Result<Value, Value> {
    let Some(start) = page.get("start_cursor").filter(|s| !s.is_null()) else {
        return Ok(Value::Null);
    };
    let id_ok = matches!(start.get("id"), Some(Value::String(id)) if !id.is_empty());
    if positive_int(start.get("timestamp")).is_none() || !id_ok {
        return Err(refusal("Shared subchat page cursor was invalid."));
    }
    Ok(json!({ "timestamp": start["timestamp"], "id": start["id"] }))
}

/// Bounded-metadata check of a fetched page, then which branch loads the rows.
fn page_check(input: &Value) -> Decision {
    let chat_id = str_field(input, "chat_id")?;
    let page = field(input, "page")?;
    let rows = page.get("rows").and_then(Value::as_array);
    let bytes_ok = page.get("payload_bytes").and_then(safe_int).is_some_and(|b| (0..=MAX_PAGE_BYTES).contains(&b));
    let bounded = page.get("items_is_array") == Some(&json!(true))
        && rows.is_some_and(|r| r.len() <= MAX_PAGE_ITEMS && r.iter().all(|row| valid_row(row, chat_id)))
        && matches!(page.get("has_more_before"), Some(Value::Bool(_)))
        && bytes_ok;
    if !bounded {
        return Ok(refusal("Shared subchat page had invalid bounded metadata."));
    }
    let row_count = rows.map_or(0, Vec::len);
    if let Some(oversized) = page.get("oversized_id").filter(|o| !o.is_null()) {
        let valid = row_count == 0
            && matches!(oversized, Value::String(id) if !id.is_empty())
            && page.get("has_more_before") == Some(&json!(true));
        return Ok(if valid {
            json!({ "mode": "fetch_oversized", "id": oversized })
        } else {
            refusal("Shared subchat oversized cursor was invalid.")
        });
    }
    Ok(match start_cursor(page) {
        Ok(cursor) => json!({ "mode": "items", "cursor": cursor }),
        Err(refused) => refused,
    })
}

/// Identity check of the selected oversized row; its position becomes the page cursor.
fn oversized_check(input: &Value) -> Decision {
    let chat_id = str_field(input, "chat_id")?;
    let item = field(input, "item")?;
    let id = field(input, "oversized_id")?;
    if !valid_row(item, chat_id) || item.get("id") != Some(id) {
        return Ok(refusal("Shared oversized subchat identity did not match its cursor."));
    }
    Ok(json!({ "cursor": { "timestamp": item["created_at"], "id": item["id"] } }))
}

fn out_of_order(rows: &[Value]) -> bool {
    rows.windows(2).any(|pair| {
        let (prev, row) = (&pair[0], &pair[1]);
        let created = row["created_at"].as_f64().partial_cmp(&prev["created_at"].as_f64());
        created == Some(Ordering::Less)
            || (created == Some(Ordering::Equal)
                && utf16_cmp(row["id"].as_str().unwrap_or_default(), prev["id"].as_str().unwrap_or_default()) != Ordering::Greater)
    })
}

/// Contiguity, next-cursor and advance checks once the final rows are known.
fn final_check(input: &Value) -> Decision {
    let rows = array(field(input, "rows")?, "rows")?;
    let cursor = input.get("cursor").filter(|c| !c.is_null());
    if let Some(first) = rows.first() {
        let anchored = cursor.is_some_and(|c| {
            strict_eq(c.get("timestamp"), first.get("created_at")) && strict_eq(c.get("id"), first.get("id"))
        });
        if !anchored || out_of_order(rows) {
            return Ok(refusal("Shared subchat page was not a contiguous chronological window."));
        }
    }
    if input.get("has_more_before") == Some(&json!(true)) && cursor.is_none() {
        return Ok(refusal("Shared subchat page did not provide its next cursor."));
    }
    let before = input.get("before").filter(|b| truthy(Some(b)));
    if let (Some(before), Some(cursor)) = (before, cursor) {
        if cursor_not_before(cursor, before) {
            return Ok(refusal("Shared subchat cursor did not advance."));
        }
    }
    Ok(json!({ "ok": true }))
}

/// Dispatches the `subChat*` ops.
pub(super) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "subChatCursorCheck" => cursor_input_check(input),
        "subChatPageCheck" => page_check(input),
        "subChatOversizedCheck" => oversized_check(input),
        "subChatFinalCheck" => final_check(input),
        _ => Err(format!("unknown_op:{op}")),
    }
}
