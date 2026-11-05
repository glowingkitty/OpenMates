//! JSON-string boundary for the web search and PII alias ports.
//!
//! Shared by the browser worker binding and native tests. Every function takes
//! and returns JSON text so the wasm boundary carries one string per call.
//! Errors are the stable code `protocol` (malformed input JSON).
use crate::pii_display_aliases::{create_pii_display_aliases, PiiMapping, SourceNode};
use crate::web_search::{context_bounds, SNIPPET_CONTEXT_CHARS, find_match_ranges, plan_snippet, plan_window, search_saved_embed_memories, utf16_len, utf16_window, SavedMemoriesInput};

fn protocol<E>(_: E) -> String {
    "protocol".to_string()
}

fn encode<T: serde::Serialize>(value: &T) -> Result<String, String> {
    serde_json::to_string(value).map_err(protocol)
}

/// JSON string literal that, like `JSON.stringify`, keeps lone UTF-16
/// surrogates (a snippet cut inside an emoji) as `\uXXXX` escapes.
fn json_string_from_units(units: &[u16]) -> String {
    let mut out = String::with_capacity(units.len() + 16);
    out.push('"');
    let mut i = 0;
    while i < units.len() {
        let u = units[i];
        if (0x20..0x7f).contains(&u) && u != 0x22 && u != 0x5c {
            out.push(u as u8 as char);
            i += 1;
            continue;
        }
        let pair_end = if i + 1 < units.len() { i + 2 } else { i + 1 };
        match char::decode_utf16(units[i..pair_end].iter().copied()).next() {
            Some(Ok(c)) => {
                push_json_char(&mut out, c);
                i += c.len_utf16();
            }
            Some(Err(e)) => {
                out.push_str(&format!("\\u{:04x}", e.unpaired_surrogate()));
                i += 1;
            }
            None => break,
        }
    }
    out.push('"');
    out
}

fn push_json_char(out: &mut String, c: char) {
    match c {
        '"' => out.push_str("\\\""),
        '\\' => out.push_str("\\\\"),
        '\n' => out.push_str("\\n"),
        '\r' => out.push_str("\\r"),
        '\t' => out.push_str("\\t"),
        '\u{8}' => out.push_str("\\b"),
        '\u{c}' => out.push_str("\\f"),
        c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
        c => out.push(c),
    }
}

/// JSON string literal for ASCII text (fast path of `json_string_from_units`).
fn json_string_ascii(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 2);
    out.push('"');
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn itoa_usize(mut n: usize) -> String {
    if n == 0 {
        return "0".to_string();
    }
    let mut digits = [0u8; 20];
    let mut i = digits.len();
    while n > 0 {
        i -= 1;
        digits[i] = b'0' + (n % 10) as u8;
        n /= 10;
    }
    digits[i..].iter().map(|d| *d as char).collect()
}

/// `[{"start":n,"length":n},...]`
pub fn find_match_ranges_json(text: &str, query: &str) -> Result<String, String> {
    encode(&find_match_ranges(text, query))
}

/// `{"snippet":s,"snippetMatchStart":n,"snippetMatchLength":n}`; offsets in UTF-16 units.
pub fn build_snippet_json(content: &str, match_start: usize, match_length: usize) -> String {
    let (snippet_json, start) = if content.is_ascii() {
        let plan = plan_snippet(content.as_bytes(), b' ', match_start, match_length);
        let mut text = String::with_capacity(plan.to - plan.from + 8);
        if plan.front_ellipsis {
            text.push_str("... ");
        }
        text.push_str(&content[plan.from..plan.to]);
        if plan.back_ellipsis {
            text.push_str(" ...");
        }
        (json_string_ascii(&text), plan.match_start)
    } else {
        // One unit past the context end tells whether text follows it, so the
        // full UTF-16 length is only needed when the window is empty.
        let target = match_start + match_length + SNIPPET_CONTEXT_CHARS;
        let window_start = match_start.saturating_sub(SNIPPET_CONTEXT_CHARS);
        let window = utf16_window(content, window_start, target + 1);
        let total = if window.is_empty() { utf16_len(content) } else { window_start + window.len() };
        let (context_start, window_end) = context_bounds(total, match_start, match_length);
        let window_start = context_start.min(window_end);
        let window = if window_start == context_start { window } else { Vec::new() };
        let plan = plan_window(&window, b' ' as u16, window_start, total, match_start, match_length);
        let mut units: Vec<u16> = Vec::with_capacity(plan.to - plan.from + 8);
        if plan.front_ellipsis {
            units.extend("... ".encode_utf16());
        }
        units.extend_from_slice(&window[plan.from - window_start..plan.to - window_start]);
        if plan.back_ellipsis {
            units.extend(" ...".encode_utf16());
        }
        (json_string_from_units(&units), plan.match_start)
    };
    let mut out = String::with_capacity(snippet_json.len() + 64);
    out.push_str("{\"snippet\":");
    out.push_str(&snippet_json);
    out.push_str(",\"snippetMatchStart\":");
    out.push_str(itoa_usize(start).as_str());
    out.push_str(",\"snippetMatchLength\":");
    out.push_str(itoa_usize(match_length).as_str());
    out.push('}');
    out
}

/// `entries_json`: `[[appId,[[group,[{id?,item_value:[[k,v]...],updated_at?}]]]]]`.
pub fn search_saved_embed_memories_json(entries_json: &str, query: &str, limit: i64) -> Result<String, String> {
    let input: SavedMemoriesInput = serde_json::from_str(entries_json).map_err(protocol)?;
    let results = search_saved_embed_memories(&input, query, limit);
    let mut values = serde_json::to_value(&results).map_err(protocol)?;
    // JavaScript numbers print integral values without a fraction.
    if let Some(items) = values.as_array_mut() {
        for (item, r) in items.iter_mut().zip(&results) {
            if r.updated_at.fract() == 0.0 && r.updated_at.abs() < 9e15 {
                item["updatedAt"] = serde_json::Value::from(r.updated_at as i64);
            }
        }
    }
    encode(&values)
}

/// Returns `[[placeholder,alias],...]` in insertion order.
pub fn create_pii_display_aliases_json(source_json: &str, mappings_json: &str, configured_json: &str) -> Result<String, String> {
    let source: Option<SourceNode> = serde_json::from_str(source_json).map_err(protocol)?;
    let mappings: Vec<PiiMapping> = serde_json::from_str(mappings_json).map_err(protocol)?;
    let configured: Vec<String> = serde_json::from_str(configured_json).map_err(protocol)?;
    encode(&create_pii_display_aliases(source.as_ref(), &mappings, &configured))
}
