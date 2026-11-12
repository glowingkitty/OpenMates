//! Git operations on a chat worktree as structured source-host operations:
//! `git_status`, `git_commit`, `git_land` (shared core, native source host
//! only; plan native-agentic-coding-readiness R5). Never free argv: the host
//! runs a fixed set of Git commands through the hardened runner of
//! `worktrees_git.rs` (cleared environment, hooks disabled, no prompts).
//! There is deliberately no push operation: a push always asks the user and
//! has no host seam yet. spec: specifications/features/projects
//! `projects.sources.chat-worktrees`.

use super::dispatch::HostedSource;
use super::worktrees::{ChatWorktree, WorktreeArea, area_lock, record_head};
use super::worktrees_git::{branch_commit, git, head_commit, is_dirty, landing, run};
use super::{HostError, HostResult};
use hmac::{Hmac, Mac};
use serde_json::{Value, json};
use sha2::Sha256;
use std::ffi::OsStr;
use std::path::{Path, PathBuf};

/// Wire operation name of the read-only worktree state.
pub(crate) const STATUS_OPERATION: &str = "git_status";
/// Wire operation name of the commit operation.
pub(crate) const COMMIT_OPERATION: &str = "git_commit";
/// Wire operation name of the landing operation.
pub(crate) const LAND_OPERATION: &str = "git_land";
const MAX_MESSAGE_BYTES: usize = 8 * 1024;
/// Changed files reported by one status answer (the rest is `truncated`).
const MAX_CHANGED_FILES: usize = 500;

fn invalid(message: &str) -> HostError {
    HostError::new("invalid_request", message)
}

/// A validated `arguments.git` proposal of `git_commit` or `git_land`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct GitProposal {
    /// Approval-bound operation id.
    pub(crate) operation_id: String,
    /// Commit message (`git_commit` only).
    pub(crate) message: Option<String>,
}

/// Validate `arguments.git`: `{operation_id, message}` for a commit,
/// `{operation_id}` for a landing. Unknown keys are refused.
///
/// # Errors
/// `invalid_request` for any shape, size or charset violation.
pub(crate) fn validate(value: &Value, with_message: bool) -> HostResult<GitProposal> {
    let object = value
        .as_object()
        .ok_or_else(|| invalid("git must be an object"))?;
    let allowed: &[&str] = if with_message {
        &["operation_id", "message"]
    } else {
        &["operation_id"]
    };
    if object.keys().any(|key| !allowed.contains(&key.as_str())) {
        return Err(invalid("git has an unsupported field"));
    }
    let operation_id = object
        .get("operation_id")
        .and_then(Value::as_str)
        .filter(|id| {
            (1..=128).contains(&id.len())
                && id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b':' | b'-'))
        })
        .ok_or_else(|| invalid("git operation_id is invalid"))?
        .to_owned();
    let message = if with_message {
        Some(
            object
                .get("message")
                .and_then(Value::as_str)
                .filter(|m| {
                    !m.trim().is_empty() && m.len() <= MAX_MESSAGE_BYTES && !m.contains('\0')
                })
                .ok_or_else(|| invalid("git message is invalid"))?
                .to_owned(),
        )
    } else {
        None
    };
    Ok(GitProposal {
        operation_id,
        message,
    })
}

/// HMAC-SHA256(projectKey, JSON tuple), the proposal digest construction of
/// `commands::digest` with its own domain tag:
/// `["openmates-remote-git-proposal-v1", project_id, chat_id, operation,
/// operation_id, message|null]`. The backend holds it from the user's
/// approval; the host refuses a request whose recomputed digest differs.
///
/// # Errors
/// `invalid_request` for an empty project or chat id.
pub(crate) fn digest(
    key: &[u8; 32],
    project_id: &str,
    chat_id: &str,
    operation: &str,
    proposal: &GitProposal,
) -> HostResult<String> {
    if project_id.is_empty() || chat_id.is_empty() {
        return Err(invalid("git identity is incomplete"));
    }
    let message = json!([
        "openmates-remote-git-proposal-v1",
        project_id,
        chat_id,
        operation,
        proposal.operation_id,
        proposal.message,
    ])
    .to_string();
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key)
        .map_err(|_| invalid("git identity is incomplete"))?;
    mac.update(message.as_bytes());
    Ok(mac
        .finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}

