//! Send with per-turn options on `ViewModelCore`: PII detection on or off, an
//! incognito first turn, a new chat's slug, caller-reserved chat and
//! user-message ids, and the delivery receipt (completed, waiting for the
//! user, queued with its mode and revision), the composer's attachments,
//! un-redacted PII values and shell-made PII mappings, over
//! `openmates_sdk::view_model::begin_send_with` (`view_send_stream.rs`).
//! Bindings only marshal. Plan
//! `apple-client-core-migration` A5; spec `client-core`.
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use crate::view_record_details::PiiMappingRecord;
use crate::view_send::SendSettings;
use crate::view_send_attachments::{SendEmbedRecord, exclusions, pii_mapping};
use crate::{CoreError, view_records::ChatWindowViewRecord};
use openmates_sdk::client::{
    MachineProjectDecision, ReservedTurnIds, SendQueueMode, SendStatus, VoiceCallTurn, VoiceHeardBoundary,
};
use openmates_sdk::view_model::{RequestId, SendReceipt, SendTurnOptions};
use std::sync::Arc;

/// What the user heard of the assistant reply a voice call interrupted.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct VoiceHeardBoundaryRecord {
    /// The assistant message that was being spoken.
    pub assistant_message_id: String,
    /// Fully spoken segment sequences (0..=255; others are dropped).
    pub completed_sequences: Vec<u32>,
    /// The segment being spoken, if any (0..=255).
    pub active_sequence: Option<u32>,
    /// Milliseconds heard of the active segment (capped at one hour).
    pub active_offset_ms: u32,
}

/// Marks a turn as the user's utterance of a live voice call.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct VoiceCallTurnRecord {
    /// The call's id.
    pub call_id: String,
    /// The transcript's turn id (the user message id).
    pub turn_id: String,
    /// What the user heard of the previous reply, when it was interrupted.
    pub heard_boundary: Option<VoiceHeardBoundaryRecord>,
}

impl From<VoiceCallTurnRecord> for VoiceCallTurn {
    fn from(record: VoiceCallTurnRecord) -> Self {
        Self {
            call_id: record.call_id,
            turn_id: record.turn_id,
            heard_boundary: record.heard_boundary.map(|heard| VoiceHeardBoundary {
                assistant_message_id: heard.assistant_message_id,
                completed_sequences: heard.completed_sequences,
                active_sequence: heard.active_sequence,
                active_offset_ms: heard.active_offset_ms,
            }),
        }
    }
}

/// The options of one turn. All defaults give the plain `send`.
#[derive(Clone, PartialEq, Eq, uniffi::Record)]
pub struct SendOptionsRecord {
    /// Replace detected personal data with placeholders before the turn
    /// leaves the device; the mappings are stored encrypted with the message.
    #[uniffi(default = true)]
    pub pii_detection: bool,
    /// An incognito (volatile) chat: nothing is stored. Only a first turn
    /// (`chatId` nil) is supported; the chat is not in `ChatList`.
    #[uniffi(default = false)]
    pub incognito: bool,
    /// The slug of a new saved chat (`chatId` nil only).
    #[uniffi(default = None)]
    pub slug: Option<String>,
    /// The id of the NEW chat, reserved by Swift before the send (`chatId`
    /// nil only); canonical lowercase UUID, unknown to the core.
    #[uniffi(default = None)]
    pub reserved_chat_id: Option<String>,
    /// The user message's id, reserved by Swift; the optimistic message
    /// carries it from the first event. Canonical lowercase UUID.
    #[uniffi(default = None)]
    pub reserved_message_id: Option<String>,
    /// Embeds the composer attaches; the core appends their reference blocks
    /// to the text and encrypts them (a turn of attachments only may have an
    /// empty text).
    #[uniffi(default = [])]
    pub embeds: Vec<SendEmbedRecord>,
    /// Exact detected values the user un-redacted; they stay in clear.
    #[uniffi(default = [])]
    pub excluded_pii_originals: Vec<String>,
    /// Known placeholders whose mapping must not be re-applied.
    #[uniffi(default = [])]
    pub excluded_pii_placeholders: Vec<String>,
    /// Placeholders Swift already wrote (text or attachments) with their
    /// originals; stored encrypted with the message.
    #[uniffi(default = [])]
    pub pii_mappings: Vec<PiiMappingRecord>,
    /// The Project the turn belongs to (canonical lowercase UUID); applies to
    /// a new chat, a continuation and an edit.
    #[uniffi(default = None)]
    pub project_id: Option<String>,
    /// The turn is the user's utterance of a live voice call (saved personal
    /// chats only); the core adds the call fields to the message.
    #[uniffi(default = None)]
    pub voice_call: Option<VoiceCallTurnRecord>,
    /// Opt in to assistant-initiated Project creation: the core executes the
    /// request; set it only when the shell renders the created-Project card.
    #[uniffi(default = false)]
    pub project_create_requests: bool,
    /// The user's answer to a machine Project confirmation card, applied
    /// during the turn; nil leaves the card pending.
    #[uniffi(default = None)]
    pub machine_project: Option<MachineProjectDecisionRecord>,
    /// Opt in to assistant Project file jobs the core runs on this device;
    /// always-ask writes are declined with a notice.
    #[uniffi(default = false)]
    pub project_file_jobs: bool,
}

