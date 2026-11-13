//! Web chat ZIP export planning on the shared Rust core `transfer` unit.
//!
//! Ports the pure half of `frontend/packages/ui/src/services/zipExportService.ts`:
//! the zip entry layout of a single or bulk chat download (metadata, Markdown,
//! code, transcript, image, audio and PDF paths), the chat Markdown document,
//! code-file and application-project download names and the dated zip names. The
//! page keeps embed loading, key use, TipTap serialization, blob fetching, the
//! JSZip byte writing and the download. Entries that carry page data are
//! references (`src`) the page resolves; Rust-built text is returned inline.
//! Parity: `web_transfer_zip_ts_vectors.json` (generated from the TS service).
use super::export::{
    PiiMapping, array_field, field, opt_text, parse, pii_mappings, restore_pii, text_field,
    timestamp_ms,
};
use super::yaml::Node;
use crate::account::imports_parse::{iso_from_ms, js_is_space};
use serde_json::{Value, json};

/// `filename.replace(/\.[^.]+$/, "")`: drops the last extension, but only when
/// at least one non-dot character follows its dot (a trailing dot stays).
pub(super) fn strip_extension(name: &str) -> &str {
    match name.rfind('.') {
        Some(dot) if dot + 1 < name.len() => &name[..dot],
        _ => name,
    }
}

/// `getFileExtensionForLanguage`. The TypeScript lookup also resolves the
/// inherited object keys `constructor` and `__proto__` to non-string values; no
/// code language uses those names, so they are not reproduced.
fn extension_for_language(language: &str) -> String {
    let lower = language.to_lowercase();
    let mapped = match lower.as_str() {
        "javascript" => "js",
        "typescript" => "ts",
        "python" => "py",
        "rust" => "rs",
        "ruby" => "rb",
        "kotlin" => "kt",
        "yaml" => "yml",
        "markdown" => "md",
        "bash" | "shell" => "sh",
        "dockerfile" => "Dockerfile",
        _ => return lower,
    };
    mapped.to_string()
}

/// `(iso)` as `YYYY-MM-DDTHH:MM:SS.mmmZ` for a page timestamp node; the error is
/// the `Invalid time value` message `Date#toISOString` throws.
fn strict_iso(value: &Node) -> Result<String, String> {
    match value {
        Node::Num(n) => iso_from_ms(timestamp_ms(*n)),
        _ => Err("Invalid time value".into()),
    }
}

/// `convertMessageToMarkdown`: empty text when the timestamp is invalid or the
/// page could not serialize the body (`content: null`).
fn message_markdown(message: &Node, mappings: &[PiiMapping]) -> Result<String, String> {
    let Ok(timestamp) = strict_iso(field(message, "createdAt")?) else {
        return Ok(String::new());
    };
    let role = if text_field(message, "role")? == "assistant" {
        "Assistant"
    } else {
        "You"
    };
    let content = match field(message, "content")? {
        Node::Str(text) if mappings.is_empty() => text.clone(),
        Node::Str(text) => restore_pii(text, mappings),
        Node::Null => return Ok(String::new()),
        _ => return Err("protocol".into()),
    };
    Ok(format!("## {role} - {timestamp}\n\n{content}\n\n"))
}

/// `convertChatToMarkdown`: title header, creation line, then every message.
fn chat_markdown(input: &Node) -> Result<String, String> {
    let chat = field(input, "chat")?;
    let mappings = pii_mappings(input)?;
    let Ok(created) = strict_iso(field(chat, "createdAt")?) else {
        // The TypeScript catch block returns an empty document.
        return Ok(String::new());
    };
    let mut out = String::new();
    if let Some(title) = opt_text(chat, "title")?.filter(|title| !title.is_empty()) {
        out.push_str(&format!("# {title}\n\n"));
    }
    out.push_str(&format!("*Created: {created}*\n\n---\n\n"));
    for message in array_field(input, "messages")? {
        out.push_str(&message_markdown(message, &mappings)?);
    }
    Ok(out)
}

