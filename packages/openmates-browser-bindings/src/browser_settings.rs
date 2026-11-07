//! Worker exports for the shared web app settings/memories request policy
//! (`settings` unit). Pure string-in/string-out functions over
//! `openmates_sdk::web_settings`; results are JSON text. A malformed input
//! rejects with the stable code `protocol`.
use wasm_bindgen::prelude::*;

use openmates_sdk::web_settings;
use openmates_sdk::web_settings::response;
use openmates_sdk::web_settings_privacy;

/// Hydration plan of one decrypted privacy entry (`web_settings_privacy::plan_privacy_entry_json`).
#[wasm_bindgen]
pub fn settings_plan_privacy_entry(item_type: &str, data_json: &str, default_categories_json: &str) -> Result<String, JsValue> {
    web_settings_privacy::plan_privacy_entry_json(item_type, data_json, default_categories_json).map_err(|e| JsValue::from_str(&e))
}

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

/// Routes of the selected dialog keys (`response::plan_selected_keys_json`).
#[wasm_bindgen]
pub fn settings_plan_selected_keys(selected_keys_json: &str) -> Result<String, JsValue> {
    response::plan_selected_keys_json(selected_keys_json).map_err(|e| JsValue::from_str(&e))
}

/// Entry ids released for a category (`response::select_entry_ids_json`).
#[wasm_bindgen]
pub fn settings_select_entry_ids(entry_ids_json: &str, selection_json: &str) -> Result<String, JsValue> {
    response::select_entry_ids_json(entry_ids_json, selection_json).map_err(|e| JsValue::from_str(&e))
}

/// Response categories with released counts (`response::response_categories_json`).
#[wasm_bindgen]
pub fn settings_response_categories(categories_json: &str, released_json: &str) -> Result<String, JsValue> {
    response::response_categories_json(categories_json, released_json).map_err(|e| JsValue::from_str(&e))
}

/// What the confirm handler does after collecting entries (`response::confirm_outcome_json`).
#[wasm_bindgen]
pub fn settings_confirm_outcome(released_count: u32, voice: bool, has_message_id: bool) -> String {
    response::confirm_outcome_json(u64::from(released_count), voice, has_message_id)
}

/// Content of the persisted response system message (`response::response_content_json`).
#[wasm_bindgen]
pub fn settings_response_content(user_message_id: &str, action: &str, categories_json: &str) -> Result<String, JsValue> {
    response::response_content_json(user_message_id, action, categories_json).map_err(|e| JsValue::from_str(&e))
}
