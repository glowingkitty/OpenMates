//! Verdicts on a decrypted connected-source answer: the response envelope (ok/result or a
//! typed refusal) and the operation-specific shape checks of text, image-chunk and
//! file-chunk results. Shared core part of `web_projects`.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `projectRemoteResponse` / `projectRemoteNormalize` of `remoteAccessPolicy.ts`.

use super::js::{TableHit, is_safe_integer, js_string, len16, table_get};
use super::remote_access::parse_remote_object;
use super::{Outcome, throw};
use regex::Regex;
use serde_json::{Map, Value, json};
use std::sync::LazyLock;

/// A lower-case hex SHA-256 digest.
static HEX64: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-f0-9]{64}$").expect("static pattern compiles"));
/// Padded standard base64.
static BASE64: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$").expect("static pattern compiles")
});
/// A source-chosen error code that may be shown as its own refusal code.
static ERROR_CODE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[a-z][a-z0-9_]{0,63}$").expect("static pattern compiles"));

/// Chunk alignment of image and file reads.
const CHUNK_BYTES: f64 = 128.0 * 1024.0;
/// Base64 text cap of one chunk.
const MAX_CHUNK_BASE64: usize = 175_000;
/// Largest image a README/preview reads from a connected source.
const MAX_IMAGE_BYTES: f64 = 2.0 * 1024.0 * 1024.0;
const IMAGE_TYPES: [&str; 5] = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"];

/// `remoteAccessErrorMessage`: caller-facing text of a source refusal code.
const ERROR_MESSAGES: &[(&str, &str)] = &[
    ("protected_path", "This file is protected or ignored"),
    ("unsupported_file", "This file is binary or unsupported"),
    ("invalid_path", "This source path is unavailable"),
    ("search_query_required", "Enter a search query"),
    ("operation_failed", "The remote source could not complete this request"),
    ("file_changed", "The file changed. Read its current content and rebuild the edit"),
    ("target_exists", "The create target already exists; its content was preserved"),
    ("source_missing", "The source is gone. Check the destination before trying again"),
    ("invalid_patch", "The patch does not exactly match the current file"),
    ("operation_conflict", "This operation identity was already used for different changes"),
    ("operation_unconfirmed", "A previous file operation may be incomplete. Inspect the destination before retrying"),
    ("write_authorization_denied", "The originating chat no longer has permission to write this Project"),
    ("ignored_path_requires_approval", "This ignored file requires explicit approval"),
];

/// `projectRemoteResponse`: `{result}` for `ok: true`, else a refusal with the source's code.
pub(super) fn response(input: &Value) -> Outcome {
    let response =
        parse_remote_object(input.get("plaintext"), "The Project source returned an invalid encrypted response")?;
    if response.get("ok") != Some(&Value::Bool(true)) {
        let code = match response.get("error") {
            Some(Value::String(code)) if ERROR_CODE.is_match(code) => code.as_str(),
            _ => "operation_failed",
        };
        let mut error = Map::new();
        error.insert("code".into(), json!(code));
        // The TS table is an object literal: `constructor` resolves to a function that
        // JSON drops, so that code answers without a message, exactly like TS.
        let message = match table_get(ERROR_MESSAGES, code) {
            TableHit::Missing => Some(json!("The remote source rejected this request")),
            hit => hit.json(),
        };
        if let Some(message) = message {
            error.insert("message".into(), message);
        }
        return Ok(json!({ "remoteError": error }));
    }
    let mut out = Map::new();
    if let Some(result) = response.get("result") {
        out.insert("result".into(), result.clone());
    }
    Ok(Value::Object(out))
}

fn number(map: &Map<String, Value>, name: &str) -> Option<f64> {
    let value = map.get(name);
    is_safe_integer(value).then(|| value.and_then(Value::as_f64)).flatten()
}

fn hex(map: &Map<String, Value>, name: &str) -> bool {
    map.get(name).and_then(Value::as_str).is_some_and(|text| HEX64.is_match(text))
}

fn base64(map: &Map<String, Value>) -> bool {
    map.get("content_base64")
        .and_then(Value::as_str)
        .is_some_and(|text| len16(text) <= MAX_CHUNK_BASE64 && BASE64.is_match(text))
}

fn text_result(value: Option<&Value>) -> Outcome {
    const INVALID: &str = "The Project source returned an invalid text result";
    let result = parse_remote_object(value, INVALID)?;
    let expected_base = result.get("expected_base");
    let base_ok = match expected_base {
        Some(Value::Null) => true,
        Some(Value::String(text)) => HEX64.is_match(text),
        _ => false,
    };
    let content = result.get("content").filter(|v| v.is_string());
    let truncated = result.get("truncated").and_then(Value::as_bool);
    let size = number(&result, "sizeBytes").filter(|n| *n >= 0.0);
    let lines = number(&result, "lineCount").filter(|n| *n >= 0.0);
    let (Some(content), Some(truncated), Some(size), Some(lines), true) = (content, truncated, size, lines, base_ok)
    else {
        return Err(throw(INVALID));
    };
    if truncated && expected_base != Some(&Value::Null) {
        return Err(throw(INVALID));
    }
    Ok(json!({
        "content": content, "truncated": truncated, "sizeBytes": size, "lineCount": lines,
        "expectedBase": expected_base,
    }))
}

fn image_chunk(value: Option<&Value>) -> Outcome {
    const INVALID: &str = "The Project source returned an invalid image chunk";
    let result = parse_remote_object(value, INVALID)?;
    let mime = js_string(result.get("mime_type"));
    let size = number(&result, "size_bytes").filter(|n| *n > 0.0 && *n <= MAX_IMAGE_BYTES);
    let valid = base64(&result)
        && IMAGE_TYPES.contains(&mime.as_str())
        && size.is_some_and(|size| {
            number(&result, "offset").is_some_and(|offset| offset >= 0.0 && offset < size && offset % CHUNK_BYTES == 0.0)
        })
        && hex(&result, "content_hash");
    if !valid {
        return Err(throw(INVALID));
    }
    Ok(Value::Object(result))
}

fn file_chunk(value: Option<&Value>) -> Outcome {
    const INVALID: &str = "The Project source returned an invalid file chunk";
    let result = parse_remote_object(value, INVALID)?;
    let size = number(&result, "size_bytes").filter(|n| *n >= 0.0);
    let valid = base64(&result)
        && size.is_some_and(|size| {
            number(&result, "offset").is_some_and(|offset| {
                offset >= 0.0 && !(size > 0.0 && offset >= size) && offset % CHUNK_BYTES == 0.0
            })
        })
        && hex(&result, "file_identity")
        && hex(&result, "chunk_hash");
    if !valid {
        return Err(throw(INVALID));
    }
    Ok(Value::Object(result))
}

/// `projectRemoteNormalize`: shape check of a `read_text` / `read_image_chunk` / `read_file_chunk` result.
pub(super) fn normalize(input: &Value) -> Outcome {
    let value = input.get("value");
    let result = match input.get("operation").and_then(Value::as_str) {
        Some("read_text") => text_result(value)?,
        Some("read_image_chunk") => image_chunk(value)?,
        Some("read_file_chunk") => file_chunk(value)?,
        _ => return Err(throw("The Project source operation has no result check")),
    };
    Ok(json!({ "result": result }))
}
