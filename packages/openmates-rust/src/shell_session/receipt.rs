//! Durable-commit candidates: SDK reads whose publication requires an exact
//! durable cache+credential save first. [`super::ShellSession::persist_for`]
//! is the only native path that mints their `ChatRefreshDurableReceipt`.
//! Spec: `client-core.cache` (shells stop vouching for durability).
use crate::{
    client::{
        CacheSettlementCandidate, CanonicalChatCandidate, ChatFirstPageCandidate, ChatRefresh,
    },
    error::Result,
};

/// A candidate the SDK commits only against a durable receipt: the exact
/// ciphertext digest and credential revision the receipt must name.
pub trait DurableCandidate {
    /// SHA-256 of the candidate's ciphertext; validates the candidate's
    /// fences first.
    ///
    /// # Errors
    /// `Cancelled` when the candidate is stale or cancelled.
    fn ciphertext_sha256(&self) -> Result<String>;

    /// Credential revision the candidate was read at.
    fn credential_revision(&self) -> u64;
}

impl DurableCandidate for ChatRefresh {
    fn ciphertext_sha256(&self) -> Result<String> {
        ChatRefresh::ciphertext_sha256(self)
    }
    fn credential_revision(&self) -> u64 {
        ChatRefresh::credential_revision(self)
    }
}

impl DurableCandidate for CanonicalChatCandidate {
    fn ciphertext_sha256(&self) -> Result<String> {
        CanonicalChatCandidate::ciphertext_sha256(self)
    }
    fn credential_revision(&self) -> u64 {
        CanonicalChatCandidate::credential_revision(self)
    }
}

impl DurableCandidate for CacheSettlementCandidate {
    fn ciphertext_sha256(&self) -> Result<String> {
        CacheSettlementCandidate::ciphertext_sha256(self)
    }
    fn credential_revision(&self) -> u64 {
        CacheSettlementCandidate::credential_revision(self)
    }
}

impl DurableCandidate for ChatFirstPageCandidate {
    fn ciphertext_sha256(&self) -> Result<String> {
        ChatFirstPageCandidate::ciphertext_sha256(self)
    }
    fn credential_revision(&self) -> u64 {
        ChatFirstPageCandidate::credential_revision(self)
    }
}
