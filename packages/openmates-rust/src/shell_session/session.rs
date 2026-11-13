//! `ShellSession`: restore, cache-first Chat open, persistence and logout over
//! one `CacheStore` and a shell's [`CredentialPersistence`].
//!
//! Moved unchanged from the TUI `session_runtime.rs` (`restore_command_cache`,
//! `load_cached_chat`, `persist`, `logout`) and `runtime_store.rs` (deferred
//! cache state). Ordering invariants: credentials are durable before any cache
//! section is published; section records are published before the index; the
//! client acknowledges a credential revision only after both; logout makes
//! revocation durable before credential cleanup. Spec: `client-core.cache`.
use super::{
    CredentialPersistence, CredentialSave, DurableCandidate, cache_key, credential_digest, current,
    session_digest,
};
use crate::{
    client::{ChatRefreshDurableReceipt, Client},
    error::{Error, Result},
    local_cache::{ByteStore, CacheStore, OrderedBlocking, SyncCacheRead, SyncReadMode},
};
use futures_util::future::BoxFuture;
use std::sync::{Arc, Mutex, PoisonError};
use tokio_util::sync::CancellationToken;

/// Which part of the protected sync cache a restore reads.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CacheLoad {
    /// Never read or rewrite the cache (operations that read no cached Chats).
    /// With `revoke_list_freshness`, list freshness is still durably revoked
    /// at the next persist (the pre-dispatch fence).
    Deferred {
        /// Revoke the list-freshness receipt at the next persist.
        revoke_list_freshness: bool,
    },
    /// Only the Chat-list index; per-Chat content loads on demand.
    Index,
    /// The index plus one Chat's cached content (cache-first open).
    Chat(String),
    /// Everything.
    Full,
}

/// Deliberately unread sync cache state of this process.
#[derive(Clone, Copy)]
struct DeferredCache {
    revoke_freshness: bool,
}

/// What `persist` did; only `Committed` may mint a durable receipt.
enum Persisted {
    /// Credentials durable, cache published, revision acknowledged.
    Committed,
    /// Another process stored newer credentials; they were adopted and no
    /// cache was written.
    Superseded,
    /// The client had no credentials; the profile was revoked and cleared.
    Cleared,
}

/// The core session runtime of one shell profile. Cheap to clone; clones
/// share the cache, its ordered queue and the deferred-cache state.
pub struct ShellSession<S: ByteStore + 'static> {
    cache: CacheStore<S>,
    deferred: Arc<Mutex<Option<DeferredCache>>>,
}

impl<S: ByteStore + 'static> Clone for ShellSession<S> {
    fn clone(&self) -> Self {
        Self {
            cache: self.cache.clone(),
            deferred: self.deferred.clone(),
        }
    }
}

