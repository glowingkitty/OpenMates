//! Chat worktrees for connected Git sources (shared core, native source host).
//!
//! One Git worktree per workspace chat at `<state_dir>/worktrees/<source>/<chat>`
//! (default state dir `~/.openmates`), detached from the source's target branch
//! and created on first write; a hidden ref `refs/openmates/chats/<chat>` (not a
//! branch) protects its commits. No npm original. spec: specifications/features/
//! projects `projects.sources.chat-worktrees`.
// The request path uses `ensure`/`resolve_existing`; the lifecycle half
// (`state`, `list`, `remove_if_safe`, `sweep_idle`) is consumed by the landing
// tools and host cleanup of the next slice and is exercised by the tests now.
#![cfg_attr(not(test), allow(dead_code))]

use super::store::{private_directory, write_private_file};
use super::worktrees_git::{
    branch_commit, current_branch, git, head_commit, is_dirty, is_worktree_top, landing,
    ref_commit, repository,
};
use serde::{Deserialize, Serialize};
use std::ffi::OsStr;
use std::fmt;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};

/// Directory below the OpenMates state directory that holds every chat worktree.
pub(crate) const WORKTREE_DIRECTORY: &str = "worktrees";
/// Idle time after which [`WorktreeArea::sweep_idle`] tries to remove a worktree.
pub(crate) const IDLE_LIMIT_MS: u64 = 14 * 24 * 60 * 60 * 1000;
const HIDDEN_REF_PREFIX: &str = "refs/openmates/chats/";
const STATE_SUFFIX: &str = ".state.json";
const STATE_SCHEMA_VERSION: u32 = 1;
/// `last_used_ms` is rewritten at most once per interval so reads stay cheap.
const TOUCH_INTERVAL_MS: u64 = 60_000;
const MAX_STATE_BYTES: u64 = 16 * 1024;

/// Serializes worktree creation and removal in this process: two first writes
/// of the same chat must not both run `git worktree add`.
static AREA_LOCK: Mutex<()> = Mutex::new(());

fn area_lock() -> MutexGuard<'static, ()> {
    // A poisoned lock only means an earlier operation panicked; every
    // operation re-reads Git and the state file, so continuing is safe.
    AREA_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

/// A chat-worktree failure with a stable code.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum WorktreeError {
    /// The chat id is not `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`.
    InvalidChatId,
    /// The source id is not `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`.
    InvalidSourceId,
    /// The target branch name is not a plain, valid branch name.
    InvalidTargetBranch,
    /// The target branch does not exist or the source has a detached HEAD.
    TargetBranchUnavailable(String),
    /// The `git` binary could not be started.
    GitUnavailable(String),
    /// A `git` command failed.
    Git {
        command: &'static str,
        detail: String,
    },
    /// The chat has no worktree.
    NotFound,
    /// The worktree state file is missing, unreadable or belongs elsewhere.
    State(String),
    /// A filesystem operation failed.
    Io(String),
}

impl WorktreeError {
    /// Stable machine code for logs and diagnostics.
    pub(crate) fn code(&self) -> &'static str {
        match self {
            Self::InvalidChatId => "invalid_chat_id",
            Self::InvalidSourceId => "invalid_source_id",
            Self::InvalidTargetBranch => "invalid_target_branch",
            Self::TargetBranchUnavailable(_) => "target_branch_unavailable",
            Self::GitUnavailable(_) => "git_unavailable",
            Self::Git { .. } => "git_failed",
            Self::NotFound => "worktree_not_found",
            Self::State(_) => "worktree_state_invalid",
            Self::Io(_) => "worktree_io_failed",
        }
    }
}

impl fmt::Display for WorktreeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TargetBranchUnavailable(d)
            | Self::GitUnavailable(d)
            | Self::State(d)
            | Self::Io(d) => {
                write!(f, "{}: {d}", self.code())
            }
            Self::Git { command, detail } => write!(f, "git_failed: git {command}: {detail}"),
            _ => f.write_str(self.code()),
        }
    }
}

impl std::error::Error for WorktreeError {}

impl From<WorktreeError> for super::HostError {
    /// Requesters only learn `operation_failed`; the code stays in the local message.
    fn from(error: WorktreeError) -> Self {
        Self::failed(error.to_string())
    }
}

pub(super) type WResult<T> = std::result::Result<T, WorktreeError>;

