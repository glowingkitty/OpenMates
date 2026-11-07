//! Reply-recovery decisions of the web client: the optimistic version fence, the
//! authoritative-version response checks, the recovered-embed source helpers.
//!
//! Invariant: a recovered terminal ACK never lowers a newer local
//! `messages_v`, a version is trusted only from a response that names the exact
//! chat (and, for the legacy ACK, the exact encrypted assistant row), and a
//! recovered embed's catalog identity must be a bounded lowercase id.
//! Mirrors `chatRecoveryVersionApply.ts`, `chatRecoveryVersionRefresh.ts`,
//! and `recoveryEmbedSource.ts`.
//! spec: specifications/architecture/sync#sync.client.shared-rust-policy
use serde_json::{json, Map, Value};

use super::recovery_text::js_trim_is_empty;
use super::{field, nullish, num, number, parse, safe_integer};

/// `chatAfterRecoveredReply`: keep a newer local chat, else raise the fence.
///
/// Input `{latest:{messages_v,last_edited_overall_timestamp,updated_at},
/// committedVersion, now}` where `latest` is the page's `current ?? baseline`.
/// Output `{keep:true}` or the three fields to spread over the chat.
///
/// # Errors
/// `protocol` when the input is not a JSON object.
pub fn apply_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let latest = field(&input, "latest").ok_or_else(|| super::protocol(()))?;
    let committed = field(&input, "committedVersion");
    // `latest.messages_v > committedVersion`; NaN compares false, so the fence rises.
    if num(field(latest, "messages_v")) > num(committed) {
        return Ok(json!({ "keep": true }).to_string());
    }
    let now = num(field(&input, "now"));
    let max = |key: &str| {
        let value = num(field(latest, key));
        // `Math.max` is NaN when either operand is NaN.
        if value.is_nan() || now.is_nan() {
            f64::NAN
        } else {
            value.max(now)
        }
    };
    Ok(json!({
        "keep": false,
        "messages_v": committed.cloned().unwrap_or(Value::Null),
        "last_edited_overall_timestamp": number(max("last_edited_overall_timestamp")),
        "updated_at": number(max("updated_at")),
    })
    .to_string())
}

fn version_of(result: &Value, chat_id: Option<&Value>) -> Option<i64> {
    if field(result, "chat_id") != chat_id || chat_id.is_none() {
        return None;
    }
    safe_integer(field(result, "messages_v")).filter(|v| *v >= 0)
}

/// `refreshRecoveryChatVersion` response check: `{chatId, result}` to
/// `{version:n|null}`.
///
/// # Errors
/// `protocol` when the input is not valid JSON.
pub fn window_version_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let version = field(&input, "result").and_then(|r| version_of(r, field(&input, "chatId")));
    Ok(json!({ "version": version }).to_string())
}

/// `refreshPersistedAssistantVersion` response check: the version only when the
/// window holds the exact non-empty encrypted assistant row of that user turn.
///
/// # Errors
/// `protocol` when the input is not valid JSON.
pub fn assistant_version_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let chat_id = field(&input, "chatId");
    let version = field(&input, "result").and_then(|result| {
        let version = version_of(result, chat_id)?;
        let rows = field(result, "messages")?.as_array()?;
        let found = rows.iter().any(|row| {
            field(row, "message_id") == field(&input, "assistantMessageId")
                && field(row, "chat_id") == chat_id
                && field(row, "role").and_then(Value::as_str) == Some("assistant")
                && field(row, "user_message_id") == field(&input, "userMessageId")
                && field(row, "user_message_id").is_some()
                && field(row, "encrypted_content")
                    .and_then(Value::as_str)
                    .is_some_and(|s| !js_trim_is_empty(s))
        });
        found.then_some(version)
    });
    Ok(json!({ "version": version }).to_string())
}

/// `isUnwrittenInitialDiffRead`.
///
/// # Errors
/// `protocol` when the input is not valid JSON.
pub fn initial_diff_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let unwritten = num(field(&input, "version")) == 1.0
        && num(field(&input, "status")) == 409.0
        && field(&input, "detail").and_then(Value::as_str) == Some("snapshot_required");
    Ok(json!({ "unwritten": unwritten }).to_string())
}

fn is_catalog_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=64).contains(&bytes.len())
        && bytes[0].is_ascii_lowercase()
        && bytes[1..]
            .iter()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || *b == b'_')
}

