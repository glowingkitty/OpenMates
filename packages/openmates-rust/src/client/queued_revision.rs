//! Revise a queued follow-up of a running reply, or switch it to steering
//! (`revise_queued_message`, answered by `queued_message_updated` or
//! `queued_message_revision_rejected`). The message id stays; only its text
//! and queue mode change, guarded by the revision the client last saw. The
//! text is privacy-prepared and encrypted with the chat key exactly like a
//! send; the plain text travels beside it because the server sanitizes and
//! vault-encrypts it for the queued inference request. Backend contract:
//! `revise_queued_message_handler.py`. Spec `client-core` (send, queue).
use super::message_actions::acknowledged;
use super::plaintext::Plain;
use super::sync_capability::AsyncCryptoScope;
use super::transport::{send, wait_any};
use super::*;

/// Largest revised text the server accepts.
const MAX_TEXT_BYTES: usize = 2 * 1024 * 1024;

/// How the queued message waits after the revision.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum QueuedRevisionMode {
    /// Answered after the active reply.
    FollowUp,
    /// Steers the active reply at its next safe boundary.
    Steer,
}

impl QueuedRevisionMode {
    fn wire(self) -> &'static str {
        match self {
            Self::FollowUp => "follow_up",
            Self::Steer => "steer",
        }
    }
}

/// The server's confirmation of an applied revision.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct QueuedRevisionReceipt {
    /// The chat of the queued message.
    pub chat_id: String,
    /// The unchanged id of the queued message.
    pub message_id: String,
    /// The mode now in force.
    pub queue_mode: QueuedRevisionMode,
    /// The revision now in force (the expected one plus one).
    pub queue_revision: u64,
}

/// The `revise_queued_message` payload: ids, the guarded revision, and, when
/// the text changes, the plain text with its chat-key ciphertext and the
/// encrypted PII mappings (`null` without mappings, as the server requires
/// the key to be present).
pub(super) fn revision_payload(
    chat_id: &str,
    message_id: &str,
    expected_revision: u64,
    request_id: &str,
    mode: Option<QueuedRevisionMode>,
    text: Option<(&str, &str, Option<&str>)>,
) -> Value {
    let mut payload = json!({"chat_id":chat_id,"message_id":message_id,
        "expected_revision":expected_revision,"client_request_id":request_id});
    if let Some(mode) = mode {
        payload["queue_mode"] = json!(mode.wire());
    }
    if let Some((content, encrypted, mappings)) = text {
        payload["content"] = json!(content);
        payload["encrypted_content"] = json!(encrypted);
        payload["encrypted_pii_mappings"] = json!(mappings);
    }
    payload
}

/// The typed error of a server rejection: a stale revision is `Conflict`.
pub(super) fn rejection(reason: &str) -> Error {
    match reason {
        "conflict" => Error::Conflict,
        "invalid_request" => Error::Invalid("The queued message revision was refused."),
        "unsafe_content_encoding" => Error::Invalid("The revised text has an unsafe encoding."),
        "forbidden" => Error::Forbidden,
        "not_queued" => Error::Unavailable {
            code: "queued_revision",
            reason: "not_queued",
        },
        "inactive" => Error::Unavailable {
            code: "queued_revision",
            reason: "inactive",
        },
        "busy" => Error::Unavailable {
            code: "queued_revision",
            reason: "busy",
        },
        "invalid_queue_state" => Error::Unavailable {
            code: "queued_revision",
            reason: "invalid_queue_state",
        },
        "not_persisted" => Error::Unavailable {
            code: "queued_revision",
            reason: "not_persisted",
        },
        _ => Error::Unavailable {
            code: "queued_revision",
            reason: "storage_unavailable",
        },
    }
}

