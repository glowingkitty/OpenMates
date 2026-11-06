//! Pure port of the client-side web search helpers.
//!
//! Ports `searchService.ts` (`findMatchRanges`, `buildSnippet`) and
//! `embedSuggestionSearch.ts` (`searchSavedEmbedMemories`). All offsets are
//! UTF-16 code units so results are byte-identical to the TypeScript original.
//! Browser IO, decryption and the message index stay in the web adapter.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

/// Context characters kept before and after a snippet match.
pub const SNIPPET_CONTEXT_CHARS: usize = 50;

/// One non-overlapping match, measured in UTF-16 code units of the lowercased text.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct MatchRange {
    pub start: usize,
    pub length: usize,
}

/// Snippet built around a match; `units` is the UTF-16 snippet text.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Snippet {
    pub units: Vec<u16>,
    pub match_start: usize,
    pub match_length: usize,
}

impl Snippet {
    /// Lossy text view; lone surrogates (cut emoji) become U+FFFD.
    pub fn text(&self) -> String {
        String::from_utf16_lossy(&self.units)
    }
}

/// `findMatchRanges`: case-insensitive, non-overlapping. An empty query yields
/// no ranges (the TypeScript loop never terminates for it; callers guard).
/// Searches the lowercased UTF-8 text and converts offsets to UTF-16 units
/// incrementally, so no UTF-16 copy of the text is made.
pub fn find_match_ranges(text: &str, query: &str) -> Vec<MatchRange> {
    let lower_query = query.to_lowercase();
    if lower_query.is_empty() {
        return Vec::new();
    }
    lowered_ranges(&text.to_lowercase(), &lower_query)
}

/// Non-overlapping ranges of an already lowercased query in already lowercased text.
pub(crate) fn lowered_ranges(lower_text: &str, lower_query: &str) -> Vec<MatchRange> {
    lowered_hits(lower_text, lower_text.is_ascii(), lower_query).into_iter().map(|(range, _)| range).collect()
}

/// Like `lowered_ranges`, each range paired with the UTF-8 offset of its start in `lower_text`.
pub(crate) fn lowered_hits(lower_text: &str, ascii: bool, lower_query: &str) -> Vec<(MatchRange, usize)> {
    let length = utf16_len(lower_query);
    let mut hits = Vec::new();
    let (mut last_byte, mut last_unit) = (0, 0);
    for (byte, _) in lower_text.match_indices(lower_query) {
        let start = if ascii { byte } else { last_unit + utf16_len(&lower_text[last_byte..byte]) };
        (last_byte, last_unit) = (byte, start);
        hits.push((MatchRange { start, length }, byte));
    }
    hits
}

/// Slice plan of `buildSnippet`: `content[from..to]` between optional ellipses.
#[derive(Debug, Clone, Copy)]
pub(crate) struct SnippetPlan {
    pub(crate) from: usize,
    pub(crate) to: usize,
    pub(crate) front_ellipsis: bool,
    pub(crate) back_ellipsis: bool,
    pub(crate) match_start: usize,
}

/// `buildSnippet` boundaries over any code-unit slice (`u8` for ASCII text,
/// `u16` otherwise); `space` is the unit of `" "`.
pub(crate) fn plan_snippet<T: Copy + PartialEq>(content: &[T], space: T, match_start: usize, match_length: usize) -> SnippetPlan {
    plan_window(content, space, 0, content.len(), match_start, match_length)
}

/// Bounds of the context window, in code units of the full text.
pub(crate) fn context_bounds(total: usize, match_start: usize, match_length: usize) -> (usize, usize) {
    (match_start.saturating_sub(SNIPPET_CONTEXT_CHARS), total.min(match_start + match_length + SNIPPET_CONTEXT_CHARS))
}

/// Same as `plan_snippet` when `window` holds only units `base..` of a text of
/// `total` units; returned offsets are absolute.
pub(crate) fn plan_window<T: Copy + PartialEq>(window: &[T], space: T, base: usize, total: usize, match_start: usize, match_length: usize) -> SnippetPlan {
    let (context_start, context_end) = context_bounds(total, match_start, match_length);
    let mut from = context_start.min(context_end);
    let mut to = context_end;
    let mut start = match_start as isize - context_start as isize;
    let front = context_start > 0;
    if front {
        if let Some(first) = window[from - base..to - base].iter().position(|&u| u == space) {
            if first > 0 && (first as isize) < start {
                from += first + 1;
                start -= first as isize + 1;
            }
        }
        start += 4;
    }
    let back = context_end < total;
    if back {
        if let Some(last) = window[from - base..to - base].iter().rposition(|&u| u == space) {
            // Offsets inside the prefixed snippet include the 4-unit "... ".
            let in_snippet = last + if front { 4 } else { 0 };
            if in_snippet as isize > start + match_length as isize {
                to = from + last;
            }
        }
    }
    SnippetPlan { from, to, front_ellipsis: front, back_ellipsis: back, match_start: start.max(0) as usize }
}

