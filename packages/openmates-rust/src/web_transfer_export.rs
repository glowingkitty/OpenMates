//! Web chat export (Settings -> chat download / copy) on the shared Rust core
//! `transfer` unit: filename and timestamp helpers, PII restore, message and chat
//! YAML building. Port of the pure half of
//! `frontend/packages/ui/src/services/chatExportService.ts`; the page keeps
//! hydration, the metadata cache, decryption, TipTap serialization and embed
//! loading and sends the resolved values. Every entry point takes and returns
//! JSON text; malformed payloads answer the fixed code `protocol`.
//! Parity: `web_transfer_export_ts_vectors.json` (generated from the TS service).
use super::yaml::{Node, to_yaml_string};
use crate::account::imports_parse::{iso_from_ms, js_is_space};
use serde_json::json;

fn protocol<E>(_: E) -> String {
    "protocol".into()
}
fn parse(text: &str) -> Result<Node, String> {
    serde_json::from_str(text).map_err(protocol)
}
fn field<'a>(node: &'a Node, key: &str) -> Result<&'a Node, String> {
    node.get(key).ok_or_else(|| "protocol".to_string())
}
fn text_field<'a>(node: &'a Node, key: &str) -> Result<&'a str, String> {
    field(node, key)?.as_str().ok_or_else(|| "protocol".into())
}
fn array_field<'a>(node: &'a Node, key: &str) -> Result<&'a [Node], String> {
    match field(node, key)? {
        Node::Array(items) => Ok(items),
        _ => Err("protocol".into()),
    }
}
/// Optional member that is absent, `null` or a string.
fn opt_text<'a>(node: &'a Node, key: &str) -> Result<Option<&'a str>, String> {
    match node.get(key) {
        None | Some(Node::Null) => Ok(None),
        Some(Node::Str(text)) => Ok(Some(text)),
        Some(_) => Err("protocol".into()),
    }
}
fn member(node: &Node, key: &str) -> Node {
    node.get(key).cloned().unwrap_or(Node::Null)
}

/// Seconds-vs-milliseconds heuristic shared by every export timestamp.
fn timestamp_ms(value: f64) -> f64 {
    if value < 1e12 { value * 1000.0 } else { value }
}

/// `safeTimestampToISO`: `null` for anything that is not a valid instant.
fn safe_iso(value: &Node) -> Option<String> {
    match value {
        Node::Num(n) if !n.is_nan() => iso_from_ms(timestamp_ms(*n)).ok(),
        _ => None,
    }
}

/// `formatTimestamp` (embed timestamps): falsy values are `null`.
fn embed_iso(value: &Node) -> Option<String> {
    if value.truthy() {
        safe_iso(value)
    } else {
        None
    }
}

fn opt_node(value: Option<String>) -> Node {
    value.map_or(Node::Null, Node::Str)
}

/// A title/summary candidate is used only when it is a non-empty string.
fn candidate<'a>(node: &'a Node, key: &str) -> Result<Option<&'a str>, String> {
    Ok(opt_text(node, key)?.filter(|text| !text.is_empty()))
}

/// Sanitized filename title: invalid filename characters removed, at most 50
/// UTF-16 units, trimmed. A cut inside a surrogate pair becomes U+FFFD, which is
/// what the browser writes for the lone surrogate the TypeScript string holds.
fn sanitize_title(title: &str) -> String {
    let kept: Vec<u16> = title
        .chars()
        .filter(|c| !matches!(c, '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*'))
        .collect::<String>()
        .encode_utf16()
        .take(50)
        .collect();
    String::from_utf16_lossy(&kept)
        .trim_matches(js_is_space)
        .to_string()
}

/// `generateChatFilename`: `YYYY-MM-DD_HH-MM-SS_<title>.<extension>` from the
/// chat creation time (seconds or milliseconds) and the page-resolved titles.
///
/// Input: `{createdAt, titleDecrypted, titlePlain, extension}`. Output:
/// `{"kind":"ok","filename"}`, or `{"kind":"error","message":"Invalid time value"}`
/// where the TypeScript service throws a `RangeError`.
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn export_filename_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let extension = text_field(&input, "extension")?;
    let decrypted = candidate(&input, "titleDecrypted")?;
    let plain = candidate(&input, "titlePlain")?;
    let created = match field(&input, "createdAt")? {
        Node::Num(n) => iso_from_ms(timestamp_ms(*n)),
        _ => Err("Invalid time value".to_string()),
    };
    let iso = match created {
        Ok(iso) => iso,
        Err(message) => return Ok(json!({"kind": "error", "message": message}).to_string()),
    };
    let date: String = iso
        .chars()
        .take(19)
        .map(|c| if c == ':' || c == '-' { '-' } else { c })
        .collect::<String>()
        .replacen('T', "_", 1);
    let title = decrypted
        .or(plain)
        .map_or_else(|| "Untitled Chat".to_string(), sanitize_title);
    Ok(json!({"kind": "ok", "filename": format!("{date}_{title}.{extension}")}).to_string())
}

