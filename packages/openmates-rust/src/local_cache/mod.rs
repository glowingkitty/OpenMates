//! Byte layer of the encrypted local cache owned by the shared core.
//!
//! `ByteStore` is the synchronous seam under the cache codec; `FileByteStore`
//! is the native directory implementation moved out of the TUI `storage.rs`
//! (atomic writes, fsync ordering, symlink-safe walk, owner/mode checks, file
//! locks). On-disk names and permissions are unchanged. Plan:
//! `docs/plans/apple-client-core-migration/a2-design.md` (lane L1); spec
//! `client-core.cache.core-owned`.
//! Core-owned encrypted local cache: the byte store, its native file
//! implementation, the cache record codec and the revocation fence. Shared by
//! the TUI, web and Apple shells; spec `client-core.cache`.
mod byte_store;
#[cfg(not(target_arch = "wasm32"))]
mod cache_store;
#[cfg(all(test, not(target_arch = "wasm32")))]
mod cache_store_tests;
mod context;
mod engine;
mod error;
mod fence;
mod record;
mod sections;
#[cfg(test)]
mod sections_tests;
#[cfg(test)]
mod record_tests;
#[cfg(unix)]
mod file_store;
#[cfg(all(test, unix))]
mod file_store_tests;

pub use context::{CacheAdmission, CacheContext, FixedContext, NoScope, OperationScope, SESSION_LOCK};
#[cfg(not(target_arch = "wasm32"))]
pub use cache_store::{CacheKey, CacheStore, GenerationGuard, OrderedBlocking};
pub use engine::CacheEngine;
pub use sections::{PreparedSections, SyncCacheRead, SyncReadMode};
pub use byte_store::{ByteStore, Durability, LockGuard};
pub use error::ByteStoreError;
pub use fence::{
    PendingCleanup, REVOCATION_FILE, REVOCATION_LOCK, RevocationFence, StorageMode, publish_record,
    read_record,
};
pub use record::{
    CacheRecord, cache_aad, cache_file_name, cache_record_encoded_len, decode_cache_record,
    decode_cache_record_value, encode_bounded_json, encode_cache_record, open, owner_hash, seal,
    sha256_hex,
};
#[cfg(unix)]
pub use file_store::{FileByteStore, FileIdentity};

/// Largest record a store reads back. Writers must refuse anything larger so a
/// record this core wrote can always be read on restart.
pub const MAX_LOCAL_RECORD_BYTES: usize = 32 * 1024 * 1024;
