//! Worker exports for the shared web app settings/memories request policy
//! (`settings` unit). Pure string-in/string-out functions over
//! `openmates_sdk::web_settings`; results are JSON text. A malformed input
//! rejects with the stable code `protocol`.
use wasm_bindgen::prelude::*;

use openmates_sdk::web_settings;

/// Dialog categories of a server request (`web_settings::category_plan_json`).
#[wasm_bindgen]
pub fn settings_category_plan(requested_keys_json: &str, counts_json: &str) -> Result<String, JsValue> {
    web_settings::category_plan_json(requested_keys_json, counts_json).map_err(|e| JsValue::from_str(&e))
}

/// Whether a system message already answers the request.
#[wasm_bindgen]
pub fn settings_request_answered(system_contents_json: &str, user_message_id: &str) -> Result<bool, JsValue> {
    web_settings::is_request_answered_json(system_contents_json, user_message_id).map_err(|e| JsValue::from_str(&e))
}

/// The persisted memory request system message.
#[wasm_bindgen]
pub fn settings_build_request_message(
    user_message_id: &str,
    request_id: &str,
    requested_keys_json: &str,
    created_at_json: &str,
    counts_json: &str,
    voice: bool,
) -> Result<String, JsValue> {
    web_settings::build_request_message_json(user_message_id, request_id, requested_keys_json, created_at_json, counts_json, voice)
        .map_err(|e| JsValue::from_str(&e))
}
