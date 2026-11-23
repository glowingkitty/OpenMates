//! Pure Code Run request building shared by every client shell.
//!
//! Shells read files from their platform (disk, browser, Apple) and hand the
//! in-memory bytes to [`build_direct_request`]. This module owns path
//! normalisation, bundle limits, duplicate detection, entry selection,
//! language inference, include/exclude matching and the human rendering of a
//! final run status, so every shell behaves the same. It performs no I/O.
use base64::{Engine, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::{collections::HashSet, fmt};

/// Most files one Code Run request may carry.
pub const MAX_FILES: usize = 50;
/// Largest single file in bytes.
pub const MAX_FILE_BYTES: usize = 1_000_000;
/// Largest total bundle in bytes.
pub const MAX_TOTAL_BYTES: usize = 10_000_000;
/// Directory or file names a directory walk skips unless excluded explicitly too.
pub const DEFAULT_IGNORES: [&str; 6] = [
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "dist",
    "build",
];

/// A refusal while building a Code Run request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CodeRunError {
    /// The sandbox path is absolute, empty, escapes upward or is otherwise unsafe.
    UnsafePath(String),
    /// Two files normalise to the same sandbox path.
    DuplicatePath(String),
    /// More than [`MAX_FILES`] files.
    TooManyFiles,
    /// A file is larger than [`MAX_FILE_BYTES`].
    FileTooLarge(String),
    /// The bundle is larger than [`MAX_TOTAL_BYTES`].
    BundleTooLarge,
    /// No file was supplied.
    NoFiles,
    /// The requested entry is not among the files.
    EntryMissing(String),
}
impl fmt::Display for CodeRunError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnsafePath(path) => write!(f, "Unsafe Code Run path: {path}"),
            Self::DuplicatePath(path) => write!(f, "Duplicate Code Run file path: {path}"),
            Self::TooManyFiles => write!(f, "Code Run supports at most {MAX_FILES} files."),
            Self::FileTooLarge(path) => write!(f, "Code Run file is too large: {path}"),
            Self::BundleTooLarge => f.write_str("Code Run file bundle is too large."),
            Self::NoFiles => f.write_str("Code Run requires --code, --file or --dir."),
            Self::EntryMissing(path) => {
                write!(f, "Code Run entry file was not included: {path}")
            }
        }
    }
}
impl std::error::Error for CodeRunError {}

/// One in-memory file of a Code Run request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodeRunFile {
    /// Path inside the sandbox (normalised by the builder).
    pub path: String,
    /// Raw file bytes.
    pub content: Vec<u8>,
    /// Language override; inferred from the extension when `None`.
    pub language: Option<String>,
}

/// Normalise a sandbox path: forward slashes, no empty, `.` or `..` parts, not absolute.
pub fn normalize_path(raw: &str) -> Result<String, CodeRunError> {
    let path = raw.trim().replace('\\', "/");
    let drive = path.as_bytes().get(1) == Some(&b':')
        && path.as_bytes().first().is_some_and(u8::is_ascii_alphabetic)
        && path.as_bytes().get(2) == Some(&b'/');
    if path.is_empty()
        || path.contains('\0')
        || path.starts_with('/')
        || path.starts_with("~/")
        || drive
        || path.split('/').any(|p| p.is_empty() || p == "." || p == "..")
    {
        return Err(CodeRunError::UnsafePath(raw.to_owned()));
    }
    Ok(path)
}

/// Language name for a file extension, or the empty string when unknown.
pub fn infer_language(path: &str) -> &'static str {
    match path
        .rsplit('.')
        .next()
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        Some("py") => "python",
        Some("js" | "mjs" | "cjs") => "javascript",
        Some("ts") => "typescript",
        Some("sh") => "bash",
        Some("go") => "go",
        Some("rs") => "rust",
        Some("c") => "c",
        Some("cc" | "cpp" | "cxx") => "cpp",
        _ => "",
    }
}

/// Default file name for inline `--code` of a language.
pub fn default_filename(language: Option<&str>) -> &'static str {
    match language {
        Some("python" | "py") => "main.py",
        Some("javascript" | "js" | "node") => "main.js",
        Some("typescript" | "ts") => "main.ts",
        Some("bash" | "sh") => "main.sh",
        _ => "main.txt",
    }
}

/// Build the inline `--code` file: name from `filename`, else `entry`, else the language default.
pub fn inline_file(
    code: &str,
    language: Option<&str>,
    filename: Option<&str>,
    entry: Option<&str>,
) -> Result<CodeRunFile, CodeRunError> {
    let path = normalize_path(
        filename
            .filter(|s| !s.is_empty())
            .or(entry.filter(|s| !s.is_empty()))
            .unwrap_or_else(|| default_filename(language)),
    )?;
    Ok(CodeRunFile {
        path,
        content: code.as_bytes().to_vec(),
        language: language.filter(|s| !s.is_empty()).map(str::to_owned),
    })
}

