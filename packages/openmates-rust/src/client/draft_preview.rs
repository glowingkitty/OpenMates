//! Draft chat-list preview text: the single implementation of the web
//! client's `generateDraftPreview` (100 UTF-16 units, mention display names,
//! embed labels, code placeholders). Pure text logic, no crypto or IO.
//!
//! JavaScript semantics are mirrored exactly where they affect output:
//! `\s`/`trim()` use the ECMAScript whitespace set, `\w`/`\b` are ASCII, and
//! lengths/truncation count UTF-16 code units. A cut inside a surrogate pair
//! yields U+FFFD, which is what TextEncoder writes for the lone surrogate the
//! web client produced. Malformed editor documents fall back to the markdown
//! path, as the web client's exception handler does.
use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

use regex::{Captures, Regex};
use serde_json::Value;

use crate::{Error, Result};

pub const DRAFT_PREVIEW_MAX_UNITS: usize = 100;
/// Upper bound for the caller's preview context (editor document + names).
pub const MAX_DRAFT_PREVIEW_CONTEXT_BYTES: usize = 2 * 1024 * 1024;

/// ECMAScript `\s` (WhiteSpace + LineTerminator), as a regex class body.
const WS: &str = r"\t\n\x0B\x0C\r \x{A0}\x{1680}\x{2000}-\x{200A}\x{2028}\x{2029}\x{202F}\x{205F}\x{3000}\x{FEFF}";

fn js_ws(c: char) -> bool {
    matches!(
        c,
        '\t' | '\n' | '\u{0B}' | '\u{0C}' | '\r' | ' ' | '\u{A0}' | '\u{1680}' | '\u{2000}'
            ..='\u{200A}'
                | '\u{2028}'
                | '\u{2029}'
                | '\u{202F}'
                | '\u{205F}'
                | '\u{3000}'
                | '\u{FEFF}'
    )
}
fn js_trim(s: &str) -> &str {
    s.trim_matches(js_ws)
}
/// `s.replace(/\s+/g, " ").trim()`
fn collapse(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut in_ws = false;
    for c in s.chars() {
        if js_ws(c) {
            if !in_ws {
                out.push(' ');
            }
            in_ws = true;
        } else {
            out.push(c);
            in_ws = false;
        }
    }
    js_trim(&out).to_owned()
}
fn hyphenate(s: &str) -> String {
    static RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(&format!("[{WS}]+")).unwrap());
    RE.replace_all(s, "-").into_owned()
}
/// `s.length > max ? s.substring(0, max) + suffix : s` in UTF-16 units.
fn truncate_units(s: &str, max: usize, suffix: &str) -> String {
    if s.encode_utf16().count() <= max {
        return s.to_owned();
    }
    let (mut out, mut units) = (String::new(), 0usize);
    for c in s.chars() {
        let width = c.len_utf16();
        if units + width > max {
            if units < max {
                out.push('\u{FFFD}');
            }
            break;
        }
        out.push(c);
        units += width;
    }
    out.push_str(suffix);
    out
}
/// `word.charAt(0).toUpperCase() + word.slice(1)` per `-`-separated word.
fn capitalize_words(s: &str) -> String {
    s.split('-')
        .map(|word| {
            let mut chars = word.chars();
            match chars.next() {
                // charAt(0) of an astral character is a lone surrogate: unchanged.
                Some(first) if first.len_utf16() == 1 => {
                    first.to_uppercase().chain(chars).collect()
                }
                Some(first) => std::iter::once(first).chain(chars).collect(),
                None => String::new(),
            }
        })
        .collect::<Vec<_>>()
        .join("-")
}

/// Display-name catalog supplied by the client (data only).
#[derive(Debug, Default)]
pub struct DraftPreviewNames {
    models: HashMap<String, String>,
    mates: HashMap<String, String>,
    skills: HashSet<String>,
    focus: HashSet<String>,
    memories: HashSet<String>,
}

/// Parse `{"doc":…|null,"models":{id:name},"mates":{id:name},"skills":["app:id"],"focus":[…],"memories":[…]}`.
pub fn parse_draft_preview_context(encoded: &str) -> Result<(Option<Value>, DraftPreviewNames)> {
    if encoded.len() > MAX_DRAFT_PREVIEW_CONTEXT_BYTES {
        return Err(Error::Protocol);
    }
    let value: Value = serde_json::from_str(encoded)?;
    let object = value.as_object().ok_or(Error::Protocol)?;
    const KEYS: [&str; 6] = ["doc", "models", "mates", "skills", "focus", "memories"];
    if object.len() != KEYS.len() || KEYS.iter().any(|key| !object.contains_key(*key)) {
        return Err(Error::Protocol);
    }
    let map = |key: &str| -> Result<HashMap<String, String>> {
        object[key]
            .as_object()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|(id, name)| Ok((id.clone(), name.as_str().ok_or(Error::Protocol)?.to_owned())))
            .collect()
    };
    let set = |key: &str| -> Result<HashSet<String>> {
        object[key]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .map(|id| Ok(id.as_str().ok_or(Error::Protocol)?.to_owned()))
            .collect()
    };
    let names = DraftPreviewNames {
        models: map("models")?,
        mates: map("mates")?,
        skills: set("skills")?,
        focus: set("focus")?,
        memories: set("memories")?,
    };
    let doc = match &object["doc"] {
        Value::Null => None,
        doc => Some(doc.clone()),
    };
    Ok((doc, names))
}

