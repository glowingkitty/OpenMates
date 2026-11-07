//! Message-window cache, offline cache budget and quota-recovery decisions of
//! the IndexedDB layer (port of `db/cachePolicy.ts`): window request planning,
//! window page records and eviction plans, the budget trim gates and the
//! quota retry flow. Callers pass facts and act on the answers; no IO here.
//!
//! spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
use std::collections::HashSet;

use serde_json::{json, Map, Value};

use super::jsval::{
    as_f64, js_number_text, nullish, number, protocol, req_f64, req_list, req_object, req_str,
};
use crate::web_sync::{field, parse, truthy};

const DEFAULT_WINDOW_LIMIT: f64 = 30.0;
const MAX_WINDOW_LIMIT: f64 = 100.0;
const PAGE_CACHE_GENERATION: f64 = 1.0;
const DEFAULT_PAGE_CACHE_LIMIT: f64 = 12.0;
const MAX_BUDGET_EVICTIONS: f64 = 32.0;
const BUDGET_CHECK_INTERVAL_MS: f64 = 30_000.0;

/// `clampWindowLimit`: non-numeric, zero, negative and sub-1 limits use the default.
pub fn clamp_window_limit(limit: Option<&Value>) -> f64 {
    match as_f64(limit) {
        Some(l) if l.is_finite() && l != 0.0 && l >= 1.0 => l.floor().min(MAX_WINDOW_LIMIT),
        _ => DEFAULT_WINDOW_LIMIT,
    }
}

fn opt_num(value: Option<&Value>) -> Value {
    nullish(value).map_or(Value::Null, Clone::clone)
}

/// `planMessageWindow`: `{chatId, direction?, limit?, anchorMessageId?, anchorCreatedAt?,
/// beforeTimestamp?, afterTimestamp?, compressedUpToTimestamp?, anchorRecord?}` -> the plan.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn window_plan_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let chat_id = req_str(field(&input, "chatId"))?;
    let direction = match nullish(field(&input, "direction")) {
        None => "latest",
        Some(v) => v.as_str().ok_or_else(protocol)?,
    };
    let limit = clamp_window_limit(field(&input, "limit"));
    let needs_anchor_read = direction == "around" && truthy(field(&input, "anchorMessageId"));
    let anchor = nullish(field(&input, "anchorRecord"))
        .filter(|record| field(record, "chat_id").and_then(Value::as_str) == Some(chat_id));
    let compressed = field(&input, "compressedUpToTimestamp");
    let mut plan = json!({
        "limit": number(limit), "direction": direction, "needsAnchorRead": needs_anchor_read,
        "empty": false, "keepAnchor": false, "anchorCreatedAt": null, "beforeLimit": 0,
        "afterLimit": 0, "timestamp": null, "lowerBound": opt_num(compressed),
        "lowerOpen": truthy(compressed), "anchorFound": true,
    });
    let fields = plan.as_object_mut().ok_or_else(protocol)?;
    let empty = |fields: &mut Map<String, Value>| {
        fields.insert("empty".into(), json!(true));
        fields.insert("anchorFound".into(), json!(false));
    };
    match direction {
        "around" => {
            let created = anchor
                .and_then(|record| nullish(field(record, "created_at")))
                .or_else(|| nullish(field(&input, "anchorCreatedAt")));
            match created.filter(|v| truthy(Some(v))) {
                None => empty(fields),
                Some(created) => {
                    let before = ((limit - 1.0) / 2.0).floor();
                    fields.insert("keepAnchor".into(), json!(anchor.is_some()));
                    fields.insert("anchorCreatedAt".into(), created.clone());
                    fields.insert("beforeLimit".into(), number(before));
                    fields.insert("afterLimit".into(), number(limit - 1.0 - before));
                    let found = anchor.is_some() || truthy(field(&input, "anchorCreatedAt"));
                    fields.insert("anchorFound".into(), json!(found));
                }
            }
        }
        "before" | "after" => {
            let own = if direction == "before" { "beforeTimestamp" } else { "afterTimestamp" };
            let stamp = nullish(field(&input, own))
                .or_else(|| nullish(field(&input, "anchorCreatedAt")))
                .filter(|v| truthy(Some(v)));
            match stamp {
                None => empty(fields),
                Some(stamp) => {
                    fields.insert("timestamp".into(), stamp.clone());
                }
            }
        }
        _ => {}
    }
    Ok(plan.to_string())
}

