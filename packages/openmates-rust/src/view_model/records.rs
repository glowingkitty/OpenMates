//! Plain owned records of the view-model boundary: chat list rows, messages,
//! embed references, chat windows and stream events. They replace the
//! `serde_json::Value` bags the terminal UI reads today (`Item.fields`) and are
//! shaped for later UniFFI export. Spec: `a2-design.md` (View model).
use super::error::ViewErrorKind;
use super::metadata::{ChatRowMetadata, MessageMetadata};

/// How trustworthy a published chat list is.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ListCompleteness {
    /// Restored from the local index; no network read has confirmed it yet.
    Cached,
    /// A network read delivered the first pages; older chats may be missing.
    Partial,
    /// The full inventory of the current scope was read.
    Complete,
}

/// Display state of a chat list row (`Item.status` of chat inventory items).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ChatRowStatus {
    /// An ordinary chat (empty core status).
    Ready,
    /// A chat that so far exists only as a draft.
    Draft,
    /// A chat whose key is not available in the current scope.
    Locked,
}

/// One row of the chat list.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChatListRow {
    /// Chat id.
    pub id: String,
    /// Display title, including draft and locked fallbacks.
    pub title: String,
    /// Exact decrypted title when one exists; `None` for untitled or locked chats.
    pub chat_list_title: Option<String>,
    /// Decrypted chat summary (empty when none).
    pub summary: String,
    /// Decrypted category (empty when none).
    pub category: String,
    /// Draft or locked state.
    pub status: ChatRowStatus,
    /// Creation time in unix milliseconds, when the row carries one.
    pub created_at: Option<i64>,
    /// Last update in unix milliseconds, when the row carries one.
    pub updated_at: Option<i64>,
    /// Server message version, when the row carries one.
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
    pub metadata: ChatRowMetadata,
}

/// Author role of a message.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MessageRole {
    /// Written by the account owner.
    User,
    /// Written by an assistant mate.
    Assistant,
    /// Written by the system.
    System,
}

/// Delivery state of a message inside a window.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MessageStatus {
    /// Stored message with final content.
    Complete,
    /// Assistant reply still being streamed.
    Streaming,
}

/// Delivery state of a user message the core added to the open window for
/// a running or ended send (lane L9). Stored messages carry none. The
/// `submitted` flags mirror the `Submitted` stream fence: once dispatch may
/// have committed, a shell must not resend the text automatically.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SendState {
    /// Shown before the server saw it.
    Sending,
    /// Dispatch may have committed; never resend automatically.
    Submitted,
    /// The server acknowledged persistence of the message.
    Delivered,
    /// The send failed; the text stays visible for a deliberate retry.
    Failed {
        /// Failure class.
        error: ViewErrorKind,
        /// Dispatch may have committed before the failure.
        submitted: bool,
    },
    /// The user cancelled the send or its reply.
    Cancelled {
        /// Dispatch may have committed before the cancel.
        submitted: bool,
    },
}

/// A decrypted chat message.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MessageRecord {
    /// Message id (client message id when the sender assigned one).
    pub id: String,
    /// Author role.
    pub role: MessageRole,
    /// Delivery state.
    pub status: MessageStatus,
    /// Message text after PII restoration.
    pub content: String,
    /// Mate display name; empty for the user.
    pub sender: String,
    /// Reasoning text; empty when none was stored.
    pub thinking: String,
    /// Embeds attached to the message.
    pub embeds: Vec<EmbedRef>,
    /// Send state of a user message of a running or ended send; `None` for
    /// stored messages.
    pub send_state: Option<SendState>,
    /// Stored facts of the message row (timestamps, ids, model, queue, PII).
    pub metadata: MessageMetadata,
}

/// Reference to a decrypted embed shown on a message or in a consent request.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EmbedRef {
    /// Embed id.
    pub id: String,
    /// Embed type (`fields.type`, else the core category); empty when unknown.
    pub kind: String,
    /// Owning app id (`app_id` or `app`); empty when none.
    pub app_id: String,
    /// Skill id (`skill_id` or `skill`); empty when none.
    pub skill_id: String,
    /// Display title.
    pub title: String,
    /// Description or summary; empty when none.
    pub description: String,
    /// Embed status such as `finished`; empty when none.
    pub status: String,
    /// The embed's metadata object serialized as JSON, until the embeds lane
    /// replaces it with typed content.
    pub data_json: String,
}

/// Where a chat window's data came from.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ChatWindowSource {
    /// Local cache only, no completed network read.
    Cached,
    /// Cache served while offline; read-only.
    CachedOffline,
    /// Authorized cache confirmed by the server; not a complete-history receipt.
    CacheSettled,
    /// First page of messages read from the network.
    FirstPage,
    /// Canonical read of the chat.
    Canonical,
    /// Window updated from a live event.
    Live,
    /// Window updated from a live event with authorized cached content; not
    /// a complete-history receipt.
    LiveSettled,
}

/// How personal data tokens in a window were restored.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PiiRestoration {
    /// Only mappings from the same page were applied.
    PageLocal,
    /// Mappings from every cached user row were applied.
    AllCachedUserRows,
}

/// The messages of one open chat.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChatWindowRecord {
    /// Chat id.
    pub chat_id: String,
    /// Display title.
    pub title: String,
    /// Decrypted category (empty when none).
    pub category: String,
    /// Messages, oldest first.
    pub messages: Vec<MessageRecord>,
    /// Origin of the data.
    pub source: ChatWindowSource,
    /// Whether older messages exist; `None` when unknown.
    pub has_more_before: Option<bool>,
    /// Whether newer messages exist than the last one shown; `None` when
    /// unknown (`Some(false)` for a complete canonical read).
    pub has_more_after: Option<bool>,
    /// Every message of the chat is in `messages`.
    pub history_complete: bool,
    /// A network refresh is still running.
    pub refreshing: bool,
    /// PII restoration scope applied to the messages.
    pub pii_restoration: PiiRestoration,
}

/// Progress of a send or a live assistant reply (mirror of `StreamUpdate`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StreamEvent {
    /// The assistant asks permission to use the listed items.
    Consent {
        /// Consent request id.
        request_id: String,
        /// Items the assistant wants to use.
        items: Vec<EmbedRef>,
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
    /// Dispatch may have committed; callers must not resend automatically.
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
