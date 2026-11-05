//! Worker exports for the shared web search and PII alias ports (U16/U18).
//! Pure string-in/string-out functions; results are JSON text. A malformed
//! input rejects with the stable code `protocol`.
use wasm_bindgen::prelude::*;

#[wasm_bindgen]
pub fn search_find_match_ranges(text: &str, query: &str) -> Result<String, JsValue> {
    openmates_sdk::web_search_json::find_match_ranges_json(text, query).map_err(|e| JsValue::from_str(&e))
}

#[wasm_bindgen]
pub fn search_build_snippet(content: &str, match_start: usize, match_length: usize) -> String {
    openmates_sdk::web_search_json::build_snippet_json(content, match_start, match_length)
}

#[wasm_bindgen]
pub fn search_saved_embed_memories(entries_json: &str, query: &str, limit: i32) -> Result<String, JsValue> {
    openmates_sdk::web_search_json::search_saved_embed_memories_json(entries_json, query, i64::from(limit))
        .map_err(|e| JsValue::from_str(&e))
}

#[wasm_bindgen]
pub fn pii_create_display_aliases(source_json: &str, mappings_json: &str, configured_json: &str) -> Result<String, JsValue> {
    openmates_sdk::web_search_json::create_pii_display_aliases_json(source_json, mappings_json, configured_json)
        .map_err(|e| JsValue::from_str(&e))
}
