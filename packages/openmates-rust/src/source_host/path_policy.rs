//! Project ignore/private path policy for the filesystem host.
//!
//! Mirrors `loadProjectPathPolicy` (`openmates-cli/src/projectPathPolicy.ts`) and
//! `createProjectPathPolicy` (`ui/src/utils/projectPathPolicy.ts`):
//! - ignore files: the `.gitignore` chain from the nearest `.git` ancestor down
//!   to the source root, the ancestors of each direct target and (for search)
//!   every nested `.gitignore` git would read; evaluated scope by scope, with a
//!   scope skipped when an earlier scope excludes its directory;
//! - private paths: built-in credential globs, `.openmates/permissions.yml`,
//!   its `file_access.private_paths` and trusted caller paths, made sticky in
//!   `<state>/project-path-policies/<sha256(root)>.json` so removing a line from
//!   the repository can never shrink protection. Private matching is
//!   case-insensitive (npm `ignore()` default); gitignores are case-sensitive.

use super::fs_safe::{lexical_join, relative_posix};
use super::ignore_rules::{Matcher, candidate};
use super::{HostError, HostResult, sha256_hex};
use std::path::{Path, PathBuf};

const MAX_IGNORE_FILES: usize = 128;
const MAX_IGNORE_BYTES: u64 = 1024 * 1024;
const MAX_POLICY_ENTRIES: usize = 50_000;
const POLICY_STATE_DIRECTORY: &str = "project-path-policies";
const MAX_STICKY_BYTES: u64 = 256 * 1024;

/// npm `PROJECT_CREDENTIAL_GLOBS` (`projectSearchProtocol.ts`).
pub(crate) const PROJECT_CREDENTIAL_GLOBS: &[&str] = &[
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    ".ssh/**",
    "**/.ssh/**",
    ".aws/**",
    "**/.aws/**",
    ".gnupg/**",
    "**/.gnupg/**",
    ".config/gcloud/**",
    "**/.config/gcloud/**",
    ".npmrc",
    "**/.npmrc",
    ".pypirc",
    "**/.pypirc",
    ".netrc",
    "**/.netrc",
    ".pgpass",
    "**/.pgpass",
    ".my.cnf",
    "**/.my.cnf",
    ".git-credentials",
    "**/.git-credentials",
    "credentials",
    "**/credentials",
    "credentials.json",
    "**/credentials.json",
    "application_default_credentials.json",
    "**/application_default_credentials.json",
    "id_rsa",
    "**/id_rsa",
    "id_ed25519",
    "**/id_ed25519",
    "id_dsa",
    "**/id_dsa",
    "id_ecdsa",
    "**/id_ecdsa",
    "*.pem",
    "**/*.pem",
    "*.key",
    "**/*.key",
    "*.p12",
    "**/*.p12",
    "*.pfx",
    "**/*.pfx",
    "*.keystore",
    "**/*.keystore",
    "*.kdbx",
    "**/*.kdbx",
    "*.credentials",
    "**/*.credentials",
];

/// Inputs for one policy load.
pub(crate) struct PolicyOptions<'a> {
    /// The OpenMates state directory (sticky private state lives below it).
    pub(crate) state_dir: &'a Path,
    /// Trusted extra private patterns from outside the source root.
    pub(crate) trusted_private: &'a [String],
    /// Source-relative targets whose ancestor ignore files apply.
    pub(crate) targets: &'a [&'a str],
    /// Load every nested ignore file (search only).
    pub(crate) discover_nested: bool,
}

struct Scope {
    base: String,
    matcher: Matcher,
}

/// A loaded policy for one canonical source root.
pub(crate) struct PathPolicy {
    prefix: String,
    scopes: Vec<Scope>,
    private: Matcher,
    private_globs: Vec<String>,
}

fn policy_error(message: impl Into<String>) -> HostError {
    HostError::new("invalid_path_policy", message)
}