/// Strict id charset: ids become path components and ref names, so anything
/// that could traverse (`..`, `/`), hide (`.`) or look like an option (`-`)
/// is refused rather than sanitized.
pub(crate) fn valid_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    (1..=128).contains(&bytes.len())
        && bytes[0].is_ascii_alphanumeric()
        && bytes
            .iter()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'))
}

/// Plain branch names only (`dev`, `release/1.2`); `git check-ref-format`
/// still runs afterwards for the full Git rules.
pub(super) fn valid_branch(value: &str) -> bool {
    (1..=200).contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'/' | b'-'))
        && !value.starts_with(['-', '/', '.'])
        && !value.ends_with(['/', '.'])
        && !value.ends_with(".lock")
        && !value.contains("..")
        && !value.contains("//")
        && !value.contains("/.")
}

/// One chat's worktree as the source host uses it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ChatWorktree {
    /// Stable source id (a validated path component).
    pub(crate) source_id: String,
    /// Workspace (root parent) chat id.
    pub(crate) chat_id: String,
    /// Worktree top-level directory.
    pub(crate) path: PathBuf,
    /// The source root's counterpart inside the worktree (`path` plus the
    /// source root's prefix inside its repository).
    pub(crate) root: PathBuf,
    /// Canonical connected source root.
    pub(crate) source_root: PathBuf,
    /// Branch the chat's commits must land on.
    pub(crate) target_branch: String,
}

/// Observed state of one chat worktree.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct WorktreeState {
    /// Chat id the worktree belongs to.
    pub(crate) chat_id: String,
    /// Worktree top-level directory.
    pub(crate) path: PathBuf,
    /// Current detached HEAD commit.
    pub(crate) head: String,
    /// Branch the commits must land on.
    pub(crate) target_branch: String,
    /// Commits on HEAD that the target branch does not contain.
    pub(crate) ahead: u64,
    /// Tracked modifications or untracked (not ignored) files exist.
    pub(crate) dirty: bool,
    /// HEAD is an ancestor of (or equal to) the target branch.
    pub(crate) landed: bool,
    /// Last time the host resolved this worktree (Unix ms).
    pub(crate) last_used_ms: u64,
}

/// Why a worktree was kept instead of removed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum KeptReason {
    /// Tracked changes or untracked files would be lost.
    UncommittedChanges,
    /// HEAD has commits that have not landed on the target branch.
    UnlandedCommits { ahead: u64 },
    /// The target branch is gone, so landing cannot be proven.
    TargetBranchMissing,
}

/// Outcome of a removal attempt.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Removal {
    /// The worktree, its hidden ref and its state file are gone.
    Removed,
    /// Nothing was deleted.
    Kept(KeptReason),
}

/// One entry of an idle sweep.
#[derive(Debug)]
pub(crate) struct SweepOutcome {
    /// Source the worktree belongs to.
    pub(crate) source_id: String,
    /// Chat the worktree belongs to.
    pub(crate) chat_id: String,
    /// Removal result; an error affects only this entry.
    pub(crate) result: WResult<Removal>,
}

/// Persisted per-chat metadata next to (never inside) the worktree:
/// `<area>/<source>/<chat>.state.json`. It records the target branch chosen
/// at creation and the idle clock; Git stays the authority for HEAD/landing.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StateFile {
    schema_version: u32,
    source_id: String,
    chat_id: String,
    source_root: PathBuf,
    prefix: String,
    target_branch: String,
    created_ms: u64,
    last_used_ms: u64,
}

/// The host-owned worktree area below one OpenMates state directory.
pub(crate) struct WorktreeArea {
    base: PathBuf,
}

impl WorktreeArea {
    /// The area for `state_dir` (`<state_dir>/worktrees`).
    pub(crate) fn new(state_dir: &Path) -> Self {
        Self {
            base: state_dir.join(WORKTREE_DIRECTORY),
        }
    }

    fn chat_path(&self, source_id: &str, chat_id: &str) -> PathBuf {
        self.base.join(source_id).join(chat_id)
    }

    fn state_path(&self, source_id: &str, chat_id: &str) -> PathBuf {
        self.base
            .join(source_id)
            .join(format!("{chat_id}{STATE_SUFFIX}"))
    }

