//! Worker-only glue for the slides presentation remote (`slides.present.remote-*`).
//! Encrypt and decrypt run on the admitted shared core `Client`, which resolves the
//! deck's embed key by embed id inside the Worker (keys never cross to the page).
//! The per-embed ordering rule lives in a Worker-local table. Marshalling only:
//! states are JSON text, errors reject with the core's stable code string.
use super::BrowserCoreClient;
use openmates_sdk::client::shared_items::present_remote::{
    PresentRemoteError, PresentRemoteOrderings, PresentRemoteOrigin, PresentRemoteState,
};
use serde_json::{Value, json};
use std::cell::RefCell;
use wasm_bindgen::prelude::*;

thread_local! {
    // One Worker, one wasm instance: a thread-local is the Worker-wide table.
    static ORDERINGS: RefCell<PresentRemoteOrderings> = RefCell::new(PresentRemoteOrderings::default());
}

fn malformed() -> JsValue {
    JsValue::from_str("present_remote_malformed")
}

/// Parses the camelCase JSON of `presentRemoteClient.ts`; unknown fields are refused.
fn parse(state_json: &str) -> Result<PresentRemoteState, JsValue> {
    let value: Value = serde_json::from_str(state_json).map_err(|_| malformed())?;
    let map = value
        .as_object()
        .filter(|m| m.len() == 8)
        .ok_or_else(malformed)?;
    let text = |k: &str| {
        map.get(k)
            .and_then(Value::as_str)
            .map(str::to_owned)
            .ok_or_else(malformed)
    };
    let flag = |k: &str| map.get(k).and_then(Value::as_bool).ok_or_else(malformed);
    let number = |k: &str| map.get(k).and_then(Value::as_u64).ok_or_else(malformed);
    let small = |k: &str| u32::try_from(number(k)?).map_err(|_| malformed());
    let origin = match map.get("origin").and_then(Value::as_str) {
        Some("presenter") => PresentRemoteOrigin::Presenter,
        Some("remote") => PresentRemoteOrigin::Remote,
        _ => return Err(malformed()),
    };
    Ok(PresentRemoteState {
        embed_id: text("embedId")?,
        session_id: text("sessionId")?,
        seq: number("seq")?,
        index: small("index")?,
        step: small("step")?,
        notes_visible: flag("notesVisible")?,
        presenting: flag("presenting")?,
        origin,
    })
}

fn to_json(s: &PresentRemoteState) -> String {
    json!({
        "embedId": s.embed_id, "sessionId": s.session_id, "seq": s.seq, "index": s.index,
        "step": s.step, "notesVisible": s.notes_visible, "presenting": s.presenting,
        "origin": match s.origin { PresentRemoteOrigin::Presenter => "presenter", PresentRemoteOrigin::Remote => "remote" },
    })
    .to_string()
}

fn refuse(error: PresentRemoteError) -> JsValue {
    JsValue::from_str(error.code())
}

#[wasm_bindgen]
impl BrowserCoreClient {
    /// Encrypts the state (camelCase JSON) with the deck's embed key; resolves to the
    /// ciphertext string for the `slides_present_state` frame.
    pub async fn present_remote_encrypt(
        &mut self,
        handle: &str,
        generation: f64,
        state_json: &str,
    ) -> Result<String, JsValue> {
        self.status(handle, generation)?;
        let state = parse(state_json)?;
        self.client
            .present_remote_encrypt(&state)
            .await
            .map_err(refuse)
    }

    /// Decrypts a relayed ciphertext for `embed_id`; resolves to the state as camelCase JSON.
    pub async fn present_remote_decrypt(
        &mut self,
        handle: &str,
        generation: f64,
        embed_id: &str,
        ciphertext: &str,
    ) -> Result<String, JsValue> {
        self.status(handle, generation)?;
        let state = self
            .client
            .present_remote_decrypt(embed_id, ciphertext)
            .await
            .map_err(refuse)?;
        Ok(to_json(&state))
    }
}

/// Ordering decision of the shared core for one state (camelCase JSON), kept per
/// embed in the Worker. True when the state should be applied.
#[wasm_bindgen]
pub fn present_remote_accept(state_json: &str) -> Result<bool, JsValue> {
    let state = parse(state_json)?;
    Ok(ORDERINGS.with(|orderings| orderings.borrow_mut().accept(&state)))
}
