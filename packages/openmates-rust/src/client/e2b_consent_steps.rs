//! Socket-free E2B upload consent steps for shells that own their WebSocket
//! (web Worker/wasm) and the native methods that share them.
//!
//! A step builds the encrypted system message and the frames the shell must
//! send, in order, without touching a socket. The shell sends the frames on its
//! one main socket and stores `message` (already encrypted) in its chat store.
//! Wire contract: `docs/plans/e2b-upload-consent/plan.yml` (`wire_contract`).
use super::e2b_consent::{ANSWER_FRAME, E2bConsentChoice, request_content, response_content};
use super::*;
use serde::Serialize;

/// One frame the shell must send over its WebSocket.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct E2bConsentFrame {
    /// Event name, e.g. `chat_system_message_added`.
    pub name: String,
    /// Event payload.
    pub payload: Value,
}

/// The persisted system message of a step (content stays encrypted at rest;
/// `content` is the plain JSON the local chat store shows).
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct E2bConsentMessage {
    /// Stable message id (`<request>-e2b-request` / `-e2b-response`).
    pub message_id: String,
    /// Chat the message belongs to.
    pub chat_id: String,
    /// Always `system`.
    pub role: &'static str,
    /// Plain system-message JSON content.
    pub content: String,
    /// Content encrypted with the chat key.
    pub encrypted_content: String,
    /// Creation time, seconds.
    pub created_at: u64,
    /// The request id this message belongs to.
    pub user_message_id: String,
}

/// Frames and message of one consent step.
#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct E2bConsentStep {
    /// Frames to send, in order.
    pub frames: Vec<E2bConsentFrame>,
    /// The encrypted system message those frames persist.
    pub message: E2bConsentMessage,
}

impl Client {
    fn e2b_system_step(
        &self,
        chat_id: &str,
        message_id: String,
        request_id: &str,
        key: &[u8; 32],
        content: Value,
        mut frames: Vec<E2bConsentFrame>,
    ) -> Result<E2bConsentStep> {
        let plain = content.to_string();
        let encrypted = crypto::encrypt_combined(&plain, key)?;
        let created_at = now_ms() / 1000;
        let mut payload = json!({"chat_id":chat_id,"message":{
            "message_id":message_id,"chat_id":chat_id,"role":"system","user_message_id":request_id,
            "encrypted_content":encrypted,"created_at":created_at,"status":"synced"}});
        if let Some(team) = self.team()? {
            payload["team_id"] = json!(team);
        }
        frames.push(E2bConsentFrame {
            name: "chat_system_message_added".to_owned(),
            payload,
        });
        Ok(E2bConsentStep {
            frames,
            message: E2bConsentMessage {
                message_id,
                chat_id: chat_id.to_owned(),
                role: "system",
                content: plain,
                encrypted_content: encrypted,
                created_at,
                user_message_id: request_id.to_owned(),
            },
        })
    }

    /// Build the encrypted request system message for a
    /// `request_e2b_upload_consent` frame `{request_id, chat_id, version}`.
    ///
    /// # Errors
    /// `Protocol` for a frame without a version, `Invalid` for missing identities.
    pub fn e2b_consent_request_step(
        &self,
        frame: &Value,
        key: &[u8; 32],
    ) -> Result<E2bConsentStep> {
        let chat = text(frame, "chat_id");
        let request = text(frame, "request_id");
        let version = frame
            .get("version")
            .and_then(Value::as_u64)
            .and_then(|v| u32::try_from(v).ok())
            .ok_or(Error::Protocol)?;
        let content = request_content(request, chat, version)?;
        self.e2b_system_step(
            chat,
            format!("{request}-e2b-request"),
            request,
            key,
            content,
            Vec::new(),
        )
    }

    /// Build the `e2b_upload_consent_answer` frame and the encrypted response
    /// system message for the user's choice.
    ///
    /// # Errors
    /// `Protocol` for an empty request or chat id.
    pub fn e2b_consent_answer_step(
        &self,
        chat_id: &str,
        request_id: &str,
        choice: E2bConsentChoice,
        key: &[u8; 32],
    ) -> Result<E2bConsentStep> {
        if request_id.is_empty() || chat_id.is_empty() {
            return Err(Error::Protocol);
        }
        let answer = E2bConsentFrame {
            name: ANSWER_FRAME.to_owned(),
            payload: json!({"request_id": request_id, "chat_id": chat_id, "choice": choice.as_wire()}),
        };
        self.e2b_system_step(
            chat_id,
            format!("{request_id}-e2b-response"),
            request_id,
            key,
            response_content(request_id, choice),
            vec![answer],
        )
    }
}

#[cfg(test)]
#[path = "e2b_consent_steps_tests.rs"]
mod tests;
