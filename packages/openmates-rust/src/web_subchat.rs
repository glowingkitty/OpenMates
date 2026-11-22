//! Sub-chat shell and Plan-assumption link decisions of the web `subchatDecide` op.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//!
//! Replaces the field building and encryption of `handleSpawnSubChatsImpl`
//! (`chatSyncServiceHandlersAI.ts`). The page keeps IndexedDB, the parent key
//! (passed as base64 for the one call, never stored or logged here), the
//! master-key wrapping of the chat key and the HTTP transport. Ops are JSON in,
//! JSON out; failures answer `Err(reason)`.
//!
//! - `subchatShell`: the child chat record (encrypted title, category, icon) with
//!   `encrypted_active_focus_id` taken from `focus_id`, else from the Project base
//!   focus `project-<project_id>`, plus `project_id` when the child joins the
//!   parent's Project.
//! - `subchatLinkRequest`: the PATCH that links an assumption to the child chat
//!   (`null` for task links, which the server writes, and for no link).
//! - `subchatLinkRetry`: backoff after a failed link PATCH (Plan or assumption not
//!   created yet) and the final warn-and-give-up decision.

use crate::crypto;
use serde_json::{Value, json};

/// Attempts of the link PATCH before giving up with a warning.
pub const LINK_MAX_ATTEMPTS: u64 = 5;
/// Delay before the first retry; doubles per attempt.
pub const LINK_BASE_DELAY_MS: u64 = 500;

/// Runs one op on a JSON document and answers its JSON.
pub fn run_json(op: &str, input: &str) -> Result<String, String> {
    let input: Value = serde_json::from_str(input).map_err(|e| e.to_string())?;
    let out = match op {
        "subchatShell" => shell(&input)?,
        "subchatLinkRequest" => link_request(&input),
        "subchatLinkRetry" => link_retry(&input),
        other => return Err(format!("unknown op {other}")),
    };
    Ok(out.to_string())
}

fn text<'a>(value: &'a Value, field: &str) -> Option<&'a str> {
    value
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|s| !s.is_empty())
}

fn shell(input: &Value) -> Result<Value, String> {
    let child = input.get("child").ok_or("missing child")?;
    let parent = text(input, "parent_chat_id").ok_or("missing parent_chat_id")?;
    let key = crypto::decode_key(text(input, "parent_key").ok_or("missing parent_key")?)
        .map_err(|_| "bad parent_key".to_string())?;
    let now = input
        .get("now")
        .and_then(Value::as_i64)
        .ok_or("missing now")?;
    let id = text(child, "id")
        .or_else(|| text(child, "chat_id"))
        .ok_or("missing child id")?;
    let title = text(child, "title")
        .or_else(|| text(child, "prompt"))
        .unwrap_or("");
    let seal = |value: &str| {
        crypto::encrypt_combined(value, &key).map_err(|_| "encrypt failed".to_string())
    };
    let category = text(child, "category");
    let icon = text(child, "icon");
    let project_id = child
        .get("project_base")
        .and_then(|b| text(b, "project_id"));
    let focus = text(child, "focus_id")
        .map(str::to_owned)
        .or_else(|| project_id.map(|p| format!("project-{p}")));
    let mut chat = json!({
        "chat_id": id,
        "parent_id": parent,
        "is_sub_chat": true,
        "title": title,
        "encrypted_title": seal(title)?,
        "category": category,
        "encrypted_category": category.map(seal).transpose()?,
        "icon": icon,
        "encrypted_icon": icon.map(seal).transpose()?,
        "messages_v": 1,
        "title_v": 0,
        "unread_count": 0,
        "created_at": now,
        "updated_at": now,
        "last_edited_overall_timestamp": now,
    });
    if let Some(user) = text(input, "user_id") {
        chat["user_id"] = json!(user);
    }
    if let Some(focus) = focus {
        chat["encrypted_active_focus_id"] = json!(seal(&focus)?);
    }
    Ok(json!({"chat": chat, "project_id": project_id}))
}

fn link_request(input: &Value) -> Value {
    let Some(link) = input
        .get("link")
        .filter(|l| l.get("kind").and_then(Value::as_str) == Some("assumption"))
    else {
        return Value::Null;
    };
    let (Some(plan), Some(assumption), Some(chat)) = (
        text(link, "plan_id"),
        text(link, "id"),
        text(input, "chat_id"),
    ) else {
        return Value::Null;
    };
    json!({
        "method": "PATCH",
        "path": format!("/v1/user-plans/{plan}/assumptions/{assumption}"),
        "body": {"linked_sub_chat_id": chat},
    })
}

fn link_retry(input: &Value) -> Value {
    let attempt = input.get("attempt").and_then(Value::as_u64).unwrap_or(1);
    if attempt >= LINK_MAX_ATTEMPTS {
        return json!({"retry": false, "warn": true});
    }
    json!({"retry": true, "delay_ms": LINK_BASE_DELAY_MS << (attempt.saturating_sub(1)).min(6)})
}
