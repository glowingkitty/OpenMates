//! E2B upload consent inside the saved-turn send loop: persist the request, answer by policy or surface it.
//!
//! Wire contract: `docs/plans/e2b-upload-consent/plan.yml`. The request frame is
//! always persisted as a system message. `Approve`/`Reject` answer at once and
//! the turn keeps streaming (the server continues it); `Caller` answers
//! nothing and reports the request through the stream and the outcome, unless the
//! shell set an answer channel ([`Client::set_e2b_consent_receiver`]).
use super::e2b_consent::{E2bConsentChoice, E2bConsentPolicy, REQUEST_FRAME};
use super::plaintext::Wipe;
use super::sync_capability::AsyncCryptoScope;
use super::transport::Socket;
use super::*;
use serde::{Deserialize, Serialize};

/// Prefix of the `StreamUpdate::Status` text that surfaces a pending request; the
/// rest is the JSON of [`SendE2bConsentRequest`].
pub const E2B_CONSENT_STATUS_PREFIX: &str = "e2b_upload_consent_request ";

/// An E2B upload consent request the caller must answer with
/// [`Client::e2b_consent_answer`]; the paused turn continues after the answer.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SendE2bConsentRequest {
    /// Request identity to answer.
    pub request_id: String,
    /// Chat holding the request system message.
    pub chat_id: String,
    /// Consent wording version.
    pub version: u32,
}

impl Wipe for SendE2bConsentRequest {
    fn wipe(&mut self) {
        self.request_id.wipe();
        self.chat_id.wipe();
        self.version = 0;
    }
}

/// True for a request frame of this chat that this send handles once.
pub(super) fn admit_e2b_request(
    event: &Value,
    chat: &str,
    seen: &mut std::collections::HashSet<String>,
) -> bool {
    let request = text(event, "request_id");
    text(event, "chat_id") == chat
        && !request.is_empty()
        && request.len() <= 128
        && seen.insert(format!("e2b:{request}"))
}

/// The frame type the send loop routes here.
pub(super) fn is_request_frame(kind: &str) -> bool {
    kind == REQUEST_FRAME
}

impl Client {
    /// Handle one `request_e2b_upload_consent` frame of the running turn.
    ///
    /// Returns `Some(request)` only when the policy leaves the answer to the
    /// caller; automatic answers return `None`.
    ///
    /// # Errors
    /// `Protocol` for a malformed frame, `Cancelled`, or the persist/answer error.
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn send_e2b_consent(
        &mut self,
        ws: &mut Socket,
        event: &Value,
        chat_id: &str,
        key: &[u8; 32],
        updates: &mpsc::Sender<StreamUpdate>,
        cancel: &CancellationToken,
        policy: E2bConsentPolicy,
    ) -> Result<Option<SendE2bConsentRequest>> {
        let request_id = text(event, "request_id");
        let version = event
            .get("version")
            .and_then(Value::as_u64)
            .and_then(|v| u32::try_from(v).ok())
            .ok_or(Error::Protocol)?;
        self.e2b_consent_persist_request(ws, event, key, cancel)
            .await?;
        if let Some(choice) = policy.automatic_choice() {
            self.e2b_consent_answer(ws, chat_id, request_id, choice, key, cancel)
                .await?;
            return Ok(None);
        }
        let request = SendE2bConsentRequest {
            request_id: request_id.to_owned(),
            chat_id: chat_id.to_owned(),
            version,
        };
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, chat_id)?;
        let status = format!(
            "{E2B_CONSENT_STATUS_PREFIX}{}",
            serde_json::to_string(&request).map_err(|_| Error::Protocol)?
        );
        let delivered = self
            .deliver_turn_update(
                &scope,
                chat_id,
                updates,
                cancel,
                StreamUpdate::Status(status),
            )
            .await;
        scope.check_chat(self, chat_id)?;
        delivered?;
        if self.e2b_consent.is_none() {
            return Ok(Some(request));
        }
        match self.await_e2b_choice(&request.request_id, cancel).await? {
            Some(choice) => {
                self.e2b_consent_answer(ws, chat_id, &request.request_id, choice, key, cancel)
                    .await?;
                Ok(None)
            }
            // The shell dropped its sender: behave as without a receiver.
            None => Ok(Some(request)),
        }
    }

    /// Wait for the caller's choice for `request_id`; answers for other requests
    /// are discarded. `None` when the sender closed; `Cancelled` on cancellation.
    async fn await_e2b_choice(
        &mut self,
        request_id: &str,
        cancel: &CancellationToken,
    ) -> Result<Option<E2bConsentChoice>> {
        let Some(receiver) = self.e2b_consent.as_mut() else {
            return Ok(None);
        };
        loop {
            tokio::select! {biased;
                _ = cancel.cancelled() => return Err(Error::Cancelled),
                _ = self.operation_cancel.cancelled() => return Err(Error::Cancelled),
                next = receiver.recv() => match next {
                    Some((id, choice)) if id == request_id => return Ok(Some(choice)),
                    Some(_) => continue,
                    None => return Ok(None),
                },
            }
        }
    }

    /// Let the shell answer a `Caller`-policy E2B upload consent request while the
    /// send is running: each `(request_id, choice)` sent on the channel is
    /// answered over the send socket and the paused turn continues. Without a
    /// receiver a `Caller` request is only surfaced, never answered.
    pub fn set_e2b_consent_receiver(
        &mut self,
        receiver: mpsc::UnboundedReceiver<(String, E2bConsentChoice)>,
    ) {
        self.e2b_consent = Some(receiver);
    }
}

#[cfg(test)]
#[path = "send_e2b_consent_tests.rs"]
mod tests;