/// The shell's answer to a machine Project confirmation card.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum MachineProjectDecisionRecord {
    /// Create the Project on a machine; nil host picks the only machine.
    Confirm {
        /// Device hash of the chosen machine.
        host_device_hash: Option<String>,
    },
    /// The user does not want the Project.
    Decline,
    /// The shell cannot ask; reported to the assistant as a failure.
    Unavailable,
}

impl From<MachineProjectDecisionRecord> for MachineProjectDecision {
    fn from(record: MachineProjectDecisionRecord) -> Self {
        match record {
            MachineProjectDecisionRecord::Confirm { host_device_hash } => {
                Self::Confirm { host_device_hash }
            }
            MachineProjectDecisionRecord::Decline => Self::Decline,
            MachineProjectDecisionRecord::Unavailable => Self::Unavailable,
        }
    }
}

impl std::fmt::Debug for SendOptionsRecord {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        // Excluded originals are personal data: counts only.
        f.debug_struct("SendOptionsRecord")
            .field("pii_detection", &self.pii_detection)
            .field("incognito", &self.incognito)
            .field("slug", &self.slug)
            .field("reserved_chat_id", &self.reserved_chat_id)
            .field("reserved_message_id", &self.reserved_message_id)
            .field("embeds", &self.embeds)
            .field("excluded_pii_originals", &self.excluded_pii_originals.len())
            .field(
                "excluded_pii_placeholders",
                &self.excluded_pii_placeholders.len(),
            )
            .field("pii_mappings", &self.pii_mappings.len())
            .field("project_id", &self.project_id)
            .field("voice_call", &self.voice_call)
            .field("project_create_requests", &self.project_create_requests)
            .field("machine_project", &self.machine_project)
            .field("project_file_jobs", &self.project_file_jobs)
            .finish()
    }
}

impl From<SendOptionsRecord> for SendTurnOptions {
    fn from(record: SendOptionsRecord) -> Self {
        Self {
            pii_detection: record.pii_detection,
            incognito: record.incognito,
            slug: record.slug,
            reserved: ReservedTurnIds {
                chat_id: record.reserved_chat_id,
                message_id: record.reserved_message_id,
            },
            embeds: record.embeds.into_iter().map(Into::into).collect(),
            pii_exclusions: exclusions(
                record.excluded_pii_originals,
                record.excluded_pii_placeholders,
            ),
            pii_mappings: record.pii_mappings.into_iter().map(pii_mapping).collect(),
            project_id: record.project_id,
            voice_call: record.voice_call.map(Into::into),
            project_create_requests: record.project_create_requests,
            machine_project: record.machine_project.map(Into::into),
            project_file_jobs: record.project_file_jobs,
        }
    }
}

/// How a turn ended.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum SendStatusRecord {
    /// The assistant replied.
    Completed,
    /// The assistant asks the user a question before it goes on.
    WaitingForUser,
    /// Saved and queued behind an active reply of this chat; no reply yet.
    Queued,
}

/// How a queued turn waits.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum SendQueueModeRecord {
    /// Answered after the active reply.
    FollowUp,
    /// Steers the active reply at its next safe boundary.
    Steer,
}

