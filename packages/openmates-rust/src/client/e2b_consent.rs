//! One-time E2B upload consent: request and answer message policy, account decision calls and typed refusals.
//!
//! Wire contract: `docs/plans/e2b-upload-consent/plan.yml` (`design.wire_contract`).
//! Specification: assertion `code-run.e2b.upload-consent`. A request is never
//! approved silently; every answer is an explicit [`E2bConsentChoice`].
use super::e2b_consent_steps::E2bConsentStep;
use super::sync_capability::AsyncCryptoScope;
use super::transport::{Socket, send_plaintext, wait};
use super::*;

/// System message type of the in-chat consent request.
pub const REQUEST_TYPE: &str = "e2b_upload_consent_request";
/// System message type of the user's answer.
pub const RESPONSE_TYPE: &str = "e2b_upload_consent_response";
/// Server frame that asks the client to show and persist the request.
pub const REQUEST_FRAME: &str = "request_e2b_upload_consent";
/// Client frame that carries the answer to the server.
pub const ANSWER_FRAME: &str = "e2b_upload_consent_answer";
/// Server frame that fans the recorded decision out to the user's devices.
pub const UPDATED_FRAME: &str = "e2b_upload_consent_updated";
/// First-party settings route (GET reads, PUT updates the decision).
pub(crate) const SETTINGS_ROUTE: &str = "/v1/settings/e2b-upload-consent";
/// HTTP 403 code when the account has no decision yet.
pub const REQUIRED_CODE: &str = "e2b_consent_required";
/// HTTP 403 code when the account declined.
pub const DECLINED_CODE: &str = "e2b_consent_declined";
const PRIVACY_POLICY_URL: &str = "https://openmates.org/privacy";
const REMOTE_ACCESS_COMMAND: &str = "openmates remote-access";
const PROVIDER: &str = "e2b";

/// How a send handles an E2B upload consent request raised during the turn.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum E2bConsentPolicy {
    /// The caller's shell asks the user; nothing is answered automatically.
    #[default]
    Caller,
    /// Answer `not_now`: nothing is uploaded.
    Reject,
    /// Answer `allow`: only for an explicit caller flag such as `--allow-e2b-upload`.
    Approve,
}

impl E2bConsentPolicy {
    /// The choice sent automatically, or `None` when the caller must answer.
    pub fn automatic_choice(self) -> Option<E2bConsentChoice> {
        match self {
            Self::Caller => None,
            Self::Reject => Some(E2bConsentChoice::NotNow),
            Self::Approve => Some(E2bConsentChoice::Allow),
        }
    }
}

/// The three answers offered by the consent request.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum E2bConsentChoice {
    /// Send files to E2B (recorded as allowed).
    Allow,
    /// Run on the user's own machine (recorded as declined).
    OwnMachine,
    /// Not now (recorded as declined).
    NotNow,
}

impl E2bConsentChoice {
    /// Wire string of the choice.
    pub fn as_wire(self) -> &'static str {
        match self {
            Self::Allow => "allow",
            Self::OwnMachine => "own_machine",
            Self::NotNow => "not_now",
        }
    }

    /// Parse a wire string; unknown values are refused.
    pub fn from_wire(value: &str) -> Option<Self> {
        match value {
            "allow" => Some(Self::Allow),
            "own_machine" => Some(Self::OwnMachine),
            "not_now" => Some(Self::NotNow),
            _ => None,
        }
    }

    /// The account decision this choice records.
    pub fn decision(self) -> E2bDecision {
        match self {
            Self::Allow => E2bDecision::Allowed,
            Self::OwnMachine | Self::NotNow => E2bDecision::Declined,
        }
    }
}

/// The recorded account decision.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum E2bDecision {
    /// Files may be sent to E2B.
    Allowed,
    /// Nothing is sent to E2B.
    Declined,
}

impl E2bDecision {
    /// Wire string of the decision.
    pub fn as_wire(self) -> &'static str {
        match self {
            Self::Allowed => "allowed",
            Self::Declined => "declined",
        }
    }
}

/// Account decision as returned by `GET`/`PUT /v1/settings/e2b-upload-consent`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct E2bConsentRecord {
    /// `None` while the account has not decided for this wording version.
    pub decision: Option<E2bDecision>,
    /// Server timestamp of the decision.
    pub decided_at: Option<u64>,
    /// Consent wording version the decision belongs to.
    pub version: u32,
}

