//! Commands a shell sends to the view-model actor and events it receives back.
//! Request ids are typed so a stale reply can be matched to the request that
//! caused it. Spec: `a2-design.md` (View model); served by `actor_flows.rs`.
use super::error::ViewErrorKind;
use super::records::{ChatListRow, ChatWindowRecord, ListCompleteness, StreamEvent};
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
}
