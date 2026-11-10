//! `create_file` / `update_file` for the filesystem host: proposal validation,
//! the keyed proposal digest and the crash-recoverable pinned-parent write.
//!
//! Mirrors `validateProjectFileMutation` / `projectFileMutationDigest`
//! (`ui/src/utils/projectFileMutationProtocol.ts`) and
//! `executeRemoteFileMutation` (`openmates-cli/src/remoteFileWrites.ts`):
//! - the host recomputes HMAC-SHA256(projectKey, JSON tuple) and refuses a
//!   proposal whose digest differs from the server-held approval;
//! - the backend re-authorizes before the journal is consulted and again
//!   under the source and path locks, with an unchanged scope and operation;
//! - the parent directory is pinned by an `openat` chain with `O_NOFOLLOW`,
//!   creates use temp file + `link` (never overwrite), updates use temp file +
//!   `rename` after a near-write re-read, and the journal makes replays
//!   idempotent (`replayed` / `already_applied`).

use super::fs_safe::canonical_root;
use super::patch::{apply, create_diff};
use super::path_policy::{PathPolicy, PolicyOptions};
use super::writes_journal::{
    journal_path, journal_root, path_lock, private_state_directory, read_journal, source_lock,
    write_journal,
};
use super::{HostError, HostResult, sha256_hex};
use crate::web_projects::search_request::is_protected_read_path;
use hmac::{Hmac, Mac};
use rustix::fs::{AtFlags, Mode, OFlags};
use serde_json::{Value, json};
use sha2::Sha256;
use std::io::{Read, Write};
use std::os::fd::OwnedFd;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};

const MAX_FILE_BYTES: usize = 200 * 1024;

/// A validated proposal (`ProjectFileMutation`).
#[derive(Clone, Debug)]
pub(crate) struct Mutation {
    pub(crate) create: bool,
    pub(crate) operation_id: String,
    pub(crate) path: String,
    pub(crate) expected_base: Option<String>,
    pub(crate) content: Option<String>,
    pub(crate) patch: Option<String>,
    raw: Value,
}

impl Mutation {
    /// The wire operation name.
    pub(crate) fn operation(&self) -> &'static str {
        if self.create { "create_file" } else { "update_file" }
    }
}

fn operation_id_valid(value: &str) -> bool {
    (1..=128).contains(&value.len())
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b':' | b'-'))
}

/// npm `validateProjectFileMutation`. Its plain errors reach the requester
/// as `operation_failed`.
///
/// # Errors
/// `operation_failed` (`invalid_file_mutation`, `file_mutation_too_large`).
pub(crate) fn validate(value: &Value) -> HostResult<Mutation> {
    let fail = || HostError::failed("invalid_file_mutation");
    let object = value.as_object().ok_or_else(fail)?;
    const ALLOWED: [&str; 6] = ["operation", "operation_id", "path", "expected_base", "content", "patch"];
    if object.keys().any(|key| !ALLOWED.contains(&key.as_str())) {
        return Err(fail());
    }
    let create = match object.get("operation").and_then(Value::as_str) {
        Some("create_file") => true,
        Some("update_file") => false,
        _ => return Err(fail()),
    };
    let operation_id = object
        .get("operation_id")
        .and_then(Value::as_str)
        .filter(|v| operation_id_valid(v))
        .ok_or_else(fail)?;
    let path = object
        .get("path")
        .and_then(Value::as_str)
        .filter(|p| !p.is_empty() && p.encode_utf16().count() <= 4096 && !p.contains('\0'))
        .ok_or_else(fail)?;
    let content = object.get("content");
    let patch = object.get("patch");
    let expected = object.get("expected_base");
    if create {
        if expected != Some(&Value::Null) || !content.is_some_and(Value::is_string) || patch.is_some() {
            return Err(fail());
        }
    } else {
        let base_ok = expected
            .and_then(Value::as_str)
            .is_some_and(|b| b.len() == 64 && b.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)));
        if !base_ok || !patch.and_then(Value::as_str).is_some_and(|p| !p.is_empty()) || content.is_some() {
            return Err(fail());
        }
    }
    let body = content.or(patch).and_then(Value::as_str).unwrap_or_default();
    if body.len() > MAX_FILE_BYTES {
        return Err(HostError::failed("file_mutation_too_large"));
    }
    Ok(Mutation {
        create,
        operation_id: operation_id.to_owned(),
        path: path.to_owned(),
        expected_base: expected.and_then(Value::as_str).map(str::to_owned),
        content: content.and_then(Value::as_str).map(str::to_owned),
        patch: patch.and_then(Value::as_str).map(str::to_owned),
        raw: value.clone(),
    })
}

