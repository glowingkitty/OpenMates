//! Account Export V1 archive assembly on the shared Rust core `transfer` unit.
//!
//! Ports the pure half of `createAccountExportV1Zip` in
//! `frontend/packages/ui/src/services/accountExportService.ts`: manifest
//! sanitizing, the secret-field and secret-value guards, README, report, domain
//! JSON, per-chat YAML and Markdown. It returns the ordered `{path, content}`
//! entries; the page keeps fetching chunks, the byte writing of the zip, the size
//! limit and the download. Output is byte-identical to the TypeScript service
//! (JavaScript number text, `JSON.stringify` layout, its YAML quirks).
//! Parity: `web_transfer_account_export_ts_vectors.json`.
use super::export::{array_field, field, parse};
use super::yaml::{Node, js_number_string};
use crate::account::imports_parse::js_is_space;
use serde_json::json;

/// Field names that must never appear in an export (TS `FORBIDDEN_FIELD_NAMES`).
const FORBIDDEN_FIELDS: [&str; 34] = [
    "access_token",
    "api_key",
    "anonymous_encrypted_chat_key",
    "backup_code_hash",
    "chat_key",
    "chat_key_wrappers",
    "credential_secret",
    "device_key",
    "embed_key",
    "embed_key_wrappers",
    "encrypted_chat_key",
    "encrypted_embed_key",
    "encrypted_master_key",
    "encrypted_plan_key",
    "encrypted_project_key",
    "encrypted_task_key",
    "encrypted_workflow_secret_key",
    "key_wrappers",
    "lookup_hash",
    "master_key",
    "plan_key",
    "password_hash",
    "private_key",
    "project_key",
    "raw_key",
    "refresh_token",
    "share_key",
    "shared_encrypted_chat_key",
    "signing_secret",
    "task_key",
    "token_hash",
    "totp_seed",
    "webhook_secret",
    "workflow_secret_key",
];

/// Redaction categories printed in the report.
const REDACTIONS: [&str; 5] = [
    "api_credentials",
    "authentication_tokens",
    "key_material",
    "password_and_recovery_hashes",
    "webhook_secrets",
];

fn is_word(b: u8) -> bool {
    b.is_ascii_alphanumeric()
}

/// `/-----BEGIN [A-Z ]*PRIVATE KEY-----/`.
fn has_private_key_block(text: &str) -> bool {
    const OPEN: &str = "-----BEGIN ";
    const CLOSE: &str = "PRIVATE KEY-----";
    text.match_indices(OPEN).any(|(at, _)| {
        let rest = &text[at + OPEN.len()..];
        let run = rest
            .bytes()
            .take_while(|b| b.is_ascii_uppercase() || *b == b' ')
            .count();
        (0..=run).any(|start| rest[start..].starts_with(CLOSE))
    })
}

/// `/(?:^|[^a-z0-9])sk-(?:api|proj|live|test)[-_a-z0-9]{6,}/i`.
fn has_secret_key_token(text: &str) -> bool {
    let bytes = text.as_bytes();
    let lower: Vec<u8> = bytes.to_ascii_lowercase();
    (0..lower.len()).any(|at| {
        if !lower[at..].starts_with(b"sk-") || (at > 0 && is_word(bytes[at - 1])) {
            return false;
        }
        let rest = &lower[at + 3..];
        ["api", "proj", "live", "test"].iter().any(|word| {
            rest.starts_with(word.as_bytes())
                && rest[word.len()..]
                    .iter()
                    .take_while(|b| b.is_ascii_alphanumeric() || **b == b'-' || **b == b'_')
                    .count()
                    >= 6
        })
    })
}

/// `/#key=[A-Za-z0-9_-]{8,}/`.
fn has_share_key_fragment(text: &str) -> bool {
    text.match_indices("#key=").any(|(at, tag)| {
        text.as_bytes()[at + tag.len()..]
            .iter()
            .take_while(|b| b.is_ascii_alphanumeric() || **b == b'-' || **b == b'_')
            .count()
            >= 8
    })
}

fn has_secret_value(text: &str) -> bool {
    has_private_key_block(text) || has_secret_key_token(text) || has_share_key_fragment(text)
}

