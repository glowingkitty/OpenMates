//! UniFFI mirrors of the core view-model events and records
//! (`openmates_sdk::view_model`), delivered to Swift through `ViewListener`.
//! Each type maps its core counterpart 1:1 (same variants, same fields, no
//! defaults, no logic); tuple variants get one named field because Swift
//! enums need labels. Spec: `a2-design.md` (View model); plan
//! `apple-client-core-migration` lane L8. Row and message metadata mirrors
//! live in `view_record_details.rs`.
use crate::view_record_details::{ChatRowMetadataRecord, MessageMetadataRecord};
use openmates_sdk::view_model::{
    AccessDenial, ChatListRow, ChatRowStatus, ChatWindowRecord, ChatWindowSource, EmbedRef,
    ListCompleteness, MessageRecord, MessageRole, MessageStatus, PiiRestoration, SendState,
    SessionEvent, StreamEvent, SyncPhase, ViewErrorKind, ViewEvent,
};

/// How trustworthy a published chat list is (core `ListCompleteness`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum ListCompletenessRecord {
    /// Restored from the local index; no network read confirmed it yet.
    Cached,
    /// A network read delivered the first pages; older chats may be missing.
    Partial,
    /// The full inventory of the current scope was read.
    Complete,
}

/// Display state of a chat list row (core `ChatRowStatus`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum ChatRowStatusRecord {
    /// An ordinary chat.
    Ready,
    /// A chat that so far exists only as a draft.
    Draft,
    /// A chat whose key is not available in the current scope.
    Locked,
}

/// One row of the chat list (core `ChatListRow`). Plaintext: never log it.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ChatListRowRecord {
    /// Chat id.
    pub id: String,
    /// Display title, including draft and locked fallbacks.
    pub title: String,
    /// Exact decrypted title when one exists.
    pub chat_list_title: Option<String>,
    /// Decrypted chat summary (empty when none).
    pub summary: String,
    /// Decrypted category (empty when none).
    pub category: String,
    /// Draft or locked state.
    pub status: ChatRowStatusRecord,
    /// Creation time in unix milliseconds.
    pub created_at: Option<i64>,
    /// Last update in unix milliseconds.
    pub updated_at: Option<i64>,
    /// Server message version.
    pub messages_v: Option<u64>,
    /// Finished assistant replies not yet read on any device.
    pub unread_count: u64,
    /// Pinned by the user.
    pub pinned: bool,
    /// Archived by the user.
    pub archived: bool,
    /// An unsent draft exists for this chat.
    pub has_draft: bool,
    /// Home-card footer such as a reminder countdown.
    pub footer: Option<String>,
    /// Further facts of the held chat row (icon, sub-chat, budget, draft).
    pub metadata: ChatRowMetadataRecord,
}

/// Author role of a message (core `MessageRole`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum MessageRoleRecord {
    /// Written by the account owner.
    User,
    /// Written by an assistant mate.
    Assistant,
    /// Written by the system.
    System,
}

/// Delivery state of a message (core `MessageStatus`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum MessageStatusRecord {
    /// Stored message with final content.
    Complete,
    /// Assistant reply still being streamed.
    Streaming,
}

/// Delivery state of a message the user sent from this device (core
/// `SendState`).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum SendStateRecord {
    /// Shown before the server saw it.
    Sending,
    /// Dispatch may have committed; never resend automatically.
    Submitted,
    /// The server acknowledged persistence of the message.
    Delivered,
    /// The send failed; the text stays visible for a deliberate retry.
    Failed {
        /// Failure class.
        error: ViewErrorKindRecord,
        /// Dispatch may have committed before the failure.
        submitted: bool,
    },
    /// The user cancelled the send or its reply.
    Cancelled {
        /// Dispatch may have committed before the cancel.
        submitted: bool,
    },
}

/// Reference to a decrypted embed (core `EmbedRef`).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct EmbedRefRecord {
    /// Embed id.
    pub id: String,
    /// Embed type; empty when unknown.
    pub kind: String,
    /// Owning app id; empty when none.
    pub app_id: String,
    /// Skill id; empty when none.
    pub skill_id: String,
    /// Display title.
    pub title: String,
    /// Description or summary; empty when none.
    pub description: String,
    /// Embed status such as `finished`; empty when none.
    pub status: String,
    /// The embed's metadata object as JSON (until the embeds lane).
    pub data_json: String,
}

