//! Private/ignored path policy of hosted Project files (port of
//! `loadProjectPolicy` in `hostedProjectFileExecutor.ts` and the in-memory
//! `createProjectPathPolicy`). Control files (`.gitignore`, `.openmates/permissions.yml`)
//! are decrypted only when no earlier private or ignore rule excludes them, and
//! every failure to load the policy fails closed as `protected_path`.
//! Pattern semantics come from the shared npm-`ignore` matcher in `source_host`.
use super::io::HostedIo;
use super::{HostedFile, HostedFileError, HostedResult, decide, refused};
use crate::source_host::ignore_rules::{Matcher, candidate};
use crate::source_host::path_policy::PROJECT_CREDENTIAL_GLOBS;
use serde_json::{Value, json};
use std::collections::BTreeSet;

pub(super) const PERMISSIONS_PATH: &str = ".openmates/permissions.yml";
const MAX_IGNORE_FILES: usize = 64;
const MAX_CONTROL_FILE_BYTES: usize = 64 * 1024;
const MAX_CONTROL_BYTES: usize = 256 * 1024;
const MAX_PRIVATE_PATHS: usize = 256;

fn protected<T>() -> HostedResult<T> {
    refused("protected_path")
}

struct Scope {
    base: String,
    matcher: Matcher,
}

/// The evaluated policy for one operation; never cached across operations.
pub(super) struct PathPolicy {
    scopes: Vec<Scope>,
    private: Matcher,
}

impl PathPolicy {
    fn new(ignore_files: &[(String, String)], private_paths: &[String]) -> HostedResult<Self> {
        let mut sorted: Vec<(String, &str, &str)> = Vec::new();
        for (path, content) in ignore_files {
            let base = if path == ".gitignore" {
                String::new()
            } else if let Some(base) = path.strip_suffix("/.gitignore") {
                base.to_owned()
            } else {
                return protected();
            };
            sorted.push((base, path, content));
        }
        sorted.sort_by(|a, b| depth(&a.0).cmp(&depth(&b.0)).then_with(|| a.1.cmp(b.1)));
        let scopes = sorted
            .into_iter()
            .map(|(base, _, content)| {
                Ok(Scope {
                    base,
                    matcher: Matcher::new(content.split('\n'), false)
                        .map_err(|_| HostedFileError::Refused("protected_path"))?,
                })
            })
            .collect::<HostedResult<Vec<_>>>()?;
        let mut patterns = Vec::new();
        let mut seen = BTreeSet::new();
        let builtin = PROJECT_CREDENTIAL_GLOBS
            .iter()
            .copied()
            .chain([PERMISSIONS_PATH, "**/.openmates/permissions.yml"]);
        for pattern in builtin.chain(private_paths.iter().map(String::as_str)) {
            let normalized = private_pattern(pattern)?;
            if seen.insert(normalized.clone()) {
                patterns.push(normalized);
            }
        }
        // npm `ignore()` default: private matching is case-insensitive.
        let private = Matcher::new(patterns.iter().map(String::as_str), true)
            .map_err(|_| HostedFileError::Refused("protected_path"))?;
        Ok(Self { scopes, private })
    }

    /// Whether git would ignore this hosted file path (`isIgnored(path, false)`).
    pub(super) fn is_ignored(&self, path: &str) -> bool {
        evaluate(&self.scopes, path, false, None)
    }

    /// Built-in, configured or file-local private path, or the permissions file.
    pub(super) fn is_private(&self, path: &str) -> bool {
        path == PERMISSIONS_PATH || self.private.ignores(&candidate(path, false))
    }
}

fn depth(path: &str) -> usize {
    if path.is_empty() {
        0
    } else {
        path.split('/').count()
    }
}

