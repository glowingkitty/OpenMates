//! Worker-resident search corpus. Texts are copied into the core once; every
//! query then runs on lowercase text kept next to the original, so a search
//! crosses the browser boundary with the query and returns only the hits.
//! Matching, UTF-16 offsets and snippets equal `findMatchRanges` / `buildSnippet`.
use crate::web_search::{lowered_hits, utf16_len};
use crate::web_search_json::{push_json_escaped, push_usize};
use crate::web_search_json::write_snippet_json;
use std::collections::HashMap;

struct Entry {
    key: String,
    text: String,
    lower: String,
    /// Every char keeps its UTF-8 and UTF-16 width when lowercased, so a byte
    /// offset found in `lower` is the same offset in `text`.
    same_layout: bool,
    lower_ascii: bool,
}

fn same_layout(text: &str, lower: &str) -> bool {
    text.len() == lower.len()
        && text.is_ascii() == lower.is_ascii()
        && (text.is_ascii() || text.chars().zip(lower.chars()).all(|(a, b)| a.len_utf8() == b.len_utf8() && a.len_utf16() == b.len_utf16()))
}

#[derive(Default)]
pub struct SearchCorpus {
    entries: Vec<Entry>,
    slots: HashMap<String, usize>,
}

impl SearchCorpus {
    /// Inserts or replaces the text stored under `key` (insertion order is kept).
    pub fn set(&mut self, key: &str, text: &str) {
        let lower = text.to_lowercase();
        let entry = Entry { key: key.to_string(), text: text.to_string(), same_layout: same_layout(text, &lower), lower_ascii: lower.is_ascii(), lower };
        match self.slots.get(key) {
            Some(&slot) => self.entries[slot] = entry,
            None => {
                self.slots.insert(key.to_string(), self.entries.len());
                self.entries.push(entry);
            }
        }
    }

    /// `[[key,text],...]`; a malformed payload is the stable error `protocol`.
    pub fn set_many_json(&mut self, entries_json: &str) -> Result<(), String> {
        let rows: Vec<(String, String)> = serde_json::from_str(entries_json).map_err(|_| "protocol".to_string())?;
        for (key, text) in &rows {
            self.set(key, text);
        }
        Ok(())
    }

    pub fn remove(&mut self, key: &str) {
        let Some(slot) = self.slots.remove(key) else { return };
        self.entries.swap_remove(slot);
        if let Some(moved) = self.entries.get(slot) {
            self.slots.insert(moved.key.clone(), slot);
        }
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// `[{"key":k,"ranges":[{"start","length"}],"snippets":[{"snippet","snippetMatchStart","snippetMatchLength"}]}]`
    /// for every text with at least one match (storage order after removals may differ
    /// from insertion order). Snippets are built for each text's first `max_snippets` ranges.
    pub fn search_json(&self, query: &str, max_snippets: usize) -> String {
        let lower_query = query.to_lowercase();
        let mut out = String::from("[");
        if lower_query.is_empty() {
            out.push(']');
            return out;
        }
        let mut first = true;
        for entry in &self.entries {
            let hits = lowered_hits(&entry.lower, entry.lower_ascii, &lower_query);
            if hits.is_empty() {
                continue;
            }
            if !first {
                out.push(',');
            }
            first = false;
            out.push_str("{\"key\":\"");
            push_json_escaped(&mut out, &entry.key);
            out.push_str("\",\"ranges\":[");
            for (j, (r, _)) in hits.iter().enumerate() {
                if j > 0 {
                    out.push(',');
                }
                out.push_str("{\"start\":");
                push_usize(&mut out, r.start);
                out.push_str(",\"length\":");
                push_usize(&mut out, r.length);
                out.push('}');
            }
            out.push_str("],\"snippets\":[");
            for (j, (r, byte)) in hits.iter().take(max_snippets).enumerate() {
                if j > 0 {
                    out.push(',');
                }
                write_snippet_json(&mut out, &entry.text, r.start, r.length, entry.same_layout.then_some(*byte));
            }
            out.push_str("]}");
        }
        out.push(']');
        out
    }

    /// Chat-search hot path (`searchMessagesInChat`): scans texts in storage order,
    /// takes the first match of each, and stops after `max_results` hits.
    /// `[{"key","snippet","snippetMatchStart","snippetMatchLength"}]`; the snippet is
    /// `buildSnippet(text, firstIndex, query.length)` with the UTF-16 length of the
    /// unlowered `query`, exactly as the TypeScript caller computes it.
    pub fn first_hits_json(&self, query: &str, max_results: usize) -> String {
        let lower_query = query.to_lowercase();
        let query_len = utf16_len(query);
        let mut out = String::from("[");
        let mut found = 0;
        let mut object = String::new();
        if !lower_query.is_empty() {
            for entry in &self.entries {
                if found >= max_results {
                    break;
                }
                let Some(byte) = entry.lower.find(lower_query.as_str()) else { continue };
                let start = if entry.lower_ascii { byte } else { utf16_len(&entry.lower[..byte]) };
                if found > 0 {
                    out.push(',');
                }
                found += 1;
                out.push_str("{\"key\":\"");
                push_json_escaped(&mut out, &entry.key);
                out.push_str("\",\"snippet\":");
                object.clear();
                write_snippet_json(&mut object, &entry.text, start, query_len, entry.same_layout.then_some(byte));
                // Splice the snippet object's members into this entry.
                out.push_str(&object["{\"snippet\":".len()..object.len() - 1]);
                out.push('}');
            }
        }
        out.push(']');
        out
    }
}
