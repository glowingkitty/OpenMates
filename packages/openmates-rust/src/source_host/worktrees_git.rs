//! Git plumbing for chat worktrees (`worktrees.rs`): repository discovery,
//! ref/HEAD/landing queries and the sandboxed `git` runner. Shared core,
//! native source host only. spec: specifications/features/projects
//! `projects.sources.chat-worktrees`.
// Landing queries serve the lifecycle half of `worktrees.rs` (see there).
#![cfg_attr(not(test), allow(dead_code))]

use super::worktrees::{WResult, WorktreeError, valid_branch};
use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

const MAX_DETAIL_CHARS: usize = 512;

/// The repository that contains a source root.
pub(super) struct Repository {
    /// Canonical top-level directory of the repository checkout.
    pub(super) toplevel: PathBuf,
    /// The source root's path inside it (`""` or `"sub/dir/"`).
    pub(super) prefix: String,
}

/// The repository containing `source_root`, or `None` for a plain folder.
/// The `.git` walk mirrors `path_policy::git_policy_root`, so plain folders
/// never spawn Git; once a `.git` exists, Git must answer (fail closed).
pub(super) fn repository(source_root: &Path) -> WResult<Option<Repository>> {
    if !source_root.ancestors().any(|dir| dir.join(".git").exists()) {
        return Ok(None);
    }
    let out = git(
        source_root,
        "rev-parse",
        &[
            "rev-parse".as_ref(),
            "--show-toplevel".as_ref(),
            "--show-prefix".as_ref(),
        ],
    )?;
    let mut lines = out.lines();
    let (Some(top), prefix) = (lines.next(), lines.next().unwrap_or("")) else {
        return Err(WorktreeError::Git {
            command: "rev-parse",
            detail: "no toplevel".into(),
        });
    };
    let toplevel = std::fs::canonicalize(top)
        .map_err(|e| WorktreeError::Io(format!("repository root: {e}")))?;
    Ok(Some(Repository {
        toplevel,
        prefix: prefix.to_owned(),
    }))
}

pub(super) fn is_worktree_top(path: &Path) -> WResult<bool> {
    if !path.join(".git").is_file() {
        return Ok(false);
    }
    let top = git(
        path,
        "rev-parse",
        &["rev-parse".as_ref(), "--show-toplevel".as_ref()],
    )?;
    let canonical =
        std::fs::canonicalize(path).map_err(|e| WorktreeError::Io(format!("worktree: {e}")))?;
    Ok(Path::new(top.trim_end()) == canonical)
}

pub(super) fn current_branch(toplevel: &Path) -> WResult<String> {
    let args: [&OsStr; 4] = [
        "symbolic-ref".as_ref(),
        "--quiet".as_ref(),
        "--short".as_ref(),
        "HEAD".as_ref(),
    ];
    match git(toplevel, "symbolic-ref", &args) {
        Ok(name) => Ok(name.trim_end().to_owned()),
        Err(WorktreeError::Git { .. }) => Err(WorktreeError::TargetBranchUnavailable(
            "source HEAD is detached".into(),
        )),
        Err(other) => Err(other),
    }
}

pub(super) fn branch_commit(dir: &Path, branch: &str) -> WResult<Option<String>> {
    if !valid_branch(branch) {
        return Err(WorktreeError::InvalidTargetBranch);
    }
    let name = format!("refs/heads/{branch}");
    if git(
        dir,
        "check-ref-format",
        &["check-ref-format".as_ref(), name.as_ref()],
    )
    .is_err()
    {
        return Err(WorktreeError::InvalidTargetBranch);
    }
    ref_commit(dir, &name)
}