/// npm `normalizeSourceRelativePath`: refuses `.`/`..`/empty segments,
/// backslashes, absolute paths and control characters. The npm rule throws a
/// plain policy error, which the host reports as `operation_failed`.
pub(crate) fn source_relative(value: &str) -> HostResult<&str> {
    if value.is_empty()
        || value.contains('\\')
        || value.starts_with('/')
        || value
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..")
        || value.chars().any(|c| (c as u32) < 32 || c as u32 == 127)
    {
        return Err(HostError::failed("Project path is invalid"));
    }
    Ok(value)
}

impl PathPolicy {
    /// Load the policy for a canonical root.
    ///
    /// # Errors
    /// `invalid_path_policy` for unreadable/oversized ignore files, invalid
    /// permissions or sticky state, a busy state lock or an invalid target.
    pub(crate) fn load(root: &Path, options: &PolicyOptions<'_>) -> HostResult<Self> {
        let policy_root = git_policy_root(root);
        let prefix = relative_posix(&policy_root, root).map_err(|e| policy_error(e.message))?;
        let configured = crate::remote_command::load_remote_command_permissions(root)
            .map_err(|e| policy_error(e.message))?
            .map(|p| p.file_access.private_paths)
            .unwrap_or_default();
        let mut additions = configured;
        additions.extend(options.trusted_private.iter().cloned());
        let sticky = update_sticky(root, &additions, options.state_dir)?;
        let mut patterns: Vec<String> = Vec::new();
        for raw in PROJECT_CREDENTIAL_GLOBS
            .iter()
            .map(|s| (*s).to_owned())
            .chain([
                ".openmates/permissions.yml".to_owned(),
                "**/.openmates/permissions.yml".to_owned(),
            ])
            .chain(sticky.iter().cloned())
        {
            let normalized = private_pattern(&raw)?;
            if !patterns.contains(&normalized) {
                patterns.push(normalized);
            }
        }
        let private = Matcher::new(patterns.iter().map(String::as_str), true)?;
        let mut private_globs = Vec::new();
        for glob in patterns.iter().flat_map(|p| private_rg_globs(p)) {
            if !private_globs.contains(&glob) {
                private_globs.push(glob);
            }
        }
        let mut policy = Self {
            prefix,
            scopes: Vec::new(),
            private,
            private_globs,
        };
        policy.collect_ignore_files(&policy_root, root, options)?;
        Ok(policy)
    }

    fn source_path(&self, path: &str) -> String {
        if self.prefix.is_empty() {
            path.to_owned()
        } else {
            format!("{}/{path}", self.prefix)
        }
    }

    /// Whether git would ignore this source-relative path.
    ///
    /// # Errors
    /// `operation_failed` for an invalid path (npm policy error).
    pub(crate) fn is_ignored(&self, path: &str, is_directory: bool) -> HostResult<bool> {
        let path = source_relative(path)?;
        Ok(evaluate(
            &self.scopes,
            &self.source_path(path),
            is_directory,
            None,
        ))
    }

    /// Whether the path is private (built-in, configured or sticky).
    ///
    /// # Errors
    /// `operation_failed` for an invalid path.
    pub(crate) fn is_private(&self, path: &str, is_directory: bool) -> HostResult<bool> {
        let path = source_relative(path)?;
        if self.private.ignores(&candidate(path, is_directory)) {
            return Ok(true);
        }
        // A private subtree pattern such as `secrets/**` protects its directory name too.
        Ok(is_directory
            && self
                .private
                .ignores(&format!("{path}/.openmates-private-path-probe")))
    }

    /// Ripgrep exclusions applied before content search starts.
    pub(crate) fn rg_exclusion_globs(&self) -> &[String] {
        &self.private_globs
    }

    /// npm `assertReadablePath`.
    ///
    /// # Errors
    /// `protected_path` for private paths, `ignored_path_requires_approval` for
    /// ignored paths without an approval.
    pub(crate) fn assert_readable(&self, path: &str, ignored_approved: bool) -> HostResult<()> {
        if self.is_private(path, false)? {
            return Err(HostError::protected("Project path is protected and private"));
        }
        if self.is_ignored(path, false)? && !ignored_approved {
            return Err(HostError::new(
                "ignored_path_requires_approval",
                "Project path is ignored and requires explicit approval",
            ));
        }
        Ok(())
    }

