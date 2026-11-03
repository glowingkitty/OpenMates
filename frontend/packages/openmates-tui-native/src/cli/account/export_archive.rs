//! Account Export V1 archive writer (port of npm accountExportArchive.ts):
//! README, manifest.yml/json, export report, per-domain JSON and per-chat
//! YAML/Markdown, written as a directory or a zip (optionally encrypted as the
//! npm "OMZIP1" scrypt + AES-256-GCM container). Every file passes the same
//! secret scan before it is written, and payloads are scanned on download.
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};

const FORBIDDEN_FIELDS: &[&str] = &[
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
pub(super) const REDACTION_CATEGORIES: &[&str] = &[
    "api_credentials",
    "authentication_tokens",
    "key_material",
    "password_and_recovery_hashes",
    "webhook_secrets",
];

fn value_patterns() -> &'static [regex::Regex; 3] {
    static PATTERNS: std::sync::OnceLock<[regex::Regex; 3]> = std::sync::OnceLock::new();
    PATTERNS.get_or_init(|| {
        [
            regex::Regex::new(r"-----BEGIN [A-Z ]*PRIVATE KEY-----").expect("static"),
            regex::Regex::new(r"(?i)(?:^|[^a-z0-9])sk-(?:api|proj|live|test)[-_a-z0-9]{6,}")
                .expect("static"),
            regex::Regex::new(r"#key=[A-Za-z0-9_-]{8,}").expect("static"),
        ]
    })
}
fn field_pattern(field: &str) -> regex::Regex {
    regex::Regex::new(&format!(
        r#"(?i)(^|[^A-Za-z0-9_])['"]?{}['"]?\s*:"#,
        regex::escape(field)
    ))
    .expect("escaped field pattern")
}

