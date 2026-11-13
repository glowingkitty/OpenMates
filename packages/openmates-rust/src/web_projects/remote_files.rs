//! Connected-source file decisions for the web page: preview classification, the
//! bounded virtual preview, the explicit upload plan and the virtual fullscreen detail.
//! Shared core part of `web_projects`.
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//! Mirrors `projectState/remoteFilePolicy.ts`. The CLI table in `work/projects/remote_files.rs`
//! words its messages differently, so this web table stays separate.

use super::js::{
    TableHit, is_integer, js_string, len16, nullish_or, opt_prop, prop, put, req_str, slice16, spread,
    strict_eq, table_get, to_number, trim, truthy,
};
use super::{Fault, Outcome, throw};
use regex::Regex;
use serde_json::{Map, Value, json};
use std::sync::LazyLock;

const MAX_SNIPPET_CHARS: usize = 20_000;
const MAX_FIELD_CHARS: usize = 1_024;
const MAX_POLICY_CHARS: usize = 128;
const MAX_SAFETY_FLAGS: f64 = 20.0;
const MAX_UPLOAD_FILENAME_CHARS: i64 = 180;

static HEX64: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[a-f0-9]{64}$").expect("static pattern compiles"));

const LANGUAGE_BY_EXTENSION: &[(&str, &str)] = &[
    ("c", "c"), ("cjs", "javascript"), ("cpp", "cpp"), ("css", "css"), ("entitlements", "entitlements"), ("go", "go"),
    ("gradle", "gradle"), ("h", "c"), ("hpp", "cpp"), ("html", "html"), ("java", "java"), ("js", "javascript"),
    ("jsx", "javascript"), ("kt", "kotlin"), ("mjs", "javascript"), ("php", "php"), ("plist", "plist"),
    ("py", "python"), ("rb", "ruby"), ("rs", "rust"), ("sh", "bash"), ("sql", "sql"), ("svelte", "svelte"),
    ("swift", "swift"), ("toml", "toml"), ("ts", "typescript"), ("tsx", "typescript"), ("xml", "xml"),
    ("yaml", "yaml"), ("yml", "yaml"),
];
const BINARY_EXTENSIONS: [&str; 35] = [
    "7z", "avi", "bin", "bmp", "dmg", "doc", "docx", "dylib", "exe", "gif", "gz", "ico", "jar", "jpeg", "jpg", "mov",
    "mp3", "mp4", "odt", "pdf", "png", "ppt", "pptx", "rar", "so", "tar", "ttf", "wasm", "webm", "webp", "woff",
    "woff2", "xls", "xlsx", "zip",
];

/// `classifyRemotePreviewPath`.
pub(super) fn classify(input: &Value) -> Outcome {
    let path = req_str(input.get("path"), "path")?;
    let name = path.replace('\\', "/").rsplit('/').next().unwrap_or("").to_lowercase();
    let extension = if name.contains('.') { name.rsplit('.').next().unwrap_or("") } else { "" };
    let kind = |kind: &str, language: &str| json!({ "kind": kind, "language": language });
    Ok(match extension {
        "md" | "mdx" => kind("markdown", "markdown"),
        "json" | "jsonl" => kind("json", "json"),
        "txt" | "log" | "csv" => kind("text", "text"),
        _ if name == "dockerfile" => kind("code", "dockerfile"),
        _ if name == "makefile" => kind("code", "makefile"),
        _ => match table_get(LANGUAGE_BY_EXTENSION, extension) {
            // `if (language)`: an `Object.prototype` member is truthy too; JSON then drops a
            // function and prints the prototype as `{}`.
            TableHit::Missing => {
                if BINARY_EXTENSIONS.contains(&extension) {
                    json!({ "kind": "unsupported", "language": "text", "reason": "This file type does not have a text preview" })
                } else {
                    kind("text", "text")
                }
            }
            hit => {
                let mut out = Map::new();
                out.insert("kind".into(), json!("code"));
                put(&mut out, "language", hit.json().as_ref());
                Value::Object(out)
            }
        },
    })
}

/// `value.length > max` for any JS value (strings count UTF-16 units, arrays elements,
/// objects their own `length` field, other primitives have no length).
fn length_exceeds(value: &Value, max: usize) -> bool {
    match value {
        Value::String(text) => len16(text) > max,
        Value::Array(items) => items.len() > max,
        Value::Object(map) => to_number(map.get("length")) > max as f64,
        _ => false,
    }
}

/// `assertNonEmptyBoundedString`.
fn non_empty_bounded(value: Option<&Value>, field: &str, max: usize) -> Result<(), Fault> {
    if !truthy(value) || value.is_some_and(|v| length_exceeds(v, max)) {
        return Err(Fault::Throw(format!("Remote preview {field} is missing or exceeds the bounded metadata limit")));
    }
    Ok(())
}

