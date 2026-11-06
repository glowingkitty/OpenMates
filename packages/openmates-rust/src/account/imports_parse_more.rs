//! OpenCode, OpenMates Export V1 and generic role/content import parsers.
use super::*;
use serde_json::{Value, json};

/// Filtered OpenCode transcript (`opencode export` session JSON).
pub fn parse_opencode_import(
    text: &str,
    source_name: &str,
    selected: ImportSource,
) -> Result<ParsedAccountImport, String> {
    parse_opencode_value(
        &decode(text, "OpenCode transcript export")?,
        source_name,
        selected,
    )
}
/// [`parse_opencode_import`] over an already decoded transcript.
pub fn parse_opencode_value(
    record: &Value,
    source_name: &str,
    selected: ImportSource,
) -> Result<ParsedAccountImport, String> {
    if !record.is_object() {
        return Err("OpenCode transcript export must be an object".into());
    }
    let info = record.get("info").filter(|v| is_js_object(v));
    let raw_messages = record.get("messages").and_then(Value::as_array);
    let source_chat_id = js_string(info.and_then(|i| i.get("id")), "");
    let (Some(info), Some(raw_messages)) = (info, raw_messages) else {
        return Err("OpenCode transcript export is missing info.id or messages".into());
    };
    if source_chat_id.is_empty() {
        return Err("OpenCode transcript export is missing info.id or messages".into());
    }
    let mut messages = vec![];
    for item in raw_messages.iter().filter(|v| is_js_object(v)) {
        let message_info = item
            .get("info")
            .filter(|v| is_js_object(v))
            .cloned()
            .unwrap_or(json!({}));
        let role = js_string(message_info.get("role"), "");
        if role != "user" && role != "assistant" {
            continue;
        }
        let parts = js_objects(item.get("parts"));
        let texts: Vec<&str> = parts
            .iter()
            .filter(|p| {
                p.get("type").and_then(Value::as_str) == Some("text")
                    && p.get("ignored") != Some(&Value::Bool(true))
            })
            .filter_map(|p| p.get("text").and_then(Value::as_str))
            .collect();
        let content = texts
            .iter()
            .filter(|t| !js_blank(t))
            .copied()
            .collect::<Vec<_>>()
            .join("\n");
        if js_blank(&content) {
            continue;
        }
        let time = message_info
            .get("time")
            .filter(|v| is_js_object(v))
            .cloned()
            .unwrap_or(json!({}));
        messages.push(message(
            &role,
            content,
            positive_time(time.get("created"), 1.0)?,
            string_field(&message_info, "id"),
            json!({
                "part_types": parts.iter().map(|p| js_string(p.get("type"), "unknown")).collect::<Vec<_>>(),
                "text_part_count": texts.len(),
            }),
        ));
    }
    let time = info
        .get("time")
        .filter(|v| is_js_object(v))
        .cloned()
        .unwrap_or(json!({}));
    let count = messages.len();
    let parsed = chat(
        ImportParser::OpenCode,
        selected,
        source_chat_id,
        string_field(info, "title"),
        positive_time(time.get("created"), 1.0)?,
        positive_time(time.get("updated"), 1.0)?,
        messages,
        vec![],
        vec!["opencode".into()],
        json!({"source_name": source_name, "message_count": count}),
    );
    Ok(finalize(
        ImportParser::OpenCode,
        selected,
        vec![parsed],
        vec![],
    ))
}

fn manifest_domains(manifest: &str) -> Vec<String> {
    let entry = regex::Regex::new(r"^\s{2}([a-zA-Z0-9_-]+):").expect("static pattern");
    let mut domains = vec![];
    let mut inside = false;
    for line in manifest
        .split('\n')
        .map(|l| l.strip_suffix('\r').unwrap_or(l))
    {
        if line.starts_with("domains:") && line["domains:".len()..].trim().is_empty() {
            inside = true;
            continue;
        }
        if inside && line.chars().next().is_some_and(|c| !c.is_whitespace()) {
            break;
        }
        if inside && let Some(m) = entry.captures(line) {
            domains.push(m[1].to_owned());
        }
    }
    domains
}