/// `evaluateScopedIgnores` (`stop` set: `evaluateEarlierScopes`).
fn evaluate(scopes: &[Scope], path: &str, is_directory: bool, stop: Option<usize>) -> bool {
    let mut ignored = false;
    for (index, scope) in scopes.iter().enumerate() {
        if stop == Some(index) {
            break;
        }
        if !scope.base.is_empty() {
            if path != scope.base && !path.starts_with(&format!("{}/", scope.base)) {
                continue;
            }
            // Git never reads an ignore file inside a directory a parent rule excludes.
            if stop.is_none() && evaluate(scopes, &scope.base, true, Some(index)) {
                continue;
            }
        }
        let relative = if scope.base.is_empty() {
            path
        } else if path == scope.base {
            ""
        } else {
            &path[scope.base.len() + 1..]
        };
        if relative.is_empty() {
            continue;
        }
        let verdict = scope.matcher.test(&candidate(relative, is_directory));
        if verdict.ignored {
            ignored = true;
        } else if verdict.unignored {
            ignored = false;
        }
    }
    ignored
}

/// npm `normalizePrivatePattern`; an invalid pattern fails the whole policy.
fn private_pattern(value: &str) -> HostedResult<String> {
    let drive = value.len() >= 2
        && value.as_bytes()[0].is_ascii_alphabetic()
        && value.as_bytes()[1] == b':';
    if value.trim().is_empty()
        || value.starts_with('!')
        || value.contains('\\')
        || value.chars().any(|c| (c as u32) < 32 || c as u32 == 127)
        || drive
        || value.split('/').any(|part| part == "..")
    {
        return protected();
    }
    let normalized = value.strip_prefix("./").unwrap_or(value);
    if normalized.is_empty() || normalized == "/" || normalized.starts_with("//") {
        return protected();
    }
    Ok(normalized.to_owned())
}

fn valid_private_list(paths: &[String]) -> bool {
    paths.len() <= MAX_PRIVATE_PATHS && paths.iter().all(|p| !p.is_empty() && p.len() <= 4_096)
}

/// `parsePrivatePaths` of `.openmates/permissions.yml`: `file_access.private_paths`.
fn permissions_private_paths(content: &str) -> HostedResult<Vec<String>> {
    let document: Value = serde_yaml::from_str::<Option<Value>>(content)
        .map_err(|_| HostedFileError::Refused("protected_path"))?
        .unwrap_or(Value::Null);
    if document.is_null() {
        return Ok(Vec::new());
    }
    let Some(document) = document.as_object() else {
        return protected();
    };
    let Some(access) = document.get("file_access") else {
        return Ok(Vec::new());
    };
    let Some(access) = access.as_object() else {
        return protected();
    };
    let Some(paths) = access.get("private_paths") else {
        return Ok(Vec::new());
    };
    let paths: Vec<String> = paths
        .as_array()
        .ok_or(HostedFileError::Refused("protected_path"))?
        .iter()
        .map(|path| path.as_str().map(str::to_owned))
        .collect::<Option<_>>()
        .ok_or(HostedFileError::Refused("protected_path"))?;
    if !valid_private_list(&paths) {
        return protected();
    }
    Ok(paths)
}

/// Policy-filtered files of one operation.
pub(super) struct LoadedPolicy {
    pub(super) files: Vec<HostedFile>,
    pub(super) policy: PathPolicy,
    pub(super) excluded: u64,
}

async fn control_text<I: HostedIo>(
    io: &mut I,
    embed_id: &str,
    total: &mut usize,
) -> HostedResult<String> {
    let head = io.read_head(embed_id).await.map_err(|error| match error {
        HostedFileError::Core(crate::Error::Cancelled) => error,
        _ => HostedFileError::Refused("protected_path"),
    })?;
    let text = head
        .text()
        .map_err(|_| HostedFileError::Refused("protected_path"))?
        .to_owned();
    *total += text.len();
    if text.len() > MAX_CONTROL_FILE_BYTES || *total > MAX_CONTROL_BYTES {
        return protected();
    }
    Ok(text)
}