/// Whether a stored draft is cleartext (non-authenticated sessionStorage draft)
/// or ciphertext the page must decrypt, using the service's heuristic: no
/// `encrypted:` marker, no `v1:` prefix and under 1000 UTF-16 units.
///
/// Input `{draft}`; output `{"kind":"ok","cleartext":bool}`.
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn export_draft_kind_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let draft = text_field(&input, "draft")?;
    let cleartext = !draft.contains("encrypted:")
        && !draft.starts_with("v1:")
        && draft.encode_utf16().count() < 1000;
    Ok(json!({"kind": "ok", "cleartext": cleartext}).to_string())
}

/// `[placeholder, original]` PII mapping in UTF-16 units (JavaScript semantics).
type PiiMapping = (Vec<u16>, Vec<u16>);

/// `text.split(pattern).join(replacement)` over UTF-16 units.
fn split_join(text: &[u16], pattern: &[u16], replacement: &[u16]) -> Vec<u16> {
    let mut out = Vec::with_capacity(text.len());
    if pattern.is_empty() {
        // `"abc".split("")` splits into code units, so the original lands between them.
        for (index, unit) in text.iter().enumerate() {
            if index > 0 {
                out.extend_from_slice(replacement);
            }
            out.push(*unit);
        }
        return out;
    }
    let mut index = 0;
    while index < text.len() {
        if text[index..].starts_with(pattern) {
            out.extend_from_slice(replacement);
            index += pattern.len();
        } else {
            out.push(text[index]);
            index += 1;
        }
    }
    out
}

fn is_word(unit: u16) -> bool {
    u8::try_from(unit).is_ok_and(|b| b.is_ascii_alphanumeric() || b == b'_')
}

/// `text.replace(/(^|[^A-Za-z0-9_\[])BARE(?![A-Za-z0-9_\]])/g, prefix => prefix + original)`.
fn replace_bare(text: &[u16], bare: &[u16], original: &[u16]) -> Vec<u16> {
    let bare_at = |at: usize| {
        text[at..].starts_with(bare) && {
            let after = text.get(at + bare.len()).copied();
            after.is_none_or(|unit| !is_word(unit) && unit != u16::from(b']'))
        }
    };
    let mut out = Vec::with_capacity(text.len());
    let mut index = 0;
    while index < text.len() {
        if index == 0 && bare_at(0) {
            out.extend_from_slice(original);
            index = bare.len();
        } else if !is_word(text[index]) && text[index] != u16::from(b'[') && bare_at(index + 1) {
            out.push(text[index]);
            out.extend_from_slice(original);
            index += 1 + bare.len();
        } else {
            out.push(text[index]);
            index += 1;
        }
    }
    out
}

/// `restorePIIInText`: mappings apply in order to the running result, so an
/// original containing a later placeholder is expanded again (unlike the CLI's
/// one-pass `privacy::restore`; the export keeps the TypeScript behavior).
pub(crate) fn restore_pii(text: &str, mappings: &[PiiMapping]) -> String {
    let mut result: Vec<u16> = text.encode_utf16().collect();
    for (placeholder, original) in mappings {
        result = split_join(&result, placeholder, original);
        let is_bracketed = placeholder.len() >= 2
            && placeholder.first() == Some(&u16::from(b'['))
            && placeholder.last() == Some(&u16::from(b']'));
        if is_bracketed && placeholder.len() > 2 {
            result = replace_bare(&result, &placeholder[1..placeholder.len() - 1], original);
        }
    }
    String::from_utf16_lossy(&result)
}

/// The export's PII options: `None` when no mappings apply or PII stays hidden.
fn pii_mappings(input: &Node) -> Result<Vec<PiiMapping>, String> {
    let options = match input.get("pii") {
        None | Some(Node::Null) => return Ok(Vec::new()),
        Some(options) => options,
    };
    // Hidden mode keeps the placeholders the database stores.
    if !matches!(field(options, "hidden")?, Node::Bool(false)) {
        return Ok(Vec::new());
    }
    array_field(options, "mappings")?
        .iter()
        .map(|mapping| {
            let units = |key| text_field(mapping, key).map(|t| t.encode_utf16().collect());
            Ok((units("placeholder")?, units("original")?))
        })
        .collect()
}

fn object(entries: Vec<(&str, Node)>) -> Node {
    Node::Object(
        entries
            .into_iter()
            .map(|(k, v)| (k.to_string(), v))
            .collect(),
    )
}

