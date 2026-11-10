//! Read operations of the filesystem host: `list`, `read_text`,
//! `read_image_chunk` and `read_file_chunk`, plus the 200 KiB response bound.
//!
//! Mirrors `listRemoteAccessDirectory`, `readRemoteAccessTextFile`,
//! `readRemoteAccessImageChunk`, `readRemoteAccessFileChunk` and
//! `serializeRemoteAccessSuccessResponse` in `remoteAccess.ts`. Result keys keep
//! npm's spelling (`sizeBytes`, `nextCursor`, `expected_base`, ...) because the
//! requester parses them. Every call reloads the path policy and re-resolves
//! the canonical root, so a policy edit applies to the next request.

use super::fs_safe::{
    canonical_root, ctime_ms, mtime_ms, open_inside, refuse_hardlink, relative_posix,
    resolve_approved,
};
use super::path_policy::{PathPolicy, PolicyOptions};
use super::{HostError, HostResult, NameOrder, sha256_hex};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::io::{Read, Seek, SeekFrom};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

pub(crate) const DEFAULT_MAX_DIRECTORY_ENTRIES: usize = 500;
pub(crate) const DEFAULT_MAX_READ_BYTES: usize = 200 * 1024;
pub(crate) const DEFAULT_MAX_READ_LINES: usize = 4_000;
pub(crate) const RESULT_MAX_BYTES: usize = 200 * 1024;
const MAX_REMOTE_IMAGE_BYTES: u64 = 2 * 1024 * 1024;
const IMAGE_CHUNK_BYTES: u64 = 128 * 1024;
const DOWNLOAD_CHUNK_BYTES: u64 = 128 * 1024;
pub(crate) const BINARY_PROBE_BYTES: usize = 8 * 1024;
const MAX_CHILD_SUMMARY_ENTRIES: usize = 200;
const MAX_CHILD_SUMMARY_TOTAL: usize = 2_000;
const MAX_FOLDER_SUMMARIES: usize = 100;
/// npm `BINARY_EXTENSIONS`.
pub(crate) const BINARY_EXTENSIONS: &[&str] = &[
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".pdf", ".zip", ".gz", ".tar", ".mp3",
    ".mp4", ".mov",
];

/// One approved source root plus the private state directory.
#[derive(Clone, Debug)]
pub(crate) struct HostRoot {
    pub(crate) root: PathBuf,
    pub(crate) state_dir: PathBuf,
}

impl HostRoot {
    pub(crate) fn canonical(&self) -> HostResult<PathBuf> {
        canonical_root(&self.root, &self.state_dir)
    }
    pub(crate) fn policy(
        &self,
        root: &Path,
        targets: &[&str],
        nested: bool,
    ) -> HostResult<PathPolicy> {
        PathPolicy::load(
            root,
            &PolicyOptions {
                state_dir: &self.state_dir,
                trusted_private: &[],
                targets,
                discover_nested: nested,
            },
        )
    }
}

/// npm `isBinaryPath`.
pub(crate) fn is_binary_path(path: &str) -> bool {
    let lower = path.to_lowercase();
    BINARY_EXTENSIONS.iter().any(|ext| lower.ends_with(ext))
}

fn extension_is_binary(name: &str) -> bool {
    // npm `extname(name).toLowerCase()`: a leading-dot-only name has no extension.
    match name.rfind('.') {
        Some(index) if index > 0 => BINARY_EXTENSIONS.contains(&name[index..].to_lowercase().as_str()),
        _ => false,
    }
}