/// `new RegExp("(^|[^A-Za-z0-9_])['\"]?FIELD['\"]?\\s*:", "i")`.
fn mentions_field(text: &str, name: &str) -> bool {
    let bytes = text.as_bytes();
    let lower = text.to_ascii_lowercase();
    lower.match_indices(name).any(|(at, _)| {
        if at > 0 && (is_word(bytes[at - 1]) || bytes[at - 1] == b'_') {
            return false;
        }
        let mut rest = &text[at + name.len()..];
        if rest.starts_with(['\'', '"']) {
            rest = &rest[1..];
        }
        rest.trim_start_matches(js_is_space).starts_with(':')
    })
}

/// `assertAccountExportTextSafe`: the thrown message, if any.
fn text_problem(content: &str, path: &str) -> Option<String> {
    if has_secret_value(content) {
        return Some(format!(
            "Account export file {path} contains forbidden secret-like content"
        ));
    }
    FORBIDDEN_FIELDS
        .iter()
        .find(|name| mentions_field(content, name))
        .map(|name| format!("Account export file {path} contains forbidden secret field '{name}'"))
}

/// `assertAccountExportPayloadSafe`: first secret-like value or field, in
/// `Object.entries` order.
fn payload_problem(node: &Node, path: &str) -> Option<String> {
    match node {
        Node::Str(text) if has_secret_value(text) => Some(format!(
            "Account export contains forbidden secret-like value at {path}"
        )),
        Node::Array(items) => items
            .iter()
            .enumerate()
            .find_map(|(i, item)| payload_problem(item, &format!("{path}[{i}]"))),
        Node::Object(entries) => entries.iter().find_map(|(key, child)| {
            if FORBIDDEN_FIELDS.contains(&key.to_lowercase().as_str()) {
                Some(format!(
                    "Account export contains forbidden secret field '{key}' at {path}"
                ))
            } else {
                payload_problem(child, &format!("{path}.{key}"))
            }
        }),
        _ => None,
    }
}

fn nullish(node: Option<&Node>) -> Option<&Node> {
    node.filter(|n| !matches!(n, Node::Null))
}

/// JavaScript `String(value)` of a JSON value.
fn js_string(node: &Node) -> String {
    match node {
        Node::Null => "null".into(),
        Node::Bool(b) => b.to_string(),
        Node::Num(n) => js_number_string(*n),
        Node::Str(s) | Node::Raw(s) => s.clone(),
        Node::Array(items) => items
            .iter()
            .map(|i| {
                if matches!(i, Node::Null) {
                    String::new()
                } else {
                    js_string(i)
                }
            })
            .collect::<Vec<_>>()
            .join(","),
        Node::Object(_) => "[object Object]".into(),
    }
}

/// `String(value ?? fallback)`.
fn string_or(node: Option<&Node>, fallback: &str) -> String {
    nullish(node).map_or_else(|| fallback.to_string(), js_string)
}

fn record(node: Option<&Node>) -> Option<&Node> {
    node.filter(|n| matches!(n, Node::Object(_)))
}

fn text(value: &str) -> Node {
    Node::Str(value.to_string())
}

/// `safeArchiveSegment`: `[A-Za-z0-9._-]` only, other runs as `-`, never empty.
fn safe_segment(value: &str) -> String {
    let mut out = String::new();
    let mut in_run = false;
    for c in value.trim_matches(js_is_space).chars() {
        if c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-') {
            out.push(c);
            in_run = false;
        } else if !in_run {
            out.push('-');
            in_run = true;
        }
    }
    let cleaned = out.trim_matches('-');
    if cleaned.is_empty() {
        "unknown".into()
    } else {
        cleaned.to_string()
    }
}

fn quote_yaml(value: &str) -> String {
    let needs = value.contains(':')
        || value.contains('#')
        || value.starts_with(['{', '['])
        || matches!(value, "" | "true" | "false" | "null");
    if needs {
        format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
    } else {
        value.to_string()
    }
}

/// `serializeArchiveYaml` (a different, simpler emitter than the chat YAML).
fn archive_yaml(entries: &[(String, Node)], indent: usize) -> String {
    let pad = "  ".repeat(indent);
    let mut out = String::new();
    for (key, val) in entries {
        match val {
            Node::Null => out.push_str(&format!("{pad}{key}: null\n")),
            Node::Bool(_) | Node::Num(_) | Node::Raw(_) => {
                out.push_str(&format!("{pad}{key}: {}\n", js_string(val)))
            }
            Node::Str(s) if s.contains('\n') => {
                let lines: Vec<String> = s.split('\n').map(|l| format!("{pad}  {l}")).collect();
                out.push_str(&format!("{pad}{key}: |\n{}\n", lines.join("\n")));
            }
            Node::Str(s) => out.push_str(&format!("{pad}{key}: {}\n", quote_yaml(s))),
            Node::Array(items) => {
                out.push_str(&format!("{pad}{key}:\n"));
                for item in items {
                    match item {
                        Node::Object(inner) => {
                            // The TypeScript emitter leaves a trailing space after the dash.
                            out.push_str(&format!("{pad}- \n{}", archive_yaml(inner, indent + 2)));
                        }
                        Node::Str(s) => out.push_str(&format!("{pad}- {}\n", quote_yaml(s))),
                        other => out.push_str(&format!("{pad}- {}\n", js_string(other))),
                    }
                }
            }
            Node::Object(inner) => {
                out.push_str(&format!("{pad}{key}:\n{}", archive_yaml(inner, indent + 1)))
            }
        }
    }
    out
}

