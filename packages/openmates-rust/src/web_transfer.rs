//! Web chat import/export (Settings -> Account -> Import, chat downloads) on the
//! shared Rust core Worker `transfer` unit.
//!
//! Import parsing and normalization reuse the CLI's Account Import V1 parsers
//! (`account::imports_parse`) so every client produces the same chats and
//! source fingerprints; this module adds only what the web service decides
//! differently: file and archive routing, provider auto-detection, the strict
//! web role/content transcript, OpenMates Export V1 archives whose YAML the page
//! already parsed, newest-first ordering, the web error wording and the cost
//! estimate inputs. The page keeps the file picker, JSZip, YAML text parsing,
//! Fetch, encryption and IndexedDB. Every entry point takes and returns JSON
//! text so the browser binding is a thin pass-through. Chat export (filename,
//! timestamp, PII restore and YAML building) lives in `web_transfer_export.rs`.
use crate::account::imports_parse::{
    ImportParser, ImportSource, ParsedAccountImport, ParsedImportChat, js_blank,
};
use serde_json::{Value, json};

#[path = "web_transfer_import.rs"]
mod import;
pub use import::{
    import_route_json, openmates_manifest_json, parse_json_import_json,
    parse_openmates_archive_json, zip_plan_json,
};

#[path = "web_transfer_yaml.rs"]
mod yaml;
#[path = "web_transfer_export.rs"]
mod export;
pub use export::{export_draft_kind_json, export_filename_json, export_yaml_json};

#[cfg(test)]
#[path = "web_transfer_tests.rs"]
mod tests;
#[cfg(test)]
#[path = "web_transfer_export_tests.rs"]
mod export_tests;

/// `Math.max(1, Math.ceil(content.length / 4))` over non-blank messages, per chat.
pub fn chat_estimate(chat: &ParsedImportChat) -> (u64, u64) {
    let mut tokens = 0u64;
    let mut messages = 0u64;
    for message in &chat.messages {
        if js_blank(&message.content) {
            continue;
        }
        let units = message.content.encode_utf16().count() as u64;
        tokens += units.div_ceil(4).max(1);
        messages += 1;
    }
    (tokens, messages)
}

fn file_type(parser: ImportParser, zip_container: bool) -> &'static str {
    match (parser, zip_container) {
        (ImportParser::Claude, false) => "claude-json",
        (ImportParser::Claude, true) => "claude-zip",
        (ImportParser::ChatGpt, false) => "chatgpt-json",
        (ImportParser::ChatGpt, true) => "chatgpt-zip",
        (ImportParser::OpenCode, _) => "opencode-json",
        (ImportParser::OpenMates, _) => "openmates-zip",
        (ImportParser::Generic, _) => "generic-json",
    }
}

/// The web `ParsedAccountImport` plus per-chat `[tokens, messages]` estimates.
/// Assistant identities carry no avatar key on the web.
fn web_result(parsed: ParsedAccountImport, zip_container: bool) -> Value {
    let estimates: Vec<Value> = parsed
        .chats
        .iter()
        .map(|chat| {
            let (tokens, messages) = chat_estimate(chat);
            json!([tokens, messages])
        })
        .collect();
    let mut chats = serde_json::to_value(&parsed.chats).expect("parsed chats serialize");
    for chat in chats.as_array_mut().into_iter().flatten() {
        for message in chat["messages"].as_array_mut().into_iter().flatten() {
            if let Some(identity) = message
                .get_mut("imported_assistant_identity")
                .and_then(Value::as_object_mut)
            {
                identity.remove("avatar_key");
            }
        }
    }
    json!({
        "kind": "ok",
        "parsed": {
            "source": parsed.source.as_str(),
            "parserFormat": parsed.parser_format.as_str(),
            "fileType": file_type(parsed.parser_format, zip_container),
            "chats": chats,
            "skippedDomains": parsed.skipped_domains,
        },
        "estimates": estimates,
    })
}

fn error(message: impl Into<String>) -> Value {
    json!({"kind": "error", "message": message.into()})
}

/// `selectedSource` as sent by the page: absent/empty means "use the detected source".
fn selected_source(value: &Value) -> Result<Option<ImportSource>, String> {
    match value {
        Value::Null => Ok(None),
        Value::String(s) if s.is_empty() => Ok(None),
        Value::String(s) => ImportSource::parse(s)
            .map(Some)
            .ok_or_else(|| "protocol".to_string()),
        _ => Err("protocol".into()),
    }
}

/// Scan batch descriptors (`buildMessageBatches`) as `[chatIndex, chunkIndex,
/// start, end, batchId]`; the page slices its own chat objects.
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn batch_plan_json(input: &str) -> Result<String, String> {
    let input: Value = serde_json::from_str(input).map_err(|_| "protocol".to_string())?;
    let max = input["maxMessages"].as_f64().ok_or("protocol")?;
    if max.fract() != 0.0 || max <= 0.0 {
        return Ok(error("Import message batch size must be positive.").to_string());
    }
    let max = max as usize;
    let mut out = vec![];
    for (chat_index, chat) in input["chats"]
        .as_array()
        .ok_or("protocol")?
        .iter()
        .enumerate()
    {
        let fingerprint = chat["fingerprint"].as_str().ok_or("protocol")?;
        let count = chat["messageCount"].as_u64().ok_or("protocol")? as usize;
        // Fingerprints are hex, so 16 chars equal JavaScript's 16 UTF-16 units.
        let prefix: String = fingerprint.chars().take(16).collect();
        for chunk_index in 0..count.div_ceil(max).max(1) {
            let start = (chunk_index * max).min(count);
            let end = ((chunk_index + 1) * max).min(count);
            out.push(json!([
                chat_index,
                chunk_index,
                start,
                end,
                format!("scan-{prefix}-{chunk_index}")
            ]));
        }
    }
    Ok(json!({"kind": "ok", "batches": out}).to_string())
}