    /// npm `assertWritablePath`: private or ignored paths are never written.
    ///
    /// # Errors
    /// `protected_path`.
    pub(crate) fn assert_writable(&self, path: &str) -> HostResult<()> {
        if self.is_private(path, false)? || self.is_ignored(path, false)? {
            return Err(HostError::protected("Project path is protected"));
        }
        Ok(())
    }

    fn collect_ignore_files(
        &mut self,
        policy_root: &Path,
        root: &Path,
        options: &PolicyOptions<'_>,
    ) -> HostResult<()> {
        let mut loader = Loader {
            policy_root,
            files: Vec::new(),
            bytes: 0,
            entries: 0,
        };
        let mut chain = Vec::new();
        let mut current = root.to_path_buf();
        loop {
            chain.push(current.clone());
            if current == policy_root {
                break;
            }
            if !current.pop() || !current.starts_with(policy_root) {
                return Err(policy_error("Source root is outside its Git policy root"));
            }
        }
        for directory in chain.iter().rev() {
            loader.add(&directory.join(".gitignore"))?;
        }
        for target in options.targets {
            let normalized = if *target == "." {
                ""
            } else {
                source_relative(target).map_err(|e| policy_error(e.message))?
            };
            let absolute = lexical_join(root, Path::new(normalized));
            if !absolute.starts_with(root) {
                return Err(policy_error("Project policy target escapes its source root"));
            }
            let is_dir = std::fs::symlink_metadata(&absolute).is_ok_and(|m| m.is_dir());
            let mut directory = if is_dir {
                absolute.clone()
            } else {
                absolute.parent().map(Path::to_path_buf).unwrap_or_default()
            };
            let mut ancestors = Vec::new();
            while directory.starts_with(root) {
                ancestors.push(directory.clone());
                if directory == root || !directory.pop() {
                    break;
                }
            }
            for ancestor in ancestors.iter().rev() {
                loader.add_once(&ancestor.join(".gitignore"))?;
            }
        }
        self.scopes = scopes(&loader.files)?;
        if !options.discover_nested {
            return Ok(());
        }
        let mut seen: Vec<PathBuf> = chain
            .iter()
            .filter_map(|d| std::fs::canonicalize(d).ok())
            .collect();
        let mut directories = vec![root.to_path_buf()];
        while let Some(directory) = directories.pop() {
            let entries = std::fs::read_dir(&directory)
                .map_err(|e| policy_error(format!("Project policy scan failed: {e}")))?;
            for entry in entries {
                let entry = entry.map_err(|e| policy_error(format!("Project policy scan: {e}")))?;
                loader.entries += 1;
                if loader.entries > MAX_POLICY_ENTRIES {
                    return Err(policy_error(
                        "Project path policy scan exceeds its entry limit",
                    ));
                }
                let kind = entry
                    .file_type()
                    .map_err(|e| policy_error(format!("Project policy scan: {e}")))?;
                if entry.file_name() == ".git" || kind.is_symlink() || !kind.is_dir() {
                    continue;
                }
                let child = entry.path();
                let canonical = std::fs::canonicalize(&child)
                    .map_err(|e| policy_error(format!("Project policy scan: {e}")))?;
                if !canonical.starts_with(root) || seen.contains(&canonical) {
                    continue;
                }
                let source_relative_path =
                    relative_posix(root, &child).map_err(|e| policy_error(e.message))?;
                let policy_relative =
                    relative_posix(policy_root, &child).map_err(|e| policy_error(e.message))?;
                if self
                    .private
                    .ignores(&candidate(&source_relative_path, true))
                    || self
                        .private
                        .ignores(&format!("{source_relative_path}/.openmates-private-path-probe"))
                    || evaluate(&self.scopes, &policy_relative, true, None)
                {
                    continue;
                }
                seen.push(canonical);
                let before = loader.files.len();
                loader.add(&child.join(".gitignore"))?;
                if loader.files.len() != before {
                    self.scopes = scopes(&loader.files)?;
                }
                directories.push(child);
            }
        }
        Ok(())
    }
}

