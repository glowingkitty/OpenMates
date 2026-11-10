//! `search` for the filesystem host: filename search, content search and the
//! optional bounded content attachment for filename matches.
//!
//! Mirrors `searchRemoteSource`, `searchRemoteFileNamesWithoutRg`,
//! `searchRemoteSourceWithoutRg`, `includeRemoteSearchContent` and
//! `collectSearchPathMetadata` in `remoteAccess.ts`. Request validation reuses
//! the shared `web_projects::search_request` rules (`projectSearchProtocol.ts`).
//! Content search runs ripgrep (`search_rg`); filename search always uses the
//! bounded in-process enumerator (the npm fallback path), with regex mode
//! evaluated by the Rust `regex` engine that ripgrep itself uses.

use super::fs_safe::{relative_posix, resolve_approved};
use super::path_policy::PathPolicy;
use super::reads::{
    DEFAULT_MAX_READ_BYTES, DEFAULT_MAX_READ_LINES, HostRoot, is_binary_path, read_text_file,
};
use super::search_rg::{RgError, content_search};
use super::{HostError, HostResult, NameOrder, utf16_prefix};
use crate::web_projects::search_request::{glob_matches, normalize};
use serde_json::{Map, Value, json};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

pub(crate) const MAX_SEARCH_SNIPPET_CHARS: usize = 500;
pub(crate) const SEARCH_TIMEOUT: Duration = Duration::from_secs(10);
pub(crate) const MAX_FALLBACK_SEARCH_FILES: usize = 10_000;
const CONTENT_MAX_FILES: usize = 8;
const CONTENT_MAX_FILE_BYTES: usize = 24 * 1024;
const CONTENT_MAX_TOTAL_BYTES: u64 = 96 * 1024;

/// A normalized search request (`ProjectSearchRequest`).
pub(crate) struct Request {
    pub(crate) files: bool,
    pub(crate) regex: bool,
    pub(crate) query: String,
    pub(crate) path: String,
    pub(crate) glob: Option<String>,
    pub(crate) max_results: usize,
    pub(crate) include_content: bool,
}

fn code(code: &'static str) -> HostError {
    HostError::new(code, code)
}

fn request_from(args: &Map<String, Value>) -> HostResult<Request> {
    let normalized = normalize(Some(&Value::Object(args.clone())))
        .map_err(|fault| HostError::failed(fault.to_string()))?
        .map_err(code)?;
    Ok(Request {
        files: normalized["target"] == "files",
        regex: normalized["mode"] == "regex",
        query: normalized["query"].as_str().unwrap_or_default().to_owned(),
        path: normalized["path"].as_str().unwrap_or(".").to_owned(),
        glob: normalized.get("glob").and_then(Value::as_str).map(str::to_owned),
        max_results: normalized["maxResults"].as_f64().unwrap_or(20.0) as usize,
        include_content: normalized["includeContent"] == true,
    })
}

/// The arguments npm `executeRemoteAccessOperation` forwards to `searchRemoteSource`.
fn forwarded(args: &Value) -> Map<String, Value> {
    let mut out = Map::new();
    out.insert(
        "query".into(),
        json!(args["query"].as_str().unwrap_or_default()),
    );
    for key in ["target", "mode", "include_content"] {
        if !args[key].is_null() {
            out.insert(key.into(), args[key].clone());
        }
    }
    if let Some(path) = args["path"].as_str() {
        out.insert("path".into(), json!(path));
    }
    if let Some(glob) = args["glob"].as_str() {
        out.insert("glob".into(), json!(glob));
    }
    if args["max_results"].is_number() {
        out.insert("max_results".into(), args["max_results"].clone());
    }
    out
}

/// npm `isWithinSearchPath`.
pub(crate) fn within(path: &str, search_path: &str) -> bool {
    search_path == "." || path == search_path || path.starts_with(&format!("{search_path}/"))
}

fn hidden(path: &str) -> bool {
    path.split('/').any(|part| part != "." && part.starts_with('.'))
}

