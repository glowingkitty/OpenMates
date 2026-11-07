//! Worker exports for the shared `composer` unit (paste classification, PII
//! detect/redact/restore, known-original rewrite, local-model span merge,
//! mention/saved-embed ranking, ghost-suggestion validation).
//! Pure string-in/string-out JSON text functions; a malformed payload rejects
//! with the stable code `protocol` (`invalid_offsets` for model offset breaks).
use openmates_sdk::web_composer::{mentions, paste, pii_detect, pii_text, rewrite, suggestions, web_pii};
use wasm_bindgen::prelude::*;

fn js(result: Result<String, String>) -> Result<String, JsValue> {
    result.map_err(|e| JsValue::from_str(&e))
}

/// `classifyPastedContent`.
#[wasm_bindgen]
pub fn composer_paste_classify(input: &str) -> Result<String, JsValue> {
    js(paste::classify_pasted_content_json(input))
}

/// `plainTextToDocumentHtml`.
#[wasm_bindgen]
pub fn composer_plain_text_to_html(input: &str) -> Result<String, JsValue> {
    js(paste::plain_text_to_document_html_json(input))
}

/// `detectPII`.
#[wasm_bindgen]
pub fn composer_pii_detect(input: &str) -> Result<String, JsValue> {
    js(pii_detect::detect_json(input))
}

/// `replacePIIWithPlaceholders`.
#[wasm_bindgen]
pub fn composer_pii_replace(input: &str) -> Result<String, JsValue> {
    js(pii_text::replace_json(input))
}

/// `restorePIIInText`.
#[wasm_bindgen]
pub fn composer_pii_restore(input: &str) -> Result<String, JsValue> {
    js(pii_text::restore_json(input))
}

/// `replacePIIOriginalsWithPlaceholders`.
#[wasm_bindgen]
pub fn composer_pii_replace_originals(input: &str) -> Result<String, JsValue> {
    js(pii_text::replace_originals_json(input))
}

/// `findRestoredPIIPositions`.
#[wasm_bindgen]
pub fn composer_pii_find_restored(input: &str) -> Result<String, JsValue> {
    js(pii_text::find_restored_json(input))
}

/// `createPIISummary`.
#[wasm_bindgen]
pub fn composer_pii_summary(input: &str) -> Result<String, JsValue> {
    js(pii_text::summary_json(input))
}

/// `rewriteKnownPIIPlaceholders`.
#[wasm_bindgen]
pub fn composer_pii_rewrite(input: &str) -> Result<String, JsValue> {
    js(rewrite::rewrite_json(input))
}

/// `buildWebPIIWindows`.
#[wasm_bindgen]
pub fn composer_pii_windows(input: &str) -> Result<String, JsValue> {
    js(web_pii::windows_json(input))
}

/// `mergeWebPIIWindowEntities`.
#[wasm_bindgen]
pub fn composer_pii_merge_window_entities(input: &str) -> Result<String, JsValue> {
    js(web_pii::merge_window_entities_json(input))
}

/// `mergeWebPIIMatches`.
#[wasm_bindgen]
pub fn composer_pii_merge_matches(input: &str) -> Result<String, JsValue> {
    js(web_pii::merge_matches_json(input))
}

/// `rankMentionResults` (indices and scores).
#[wasm_bindgen]
pub fn composer_mentions_rank(input: &str) -> Result<String, JsValue> {
    js(mentions::rank_mentions_json(input))
}

/// `rankSavedEmbedIndex` (indices).
#[wasm_bindgen]
pub fn composer_saved_embeds_rank(input: &str) -> Result<String, JsValue> {
    js(mentions::rank_saved_embeds_json(input))
}

/// `decodeComposerGhostSuggestion` validity.
#[wasm_bindgen]
pub fn composer_ghost_validate(input: &str) -> Result<String, JsValue> {
    js(suggestions::ghost_validate_json(input))
}