/// `assertBoundedString` (a `null` value is a TypeError in TS: malformed input).
fn bounded(value: Option<&Value>, field: &str, max: usize) -> Result<(), Fault> {
    match value {
        None => Ok(()),
        Some(Value::Null) => Err(Fault::Malformed(format!("null_field:{field}"))),
        Some(v) if length_exceeds(v, max) => {
            Err(Fault::Throw(format!("Remote preview {field} exceeds the bounded metadata limit")))
        }
        Some(_) => Ok(()),
    }
}

fn non_negative_integer(value: Option<&Value>, field: &str) -> Result<(), Fault> {
    if value.is_some() && (!is_integer(value) || value.and_then(Value::as_f64).is_some_and(|n| n < 0.0)) {
        return Err(Fault::Throw(format!("Remote preview {field} must be a non-negative integer")));
    }
    Ok(())
}

fn validate(input: &Value) -> Result<(), Fault> {
    non_empty_bounded(input.get("sourceId"), "sourceId", MAX_FIELD_CHARS)?;
    non_empty_bounded(input.get("path"), "path", MAX_FIELD_CHARS)?;
    non_empty_bounded(input.get("displayName"), "displayName", MAX_FIELD_CHARS)?;
    bounded(input.get("remoteItemId"), "remoteItemId", MAX_FIELD_CHARS)?;
    bounded(input.get("language"), "language", MAX_POLICY_CHARS)?;
    bounded(input.get("baseHash"), "baseHash", MAX_FIELD_CHARS)?;
    bounded(input.get("mtime"), "mtime", MAX_POLICY_CHARS)?;
    bounded(input.get("contentHash"), "contentHash", MAX_FIELD_CHARS)?;
    bounded(input.get("gitStatus"), "gitStatus", MAX_POLICY_CHARS)?;
    bounded(input.get("previewPolicy"), "previewPolicy", MAX_POLICY_CHARS)?;
    match input.get("snippet") {
        None | Some(Value::Null) => return Err(Fault::Malformed("bad_field:snippet".to_owned())),
        Some(snippet) if length_exceeds(snippet, MAX_SNIPPET_CHARS) => {
            return Err(throw("Remote preview snippet exceeds the bounded preview limit"));
        }
        Some(_) => {}
    }
    non_negative_integer(input.get("sizeBytes"), "sizeBytes")?;
    non_negative_integer(input.get("lineCount"), "lineCount")?;
    let flags = input.get("safetyFlags");
    // `(input.safetyFlags?.length ?? 0) > 20`
    let count = match flags {
        Some(Value::String(text)) => len16(text) as f64,
        Some(Value::Array(items)) => items.len() as f64,
        Some(Value::Object(map)) => match map.get("length") {
            None | Some(Value::Null) => 0.0,
            length => to_number(length),
        },
        _ => 0.0,
    };
    if count > MAX_SAFETY_FLAGS {
        return Err(throw("Remote preview safety flags exceed the bounded metadata limit"));
    }
    match flags {
        None | Some(Value::Null) => {}
        Some(Value::Array(items)) => {
            for flag in items {
                non_empty_bounded(Some(flag), "safetyFlag", MAX_POLICY_CHARS)?;
            }
        }
        // A string iterates as non-empty one-character strings, which always pass.
        Some(Value::String(_)) => {}
        Some(_) => return Err(Fault::Malformed("safety_flags_not_iterable".to_owned())),
    }
    Ok(())
}

/// `remote:${source}:${path}` with JS template conversion.
fn content_ref(source: Option<&Value>, path: Option<&Value>) -> String {
    format!("remote:{}:{}", js_string(source), js_string(path))
}

/// `projectRemotePreview` (`normalizeRemoteFilePreview`): the bounded message-local virtual preview.
pub(super) fn preview(input: &Value) -> Outcome {
    validate(input)?;
    let get = |name: &str| input.get(name);
    let mut content = Map::new();
    content.insert("type".into(), json!("remote_file_preview"));
    put(&mut content, "source_id", get("sourceId"));
    put(&mut content, "path", get("path"));
    put(&mut content, "display_name", get("displayName"));
    if truthy(get("remoteItemId")) {
        put(&mut content, "remote_item_id", get("remoteItemId"));
    }
    content.insert("kind".into(), nullish_or(get("kind"), &json!("file")).clone());
    content.insert("language".into(), nullish_or(get("language"), &json!("text")).clone());
    put(&mut content, "snippet", get("snippet"));
    content.insert("snippet_truncated".into(), json!(get("snippetTruncated") == Some(&Value::Bool(true))));
    if truthy(get("baseHash")) {
        put(&mut content, "base_hash", get("baseHash"));
    }
    put(&mut content, "size_bytes", get("sizeBytes"));
    put(&mut content, "line_count", get("lineCount"));
    for (from, to) in [("mtime", "mtime"), ("contentHash", "content_hash"), ("gitStatus", "git_status"), ("previewPolicy", "preview_policy")] {
        if truthy(get(from)) {
            put(&mut content, to, get(from));
        }
    }
    content.insert("safety_flags".into(), nullish_or(get("safetyFlags"), &json!([])).clone());
    Ok(json!({
        "isVirtual": true,
        "persistAsEmbed": false,
        "embed": {
            "embed_id": content_ref(get("sourceId"), get("path")),
            "type": "code-code",
            "status": "finished",
            "content": content,
        },
    }))
}

