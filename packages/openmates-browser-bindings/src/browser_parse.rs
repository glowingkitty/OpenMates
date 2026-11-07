//! Browser binding of the shared Rust message-parsing block model (`web_parse`).
//! Marshals JSON text only; the `parse` unit of the shared Worker calls these.
use wasm_bindgen::prelude::*;

use openmates_sdk::web_parse::{blocks, voice_cues};

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
