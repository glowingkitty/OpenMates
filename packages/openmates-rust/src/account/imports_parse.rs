//! Account Import V1 parsers (port of the npm CLI `accountImport.ts`). Every
//! parser is pure: callers supply already-read export text (archive decoding
//! and password-protected containers stay in the platform adapter), and the
//! result carries the same chats, fingerprints and imported assistant identity
//! the legacy CLI sends to the import preview/scan routes.
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};

pub const ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE: usize = 250;
pub const COMPRESSION_SUMMARY_CATEGORY: &str = "compression_summary";

/// The provider a user selects for imported chats.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ImportSource {
    OpenMates,
    ChatGpt,
    Claude,
    Gemini,
    OpenCode,
    Other,
}
impl ImportSource {
    pub fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "openmates" => Self::OpenMates,
            "chatgpt" => Self::ChatGpt,
            "claude" => Self::Claude,
            "gemini" => Self::Gemini,
            "opencode" => Self::OpenCode,
            "other" => Self::Other,
            _ => return None,
        })
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Self::OpenMates => "openmates",
            Self::ChatGpt => "chatgpt",
            Self::Claude => "claude",
            Self::Gemini => "gemini",
            Self::OpenCode => "opencode",
            Self::Other => "other",
        }
    }
    pub fn identity(self) -> ImportedAssistantIdentity {
        let (sender, model, avatar) = match self {
            Self::OpenMates => ("OpenMates", "OpenMates", "openmates"),
            Self::ChatGpt => ("ChatGPT", "ChatGPT", "chatgpt"),
            Self::Claude => ("Claude", "Claude", "claude"),
            Self::Gemini => ("Gemini", "Gemini", "gemini"),
            Self::OpenCode => ("OpenCode", "OpenCode", "opencode"),
            Self::Other => ("AI assistant", "Other", "ai-star"),
        };
        ImportedAssistantIdentity {
            category: self.as_str().into(),
            sender_name: sender.into(),
            model_name: model.into(),
            avatar_key: avatar.into(),
        }
    }
}