const EMBED_LABELS: [(&str, &str); 16] = [
    ("image", "Image"),
    ("audio", "Audio"),
    ("audio-recording", "Audio"),
    ("recording", "Recording"),
    ("website", "Website"),
    ("web-website", "Website"),
    ("video", "Video"),
    ("videos-video", "Video"),
    ("location", "Location"),
    ("maps", "Location"),
    ("pdf", "PDF"),
    ("file", "File"),
    ("book", "Book"),
    ("code", "Code"),
    ("code-code", "Code"),
    ("code-code-group", "Code"),
];
fn known_label(kind: &str) -> Option<&'static str> {
    EMBED_LABELS
        .iter()
        .find(|(k, _)| *k == kind)
        .map(|(_, v)| *v)
}
/// `draftEmbedLabel`: known label, else `-`/`_` runs to spaces and ASCII word starts uppercased.
pub fn draft_embed_label(kind: &str) -> String {
    let label = match known_label(kind) {
        Some(label) => label.to_owned(),
        None => {
            static SEP: LazyLock<Regex> = LazyLock::new(|| Regex::new("[-_]+").unwrap());
            let spaced = SEP.replace_all(kind, " ");
            let (mut out, mut previous_word) = (String::with_capacity(spaced.len()), false);
            for c in spaced.chars() {
                let word = c.is_ascii_alphanumeric() || c == '_';
                out.push(if word && !previous_word {
                    c.to_ascii_uppercase()
                } else {
                    c
                });
                previous_word = word;
            }
            out
        }
    };
    format!("[{label}]")
}

fn label_for_reference(content: &str) -> String {
    static TYPE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(&format!(r#""type"[{WS}]*:[{WS}]*"([a-zA-Z0-9_-]+)""#)).unwrap()
    });
    static EMBED_ID: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!(r#""embed_id"[{WS}]*:"#)).unwrap());
    let embedded = EMBED_ID.is_match(content);
    match TYPE.captures(content).map(|c| c.get(1).unwrap().as_str()) {
        None if embedded => "[Embed]".into(),
        None => "[Code]".into(),
        Some(kind) if known_label(kind).is_none() && !embedded => "[Code]".into(),
        Some(kind) => draft_embed_label(kind),
    }
}

/// `formatDraftPreview` (utils/draftPreview.ts).
pub fn format_draft_preview(value: &str) -> String {
    if value.is_empty() {
        return String::new();
    }
    static MARKER: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"<<<TEST_LIVE_MOCK:[^>]+>>>").unwrap());
    static FENCE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(&format!(
            r"```(?:json|json_embed)[{WS}]*((?s:.)*?)(?:```|\z)"
        ))
        .unwrap()
    });
    static EMBED_ID: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!(r#""embed_id"[{WS}]*:"#)).unwrap());
    static TYPE_KEY: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!(r#""type"[{WS}]*:"#)).unwrap());
    let without_markers = MARKER.replace_all(value, " ");
    let with_labels = FENCE.replace_all(&without_markers, |c: &Captures| {
        format!(" {} ", label_for_reference(&c[1]))
    });
    let trimmed = js_trim(&with_labels);
    if trimmed.starts_with('{') && EMBED_ID.is_match(trimmed) && TYPE_KEY.is_match(trimmed) {
        return label_for_reference(trimmed);
    }
    collapse(&with_labels)
}

/// `convertMentionSyntaxToDisplayName`: unknown references are kept verbatim.
fn convert_mentions(text: &str, names: &DraftPreviewNames) -> String {
    static MODEL: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!("@ai-model:([^{WS}]+)")).unwrap());
    static MATE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!("@mate:([^{WS}]+)")).unwrap());
    static SKILL: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!("@skill:([^:]+):([^{WS}]+)")).unwrap());
    static FOCUS: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!("@focus:([^:]+):([^{WS}]+)")).unwrap());
    static MEMORY: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(&format!("@memory:([^:]+):([^:]+):([^{WS}]+)")).unwrap());
    let app_item = |c: &Captures, set: &HashSet<String>| {
        let (app, item) = (&c[1], &c[2]);
        if set.contains(&format!("{app}:{item}")) {
            format!(
                "@{}-{}",
                capitalize_words(app),
                capitalize_words(&item.replace('_', "-"))
            )
        } else {
            c[0].to_owned()
        }
    };
    let text = MODEL.replace_all(text, |c: &Captures| match names.models.get(&c[1]) {
        Some(name) => format!("@{}", hyphenate(name)),
        None => c[0].to_owned(),
    });
    let text = MATE.replace_all(&text, |c: &Captures| match names.mates.get(&c[1]) {
        Some(name) => format!("@{}", capitalize_words(name)),
        None => c[0].to_owned(),
    });
    let text = SKILL.replace_all(&text, |c: &Captures| app_item(c, &names.skills));
    let text = FOCUS.replace_all(&text, |c: &Captures| app_item(c, &names.focus));
    MEMORY
        .replace_all(&text, |c: &Captures| app_item(c, &names.memories))
        .into_owned()
}