/// `convertMessageToYaml` over a page-resolved message.
fn message_node(
    message: &Node,
    exported_at: &str,
    mappings: &[PiiMapping],
) -> Result<Node, String> {
    let role = member(message, "role");
    let completed_at =
        safe_iso(&member(message, "createdAt")).unwrap_or_else(|| exported_at.into());
    let assistant = role.as_str() == Some("assistant");
    let mut data = vec![("role", role), ("completed_at", Node::Str(completed_at))];
    if assistant {
        let category = member(message, "category");
        let category = if category.truthy() {
            category
        } else {
            member(message, "assistantCategory")
        };
        if category.truthy() {
            data.push(("assistant_category", category));
        }
    }
    let content = opt_text(message, "content")?.unwrap_or("");
    let content = if mappings.is_empty() {
        content.to_string()
    } else {
        restore_pii(content, mappings)
    };
    data.push(("content", Node::Str(content)));
    if assistant {
        if let Some(thinking) = candidate(message, "thinking")? {
            data.push(("thinking", Node::Str(thinking.into())));
        }
        if member(message, "hasThinking").truthy() {
            data.push(("has_thinking", Node::Bool(true)));
        }
        let tokens = member(message, "thinkingTokenCount");
        if tokens.truthy() {
            data.push(("thinking_tokens", tokens));
        }
    }
    Ok(object(data))
}

/// One collected embed: either the decoded record or the page's error marker.
fn embed_node(embed: &Node) -> Result<Node, String> {
    match text_field(embed, "kind")? {
        "ok" => {
            let mut data = vec![
                ("embed_id", member(embed, "embed_id")),
                ("type", member(embed, "type")),
                ("status", member(embed, "status")),
                ("content", member(embed, "content")),
                (
                    "createdAt",
                    opt_node(embed_iso(&member(embed, "createdAt"))),
                ),
                (
                    "updatedAt",
                    opt_node(embed_iso(&member(embed, "updatedAt"))),
                ),
            ];
            let preview = member(embed, "text_preview");
            if preview.truthy() {
                data.push(("text_preview", preview));
            }
            Ok(object(data))
        }
        "error" => Ok(object(vec![
            ("embed_id", member(embed, "embed_id")),
            ("type", member(embed, "type")),
            ("status", Node::Str("error".into())),
            ("content", Node::Null),
            ("error", Node::Str(text_field(embed, "error")?.into())),
        ])),
        _ => Err("protocol".into()),
    }
}

fn checkpoint_node(checkpoint: &Node) -> Node {
    let estimate = member(checkpoint, "summary_token_estimate");
    let summary = member(checkpoint, "summary");
    object(vec![
        ("id", member(checkpoint, "id")),
        (
            "created_at",
            opt_node(safe_iso(&member(checkpoint, "created_at"))),
        ),
        (
            "compressed_up_to",
            opt_node(safe_iso(&member(checkpoint, "compressed_up_to_timestamp"))),
        ),
        (
            "compressed_message_count",
            member(checkpoint, "compressed_message_count"),
        ),
        ("summary_token_estimate", estimate),
        ("summary", summary),
    ])
}

/// `convertChatToYaml` over the page-resolved chat: title and summary candidates
/// (decrypted preferred, plaintext demo fallback), draft, hydration completeness
/// and checkpoints, messages (content already Markdown, thinking already
/// decrypted), collected embeds, optional PII restore and the share link.
///
/// Output: `{"kind":"ok","yaml"}`; the YAML is byte-identical to the TypeScript
/// service's string.
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn export_yaml_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let exported_at = text_field(&input, "exportedAt")?;
    let messages = array_field(&input, "messages")?;
    let mappings = pii_mappings(&input)?;
    let titles = field(&input, "titles")?;
    let summaries = field(&input, "summaries")?;
    let count = Node::Num(messages.len() as f64);
    let completeness = match input.get("completeness") {
        None | Some(Node::Null) => object(vec![
            ("status", Node::Str("complete".into())),
            ("requested_message_count", count.clone()),
            ("hydrated_message_count", count.clone()),
            ("checkpoint_count", Node::Num(0.0)),
            ("warnings", Node::Array(Vec::new())),
        ]),
        Some(completeness) => completeness.clone(),
    };
    let pick = |node: &Node| -> Result<Node, String> {
        Ok(opt_node(
            candidate(node, "decrypted")?
                .or(candidate(node, "plain")?)
                .map(String::from),
        ))
    };
    let mut meta = vec![
        ("title", pick(titles)?),
        ("exported_at", Node::Str(exported_at.into())),
        ("message_count", count),
        (
            "draft",
            opt_node(opt_text(&input, "draft")?.map(String::from)),
        ),
        ("summary", pick(summaries)?),
        ("export_completeness", completeness),
    ];
    if let Some(link) = opt_text(&input, "link")? {
        meta.push(("link", Node::Str(link.into())));
    }
    let yaml_messages = messages
        .iter()
        .map(|message| message_node(message, exported_at, &mappings))
        .collect::<Result<Vec<_>, _>>()?;
    let embeds = array_field(&input, "embeds")?
        .iter()
        .map(embed_node)
        .collect::<Result<Vec<_>, _>>()?;
    let checkpoints = array_field(&input, "checkpoints")?
        .iter()
        .map(checkpoint_node)
        .collect();
    let data = vec![
        ("chat".to_string(), object(meta)),
        ("messages".to_string(), Node::Array(yaml_messages)),
        ("embeds".to_string(), Node::Array(embeds)),
        (
            "compression_checkpoints".to_string(),
            Node::Array(checkpoints),
        ),
    ];
    Ok(json!({"kind": "ok", "yaml": to_yaml_string(&data)}).to_string())
}
