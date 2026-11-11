//! `CacheEngine`: the synchronous encrypted cache over a `ByteStore`: single
//! records plus the publication evidence the sectioned layout reuses.
//!
//! Part of the shared client core (`local_cache`); moved from the TUI
//! `storage.rs`/`storage_sections.rs` with the on-disk format unchanged
//! (`client-core.cache`). Invariants: every publication re-checks the durable
//! epoch under `revocation.lock`; a skipped rewrite needs the same epoch,
//! key/AAD binding, plaintext digest and unchanged record version, and fsyncs
//! a merely loaded record once before it counts as durable.
use super::{
    ByteStore, CacheAdmission, Durability, LockGuard, MAX_LOCAL_RECORD_BYTES, RevocationFence,
    SESSION_LOCK, cache_file_name, decode_cache_record_value, encode_bounded_json,
    encode_cache_record, publish_record,
    sections::{Manifest, SyncCacheRead, SyncReadMode},
};
use crate::error::{Error, Result};
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    sync::{
        Mutex, PoisonError,
        atomic::{AtomicUsize, Ordering},
    },
};
use zeroize::Zeroizing;

/// In-process evidence of one durable cache record. Never serialized.
pub(super) struct DurableCache<V> {
    pub(super) epoch: String,
    pub(super) binding: Zeroizing<[u8; 32]>,
    pub(super) plaintext_digest: [u8; 32],
    pub(super) version: V,
    pub(super) synced: bool,
}

/// Keyed binding of a record's epoch and AAD, used only by the retained
/// publication evidence: a different key, epoch or AAD never matches.
pub(super) fn cache_publication_mac(
    key: &[u8; 32],
    epoch: &str,
    aad: &[u8],
) -> Result<Hmac<Sha256>> {
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key).map_err(|_| Error::Crypto)?;
    mac.update(b"openmates-rust-cache-publication-v1\0");
    mac.update(&serde_json::to_vec(&(epoch, aad))?);
    Ok(mac)
}

/// The encrypted cache over one `ByteStore`. All calls are synchronous and
/// blocking; [`super::CacheStore`] runs them on the ordered blocking queue.
pub struct CacheEngine<S: ByteStore> {
    pub(super) bytes: S,
    pub(super) durable: Mutex<HashMap<String, DurableCache<S::Version>>>,
    pub(super) manifests: Mutex<HashMap<String, Manifest>>,
    encodings: AtomicUsize,
}

impl<S: ByteStore> CacheEngine<S> {
    /// Engine over `bytes` with no remembered evidence.
    pub fn new(bytes: S) -> Self {
        Self {
            bytes,
            durable: Mutex::new(HashMap::new()),
            manifests: Mutex::new(HashMap::new()),
            encodings: AtomicUsize::new(0),
        }
    }

    /// The underlying byte store (for shells that keep other records in it).
    pub fn bytes(&self) -> &S {
        &self.bytes
    }

    /// Completed bounded serializations since creation. A test seam: shells
    /// assert that refused or skipped writes do not serialize.
    pub fn encode_count(&self) -> usize {
        self.encodings.load(Ordering::SeqCst)
    }

    pub(super) fn count_encoding(&self) {
        self.encodings.fetch_add(1, Ordering::SeqCst);
    }

    /// Drop all remembered publication evidence and manifests (logout,
    /// revocation): afterwards every write takes the full encrypted path.
    pub fn forget_evidence(&self) {
        self.durable
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clear();
        self.manifests
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .clear();
    }

    pub(super) fn active_epoch(&self) -> Result<String> {
        RevocationFence::load(&self.bytes)?.active_epoch()
    }

    pub(super) fn require_epoch(&self, expected: &str) -> Result<()> {
        RevocationFence::load(&self.bytes)?.require_epoch(expected)
    }

    pub(super) fn lock(&self, scope: &str) -> Result<LockGuard> {
        Ok(self.bytes.lock(scope)?)
    }

    /// Bounded JSON encoding of one single-record value; counts a completed
    /// serialization.
    fn encode_value(&self, value: &serde_json::Value) -> Result<Zeroizing<Vec<u8>>> {
        let bytes = encode_bounded_json(value)?;
        self.count_encoding();
        Ok(bytes)
    }

    /// Authenticated read of one logical cache value: the committed sectioned
    /// layout (assembled completely) supersedes a legacy single record.
    ///
    /// # Errors
    /// `Authentication`/`Cancelled` after revocation, admission errors,
    /// `Crypto` for a record of another context or key, store errors.
    pub fn read_cache(
        &self,
        admission: &dyn CacheAdmission,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
    ) -> Result<Option<serde_json::Value>> {
        let epoch = self.active_epoch()?;
        let _session_guard = self.lock(SESSION_LOCK)?;
        self.require_epoch(&epoch)?;
        let context = admission.admit(owner)?;
        let name = cache_file_name(owner, cache_key);
        let _cache_guard = self.lock(&format!("{name}.lock"))?;
        if let Some(read) = self.read_sections_locked(
            &context,
            owner,
            cache_key,
            key,
            &epoch,
            SyncReadMode::Complete,
        )? {
            let value = match read {
                SyncCacheRead::Complete(value) | SyncCacheRead::Index(value) => value,
            };
            let _fence = self.lock(super::REVOCATION_LOCK)?;
            self.require_epoch(&epoch)?;
            return Ok(Some(value));
        }
        let Some(bytes) = self.bytes.get(&name)? else {
            return Ok(None);
        };
        let aad = context.aad(cache_key)?;
        let value = decode_cache_record_value(&bytes, key, &aad)?;
        let _fence = self.lock(super::REVOCATION_LOCK)?;
        self.require_epoch(&epoch)?;
        Ok(Some(value))
    }