/// `content` iteration as the web walk performs it; `None` where JS would throw.
fn content(node: &Value) -> Option<Vec<&Value>> {
    match node.get("content") {
        None | Some(Value::Null) => Some(Vec::new()),
        Some(Value::Array(items)) => Some(items.iter().collect()),
        // for…of over a string yields characters without a node type.
        Some(Value::String(_)) => Some(Vec::new()),
        Some(_) => None,
    }
}
fn kind(node: &Value) -> Option<&str> {
    node.get("type").and_then(Value::as_str)
}
fn attr<'a>(node: &'a Value, key: &str) -> Option<&'a str> {
    node.get("attrs")
        .and_then(|a| a.get(key))
        .and_then(Value::as_str)
        .filter(|s| !s.is_empty())
}
fn embed_token(node: &Value) -> Option<String> {
    attr(node, "type").map(draft_embed_label)
}
fn paragraph(node: &Value, names: &DraftPreviewNames, tokens: &mut Vec<String>) -> Option<()> {
    for child in content(node)? {
        if child.is_null() {
            return None;
        }
        match kind(child) {
            Some("text") => {
                let text = match child.get("text") {
                    None | Some(Value::Null) => "",
                    Some(Value::String(text)) => text.as_str(),
                    Some(_) => return None,
                };
                let converted = convert_mentions(text, names);
                let trimmed = js_trim(&converted);
                if !trimmed.is_empty() {
                    tokens.push(trimmed.to_owned());
                }
            }
            Some("embed") => tokens.extend(embed_token(child)),
            Some("aiModelMention") => {
                if let Some(id) = attr(child, "modelId") {
                    tokens.push(match names.models.get(id) {
                        Some(name) => format!("@{}", hyphenate(name)),
                        None => format!("@ai-model:{id}"),
                    });
                }
            }
            Some("mate") => tokens.extend(attr(child, "name").map(|name| format!("@{name}"))),
            Some("genericMention") => {
                tokens.extend(attr(child, "mentionSyntax").map(|s| convert_mentions(s, names)))
            }
            Some("hardBreak") => tokens.push(" ".into()),
            _ => {}
        }
    }
    Some(())
}
fn document_tokens(doc: &Value, names: &DraftPreviewNames) -> Option<Vec<String>> {
    let mut tokens = Vec::new();
    for node in content(doc)? {
        if node.is_null() {
            return None;
        }
        match kind(node) {
            Some("paragraph") => paragraph(node, names, &mut tokens)?,
            Some("embed") => tokens.extend(embed_token(node)),
            Some("heading") => {
                let children = match node.get("content") {
                    None | Some(Value::Null) => Vec::new(),
                    Some(Value::Array(items)) => items.iter().collect(),
                    Some(_) => return None,
                };
                let mut text = String::new();
                for child in children {
                    if child.is_null() {
                        return None;
                    }
                    if kind(child) == Some("text") {
                        match child.get("text") {
                            None | Some(Value::Null) => {}
                            Some(Value::String(value)) => text.push_str(value),
                            Some(_) => return None,
                        }
                    }
                }
                let text = js_trim(&text);
                if !text.is_empty() {
                    tokens.push(text.to_owned());
                }
            }
            Some("bulletList" | "orderedList") => {
                for item in content(node)? {
                    if item.is_null() {
                        return None;
                    }
                    for child in content(item)? {
                        if child.is_null() {
                            return None;
                        }
                        if kind(child) == Some("paragraph") {
                            paragraph(child, names, &mut tokens)?;
                        }
                    }
                }
            }
            Some("blockquote") => {
                for child in content(node)? {
                    if child.is_null() {
                        return None;
                    }
                    if kind(child) == Some("paragraph") {
                        paragraph(child, names, &mut tokens)?;
                    }
                }
            }
            _ => {}
        }
    }
    Some(tokens)
}

