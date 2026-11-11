//! The sectioned cache layout: one index record, one shared record and one
//! record per chat, each an encrypted `CacheRecord`.
//!
//! Part of the shared client core (`local_cache`); moved unchanged from the
//! TUI `storage_sections.rs`, on-disk format byte-compatible (proved by the
//! golden records in `golden/`). Spec: `client-core.cache`.
//! Write order is the commit protocol: section records first (durable after a
//! barrier), then the index last; a reader never follows an index to a section
//! that is not on disk, and a section whose set id no longer matches the index
//! is treated as absent. There is no multi-key transaction.
use super::{
    ByteStore, CacheAdmission, CacheContext, CacheRecord, Durability, MAX_LOCAL_RECORD_BYTES,
    REVOCATION_LOCK, SESSION_LOCK, cache_file_name, cache_record_encoded_len, encode_bounded_json,
    engine::{CacheEngine, DurableCache, cache_publication_mac},
    open,
};
use crate::error::{Error, Result};
use hmac::Mac;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::PoisonError,
};
use zeroize::Zeroizing;

const LAYOUT: &str = "openmates-native-cache-sections-v1";
/// Records may exceed their pre-encoded section by this much framing.
const RECORD_FRAMING_BYTES: usize = 512;

fn index_key(key: &str) -> String {
    format!("{key}#index")
}
fn shared_key(key: &str) -> String {
    format!("{key}#shared")
}
fn chat_key(key: &str, chat: &str) -> String {
    format!("{key}#chat:{chat}")
}
fn freshness_marker_key(key: &str) -> String {
    format!("{key}#list-freshness-revoked")
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct IndexRecord {
    version: u8,
    layout: String,
    shared: Option<String>,
    records: BTreeMap<String, String>,
    snapshot: serde_json::Map<String, serde_json::Value>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SectionRecord {
    version: u8,
    set: String,
    chat: Option<String>,
    section: serde_json::Map<String, serde_json::Value>,
}

/// In-process copy of the committed manifest for one owner/key/epoch.
#[derive(Clone, Default)]
pub(super) struct Manifest {
    epoch: String,
    shared: Option<String>,
    records: BTreeMap<String, String>,
}

/// What an authenticated sync-cache read restored.
pub enum SyncCacheRead {
    /// Only the Chat-list index (sectioned layout); content stays on disk.
    Index(serde_json::Value),
    /// A complete snapshot (legacy single file, or every section assembled).
    Complete(serde_json::Value),
}
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum SyncReadMode {
    Index,
    Complete,
}

/// Bounded, pre-encoded sections. Capacity admission only: no key, epoch,
/// owner or durability authority is consumed until `write_sync_sections`.
pub struct PreparedSections {
    index: Zeroizing<Vec<u8>>,
    index_chats: BTreeSet<String>,
    shared: Option<Zeroizing<Vec<u8>>>,
    chats: Vec<(String, Zeroizing<Vec<u8>>)>,
    /// Chats restored into a partially restored client; None when complete.
    partial: Option<BTreeSet<String>>,
}

fn encode_section(value: &serde_json::Value) -> Result<Zeroizing<Vec<u8>>> {
    let bytes = encode_bounded_json(value)?;
    if cache_record_encoded_len(bytes.len() + RECORD_FRAMING_BYTES)? > MAX_LOCAL_RECORD_BYTES {
        return Err(Error::Invalid("The local record is too large."));
    }
    Ok(bytes)
}
fn section_record(set: &str, chat: Option<&str>, section: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
    let mut bytes = Zeroizing::new(Vec::with_capacity(section.len() + 160));
    bytes.extend_from_slice(b"{\"version\":1,\"set\":");
    bytes.extend_from_slice(&serde_json::to_vec(set)?);
    bytes.extend_from_slice(b",\"chat\":");
    bytes.extend_from_slice(&serde_json::to_vec(&chat)?);
    bytes.extend_from_slice(b",\"section\":");
    bytes.extend_from_slice(section);
    bytes.push(b'}');
    Ok(bytes)
}
fn index_record(manifest: &Manifest, snapshot: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
    let mut bytes = Zeroizing::new(Vec::with_capacity(
        snapshot.len() + 160 + manifest.records.len() * 120,
    ));
    bytes.extend_from_slice(b"{\"version\":1,\"layout\":");
    bytes.extend_from_slice(&serde_json::to_vec(LAYOUT)?);
    bytes.extend_from_slice(b",\"shared\":");
    bytes.extend_from_slice(&serde_json::to_vec(&manifest.shared)?);
    bytes.extend_from_slice(b",\"records\":");
    bytes.extend_from_slice(&serde_json::to_vec(&manifest.records)?);
    bytes.extend_from_slice(b",\"snapshot\":");
    bytes.extend_from_slice(snapshot);
    bytes.push(b'}');
    Ok(bytes)
}
fn valid_set(set: &str) -> bool {
    uuid::Uuid::parse_str(set).is_ok_and(|id| id.hyphenated().to_string() == set)
}

impl<S: ByteStore> CacheEngine<S> {
    /// Pure, bounded preparation (runs before any credential publication).
    pub fn prepare_sync_sections(
        &self,
        snapshot: serde_json::Value,
        partial: Option<Vec<String>>,
    ) -> Result<PreparedSections> {
        let sections = crate::client::snapshot_sections::split(snapshot)?;
        let index_chats = sections
            .index
            .get("chats")
            .and_then(serde_json::Value::as_object)
            .map(|rows| rows.keys().cloned().collect())
            .unwrap_or_default();
        let index = encode_section(&serde_json::Value::Object(sections.index))?;
        let shared_empty = sections.shared.values().all(|value| match value {
            serde_json::Value::Null => true,
            serde_json::Value::Object(rows) => rows.is_empty(),
            serde_json::Value::Array(rows) => rows.is_empty(),
            _ => false,
        });
        let shared = if shared_empty {
            None
        } else {
            Some(encode_section(&serde_json::Value::Object(sections.shared))?)
        };
        let mut chats = Vec::with_capacity(sections.chats.len());
        for (chat, section) in sections.chats {
            chats.push((chat, encode_section(&serde_json::Value::Object(section))?));
        }
        self.count_encoding();
        Ok(PreparedSections {
            index,
            index_chats,
            shared,
            chats,
            partial: partial.map(|loaded| loaded.into_iter().collect()),
        })
    }

    /// Authenticated read of the sync cache. Index mode reads only the index
    /// record of a sectioned layout; a legacy single file is read completely.
    /// A durable freshness revocation removes the receipt before restore.
    pub fn read_sync_cache(
        &self,
        admission: &dyn CacheAdmission,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
        mode: SyncReadMode,
    ) -> Result<Option<SyncCacheRead>> {
        let epoch = self.active_epoch()?;
        let _session_guard = self.lock(SESSION_LOCK)?;
        self.require_epoch(&epoch)?;
        let context = admission.admit(owner)?;
        let _cache_guard = self.lock(&format!("{}.lock", cache_file_name(owner, cache_key)))?;
        let revoked = self
            .bytes
            .get(&cache_file_name(owner, &freshness_marker_key(cache_key)))?
            .is_some();
        let read = match self.read_sections_locked(&context, owner, cache_key, key, &epoch, mode)? {
            Some(read) => Some(read),
            None => self
                .read_legacy_locked(&context, owner, cache_key, key)?
                .map(SyncCacheRead::Complete),
        };
        let _fence = self.lock(REVOCATION_LOCK)?;
        self.require_epoch(&epoch)?;
        Ok(read.map(|read| {
            if !revoked {
                return read;
            }
            let strip = |mut value: serde_json::Value| {
                if let Some(root) = value.as_object_mut() {
                    root.remove(crate::client::snapshot_sections::CHAT_LIST_FRESHNESS_FIELD);
                }
                value
            };
            match read {
                SyncCacheRead::Index(value) => SyncCacheRead::Index(strip(value)),
                SyncCacheRead::Complete(value) => SyncCacheRead::Complete(strip(value)),
            }
        }))
    }

    /// One Chat's content section from the committed sectioned layout, after
    /// `read_sync_cache` loaded its manifest. Absent/stale records are None.
    pub fn read_sync_chat(
        &self,
        admission: &dyn CacheAdmission,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
        chat: &str,
    ) -> Result<Option<serde_json::Value>> {
        let epoch = self.active_epoch()?;
        let _session_guard = self.lock(SESSION_LOCK)?;
        let context = admission.admit(owner)?;
        let _cache_guard = self.lock(&format!("{}.lock", cache_file_name(owner, cache_key)))?;
        let manifest = self.current_manifest(owner, cache_key, &epoch)?;
        let section = match manifest.records.get(chat) {
            Some(set) => {
                self.read_section_locked(&context, owner, cache_key, key, &epoch, Some(chat), set)?
            }
            None => None,
        };
        let _fence = self.lock(REVOCATION_LOCK)?;
        self.require_epoch(&epoch)?;
        Ok(section.map(serde_json::Value::Object))
    }

    /// Every committed section not yet restored: `{"shared":..,"chats":{..}}`.
    pub fn read_sync_remainder(
        &self,
        admission: &dyn CacheAdmission,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
        loaded: &[String],
    ) -> Result<serde_json::Value> {
        let epoch = self.active_epoch()?;
        let _session_guard = self.lock(SESSION_LOCK)?;
        let context = admission.admit(owner)?;
        let _cache_guard = self.lock(&format!("{}.lock", cache_file_name(owner, cache_key)))?;
        let manifest = self.current_manifest(owner, cache_key, &epoch)?;
        let shared = match &manifest.shared {
            Some(set) => {
                self.read_section_locked(&context, owner, cache_key, key, &epoch, None, set)?
            }
            None => None,
        };
        let mut chats = serde_json::Map::new();
        for (chat, set) in &manifest.records {
            if loaded.contains(chat) {
                continue;
            }
            if let Some(section) =
                self.read_section_locked(&context, owner, cache_key, key, &epoch, Some(chat), set)?
            {
                chats.insert(chat.clone(), serde_json::Value::Object(section));
            }
        }
        let _fence = self.lock(REVOCATION_LOCK)?;
        self.require_epoch(&epoch)?;
        Ok(serde_json::json!({"shared": shared, "chats": chats}))
    }

    /// Durably revoke the list-freshness receipt without reading or rewriting
    /// the cache. The next authenticated restore drops the receipt; the next
    /// successful sectioned publication (which never contains a revoked
    /// receipt) removes the marker. Idempotent and cheap when already present.
    pub fn revoke_sync_freshness(
        &self,
        admission: &dyn CacheAdmission,
        owner: &str,
        cache_key: &str,
    ) -> Result<()> {
        let epoch = self.active_epoch()?;
        let _session_guard = self.lock(SESSION_LOCK)?;
        admission.admit(owner)?;
        let _cache_guard = self.lock(&format!("{}.lock", cache_file_name(owner, cache_key)))?;
        let marker = cache_file_name(owner, &freshness_marker_key(cache_key));
        if self.bytes.get(&marker)?.is_some() {
            return Ok(());
        }
        let _fence = self.lock(REVOCATION_LOCK)?;
        self.require_epoch(&epoch)?;
        self.bytes
            .put(&marker, b"{\"version\":1}", Durability::Now)?;
        Ok(())
    }

    /// Change-only publication of prepared sections. Unchanged records (same
    /// epoch, key/AAD binding, plaintext digest and exact current file) are
    /// not rewritten; content of Chats a partial client never restored is
    /// retained. Returns whether anything was written or removed.
    pub fn write_sync_sections(
        &self,
        admission: &dyn CacheAdmission,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
        prepared: PreparedSections,
    ) -> Result<bool> {
        let epoch = self.active_epoch()?;
        let _session_guard = self.lock(SESSION_LOCK)?;
        let context = admission.admit(owner)?;
        let legacy = cache_file_name(owner, cache_key);
        let _cache_guard = self.lock(&format!("{legacy}.lock"))?;
        let previous = match self.loaded_manifest(owner, cache_key, &epoch) {
            Some(manifest) => manifest,
            // Never read in this process: learn the committed record names so
            // a complete replacement can remove superseded records.
            None => match self.read_index_locked(&context, owner, cache_key, key, &epoch)? {
                Some((manifest, _)) => manifest,
                None => Manifest {
                    epoch: epoch.clone(),
                    ..Default::default()
                },
            },
        };
        let mut changed = false;
        let mut next = Manifest {
            epoch: epoch.clone(),
            ..Default::default()
        };
        for (chat, section) in &prepared.chats {
            let set = self.publish_section(
                &context,
                owner,
                cache_key,
                key,
                &epoch,
                Some(chat),
                section,
                &mut changed,
            )?;
            next.records.insert(chat.clone(), set);
        }
        if let Some(loaded) = &prepared.partial {
            for (chat, set) in &previous.records {
                if !next.records.contains_key(chat)
                    && !loaded.contains(chat)
                    && prepared.index_chats.contains(chat)
                {
                    next.records.insert(chat.clone(), set.clone());
                }
            }
        }
        next.shared = match (&prepared.shared, &prepared.partial) {
            (Some(section), _) => Some(self.publish_section(
                &context,
                owner,
                cache_key,
                key,
                &epoch,
                None,
                section,
                &mut changed,
            )?),
            (None, Some(_)) => previous.shared.clone(),
            (None, None) => None,
        };
        if changed {
            // Every renamed record must be durable before the index names it.
            self.bytes.barrier()?;
        }
        let index_name = cache_file_name(owner, &index_key(cache_key));
        let plaintext = index_record(&next, &prepared.index)?;
        let aad = context.aad(&index_key(cache_key))?;
        if !self.reuse_durable(&index_name, key, &epoch, &aad, &plaintext)? {
            self.publish_sealed(&index_name, key, &epoch, &aad, &plaintext, Durability::Now)?;
            changed = true;
        }
        self.remember_manifest(owner, cache_key, next.clone());
        // Superseded files only after the commit; failures leave harmless orphans.
        let mut removed = false;
        for chat in previous
            .records
            .keys()
            .filter(|chat| !next.records.contains_key(*chat))
        {
            removed |= self.remove_present(&cache_file_name(owner, &chat_key(cache_key, chat)))?;
        }
        if previous.shared.is_some() && next.shared.is_none() {
            removed |= self.remove_present(&cache_file_name(owner, &shared_key(cache_key)))?;
        }
        removed |= self.remove_present(&legacy)?;
        removed |=
            self.remove_present(&cache_file_name(owner, &freshness_marker_key(cache_key)))?;
        if removed {
            self.bytes.barrier()?;
        }
        let _fence = self.lock(REVOCATION_LOCK)?;
        self.require_epoch(&epoch)?;
        Ok(changed || removed)
    }

    /// After a legacy single-file publication: make it authoritative again.
    pub(super) fn retire_sections_locked(&self, owner: &str, cache_key: &str) -> Result<()> {
        if self.remove_present(&cache_file_name(owner, &index_key(cache_key)))? {
            self.bytes.barrier()?;
        }
        if let Ok(mut manifests) = self.manifests.lock() {
            manifests.remove(&cache_file_name(owner, cache_key));
        }
        Ok(())
    }

    /// Caller holds session.lock and the family lock.
    pub(super) fn read_sections_locked(
        &self,
        context: &CacheContext,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
        epoch: &str,
        mode: SyncReadMode,
    ) -> Result<Option<SyncCacheRead>> {
        let Some((manifest, snapshot)) =
            self.read_index_locked(context, owner, cache_key, key, epoch)?
        else {
            return Ok(None);
        };
        self.remember_manifest(owner, cache_key, manifest.clone());
        if mode == SyncReadMode::Index {
            return Ok(Some(SyncCacheRead::Index(serde_json::Value::Object(
                snapshot,
            ))));
        }
        let shared = match &manifest.shared {
            Some(set) => {
                self.read_section_locked(context, owner, cache_key, key, epoch, None, set)?
            }
            None => None,
        };
        let mut chats = Vec::with_capacity(manifest.records.len());
        for (chat, set) in &manifest.records {
            if let Some(section) =
                self.read_section_locked(context, owner, cache_key, key, epoch, Some(chat), set)?
            {
                chats.push((chat.clone(), section));
            }
        }
        Ok(Some(SyncCacheRead::Complete(
            crate::client::snapshot_sections::assemble(snapshot, shared, chats)?,
        )))
    }

    fn read_index_locked(
        &self,
        context: &CacheContext,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
        epoch: &str,
    ) -> Result<Option<(Manifest, serde_json::Map<String, serde_json::Value>)>> {
        let name = cache_file_name(owner, &index_key(cache_key));
        let aad = context.aad(&index_key(cache_key))?;
        let Some(plaintext) = self.read_record(&name, key, epoch, &aad)? else {
            return Ok(None);
        };
        let record: IndexRecord = serde_json::from_slice(&plaintext)?;
        if record.version != 1
            || record.layout != LAYOUT
            || !record
                .records
                .values()
                .chain(record.shared.iter())
                .all(|set| valid_set(set))
        {
            return Err(Error::Protocol);
        }
        let manifest = Manifest {
            epoch: epoch.to_owned(),
            shared: record.shared,
            records: record.records,
        };
        Ok(Some((manifest, record.snapshot)))
    }

    #[allow(clippy::too_many_arguments)]
    fn read_section_locked(
        &self,
        context: &CacheContext,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
        epoch: &str,
        chat: Option<&str>,
        set: &str,
    ) -> Result<Option<serde_json::Map<String, serde_json::Value>>> {
        let record_key = match chat {
            Some(chat) => chat_key(cache_key, chat),
            None => shared_key(cache_key),
        };
        let name = cache_file_name(owner, &record_key);
        let aad = context.aad(&record_key)?;
        let Some(plaintext) = self.read_record(&name, key, epoch, &aad)? else {
            return Ok(None);
        };
        let record: SectionRecord = serde_json::from_slice(&plaintext)?;
        if record.version != 1 || record.chat.as_deref() != chat {
            return Err(Error::Protocol);
        }
        // A record from an uncommitted publication is absent content.
        if record.set != set {
            self.durable
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .remove(&name);
            return Ok(None);
        }
        Ok(Some(record.section))
    }

    /// Decrypt one record and remember its durable evidence.
    fn read_record(
        &self,
        name: &str,
        key: &[u8; 32],
        epoch: &str,
        aad: &[u8],
    ) -> Result<Option<Zeroizing<Vec<u8>>>> {
        let Some((bytes, version)) = self.read_with_version(name)? else {
            return Ok(None);
        };
        let record: CacheRecord = serde_json::from_slice(&bytes)?;
        if record.version != 1 {
            return Err(Error::Protocol);
        }
        let plaintext = open(key, &record.ciphertext, aad)?;
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
                    plaintext_digest: Sha256::digest(plaintext.as_slice()).into(),
                    version,
                    synced: false,
                },
            );
        }
        Ok(Some(plaintext))
    }

    /// Reuse (or write) one section record; returns its committed set ID.
    #[allow(clippy::too_many_arguments)]
    fn publish_section(
        &self,
        context: &CacheContext,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
        epoch: &str,
        chat: Option<&str>,
        section: &[u8],
        changed: &mut bool,
    ) -> Result<String> {
        let record_key = match chat {
            Some(chat) => chat_key(cache_key, chat),
            None => shared_key(cache_key),
        };
        let name = cache_file_name(owner, &record_key);
        let aad = context.aad(&record_key)?;
        if let Some(set) = self.remembered_set(owner, cache_key, chat) {
            let plaintext = section_record(&set, chat, section)?;
            if self.reuse_durable(&name, key, epoch, &aad, &plaintext)? {
                return Ok(set);
            }
        }
        let set = uuid::Uuid::new_v4().to_string();
        let plaintext = section_record(&set, chat, section)?;
        self.publish_sealed(
            &name,
            key,
            epoch,
            &aad,
            &plaintext,
            Durability::AfterBarrier,
        )?;
        *changed = true;
        Ok(set)
    }

    fn remembered_set(&self, owner: &str, cache_key: &str, chat: Option<&str>) -> Option<String> {
        let manifests = self.manifests.lock().ok()?;
        let manifest = manifests.get(&cache_file_name(owner, cache_key))?;
        match chat {
            Some(chat) => manifest.records.get(chat).cloned(),
            None => manifest.shared.clone(),
        }
    }

    fn remember_manifest(&self, owner: &str, cache_key: &str, manifest: Manifest) {
        if let Ok(mut manifests) = self.manifests.lock() {
            manifests.insert(cache_file_name(owner, cache_key), manifest);
        }
    }
    fn loaded_manifest(&self, owner: &str, cache_key: &str, epoch: &str) -> Option<Manifest> {
        self.manifests
            .lock()
            .ok()?
            .get(&cache_file_name(owner, cache_key))
            .filter(|manifest| manifest.epoch == epoch)
            .cloned()
    }
    fn current_manifest(&self, owner: &str, cache_key: &str, epoch: &str) -> Result<Manifest> {
        self.loaded_manifest(owner, cache_key, epoch)
            .ok_or(Error::Cancelled)
    }
}
