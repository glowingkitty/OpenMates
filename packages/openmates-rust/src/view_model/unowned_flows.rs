//! The view-model side of the shell passthrough: which live monitor socket
//! the shell's raw frames go to, and the forwarder task that turns the frames
//! the core does not own into `ViewEvent::UnownedSocketFrame` events.
//!
//! Temporary strangler seam (lane A4 of `docs/plans/apple-client-core-migration/`):
//! removed when A5/A6 move the remaining features into the core. The socket
//! half is `socket_passthrough.rs`, the classification `socket_frames.rs`.
//! Native only.
use super::{
    ViewEvent,
    actor_host::ViewSink,
    socket_passthrough::{
        SocketPassthrough, UnownedFrameError, UnownedFrameReceiver, UnownedSocketItem,
    },
};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use tokio::sync::oneshot;

type Slot = Arc<Mutex<Option<Arc<SocketPassthrough>>>>;

fn locked(slot: &Slot) -> MutexGuard<'_, Option<Arc<SocketPassthrough>>> {
    // The slot holds one `Arc`; a panic elsewhere cannot leave it half
    // written, so a poisoned lock is safe to keep using.
    slot.lock().unwrap_or_else(PoisonError::into_inner)
}

/// Per-actor passthrough state, kept inside `ViewCore`.
#[derive(Default)]
pub(super) struct UnownedSeam {
    /// The shell's sink for forwarded frames; `None`: the shell runs no
    /// forwarder and nothing is kept (the terminal app).
    sink: Option<Arc<dyn ViewSink>>,
    /// The passthrough of the installed monitor, shared with every
    /// [`UnownedFrameSender`].
    current: Slot,
    /// Completion of the latest forwarder; the next one waits for it, so the
    /// frames of a replaced socket are all delivered before the new socket's.
    previous: Option<oneshot::Receiver<()>>,
}

impl UnownedSeam {
    /// Install the passthrough of a newly installed monitor (`None`: the
    /// monitor was retired). The previous socket's frames end after what it
    /// already queued.
    pub(super) fn replace(&mut self, next: Option<Arc<SocketPassthrough>>) {
        let previous = std::mem::replace(&mut *locked(&self.current), next.clone());
        if let Some(previous) = previous {
            previous.close_inbound();
        }
        if let Some(next) = next {
            self.connect(&next);
        }
    }

    /// Opt in to forwarding into `sink`; a monitor installed earlier starts
    /// forwarding now (with the frames it buffered since its socket opened).
    pub(super) fn forward_to(&mut self, sink: Arc<dyn ViewSink>) {
        self.sink = Some(sink);
        let current = locked(&self.current).clone();
        if let Some(current) = current {
            self.connect(&current);
        }
    }

    fn connect(&mut self, passthrough: &Arc<SocketPassthrough>) {
        let Some(sink) = self.sink.clone() else {
            passthrough.disable();
            return;
        };
        // `None`: this socket already has its forwarder.
        let Some(frames) = passthrough.attach() else {
            return;
        };
        let (done, finished) = oneshot::channel();
        let previous = self.previous.replace(finished);
        crate::platform::spawn(forward(previous, frames, sink, done));
    }

    /// A sender bound to whichever monitor is installed when it sends.
    pub(super) fn sender(&self) -> UnownedFrameSender {
        UnownedFrameSender {
            current: self.current.clone(),
        }
    }
}

/// Deliver one socket's items in order. Runs on its own task, so a slow
/// shell never blocks the actor or the socket (the socket side drops and
/// reports instead). Forwarded frames are ordered among themselves, not
/// against the actor's own events.
async fn forward(
    previous: Option<oneshot::Receiver<()>>,
    frames: UnownedFrameReceiver,
    sink: Arc<dyn ViewSink>,
    done: oneshot::Sender<()>,
) {
    if let Some(previous) = previous {
        // `Err`: the earlier forwarder's task ended without signalling; it
        // emits nothing more either way.
        drop(previous.await);
    }
    while let Some(item) = frames.recv().await {
        let event = match item {
            UnownedSocketItem::Frame {
                event_type,
                payload_json,
            } => ViewEvent::UnownedSocketFrame {
                event_type,
                payload_json,
            },
            UnownedSocketItem::Dropped { count } => ViewEvent::UnownedSocketFramesDropped { count },
        };
        // A sink error means the shell stopped listening (or refuses this
        // event kind): stop, and dropping `frames` stops keeping frames.
        if sink.emit(event).await.is_err() {
            break;
        }
    }
    drop(frames);
    // The next forwarder may be gone already (actor dropped); nothing waits.
    let _unheard = done.send(());
}

/// A cheap, cloneable handle a shell uses to send raw frames of un-migrated
/// features through the core's one socket, also while the actor is busy.
/// Temporary strangler seam, removed when A5/A6 move the remaining features
/// into the core.
#[derive(Clone)]
pub struct UnownedFrameSender {
    current: Slot,
}

impl UnownedFrameSender {
    /// Write one frame `{"type": event_type, "payload": <payload_json>}` on
    /// the installed monitor's socket. Settles within
    /// `OUTBOUND_SETTLE_TIMEOUT` (10 s); never hangs.
    ///
    /// # Errors
    /// `CoreOwned` for a type the core owns (checked first, also while
    /// disconnected), `InvalidEventType`/`InvalidPayload`, `Disconnected`
    /// without a live socket, `Busy` when 16 frames wait, `Timeout`.
    pub async fn send(
        &self,
        event_type: &str,
        payload_json: &str,
    ) -> Result<(), UnownedFrameError> {
        super::socket_passthrough::validate_shell_frame(event_type, payload_json)?;
        let current = locked(&self.current).clone();
        let Some(passthrough) = current else {
            return Err(UnownedFrameError::Disconnected);
        };
        passthrough.send(event_type, payload_json).await
    }
}
