//! The synchronous `ByteStore` trait: named byte records with ordered
//! durability, listing and scope locks. No multi-key transaction exists:
//! callers write section records, call `barrier`, then write the index last.
use super::error::ByteStoreError;

/// How strongly one `put` must be on stable storage when it returns.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Durability {
    /// The record (and its directory entry) is durable on return.
    Now,
    /// The record is durable, but its directory entry only after the next
    /// `barrier`; for records a later, synced commit names.
    AfterBarrier,
}

/// Holds a store lock until dropped. Opaque so every store can use its own
/// mechanism (file lock, in-memory mutex).
pub struct LockGuard {
    _release: Box<dyn Send>,
}

impl LockGuard {
    /// Wrap the value whose `Drop` releases the lock.
    pub fn new(release: impl Send + 'static) -> Self {
        Self {
            _release: Box::new(release),
        }
    }
}

/// Named byte records. Names are single plain components (no `/`, `.`, `..`).
pub trait ByteStore: Send + Sync {
    /// Opaque description of one stored record state; equal values mean the
    /// same file was observed, used to detect replacement between steps.
    type Version: Clone + PartialEq + Send;

    /// Bytes of `name`, or `None` when it does not exist.
    ///
    /// # Errors
    /// `TooLarge` above `MAX_LOCAL_RECORD_BYTES`, `NotPrivate`, `Io`.
    fn get(&self, name: &str) -> Result<Option<Vec<u8>>, ByteStoreError>;
    /// Current version of `name`, or `None` when it does not exist.
    fn version(&self, name: &str) -> Result<Option<Self::Version>, ByteStoreError>;
    /// Atomically replace `name`: a reader sees the old or the new bytes.
    fn put(&self, name: &str, bytes: &[u8], durability: Durability) -> Result<(), ByteStoreError>;
    /// Remove `name`; a missing record is success.
    fn delete(&self, name: &str) -> Result<(), ByteStoreError>;
    /// Names starting with `prefix`, in no particular order.
    fn list(&self, prefix: &str) -> Result<Vec<String>, ByteStoreError>;
    /// Make every `AfterBarrier` put and every delete durable.
    fn barrier(&self) -> Result<(), ByteStoreError>;
    /// Flush the existing record `name` to stable storage.
    fn sync(&self, name: &str) -> Result<(), ByteStoreError>;
    /// Take the exclusive lock of `scope`, waiting for other holders.
    fn lock(&self, scope: &str) -> Result<LockGuard, ByteStoreError>;
}
