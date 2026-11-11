//! Credential persistence for acknowledgement-style shells (the Apple
//! Keychain). The shell keeps only opaque credential bytes behind
//! [`CredentialVault`]; the core writes the durable revocation fence
//! (`revocation.json`) in the cache directory, deletes the cache records on
//! clear, and awaits the shell's acknowledgement of each credential revision
//! with a timeout. Native only. Plan: `docs/plans/apple-client-core-migration/a2-design.md`
//! (lane L8); spec: `client-core` credential rules and `client-core.cache`.
use super::{
    CREDENTIAL_ACKNOWLEDGEMENT_TIMEOUT, CredentialPersistence, CredentialSave,
    await_credential_acknowledgement, session_digest,
};
use crate::{
    client::CredentialSnapshot,
    error::{Error, Result},
    local_cache::{
        ByteStore, CacheContext, CacheEngine, Durability, REVOCATION_FILE, REVOCATION_LOCK,
        RevocationFence, owner_hash, sha256_hex,
    },
    session::Session,
};
use futures_util::future::BoxFuture;
use std::{
    sync::{Arc, Mutex, PoisonError},
    time::Duration,
};
use tokio::sync::oneshot;
use zeroize::Zeroizing;

/// Prefix of every cache record file name (`cache-<owner>-<logical>.json`).
const CACHE_RECORD_PREFIX: &str = "cache-";

/// The shell's credential store holding one opaque payload (the serialized
/// core `Session`, secret). The shell never parses, logs or shows it.
pub trait CredentialVault: Send + Sync {
    /// The stored payload, or `None`. Blocking (one Keychain read); the core
    /// calls it on a blocking thread, never on an async worker.
    ///
    /// # Errors
    /// `Locked` when the store is unavailable (device locked), store errors.
    fn load(&self) -> Result<Option<Zeroizing<Vec<u8>>>>;

    /// Credentials changed to `payload` at `revision`. The shell stores the
    /// payload durably, then calls [`AcknowledgedCredentials::acknowledge`]
    /// with the same revision (from any thread). Must not block.
    fn credentials_changed(&self, revision: u64, payload: &[u8]);

    /// Delete the stored payload; a missing payload is success. Blocking.
    ///
    /// # Errors
    /// `Locked` when the store refuses deletion, store errors.
    fn delete(&self) -> Result<()>;
}

/// The cache binding of `session`: owner hash, a context hash over the
/// session identity (`api_url`, `session_id`, `hashed_email`, `created_at`,
/// the TUI `session_context` formula) and the pairing expiry. Records of
/// another session never open with it, because the context enters every AAD.
///
/// # Errors
/// JSON serialization errors (none are expected for these inputs).
pub fn session_cache_context(session: &Session) -> Result<CacheContext> {
    let identity = Zeroizing::new(serde_json::to_vec(&(
        &session.api_url,
        &session.session_id,
        &session.hashed_email,
        session.created_at,
    ))?);
    Ok(CacheContext {
        owner_hash: owner_hash(&session.hashed_email),
        context: sha256_hex(&identity),
        expires_at: session.paired_session_expires_at,
    })
}

#[derive(Default)]
struct State {
    /// The one store waiting for its acknowledgement (stores are serialized
    /// by the session runtime; a newer store drops the older waiter).
    waiting: Option<(u64, oneshot::Sender<()>)>,
    /// Digest of the session known durable in the vault (loaded or acknowledged).
    durable: Option<[u8; 32]>,
}

/// [`CredentialPersistence`] over a [`CredentialVault`] and the cache's byte
/// store. Invariants: `store` reports `Saved` only after the shell
/// acknowledged that exact revision; `revoke` makes the fence durable before
/// it returns and never waits for the vault; `load` returns nothing while the
/// fence is revoked; after revocation `store` refuses with `Locked`.
pub struct AcknowledgedCredentials<S: ByteStore + 'static> {
    vault: Arc<dyn CredentialVault>,
    engine: Arc<CacheEngine<S>>,
    timeout: Duration,
    state: Mutex<State>,
}

/// Run blocking store or vault work off the async workers.
fn blocking<T: Send + 'static>(
    work: impl FnOnce() -> Result<T> + Send + 'static,
) -> BoxFuture<'static, Result<T>> {
    Box::pin(async move {
        tokio::task::spawn_blocking(work)
            .await
            .map_err(|_| Error::Io)?
    })
}

