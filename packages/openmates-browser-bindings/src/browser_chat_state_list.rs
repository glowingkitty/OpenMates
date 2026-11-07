//! Worker exports of the web chat-list ordering and grouping policy
//! (`openmates_sdk::web_chat_state`). Marshalling only: every export takes and
//! returns JSON text; a malformed input throws the fixed `protocol` code.
//! Served by the `chatState` shared-Worker unit.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use wasm_bindgen::prelude::*;

use openmates_sdk::web_chat_state::list;

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// Chat-list display order (`sortChats`): input indices, best first.
#[wasm_bindgen]
pub fn chat_state_sort(input_json: &str) -> Result<String, JsValue> {
    js(list::sort_json(input_json))
}

/// Chat-list time grouping (`groupChats`): `[key, [input indices]]` pairs.
#[wasm_bindgen]
pub fn chat_state_group(input_json: &str) -> Result<String, JsValue> {
    js(list::group_json(input_json))
}