struct Loader<'a> {
    policy_root: &'a Path,
    files: Vec<(String, String)>,
    bytes: u64,
    entries: usize,
}

impl Loader<'_> {
    fn add_once(&mut self, path: &Path) -> HostResult<()> {
        let relative = relative_posix(self.policy_root, path).map_err(|e| policy_error(e.message))?;
        if self.files.iter().any(|(p, _)| *p == relative) {
            return Ok(());
        }
        self.add(path)
    }

    fn add(&mut self, path: &Path) -> HostResult<()> {
        let metadata = match std::fs::symlink_metadata(path) {
            Ok(metadata) => metadata,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(()),
            Err(e) => return Err(policy_error(format!("Ignore file is unreadable: {e}"))),
        };
        if !metadata.is_file() {
            return Err(policy_error("Ignore file must be a regular file"));
        }
        self.entries += 1;
        if self.entries > MAX_POLICY_ENTRIES
            || self.files.len() >= MAX_IGNORE_FILES
            || self.bytes + metadata.len() > MAX_IGNORE_BYTES
        {
            return Err(policy_error(
                "Project ignore policy exceeds its bounded load limits",
            ));
        }
        let content = read_bounded(path, MAX_IGNORE_BYTES - self.bytes)?;
        self.bytes += content.len() as u64;
        let relative = relative_posix(self.policy_root, path).map_err(|e| policy_error(e.message))?;
        self.files.push((relative, content));
        Ok(())
    }
}

