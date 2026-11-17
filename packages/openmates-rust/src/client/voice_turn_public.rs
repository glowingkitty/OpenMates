//! Public facade of the voice-call turn split for shells that own the socket
//! (the web shared Worker + page). Browser binding glue; mirrors nothing in
//! npm. Begin builds the snapshot frame, prepare consumes the snapshot result,
//! commit returns the `chat_turn_admit` payload; sends nothing. Chat key,
//! wrapper and baseline are derived inside the core, never passed by a shell.
//! Spec: `specifications/features/voice-calls`.
use super::send::voice_turn::PreparedVoiceTurn;
use super::{Client, Error, Result, SendOptions, VoiceCallTurn, VoiceHeardBoundary};
use serde_json::Value;

/// Snapshot request the page must send on its socket.
pub struct VoiceTurnFrame {
    /// Request id the snapshot result must echo.
    pub request_id: String,
    /// Payload of the `personal_send_context_snapshot` frame.
    pub frame: Value,
}

/// Opaque text-independent half of a turn. Holds decrypted context in
/// zeroizing fields; dropping it discards the turn and emits nothing.
pub struct VoiceTurnPrepared(PreparedVoiceTurn);

/// Committed final transcript: nothing was sent. Contains ciphertext only.
pub struct VoiceTurnCommit {
    /// Payload of the `chat_turn_admit` frame the page sends.
    pub admit: Value,
    /// Encrypted user message object for the local row write.
    pub user_message: Value,
    /// Whether the turn asks for an AI reply.
    pub wait_ai: bool,
}

impl Client {
    /// Build the snapshot frame for `turn_id` (also the user message id).
    pub fn voice_turn_begin(&self, chat_id: &str, turn_id: &str) -> VoiceTurnFrame {
        let (request_id, frame) = self.voice_turn_snapshot_frame(chat_id, turn_id);
        VoiceTurnFrame { request_id, frame }
    }

    /// Validate the snapshot result and run the text-independent stage.
    ///
    /// # Errors
    /// See `prepare_voice_turn`: Team chat, mismatched or unsuccessful result.
    pub async fn voice_turn_prepare(
        &self,
        chat_id: &str,
        turn_id: &str,
        request_id: &str,
        snapshot_result: Value,
    ) -> Result<VoiceTurnPrepared> {
        self.prepare_voice_turn(chat_id, turn_id, request_id, snapshot_result)
            .await
            .map(VoiceTurnPrepared)
    }

    /// Run the text-dependent stage for the final transcript. `created_at`
    /// (seconds) is the time of the page's optimistic row; the admitted row
    /// keeps it, `None` stamps the commit time.
    ///
    /// # Errors
    /// `Error::Invalid` for an empty transcript or call id; see
    /// `commit_voice_turn_from_state` for the rest.
    pub async fn voice_turn_commit(
        &mut self,
        prepared: VoiceTurnPrepared,
        turn_id: &str,
        call_id: &str,
        heard_boundary: Option<VoiceHeardBoundary>,
        final_text: &str,
        created_at: Option<u64>,
    ) -> Result<VoiceTurnCommit> {
        if final_text.trim().is_empty() || call_id.is_empty() {
            return Err(Error::Invalid(
                "A voice turn needs a transcript and a call id.",
            ));
        }
        let options = SendOptions {
            voice_call: Some(VoiceCallTurn {
                call_id: call_id.into(),
                turn_id: turn_id.into(),
                heard_boundary,
            }),
            ..SendOptions::default()
        };
        let done = self
            .commit_voice_turn_from_state(prepared.0, final_text, created_at, &options)
            .await?;
        Ok(VoiceTurnCommit {
            admit: done.admit.into_inner(),
            user_message: done.user_message.into_inner(),
            wait_ai: done.wait_ai,
        })
    }
}
