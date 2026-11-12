//! Send and cancel on `ViewModelCore`: the core view-model send
//! (`openmates_sdk::view_model::send`, the encrypted turn, its stream relay
//! and the `SendState` end states) and its priority-lane cancel
//! (`SendCancelHandle`), exported to Swift. Bindings only marshal. Plan
//! `apple-client-core-migration` (A2 L9 for Apple, A5); spec `client-core`.
use crate::core::CoreCancellation;
use crate::view_core::{ViewModelCore, lock};
use crate::{CoreError, view_records::ChatWindowViewRecord};
use openmates_sdk::view_model::{self, RequestId, SendCancelHandle, ViewHost};
use std::sync::Arc;
use std::sync::atomic::Ordering;

#[uniffi::export]
impl ViewModelCore {
    /// Send `text` as the turn of Swift's `request` id into `chat_id`
    /// (`nil`: a new chat) and return the sent chat's window (`Canonical`).
    /// Events, all carrying `request`: the user message with send state
    /// `Sending` in the open window before any network request, then per
    /// stream update a `Stream` event plus the changed window (`Live`), then
    /// the sent window (`Canonical`) and the chat list. A turn into a chat
    /// that is not open emits `Stream` events and the list only. A failed
    /// send keeps the user message with `Failed`; a cancel (through
    /// `cancellation` or `cancelSend`) publishes `Cancelled` and ends with
    /// `CoreError.Cancelled`. Runs on the actor, so other commands wait for it;
    /// `logout` cancels it.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for empty text, an unknown
    /// `@mention` (nothing is sent) or a refused turn; network, send and
    /// persistence errors; `Cancelled` when cancelled.
    pub async fn send(
        &self,
        request: u64,
        chat_id: Option<String>,
        text: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<ChatWindowViewRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            let memory_writes = shared.memory_write_jobs.load(Ordering::SeqCst);
            let region = crate::view_region::preference_of(
                shared.server_region_global.load(Ordering::SeqCst),
            );
            let record = shared
                .signed_in(token, move |host, sink, cancel| {
                    host.core_mut().set_memory_write_jobs(memory_writes);
                    host.core_mut().set_server_region(region);
                    view_model::send(host, RequestId(request), chat_id, text, sink, cancel)
                })
                .await?;
            Ok(ChatWindowViewRecord::from(record))
        })
        .await
    }

    /// Cancel the running send without waiting for the actor; returns
    /// whether one was running. The send then persists what was admitted,
    /// publishes its `Cancelled` state and throws `CoreError.Cancelled`.
    /// Callable from any thread; never blocks on the network.
    pub fn cancel_send(&self) -> bool {
        lock(&self.shared.send_cancel)
            .as_ref()
            .is_some_and(SendCancelHandle::cancel)
    }
}
