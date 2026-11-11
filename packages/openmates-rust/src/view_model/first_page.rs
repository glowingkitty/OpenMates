//! The core's cold-history first-page sink for `OpenChat`: admits the
//! prospective checkpoint against the cache's capacity, persists the exact
//! candidate through the `ShellSession` (durable credentials and cache before
//! the receipt), commits it and emits the page as a `ChatWindow` event.
//! Moved from the TUI `runtime.rs` (`NativeChatFirstPageSink`); spec
//! `a2-design.md` (View model, lane L7) and `architecture.sync` (bounded open).
use super::{
    ChatWindowRecord, ChatWindowSource, RequestId, ViewEvent, ViewSink, chat_window_from_cached,
};
use crate::{
    client::{ChatFirstPageCandidate, ChatFirstPageSink, Client},
    error::{Error, Result},
    local_cache::{ByteStore, GenerationGuard},
    shell_session::{CredentialPersistence, ShellSession},
};
use std::{future::Future, pin::Pin};
use zeroize::Zeroize;

/// First-page sink of one open request. A moved queue generation (logout,
/// revocation) refuses both the capacity decision and the publication.
pub(super) struct FirstPageEmitter<'a, S: ByteStore + 'static, K: ViewSink> {
    pub(super) session: &'a ShellSession<S>,
    pub(super) credentials: &'a dyn CredentialPersistence,
    pub(super) generation: GenerationGuard,
    pub(super) sink: &'a K,
    pub(super) request: RequestId,
    /// The record emitted, so the window keeps it when the strict read fails.
    pub(super) published: Option<ChatWindowRecord>,
}

fn current(generation: &GenerationGuard) -> Result<()> {
    if generation.is_current() {
        Ok(())
    } else {
        Err(Error::Cancelled)
    }
}

impl<S: ByteStore + 'static, K: ViewSink> ChatFirstPageSink for FirstPageEmitter<'_, S, K> {
    fn admit_checkpoint<'b>(
        &'b mut self,
        _client: &'b Client,
        checkpoint_json_bytes: usize,
    ) -> Pin<Box<dyn Future<Output = Result<bool>> + Send + 'b>> {
        Box::pin(async move {
            current(&self.generation)?;
            let accepted = self
                .session
                .cache()
                .admits_checkpoint(checkpoint_json_bytes)?;
            current(&self.generation)?;
            Ok(accepted)
        })
    }

    fn first_page<'b>(
        &'b mut self,
        client: &'b mut Client,
        candidate: ChatFirstPageCandidate,
    ) -> Pin<Box<dyn Future<Output = Result<()>> + Send + 'b>> {
        Box::pin(async move {
            current(&self.generation)?;
            // The receipt exists only after the exact ciphertext and the
            // credentials are durable and acknowledged (`persist_for`).
            let receipt = self
                .session
                .persist_for(client, self.credentials, &candidate)
                .await?;
            current(&self.generation)?;
            let mut window = client
                .commit_chat_first_page(candidate, receipt)?
                .into_window()?;
            let record = chat_window_from_cached(&window, ChatWindowSource::FirstPage);
            window.zeroize();
            let mut record = record.map_err(|_| Error::Protocol)?;
            super::enrich::enrich_window(client, &mut record)?;
            self.sink
                .emit(ViewEvent::ChatWindow {
                    request: self.request,
                    window: record.clone(),
                })
                .await?;
            self.published = Some(record);
            Ok(())
        })
    }
}
