//! Worker exports of the web chat-sync decision policy (`openmates_sdk::web_sync`).
//! Marshalling only: every export takes and returns JSON text; a malformed
//! input throws the fixed `protocol` code. Served by the `sync` shared-Worker unit.
use wasm_bindgen::prelude::*;

use openmates_sdk::web_sync::{merge, message_keys, phased, updates};

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// Server/local chat merge (`mergeServerChatWithLocal`).
#[wasm_bindgen]
pub fn sync_merge_chat(input_json: &str) -> Result<String, JsValue> {
    js(merge::merge_json(input_json))
}

/// Chat-key mismatch decision (`hasEncryptedChatKeyMismatch`).
#[wasm_bindgen]
pub fn sync_key_mismatch(input_json: &str) -> Result<String, JsValue> {
    js(merge::key_mismatch_json(input_json))
}

/// Phased-sync retryable-error step.
#[wasm_bindgen]
pub fn sync_retry_step(input_json: &str) -> Result<String, JsValue> {
    js(phased::retry_json(input_json))
}

/// Key admission of one synced chat.
#[wasm_bindgen]
pub fn sync_chat_admission(input_json: &str) -> Result<String, JsValue> {
    js(phased::admission_json(input_json))
}

/// Metadata-only chat record (load more / metadata sync).
#[wasm_bindgen]
pub fn sync_metadata_chat(input_json: &str) -> Result<String, JsValue> {
    js(phased::metadata_chat_json(input_json))
}

/// Authoritative deletion plan.
#[wasm_bindgen]
pub fn sync_deletion_plan(input_json: &str) -> Result<String, JsValue> {
    js(phased::deletion_plan_json(input_json))
}

/// Synced-message key plan.
#[wasm_bindgen]
pub fn sync_message_key_plan(input_json: &str) -> Result<String, JsValue> {
    js(message_keys::plan_json(input_json))
}

/// Notification preview of an assistant reply (UTF-16 units).
#[wasm_bindgen]
pub fn sync_message_preview(input_json: &str) -> Result<String, JsValue> {
    js(updates::preview_json(input_json))
}

/// Validation of the thinking fields of a recovered message.
#[wasm_bindgen]
pub fn sync_thinking_fields(input_json: &str) -> Result<String, JsValue> {
    js(updates::thinking_fields_json(input_json))
}