/// UTF-16 length of `text` without allocating.
pub(crate) fn utf16_len(text: &str) -> usize {
    let bytes = text.as_bytes();
    bytes.iter().filter(|b| (**b & 0xC0) != 0x80).count() + bytes.iter().filter(|b| **b >= 0xF0).count()
}

/// UTF-16 units `[from, to)` of `text` (a surrogate pair split by the bounds
/// contributes only the half inside).
pub(crate) fn utf16_window(text: &str, from: usize, to: usize) -> Vec<u16> {
    let mut out = Vec::with_capacity(to.saturating_sub(from));
    // ASCII bytes are one unit each, so the leading ASCII run needs no decoding.
    let bytes = text.as_bytes();
    let ascii_len = bytes.chunks(32).position(|c| !c.is_ascii()).map_or(bytes.len(), |n| n * 32);
    let ascii_end = to.min(ascii_len);
    if from < ascii_end {
        out.extend(bytes[from..ascii_end].iter().map(|b| u16::from(*b)));
    }
    if to <= ascii_len {
        return out;
    }
    let mut offset = ascii_len;
    let mut buf = [0u16; 2];
    for c in text[ascii_len..].chars() {
        if offset >= to {
            break;
        }
        let n = c.len_utf16();
        if offset + n > from {
            for (i, u) in c.encode_utf16(&mut buf).iter().enumerate() {
                if (from..to).contains(&(offset + i)) {
                    out.push(*u);
                }
            }
        }
        offset += n;
    }
    out
}

/// `buildSnippet` over UTF-16 units.
pub fn build_snippet(content: &[u16], match_start: usize, match_length: usize) -> Snippet {
    let plan = plan_snippet(content, b' ' as u16, match_start, match_length);
    let mut units: Vec<u16> = Vec::with_capacity(plan.to - plan.from + 8);
    if plan.front_ellipsis {
        units.extend("... ".encode_utf16());
    }
    units.extend_from_slice(&content[plan.from..plan.to]);
    if plan.back_ellipsis {
        units.extend(" ...".encode_utf16());
    }
    Snippet { units, match_start: plan.match_start, match_length }
}

/// Node of the saved-memories input. Objects arrive as ordered `[key, value]`
/// pairs so JavaScript `Object.entries` order is preserved exactly.
#[derive(Debug, Clone, Deserialize)]
pub struct SavedMemoryEntry {
    #[serde(default)]
    pub id: Option<String>,
    pub item_value: Vec<(String, Value)>,
    #[serde(default)]
    pub updated_at: Option<f64>,
}

/// `entriesByApp`: ordered `(appId, [(groupName, entries)])`.
pub type SavedMemoriesInput = Vec<(String, Vec<(String, Vec<SavedMemoryEntry>)>)>;

/// One suggestion; serialization matches the TypeScript object (camelCase,
/// `settingsPath` omitted when absent).
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SavedEmbedSuggestion {
    pub embed_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub settings_path: Option<String>,
    pub title: String,
    pub subtitle: String,
    pub app_id: String,
    pub updated_at: f64,
}

struct Indexed {
    suggestion: SavedEmbedSuggestion,
    search_text: String,
    title_lower: String,
}

/// JavaScript `String.prototype.trim` whitespace (differs from Rust's set).
fn is_js_space(c: char) -> bool {
    matches!(c, '\u{0009}'..='\u{000D}' | '\u{0020}' | '\u{00A0}' | '\u{1680}' | '\u{2000}'..='\u{200A}'
        | '\u{2028}' | '\u{2029}' | '\u{202F}' | '\u{205F}' | '\u{3000}' | '\u{FEFF}')
}

fn js_trim(s: &str) -> &str {
    s.trim_matches(is_js_space)
}

fn slice_units(s: &str, max: usize) -> String {
    if s.len() <= max || s.encode_utf16().count() <= max {
        return s.to_string();
    }
    let units: Vec<u16> = s.encode_utf16().take(max).collect();
    String::from_utf16_lossy(&units)
}

fn string_value(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(s)) => js_trim(s).to_string(),
        _ => String::new(),
    }
}