fn cursor_value(message: Option<&Value>, key: &str) -> Value {
    message
        .and_then(|m| nullish(field(m, key)))
        .map_or(Value::Null, Clone::clone)
}

/// `windowResultMeta`: direction, `hasMore` flags and first/last message cursors -> result meta.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn window_result_meta_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let flag = |key: &str| field(&input, key).and_then(Value::as_bool).ok_or_else(protocol);
    let direction = req_str(field(&input, "direction"))?;
    let (has_more_before, has_more_after) = match direction {
        "around" => (flag("beforeHasMore")?, flag("afterHasMore")?),
        "before" => (flag("hasMore")?, true),
        "after" => (true, flag("hasMore")?),
        _ => (flag("hasMore")?, false),
    };
    let first = nullish(field(&input, "first"));
    let last = nullish(field(&input, "last"));
    Ok(json!({
        "hasMoreBefore": has_more_before, "hasMoreAfter": has_more_after,
        "startCursor": cursor_value(first, "created_at"),
        "startCursorMessageId": cursor_value(first, "message_id"),
        "endCursor": cursor_value(last, "created_at"),
        "endCursorMessageId": cursor_value(last, "message_id"),
        "anchorFound": flag("anchorFound")?,
    })
    .to_string())
}

fn id_part(value: Option<&Value>, fallback: &str) -> Result<String, String> {
    match nullish(value) {
        None => Ok(fallback.to_string()),
        Some(Value::String(text)) => Ok(text.clone()),
        Some(Value::Number(n)) => js_number_text(n.as_f64().ok_or_else(protocol)?),
        Some(_) => Err(protocol()),
    }
}

/// `buildWindowPageRecord`: the cache record of a viewed message window.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn window_page_record_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let chat_id = req_str(field(&input, "chatId"))?;
    let page_kind = req_str(field(&input, "pageKind"))?;
    let direction = req_str(field(&input, "direction"))?;
    let result = req_object(field(&input, "result"))?;
    let now = req_f64(field(&input, "now"))?;
    let message_ids = req_list(&input, "messageIds")?;
    let id = [
        chat_id.to_string(),
        page_kind.to_string(),
        direction.to_string(),
        id_part(field(result, "startCursor"), "start")?,
        id_part(field(result, "startCursorMessageId"), "start-id")?,
        id_part(field(result, "endCursor"), "end")?,
        id_part(field(result, "endCursorMessageId"), "end-id")?,
        number(PAGE_CACHE_GENERATION).to_string(),
    ]
    .join("|");
    let cached_at = nullish(field(&input, "existingCachedAt")).map_or(number(now), Clone::clone);
    let get = |key: &str| field(result, key).cloned().unwrap_or(Value::Null);
    Ok(json!({
        "id": id, "chat_id": chat_id, "page_kind": page_kind, "direction": direction,
        "start_cursor": get("startCursor"), "start_cursor_message_id": get("startCursorMessageId"),
        "end_cursor": get("endCursor"), "end_cursor_message_id": get("endCursorMessageId"),
        "has_more_before": get("hasMoreBefore"), "has_more_after": get("hasMoreAfter"),
        "message_ids": message_ids, "cached_at": cached_at, "last_accessed_at": number(now),
        "cache_generation": number(PAGE_CACHE_GENERATION),
    })
    .to_string())
}

struct Page<'a> {
    id: &'a str,
    chat_id: &'a str,
    kind: &'a str,
    accessed: f64,
    message_ids: Vec<&'a str>,
    generation: Option<f64>,
}

