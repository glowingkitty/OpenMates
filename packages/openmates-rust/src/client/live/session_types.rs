//! Types of the sans-I/O [`super::session::LiveSession`]: what the host feeds in and the
//! [`Action`]s the session asks it to perform.

use super::engine::SealedUpdate;
use serde_json::Value;

/// Save state shown in the header.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    /// Everything acknowledged by the server.
    Saved,
    /// Local changes wait for an acknowledgement.
    Saving,
    /// No connection.
    Offline,
    /// The server allows viewing only.
    ReadOnly,
    /// Access was removed; the item is closed.
    AccessRevoked,
}

impl Status {
    /// Wire string of the `liveStatus` event.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Saved => "saved",
            Self::Saving => "saving",
            Self::Offline => "offline",
            Self::ReadOnly => "read_only",
            Self::AccessRevoked => "access_revoked",
        }
    }
}

/// Event for the shell (`liveRemoteUpdate`, `liveView`, `livePresence`, `liveStatus`).
#[derive(Clone, Debug, PartialEq)]
pub enum Event {
    /// Plain Yjs bytes the JS mirror applies (documents and code).
    RemoteUpdate {
        /// Item id.
        item_id: String,
        /// Plain Yjs v1 update.
        bytes: Vec<u8>,
    },
    /// New view model (sheets and decks).
    View {
        /// Item id.
        item_id: String,
        /// View model.
        view: Value,
    },
    /// The present peers (expired ones removed).
    Presence {
        /// Item id.
        item_id: String,
        /// Peer presence payloads.
        peers: Value,
    },
    /// Save state.
    Status {
        /// Item id.
        item_id: String,
        /// New state.
        status: Status,
    },
    /// An editor lost access with pending work, which can be downloaded locally.
    PrivateCopy {
        /// The item whose edits are recovered.
        item_id: String,
        /// The latest pending message ID identifies the same draft in memory and on disk.
        copy_id: String,
        /// The kind supplies the file extension for the local download.
        kind: super::LiveItemKind,
        /// The replica's text, including edits that never reached the server.
        text: String,
    },
    /// A stored version was written (session end, leaving the editor): the read view and
    /// the version timeline show it at once instead of waiting for the embed to refetch.
    VersionWritten {
        /// Item id.
        item_id: String,
        /// The new stored version number.
        version: i64,
        /// The item's text form as written (document HTML, code, sheet table, deck markup).
        text: String,
    },
}

/// One version to write through the user-revisions path.
#[derive(Clone, Debug, PartialEq)]
pub struct CheckpointRequest {
    /// Item (embed) id.
    pub item_id: String,
    /// The item's current text form.
    pub text: String,
    /// Version the write is based on; `None` before the first conflict answer.
    pub base_version: Option<i64>,
    /// `session`, `assistant`, `restore`, `named` or `commit`.
    pub version_kind: &'static str,
    /// Historical source of a restore checkpoint.
    pub restored_from: Option<i64>,
    /// User ids that edited since the last checkpoint.
    pub contributors: Vec<String>,
}

/// Something the host must do for the session.
#[derive(Clone, Debug, PartialEq)]
pub enum Action {
    /// Send a WebSocket frame `{"type", "payload"}`.
    Send {
        /// Message type.
        message_type: &'static str,
        /// Payload object.
        payload: Value,
    },
    /// Deliver an event to the shell.
    Emit(Event),
    /// Store the item's outbox in the core cache (replaces the stored list).
    PersistOutbox {
        /// Item id.
        item_id: String,
        /// Unacknowledged updates, oldest first.
        entries: Vec<SealedUpdate>,
    },
    /// Resolve the embed key and epoch, then call `provide_key`. `stale` asks for a newer
    /// epoch than the one in use (after `key_epoch_stale`).
    NeedKey {
        /// Item id.
        item_id: String,
        /// A newer epoch is required.
        stale: bool,
    },
    /// The log is empty: read the embed's current text form, then call `provide_content`.
    NeedContent {
        /// Item id.
        item_id: String,
    },
    /// Write a version, then report with `checkpoint_result`.
    WriteCheckpoint(CheckpointRequest),
    /// An assistant change carries only `base_version`: read that version's text form through
    /// the embed version read path, then call `provide_assistant_base` (or
    /// `fail_assistant_base` when the version cannot be read).
    AssistantNeedBase {
        /// Embed id.
        embed_id: String,
        /// Assistant turn.
        turn_id: String,
        /// Version the assistant read.
        base_version: i64,
    },
    /// `POST /v1/embeds/{embed_id}/assistant-change-outcome` with this JSON body.
    PostAssistantOutcome {
        /// Embed id.
        embed_id: String,
        /// `{turn_id, outcome, details}`.
        body: Value,
    },
    /// An `embed_assistant_change` arrived for an item that is not open. Open it (the server
    /// parks the change meanwhile), then feed `frame` to `on_frame` again as
    /// `embed_assistant_change`; close the item after its update is acknowledged.
    AssistantChangeNotOpen {
        /// Embed id.
        embed_id: String,
        /// The original frame payload.
        frame: Value,
    },
}

/// Answer of a checkpoint write.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CheckpointResult {
    /// Written as this version.
    Written(i64),
    /// 409: the server's current version. Retried on it (the live doc holds everything).
    Conflict(i64),
    /// Any other failure; tried again after the next idle period.
    Failed,
}

/// When to write a version. Pure so the timeline lane can supply its own policy.
pub trait CheckpointPolicy: Send {
    /// `true` when a checkpoint is due: `dirty_since` is the time of the first edit not
    /// yet in a version, `last_edit` the last edit (milliseconds).
    fn due(&self, now_ms: u64, dirty_since: u64, last_edit: u64) -> bool;
}

/// Default policy: the timeline's session rule (`live/timeline.rs`): 3 idle minutes, or 30
/// minutes of continuous editing.
#[derive(Clone, Copy, Debug, Default)]
pub struct IdleCheckpointPolicy;

impl CheckpointPolicy for IdleCheckpointPolicy {
    fn due(&self, now_ms: u64, dirty_since: u64, last_edit: u64) -> bool {
        use super::timeline::{SESSION_IDLE_MS, SESSION_MAX_MS};
        now_ms.saturating_sub(last_edit) >= SESSION_IDLE_MS
            || now_ms.saturating_sub(dirty_since) >= SESSION_MAX_MS
    }
}