fn is_blocked_char(c: char) -> bool {
    let code = c as u32;
    code < 32 || code == 127 || (0x202A..=0x202E).contains(&code) || (0x2066..=0x2069).contains(&code) || "<>:\"/\\|?*".contains(c)
}

/// `safeUploadFileName`: last path segment without control, bidi or reserved characters.
fn safe_upload_file_name(display_name: &str) -> String {
    let replaced = display_name.replace('\\', "/");
    let basename = replaced.split('/').filter(|part| !part.is_empty()).next_back().unwrap_or("remote-file.txt");
    let sanitized: String = basename.chars().map(|c| if is_blocked_char(c) { '_' } else { c }).collect();
    let sanitized = trim(&sanitized);
    if sanitized.is_empty() || sanitized == "." || sanitized == ".." {
        return "remote-file.txt".to_owned();
    }
    slice16(sanitized, 0, Some(MAX_UPLOAD_FILENAME_CHARS))
}

/// `projectRemoteUploadPlan` (`remoteFileUploadPlan`): name, MIME type and provenance of an explicit import.
pub(super) fn upload_plan(input: &Value) -> Outcome {
    let content = prop(prop(input.get("preview"), "embed")?, "content")?;
    let read = input.get("readResult");
    let expected = prop(read, "expectedBase")?;
    if truthy(prop(read, "truncated")?) || !truthy(expected) || !HEX64.is_match(&js_string(expected)) {
        return Err(throw("Remote file import requires complete, non-truncated content"));
    }
    let field = |name: &str| prop(content, name);
    let matches_read = strict_eq(field("base_hash")?, expected);
    let display_name = req_str(field("display_name")?, "display_name")?;
    let language = field("language")?;
    let mime = if truthy(language) { format!("text/x-{}", js_string(language)) } else { "text/plain".to_owned() };
    let mut metadata = Map::new();
    put(&mut metadata, "source_id", field("source_id")?);
    put(&mut metadata, "remote_path", field("path")?);
    put(&mut metadata, "remote_base_hash", expected);
    for (from, to) in [("content_hash", "remote_content_hash"), ("mtime", "remote_mtime"), ("git_status", "remote_git_status")] {
        if matches_read && truthy(field(from)?) {
            put(&mut metadata, to, field(from)?);
        }
    }
    put(&mut metadata, "safety_flags", field("safety_flags")?);
    metadata.insert("imported_from_remote_source".into(), json!(true));
    Ok(json!({ "fileName": safe_upload_file_name(display_name), "mimeType": mime, "metadata": metadata }))
}

/// `projectRemoteFullscreen` (`buildVirtualRemoteFullscreenDetail`).
pub(super) fn fullscreen(input: &Value) -> Outcome {
    let embed = prop(input.get("preview"), "embed")?;
    let content = prop(embed, "content")?;
    let reference = content_ref(prop(content, "source_id")?, prop(content, "path")?);
    let mut embed_data = spread(embed);
    embed_data.insert("app_id".into(), json!("code"));
    embed_data.insert("skill_id".into(), json!("code"));
    let mut decoded = spread(content);
    decoded.insert("app_id".into(), json!("code"));
    decoded.insert("skill_id".into(), json!("code"));
    match input.get("fullContent") {
        Some(full) => {
            decoded.insert("code".into(), full.clone());
        }
        None => {
            decoded.remove("code");
        }
    }
    match opt_prop(content, "display_name") {
        Some(name) => {
            decoded.insert("filename".into(), name.clone());
        }
        None => {
            decoded.remove("filename");
        }
    }
    let mut out = Map::new();
    put(&mut out, "embedId", prop(embed, "embed_id")?);
    out.insert("embedData".into(), Value::Object(embed_data));
    out.insert("decodedContent".into(), Value::Object(decoded));
    out.insert("embedType".into(), json!("code-code"));
    out.insert("attrs".into(), json!({ "type": "code-code", "contentRef": reference, "status": "finished", "virtual": true }));
    Ok(Value::Object(out))
}