/// `list`: one directory page with child summaries.
///
/// # Errors
/// `protected_path` for private/ignored directories, `invalid_path` for
/// missing paths or non-directories, `operation_failed` for bad bounds.
pub(crate) fn list(host: &HostRoot, args: &Value) -> HostResult<Value> {
    let relative = args["path"].as_str().unwrap_or(".");
    let root = host.canonical()?;
    let policy = host.policy(&root, &[relative], false)?;
    let directory = resolve_approved(&root, relative)?;
    let directory_path = relative_posix(&root, &directory)?;
    if !directory_path.is_empty()
        && (policy.is_private(&directory_path, true)? || policy.is_ignored(&directory_path, true)?)
    {
        return Err(HostError::protected("Remote source directory is unavailable"));
    }
    if !std::fs::metadata(&directory).is_ok_and(|m| m.is_dir()) {
        return Err(HostError::invalid_path("Remote source path is not a directory"));
    }
    let max_entries = match &args["maxEntries"] {
        Value::Null => DEFAULT_MAX_DIRECTORY_ENTRIES,
        value => value
            .as_u64()
            .filter(|v| (1..=DEFAULT_MAX_DIRECTORY_ENTRIES as u64).contains(v))
            .map(|v| v as usize)
            .ok_or_else(|| HostError::failed("Remote directory entry limit must be between 1 and 500"))?,
    };
    let cursor = match &args["cursor"] {
        Value::Null => None,
        Value::String(c)
            if !c.is_empty()
                && c != "."
                && c != ".."
                && c.len() <= 255
                && !c.contains(['/', '\\', '\0']) =>
        {
            Some(c.clone())
        }
        _ => {
            return Err(HostError::failed(
                "Remote directory cursor must be a valid entry basename",
            ));
        }
    };
    let order = NameOrder::new()?;
    let mut names = Vec::new();
    for entry in std::fs::read_dir(&directory).map_err(|e| HostError::io("Remote directory", &e))? {
        let entry = entry.map_err(|e| HostError::io("Remote directory", &e))?;
        let Some(name) = entry.file_name().to_str().map(str::to_owned) else {
            continue;
        };
        let kind = entry
            .file_type()
            .map_err(|e| HostError::io("Remote directory", &e))?;
        names.push((name, kind));
    }
    names.sort_by(|a, b| order.compare(&a.0, &b.0));
    let mut summaries = SummaryBudget {
        entries: MAX_CHILD_SUMMARY_TOTAL,
        folders: MAX_FOLDER_SUMMARIES,
    };
    let (mut entries, mut omitted, mut excluded) = (Vec::new(), 0u64, 0u64);
    let mut last_returned: Option<String> = None;
    for (name, kind) in names {
        // A cursor is the last returned basename: skip earlier entries before
        // any policy check so only later readable entries count as omitted.
        if let Some(cursor) = &cursor
            && order.compare(&name, cursor) != std::cmp::Ordering::Greater
        {
            continue;
        }
        let entry_path = if directory_path.is_empty() {
            name.clone()
        } else {
            format!("{directory_path}/{name}")
        };
        if name.starts_with('.')
            || kind.is_symlink()
            || policy.is_ignored(&entry_path, kind.is_dir())?
            || policy.is_private(&entry_path, kind.is_dir())?
            || (!kind.is_file() && !kind.is_dir())
        {
            excluded += 1;
            continue;
        }
        let absolute = directory.join(&name);
        let stat = if kind.is_file() {
            let stat = std::fs::symlink_metadata(&absolute)
                .map_err(|e| HostError::io("Remote directory", &e))?;
            if stat.nlink() > 1 {
                excluded += 1;
                continue;
            }
            Some(stat)
        } else {
            None
        };
        if entries.len() >= max_entries {
            omitted += 1;
            continue;
        }
        let mut item = json!({
            "path": entry_path,
            "kind": if kind.is_dir() { "directory" } else { "file" },
        });
        if kind.is_file() && extension_is_binary(&name) {
            item["previewable"] = json!(false);
        }
        if let Some(stat) = stat {
            item["sizeBytes"] = json!(stat.len());
        }
        if kind.is_dir() {
            summaries.summarize(host, &root, &entry_path, &mut item);
        }
        entries.push(item);
        last_returned = Some(name);
    }
    let mut result = json!({
        "entries": entries,
        "omitted": omitted,
        "excluded": excluded,
        "truncated": omitted > 0,
    });
    if omitted > 0 {
        result["nextCursor"] = json!(last_returned);
    }
    Ok(result)
}

