//! Socket passthrough on `ViewModelCore` for Swift features that are not
//! migrated yet: opt in to receive the monitor socket's frames the core does
//! not own (`ViewEvent.unownedSocketFrame`) and send raw frames of such
//! features through the core's one socket. Temporary strangler seam
//! (`UnownedFrameSender`), removed when the remaining features move into the
//! core. Bindings only marshal. Plan `apple-client-core-migration`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::{ViewModelCore, lock};
use openmates_sdk::error::Error;
use std::sync::Arc;
use std::sync::atomic::Ordering;

#[uniffi::export]
impl ViewModelCore {
    /// Opt in to unowned socket frames: from now on, also after a new
    /// sign-in, every frame of a type the core does not own reaches the
    /// listener as `unownedSocketFrame` (a slow listener makes the core drop
    /// frames and report `unownedSocketFramesDropped`). Without this call
    /// nothing is kept.
    ///
    /// Signed out, the opt-in is kept for the next session.
    ///
    /// # Errors
    /// `Internal` when the core was shut down.
    pub async fn forward_unowned_frames(&self) -> Result<(), CoreError> {
        let shared = self.shared.clone();
        self.run(async move {
            shared.forward_unowned.store(true, Ordering::SeqCst);
            let mut guard = shared.host.lock().await;
            if let Some(host) = guard.as_mut() {
                host.enable_unowned_forwarding(&shared.sink);
            }
            Ok(())
        })
        .await
    }

    /// Write one raw frame `{"type": eventType, "payload": <payloadJson>}`
    /// on the core's monitor socket. Works while the actor is busy and
    /// settles within 10 seconds, or earlier through `cancellation`.
    ///
    /// # Errors
    /// `Unavailable` (`socket_frame_core_owned`) for a type the core owns,
    /// checked first; `Invalid` for a malformed type or a payload that is not
    /// a JSON object; `Offline` without a live socket or on timeout;
    /// `Unavailable` (`socket_frame_queue_full`) when 16 frames wait;
    /// `Offline` also when signed out; `Cancelled`.
    pub async fn send_unowned_frame(
        &self,
        event_type: String,
        payload_json: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<(), CoreError> {
        let sender = lock(&self.shared.unowned_sender).clone();
        let token = self.detached(cancellation);
        self.run(async move {
            let Some(sender) = sender else {
                return Err(Error::Offline);
            };
            tokio::select! {
                () = token.cancelled() => Err(Error::Cancelled),
                sent = sender.send(&event_type, &payload_json) => sent.map_err(Error::from),
            }
        })
        .await
    }
}