/// A decrypted chat message (core `MessageRecord`). Plaintext: never log it.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct MessageViewRecord {
    /// Message id.
    pub id: String,
    /// Author role.
    pub role: MessageRoleRecord,
    /// Delivery state.
    pub status: MessageStatusRecord,
    /// Message text after PII restoration.
    pub content: String,
    /// Mate display name; empty for the user.
    pub sender: String,
    /// Reasoning text; empty when none.
    pub thinking: String,
    /// Embeds attached to the message.
    pub embeds: Vec<EmbedRefRecord>,
    /// Send progress of a message sent from this device; `None` for stored
    /// messages and replies.
    pub send_state: Option<SendStateRecord>,
    /// Stored facts of the message row (timestamps, ids, model, queue, PII).
    pub metadata: MessageMetadataRecord,
}

/// Where a chat window's data came from (core `ChatWindowSource`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum ChatWindowSourceRecord {
    /// Local cache only.
    Cached,
    /// Cache served while offline; read-only.
    CachedOffline,
    /// Authorized cache confirmed by the server.
    CacheSettled,
    /// First page of messages read from the network.
    FirstPage,
    /// Canonical read of the chat.
    Canonical,
    /// Window updated from a live event.
    Live,
    /// Window updated from a live event with authorized cached content.
    LiveSettled,
}

/// How personal data tokens were restored (core `PiiRestoration`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum PiiRestorationRecord {
    /// Only mappings from the same page were applied.
    PageLocal,
    /// Mappings from every cached user row were applied.
    AllCachedUserRows,
}

/// The messages of one open chat (core `ChatWindowRecord`).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ChatWindowViewRecord {
    /// Chat id.
    pub chat_id: String,
    /// Display title.
    pub title: String,
    /// Decrypted category (empty when none).
    pub category: String,
    /// Messages, oldest first.
    pub messages: Vec<MessageViewRecord>,
    /// Origin of the data.
    pub source: ChatWindowSourceRecord,
    /// Whether older messages exist; `None` when unknown.
    pub has_more_before: Option<bool>,
    /// Whether newer messages exist; `None` when unknown.
    pub has_more_after: Option<bool>,
    /// Every message of the chat is in `messages`.
    pub history_complete: bool,
    /// A network refresh is still running.
    pub refreshing: bool,
    /// PII restoration scope applied to the messages.
    pub pii_restoration: PiiRestorationRecord,
}

/// Progress of a send or live reply (core `StreamEvent`).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum StreamEventRecord {
    /// The assistant asks permission to use the listed items.
    Consent {
        /// Consent request id.
        request_id: String,
        /// Items the assistant wants to use.
        items: Vec<EmbedRefRecord>,
    },
    /// Sending began.
    Started {
        /// Chat id.
        chat_id: String,
        /// User message id.
        message_id: String,
        /// A reply will follow.
        expects_reply: bool,
    },
    /// Dispatch may have committed; never resend automatically.
    Submitted {
        /// Chat id.
        chat_id: String,
        /// User message id.
        message_id: String,
    },
    /// The server acknowledged persistence of the user message.
    Admitted {
        /// Chat id.
        chat_id: String,
        /// User message id.
        message_id: String,
    },
    /// Reply text so far.
    Content {
        /// Visible reply text.
        content: String,
        /// Reasoning text.
        thinking: String,
        /// Mate producing the reply.
        mate: String,
    },
    /// The reply finished.
    Completed {
        /// Chat id.
        chat_id: String,
        /// Reply message id.
        message_id: String,
        /// Final reply text.
        content: String,
    },
    /// Human-readable progress note.
    Status {
        /// Note text.
        message: String,
    },
}

/// Why access was withdrawn (core `AccessDenial`).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum AccessDenialRecord {
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

/// Session lifecycle events (core `SessionEvent`).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum SessionEventRecord {
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
    AccessDenied {
        /// Why.
        denial: AccessDenialRecord,
    },
}