/// `search`.
///
/// # Errors
/// Search protocol codes (`invalid_search_*`, `regex_search_unavailable`),
/// `protected_path` for a private/ignored search path, `invalid_path` and
/// `operation_failed` (timeouts, ripgrep failures, bound overruns).
pub(crate) fn search(host: &HostRoot, args: &Value) -> HostResult<Value> {
    let root = host.canonical()?;
    let request = request_from(&forwarded(args))?;
    let policy = host.policy(&root, &[], true)?;
    let target = resolve_approved(&root, &request.path)?;
    let search_path = match relative_posix(&root, &target)? {
        p if p.is_empty() => ".".to_owned(),
        p => p,
    };
    let target_is_dir = std::fs::metadata(&target).is_ok_and(|m| m.is_dir());
    if search_path != "."
        && (policy.is_private(&search_path, target_is_dir)?
            || policy.is_ignored(&search_path, target_is_dir)?)
    {
        return Err(HostError::protected("Remote source search path is protected"));
    }
    let priority = match args["priority_path"].as_str() {
        None => None,
        Some(raw) => {
            let mut forwarded = Map::new();
            forwarded.insert("query".into(), json!(request.query));
            forwarded.insert("target".into(), json!("files"));
            forwarded.insert("mode".into(), json!(if request.regex { "regex" } else { "literal" }));
            forwarded.insert("path".into(), json!(raw));
            let path = request_from(&forwarded)?.path;
            if !request.files || !within(&path, &request.path) {
                return Err(code("invalid_search_path"));
            }
            let absolute = resolve_approved(&root, &path)?;
            let is_dir = std::fs::metadata(&absolute).is_ok_and(|m| m.is_dir());
            if !is_dir
                || (path != "."
                    && (policy.is_private(&path, true)? || policy.is_ignored(&path, true)?))
                || hidden(&path)
            {
                return Err(code("invalid_search_path"));
            }
            Some((path, absolute))
        }
    };
    if request.files {
        let result = filenames(&request, &root, &target, &policy, priority.as_ref())?;
        return include_content(host, result, &request);
    }
    let hardlinks = hardlink_exclusions(&root, &target, &policy)?;
    match content_search(&request, &root, &search_path, &policy, &hardlinks) {
        Ok(output) => collect_rg_matches(&output, &request, &policy),
        Err(RgError::Missing) if request.regex => Err(code("regex_search_unavailable")),
        Err(RgError::Missing) => content_without_rg(host, &request, &root, &target, &policy),
        Err(RgError::Failed(error)) => Err(error),
    }
}

/// npm `collectSearchPathMetadata` for content search: multiply-linked files
/// are excluded before ripgrep can open them.
fn hardlink_exclusions(root: &Path, target: &Path, policy: &PathPolicy) -> HostResult<Vec<String>> {
    let stat = std::fs::symlink_metadata(target).map_err(|e| HostError::io("Search", &e))?;
    if stat.is_file() {
        return Ok(if stat.nlink() > 1 {
            vec![relative_posix(root, target)?]
        } else {
            Vec::new()
        });
    }
    if !stat.is_dir() {
        return Ok(Vec::new());
    }
    let (mut pending, mut links, mut inspected) = (vec![target.to_path_buf()], Vec::new(), 0usize);
    while let Some(directory) = pending.pop() {
        for entry in std::fs::read_dir(&directory).map_err(|e| HostError::io("Search", &e))? {
            let entry = entry.map_err(|e| HostError::io("Search", &e))?;
            inspected += 1;
            if inspected > MAX_FALLBACK_SEARCH_FILES {
                return Err(HostError::failed(
                    "Remote source search alias scan exceeded its bounded file limit",
                ));
            }
            let kind = entry.file_type().map_err(|e| HostError::io("Search", &e))?;
            if entry.file_name() == ".git" || kind.is_symlink() {
                continue;
            }
            let absolute = entry.path();
            let Ok(path) = relative_posix(root, &absolute) else {
                continue;
            };
            if kind.is_dir() {
                if !policy.is_ignored(&path, true)? && !policy.is_private(&path, true)? {
                    pending.push(absolute);
                }
                continue;
            }
            if !kind.is_file() || policy.is_ignored(&path, false)? || policy.is_private(&path, false)? {
                continue;
            }
            if std::fs::symlink_metadata(&absolute).is_ok_and(|m| m.nlink() > 1) {
                links.push(path);
            }
        }
    }
    Ok(links)
}

fn compare_paths(order: &NameOrder, a: &str, b: &str, priority: Option<&str>) -> std::cmp::Ordering {
    if let Some(priority) = priority {
        let rank = |path: &str| -> u8 {
            let parent = path.rfind('/').map_or(".", |i| &path[..i]);
            if parent == priority {
                0
            } else if within(path, priority) {
                1
            } else {
                2
            }
        };
        let ordering = rank(a).cmp(&rank(b));
        if ordering.is_ne() {
            return ordering;
        }
    }
    order.compare(a, b)
}

