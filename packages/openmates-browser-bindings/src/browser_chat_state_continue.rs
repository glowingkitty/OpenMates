//! Worker export of the web continue-carousel decisions (`openmates_sdk::web_continue`),
//! served by the `chatState` shared-Worker unit op `continueDecide`. Marshalling only:
//! one op name plus JSON text in, JSON text out; an unknown op or malformed input
//! rejects and the adapter answers the fixed `protocol` code.
//! spec: specifications/features/continue-carousel#continue-carousel.chat.reminder-gated
use wasm_bindgen::prelude::*;

/// Runs one named continue-carousel decision (`reminderByChat`, `sortPriorities`) on a JSON document.
#[wasm_bindgen]
pub fn chat_state_continue_decide(op: &str, input_json: &str) -> Result<String, JsValue> {
    openmates_sdk::web_continue::run_json(op, input_json).map_err(|e| JsValue::from_str(&e))
}
