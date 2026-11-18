//! UniFFI export of the shared voice-call activity clock and the call
//! start/end transcript notices. Marshalling only: the counting/dimming rules
//! live in `openmates_sdk::client::voice_call_activity` and the notice
//! content, validation and deterministic ids in
//! `openmates_sdk::client::voice_call_lifecycle` (mirrors of web `voiceCall.ts`
//! and `voiceCallMessages.ts`). Spec `video-call` (`video-call.chat.call-events`).
use crate::CoreError;
use openmates_sdk::client::voice_call_activity::{
    parse_billing_activity, BillingActivity, VoiceCallActivityClock, VoiceCallActivitySnapshot,
};
use openmates_sdk::client::voice_call_lifecycle::{
    parse_notice, VoiceCallAction, VoiceCallLifecycleEvent,
};
use openmates_sdk::client::voice_call_media::{
    voice_call_stage_media, voice_call_stage_selection, VoiceCallMediaEmbed, VoiceCallMediaKind,
    VoiceCallMediaVariant, VoiceCallStageMedia,
};
use std::collections::HashMap;
use std::sync::Mutex;

/// One reading of the call clock.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Record)]
pub struct VoiceCallClockRecord {
    /// Whole seconds of server-confirmed (or not yet known) active time.
    pub active_elapsed_seconds: u64,
    /// True only after the server confirmed input and processing idle.
    pub dimmed: bool,
    /// Whether a server `billing_activity` frame has arrived yet.
    pub activity_known: bool,
}

impl From<VoiceCallActivitySnapshot> for VoiceCallClockRecord {
    fn from(snapshot: VoiceCallActivitySnapshot) -> Self {
        Self {
            active_elapsed_seconds: snapshot.active_elapsed_seconds,
            dimmed: snapshot.dimmed,
            activity_known: snapshot.activity_known,
        }
    }
}

/// Call clock owned by one live call. Time is passed in as `now_ms`.
#[derive(uniffi::Object)]
pub struct VoiceCallActivityClockHandle {
    clock: Mutex<VoiceCallActivityClock>,
}

impl Default for VoiceCallActivityClockHandle {
    fn default() -> Self {
        Self {
            clock: Mutex::new(VoiceCallActivityClock::new()),
        }
    }
}

impl VoiceCallActivityClockHandle {
    fn with<T>(&self, body: impl FnOnce(&mut VoiceCallActivityClock) -> T) -> T {
        // A poisoned lock only means an earlier caller panicked mid-update;
        // the clock holds plain numbers, so continuing with it is safe.
        let mut guard = self
            .clock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        body(&mut guard)
    }
}

#[uniffi::export]
impl VoiceCallActivityClockHandle {
    /// New clock: activity unknown, nothing accumulated.
    #[uniffi::constructor]
    pub fn new() -> Self {
        Self::default()
    }

    /// Applies a raw server frame for `call_id`. Returns false (and changes
    /// nothing) when the frame is not a well-formed `billing_activity` frame
    /// of this call.
    pub fn apply_frame_json(&self, call_id: String, now_ms: f64, json: String) -> bool {
        match parse_billing_activity(&json) {
            Some(frame) if frame.call_id == call_id => {
                self.with(|clock| clock.apply_billing_activity(now_ms, frame.activity));
                true
            }
            _ => false,
        }
    }

    /// Applies already-decoded server activity flags.
    pub fn apply_activity(&self, now_ms: f64, input_listening: bool, processing: bool) {
        self.with(|clock| {
            clock.apply_billing_activity(
                now_ms,
                BillingActivity {
                    input_listening,
                    processing,
                },
            )
        });
    }

    /// Accounts time up to `now_ms` and returns the reading.
    pub fn tick(&self, now_ms: f64) -> VoiceCallClockRecord {
        self.with(|clock| clock.tick(now_ms)).into()
    }

    /// Marks the call ended (both flags idle).
    pub fn finish(&self, now_ms: f64) {
        self.with(|clock| clock.finish(now_ms));
    }
}

/// Start or end of a call.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum VoiceCallNoticeAction {
    /// The call started.
    Started,
    /// The call ended.
    Ended,
}

/// A call notice ready to render or to write as a system message.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct VoiceCallNoticeRecord {
    /// Started or ended.
    pub action: VoiceCallNoticeAction,
    /// Call id.
    pub call_id: String,
    /// Unix seconds.
    pub created_at: i64,
    /// Floored active seconds.
    pub active_elapsed_seconds: Option<u64>,
    /// Deterministic message id (same as web).
    pub message_id: String,
    /// System-message content JSON exactly as the web writes it.
    pub content_json: String,
}

fn record(event: &VoiceCallLifecycleEvent) -> VoiceCallNoticeRecord {
    VoiceCallNoticeRecord {
        action: match event.action {
            VoiceCallAction::Started => VoiceCallNoticeAction::Started,
            VoiceCallAction::Ended => VoiceCallNoticeAction::Ended,
        },
        call_id: event.call_id.clone(),
        created_at: event.created_at,
        active_elapsed_seconds: event.active_elapsed_seconds,
        message_id: event.message_id(),
        content_json: event.to_content_json(),
    }
}

/// Parses a transcript message into a call notice; `None` for any message
/// the web would not render as a call notice.
#[uniffi::export]
pub fn voice_call_notice_from_message(
    role: String,
    content: String,
) -> Option<VoiceCallNoticeRecord> {
    parse_notice(&role, &content).as_ref().map(record)
}