/// npm `searchRemoteFileNamesWithoutRg` (plus regex matching on names).
fn filenames(
    request: &Request,
    root: &Path,
    target: &Path,
    policy: &PathPolicy,
    priority: Option<&(String, PathBuf)>,
) -> HostResult<Value> {
    let deadline = Instant::now() + SEARCH_TIMEOUT;
    let mut walk = NameWalk {
        root,
        policy,
        glob: request.glob.as_deref(),
        deadline,
        candidates: Vec::new(),
        inspected: 0,
        excluded: 0,
        truncated: false,
    };
    let priority_differs = priority.is_some_and(|(_, absolute)| absolute != target);
    if let Some((path, absolute)) = priority.filter(|_| priority_differs) {
        if glob_matches(path, request.glob.as_deref()) {
            walk.candidates.push((path.clone(), true));
        }
        walk.scan(absolute, None)?;
    }
    if !walk.truncated {
        let skip = priority.filter(|_| priority_differs).map(|(_, a)| a.as_path());
        walk.scan(target, skip)?;
    }
    let matcher = if request.regex {
        Some(
            regex::Regex::new(&request.query)
                .map_err(|_| HostError::failed("rg failed with exit code 2"))?,
        )
    } else {
        None
    };
    let lower = request.query.to_lowercase();
    let order = NameOrder::new()?;
    let mut matches: Vec<(String, bool)> = walk
        .candidates
        .into_iter()
        .filter(|(path, _)| match &matcher {
            Some(regex) => regex.is_match(path),
            None => path.to_lowercase().contains(&lower),
        })
        .collect();
    let priority_path = priority.map(|(p, _)| p.as_str());
    matches.sort_by(|a, b| compare_paths(&order, &a.0, &b.0, priority_path));
    let omitted = matches.len().saturating_sub(request.max_results) + usize::from(walk.truncated);
    let items: Vec<Value> = matches
        .into_iter()
        .take(request.max_results)
        .map(|(path, dir)| json!({"path": path, "kind": if dir { "directory" } else { "file" }}))
        .collect();
    Ok(json!({"matches": items, "omitted": omitted, "excluded": walk.excluded, "truncated": omitted > 0}))
}

struct NameWalk<'a> {
    root: &'a Path,
    policy: &'a PathPolicy,
    glob: Option<&'a str>,
    deadline: Instant,
    candidates: Vec<(String, bool)>,
    inspected: usize,
    excluded: u64,
    truncated: bool,
}

impl NameWalk<'_> {
    fn scan(&mut self, start: &Path, skip: Option<&Path>) -> HostResult<()> {
        let mut pending = vec![start.to_path_buf()];
        while let Some(absolute) = pending.pop() {
            if self.truncated {
                break;
            }
            if Instant::now() >= self.deadline {
                return Err(HostError::failed("Remote source search timed out"));
            }
            let stat = std::fs::symlink_metadata(&absolute).map_err(|e| HostError::io("Search", &e))?;
            if stat.is_dir() {
                let Ok(entries) = std::fs::read_dir(&absolute) else {
                    self.excluded += 1;
                    continue;
                };
                for entry in entries {
                    let entry = entry.map_err(|e| HostError::io("Search", &e))?;
                    self.inspected += 1;
                    if self.inspected > MAX_FALLBACK_SEARCH_FILES {
                        self.truncated = true;
                        break;
                    }
                    let child = entry.path();
                    if skip == Some(child.as_path()) {
                        continue;
                    }
                    let kind = entry.file_type().map_err(|e| HostError::io("Search", &e))?;
                    let name = entry.file_name();
                    let path = match relative_posix(self.root, &child) {
                        Ok(path) => path,
                        Err(_) => {
                            self.excluded += 1;
                            continue;
                        }
                    };
                    let is_dir = kind.is_dir();
                    if name.to_string_lossy().starts_with('.')
                        || kind.is_symlink()
                        || (!kind.is_file() && !is_dir)
                        || self.policy.is_ignored(&path, is_dir)?
                        || self.policy.is_private(&path, is_dir)?
                    {
                        self.excluded += 1;
                        continue;
                    }
                    if is_dir {
                        pending.push(child);
                    } else if std::fs::symlink_metadata(&child).is_ok_and(|m| m.nlink() > 1) {
                        self.excluded += 1;
                        continue;
                    }
                    if glob_matches(&path, self.glob) {
                        self.candidates.push((path, is_dir));
                    }
                }
            } else if stat.is_file() && stat.nlink() == 1 {
                let path = relative_posix(self.root, &absolute)?;
                if !hidden(&path)
                    && !self.policy.is_ignored(&path, false)?
                    && !self.policy.is_private(&path, false)?
                    && glob_matches(&path, self.glob)
                {
                    self.candidates.push((path, false));
                }
            }
        }
        Ok(())
    }
}