/// `processMarkdownForPreview`: mentions, legacy/website embeds, code placeholders.
fn markdown_text(markdown: &str, names: &DraftPreviewNames) -> String {
    static JSON_EMBED: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"```json_embed\n(?s:.*?)\n```").unwrap());
    static JSON: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"```json\n((?s:.)*?)\n```").unwrap());
    static CODE: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"```([A-Za-z0-9_]*)\n((?s:.)*?)\n```").unwrap());
    let text = convert_mentions(markdown, names);
    let text = JSON_EMBED.replace_all(&text, " [Website] ");
    let text = JSON.replace_all(&text, |c: &Captures| {
        match serde_json::from_str::<Value>(js_trim(&c[1]))
            .ok()
            .as_ref()
            .and_then(|v| v.get("type"))
            .and_then(Value::as_str)
        {
            Some(kind) if !kind.is_empty() => format!(" {} ", draft_embed_label(kind)),
            _ => c[0].to_owned(),
        }
    });
    CODE.replace_all(&text, |c: &Captures| {
        let (language, code) = (&c[1], js_trim(&c[2]));
        if !code.is_empty() {
            let first = js_trim(code.split('\n').next().unwrap_or(""));
            format!(" [Code: {}] ", truncate_units(first, 30, "..."))
        } else if !language.is_empty() {
            format!(" [{language} code] ")
        } else {
            " [code] ".into()
        }
    })
    .into_owned()
}

/// `generateDraftPreview(markdown, 100, doc)`. Empty means "no preview".
pub fn draft_preview(markdown: &str, doc: Option<&Value>, names: &DraftPreviewNames) -> String {
    let finish =
        |text: &str| truncate_units(&format_draft_preview(text), DRAFT_PREVIEW_MAX_UNITS, "...");
    if let Some(doc) = doc.filter(|doc| is_truthy(doc)) {
        if let Some(tokens) = document_tokens(doc, names) {
            if tokens.is_empty() {
                return String::new();
            }
            let cleaned = collapse(&tokens.join(" "));
            return if cleaned.is_empty() {
                String::new()
            } else {
                finish(&cleaned)
            };
        }
    }
    if markdown.is_empty() {
        return String::new();
    }
    finish(&collapse(&markdown_text(markdown, names)))
}
fn is_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        _ => true,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Shared with the web client's vitest, which proves these outputs are
    /// exactly what the TypeScript `generateDraftPreview` produces.
    const VECTORS: &str = include_str!("draft_preview_vectors.json");

    #[test]
    fn matches_every_web_generated_vector() {
        let vectors: Value = serde_json::from_str(VECTORS).unwrap();
        for case in vectors["cases"].as_array().unwrap() {
            let context = serde_json::json!({"doc": case["doc"], "models": vectors["names"]["models"],
                "mates": vectors["names"]["mates"], "skills": vectors["names"]["skills"],
                "focus": vectors["names"]["focus"], "memories": vectors["names"]["memories"]});
            let (doc, names) = parse_draft_preview_context(&context.to_string()).unwrap();
            let actual = draft_preview(case["markdown"].as_str().unwrap(), doc.as_ref(), &names);
            assert_eq!(
                actual,
                case["expected"].as_str().unwrap(),
                "vector {}",
                case["name"]
            );
        }
    }

    #[test]
    fn context_is_closed_and_bounded() {
        assert!(parse_draft_preview_context(r#"{"doc":null}"#).is_err());
        assert!(
            parse_draft_preview_context(
                r#"{"doc":null,"models":{},"mates":{},"skills":[],"focus":[],"memories":[],"x":1}"#
            )
            .is_err()
        );
        assert!(
            parse_draft_preview_context(
                r#"{"doc":null,"models":{"a":1},"mates":{},"skills":[],"focus":[],"memories":[]}"#
            )
            .is_err()
        );
        let big = format!(
            r#"{{"doc":"{}","models":{{}},"mates":{{}},"skills":[],"focus":[],"memories":[]}}"#,
            "a".repeat(MAX_DRAFT_PREVIEW_CONTEXT_BYTES)
        );
        assert!(parse_draft_preview_context(&big).is_err());
    }

    #[test]
    fn utf16_truncation_replaces_a_split_surrogate() {
        let text = format!("{}😀b", "a".repeat(99));
        assert_eq!(
            truncate_units(&text, 100, "..."),
            format!("{}\u{FFFD}...", "a".repeat(99))
        );
        assert_eq!(truncate_units("short", 100, "..."), "short");
    }
}
