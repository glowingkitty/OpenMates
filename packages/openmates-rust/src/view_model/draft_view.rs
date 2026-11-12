//! The composer draft value the view model hands a shell: the decrypted draft
//! of one Personal chat, as returned by the `draft` call (`draft_flows.rs`)
//! and carried by `ViewEvent::DraftChanged`. Compiles for native and wasm
//! because `ViewEvent` does. Spec `client-core` (drafts capability).
use crate::sdk_drafts::DraftRecord;

/// One chat's saved draft, decrypted. Plaintext: shells show it in the
/// composer and never log or persist it themselves (the core caches only the
/// ciphertext).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DraftView {
    /// Chat the draft belongs to.
    pub chat_id: String,
    /// Full draft markdown.
    pub markdown: String,
    /// Decrypted short preview; `None` when the draft carries none or its
    /// preview did not decrypt.
    pub preview: Option<String>,
    /// Server draft version (`draft_v`); a later save or clear has a higher one.
    pub draft_v: u64,
}

impl From<DraftRecord> for DraftView {
    fn from(record: DraftRecord) -> Self {
        Self {
            chat_id: record.encrypted.chat_id,
            markdown: record.markdown,
            preview: record.preview,
            draft_v: record.encrypted.draft_v,
        }
    }
}
