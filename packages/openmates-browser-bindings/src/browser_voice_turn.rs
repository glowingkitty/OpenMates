//! Worker exports of the voice-call turn split (`voiceTurn` unit). Marshalling
//! only: the snapshot frame, the text-independent stage and the
//! `chat_turn_admit` payload are the core's (`Client::voice_turn_*`). Prepared
//! turns stay in a Worker-local map behind an opaque id, so JS never holds
//! decrypted context, keys or wrappers; discarding drops the entry and emits
//! nothing. The page sends the returned frames on its one main socket.
use super::{BrowserCoreClient, worker_only};
use openmates_sdk::Error;
use openmates_sdk::client::{VoiceHeardBoundary, VoiceTurnPrepared};
use serde_json::{Value, json};
use std::cell::RefCell;
use std::collections::HashMap;
use wasm_bindgen::prelude::*;

/// Largest whole number a JS number holds exactly (`Number.MAX_SAFE_INTEGER`).
const MAX_SAFE_SECONDS: f64 = 9_007_199_254_740_991.0;

/// One begun turn: its ids plus the prepared half once the snapshot arrived.
struct Entry {
    chat_id: String,
    turn_id: String,
    request_id: String,
    prepared: Option<VoiceTurnPrepared>,
}

thread_local! {
    // One wasm instance, one Worker thread: a plain map is the whole store.
    static TURNS: RefCell<HashMap<String, Entry>> = RefCell::new(HashMap::new());
    static NEXT: RefCell<u64> = const { RefCell::new(0) };
}

fn refusal(code: &'static str) -> JsValue {
    JsValue::from_str(code)
}

/// Stable code of a core refusal; never internal text.
fn code(error: Error) -> JsValue {
    JsValue::from_str(match error {
        Error::Invalid(_) => "invalid_request",
        Error::Protocol => "protocol",
        Error::Cancelled => "cancelled",
        Error::Crypto => "crypto",
        Error::Locked => "locked",
        Error::Conflict => "conflict",
        Error::Unavailable { code, .. } => code,
        _ => "unavailable",
    })
}

/// Parse `{assistantMessageId, completedSequences, activeSequence?,
/// activeOffsetMs}`; the core validates ranges.
fn heard_boundary(json: &str) -> Result<Option<VoiceHeardBoundary>, JsValue> {
    if json.is_empty() {
        return Ok(None);
    }
    let value: Value = serde_json::from_str(json).map_err(|_| refusal("invalid_request"))?;
    if value.is_null() {
        return Ok(None);
    }
    let sequences = value["completedSequences"]
        .as_array()
        .ok_or_else(|| refusal("invalid_request"))?
        .iter()
        .map(|v| v.as_u64().and_then(|n| u32::try_from(n).ok()))
        .collect::<Option<Vec<u32>>>()
        .ok_or_else(|| refusal("invalid_request"))?;
    let small = |name: &str| value[name].as_u64().and_then(|n| u32::try_from(n).ok());
    Ok(Some(VoiceHeardBoundary {
        assistant_message_id: value["assistantMessageId"]
            .as_str()
            .ok_or_else(|| refusal("invalid_request"))?
            .into(),
        completed_sequences: sequences,
        active_sequence: small("activeSequence"),
        active_offset_ms: small("activeOffsetMs").unwrap_or(0),
    }))
}

#[wasm_bindgen]
impl BrowserCoreClient {
    /// Start a voice turn. Returns `{voiceId, requestId, frame}`: the page
    /// sends `frame` as `personal_send_context_snapshot` and feeds the result
    /// to `voice_turn_prepare`. `turn_id` doubles as the user message id.
    pub fn voice_turn_begin(
        &mut self,
        handle: &str,
        generation: f64,
        chat_id: &str,
        turn_id: &str,
    ) -> Result<String, JsValue> {
        worker_only()?;
        self.status(handle, generation)?;
        uuid::Uuid::parse_str(chat_id).map_err(|_| refusal("chat_unavailable"))?;
        uuid::Uuid::parse_str(turn_id).map_err(|_| refusal("invalid_request"))?;
        let begun = self.client.voice_turn_begin(chat_id, turn_id);
        let id = NEXT.with(|n| {
            let mut n = n.borrow_mut();
            *n += 1;
            format!("voice-turn-{n}")
        });
        let out = json!({"voiceId": id, "requestId": begun.request_id, "frame": begun.frame});
        TURNS.with(|t| {
            t.borrow_mut().insert(
                id,
                Entry {
                    chat_id: chat_id.into(),
                    turn_id: turn_id.into(),
                    request_id: begun.request_id,
                    prepared: None,
                },
            )
        });
        Ok(out.to_string())
    }

