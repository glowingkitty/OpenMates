//! What a confined command may see: builds the [`ConfinementPlan`] for one
//! request root (shared core, native source host only). Finds private paths
//! (built-in, configured and sticky, via `path_policy`) and their hard-link
//! aliases, every Git `config` file, and the Git admin paths a chat worktree
//! needs. Mirrors npm `discoverProjectPathProtection` in `remoteCommandRuntime.ts`.
//! spec: specifications/features/app-skills/code-run `code-run.remote.private-path-deny`.

use super::command_sandbox::{ConfinementPlan, GitAccess, MaskedPath, SystemPath};
use super::path_policy::PathPolicy;
use super::reads::HostRoot;
use super::{HostError, HostResult};
use std::collections::{HashMap, HashSet};
use std::ffi::OsStr;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

/// Entry limit of the private-path scan (npm `MAX_PROJECT_MASK_SCAN_ENTRIES`).
pub(crate) const MAX_SCAN_ENTRIES: usize = 250_000;

fn unavailable(message: impl Into<String>) -> HostError {
    HostError::new("confinement_unavailable", message)
}

/// Inputs that are not derived from the filesystem.
pub(crate) struct PlanInputs<'a> {
    /// Canonical request root.
    pub(crate) root: &'a Path,
    /// Canonical working directory inside the root.
    pub(crate) cwd: &'a Path,
    /// The request root is a chat worktree (its Git admin paths become writable).
    pub(crate) worktree: bool,
    /// Read-only system paths of the tier.
    pub(crate) system: Vec<SystemPath>,
    /// Host scratch directory (Seatbelt `HOME`/`TMPDIR`).
    pub(crate) scratch: PathBuf,
}

/// Build the plan for `inputs.root` under the host's path policy.
///
/// # Errors
/// `confinement_unavailable` when the scan exceeds [`MAX_SCAN_ENTRIES`], a
/// directory cannot be read or Git cannot describe the repository: a
/// private rule that cannot be enforced must not run unconfined.
pub(crate) fn plan(host: &HostRoot, inputs: PlanInputs<'_>) -> HostResult<ConfinementPlan> {
    let policy = host.policy(inputs.root, &[], false)?;
    let mut masked = private_masks(inputs.root, &policy)?;
    let git = git_access(inputs.root, inputs.worktree, &mut masked)?;
    Ok(ConfinementPlan {
        root: inputs.root.to_path_buf(),
        cwd: inputs.cwd.to_path_buf(),
        git,
        masked: normalize(masked),
        system: inputs.system,
        scratch: inputs.scratch,
    })
}

/// Drop masks nested in a masked directory and order them shallow first.
fn normalize(mut masks: Vec<MaskedPath>) -> Vec<MaskedPath> {
    masks.sort_by(|a, b| {
        a.path
            .components()
            .count()
            .cmp(&b.path.components().count())
            .then_with(|| a.path.cmp(&b.path))
    });
    let mut out: Vec<MaskedPath> = Vec::with_capacity(masks.len());
    for mask in masks {
        let covered = out
            .iter()
            .any(|m| m.path == mask.path || (m.directory && mask.path.starts_with(&m.path)));
        if !covered {
            out.push(mask);
        }
    }
    out
}

/// Walk the root without following symlinks and collect what to hide.
fn private_masks(root: &Path, policy: &PathPolicy) -> HostResult<Vec<MaskedPath>> {
    let mut masks = Vec::new();
    let mut masked_inodes: HashSet<(u64, u64)> = HashSet::new();
    let mut linked: HashMap<(u64, u64), Vec<PathBuf>> = HashMap::new();
    let mut directories: Vec<(PathBuf, String)> = vec![(root.to_path_buf(), String::new())];
    let mut visited = 0usize;
    while let Some((directory, prefix)) = directories.pop() {
        let entries = std::fs::read_dir(&directory)
            .map_err(|e| unavailable(format!("Project path scan failed: {e}")))?;
        for entry in entries {
            let entry = entry.map_err(|e| unavailable(format!("Project path scan failed: {e}")))?;
            visited += 1;
            if visited > MAX_SCAN_ENTRIES {
                return Err(unavailable("Project path scan exceeds its entry limit"));
            }
            let path = entry.path();
            let metadata = std::fs::symlink_metadata(&path)
                .map_err(|e| unavailable(format!("Project path scan failed: {e}")))?;
            let name = entry.file_name();
            if name == OsStr::new(".git") {
                // Git internals hold no private-pattern targets except their
                // config (remote URLs with tokens, credential helpers).
                if metadata.is_dir() {
                    mask_file_if_present(&path.join("config"), &mut masks);
                }
                continue;
            }
            let is_dir = metadata.is_dir();
            // A name the policy cannot express (non-UTF-8, control characters,
            // backslashes) is hidden rather than exposed: fail closed.
            let relative = name.to_str().map(|n| {
                if prefix.is_empty() {
                    n.to_owned()
                } else {
                    format!("{prefix}/{n}")
                }
            });
            let private = match &relative {
                Some(rel) => policy.is_private(rel, is_dir).unwrap_or(true),
                None => true,
            };
            if metadata.file_type().is_symlink() {
                if private {
                    mask_link_target(root, &path, &mut masks);
                }
                continue;
            }
            let inode = (metadata.dev(), metadata.ino());
            if private {
                masks.push(MaskedPath {
                    path,
                    directory: is_dir,
                });
                masked_inodes.insert(inode);
                continue;
            }
            if is_dir {
                if let Some(rel) = relative {
                    directories.push((path, rel));
                } else {
                    masks.push(MaskedPath {
                        path,
                        directory: true,
                    });
                }
            } else if metadata.nlink() > 1 {
                linked.entry(inode).or_default().push(path);
            }
        }
    }
    // A hard link to a private file is the same content under an allowed
    // name; hide every alias found inside the root.
    for (inode, paths) in linked {
        if masked_inodes.contains(&inode) {
            masks.extend(paths.into_iter().map(|path| MaskedPath {
                path,
                directory: false,
            }));
        }
    }
    Ok(masks)
}