/// OpenMates Export V1 archive, given its `manifest.yml` text and entry names
/// in archive order. Only chat YAML entries become (empty) import chats.
pub fn parse_openmates_import(
    manifest: Option<&str>,
    entry_names: &[String],
    source_name: &str,
    selected: ImportSource,
) -> Result<ParsedAccountImport, String> {
    let manifest = manifest.ok_or("OpenMates Export V1 archive is missing manifest.yml")?;
    let format = regex::Regex::new(r"format:\s*openmates-account-export").expect("static pattern");
    let version = regex::Regex::new(r#"version:\s*["']?1["']?"#).expect("static pattern");
    if !format.is_match(manifest) || !version.is_match(manifest) {
        return Err("Unsupported OpenMates Export V1 archive format or version".into());
    }
    let mut skipped: Vec<String> = manifest_domains(manifest)
        .into_iter()
        .filter(|d| !["chats", "embeds", "uploads", "referenced_uploads"].contains(&d.as_str()))
        .collect();
    skipped.sort();
    let chats: Vec<_> = entry_names
        .iter()
        .filter(|name| {
            name.starts_with("chats/") && (name.ends_with(".yml") || name.ends_with(".yaml"))
        })
        .map(|name| {
            let last = name.rsplit('/').next().unwrap_or("");
            let stem = last
                .strip_suffix(".yaml")
                .or_else(|| last.strip_suffix(".yml"))
                .unwrap_or(last);
            let id = if stem.is_empty() {
                name.clone()
            } else {
                stem.to_owned()
            };
            chat(
                ImportParser::OpenMates,
                selected,
                id.clone(),
                Some(id),
                None,
                None,
                vec![],
                vec![],
                vec!["openmates".into()],
                json!({"source_name": source_name, "archive_path": name}),
            )
        })
        .collect();
    if chats.is_empty() {
        return Err("OpenMates Export V1 archive contains no chat YAML files".into());
    }
    Ok(finalize(ImportParser::OpenMates, selected, chats, skipped))
}

/// Strict role/content JSON imported as Gemini or Other.
pub fn parse_generic_import(
    text: &str,
    source_name: &str,
    selected: ImportSource,
) -> Result<ParsedAccountImport, String> {
    if !matches!(selected, ImportSource::Gemini | ImportSource::Other) {
        return Err("Generic account import requires --source gemini or --source other.".into());
    }
    let decoded = decode(text, "Generic role/content transcript")?;
    let raw_chats = match &decoded {
        Value::Array(items) => items.clone(),
        other => vec![other.clone()],
    };
    if raw_chats.is_empty()
        || raw_chats
            .iter()
            .any(|c| !c.is_object() || !c.get("messages").is_some_and(Value::is_array))
    {
        return Err("Generic role/content transcript must be a chat object or array of chat objects with messages arrays".into());
    }
    let mut chats = vec![];
    for (chat_index, raw) in raw_chats.iter().enumerate() {
        let object = raw.as_object().expect("checked object");
        let unknown: Vec<&str> = object
            .keys()
            .map(String::as_str)
            .filter(|k| !["id", "title", "created_at", "updated_at", "messages"].contains(k))
            .collect();
        if !unknown.is_empty() {
            return Err(format!(
                "Generic role/content transcript contains unknown chat fields: {}",
                unknown.join(", ")
            ));
        }
        let raw_messages = object["messages"].as_array().expect("checked array");
        if raw_messages.is_empty() {
            return Err("Generic role/content transcript messages must not be empty".into());
        }
        let mut messages = vec![];
        for (index, raw_message) in raw_messages.iter().enumerate() {
            let n = index + 1;
            let item = raw_message
                .as_object()
                .ok_or_else(|| format!("Generic role/content message {n} must be an object"))?;
            let unknown: Vec<&str> = item
                .keys()
                .map(String::as_str)
                .filter(|k| !["id", "role", "content", "created_at"].contains(k))
                .collect();
            if !unknown.is_empty() {
                return Err(format!(
                    "Generic role/content message {n} contains unknown fields: {}",
                    unknown.join(", ")
                ));
            }
            if !item.contains_key("role") || !item.contains_key("content") {
                return Err(format!(
                    "Generic role/content message {n} requires role and content"
                ));
            }
            let role = item["role"]
                .as_str()
                .filter(|r| matches!(*r, "user" | "assistant" | "system"));
            let Some(role) = role else {
                return Err(format!(
                    "Generic role/content message {n} has unsupported role"
                ));
            };
            let content = item["content"].as_str().filter(|c| !c.trim().is_empty());
            let Some(content) = content else {
                return Err(format!(
                    "Generic role/content message {n} requires non-empty string content"
                ));
            };
            messages.push(message(
                role,
                content.into(),
                string_field(raw_message, "created_at"),
                string_field(raw_message, "id"),
                json!({}),
            ));
        }
        let id = string_field(raw, "id")
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| format!("generic-chat-{}", chat_index + 1));
        let count = messages.len();
        let mut parsed = chat(
            ImportParser::Generic,
            selected,
            id,
            string_field(raw, "title"),
            string_field(raw, "created_at"),
            string_field(raw, "updated_at"),
            messages,
            vec![],
            vec![selected.as_str().into(), "generic".into()],
            json!({"source_name": source_name, "message_count": count}),
        );
        parsed.provider = selected.as_str().into();
        chats.push(parsed);
    }
    Ok(finalize(ImportParser::Generic, selected, chats, vec![]))
}
