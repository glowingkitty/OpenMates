//! Crash-recovery journal and write locks for host file mutations.
//!
//! Byte-compatible with `remoteFileWrites.ts` and `remoteCommandSourceLock.ts`
//! so the npm and Rust hosts serialize against each other on one machine:
//! - journal: `<tmp>/openmates-remote-file-journal-<uid>/<sha256(scope)>/
//!   <sha256(scope \0 operation_id)>.json` (`schema_version: 1`, state
//!   `prepared` then `applied`); a replay of an applied entry returns its
//!   receipt, a prepared entry is confirmed only when the file already holds
//!   the recorded after-hash;
//! - path lock: a `proper-lockfile` style `<dir>.lock` directory under
//!   `<tmp>/openmates-remote-file-locks-<uid>` (stale after 30 s);
//! - source lock: a shared `flock` on
//!   `<tmp>/openmates-project-source-locks-<uid>/source-writes.lock`, which
//!   source-mutating commands hold exclusively.

use super::{HostError, HostResult, sha256_hex};
use serde_json::Value;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};

const MAX_FILE_BYTES: u64 = 200 * 1024;
const PATH_LOCK_STALE: Duration = Duration::from_secs(30);
const PATH_LOCK_RETRIES: u32 = 20;
const SOURCE_LOCK_TIMEOUT: Duration = Duration::from_secs(30);

fn uid() -> u32 {
    rustix::process::getuid().as_raw()
}

fn tmp_dir(prefix: &str) -> PathBuf {
    std::env::temp_dir().join(format!("{prefix}-{}", uid()))
}

fn invalid(message: &str) -> HostError {
    HostError::invalid_path(message)
}

fn unconfirmed(message: impl Into<String>) -> HostError {
    HostError::new("operation_unconfirmed", message)
}

/// npm `preparePrivateDirectory` (mutation state): a real `0700` directory
/// owned by this user.
///
/// # Errors
/// `invalid_path` for an unsafe path.
pub(crate) fn private_state_directory(path: &Path) -> HostResult<PathBuf> {
    std::fs::create_dir_all(path).map_err(|_| invalid("Private mutation state path is unsafe"))?;
    let stats =
        std::fs::symlink_metadata(path).map_err(|_| invalid("Private mutation state path is unsafe"))?;
    if !stats.is_dir() || stats.file_type().is_symlink() {
        return Err(invalid("Private mutation state path is unsafe"));
    }
    if stats.uid() != uid() {
        return Err(invalid("Private mutation state path has the wrong owner"));
    }
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
        .map_err(|_| invalid("Private mutation state path is unsafe"))?;
    Ok(path.to_path_buf())
}

/// The default journal root.
pub(crate) fn journal_root() -> PathBuf {
    tmp_dir("openmates-remote-file-journal")
}

/// Journal path for one scoped operation.
pub(crate) fn journal_path(root: &Path, scope: &str, operation_id: &str) -> PathBuf {
    root.join(sha256_hex(scope.as_bytes()))
        .join(format!("{}.json", sha256_hex(format!("{scope}\0{operation_id}").as_bytes())))
}

/// npm `readJournal`.
///
/// # Errors
/// `operation_unconfirmed` for an unsafe or unverifiable entry.
pub(crate) fn read_journal(path: &Path) -> HostResult<Option<Value>> {
    let stats = match std::fs::symlink_metadata(path) {
        Ok(stats) => stats,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(unconfirmed("Mutation journal entry cannot be verified")),
    };
    if !stats.is_file() || stats.nlink() != 1 || stats.len() > 3 * MAX_FILE_BYTES {
        return Err(unconfirmed("Mutation journal entry is unsafe or invalid"));
    }
    let text = std::fs::read_to_string(path)
        .map_err(|_| unconfirmed("Mutation journal entry cannot be verified"))?;
    let parsed: Value = serde_json::from_str(&text)
        .map_err(|_| unconfirmed("Mutation journal entry cannot be verified"))?;
    if parsed["schema_version"] != 1
        || !matches!(parsed["state"].as_str(), Some("prepared" | "applied"))
        || !parsed["result"].is_object()
    {
        return Err(unconfirmed("Mutation journal entry cannot be verified"));
    }
    Ok(Some(parsed))
}