/// npm `projectFileMutationDigest`: lowercase hex HMAC-SHA256 over
/// `JSON.stringify(["openmates-project-file-proposal-v1", projectId, chatId,
/// operation, operation_id, path, expected_base, content ?? null, patch ?? null])`.
///
/// # Errors
/// `operation_failed` for an empty identity.
pub(crate) fn digest(key: &[u8; 32], project_id: &str, chat_id: &str, m: &Mutation) -> HostResult<String> {
    if project_id.is_empty() || chat_id.is_empty() {
        return Err(HostError::failed("invalid_file_mutation_identity"));
    }
    let message = json!([
        "openmates-project-file-proposal-v1",
        project_id,
        chat_id,
        m.operation(),
        m.operation_id,
        m.path,
        m.expected_base,
        m.content,
        m.patch,
    ])
    .to_string();
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key)
        .map_err(|_| HostError::failed("invalid_file_mutation_identity"))?;
    mac.update(message.as_bytes());
    let bytes = mac.finalize().into_bytes();
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

/// npm `validateRelativePath` (mutation flavour).
fn strict_path(value: &str) -> HostResult<()> {
    if value.is_empty()
        || value.encode_utf16().count() > 4096
        || value.starts_with('/')
        || value.contains('\\')
        || value.chars().any(|c| (c as u32) < 32 || c as u32 == 127)
        || value.split('/').any(|part| part.is_empty() || part == "." || part == "..")
    {
        return Err(HostError::invalid_path(
            "Project file path must be a strict root-relative POSIX path",
        ));
    }
    Ok(())
}

/// npm `enforcePathPolicy`.
fn enforce_policy(root: &Path, state_dir: &Path, path: &str) -> HostResult<()> {
    if path.split('/').any(|p| p == ".git")
        || path == ".openmates/permissions.yml"
        || is_protected_read_path(path)
    {
        return Err(HostError::protected("Project file path is protected"));
    }
    let options = PolicyOptions {
        state_dir,
        trusted_private: &[],
        targets: &[path],
        discover_nested: false,
    };
    PathPolicy::load(root, &options)
        .and_then(|policy| policy.assert_writable(path))
        .map_err(|error| match error.code {
            "protected_path" | "ignored_path_requires_approval" | "invalid_path_policy" => {
                HostError::protected("Project file path is ignored or private")
            }
            _ => error,
        })
}

struct Parent {
    fd: OwnedFd,
    identity: String,
    name: String,
}

/// npm `openPinnedParent` via an `openat` chain (no `/proc` dependency).
fn pin_parent(root: &Path, path: &str) -> HostResult<Parent> {
    let mut parts: Vec<&str> = path.split('/').collect();
    let name = parts.pop().unwrap_or_default().to_owned();
    let dir_flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
    let mut fd = rustix::fs::open(root, dir_flags, Mode::empty())
        .map_err(|_| HostError::invalid_path("Could not pin the source root"))?;
    for part in parts {
        fd = rustix::fs::openat(&fd, part, dir_flags, Mode::empty()).map_err(|errno| {
            if errno == rustix::io::Errno::LOOP || errno == rustix::io::Errno::NOTDIR {
                HostError::invalid_path("Project file path contains a symbolic link")
            } else {
                HostError::invalid_path("Project file parent does not exist or is unsupported")
            }
        })?;
    }
    let stats = rustix::fs::fstat(&fd)
        .map_err(|_| HostError::invalid_path("Project file parent does not exist or is unsupported"))?;
    Ok(Parent {
        identity: format!("{}:{}:{name}", stats.st_dev, stats.st_ino),
        fd,
        name,
    })
}

struct Current {
    content: String,
    hash: String,
    mode: u32,
    dev: u64,
    ino: u64,
}

