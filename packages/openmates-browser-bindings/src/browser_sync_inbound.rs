//! Inbound chat-update decision exports of the shared Rust core Worker `sync` unit.
//!
//! spec: specifications/architecture/sync#sync.client.shared-rust-policy
use wasm_bindgen::prelude::*;

use openmates_sdk::web_sync::inbound;

/// Draft-only shell clearing decision (`clearDraftOnlyShellForMessages`).
#[wasm_bindgen]
pub fn sync_draft_shell(input_json: &str) -> Result<String, JsValue> {
    inbound::draft_shell_json(input_json).map_err(|e| JsValue::from_str(&e))
}

/// Admission of a `chat_title_updated` / `chat_draft_updated` frame.
#[wasm_bindgen]
pub fn sync_update_frame(input_json: &str) -> Result<String, JsValue> {
    inbound::update_frame_json(input_json).map_err(|e| JsValue::from_str(&e))
}

/// Stale / cleared-version decision of an applied `chat_draft_updated` frame.
#[wasm_bindgen]
pub fn sync_draft_apply(input_json: &str) -> Result<String, JsValue> {
    inbound::draft_apply_json(input_json).map_err(|e| JsValue::from_str(&e))
}