fn text_entry(path: String, text: String) -> Value {
    json!({"path": path, "text": text})
}

fn src_entry(path: String, src: Value) -> Value {
    json!({"path": path, "src": src})
}

fn names(input: &Node, key: &str) -> Result<Vec<String>, String> {
    array_field(input, key)?
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::to_string)
                .ok_or_else(|| "protocol".to_string())
        })
        .collect()
}

/// The zip path of a code embed: its own file path, else `code/<filename>`, else
/// `code/<embed id>.<language extension>`.
fn code_path(code: &Node) -> Result<String, String> {
    if let Some(path) = opt_text(code, "filePath")?.filter(|p| !p.is_empty()) {
        return Ok(path.to_string());
    }
    if let Some(name) = opt_text(code, "filename")?.filter(|n| !n.is_empty()) {
        return Ok(format!("code/{name}"));
    }
    let embed_id = text_field(code, "embedId")?;
    let ext = extension_for_language(text_field(code, "language")?);
    Ok(format!("code/{embed_id}.{ext}"))
}

/// Entry layout of `downloadChatAsZip` / one chat folder of `downloadChatsAsZip`,
/// in the order the TypeScript service writes them.
///
/// Input: `{filename, completenessJson, chat:{title,createdAt}, messages:[{role,
/// createdAt, content}], pii, code:[{filePath,filename,language,embedId}],
/// transcripts, images, generatedAudio, staticFiles, audio, pdfs:[{folderName,
/// pages}]}` where the name lists hold the page-resolved file names.
/// Output: `{"kind":"ok","base","zipName","entries"}`; each entry is
/// `{path,text}` or `{path,src:[group,index,page?]}`.
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn zip_chat_plan_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let filename = text_field(&input, "filename")?;
    let base = strip_extension(filename);
    let mut entries = Vec::new();
    if let Some(metadata) = opt_text(&input, "completenessJson")? {
        entries.push(text_entry(
            "export-metadata.json".into(),
            metadata.to_string(),
        ));
    }
    entries.push(src_entry(format!("{base}.yml"), json!(["yaml"])));
    entries.push(text_entry(format!("{base}.md"), chat_markdown(&input)?));
    for (index, code) in array_field(&input, "code")?.iter().enumerate() {
        entries.push(src_entry(code_path(code)?, json!(["code", index])));
    }
    let groups = [
        ("transcripts", "transcripts/", "transcript"),
        ("images", "images/", "image"),
        ("generatedAudio", "generated-audio/", "generatedAudio"),
        ("staticFiles", "static-files/", "staticFile"),
    ];
    for (key, prefix, group) in groups {
        for (index, name) in names(&input, key)?.iter().enumerate() {
            entries.push(src_entry(format!("{prefix}{name}"), json!([group, index])));
        }
    }
    for (index, name) in names(&input, "audio")?.iter().enumerate() {
        entries.push(src_entry(
            format!("uploads/audio/{name}"),
            json!(["audio", index]),
        ));
        // The sidecar is always written, empty when no transcript exists yet.
        let sidecar = format!("{}_transcript.txt", strip_extension(name));
        entries.push(src_entry(
            format!("uploads/audio/{sidecar}"),
            json!(["audioTranscript", index]),
        ));
    }
    for (index, pdf) in array_field(&input, "pdfs")?.iter().enumerate() {
        let folder = text_field(pdf, "folderName")?;
        for (page, name) in names(pdf, "pages")?.iter().enumerate() {
            entries.push(src_entry(
                format!("uploads/pdfs/{folder}/{name}"),
                json!(["pdf", index, page]),
            ));
        }
    }
    Ok(
        json!({"kind": "ok", "base": base, "zipName": format!("{base}.zip"), "entries": entries})
            .to_string(),
    )
}

/// `<prefix>_YYYY-MM-DD_HH-MM-SS.zip` from the page clock's ISO timestamp.
fn dated_zip_name(prefix: &str, now_iso: &str) -> String {
    let stamp: String = now_iso
        .chars()
        .take(19)
        .map(|c| if c == ':' || c == '-' { '-' } else { c })
        .collect::<String>()
        .replacen('T', "_", 1);
    format!("{prefix}_{stamp}.zip")
}