fn field<'a>(entries: &'a [(String, Value)], key: &str) -> Option<&'a Value> {
    entries.iter().rev().find(|(k, _)| k == key).map(|(_, v)| v)
}

fn build_index(input: &SavedMemoriesInput) -> Vec<Indexed> {
    let mut slots: Vec<Indexed> = Vec::new();
    let mut by_id: HashMap<String, usize> = HashMap::new();
    for (app_id, groups) in input {
        for (group, entries) in groups {
            for entry in entries {
                let v = &entry.item_value;
                let embed_id = string_value(field(v, "embed_id"));
                if embed_id.is_empty() {
                    continue;
                }
                let mut title = string_value(field(v, "title"));
                if title.is_empty() {
                    title = string_value(field(v, "name"));
                }
                if title.is_empty() {
                    title = group.replace('_', " ");
                }
                let subtitle = slice_units(
                    &["location", "address", "where", "origin", "destination", "provider", "date_start"]
                        .iter()
                        .map(|k| string_value(field(v, k)))
                        .filter(|s| !s.is_empty())
                        .collect::<Vec<_>>()
                        .join(" \u{b7} "),
                    160,
                );
                // Object.entries yields each key once, at its first position,
                // with its last value; pair order is already deduplicated by the adapter.
                let metadata = slice_units(
                    &v.iter()
                        .filter(|(k, _)| !["embed_id", "url", "booking_url", "link"].contains(&k.as_str()))
                        .map(|(_, f)| slice_units(&string_value(Some(f)), 120))
                        .filter(|s| !s.is_empty())
                        .collect::<Vec<_>>()
                        .join(" "),
                    500,
                );
                let title_lower = title.to_lowercase();
                let search_text = format!("{} {}", title, metadata).to_lowercase();
                let settings_path = entry
                    .id
                    .as_ref()
                    .filter(|id| !id.is_empty())
                    .map(|id| format!("apps/{app_id}/settings_memories/{group}/entry/{id}"));
                let updated_at = entry.updated_at.unwrap_or(0.0);
                let candidate = Indexed {
                    suggestion: SavedEmbedSuggestion {
                        embed_id: embed_id.clone(),
                        settings_path,
                        title,
                        subtitle,
                        app_id: app_id.clone(),
                        updated_at,
                    },
                    search_text,
                    title_lower,
                };
                match by_id.get(&embed_id) {
                    Some(&slot) => {
                        if slots[slot].suggestion.updated_at < updated_at {
                            slots[slot] = candidate;
                        }
                    }
                    None => {
                        by_id.insert(embed_id, slots.len());
                        slots.push(candidate);
                    }
                }
            }
        }
    }
    slots.sort_by(|a, b| b.suggestion.updated_at.total_cmp(&a.suggestion.updated_at));
    slots
}

/// Built index over saved memories; keeping it resident turns each composer
/// keystroke into a query that crosses the boundary with the query text only.
pub struct SavedEmbedIndex {
    entries: Vec<Indexed>,
}

impl SavedEmbedIndex {
    pub fn build(input: &SavedMemoriesInput) -> Self {
        Self { entries: build_index(input) }
    }

    /// `searchSavedEmbedMemories` over the built index.
    pub fn search(&self, query: &str, limit: i64) -> Vec<SavedEmbedSuggestion> {
        let normalized = js_trim(query).to_lowercase();
        if normalized.is_empty() || limit <= 0 {
            return Vec::new();
        }
        // `entries` is already newest first (stable), so the TypeScript sort by
        // (title match, updatedAt) equals a stable partition: title matches first,
        // then the rest, each in index order. Stop as soon as `limit` are taken.
        let limit = limit as usize;
        let mut title_hits: Vec<&Indexed> = Vec::new();
        let mut other_hits: Vec<&Indexed> = Vec::new();
        for entry in &self.entries {
            if title_hits.len() >= limit {
                break;
            }
            if !entry.search_text.contains(&normalized) {
                continue;
            }
            if entry.title_lower.contains(&normalized) {
                title_hits.push(entry);
            } else if other_hits.len() < limit {
                other_hits.push(entry);
            }
        }
        title_hits.into_iter().chain(other_hits).take(limit).map(|e| e.suggestion.clone()).collect()
    }
}

/// `searchSavedEmbedMemories` (index built per call; use `SavedEmbedIndex` to keep it).
pub fn search_saved_embed_memories(input: &SavedMemoriesInput, query: &str, limit: i64) -> Vec<SavedEmbedSuggestion> {
    SavedEmbedIndex::build(input).search(query, limit)
}
