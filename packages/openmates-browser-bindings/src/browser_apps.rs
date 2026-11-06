//! Worker exports for the shared web Apps skill execution policy (`apps` unit).
//! Pure string-in/string-out functions over `openmates_sdk::web_apps`; results
//! are JSON text. A malformed input rejects with the stable code `protocol`.
use wasm_bindgen::prelude::*;

use openmates_sdk::web_apps;

#[wasm_bindgen]
pub fn apps_details_request(app: &str, skill: &str, has_signal: bool) -> String {
    web_apps::details_request_json(app, skill, has_signal)
}

#[wasm_bindgen]
pub fn apps_details_outcome(status: u16, ok: bool, text: &str) -> String {
    web_apps::details_outcome_json(status, ok, text)
}

#[wasm_bindgen]
pub fn apps_execution_request(app: &str, skill: &str, guest: bool, team_id: &str, metadata_json: &str) -> Result<String, JsValue> {
    web_apps::execution_request_json(app, skill, guest, team_id, metadata_json).map_err(|e| JsValue::from_str(&e))
}

#[wasm_bindgen]
pub fn apps_availability_outcome(status: u16, ok: bool, text: &str) -> String {
    web_apps::availability_outcome_json(status, ok, text)
}

#[wasm_bindgen]
pub fn apps_skill_response(status: u16, ok: bool, text: &str, guest: bool) -> String {
    web_apps::skill_response_json(status, ok, text, guest)
}

#[wasm_bindgen]
pub fn apps_poll_step(task_id: &str, status: u16, ok: bool, text: &str) -> String {
    web_apps::poll_step_json(task_id, status, ok, text)
}

#[wasm_bindgen]
pub fn apps_assemble_tasks(envelope_text: &str, poll_texts_json: &str, check_failure: bool) -> Result<String, JsValue> {
    web_apps::assemble_tasks_json(envelope_text, poll_texts_json, check_failure).map_err(|e| JsValue::from_str(&e))
}

#[wasm_bindgen]
pub fn apps_availability_request(app: &str, skill: &str) -> String {
    web_apps::availability_request_json(app, skill)
}

#[wasm_bindgen]
pub fn apps_task_result(poll_text: &str) -> Result<String, JsValue> {
    web_apps::task_result_json(poll_text).map_err(|e| JsValue::from_str(&e))
}
