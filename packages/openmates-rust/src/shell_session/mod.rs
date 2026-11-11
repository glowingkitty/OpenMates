//! Shell session runtime owned by the shared client core: restore (durable
//! credentials plus the protected cache index), cache-first Chat open, fresh
//! session admission, persistence with durable receipts, logout, and the
//! fresh-session fence after a login (`begin`) and the hand-over of a core
//! password or pair login to an acknowledging shell (`login`).
//!
//! Moved from the TUI `session_runtime.rs` (lane L4 of
//! `docs/plans/apple-client-core-migration/a2-design.md`); shells keep only
//! their credential backend behind [`CredentialPersistence`]. Native targets
//! only (needs the blocking queue of `local_cache::CacheStore`). Spec:
//! `client-core.cache` and the credential rules in `client-core`.
mod acknowledged;
mod admission;
mod begin;
#[cfg(all(test, unix))]
mod begin_tests;
mod credentials;
mod login;
mod receipt;
mod session;
#[cfg(all(test, unix))]
mod session_tests;

pub use acknowledged::{AcknowledgedCredentials, CredentialVault, session_cache_context};
pub use admission::FreshSessionAdmission;
pub use begin::{SessionBeginStore, StoredCredential, begin_session_epoch};
pub use credentials::{
    CREDENTIAL_ACKNOWLEDGEMENT_TIMEOUT, CredentialPersistence, CredentialSave,
    await_credential_acknowledgement,
};
pub use receipt::DurableCandidate;
pub use session::{CacheLoad, ShellSession};

use crate::{
    client::Client,
    error::{Error, Result},
    local_cache::OrderedBlocking,
    session::Session,
};
use sha2::{Digest, Sha256};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

/// Logical cache key of the sync cache for the session's active scope
/// (`sync-personal` or `sync-<team id>`). Byte-compatible with existing
/// native installs: it enters the cache file name and the record AAD.
pub fn cache_key(session: &Session) -> String {
    format!(
        "sync-{}",
        session.active_team_id.as_deref().unwrap_or("personal")
    )
}

/// SHA-256 of the serialized session; equal digests mean the same credentials.
/// The serialization is zeroized after hashing.
fn session_digest(session: &Session) -> Result<[u8; 32]> {
    let encoded = Zeroizing::new(serde_json::to_vec(session)?);
    Ok(Sha256::digest(encoded.as_slice()).into())
}

fn credential_digest(client: &Client) -> Result<[u8; 32]> {
    let session = client.session().ok_or(Error::Authentication)?;
    session_digest(session)
}

/// The operation may continue: not cancelled, the queue generation it started
/// at is still current, the client holds a session and a pairing has not
/// lapsed.
fn current(
    client: &Client,
    ops: &OrderedBlocking,
    generation: u64,
    cancel: &CancellationToken,
) -> Result<()> {
    if cancel.is_cancelled() || ops.generation() != generation {
        return Err(Error::Cancelled);
    }
    let session = client.session().ok_or(Error::Authentication)?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| Error::Protocol)?
        .as_millis();
    if session
        .paired_session_expires_at
        .is_some_and(|expires| u128::from(expires) <= now)
    {
        return Err(Error::Expired);
    }
    Ok(())
}