/// Server sync phase (core `SyncPhase`).
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum SyncPhaseRecord {
    /// The last opened chat arrived.
    LastChat,
    /// The recent chats arrived.
    RecentChats,
    /// Message content of the last chat arrived.
    ChatContent,
}

/// Payload-free failure class (core `ViewErrorKind`).
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum ViewErrorKindRecord {
    /// Caller supplied an invalid request.
    Invalid,
    /// Cryptographic operation failed.
    Crypto,
    /// Credentials were refused.
    Authentication,
    /// A second factor is required.
    TwoFactorRequired,
    /// Signup is required.
    SignupRequired,
    /// A capability is unavailable.
    Unavailable {
        /// Stable code of the refusal.
        code: String,
    },
    /// Local data is locked.
    Locked,
    /// No network.
    Offline,
    /// Access is forbidden.
    Forbidden,
    /// The session expired.
    Expired,
    /// The operation was cancelled.
    Cancelled,
    /// Local I/O failed.
    Io,
    /// The server answered outside the protocol.
    ProtocolError,
    /// A concurrent change conflicted.
    Conflict,
}

/// What the core tells the Swift shell (core `ViewEvent`). Request ids are
/// the core's `RequestId` values.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum ViewEventRecord {
    /// Session lifecycle change.
    Session {
        /// The change.
        event: SessionEventRecord,
    },
    /// Initial sync advanced.
    SyncProgress {
        /// Phase just reached.
        phase: SyncPhaseRecord,
        /// Items received so far.
        received: u64,
    },
    /// The chat list changed.
    ChatList {
        /// Rows in display order.
        rows: Vec<ChatListRowRecord>,
        /// How far the list can be trusted.
        completeness: ListCompletenessRecord,
    },
    /// A chat window is ready or changed.
    ChatWindow {
        /// Request that asked for it.
        request: u64,
        /// The window.
        window: ChatWindowViewRecord,
    },
    /// A chat is gone or unreadable.
    ChatUnavailable {
        /// Affected chat.
        chat_id: String,
    },
    /// Opening a chat failed.
    ChatOpenFailed {
        /// Request that failed.
        request: u64,
        /// Chat that failed to open.
        chat_id: String,
        /// Failure class.
        error: ViewErrorKindRecord,
    },
    /// One message of the open window changed while its reply streams (the
    /// whole message as it is now; an id not shown yet is appended). Sent
    /// instead of a full `ChatWindow` per reply-text update, after the
    /// `Stream` event that caused it.
    MessageUpdated {
        /// Request of the window (the send's request).
        request: u64,
        /// Chat of the window.
        chat_id: String,
        /// The changed message.
        message: MessageViewRecord,
    },
    /// Progress of a send.
    Stream {
        /// Request that started the send.
        request: u64,
        /// Chat the stream belongs to.
        chat_id: String,
        /// The progress item.
        event: StreamEventRecord,
    },
    /// Human-readable progress note.
    Status {
        /// Note text.
        message: String,
    },
    /// A request failed.
    Failed {
        /// Failure class.
        error: ViewErrorKindRecord,
    },
    /// The current unit of work finished.
    Done,
}

impl From<ListCompleteness> for ListCompletenessRecord {
    fn from(value: ListCompleteness) -> Self {
        match value {
            ListCompleteness::Cached => Self::Cached,
            ListCompleteness::Partial => Self::Partial,
            ListCompleteness::Complete => Self::Complete,
        }
    }
}

impl From<ChatRowStatus> for ChatRowStatusRecord {
    fn from(value: ChatRowStatus) -> Self {
        match value {
            ChatRowStatus::Ready => Self::Ready,
            ChatRowStatus::Draft => Self::Draft,
            ChatRowStatus::Locked => Self::Locked,
        }
    }
}

impl From<ChatListRow> for ChatListRowRecord {
    fn from(row: ChatListRow) -> Self {
        Self {
            id: row.id,
            title: row.title,
            chat_list_title: row.chat_list_title,
            summary: row.summary,
            category: row.category,
            status: row.status.into(),
            created_at: row.created_at,
            updated_at: row.updated_at,
            messages_v: row.messages_v,
            unread_count: row.unread_count,
            pinned: row.pinned,
            archived: row.archived,
            has_draft: row.has_draft,
            footer: row.footer,
            metadata: row.metadata.into(),
        }
    }
}

