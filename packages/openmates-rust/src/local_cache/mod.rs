//! Byte layer of the encrypted local cache owned by the shared core.
//!
//! `ByteStore` is the synchronous seam under the cache codec; `FileByteStore`
//! is the native directory implementation moved out of the TUI `storage.rs`
//! (atomic writes, fsync ordering, symlink-safe walk, owner/mode checks, file
//! locks). On-disk names and permissions are unchanged. Plan:
//! `docs/plans/apple-client-core-migration/a2-design.md` (lane L1); spec
//! `client-core.cache.core-owned`.
mod byte_store;
mod error;
#[cfg(unix)]
mod file_store;
#[cfg(all(test, unix))]
mod file_store_tests;

pub use byte_store::{ByteStore, Durability, LockGuard};
pub use error::ByteStoreError;
#[cfg(unix)]
pub use file_store::{FileByteStore, FileIdentity};

/// Largest record a store reads back. Writers must refuse anything larger so a
/// record this core wrote can always be read on restart.
pub const MAX_LOCAL_RECORD_BYTES: usize = 32 * 1024 * 1024;
