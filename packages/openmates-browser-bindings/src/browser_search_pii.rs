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

/// Worker-resident search corpus: texts cross the boundary once (`set_text`,
/// `set_texts_json`), then `search` runs entirely in wasm memory and returns
/// only matching entries as JSON (see `web_search_corpus`).
#[wasm_bindgen]
#[derive(Default)]
pub struct SearchCorpus {
    inner: openmates_sdk::web_search_corpus::SearchCorpus,
}

#[wasm_bindgen]
impl SearchCorpus {
    #[wasm_bindgen(constructor)]
    pub fn new() -> SearchCorpus {
        SearchCorpus::default()
    }

    pub fn set_text(&mut self, key: &str, text: &str) {
        self.inner.set(key, text);
    }

    /// `[[key,text],...]`
    pub fn set_texts_json(&mut self, entries_json: &str) -> Result<(), JsValue> {
        self.inner.set_many_json(entries_json).map_err(|e| JsValue::from_str(&e))
    }

    pub fn remove(&mut self, key: &str) {
        self.inner.remove(key);
    }

    pub fn len(&self) -> usize {
        self.inner.len()
    }

    pub fn search(&self, query: &str, max_snippets: usize) -> String {
        self.inner.search_json(query, max_snippets)
    }

    /// First match per text, at most `max_results` hits (the chat-search hot path).
    pub fn first_hits(&self, query: &str, max_results: usize) -> String {
        self.inner.first_hits_json(query, max_results)
    }
}

/// Worker-resident saved-memories index: `set_entries_json` once per memories
/// snapshot, then `search` per keystroke with only the query crossing the boundary.
#[wasm_bindgen]
#[derive(Default)]
pub struct SavedMemoriesIndex {
    inner: Option<openmates_sdk::web_search::SavedEmbedIndex>,
}

#[wasm_bindgen]
impl SavedMemoriesIndex {
    #[wasm_bindgen(constructor)]
    pub fn new() -> SavedMemoriesIndex {
        SavedMemoriesIndex::default()
    }

    pub fn set_entries_json(&mut self, entries_json: &str) -> Result<(), JsValue> {
        self.inner = Some(openmates_sdk::web_search_json::saved_embed_index_from_json(entries_json).map_err(|e| JsValue::from_str(&e))?);
        Ok(())
    }

    pub fn search(&self, query: &str, limit: i32) -> Result<String, JsValue> {
        match &self.inner {
            Some(index) => openmates_sdk::web_search_json::saved_embed_index_search_json(index, query, i64::from(limit))
                .map_err(|e| JsValue::from_str(&e)),
            None => Ok("[]".to_string()),
        }
    }
}

/// Worker-resident chat message search for the shared core `search` unit
/// (`web_search_chats`). Chats are addressed by page-assigned `u32` handles;
/// `search` returns flat `u32` rows (a `Uint32Array`) that carry entry indices
/// and UTF-16 snippet slice plans, never text.
#[wasm_bindgen]
#[derive(Default)]
pub struct ChatSearchIndex {
    inner: openmates_sdk::web_search_chats::ChatSearchIndex,
}

#[wasm_bindgen]
impl ChatSearchIndex {
    /// Empty index (one per shared Worker `search` unit).
    #[wasm_bindgen(constructor)]
    pub fn new() -> ChatSearchIndex {
        ChatSearchIndex::default()
    }

    /// Empties `handle` before its entries are pushed again.
    pub fn reset_chat(&mut self, handle: u32) {
        self.inner.reset_chat(handle);
    }

    /// Appends one entry in the page's index order (`embed_id` is empty for message text).
    pub fn push_entry(&mut self, handle: u32, message_id: &str, text: &str, embed_id: &str, embed_titled: bool) {
        self.inner.push_entry(handle, message_id, text, embed_id, embed_titled);
    }

    /// Drops `handle`.
    pub fn remove_chat(&mut self, handle: u32) {
        self.inner.remove_chat(handle);
    }

    /// Drops every chat (logout).
    pub fn clear(&mut self) {
        self.inner.clear();
    }

    /// Number of chats held.
    pub fn chat_count(&self) -> usize {
        self.inner.chat_count()
    }

    /// Flat result rows as a `Uint32Array` (layout in `web_search_chats`).
    pub fn search(&self, query: &str, handles: &[u32], include_embeds: bool) -> Vec<u32> {
        self.inner.search(query, handles, include_embeds)
    }
}