    /// Resolve or create the chat's worktree for a write. Returns `None` for a
    /// source that is not inside a Git repository (plain folders are edited
    /// live). A new worktree starts at the hidden ref when one survives from an
    /// earlier worktree, else at the target branch: `target_branch`, or the
    /// branch currently checked out in the source root.
    ///
    /// # Errors
    /// Invalid ids or branch, a missing/detached target, Git or IO failures,
    /// or a state file that belongs to another source root.
    pub(crate) fn ensure(
        &self,
        source_root: &Path,
        source_id: &str,
        chat_id: &str,
        target_branch: Option<&str>,
        now_ms: u64,
    ) -> WResult<Option<ChatWorktree>> {
        check_ids(source_id, chat_id)?;
        let _guard = area_lock();
        let Some(repo) = repository(source_root)? else {
            return Ok(None);
        };
        let path = self.chat_path(source_id, chat_id);
        let previous = self.read_state(source_id, chat_id)?;
        if let Some(state) = &previous {
            same_source(state, source_root)?;
            if is_worktree_top(&path)? {
                let worktree = self.touch(state.clone(), now_ms)?;
                record_head(&worktree)?;
                return Ok(Some(worktree));
            }
        }
        let target = match target_branch.or(previous.as_ref().map(|s| s.target_branch.as_str())) {
            Some(branch) => branch.to_owned(),
            None => current_branch(&repo.toplevel)?,
        };
        let target_commit = branch_commit(&repo.toplevel, &target)?
            .ok_or_else(|| WorktreeError::TargetBranchUnavailable(target.clone()))?;
        let start = ref_commit(&repo.toplevel, &hidden_ref(chat_id))?.unwrap_or(target_commit);
        private_directory(&self.base).map_err(|e| WorktreeError::Io(e.message))?;
        private_directory(&self.base.join(source_id)).map_err(|e| WorktreeError::Io(e.message))?;
        let mut args: Vec<&OsStr> = vec!["worktree".as_ref(), "add".as_ref(), "--detach".as_ref()];
        // A registered-but-deleted worktree at this path blocks `add`; only our
        // own earlier worktree can be registered here, so overriding is safe.
        if previous.is_some() {
            args.push("--force".as_ref());
        }
        // The path is absolute and the start a full commit id, so neither can
        // be read as an option; passing a commit (never a branch name) keeps
        // `worktree add` from creating a branch.
        args.extend([path.as_os_str(), start.as_ref()]);
        git(&repo.toplevel, "worktree add", &args)?;
        let state = StateFile {
            schema_version: STATE_SCHEMA_VERSION,
            source_id: source_id.to_owned(),
            chat_id: chat_id.to_owned(),
            source_root: source_root.to_path_buf(),
            prefix: repo.prefix,
            target_branch: target,
            created_ms: previous.as_ref().map_or(now_ms, |s| s.created_ms),
            last_used_ms: now_ms,
        };
        self.write_state(&state)?;
        let worktree = self.worktree_of(&state);
        record_head(&worktree)?;
        Ok(Some(worktree))
    }

    /// The chat's worktree if it already exists (reads before the first write
    /// use the source root). Spawns no Git process.
    ///
    /// # Errors
    /// Invalid ids, an unreadable state file, or one for another source root.
    pub(crate) fn resolve_existing(
        &self,
        source_root: &Path,
        source_id: &str,
        chat_id: &str,
        now_ms: u64,
    ) -> WResult<Option<ChatWorktree>> {
        check_ids(source_id, chat_id)?;
        let Some(state) = self.read_state(source_id, chat_id)? else {
            return Ok(None);
        };
        same_source(&state, source_root)?;
        if !self.chat_path(source_id, chat_id).join(".git").exists() {
            return Ok(None);
        }
        self.touch(state, now_ms).map(Some)
    }

    /// Observed Git state of one chat worktree.
    ///
    /// # Errors
    /// `NotFound` without a worktree; Git failures.
    pub(crate) fn state(&self, source_id: &str, chat_id: &str) -> WResult<WorktreeState> {
        check_ids(source_id, chat_id)?;
        let file = self
            .read_state(source_id, chat_id)?
            .ok_or(WorktreeError::NotFound)?;
        let worktree = self.worktree_of(&file);
        if !is_worktree_top(&worktree.path)? {
            return Err(WorktreeError::NotFound);
        }
        let head = head_commit(&worktree.path)?;
        let dirty = is_dirty(&worktree.path)?;
        let (landed, ahead) =
            landing(&worktree.source_root, &head, &file.target_branch)?.unwrap_or((false, 0));
        Ok(WorktreeState {
            chat_id: file.chat_id,
            path: worktree.path,
            head,
            target_branch: file.target_branch,
            ahead,
            dirty,
            landed,
            last_used_ms: file.last_used_ms,
        })
    }

