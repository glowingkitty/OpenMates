//! Source-root boundary and no-follow file access for the filesystem host.
//!
//! Mirrors `canonicalProjectSourceRoot` (`projectSourceRootPolicy.ts`) and the
//! `resolveApprovedPath` / `assertInsideRoot` / `openedDescriptorPath` helpers of
//! `remoteAccess.ts`: a request path is resolved lexically inside the canonical
//! root, every existing component is refused when it is a symlink, and opened
//! descriptors are re-checked through `/proc/self/fd` (or realpath) so a race
//! cannot redirect a read outside the approved root.

use super::{HostError, HostResult};
use std::fs::File;
use std::os::unix::fs::MetadataExt;
use std::path::{Component, Path, PathBuf};

/// Canonicalize `root` and refuse any overlap with the OpenMates state directory.
///
/// # Errors
/// `invalid_path` when the root is missing or not a directory; `protected_path`
/// when it overlaps private CLI state (npm message contains "private").
pub(crate) fn canonical_root(root: &Path, state_dir: &Path) -> HostResult<PathBuf> {
    let canonical =
        std::fs::canonicalize(root).map_err(|e| HostError::io("Project source root", &e))?;
    let metadata =
        std::fs::metadata(&canonical).map_err(|e| HostError::io("Project source root", &e))?;
    if !metadata.is_dir() {
        return Err(HostError::invalid_path(
            "Project source root is not a directory",
        ));
    }
    let state = canonical_potential_path(state_dir)?;
    if canonical.starts_with(&state) || state.starts_with(&canonical) {
        return Err(HostError::protected(
            "Project source root overlaps OpenMates private state",
        ));
    }
    Ok(canonical)
}

/// Canonicalize a chat worktree root. Unlike [`canonical_root`] the root must
/// lie strictly inside `<state_dir>/worktrees/` (the host-owned worktree
/// area, see `worktrees.rs`); it still must never contain the state directory
/// itself, so the private policy state, journal and credentials stay
/// unreachable. Path confinement inside the root then applies unchanged.
///
/// # Errors
/// `invalid_path` when missing or not a directory; `protected_path` when the
/// root is outside the worktree area or contains private state.
pub(crate) fn canonical_worktree_root(root: &Path, state_dir: &Path) -> HostResult<PathBuf> {
    let canonical =
        std::fs::canonicalize(root).map_err(|e| HostError::io("Chat worktree root", &e))?;
    let metadata =
        std::fs::metadata(&canonical).map_err(|e| HostError::io("Chat worktree root", &e))?;
    if !metadata.is_dir() {
        return Err(HostError::invalid_path(
            "Chat worktree root is not a directory",
        ));
    }
    let state = canonical_potential_path(state_dir)?;
    let area = state.join(super::worktrees::WORKTREE_DIRECTORY);
    if canonical == area || !canonical.starts_with(&area) || state.starts_with(&canonical) {
        return Err(HostError::protected(
            "Chat worktree root is outside the OpenMates worktree area",
        ));
    }
    Ok(canonical)
}

/// npm `canonicalizePotentialPath`: realpath of the deepest existing ancestor
/// plus the missing suffix, without creating anything.
pub(crate) fn canonical_potential_path(value: &Path) -> HostResult<PathBuf> {
    let absolute = lexical_absolute(value)?;
    let mut existing = absolute.clone();
    let mut suffix = Vec::new();
    while !existing.exists() {
        let Some(name) = existing.file_name().map(|n| n.to_owned()) else {
            return Ok(absolute);
        };
        suffix.push(name);
        if !existing.pop() {
            return Ok(absolute);
        }
    }
    let mut out =
        std::fs::canonicalize(&existing).map_err(|e| HostError::io("OpenMates state", &e))?;
    for part in suffix.into_iter().rev() {
        out.push(part);
    }
    Ok(out)
}

/// Node `path.resolve(value)` against the process working directory.
pub(crate) fn lexical_absolute(value: &Path) -> HostResult<PathBuf> {
    let base = if value.is_absolute() {
        PathBuf::from("/")
    } else {
        std::env::current_dir().map_err(|e| HostError::io("Working directory", &e))?
    };
    Ok(lexical_join(&base, value))
}

/// Node `path.resolve(base, value)` without touching the filesystem.
pub(crate) fn lexical_join(base: &Path, value: &Path) -> PathBuf {
    let mut out = if value.is_absolute() {
        PathBuf::from("/")
    } else {
        base.to_path_buf()
    };
    for component in value.components() {
        match component {
            Component::RootDir | Component::Prefix(_) => out = PathBuf::from("/"),
            Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            Component::Normal(part) => out.push(part),
        }
    }
    out
}

