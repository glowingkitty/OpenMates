//! The socket-side half of the shell passthrough: a bounded inbound queue of
//! the frames the core does not own (filled by the live monitor's socket task,
//! drained by the shell's forwarder) and a bounded outbound queue of raw shell
//! frames the socket task writes between its own frames.
//!
//! Temporary strangler seam (lane A4 of `docs/plans/apple-client-core-migration/`):
//! one server socket per account and device means un-migrated shell features
//! must share the core's socket. Removed when A5/A6 move the remaining
//! features into the core. Classification: `socket_frames.rs`.
use super::socket_frames::{forwards_to_shell, shell_may_send};
use crate::error::Error;
use serde_json::Value;
use std::collections::VecDeque;
use std::fmt;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;
use tokio::sync::{Notify, mpsc, oneshot};

/// Frames the inbound queue holds before it starts dropping.
pub const INBOUND_FRAME_LIMIT: usize = 256;
/// Payload bytes the inbound queue holds before it starts dropping.
pub const INBOUND_BYTE_LIMIT: usize = 8 * 1024 * 1024;
/// Shell frames waiting for the socket task before `send` answers `Busy`.
pub const OUTBOUND_QUEUE_LIMIT: usize = 16;
/// Longest wait of one shell send: queueing plus the socket write.
pub const OUTBOUND_SETTLE_TIMEOUT: Duration = Duration::from_secs(10);
/// Longest event type name a shell may send.
const EVENT_TYPE_MAX_LEN: usize = 64;

/// One item for the shell, in socket arrival order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum UnownedSocketItem {
    /// A frame the core does not own: its type and its payload as JSON text.
    Frame {
        /// The frame's `type` (or legacy `event`) name.
        event_type: String,
        /// The frame's `payload` (the whole legacy envelope for `event`
        /// frames), serialized.
        payload_json: String,
    },
    /// `count` frames were dropped here because the shell did not drain the
    /// queue fast enough (at most [`INBOUND_FRAME_LIMIT`] frames or
    /// [`INBOUND_BYTE_LIMIT`] payload bytes wait). The shell must treat the
    /// state those frames carried as unknown and re-read it.
    Dropped {
        /// Consecutive frames lost at this position.
        count: u64,
    },
}

/// Why a shell frame was not written to the core's socket.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum UnownedFrameError {
    /// The core owns this event type (`socket_frames::shell_may_send`).
    CoreOwned {
        /// The refused type.
        event_type: String,
    },
    /// The type is empty, longer than 64 bytes or not `[a-z0-9_]`.
    InvalidEventType,
    /// The payload is not a JSON object.
    InvalidPayload,
    /// No live core socket (signed out, monitor not admitted, socket closed
    /// or failed while writing).
    Disconnected,
    /// [`OUTBOUND_QUEUE_LIMIT`] shell frames are already waiting.
    Busy,
    /// Not settled within [`OUTBOUND_SETTLE_TIMEOUT`]. The frame was not
    /// written, unless its write had already begun (then the outcome is
    /// unknown, as for any socket write that times out).
    Timeout,
}

impl fmt::Display for UnownedFrameError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::CoreOwned { event_type } => {
                write!(f, "the core owns socket event `{event_type}`")
            }
            Self::InvalidEventType => f.write_str("invalid socket event type"),
            Self::InvalidPayload => f.write_str("socket payload must be a JSON object"),
            Self::Disconnected => f.write_str("the core socket is not connected"),
            Self::Busy => f.write_str("too many shell socket frames are waiting"),
            Self::Timeout => f.write_str("the shell socket frame did not settle in time"),
        }
    }
}

impl std::error::Error for UnownedFrameError {}

impl From<UnownedFrameError> for Error {
    fn from(error: UnownedFrameError) -> Self {
        match error {
            UnownedFrameError::CoreOwned { .. } => Error::Unavailable {
                code: "socket_frame_core_owned",
                reason: "SHELL_SEND_OF_CORE_OWNED_SOCKET_EVENT",
            },
            UnownedFrameError::InvalidEventType => Error::Invalid("Invalid socket event type."),
            UnownedFrameError::InvalidPayload => {
                Error::Invalid("A socket payload must be a JSON object.")
            }
            UnownedFrameError::Disconnected | UnownedFrameError::Timeout => Error::Offline,
            UnownedFrameError::Busy => Error::Unavailable {
                code: "socket_frame_queue_full",
                reason: "SHELL_SOCKET_FRAME_QUEUE_FULL",
            },
        }
    }
}

/// Whether frames are kept for a forwarder.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Mode {
    /// No forwarder yet: frames wait (bounded) so the first frames after the
    /// socket opened are not lost before the shell attaches.
    Buffering,
    /// One forwarder drains the queue.
    Attached,
    /// The shell declared no forwarder, or the forwarder went away: nothing
    /// is kept.
    Disabled,
}

struct Inbound {
    mode: Mode,
    items: VecDeque<UnownedSocketItem>,
    frames: usize,
    bytes: usize,
    /// The socket ended (or the monitor was replaced): the forwarder drains
    /// what is queued and stops.
    closed: bool,
}