/// `JSON.stringify(value, null, 2)` of a JSON-derived value.
fn pretty_json(node: &Node, level: usize) -> String {
    let pad = "  ".repeat(level + 1);
    let end = "  ".repeat(level);
    match node {
        Node::Null => "null".into(),
        Node::Bool(b) => b.to_string(),
        Node::Num(n) if n.is_finite() => js_number_string(*n),
        Node::Num(_) | Node::Raw(_) => "null".into(),
        Node::Str(s) => json!(s).to_string(),
        Node::Array(items) if items.is_empty() => "[]".into(),
        Node::Array(items) => {
            let body: Vec<String> = items
                .iter()
                .map(|i| format!("{pad}{}", pretty_json(i, level + 1)))
                .collect();
            format!("[\n{}\n{end}]", body.join(",\n"))
        }
        Node::Object(entries) if entries.is_empty() => "{}".into(),
        Node::Object(entries) => {
            let body: Vec<String> = entries
                .iter()
                .map(|(k, v)| format!("{pad}{}: {}", json!(k), pretty_json(v, level + 1)))
                .collect();
            format!("{{\n{}\n{end}}}", body.join(",\n"))
        }
    }
}

/// Position of a JavaScript property key: canonical array indices come first in
/// ascending order, every other key keeps insertion order.
fn index_key(key: &str) -> Option<u32> {
    let canonical = key == "0" || (!key.starts_with('0') && !key.is_empty());
    if !canonical || !key.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    key.parse::<u32>().ok().filter(|n| *n != u32::MAX)
}

fn js_order(entries: Vec<(String, Node)>) -> Vec<(String, Node)> {
    let (mut indexed, rest): (Vec<_>, Vec<_>) = entries
        .into_iter()
        .partition(|(k, _)| index_key(k).is_some());
    indexed.sort_by_key(|(k, _)| index_key(k));
    indexed.extend(rest);
    indexed
}

/// Object assignment: replaces a present key in place, else appends.
fn assign(entries: &mut Vec<(String, Node)>, key: &str, value: Node) {
    match entries.iter_mut().find(|(k, _)| k == key) {
        Some(slot) => slot.1 = value,
        None => entries.push((key.to_string(), value)),
    }
}

/// `collectAccountExportDomainPayloads`: payload objects grouped by safe domain.
fn domain_payloads(chunks: &[Node]) -> Vec<(String, Vec<Node>)> {
    let mut grouped: Vec<(String, Vec<Node>)> = Vec::new();
    for chunk in chunks {
        let domain = safe_segment(&string_or(chunk.get("domain"), "unknown"));
        let mut merged = vec![
            (
                "chunk_id".to_string(),
                nullish(chunk.get("chunk_id"))
                    .cloned()
                    .unwrap_or(Node::Null),
            ),
            (
                "sequence".to_string(),
                nullish(chunk.get("sequence"))
                    .cloned()
                    .unwrap_or(Node::Null),
            ),
            (
                "status".to_string(),
                nullish(chunk.get("status")).cloned().unwrap_or(Node::Null),
            ),
        ];
        let payload = chunk.get("payload");
        match payload {
            Some(Node::Object(entries)) => {
                for (key, value) in entries {
                    assign(&mut merged, key, value.clone());
                }
            }
            other => {
                let value = nullish(other).cloned().unwrap_or(Node::Null);
                assign(&mut merged, "value", value);
            }
        }
        let node = Node::Object(js_order(merged));
        match grouped.iter_mut().find(|(d, _)| *d == domain) {
            Some((_, list)) => list.push(node),
            None => grouped.push((domain, vec![node])),
        }
    }
    let (domains, lists): (Vec<_>, Vec<_>) = grouped.into_iter().unzip();
    let ordered = js_order(
        domains
            .into_iter()
            .zip(lists.into_iter().map(Node::Array))
            .collect(),
    );
    ordered
        .into_iter()
        .map(|(d, list)| match list {
            Node::Array(items) => (d, items),
            _ => (d, Vec::new()),
        })
        .collect()
}

