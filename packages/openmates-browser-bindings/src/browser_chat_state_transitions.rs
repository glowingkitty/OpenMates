//! Worker exports of the web message-list transition, running-chat activity and
//! typing/streaming indicator policies (`openmates_sdk::web_chat_state`).
//! Marshalling only: every export takes and returns JSON text; a malformed
//! input throws the fixed `protocol` code. Served by the `chatState` shared-Worker unit.
//! spec: specifications/architecture/sync/specification.yml#sync.client.shared-rust-policy
use wasm_bindgen::prelude::*;

use openmates_sdk::web_chat_state::{activity, indicators, timeline, window};

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// Decrypted message window pruning (`pruneDecryptedMessageWindow`): kept input indices.
#[wasm_bindgen]
pub fn chat_state_window_prune(input_json: &str) -> Result<String, JsValue> {
    js(window::prune_json(input_json))
}

/// `shouldPreserveExpandedMessageWindow`.
#[wasm_bindgen]
pub fn chat_state_window_preserve(input_json: &str) -> Result<String, JsValue> {
    js(window::preserve_json(input_json))
}

/// `mergeTimelineEntries`: winning input indices in display order.
#[wasm_bindgen]
pub fn chat_state_timeline_merge(input_json: &str) -> Result<String, JsValue> {
    js(timeline::merge_json(input_json))
}

/// `buildTimelineExchangeIndex`.
#[wasm_bindgen]
pub fn chat_state_timeline_index(input_json: &str) -> Result<String, JsValue> {
    js(timeline::exchange_index_json(input_json))
}

/// `timelineResponseId`.
#[wasm_bindgen]
pub fn chat_state_timeline_response(input_json: &str) -> Result<String, JsValue> {
    js(timeline::response_id_json(input_json))
}

/// `pairTimelineExchange` decision.
#[wasm_bindgen]
pub fn chat_state_timeline_pair(input_json: &str) -> Result<String, JsValue> {
    js(timeline::pair_json(input_json))
}

/// `processingAncestorIds`.
#[wasm_bindgen]
pub fn chat_state_activity_ancestors(input_json: &str) -> Result<String, JsValue> {
    js(activity::ancestors_json(input_json))
}

/// `aggregateRunningChats`.
#[wasm_bindgen]
pub fn chat_state_activity_aggregate(input_json: &str) -> Result<String, JsValue> {
    js(activity::aggregate_json(input_json))
}

/// Composer typing/processing indicator lines and status type.
#[wasm_bindgen]
pub fn chat_state_indicator_composer(input_json: &str) -> Result<String, JsValue> {
    js(indicators::composer_json(input_json))
}

/// Chat-row title typing indicator.
#[wasm_bindgen]
pub fn chat_state_indicator_title(input_json: &str) -> Result<String, JsValue> {
    js(indicators::title_json(input_json))
}