/// Parse the settings route response.
pub(crate) fn parse_record(value: &Value) -> Result<E2bConsentRecord> {
    let decision = match value.get("decision") {
        None | Some(Value::Null) => None,
        Some(Value::String(text)) => Some(match text.as_str() {
            "allowed" => E2bDecision::Allowed,
            "declined" => E2bDecision::Declined,
            _ => return Err(Error::Protocol),
        }),
        Some(_) => return Err(Error::Protocol),
    };
    let version = value
        .get("version")
        .and_then(Value::as_u64)
        .and_then(|v| u32::try_from(v).ok())
        .ok_or(Error::Protocol)?;
    Ok(E2bConsentRecord {
        decision,
        decided_at: value.get("decided_at").and_then(Value::as_u64),
        version,
    })
}

/// The request system-message content (`wire_contract.request_message`).
pub fn request_content(request_id: &str, chat_id: &str, version: u32) -> Result<Value> {
    if request_id.is_empty() || chat_id.is_empty() || request_id.len() > 128 || chat_id.len() > 128
    {
        return Err(Error::Invalid(
            "E2B consent requests need stable request and chat identities.",
        ));
    }
    Ok(json!({
        "type": REQUEST_TYPE,
        "request_id": request_id,
        "chat_id": chat_id,
        "version": version,
        "provider": PROVIDER,
        "privacy_policy_url": PRIVACY_POLICY_URL,
        "remote_access_command": REMOTE_ACCESS_COMMAND,
        "choices": [
            E2bConsentChoice::Allow.as_wire(),
            E2bConsentChoice::OwnMachine.as_wire(),
            E2bConsentChoice::NotNow.as_wire(),
        ],
    }))
}

/// The persisted request system message built from a `request_e2b_upload_consent` frame.
/// Outcome `{kind:"ok",message}` or `{kind:"error",message}`.
pub fn build_request_message_json(
    request_id: &str,
    chat_id: &str,
    version: u32,
    created_at: u64,
) -> std::result::Result<String, String> {
    let outcome = match request_content(request_id, chat_id, version) {
        Ok(content) => json!({"kind":"ok","message":{
            "message_id": request_id,
            "role": "system",
            "content": content.to_string(),
            "created_at": created_at,
            "user_message_id": request_id,
        }}),
        Err(_) => {
            json!({"kind":"error","message":"E2B consent requests need stable request and chat identities."})
        }
    };
    Ok(outcome.to_string())
}

/// The response system-message content `{type, request_id, choice}`.
pub fn response_content(request_id: &str, choice: E2bConsentChoice) -> Value {
    json!({"type": RESPONSE_TYPE, "request_id": request_id, "choice": choice.as_wire()})
}

/// The choice of the system message in `system_contents_json` (a JSON array
/// of content strings) that answers `request_id`, or `None` while unanswered.
pub fn request_answer_json(
    system_contents_json: &str,
    request_id: &str,
) -> std::result::Result<Option<&'static str>, String> {
    let contents: Vec<String> = serde_json::from_str(system_contents_json)
        .map_err(|_| "Invalid system message list".to_owned())?;
    Ok(contents.iter().find_map(|content| {
        let parsed: Value = serde_json::from_str(content).ok()?;
        if parsed.get("type").and_then(Value::as_str) != Some(RESPONSE_TYPE)
            || parsed.get("request_id").and_then(Value::as_str) != Some(request_id)
        {
            return None;
        }
        E2bConsentChoice::from_wire(parsed.get("choice").and_then(Value::as_str)?)
            .map(E2bConsentChoice::as_wire)
    }))
}

/// True when a system message already answers the request `request_id`.
pub fn is_request_answered_json(
    system_contents_json: &str,
    request_id: &str,
) -> std::result::Result<bool, String> {
    request_answer_json(system_contents_json, request_id).map(|choice| choice.is_some())
}