fn pages(input: &Value) -> Result<Vec<Page<'_>>, String> {
    req_list(input, "pages")?
        .iter()
        .map(|page| {
            let ids = req_list(page, "message_ids")?
                .iter()
                .map(|id| id.as_str().ok_or_else(protocol))
                .collect::<Result<Vec<_>, _>>()?;
            Ok(Page {
                id: req_str(field(page, "id"))?,
                chat_id: req_str(field(page, "chat_id"))?,
                kind: req_str(field(page, "page_kind"))?,
                accessed: req_f64(field(page, "last_accessed_at"))?,
                message_ids: ids,
                generation: as_f64(field(page, "cache_generation")),
            })
        })
        .collect()
}

fn string_set(input: &Value, key: &str) -> Result<HashSet<String>, String> {
    match nullish(field(input, key)) {
        None => Ok(HashSet::new()),
        Some(Value::Array(items)) => items
            .iter()
            .map(|v| v.as_str().map(str::to_string).ok_or_else(protocol))
            .collect(),
        Some(_) => Err(protocol()),
    }
}

fn sorted_normal<'a>(pages: &'a [Page<'a>]) -> Vec<&'a Page<'a>> {
    let mut normal: Vec<&Page> = pages.iter().filter(|p| p.kind == "normal").collect();
    normal.sort_by(|a, b| a.accessed.total_cmp(&b.accessed));
    normal
}

/// `planPageEviction`: `{pages, maxPagesPerChat?, protectedPageIds?, protectedMessageIds?}`
/// -> `{deleteCount, candidates}` (page ids, oldest access first).
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn evict_plan_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let pages = pages(&input)?;
    let max = nullish(field(&input, "maxPagesPerChat"))
        .map_or(Ok(DEFAULT_PAGE_CACHE_LIMIT), |v| req_f64(Some(v)))?
        .floor()
        .max(1.0);
    let protected_pages = string_set(&input, "protectedPageIds")?;
    let protected_messages = string_set(&input, "protectedMessageIds")?;
    let normal = sorted_normal(&pages);
    let delete_count = (normal.len() as f64 - max).max(0.0);
    let candidates: Vec<&str> = normal
        .iter()
        .filter(|p| !protected_pages.contains(p.id))
        .filter(|p| !p.message_ids.iter().any(|id| protected_messages.contains(*id)))
        .map(|p| p.id)
        .collect();
    Ok(json!({ "deleteCount": number(delete_count), "candidates": candidates }).to_string())
}

/// `planPageDeletion`: `{pages, deletingPageIds, protectedMessageIds?}` -> `{plan: [{pageId, messageIds}]}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn evict_delete_plan_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let pages = pages(&input)?;
    let deleting_ids = string_set(&input, "deletingPageIds")?;
    let order: Vec<&str> = req_list(&input, "deletingPageIds")?
        .iter()
        .filter_map(Value::as_str)
        .collect();
    let protected = string_set(&input, "protectedMessageIds")?;
    let retained: HashSet<&str> = pages
        .iter()
        .filter(|p| !deleting_ids.contains(p.id))
        .flat_map(|p| p.message_ids.iter().copied())
        .collect();
    let plan: Vec<Value> = order
        .iter()
        .map(|page_id| {
            let ids: Vec<&str> = pages
                .iter()
                .find(|p| p.id == *page_id)
                .map(|p| p.message_ids.clone())
                .unwrap_or_default()
                .into_iter()
                .filter(|id| !retained.contains(id) && !protected.contains(*id))
                .collect();
            json!({ "pageId": page_id, "messageIds": ids })
        })
        .collect();
    Ok(json!({ "plan": plan }).to_string())
}