impl<S: ByteStore + 'static> ShellSession<S> {
    /// Session runtime over `cache`. The shell's credential operations must
    /// run on the same `OrderedBlocking` as `cache` (see [`Self::ops`]).
    pub fn new(cache: CacheStore<S>) -> Self {
        Self {
            cache,
            deferred: Arc::default(),
        }
    }

    /// The cache façade.
    pub fn cache(&self) -> &CacheStore<S> {
        &self.cache
    }

    /// The ordered queue shared by cache and credential operations.
    pub fn ops(&self) -> &OrderedBlocking {
        self.cache.ops()
    }

    /// Mark the sync cache as deliberately unread: persistence then never
    /// reads or rewrites it; with `revoke_freshness` the next persist durably
    /// revokes only the list-freshness receipt.
    pub fn defer_sync_cache(&self, revoke_freshness: bool) {
        *self.deferred.lock().unwrap_or_else(PoisonError::into_inner) =
            Some(DeferredCache { revoke_freshness });
    }

    /// `Some(revocation still pending)` while the sync cache is deferred.
    pub fn sync_cache_deferred(&self) -> Option<bool> {
        self.deferred
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .map(|deferred| deferred.revoke_freshness)
    }

    async fn revoke_deferred_freshness(&self, owner: String, key: String) -> Result<()> {
        self.cache.revoke_freshness(owner, key).await?;
        if let Some(deferred) = self
            .deferred
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .as_mut()
        {
            deferred.revoke_freshness = false;
        }
        Ok(())
    }

    /// Restore the durable profile's protected ciphertext into `client`
    /// before its first save, limited to `load`. Grants no server
    /// authentication and publishes nothing. The durable credentials must be
    /// exactly the client's (else `Cancelled`). Read, shape and context
    /// failures preserve the on-disk profile and cache; a failure after the
    /// restore started forgets the client's session.
    ///
    /// # Errors
    /// `Cancelled` (cancel, generation moved, other credentials),
    /// `Authentication` (no durable session), `Expired`, cache errors.
    pub fn restore<'a>(
        &'a self,
        client: &'a mut Client,
        credentials: &'a dyn CredentialPersistence,
        cancel: &'a CancellationToken,
        load: CacheLoad,
    ) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            let ops = self.ops().clone();
            let generation = ops.generation();
            current(client, &ops, generation, cancel)?;
            let durable = credentials
                .load(generation)
                .await?
                .ok_or(Error::Authentication)?;
            self.restore_loaded_at(client, &durable, generation, cancel, load)
                .await
                .map(|_| ())
        })
    }

    /// [`Self::restore`] for credentials the shell has just loaded from its
    /// store (the view-model `Start` command carries them), so the store is
    /// not read twice (a vault load runs a password KDF). `durable` must be
    /// exactly the client's credentials. Returns whether a cached index existed.
    ///
    /// # Errors
    /// As [`Self::restore`].
    pub fn restore_loaded<'a>(
        &'a self,
        client: &'a mut Client,
        durable: &'a crate::session::Session,
        cancel: &'a CancellationToken,
        load: CacheLoad,
    ) -> BoxFuture<'a, Result<bool>> {
        Box::pin(async move {
            let ops = self.ops().clone();
            let generation = ops.generation();
            current(client, &ops, generation, cancel)?;
            self.restore_loaded_at(client, durable, generation, cancel, load)
                .await
        })
    }

    async fn restore_loaded_at(
        &self,
        client: &mut Client,
        durable: &crate::session::Session,
        generation: u64,
        cancel: &CancellationToken,
        load: CacheLoad,
    ) -> Result<bool> {
        let ops = self.ops().clone();
        {
            if session_digest(durable)? != credential_digest(client)? {
                return Err(Error::Cancelled);
            }
            let owner = durable.hashed_email.clone();
            let key = cache_key(durable);
            let master = durable.master_key.clone();
            let mode = match &load {
                CacheLoad::Deferred {
                    revoke_list_freshness,
                } => {
                    self.defer_sync_cache(*revoke_list_freshness);
                    return current(client, &ops, generation, cancel).map(|()| false);
                }
                CacheLoad::Full => SyncReadMode::Complete,
                CacheLoad::Index | CacheLoad::Chat(_) => SyncReadMode::Index,
            };
            let read = self
                .cache
                .read_sync_cache(owner.clone(), key.clone(), master.clone(), mode)
                .await?;
            current(client, &ops, generation, cancel)?;
            let found = read.is_some();
            let restored = match read {
                None => Ok(()),
                Some(SyncCacheRead::Complete(snapshot)) => {
                    client.restore_authenticated_ciphertext_snapshot(&snapshot)
                }
                Some(SyncCacheRead::Index(index)) => client.restore_authenticated_ciphertext_index(
                    &index,
                    self.cache.content_loader(owner, key, master),
                ),
            };
            if let Err(error) = restored {
                client.forget_session();
                return Err(error);
            }
            if let CacheLoad::Chat(chat) = load
                && let Err(error) = self.load_cached_chat(client, &chat).await
            {
                client.forget_session();
                return Err(error);
            }
            if let Err(error) = current(client, &ops, generation, cancel) {
                client.forget_session();
                return Err(error);
            }
            Ok(found)
        }
    }

    /// Cache-first Chat open: decrypt only this Chat's cached content section
    /// (messages, sync window/cursor, selected first page, its embeds and
    /// keys) into a partially restored client. Returns whether a cached
    /// section existed; a completely restored client already holds it.
    ///
    /// # Errors
    /// `Authentication` without a session, cache and restore errors.
    pub fn load_cached_chat<'a>(
        &'a self,
        client: &'a mut Client,
        chat: &'a str,
    ) -> BoxFuture<'a, Result<bool>> {
        Box::pin(async move {
            if client
                .partially_restored_chats()
                .is_none_or(|loaded| loaded.iter().any(|id| id == chat))
            {
                return Ok(true);
            }
            let session = client.session().ok_or(Error::Authentication)?;
            let section = self
                .cache
                .read_sync_chat(
                    session.hashed_email.clone(),
                    cache_key(session),
                    session.master_key.clone(),
                    chat.to_owned(),
                )
                .await?;
            let found = section.is_some();
            client.restore_cached_chat_content(chat, section.as_ref())?;
            Ok(found)
        })
    }

    /// Persist the client's credentials and protected cache, then acknowledge
    /// exactly the saved credential revision. Change-only: unchanged
    /// credentials and sections are not rewritten; content a partially
    /// restored client never loaded is retained. A client without credentials
    /// revokes and clears the profile.
    ///
    /// # Errors
    /// `Invalid` for an oversized cache (before any credential write),
    /// `Cancelled` when the generation moved, credential and cache errors.
    pub fn persist<'a>(
        &'a self,
        client: &'a mut Client,
        credentials: &'a dyn CredentialPersistence,
    ) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move { self.persist_inner(client, credentials).await.map(|_| ()) })
    }

    /// [`Self::persist`] for a candidate whose publication needs a durable
    /// receipt. The receipt is minted only after the credentials are durable,
    /// the cache index is committed and the client acknowledged the revision;
    /// the candidate is validated before anything is written.
    ///
    /// # Errors
    /// As [`Self::persist`]; `Cancelled` for a stale candidate or when another
    /// process superseded the credentials (nothing of this client was saved).
    pub fn persist_for<'a, C: DurableCandidate + Sync>(
        &'a self,
        client: &'a mut Client,
        credentials: &'a dyn CredentialPersistence,
        candidate: &'a C,
    ) -> BoxFuture<'a, Result<ChatRefreshDurableReceipt>> {
        Box::pin(async move {
            let ciphertext_sha256 = candidate.ciphertext_sha256()?;
            let credential_revision = candidate.credential_revision();
            match self.persist_inner(client, credentials).await? {
                Persisted::Committed => Ok(ChatRefreshDurableReceipt {
                    ciphertext_sha256,
                    credential_revision,
                }),
                Persisted::Superseded | Persisted::Cleared => Err(Error::Cancelled),
            }
        })
    }

    async fn persist_inner(
        &self,
        client: &mut Client,
        credentials: &dyn CredentialPersistence,
    ) -> Result<Persisted> {
        let Some(snapshot) = client.credential_snapshot() else {
            self.clear_credentials(credentials).await?;
            return Ok(Persisted::Cleared);
        };
        let (owner, key, master, revision) = (
            snapshot.session.hashed_email.clone(),
            cache_key(&snapshot.session),
            snapshot.session.master_key.clone(),
            snapshot.revision,
        );
        let generation = self.ops().guard();
        let deferred = self.sync_cache_deferred();
        // Pure, bounded preparation first: an oversized cache refuses before
        // any credential is written.
        let cache = match deferred {
            Some(_) => None,
            None => Some(
                self.cache
                    .prepare_sections(
                        client.ciphertext_snapshot(),
                        client.partially_restored_chats(),
                    )
                    .await?,
            ),
        };
        if !generation.is_current() {
            return Err(Error::Cancelled);
        }
        // Credentials durable before any section that names them.
        if let CredentialSave::Superseded(stored) =
            credentials.store(snapshot, generation.generation()).await?
        {
            if !generation.is_current() {
                return Err(Error::Cancelled);
            }
            client.adopt_stored_credentials(&stored)?;
            return Ok(Persisted::Superseded);
        }
        if !generation.is_current() {
            return Err(Error::Cancelled);
        }
        // Section records, barrier, then the index (inside write_sections).
        if let Some(cache) = cache {
            self.cache.write_sections(owner, key, master, cache).await?;
        } else if deferred == Some(true) {
            self.revoke_deferred_freshness(owner, key).await?;
        }
        if !generation.is_current() {
            return Err(Error::Cancelled);
        }
        // Acknowledge only after durable credential and cache publication.
        client.acknowledge_credentials(revision)?;
        Ok(Persisted::Committed)
    }

    /// Durable pre-dispatch fence for recovery, TUI and other uncertain
    /// effects: revoke list freshness and persist. Failure refuses dispatch;
    /// a crash afterwards restores no stale receipt.
    ///
    /// # Errors
    /// `Cancelled` (cancel or generation moved), as [`Self::persist`].
    pub fn revoke_list_freshness_before_dispatch<'a>(
        &'a self,
        client: &'a mut Client,
        credentials: &'a dyn CredentialPersistence,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            let ops = self.ops().clone();
            let generation = ops.generation();
            current(client, &ops, generation, cancel)?;
            client.invalidate_chat_list_freshness();
            self.persist(client, credentials).await?;
            current(client, &ops, generation, cancel)
        })
    }

    /// Announce sign-out ahead of the session's owner: advance the generation
    /// (every queued or later operation captured before refuses) and make the
    /// revocation durable, without waiting for credential cleanup. A shell
    /// calls this from a lane that does not wait for a busy client (a stalled
    /// keyring cannot delay it); the later [`Self::logout`] repeats it.
    ///
    /// # Errors
    /// Revocation errors; the shell then reports logout as failed.
    pub fn revoke_credentials<'a>(
        &'a self,
        credentials: &'a dyn CredentialPersistence,
    ) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            self.ops().advance();
            credentials.revoke().await
        })
    }

    /// Local sign-out: advance the generation (every queued or later
    /// operation captured before refuses), make revocation durable, then
    /// clear credentials. Revocation is durable before any cleanup starts.
    ///
    /// # Errors
    /// Revocation or cleanup errors; a failed cleanup leaves the revocation.
    pub fn clear_credentials<'a>(
        &'a self,
        credentials: &'a dyn CredentialPersistence,
    ) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            self.ops().advance();
            credentials.revoke().await?;
            credentials.clear().await
        })
    }

    /// Sign out: local revocation and cleanup run even when remote logout is
    /// unavailable, concurrently with it. The queue fences earlier started
    /// writes; SDK logout drops live key material.
    ///
    /// # Errors
    /// The local error first, else the remote one.
    pub fn logout<'a>(
        &'a self,
        client: &'a mut Client,
        credentials: &'a dyn CredentialPersistence,
    ) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            let (local, remote) =
                tokio::join!(self.clear_credentials(credentials), client.logout());
            local?;
            remote
        })
    }
}