struct SummaryBudget {
    entries: usize,
    folders: usize,
}

impl SummaryBudget {
    /// npm `summarizeChildren`; any failure only marks the summary truncated.
    fn summarize(&mut self, host: &HostRoot, root: &Path, folder: &str, item: &mut Value) {
        if self.folders == 0 || self.entries == 0 {
            item["childSummaryTruncated"] = json!(true);
            return;
        }
        self.folders -= 1;
        match self.children(host, root, folder) {
            Ok(summary) => {
                for (key, value) in summary {
                    item[key] = value;
                }
            }
            Err(_) => item["childSummaryTruncated"] = json!(true),
        }
    }

    fn children(
        &mut self,
        host: &HostRoot,
        root: &Path,
        folder: &str,
    ) -> HostResult<Vec<(&'static str, Value)>> {
        let absolute = resolve_approved(root, folder)?;
        let policy = host.policy(root, &[folder], false)?;
        let (mut files, mut folders, mut bytes, mut truncated) = (0u64, 0u64, 0u64, false);
        let mut summary: Vec<(String, bool)> = Vec::new();
        for child in std::fs::read_dir(&absolute).map_err(|e| HostError::io("Summary", &e))? {
            if self.entries == 0 || (files + folders) as usize >= MAX_CHILD_SUMMARY_ENTRIES {
                truncated = true;
                break;
            }
            self.entries -= 1;
            let child = child.map_err(|e| HostError::io("Summary", &e))?;
            let kind = child.file_type().map_err(|e| HostError::io("Summary", &e))?;
            let Some(name) = child.file_name().to_str().map(str::to_owned) else {
                continue;
            };
            let path = format!("{folder}/{name}");
            if name.starts_with('.')
                || kind.is_symlink()
                || (!kind.is_file() && !kind.is_dir())
                || policy.is_ignored(&path, kind.is_dir())?
                || policy.is_private(&path, kind.is_dir())?
            {
                continue;
            }
            if kind.is_file() {
                let stat = std::fs::symlink_metadata(absolute.join(&name))
                    .map_err(|e| HostError::io("Summary", &e))?;
                if stat.nlink() > 1 {
                    continue;
                }
                files += 1;
                bytes += stat.len();
            } else {
                folders += 1;
            }
            summary.push((path, kind.is_dir()));
        }
        let order = NameOrder::new()?;
        summary.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| order.compare(&a.0, &b.0)));
        let children: Vec<Value> = summary
            .iter()
            .take(3)
            .map(|(path, dir)| json!({"path": path, "kind": if *dir { "directory" } else { "file" }}))
            .collect();
        Ok(vec![
            ("children", json!(children)),
            ("childFileCount", json!(files)),
            ("childFolderCount", json!(folders)),
            ("childFileSizeBytes", json!(bytes)),
            ("childSummaryTruncated", json!(truncated)),
        ])
    }
}

/// npm `normalizeBound` over a JSON argument (`remoteAccessReadLimits`).
fn bound(value: &Value, maximum: usize, label: &str) -> HostResult<usize> {
    let fail = || HostError::failed(format!("Remote source {label} limit must be between 1 and {maximum}"));
    match value {
        Value::Null => Ok(maximum),
        Value::Number(n) => n
            .as_f64()
            .filter(|v| v.fract() == 0.0 && *v >= 1.0 && *v <= maximum as f64)
            .map(|v| v as usize)
            .ok_or_else(fail),
        _ => Err(fail()),
    }
}

/// A bounded text read (npm `RemoteTextReadResult`).
pub(crate) struct TextRead {
    pub(crate) content: String,
    pub(crate) truncated: bool,
    pub(crate) size_bytes: u64,
    pub(crate) expected_base: Option<String>,
}

