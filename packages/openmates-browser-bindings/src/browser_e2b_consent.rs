//! Worker exports of the account-level E2B upload consent (`e2bConsent` unit).
//! Marshalling only: reading and changing the decision are the core's
//! (`Client::e2b_consent_get` / `e2b_consent_set`); this file adds no policy.
//! Specification: assertion `code-run.e2b.upload-consent`.
use super::{BrowserCoreClient, worker_only};
use openmates_sdk::client::{
    E2bConsentChoice, E2bConsentRecord, E2bDecision, e2b_consent_request_answer_json,
};
use openmates_sdk::Error;
use serde_json::json;
use wasm_bindgen::prelude::*;

/// Stable code of a core refusal; never internal text.
fn code(error: Error) -> JsValue {
    JsValue::from_str(match error {
        Error::Invalid(_) => "invalid_request",
        Error::Protocol => "protocol",
        Error::Cancelled => "cancelled",
        Error::Offline => "offline",
        Error::Authentication => "authentication",
        Error::Forbidden => "forbidden",
        Error::Unavailable { code, .. } => code,
        _ => "unavailable",
    })
}

fn record_json(record: &E2bConsentRecord) -> String {
    json!({
        "decision": record.decision.map(E2bDecision::as_wire),
        "decidedAt": record.decided_at,
        "version": record.version,
    })
    .to_string()
}

#[wasm_bindgen]
impl BrowserCoreClient {
    /// Read the account decision as `{decision, decidedAt, version}`.
    pub async fn e2b_consent_get(&mut self, handle: &str, generation: f64) -> Result<String, JsValue> {
        worker_only()?;
        self.status(handle, generation)?;
        let record = self.client.e2b_consent_get().await.map_err(code)?;
        self.status(handle, generation)?;
        Ok(record_json(&record))
    }

    /// Change the account decision (`allowed` or `declined`); returns the record.
    pub async fn e2b_consent_set(&mut self, handle: &str, generation: f64, decision: &str) -> Result<String, JsValue> {
        worker_only()?;
        self.status(handle, generation)?;
        let decision = match decision {
            "allowed" => E2bDecision::Allowed,
            "declined" => E2bDecision::Declined,
            _ => return Err(JsValue::from_str("invalid_request")),
        };
        let record = self.client.e2b_consent_set(decision).await.map_err(code)?;
        self.status(handle, generation)?;
        Ok(record_json(&record))
    }

    /// Build the encrypted request system message for a
    /// `request_e2b_upload_consent` frame; returns `{frames, message}`. The page
    /// sends the frames on its main socket and stores `message`. `chat_key` is
    /// the chat's 32-byte key.
    pub fn e2b_consent_request_step(&mut self, handle: &str, generation: f64, frame_json: &str, chat_key: Vec<u8>) -> Result<String, JsValue> {
        worker_only()?;
        self.status(handle, generation)?;
        let key = key_of(chat_key)?;
        let frame: serde_json::Value = serde_json::from_str(frame_json).map_err(|_| JsValue::from_str("invalid_request"))?;
        let step = self.client.e2b_consent_request_step(&frame, &key).map_err(code)?;
        serde_json::to_string(&step).map_err(|_| JsValue::from_str("protocol"))
    }

    /// Build the answer frame and the encrypted response system message;
    /// returns `{frames, message}`.
    pub fn e2b_consent_answer_step(&mut self, handle: &str, generation: f64, chat_id: &str, request_id: &str, choice: &str, chat_key: Vec<u8>) -> Result<String, JsValue> {
        worker_only()?;
        self.status(handle, generation)?;
        let key = key_of(chat_key)?;
        let choice = E2bConsentChoice::from_wire(choice).ok_or_else(|| JsValue::from_str("invalid_request"))?;
        let step = self.client.e2b_consent_answer_step(chat_id, request_id, choice, &key).map_err(code)?;
        serde_json::to_string(&step).map_err(|_| JsValue::from_str("protocol"))
    }

    /// The answering choice (`allow`, `own_machine`, `not_now`) found in
    /// `system_contents_json` (a JSON array of decrypted system message
    /// contents) for `request_id`, or `undefined` while unanswered.
    pub fn e2b_consent_request_answer(&self, system_contents_json: &str, request_id: &str) -> Result<Option<String>, JsValue> {
        e2b_consent_request_answer_json(system_contents_json, request_id)
            .map(|choice| choice.map(str::to_owned))
            .map_err(|_| JsValue::from_str("invalid_request"))
    }
}

fn key_of(raw: Vec<u8>) -> Result<zeroize::Zeroizing<[u8; 32]>, JsValue> {
    let raw = zeroize::Zeroizing::new(raw);
    let mut key = zeroize::Zeroizing::new([0u8; 32]);
    if raw.len() != 32 {
        return Err(JsValue::from_str("crypto"));
    }
    key.copy_from_slice(&raw);
    Ok(key)
}
