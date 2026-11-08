//! Worker export of the shared `work` decisions (parked wave-5 `work` lane):
//! one string-in/string-out function over `openmates_sdk::web_work`, called by
//! the `crypto` unit's `work` op (workOps.ts). Only marshals; no keys cross.
use openmates_sdk::web_work;
use wasm_bindgen::prelude::*;

/// Runs one work decision (`op` name, JSON input) and answers its JSON.
/// Rejects with `rust_work:<reason>` for an unknown op or a malformed document.
#[wasm_bindgen(js_name = workDecide)]
pub fn work_decide(op: String, input: String) -> Result<String, JsValue> {
    web_work::run_json(&op, &input).map_err(|reason| JsValue::from_str(&format!("rust_work:{reason}")))
}