/// npm `includeRemoteSearchContent`: bounded fresh reads for filename matches.
fn include_content(host: &HostRoot, mut result: Value, request: &Request) -> HostResult<Value> {
    if !request.include_content {
        return Ok(result);
    }
    let (mut contents, mut omissions, mut total) = (Vec::new(), Vec::new(), 0u64);
    if let Some(matches) = result["matches"].as_array_mut() {
        for item in matches.iter_mut() {
            let path = item["path"].as_str().unwrap_or_default().to_owned();
            let reason = if item["kind"] == "directory" {
                Some("directory")
            } else if contents.len() >= CONTENT_MAX_FILES {
                Some("file_limit")
            } else if is_binary_path(&path) {
                Some("binary_or_unsupported")
            } else {
                match read_text_file(host, &path, CONTENT_MAX_FILE_BYTES, DEFAULT_MAX_READ_LINES, false) {
                    Err(_) => Some("unreadable_or_unsupported"),
                    Ok(read) => match &read.expected_base {
                        None => Some("file_too_large_or_line_limit"),
                        Some(_) if read.truncated => Some("file_too_large_or_line_limit"),
                        Some(_) if total + read.size_bytes > CONTENT_MAX_TOTAL_BYTES => {
                            Some("total_bytes_limit")
                        }
                        Some(base) => {
                            item["expected_base"] = json!(base);
                            contents.push(json!({
                                "path": path,
                                "content": read.content,
                                "expected_base": base,
                                "size_bytes": read.size_bytes,
                            }));
                            total += read.size_bytes;
                            None
                        }
                    },
                }
            };
            if let Some(reason) = reason {
                omissions.push(json!({"path": path, "reason": reason}));
            }
        }
    }
    result["content_incomplete"] = json!(!omissions.is_empty());
    result["contents"] = json!(contents);
    result["content_omissions"] = json!(omissions);
    Ok(result)
}

/// npm `normalizeRgPath`.
pub(crate) fn normalize_rg_path(value: &str) -> Option<String> {
    let slashed = value.replace('\\', "/");
    let normalized = slashed.strip_prefix("./").unwrap_or(&slashed);
    if normalized.is_empty()
        || normalized.encode_utf16().count() > 2_048
        || normalized.starts_with('/')
        || normalized.chars().any(|c| (c as u32) <= 0x1f || c as u32 == 0x7f)
        || normalized.split('/').any(|part| part == "..")
    {
        return None;
    }
    Some(normalized.to_owned())
}

/// npm `shouldExcludeReadPath`.
fn exclude_read_path(path: &str, policy: &PathPolicy) -> HostResult<bool> {
    if normalize_rg_path(path).is_none() || is_binary_path(path) {
        return Ok(true);
    }
    Ok(policy.is_ignored(path, false)? || policy.is_private(path, false)?)
}

/// npm `collectRgContentMatches` over `rg --json` output lines.
fn collect_rg_matches(output: &[String], request: &Request, policy: &PathPolicy) -> HostResult<Value> {
    let (mut matches, mut omitted, mut excluded) = (Vec::new(), 0u64, 0u64);
    for line in output {
        let Some((path, number, snippet)) = parse_rg_match(line) else {
            continue;
        };
        if exclude_read_path(&path, policy)?
            || !within(&path, &request.path)
            || !glob_matches(&path, request.glob.as_deref())
            || number > DEFAULT_MAX_READ_LINES as u64
        {
            excluded += 1;
            continue;
        }
        if matches.len() >= request.max_results {
            omitted += 1;
            continue;
        }
        matches.push(json!({"path": path, "line": number, "snippet": snippet}));
    }
    Ok(json!({"matches": matches, "omitted": omitted, "excluded": excluded, "truncated": omitted > 0}))
}