impl TextRead {
    pub(crate) fn to_json(&self) -> Value {
        json!({
            "content": self.content,
            "truncated": self.truncated,
            "sizeBytes": self.size_bytes,
            "lineCount": count_lines(&self.content),
            "expected_base": self.expected_base,
        })
    }
}

/// npm `countTextLines`.
pub(crate) fn count_lines(content: &str) -> usize {
    if content.is_empty() {
        return 0;
    }
    content.split('\n').count() - usize::from(content.ends_with('\n'))
}

/// `read_text` JSON arguments.
///
/// # Errors
/// See [`read_text_file`].
pub(crate) fn read_text(host: &HostRoot, args: &Value, ignored_approved: bool) -> HostResult<Value> {
    let relative = args["path"].as_str().unwrap_or(".");
    let max_bytes = bound(&args["max_bytes"], DEFAULT_MAX_READ_BYTES, "byte")?;
    let max_lines = bound(&args["max_lines"], DEFAULT_MAX_READ_LINES, "line")?;
    Ok(read_text_file(host, relative, max_bytes, max_lines, ignored_approved)?.to_json())
}

/// npm `readRemoteAccessTextFile`.
///
/// # Errors
/// `protected_path`, `ignored_path_requires_approval`, `invalid_path`,
/// `unsupported_file` (binary or invalid UTF-8) or `operation_failed`.
pub(crate) fn read_text_file(
    host: &HostRoot,
    relative: &str,
    max_bytes: usize,
    max_lines: usize,
    ignored_approved: bool,
) -> HostResult<TextRead> {
    let root = host.canonical()?;
    let normalized = relative.replace('\\', "/");
    let policy = host.policy(&root, &[&normalized], false)?;
    policy.assert_readable(&normalized, ignored_approved)?;
    let requested = resolve_approved(&root, &normalized)?;
    refuse_hardlink(&requested)?;
    let file = open_inside(&root, &requested)?;
    let stats = file.metadata().map_err(|e| HostError::io("Remote source file", &e))?;
    if !stats.is_file() {
        return Err(HostError::invalid_path("Remote source path is not a regular file"));
    }
    let to_read = stats.len().min(max_bytes as u64 + 1);
    let mut bytes = Vec::new();
    file.take(to_read)
        .read_to_end(&mut bytes)
        .map_err(|e| HostError::io("Remote source file", &e))?;
    if bytes[..bytes.len().min(BINARY_PROBE_BYTES)].contains(&0) {
        return Err(HostError::unsupported("Remote source file is binary or unsupported"));
    }
    let decoded = decode_bounded(&bytes, bytes.len().min(max_bytes), stats.len() <= max_bytes as u64)?;
    let lines: Vec<&str> = decoded.split_inclusive('\n').collect();
    let content: String = lines.iter().take(max_lines).copied().collect();
    let truncated = stats.len() > max_bytes as u64 || lines.len() > max_lines;
    Ok(TextRead {
        content,
        truncated,
        size_bytes: stats.len(),
        expected_base: (!truncated).then(|| sha256_hex(&bytes)),
    })
}

/// npm `decodeBoundedUtf8`: a byte-bounded prefix may split one code point, so
/// up to three trailing bytes may be dropped; complete files must be valid.
fn decode_bounded(bytes: &[u8], limit: usize, complete: bool) -> HostResult<String> {
    let attempts = if complete { 1 } else { 4 };
    for backoff in 0..attempts {
        if backoff > limit {
            break;
        }
        if let Ok(text) = std::str::from_utf8(&bytes[..limit - backoff]) {
            return Ok(text.to_owned());
        }
    }
    Err(HostError::unsupported("Remote source file is binary or unsupported"))
}

