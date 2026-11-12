//! Send and cancel on `ViewModelCore`: the core view-model send
//! (`openmates_sdk::view_model::begin_send`, the encrypted turn admitted on
//! the actor, its reply streamed beside it by `view_send_stream.rs`, and the
//! `SendState` end states) and its priority-lane cancel
//! (`SendCancelHandle`), exported to Swift. Bindings only marshal. Plan
//! `apple-client-core-migration` (A2 L9 for Apple, A5); spec `client-core`.
use crate::core::CoreCancellation;
use crate::view_core::{AppleHost, Shared, ViewModelCore, lock};
use crate::{CoreError, view_records::ChatWindowViewRecord};
use openmates_sdk::client::server_region::ServerRegionPreference;
use openmates_sdk::view_model::{RequestId, SendCancelHandle, SendTurnOptions, ViewHost};
use std::sync::Arc;
use std::sync::atomic::Ordering;

/// The device-local send settings Swift set (assistant Memory writes, server
/// region), read once per send and applied on the actor right before the
/// turn. Edits and retries (`view_chat_actions.rs`) send the same way.
#[derive(Clone, Copy)]
pub(crate) struct SendSettings {
    memory_writes: bool,
    region: ServerRegionPreference,
}

impl SendSettings {
    /// The settings current in `shared`.
    pub(crate) fn read(shared: &Shared) -> Self {
        Self {
            memory_writes: shared.memory_write_jobs.load(Ordering::SeqCst),
            region: crate::view_region::preference_of(
                shared.server_region_global.load(Ordering::SeqCst),
            ),
        }
    }

    /// Apply to the actor's core before a send.
    pub(crate) fn apply(self, host: &mut AppleHost) {
        host.core_mut().set_memory_write_jobs(self.memory_writes);
        host.core_mut().set_server_region(self.region);
    }
}

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
    /// `CoreError.Cancelled`. Only the admission runs on the actor; while the
    /// reply streams, other commands are served: a second send into the same
    /// chat comes back queued, a send into another chat streams alongside,
    /// and `stopReply`, `cancelSend` and `logout` end it.
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
            let settings = SendSettings::read(&shared);
            let receipt = shared
                .stream_send(
                    token,
                    settings,
                    RequestId(request),
                    chat_id,
                    text,
                    SendTurnOptions::default(),
                )
                .await?;
            Ok(ChatWindowViewRecord::from(receipt.window))
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