fn readme(export: &Node, manifest: &Node, exported_at: &str) -> String {
    let domains: Vec<String> = match manifest.get("selected_domains") {
        Some(Node::Array(items)) => items.iter().map(js_string).collect(),
        _ => Vec::new(),
    };
    let mut lines = vec![
        "# OpenMates Account Export".to_string(),
        String::new(),
        format!("Export ID: {}", string_or(export.get("export_id"), "unknown")),
        format!("Status: {}", string_or(export.get("status"), "unknown")),
        format!("Schema: {}", string_or(manifest.get("schema_version"), "account-export-v1")),
        format!("Exported at: {exported_at}"),
        String::new(),
        "## Contents".into(),
        String::new(),
        "- `manifest.yml` records selected domains, filters, and domain status.".into(),
        "- `export-report.yml` summarizes completion, failures, and redacted categories.".into(),
        "- `domains/` contains one JSON file per exported domain.".into(),
        "- `chats/` contains one Markdown and one YAML file per chat when chat rows include readable content.".into(),
        String::new(),
        "## Selected Domains".into(),
        String::new(),
    ];
    if domains.is_empty() {
        lines.push("- none".into());
    } else {
        lines.extend(domains.iter().map(|d| format!("- {d}")));
    }
    lines.push(String::new());
    lines.push("Reusable credentials, token hashes, private keys, and raw secrets are intentionally excluded.".into());
    lines.push(String::new());
    lines.join("\n")
}

fn report(export: &Node, manifest: &Node) -> Vec<(String, Node)> {
    let rep = record(manifest.get("report"));
    let rep_get = |key: &str| rep.and_then(|r| r.get(key));
    let status = nullish(export.get("status"))
        .or_else(|| nullish(rep_get("status")))
        .cloned()
        .unwrap_or_else(|| text("unknown"));
    let array_or_empty = |node: Option<&Node>| match node {
        Some(array @ Node::Array(_)) => array.clone(),
        _ => Node::Array(Vec::new()),
    };
    vec![
        (
            "export_id".into(),
            nullish(export.get("export_id"))
                .cloned()
                .unwrap_or(Node::Null),
        ),
        ("status".into(), status),
        (
            "selected_domains".into(),
            array_or_empty(manifest.get("selected_domains")),
        ),
        ("failures".into(), array_or_empty(rep_get("failures"))),
        (
            "redacted_secret_categories".into(),
            Node::Array(REDACTIONS.iter().map(|c| text(c)).collect()),
        ),
        (
            "partial_requires_acceptance".into(),
            Node::Bool(rep_get("partial_requires_acceptance").is_some_and(Node::truthy)),
        ),
    ]
}

fn chat_markdown(chat: &Node) -> String {
    let title = ["title", "name", "id", "chat_id"]
        .iter()
        .find_map(|k| nullish(chat.get(k)))
        .map_or_else(|| "Untitled Chat".to_string(), js_string);
    let mut lines = vec![format!("# {title}"), String::new()];
    if let Some(Node::Str(summary)) = chat.get("summary") {
        let trimmed = summary.trim_matches(js_is_space);
        if !trimmed.is_empty() {
            lines.extend([
                "## Summary".to_string(),
                String::new(),
                trimmed.to_string(),
                String::new(),
            ]);
        }
    }
    match chat.get("messages") {
        Some(Node::Array(messages)) if !messages.is_empty() => {
            lines.extend(["## Messages".to_string(), String::new()]);
            for message in messages.iter().filter(|m| matches!(m, Node::Object(_))) {
                let role = ["role", "sender"]
                    .iter()
                    .find_map(|k| nullish(message.get(k)))
                    .map_or_else(|| "message".to_string(), js_string);
                let content = ["content", "text"]
                    .iter()
                    .find_map(|k| nullish(message.get(k)))
                    .map_or_else(String::new, js_string);
                lines.extend([format!("### {role}"), String::new(), content, String::new()]);
            }
        }
        _ => lines.extend([
            "No readable message records were included in this export chunk.".to_string(),
            String::new(),
        ]),
    }
    format!("{}\n", lines.join("\n"))
}