/// Commit a full ref name points to, or `None` when the ref does not exist.
pub(super) fn ref_commit(dir: &Path, name: &str) -> WResult<Option<String>> {
    let spec = format!("{name}^{{commit}}");
    let args: [&OsStr; 4] = [
        "rev-parse".as_ref(),
        "--verify".as_ref(),
        "--quiet".as_ref(),
        spec.as_ref(),
    ];
    match run(dir, &args)? {
        (Some(0), out) => Ok(Some(out.trim_end().to_owned())),
        (Some(1), _) => Ok(None),
        (_, _) => Err(WorktreeError::Git {
            command: "rev-parse --verify",
            detail: "unexpected status".into(),
        }),
    }
}

pub(super) fn head_commit(path: &Path) -> WResult<String> {
    Ok(git(
        path,
        "rev-parse HEAD",
        &["rev-parse".as_ref(), "HEAD".as_ref()],
    )?
    .trim_end()
    .to_owned())
}

pub(super) fn is_dirty(path: &Path) -> WResult<bool> {
    let args: [&OsStr; 3] = [
        "status".as_ref(),
        "--porcelain=v1".as_ref(),
        "--untracked-files=normal".as_ref(),
    ];
    Ok(!git(path, "status", &args)?.trim().is_empty())
}

/// `Some((landed, ahead))`, or `None` when the target branch no longer exists.
pub(super) fn landing(dir: &Path, head: &str, target: &str) -> WResult<Option<(bool, u64)>> {
    let Some(target_commit) = branch_commit(dir, target)? else {
        return Ok(None);
    };
    let range = format!("{target_commit}..{head}");
    let ahead = git(
        dir,
        "rev-list --count",
        &["rev-list".as_ref(), "--count".as_ref(), range.as_ref()],
    )?;
    let ahead: u64 = ahead.trim().parse().map_err(|_| WorktreeError::Git {
        command: "rev-list --count",
        detail: "not a number".into(),
    })?;
    let args: [&OsStr; 4] = [
        "merge-base".as_ref(),
        "--is-ancestor".as_ref(),
        head.as_ref(),
        target_commit.as_ref(),
    ];
    match run(dir, &args)? {
        (Some(0), _) => Ok(Some((true, ahead))),
        (Some(1), _) => Ok(Some((false, ahead))),
        (_, _) => Err(WorktreeError::Git {
            command: "merge-base --is-ancestor",
            detail: "unexpected status".into(),
        }),
    }
}

/// Run Git expecting success and return stdout.
pub(super) fn git(dir: &Path, command: &'static str, args: &[&OsStr]) -> WResult<String> {
    let output = spawn(dir, args)?;
    if output.status.success() {
        return String::from_utf8(output.stdout).map_err(|_| WorktreeError::Git {
            command,
            detail: "output is not UTF-8".into(),
        });
    }
    let detail: String = String::from_utf8_lossy(&output.stderr)
        .trim()
        .chars()
        .take(MAX_DETAIL_CHARS)
        .collect();
    Err(WorktreeError::Git { command, detail })
}

/// Run Git and return its exit code with stdout (for status-coded queries).
pub(super) fn run(dir: &Path, args: &[&OsStr]) -> WResult<(Option<i32>, String)> {
    let output = spawn(dir, args)?;
    Ok((
        output.status.code(),
        String::from_utf8_lossy(&output.stdout).into_owned(),
    ))
}

/// Git via argv with an explicit `-C`, no shell and a cleared environment
/// (only `PATH` to find `git` and `HOME` for the user's own config survive).
/// Hooks and fsmonitor are disabled: a repository's config must not make the
/// host run programs while it manages worktrees.
fn spawn(dir: &Path, args: &[&OsStr]) -> WResult<std::process::Output> {
    let mut command = Command::new("git");
    command
        .env_clear()
        .env("LC_ALL", "C")
        .env("GIT_TERMINAL_PROMPT", "0")
        .args([
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-C",
        ])
        .arg(dir)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for key in ["PATH", "HOME"] {
        if let Some(value) = std::env::var_os(key) {
            command.env(key, value);
        }
    }
    command
        .output()
        .map_err(|e| WorktreeError::GitUnavailable(e.to_string()))
}
