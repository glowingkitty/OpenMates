//! Web Account Import V1 routing and parsing (port of the parse half of
//! `frontend/packages/ui/src/services/chatImportService.ts`). Claude, ChatGPT and
//! OpenCode exports go through the shared CLI parsers; the strict web
//! role/content transcript and OpenMates Export V1 archives (YAML parsed by the
//! page) are web-only shapes. Errors keep the web service's exact wording.
//! Parity: `web_transfer_ts_vectors.json` (generated from the TypeScript service).
use super::{error, selected_source, web_result};
use crate::account::imports_parse::{
    ImportParser, ImportSource, ParsedAccountImport, ParsedImportChat, ParsedImportMessage,
    ParsedImportUpload, finalize, is_js_object, js_blank, js_objects, js_string,
    parse_chatgpt_value, parse_claude_value, parse_opencode_value, source_fingerprint_for,
    string_field,
};
use crate::client::overview::parse_time;
use serde_json::{Value, json};
use std::collections::BTreeMap;

fn protocol<E>(_: E) -> String {
    "protocol".into()
}
fn input(text: &str) -> Result<Value, String> {
    serde_json::from_str(text).map_err(protocol)
}
fn text_field<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value[key].as_str().ok_or_else(|| "protocol".into())
}
fn offset(value: &Value) -> Result<i32, String> {
    value["utcOffsetMinutes"]
        .as_i64()
        .and_then(|v| i32::try_from(v).ok())
        .ok_or_else(|| "protocol".into())
}

/// The shared parsers' messages in the web service's wording (the CLI keeps
/// its own unpunctuated text).
fn web_error(message: String) -> String {
    let mapped = match message.as_str() {
        "Claude export conversations must be an array" => {
            "Claude export conversations must be an array."
        }
        "Claude conversation is missing uuid" => "Claude conversation is missing uuid.",
        "ChatGPT export conversations must be an array" => {
            "ChatGPT export conversations must be an array."
        }
        "ChatGPT conversation is missing id" => "ChatGPT conversation is missing id.",
        "ChatGPT conversation is missing mapping" => {
            "ChatGPT export conversation is missing mapping."
        }
        "OpenCode transcript export must be an object" => {
            "OpenCode transcript export must be an object."
        }
        "OpenCode transcript export is missing info.id or messages" => {
            "OpenCode transcript export is missing info.id or messages."
        }
        _ => return message,
    };
    mapped.into()
}

/// `Date.parse` for the ISO shapes exports carry; anything else sorts as 0
/// like JavaScript's `NaN` branch.
fn date_ms(value: Option<&str>, utc_offset_minutes: i32) -> f64 {
    value
        .and_then(|v| parse_time(Some(&Value::String(v.into())), utc_offset_minutes))
        .map_or(0.0, |ms| ms as f64)
}

/// `newestFirst`: stable sort by `updated_at ?? created_at`, newest first.
fn newest_first(parsed: &mut ParsedAccountImport, utc_offset_minutes: i32) {
    let key = |chat: &ParsedImportChat| {
        date_ms(
            chat.updated_at.as_deref().or(chat.created_at.as_deref()),
            utc_offset_minutes,
        )
    };
    parsed.chats.sort_by(|l, r| key(r).total_cmp(&key(l)));
}

/// File routing of `parseImportFile`: `.json` text or a `.zip` archive.
///
/// # Errors
/// `protocol` when the input is not `{fileName}`.
pub fn import_route_json(input_text: &str) -> Result<String, String> {
    let request = input(input_text)?;
    let name = text_field(&request, "fileName")?.to_lowercase();
    let out = if name.ends_with(".json") {
        json!({"kind": "json"})
    } else if name.ends_with(".zip") {
        json!({"kind": "zip"})
    } else {
        error(
            "Unsupported import file. Choose a Claude/ChatGPT/OpenCode export .zip/.json file or an OpenMates Export V1 .zip archive.",
        )
    };
    Ok(out.to_string())
}

/// `providerConversationSource`: OpenCode transcript, or the first export
/// conversation's keys decide ChatGPT vs Claude (`None` falls back to Claude).
fn detect(raw: &Value) -> Option<ImportParser> {
    if raw.is_object()
        && raw.get("info").is_some_and(|i| is_js_object(i))
        && raw.get("messages").is_some_and(Value::is_array)
    {
        return Some(ImportParser::OpenCode);
    }
    let conversations = raw
        .as_array()
        .or_else(|| raw.get("conversations").and_then(Value::as_array))?;
    let first = conversations
        .iter()
        .find(|v| is_js_object(v))?
        .as_object()?;
    if ["mapping", "conversation_id", "current_node"]
        .iter()
        .any(|k| first.contains_key(*k))
    {
        return Some(ImportParser::ChatGpt);
    }
    if ["chat_messages", "uuid"]
        .iter()
        .any(|k| first.contains_key(*k))
    {
        return Some(ImportParser::Claude);
    }
    None
}

