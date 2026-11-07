//! Offline share-metadata queue decisions.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `shareMetadataQueue.ts`: the pending-update records, the request
//! bodies of the two metadata endpoints, the retry/drop rule and the response
//! success test. Absent input fields mean JS `undefined` (omitted from the JSON
//! body); `null` stays `null`. IndexedDB, `fetch` and timers stay on the page.

use super::{Decision, field, js_number, str_field};
use serde_json::{Map, Value, json};

/// A queued update is dropped once it has been tried this many times (TS `MAX_RETRY_COUNT`).
const MAX_RETRY_COUNT: f64 = 5.0;

/// Copies `names` that are present in `input` (so `undefined` stays omitted, `null` stays `null`).
fn copy_present(input: &Value, names: &[&str], out: &mut Map<String, Value>) {
    for name in names {
        if let Some(value) = input.get(*name) {
            out.insert((*name).to_owned(), value.clone());
        }
    }
}

fn created_at(input: &Value) -> Result<Value, String> {
    let now_ms = field(input, "now_ms")?.as_f64().ok_or("bad_field:now_ms")?;
    Ok(json!((now_ms / 1000.0).floor() as i64))
}

/// JS `value || null` for a string-or-null field.
fn or_null(input: &Value, name: &str) -> Value {
    match input.get(name) {
        Some(Value::String(text)) if !text.is_empty() => json!(text),
        _ => Value::Null,
    }
}

fn chat_record(input: &Value) -> Decision {
    let mut out = Map::new();
    out.insert("update_id".into(), json!(str_field(input, "update_id")?));
    out.insert("chat_id".into(), json!(str_field(input, "chat_id")?));
    copy_present(input, &["title", "summary", "share_cta_text", "encrypted_shared_short_url", "share_pii", "share_highlights"], &mut out);
    out.insert("created_at".into(), created_at(input)?);
    out.insert("retry_count".into(), json!(0));
    Ok(Value::Object(out))
}

fn embed_record(input: &Value) -> Decision {
    let mut out = Map::new();
    out.insert("update_id".into(), json!(str_field(input, "update_id")?));
    out.insert("embed_id".into(), json!(str_field(input, "embed_id")?));
    out.insert("is_shared".into(), field(input, "is_shared")?.clone());
    copy_present(input, &["title", "description"], &mut out);
    out.insert("created_at".into(), created_at(input)?);
    out.insert("retry_count".into(), json!(0));
    Ok(Value::Object(out))
}

fn chat_body(input: &Value) -> Decision {
    let mut out = Map::new();
    out.insert("chat_id".into(), json!(str_field(input, "chat_id")?));
    out.insert("title".into(), or_null(input, "title"));
    out.insert("summary".into(), or_null(input, "summary"));
    // `shareCtaText || summary || null`
    let cta = match or_null(input, "share_cta_text") {
        Value::Null => or_null(input, "summary"),
        text => text,
    };
    out.insert("share_cta_text".into(), cta);
    out.insert("is_shared".into(), field(input, "is_shared")?.clone());
    copy_present(input, &["share_pii", "share_highlights", "encrypted_shared_short_url"], &mut out);
    Ok(Value::Object(out))
}

fn embed_body(input: &Value) -> Decision {
    Ok(json!({
        "embed_id": str_field(input, "embed_id")?,
        "is_shared": field(input, "is_shared")?,
        "title": or_null(input, "title"),
        "description": or_null(input, "description"),
    }))
}

fn retry_count(input: &Value) -> Result<f64, String> {
    field(input, "retry_count")?.as_f64().ok_or_else(|| "bad_field:retry_count".to_owned())
}

/// Dispatches the `queue*` ops.
pub(super) fn run(op: &str, input: &Value) -> Decision {
    match op {
        "queueChatRecord" => chat_record(input),
        "queueEmbedRecord" => embed_record(input),
        "queueChatBody" => chat_body(input),
        "queueEmbedBody" => embed_body(input),
        "queueRetryDecision" => Ok(json!(if retry_count(input)? >= MAX_RETRY_COUNT { "drop" } else { "send" })),
        "queueAttemptOutcome" => {
            let success = field(input, "success")?.as_bool().ok_or("bad_field:success")?;
            Ok(if success {
                json!({ "action": "delete" })
            } else {
                json!({ "action": "store", "retry_count": js_number(retry_count(input)? + 1.0) })
            })
        }
        // `data.success === true`
        "queueResponseSuccess" => Ok(json!(input.get("body").and_then(|body| body.get("success")) == Some(&json!(true)))),
        _ => Err(format!("unknown_op:{op}")),
    }
}
