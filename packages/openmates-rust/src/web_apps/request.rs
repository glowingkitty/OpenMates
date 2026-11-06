//! Natural-language Apps request policy (web `runAppsWorkspaceRequest`).
//!
//! Shared core for the web shared Worker `apps` unit. Mirrors the decisions of
//! `appsWorkspaceRequestService.ts`: request text trimming, the 24 KiB request
//! bounds (measured exactly like `TextEncoder(JSON.stringify(...))`), chat and
//! workflow handoff decisions and validation of the interpreter response.
//! The page keeps the privacy transform, identity asserts, attachments and Fetch.
//! Parity: `web_apps_request_ts_vectors.json`. Spec: feature.apps-workspace.
use serde::Deserialize;
use serde_json::value::RawValue;
use serde_json::{Value, json};

use super::{OrderedObject, field, read_json};

/// Maximum serialized request (and request + context) size accepted by the interpreter.
pub const MAX_REQUEST_BYTES: usize = 24 * 1024;

/// `String.prototype.trim()`: ECMAScript WhiteSpace and LineTerminator. Unlike
/// `char::is_whitespace`, U+FEFF is trimmed and U+0085 is not.
pub fn js_trim(text: &str) -> &str {
    text.trim_matches(|c: char| (c.is_whitespace() && c != '\u{85}') || c == '\u{feff}')
}

/// The page's request facts (platform values already resolved by the page).
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RequestFacts {
    /// Untrimmed composer text.
    pub text: String,
    /// App the request is scoped to.
    pub app_id: String,
    /// Caller-supplied request id; `None` mints a UUID v4.
    pub request_id: Option<String>,
    /// IANA timezone (caller option or the browser's).
    pub timezone: String,
    /// BCP 47 locale (caller option or the browser's).
    pub locale: String,
    /// Active Team; empty or `None` is Personal.
    pub team_id: Option<String>,
    /// Authenticated user id sent as `expected_user_id`.
    pub expected_user_id: Option<String>,
    /// Guest (anonymous) request.
    pub guest: bool,
    /// `File.type` of every attachment, in order.
    pub attachment_types: Vec<String>,
    /// Whether the caller supplied `onChat`.
    pub has_chat: bool,
}

impl RequestFacts {
    /// `requestBase` JSON text in the TS spread order. `text` is the trimmed (or
    /// privacy-protected) request text.
    fn base(&self, text: &str, request_id: &str) -> String {
        // serde_json's Map is sorted, so the object is written member by member.
        let mut out = String::from("{");
        let mut member = |key: &str, value: &str| {
            if out.len() > 1 {
                out.push(',');
            }
            out.push_str(&json!(key).to_string());
            out.push(':');
            out.push_str(&json!(value).to_string());
        };
        member("app_id", &self.app_id);
        member("text", text);
        member("request_id", request_id);
        member("timezone", &self.timezone);
        member("locale", &self.locale);
        if let Some(team) = self.team_id.as_deref().filter(|t| !t.is_empty()) {
            member("team_id", team);
        }
        if let Some(user) = self.expected_user_id.as_deref().filter(|u| !u.is_empty()) {
            member("expected_user_id", user);
        }
        out.push('}');
        out
    }
}

/// Size of `{...object, key: value}` given the JSON text of `object` (non-empty) and `value`.
fn with_member(object: &str, key: &str, value: &str) -> String {
    let mut out = String::with_capacity(object.len() + key.len() + value.len() + 4);
    out.push_str(&object[..object.len() - 1]);
    if object.len() > 2 {
        out.push(',');
    }
    out.push_str(&json!(key).to_string());
    out.push(':');
    out.push_str(value);
    out.push('}');
    out
}

/// A chat/workflow handoff the page performs. `reason` is raw JSON text (null:
/// no `reason` member). `identity_first` keeps the TS error precedence: the
/// large-context handoff asserts identity before checking the handler, every
/// other handoff checks the handler first.
fn handoff(target: &str, reason: Option<String>, available: bool, identity_first: bool) -> Value {
    json!({
        "kind": "handoff",
        "target": target,
        "reason": reason,
        "identityFirst": identity_first,
        "unavailable": if available { Value::Null } else { Value::from(format!("{target}_handoff_unavailable")) },
    })
}

fn large_context(facts: &RequestFacts) -> Value {
    handoff(
        "chat",
        Some(json!("result_context_too_large").to_string()),
        facts.has_chat,
        true,
    )
}

fn parse_facts(facts_json: &str) -> Result<RequestFacts, String> {
    serde_json::from_str(facts_json).map_err(|_| "protocol".to_string())
}

/// First request step, before the privacy transform.
///
/// `{kind:"error",message:"request_required"}` for blank text, else
/// `{kind:"ok",text,requestId,next}` where `next` is the decision the page acts
/// on after its team/identity asserts: `{kind:"error",message:"request_too_large"}`,
/// a handoff (large context, or attachments the Apps interpreter cannot take:
/// any for guests, anything but image/audio otherwise) or `{kind:"protect"}`.
/// `context_json` is `JSON.stringify(options.context)`, empty when absent.
///
/// # Errors
/// `protocol` for malformed facts or context text.
pub fn request_plan_json(facts_json: &str, context_json: &str) -> Result<String, String> {
    let facts = parse_facts(facts_json)?;
    let text = js_trim(&facts.text);
    if text.is_empty() {
        return Ok(json!({"kind":"error","message":"request_required"}).to_string());
    }
    let request_id = facts
        .request_id
        .clone()
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    let base = facts.base(text, &request_id);
    let next = if base.len() > MAX_REQUEST_BYTES {
        json!({"kind":"error","message":"request_too_large"})
    } else if !context_json.is_empty()
        && with_member(&base, "context", raw(context_json)?.get()).len() > MAX_REQUEST_BYTES
    {
        large_context(&facts)
    } else if !facts.attachment_types.is_empty()
        && (facts.guest
            || facts
                .attachment_types
                .iter()
                .any(|t| !t.starts_with("image/") && !t.starts_with("audio/")))
    {
        handoff("chat", None, facts.has_chat, false)
    } else {
        json!({"kind":"protect"})
    };
    Ok(json!({"kind":"ok","text":text,"requestId":request_id,"next":next}).to_string())
}