impl<S: ByteStore + 'static> AcknowledgedCredentials<S> {
    /// Persistence over `vault`, fencing through `engine`'s byte store (the
    /// same engine the shell's `CacheStore` uses). Acknowledgement timeout:
    /// [`CREDENTIAL_ACKNOWLEDGEMENT_TIMEOUT`].
    pub fn new(vault: Arc<dyn CredentialVault>, engine: Arc<CacheEngine<S>>) -> Self {
        Self::with_timeout(vault, engine, CREDENTIAL_ACKNOWLEDGEMENT_TIMEOUT)
    }

    /// As [`Self::new`] with an explicit acknowledgement timeout (tests).
    pub fn with_timeout(
        vault: Arc<dyn CredentialVault>,
        engine: Arc<CacheEngine<S>>,
        timeout: Duration,
    ) -> Self {
        Self {
            vault,
            engine,
            timeout,
            state: Mutex::default(),
        }
    }

    fn state(&self) -> std::sync::MutexGuard<'_, State> {
        // A poisoned lock only means a panic elsewhere; the state stays valid.
        self.state.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The shell stored the payload of `revision` durably.
    ///
    /// # Errors
    /// `Cancelled` when no store waits for `revision` (stale, timed out or
    /// revoked in between): the shell must not treat it as current.
    pub fn acknowledge(&self, revision: u64) -> Result<()> {
        let mut state = self.state();
        match state.waiting.take() {
            Some((waiting, sender)) if waiting == revision => {
                sender.send(()).map_err(|()| Error::Cancelled)
            }
            other => {
                state.waiting = other;
                Err(Error::Cancelled)
            }
        }
    }

    fn fence_revoked(&self) -> BoxFuture<'static, Result<bool>> {
        let engine = self.engine.clone();
        blocking(move || Ok(RevocationFence::load(engine.bytes())?.revoked))
    }
}

impl<S: ByteStore + 'static> CredentialPersistence for AcknowledgedCredentials<S> {
    fn load(&self, _generation: u64) -> BoxFuture<'_, Result<Option<Session>>> {
        Box::pin(async move {
            let (vault, engine) = (self.vault.clone(), self.engine.clone());
            let payload = blocking(move || {
                // A revoked profile never hands out credentials, even when a
                // failed cleanup left them in the vault (TUI `load_session`).
                if RevocationFence::load(engine.bytes())?.revoked {
                    return Ok(None);
                }
                vault.load()
            })
            .await?;
            let Some(payload) = payload else {
                return Ok(None);
            };
            let session: Session = serde_json::from_slice(&payload).map_err(|_| Error::Protocol)?;
            if session.is_expired() {
                return Err(Error::Expired);
            }
            self.state().durable = Some(session_digest(&session)?);
            Ok(Some(session))
        })
    }

    fn store(
        &self,
        snapshot: CredentialSnapshot,
        _generation: u64,
    ) -> BoxFuture<'_, Result<CredentialSave>> {
        Box::pin(async move {
            // Revocation is final for this profile (TUI `save_session`).
            if self.fence_revoked().await? {
                return Err(Error::Locked);
            }
            let digest = session_digest(&snapshot.session)?;
            // Change-only: the vault already holds exactly these credentials.
            if self.state().durable == Some(digest) {
                return Ok(CredentialSave::Saved);
            }
            let payload = Zeroizing::new(serde_json::to_vec(&snapshot.session)?);
            let (sender, receiver) = oneshot::channel();
            self.state().waiting = Some((snapshot.revision, sender));
            self.vault
                .credentials_changed(snapshot.revision, payload.as_slice());
            let acknowledged = await_credential_acknowledgement(
                async { receiver.await.map_err(|_| Error::Cancelled) },
                self.timeout,
            )
            .await;
            let mut state = self.state();
            if let Err(error) = acknowledged {
                if state
                    .waiting
                    .as_ref()
                    .is_some_and(|(revision, _)| *revision == snapshot.revision)
                {
                    state.waiting = None;
                }
                return Err(error);
            }
            state.durable = Some(digest);
            Ok(CredentialSave::Saved)
        })
    }

    fn revoke(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            {
                // Any store still waiting for an acknowledgement now fails.
                let mut state = self.state();
                state.waiting = None;
                state.durable = None;
            }
            let engine = self.engine.clone();
            blocking(move || {
                let bytes = engine.bytes();
                let _fence = bytes.lock(REVOCATION_LOCK)?;
                engine.forget_evidence();
                let mut fence = RevocationFence::load(bytes)?;
                if !fence.revoked {
                    // A new epoch: every write prepared for the old one refuses.
                    fence.retired_contexts = fence.context.iter().cloned().collect();
                    fence.version = 1;
                    fence.epoch = uuid::Uuid::new_v4().to_string();
                    fence.revoked = true;
                    bytes.put(
                        REVOCATION_FILE,
                        &serde_json::to_vec(&fence)?,
                        Durability::Now,
                    )?;
                }
                Ok(())
            })
            .await
        })
    }

    fn clear(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            let (vault, engine) = (self.vault.clone(), self.engine.clone());
            blocking(move || {
                let bytes = engine.bytes();
                if !RevocationFence::load(bytes)?.revoked {
                    return Err(Error::Cancelled);
                }
                // The directory belongs to one app profile: every cache record
                // and its lock file goes, whichever owner wrote it.
                for name in bytes.list(CACHE_RECORD_PREFIX)? {
                    if name.ends_with(".json") || name.ends_with(".json.lock") {
                        bytes.delete(&name)?;
                    }
                }
                bytes.barrier()?;
                vault.delete()
            })
            .await
        })
    }
}
