//! Commands a shell sends to the view-model actor and events it receives back.
//! Request ids are typed so a stale reply can be matched to the request that
//! caused it. Spec: `a2-design.md` (View model); served by `actor_flows.rs`.
use super::draft_view::DraftView;
use super::error::ViewErrorKind;
use super::records::{ChatListRow, ChatWindowRecord, ListCompleteness, MessageRecord, StreamEvent};
use crate::session::Session;

/// Identifier of one shell request (open, page, send). Allocated by the shell;
/// replies carry it back unchanged.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RequestId(pub u64);

/// Work a shell asks the core to do. Deliberately without `Debug`: `Start`
/// carries credentials.
pub enum ViewCommand {
    /// Restore the index and start the session with the given credentials.
    Start {
        /// Explicit caller-owned credentials.
        credentials: Box<Session>,
    },
    /// Re-read the chat list.
    RefreshChats,
    /// Open a chat window.
    OpenChat {
        /// Request the `ChatWindow`/`ChatOpenFailed` reply answers.
        request: RequestId,
        /// Chat to open.
        chat_id: String,
    },
    /// Load the page of messages before the oldest one of an open chat.
    LoadOlder {
        /// Request the `ChatWindow` reply answers.
        request: RequestId,
        /// Open chat.
        chat_id: String,
    },
    /// Release an open chat.
    CloseChat {
        /// Chat to close.
        chat_id: String,
    },
    /// Mark a chat read on every device.
    MarkRead {
        /// Chat to mark.
        chat_id: String,
    },
    /// Switch the active team scope; `None` selects the personal scope.
    SwitchTeam {
        /// Team id, or `None` for personal.
        team_id: Option<String>,
    },
    /// Send a message; `chat_id` is `None` for a new chat.
    Send {
        /// Request the `Stream` and send `ChatWindow` events answer.
        request: RequestId,
        /// Target chat, or `None` to create one.
        chat_id: Option<String>,
        /// Message text.
        text: String,
    },
    /// Cancel a running send. Commands run one at a time, so a shell that
    /// interrupts a running send uses `SendCancelHandle`; queued, this
    /// cancels nothing when no send runs.
    Cancel,
    /// Sign out and wipe local credentials.
    Logout,
    /// Write a raw frame of a shell feature that is not in the core yet on
    /// the core's socket (`UnownedFrameSender::send`; types the core owns are
    /// refused). Temporary strangler seam, removed when A5/A6 move the
    /// remaining features into the core.
    SendUnownedFrame {
        /// The frame's `type`.
        event_type: String,
        /// The frame's `payload`, a JSON object as text.
        payload_json: String,
    },
}

/// Why access was withdrawn (mirror of `ChatMonitorAccessDenial`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AccessDenial {
    /// The session expired.
    Expired,
    /// The team scope was revoked.
    ScopeRevoked,
    /// A chat is gone or no longer readable.
    ChatUnavailable {
        /// Affected chat.
        chat_id: String,
    },
}

/// Session lifecycle events.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SessionEvent {
    /// No usable session exists.
    SignedOut,
    /// A stored session was restored for the first paint, not yet admitted.
    Restored {
        /// Cached display name, when known.
        display_name: Option<String>,
    },
    /// The server admitted the session.
    Admitted {
        /// Account username.
        username: String,
        /// Absolute expiry in unix milliseconds, for paired sessions.
        expires_at: Option<u64>,
    },
    /// The session expired.
    Expired,
    /// The server kept the session but asks to verify this device or to sign
    /// in again before it admits it; credentials stay stored.
    VerificationRequired(crate::client::SessionVerification),
    /// Access was denied.
    AccessDenied(AccessDenial),
}

/// Server sync phase (`phase_1_last_chat_ready`, `phase_2_last_20_chats_ready`,
/// `phase_1b_chat_content_ready`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SyncPhase {
    /// The last opened chat arrived.
    LastChat,
    /// The recent chats arrived.
    RecentChats,
    /// Message content of the last chat arrived.
    ChatContent,
}

/// What the core tells the shell.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ViewEvent {
    /// Session lifecycle change.
    Session(SessionEvent),
    /// Initial sync advanced.
    SyncProgress {
        /// Phase just reached.
        phase: SyncPhase,
        /// Items received so far.
        received: u64,
    },
    /// The chat list changed.
    ChatList {
        /// Rows in display order.
        rows: Vec<ChatListRow>,
        /// How far the list can be trusted.
        completeness: ListCompleteness,
        /// Chats the account has in this scope as the server last reported
        /// it (more than `rows` when the list is partial); `None` until the
        /// server reported one.
        total_count: Option<u64>,
    },
    /// A chat window is ready or changed.
    ChatWindow {
        /// Request that asked for it.
        request: RequestId,
        /// The window.
        window: ChatWindowRecord,
    },
    /// A chat is gone or unreadable.
    ChatUnavailable {
        /// Affected chat.
        chat_id: String,
    },
    /// Opening a chat failed.
    ChatOpenFailed {
        /// Request that failed.
        request: RequestId,
        /// Chat that failed to open.
        chat_id: String,
        /// Failure class.
        error: ViewErrorKind,
    },
    /// One message of the open window changed while its reply streams: the
    /// whole message as it is now (text and reasoning so far, replacing the
    /// previous value), sent instead of a full `ChatWindow` per stream
    /// update. It follows the `Stream` event that caused it. A message id
    /// the shown window does not have yet (the first reply text) is appended
    /// at the end; the next `ChatWindow` of `request` already contains it.
    MessageUpdated {
        /// Request that started the send (the window's request).
        request: RequestId,
        /// Chat of the window.
        chat_id: String,
        /// The changed message; its id is stable until `Completed` renames it.
        message: MessageRecord,
    },
    /// Progress of a send.
    Stream {
        /// Request that started the send.
        request: RequestId,
        /// Chat the stream belongs to.
        chat_id: String,
        /// The progress item.
        event: StreamEvent,
    },
    /// Human-readable progress note.
    Status {
        /// Note text.
        message: String,
    },
    /// A request failed.
    Failed {
        /// Failure class.
        error: ViewErrorKind,
    },
    /// The current unit of work finished.
    Done,
    /// The saved draft of `chat_id` changed outside this client (saved or
    /// cleared on another device) and a refresh applied it: an open composer
    /// of that chat shows `draft` (`None`: cleared, or the chat is gone).
    /// This client's own saves and clears are never echoed. Follows the
    /// `ChatList` (and `ChatWindow`) events of the same refresh.
    DraftChanged {
        /// Chat whose draft changed.
        chat_id: String,
        /// The draft as it is now; `None` when there is none.
        draft: Option<DraftView>,
    },
    /// An inbound socket frame whose type the core does not own
    /// (`classify_socket_event`), for a shell feature that is not in the
    /// core yet. Delivered in socket arrival order by the forwarder that
    /// `ViewCore::forward_unowned_frames` starts; not ordered against the
    /// other events. Temporary strangler seam, removed when A5/A6 move the
    /// remaining features into the core.
    UnownedSocketFrame {
        /// The frame's `type` (or legacy `event`) name.
        event_type: String,
        /// The frame's payload as JSON text.
        payload_json: String,
    },
    /// `count` consecutive unowned frames were dropped at this position
    /// because the shell drained too slowly (bounded queue); the state they
    /// carried is unknown and must be re-read. Same seam and end as
    /// `UnownedSocketFrame`.
    UnownedSocketFramesDropped {
        /// Frames lost at this position.
        count: u64,
    },
}
