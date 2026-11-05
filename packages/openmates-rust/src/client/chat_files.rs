//! Chat file references (`chats files`): embed IDs referenced by decrypted
//! messages, a breadth-first walk over their decrypted embeds and the shared
//! lightweight file rows used by chat settings and the CLI. Plaintext stays in
//! caller memory; nothing is cached or written by this module.
use super::*;
use regex::Regex;
use serde_json::Map;
use std::collections::{HashSet, VecDeque};
use std::sync::LazyLock;

/// Bound on embeds inspected for one chat, including nested child embeds.
const MAX_EMBEDS: usize = 512;

/// One file-like embed. `to_json` is the preserved CLI JSON row shape.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChatFileReference {
    pub embed_id: String,
    pub content_ref: String,
    pub title: String,
    pub subtitle: String,
    pub kind: String,
    pub node_type: String,
    pub icon_name: String,
    pub metadata: String,
    pub app_id: Option<String>,
    pub skill_id: Option<String>,
    pub url: Option<String>,
    pub mime_type: Option<String>,
}
impl ChatFileReference {
    pub fn to_json(&self) -> Value {
        json!({"embed_id":self.embed_id,"content_ref":self.content_ref,"title":self.title,
            "type":self.kind,"node_type":self.node_type,"metadata":self.metadata,
            "app_id":self.app_id,"skill_id":self.skill_id,"url":self.url,"mime_type":self.mime_type})
    }
}
/// An embed that could not be read or decrypted; other files are still listed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChatFileError {
    pub embed_id: String,
    pub message: String,
}
#[derive(Clone, Debug, Default)]
pub struct ChatFiles {
    pub chat_id: String,
    pub title: String,
    pub files: Vec<ChatFileReference>,
    pub errors: Vec<ChatFileError>,
}

impl Client {
    /// Bounded selected-chat read plus per-embed reads; no account sync.
    pub async fn chat_files(&mut self, chat_id: &str) -> Result<ChatFiles> {
        let chat = self.open_chat(chat_id).await?;
        let cancel = self.operation_cancel.clone();
        let mut queue: VecDeque<String> =
            message_embed_ids(chat.messages.iter().map(|m| m.content.as_str())).into();
        let mut visited = HashSet::new();
        let mut seen_files = HashSet::new();
        let mut result = ChatFiles {
            chat_id: chat.id.clone(),
            title: chat.title.clone(),
            ..ChatFiles::default()
        };
        while let Some(embed_id) = queue.pop_front() {
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            if embed_id.is_empty() || !visited.insert(embed_id.clone()) {
                continue;
            }
            if visited.len() > MAX_EMBEDS {
                return Err(Error::Invalid(
                    "This chat references too many embeds to list.",
                ));
            }
            match self.embed_detail(&embed_id).await {
                Ok(item) => {
                    let kind = item.fields["type"].as_str().unwrap_or("");
                    let content = &item.fields["content"];
                    for file in embed_file_references(&embed_id, kind, content) {
                        if seen_files
                            .insert(format!("{}:{}", file.embed_id, file.title).to_lowercase())
                        {
                            result.files.push(file);
                        }
                    }
                    for child in child_embed_ids(content) {
                        if !visited.contains(&child) {
                            queue.push_back(child);
                        }
                    }
                }
                Err(Error::Cancelled) => return Err(Error::Cancelled),
                Err(error) => result.errors.push(ChatFileError {
                    embed_id,
                    message: error.to_string(),
                }),
            }
        }
        Ok(result)
    }
}

static INLINE_EMBED: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"embed:([a-zA-Z0-9_.:-]+)").expect("static regex"));
static FENCE_OPEN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^ {0,3}(`{3,}|~{3,})([^`~]*)$").expect("static regex"));

/// Ordered, unique embed IDs referenced by message contents: inline
/// `embed:<id>` references, then closed `json_embed`/`json` fences with an
/// `embed_id`. Unclosed fences end scanning like the shared segment parser.
pub fn message_embed_ids<'a>(contents: impl IntoIterator<Item = &'a str>) -> Vec<String> {
    let mut ids = Vec::<String>::new();
    let mut push = |id: &str| {
        if !id.is_empty() && !ids.iter().any(|v| v == id) {
            ids.push(id.to_owned());
        }
    };
    for content in contents {
        for capture in INLINE_EMBED.captures_iter(content) {
            push(&capture[1]);
        }
        for id in fenced_embed_ids(content) {
            push(&id);
        }
    }
    ids
}

fn strip_newline(row: &str) -> &str {
    row.strip_suffix("\r\n")
        .or_else(|| row.strip_suffix('\n'))
        .unwrap_or(row)
}