/// `budgetCheckThrottled`: `{force, now, lastCheckAt}` -> `{throttled}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn budget_throttle_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let force = field(&input, "force").and_then(Value::as_bool).ok_or_else(protocol)?;
    let elapsed = req_f64(field(&input, "now"))? - req_f64(field(&input, "lastCheckAt"))?;
    Ok(json!({ "throttled": !force && elapsed < BUDGET_CHECK_INTERVAL_MS }).to_string())
}

/// `budgetTarget`: `{force, configuredBytes, quota?, usage?}` -> `{target, trim}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn budget_target_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let force = field(&input, "force").and_then(Value::as_bool).ok_or_else(protocol)?;
    let configured = req_f64(field(&input, "configuredBytes"))?;
    let target = match as_f64(field(&input, "quota")) {
        Some(quota) if quota.is_finite() && quota > 0.0 => configured.min((quota / 2.0).floor()),
        _ => configured,
    };
    let under = match as_f64(field(&input, "usage")) {
        None => true,
        Some(usage) => usage <= target,
    };
    Ok(json!({ "target": number(target), "trim": force || !under }).to_string())
}

/// `budgetCandidates`: `{pages}` -> `{pages: [{id, chat_id}]}` the trim visits, oldest first.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn budget_candidates_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let pages = pages(&input)?;
    let visit: Vec<Value> = sorted_normal(&pages)
        .iter()
        .filter(|p| p.generation == Some(PAGE_CACHE_GENERATION))
        .map(|p| json!({ "id": p.id, "chat_id": p.chat_id }))
        .collect();
    Ok(json!({ "pages": visit }).to_string())
}

/// `budgetChatStep`: `{normalPageCount}` -> `{skip, maxPagesPerChat}`.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn budget_chat_step_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let count = req_f64(field(&input, "normalPageCount"))?;
    Ok(json!({ "skip": count <= 1.0, "maxPagesPerChat": number(count - 1.0) }).to_string())
}

/// `budgetAfterEviction`: `{force, removed, target, usage?}` -> `{action}`; an absent
/// `usage` asks for an estimate when one is due, `null` means none is available.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn budget_after_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let force = field(&input, "force").and_then(Value::as_bool).ok_or_else(protocol)?;
    let removed = req_f64(field(&input, "removed"))?;
    let target = req_f64(field(&input, "target"))?;
    let action = if removed >= MAX_BUDGET_EVICTIONS {
        "stop_max"
    } else if force || removed % 4.0 != 0.0 {
        "continue"
    } else {
        match field(&input, "usage") {
            None => "need_usage",
            Some(usage) if as_f64(Some(usage)).is_some_and(|u| u <= target) => "stop_under_target",
            Some(_) => "continue",
        }
    };
    Ok(json!({ "action": action }).to_string())
}

/// `quotaStep`: `{stage, canRetry, errorName}` -> `{action}` of the quota retry flow.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn quota_step_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let stage = req_str(field(&input, "stage"))?;
    let can_retry = field(&input, "canRetry").and_then(Value::as_bool).ok_or_else(protocol)?;
    let quota = field(&input, "errorName").and_then(Value::as_str) == Some("QuotaExceededError");
    let action = if !quota {
        "rethrow"
    } else if stage == "write" && can_retry {
        "trim_retry"
    } else {
        "notify_throw"
    };
    Ok(json!({ "action": action }).to_string())
}

/// `chatsPageSize`: `{limit}` -> `{size}` clamped to 1..=50.
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn chats_page_size_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let limit = req_f64(field(&input, "limit"))?;
    Ok(json!({ "size": number(limit.clamp(1.0, 50.0)) }).to_string())
}

/// `pageConfirmed`: `{messages: [row | null]}` -> `{confirmed}`: every stored message of a
/// cached window page is safe to evict (an empty page is confirmed).
///
/// # Errors
/// `protocol` when the input is not that shape.
pub fn page_confirmed_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let confirmed = req_list(&input, "messages")?
        .iter()
        .all(super::message_policy::is_safe_to_evict);
    Ok(json!({ "confirmed": confirmed }).to_string())
}