fn raw(text: &str) -> Result<&RawValue, String> {
    serde_json::from_str::<&RawValue>(text).map_err(|_| "protocol".to_string())
}

/// Protected request pieces after the page's privacy transform and attachment
/// preparation. Every `*_json` is `JSON.stringify` output, empty when absent.
pub struct ProtectedRequest<'a> {
    /// `privacy.protect(text)`.
    pub protected_text: &'a str,
    /// Protected `options.context`.
    pub protected_context_json: &'a str,
    /// `prepared.attachments` (unprotected; only measured for the handoff fallback).
    pub attachments_json: &'a str,
    /// Protected attachment descriptors.
    pub protected_attachments_json: &'a str,
    /// `prepared.assets`, sent but never counted against the bound.
    pub assets_json: &'a str,
}

/// Second request step: `{kind:"send",body}` (the interpreter POST body),
/// `{kind:"error",message:"request_too_large"}` or the large-context handoff
/// when only the context pushes the protected body over the bound.
///
/// # Errors
/// `protocol` for malformed facts or JSON pieces.
pub fn request_body_json(
    facts_json: &str,
    request_id: &str,
    pieces: &ProtectedRequest<'_>,
) -> Result<String, String> {
    let facts = parse_facts(facts_json)?;
    let text = js_trim(&facts.text);
    let prepared = !pieces.attachments_json.is_empty();
    let mut body = facts.base(pieces.protected_text, request_id);
    if prepared {
        body = with_member(
            &body,
            "attachments",
            raw(pieces.protected_attachments_json)?.get(),
        );
    }
    if !pieces.protected_context_json.is_empty() {
        body = with_member(&body, "context", raw(pieces.protected_context_json)?.get());
    }
    if body.len() > MAX_REQUEST_BYTES {
        let has_context = !pieces.protected_context_json.is_empty();
        let mut unprotected = facts.base(text, request_id);
        if prepared {
            unprotected = with_member(
                &unprotected,
                "attachments",
                raw(pieces.attachments_json)?.get(),
            );
        }
        if has_context && unprotected.len() <= MAX_REQUEST_BYTES {
            return Ok(large_context(&facts).to_string());
        }
        return Ok(json!({"kind":"error","message":"request_too_large"}).to_string());
    }
    if prepared {
        body = with_member(&body, "assets", raw(pieces.assets_json)?.get());
    }
    Ok(json!({"kind":"send","body":body}).to_string())
}

/// Interpreter response decision. `{kind:"syntax"}` means the body is not JSON
/// (the page rethrows the platform parse error, as `response.json()` would);
/// otherwise the page asserts identity and acts on `{kind:"error",message}`, a
/// handoff carrying `action` and raw `reason`, or `{kind:"execute",skillId,input,reason}`.
/// `reason`/`input` are raw JSON text (`reason` null when absent).
///
/// A `null` body makes the TS service throw a `TypeError` from a property read;
/// here it is the documented `interpretation_failed`/`invalid_interpretation`.
pub fn interpretation_json(
    ok: bool,
    text: &str,
    has_attachments: bool,
    has_chat: bool,
    has_workflow: bool,
) -> String {
    let (body, valid) = read_json(text);
    if !valid {
        return json!({"kind":"syntax"}).to_string();
    }
    if !ok {
        let message = field(&body, "detail")
            .and_then(Value::as_str)
            .unwrap_or("interpretation_failed");
        return json!({"kind":"error","message":message}).to_string();
    }
    let invalid = json!({"kind":"error","message":"invalid_interpretation"}).to_string();
    let action = match field(&body, "action").and_then(Value::as_str) {
        Some(action @ ("execute" | "chat" | "workflow")) => action,
        _ => return invalid,
    };
    // Raw members keep `reason`/`input` spelling; JSON.parse keeps a repeated key's last value.
    let members: Option<OrderedObject> = if body.is_object() {
        serde_json::from_str(text).ok()
    } else {
        None
    };
    let member = |key: &str| {
        members
            .as_ref()
            .and_then(|m| m.0.iter().find(|(k, _)| k == key))
            .map(|(_, raw)| raw.get().to_owned())
    };
    let reason = member("reason");
    let with_action = |mut decision: Value, result_action: &str, result_reason: Value| {
        decision["action"] = json!(result_action);
        decision["resultReason"] = result_reason;
        decision.to_string()
    };
    if action == "workflow" && has_attachments {
        let reason = json!("workflow_attachments_require_chat").to_string();
        return with_action(
            handoff("chat", Some(reason.clone()), has_chat, false),
            "chat",
            json!(reason),
        );
    }
    if action != "execute" {
        let available = if action == "chat" {
            has_chat
        } else {
            has_workflow
        };
        return with_action(
            handoff(action, reason.clone(), available, false),
            action,
            json!(reason),
        );
    }
    let skill = field(&body, "skill_id")
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty());
    let input_is_object = field(&body, "input").is_some_and(Value::is_object);
    match (skill, member("input")) {
        (Some(skill), Some(input)) if input_is_object => {
            json!({"kind":"execute","skillId":skill,"input":input,"reason":reason}).to_string()
        }
        _ => invalid,
    }
}

#[cfg(test)]
#[path = "request_tests.rs"]
mod tests;