/// Parses a `.json` import file or a ZIP's `conversations.json` text (passed
/// separately so the page never re-encodes the export inside a JSON envelope).
///
/// Answers `{kind:"ok",parsed,estimates}`, `{kind:"error",message}` or
/// `{kind:"syntax"}` (the page rethrows its own `JSON.parse` error so the
/// message stays the browser's).
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn parse_json_import_json(input_text: &str, text: &str) -> Result<String, String> {
    let request = input(input_text)?;
    let name = text_field(&request, "fileName")?;
    let zip = match text_field(&request, "container")? {
        "json" => false,
        "zip" => true,
        _ => return Err("protocol".into()),
    };
    let selected = selected_source(&request["selectedSource"])?;
    let utc_offset = offset(&request)?;
    let Ok(raw) = serde_json::from_str::<Value>(text) else {
        return Ok(json!({"kind": "syntax"}).to_string());
    };
    let parsed = if !zip && matches!(selected, Some(ImportSource::Gemini | ImportSource::Other)) {
        parse_web_generic(&raw, selected.expect("matched above"), name)
    } else {
        match detect(&raw) {
            Some(ImportParser::ChatGpt) => {
                parse_chatgpt_value(&raw, name, selected.unwrap_or(ImportSource::ChatGpt)).map(
                    |mut p| {
                        newest_first(&mut p, utc_offset);
                        p
                    },
                )
            }
            Some(ImportParser::OpenCode) => {
                parse_opencode_value(&raw, name, selected.unwrap_or(ImportSource::OpenCode))
            }
            _ => parse_claude_value(&raw, name, selected.unwrap_or(ImportSource::Claude)).map(
                |mut p| {
                    newest_first(&mut p, utc_offset);
                    p
                },
            ),
        }
    };
    Ok(match parsed {
        Ok(parsed) => web_result(parsed, zip),
        Err(message) => error(web_error(message)),
    }
    .to_string())
}

/// `parseGenericTranscript`: one `{messages:[{role,content}]}` chat imported as
/// Gemini or Other. Metadata and `model` pass through; fingerprints hash `other`.
fn parse_web_generic(
    raw: &Value,
    selected: ImportSource,
    source_name: &str,
) -> Result<ParsedAccountImport, String> {
    let transcript = raw
        .as_object()
        .ok_or("Generic role/content JSON must be an object with a messages array.")?;
    let raw_messages = transcript.get("messages").and_then(Value::as_array).ok_or(
        "Gemini and Other require generic role/content JSON; raw Gemini Takeout exports are not supported yet.",
    )?;
    let mut messages = vec![];
    for (index, item) in raw_messages.iter().enumerate() {
        let n = index + 1;
        let message = item
            .as_object()
            .ok_or_else(|| format!("Generic message {n} must contain role and content."))?;
        let role = message
            .get("role")
            .and_then(Value::as_str)
            .filter(|r| matches!(*r, "user" | "assistant" | "system"));
        let (Some(role), Some(content)) = (role, message.get("content").and_then(Value::as_str))
        else {
            return Err(format!(
                "Generic message {n} must contain a valid role and content string."
            ));
        };
        let mut metadata = serde_json::Map::new();
        if let Some(model) = message.get("model").filter(|m| m.is_string()) {
            metadata.insert("model".into(), model.clone());
        }
        if let Some(extra) = message.get("metadata").and_then(Value::as_object) {
            metadata.extend(extra.clone());
        }
        messages.push(ParsedImportMessage {
            role: role.into(),
            content: content.into(),
            created_at: string_field(item, "created_at"),
            source_message_id: string_field(item, "id"),
            provider_metadata: Value::Object(metadata),
            imported_assistant_identity: None,
        });
    }
    if messages.is_empty() {
        return Err("Generic role/content JSON contains no messages.".into());
    }
    let source_chat_id = string_field(raw, "id")
        .filter(|id| !js_blank(id))
        .unwrap_or_else(|| format!("generic-{source_name}"));
    let count = messages.len();
    let chat = ParsedImportChat {
        provider: selected.as_str().into(),
        parser_format: ImportParser::Generic.as_str().into(),
        selected_source: selected.as_str().into(),
        source_fingerprint: source_fingerprint_for("other", &source_chat_id, &messages),
        source_chat_id,
        title: string_field(raw, "title"),
        created_at: string_field(raw, "created_at"),
        updated_at: string_field(raw, "updated_at"),
        messages,
        embeds: vec![],
        uploads: vec![],
        provider_labels: vec!["generic".into()],
        source_metadata: json!({"source_name": source_name, "message_count": count}),
    };
    Ok(finalize(
        ImportParser::Generic,
        selected,
        vec![chat],
        vec![],
    ))
}

