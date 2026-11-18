//! Headless streamed embed write engine shared by web (WASM), CLI and Apple.
//!
//! Ports the client-side write logic of the web `chatSyncServiceHandlersAI`
//! (finalized `send_embed_data` and processing->finished `embed_update`),
//! `streamedEmbedRevisionHistory`, `embedDiffStore` restore/snapshot writes,
//! `canonicalEmbedWriteCoordinator`, `embedStateMachine` and `embedRefIndex`.
//! Every ciphertext uses the exact deployed MetadataEncryptor layout
//! (base64(IV || AES-256-GCM ciphertext || tag)); `ts_embed_writes.json` holds
//! TypeScript-generated vectors proving byte-identical output for a fixed IV.
//!
//! IO stays explicit: IndexedDB rows, WebSocket sends, HTTP canonical reads and
//! the embed type registry projection are performed by the platform adapter.
//! Raw chat/embed keys never leave Rust: [`EmbedWriteSession`] adopts them only
//! from master-wrapped ciphertext and returns ciphertext plus row shapes.
#[path = "embed_write_coordinator.rs"]
pub mod coordinator;
#[path = "embed_write_history.rs"]
pub mod history;
#[path = "embed_write_keys.rs"]
pub mod keys;
/// Message-scoped image versions and version-K content (`pinned_embeds`).
#[path = "embed_pinned_version.rs"]
pub mod pinned;
#[path = "embed_write_payload.rs"]
pub mod payload;
#[path = "embed_write_read.rs"]
pub mod read;
#[path = "embed_write_ref_index.rs"]
pub mod ref_index;
/// Child revision persistence (version N+1 of a generated image child).
#[path = "embed_child_revision.rs"]
pub mod revision;
/// Recovery receipts of a child revision's sealed `(embed, N+1)` / `(diff, N+1)` outputs.
#[path = "embed_child_revision_recovery.rs"]
pub mod revision_recovery;
#[path = "embed_write_session.rs"]
pub mod session;
#[path = "embed_write_status.rs"]
pub mod status;

pub use coordinator::{EmbedWriteCoordinator, EmbedWriteLease};
pub use history::{
    CanonicalRead, EncryptedDiffRow, RestorePlan, RestoreRequest, StreamedHistoryRow, build_unified_diff,
};
pub use keys::{NonceSource, OsNonces};
pub use payload::{PreparedEmbedWrite, ProcessingEmbedUpdate, StreamedEmbedData};
pub use pinned::{MessageImageVersion, MessageParents, PinnedEmbed};
pub use ref_index::{EmbedRefIndex, EmbedRefIndexEntry, ResolvedEmbedRef};
pub use revision::{ChildRevision, ChildRevisionStep, ChildRevisionWrites, RevisionRowRole};
pub use revision_recovery::{ReceiptSource, RevisionRecoveryReceipt};
pub use session::{AdoptedKey, EmbedWriteSession, KeyAdoption, KeyLookup, PlannedEmbedWrite};
pub use status::EmbedStatus;

/// TS `normalizeToUnixSeconds`: non-number/non-finite/<=0 -> fallback,
/// >= 1e10 is milliseconds (floored /1000), otherwise floored seconds.
pub fn normalize_to_unix_seconds(value: Option<&serde_json::Value>, fallback: i64) -> i64 {
    match value.and_then(serde_json::Value::as_f64) {
        Some(v) if v.is_finite() && v > 0.0 => {
            if v >= 10_000_000_000.0 {
                (v / 1000.0).floor() as i64
            } else {
                v.floor() as i64
            }
        }
        _ => fallback,
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "embed_write_tests.rs"]
mod tests;
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "embed_write_resolve_tests.rs"]
mod resolve_tests;
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "embed_child_revision_tests.rs"]
mod child_revision_tests;
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "embed_child_revision_recovery_tests.rs"]
mod child_revision_recovery_tests;
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "embed_write_local_only_tests.rs"]
mod local_only_tests;