fn fenced_embed_ids(content: &str) -> Vec<String> {
    let rows: Vec<&str> = content.split_inclusive('\n').collect();
    let mut ids = vec![];
    let mut index = 0;
    while index < rows.len() {
        let Some(open) = FENCE_OPEN.captures(strip_newline(rows[index])) else {
            index += 1;
            continue;
        };
        let marker = &open[1];
        let fence_char = marker.chars().next().unwrap_or('`');
        let closes = |row: &str| {
            let row = strip_newline(row);
            let indent = row.len() - row.trim_start_matches(' ').len();
            let rest = &row[indent..];
            let run = rest.len() - rest.trim_start_matches(fence_char).len();
            indent <= 3 && run >= marker.len() && rest[run..].chars().all(|c| c == ' ' || c == '\t')
        };
        let mut end = index + 1;
        while end < rows.len() && !closes(rows[end]) {
            end += 1;
        }
        if end == rows.len() {
            break;
        }
        let language = open[2].trim();
        if language == "json_embed" || language == "json" {
            let body: String = rows[index + 1..end].concat();
            if let Ok(Value::Object(parsed)) = serde_json::from_str::<Value>(body.trim())
                && let Some(id) = parsed
                    .get("embed_id")
                    .and_then(Value::as_str)
                    .filter(|v| !v.is_empty())
            {
                ids.push(id.to_owned());
            }
        }
        index = end + 1;
    }
    ids
}

fn normalize_embed_id(id: &str) -> String {
    id.strip_prefix("embed:").unwrap_or(id).to_owned()
}

fn strip_quotes(value: &str) -> String {
    match value.chars().next() {
        // A lone quote both starts and ends the value, leaving nothing inside.
        Some('"' | '\'') if value.len() == 1 => String::new(),
        Some(first @ ('"' | '\'')) if value.ends_with(first) => value[1..value.len() - 1]
            .replace("\\n", "\n")
            .replace("\\\"", "\"")
            .replace("\\'", "'"),
        _ => value.to_owned(),
    }
}

fn clean_string(value: Option<&Value>) -> String {
    let Some(Value::String(value)) = value else {
        return String::new();
    };
    let trimmed = strip_quotes(value.trim());
    if trimmed.is_empty() || trimmed == "null" || trimmed == "undefined" {
        String::new()
    } else {
        trimmed
    }
}

fn number_value(value: Option<&Value>) -> Option<f64> {
    match value? {
        Value::Number(n) => n.as_f64().filter(|n| n.is_finite()),
        Value::String(s) if !s.trim().is_empty() => {
            s.trim().parse::<f64>().ok().filter(|n| n.is_finite())
        }
        _ => None,
    }
}

fn parse_flat_toon(content: &str) -> Map<String, Value> {
    let mut fields = Map::new();
    for line in content.split('\n') {
        if line.is_empty() || line.starts_with(char::is_whitespace) {
            continue;
        }
        let Some(separator) = line.find(':').filter(|i| *i > 0) else {
            continue;
        };
        let key = line[..separator].trim();
        let value = line[separator + 1..].trim();
        if key.is_empty() || value.is_empty() {
            continue;
        }
        fields.insert(key.to_owned(), Value::String(strip_quotes(value)));
    }
    fields
}

fn decode_content(content: &Value) -> Map<String, Value> {
    match content {
        Value::Object(map) => map.clone(),
        Value::String(raw) if !raw.trim().is_empty() => {
            let trimmed = raw.trim();
            if trimmed.starts_with('{') || trimmed.starts_with('[') {
                match serde_json::from_str::<Value>(trimmed) {
                    Ok(Value::Object(map)) => map,
                    Ok(_) => Map::new(),
                    Err(_) => parse_flat_toon(raw),
                }
            } else {
                parse_flat_toon(raw)
            }
        }
        _ => Map::new(),
    }
}

fn string_field(record: &Map<String, Value>, keys: &[&str]) -> String {
    keys.iter()
        .map(|key| clean_string(record.get(*key)))
        .find(|value| !value.is_empty())
        .unwrap_or_default()
}

