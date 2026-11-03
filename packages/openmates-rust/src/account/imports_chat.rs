//! `account import-chat` payload parsing (port of the npm CLI
//! `parseChatImportPayload`): a CLI chat export YAML file, or JSON holding a
//! `chats` array, a bare array, or a single chat/messages object.
use serde_json::{Map, Value, json};

/// Parse an import-chat file into the `{chats:[...]}` request payload.
pub fn parse_chat_import_payload(raw: &str) -> Result<Value, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err("Import file is empty.".into());
    }
    if trimmed.starts_with('{') || trimmed.starts_with('[') {
        let parsed: Value = serde_json::from_str(trimmed).map_err(|e| e.to_string())?;
        if parsed.is_array() {
            return Ok(json!({"chats": parsed}));
        }
        if parsed.get("chats").is_some_and(Value::is_array) {
            return Ok(parsed);
        }
        if parsed.is_object() && (truthy(parsed.get("chat")) || truthy(parsed.get("messages"))) {
            return Ok(json!({"chats": [normalize_chat(&parsed)]}));
        }
        return Err("JSON import must contain a chats array, a chat object, or messages.".into());
    }
    Ok(json!({"chats": [parse_cli_export_yaml(trimmed)?]}))
}

fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0 && !f.is_nan()),
        Some(Value::String(s)) => !s.is_empty(),
        Some(_) => true,
    }
}
fn or_null(value: Option<&Value>) -> Value {
    value
        .filter(|v| !v.is_null())
        .cloned()
        .unwrap_or(Value::Null)
}

fn normalize_chat(source: &Value) -> Value {
    let chat = source
        .get("chat")
        .filter(|c| c.is_object() || c.is_array())
        .unwrap_or(source);
    let messages: Vec<Value> = source
        .get("messages")
        .and_then(Value::as_array)
        .map(|items| items.iter().map(normalize_message).collect())
        .unwrap_or_default();
    json!({
        "title": or_null(chat.get("title")),
        "draft": or_null(chat.get("draft")),
        "summary": or_null(chat.get("summary")),
        "messages": messages,
    })
}

fn normalize_message(message: &Value) -> Value {
    let mut out = Map::new();
    // `undefined` role/content are omitted by JSON.stringify; null stays null.
    for key in ["role", "content"] {
        if let Some(value) = message.get(key) {
            out.insert(key.into(), value.clone());
        }
    }
    let completed = message
        .get("completed_at")
        .filter(|v| !v.is_null())
        .or_else(|| message.get("timestamp"));
    out.insert("completed_at".into(), or_null(completed));
    for key in [
        "assistant_category",
        "thinking",
        "has_thinking",
        "thinking_tokens",
    ] {
        out.insert(key.into(), or_null(message.get(key)));
    }
    Value::Object(out)
}

struct Multiline {
    message: Option<usize>,
    key: String,
    indent: usize,
}

fn parse_cli_export_yaml(raw: &str) -> Result<Value, String> {
    let pattern = regex::Regex::new(r"^\s*([A-Za-z0-9_-]+):\s*([^\r\n\u{2028}\u{2029}]*)$")
        .expect("static pattern");
    let mut chat = Map::new();
    let mut messages: Vec<Map<String, Value>> = vec![];
    let mut section = "";
    let mut current: Option<usize> = None;
    let mut multiline: Option<Multiline> = None;
    for line in raw.split('\n') {
        let indent = line.len() - line.trim_start_matches(' ').len();
        let trimmed = line.trim_end();
        if trimmed.trim().is_empty() {
            continue;
        }
        if multiline
            .as_ref()
            .is_some_and(|state| indent < state.indent)
        {
            multiline = None;
        }
        if let Some(state) = &multiline {
            let target = match state.message {
                Some(i) => &mut messages[i],
                None => &mut chat,
            };
            let previous = match target.get(&state.key) {
                None | Some(Value::Null) => String::new(),
                Some(Value::String(s)) => s.clone(),
                Some(other) => other.to_string(),
            };
            let next = line.get(state.indent..).unwrap_or("");
            let value = if previous.is_empty() {
                next.to_owned()
            } else {
                format!("{previous}\n{next}")
            };
            target.insert(state.key.clone(), Value::String(value));
            continue;
        }
        if trimmed == "chat:" {
            section = "chat";
            current = None;
            continue;
        }
        if trimmed == "messages:" {
            section = "messages";
            current = None;
            continue;
        }
        if section == "messages" && trimmed.trim() == "-" {
            messages.push(Map::new());
            current = Some(messages.len() - 1);
            continue;
        }
        let Some(captures) = pattern.captures(line) else {
            continue;
        };
        let (key, value) = (captures[1].to_owned(), &captures[2]);
        let message = match section {
            "chat" => None,
            "messages" if current.is_some() => current,
            _ => continue,
        };
        let target = match message {
            Some(i) => &mut messages[i],
            None => &mut chat,
        };
        if value == "|" {
            target.insert(key.clone(), Value::String(String::new()));
            multiline = Some(Multiline {
                message,
                key,
                indent: indent + 2,
            });
        } else {
            target.insert(key, yaml_scalar(value));
        }
    }
    if messages.is_empty() {
        return Err("Import YAML did not contain any messages.".into());
    }
    let messages: Vec<Value> = messages.into_iter().map(Value::Object).collect();
    Ok(normalize_chat(&json!({"chat": chat, "messages": messages})))
}

/// Legacy `parseYamlScalar`, including JavaScript `Number()` acceptance.
fn yaml_scalar(value: &str) -> Value {
    let trimmed = value.trim();
    match trimmed {
        "null" => return Value::Null,
        "true" => return Value::Bool(true),
        "false" => return Value::Bool(false),
        _ => {}
    }
    if let Some(number) = js_finite_number(trimmed) {
        return if number.fract() == 0.0 && number.abs() < 9_007_199_254_740_992.0 {
            json!(number as i64)
        } else {
            json!(number)
        };
    }
    let quoted = trimmed.len() >= 2
        && ((trimmed.starts_with('"') && trimmed.ends_with('"'))
            || (trimmed.starts_with('\'') && trimmed.ends_with('\'')));
    if quoted {
        return Value::String(
            trimmed[1..trimmed.len() - 1]
                .replace("\\\"", "\"")
                .replace("\\\\", "\\"),
        );
    }
    Value::String(trimmed.into())
}
fn js_finite_number(text: &str) -> Option<f64> {
    if text.is_empty() {
        return None;
    }
    let lower = text.to_ascii_lowercase();
    for (prefix, radix) in [("0x", 16), ("0o", 8), ("0b", 2)] {
        if let Some(digits) = lower.strip_prefix(prefix) {
            return u64::from_str_radix(digits, radix).ok().map(|n| n as f64);
        }
    }
    // Rust accepts "inf"/"nan" spellings JavaScript rejects; both are non-finite anyway.
    if !text
        .bytes()
        .all(|b| b.is_ascii_digit() || matches!(b, b'+' | b'-' | b'.' | b'e' | b'E'))
    {
        return None;
    }
    text.parse::<f64>().ok().filter(|n| n.is_finite())
}
