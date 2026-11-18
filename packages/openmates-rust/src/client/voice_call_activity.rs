//! Voice-call activity clock shared by the native shells (Apple now; web via
//! wasm later). Mirrors the web call strip (`voiceCall.ts` billing_activity
//! handling): activity is unknown until the first server `billing_activity`
//! frame and the clock counts while unknown; once known it counts while the
//! server reports input listening or processing and dims only when the server
//! confirmed both idle. Local assistant playback is not an input. Pure state:
//! callers pass `now_ms`.
//! Voice-call billing-activity clock: pure state shared by the native shells.
//! Mirrors `frontend/packages/ui/src/services/voiceCall.ts` (`refreshClock`,
//! the `billing_activity` frame handler). Spec: `client-core`.
//!
//! Invariants: activity is unknown until the first server `billing_activity`
//! frame and an unknown call counts as active; once known the clock counts
//! while input is listening OR the server is processing and dims only when both
//! are idle. Local assistant playback is never an input. Time is accounted in
//! milliseconds and reported as whole seconds (floor), like the web.
use serde::{Deserialize, Serialize};

/// Server-confirmed activity from one `billing_activity` frame.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct BillingActivity {
    /// The server is listening to the caller's input.
    pub input_listening: bool,
    /// The server is processing a turn.
    pub processing: bool,
}

/// A parsed `billing_activity` frame (`call_id` plus both flags).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BillingActivityFrame {
    /// Call the frame belongs to; callers must compare it with the live call.
    pub call_id: String,
    /// The activity flags.
    pub activity: BillingActivity,
}

#[derive(Deserialize)]
struct RawFrame {
    #[serde(rename = "type")]
    kind: Option<String>,
    call_id: Option<String>,
    input_listening: Option<bool>,
    processing: Option<bool>,
}

/// Parses a frame; `None` when it is not a well-formed `billing_activity`
/// frame (the web ignores frames whose flags are not booleans).
pub fn parse_billing_activity(json: &str) -> Option<BillingActivityFrame> {
    let raw: RawFrame = serde_json::from_str(json).ok()?;
    if raw.kind.as_deref() != Some("billing_activity") {
        return None;
    }
    Some(BillingActivityFrame {
        call_id: raw.call_id?,
        activity: BillingActivity {
            input_listening: raw.input_listening?,
            processing: raw.processing?,
        },
    })
}

/// Clock reading returned by [`VoiceCallActivityClock::tick`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct VoiceCallActivitySnapshot {
    /// Whole seconds of accumulated active time.
    pub active_elapsed_seconds: u64,
    /// True only when the server confirmed both input and processing idle.
    pub dimmed: bool,
    /// Whether a server frame has been seen yet.
    pub activity_known: bool,
}

/// Accumulates active call time from server activity.
#[derive(Debug, Clone, Default)]
pub struct VoiceCallActivityClock {
    activity: Option<BillingActivity>,
    active_millis: f64,
    last_ms: Option<f64>,
}

impl VoiceCallActivityClock {
    /// New clock with unknown activity and no accumulated time.
    pub fn new() -> Self {
        Self::default()
    }

    fn advance(&mut self, now_ms: f64) {
        if let Some(last) = self.last_ms {
            let counting = self
                .activity
                .is_none_or(|a| a.input_listening || a.processing);
            if counting {
                self.active_millis += (now_ms - last).max(0.0);
            }
        }
        self.last_ms = Some(now_ms);
    }

    /// Applies a frame: accounts the time up to `now_ms` under the previous
    /// state first (as the web does), then stores the new activity.
    pub fn apply_billing_activity(&mut self, now_ms: f64, activity: BillingActivity) {
        self.advance(now_ms);
        self.activity = Some(activity);
    }

    /// Accounts time up to `now_ms` and returns the current reading.
    pub fn tick(&mut self, now_ms: f64) -> VoiceCallActivitySnapshot {
        self.advance(now_ms);
        VoiceCallActivitySnapshot {
            active_elapsed_seconds: (self.active_millis / 1000.0).floor() as u64,
            dimmed: self
                .activity
                .is_some_and(|a| !a.input_listening && !a.processing),
            activity_known: self.activity.is_some(),
        }
    }

    /// Marks the call ended: both flags idle (the web's `finish` state).
    pub fn finish(&mut self, now_ms: f64) {
        self.apply_billing_activity(
            now_ms,
            BillingActivity {
                input_listening: false,
                processing: false,
            },
        );
    }
}

#[cfg(test)]
#[path = "voice_call_activity_tests.rs"]
mod tests;