/// `loadProjectPolicy`: normalize every listed path (a refused path taints its
/// embed), read the permissions file and the reachable `.gitignore` chain, and
/// hide private files.
///
/// # Errors
/// `protected_path` for any policy that cannot be loaded exactly.
pub(super) async fn load<I: HostedIo>(
    io: &mut I,
    private_paths: &[String],
    listed: Vec<HostedFile>,
) -> HostedResult<LoadedPolicy> {
    if !valid_private_list(private_paths) {
        return protected();
    }
    let paths: Vec<Value> = listed.iter().map(|f| json!(f.path)).collect();
    let normalized = decide("projectHostedPaths", &json!({ "paths": paths }))?;
    let results = normalized["results"]
        .as_array()
        .ok_or(HostedFileError::Refused("protected_path"))?;
    let mut files = Vec::new();
    let mut private_embeds = BTreeSet::new();
    let mut excluded = 0u64;
    for (index, file) in listed.into_iter().enumerate() {
        match results.get(index).and_then(|r| r["path"].as_str()) {
            Some(path) => files.push(HostedFile {
                embed_id: file.embed_id,
                path: path.to_owned(),
            }),
            None if results.get(index).is_some() => {
                // A protected or malformed link taints the ciphertext target, so
                // an innocuous alias cannot make the same embed readable.
                private_embeds.insert(file.embed_id);
                excluded += 1;
            }
            None => return protected(),
        }
    }
    let order = crate::source_host::NameOrder::new()
        .map_err(|_| HostedFileError::Refused("protected_path"))?;
    let mut ignore_controls: Vec<&HostedFile> = files
        .iter()
        .filter(|f| f.path == ".gitignore" || f.path.ends_with("/.gitignore"))
        .collect();
    ignore_controls.sort_by(|a, b| {
        depth(&a.path)
            .cmp(&depth(&b.path))
            .then_with(|| order.compare(&a.path, &b.path))
    });
    let permissions: Vec<&HostedFile> = files
        .iter()
        .filter(|f| f.path == PERMISSIONS_PATH)
        .collect();
    if ignore_controls.len() > MAX_IGNORE_FILES || permissions.len() > 1 {
        return protected();
    }
    let control_paths: BTreeSet<&str> = ignore_controls
        .iter()
        .chain(permissions.iter())
        .map(|f| f.path.as_str())
        .collect();
    if control_paths.len() != ignore_controls.len() + permissions.len() {
        return protected();
    }
    let mut total = 0usize;
    let mut file_private = Vec::new();
    if let Some(control) = permissions.first() {
        if private_embeds.contains(&control.embed_id) {
            return protected();
        }
        let text = control_text(io, &control.embed_id, &mut total).await?;
        file_private = permissions_private_paths(&text)?;
    }
    let all_private: Vec<String> = private_paths.iter().cloned().chain(file_private).collect();
    let private_only = PathPolicy::new(&[], &all_private)?;
    for file in &files {
        if private_only.is_private(&file.path) {
            private_embeds.insert(file.embed_id.clone());
        }
    }
    let mut ignore_files: Vec<(String, String)> = Vec::new();
    for control in ignore_controls {
        // A private rule takes effect before the ignore body is decrypted.
        if private_embeds.contains(&control.embed_id) {
            if control.path == ".gitignore" {
                return protected();
            }
            continue;
        }
        let current = PathPolicy::new(&ignore_files, &all_private)?;
        // Git does not read a nested ignore file excluded by a parent policy.
        if current.is_ignored(&control.path) {
            continue;
        }
        let text = control_text(io, &control.embed_id, &mut total).await?;
        ignore_files.push((control.path.clone(), text));
    }
    let policy = PathPolicy::new(&ignore_files, &all_private)?;
    let before = files.len();
    files.retain(|file| !private_embeds.contains(&file.embed_id));
    excluded += (before - files.len()) as u64;
    Ok(LoadedPolicy {
        files,
        policy,
        excluded,
    })
}