/// Builds the start/end notice the shell writes when a call starts or ends.
///
/// # Errors
/// `CoreError::Invalid` for an invalid call id, creation time or elapsed time.
#[uniffi::export]
pub fn build_voice_call_notice(
    action: VoiceCallNoticeAction,
    call_id: String,
    created_at: i64,
    active_elapsed_seconds: f64,
) -> Result<VoiceCallNoticeRecord, CoreError> {
    let action = match action {
        VoiceCallNoticeAction::Started => VoiceCallAction::Started,
        VoiceCallNoticeAction::Ended => VoiceCallAction::Ended,
    };
    VoiceCallLifecycleEvent::new(action, &call_id, created_at, active_elapsed_seconds)
        .map(|event| record(&event))
        .map_err(|error| CoreError::Invalid {
            message: error.to_string(),
        })
}

/// Kind of a stage media item.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum VoiceCallStageMediaKind {
    /// Still image.
    Image,
    /// Video clip.
    Video,
}

/// Which stored file variant to fetch.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum VoiceCallStageMediaVariant {
    /// `files.original`.
    Original,
    /// `files.preview` (images only).
    Preview,
}

/// One embed handed to the stage policy: row fields plus decrypted content JSON.
#[derive(Clone, Debug, PartialEq, uniffi::Record)]
pub struct VoiceCallStageEmbedInput {
    /// Embed id.
    pub embed_id: String,
    /// Row-level app id.
    pub app_id: Option<String>,
    /// Row-level skill id.
    pub skill_id: Option<String>,
    /// Row-level embed type.
    pub embed_type: Option<String>,
    /// Row-level status.
    pub status: Option<String>,
    /// Decryption failed.
    pub decryption_failed: bool,
    /// Decryption pending.
    pub decryption_pending: bool,
    /// Decrypted content as a JSON object string.
    pub content_json: String,
}

/// A displayable stage item; the shell fetches and decrypts the file itself.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct VoiceCallStageMediaRecord {
    /// Owning embed id.
    pub embed_id: String,
    /// Image or video.
    pub kind: VoiceCallStageMediaKind,
    /// File variant to fetch.
    pub variant: VoiceCallStageMediaVariant,
    /// Object key of the encrypted file.
    pub s3_key: String,
    /// Object store base URL.
    pub s3_base_url: String,
    /// Declared mime type.
    pub mime_type: Option<String>,
}

/// Displayed-item choice after a resolve.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct VoiceCallStageSelectionRecord {
    /// Index to display; `None` leaves the stage unchanged.
    pub displayed_index: Option<u32>,
    /// A not-yet-presented item was chosen.
    pub fresh: bool,
    /// Ids to add to the presented set.
    pub newly_presented: Vec<String>,
}

fn media_record(item: VoiceCallStageMedia) -> VoiceCallStageMediaRecord {
    VoiceCallStageMediaRecord {
        embed_id: item.embed_id,
        kind: match item.kind {
            VoiceCallMediaKind::Image => VoiceCallStageMediaKind::Image,
            VoiceCallMediaKind::Video => VoiceCallStageMediaKind::Video,
        },
        variant: match item.variant {
            VoiceCallMediaVariant::Original => VoiceCallStageMediaVariant::Original,
            VoiceCallMediaVariant::Preview => VoiceCallStageMediaVariant::Preview,
        },
        s3_key: item.s3_key,
        s3_base_url: item.s3_base_url,
        mime_type: item.mime_type,
    }
}

/// Picks the generated media the call stage shows: `candidate_ids_newest_first`
/// are the call's media embed ids newest first. Embeds with unparseable
/// content JSON are treated as having no content (the web skips them too).
#[uniffi::export]
pub fn voice_call_stage_media_items(
    candidate_ids_newest_first: Vec<String>,
    embeds: Vec<VoiceCallStageEmbedInput>,
) -> Vec<VoiceCallStageMediaRecord> {
    let map: HashMap<String, VoiceCallMediaEmbed> = embeds
        .into_iter()
        .map(|e| {
            (
                e.embed_id.clone(),
                VoiceCallMediaEmbed {
                    embed_id: e.embed_id,
                    app_id: e.app_id,
                    skill_id: e.skill_id,
                    embed_type: e.embed_type,
                    status: e.status,
                    decryption_failed: e.decryption_failed,
                    decryption_pending: e.decryption_pending,
                    content: serde_json::from_str(&e.content_json)
                        .unwrap_or(serde_json::Value::Null),
                },
            )
        })
        .collect();
    voice_call_stage_media(&candidate_ids_newest_first, &map)
        .into_iter()
        .map(media_record)
        .collect()
}

/// Chooses which resolved item to display (web `refreshCallMedia` rule).
#[uniffi::export]
pub fn voice_call_stage_media_selection(
    item_embed_ids: Vec<String>,
    presented: Vec<String>,
    displayed_embed_id: Option<String>,
) -> VoiceCallStageSelectionRecord {
    // Selection only reads embed ids, so ids stand in for full items.
    let items: Vec<VoiceCallStageMedia> = item_embed_ids
        .into_iter()
        .map(|embed_id| VoiceCallStageMedia {
            embed_id,
            kind: VoiceCallMediaKind::Image,
            variant: VoiceCallMediaVariant::Original,
            s3_key: String::new(),
            s3_base_url: String::new(),
            mime_type: None,
        })
        .collect();
    let s = voice_call_stage_selection(&items, &presented, displayed_embed_id.as_deref());
    VoiceCallStageSelectionRecord {
        displayed_index: s.displayed_index,
        fresh: s.fresh,
        newly_presented: s.newly_presented,
    }
}

#[cfg(test)]
#[path = "view_voice_call_tests.rs"]
mod tests;