/// One shell frame waiting for the socket task.
pub(crate) struct OutboundFrame {
    event_type: String,
    payload: Value,
    reply: oneshot::Sender<Result<(), Error>>,
}

impl OutboundFrame {
    /// Whether the sender gave up (timed out or dropped); such a frame is
    /// not written.
    pub(crate) fn abandoned(&self) -> bool {
        self.reply.is_closed()
    }

    /// The frame's type and payload, and the reply slot the socket task
    /// settles with the write's outcome.
    pub(crate) fn into_parts(self) -> (String, Value, OutboundReply) {
        (self.event_type, self.payload, OutboundReply(self.reply))
    }
}

/// Reply slot of one shell frame.
pub(crate) struct OutboundReply(oneshot::Sender<Result<(), Error>>);

impl OutboundReply {
    /// Report the write's outcome; a sender that gave up is not told.
    pub(crate) fn settle(self, result: Result<(), Error>) {
        // The receiver is gone only when the sender timed out or was dropped;
        // it already reported its own outcome then.
        let _unheard = self.0.send(result);
    }
}

/// The passthrough of one live monitor socket. Owned by the monitor's change
/// state; the socket task calls [`Self::observe`], [`Self::next_outbound`]
/// and [`Self::close`]. Never blocks the socket task: a full inbound queue
/// drops (reported as [`UnownedSocketItem::Dropped`]).
pub(crate) struct SocketPassthrough {
    inbound: Mutex<Inbound>,
    wake: Notify,
    outbound: mpsc::Sender<OutboundFrame>,
    outbound_queue: tokio::sync::Mutex<mpsc::Receiver<OutboundFrame>>,
    /// A shell frame was written on this socket ([`Self::note_shell_write`]).
    shell_wrote: AtomicBool,
}

impl Default for SocketPassthrough {
    fn default() -> Self {
        let (outbound, receiver) = mpsc::channel(OUTBOUND_QUEUE_LIMIT);
        Self {
            inbound: Mutex::new(Inbound {
                mode: Mode::Buffering,
                items: VecDeque::new(),
                frames: 0,
                bytes: 0,
                closed: false,
            }),
            wake: Notify::new(),
            outbound,
            outbound_queue: tokio::sync::Mutex::new(receiver),
            shell_wrote: AtomicBool::new(false),
        }
    }
}

impl SocketPassthrough {
    fn inbound(&self) -> MutexGuard<'_, Inbound> {
        // The guarded state is plain counters and owned frames that every
        // writer leaves consistent before it can panic, so a poisoned lock is
        // safe to keep using.
        self.inbound.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Queue an inbound frame of `kind` for the shell when the core does not
    /// own it. Called by the socket task after the core handled the frame,
    /// once per frame, in arrival order.
    pub(crate) fn observe(&self, kind: &str, payload: &Value) {
        if forwards_to_shell(kind) {
            self.queue(kind, payload);
        }
    }

    /// Record that a shell frame was written on this socket; from then on a
    /// server `error` frame may answer the shell (`client/monitor_error_frames.rs`).
    pub(crate) fn note_shell_write(&self) {
        self.shell_wrote.store(true, Ordering::Release);
    }

    /// Whether any shell frame was written on this socket.
    pub(crate) fn shell_wrote(&self) -> bool {
        self.shell_wrote.load(Ordering::Acquire)
    }

    /// Queue a server `error` frame the monitor attributed to a shell frame
    /// as `UnownedSocketItem::Frame { event_type: "error" }`, in arrival
    /// order. The type stays core-owned for every other purpose: a shell may
    /// not send it, and unattributed error frames are never forwarded.
    pub(crate) fn observe_shell_error(&self, payload: &Value) {
        self.queue("error", payload);
    }

    fn queue(&self, kind: &str, payload: &Value) {
        let mut inbound = self.inbound();
        if inbound.closed || inbound.mode == Mode::Disabled {
            return;
        }
        let payload_json = payload.to_string();
        let fits = inbound.frames < INBOUND_FRAME_LIMIT
            && inbound.bytes.saturating_add(payload_json.len()) <= INBOUND_BYTE_LIMIT;
        if fits {
            inbound.frames += 1;
            inbound.bytes += payload_json.len();
            inbound.items.push_back(UnownedSocketItem::Frame {
                event_type: kind.to_owned(),
                payload_json,
            });
        } else if let Some(UnownedSocketItem::Dropped { count }) = inbound.items.back_mut() {
            *count = count.saturating_add(1);
        } else {
            // One marker per gap, at the gap's position; markers are not
            // counted against the limits (a gap needs a full queue first).
            inbound
                .items
                .push_back(UnownedSocketItem::Dropped { count: 1 });
        }
        drop(inbound);
        self.wake.notify_one();
    }