const FILE_LIKE_TYPES: &[&str] = &[
    "audio",
    "audio-recording",
    "code",
    "code-code",
    "design",
    "diagram",
    "docs",
    "docs-doc",
    "document",
    "image",
    "images-image",
    "mind-map",
    "mind_map",
    "model3d",
    "music",
    "notebook",
    "pcb_schematic",
    "pdf",
    "recording",
    "remotion-video",
    "sheet",
    "sheets",
    "sheets-sheet",
    "spreadsheet",
    "svg",
    "video",
];
const URL_FIELDS: &[&str] = &[
    "downloadUrl",
    "download_url",
    "file_url",
    "previewAudioUrl",
    "preview_audio_url",
    "previewImageUrl",
    "preview_image_url",
    "previewVideoUrl",
    "preview_video_url",
    "src",
    "url",
    "video_url",
];
const AUDIO_URL_FIELDS: &[&str] = &[
    "downloadUrl",
    "download_url",
    "file_url",
    "previewAudioUrl",
    "preview_audio_url",
    "src",
    "url",
];
const VIDEO_URL_FIELDS: &[&str] = &[
    "downloadUrl",
    "download_url",
    "file_url",
    "previewVideoUrl",
    "preview_video_url",
    "video_url",
    "src",
    "url",
    "previewImageUrl",
    "preview_image_url",
];
const IMAGE_URL_FIELDS: &[&str] = &[
    "downloadUrl",
    "download_url",
    "file_url",
    "previewImageUrl",
    "preview_image_url",
    "src",
    "url",
];
const FILENAME_FIELDS: &[&str] = &["filename", "file_name", "file_path", "original_filename"];
const MIME_FIELDS: &[&str] = &["mime_type", "file_type", "mimeType"];

fn mime_extension(mime: &str) -> Option<&'static str> {
    Some(match mime {
        "application/pdf" => "pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" => "xlsx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document" => "docx",
        "audio/mpeg" => "mp3",
        "audio/wav" => "wav",
        "image/jpeg" => "jpg",
        "image/png" => "png",
        "image/svg+xml" => "svg",
        "image/webp" => "webp",
        "model/gltf-binary" => "glb",
        "text/html" => "html",
        "text/markdown" => "md",
        "text/plain" => "txt",
        "video/mp4" => "mp4",
        _ => return None,
    })
}

fn is_audio(kind: &str) -> bool {
    kind.contains("audio") || kind == "music" || kind == "recording"
}

fn url_for_type(kind: &str, record: &Map<String, Value>) -> String {
    if kind.contains("video") || kind == "remotion-video" {
        string_field(record, VIDEO_URL_FIELDS)
    } else if is_audio(kind) {
        string_field(record, AUDIO_URL_FIELDS)
    } else if kind.contains("image") || kind == "svg" {
        string_field(record, IMAGE_URL_FIELDS)
    } else {
        string_field(record, URL_FIELDS)
    }
}

fn basename_from_url(url: &str) -> String {
    if url.starts_with("data:") {
        return String::new();
    }
    let without_query = url.split(['?', '#']).next().unwrap_or("");
    without_query
        .rsplit('/')
        .next()
        .unwrap_or("")
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-') {
                c
            } else {
                '_'
            }
        })
        .collect()
}

fn extension_from_url(url: &str) -> String {
    let basename = basename_from_url(url);
    match basename.rfind('.') {
        Some(dot) if dot > 0 => basename[dot + 1..].to_lowercase(),
        _ => String::new(),
    }
}

