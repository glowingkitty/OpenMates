//! Worker exports of the web chat-state view policy (`openmates_sdk::web_chat_state`):
//! active-chat selection plans, unread bookkeeping and chat metadata derivation.
//! Marshalling only: every export takes and returns JSON text; malformed input
//! throws the fixed `protocol` code. Served by the `chatState` shared-Worker unit.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use wasm_bindgen::prelude::*;

use openmates_sdk::web_chat_state::{metadata, selection, unread};

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// URL hash plan of the active-chat store (`updateUrlHash`).
#[wasm_bindgen]
pub fn chat_state_selection_url_plan(input_json: &str) -> Result<String, JsValue> {
    js(selection::url_plan_json(input_json))
}

/// `globalChatSelected` mirror decision of the chat list.
#[wasm_bindgen]
pub fn chat_state_selection_global_selected(input_json: &str) -> Result<String, JsValue> {
    js(selection::global_selected_json(input_json))
}

/// Stale persisted-draft activation guard of the chat list.
#[wasm_bindgen]
pub fn chat_state_selection_draft_activation(input_json: &str) -> Result<String, JsValue> {
    js(selection::draft_activation_json(input_json))
}

/// Unread store mutation (`{state, event}` to the new state).
#[wasm_bindgen]
pub fn chat_state_unread_reduce(input_json: &str) -> Result<String, JsValue> {
    js(unread::reduce_json(input_json))
}

/// Unread read model of one chat.
#[wasm_bindgen]
pub fn chat_state_unread_query(input_json: &str) -> Result<String, JsValue> {
    js(unread::query_json(input_json))
}

/// Mark-as-read gate (`markWhenSettled` checks).
#[wasm_bindgen]
pub fn chat_state_unread_read_gate(input_json: &str) -> Result<String, JsValue> {
    js(unread::read_gate_json(input_json))
}

/// List `Chat` of a shared sub-chat row (`sharedSubChatToChat`).
#[wasm_bindgen]
pub fn chat_state_metadata_shared_sub_chat(input_json: &str) -> Result<String, JsValue> {
    js(metadata::shared_sub_chat_json(input_json))
}
