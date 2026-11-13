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

/// Natural-language request plan (`web_apps::request::request_plan_json`).
#[wasm_bindgen]
pub fn apps_request_plan(facts_json: &str, context_json: &str) -> Result<String, JsValue> {
    web_apps::request::request_plan_json(facts_json, context_json).map_err(|e| JsValue::from_str(&e))
}

/// Interpreter request body over the page's privacy-protected pieces.
#[wasm_bindgen]
#[allow(clippy::too_many_arguments)] // wasm-bindgen marshals flat strings only.
pub fn apps_request_body(
    facts_json: &str,
    request_id: &str,
    protected_text: &str,
    protected_context_json: &str,
    attachments_json: &str,
    protected_attachments_json: &str,
    assets_json: &str,
) -> Result<String, JsValue> {
    let protected = web_apps::request::ProtectedRequest {
        protected_text,
        protected_context_json,
        attachments_json,
        protected_attachments_json,
        assets_json,
    };
    web_apps::request::request_body_json(facts_json, request_id, &protected).map_err(|e| JsValue::from_str(&e))
}

/// Interpreter response decision.
#[wasm_bindgen]
pub fn apps_interpretation(ok: bool, text: &str, has_attachments: bool, has_chat: bool, has_workflow: bool) -> String {
    web_apps::request::interpretation_json(ok, text, has_attachments, has_chat, has_workflow)
}

/// Skill input validation issues (`[{code,path}]`).
#[wasm_bindgen]
pub fn apps_validate_input(schema_json: &str, input_json: &str) -> Result<String, JsValue> {
    web_apps::schema::validate_skill_input_json(schema_json, input_json).map_err(|e| JsValue::from_str(&e))
}

/// Result retention plan (paths into the page's response object).
#[wasm_bindgen]
pub fn apps_retention_plan(facts_json: &str, response_json: &str, previous_content: &str) -> Result<String, JsValue> {
    web_apps::results::retention_plan_json(facts_json, response_json, previous_content).map_err(|e| JsValue::from_str(&e))
}

/// Outbox record scope check.
#[wasm_bindgen]
pub fn apps_outbox_scope_valid(scope_json: &str) -> Result<bool, JsValue> {
    web_apps::results::outbox_scope_valid_json(scope_json).map_err(|e| JsValue::from_str(&e))
}

/// Indices of the fresh recommendations.
#[wasm_bindgen]
pub fn apps_fresh_recommendations(items_json: &str, now_ms: f64) -> Result<String, JsValue> {
    web_apps::results::fresh_recommendations_json(items_json, now_ms).map_err(|e| JsValue::from_str(&e))
}