fn open_policy_file(host: &HostRoot, relative: &str) -> HostResult<(PathBuf, std::fs::File)> {
    let root = host.canonical()?;
    let path = relative.replace('\\', "/");
    let policy = host.policy(&root, &[&path], false)?;
    policy.assert_readable(&path, false)?;
    let requested = resolve_approved(&root, &path)?;
    refuse_hardlink(&requested)?;
    let file = open_inside(&root, &requested)?;
    Ok((requested, file))
}

fn offset_arg(args: &Value) -> Option<u64> {
    args["offset"].as_u64()
}

fn same_file(a: &std::fs::Metadata, b: &std::fs::Metadata, ctime: bool) -> bool {
    a.len() == b.len()
        && mtime_ms(a) == mtime_ms(b)
        && a.ino() == b.ino()
        && a.dev() == b.dev()
        && (!ctime || ctime_ms(a) == ctime_ms(b))
}

/// npm `readRemoteAccessImageChunk`: one 128 KiB chunk of a raster image up to 2 MiB.
///
/// # Errors
/// `unsupported_file` for non-images or oversized files; `operation_failed`
/// for a bad offset or a file that changed while reading.
pub(crate) fn read_image_chunk(host: &HostRoot, args: &Value) -> HostResult<Value> {
    let (_, mut file) = open_policy_file(host, args["path"].as_str().unwrap_or("."))?;
    let stats = file.metadata().map_err(|e| HostError::io("Remote source image", &e))?;
    if !stats.is_file() || stats.len() == 0 || stats.len() > MAX_REMOTE_IMAGE_BYTES {
        return Err(HostError::unsupported(
            "Remote source image is unsupported or exceeds the safe image limit",
        ));
    }
    let offset = offset_arg(args)
        .filter(|o| *o < stats.len() && o % IMAGE_CHUNK_BYTES == 0)
        .ok_or_else(|| HostError::failed("Remote source image offset is invalid"))?;
    let mut bytes = Vec::with_capacity(stats.len() as usize);
    (&mut file)
        .take(stats.len())
        .read_to_end(&mut bytes)
        .map_err(|e| HostError::io("Remote source image", &e))?;
    let after = file.metadata().map_err(|e| HostError::io("Remote source image", &e))?;
    if bytes.len() as u64 != stats.len() || !same_file(&stats, &after, false) {
        return Err(HostError::failed("Remote source image changed"));
    }
    let mime = raster_mime(&bytes)
        .ok_or_else(|| HostError::unsupported("Remote source image is binary or unsupported"))?;
    let end = (offset + IMAGE_CHUNK_BYTES).min(stats.len()) as usize;
    Ok(json!({
        "content_base64": STANDARD.encode(&bytes[offset as usize..end]),
        "mime_type": mime,
        "size_bytes": stats.len(),
        "offset": offset,
        "content_hash": sha256_hex(&bytes),
    }))
}

/// npm `readRemoteAccessFileChunk`: exact bytes for an explicit download.
///
/// # Errors
/// `invalid_path` for non-regular files; `operation_failed` for a bad offset
/// or a file that changed during the read.
pub(crate) fn read_file_chunk(host: &HostRoot, args: &Value) -> HostResult<Value> {
    let (_, mut file) = open_policy_file(host, args["path"].as_str().unwrap_or("."))?;
    let stats = file.metadata().map_err(|e| HostError::io("Remote source file", &e))?;
    if !stats.is_file() {
        return Err(HostError::invalid_path("Remote source path is not a regular file"));
    }
    let size = stats.len();
    let offset = offset_arg(args)
        .filter(|o| (size == 0 || *o < size) && o % DOWNLOAD_CHUNK_BYTES == 0)
        .ok_or_else(|| HostError::failed("Remote source file offset is invalid"))?;
    let length = DOWNLOAD_CHUNK_BYTES.min(size.saturating_sub(offset));
    file.seek(SeekFrom::Start(offset))
        .map_err(|e| HostError::io("Remote source file", &e))?;
    let mut bytes = Vec::with_capacity(length as usize);
    (&mut file)
        .take(length)
        .read_to_end(&mut bytes)
        .map_err(|e| HostError::io("Remote source file", &e))?;
    let after = file.metadata().map_err(|e| HostError::io("Remote source file", &e))?;
    if bytes.len() as u64 != length || !same_file(&stats, &after, true) {
        return Err(HostError::failed("Remote source file changed during download"));
    }
    // Node formats the float millisecond stamps; identity only has to stay
    // stable across the chunks of one download from this host.
    let identity = format!(
        "{}:{}:{}:{}:{}",
        stats.dev(),
        stats.ino(),
        size,
        mtime_ms(&stats),
        ctime_ms(&stats)
    );
    Ok(json!({
        "content_base64": STANDARD.encode(&bytes),
        "size_bytes": size,
        "offset": offset,
        "file_identity": sha256_hex(identity.as_bytes()),
        "chunk_hash": sha256_hex(&bytes),
    }))
}

