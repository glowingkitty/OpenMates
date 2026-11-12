//! Local filesystem host for Project remote access: the Rust CLI serves an
//! approved folder to encrypted requesters (shared core, native only).
//!
//! Mirrors the npm host in `frontend/packages/openmates-cli/src/remoteAccess.ts`,
//! `projectPathPolicy.ts`, `projectSourceRootPolicy.ts` and `remoteFileWrites.ts`:
//! same path policy (gitignore chain, built-in and user private paths, sticky
//! private state), same limits, same result shapes and error codes. The wire
//! session (register, heartbeat, takeover, completion) lives in
//! `crate::client::source_host`; this module owns the filesystem operations,
//! per-request dispatch and the reconnecting run loop.
//! spec: specifications/features/projects (remote sources).

mod attach;
mod command_process;
mod command_sandbox;
mod command_scope;
pub(crate) mod commands;
mod dispatch;
mod fs_safe;
pub(crate) mod git_ops;
pub(crate) mod ignore_rules;
mod patch;
pub(crate) mod path_policy;
mod reads;
mod runner;
mod search;
mod search_rg;
mod store;
mod worktrees;
mod worktrees_git;
mod writes;
mod writes_journal;

#[cfg(test)]
mod command_sandbox_tests;
#[cfg(test)]
mod commands_tests;
#[cfg(test)]
mod git_ops_tests;
#[cfg(test)]
mod host_capability_tests;
#[cfg(test)]
mod ignore_rules_tests;
#[cfg(test)]
mod patch_tests;
#[cfg(test)]
mod path_policy_tests;
#[cfg(test)]
mod reads_tests;
#[cfg(test)]
mod search_tests;
#[cfg(test)]
mod store_tests;
#[cfg(test)]
mod worktrees_tests;
#[cfg(test)]
mod writes_tests;

pub use attach::{
    AttachContext, AttachError, AttachResult, HostingCandidates, MAX_APPROVED_ROOTS, ProjectChoice,
    StoredAttachment, attach_root, hosting_candidates, prepare_source, resolve_roots,
    selectable_projects, stored_attachments,
};
pub use dispatch::FilesystemSourceAdapter;
pub use runner::{CredentialSync, CredentialSyncFuture, SourceHostEvent, SourceHostRun, SourceHostRunSource, run_source_host};
pub use store::{
    StoredRemoteSource, load_remote_sources, npm_state_dir, remote_cache_path,
    remote_source_type, save_remote_sources, upsert_remote_source,
};

use std::cmp::Ordering;
use std::fmt;

/// Capabilities the Rust host always advertises for each source, in npm order.
/// `run_command` is added only on hosts with a command sandbox tier; use
/// [`host_capability_names`] for the full list of this machine.
pub const HOST_CAPABILITIES: [&str; 4] = ["read", "search", "import", "write_request"];

/// The capability names this host advertises: [`HOST_CAPABILITIES`] plus
/// `run_command` when `sandbox_available` (a confinement tier was detected).
/// Without a sandbox the operation still answers `confinement_unavailable`
/// but is never advertised.
pub(crate) fn host_capability_names(sandbox_available: bool) -> Vec<&'static str> {
    let mut names = HOST_CAPABILITIES.to_vec();
    if sandbox_available {
        names.push("run_command");
    }
    names
}

/// A host operation failure carrying the exact npm wire error code
/// (`remoteAccessOperationErrorCode`). The message is local diagnostics only and
/// never leaves the host: requesters receive `{"ok":false,"error":code}`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HostError {
    /// Stable npm error code, for example `invalid_path` or `protected_path`.
    pub code: &'static str,
    /// Local, non-secret diagnostic text.
    pub message: String,
}

impl HostError {
    /// Build an error with an explicit npm code.
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }
    pub(crate) fn invalid_path(message: impl Into<String>) -> Self {
        Self::new("invalid_path", message)
    }
    pub(crate) fn protected(message: impl Into<String>) -> Self {
        Self::new("protected_path", message)
    }
    pub(crate) fn unsupported(message: impl Into<String>) -> Self {
        Self::new("unsupported_file", message)
    }
    pub(crate) fn failed(message: impl Into<String>) -> Self {
        Self::new("operation_failed", message)
    }
    /// npm maps a Node `ENOENT` to `invalid_path`; other IO errors fail generically.
    pub(crate) fn io(context: &str, error: &std::io::Error) -> Self {
        if error.kind() == std::io::ErrorKind::NotFound {
            Self::invalid_path(format!("{context}: ENOENT"))
        } else {
            Self::failed(format!("{context}: {error}"))
        }
    }
}

impl fmt::Display for HostError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for HostError {}

/// Result alias for host operations.
pub type HostResult<T> = std::result::Result<T, HostError>;

/// `a.localeCompare(b) || (a < b ? -1 : a > b ? 1 : 0)`: the npm listing and
/// search order. ICU root collation (en-US, like Node's default) with a code
/// unit tie-break so the order is total and cursors stay stable.
pub(crate) struct NameOrder {
    collator: icu_collator::CollatorBorrowed<'static>,
}

impl NameOrder {
    pub(crate) fn new() -> HostResult<Self> {
        let locale: icu_locale_core::Locale = "en-US"
            .parse()
            .map_err(|_| HostError::failed("Collation locale is unavailable."))?;
        let collator = icu_collator::Collator::try_new(
            locale.into(),
            icu_collator::options::CollatorOptions::default(),
        )
        .map_err(|_| HostError::failed("Collation data is unavailable."))?;
        Ok(Self { collator })
    }
    pub(crate) fn compare(&self, a: &str, b: &str) -> Ordering {
        self.collator
            .compare(a, b)
            .then_with(|| a.encode_utf16().cmp(b.encode_utf16()))
    }
}

/// Lowercase hex SHA-256 of bytes.
pub(crate) fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let digest = Sha256::digest(bytes);
    let mut out = String::with_capacity(64);
    for byte in digest {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

/// JS `String.prototype.slice(0, n)` on UTF-16 units, never splitting a
/// surrogate pair (the dangling high surrogate is dropped like `safeTextPrefix`).
pub(crate) fn utf16_prefix(value: &str, units: usize) -> String {
    let mut out = String::new();
    let mut used = 0;
    for c in value.chars() {
        let width = c.len_utf16();
        if used + width > units {
            break;
        }
        used += width;
        out.push(c);
    }
    out
}
