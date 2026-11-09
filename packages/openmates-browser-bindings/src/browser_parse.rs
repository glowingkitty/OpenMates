//! Browser binding of the shared Rust message-parsing block model (`web_parse`).
//! Marshals JSON text only; the `parse` unit of the shared Worker calls these.
use wasm_bindgen::prelude::*;

use openmates_sdk::web_parse::{blocks, image_recovery, voice_cues};

/// Parent embed ids a saved image answer needs read (`image_recovery::lost_image_parents_json`).
#[wasm_bindgen]
pub fn parse_image_recovery_parents(source_json: &str) -> Result<String, JsValue> {
    image_recovery::lost_image_parents_json(source_json).map_err(|e| JsValue::from_str(&e))
}

/// Recovered saved image answer or `null` (`image_recovery::recover_generated_images_json`).
#[wasm_bindgen]
pub fn parse_recover_generated_images(source_json: &str, parents_json: &str) -> Result<String, JsValue> {
    image_recovery::recover_generated_images_json(source_json, parents_json).map_err(|e| JsValue::from_str(&e))
}

/// Block plan of one assistant message (`blocks::plan_blocks_json`).
#[wasm_bindgen]
pub fn parse_plan_blocks(markdown: &str, phase: &str, previous_json: &str) -> Result<String, JsValue> {
    blocks::plan_blocks_json(markdown, phase, previous_json).map_err(|e| JsValue::from_str(&e))
}

/// Read projection of an assistant message without voice-delivery cues (`voice_cues::strip_voice_cues`).
#[wasm_bindgen]
pub fn parse_strip_voice_cues(markdown: &str) -> String {
    voice_cues::strip_voice_cues(markdown)
}

/// Semantic summary of a compiled plan (`blocks::normalize_json`).
#[wasm_bindgen]
pub fn parse_normalize_plan(plan_json: &str) -> Result<String, JsValue> {
    blocks::normalize_json(plan_json).map_err(|e| JsValue::from_str(&e))
}

/// Chat Recommendations reconcile (`recommendations::reconcile_recommendations_json`).
#[wasm_bindgen]
pub fn parse_reconcile_recommendations(input_json: &str) -> Result<String, JsValue> {
    openmates_sdk::client::recommendations::reconcile_recommendations_json(input_json).map_err(|e| JsValue::from_str(&e.to_string()))
}

/// Validated `context_entry` system message content (`recommendations::build_context_entry_event_json`).
#[wasm_bindgen]
pub fn parse_build_context_entry_event(event_json: &str) -> Result<String, JsValue> {
    openmates_sdk::client::recommendations::build_context_entry_event_json(event_json).map_err(|e| JsValue::from_str(&e.to_string()))
}

/// Event object or `null` for system message content (`recommendations::parse_context_entry_event_json`).
#[wasm_bindgen]
pub fn parse_context_entry_event(content: &str) -> String {
    openmates_sdk::client::recommendations::parse_context_entry_event_json(content)
}
