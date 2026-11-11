//! Who a cache belongs to: the session context the records are bound to, the
//! admission hook a shell implements, and the optional operation scope.
//!
//! Part of the shared client core (`local_cache`); replaces the TUI's session
//! `Envelope` adapter. Spec: `client-core.cache`. The core never reads a
//! credential store: the shell answers "is this owner admitted right now" and
//! hands back the owner hash, context hash and pairing expiry that enter every
//! record's AAD.
use super::{LockGuard, owner_hash};
use crate::error::{Error, Result};

/// Lock scope that serializes cache operations against session changes. The
/// shell takes the same scope around its credential writes.
pub const SESSION_LOCK: &str = "session.lock";

/// The session identity every cache record is bound to (through its AAD).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CacheContext {
    /// Hash of the cache owner (`owner_hash(hashed_email)`).
    pub owner_hash: String,
    /// Hash of the admitted session; a record opens only for this context.
    pub context: String,
    /// Pairing expiry in milliseconds since the epoch, if the session has one.
    pub expires_at: Option<u64>,
}

impl CacheContext {
    /// AAD of the record stored under the logical `cache_key`.
    ///
    /// # Errors
    /// JSON serialization errors (none are expected for these inputs).
    pub fn aad(&self, cache_key: &str) -> Result<Vec<u8>> {
        super::cache_aad(&self.owner_hash, &self.context, self.expires_at, cache_key)
    }
}

/// Decides, per operation, whether `owner` may use the cache and which
/// context its records are bound to.
///
/// `admit` runs while the operation holds [`SESSION_LOCK`], so a shell can
/// read its own session record without racing a credential write. It returns
/// `Authentication` when no session is admitted, `Forbidden` for another
/// owner and `Expired` for a lapsed pairing.
pub trait CacheAdmission: Send + Sync {
    /// The context for `owner`, or why the cache must not be used.
    ///
    /// # Errors
    /// `Authentication`, `Forbidden`, `Expired` or a shell storage error.
    fn admit(&self, owner: &str) -> Result<CacheContext>;
}

/// Admission for shells that bind one context for the lifetime of the store
/// (no session file to consult), such as the Apple app.
pub struct FixedContext(pub CacheContext);

impl CacheAdmission for FixedContext {
    fn admit(&self, owner: &str) -> Result<CacheContext> {
        if owner_hash(owner) != self.0.owner_hash {
            return Err(Error::Forbidden);
        }
        Ok(self.0.clone())
    }
}

/// Optional exclusion a shell wants around every cache operation (the TUI's
/// per-operation runtime lock). The returned guard lives for the operation.
pub trait OperationScope: Send + Sync {
    /// Enter the scope; `None` when nothing needs holding.
    ///
    /// # Errors
    /// Whatever the shell's lock reports (for example a timeout).
    fn enter(&self) -> Result<Option<LockGuard>>;
}

/// The scope that holds nothing.
pub struct NoScope;

impl OperationScope for NoScope {
    fn enter(&self) -> Result<Option<LockGuard>> {
        Ok(None)
    }
}
