//! Worker exports of the web WebSocket lifecycle policy (`openmates_sdk::web_ws`).
//! Marshalling only: every export takes and returns JSON text; a malformed
//! input throws the fixed `protocol` code. Served by the `ws` shared-Worker unit.
use wasm_bindgen::prelude::*;

use openmates_sdk::web_ws::{close, liveness};

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// Decision for one WebSocket close event.
#[wasm_bindgen]
pub fn ws_close_plan(input_json: &str) -> Result<String, JsValue> {
    js(close::close_plan_json(input_json))
}

/// Decision after the REST session check of a close plan.
#[wasm_bindgen]
pub fn ws_session_result(input_json: &str) -> Result<String, JsValue> {
    js(close::session_result_json(input_json))
}

/// Capped exponential reconnect decision.
#[wasm_bindgen]
pub fn ws_reconnect_plan(input_json: &str) -> Result<String, JsValue> {
    js(close::reconnect_plan_json(input_json))
}

/// Pong-timeout decision.
#[wasm_bindgen]
pub fn ws_pong_timeout(input_json: &str) -> Result<String, JsValue> {
    js(liveness::pong_timeout_json(input_json))
}

/// Online/resume/connection-change decision.
#[wasm_bindgen]
pub fn ws_lifecycle(input_json: &str) -> Result<String, JsValue> {
    js(liveness::lifecycle_json(input_json))
}

/// Periodic-retry tick decision.
#[wasm_bindgen]
pub fn ws_periodic_retry(input_json: &str) -> Result<String, JsValue> {
    js(liveness::periodic_retry_json(input_json))
}