/// The export format being parsed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ImportParser {
    Claude,
    ChatGpt,
    OpenMates,
    OpenCode,
    Generic,
}
impl ImportParser {
    pub fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "claude" => Self::Claude,
            "chatgpt" => Self::ChatGpt,
            "openmates" => Self::OpenMates,
            "opencode" => Self::OpenCode,
            "generic" => Self::Generic,
            _ => return None,
        })
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Claude => "claude",
            Self::ChatGpt => "chatgpt",
            Self::OpenMates => "openmates",
            Self::OpenCode => "opencode",
            Self::Generic => "generic",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ImportedAssistantIdentity {
    pub category: String,
    pub sender_name: String,
    pub model_name: String,
    pub avatar_key: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ParsedImportMessage {
    pub role: String,
    #[serde(default)]
    pub content: String,
    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub source_message_id: Option<String>,
    #[serde(default = "empty_object")]
    pub provider_metadata: Value,
    #[serde(default)]
    pub imported_assistant_identity: Option<ImportedAssistantIdentity>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ParsedImportUpload {
    pub source_upload_id: String,
    pub file_name: String,
    pub mime_type: Option<String>,
    pub bytes: Option<Value>,
    pub content_ref: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ParsedImportChat {
    pub provider: String,
    pub parser_format: String,
    pub selected_source: String,
    pub source_chat_id: String,
    pub source_fingerprint: String,
    pub title: Option<String>,
    pub created_at: Option<String>,
    pub updated_at: Option<String>,
    pub messages: Vec<ParsedImportMessage>,
    pub embeds: Vec<Value>,
    pub uploads: Vec<ParsedImportUpload>,
    pub provider_labels: Vec<String>,
    pub source_metadata: Value,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ParsedAccountImport {
    pub source: ImportSource,
    pub parser_format: ImportParser,
    pub chats: Vec<ParsedImportChat>,
    pub skipped_domains: Vec<String>,
}

/// One scan batch: a chat slice of at most `ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE` messages.
#[derive(Clone, Debug, PartialEq)]
pub struct AccountImportMessageBatch {
    pub chat_index: usize,
    pub chunk_index: usize,
    pub source_fingerprint: String,
    pub batch_id: String,
    pub chat: ParsedImportChat,
}

fn empty_object() -> Value {
    json!({})
}

pub fn build_account_import_message_batches(
    chats: &[ParsedImportChat],
    max_messages: usize,
) -> Result<Vec<AccountImportMessageBatch>, String> {
    if max_messages == 0 {
        return Err("Account import message batch size must be positive".into());
    }
    let mut batches = vec![];
    for (chat_index, chat) in chats.iter().enumerate() {
        let chunk_count = chat.messages.len().div_ceil(max_messages).max(1);
        for chunk_index in 0..chunk_count {
            let start = (chunk_index * max_messages).min(chat.messages.len());
            let end = ((chunk_index + 1) * max_messages).min(chat.messages.len());
            let mut slice = chat.clone();
            slice.messages = chat.messages[start..end].to_vec();
            batches.push(AccountImportMessageBatch {
                chat_index,
                chunk_index,
                source_fingerprint: chat.source_fingerprint.clone(),
                batch_id: format!("scan-{}-{chunk_index}", prefix16(&chat.source_fingerprint)),
                chat: slice,
            });
        }
    }
    Ok(batches)
}

pub(crate) fn prefix16(value: &str) -> &str {
    value
        .char_indices()
        .nth(16)
        .map_or(value, |(at, _)| &value[..at])
}

pub fn append_compression_summary(chat: &mut ParsedImportChat, summary: Option<&str>) {
    let Some(summary) = summary.filter(|s| !js_blank(s)) else {
        return;
    };
    chat.messages.push(ParsedImportMessage {
        role: "system".into(),
        content: summary.into(),
        created_at: None,
        source_message_id: None,
        provider_metadata: json!({"import_type": COMPRESSION_SUMMARY_CATEGORY}),
        imported_assistant_identity: None,
    });
}

/// SHA-256 of the exact `JSON.stringify` shape the legacy CLI hashes.
pub fn source_fingerprint(
    parser: ImportParser,
    source_chat_id: &str,
    messages: &[ParsedImportMessage],
) -> String {
    source_fingerprint_for(parser.as_str(), source_chat_id, messages)
}

/// [`source_fingerprint`] over an explicit provider label (the web hashes
/// generic transcripts as `other`).
pub fn source_fingerprint_for(
    provider: &str,
    source_chat_id: &str,
    messages: &[ParsedImportMessage],
) -> String {
    let quote = |value: &str| Value::String(value.to_owned()).to_string();
    let mut text = format!(
        "{{\"provider\":{},\"source_chat_id\":{},\"messages\":[",
        quote(provider),
        quote(source_chat_id)
    );
    for (index, message) in messages.iter().enumerate() {
        if index > 0 {
            text.push(',');
        }
        text.push_str(&format!(
            "{{\"role\":{},\"source_message_id\":{},\"content\":{}}}",
            quote(&message.role),
            message
                .source_message_id
                .as_deref()
                .map_or("null".into(), quote),
            quote(&message.content)
        ));
    }
    text.push_str("]}");
    Sha256::digest(text.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// JavaScript `String(value ?? fallback)` for JSON values.
pub(crate) fn js_string(value: Option<&Value>, fallback: &str) -> String {
    match value {
        None | Some(Value::Null) => fallback.into(),
        Some(Value::String(s)) => s.clone(),
        Some(Value::Number(n)) => n.to_string(),
        Some(Value::Bool(b)) => b.to_string(),
        Some(Value::Array(items)) => items
            .iter()
            .map(|v| match v {
                Value::Null => String::new(),
                other => js_string(Some(other), ""),
            })
            .collect::<Vec<_>>()
            .join(","),
        Some(Value::Object(_)) => "[object Object]".into(),
    }
}
pub(crate) fn string_field(value: &Value, key: &str) -> Option<String> {
    value.get(key).and_then(Value::as_str).map(str::to_owned)
}
/// `item && typeof item === "object"` (arrays included).
pub(crate) fn is_js_object(value: &Value) -> bool {
    value.is_object() || value.is_array()
}
/// JavaScript `String.prototype.trim` whitespace: Unicode White_Space without
/// NEL (U+0085) plus the byte order mark (U+FEFF).
pub fn js_is_space(c: char) -> bool {
    c == '\u{feff}' || (c != '\u{85}' && c.is_whitespace())
}
/// JavaScript `!value.trim()`.
pub fn js_blank(value: &str) -> bool {
    value.chars().all(js_is_space)
}
pub(crate) fn js_objects(value: Option<&Value>) -> Vec<&Value> {
    value
        .and_then(Value::as_array)
        .map(|items| items.iter().filter(|v| is_js_object(v)).collect())
        .unwrap_or_default()
}

/// `new Date(ms).toISOString()`; out-of-range instants are invalid like JS.
pub fn iso_from_ms(ms: f64) -> Result<String, String> {
    let ms = ms.trunc();
    if !ms.is_finite() || ms.abs() > 8.64e15 {
        return Err("Invalid time value".into());
    }
    let ms = ms as i64;
    let days = ms.div_euclid(86_400_000);
    let rem = ms.rem_euclid(86_400_000);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    let year = if (0..=9999).contains(&year) {
        format!("{year:04}")
    } else if year < 0 {
        format!("-{:06}", -year)
    } else {
        format!("+{year:06}")
    };
    Ok(format!(
        "{year}-{month:02}-{day:02}T{:02}:{:02}:{:02}.{:03}Z",
        rem / 3_600_000,
        rem / 60_000 % 60,
        rem / 1000 % 60,
        rem % 1000
    ))
}
pub(crate) fn positive_time(value: Option<&Value>, scale: f64) -> Result<Option<String>, String> {
    match value.and_then(Value::as_f64) {
        Some(v) if v.is_finite() && v > 0.0 => iso_from_ms(v * scale).map(Some),
        _ => Ok(None),
    }
}

pub(crate) fn finalize(
    parser: ImportParser,
    selected: ImportSource,
    chats: Vec<ParsedImportChat>,
    skipped_domains: Vec<String>,
) -> ParsedAccountImport {
    let identity = selected.identity();
    let chats = chats
        .into_iter()
        .map(|mut chat| {
            chat.provider = selected.as_str().into();
            chat.parser_format = parser.as_str().into();
            chat.selected_source = selected.as_str().into();
            for message in &mut chat.messages {
                message.imported_assistant_identity = (message.role == "assistant").then(|| {
                    let mut identity = identity.clone();
                    if let Some(model) = message
                        .provider_metadata
                        .get("model")
                        .and_then(Value::as_str)
                        && !js_blank(model)
                    {
                        identity.model_name = model.to_owned();
                    }
                    identity
                });
            }
            chat
        })
        .collect();
    ParsedAccountImport {
        source: selected,
        parser_format: parser,
        chats,
        skipped_domains,
    }
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn chat(
    parser: ImportParser,
    selected: ImportSource,
    source_chat_id: String,
    title: Option<String>,
    created_at: Option<String>,
    updated_at: Option<String>,
    messages: Vec<ParsedImportMessage>,
    uploads: Vec<ParsedImportUpload>,
    labels: Vec<String>,
    source_metadata: Value,
) -> ParsedImportChat {
    ParsedImportChat {
        provider: parser.as_str().into(),
        parser_format: parser.as_str().into(),
        selected_source: selected.as_str().into(),
        source_fingerprint: source_fingerprint(parser, &source_chat_id, &messages),
        source_chat_id,
        title,
        created_at,
        updated_at,
        messages,
        embeds: vec![],
        uploads,
        provider_labels: labels,
        source_metadata,
    }
}
pub(crate) fn message(
    role: &str,
    content: String,
    created_at: Option<String>,
    id: Option<String>,
    metadata: Value,
) -> ParsedImportMessage {
    ParsedImportMessage {
        role: role.into(),
        content,
        created_at,
        source_message_id: id,
        provider_metadata: metadata,
        imported_assistant_identity: None,
    }
}

fn conversations<'a>(decoded: &'a Value, label: &str) -> Result<Vec<&'a Value>, String> {
    let raw = decoded
        .as_array()
        .or_else(|| decoded.get("conversations").and_then(Value::as_array))
        .ok_or_else(|| format!("{label} export conversations must be an array"))?;
    Ok(raw.iter().filter(|v| is_js_object(v)).collect())
}
pub(crate) fn decode(text: &str, label: &str) -> Result<Value, String> {
    serde_json::from_str(text).map_err(|e| format!("{label} could not be parsed: {e}"))
}

/// Claude official export (`conversations.json` text).
pub fn parse_claude_import(
    text: &str,
    source_name: &str,
    selected: ImportSource,
) -> Result<ParsedAccountImport, String> {
    parse_claude_value(&decode(text, "Claude export")?, source_name, selected)
}
/// [`parse_claude_import`] over an already decoded export.
pub fn parse_claude_value(
    decoded: &Value,
    source_name: &str,
    selected: ImportSource,
) -> Result<ParsedAccountImport, String> {
    let mut chats = vec![];
    for conversation in conversations(decoded, "Claude")? {
        let source_chat_id = js_string(conversation.get("uuid"), "");
        if source_chat_id.is_empty() {
            return Err("Claude conversation is missing uuid".into());
        }
        let raw_messages = js_objects(conversation.get("chat_messages"));
        let messages: Vec<_> = raw_messages
            .iter()
            .map(|m| {
                let mut types = vec![];
                let mut parts = vec![];
                for block in js_objects(m.get("content")) {
                    let kind = js_string(block.get("type"), "unknown");
                    if kind == "text"
                        && let Some(text) = block.get("text").and_then(Value::as_str)
                    {
                        parts.push(text.to_owned());
                    }
                    if kind == "tool_result"
                        && let Some(text) = block.get("content").and_then(Value::as_str)
                    {
                        parts.push(text.to_owned());
                    }
                    types.push(kind);
                }
                let content = if parts.is_empty() {
                    js_string(m.get("text"), "")
                } else {
                    parts.join("\n")
                };
                let role = match js_string(m.get("sender"), "").as_str() {
                    "human" => "user",
                    "assistant" => "assistant",
                    _ => "system",
                };
                message(
                    role,
                    content,
                    string_field(m, "created_at"),
                    string_field(m, "uuid"),
                    json!({"content_block_types": types}),
                )
            })
            .collect();
        let uploads = raw_messages
            .iter()
            .flat_map(|m| claude_uploads(m))
            .collect();
        let count = messages.len();
        chats.push(chat(
            ImportParser::Claude,
            selected,
            source_chat_id,
            string_field(conversation, "name"),
            string_field(conversation, "created_at"),
            string_field(conversation, "updated_at"),
            messages,
            uploads,
            vec!["claude".into()],
            json!({"source_name": source_name, "message_count": count}),
        ));
    }
    Ok(finalize(ImportParser::Claude, selected, chats, vec![]))
}
fn claude_uploads(message: &Value) -> Vec<ParsedImportUpload> {
    let mut items = js_objects(message.get("attachments"));
    items.extend(js_objects(message.get("files")));
    items
        .into_iter()
        .enumerate()
        .map(|(index, item)| {
            let file_name = match item.get("file_name").filter(|v| !v.is_null()) {
                Some(v) => js_string(Some(v), ""),
                None => js_string(item.get("name"), &format!("attachment-{}", index + 1)),
            };
            let source_upload_id = match item.get("uuid").filter(|v| !v.is_null()) {
                Some(v) => js_string(Some(v), ""),
                None => js_string(item.get("id"), &file_name),
            };
            ParsedImportUpload {
                source_upload_id,
                mime_type: string_field(item, "mime_type")
                    .or_else(|| string_field(item, "file_type")),
                bytes: item
                    .get("file_size")
                    .filter(|v| v.is_number())
                    .or_else(|| item.get("bytes").filter(|v| v.is_number()))
                    .cloned(),
                content_ref: file_name.clone(),
                file_name,
            }
        })
        .collect()
}

/// ChatGPT official export (`conversations.json` text): the active branch only.
pub fn parse_chatgpt_import(
    text: &str,
    source_name: &str,
    selected: ImportSource,
) -> Result<ParsedAccountImport, String> {
    parse_chatgpt_value(&decode(text, "ChatGPT export")?, source_name, selected)
}
/// [`parse_chatgpt_import`] over an already decoded export.
pub fn parse_chatgpt_value(
    decoded: &Value,
    source_name: &str,
    selected: ImportSource,
) -> Result<ParsedAccountImport, String> {
    let mut chats = vec![];
    for conversation in conversations(decoded, "ChatGPT")? {
        let source_chat_id = match conversation.get("conversation_id").filter(|v| !v.is_null()) {
            Some(v) => js_string(Some(v), ""),
            None => js_string(conversation.get("id"), ""),
        };
        if source_chat_id.is_empty() {
            return Err("ChatGPT conversation is missing id".into());
        }
        let mut messages = vec![];
        for node in chatgpt_active_nodes(conversation)? {
            let Some(raw) = node.get("message").filter(|v| is_js_object(v)) else {
                continue;
            };
            let author = raw
                .get("author")
                .filter(|v| is_js_object(v))
                .cloned()
                .unwrap_or(json!({}));
            let role = js_string(author.get("role"), "");
            if !matches!(role.as_str(), "user" | "assistant" | "system") {
                continue;
            }
            let Some(content) = raw.get("content").filter(|v| is_js_object(v)) else {
                continue;
            };
            let parts = content
                .get("parts")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            let mut texts = vec![];
            let mut assets = 0;
            for part in &parts {
                match part {
                    Value::String(s) if !js_blank(s) => texts.push(s.clone()),
                    Value::Object(o) if o.contains_key("asset_pointer") => assets += 1,
                    _ => {}
                }
            }
            if parts.is_empty()
                && let Some(text) = content.get("content").and_then(Value::as_str)
            {
                texts.push(text.to_owned());
            }
            let text = texts.join("\n");
            if js_blank(&text) {
                continue;
            }
            messages.push(message(
                &role,
                text,
                positive_time(raw.get("create_time"), 1000.0)?,
                string_field(raw, "id"),
                json!({"content_type": js_string(content.get("content_type"), "unknown"), "asset_count": assets}),
            ));
        }
        let count = messages.len();
        chats.push(chat(
            ImportParser::ChatGpt,
            selected,
            source_chat_id,
            string_field(conversation, "title"),
            positive_time(conversation.get("create_time"), 1000.0)?,
            positive_time(conversation.get("update_time"), 1000.0)?,
            messages,
            vec![],
            vec!["chatgpt".into()],
            json!({"source_name": source_name, "message_count": count}),
        ));
    }
    Ok(finalize(ImportParser::ChatGpt, selected, chats, vec![]))
}
fn chatgpt_active_nodes(conversation: &Value) -> Result<Vec<&Value>, String> {
    let nodes: &Map<String, Value> = conversation
        .get("mapping")
        .and_then(Value::as_object)
        .ok_or("ChatGPT conversation is missing mapping")?;
    let current = js_string(conversation.get("current_node"), "");
    if !current.is_empty() && nodes.get(&current).is_some_and(|n| !n.is_null()) {
        let mut ordered = vec![];
        let mut seen = std::collections::BTreeSet::new();
        let mut id = current;
        while let Some(node) = nodes.get(&id).filter(|n| !n.is_null() && !id.is_empty()) {
            if !seen.insert(id.clone()) {
                break;
            }
            ordered.push(node);
            id = js_string(node.get("parent"), "");
        }
        ordered.reverse();
        return Ok(ordered);
    }
    let created = |node: &Value| {
        node.get("message")
            .and_then(|m| m.get("create_time"))
            .and_then(Value::as_f64)
            .unwrap_or(0.0)
    };
    let mut all: Vec<&Value> = nodes.values().collect();
    all.sort_by(|a, b| created(a).total_cmp(&created(b)));
    Ok(all)
}

#[path = "imports_parse_more.rs"]
mod more;
pub use more::{
    parse_generic_import, parse_opencode_import, parse_opencode_value, parse_openmates_import,
};