fn extension_from_language(language: &str) -> String {
    let normalized = language.to_lowercase();
    let mapped = match normalized.as_str() {
        "bash" => "sh",
        "css" => "css",
        "dockerfile" => "Dockerfile",
        "html" => "html",
        "javascript" => "js",
        "json" => "json",
        "markdown" => "md",
        "python" => "py",
        "rust" => "rs",
        "svelte" => "svelte",
        "text" => "txt",
        "typescript" => "ts",
        "yaml" => "yml",
        _ => "",
    };
    let value = if mapped.is_empty() {
        normalized
            .chars()
            .filter(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
            .collect()
    } else {
        mapped.to_owned()
    };
    if value.is_empty() {
        "txt".into()
    } else {
        value
    }
}

/// The TOON `format:` of a nested object (decoded content keeps no raw text).
fn nested_format(record: &Map<String, Value>) -> String {
    record
        .values()
        .filter_map(Value::as_object)
        .map(|nested| clean_string(nested.get("format")))
        .find(|value| !value.is_empty())
        .unwrap_or_default()
}

fn fallback_extension(kind: &str, record: &Map<String, Value>) -> String {
    let mime = string_field(record, MIME_FIELDS);
    if let Some(extension) = mime_extension(&mime) {
        return extension.into();
    }
    let from_url = extension_from_url(&url_for_type(kind, record));
    if !from_url.is_empty() {
        return from_url;
    }
    let nested = nested_format(record);
    if !nested.is_empty() {
        return nested;
    }
    let fixed = if kind.contains("video") {
        "mp4"
    } else if is_audio(kind) {
        "mp3"
    } else if kind.contains("image") {
        "png"
    } else if kind.contains("pdf") {
        "pdf"
    } else if kind.contains("doc") || kind == "document" {
        "docx"
    } else if kind.contains("sheet") || kind == "spreadsheet" {
        "xlsx"
    } else if kind == "model3d" {
        "glb"
    } else if kind.contains("code") || kind == "notebook" || kind == "pcb_schematic" {
        return extension_from_language(&string_field(record, &["language"]));
    } else {
        "txt"
    };
    fixed.into()
}

fn infer_title(embed_id: &str, kind: &str, record: &Map<String, Value>) -> String {
    let url_basename = basename_from_url(&url_for_type(kind, record));
    let filename = string_field(record, FILENAME_FIELDS);
    if (kind.contains("video") || kind == "music" || kind == "audio") && !url_basename.is_empty() {
        return url_basename;
    }
    if !filename.is_empty() {
        return filename.replace(['/', '\\'], "_");
    }
    if !url_basename.is_empty() {
        return url_basename;
    }
    let extension = fallback_extension(kind, record);
    let title = string_field(record, &["title"]);
    if !title.is_empty() {
        let safe: String = title
            .chars()
            .map(|c| {
                if c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | ' ' | '-') {
                    c
                } else {
                    '_'
                }
            })
            .collect();
        return format!("{}.{extension}", safe.trim());
    }
    let prefix: String = embed_id.chars().take(8).collect();
    format!(
        "{}-{prefix}.{extension}",
        if kind.is_empty() { "file" } else { kind }
    )
}

fn ends_with_any(value: &str, extensions: &[&str]) -> bool {
    extensions
        .iter()
        .any(|ext| value.ends_with(&format!(".{ext}")))
}

fn infer_node_type(title: &str, kind: &str) -> &'static str {
    let lower = title.to_lowercase();
    if kind.contains("pdf") || lower.ends_with(".pdf") {
        "pdf"
    } else if kind.contains("image")
        || ends_with_any(
            &lower,
            &[
                "png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "heic", "heif",
            ],
        )
    {
        "image"
    } else if kind.contains("video") || ends_with_any(&lower, &["mp4", "mov", "webm", "m4v"]) {
        "video"
    } else if is_audio(kind) || ends_with_any(&lower, &["mp3", "wav", "m4a", "ogg", "webm"]) {
        "recording"
    } else if kind.contains("sheet")
        || kind == "spreadsheet"
        || ends_with_any(&lower, &["csv", "xls", "xlsx", "ods"])
    {
        "sheets-sheet"
    } else if kind.contains("doc")
        || kind == "document"
        || ends_with_any(&lower, &["doc", "docx", "odt", "rtf"])
    {
        "docs-doc"
    } else if kind == "model3d" || ends_with_any(&lower, &["glb", "gltf", "obj", "stl"]) {
        "model3d"
    } else if kind.contains("code") || kind == "notebook" || kind == "pcb_schematic" {
        "code-code"
    } else {
        "file"
    }
}

fn icon_for_node_type(node_type: &str) -> &'static str {
    match node_type {
        "pdf" => "pdf",
        "image" => "image",
        "video" => "video",
        "recording" => "audio",
        "sheets-sheet" => "sheets",
        "docs-doc" => "document",
        "code-code" => "coding",
        "model3d" => "3dmodels",
        _ => "files",
    }
}

fn label_for_node_type(node_type: &str, kind: &str) -> &'static str {
    match node_type {
        "pdf" => "PDF",
        "image" => "Image",
        "video" => "Video",
        "recording" if kind == "music" => "Music",
        "recording" => "Audio",
        "sheets-sheet" => "Sheet",
        "docs-doc" => "Document",
        "code-code" if kind == "notebook" => "Notebook",
        "code-code" => "Code file",
        "model3d" => "3D model",
        _ => "File",
    }
}

/// Fixed decimals with ties rounded up, like the web resolver's formatting.
fn to_fixed(value: f64, digits: i32) -> String {
    let scale = 10f64.powi(digits);
    format!("{:.*}", digits as usize, (value * scale).round() / scale)
}

fn format_bytes(bytes: Option<f64>) -> String {
    let Some(bytes) = bytes.filter(|b| *b > 0.0) else {
        return String::new();
    };
    if bytes < 1024.0 {
        format!("{bytes} B")
    } else if bytes < 1024.0 * 1024.0 {
        let precision = if bytes < 10.0 * 1024.0 { 1 } else { 0 };
        format!("{} KB", to_fixed(bytes / 1024.0, precision))
    } else {
        let precision = if bytes < 10.0 * 1024.0 * 1024.0 { 1 } else { 0 };
        format!("{} MB", to_fixed(bytes / (1024.0 * 1024.0), precision))
    }
}

