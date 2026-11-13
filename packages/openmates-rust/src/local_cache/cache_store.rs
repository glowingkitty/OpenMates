//! `CacheStore`: the async façade over [`CacheEngine`]. It runs the blocking
//! store calls on one ordered queue guarded by a generation counter, and
//! offers two fast paths that do not wait behind that queue.
//!
//! Part of the shared client core (`local_cache`); moved from the TUI
//! `runtime_store.rs` (ordered queue, generation guard, content loader).
//! Native targets only (needs `spawn_blocking`). Spec: `client-core.cache`.
//! Ordering invariant: a started operation keeps its queue permit until the
//! blocking closure ends, even if the caller's future is dropped; an operation
//! whose captured generation is no longer current refuses with `Cancelled`.
use super::{
    ByteStore, CacheAdmission, CacheEngine, MAX_LOCAL_RECORD_BYTES, OperationScope,
    PreparedSections, SyncCacheRead, SyncReadMode, cache_record_encoded_len,
};
use crate::{
    client::CachedContentLoader,
    error::{Error, Result},
};
use futures_util::future::BoxFuture;
use serde_json::Value;
use std::sync::{
    Arc,
    atomic::{AtomicU64, Ordering},
};
use tokio::sync::Mutex;
use zeroize::Zeroizing;

/// 32-byte cache key handed to every operation; never retained by the store.
pub type CacheKey = Zeroizing<[u8; 32]>;

/// Read-only publication guard: true while no revocation advanced the
/// generation it was taken at. Holds neither store nor credentials.
#[derive(Clone)]
pub struct GenerationGuard {
    current: Arc<AtomicU64>,
    expected: u64,
}

impl GenerationGuard {
    /// Whether the generation has not moved since the guard was taken.
    pub fn is_current(&self) -> bool {
        self.current.load(Ordering::SeqCst) == self.expected
    }

    /// The generation the guard was taken at, for operations that must refuse
    /// on their own queue once it moved (`OrderedBlocking::run(Some(..))`).
    pub fn generation(&self) -> u64 {
        self.expected
    }
}

/// The shell-wide ordered blocking queue and its generation counter. Cloned
/// into every façade that must serialize with the others (cache operations and
/// the shell's credential operations share one queue).
#[derive(Clone, Default)]
pub struct OrderedBlocking {
    queue: Arc<Mutex<()>>,
    generation: Arc<AtomicU64>,
}

impl OrderedBlocking {
    /// Fresh queue at generation 0.
    pub fn new() -> Self {
        Self::default()
    }

    /// Current generation.
    pub fn generation(&self) -> u64 {
        self.generation.load(Ordering::SeqCst)
    }

    /// Advance the generation: every operation captured earlier refuses.
    /// Returns the new generation.
    pub fn advance(&self) -> u64 {
        self.generation.fetch_add(1, Ordering::SeqCst) + 1
    }

    /// A guard bound to the current generation.
    pub fn guard(&self) -> GenerationGuard {
        GenerationGuard {
            current: self.generation.clone(),
            expected: self.generation(),
        }
    }

    /// Whether `generation` is still the current one.
    pub fn is_current(&self, generation: u64) -> bool {
        self.generation() == generation
    }

    /// Take the queue until the returned guard drops: every later queued
    /// operation waits. A test seam for ordering behaviour.
    pub async fn hold(&self) -> tokio::sync::OwnedMutexGuard<()> {
        self.queue.clone().lock_owned().await
    }

    /// Run `operation` on the blocking pool behind everything queued before
    /// it. With `Some(generation)` (captured by the caller before queueing) it
    /// refuses with `Cancelled` when the generation has moved by the time it
    /// starts; `None` runs regardless (logout cleanup must not be refused).
    ///
    /// # Errors
    /// `Cancelled` for a stale generation, `Io` when the blocking task fails,
    /// otherwise the operation's error.
    pub fn run<T: Send + 'static>(
        &self,
        generation: Option<u64>,
        operation: impl FnOnce() -> Result<T> + Send + 'static,
    ) -> BoxFuture<'static, Result<T>> {
        let (queue, current) = (self.queue.clone(), self.generation.clone());
        // Boxed on purpose: the caller's future then holds a pointer instead of
        // this whole state, which keeps deeply nested test futures within a
        // default thread stack.
        Box::pin(async move {
            let permit = queue.lock_owned().await;
            tokio::task::spawn_blocking(move || {
                // The permit lives in the blocking closure, not the cancellable
                // future, until the filesystem operation ends.
                let _permit = permit;
                if generation.is_some_and(|expected| current.load(Ordering::SeqCst) != expected) {
                    return Err(Error::Cancelled);
                }
                operation()
            })
            .await
            .map_err(|_| Error::Io)?
        })
    }
}

