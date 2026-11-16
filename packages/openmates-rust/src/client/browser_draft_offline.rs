//! Offline (local-read-only) browser draft publication state. Shared core, browser
//! binding: a local profile may run only the local draft plans (capture, encrypted
//! chats_db row, durable intent) on its master key. Publication stays refused until
//! the same principal is admitted with server validation; the durable intent is then
//! replayed. Implements `drafts.persistence.local-first-encrypted` (specifications/architecture/drafts).
//! Offline (local-read-only) browser draft saves in the shared core, used by the
//! web `drafts` Worker unit. A local profile may persist the encrypted draft row
//! and its queued encrypted intent, but never publishes: `remote_payload`,
//! transport acknowledgement and snapshots keep refusing local profiles.
//! Implements `architecture.drafts` example `offline-save-queues-encrypted-update`.
use super::*;
use super::browser_draft::BrowserDraftWrite;
use zeroize::Zeroizing;

impl BrowserDraftWrite {
    /// Ciphertext `update_draft` payload when this client has server authority, or
    /// `None` for a local-read-only profile: the write is saved locally and its
    /// encrypted intent stays queued (no plaintext), and nothing is published.
    ///
    /// # Errors
    /// Fails like `local_result` when the admission or operation scope is stale.
    pub fn remote_payload_if_admitted(&self, c: &Client) -> Result<Option<Zeroizing<String>>> {
        self.check(c)?;
        if c.is_local_browser_profile() {
            return Ok(None);
        }
        self.remote_payload(c).map(Some)
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "browser_draft_offline_tests.rs"]
mod tests;
