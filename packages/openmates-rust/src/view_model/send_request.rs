//! A view-model send with per-turn options and a delivery receipt: PII
//! detection on or off, a volatile (incognito) first turn, a new chat's slug,
//! caller-reserved chat and user-message ids, and the turn's status (completed,
//! waiting for the user, queued behind an active reply) with its ids and queue
//! position, plus the composer's attachments, un-redacted PII values and
//! shell-made PII mappings. Same events and cancel as `send_flows::send`. Mirrors the web and
//! Apple composers' send options; plan `apple-client-core-migration` A5, spec
//! `client-core` and `features/chat-queued-followups`.
use super::{
    ChatWindowRecord, RequestId,
    actor_host::ViewHost,
    send_flows::{ClientDispatch, TurnDispatch},
};
use crate::{
    client::{
        ReservedTurnIds, SendEmbed, SendOptions, SendOutcome, SendPiiMapping, SendQueueMode,
        SendStatus, VoiceCallTurn,
    },
    error::{Error, Result},
    local_cache::ByteStore,
    privacy::PiiExclusions,
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// The shell's options of one turn. `Default` is today's plain send: PII
/// detection on, saved chat, no slug, core-minted ids.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SendTurnOptions {
    /// Replace detected personal data with placeholders before the turn
    /// leaves the device (the mappings are stored encrypted with the message).
    pub pii_detection: bool,
    /// A volatile chat: nothing is stored on the server or in the cache.
    /// Only a first turn (no chat id) is supported.
    pub incognito: bool,
    /// The encrypted slug of a new saved chat.
    pub slug: Option<String>,
    /// Ids the shell reserved for this turn (`ReservedTurnIds`).
    pub reserved: ReservedTurnIds,
    /// Embeds the composer attaches (uploads, pasted code/text, recordings,
    /// URL previews, stored references). The core appends their reference
    /// blocks, encrypts and wraps them; no key leaves the core.
    pub embeds: Vec<SendEmbed>,
    /// Values the user un-redacted before sending (left in clear).
    pub pii_exclusions: PiiExclusions,
    /// Placeholders the shell already wrote, with their originals.
    pub pii_mappings: Vec<SendPiiMapping>,
    /// The Project this turn belongs to (canonical UUID). Applies to a new
    /// chat, a continuation and an edit.
    pub project_id: Option<String>,
    /// The turn is a live voice call utterance (saved personal chats only).
    pub voice_call: Option<VoiceCallTurn>,
}

impl Default for SendTurnOptions {
    fn default() -> Self {
        Self {
            pii_detection: true,
            incognito: false,
            slug: None,
            reserved: ReservedTurnIds::default(),
            embeds: Vec::new(),
            pii_exclusions: PiiExclusions::default(),
            pii_mappings: Vec::new(),
            project_id: None,
            voice_call: None,
        }
    }
}

impl SendTurnOptions {
    /// Refuse option combinations before anything is shown or sent.
    ///
    /// # Errors
    /// `Invalid` for an incognito continuation, a slug or reserved chat id
    /// with an existing chat, a slug on a volatile chat, or a malformed
    /// reserved id, or malformed attachments, exclusions or PII mappings.
    pub(super) fn check(&self, chat_id: Option<&str>) -> Result<()> {
        if chat_id.is_some() && self.incognito {
            return Err(Error::Invalid(
                "Incognito continuation is not supported yet; start a new incognito chat.",
            ));
        }
        if chat_id.is_some() && (self.slug.is_some() || self.reserved.chat_id.is_some()) {
            return Err(Error::Invalid(
                "A slug or reserved chat ID applies only to a new chat.",
            ));
        }
        if self.incognito && self.slug.is_some() {
            return Err(Error::Invalid("Volatile chats cannot have a saved slug."));
        }
        self.reserved.check_format()?;
        // The client checks the same rules again; here they fail before the
        // optimistic message is shown.
        self.send_options().validate()
    }

