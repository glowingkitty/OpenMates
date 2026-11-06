//! Web Apps skill execution policy (the shared Rust core Worker `apps` unit).
//!
//! The browser keeps Fetch, identity stores, timers and caches; every decision
//! about a skill details/availability/execute/poll exchange is made here, with
//! exactly the semantics of the web TypeScript service it replaces
//! (`appsWorkspaceService.ts`, proven by `web_apps_ts_vectors.json`).
//! Every function takes and returns JSON text, so the wasm boundary carries one
//! string per call. Response bodies are never re-serialized for the page except
//! in [`assemble_tasks_json`], which splices the original JSON text (key order
//! and number spelling preserved) instead of round-tripping a `Value`.
use serde::de::{Deserializer, MapAccess, Visitor};
use serde_json::value::RawValue;
use serde_json::{json, Value};

/// Delay between two task polls and the total poll budget (ms).
pub const POLL_INTERVAL_MS: u64 = 2_000;
pub const POLL_TIMEOUT_MS: u64 = 10 * 60 * 1_000;

fn protocol<E>(_: E) -> String {
    "protocol".to_string()
}

/// `response.json()` with the web service's `readJson` fallback: invalid JSON is `{}`.
fn read_json(text: &str) -> (Value, bool) {
    match serde_json::from_str::<Value>(text) {
        Ok(value) => (value, true),
        Err(_) => (json!({}), false),
    }
}

/// JS truthiness of a JSON value.
fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|n| n != 0.0 && !n.is_nan()),
        Some(Value::String(s)) => !s.is_empty(),
        Some(_) => true,
    }
}

/// `value ?? fallback` (null and absent are nullish).
fn nullish<'a>(value: Option<&'a Value>) -> Option<&'a Value> {
    value.filter(|v| !v.is_null())
}

/// `typeof value === 'object' && value` (objects and arrays).
fn object_like(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Object(_)) | Some(Value::Array(_)))
}

/// Property read with JS semantics: only plain objects carry named fields here.
fn field<'a>(value: &'a Value, key: &str) -> Option<&'a Value> {
    value.as_object().and_then(|object| object.get(key))
}

/// `Number.prototype.toString()` for a finite or non-finite double.
pub(crate) fn js_number(value: f64) -> String {
    if value.is_nan() {
        return "NaN".into();
    }
    if value.is_infinite() {
        return if value > 0.0 { "Infinity".into() } else { "-Infinity".into() };
    }
    if value == 0.0 {
        return "0".into();
    }
    let sign = if value < 0.0 { "-" } else { "" };
    // Rust's `{:e}` prints the shortest round-trip digits, as JS does.
    let formatted = format!("{:e}", value.abs());
    let (mantissa, exponent) = formatted.split_once('e').unwrap_or((&formatted, "0"));
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    let k = digits.len() as i64;
    let n = exponent.parse::<i64>().unwrap_or(0) + 1;
    let body = if k <= n && n <= 21 {
        format!("{digits}{}", "0".repeat((n - k) as usize))
    } else if 0 < n && n <= 21 {
        format!("{}.{}", &digits[..n as usize], &digits[n as usize..])
    } else if -6 < n && n <= 0 {
        format!("0.{}{digits}", "0".repeat((-n) as usize))
    } else {
        let rest = if k > 1 { format!(".{}", &digits[1..]) } else { String::new() };
        let e = n - 1;
        format!("{}{rest}e{}{}", &digits[..1], if e >= 0 { "+" } else { "-" }, e.abs())
    };
    format!("{sign}{body}")
}

/// `String(value)` for a JSON value.
pub(crate) fn js_string(value: &Value) -> String {
    match value {
        Value::Null => "null".into(),
        Value::Bool(b) => b.to_string(),
        Value::Number(n) => js_number(n.as_f64().unwrap_or(f64::NAN)),
        Value::String(s) => s.clone(),
        Value::Array(items) => items
            .iter()
            .map(|item| if item.is_null() { String::new() } else { js_string(item) })
            .collect::<Vec<_>>()
            .join(","),
        Value::Object(_) => "[object Object]".into(),
    }
}