/// npm `readPinnedFile`.
fn read_pinned(parent: &Parent) -> HostResult<Option<Current>> {
    let fd = match rustix::fs::openat(
        &parent.fd,
        parent.name.as_str(),
        OFlags::RDONLY | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::empty(),
    ) {
        Ok(fd) => fd,
        Err(rustix::io::Errno::NOENT) => return Ok(None),
        Err(rustix::io::Errno::LOOP) => {
            return Err(HostError::invalid_path("Project file target is a symbolic link"));
        }
        Err(_) => {
            return Err(HostError::invalid_path(
                "Project file target cannot be opened safely",
            ));
        }
    };
    let mut file = std::fs::File::from(fd);
    let stats = file.metadata().map_err(|e| HostError::io("Project file", &e))?;
    if !stats.is_file() || stats.nlink() != 1 {
        return Err(HostError::unsupported(
            "Project file must be a regular file with one link",
        ));
    }
    if stats.len() > MAX_FILE_BYTES as u64 {
        return Err(HostError::new("size_limit_exceeded", "Project file exceeds 204800 bytes"));
    }
    let mut bytes = Vec::with_capacity(stats.len() as usize);
    (&mut file)
        .take(stats.len())
        .read_to_end(&mut bytes)
        .map_err(|e| HostError::io("Project file", &e))?;
    let changed = || HostError::new("file_changed", "Project file changed while it was read");
    if bytes.len() as u64 != stats.len() {
        return Err(changed());
    }
    if bytes.contains(&0) {
        return Err(HostError::unsupported("Binary Project files are unsupported"));
    }
    let content = String::from_utf8(bytes.clone())
        .map_err(|_| HostError::unsupported("Project file is not valid UTF-8 text"))?;
    let after = file.metadata().map_err(|e| HostError::io("Project file", &e))?;
    if after.len() != stats.len()
        || super::fs_safe::mtime_ms(&after) != super::fs_safe::mtime_ms(&stats)
        || after.ino() != stats.ino()
        || after.dev() != stats.dev()
    {
        return Err(changed());
    }
    Ok(Some(Current {
        content,
        hash: sha256_hex(&bytes),
        mode: stats.mode() & 0o777,
        dev: stats.dev(),
        ino: stats.ino(),
    }))
}

/// npm `proposedMutation`: `(after_content, applied_diff)`.
fn propose(m: &Mutation, current: Option<&Current>) -> HostResult<(String, String)> {
    if m.create {
        if current.is_some() {
            return Err(HostError::new("target_exists", "Create target already exists"));
        }
        let content = m.content.clone().unwrap_or_default();
        let diff = create_diff(&m.path, &content);
        return Ok((content, diff));
    }
    let current = current.ok_or_else(|| HostError::new("file_changed", "Update target no longer exists"))?;
    if Some(&current.hash) != m.expected_base.as_ref() {
        return Err(HostError::new(
            "file_changed",
            "Project file no longer matches expected_base",
        ));
    }
    let patch = m.patch.clone().unwrap_or_default();
    let content = apply(&current.content, &patch, &m.path)
        .map_err(|e| HostError::new("invalid_patch", e.0))?;
    if content.len() > MAX_FILE_BYTES {
        return Err(HostError::new("size_limit_exceeded", "Updated file exceeds 204800 bytes"));
    }
    Ok((content, patch))
}

fn temp_name() -> String {
    format!(
        ".openmates-write-{}-{}.tmp",
        std::process::id(),
        &uuid::Uuid::new_v4().simple().to_string()[..20]
    )
}

/// `chmod` is applied only for replacements (keep the original mode); creates
/// keep the kernel's umask-filtered `0o666` like Node.
fn write_temp(parent: &Parent, name: &str, content: &str, mode: u32, chmod: bool) -> HostResult<()> {
    let fd = rustix::fs::openat(
        &parent.fd,
        name,
        OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::from_raw_mode(mode),
    )
    .map_err(|e| HostError::failed(format!("Temporary write failed: {e}")))?;
    let mut file = std::fs::File::from(fd);
    file.write_all(content.as_bytes())
        .and_then(|()| {
            if chmod {
                file.set_permissions(std::fs::Permissions::from_mode(mode))
            } else {
                Ok(())
            }
        })
        .and_then(|()| file.sync_all())
        .map_err(|e| HostError::failed(format!("Temporary write failed: {e}")))
}