/// The chat's existing worktree. Git operations never create one: a chat
/// without a worktree has nothing to report, commit or land.
///
/// # Errors
/// `no_worktree` without a workspace chat id, worktree or Git repository.
pub(crate) fn existing_worktree(
    source: &HostedSource,
    workspace_chat_id: Option<&str>,
    now_ms: u64,
) -> HostResult<(WorktreeArea, ChatWorktree)> {
    let no_worktree = || HostError::new("no_worktree", "The chat has no worktree");
    let chat = workspace_chat_id.ok_or_else(no_worktree)?;
    let source_root = source.root.canonical()?;
    let area = WorktreeArea::new(&source.root.state_dir);
    let worktree = area
        .resolve_existing(&source_root, &source.source_id, chat, now_ms)?
        .ok_or_else(no_worktree)?;
    Ok((area, worktree))
}

/// `git_status`: `{exists, head, target_branch, ahead, dirty, landed,
/// changed_files:[{path,status}], truncated}`. `status` is the two-letter
/// porcelain code (`" M"`, `"??"`, ...). Branch-less: HEAD is detached.
///
/// # Errors
/// `operation_failed` on Git failures.
pub(crate) fn status(area: &WorktreeArea, worktree: &ChatWorktree) -> HostResult<Value> {
    let state = area.state(&worktree.source_id, &worktree.chat_id)?;
    let raw = git(
        &worktree.path,
        "status",
        &[
            "status".as_ref(),
            "--porcelain=v1".as_ref(),
            "-z".as_ref(),
            "--untracked-files=normal".as_ref(),
        ],
    )?;
    let mut changed = Vec::new();
    let mut tokens = raw.split('\0').filter(|t| !t.is_empty());
    while let Some(entry) = tokens.next() {
        let (code, path) = entry.split_at(entry.len().min(2));
        // Renames and copies carry the original path as a second token.
        if code.starts_with(['R', 'C']) || code.ends_with(['R', 'C']) {
            tokens.next();
        }
        changed.push(json!({"path": path.trim_start(), "status": code}));
    }
    let truncated = changed.len() > MAX_CHANGED_FILES;
    changed.truncate(MAX_CHANGED_FILES);
    Ok(json!({
        "exists": true,
        "head": state.head,
        "target_branch": state.target_branch,
        "ahead": state.ahead,
        "dirty": state.dirty,
        "landed": state.landed,
        "changed_files": changed,
        "truncated": truncated,
    }))
}

/// `git_commit`: stage every change in the worktree and commit it with
/// `message`, then move the hidden chat ref. Result `{commit, ahead,
/// target_branch}`.
///
/// # Errors
/// `identity_missing` (no `user.name`/`user.email` in the repository's Git
/// configuration), `nothing_to_commit`, `operation_failed`.
pub(crate) fn commit(worktree: &ChatWorktree, message: &str) -> HostResult<Value> {
    let _guard = area_lock();
    let dir = &worktree.path;
    require_identity(dir)?;
    if !is_dirty(dir)? {
        return Err(HostError::new("nothing_to_commit", "No changes to commit"));
    }
    git(dir, "add", &["add".as_ref(), "-A".as_ref()])?;
    // Hooks are already disabled by the runner; `--no-verify` and
    // `--no-gpg-sign` keep a user's signing setup from prompting.
    git(
        dir,
        "commit",
        &[
            "commit".as_ref(),
            "--quiet".as_ref(),
            "--no-verify".as_ref(),
            "--no-gpg-sign".as_ref(),
            "-m".as_ref(),
            message.as_ref(),
        ],
    )?;
    let head = record_head(worktree)?;
    let ahead = landing(&worktree.source_root, &head, &worktree.target_branch)?
        .map_or(0, |(_, ahead)| ahead);
    Ok(json!({
        "commit": head,
        "ahead": ahead,
        "target_branch": worktree.target_branch,
    }))
}