fn is_yaml_name(name: &str) -> bool {
    let lower = name.to_ascii_lowercase();
    lower.ends_with(".yml") || lower.ends_with(".yaml")
}
fn strip_yaml(name: &str) -> &str {
    let lower = name.to_ascii_lowercase();
    let cut = if lower.ends_with(".yaml") {
        5
    } else if lower.ends_with(".yml") {
        4
    } else {
        0
    };
    &name[..name.len() - cut]
}
/// JavaScript default `Array.prototype.sort` (UTF-16 code unit order).
fn js_sort(names: &mut [String]) {
    names.sort_by(|a, b| a.encode_utf16().cmp(b.encode_utf16()));
}

/// ZIP routing: the first real `conversations.json` (macOS resource forks
/// skipped), else an OpenMates Export V1 archive with the YAML entries the page
/// must read (embeds and uploads in archive order, chats sorted).
///
/// # Errors
/// `protocol` when the input is not `{entries:[{name,dir}]}`.
pub fn zip_plan_json(input_text: &str) -> Result<String, String> {
    let request = input(input_text)?;
    let mut entries = vec![];
    for entry in request["entries"].as_array().ok_or("protocol")? {
        entries.push((
            text_field(entry, "name")?.to_owned(),
            entry["dir"].as_bool().ok_or("protocol")?,
        ));
    }
    let conversations = entries.iter().find(|(name, dir)| {
        !dir && !name.starts_with("__MACOSX/")
            && !name.contains("/._")
            && !name.starts_with("._")
            && name.rsplit('/').next() == Some("conversations.json")
    });
    if let Some((name, _)) = conversations {
        return Ok(json!({"kind": "conversations", "name": name}).to_string());
    }
    if !entries
        .iter()
        .any(|(name, dir)| !dir && name == "manifest.yml")
    {
        return Ok(error("Unsupported ZIP archive. Expected Claude/ChatGPT conversations.json or OpenMates Export V1 manifest.yml.").to_string());
    }
    let under = |prefix: &str| -> Vec<String> {
        entries
            .iter()
            .filter(|(name, dir)| !dir && name.starts_with(prefix) && is_yaml_name(name))
            .map(|(name, _)| name.clone())
            .collect()
    };
    let mut chats = under("chats/");
    js_sort(&mut chats);
    Ok(json!({"kind": "openmates", "embeds": under("embeds/"), "uploads": under("uploads/"), "chats": chats}).to_string())
}

fn manifest_valid(manifest: &Value) -> bool {
    manifest.get("format").and_then(Value::as_str) == Some("openmates-account-export")
        && manifest.is_object()
        && js_string(manifest.get("version"), "undefined") == "1"
}
const MANIFEST_ERROR: &str = "Unsupported OpenMates Export V1 archive format or version.";

/// Checks the parsed `manifest.yml` before the page reads any other entry.
///
/// # Errors
/// `protocol` when the input is not `{manifest}`.
pub fn openmates_manifest_json(input_text: &str) -> Result<String, String> {
    let request = input(input_text)?;
    Ok(if manifest_valid(&request["manifest"]) {
        json!({"kind": "ok"})
    } else {
        error(MANIFEST_ERROR)
    }
    .to_string())
}

/// `readYamlRecordsById`: objects keyed by `String(id)`; later entries win.
fn records_by_id(values: &[Value]) -> BTreeMap<String, &Value> {
    let mut out = BTreeMap::new();
    for value in values.iter().filter(|v| is_js_object(v)) {
        let id = js_string(value.get("id"), "");
        if !id.is_empty() {
            out.insert(id, value);
        }
    }
    out
}
/// JavaScript `String(value)` for an array element (`null` is `"null"`).
fn js_to_string(value: &Value) -> String {
    if value.is_null() {
        "null".into()
    } else {
        js_string(Some(value), "")
    }
}
fn non_null<'a>(record: Option<&&'a Value>, key: &str) -> Option<&'a Value> {
    record.and_then(|r| r.get(key)).filter(|v| !v.is_null())
}