    /// Legacy single-record read for restore. The caller holds the session
    /// lock and the family lock.
    pub(super) fn read_legacy_locked(
        &self,
        context: &super::CacheContext,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
    ) -> Result<Option<serde_json::Value>> {
        let Some(bytes) = self.bytes.get(&cache_file_name(owner, cache_key))? else {
            return Ok(None);
        };
        Ok(Some(decode_cache_record_value(
            &bytes,
            key,
            &context.aad(cache_key)?,
        )?))
    }

    /// Publish one logical value as a single record and make it authoritative
    /// over any sectioned layout. Session/record locks, bounded encode, seal,
    /// then the fenced publish (epoch rechecked under `revocation.lock`).
    ///
    /// # Errors
    /// `Invalid` over the record ceiling, `Authentication`/`Cancelled` after
    /// revocation, admission errors, store errors.
    pub fn write_cache(
        &self,
        admission: &dyn CacheAdmission,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
        value: &serde_json::Value,
    ) -> Result<()> {
        let epoch = self.active_epoch()?;
        let _session_guard = self.lock(SESSION_LOCK)?;
        let context = admission.admit(owner)?;
        let name = cache_file_name(owner, cache_key);
        let _cache_guard = self.lock(&format!("{name}.lock"))?;
        let aad = context.aad(cache_key)?;
        let plaintext = self.encode_value(value)?;
        let encoded = encode_cache_record(key, &plaintext, &aad)?;
        publish_record(&self.bytes, &name, &epoch, &encoded, |name, bytes| {
            Ok(self.bytes.put(name, bytes, Durability::Now)?)
        })?;
        self.retire_sections_locked(owner, cache_key)
    }

    /// Bytes plus the record version they were read at. The version is optional
    /// evidence: it is kept only when it is identical before and after the
    /// read, and a failed capture yields `None`, never an error.
    pub(super) fn read_with_version(
        &self,
        name: &str,
    ) -> Result<Option<(Vec<u8>, Option<S::Version>)>> {
        let before = self.bytes.version(name).ok().flatten();
        let Some(bytes) = self.bytes.get(name)? else {
            return Ok(None);
        };
        let after = self.bytes.version(name).ok().flatten();
        let version = match (before, after) {
            (Some(before), Some(after)) if before == after => Some(after),
            _ => None,
        };
        Ok(Some((bytes, version)))
    }

    pub(super) fn remember_durable(&self, name: &str, evidence: DurableCache<S::Version>) {
        self.durable
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .insert(name.to_owned(), evidence);
    }

    /// The exact plaintext is already durable at `name`: same epoch, key/AAD
    /// binding, digest and record version. Fsyncs a loaded record once.
    pub(super) fn reuse_durable(
        &self,
        name: &str,
        key: &[u8; 32],
        epoch: &str,
        aad: &[u8],
        plaintext: &[u8],
    ) -> Result<bool> {
        let binding = cache_publication_mac(key, epoch, aad)?;
        let digest: [u8; 32] = Sha256::digest(plaintext).into();
        let mut caches = self.durable.lock().unwrap_or_else(PoisonError::into_inner);
        let Some(evidence) = caches.get_mut(name) else {
            return Ok(false);
        };
        if evidence.epoch != epoch
            || evidence.plaintext_digest != digest
            || binding.verify_slice(evidence.binding.as_ref()).is_err()
        {
            return Ok(false);
        }
        let Some(version) = self.bytes.version(name)? else {
            return Ok(false);
        };
        if version != evidence.version {
            return Ok(false);
        }
        if !evidence.synced {
            self.bytes.sync(name)?;
            self.bytes.barrier()?;
            evidence.synced = true;
        }
        Ok(true)
    }

    /// Seal and publish one section/index record under the fence and remember
    /// its evidence. `durability` is `AfterBarrier` for section records a later
    /// synced index names, `Now` for the index itself.
    pub(super) fn publish_sealed(
        &self,
        name: &str,
        key: &[u8; 32],
        epoch: &str,
        aad: &[u8],
        plaintext: &[u8],
        durability: Durability,
    ) -> Result<()> {
        self.durable
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .remove(name);
        let encoded = encode_cache_record(key, plaintext, aad)?;
        if encoded.len() > MAX_LOCAL_RECORD_BYTES {
            return Err(Error::Invalid("The local record is too large."));
        }
        let mut version = None;
        publish_record(&self.bytes, name, epoch, &encoded, |name, bytes| {
            self.bytes.put(name, bytes, durability)?;
            // Evidence only: a failed capture just means the next write is not skipped.
            version = self.bytes.version(name).ok().flatten();
            Ok(())
        })?;
        if let Some(version) = version {
            self.remember_durable(
                name,
                DurableCache {
                    epoch: epoch.to_owned(),
                    binding: Zeroizing::new(
                        cache_publication_mac(key, epoch, aad)?
                            .finalize()
                            .into_bytes()
                            .into(),
                    ),
                    plaintext_digest: Sha256::digest(plaintext).into(),
                    version,
                    synced: true,
                },
            );
        }
        Ok(())
    }

    /// Delete `name` when it exists; whether it did.
    pub(super) fn remove_present(&self, name: &str) -> Result<bool> {
        if self.bytes.version(name)?.is_none() {
            return Ok(false);
        }
        self.bytes.delete(name)?;
        Ok(true)
    }
}