/// Typed refusal for an HTTP 403 body carrying an E2B consent code, as
/// `{"detail":{"code":...}}` or `{"detail":"..."}`; `None` for any other 403.
pub(crate) fn refusal_from_body(body: &[u8]) -> Option<Error> {
    let parsed: Value = serde_json::from_slice(body).ok()?;
    let detail = parsed.get("detail")?;
    let code = detail
        .get("code")
        .and_then(Value::as_str)
        .or_else(|| detail.as_str())?;
    refusal_from_code(code)
}

/// Typed refusal for a WebSocket error or HTTP detail code.
pub fn refusal_from_code(code: &str) -> Option<Error> {
    match code {
        REQUIRED_CODE => Some(Error::Unavailable {
            code: REQUIRED_CODE,
            reason: "Allow sending code and files to E2B first, or use your own machine.",
        }),
        DECLINED_CODE => Some(Error::Unavailable {
            code: DECLINED_CODE,
            reason: "Sending code and files to E2B was declined for this account.",
        }),
        _ => None,
    }
}

impl Client {
    /// Read the account decision.
    ///
    /// # Errors
    /// Fails without a native or browser session (`require_work_authority`) or when
    /// the settings route refuses or is unreachable.
    pub async fn e2b_consent_get(&mut self) -> Result<E2bConsentRecord> {
        self.require_work_authority()?;
        parse_record(&self.request(Method::GET, SETTINGS_ROUTE, None).await?)
    }

    /// Change the account decision (settings).
    ///
    /// # Errors
    /// Fails without a native or browser session (`require_work_authority`) or when
    /// the settings route refuses or is unreachable.
    pub async fn e2b_consent_set(&mut self, decision: E2bDecision) -> Result<E2bConsentRecord> {
        self.require_work_authority()?;
        let body = json!({"decision": decision.as_wire()});
        parse_record(
            &self
                .request(Method::PUT, SETTINGS_ROUTE, Some(body))
                .await?,
        )
    }

    /// Persist the encrypted request system message for a `request_e2b_upload_consent` frame.
    ///
    /// # Errors
    /// `Protocol` for a frame without a version, or the persist error of the consent message.
    pub async fn e2b_consent_persist_request(
        &mut self,
        ws: &mut Socket,
        frame: &Value,
        key: &[u8; 32],
        cancel: &CancellationToken,
    ) -> Result<()> {
        let scope = AsyncCryptoScope::begin(self)?;
        self.require_browser_owner_guards()?;
        let chat = text(frame, "chat_id");
        scope.check_chat(self, chat)?;
        let step = self.e2b_consent_request_step(frame, key)?;
        self.send_consent_step(ws, &scope, chat, step, cancel).await
    }

    /// Answer a request: send `e2b_upload_consent_answer`, then persist the
    /// encrypted response system message like the memory consent response.
    ///
    /// # Errors
    /// `Protocol` for an empty request id, `Cancelled`, or the send/persist error.
    pub async fn e2b_consent_answer(
        &mut self,
        ws: &mut Socket,
        chat_id: &str,
        request_id: &str,
        choice: E2bConsentChoice,
        key: &[u8; 32],
        cancel: &CancellationToken,
    ) -> Result<()> {
        let scope = AsyncCryptoScope::begin(self)?;
        self.require_browser_owner_guards()?;
        scope.check_chat(self, chat_id)?;
        if request_id.is_empty() || cancel.is_cancelled() {
            return Err(if request_id.is_empty() {
                Error::Protocol
            } else {
                Error::Cancelled
            });
        }
        let step = self.e2b_consent_answer_step(chat_id, request_id, choice, key)?;
        self.send_consent_step(ws, &scope, chat_id, step, cancel)
            .await
    }

    async fn send_consent_step(
        &mut self,
        ws: &mut Socket,
        scope: &AsyncCryptoScope,
        chat: &str,
        step: E2bConsentStep,
        cancel: &CancellationToken,
    ) -> Result<()> {
        for frame in step.frames {
            if cancel.is_cancelled() {
                return Err(Error::Cancelled);
            }
            let sent = send_plaintext(ws, &frame.name, frame.payload).await;
            scope.check_chat(self, chat)?;
            sent?;
        }
        let result = wait(
            ws,
            "system_message_confirmed",
            "message_id",
            &step.message.message_id,
        )
        .await;
        scope.check_chat(self, chat)?;
        result?;
        Ok(())
    }
}

#[cfg(test)]
#[path = "e2b_consent_tests.rs"]
mod tests;
