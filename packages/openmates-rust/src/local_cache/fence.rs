//! Generation/revocation fence (`revocation.json`) and fenced single-record
//! publication.
//!
//! Part of the shared client core (`local_cache`); moved unchanged from the
//! native TUI `storage.rs` and byte-compatible with existing state
//! directories. Spec: `client-core.cache`.
//! Invariant: every cache write re-checks the durable epoch while holding
//! `revocation.lock`, so a record can never be published after logout has
//! revoked the epoch it was prepared for. Logout bumps the epoch and marks
//! the fence revoked before any credential or cache cleanup starts.
use super::{ByteStore, record::decode_cache_record_value};
use crate::error::{Error, Result};
use serde::{Deserialize, Serialize};

/// File that holds the fence; independent of the session file so logout can
/// revoke while a credential operation is still blocked.
pub const REVOCATION_FILE: &str = "revocation.json";
/// Lock scope that serializes fence changes and fenced cache writes.
pub const REVOCATION_LOCK: &str = "revocation.lock";
/// Largest fence file accepted on read.
const MAX_FENCE_BYTES: usize = 4096;

/// Where the native shell keeps its credential secret. Recorded in the fence
/// cleanup intent so an interrupted logout still removes the right secret.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StorageMode {
    /// Operating-system keyring.
    OsKeyring,
    /// Owner-only local key file.
    RestrictedLocalFile,
    /// Passphrase-encrypted vault.
    EncryptedVault,
}

/// Credential cleanup that must still run after a revocation.
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PendingCleanup {
    /// Secret location to remove.
    pub mode: StorageMode,
    /// Owner hash whose cache files are deleted.
    pub owner: String,
}

/// Parsed `revocation.json`. Contexts are hashes, never credentials; a fresh
/// admission replaces the epoch.
#[derive(Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RevocationFence {
    /// Format version; `1` once written (a missing file reads as default).
    pub version: u8,
    /// UUID of the current generation.
    pub epoch: String,
    /// True after logout announced revocation.
    pub revoked: bool,
    /// Context hash of the last admitted session.
    pub context: Option<String>,
    /// Context hash admitted by a fresh login, until its session is saved.
    pub admitted: Option<String>,
    /// Pending credential cleanup, if any.
    pub cleanup: Option<PendingCleanup>,
    /// Up to two previously revoked contexts.
    pub retired_contexts: Vec<String>,
}

impl RevocationFence {
    /// Read the fence from `store`; a missing file is the default (epoch "").
    ///
    /// # Errors
    /// `Protocol` for an oversized or malformed fence, wrong version, a
    /// non-UUID epoch or more than two retired contexts; store errors.
    pub fn load<S: ByteStore>(store: &S) -> Result<Self> {
        let Some(bytes) = store.get(REVOCATION_FILE)? else {
            return Ok(Self::default());
        };
        if bytes.len() > MAX_FENCE_BYTES {
            return Err(Error::Protocol);
        }
        let fence: Self = serde_json::from_slice(&bytes)?;
        if fence.version != 1
            || uuid::Uuid::parse_str(&fence.epoch).is_err()
            || fence.retired_contexts.len() > 2
        {
            return Err(Error::Protocol);
        }
        Ok(fence)
    }

    /// The epoch writers must bind to.
    ///
    /// # Errors
    /// `Authentication` when the fence is revoked.
    pub fn active_epoch(&self) -> Result<String> {
        if self.revoked {
            return Err(Error::Authentication);
        }
        Ok(self.epoch.clone())
    }

    /// Check that the fence is still at `expected` and not revoked.
    ///
    /// # Errors
    /// `Cancelled` when revoked or the epoch changed.
    pub fn require_epoch(&self, expected: &str) -> Result<()> {
        if self.revoked || self.epoch != expected {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}

/// Publish the already sealed record bytes `encoded` as `name`, but only while
/// the durable epoch is still `epoch`. `put` performs the actual atomic write
/// so shells can wrap it (instrumentation, fault injection); it runs under
/// `revocation.lock`.
///
/// # Errors
/// `Cancelled` when the epoch moved or was revoked; whatever `put` or the
/// store returns.
pub fn publish_record<S: ByteStore>(
    store: &S,
    name: &str,
    epoch: &str,
    encoded: &[u8],
    put: impl FnOnce(&str, &[u8]) -> Result<()>,
) -> Result<()> {
    let _fence = store.lock(REVOCATION_LOCK)?;
    RevocationFence::load(store)?.require_epoch(epoch)?;
    put(name, encoded)
}

/// Read and open one cache record: `None` when `name` does not exist.
///
/// # Errors
/// As [`decode_cache_record`] plus store errors and JSON errors for a
/// plaintext that is not JSON.
pub fn read_record<S: ByteStore>(
    store: &S,
    name: &str,
    key: &[u8; 32],
    aad: &[u8],
) -> Result<Option<serde_json::Value>> {
    store
        .get(name)?
        .map(|bytes| decode_cache_record_value(&bytes, key, aad))
        .transpose()
}