/// Last path segment after `/` or `\`.
fn basename(path: &str) -> &str {
    path.rsplit(['/', '\\']).next().unwrap_or(path)
}

/// Download names of `downloadCodeFilesAsZip` / `downloadCodeFile`.
///
/// Input `{nowIso, files:[{filename, headerFilename, language}]}` (`language` is
/// the header-parsed language the page resolved). Output
/// `{"kind":"ok","zipName","names"}`: the explicit file name, else the header
/// name (basename each), else `code_snippet.<ext>`; later case-insensitive
/// duplicates get `_<position+1>` before the extension (a single pass, like TS).
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn zip_code_files_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let now = text_field(&input, "nowIso")?;
    let mut used: Vec<String> = Vec::new();
    let mut out = Vec::new();
    for (index, file) in array_field(&input, "files")?.iter().enumerate() {
        let explicit = opt_text(file, "filename")?.filter(|n| !n.is_empty());
        let header = opt_text(file, "headerFilename")?.filter(|n| !n.is_empty());
        let name = match explicit.or(header) {
            Some(path) => basename(path).to_string(),
            None => format!(
                "code_snippet.{}",
                extension_for_language(text_field(file, "language")?)
            ),
        };
        let mut unique = name.clone();
        if used.contains(&name.to_lowercase()) {
            unique = match name.rfind('.').filter(|dot| *dot > 0) {
                Some(dot) => format!("{}_{}{}", &name[..dot], index + 1, &name[dot..]),
                None => format!("{name}_{}", index + 1),
            };
        }
        used.push(unique.to_lowercase());
        out.push(unique);
    }
    Ok(
        json!({"kind": "ok", "zipName": dated_zip_name("code_files", now), "names": out})
            .to_string(),
    )
}

/// `safeApplicationZipPath`: forward slashes, trimmed segments, no `.`/`..`.
fn safe_application_path(path: &str) -> String {
    let parts: Vec<&str> = path
        .split(['/', '\\'])
        .map(|part| part.trim_matches(js_is_space))
        .filter(|part| !part.is_empty() && *part != "." && *part != "..")
        .collect();
    if parts.is_empty() {
        "application-file.txt".into()
    } else {
        parts.join("/")
    }
}

/// `safeDownloadName`: lowercase `[a-z0-9._-]` with runs of anything else as `-`.
fn safe_download_name(value: &str) -> String {
    let lower = value.trim_matches(js_is_space).to_lowercase();
    let mut out = String::new();
    let mut in_run = false;
    for c in lower.chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, '.' | '_' | '-') {
            out.push(c);
            in_run = false;
        } else if !in_run {
            out.push('-');
            in_run = true;
        }
    }
    let trimmed = out.trim_matches('-');
    if trimmed.is_empty() {
        "application".into()
    } else {
        trimmed.to_string()
    }
}

/// Paths and zip name of `downloadApplicationProjectZip`.
///
/// Input `{appName, paths}`; output `{"kind":"ok","zipName","paths"}`.
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn zip_application_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let app = opt_text(&input, "appName")?
        .filter(|n| !n.is_empty())
        .unwrap_or("application");
    let paths: Vec<String> = names(&input, "paths")?
        .iter()
        .map(|p| safe_application_path(p))
        .collect();
    Ok(json!({"kind": "ok", "zipName": format!("{}.zip", safe_download_name(app)), "paths": paths}).to_string())
}

/// Bulk chat download name `chats_<date>_<time>.zip` from the page clock.
///
/// Input `{nowIso}`; output `{"kind":"ok","zipName"}`.
///
/// # Errors
/// `protocol` when the input is not the documented shape.
pub fn zip_bulk_name_json(input: &str) -> Result<String, String> {
    let input = parse(input)?;
    let name = dated_zip_name("chats", text_field(&input, "nowIso")?);
    Ok(json!({"kind": "ok", "zipName": name}).to_string())
}