/// The sent window and the turn's delivery facts.
#[derive(Clone, Debug, PartialEq, uniffi::Record)]
pub struct SendReceiptRecord {
    /// The sent chat's window (`Canonical`).
    pub window: ChatWindowViewRecord,
    /// How the turn ended.
    pub status: SendStatusRecord,
    /// The turn's chat id (the reserved or new id for a new chat).
    pub chat_id: String,
    /// The user message id.
    pub user_message_id: Option<String>,
    /// The assistant reply id; nil while queued and for team sends.
    pub assistant_message_id: Option<String>,
    /// Set only for `Queued`.
    pub queue_mode: Option<SendQueueModeRecord>,
    /// The queued message's revision (for later queued edits); `Queued` only.
    pub queue_revision: Option<u64>,
}

impl From<SendReceipt> for SendReceiptRecord {
    fn from(receipt: SendReceipt) -> Self {
        Self {
            window: ChatWindowViewRecord::from(receipt.window),
            status: match receipt.status {
                SendStatus::Completed => SendStatusRecord::Completed,
                SendStatus::WaitingForUser => SendStatusRecord::WaitingForUser,
                SendStatus::Queued => SendStatusRecord::Queued,
            },
            chat_id: receipt.chat_id,
            user_message_id: receipt.user_message_id,
            assistant_message_id: receipt.assistant_message_id,
            queue_mode: receipt.queue_mode.map(|mode| match mode {
                SendQueueMode::FollowUp => SendQueueModeRecord::FollowUp,
                SendQueueMode::Steer => SendQueueModeRecord::Steer,
            }),
            queue_revision: receipt.queue_revision,
        }
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// `send` with per-turn `options`; returns the sent window plus the
    /// delivery receipt. Same events (all carrying `request`), the same
    /// `cancelSend`, the same send settings (Memory writes, server region).
    /// With `reservedMessageId` the optimistic user message carries that id
    /// from the first event instead of a provisional one. Like `send`, only
    /// the admission runs on the actor; while the reply streams other
    /// commands are served (a second send into the chat returns `Queued`).
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` before anything is shown
    /// for an incognito turn into an existing chat, a slug or reserved chat id
    /// with `chatId`, a slug on an incognito chat; `Invalid` for a
    /// non-canonical reserved id or one equal to the chat id; `Invalid` before
    /// anything is shown for a malformed or duplicate embed id or type, empty
    /// or oversized embed content, a stored-reference embed in an incognito
    /// chat, or a malformed exclusion or PII mapping; `Conflict` when
    /// a reserved chat or message id already exists; otherwise as `send`.
    pub async fn send_with_options(
        &self,
        request: u64,
        chat_id: Option<String>,
        text: String,
        options: SendOptionsRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<SendReceiptRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            let settings = SendSettings::read(&shared);
            let options = SendTurnOptions::from(options);
            let receipt = shared
                .stream_send(token, settings, RequestId(request), chat_id, text, options)
                .await?;
            Ok(SendReceiptRecord::from(receipt))
        })
        .await
    }

    /// Edit user message `message_id` of personal chat `chat_id` with the
    /// options of `sendWithOptions` (embeds, PII exclusions and mappings,
    /// `projectId`, `reservedMessageId`): the core removes the message and
    /// every later one, reads the open window again, then sends `text` as
    /// `request`. The reply streams beside the actor like `sendWithOptions`;
    /// events, `cancelSend` and send settings are the same. A turn of
    /// attachments only may have an empty `text`. A failed send keeps the
    /// truncation.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` before anything changes
    /// for incognito, `slug` or `reservedChatId` (new-chat options), empty text
    /// without embeds, a non-canonical Project id, or malformed embeds,
    /// exclusions or PII mappings; `Invalid` for an assistant or unknown
    /// message; `Forbidden` in a team scope; otherwise as `sendWithOptions`.
    pub async fn edit_message_with_options(
        &self,
        request: u64,
        chat_id: String,
        message_id: String,
        text: String,
        options: SendOptionsRecord,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<SendReceiptRecord, CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            let settings = SendSettings::read(&shared);
            let options = SendTurnOptions::from(options);
            let receipt = shared
                .stream_edit(
                    token,
                    settings,
                    RequestId(request),
                    chat_id,
                    message_id,
                    text,
                    options,
                )
                .await?;
            Ok(SendReceiptRecord::from(receipt))
        })
        .await
    }
}
