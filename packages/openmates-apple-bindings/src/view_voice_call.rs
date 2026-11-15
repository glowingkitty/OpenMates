//! UniFFI export of the shared voice-call activity clock and the call
//! start/end transcript notices. Marshalling only: the counting/dimming rules
//! live in `openmates_sdk::client::voice_call_activity` and the notice
//! content, validation and deterministic ids in
//! `openmates_sdk::client::voice_call_lifecycle` (mirrors of web `voiceCall.ts`
//! and `voiceCallMessages.ts`). Spec `video-call` (`video-call.chat.call-events`).
use crate::CoreError;
use openmates_sdk::client::voice_call_activity::{
    BillingActivity, VoiceCallActivityClock, VoiceCallActivitySnapshot, parse_billing_activity,
};
use openmates_sdk::client::voice_call_lifecycle::{
    VoiceCallAction, VoiceCallLifecycleEvent, parse_notice,
};
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

#[cfg(test)]
#[path = "view_voice_call_tests.rs"]
mod tests;