fn plural(value: f64, singular: &str) -> String {
    format!(
        "{value} {}",
        if value == 1.0 {
            singular.to_owned()
        } else {
            format!("{singular}s")
        }
    )
}

fn build_metadata(node_type: &str, kind: &str, record: &Map<String, Value>) -> String {
    let first = |keys: &[&str]| {
        keys.iter()
            .find_map(|key| record.get(*key).filter(|v| !v.is_null()))
    };
    let number = |keys: &[&str]| number_value(first(keys)).filter(|n| *n != 0.0);
    let mut parts = vec![label_for_node_type(node_type, kind).to_owned()];
    if let Some(lines) = number(&["line_count", "lineCount"]) {
        parts.push(plural(lines, "line"));
    }
    if let Some(pages) = number(&["page_count", "pageCount"]) {
        parts.push(plural(pages, "page"));
    }
    if let Some(words) = number(&["word_count", "wordCount"]) {
        parts.push(plural(words, "word"));
    }
    if let Some(duration) = number(&["duration_seconds", "durationSeconds"]) {
        parts.push(format!(
            "{}s",
            to_fixed(duration, if duration < 10.0 { 1 } else { 0 })
        ));
    }
    let size = format_bytes(number_value(first(&[
        "byte_length",
        "size_bytes",
        "sizeBytes",
    ])));
    if !size.is_empty() {
        parts.push(size);
    }
    parts.join(" | ")
}

fn supported_public_url(url: &str) -> bool {
    let lower = url.get(..8).unwrap_or(url).to_ascii_lowercase();
    url.starts_with('/')
        || url.starts_with("data:")
        || lower.starts_with("http://")
        || lower.starts_with("https://")
}

/// File rows for one decrypted embed (none when the embed is not file-like).
pub fn embed_file_references(
    embed_id: &str,
    embed_type: &str,
    content: &Value,
) -> Vec<ChatFileReference> {
    let embed_id = clean_string(Some(&Value::String(embed_id.to_owned())));
    if embed_id.is_empty() {
        return vec![];
    }
    let record = decode_content(content);
    let mut raw_type = string_field(&record, &["type", "embed_type", "embedType"]);
    if raw_type.is_empty() {
        raw_type = clean_string(Some(&Value::String(embed_type.to_owned())));
    }
    if raw_type.is_empty() {
        raw_type = "file".into();
    }
    let raw_type = raw_type.to_lowercase();
    let kind = if raw_type == "generated_audio" {
        "audio".to_owned()
    } else {
        raw_type
    };
    if !FILE_LIKE_TYPES.contains(&kind.as_str()) {
        return vec![];
    }
    let title = infer_title(&embed_id, &kind, &record);
    let node_type = infer_node_type(&title, &kind);
    let url = url_for_type(&kind, &record);
    let mime = string_field(&record, MIME_FIELDS);
    let id = normalize_embed_id(&embed_id);
    let optional = |value: String| (!value.is_empty()).then_some(value);
    vec![ChatFileReference {
        content_ref: format!("embed:{id}"),
        embed_id: id,
        title,
        subtitle: label_for_node_type(node_type, &kind).into(),
        node_type: node_type.into(),
        icon_name: icon_for_node_type(node_type).into(),
        metadata: build_metadata(node_type, &kind, &record),
        app_id: optional(string_field(&record, &["app_id", "appId"])),
        skill_id: optional(string_field(&record, &["skill_id", "skillId"])),
        url: (!url.is_empty() && supported_public_url(&url)).then_some(url),
        mime_type: optional(mime),
        kind,
    }]
}

/// Child embed IDs listed by a decrypted embed's `embed_ids` field.
pub fn child_embed_ids(content: &Value) -> Vec<String> {
    let record = decode_content(content);
    let raw = record.get("embed_ids").or_else(|| record.get("embedIds"));
    let values: Vec<Value> = match raw {
        Some(Value::String(joined)) => joined
            .split(['|', ','])
            .map(|v| Value::String(v.into()))
            .collect(),
        Some(Value::Array(values)) => values.clone(),
        _ => return vec![],
    };
    values
        .iter()
        .map(|value| clean_string(Some(value)))
        .filter(|value| !value.is_empty())
        .map(|value| normalize_embed_id(&value))
        .collect()
}

#[cfg(test)]
#[path = "chat_files_tests.rs"]
mod tests;