/// npm assertAccountExportPayloadSafe.
pub(super) fn assert_payload_safe(value: &Value, path: &str) -> Result<(), String> {
    match value {
        Value::String(text) => {
            if value_patterns().iter().any(|p| p.is_match(text)) {
                return Err(format!(
                    "Account export contains forbidden secret-like value at {path}"
                ));
            }
            Ok(())
        }
        Value::Array(items) => items
            .iter()
            .enumerate()
            .try_for_each(|(i, item)| assert_payload_safe(item, &format!("{path}[{i}]"))),
        Value::Object(object) => {
            for (key, child) in object {
                let normalized = key.to_lowercase();
                if normalized.starts_with("encrypted_")
                    || FORBIDDEN_FIELDS.contains(&normalized.as_str())
                {
                    return Err(format!(
                        "Account export contains forbidden secret field '{key}' at {path}"
                    ));
                }
                assert_payload_safe(child, &format!("{path}.{key}"))?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}
/// npm assertAccountExportTextSafe.
fn assert_text_safe(content: &str, relative: &str) -> Result<(), String> {
    if value_patterns().iter().any(|p| p.is_match(content)) {
        return Err(format!(
            "Account export file {relative} contains forbidden secret-like content"
        ));
    }
    for field in FORBIDDEN_FIELDS {
        if field_pattern(field).is_match(content) {
            return Err(format!(
                "Account export file {relative} contains forbidden secret field '{field}'"
            ));
        }
    }
    if regex::Regex::new(r#"(?i)(^|[^A-Za-z0-9_])['"]?encrypted_[A-Za-z0-9_]*['"]?\s*:"#)
        .expect("static")
        .is_match(content)
    {
        return Err(format!(
            "Account export file {relative} contains forbidden encrypted storage field"
        ));
    }
    Ok(())
}
/// npm sanitizeAccountExportManifest.
pub(super) fn sanitize_manifest(manifest: &Value) -> Result<Value, String> {
    let mut copy = manifest.clone();
    if let Some(report) = copy.get_mut("report").and_then(Value::as_object_mut)
        && report.get("redactions").is_some_and(Value::is_array)
    {
        report.insert("redactions".into(), json!(REDACTION_CATEGORIES));
    }
    assert_payload_safe(&copy, "$manifest")?;
    Ok(copy)
}
/// npm safeArchiveSegment.
fn segment(value: &str) -> String {
    let mut out = String::new();
    let mut dash = false;
    for c in value.trim().chars() {
        if c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-') {
            out.push(c);
            dash = false;
        } else if !dash {
            out.push('-');
            dash = true;
        }
    }
    let trimmed = out.trim_matches('-').to_owned();
    if trimmed.is_empty() {
        "unknown".into()
    } else {
        trimmed
    }
}
fn js_text(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        Value::Null => "null".into(),
        other => other.to_string(),
    }
}
fn quote_yaml(value: &str) -> String {
    let needs = value.contains(':')
        || value.contains('#')
        || value.starts_with('{')
        || value.starts_with('[')
        || value.is_empty()
        || matches!(value, "true" | "false" | "null");
    if needs {
        format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
    } else {
        value.into()
    }
}
/// npm serializeArchiveYaml.
fn yaml(data: &Map<String, Value>, indent: usize) -> String {
    let pad = "  ".repeat(indent);
    let mut out = String::new();
    for (key, value) in data {
        match value {
            Value::Null => out.push_str(&format!("{pad}{key}: null\n")),
            Value::Bool(_) | Value::Number(_) => out.push_str(&format!("{pad}{key}: {value}\n")),
            Value::String(text) if text.contains('\n') => out.push_str(&format!(
                "{pad}{key}: |\n{}\n",
                text.split('\n')
                    .map(|l| format!("{pad}  {l}"))
                    .collect::<Vec<_>>()
                    .join("\n")
            )),
            Value::String(text) => out.push_str(&format!("{pad}{key}: {}\n", quote_yaml(text))),
            Value::Array(items) => {
                out.push_str(&format!("{pad}{key}:\n"));
                for item in items {
                    match item {
                        Value::Object(object) => {
                            out.push_str(&format!("{pad}- \n{}", yaml(object, indent + 2)))
                        }
                        Value::String(text) => {
                            out.push_str(&format!("{pad}- {}\n", quote_yaml(text)))
                        }
                        other => out.push_str(&format!("{pad}- {}\n", js_text(other))),
                    }
                }
            }
            Value::Object(object) => {
                out.push_str(&format!("{pad}{key}:\n{}", yaml(object, indent + 1)))
            }
        }
    }
    out
}
fn readme(bundle: &Value) -> String {
    let domains = bundle["manifest"]["selected_domains"]
        .as_array()
        .map(|d| {
            d.iter()
                .map(|v| format!("- {}", js_text(v)))
                .collect::<Vec<_>>()
        })
        .filter(|d| !d.is_empty())
        .unwrap_or_else(|| vec!["- none".into()]);
    let now = time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .unwrap_or_default();
    let mut lines = vec![
        "# OpenMates Account Export".to_owned(),
        String::new(),
        format!("Export ID: {}", bundle["export"]["export_id"].as_str().map(str::to_owned).unwrap_or_else(|| "unknown".into())),
        format!("Status: {}", bundle["export"]["status"].as_str().unwrap_or("unknown")),
        format!("Schema: {}", bundle["manifest"]["schema_version"].as_str().unwrap_or("account-export-v1")),
        format!("Exported at: {now}"),
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
    lines.extend(domains);
    lines.push(String::new());
    lines.push("Reusable credentials, token hashes, private keys, and raw secrets are intentionally excluded.".into());
    lines.push(String::new());
    lines.join("\n")
}
fn report(bundle: &Value) -> Map<String, Value> {
    let report = bundle["manifest"]["report"]
        .as_object()
        .cloned()
        .unwrap_or_default();
    let mut out = Map::new();
    out.insert(
        "export_id".into(),
        bundle["export"]
            .get("export_id")
            .cloned()
            .unwrap_or(Value::Null),
    );
    out.insert(
        "status".into(),
        bundle["export"]
            .get("status")
            .filter(|v| !v.is_null())
            .cloned()
            .or_else(|| report.get("status").filter(|v| !v.is_null()).cloned())
            .unwrap_or(json!("unknown")),
    );
    out.insert(
        "selected_domains".into(),
        bundle["manifest"]["selected_domains"]
            .as_array()
            .map(|a| json!(a))
            .unwrap_or(json!([])),
    );
    out.insert(
        "failures".into(),
        report
            .get("failures")
            .filter(|v| v.is_array())
            .cloned()
            .unwrap_or(json!([])),
    );
    out.insert(
        "redacted_secret_categories".into(),
        json!(REDACTION_CATEGORIES),
    );
    out.insert(
        "partial_requires_acceptance".into(),
        json!(
            report
                .get("partial_requires_acceptance")
                .is_some_and(|v| !matches!(v, Value::Null | Value::Bool(false))
                    && *v != json!(0)
                    && *v != json!(""))
        ),
    );
    out
}
/// npm collectAccountExportDomainPayloads, preserving first-seen domain order.
fn domains(chunks: &[Value]) -> Vec<(String, Vec<Value>)> {
    let mut grouped: Vec<(String, Vec<Value>)> = vec![];
    for chunk in chunks {
        let domain = segment(
            &chunk
                .get("domain")
                .map(js_text)
                .unwrap_or_else(|| "unknown".into()),
        );
        let mut entry = Map::new();
        for key in ["chunk_id", "sequence", "status"] {
            entry.insert(key.into(), chunk.get(key).cloned().unwrap_or(Value::Null));
        }
        match chunk.get("payload") {
            Some(Value::Object(payload)) => entry.extend(payload.clone()),
            other => {
                entry.insert("value".into(), other.cloned().unwrap_or(Value::Null));
            }
        }
        match grouped.iter_mut().find(|(d, _)| *d == domain) {
            Some((_, list)) => list.push(Value::Object(entry)),
            None => grouped.push((domain, vec![Value::Object(entry)])),
        }
    }
    grouped
}
fn chat_markdown(chat: &Map<String, Value>) -> String {
    let title = ["title", "name", "id", "chat_id"]
        .iter()
        .find_map(|k| chat.get(*k).filter(|v| !v.is_null()).map(js_text))
        .unwrap_or_else(|| "Untitled Chat".into());
    let mut lines = vec![format!("# {title}"), String::new()];
    if let Some(summary) = chat
        .get("summary")
        .and_then(Value::as_str)
        .filter(|s| !s.trim().is_empty())
    {
        lines.extend([
            "## Summary".into(),
            String::new(),
            summary.trim().to_owned(),
            String::new(),
        ]);
    }
    let messages = chat
        .get("messages")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    if messages.is_empty() {
        lines.extend([
            "No readable message records were included in this export chunk.".into(),
            String::new(),
        ]);
    } else {
        lines.extend(["## Messages".into(), String::new()]);
        for message in messages.iter().filter_map(Value::as_object) {
            let role = message
                .get("role")
                .or(message.get("sender"))
                .filter(|v| !v.is_null())
                .map(js_text)
                .unwrap_or_else(|| "message".into());
            let content = message
                .get("content")
                .or(message.get("text"))
                .filter(|v| !v.is_null())
                .map(js_text)
                .unwrap_or_default();
            lines.extend([format!("### {role}"), String::new(), content, String::new()]);
        }
    }
    format!("{}\n", lines.join("\n"))
}
/// Ordered archive entries (relative path, UTF-8 content), all secret-scanned.
pub(super) fn entries(bundle: &Value) -> Result<Vec<(String, String)>, String> {
    let mut files = vec![];
    let mut add = |path: String, content: String| -> Result<(), String> {
        assert_text_safe(&content, &path)?;
        files.push((path, content));
        Ok(())
    };
    let manifest = bundle["manifest"].as_object().cloned().unwrap_or_default();
    add("README.md".into(), readme(bundle))?;
    add("manifest.yml".into(), yaml(&manifest, 0))?;
    add(
        "manifest.json".into(),
        format!(
            "{}\n",
            serde_json::to_string_pretty(&bundle["manifest"]).unwrap_or_default()
        ),
    )?;
    add("export-report.yml".into(), yaml(&report(bundle), 0))?;
    let grouped = domains(
        bundle["chunks"]
            .as_array()
            .map(Vec::as_slice)
            .unwrap_or(&[]),
    );
    for (domain, payloads) in &grouped {
        let file = if payloads.len() == 1 {
            payloads[0].clone()
        } else {
            json!({"chunks":payloads})
        };
        add(
            format!("domains/{}.json", segment(domain)),
            format!(
                "{}\n",
                serde_json::to_string_pretty(&file).unwrap_or_default()
            ),
        )?;
    }
    let chats = grouped
        .iter()
        .find(|(d, _)| d == "chats")
        .map(|(_, payloads)| payloads.clone())
        .unwrap_or_default();
    let mut rows = vec![];
    for payload in &chats {
        if let Some(items) = payload["items"].as_array() {
            rows.extend(items.iter().filter_map(Value::as_object).cloned());
        }
    }
    for (index, chat) in rows.iter().enumerate() {
        let id = segment(
            &chat
                .get("id")
                .or(chat.get("chat_id"))
                .filter(|v| !v.is_null())
                .map(js_text)
                .unwrap_or_else(|| format!("chat-{}", index + 1)),
        );
        let mut document = Map::new();
        document.insert("chat".into(), Value::Object(chat.clone()));
        document.insert(
            "messages".into(),
            chat.get("messages")
                .filter(|m| m.is_array())
                .cloned()
                .unwrap_or(json!([])),
        );
        add(format!("chats/{id}.yml"), yaml(&document, 0))?;
        add(format!("chats/{id}.md"), chat_markdown(chat))?;
    }
    Ok(files)
}

/// Minimal deflate zip (UTF-8 names, no zip64; export archives are small).
pub(super) fn zip(files: &[(String, String)]) -> Result<Vec<u8>, String> {
    use std::io::Write;
    let (time, date) = {
        let now = time::OffsetDateTime::now_utc();
        (
            ((now.hour() as u16) << 11) | ((now.minute() as u16) << 5) | (now.second() as u16 / 2),
            (((now.year() - 1980).max(0) as u16) << 9)
                | ((u8::from(now.month()) as u16) << 5)
                | now.day() as u16,
        )
    };
    let mut out = vec![];
    let mut central = vec![];
    for (name, content) in files {
        let mut crc = flate2::Crc::new();
        crc.update(content.as_bytes());
        let mut encoder =
            flate2::write::DeflateEncoder::new(vec![], flate2::Compression::default());
        encoder
            .write_all(content.as_bytes())
            .map_err(|e| e.to_string())?;
        let compressed = encoder.finish().map_err(|e| e.to_string())?;
        let offset = u32::try_from(out.len())
            .map_err(|_| "Account export archive is too large.".to_owned())?;
        let header = |signature: u32, central_entry: bool| {
            let mut h = vec![];
            h.extend(signature.to_le_bytes());
            if central_entry {
                h.extend(20u16.to_le_bytes());
            }
            h.extend(20u16.to_le_bytes());
            h.extend(0x0800u16.to_le_bytes());
            h.extend(8u16.to_le_bytes());
            h.extend(time.to_le_bytes());
            h.extend(date.to_le_bytes());
            h.extend(crc.sum().to_le_bytes());
            h.extend((compressed.len() as u32).to_le_bytes());
            h.extend((content.len() as u32).to_le_bytes());
            h.extend((name.len() as u16).to_le_bytes());
            h.extend(0u16.to_le_bytes());
            if central_entry {
                // Comment length, disk number and internal attributes, then
                // external attributes: 46-byte central entries before the name.
                h.extend([0u8; 6]);
                h.extend(0u32.to_le_bytes());
                h.extend(offset.to_le_bytes());
            }
            h.extend(name.as_bytes());
            h
        };
        out.extend(header(0x0403_4b50, false));
        out.extend(&compressed);
        central.extend(header(0x0201_4b50, true));
    }
    let start = out.len() as u32;
    let size = central.len() as u32;
    out.extend(central);
    out.extend(0x0605_4b50u32.to_le_bytes());
    out.extend([0u8; 4]);
    out.extend((files.len() as u16).to_le_bytes());
    out.extend((files.len() as u16).to_le_bytes());
    out.extend(size.to_le_bytes());
    out.extend(start.to_le_bytes());
    out.extend(0u16.to_le_bytes());
    Ok(out)
}
/// npm encryptZipBuffer: "OMZIP1\n<len>\n<header-json><ciphertext>".
pub(super) fn encrypt_zip(zip: &[u8], password: &str) -> Result<Vec<u8>, String> {
    use aes_gcm::{Aes256Gcm, KeyInit, Nonce, aead::Aead};
    use base64::{Engine, engine::general_purpose::STANDARD};
    use rand::RngCore;
    let mut salt = [0u8; 16];
    let mut iv = [0u8; 12];
    rand::rngs::OsRng.fill_bytes(&mut salt);
    rand::rngs::OsRng.fill_bytes(&mut iv);
    let mut key = zeroize::Zeroizing::new([0u8; 32]);
    let params = scrypt::Params::new(14, 8, 1, 32).map_err(|e| e.to_string())?;
    scrypt::scrypt(password.as_bytes(), &salt, &params, key.as_mut()).map_err(|e| e.to_string())?;
    let mut sealed = Aes256Gcm::new_from_slice(key.as_ref())
        .map_err(|e| e.to_string())?
        .encrypt(Nonce::from_slice(&iv), zip)
        .map_err(|_| "Account export encryption failed.".to_owned())?;
    let tag = sealed.split_off(sealed.len() - 16);
    let header = json!({"magic":"OMZIP1","version":1,"kdf":"scrypt","cipher":"aes-256-gcm",
        "salt":STANDARD.encode(salt),"iv":STANDARD.encode(iv),"tag":STANDARD.encode(tag)})
    .to_string();
    let mut out = format!("OMZIP1\n{}\n", header.len()).into_bytes();
    out.extend(header.as_bytes());
    out.extend(sealed);
    Ok(out)
}
/// npm writeAccountExportArchive; returns `{output, format, files[, encrypted]}`.
pub(super) fn write(
    bundle: &Value,
    directory: bool,
    password: Option<&str>,
    output: Option<&str>,
) -> Result<Value, String> {
    let export_id = segment(
        &bundle["export"]["export_id"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| {
                format!(
                    "export-{}",
                    time::OffsetDateTime::now_utc().unix_timestamp() * 1000
                )
            }),
    );
    if password.is_some() && directory {
        return Err("Password-protected account export is only supported for zip format.".into());
    }
    let target = output.map(PathBuf::from).unwrap_or_else(|| {
        let name = if directory {
            format!("openmates-account-export-{export_id}")
        } else if password.is_some() {
            format!("openmates-account-export-{export_id}.zip.enc")
        } else {
            format!("openmates-account-export-{export_id}.zip")
        };
        std::env::current_dir().unwrap_or_default().join(name)
    });
    let files = entries(bundle)?;
    let count = files.len();
    let display = target.to_string_lossy().into_owned();
    if directory {
        for (relative, content) in &files {
            let path = target.join(relative);
            create_parent(&path)?;
            std::fs::write(&path, content).map_err(|e| e.to_string())?;
        }
        return Ok(json!({"output":display,"format":"directory","files":count}));
    }
    let archive = zip(&files)?;
    let bytes = match password {
        Some(password) => encrypt_zip(&archive, password)?,
        None => archive,
    };
    create_parent(&target)?;
    std::fs::write(&target, bytes).map_err(|e| e.to_string())?;
    let mut result = json!({"output":display,"format":"zip","files":count});
    if password.is_some() {
        result["encrypted"] = json!(true);
    }
    Ok(result)
}
fn create_parent(path: &Path) -> Result<(), String> {
    match path.parent().filter(|p| !p.as_os_str().is_empty()) {
        Some(parent) => std::fs::create_dir_all(parent).map_err(|e| e.to_string()),
        None => Ok(()),
    }
}

#[cfg(test)]
#[path = "export_archive_tests.rs"]
mod tests;