impl Client {
    /// Revise queued message `message_id` of `chat_id`: set `text` (privacy
    /// prepared and encrypted like a send, using `options` for PII detection,
    /// exclusions and mappings) and/or switch its queue `mode`.
    /// `expected_revision` is the revision the queued turn last reported.
    ///
    /// # Errors
    /// `Invalid` for a malformed chat id, an empty message id, a revision
    /// below one, no change requested, or empty or oversized text; `Forbidden`
    /// in a Team scope or for a volatile chat; `Conflict` when the revision is
    /// stale (the queued message changed meanwhile); `Unavailable`
    /// (`queued_revision`: `not_queued`, `inactive`, `busy`, ...) for other
    /// server rejections; `Offline` without an answer in 20 seconds;
    /// `Protocol` for a malformed or foreign answer; `Cancelled`.
    pub async fn revise_queued_message(
        &mut self,
        chat_id: &str,
        message_id: &str,
        expected_revision: u64,
        mode: Option<QueuedRevisionMode>,
        text: Option<&str>,
        options: SendOptions,
    ) -> Result<QueuedRevisionReceipt> {
        self.require_session()?;
        uuid::Uuid::parse_str(chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        if !(1..=255).contains(&message_id.len()) || !(1..u64::MAX).contains(&expected_revision) {
            return Err(Error::Invalid(
                "A queued message ID and revision are required.",
            ));
        }
        if mode.is_none() && text.is_none() {
            return Err(Error::Invalid("Nothing to revise."));
        }
        if let Some(text) = text
            && (text.trim().is_empty() || text.len() > MAX_TEXT_BYTES)
        {
            return Err(Error::Invalid("Enter a queued message of at most 2 MB."));
        }
        options.validate()?;
        if self.is_ephemeral_chat(chat_id) || self.team()?.is_some() {
            return Err(Error::Forbidden);
        }
        let cancel = self.operation_cancel.clone();
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let request_id = uuid::Uuid::new_v4().to_string();
        let prepared = match text {
            Some(text) => Some(self.prepare_revised_text(chat_id, text, &options).await?),
            None => None,
        };
        let payload = revision_payload(
            chat_id,
            message_id,
            expected_revision,
            &request_id,
            mode,
            prepared.as_ref().map(|(content, encrypted, mappings)| {
                (content.as_str(), encrypted.as_str(), mappings.as_deref())
            }),
        );
        let mut ws = self.socket_with_task_jobs(false).await?;
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, chat_id)?;
        let result = acknowledged(&cancel, async {
            send(&mut ws, "revise_queued_message", payload).await?;
            wait_any(
                &mut ws,
                &["queued_message_updated", "queued_message_revision_rejected"],
                "client_request_id",
                &request_id,
            )
            .await
        })
        .await;
        let _ = ws.close(None).await;
        let (kind, frame) = result?;
        parse_answer(&kind, &frame, chat_id, message_id, expected_revision)
    }

    /// The privacy-prepared text with its chat-key ciphertext and the
    /// encrypted PII mappings (`None` without mappings).
    async fn prepare_revised_text(
        &mut self,
        chat_id: &str,
        text: &str,
        options: &SendOptions,
    ) -> Result<(String, String, Option<String>)> {
        if !self.chats.contains_key(chat_id) {
            self.open_chat(chat_id).await?;
        }
        let wrapping = self.wrapping_key().await?;
        let row = self.chats.get(chat_id).cloned().ok_or(Error::Offline)?;
        if super::sync::draft_only(&row) {
            return Err(Error::Invalid("The chat has no saved messages."));
        }
        let key = self.chat_key(&row, &wrapping)?;
        let mut existing = Plain::new(vec![]);
        for row in self.history.get(chat_id).into_iter().flatten() {
            let mappings = Plain::new(super::sync::decrypt_optional(
                row,
                "encrypted_pii_mappings",
                &key,
            )?);
            if !mappings.is_empty() {
                existing.extend(serde_json::from_str::<Vec<Value>>(&mappings)?);
            }
        }
        let composed = Plain::new(super::send_attachments::content_with_references(text, &[]));
        let prepared = Plain::new(super::send_attachments::prepare_turn_privacy(
            &composed,
            &[],
            &existing,
            options,
        )?);
        let encrypted = crypto::encrypt_combined(&prepared.text, &key)?;
        let mappings = if prepared.mappings.is_empty() {
            None
        } else {
            let encoded = Plain::new(serde_json::to_string(&prepared.mappings)?);
            Some(crypto::encrypt_combined(&encoded, &key)?)
        };
        Ok((prepared.text.clone(), encrypted, mappings))
    }
}

/// Validate and type the server's answer to this exact request.
fn parse_answer(
    kind: &str,
    frame: &Value,
    chat_id: &str,
    message_id: &str,
    expected_revision: u64,
) -> Result<QueuedRevisionReceipt> {
    let body = frame.get("payload").unwrap_or(frame);
    if text(body, "chat_id") != chat_id || text(body, "message_id") != message_id {
        return Err(Error::Protocol);
    }
    if kind == "queued_message_revision_rejected" {
        let reason = body["reason_code"].as_str().filter(|r| !r.is_empty());
        return Err(rejection(reason.ok_or(Error::Protocol)?));
    }
    let mode = match body["queue_mode"].as_str() {
        Some("follow_up") => QueuedRevisionMode::FollowUp,
        Some("steer") => QueuedRevisionMode::Steer,
        _ => return Err(Error::Protocol),
    };
    let revision = body["queue_revision"].as_u64().ok_or(Error::Protocol)?;
    if revision != expected_revision + 1 {
        return Err(Error::Protocol);
    }
    Ok(QueuedRevisionReceipt {
        chat_id: chat_id.to_owned(),
        message_id: message_id.to_owned(),
        queue_mode: mode,
        queue_revision: revision,
    })
}

#[cfg(test)]
#[path = "queued_revision_tests.rs"]
mod tests;