impl From<MessageRole> for MessageRoleRecord {
    fn from(value: MessageRole) -> Self {
        match value {
            MessageRole::User => Self::User,
            MessageRole::Assistant => Self::Assistant,
            MessageRole::System => Self::System,
        }
    }
}

impl From<MessageStatus> for MessageStatusRecord {
    fn from(value: MessageStatus) -> Self {
        match value {
            MessageStatus::Complete => Self::Complete,
            MessageStatus::Streaming => Self::Streaming,
        }
    }
}

impl From<EmbedRef> for EmbedRefRecord {
    fn from(embed: EmbedRef) -> Self {
        Self {
            id: embed.id,
            kind: embed.kind,
            app_id: embed.app_id,
            skill_id: embed.skill_id,
            title: embed.title,
            description: embed.description,
            status: embed.status,
            data_json: embed.data_json,
        }
    }
}

fn embeds(items: Vec<EmbedRef>) -> Vec<EmbedRefRecord> {
    items.into_iter().map(Into::into).collect()
}

impl From<MessageRecord> for MessageViewRecord {
    fn from(message: MessageRecord) -> Self {
        Self {
            id: message.id,
            role: message.role.into(),
            status: message.status.into(),
            content: message.content,
            sender: message.sender,
            thinking: message.thinking,
            embeds: embeds(message.embeds),
            send_state: message.send_state.map(Into::into),
            metadata: message.metadata.into(),
        }
    }
}

impl From<SendState> for SendStateRecord {
    fn from(value: SendState) -> Self {
        match value {
            SendState::Sending => Self::Sending,
            SendState::Submitted => Self::Submitted,
            SendState::Delivered => Self::Delivered,
            SendState::Failed { error, submitted } => Self::Failed {
                error: error.into(),
                submitted,
            },
            SendState::Cancelled { submitted } => Self::Cancelled { submitted },
        }
    }
}

impl From<ChatWindowSource> for ChatWindowSourceRecord {
    fn from(value: ChatWindowSource) -> Self {
        match value {
            ChatWindowSource::Cached => Self::Cached,
            ChatWindowSource::CachedOffline => Self::CachedOffline,
            ChatWindowSource::CacheSettled => Self::CacheSettled,
            ChatWindowSource::FirstPage => Self::FirstPage,
            ChatWindowSource::Canonical => Self::Canonical,
            ChatWindowSource::Live => Self::Live,
            ChatWindowSource::LiveSettled => Self::LiveSettled,
        }
    }
}

impl From<PiiRestoration> for PiiRestorationRecord {
    fn from(value: PiiRestoration) -> Self {
        match value {
            PiiRestoration::PageLocal => Self::PageLocal,
            PiiRestoration::AllCachedUserRows => Self::AllCachedUserRows,
        }
    }
}

impl From<ChatWindowRecord> for ChatWindowViewRecord {
    fn from(window: ChatWindowRecord) -> Self {
        Self {
            chat_id: window.chat_id,
            title: window.title,
            category: window.category,
            messages: window.messages.into_iter().map(Into::into).collect(),
            source: window.source.into(),
            has_more_before: window.has_more_before,
            has_more_after: window.has_more_after,
            history_complete: window.history_complete,
            refreshing: window.refreshing,
            pii_restoration: window.pii_restoration.into(),
        }
    }
}

impl From<StreamEvent> for StreamEventRecord {
    fn from(event: StreamEvent) -> Self {
        match event {
            StreamEvent::Consent { request_id, items } => Self::Consent {
                request_id,
                items: embeds(items),
            },
            StreamEvent::Started {
                chat_id,
                message_id,
                expects_reply,
            } => Self::Started {
                chat_id,
                message_id,
                expects_reply,
            },
            StreamEvent::Submitted {
                chat_id,
                message_id,
            } => Self::Submitted {
                chat_id,
                message_id,
            },
            StreamEvent::Admitted {
                chat_id,
                message_id,
            } => Self::Admitted {
                chat_id,
                message_id,
            },
            StreamEvent::Content {
                content,
                thinking,
                mate,
            } => Self::Content {
                content,
                thinking,
                mate,
            },
            StreamEvent::Completed {
                chat_id,
                message_id,
                content,
            } => Self::Completed {
                chat_id,
                message_id,
                content,
            },
            StreamEvent::Status { message } => Self::Status { message },
        }
    }
}

