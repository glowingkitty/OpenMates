//! Beginning a fresh session on a shell profile after a login or pairing:
//! the revocation fence (`revocation.json`) gets a new epoch bound to the new
//! session's context and is no longer revoked, after any credentials and
//! cache records left by the signed-out session are wiped. Moved from the
//! TUI `storage.rs` (`Store::begin_session_if`); the TUI keyring/vault store
//! and the Apple Keychain store (`AcknowledgedCredentials`) both implement
//! [`SessionBeginStore`]. Spec: `client-core.cache` (fences) and the
//! credential rules in `client-core`.
//!
//! Invariants: a session whose context was revoked never begins again; a
//! signed-in profile is never replaced without a sign-out; the old epoch is
//! re-checked under `revocation.lock` immediately before the new fence is
//! written, so a revocation that lands in between wins.
use super::session_cache_context;
use crate::{
    error::{Error, Result},
    local_cache::{ByteStore, REVOCATION_LOCK, RevocationFence, owner_hash},
    session::Session,
};

/// The credentials a shell store currently holds, as hashes only.
pub struct StoredCredential {
    /// Context hash of the stored session (`session_cache_context`).
    pub context: String,
    /// Owner hash of the stored session (`owner_hash(hashed_email)`).
    pub owner: String,
}

/// The shell side of [`begin_session_epoch`]. Every method is blocking and is
/// called on a blocking thread; the caller holds the shell's credential lock
/// (the TUI `session.lock`) for the whole call when it has one.
pub trait SessionBeginStore {
    /// The byte store holding `revocation.json` (the cache directory).
    type Bytes: ByteStore;

    /// The byte store holding the fence.
    fn fence_store(&self) -> &Self::Bytes;

    /// The credentials stored right now, if any.
    ///
    /// # Errors
    /// Store errors; a stored credential that does not parse.
    fn stored_credential(&self) -> Result<Option<StoredCredential>>;

    /// Whether an interrupted logout still has credential cleanup to do.
    ///
    /// # Errors
    /// Store errors.
    fn cleanup_pending(&self) -> Result<bool>;

    /// Wipe the signed-out session's credentials and every cache record, so
    /// nothing of it is readable under the new epoch.
    ///
    /// # Errors
    /// Store and credential backend errors; the fence then stays as it was.
    fn clear_stale(&self) -> Result<()>;

    /// Write the encoded new fence durably (`Durability::Now`) as
    /// `revocation.json`. Called while `revocation.lock` is held.
    ///
    /// # Errors
    /// Store errors.
    fn write_fence(&self, encoded: &[u8]) -> Result<()>;
}

/// Begin `session` on the profile behind `store`: refuse a revoked or
/// conflicting session, wipe what a sign-out left behind, then (still at the
/// epoch read first, and after `admitted` agreed) write a fresh fence with a
/// new epoch whose `context` and `admitted` are the new session's context.
/// Repeating the begin of the session that is already admitted keeps the
/// epoch (a pairing retried after an unlock prompt). The caller stores the
/// credentials afterwards.
///
/// # Errors
/// `Authentication` for an expired or ownerless session, a revoked context
/// or stored credentials of another owner; `Invalid` while another session
/// is signed in; `Cancelled` when the epoch moved meanwhile; whatever
/// `admitted` or the store returns.
pub fn begin_session_epoch<B: SessionBeginStore + ?Sized>(
    store: &B,
    session: &Session,
    admitted: impl FnOnce() -> Result<()>,
) -> Result<()> {
    if session.is_expired() || session.hashed_email.is_empty() || session.session_id.is_empty() {
        return Err(Error::Authentication);
    }
    let bytes = store.fence_store();
    let before = RevocationFence::load(bytes)?;
    let context = session_cache_context(session)?.context;
    if before.revoked && before.retired_contexts.contains(&context) {
        return Err(Error::Authentication);
    }
    let existing = store.stored_credential()?;
    if before.revoked
        && existing
            .as_ref()
            .is_some_and(|record| record.context == context)
    {
        return Err(Error::Authentication);
    }
    if !before.revoked && before.admitted.as_ref() == Some(&context) {
        if existing.as_ref().is_some_and(|record| {
            record.context != context || record.owner != owner_hash(&session.hashed_email)
        }) {
            return Err(Error::Authentication);
        }
        // A retried admission of the same session changes neither the epoch
        // nor prior cleanup metadata.
        let _fence = bytes.lock(REVOCATION_LOCK)?;
        RevocationFence::load(bytes)?.require_epoch(&before.epoch)?;
        return admitted();
    }
    if !before.revoked && (existing.is_some() || before.cleanup.is_some()) {
        return Err(Error::Invalid(
            "Sign out before admitting another stored session.",
        ));
    }
    if before.revoked || store.cleanup_pending()? {
        store.clear_stale()?;
    }
    let _fence = bytes.lock(REVOCATION_LOCK)?;
    if RevocationFence::load(bytes)?.epoch != before.epoch {
        return Err(Error::Cancelled);
    }
    admitted()?;
    let fence = RevocationFence {
        version: 1,
        epoch: uuid::Uuid::new_v4().to_string(),
        admitted: Some(context.clone()),
        context: Some(context),
        ..Default::default()
    };
    store.write_fence(&serde_json::to_vec(&fence)?)
}