    /// Every chat worktree of one source, ordered by chat id.
    ///
    /// # Errors
    /// Invalid source id, unreadable area, or a failing worktree.
    pub(crate) fn list(&self, source_id: &str) -> WResult<Vec<WorktreeState>> {
        if !valid_id(source_id) {
            return Err(WorktreeError::InvalidSourceId);
        }
        self.chat_ids(source_id)?
            .iter()
            .map(|chat| self.state(source_id, chat))
            .collect()
    }

    /// Remove the worktree, its hidden ref and its state file, unless that
    /// would lose work: uncommitted changes or commits that are not an ancestor
    /// of the target branch keep everything in place.
    ///
    /// # Errors
    /// `NotFound` without a state file; Git or IO failures.
    pub(crate) fn remove_if_safe(&self, source_id: &str, chat_id: &str) -> WResult<Removal> {
        check_ids(source_id, chat_id)?;
        let _guard = area_lock();
        let file = self
            .read_state(source_id, chat_id)?
            .ok_or(WorktreeError::NotFound)?;
        let worktree = self.worktree_of(&file);
        let present = is_worktree_top(&worktree.path)?;
        let head = if present {
            if is_dirty(&worktree.path)? {
                return Ok(Removal::Kept(KeptReason::UncommittedChanges));
            }
            Some(record_head(&worktree)?)
        } else {
            ref_commit(&file.source_root, &hidden_ref(chat_id))?
        };
        if let Some(head) = &head {
            match landing(&file.source_root, head, &file.target_branch)? {
                None => return Ok(Removal::Kept(KeptReason::TargetBranchMissing)),
                Some((false, ahead)) => {
                    return Ok(Removal::Kept(KeptReason::UnlandedCommits { ahead }));
                }
                Some((true, _)) => {}
            }
        }
        if present {
            git(
                &file.source_root,
                "worktree remove",
                &[
                    "worktree".as_ref(),
                    "remove".as_ref(),
                    worktree.path.as_os_str(),
                ],
            )?;
        } else {
            // The directory is already gone; drop Git's stale registration.
            git(
                &file.source_root,
                "worktree prune",
                &["worktree".as_ref(), "prune".as_ref()],
            )?;
        }
        if head.is_some() {
            let name = hidden_ref(chat_id);
            git(
                &file.source_root,
                "update-ref -d",
                &["update-ref".as_ref(), "-d".as_ref(), name.as_ref()],
            )?;
        }
        std::fs::remove_file(self.state_path(source_id, chat_id))
            .map_err(|e| WorktreeError::Io(format!("remove worktree state: {e}")))?;
        Ok(Removal::Removed)
    }

    /// Try to remove every worktree idle for at least `idle_ms`
    /// ([`IDLE_LIMIT_MS`] in production). Unlanded or dirty worktrees are
    /// kept and reported; worktrees used recently are skipped silently.
    ///
    /// # Errors
    /// Only an unreadable area; per-entry failures are in the outcome.
    pub(crate) fn sweep_idle(&self, now_ms: u64, idle_ms: u64) -> WResult<Vec<SweepOutcome>> {
        let mut outcomes = Vec::new();
        for source_id in list_names(&self.base, |name| valid_id(name).then(|| name.to_owned()))? {
            for chat_id in self.chat_ids(&source_id)? {
                let idle = match self.read_state(&source_id, &chat_id) {
                    Ok(Some(file)) => now_ms.saturating_sub(file.last_used_ms) >= idle_ms,
                    Ok(None) => false,
                    Err(error) => {
                        outcomes.push(SweepOutcome {
                            source_id: source_id.clone(),
                            chat_id,
                            result: Err(error),
                        });
                        continue;
                    }
                };
                if idle {
                    let result = self.remove_if_safe(&source_id, &chat_id);
                    outcomes.push(SweepOutcome {
                        source_id: source_id.clone(),
                        chat_id,
                        result,
                    });
                }
            }
        }
        Ok(outcomes)
    }

    fn chat_ids(&self, source_id: &str) -> WResult<Vec<String>> {
        list_names(&self.base.join(source_id), |name| {
            name.strip_suffix(STATE_SUFFIX)
                .filter(|id| valid_id(id))
                .map(str::to_owned)
        })
    }

