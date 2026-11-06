//! JSON-string boundary for the web search and PII alias ports.
//!
//! Shared by the browser worker binding and native tests. Every function takes
//! and returns JSON text so the wasm boundary carries one string per call.
//! Errors are the stable code `protocol` (malformed input JSON).
use crate::pii_display_aliases::{create_pii_display_aliases, PiiMapping, SourceNode};
use crate::web_search::{context_bounds, SNIPPET_CONTEXT_CHARS, find_match_ranges, plan_snippet, plan_window, search_saved_embed_memories, SavedEmbedIndex, utf16_len, utf16_window, SavedMemoriesInput};

fn protocol<E>(_: E) -> String {
    "protocol".to_string()
}

fn encode<T: serde::Serialize>(value: &T) -> Result<String, String> {
    serde_json::to_string(value).map_err(protocol)
}

/// JSON string literal that, like `JSON.stringify`, keeps lone UTF-16
/// surrogates (a snippet cut inside an emoji) as `\uXXXX` escapes.
pub(crate) fn json_string_from_units(units: &[u16]) -> String {
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

/// `[{"start":n,"length":n},...]`
pub fn find_match_ranges_json(text: &str, query: &str) -> Result<String, String> {
    encode(&find_match_ranges(text, query))
}

/// `{"snippet":s,"snippetMatchStart":n,"snippetMatchLength":n}`; offsets in UTF-16 units.
pub fn build_snippet_json(content: &str, match_start: usize, match_length: usize) -> String {
    let mut out = String::with_capacity(2 * SNIPPET_CONTEXT_CHARS + match_length + 96);
    write_snippet_json(&mut out, content, match_start, match_length, None);
    out
}

/// Appends the snippet object for `content` to `out` (shared by the single and batch entry points).
///
/// `match_byte` is the UTF-8 offset of `match_start` in `content` when the caller knows it.
pub(crate) fn write_snippet_json(out: &mut String, content: &str, match_start: usize, match_length: usize, match_byte: Option<usize>) {
    out.push_str("{\"snippet\":\"");
    let start = if content.is_ascii() {
        let plan = plan_snippet(content.as_bytes(), b' ', match_start, match_length);
        write_snippet_body(out, plan.front_ellipsis, &content[plan.from..plan.to], plan.back_ellipsis);
        plan.match_start
    } else if let Some(start) = write_utf8_window(out, content, match_start, match_length, match_byte) {
        start
    } else {
        write_unit_window(out, content, match_start, match_length)
    };
    out.push_str("\",\"snippetMatchStart\":");
    push_usize(out, start);
    out.push_str(",\"snippetMatchLength\":");
    push_usize(out, match_length);
    out.push('}');
}

fn write_snippet_body(out: &mut String, front: bool, body: &str, back: bool) {
    if front {
        out.push_str("... ");
    }
    push_json_escaped(out, body);
    if back {
        out.push_str(" ...");
    }
}

/// Escapes `text` for the inside of a JSON string literal, copying clean runs whole.
pub(crate) fn push_json_escaped(out: &mut String, text: &str) {
    let bytes = text.as_bytes();
    let mut run = 0;
    for (i, &b) in bytes.iter().enumerate() {
        if b >= 0x20 && b != b'"' && b != b'\\' {
            continue;
        }
        out.push_str(&text[run..i]);
        run = i + 1;
        match b {
            b'"' => out.push_str("\\\""),
            b'\\' => out.push_str("\\\\"),
            b'\n' => out.push_str("\\n"),
            b'\r' => out.push_str("\\r"),
            b'\t' => out.push_str("\\t"),
            0x08 => out.push_str("\\b"),
            0x0c => out.push_str("\\f"),
            _ => out.push_str(&format!("\\u{:04x}", b)),
        }
    }
    out.push_str(&text[run..]);
}

pub(crate) fn push_usize(out: &mut String, mut n: usize) {
    let mut digits = [0u8; 20];
    let mut i = digits.len();
    loop {
        i -= 1;
        digits[i] = b'0' + (n % 10) as u8;
        n /= 10;
        if n == 0 {
            break;
        }
    }
    out.extend(digits[i..].iter().map(|d| *d as char));
}

/// Byte offset reached after moving `units` UTF-16 units forward from `byte`;
/// the flag tells whether all units were available. `None` when the move ends inside a surrogate pair.
fn step_forward(content: &str, byte: usize, units: usize) -> Option<(usize, bool)> {
    let mut left = units;
    let mut at = byte;
    for c in content[byte..].chars() {
        if left == 0 {
            return Some((at, true));
        }
        let n = c.len_utf16();
        if n > left {
            return None;
        }
        left -= n;
        at += c.len_utf8();
    }
    Some((at, left == 0))
}

/// Byte offset `units` UTF-16 units before `byte`, or the start when the text is shorter.
fn step_back(content: &str, byte: usize, units: usize) -> Option<usize> {
    let mut left = units;
    let mut at = byte;
    for c in content[..byte].chars().rev() {
        if left == 0 {
            break;
        }
        let n = c.len_utf16();
        if n > left {
            return None;
        }
        left -= n;
        at -= c.len_utf8();
    }
    (left == 0).then_some(at)
}

/// Snippet for non-ASCII content computed on UTF-8 bytes of the context window.
/// `None` when a window edge splits a surrogate pair or the text ends before
/// the match starts; the code-unit path then handles those cases.
fn write_utf8_window(out: &mut String, content: &str, match_start: usize, match_length: usize, match_byte: Option<usize>) -> Option<usize> {
    let bytes = content.as_bytes();
    let ws = match_start.saturating_sub(SNIPPET_CONTEXT_CHARS);
    let anchor = match match_byte {
        Some(byte) => byte,
        None => {
            let ascii_len = bytes.chunks(32).position(|c| !c.is_ascii()).map_or(bytes.len(), |n| n * 32);
            let ascii_len = ascii_len + bytes[ascii_len..].iter().take_while(|b| b.is_ascii()).count();
            if match_start <= ascii_len {
                match_start
            } else {
                match step_forward(content, ascii_len, match_start - ascii_len)? {
                    (byte, true) => byte,
                    _ => return None,
                }
            }
        }
    };
    let b_ws = step_back(content, anchor, match_start - ws)?;
    let (b_end, reached) = step_forward(content, anchor, match_length + SNIPPET_CONTEXT_CHARS)?;
    let more = reached && b_end < bytes.len();
    let window = &content[b_ws..b_end];
    let front = ws > 0;
    let mut start = (match_start - ws) as isize;
    let mut from = 0;
    if front {
        if let Some(p) = window.find(' ') {
            let first = utf16_len(&window[..p]);
            if first > 0 && (first as isize) < start {
                from = p + 1;
                start -= first as isize + 1;
            }
        }
        start += 4;
    }
    let mut to = window.len();
    if more {
        if let Some(q) = window[from..to].rfind(' ') {
            let last = utf16_len(&window[from..from + q]);
            if (last + if front { 4 } else { 0 }) as isize > start + match_length as isize {
                to = from + q;
            }
        }
    }
    write_snippet_body(out, front, &window[from..to], more);
    Some(start.max(0) as usize)
}

/// Code-unit path for windows that cut a surrogate pair (lone surrogates keep `\uXXXX` escapes).
fn write_unit_window(out: &mut String, content: &str, match_start: usize, match_length: usize) -> usize {
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
    let literal = json_string_from_units(&units);
    out.push_str(&literal[1..literal.len() - 1]);
    plan.match_start
}

/// JSON text of suggestions; integral timestamps print without a fraction like JavaScript numbers.
fn suggestions_json(results: &[crate::web_search::SavedEmbedSuggestion]) -> Result<String, String> {
    let mut values = serde_json::to_value(results).map_err(protocol)?;
    if let Some(items) = values.as_array_mut() {
        for (item, r) in items.iter_mut().zip(results) {
            if r.updated_at.fract() == 0.0 && r.updated_at.abs() < 9e15 {
                item["updatedAt"] = serde_json::Value::from(r.updated_at as i64);
            }
        }
    }
    encode(&values)
}

/// `entries_json`: `[[appId,[[group,[{id?,item_value:[[k,v]...],updated_at?}]]]]]`.
pub fn search_saved_embed_memories_json(entries_json: &str, query: &str, limit: i64) -> Result<String, String> {
    let input: SavedMemoriesInput = serde_json::from_str(entries_json).map_err(protocol)?;
    suggestions_json(&search_saved_embed_memories(&input, query, limit))
}

/// Builds a resident index from the same `entries_json` shape.
pub fn saved_embed_index_from_json(entries_json: &str) -> Result<SavedEmbedIndex, String> {
    let input: SavedMemoriesInput = serde_json::from_str(entries_json).map_err(protocol)?;
    Ok(SavedEmbedIndex::build(&input))
}

/// Query over a resident index; same output as `search_saved_embed_memories_json`.
pub fn saved_embed_index_search_json(index: &SavedEmbedIndex, query: &str, limit: i64) -> Result<String, String> {
    suggestions_json(&index.search(query, limit))
}

/// Returns `[[placeholder,alias],...]` in insertion order.
pub fn create_pii_display_aliases_json(source_json: &str, mappings_json: &str, configured_json: &str) -> Result<String, String> {
    let source: Option<SourceNode> = serde_json::from_str(source_json).map_err(protocol)?;
    let mappings: Vec<PiiMapping> = serde_json::from_str(mappings_json).map_err(protocol)?;
    let configured: Vec<String> = serde_json::from_str(configured_json).map_err(protocol)?;
    encode(&create_pii_display_aliases(source.as_ref(), &mappings, &configured))
}
