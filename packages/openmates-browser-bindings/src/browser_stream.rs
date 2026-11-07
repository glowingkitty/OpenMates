//! Browser exports of the web AI-stream and reply-recovery decisions
//! (`openmates_sdk::web_stream`): stateless recovery ops served by the shared
//! Worker `sync` unit and the stateful stream assembler served by the `ws`
//! unit. Bindings only marshal JSON text.
//! spec: specifications/architecture/sync#sync.client.shared-rust-policy
use std::cell::RefCell;

use wasm_bindgen::prelude::*;

use openmates_sdk::web_stream::{assembler::StreamAssembler, recovery};

thread_local! {
    /// The Worker realm is single-threaded: one assembler per WASM instance.
    static ASSEMBLER: RefCell<StreamAssembler> = RefCell::new(StreamAssembler::default());
}

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// Recovered-reply version fence (`chatAfterRecoveredReply`).
#[wasm_bindgen]
pub fn stream_recovery_apply(input_json: &str) -> Result<String, JsValue> {
    js(recovery::apply_json(input_json))
}

/// Authoritative chat version of a window response (`refreshRecoveryChatVersion`).
#[wasm_bindgen]
pub fn stream_recovery_window_version(input_json: &str) -> Result<String, JsValue> {
    js(recovery::window_version_json(input_json))
}

/// Persisted-assistant proof of a window response (`refreshPersistedAssistantVersion`).
#[wasm_bindgen]
pub fn stream_recovery_assistant_version(input_json: &str) -> Result<String, JsValue> {
    js(recovery::assistant_version_json(input_json))
}

/// Unwritten initial diff read (`isUnwrittenInitialDiffRead`).
#[wasm_bindgen]
pub fn stream_recovery_initial_diff(input_json: &str) -> Result<String, JsValue> {
    js(recovery::initial_diff_json(input_json))
}

/// Recovered embed catalog identity (`catalogContextFromSealedEmbed`).
#[wasm_bindgen]
pub fn stream_recovery_catalog(input_json: &str) -> Result<String, JsValue> {
    js(recovery::catalog_json(input_json))
}

/// Historical embed source (`historySourceFromSealedEmbed`).
#[wasm_bindgen]
pub fn stream_recovery_history_source(input_json: &str) -> Result<String, JsValue> {
    js(recovery::history_source_json(input_json))
}

/// One stateful assembler op (`thinkingChunk`, `thinkingComplete`,
/// `finalTimestampRecord`, `finalTimestampGet`, `finalChunkPlan`, `reset`).
#[wasm_bindgen]
pub fn stream_assembler_op(op: &str, input_json: &str) -> Result<String, JsValue> {
    ASSEMBLER.with(|assembler| js(assembler.borrow_mut().dispatch(op, input_json)))
}