    /// Run the text-independent stage with the socket's snapshot result. The
    /// entry is dropped on failure, so a refused turn leaves nothing behind.
    pub async fn voice_turn_prepare(
        &mut self,
        handle: &str,
        generation: f64,
        voice_id: &str,
        snapshot_result: &str,
    ) -> Result<(), JsValue> {
        worker_only()?;
        self.status(handle, generation)?;
        let result: Value =
            serde_json::from_str(snapshot_result).map_err(|_| refusal("invalid_request"))?;
        let (chat_id, turn_id, request_id) = TURNS
            .with(|t| {
                t.borrow()
                    .get(voice_id)
                    .map(|e| (e.chat_id.clone(), e.turn_id.clone(), e.request_id.clone()))
            })
            .ok_or_else(|| refusal("voice_turn_unknown"))?;
        let prepared = self
            .client
            .voice_turn_prepare(&chat_id, &turn_id, &request_id, result)
            .await;
        match prepared {
            Ok(prepared) => {
                TURNS.with(|t| {
                    if let Some(entry) = t.borrow_mut().get_mut(voice_id) {
                        entry.prepared = Some(prepared);
                    }
                });
                self.status(handle, generation)?;
                Ok(())
            }
            Err(error) => {
                TURNS.with(|t| t.borrow_mut().remove(voice_id));
                Err(code(error))
            }
        }
    }

    /// Commit the final transcript. Returns `{admit, userMessage, waitAi}`
    /// (ciphertext only); nothing is sent. Consumes the entry either way.
    /// `created_at` is the page row's time in seconds; 0 stamps the commit time.
    pub async fn voice_turn_commit(
        &mut self,
        handle: &str,
        generation: f64,
        voice_id: &str,
        call_id: &str,
        heard_boundary_json: &str,
        final_text: &str,
        created_at: f64,
    ) -> Result<String, JsValue> {
        worker_only()?;
        self.status(handle, generation)?;
        let entry = TURNS
            .with(|t| t.borrow_mut().remove(voice_id))
            .ok_or_else(|| refusal("voice_turn_unknown"))?;
        let Entry {
            turn_id, prepared, ..
        } = entry;
        let prepared = prepared.ok_or_else(|| refusal("voice_turn_not_prepared"))?;
        let boundary = heard_boundary(heard_boundary_json)?;
        if !(created_at.is_finite() && created_at >= 0.0 && created_at.fract() == 0.0)
            || created_at > MAX_SAFE_SECONDS
        {
            return Err(refusal("voice_turn_bad_time"));
        }
        // Checked above: a whole, non-negative number within the safe range.
        let created_at = (created_at > 0.0).then_some(created_at as u64);
        let done = self
            .client
            .voice_turn_commit(
                prepared, &turn_id, call_id, boundary, final_text, created_at,
            )
            .await
            .map_err(code)?;
        self.status(handle, generation)?;
        Ok(
            json!({"admit": done.admit, "userMessage": done.user_message, "waitAi": done.wait_ai})
                .to_string(),
        )
    }

    /// Drop a begun or prepared turn. Emits nothing; unknown ids are ignored.
    pub fn voice_turn_discard(&mut self, voice_id: &str) -> Result<(), JsValue> {
        worker_only()?;
        TURNS.with(|t| t.borrow_mut().remove(voice_id));
        Ok(())
    }
}
