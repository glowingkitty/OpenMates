//! Worker exports for the shared web search and PII alias ports (U16/U18).
//! Pure string-in/string-out functions; results are JSON text. A malformed
//! input rejects with the stable code `protocol`.
use wasm_bindgen::prelude::*;

#[wasm_bindgen]
pub fn search_find_match_ranges(text: &str, query: &str) -> Result<String, JsValue> {
    openmates_sdk::web_search_json::find_match_ranges_json(text, query)
        .map_err(|e| JsValue::from_str(&e))
}

#[wasm_bindgen]
pub fn search_build_snippet(content: &str, match_start: usize, match_length: usize) -> String {
    openmates_sdk::web_search_json::build_snippet_json(content, match_start, match_length)
}

#[wasm_bindgen]
pub fn search_saved_embed_memories(
    entries_json: &str,
    query: &str,
    limit: i32,
) -> Result<String, JsValue> {
    openmates_sdk::web_search_json::search_saved_embed_memories_json(
        entries_json,
        query,
        i64::from(limit),
    )
    .map_err(|e| JsValue::from_str(&e))
}

#[wasm_bindgen]
pub fn pii_create_display_aliases(
    source_json: &str,
    mappings_json: &str,
    configured_json: &str,
) -> Result<String, JsValue> {
    openmates_sdk::web_search_json::create_pii_display_aliases_json(
        source_json,
        mappings_json,
        configured_json,
    )
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
        self.inner
            .set_many_json(entries_json)
            .map_err(|e| JsValue::from_str(&e))
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
        self.inner = Some(
            openmates_sdk::web_search_json::saved_embed_index_from_json(entries_json)
                .map_err(|e| JsValue::from_str(&e))?,
        );
        Ok(())
    }

    pub fn search(&self, query: &str, limit: i32) -> Result<String, JsValue> {
        match &self.inner {
            Some(index) => openmates_sdk::web_search_json::saved_embed_index_search_json(
                index,
                query,
                i64::from(limit),
            )
            .map_err(|e| JsValue::from_str(&e)),
            None => Ok("[]".to_string()),
        }
    }
}

/// Worker-resident chat search for the shared core `search` unit
/// (`web_search_chats` index + `web_search_query`). The page ingests each chat's
/// entries once (column arrays) and keeps no copy; a query returns flat `u32`
/// rows, a text table and embed timestamps (layout: `web_search_query::EncodedOutcome`).
/// Malformed columns reject with the stable code `protocol`.
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

    /// Replaces `handle`'s entries; returns the handles evicted by the index budget.
    #[allow(clippy::too_many_arguments)] // Flat wire columns: one wasm call per chat, no per-field JS reads.
    pub fn ingest_chat(
        &mut self,
        handle: u32,
        message_ids: Vec<String>,
        contents: Vec<String>,
        created_at: Vec<f64>,
        meta_entries: Vec<u32>,
        meta_masks: Vec<u16>,
        meta_values: Vec<String>,
    ) -> Result<Vec<u32>, JsValue> {
        let entries = openmates_sdk::web_search_chats::decode_ingest(
            message_ids,
            contents,
            &created_at,
            &meta_entries,
            &meta_masks,
            meta_values,
        )
        .map_err(|error| JsValue::from_str(error.code()))?;
        Ok(self.inner.ingest_chat(handle, entries))
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

    /// One complete search; returns `{ rows: Uint32Array, texts: string[], numbers: Float64Array }`.
    #[allow(clippy::too_many_arguments)] // Flat wire columns of `web_search_query::QueryColumns`.
    pub fn query(
        &mut self,
        query: &str,
        flags: u32,
        handles: Vec<u32>,
        chat_masks: Vec<u8>,
        chat_values: Vec<String>,
        tag_counts: Vec<u32>,
        last_edited: Vec<f64>,
        catalog_flags: Vec<u8>,
        catalog_labels: Vec<String>,
        catalog_keyword_counts: Vec<u32>,
        catalog_keywords: Vec<String>,
    ) -> Result<js_sys::Object, JsValue> {
        use openmates_sdk::web_search_query::{run_search, QueryColumns, SearchQuery, Text};
        let request = SearchQuery::from_wire(QueryColumns {
            query,
            flags,
            handles: &handles,
            chat_masks: &chat_masks,
            chat_values,
            tag_counts: &tag_counts,
            last_edited: &last_edited,
            catalog_flags: &catalog_flags,
            catalog_labels,
            catalog_keyword_counts: &catalog_keyword_counts,
            catalog_keywords,
        })
        .map_err(|error| JsValue::from_str(error.code()))?;
        self.inner.touch(&request.handles());
        let encoded = run_search(&self.inner, &request).encode();
        let texts = js_sys::Array::new_with_length(encoded.texts.len() as u32);
        for (at, text) in encoded.texts.iter().enumerate() {
            let value: JsValue = match text {
                Text::Str(text) => JsValue::from_str(text),
                // Exact UTF-16 (a cut surrogate pair stays a lone surrogate, as JS `slice` leaves it).
                Text::Units(units) => js_sys::JsString::from_char_code(units).into(),
            };
            texts.set(at as u32, value);
        }
        let out = js_sys::Object::new();
        let set = |key: &str, value: &JsValue| {
            js_sys::Reflect::set(&out, &JsValue::from_str(key), value).map(|_| ())
        };
        set(
            "rows",
            &js_sys::Uint32Array::from(encoded.rows.as_slice()).into(),
        )?;
        set("texts", &texts.into())?;
        set(
            "numbers",
            &js_sys::Float64Array::from(encoded.numbers.as_slice()).into(),
        )?;
        Ok(out)
    }
}