/// Async cache over one [`CacheEngine`], one admission hook and one shell
/// operation scope.
pub struct CacheStore<S: ByteStore + 'static> {
    engine: Arc<CacheEngine<S>>,
    admission: Arc<dyn CacheAdmission>,
    scope: Arc<dyn OperationScope>,
    ops: OrderedBlocking,
}

impl<S: ByteStore + 'static> Clone for CacheStore<S> {
    fn clone(&self) -> Self {
        Self {
            engine: self.engine.clone(),
            admission: self.admission.clone(),
            scope: self.scope.clone(),
            ops: self.ops.clone(),
        }
    }
}

impl<S: ByteStore + 'static> CacheStore<S> {
    /// Façade over `engine`; `ops` is shared with every other queued operation
    /// of the shell.
    pub fn new(
        engine: Arc<CacheEngine<S>>,
        admission: Arc<dyn CacheAdmission>,
        scope: Arc<dyn OperationScope>,
        ops: OrderedBlocking,
    ) -> Self {
        Self {
            engine,
            admission,
            scope,
            ops,
        }
    }

    /// The engine (for shells that keep a synchronous path).
    pub fn engine(&self) -> &Arc<CacheEngine<S>> {
        &self.engine
    }

    /// The ordered queue this store runs on.
    pub fn ops(&self) -> &OrderedBlocking {
        &self.ops
    }

    /// Queued operation: shell scope entered, then `operation` on the engine.
    fn queued<T: Send + 'static>(
        &self,
        operation: impl FnOnce(&CacheEngine<S>, &dyn CacheAdmission) -> Result<T> + Send + 'static,
    ) -> BoxFuture<'static, Result<T>> {
        let (engine, admission, scope) = (
            self.engine.clone(),
            self.admission.clone(),
            self.scope.clone(),
        );
        self.ops.run(Some(self.ops.generation()), move || {
            let _scope = scope.enter()?;
            operation(&engine, admission.as_ref())
        })
    }

    /// Unqueued operation for the fast paths: same generation refusal and
    /// scope, but no wait behind queued writes. The file locks inside the
    /// engine still order it against a running write.
    fn immediate<T: Send + 'static>(
        &self,
        operation: impl FnOnce(&CacheEngine<S>, &dyn CacheAdmission) -> Result<T> + Send + 'static,
    ) -> BoxFuture<'static, Result<T>> {
        let (engine, admission, scope) = (
            self.engine.clone(),
            self.admission.clone(),
            self.scope.clone(),
        );
        let current = self.ops.guard();
        Box::pin(async move {
            tokio::task::spawn_blocking(move || {
                if !current.is_current() {
                    return Err(Error::Cancelled);
                }
                let _scope = scope.enter()?;
                operation(&engine, admission.as_ref())
            })
            .await
            .map_err(|_| Error::Io)?
        })
    }

    /// Authenticated read of one logical value (sectioned layout assembled).
    ///
    /// # Errors
    /// As [`CacheEngine::read_cache`], plus `Cancelled` for a stale generation.
    pub fn read_cache(
        &self,
        owner: String,
        key: String,
        master: CacheKey,
    ) -> BoxFuture<'static, Result<Option<Value>>> {
        self.queued(move |engine, admission| engine.read_cache(admission, &owner, &key, &master))
    }

    /// Publish one logical value as a single record.
    ///
    /// # Errors
    /// As [`CacheEngine::write_cache`], plus `Cancelled` for a stale generation.
    pub fn write_cache(
        &self,
        owner: String,
        key: String,
        master: CacheKey,
        value: Value,
    ) -> BoxFuture<'static, Result<()>> {
        self.queued(move |engine, admission| {
            engine.write_cache(admission, &owner, &key, &master, &value)
        })
    }

    /// Capacity only, no write or admission: whether a checkpoint of
    /// `checkpoint_json_bytes` would fit a record this store can read back.
    ///
    /// # Errors
    /// `Protocol` on arithmetic overflow.
    pub fn admits_checkpoint(&self, checkpoint_json_bytes: usize) -> Result<bool> {
        Ok(cache_record_encoded_len(checkpoint_json_bytes)? <= MAX_LOCAL_RECORD_BYTES)
    }

    /// Queued authenticated read of the sync cache (index or complete).
    ///
    /// # Errors
    /// As [`CacheEngine::read_sync_cache`].
    pub fn read_sync_cache(
        &self,
        owner: String,
        key: String,
        master: CacheKey,
        mode: SyncReadMode,
    ) -> BoxFuture<'static, Result<Option<SyncCacheRead>>> {
        self.queued(move |engine, admission| {
            engine.read_sync_cache(admission, &owner, &key, &master, mode)
        })
    }

    /// Fast path: the Chat-list index only (one file), without waiting behind
    /// queued writes. Returns the index snapshot, or `None` when no cache exists.
    ///
    /// # Errors
    /// As [`CacheEngine::read_sync_cache`].
    pub fn read_index(
        &self,
        owner: String,
        key: String,
        master: CacheKey,
    ) -> BoxFuture<'static, Result<Option<Value>>> {
        let read = self.immediate(move |engine, admission| {
            engine.read_sync_cache(admission, &owner, &key, &master, SyncReadMode::Index)
        });
        Box::pin(async move {
            Ok(read.await?.map(|read| match read {
                SyncCacheRead::Index(value) | SyncCacheRead::Complete(value) => value,
            }))
        })
    }

    /// Queued read of one Chat's content section (the index must have been read).
    ///
    /// # Errors
    /// As [`CacheEngine::read_sync_chat`].
    pub fn read_sync_chat(
        &self,
        owner: String,
        key: String,
        master: CacheKey,
        chat: String,
    ) -> BoxFuture<'static, Result<Option<Value>>> {
        self.queued(move |engine, admission| {
            engine.read_sync_chat(admission, &owner, &key, &master, &chat)
        })
    }

    /// Fast path: one Chat's content section without waiting behind queued
    /// writes (instant chat open). Needs the index to have been read first;
    /// otherwise `Cancelled`.
    ///
    /// # Errors
    /// As [`CacheEngine::read_sync_chat`].
    pub fn cached_chat(
        &self,
        owner: String,
        key: String,
        master: CacheKey,
        chat: String,
    ) -> BoxFuture<'static, Result<Option<Value>>> {
        self.immediate(move |engine, admission| {
            engine.read_sync_chat(admission, &owner, &key, &master, &chat)
        })
    }

    /// Durably revoke the list-freshness receipt without reading the cache.
    ///
    /// # Errors
    /// As [`CacheEngine::revoke_sync_freshness`].
    pub fn revoke_freshness(&self, owner: String, key: String) -> BoxFuture<'static, Result<()>> {
        self.queued(move |engine, admission| engine.revoke_sync_freshness(admission, &owner, &key))
    }

    /// Loader for the SDK's partial restore. It runs synchronously inside SDK
    /// operations, outside the queue; the engine's file locks still serialize
    /// it and a revoked or advanced generation refuses it.
    pub fn content_loader(
        &self,
        owner: String,
        key: String,
        master: CacheKey,
    ) -> CachedContentLoader {
        let (engine, admission) = (self.engine.clone(), self.admission.clone());
        let generation = self.ops.guard();
        Arc::new(move |loaded: &[String]| {
            if !generation.is_current() {
                return Err(Error::Cancelled);
            }
            let remainder =
                engine.read_sync_remainder(admission.as_ref(), &owner, &key, &master, loaded)?;
            if !generation.is_current() {
                return Err(Error::Cancelled);
            }
            Ok(remainder)
        })
    }

    /// Pure, bounded preparation of the sections of `snapshot`.
    ///
    /// # Errors
    /// As [`CacheEngine::prepare_sync_sections`].
    pub fn prepare_sections(
        &self,
        snapshot: Value,
        partial: Option<Vec<String>>,
    ) -> BoxFuture<'static, Result<PreparedSections>> {
        self.queued(move |engine, _| engine.prepare_sync_sections(snapshot, partial))
    }

    /// Change-only publication of prepared sections; whether anything changed.
    ///
    /// # Errors
    /// As [`CacheEngine::write_sync_sections`].
    pub fn write_sections(
        &self,
        owner: String,
        key: String,
        master: CacheKey,
        prepared: PreparedSections,
    ) -> BoxFuture<'static, Result<bool>> {
        self.queued(move |engine, admission| {
            engine.write_sync_sections(admission, &owner, &key, &master, prepared)
        })
    }
}
