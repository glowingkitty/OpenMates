//! Share-state decision export of the shared Worker `crypto` unit (share-guest-crypto lane).
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//!
//! Marshals the generic JSON decision runner of `openmates_sdk::web_share_state` for
//! the thin TS adapters in `services/shareState`. No key material crosses this module.
//! Share-state decision export of the shared Worker `crypto` unit (share-guest-crypto lane).
//!
//! spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
//!
//! Marshals the JSON decisions of `openmates_sdk::web_share_state` for the
//! share/guest/incognito adapters. No key material crosses this module.
use openmates_sdk::web_share_state;
use wasm_bindgen::prelude::*;

/// Runs one share-state decision (`op` name, JSON input) and answers its JSON.
/// Rejects with `rust_share_state:<reason>` for an unknown op or a malformed document.
#[wasm_bindgen(js_name = shareStateDecide)]
pub fn share_state_decide(op: String, input: String) -> Result<String, JsValue> {
    web_share_state::run_json(&op, &input).map_err(|reason| JsValue::from_str(&format!("rust_share_state:{reason}")))
}