fn remove_temp(parent: &Parent, name: &str) {
    // Best-effort cleanup of our own exclusive temp file after a failure.
    let _ = rustix::fs::unlinkat(&parent.fd, name, AtFlags::empty());
}

/// npm `createPinnedFile`: `link` never replaces an existing target.
fn create_pinned(parent: &Parent, content: &str) -> HostResult<()> {
    let temp = temp_name();
    let result = write_temp(parent, &temp, content, 0o666, false).and_then(|()| {
        rustix::fs::linkat(&parent.fd, temp.as_str(), &parent.fd, parent.name.as_str(), AtFlags::empty())
            .map_err(|errno| {
                if errno == rustix::io::Errno::EXIST {
                    HostError::new("target_exists", "Create target appeared during the final write")
                } else {
                    HostError::failed(format!("Create failed: {errno}"))
                }
            })
    });
    remove_temp(parent, &temp);
    result?;
    rustix::fs::fsync(&parent.fd).map_err(|e| HostError::failed(format!("fsync failed: {e}")))
}

/// npm `replacePinnedFile`.
fn replace_pinned(parent: &Parent, expected: &Current, content: &str) -> HostResult<()> {
    let temp = temp_name();
    let result = write_temp(parent, &temp, content, expected.mode, true).and_then(|()| {
        let near = read_pinned(parent)?;
        if !near.is_some_and(|n| n.hash == expected.hash && n.dev == expected.dev && n.ino == expected.ino) {
            return Err(HostError::new(
                "file_changed",
                "Project file changed at the final write boundary",
            ));
        }
        rustix::fs::renameat(&parent.fd, temp.as_str(), &parent.fd, parent.name.as_str())
            .map_err(|e| HostError::failed(format!("Replace failed: {e}")))
    });
    if result.is_err() {
        remove_temp(parent, &temp);
    }
    result?;
    rustix::fs::fsync(&parent.fd).map_err(|e| HostError::failed(format!("fsync failed: {e}")))
}

fn replay(record: &Value) -> Value {
    let mut result = record["result"].clone();
    result["replayed"] = json!(true);
    result["already_applied"] = json!(true);
    result
}

fn assert_identity(journal: &Value, m: &Mutation, scope: &str, payload: &str) -> HostResult<()> {
    if journal["operation_id"] != m.operation_id.as_str()
        || journal["scope_digest"] != scope
        || journal["payload_digest"] != payload
    {
        return Err(HostError::new(
            "operation_conflict",
            "Operation ID was already used for a different mutation",
        ));
    }
    Ok(())
}

/// Inputs of one mutation.
pub(crate) struct WriteRequest<'a> {
    pub(crate) root: &'a Path,
    pub(crate) state_dir: &'a Path,
    pub(crate) mutation: &'a Mutation,
    /// Trusted origin scope returned by the backend authorization.
    pub(crate) scope: &'a str,
    /// Override for tests; defaults to the shared tmp journal.
    pub(crate) journal_root: Option<PathBuf>,
}

/// A fresh backend re-authorization; it must fail when the authorization
/// scope or operation changed since the first check.
pub(crate) trait WriteAuthority {
    /// Re-authorize this write now.
    async fn authorize(&mut self) -> HostResult<()>;
}

