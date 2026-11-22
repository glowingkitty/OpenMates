//! Assistant-initiated Plan creation (`openmates.plan_create_request` v1).
//!
//! spec: specifications/features/plans#plans.content.client-encrypted
//!
//! Validates the server's `plan_create_requested` event and returns what the
//! page must do: the Plan input (with the server `plan_id`), the ordered
//! assumption inputs (with the server `assumption_id`s) and the
//! `plan_create_result` frames for success and failure. The page only performs
//! the encrypted REST creates and sends the chosen result; no plaintext is
//! logged here.
use serde_json::{Value, json};

use super::Decision;

/// Contract name every request must carry.
pub const PLAN_CREATE_CONTRACT: &str = "openmates.plan_create_request";
/// Contract version this core implements.
pub const PLAN_CREATE_VERSION: u64 = 1;
const MAX_TITLE_CHARS: usize = 200;
const MAX_LONG_TEXT_CHARS: usize = 4000;
const MAX_ASSUMPTIONS: usize = 20;
const MAX_ASSUMPTION_CHARS: usize = 2000;
const REQUIRED_BEFORE: [&str; 3] = ["implementation", "task_execution", "completion"];

fn is_uuid(value: &Value) -> Option<&str> {
    value
        .as_str()
        .filter(|text| uuid::Uuid::parse_str(text).is_ok())
}

fn is_request_id(value: &Value) -> Option<&str> {
    value
        .as_str()
        .filter(|text| !text.is_empty() && text.len() <= 128)
}

fn text<'a>(value: &'a Value, max: usize, required: bool) -> Option<&'a str> {
    match value {
        Value::Null if !required => Some(""),
        Value::String(text)
            if (!required || !text.trim().is_empty()) && text.chars().count() <= max =>
        {
            Some(text)
        }
        _ => None,
    }
}

fn failed(request_id: Option<&str>, code: &str) -> Value {
    json!({ "ok": false, "request_id": request_id, "result": {
        "request_id": request_id, "status": "failed", "error_code": code } })
}

/// Validates one `plan_create_requested` payload for `now_s` (unix seconds).
///
/// Always answers with a JSON document: `{ok:true, ...}` with the steps, or
/// `{ok:false, result}` carrying the `failed` report (request id kept when it
/// could be read).
pub(crate) fn decide(input: &Value) -> Decision {
    let event = input.get("event").unwrap_or(&Value::Null);
    let now_s = input
        .get("now_s")
        .and_then(Value::as_u64)
        .ok_or("missing_field:now_s")?;
    let action = &event["pending_client_action"];
    let request_id = is_request_id(&action["request_id"]);
    let Some(rid) = request_id else {
        return Ok(failed(None, "PLAN_CREATE_REQUEST_INVALID"));
    };
    let chat_id = is_uuid(&action["chat_id"]);
    let plan_id = is_uuid(&action["plan_id"]);
    let valid_shape = action["contract"] == PLAN_CREATE_CONTRACT
        && action["version"] == PLAN_CREATE_VERSION
        && action["action"] == "create"
        && event["request_id"] == action["request_id"]
        && chat_id.is_some()
        && event["chat_id"] == action["chat_id"]
        && plan_id.is_some();
    let title = text(&action["title"], MAX_TITLE_CHARS, true);
    let goal = text(&action["goal"], MAX_LONG_TEXT_CHARS, true);
    let summary = text(&action["summary"], MAX_LONG_TEXT_CHARS, false);
    let spec_ref = text(&action["specification_ref"], MAX_TITLE_CHARS, false);
    let (Some(title), Some(goal), Some(summary), Some(spec_ref), true) =
        (title, goal, summary, spec_ref, valid_shape)
    else {
        return Ok(failed(request_id, "PLAN_CREATE_REQUEST_INVALID"));
    };
    let raw = action["assumptions"]
        .as_array()
        .map_or(&[][..], Vec::as_slice);
    if !action["assumptions"].is_null() && !action["assumptions"].is_array()
        || raw.len() > MAX_ASSUMPTIONS
    {
        return Ok(failed(request_id, "PLAN_CREATE_REQUEST_INVALID"));
    }
    let mut assumptions = Vec::with_capacity(raw.len());
    for item in raw {
        let required_before = item["required_before"].as_str().unwrap_or("implementation");
        let (Some(id), Some(body)) = (
            is_uuid(&item["assumption_id"]),
            text(&item["text"], MAX_ASSUMPTION_CHARS, true),
        ) else {
            return Ok(failed(request_id, "PLAN_CREATE_REQUEST_INVALID"));
        };
        if !REQUIRED_BEFORE.contains(&required_before) {
            return Ok(failed(request_id, "PLAN_CREATE_REQUEST_INVALID"));
        }
        assumptions.push(json!({ "assumptionId": id, "text": body,
            "requiredBefore": required_before, "status": "unchecked" }));
    }
    if action["expires_at"]
        .as_u64()
        .is_none_or(|expires| expires <= now_s)
    {
        return Ok(failed(request_id, "PLAN_CREATE_REQUEST_EXPIRED"));
    }
    let constraints = if spec_ref.is_empty() {
        String::new()
    } else {
        format!("Specification: {spec_ref}")
    };
    Ok(json!({
        "ok": true,
        "request_id": rid,
        "chat_id": chat_id,
        "plan": { "planId": plan_id, "title": title, "goal": goal, "scopeIn": summary,
            "constraints": constraints, "primaryChatId": chat_id },
        "assumptions": assumptions,
        "created": { "request_id": rid, "status": "created", "plan_id": plan_id },
        "failed": { "request_id": rid, "status": "failed", "error_code": "PLAN_CREATE_FAILED" },
        "conflict": { "request_id": rid, "status": "failed", "error_code": "PLAN_ID_CONFLICT" },
    }))
}