/// A private-named symlink hides its target when the target is inside the
/// root; a target outside the root is not mounted (or is a read-only system
/// path) and a dangling link exposes nothing.
fn mask_link_target(root: &Path, link: &Path, masks: &mut Vec<MaskedPath>) {
    let Ok(target) = std::fs::canonicalize(link) else {
        return;
    };
    if !target.starts_with(root) {
        return;
    }
    let directory = std::fs::metadata(&target).is_ok_and(|m| m.is_dir());
    masks.push(MaskedPath {
        path: target,
        directory,
    });
}

fn mask_file_if_present(path: &Path, masks: &mut Vec<MaskedPath>) {
    if std::fs::symlink_metadata(path).is_ok_and(|m| m.is_file()) {
        masks.push(MaskedPath {
            path: path.to_path_buf(),
            directory: false,
        });
    }
}

/// Git admin access for a root whose Git directory lies outside it.
///
/// - Root at a repository top with a `.git` directory: everything is inside
///   the root already; only `config` is masked (by the scan).
/// - Chat worktree: the common directory read-only, and read-write its admin
///   directory, `objects/` and `refs/openmates/chats/` so commits to the
///   hidden ref work; `refs/heads` and the user's checkout stay read-only.
/// - Live root inside a larger repository: the Git directory read-only only.
///
/// Every `config`/`config.worktree` and submodule `config` is masked.
fn git_access(root: &Path, worktree: bool, masks: &mut Vec<MaskedPath>) -> HostResult<GitAccess> {
    if !root.ancestors().any(|dir| dir.join(".git").exists()) {
        return Ok(GitAccess::default());
    }
    let out = super::worktrees_git::git(
        root,
        "rev-parse",
        &[
            "rev-parse".as_ref(),
            "--path-format=absolute".as_ref(),
            "--git-dir".as_ref(),
            "--git-common-dir".as_ref(),
            "--show-toplevel".as_ref(),
        ],
    )
    .map_err(|e| unavailable(format!("Git layout is unavailable: {e}")))?;
    let mut lines = out.lines().map(|line| std::fs::canonicalize(line.trim()));
    let (Some(Ok(git_dir)), Some(Ok(common)), Some(Ok(top))) =
        (lines.next(), lines.next(), lines.next())
    else {
        return Err(unavailable("Git layout is unavailable"));
    };
    mask_file_if_present(&common.join("config"), masks);
    mask_file_if_present(&common.join("config.worktree"), masks);
    mask_file_if_present(&git_dir.join("config.worktree"), masks);
    mask_module_configs(&common.join("modules"), masks)?;
    if common.starts_with(root) {
        return Ok(GitAccess::default());
    }
    let mut access = GitAccess {
        read_only: vec![common.clone()],
        writable: Vec::new(),
    };
    let link = top.join(".git");
    if !link.starts_with(root) && !link.starts_with(&common) && link.is_file() {
        access.read_only.push(link);
    }
    if worktree {
        for path in [
            git_dir.clone(),
            common.join("objects"),
            common.join("refs/openmates/chats"),
        ] {
            if path != common && path.is_dir() {
                access.writable.push(path);
            }
        }
    }
    Ok(access)
}

/// Submodule repositories keep their own `config` below `<common>/modules`.
fn mask_module_configs(modules: &Path, masks: &mut Vec<MaskedPath>) -> HostResult<()> {
    if !modules.is_dir() {
        return Ok(());
    }
    let mut stack = vec![modules.to_path_buf()];
    let mut visited = 0usize;
    while let Some(directory) = stack.pop() {
        let entries = std::fs::read_dir(&directory)
            .map_err(|e| unavailable(format!("Git module scan failed: {e}")))?;
        for entry in entries {
            let entry = entry.map_err(|e| unavailable(format!("Git module scan failed: {e}")))?;
            visited += 1;
            if visited > MAX_SCAN_ENTRIES {
                return Err(unavailable("Git module scan exceeds its entry limit"));
            }
            let path = entry.path();
            let Ok(metadata) = std::fs::symlink_metadata(&path) else {
                continue;
            };
            if metadata.is_dir() && entry.file_name() != OsStr::new("objects") {
                stack.push(path);
            } else if metadata.is_file() && entry.file_name() == OsStr::new("config") {
                masks.push(MaskedPath {
                    path,
                    directory: false,
                });
            }
        }
    }
    Ok(())
}