/// `sanitizeAccountExportManifest`: fixed redaction categories, then the guard.
fn sanitize(manifest: &Node) -> Result<Node, String> {
    let mut copy = manifest.clone();
    if let Node::Object(entries) = &mut copy
        && let Some((_, Node::Object(report))) = entries.iter_mut().find(|(k, _)| k == "report")
        && let Some((_, redactions)) = report.iter_mut().find(|(k, _)| k == "redactions")
        && matches!(redactions, Node::Array(_))
    {
        *redactions = Node::Array(REDACTIONS.iter().map(|c| text(c)).collect());
    }
    match payload_problem(&copy, "$manifest") {
        Some(message) => Err(message),
        None => Ok(copy),
    }
}

fn entries_of(node: &Node) -> &[(String, Node)] {
    match node {
        Node::Object(entries) => entries,
        _ => &[],
    }
}

struct Archive {
    files: Vec<serde_json::Value>,
}

impl Archive {
    /// `writeSafeZipText`: refuses secret-like text before it is added.
    fn write(&mut self, path: &str, content: String) -> Result<(), String> {
        if let Some(message) = text_problem(&content, path) {
            return Err(message);
        }
        self.files.push(json!({"path": path, "content": content}));
        Ok(())
    }
}

/// Ordered archive entries of an Account Export V1 download.
///
/// Input `{export:{export_id,status}, manifest, chunks:[{chunk_id,domain,
/// sequence,status,payload}], exportedAt}` (manifest as received from the API).
/// Output `{"kind":"ok","entries":[{path,content}]}`, or
/// `{"kind":"error","message"}` with the exact text the TypeScript service throws
/// for a forbidden secret field or value.
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn account_export_archive_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let export = field(&input, "export")?;
    let exported_at = match field(&input, "exportedAt")? {
        Node::Str(at) => at.clone(),
        _ => return Err("protocol".into()),
    };
    let chunks = array_field(&input, "chunks")?;
    let manifest = match sanitize(field(&input, "manifest")?) {
        Ok(manifest) => manifest,
        Err(message) => return Ok(json!({"kind": "error", "message": message}).to_string()),
    };
    match build_entries(export, &manifest, chunks, &exported_at) {
        Ok(files) => Ok(json!({"kind": "ok", "entries": files}).to_string()),
        Err(message) => Ok(json!({"kind": "error", "message": message}).to_string()),
    }
}

fn build_entries(
    export: &Node,
    manifest: &Node,
    chunks: &[Node],
    exported_at: &str,
) -> Result<Vec<serde_json::Value>, String> {
    let mut zip = Archive { files: Vec::new() };
    zip.write("README.md", readme(export, manifest, exported_at))?;
    zip.write("manifest.yml", archive_yaml(entries_of(manifest), 0))?;
    zip.write("manifest.json", format!("{}\n", pretty_json(manifest, 0)))?;
    zip.write(
        "export-report.yml",
        archive_yaml(&report(export, manifest), 0),
    )?;
    let domains = domain_payloads(chunks);
    for (domain, payloads) in &domains {
        let file = if payloads.len() == 1 {
            payloads[0].clone()
        } else {
            Node::Object(vec![("chunks".into(), Node::Array(payloads.clone()))])
        };
        zip.write(
            &format!("domains/{}.json", safe_segment(domain)),
            format!("{}\n", pretty_json(&file, 0)),
        )?;
    }
    let chat_payloads = domains
        .iter()
        .find(|(d, _)| d == "chats")
        .map(|(_, p)| p.as_slice())
        .unwrap_or(&[]);
    let chats = chat_payloads.iter().filter_map(|p| match p.get("items") {
        Some(Node::Array(items)) => Some(items),
        _ => None,
    });
    for (index, chat) in chats
        .flatten()
        .filter(|c| matches!(c, Node::Object(_)))
        .enumerate()
    {
        let id = ["id", "chat_id"]
            .iter()
            .find_map(|k| nullish(chat.get(k)))
            .map_or_else(|| format!("chat-{}", index + 1), js_string);
        let id = safe_segment(&id);
        let messages = match chat.get("messages") {
            Some(list @ Node::Array(_)) => list.clone(),
            _ => Node::Array(Vec::new()),
        };
        let data = vec![
            ("chat".to_string(), chat.clone()),
            ("messages".to_string(), messages),
        ];
        zip.write(&format!("chats/{id}.yml"), archive_yaml(&data, 0))?;
        zip.write(&format!("chats/{id}.md"), chat_markdown(chat))?;
    }
    Ok(zip.files)
}
