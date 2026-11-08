//! Worker export of the web Project decisions (`openmates_sdk::web_projects`), served by
//! the `chatState` shared-Worker unit op `projectDecide`. Marshalling only: one op name
//! plus JSON text in, JSON text out; refusals are data, an unknown op or malformed input
//! rejects and the adapter answers the fixed `protocol` code.
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
use wasm_bindgen::prelude::*;

/// Runs one named Project decision (`PROJECT_STATE_POLICY` op) on a JSON document.
#[wasm_bindgen]
pub fn chat_state_project_decide(op: &str, input_json: &str) -> Result<String, JsValue> {
    openmates_sdk::web_projects::run_json(op, input_json).map_err(|e| JsValue::from_str(&e))
}