/// `catalogContextFromSealedEmbed` decision. Input `{producerApp?, producerSkill?,
/// fields?}` (absent = `undefined`; `fields` is the decoded TOON object the page
/// reads only when a producer id is missing). Output `{kind:"none"}`,
/// `{kind:"context",app_id,skill_id}` or `{kind:"invalid"}`.
///
/// # Errors
/// `protocol` when the input is not valid JSON.
pub fn catalog_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let fields = field(&input, "fields");
    let pick = |producer: &str, key: &str| -> Option<Value> {
        nullish(field(&input, producer))
            .or_else(|| fields.and_then(|f| field(f, key)))
            .cloned()
    };
    let (app, skill) = (
        pick("producerApp", "app_id"),
        pick("producerSkill", "skill_id"),
    );
    if app.is_none() && skill.is_none() {
        return Ok(json!({ "kind": "none" }).to_string());
    }
    let valid = |v: &Option<Value>| {
        v.as_ref()
            .and_then(Value::as_str)
            .filter(|s| is_catalog_id(s))
            .map(str::to_owned)
    };
    Ok(match (valid(&app), valid(&skill)) {
        (Some(app_id), Some(skill_id)) => {
            json!({ "kind": "context", "app_id": app_id, "skill_id": skill_id })
        }
        _ => json!({ "kind": "invalid" }),
    }
    .to_string())
}

fn string_field<'a>(fields: &'a Value, key: &str) -> Option<&'a str> {
    field(fields, key).and_then(Value::as_str)
}

fn is_plain_object(value: Option<&Value>) -> bool {
    value.is_some_and(Value::is_object)
}

/// `historySourceFromSealedEmbed` decision over the page-decoded TOON value.
/// Output `{kind:"source",source}`, `{kind:"json_model",field}` (the page prints
/// the model with `JSON.stringify(model, null, 2)` to keep key order), or
/// `{kind:"error",code}` with code `mismatch`, `mail_fields`, `document_body` or
/// `format` (the page throws the matching original message).
///
/// # Errors
/// `protocol` when the input is not valid JSON.
pub fn history_source_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let kind = field(&input, "type")
        .and_then(Value::as_str)
        .ok_or_else(|| super::protocol(()))?;
    let decoded = field(&input, "decoded").ok_or_else(|| super::protocol(()))?;
    let error = |code: &str| Ok(json!({ "kind": "error", "code": code }).to_string());
    if !decoded.is_object() || field(decoded, "type").and_then(Value::as_str) != Some(kind) {
        return error("mismatch");
    }
    if kind == "mail" {
        let mut parts = Vec::new();
        for key in ["receiver", "subject", "content", "footer"] {
            match nullish(field(decoded, key)) {
                None => parts.push(""),
                Some(Value::String(s)) => parts.push(s.as_str()),
                Some(_) => return error("mail_fields"),
            }
        }
        let [receiver, subject, body, footer] = [parts[0], parts[1], parts[2], parts[3]];
        let mut lines: Vec<String> = Vec::new();
        if !receiver.is_empty() {
            lines.push(format!("to: {receiver}"));
        }
        if !subject.is_empty() {
            lines.push(format!("subject: {subject}"));
        }
        lines.push("content:".into());
        if !body.is_empty() {
            lines.push(body.into());
        }
        if !footer.is_empty() {
            lines.push("footer:".into());
            lines.push(footer.into());
        }
        return Ok(json!({ "kind": "source", "source": lines.join("\n") }).to_string());
    }
    if kind == "document" || kind == "notebook" {
        if kind == "document" {
            if let Some(html) = string_field(decoded, "html").filter(|s| !s.is_empty()) {
                return Ok(json!({ "kind": "source", "source": html }).to_string());
            }
        }
        let model = if kind == "document" {
            "docx_model"
        } else {
            "notebook"
        };
        if is_plain_object(field(decoded, model)) {
            return Ok(json!({ "kind": "json_model", "field": model }).to_string());
        }
        if kind == "notebook" {
            if let Some(content) = string_field(decoded, "content") {
                return Ok(json!({ "kind": "source", "source": content }).to_string());
            }
        }
        return error("document_body");
    }
    let key = match kind {
        "code" | "pcb_schematic" => "code",
        "sheet" => "table",
        "mermaid" => "diagram_code",
        _ => return error("format"),
    };
    match string_field(decoded, key) {
        Some(source) => Ok(json!({ "kind": "source", "source": source }).to_string()),
        None => error("format"),
    }
}
