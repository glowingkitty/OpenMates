//! Browser export for the web signup/pair/recovery-print policy. Marshals one
//! JSON call into `openmates_sdk::web_auth::flow_call`; the policy lives in the
//! shared core. Refusals are the core's fixed codes (`flow_op`, `flow_args`).
//! spec: specifications/features/auth#auth.pair-login.lifecycle
use openmates_sdk::web_auth;
use wasm_bindgen::prelude::*;

/// Largest accepted argument payload (a print page request is the biggest).
const MAX_ARGS_BYTES: usize = 64 * 1024;

/// Runs the named policy call with JSON `args`; returns the JSON result.
#[wasm_bindgen]
pub fn web_auth_flow(name: &str, args_json: &str) -> Result<String, JsValue> {
    if args_json.len() > MAX_ARGS_BYTES {
        return Err(JsValue::from_str("flow_args"));
    }
    let args: serde_json::Value =
        serde_json::from_str(args_json).map_err(|_| JsValue::from_str("flow_args"))?;
    let value = web_auth::flow_call(name, &args).map_err(|error| match error {
        openmates_sdk::Error::Invalid(code) => JsValue::from_str(code),
        _ => JsValue::from_str("protocol"),
    })?;
    serde_json::to_string(&value).map_err(|_| JsValue::from_str("protocol"))
}