/// `git_land`: rebase the worktree commits onto the current target tip and
/// fast-forward the target branch. Nothing is forced or deleted.
///
/// Success: `{landed:true, commit, commits, target_branch, checked_out}`
/// (`commits:0` when everything had landed before). A rebase conflict is an
/// answer, not an error: `{landed:false, code:"land_conflict",
/// conflicting_paths}`; the rebase is aborted and the worktree is exactly as
/// before, so the assistant resolves and retries.
///
/// The target branch moves only when it is not checked out anywhere or its
/// checkout is clean (then it is fast-forwarded with the working tree).
///
/// # Errors
/// `worktree_dirty` (commit first), `target_branch_unavailable`,
/// `target_checked_out_dirty`, `identity_missing`, `land_failed`,
/// `operation_failed`.
pub(crate) fn land(worktree: &ChatWorktree) -> HostResult<Value> {
    let _guard = area_lock();
    let dir = &worktree.path;
    let repo = &worktree.source_root;
    let target = &worktree.target_branch;
    if is_dirty(dir)? {
        return Err(HostError::new(
            "worktree_dirty",
            "Commit the worktree changes before landing",
        ));
    }
    let tip = branch_commit(repo, target)?
        .ok_or_else(|| HostError::new("target_branch_unavailable", "The target branch is gone"))?;
    let head = head_commit(dir)?;
    let (landed, commits) = landing(repo, &head, target)?.unwrap_or((false, 0));
    if landed {
        return Ok(json!({
            "landed": true,
            "commit": tip,
            "commits": 0,
            "target_branch": target,
            "checked_out": false,
        }));
    }
    // Refuse before touching anything when the user's checkout has work in it.
    let checkout = checked_out_at(dir, target)?;
    if let Some(path) = &checkout
        && is_dirty(path)?
    {
        return Err(HostError::new(
            "target_checked_out_dirty",
            "The target branch is checked out with uncommitted changes",
        ));
    }
    if !is_ancestor(dir, &tip, &head)? {
        require_identity(dir)?;
        if let Some(conflict) = rebase(dir, &tip, &head)? {
            return Ok(conflict);
        }
    }
    let landed_head = record_head(worktree)?;
    let moved = match &checkout {
        Some(path) => git(
            path,
            "merge --ff-only",
            &[
                "merge".as_ref(),
                "--ff-only".as_ref(),
                "--quiet".as_ref(),
                landed_head.as_ref(),
            ],
        ),
        None => {
            let name = format!("refs/heads/{target}");
            // The old value makes the update fail when the target moved.
            git(
                repo,
                "update-ref",
                &[
                    "update-ref".as_ref(),
                    name.as_ref(),
                    landed_head.as_ref(),
                    tip.as_ref(),
                ],
            )
        }
    };
    moved.map_err(|e| HostError::new("land_failed", e.to_string()))?;
    Ok(json!({
        "landed": true,
        "commit": landed_head,
        "commits": commits,
        "target_branch": target,
        "checked_out": checkout.is_some(),
    }))
}

/// Rebase HEAD onto `tip`. `None` on success; on any failure the rebase is
/// aborted, HEAD must equal `original` again, and a conflict answer carries
/// the conflicting paths.
fn rebase(dir: &Path, tip: &str, original: &str) -> HostResult<Option<Value>> {
    let args: [&OsStr; 3] = ["rebase".as_ref(), "--quiet".as_ref(), tip.as_ref()];
    if run(dir, &args)?.0 == Some(0) {
        return Ok(None);
    }
    let conflicts = git(
        dir,
        "diff",
        &[
            "diff".as_ref(),
            "--name-only".as_ref(),
            "--diff-filter=U".as_ref(),
        ],
    )?;
    git(
        dir,
        "rebase --abort",
        &["rebase".as_ref(), "--abort".as_ref()],
    )?;
    if head_commit(dir)? != original || is_dirty(dir)? {
        return Err(HostError::failed("The worktree changed during the rebase"));
    }
    let paths: Vec<&str> = conflicts.lines().filter(|l| !l.is_empty()).collect();
    if paths.is_empty() {
        return Err(HostError::failed("The rebase failed without conflicts"));
    }
    Ok(Some(json!({
        "landed": false,
        "code": "land_conflict",
        "conflicting_paths": paths,
    })))
}

/// `Some(path)` of the checkout that has `target` checked out, if any.
fn checked_out_at(dir: &Path, target: &str) -> HostResult<Option<PathBuf>> {
    let listing = git(
        dir,
        "worktree list",
        &["worktree".as_ref(), "list".as_ref(), "--porcelain".as_ref()],
    )?;
    let wanted = format!("branch refs/heads/{target}");
    let mut current: Option<&str> = None;
    for line in listing.lines() {
        if let Some(path) = line.strip_prefix("worktree ") {
            current = Some(path);
        } else if line == wanted {
            return Ok(current.map(PathBuf::from));
        }
    }
    Ok(None)
}

fn is_ancestor(dir: &Path, ancestor: &str, descendant: &str) -> HostResult<bool> {
    let args: [&OsStr; 4] = [
        "merge-base".as_ref(),
        "--is-ancestor".as_ref(),
        ancestor.as_ref(),
        descendant.as_ref(),
    ];
    match run(dir, &args)?.0 {
        Some(0) => Ok(true),
        Some(1) => Ok(false),
        _ => Err(HostError::failed("merge-base failed")),
    }
}

/// Commits are authored by the repository's configured identity; a missing
/// one is refused instead of guessing from the host name.
fn require_identity(dir: &Path) -> HostResult<()> {
    for key in ["user.name", "user.email"] {
        let args: [&OsStr; 3] = ["config".as_ref(), "--get".as_ref(), key.as_ref()];
        let (code, value) = run(dir, &args)?;
        if code != Some(0) || value.trim().is_empty() {
            return Err(HostError::new(
                "identity_missing",
                "No Git user.name/user.email is configured",
            ));
        }
    }
    Ok(())
}