/// `encodeURIComponent` for a path segment.
pub(crate) fn encode_uri_component(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || b"-_.!~*'()".contains(&byte) {
            out.push(byte as char);
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

/// The web service's `errorDetail(body, status)`.
pub fn error_detail(body: &Value, status: u16) -> String {
    let fallback = format!("HTTP {status}");
    // Arrays are `typeof 'object'` but carry no named field.
    let detail = nullish(field(body, "detail")).or_else(|| nullish(field(body, "error")));
    match detail {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Array(items)) => items
            .iter()
            .map(|item| match field(item, "msg") {
                Some(msg) => js_string(msg),
                None => js_string(item),
            })
            .collect::<Vec<_>>()
            .join("; "),
        Some(item @ Value::Object(_)) => match nullish(field(item, "message")).or_else(|| nullish(field(item, "code"))) {
            Some(value) => js_string(value),
            None => fallback,
        },
        _ => fallback,
    }
}

/// The web service's `failedSkillResponse(body)`: the thrown message, if any.
pub fn skill_failure(body: &Value) -> Option<String> {
    if field(body, "success") == Some(&Value::Bool(false)) {
        let error = field(body, "error");
        return Some(if truthy(error) { js_string(error.unwrap_or(&Value::Null)) } else { "skill_failed".into() });
    }
    let data = field(body, "data");
    if !object_like(data) {
        return None;
    }
    let data = data.unwrap_or(&Value::Null);
    let error = field(data, "error");
    if field(data, "success") == Some(&Value::Bool(false)) || matches!(error, Some(Value::String(_))) {
        return Some(if truthy(error) { js_string(error.unwrap_or(&Value::Null)) } else { "skill_failed".into() });
    }
    None
}

/// The web service's `acceptedTaskIds(envelope)`.
pub fn accepted_task_ids(envelope: &Value) -> Vec<String> {
    let data = field(envelope, "data");
    let data = if object_like(data) { data.unwrap_or(envelope) } else { envelope };
    if let Some(Value::String(id)) = field(data, "task_id") {
        return vec![id.clone()];
    }
    match field(data, "task_ids") {
        Some(Value::Array(ids)) => ids.iter().filter_map(|id| id.as_str().map(str::to_owned)).collect(),
        _ => Vec::new(),
    }
}

/// Request descriptor for a skill's public details.
pub fn details_request_json(app: &str, skill: &str, has_signal: bool) -> String {
    // Mail search is the one user-gated catalog entry: it keeps its session so
    // the backend allowlist stays authoritative, and is admitted on every call.
    let private = app == "mail" && skill == "search";
    json!({
        "path": format!("/v1/apps/{}/skills/{}/details", encode_uri_component(app), encode_uri_component(skill)),
        "credentials": if private { "include" } else { "omit" },
        // A caller-specific abort must not cancel a shared cached request.
        "cacheable": !private && !has_signal,
    })
    .to_string()
}

/// Outcome of a details response: `{kind:"ok",valid}` or `{kind:"error",message}`.
pub fn details_outcome_json(status: u16, ok: bool, text: &str) -> String {
    let (body, valid) = read_json(text);
    if !ok {
        return json!({"kind":"error","message":error_detail(&body, status)}).to_string();
    }
    json!({"kind":"ok","valid":valid}).to_string()
}

/// Pre-dispatch admission and request descriptor for one skill execution.
pub fn execution_request_json(app: &str, skill: &str, guest: bool, team_id: &str, metadata_json: &str) -> Result<String, String> {
    let metadata: Value = serde_json::from_str(metadata_json).map_err(protocol)?;
    let same = |key: &str, expected: &str| field(&metadata, key).and_then(Value::as_str) == Some(expected);
    if !same("app_id", app) || !same("skill_id", skill) || !truthy(field(&metadata, "execution_available")) {
        let reason = nullish(field(&metadata, "unavailable_reason")).map(js_string).unwrap_or_else(|| "skill_unavailable".into());
        return Ok(json!({"kind":"error","message":reason}).to_string());
    }
    if guest && (!truthy(field(&metadata, "anonymous_allowed")) || field(&metadata, "execution_mode").and_then(Value::as_str) != Some("sync")) {
        return Ok(json!({"kind":"error","message":"signup_required"}).to_string());
    }
    let skill_path = format!("/{}/skills/{}", encode_uri_component(app), encode_uri_component(skill));
    let base = if guest { "/v1/anonymous/apps" } else { "/v1/apps" };
    Ok(json!({
        "kind": "ok",
        "path": format!("{base}{skill_path}"),
        "teamId": if !guest && !team_id.is_empty() { Value::from(team_id) } else { Value::Null },
        "availabilityPath": if guest { Value::from(format!("/v1/anonymous/apps{skill_path}/availability")) } else { Value::Null },
    })
    .to_string())
}

/// Request descriptor for the anonymous request quote (never dispatches a skill).
pub fn availability_request_json(app: &str, skill: &str) -> String {
    json!({"path": format!("/v1/anonymous/apps/{}/skills/{}/availability", encode_uri_component(app), encode_uri_component(skill))}).to_string()
}

/// Anonymous request quote: `{allowed, reason}`.
pub fn availability_outcome_json(status: u16, ok: bool, text: &str) -> String {
    let (body, _) = read_json(text);
    if !ok {
        return json!({"allowed":false,"reason":error_detail(&body, status)}).to_string();
    }
    json!({
        "allowed": field(&body, "allowed") == Some(&Value::Bool(true)),
        "reason": field(&body, "reason").filter(|r| r.is_string()).cloned().unwrap_or(Value::Null),
    })
    .to_string()
}

/// Skill POST response: `{kind:"error",message}`, `{kind:"tasks",ids}` (non-guest
/// accepted async job, resolved by polling) or `{kind:"done",valid}`.
pub fn skill_response_json(status: u16, ok: bool, text: &str, guest: bool) -> String {
    let (body, valid) = read_json(text);
    if !ok {
        return json!({"kind":"error","message":error_detail(&body, status)}).to_string();
    }
    if body.is_null() {
        return json!({"kind":"error","message":"invalid_skill_response"}).to_string();
    }
    if let Some(message) = skill_failure(&body) {
        return json!({"kind":"error","message":message}).to_string();
    }
    let ids = if guest { Vec::new() } else { accepted_task_ids(&body) };
    if ids.is_empty() {
        return json!({"kind":"done","valid":valid}).to_string();
    }
    json!({"kind":"tasks","ids":ids}).to_string()
}

/// One task poll response: `completed`, `retry` (with delay and total budget)
/// or `error` with the thrown message.
pub fn poll_step_json(task_id: &str, status: u16, ok: bool, text: &str) -> String {
    let (body, _) = read_json(text);
    if !ok && status < 500 {
        return json!({"kind":"error","message":format!("Task {task_id}: {}", error_detail(&body, status))}).to_string();
    }
    if ok && body.is_null() {
        return json!({"kind":"error","message":"invalid_task_response"}).to_string();
    }
    let state = field(&body, "status").and_then(Value::as_str);
    if ok && state == Some("completed") {
        return json!({"kind":"completed"}).to_string();
    }
    if ok && state == Some("failed") {
        let error = nullish(field(&body, "error")).map(js_string).unwrap_or_else(|| "task_failed".into());
        return json!({"kind":"error","message":format!("Task {task_id}: {error}")}).to_string();
    }
    json!({
        "kind": "retry",
        "delayMs": POLL_INTERVAL_MS,
        "deadlineMs": POLL_TIMEOUT_MS,
        "timeoutMessage": format!("Task {task_id} is still processing; retain its ID to reopen the result."),
    })
    .to_string()
}

/// Top-level object members in source order, borrowed as raw JSON text.
struct OrderedObject<'a>(Vec<(String, &'a RawValue)>);

