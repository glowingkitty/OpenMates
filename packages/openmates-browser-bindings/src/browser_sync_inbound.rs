//! Inbound chat-update decision exports of the shared Rust core Worker `sync` unit.
//!
//! spec: specifications/architecture/sync#sync.client.shared-rust-policy
use wasm_bindgen::prelude::*;

use openmates_sdk::web_sync::{inbound, message_prep, versions};

/// Version plan of an `encrypted_chat_metadata` broadcast (`metadataVersionPlanTs`).
#[wasm_bindgen]
pub fn sync_metadata_versions(input_json: &str) -> Result<String, JsValue> {
    versions::metadata_versions_json(input_json).map_err(|e| JsValue::from_str(&e))
}

/// Versionless / stale / cleared-version plan of a `draft_deleted` frame (`draftDeletedPlanTs`).
#[wasm_bindgen]
pub fn sync_draft_deleted(input_json: &str) -> Result<String, JsValue> {
    versions::draft_deleted_json(input_json).map_err(|e| JsValue::from_str(&e))
}

/// Forward-only `messages_v` advance (`messagesVersionTs`).
#[wasm_bindgen]
pub fn sync_messages_version(input_json: &str) -> Result<String, JsValue> {
    versions::messages_version_json(input_json).map_err(|e| JsValue::from_str(&e))
}

/// Storage preparation plan of synced messages (`chatSyncMessagePrep.ts`).
#[wasm_bindgen]
pub fn sync_message_prep(input_json: &str) -> Result<String, JsValue> {
    message_prep::message_prep_json(input_json).map_err(|e| JsValue::from_str(&e))
}

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