    /// Become the one forwarder: frames buffered since the socket opened come
    /// first. `None` when a forwarder exists already or forwarding was
    /// disabled.
    pub(crate) fn attach(self: &Arc<Self>) -> Option<UnownedFrameReceiver> {
        let mut inbound = self.inbound();
        if inbound.mode != Mode::Buffering {
            return None;
        }
        inbound.mode = Mode::Attached;
        Some(UnownedFrameReceiver {
            passthrough: self.clone(),
        })
    }

    /// Keep nothing: the shell runs no forwarder (the terminal app).
    pub(crate) fn disable(&self) {
        let mut inbound = self.inbound();
        inbound.mode = Mode::Disabled;
        inbound.items.clear();
        inbound.frames = 0;
        inbound.bytes = 0;
    }

    /// End inbound forwarding after the queued items (the forwarder drains
    /// them, then stops). Called when the socket task ends and when the
    /// monitor is replaced, so frames of two sockets never interleave.
    pub(crate) fn close_inbound(&self) {
        self.inbound().closed = true;
        self.wake.notify_one();
    }

    /// End the passthrough when the socket task ends: inbound as
    /// [`Self::close_inbound`], and every waiting or later shell send
    /// settles with `Disconnected`.
    pub(crate) async fn close(&self) {
        self.close_inbound();
        let mut queue = self.outbound_queue.lock().await;
        queue.close();
        while let Ok(frame) = queue.try_recv() {
            frame.into_parts().2.settle(Err(Error::Offline));
        }
    }

    /// The next shell frame to write; pending until one is queued. The socket
    /// task selects on this next to its receive, so dropping the future (a
    /// frame or heartbeat won the select) loses nothing.
    pub(crate) async fn next_outbound(&self) -> Option<OutboundFrame> {
        self.outbound_queue.lock().await.recv().await
    }

    /// Queue one shell frame and wait for its write (bounded).
    ///
    /// # Errors
    /// See [`UnownedFrameError`]; `CoreOwned` and the validation errors come
    /// before any socket check.
    pub(crate) async fn send(
        &self,
        event_type: &str,
        payload_json: &str,
    ) -> Result<(), UnownedFrameError> {
        let payload = validate_shell_frame(event_type, payload_json)?;
        let (reply, settled) = oneshot::channel();
        let frame = OutboundFrame {
            event_type: event_type.to_owned(),
            payload,
            reply,
        };
        self.outbound.try_send(frame).map_err(|error| match error {
            mpsc::error::TrySendError::Full(_) => UnownedFrameError::Busy,
            mpsc::error::TrySendError::Closed(_) => UnownedFrameError::Disconnected,
        })?;
        match crate::platform::time::timeout(OUTBOUND_SETTLE_TIMEOUT, settled).await {
            Err(_elapsed) => Err(UnownedFrameError::Timeout),
            // The socket task dropped the frame unwritten (it ended).
            Ok(Err(_dropped)) => Err(UnownedFrameError::Disconnected),
            Ok(Ok(Err(_write_failed))) => Err(UnownedFrameError::Disconnected),
            Ok(Ok(Ok(()))) => Ok(()),
        }
    }
}

/// Check a shell frame before it is queued: a type the shell may send, in
/// the server's naming, and an object payload.
///
/// # Errors
/// `CoreOwned`, `InvalidEventType` or `InvalidPayload`.
pub(crate) fn validate_shell_frame(
    event_type: &str,
    payload_json: &str,
) -> Result<Value, UnownedFrameError> {
    let well_formed = !event_type.is_empty()
        && event_type.len() <= EVENT_TYPE_MAX_LEN
        && event_type
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_');
    if !well_formed {
        return Err(UnownedFrameError::InvalidEventType);
    }
    if !shell_may_send(event_type) {
        return Err(UnownedFrameError::CoreOwned {
            event_type: event_type.to_owned(),
        });
    }
    let payload: Value =
        serde_json::from_str(payload_json).map_err(|_| UnownedFrameError::InvalidPayload)?;
    if !payload.is_object() {
        return Err(UnownedFrameError::InvalidPayload);
    }
    Ok(payload)
}

/// The one forwarder's end of a passthrough. Dropping it disables forwarding
/// for its socket (nothing more is kept).
pub(crate) struct UnownedFrameReceiver {
    passthrough: Arc<SocketPassthrough>,
}

impl UnownedFrameReceiver {
    /// The next item in arrival order; `None` once the socket ended (or the
    /// monitor was replaced) and everything queued before was returned.
    pub(crate) async fn recv(&self) -> Option<UnownedSocketItem> {
        loop {
            // Registered before the check: `notify_one` stores a permit when
            // nobody waits, so a frame queued in between still wakes us.
            let notified = self.passthrough.wake.notified();
            {
                let mut inbound = self.passthrough.inbound();
                if let Some(item) = inbound.items.pop_front() {
                    if let UnownedSocketItem::Frame { payload_json, .. } = &item {
                        inbound.frames -= 1;
                        inbound.bytes -= payload_json.len();
                    }
                    return Some(item);
                }
                if inbound.closed {
                    return None;
                }
            }
            notified.await;
        }
    }
}

impl Drop for UnownedFrameReceiver {
    fn drop(&mut self) {
        self.passthrough.disable();
    }
}