impl<'de: 'a, 'a> serde::Deserialize<'de> for OrderedObject<'a> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct Members<'a>(std::marker::PhantomData<&'a ()>);
        impl<'de: 'a, 'a> Visitor<'de> for Members<'a> {
            type Value = OrderedObject<'a>;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("a JSON object")
            }
            fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
                let mut members: Vec<(String, &'a RawValue)> = Vec::new();
                while let Some((key, value)) = map.next_entry::<String, &'a RawValue>()? {
                    // JSON.parse: a repeated key keeps its first position and its last value.
                    match members.iter_mut().find(|(existing, _)| *existing == key) {
                        Some(slot) => slot.1 = value,
                        None => members.push((key, value)),
                    }
                }
                Ok(OrderedObject(members))
            }
        }
        deserializer.deserialize_map(Members(std::marker::PhantomData))
    }
}

fn push_member(out: &mut String, key: &str, value: &str) {
    if out.len() > 1 {
        out.push(',');
    }
    out.push_str(&serde_json::to_string(key).unwrap_or_default());
    out.push(':');
    out.push_str(value);
}

/// `{...envelope, data: results.length === 1 ? results[0] : results}` where each
/// result is the `result` member of a completed poll response, then the web
/// service's post-resolution failure check. `{kind:"done",text}` carries the
/// resolved envelope as JSON text; `{kind:"error",message}` the thrown message.
/// A completed poll without `result` stands for `undefined`: dropped for a
/// single result, `null` inside the array (as `JSON.stringify` would write it).
/// `check_failure` is false only when resuming an already accepted execution,
/// which the web service returns without the post-resolution check.
pub fn assemble_tasks_json(envelope_text: &str, poll_texts_json: &str, check_failure: bool) -> Result<String, String> {
    let polls: Vec<String> = serde_json::from_str(poll_texts_json).map_err(protocol)?;
    let envelope: OrderedObject = serde_json::from_str(envelope_text).map_err(protocol)?;
    let mut results: Vec<Option<&RawValue>> = Vec::with_capacity(polls.len());
    let parsed: Vec<OrderedObject> = polls.iter().map(|text| serde_json::from_str(text).map_err(protocol)).collect::<Result<_, _>>()?;
    for poll in &parsed {
        results.push(poll.0.iter().find(|(key, _)| key == "result").map(|(_, value)| *value));
    }
    let data: Option<String> = if results.len() == 1 {
        results[0].map(|raw| raw.get().to_owned())
    } else {
        let items: Vec<&str> = results.iter().map(|raw| raw.map_or("null", RawValue::get)).collect();
        Some(format!("[{}]", items.join(",")))
    };
    let mut out = String::from("{");
    let mut wrote_data = false;
    for (key, value) in &envelope.0 {
        if key == "data" {
            wrote_data = true;
            if let Some(data) = &data {
                push_member(&mut out, key, data);
            }
            continue;
        }
        push_member(&mut out, key, value.get());
    }
    if !wrote_data && let Some(data) = &data {
        push_member(&mut out, "data", data);
    }
    out.push('}');
    if check_failure {
        let resolved: Value = serde_json::from_str(&out).map_err(protocol)?;
        if let Some(message) = skill_failure(&resolved) {
            return Ok(json!({"kind":"error","message":message}).to_string());
        }
    }
    Ok(json!({"kind":"done","text":out}).to_string())
}

/// The `result` member of one completed poll response as its original JSON
/// text: `{kind:"done",text}`, or `{kind:"absent"}` for `undefined`.
pub fn task_result_json(poll_text: &str) -> Result<String, String> {
    let poll: OrderedObject = serde_json::from_str(poll_text).map_err(protocol)?;
    Ok(match poll.0.iter().find(|(key, _)| key == "result") {
        Some((_, raw)) => json!({"kind":"done","text":raw.get()}),
        None => json!({"kind":"absent"}),
    }
    .to_string())
}

#[cfg(test)]
#[path = "web_apps_tests.rs"]
mod tests;