/// npm `writeJournal`: exclusive temp file, fsync, rename, `0600`, dir fsync.
///
/// # Errors
/// `operation_failed` on IO failure.
pub(crate) fn write_journal(path: &Path, record: &Value) -> HostResult<()> {
    super::store::write_private_file(path, record.to_string().as_bytes())?;
    if let Some(parent) = path.parent() {
        let directory = std::fs::File::open(parent).map_err(|e| HostError::failed(e.to_string()))?;
        directory
            .sync_all()
            .map_err(|e| HostError::failed(e.to_string()))?;
    }
    Ok(())
}

/// A held `proper-lockfile` style directory lock; released on drop.
pub(crate) struct PathLock {
    path: PathBuf,
}

impl Drop for PathLock {
    fn drop(&mut self) {
        // Release is best effort: a leftover directory turns stale after 30 s.
        let _ = std::fs::remove_dir(&self.path);
    }
}

/// npm `acquirePathLock`.
///
/// # Errors
/// `operation_unconfirmed` when the lock stays busy.
pub(crate) async fn path_lock(parent_identity: &str, name: &str) -> HostResult<PathLock> {
    let root = private_state_directory(&tmp_dir("openmates-remote-file-locks"))?;
    let target = root.join(sha256_hex(format!("{parent_identity}\0{name}").as_bytes()));
    private_state_directory(&target)?;
    let lock = PathBuf::from(format!("{}.lock", target.display()));
    for attempt in 0..=PATH_LOCK_RETRIES {
        match std::fs::create_dir(&lock) {
            Ok(()) => return Ok(PathLock { path: lock }),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                let stale = std::fs::metadata(&lock)
                    .and_then(|m| m.modified())
                    .ok()
                    .and_then(|m| SystemTime::now().duration_since(m).ok())
                    .is_some_and(|age| age > PATH_LOCK_STALE);
                if stale {
                    let _ = std::fs::remove_dir(&lock);
                    continue;
                }
                if attempt < PATH_LOCK_RETRIES {
                    tokio::time::sleep(Duration::from_millis(5 + u64::from(attempt % 6))).await;
                }
            }
            Err(e) => {
                return Err(unconfirmed(format!(
                    "Could not serialize Project file mutation: {e}"
                )));
            }
        }
    }
    Err(unconfirmed(
        "Could not serialize Project file mutation: lock is busy",
    ))
}

/// A held shared source lock; the descriptor releases it on drop.
pub(crate) struct SourceLock {
    _file: std::fs::File,
}

/// npm `acquireRemoteProjectFileEditLock`: shared `flock`, waiting up to 30 s
/// while a source-mutating command holds it exclusively.
///
/// # Errors
/// `operation_failed` for an unsafe lock file or a timeout.
pub(crate) async fn source_lock() -> HostResult<SourceLock> {
    acquire_source_lock(rustix::fs::FlockOperation::NonBlockingLockShared).await
}

/// The exclusive side of [`source_lock`], held by a command that runs in the
/// live source root (npm `wrapRemoteProjectSourceCommand`): it waits for file
/// commits to finish and keeps new ones out until the command ends.
///
/// # Errors
/// `operation_failed` for an unsafe lock file or a timeout.
pub(crate) async fn source_lock_exclusive() -> HostResult<SourceLock> {
    acquire_source_lock(rustix::fs::FlockOperation::NonBlockingLockExclusive).await
}

async fn acquire_source_lock(operation: rustix::fs::FlockOperation) -> HostResult<SourceLock> {
    use rustix::fs::{Mode, OFlags};
    let directory = private_state_directory(&tmp_dir("openmates-project-source-locks"))?;
    let path = directory.join("source-writes.lock");
    let fd = rustix::fs::open(
        &path,
        OFlags::CREATE | OFlags::RDWR | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::from_raw_mode(0o600),
    )
    .map_err(|e| HostError::failed(format!("Project source lock: {e}")))?;
    let file = std::fs::File::from(fd);
    let stats = std::fs::symlink_metadata(&path).map_err(|e| HostError::failed(e.to_string()))?;
    if !stats.is_file() || stats.uid() != uid() || stats.mode() & 0o077 != 0 {
        return Err(HostError::failed("Project source lock file is unsafe"));
    }
    let deadline = tokio::time::Instant::now() + SOURCE_LOCK_TIMEOUT;
    loop {
        match rustix::fs::flock(&file, operation) {
            Ok(()) => return Ok(SourceLock { _file: file }),
            Err(rustix::io::Errno::WOULDBLOCK) if tokio::time::Instant::now() < deadline => {
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            Err(e) => return Err(HostError::failed(format!("Project source lock: {e}"))),
        }
    }
}