/// npm `executeRemoteFileMutation`.
///
/// # Errors
/// The npm `RemoteFileMutationErrorCode`s plus `protected_path` /
/// `invalid_path` from the policy and authorization failures from `authorize`.
pub(crate) async fn execute<A: WriteAuthority>(
    request: WriteRequest<'_>,
    authority: &mut A,
) -> HostResult<Value> {
    let m = request.mutation;
    strict_path(&m.path)?;
    if request.scope.is_empty() || request.scope.len() > 2048 {
        return Err(HostError::invalid_path("Operation scope is missing or invalid"));
    }
    let root = canonical_root(request.root, request.state_dir)
        .map_err(|_| HostError::invalid_path("Source root is unavailable or protected"))?;
    enforce_policy(&root, request.state_dir, &m.path)?;
    let journal_root = private_state_directory(&request.journal_root.clone().unwrap_or_else(journal_root))?;
    let real_journal = std::fs::canonicalize(&journal_root).map_err(|e| HostError::io("Journal", &e))?;
    if real_journal.starts_with(&root) {
        return Err(HostError::invalid_path(
            "Mutation journal must be outside the source root",
        ));
    }
    let scope_digest = sha256_hex(request.scope.as_bytes());
    let stable = crate::remote_command::stable_json(&m.raw).map_err(|e| HostError::failed(e.message))?;
    let payload_digest = sha256_hex(stable.as_bytes());
    let journal = journal_path(&journal_root, request.scope, &m.operation_id);
    if let Some(parent) = journal.parent() {
        private_state_directory(parent)?;
    }
    // Replaying a prior receipt still requires current Project authority.
    authority.authorize().await?;
    if let Some(existing) = read_journal(&journal)? {
        assert_identity(&existing, m, &scope_digest, &payload_digest)?;
        if existing["state"] == "applied" {
            return Ok(replay(&existing));
        }
    }
    let (preview_identity, preview_current, preview) = {
        let parent = pin_parent(&root, &m.path)?;
        let current = read_pinned(&parent)?;
        let proposed = propose(m, current.as_ref())?;
        (parent.identity, current, proposed)
    };
    let _source_lock = source_lock().await?;
    let name = m.path.rsplit('/').next().unwrap_or_default();
    let _path_lock = path_lock(&preview_identity, name).await?;
    // Revalidate under the locks: settings may have changed while another
    // writer or a source-mutating command held the boundary.
    authority.authorize().await?;
    let prior = read_journal(&journal)?;
    if let Some(prior) = &prior {
        assert_identity(prior, m, &scope_digest, &payload_digest)?;
        if prior["state"] == "applied" {
            return Ok(replay(prior));
        }
    }
    let parent = pin_parent(&root, &m.path)?;
    if parent.identity != preview_identity {
        return Err(HostError::new(
            "file_changed",
            "Project file parent changed during authorization",
        ));
    }
    let current = read_pinned(&parent)?;
    if let Some(prior) = prior.filter(|p| p["state"] == "prepared") {
        if current.as_ref().is_some_and(|c| prior["after_hash"] == c.hash.as_str()) {
            let mut recovered = prior.clone();
            recovered["state"] = json!("applied");
            write_journal(&journal, &recovered)?;
            return Ok(replay(&recovered));
        }
        return Err(HostError::new(
            "operation_unconfirmed",
            "A previous attempt reached the mutation boundary but its outcome cannot be confirmed safely",
        ));
    }
    let still_current = if m.create {
        current.is_none()
    } else {
        matches!((&preview_current, &current), (Some(b), Some(c)) if b.hash == c.hash && b.dev == c.dev && b.ino == c.ino)
    };
    if !still_current {
        return Err(if m.create {
            HostError::new("target_exists", "Create target appeared during authorization")
        } else {
            HostError::new("file_changed", "Project file changed during authorization")
        });
    }
    let proposed = propose(m, current.as_ref())?;
    if proposed != preview {
        return Err(HostError::new("file_changed", "Project file changed during authorization"));
    }
    let (after, diff) = proposed;
    let before = current.as_ref().map(|c| c.hash.clone());
    let result = json!({
        "operation_id": m.operation_id,
        "path": m.path,
        "operation": m.operation(),
        "before_hash": before,
        "after_hash": sha256_hex(after.as_bytes()),
        "content": after,
        "applied_diff": diff,
    });
    let mut record = json!({
        "schema_version": 1,
        "operation_id": m.operation_id,
        "scope_digest": scope_digest,
        "payload_digest": payload_digest,
        "state": "prepared",
        "before_hash": before,
        "after_hash": result["after_hash"],
        "preimage": current.as_ref().map(|c| c.content.clone()),
        "result": result,
    });
    write_journal(&journal, &record)?;
    match &current {
        None => create_pinned(&parent, &after)?,
        Some(current) => replace_pinned(&parent, current, &after)?,
    }
    record["state"] = json!("applied");
    write_journal(&journal, &record)?;
    let mut out = record["result"].clone();
    out["replayed"] = json!(false);
    out["already_applied"] = json!(false);
    Ok(out)
}
