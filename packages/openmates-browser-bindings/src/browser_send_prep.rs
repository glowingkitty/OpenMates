//! spec: specifications/features/chats#chats.message.identity-idempotent
use wasm_bindgen::prelude::*;

use openmates_sdk::web_send_prep;

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// Replay order of queued offline changes (`orderOfflineChanges`).
#[wasm_bindgen]
pub fn send_prep_order_offline(input: &str) -> Result<String, JsValue> {
    js(web_send_prep::outbox_order::order_offline_changes_json(input))
}

/// Accepted and retired-conflict ids of an offline sync batch receipt.
#[wasm_bindgen]
pub fn send_prep_offline_receipt(input: &str) -> Result<String, JsValue> {
    js(web_send_prep::outbox_receipt::offline_batch_receipt_json(input))
}

/// Validated per-turn model routing restrictions (`modelRoutingRestrictionsForTurn`).
#[wasm_bindgen]
pub fn send_prep_routing_restrictions(input: &str) -> Result<String, JsValue> {
    js(web_send_prep::routing_restrictions::model_routing_restrictions_json(input))
}