/// Bounded no-follow read of a small regular file (lossy UTF-8 like Node).
pub(crate) fn read_bounded(path: &Path, max: u64) -> HostResult<String> {
    use std::io::Read;
    let fd = rustix::fs::open(
        path,
        rustix::fs::OFlags::RDONLY | rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| policy_error("Policy file is not a bounded regular file"))?;
    let mut file = std::fs::File::from(fd);
    let metadata = file
        .metadata()
        .map_err(|e| policy_error(format!("Policy file: {e}")))?;
    if !metadata.is_file() || metadata.len() > max {
        return Err(policy_error("Policy file is not a bounded regular file"));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(max)
        .read_to_end(&mut bytes)
        .map_err(|e| policy_error(format!("Policy file: {e}")))?;
    Ok(String::from_utf8_lossy(&bytes).into_owned())
}

fn depth(path: &str) -> usize {
    if path.is_empty() {
        0
    } else {
        path.split('/').count()
    }
}

fn scopes(files: &[(String, String)]) -> HostResult<Vec<Scope>> {
    let mut sorted: Vec<(String, &String, &String)> = Vec::new();
    for (path, content) in files {
        let base = if path == ".gitignore" {
            String::new()
        } else if let Some(base) = path.strip_suffix("/.gitignore") {
            base.to_owned()
        } else {
            return Err(policy_error("Ignore file path is invalid"));
        };
        sorted.push((base, path, content));
    }
    sorted.sort_by(|a, b| depth(&a.0).cmp(&depth(&b.0)).then_with(|| a.1.cmp(b.1)));
    sorted
        .into_iter()
        .map(|(base, _, content)| {
            Ok(Scope {
                base,
                matcher: Matcher::new(content.split('\n'), false)?,
            })
        })
        .collect()
}

/// npm `evaluateScopedIgnores` (and `evaluateEarlierScopes` when `stop` is set).
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
            // Git never reads an ignore file inside a directory excluded by a parent rule.
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

fn git_policy_root(root: &Path) -> PathBuf {
    let mut current = root.to_path_buf();
    loop {
        if current.join(".git").exists() {
            return current;
        }
        if !current.pop() {
            return root.to_path_buf();
        }
    }
}

/// npm `normalizePrivatePattern`.
fn private_pattern(value: &str) -> HostResult<String> {
    if value.trim().is_empty()
        || value.starts_with('!')
        || value.contains('\\')
        || value.chars().any(|c| (c as u32) < 32 || c as u32 == 127)
        || value.as_bytes().get(1) == Some(&b':') && value.as_bytes()[0].is_ascii_alphabetic()
        || value.split('/').any(|part| part == "..")
    {
        return Err(policy_error("Private path pattern is invalid"));
    }
    let normalized = value.strip_prefix("./").unwrap_or(value);
    if normalized.is_empty() || normalized == "/" || normalized.starts_with("//") {
        return Err(policy_error("Private path pattern is invalid"));
    }
    Ok(normalized.to_owned())
}

/// npm `privatePatternToRgGlobs`.
pub(crate) fn private_rg_globs(pattern: &str) -> Vec<String> {
    let anchored = pattern.starts_with('/');
    let mut value = if anchored { &pattern[1..] } else { pattern };
    let directory = value.ends_with('/');
    if directory {
        value = &value[..value.len() - 1];
    }
    let values = if value.contains('/') || anchored {
        vec![value.to_owned()]
    } else {
        vec![value.to_owned(), format!("**/{value}")]
    };
    values
        .into_iter()
        .flat_map(|item| {
            if directory {
                vec![item.clone(), format!("{item}/**")]
            } else {
                vec![item]
            }
        })
        .collect()
}

/// Merge additions into the sticky private-path state (`schema_version: 1`).
fn update_sticky(root: &Path, additions: &[String], state_dir: &Path) -> HostResult<Vec<String>> {
    let state_root = lexical_join(state_dir, Path::new(POLICY_STATE_DIRECTORY));
    if state_root.starts_with(root) || root.starts_with(&state_root) {
        return Err(policy_error(
            "Project path policy state must stay outside the source root",
        ));
    }
    let real = std::fs::canonicalize(root).map_err(|e| policy_error(e.to_string()))?;
    let real = real
        .to_str()
        .ok_or_else(|| policy_error("Source root is not UTF-8"))?;
    let key = sha256_hex(real.as_bytes());
    let path = state_root.join(format!("{key}.json"));
    if additions.is_empty() && !path.exists() {
        return Ok(Vec::new());
    }
    super::store::private_directory(&state_root).map_err(|e| policy_error(e.message))?;
    let lock = state_root.join(format!("{key}.lock"));
    if let Err(error) = std::fs::create_dir(&lock) {
        return Err(if error.kind() == std::io::ErrorKind::AlreadyExists {
            policy_error("Project path policy state is busy")
        } else {
            policy_error(error.to_string())
        });
    }
    let result = merge_sticky(&path, additions);
    let removed = std::fs::remove_dir_all(&lock);
    let merged = result?;
    removed.map_err(|e| policy_error(format!("Policy lock cleanup failed: {e}")))?;
    Ok(merged)
}

fn merge_sticky(path: &Path, additions: &[String]) -> HostResult<Vec<String>> {
    let mut current: Vec<String> = if path.exists() {
        let source = read_bounded(path, MAX_STICKY_BYTES)?;
        let parsed: serde_json::Value = serde_json::from_str(&source)
            .map_err(|_| policy_error("Stored Project private-path policy is invalid"))?;
        let items = parsed["private_paths"]
            .as_array()
            .filter(|_| parsed["schema_version"] == 1)
            .ok_or_else(|| policy_error("Stored Project private-path policy is invalid"))?;
        items
            .iter()
            .map(|item| {
                item.as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| policy_error("Stored Project private-path policy is invalid"))
            })
            .collect::<HostResult<_>>()?
    } else {
        Vec::new()
    };
    current.extend(additions.iter().cloned());
    current.sort_by(|a, b| a.encode_utf16().cmp(b.encode_utf16()));
    current.dedup();
    for pattern in &current {
        private_pattern(pattern)?;
    }
    Matcher::new(current.iter().map(String::as_str), true)?;
    let body = format!(
        "{}\n",
        serde_json::json!({"schema_version": 1, "private_paths": current})
    );
    super::store::write_private_file(path, body.as_bytes()).map_err(|e| policy_error(e.message))?;
    Ok(current)
}
