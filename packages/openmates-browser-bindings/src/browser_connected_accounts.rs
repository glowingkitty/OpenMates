//! Worker exports for the shared web connected-account decisions
//! (`connectedAccounts` unit). Pure string-in/string-out functions over
//! `openmates_sdk::web_connected_accounts`; results are JSON text. A malformed
//! envelope rejects with the stable code `protocol`. No refresh-token envelope
//! or other credential material crosses these exports.
use wasm_bindgen::prelude::*;

use openmates_sdk::web_connected_accounts;

/// Rows a send context reads, after the plaintext-field guard.
#[wasm_bindgen]
pub fn connected_accounts_select_send_rows(rows_json: &str, account_ids_json: &str) -> Result<String, JsValue> {
    web_connected_accounts::select_send_rows_json(rows_json, account_ids_json).map_err(|e| JsValue::from_str(&e))
}

/// Directory entries and token-ref plans over decrypted row facts.
#[wasm_bindgen]
pub fn connected_accounts_send_context_plan(input_json: &str) -> Result<String, JsValue> {
    web_connected_accounts::send_context_plan_json(input_json).map_err(|e| JsValue::from_str(&e))
}

/// Account summaries over decrypted row facts, with local-connector fallbacks.
#[wasm_bindgen]
pub fn connected_accounts_summary_plan(input_json: &str) -> Result<String, JsValue> {
    web_connected_accounts::summary_plan_json(input_json).map_err(|e| JsValue::from_str(&e))
}

/// Turn-token refs of a broker response completed from the (envelope-free) inputs.
#[wasm_bindgen]
pub fn connected_accounts_merge_token_refs(inputs_json: &str, payload_json: &str) -> Result<String, JsValue> {
    web_connected_accounts::tokens::merge_turn_token_refs_json(inputs_json, payload_json).map_err(|e| JsValue::from_str(&e))
}
