//! Browser exports of the chat orchestration core (`chat_orchestration_jobs`).
//!
//! Thin JSON marshalling over `openmates_sdk::client::chat_orchestration`; every
//! rule (validation, planning, refusal, event lines, read bounds) lives in the
//! core. The web shell's Worker op table maps these `orchestration*` exports
//! (frontend/packages/ui/src/services/rustCore/crypto/orchestrationOps.ts).
use openmates_sdk::client::chat_orchestration::{
    Action, OrchestrationEvent, ReadMessage, bound_read_result, build_event, claim_frame,
    creator_from_sender_name, event_line, parse_event, parse_job, plan_job, result_frame,
};
use serde_json::{Value, json};
use wasm_bindgen::prelude::*;

fn code(value: &str) -> JsValue {
    JsValue::from_str(value)
}

fn event_value(event: &OrchestrationEvent) -> Value {
    json!({"action": event.action.as_str(), "chat_id": event.chat_id, "title": event.title,
        "text": event.text, "event_id": event.event_id, "created_at": event.created_at})
}

fn event_of(value: &Value) -> Option<OrchestrationEvent> {
    let action = match value.get("action")?.as_str()? {
        "started" => Action::Started,
        "report" => Action::Report,
        "finished" => Action::Finished,
        "waiting_for_user" => Action::WaitingForUser,
        "user_wrote" => Action::UserWrote,
        "sent" => Action::Sent,
        "reported" => Action::Reported,
        _ => return None,
    };
    let opt = |key: &str| value.get(key).and_then(Value::as_str).map(str::to_owned);
    Some(OrchestrationEvent {
        action,
        chat_id: opt("chat_id")?,
        title: opt("title"),
        text: opt("text"),
        event_id: opt("event_id")?,
        created_at: value.get("created_at")?.as_i64()?,
    })
}

/// Validate a `chat_orchestration_job_available` payload against `now_s`;
/// resolves the job JSON or `"null"` for an invalid or expired job.
#[wasm_bindgen(js_name = orchestrationParseJob)]
pub fn orchestration_parse_job(payload_json: String, now_s: f64) -> String {
    let parsed = serde_json::from_str::<Value>(&payload_json)
        .ok()
        .and_then(|value| parse_job(&value, Some(now_s as i64)).ok());
    parsed.map_or_else(|| "null".into(), |job| job.to_value().to_string())
}

/// Plan an already validated job; resolves the effect JSON (`kind` discriminates).
#[wasm_bindgen(js_name = orchestrationPlan)]
pub fn orchestration_plan(
    job_json: String,
    local_creator_chat_id: Option<String>,
) -> Result<String, JsValue> {
    let value: Value = serde_json::from_str(&job_json).map_err(|_| code("protocol"))?;
    let job = parse_job(&value, None).map_err(|_| code("protocol"))?;
    Ok(plan_job(&job, local_creator_chat_id.as_deref())
        .to_value()
        .to_string())
}

/// Payload of the `chat_orchestration_job_claim` frame.
#[wasm_bindgen(js_name = orchestrationClaimFrame)]
pub fn orchestration_claim_frame(job_id: String) -> String {
    claim_frame(&job_id).to_string()
}

/// Payload of the `chat_orchestration_job_result` frame.
#[wasm_bindgen(js_name = orchestrationResultFrame)]
pub fn orchestration_result_frame(
    job_id: String,
    ok: bool,
    error_code: Option<String>,
    result_json: Option<String>,
) -> Result<String, JsValue> {
    let result = match result_json.as_deref() {
        None | Some("") => None,
        Some(raw) => Some(serde_json::from_str::<Value>(raw).map_err(|_| code("protocol"))?),
    };
    Ok(result_frame(&job_id, ok, error_code.as_deref(), result.as_ref()).to_string())
}

/// Bound a `read_chat` result; `messages_json` is `[{role, content, created_at}]`.
#[wasm_bindgen(js_name = orchestrationBoundRead)]
pub fn orchestration_bound_read(messages_json: String, limit: u32) -> Result<String, JsValue> {
    let rows: Vec<Value> = serde_json::from_str(&messages_json).map_err(|_| code("protocol"))?;
    let mut messages = Vec::with_capacity(rows.len());
    for row in &rows {
        messages.push(ReadMessage {
            role: row
                .get("role")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned(),
            content: row
                .get("content")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned(),
            created_at: row
                .get("created_at")
                .and_then(Value::as_i64)
                .unwrap_or_default(),
        });
    }
    Ok(bound_read_result(&messages, limit as usize).to_string())
}

/// Parse system message content; the event JSON or `"null"`.
#[wasm_bindgen(js_name = orchestrationParseEvent)]
pub fn orchestration_parse_event(content: String) -> String {
    parse_event(&content).map_or_else(|| "null".into(), |event| event_value(&event).to_string())
}

/// One-line English summary of an event (`event_json` from `orchestrationParseEvent`).
#[wasm_bindgen(js_name = orchestrationEventLine)]
pub fn orchestration_event_line(
    event_json: String,
    resolved_title: Option<String>,
) -> Result<String, JsValue> {
    let value: Value = serde_json::from_str(&event_json).map_err(|_| code("protocol"))?;
    let event = event_of(&value).ok_or_else(|| code("protocol"))?;
    // Re-serialize through the core so only a valid event is rendered.
    let content = build_event(&event).map_err(|_| code("protocol"))?;
    let event = parse_event(&content).ok_or_else(|| code("protocol"))?;
    Ok(event_line(&event, resolved_title.as_deref()))
}

/// Creator chat id of a `chat:<uuid>` sender name, else `undefined`.
#[wasm_bindgen(js_name = orchestrationCreatorFromSenderName)]
pub fn orchestration_creator_from_sender_name(sender_name: Option<String>) -> Option<String> {
    creator_from_sender_name(sender_name.as_deref())
}