    /// The client options of this turn (the dispatcher adds the actor's
    /// Memory-write opt-in and server region).
    pub(super) fn send_options(&self) -> SendOptions {
        let reserved = (self.reserved != ReservedTurnIds::default()).then(|| self.reserved.clone());
        SendOptions {
            pii_detection: self.pii_detection,
            incognito: self.incognito,
            slug: self.slug.clone(),
            reserved_ids: reserved,
            embeds: self.embeds.clone(),
            pii_exclusions: self.pii_exclusions.clone(),
            pii_mappings: self.pii_mappings.clone(),
            project_id: self.project_id.clone(),
            voice_call: self.voice_call.clone(),
            ..SendOptions::default()
        }
    }
}

/// Delivery facts of one finished dispatch (`SendOutcome` without content).
#[derive(Clone, PartialEq, Eq)]
pub(super) struct TurnSummary {
    pub(super) status: SendStatus,
    pub(super) chat_id: String,
    pub(super) user_message_id: Option<String>,
    pub(super) assistant_message_id: Option<String>,
    pub(super) queue_mode: Option<SendQueueMode>,
    pub(super) queue_revision: Option<u64>,
}

impl TurnSummary {
    /// The ids and queue position of `outcome`; no message content.
    pub(super) fn from_outcome(outcome: &SendOutcome) -> Self {
        Self {
            status: outcome.status,
            chat_id: outcome.chat_id.clone(),
            user_message_id: outcome.user_message_id.clone(),
            assistant_message_id: outcome.message_id.clone(),
            queue_mode: outcome.queue_mode,
            queue_revision: outcome.queue_revision,
        }
    }
}

/// What [`send_with`] returns: the sent chat's window plus the turn's
/// delivery facts.
#[derive(Clone, PartialEq)]
pub struct SendReceipt {
    /// The sent chat's window (`Canonical`).
    pub window: ChatWindowRecord,
    /// `Completed`, `WaitingForUser` (the assistant asks a question) or
    /// `Queued` (saved behind an active reply; no assistant reply yet).
    pub status: SendStatus,
    /// The turn's chat (the reserved or new id for a new chat).
    pub chat_id: String,
    /// The user message id.
    pub user_message_id: Option<String>,
    /// The assistant reply id; `None` while queued and for team sends.
    pub assistant_message_id: Option<String>,
    /// How a queued turn waits (`FollowUp` or `Steer`); `None` unless queued.
    pub queue_mode: Option<SendQueueMode>,
    /// The queued turn's revision, for later edits of the queued message.
    pub queue_revision: Option<u64>,
}

/// [`send`](super::send) with per-turn `options`; returns the window and the
/// delivery receipt. Events and cancel are those of `send`: the optimistic
/// user message (under the reserved message id when one is given), the
/// stream, the sent window and the chat list.
///
/// # Errors
/// `Invalid` for refused option combinations or a non-canonical reserved id
/// (both before anything is shown); `Conflict` when a reserved id already
/// exists (after the optimistic message, which then shows `Failed`);
/// all errors of `send`; `Protocol` when the client reports no delivery facts.
pub fn send_with<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: Option<String>,
    text: String,
    options: SendTurnOptions,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<SendReceipt>> {
    Box::pin(async move {
        options.check(chat_id.as_deref())?;
        let mut dispatch = ClientDispatch::new(host.core(), options);
        receipt(host, request, chat_id, text, sink, cancel, &mut dispatch).await
    })
}

/// Run the turn with `dispatch` and join its window with its summary.
pub(super) async fn receipt<S: ByteStore + 'static, H: ViewHost<S>, D: TurnDispatch>(
    host: &mut H,
    request: RequestId,
    chat_id: Option<String>,
    text: String,
    sink: &H::Sink,
    cancel: &CancellationToken,
    dispatch: &mut D,
) -> Result<SendReceipt> {
    let window = host
        .core_mut()
        .send_turn(request, chat_id, text, sink, cancel, dispatch)
        .await?;
    let summary = dispatch.take_summary().ok_or(Error::Protocol)?;
    Ok(SendReceipt {
        window,
        status: summary.status,
        chat_id: summary.chat_id,
        user_message_id: summary.user_message_id,
        assistant_message_id: summary.assistant_message_id,
        queue_mode: summary.queue_mode,
        queue_revision: summary.queue_revision,
    })
}
