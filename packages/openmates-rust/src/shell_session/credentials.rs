//! The credential seam between the core session runtime and a shell's
//! credential store (TUI keyring/vault/session envelope, Apple Keychain).
//!
//! The core never reads or writes a credential store itself: it hands the
//! shell a [`CredentialSnapshot`] and waits for the shell to report it durable.
//! Spec: `client-core` credential rules (snapshots never enter view models or
//! logs).
use crate::{client::CredentialSnapshot, error::Result, session::Session};
use futures_util::future::BoxFuture;
use std::{future::Future, time::Duration};

/// Outcome of [`CredentialPersistence::store`].
pub enum CredentialSave {
    /// The snapshot is durable (written now, or already the stored one).
    Saved,
    /// Another process rotated and stored newer credentials for the same
    /// account; the snapshot was not written and the client adopts these.
    Superseded(Box<Session>),
}

/// How a shell keeps credentials durable. Object safe; every method returns
/// a boxed future so the core's futures stay small.
///
/// Generations: `load` and `store` receive the queue generation the core
/// captured before calling. An implementation that runs on the shell's
/// ordered queue refuses with `Error::Cancelled` when the generation has moved
/// (a logout started in between); one that cannot observe the generation may
/// ignore it, because the core rechecks the generation after every await.
///
/// Acknowledgement-style shells (Apple): `store` emits a "credentials changed
/// (revision)" callback carrying `snapshot.revision`, then awaits the matching
/// acknowledgement with [`await_credential_acknowledgement`]. A timeout
/// returns `Error::Locked`; the core then stops before any cache write or
/// client acknowledgement, so nothing claims durability that was not reached.
///
/// Locking: shells whose cache engine takes `local_cache::SESSION_LOCK` must
/// take the same scope around their own credential writes.
pub trait CredentialPersistence: Send + Sync {
    /// The stored credentials of the selected profile, or `None`.
    ///
    /// # Errors
    /// `Cancelled` for a stale generation, `Locked` when the store cannot be
    /// unlocked, `Expired` for a lapsed stored pairing, store errors.
    fn load(&self, generation: u64) -> BoxFuture<'_, Result<Option<Session>>>;

    /// Make `snapshot` durable unless another process already stored newer
    /// credentials for the same account. Change-only stores may skip an
    /// unchanged write but must still report `Saved` only when durable.
    ///
    /// # Errors
    /// `Cancelled` for a stale generation, `Locked` for an unavailable store
    /// or an acknowledgement timeout, `Expired`, store errors.
    fn store(
        &self,
        snapshot: CredentialSnapshot,
        generation: u64,
    ) -> BoxFuture<'_, Result<CredentialSave>>;

    /// Durably announce revocation. After this returns no later `load`
    /// returns credentials and every fenced cache write refuses. Must not wait
    /// behind slow credential-store work (a stalled keyring cannot delay it).
    /// Runs regardless of generation; repeating it is harmless.
    ///
    /// # Errors
    /// Store errors; the caller then reports logout as failed.
    fn revoke(&self) -> BoxFuture<'_, Result<()>>;

    /// Remove credential material and the owner's cache files. The core calls
    /// it only after [`CredentialPersistence::revoke`] succeeded.
    ///
    /// # Errors
    /// `Locked` when the secret store refuses deletion, store errors. The
    /// revocation stays in force either way.
    fn clear(&self) -> BoxFuture<'_, Result<()>>;
}

/// Default bound for an acknowledgement-style shell to confirm a credential
/// save (one Keychain round trip on rotation).
pub const CREDENTIAL_ACKNOWLEDGEMENT_TIMEOUT: Duration = Duration::from_secs(10);

/// Await a shell's acknowledgement of a credential save within `timeout`.
///
/// # Errors
/// `Locked` when `timeout` elapses first (the credential store did not confirm
/// durability), otherwise the acknowledgement's own error.
pub async fn await_credential_acknowledgement<T>(
    acknowledgement: impl Future<Output = Result<T>>,
    timeout: Duration,
) -> Result<T> {
    tokio::time::timeout(timeout, acknowledgement)
        .await
        .map_err(|_| crate::error::Error::Locked)?
}