/// npm `assertInsideRoot`.
pub(crate) fn assert_inside(root: &Path, path: &Path) -> HostResult<()> {
    if path.starts_with(root) {
        Ok(())
    } else {
        Err(HostError::invalid_path(
            "Remote source path escapes the approved source root",
        ))
    }
}

/// npm `resolveApprovedPath`: lexical containment, no symlink component, then
/// realpath containment.
///
/// # Errors
/// `operation_failed` for an empty/NUL path; `invalid_path` for escapes,
/// symlinks and missing components.
pub(crate) fn resolve_approved(root: &Path, relative: &str) -> HostResult<PathBuf> {
    if relative.is_empty() || relative.contains('\0') {
        return Err(HostError::failed("Remote source path is invalid"));
    }
    let lexical = lexical_join(root, Path::new(relative));
    assert_inside(root, &lexical)?;
    let mut current = root.to_path_buf();
    if let Ok(rest) = lexical.strip_prefix(root) {
        for part in rest.components() {
            current.push(part);
            let metadata = std::fs::symlink_metadata(&current)
                .map_err(|e| HostError::io("Remote source path", &e))?;
            if metadata.file_type().is_symlink() {
                return Err(HostError::invalid_path(
                    "Remote source path is a symbolic link",
                ));
            }
        }
    }
    let canonical =
        std::fs::canonicalize(&lexical).map_err(|e| HostError::io("Remote source path", &e))?;
    assert_inside(root, &canonical)?;
    Ok(canonical)
}

/// Hardlink count without following a final symlink.
pub(crate) fn link_count(path: &Path) -> HostResult<u64> {
    std::fs::symlink_metadata(path)
        .map(|m| m.nlink())
        .map_err(|e| HostError::io("Remote source path", &e))
}

/// Refuse multiply-linked files: another name could alias a private file.
pub(crate) fn refuse_hardlink(path: &Path) -> HostResult<()> {
    if link_count(path)? > 1 {
        return Err(HostError::protected(
            "Remote source file is a protected hardlink",
        ));
    }
    Ok(())
}

/// Open read-only with `O_NOFOLLOW` and re-check the descriptor's real path.
///
/// # Errors
/// `invalid_path` for a symlink (`ELOOP`), a missing file or an escape.
pub(crate) fn open_inside(root: &Path, path: &Path) -> HostResult<File> {
    use rustix::fs::{Mode, OFlags};
    let fd = rustix::fs::open(
        path,
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    )
    .map_err(|errno| {
        if errno == rustix::io::Errno::LOOP {
            HostError::invalid_path("Remote source path is a symbolic link")
        } else {
            HostError::io(
                "Remote source file",
                &std::io::Error::from_raw_os_error(errno.raw_os_error()),
            )
        }
    })?;
    let file = File::from(fd);
    assert_inside(root, &opened_path(&file, path)?)?;
    Ok(file)
}

/// npm `openedDescriptorPath`.
fn opened_path(file: &File, requested: &Path) -> HostResult<PathBuf> {
    use std::os::fd::AsRawFd;
    let proc = PathBuf::from(format!("/proc/self/fd/{}", file.as_raw_fd()));
    if proc.exists() {
        return std::fs::canonicalize(&proc).map_err(|e| HostError::io("Remote source file", &e));
    }
    std::fs::canonicalize(requested).map_err(|e| HostError::io("Remote source file", &e))
}

/// POSIX `relative(root, path)` with `/` separators; empty for the root itself.
pub(crate) fn relative_posix(root: &Path, path: &Path) -> HostResult<String> {
    let rest = path
        .strip_prefix(root)
        .map_err(|_| HostError::invalid_path("Project policy path escapes its root"))?;
    let mut parts = Vec::new();
    for component in rest.components() {
        match component {
            Component::Normal(part) => parts.push(
                part.to_str()
                    .ok_or_else(|| HostError::invalid_path("Remote source path is not UTF-8"))?
                    .to_owned(),
            ),
            _ => return Err(HostError::invalid_path("Remote source path is invalid")),
        }
    }
    Ok(parts.join("/"))
}

/// Millisecond timestamp like Node `Stats.mtimeMs`.
pub(crate) fn mtime_ms(metadata: &std::fs::Metadata) -> f64 {
    metadata.mtime() as f64 * 1000.0 + metadata.mtime_nsec() as f64 / 1_000_000.0
}

/// Millisecond timestamp like Node `Stats.ctimeMs`.
pub(crate) fn ctime_ms(metadata: &std::fs::Metadata) -> f64 {
    metadata.ctime() as f64 * 1000.0 + metadata.ctime_nsec() as f64 / 1_000_000.0
}