/// `parseOpenMatesArchive` over YAML the page already parsed.
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn parse_openmates_archive_json(input_text: &str) -> Result<String, String> {
    let request = input(input_text)?;
    let source_name = text_field(&request, "fileName")?;
    let selected = selected_source(&request["selectedSource"])?.unwrap_or(ImportSource::OpenMates);
    let utc_offset = offset(&request)?;
    let manifest = &request["manifest"];
    if !manifest_valid(manifest) {
        return Ok(error(MANIFEST_ERROR).to_string());
    }
    let mut skipped: Vec<String> = match manifest.get("domains") {
        Some(Value::Object(map)) => map.keys().cloned().collect(),
        Some(Value::Array(items)) => (0..items.len()).map(|i| i.to_string()).collect(),
        _ => vec![],
    };
    skipped.retain(|d| !["chats", "embeds", "uploads", "referenced_uploads"].contains(&d.as_str()));
    js_sort(&mut skipped);
    let embeds = request["embeds"].as_array().ok_or("protocol")?;
    let uploads = request["uploads"].as_array().ok_or("protocol")?;
    let (embeds, uploads) = (records_by_id(embeds), records_by_id(uploads));
    let chat_entries = request["chats"].as_array().ok_or("protocol")?;
    if chat_entries.is_empty() {
        return Ok(error("OpenMates Export V1 archive contains no chat YAML files.").to_string());
    }
    let mut chats = vec![];
    for entry in chat_entries {
        let name = text_field(entry, "name")?;
        let data = &entry["value"];
        if !is_js_object(data) {
            continue;
        }
        let source_chat_id = match data.get("id").filter(|v| !v.is_null()) {
            Some(id) => js_string(Some(id), ""),
            None => strip_yaml(name).to_owned(),
        };
        if source_chat_id.is_empty() {
            return Ok(error("OpenMates chat YAML is missing id.").to_string());
        }
        let messages: Vec<ParsedImportMessage> = js_objects(data.get("messages"))
            .into_iter()
            .map(|m| {
                let role = js_string(m.get("role"), "user");
                ParsedImportMessage {
                    role: if role == "assistant" || role == "system" { role } else { "user".into() },
                    content: string_field(m, "content").unwrap_or_default(),
                    created_at: string_field(m, "created_at"),
                    source_message_id: string_field(m, "id"),
                    provider_metadata: json!({"embed_refs": m.get("embed_refs").filter(|v| v.is_array()).cloned().unwrap_or(json!([]))}),
                    imported_assistant_identity: None,
                }
            })
            .collect();
        let refs = |key: &str| -> Vec<String> {
            data.get(key)
                .and_then(Value::as_array)
                .map(|a| a.iter().map(js_to_string).collect())
                .unwrap_or_default()
        };
        let chat_embeds = refs("embed_refs")
            .into_iter()
            .map(|id| {
                let record = embeds.get(&id);
                json!({
                    "source_embed_id": id,
                    "type": non_null(record, "type").map_or("unknown".into(), |v| js_string(Some(v), "")),
                    "content": non_null(record, "content").cloned().unwrap_or(json!({})),
                    "referenced_upload_ids": non_null(record, "referenced_upload_ids").cloned().unwrap_or(json!([])),
                })
            })
            .collect();
        let chat_uploads = refs("upload_refs")
            .into_iter()
            .map(|id| {
                let record = uploads.get(&id);
                ParsedImportUpload {
                    file_name: non_null(record, "file_name")
                        .map_or(id.clone(), |v| js_string(Some(v), "")),
                    mime_type: non_null(record, "mime_type")
                        .and_then(Value::as_str)
                        .map(str::to_owned),
                    bytes: non_null(record, "bytes").filter(|v| v.is_number()).cloned(),
                    content_ref: non_null(record, "path")
                        .map_or(String::new(), |v| js_string(Some(v), "")),
                    source_upload_id: id,
                }
            })
            .collect();
        chats.push(ParsedImportChat {
            provider: "openmates".into(),
            parser_format: "openmates".into(),
            selected_source: selected.as_str().into(),
            source_fingerprint: source_fingerprint_for("openmates", &source_chat_id, &messages),
            source_chat_id,
            title: string_field(data, "title"),
            created_at: string_field(data, "created_at"),
            updated_at: string_field(data, "updated_at"),
            messages,
            embeds: chat_embeds,
            uploads: chat_uploads,
            provider_labels: vec!["openmates".into()],
            source_metadata: json!({"source_name": source_name, "archive_path": name}),
        });
    }
    let mut parsed = finalize(ImportParser::OpenMates, selected, chats, skipped);
    newest_first(&mut parsed, utc_offset);
    Ok(web_result(parsed, true).to_string())
}