/// Build the `/v1/apps/code/skills/run` body for one direct request.
///
/// The entry defaults to the first file. `allow_e2b_upload` is sent only when true.
pub fn build_direct_request(
    files: Vec<CodeRunFile>,
    entry: Option<&str>,
    enable_internet: bool,
    allow_e2b_upload: bool,
) -> Result<Value, CodeRunError> {
    let entry = entry
        .filter(|s| !s.is_empty())
        .map(normalize_path)
        .transpose()?;
    let mut seen = HashSet::new();
    let mut total = 0usize;
    let mut prepared = Vec::with_capacity(files.len());
    for (count, file) in files.into_iter().enumerate() {
        let path = normalize_path(&file.path)?;
        if !seen.insert(path.clone()) {
            return Err(CodeRunError::DuplicatePath(path));
        }
        total += file.content.len();
        if count + 1 > MAX_FILES {
            return Err(CodeRunError::TooManyFiles);
        }
        if file.content.len() > MAX_FILE_BYTES {
            return Err(CodeRunError::FileTooLarge(path));
        }
        if total > MAX_TOTAL_BYTES {
            return Err(CodeRunError::BundleTooLarge);
        }
        let language = file
            .language
            .unwrap_or_else(|| infer_language(&path).to_owned());
        prepared.push((path, STANDARD.encode(&file.content), language));
    }
    let Some(first) = prepared.first() else {
        return Err(CodeRunError::NoFiles);
    };
    let entry_path = entry.unwrap_or_else(|| first.0.clone());
    if !prepared.iter().any(|(path, ..)| *path == entry_path) {
        return Err(CodeRunError::EntryMissing(entry_path));
    }
    let files: Vec<Value> = prepared
        .into_iter()
        .map(|(path, content_base64, language)| {
            json!({"path": path, "content_base64": content_base64, "language": language,
                "mime_type": "text/plain", "is_target": path == entry_path})
        })
        .collect();
    let mut body = json!({"requests": [{"mode": "direct", "entry_path": entry_path,
        "enable_internet": enable_internet, "files": files}]});
    if allow_e2b_upload {
        body["allow_e2b_upload"] = json!(true);
    }
    Ok(body)
}

fn wildcard(pattern: &[char], text: &[char]) -> bool {
    match pattern.split_first() {
        None => text.is_empty(),
        Some(('*', rest)) => (0..=text.len()).any(|i| wildcard(rest, &text[i..])),
        Some((c, rest)) => text.first() == Some(c) && wildcard(rest, &text[1..]),
    }
}

fn matches_pattern(path: &str, pattern: &str) -> bool {
    if pattern.is_empty() {
        return false;
    }
    if pattern.contains('*') {
        let pattern: Vec<char> = pattern.chars().collect();
        let chars: Vec<char> = path.chars().collect();
        return (0..=chars.len())
            .filter(|i| *i == 0 || chars[i - 1] == '/')
            .any(|i| wildcard(&pattern, &chars[i..]));
    }
    path == pattern
        || path.starts_with(&format!("{pattern}/"))
        || path.ends_with(&format!("/{pattern}"))
}

/// True when `path` matches any include/exclude pattern (`*` wildcard, exact, or directory prefix/suffix).
pub fn matches_any<S: AsRef<str>>(path: &str, patterns: &[S]) -> bool {
    patterns.iter().any(|p| matches_pattern(path, p.as_ref()))
}

fn text(value: &Value, key: &str) -> Option<String> {
    value[key]
        .as_str()
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
}

fn artifact_lines(value: &Value, skipped: bool) -> Vec<String> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter(|a| a.is_object())
        .map(|a| {
            let path = text(a, "normalized_path")
                .or_else(|| text(a, "path"))
                .unwrap_or_else(|| "artifact".into());
            if skipped {
                return format!(
                    "- {path} ({})",
                    text(a, "reason").unwrap_or_else(|| "skipped".into())
                );
            }
            let mime = text(a, "mime_type").unwrap_or_else(|| "application/octet-stream".into());
            let size = a["size_bytes"]
                .as_f64()
                .map_or("unknown size".to_owned(), |n| format!("{n} bytes"));
            if text(a, "download_url").is_some() {
                format!("- {path} ({mime}, {size}; signed download available via --json)")
            } else {
                format!("- {path} ({mime}, {size})")
            }
        })
        .collect()
}

/// Joined `text` of the status record's `events` of one `kind`, in order.
///
/// The `/v1/code/run/{id}` record stores the program's output as events
/// (`status` | `stdout` | `stderr`), not as one field. Like the npm CLI,
/// `stdout` goes to stdout and `stderr` to stderr; the final status carries
/// only the sandbox's progress lines in `status` events, which are not shown.
fn event_text(status: &Value, kind: &str) -> String {
    status["events"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|event| event["kind"].as_str() == Some(kind))
        .filter_map(|event| event["text"].as_str())
        .collect()
}

/// The program's stderr of a final run status (its `stderr` events), for the
/// shell's stderr stream; empty when the run wrote none.
pub fn final_status_stderr(status: &Value) -> String {
    event_text(status, "stderr")
}

/// Human output of a final run status: program stdout (an `output` field when
/// present, else the record's `stdout` events), artifacts, skipped artifacts.
pub fn format_final_status(status: &Value) -> String {
    let mut out = String::new();
    let stdout = status["output"]
        .as_str()
        .filter(|s| !s.is_empty())
        .map_or_else(|| event_text(status, "stdout"), str::to_owned);
    if !stdout.is_empty() {
        out.push_str(&stdout);
        if !stdout.ends_with('\n') {
            out.push('\n');
        }
    }
    for (title, lines) in [
        ("Artifacts", artifact_lines(&status["artifacts"], false)),
        (
            "Skipped artifacts",
            artifact_lines(&status["skipped_artifacts"], true),
        ),
    ] {
        if lines.is_empty() {
            continue;
        }
        if !out.is_empty() && !out.ends_with("\n\n") {
            out.push('\n');
        }
        out.push_str(&format!("{title}:\n{}\n", lines.join("\n")));
    }
    out
}

#[cfg(test)]
#[path = "code_run_request_tests.rs"]
mod tests;
