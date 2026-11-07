//! WASM exports of the web IndexedDB row-policy `persist` unit. Marshalling only:
//! each export forwards JSON text to `openmates_sdk::web_persist` and returns its
//! JSON text; a thrown string is the boundary's fixed `protocol` code.
//!
//! spec: specifications/architecture/storage-lifecycle#storage.client.shared-policy-existing-adapters
use wasm_bindgen::prelude::*;

use openmates_sdk::web_persist::message_policy;

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// `shouldUpdateMessage` over stored/incoming message pairs.
#[wasm_bindgen]
pub fn persist_message_should_update(input_json: &str) -> Result<String, JsValue> {
    js(message_policy::should_update_json(input_json))
}

/// The update and fill-encrypted-fields checks of `saveMessage`.
#[wasm_bindgen]
pub fn persist_message_save_decision(input_json: &str) -> Result<String, JsValue> {
    js(message_policy::save_decision_json(input_json))
}

/// `findContentDuplicate` over the chat's stored messages.
#[wasm_bindgen]
pub fn persist_message_content_duplicate(input_json: &str) -> Result<String, JsValue> {
    js(message_policy::content_duplicate_json(input_json))
}

/// `isSafeToEvictMessage` over stored rows.
#[wasm_bindgen]
pub fn persist_message_safe_to_evict(input_json: &str) -> Result<String, JsValue> {
    js(message_policy::safe_to_evict_json(input_json))
}