    fn worktree_of(&self, state: &StateFile) -> ChatWorktree {
        let path = self.chat_path(&state.source_id, &state.chat_id);
        ChatWorktree {
            source_id: state.source_id.clone(),
            chat_id: state.chat_id.clone(),
            root: if state.prefix.is_empty() {
                path.clone()
            } else {
                path.join(&state.prefix)
            },
            path,
            source_root: state.source_root.clone(),
            target_branch: state.target_branch.clone(),
        }
    }

    fn touch(&self, mut state: StateFile, now_ms: u64) -> WResult<ChatWorktree> {
        if now_ms.saturating_sub(state.last_used_ms) >= TOUCH_INTERVAL_MS {
            state.last_used_ms = now_ms;
            self.write_state(&state)?;
        }
        Ok(self.worktree_of(&state))
    }

    fn read_state(&self, source_id: &str, chat_id: &str) -> WResult<Option<StateFile>> {
        let path = self.state_path(source_id, chat_id);
        let file = match std::fs::File::open(&path) {
            Ok(file) => file,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(e) => return Err(WorktreeError::Io(format!("open worktree state: {e}"))),
        };
        let mut text = String::new();
        file.take(MAX_STATE_BYTES + 1)
            .read_to_string(&mut text)
            .map_err(|e| WorktreeError::State(format!("read: {e}")))?;
        if text.len() as u64 > MAX_STATE_BYTES {
            return Err(WorktreeError::State("state file is too large".into()));
        }
        let state: StateFile =
            serde_json::from_str(&text).map_err(|e| WorktreeError::State(format!("parse: {e}")))?;
        let valid = state.schema_version == STATE_SCHEMA_VERSION
            && state.source_id == source_id
            && state.chat_id == chat_id
            && state.source_root.is_absolute()
            && valid_branch(&state.target_branch)
            && (state.prefix.is_empty()
                || super::path_policy::source_relative(state.prefix.trim_end_matches('/')).is_ok());
        if !valid {
            return Err(WorktreeError::State(
                "state file does not match its location".into(),
            ));
        }
        Ok(Some(state))
    }

    fn write_state(&self, state: &StateFile) -> WResult<()> {
        let body = serde_json::to_vec(state).map_err(|e| WorktreeError::State(e.to_string()))?;
        write_private_file(&self.state_path(&state.source_id, &state.chat_id), &body)
            .map_err(|e| WorktreeError::Io(e.message))
    }
}

/// Point the chat's hidden ref at the worktree's current HEAD and return it.
/// Call after every operation that moves HEAD (commit, rebase); refs under
/// `refs/openmates/` are shared by all worktrees of the repository.
///
/// # Errors
/// Git failures.
pub(crate) fn record_head(worktree: &ChatWorktree) -> WResult<String> {
    let head = head_commit(&worktree.path)?;
    let name = hidden_ref(&worktree.chat_id);
    git(
        &worktree.path,
        "update-ref",
        &["update-ref".as_ref(), name.as_ref(), head.as_ref()],
    )?;
    Ok(head)
}

/// Hidden ref name for a validated chat id.
pub(crate) fn hidden_ref(chat_id: &str) -> String {
    format!("{HIDDEN_REF_PREFIX}{chat_id}")
}

fn check_ids(source_id: &str, chat_id: &str) -> WResult<()> {
    if !valid_id(source_id) {
        return Err(WorktreeError::InvalidSourceId);
    }
    if !valid_id(chat_id) {
        return Err(WorktreeError::InvalidChatId);
    }
    Ok(())
}

fn same_source(state: &StateFile, source_root: &Path) -> WResult<()> {
    if state.source_root != source_root {
        return Err(WorktreeError::State(
            "chat worktree belongs to another source root".into(),
        ));
    }
    Ok(())
}

fn list_names(dir: &Path, keep: impl Fn(&str) -> Option<String>) -> WResult<Vec<String>> {
    let entries = match std::fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(e) => return Err(WorktreeError::Io(format!("list worktrees: {e}"))),
    };
    let mut names = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|e| WorktreeError::Io(format!("list worktrees: {e}")))?;
        if let Some(name) = entry.file_name().to_str().and_then(&keep) {
            names.push(name);
        }
    }
    names.sort();
    Ok(names)
}