/// npm `parseRgMatch`: `(path, line_number, snippet <= 500 UTF-16 units)`.
pub(crate) fn parse_rg_match(line: &str) -> Option<(String, u64, String)> {
    let parsed: Value = serde_json::from_str(line).ok()?;
    if parsed["type"] != "match" {
        return None;
    }
    let path = normalize_rg_path(parsed["data"]["path"]["text"].as_str()?)?;
    let number = parsed["data"]["line_number"].as_u64()?;
    let snippet = parsed["data"]["lines"]["text"].as_str()?;
    Some((path, number, utf16_prefix(snippet, MAX_SEARCH_SNIPPET_CHARS)))
}

/// npm `searchRemoteSourceWithoutRg`: literal content search when `rg` is absent.
fn content_without_rg(
    host: &HostRoot,
    request: &Request,
    root: &Path,
    target: &Path,
    policy: &PathPolicy,
) -> HostResult<Value> {
    let deadline = Instant::now() + SEARCH_TIMEOUT;
    let stat = std::fs::metadata(target).map_err(|e| HostError::io("Search", &e))?;
    let mut directories = if stat.is_dir() { vec![target.to_path_buf()] } else { Vec::new() };
    let mut initial = if stat.is_file() { vec![target.to_path_buf()] } else { Vec::new() };
    let order = NameOrder::new()?;
    let (mut matches, mut inspected, mut excluded) = (Vec::new(), 0usize, 0u64);
    // The walk returns on the first omission, so the omitted count is 0 or 1.
    let omitted = 0u64;
    let done = |matches: Vec<Value>, omitted: u64, excluded: u64| {
        json!({"matches": matches, "omitted": omitted, "excluded": excluded, "truncated": omitted > 0})
    };
    while !directories.is_empty() || !initial.is_empty() {
        if Instant::now() >= deadline {
            return Err(HostError::failed("Remote source search timed out"));
        }
        let mut candidates: Vec<PathBuf> = std::mem::take(&mut initial);
        if let Some(directory) = directories.pop() {
            let Ok(entries) = std::fs::read_dir(&directory) else {
                excluded += 1;
                continue;
            };
            let mut entries: Vec<_> = entries.filter_map(Result::ok).collect();
            entries.sort_by(|a, b| {
                order.compare(&a.file_name().to_string_lossy(), &b.file_name().to_string_lossy())
            });
            for entry in entries {
                let absolute = entry.path();
                let Ok(kind) = entry.file_type() else {
                    excluded += 1;
                    continue;
                };
                let Ok(path) = relative_posix(root, &absolute) else {
                    excluded += 1;
                    continue;
                };
                if entry.file_name() == ".git"
                    || kind.is_symlink()
                    || policy.is_ignored(&path, kind.is_dir())?
                    || policy.is_private(&path, kind.is_dir())?
                {
                    excluded += 1;
                    continue;
                }
                if kind.is_dir() {
                    directories.push(absolute);
                } else if !kind.is_file() {
                    excluded += 1;
                } else {
                    candidates.push(absolute);
                }
            }
        }
        for absolute in candidates {
            let path = relative_posix(root, &absolute)?;
            if exclude_read_path(&path, policy)? || !glob_matches(&path, request.glob.as_deref()) {
                excluded += 1;
                continue;
            }
            inspected += 1;
            if inspected > MAX_FALLBACK_SEARCH_FILES {
                return Ok(done(matches, omitted + 1, excluded));
            }
            let content = match read_text_file(host, &path, DEFAULT_MAX_READ_BYTES, DEFAULT_MAX_READ_LINES, false) {
                Ok(read) if read.size_bytes <= DEFAULT_MAX_READ_BYTES as u64 => read.content,
                _ => {
                    excluded += 1;
                    continue;
                }
            };
            for (index, line) in content.split_inclusive('\n').enumerate() {
                if !line.contains(&request.query) {
                    continue;
                }
                if matches.len() >= request.max_results {
                    return Ok(done(matches, omitted + 1, excluded));
                }
                matches.push(json!({
                    "path": path,
                    "line": index + 1,
                    "snippet": utf16_prefix(line, MAX_SEARCH_SNIPPET_CHARS),
                }));
            }
        }
    }
    Ok(done(matches, omitted, excluded))
}