/// npm `rasterImageMimeType`.
pub(crate) fn raster_mime(bytes: &[u8]) -> Option<&'static str> {
    if bytes.starts_with(&[137, 80, 78, 71, 13, 10, 26, 10]) {
        return Some("image/png");
    }
    if bytes.starts_with(&[255, 216, 255]) {
        return Some("image/jpeg");
    }
    if bytes.starts_with(b"GIF87a") || bytes.starts_with(b"GIF89a") {
        return Some("image/gif");
    }
    if bytes.starts_with(b"RIFF") && bytes.get(8..12) == Some(b"WEBP") {
        return Some("image/webp");
    }
    if bytes.get(4..8) == Some(b"ftyp") && matches!(bytes.get(8..12), Some(b"avif" | b"avis")) {
        return Some("image/avif");
    }
    None
}

/// npm `serializeRemoteAccessSuccessResponse`: `{"ok":true,"result":...}`
/// within 200 KiB. An oversized text read is cut to the longest prefix that
/// fits (then `truncated: true`, `expected_base: null`); anything else that
/// does not fit becomes `{"ok":false,"error":"operation_failed"}`.
pub(crate) fn serialize_success(result: Value) -> String {
    let full = json!({"ok": true, "result": result}).to_string();
    if full.len() <= RESULT_MAX_BYTES {
        return full;
    }
    let Some(content) = text_result_content(&result) else {
        return json!({"ok": false, "error": "operation_failed"}).to_string();
    };
    let units: Vec<u16> = content.encode_utf16().collect();
    let bounded = |length: usize| -> String {
        let mut end = length.min(units.len());
        if end > 0 && (0xd800..=0xdbff).contains(&units[end - 1]) {
            end -= 1;
        }
        let prefix = String::from_utf16_lossy(&units[..end]);
        let mut value = result.clone();
        value["lineCount"] = json!(count_lines(&prefix));
        value["content"] = json!(prefix);
        value["truncated"] = json!(true);
        value["expected_base"] = Value::Null;
        json!({"ok": true, "result": value}).to_string()
    };
    let (mut low, mut high) = (0usize, units.len());
    let mut best = bounded(0);
    while low <= high {
        let middle = (low + high) / 2;
        let candidate = bounded(middle);
        if candidate.len() <= RESULT_MAX_BYTES {
            best = candidate;
            low = middle + 1;
        } else if middle == 0 {
            break;
        } else {
            high = middle - 1;
        }
    }
    best
}

fn text_result_content(value: &Value) -> Option<&str> {
    let object = value.as_object()?;
    let ok = object.get("truncated")?.is_boolean()
        && object.get("sizeBytes")?.is_number()
        && object.get("lineCount")?.is_number()
        && matches!(object.get("expected_base")?, Value::Null | Value::String(_));
    ok.then(|| object.get("content")?.as_str())?
}
