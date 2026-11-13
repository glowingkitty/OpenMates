//! Composer draft read on `ViewModelCore`: `draft(chatId:)` returns a chat's
//! saved draft from the core (`openmates_sdk::view_model::draft`), and
//! `DraftViewRecord` mirrors the core `DraftView` for that call and for the
//! `DraftChanged` event. Saves and clears are in `view_chat_actions.rs`.
//! Bindings only marshal. Plan `apple-client-core-migration` A5; spec `client-core`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use openmates_sdk::view_model::{self, DraftView};
use std::sync::Arc;

/// One chat's saved draft, decrypted (core `DraftView`). Plaintext: show it
/// in the composer only; never log or store it (the core caches it encrypted).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct DraftViewRecord {
    /// Chat the draft belongs to.
    pub chat_id: String,
    /// Full draft markdown.
    pub markdown: String,
    /// Decrypted short preview, when the draft carries one.
    pub preview: Option<String>,
    /// Server draft version; a later save or clear has a higher one.
    pub draft_v: u64,
}

impl From<DraftView> for DraftViewRecord {
    fn from(draft: DraftView) -> Self {
        Self {
            chat_id: draft.chat_id,
            markdown: draft.markdown,
            preview: draft.preview,
            draft_v: draft.draft_v,
        }
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// The saved draft of personal chat `chat_id` for its composer (`nil`:
    /// none). Online the core reads the server's current draft, so a draft
    /// typed on another device is restored, and emits `ChatList` when it
    /// differs from the cached one; offline it returns the cached draft.
    /// Runs on the actor, so it waits for a running command.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed or
    /// volatile id (before any network); `Unavailable(team_draft_read_unavailable)`
    /// in a team scope; `Conflict` when the server's draft is older than the
    /// cached one; `Crypto`; `Cancelled`.
    pub async fn draft(
        &self,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<Option<DraftViewRecord>, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let draft = shared
                .signed_in(token, move |host, sink, cancel| {
                    view_model::draft(host, chat_id, sink, cancel)
                })
                .await?;
            Ok(draft.map(DraftViewRecord::from))
        })
        .await
    }
}