impl From<AccessDenial> for AccessDenialRecord {
    fn from(value: AccessDenial) -> Self {
        match value {
            AccessDenial::Expired => Self::Expired,
            AccessDenial::ScopeRevoked => Self::ScopeRevoked,
            AccessDenial::ChatUnavailable { chat_id } => Self::ChatUnavailable { chat_id },
        }
    }
}

impl From<SessionEvent> for SessionEventRecord {
    fn from(value: SessionEvent) -> Self {
        match value {
            SessionEvent::SignedOut => Self::SignedOut,
            SessionEvent::Restored { display_name } => Self::Restored { display_name },
            SessionEvent::Admitted {
                username,
                expires_at,
            } => Self::Admitted {
                username,
                expires_at,
            },
            SessionEvent::Expired => Self::Expired,
            SessionEvent::AccessDenied(denial) => Self::AccessDenied {
                denial: denial.into(),
            },
        }
    }
}

impl From<SyncPhase> for SyncPhaseRecord {
    fn from(value: SyncPhase) -> Self {
        match value {
            SyncPhase::LastChat => Self::LastChat,
            SyncPhase::RecentChats => Self::RecentChats,
            SyncPhase::ChatContent => Self::ChatContent,
        }
    }
}

impl From<ViewErrorKind> for ViewErrorKindRecord {
    fn from(value: ViewErrorKind) -> Self {
        match value {
            ViewErrorKind::Invalid => Self::Invalid,
            ViewErrorKind::Crypto => Self::Crypto,
            ViewErrorKind::Authentication => Self::Authentication,
            ViewErrorKind::TwoFactorRequired => Self::TwoFactorRequired,
            ViewErrorKind::SignupRequired => Self::SignupRequired,
            ViewErrorKind::Unavailable { code } => Self::Unavailable { code },
            ViewErrorKind::Locked => Self::Locked,
            ViewErrorKind::Offline => Self::Offline,
            ViewErrorKind::Forbidden => Self::Forbidden,
            ViewErrorKind::Expired => Self::Expired,
            ViewErrorKind::Cancelled => Self::Cancelled,
            ViewErrorKind::Io => Self::Io,
            ViewErrorKind::Protocol => Self::ProtocolError,
            ViewErrorKind::Conflict => Self::Conflict,
        }
    }
}

impl From<ViewEvent> for ViewEventRecord {
    fn from(event: ViewEvent) -> Self {
        match event {
            ViewEvent::Session(event) => Self::Session {
                event: event.into(),
            },
            ViewEvent::SyncProgress { phase, received } => Self::SyncProgress {
                phase: phase.into(),
                received,
            },
            ViewEvent::ChatList { rows, completeness } => Self::ChatList {
                rows: rows.into_iter().map(Into::into).collect(),
                completeness: completeness.into(),
            },
            ViewEvent::ChatWindow { request, window } => Self::ChatWindow {
                request: request.0,
                window: window.into(),
            },
            ViewEvent::ChatUnavailable { chat_id } => Self::ChatUnavailable { chat_id },
            ViewEvent::ChatOpenFailed {
                request,
                chat_id,
                error,
            } => Self::ChatOpenFailed {
                request: request.0,
                chat_id,
                error: error.into(),
            },
            ViewEvent::MessageUpdated {
                request,
                chat_id,
                message,
            } => Self::MessageUpdated {
                request: request.0,
                chat_id,
                message: message.into(),
            },
            ViewEvent::Stream {
                request,
                chat_id,
                event,
            } => Self::Stream {
                request: request.0,
                chat_id,
                event: event.into(),
            },
            ViewEvent::Status { message } => Self::Status { message },
            ViewEvent::Failed { error } => Self::Failed {
                error: error.into(),
            },
            ViewEvent::Done => Self::Done,
        }
    }
}
