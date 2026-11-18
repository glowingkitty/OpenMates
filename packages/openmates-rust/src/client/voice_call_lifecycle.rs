//! Voice-call start/end transcript notices shared by the native shells.
//! Builds and parses the client-written `role: "system"` call notice content
//! and its deterministic message id exactly like the web
//! (`voiceCallMessages.ts` `recordCallLifecycle`, `voiceCallLifecycleEvent.ts`),
//! pinned by `tests/fixtures/ts_voice_call_lifecycle.json`. Encryption and send
//! stay on the existing system-message path.
//! Voice-call lifecycle system messages: content JSON, deterministic message id
//! and the "is this a call notice" parser. Mirrors
//! `frontend/packages/ui/src/services/voiceCallLifecycleEvent.ts`
//! (`parseVoiceCallHistoryEvent`, `voiceCallLifecycleMessageId`) and
//! `voiceCallMessages.ts` (`recordCallLifecycle`). Spec: `client-core`.
//!
//! Invariants: content key order is `schema_version, type, action, call_id,
//! created_at, active_elapsed_seconds` (the web `JSON.stringify` order); seconds
//! are floored; the message id depends only on call id and action so duplicate
//! closes and retries are idempotent. Parsing is as strict as the web: only
//! `system` messages with schema 1, a valid call id, positive integer
//! `created_at` and a non-negative integer `active_elapsed_seconds` are notices.
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Largest integer JavaScript represents exactly (`Number.isSafeInteger`).
const MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;

/// Lifecycle action of a call notice.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum VoiceCallAction {
    /// The call was admitted.
    Started,
    /// The call finished.
    Ended,
}

impl VoiceCallAction {
    fn as_str(self) -> &'static str {
        match self {
            Self::Started => "started",
            Self::Ended => "ended",
        }
    }
}

/// Why a lifecycle event cannot be built.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VoiceCallLifecycleError {
    /// Call id is not `[A-Za-z0-9_-]{8,128}`.
    InvalidCallId,
    /// `created_at` is not a positive safe integer.
    InvalidCreatedAt,
    /// Elapsed seconds are negative or not finite.
    InvalidElapsed,
}

impl std::fmt::Display for VoiceCallLifecycleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            Self::InvalidCallId => "invalid voice call id",
            Self::InvalidCreatedAt => "invalid voice call created_at",
            Self::InvalidElapsed => "invalid voice call elapsed seconds",
        })
    }
}

impl std::error::Error for VoiceCallLifecycleError {}

/// One call notice (`type: "voice_call"` system message content). A plain
/// serde struct: Deserialize does not validate; use [`parse_notice`].
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VoiceCallLifecycleEvent {
    #[serde(rename = "schema_version")]
    schema_version: u8,
    #[serde(rename = "type")]
    kind: String,
    /// Started or ended.
    pub action: VoiceCallAction,
    /// Call id.
    pub call_id: String,
    /// Unix seconds.
    pub created_at: i64,
    /// Floored active seconds; the web always writes it, `None` omits the key.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub active_elapsed_seconds: Option<u64>,
}

fn valid_call_id(id: &str) -> bool {
    (8..=128).contains(&id.len())
        && id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

impl VoiceCallLifecycleEvent {
    /// Validates like `recordCallLifecycle` and floors the elapsed seconds.
    pub fn new(
        action: VoiceCallAction,
        call_id: &str,
        created_at: i64,
        active_elapsed_seconds: f64,
    ) -> Result<Self, VoiceCallLifecycleError> {
        if !valid_call_id(call_id) {
            return Err(VoiceCallLifecycleError::InvalidCallId);
        }
        if created_at <= 0 || created_at > MAX_SAFE_INTEGER {
            return Err(VoiceCallLifecycleError::InvalidCreatedAt);
        }
        if !active_elapsed_seconds.is_finite() || active_elapsed_seconds < 0.0 {
            return Err(VoiceCallLifecycleError::InvalidElapsed);
        }
        Ok(Self {
            schema_version: 1,
            kind: "voice_call".to_owned(),
            action,
            call_id: call_id.to_owned(),
            created_at,
            active_elapsed_seconds: Some(active_elapsed_seconds.floor() as u64),
        })
    }

    /// Content JSON exactly as the web writes it.
    pub fn to_content_json(&self) -> String {
        // Plain struct of strings and integers: serialisation cannot fail.
        serde_json::to_string(self).unwrap_or_default()
    }

    /// Deterministic message id for this event.
    pub fn message_id(&self) -> String {
        lifecycle_message_id(&self.call_id, self.action)
    }
}

/// `voiceCallLifecycleMessageId`: start sorts before and end after the call's
/// turns. The web id does not include the chat id.
pub fn lifecycle_message_id(call_id: &str, action: VoiceCallAction) -> String {
    let prefix = match action {
        VoiceCallAction::Started => "00000000",
        VoiceCallAction::Ended => "ffffffff",
    };
    format!("{prefix}-voice-call-{call_id}-{}", action.as_str())
}

fn safe_positive_int(v: &Value) -> Option<i64> {
    let n = v.as_i64().or_else(|| {
        let f = v.as_f64()?;
        (f.fract() == 0.0 && f.abs() <= MAX_SAFE_INTEGER as f64).then_some(f as i64)
    })?;
    (n.abs() <= MAX_SAFE_INTEGER).then_some(n)
}

/// What the web renders as a call notice: `None` for non-system roles, invalid
/// JSON or any other schema.
pub fn parse_notice(role: &str, content: &str) -> Option<VoiceCallLifecycleEvent> {
    if role != "system" {
        return None;
    }
    let v: Value = serde_json::from_str(content).ok()?;
    if safe_positive_int(v.get("schema_version")?)? != 1 || v.get("type")?.as_str()? != "voice_call"
    {
        return None;
    }
    let action = match v.get("action")?.as_str()? {
        "started" => VoiceCallAction::Started,
        "ended" => VoiceCallAction::Ended,
        _ => return None,
    };
    let call_id = v.get("call_id")?.as_str()?;
    let created_at = safe_positive_int(v.get("created_at")?).filter(|n| *n > 0)?;
    let elapsed = safe_positive_int(v.get("active_elapsed_seconds")?).filter(|n| *n >= 0)?;
    if !valid_call_id(call_id) {
        return None;
    }
    Some(VoiceCallLifecycleEvent {
        schema_version: 1,
        kind: "voice_call".to_owned(),
        action,
        call_id: call_id.to_owned(),
        created_at,
        active_elapsed_seconds: Some(elapsed as u64),
    })
}

#[cfg(test)]
#[path = "voice_call_lifecycle_tests.rs"]
mod tests;
