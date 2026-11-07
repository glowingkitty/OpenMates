//! Guest promotion export of the shared Worker `crypto` unit (share-guest-crypto lane).
//!
//! spec: specifications/features/auth#auth.keys.client-wrapped
//!
//! Marshals the JSON promotion plan of `openmates_sdk::web_guest` for
//! `anonymousChatPromotionService.ts`. No key material crosses this module.
use openmates_sdk::web_guest;
use wasm_bindgen::prelude::*;

/// Promotion plan for one anonymous chat (`{chat, messages}` JSON in, plan JSON out).
/// Rejects with `rust_guest_bad_request` for a malformed document.
#[wasm_bindgen(js_name = guestPromotionPlan)]
pub fn guest_promotion_plan(input: String) -> Result<String, JsValue> {
    web_guest::promotion_plan_json(&input).map_err(|_| JsValue::from_str("rust_guest_bad_request"))
}
