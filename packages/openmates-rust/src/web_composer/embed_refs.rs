//! Embed reference spans that personal-data detection must never alter: the
//! `(embed:<ref>)` target of a markdown embed link and the `embed_id`/`embed_ids`
//! members of a fenced ```json embed reference block (other members, e.g. a user
//! note, stay scanned). Refs are machine-generated ids; a redacted
//! ref can never resolve to its embed again. Port of `embedReferenceRanges` in
//! `frontend/packages/secret-scanner/src/embedReferenceRanges.ts`.
//! spec: specifications/features/pii-protection#pii.composer.embed-references-not-scanned
use super::utf16::{Utf16Index, js_trim};
use regex::Regex;
use serde_json::Value;
use std::sync::OnceLock;

fn embed_link_target() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    // Same class as the TS `[^\s)]`; ASCII-only `\s` would differ from JS on
    // Unicode spaces, so use the shared JS whitespace class.
    RE.get_or_init(|| {
        Regex::new(&format!(r"\(embed:[^{}\)]+\)", super::utf16::WS_CLASS))
            .expect("fixed embed link pattern compiles")
    })
}

fn embed_id_member() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r#""embed_id"\s*:\s*"(?:\\.|[^"\\])*"|"embed_ids"\s*:\s*\[(?:\s*"(?:\\.|[^"\\])*"\s*,?)*\s*\]"#)
            .expect("fixed embed id member pattern compiles")
    })
}

fn json_block() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"(?s)```json\n(.*?)\n```").expect("fixed json block pattern compiles")
    })
}

/// UTF-8 byte `(start, end)` ranges of every embed reference in `text`, start-sorted.
///
/// Matches the TS helper exactly: only a JSON object (never an array or a
/// scalar) with an `embed_id` or `embed_ids` key is a reference block, and only
/// those members of it are protected. Used by the
/// byte-offset message privacy boundary (`crate::privacy`) of the native CLI/SDK.
pub(crate) fn embed_reference_byte_ranges(text: &str) -> Vec<(usize, usize)> {
    if !text.contains("embed") {
        return Vec::new();
    }
    let mut ranges: Vec<(usize, usize)> = embed_link_target()
        .find_iter(text)
        .map(|m| (m.start(), m.end()))
        .collect();
    for captures in json_block().captures_iter(text) {
        let body = captures.get(1).expect("the block pattern has one group");
        if let Ok(Value::Object(object)) = serde_json::from_str::<Value>(js_trim(body.as_str()))
            && (object.contains_key("embed_id") || object.contains_key("embed_ids"))
        {
            ranges.extend(
                embed_id_member()
                    .find_iter(body.as_str())
                    .map(|m| (body.start() + m.start(), body.start() + m.end())),
            );
        }
    }
    ranges.sort_by_key(|r| r.0);
    ranges
}

/// The same ranges as UTF-16 offsets, as used by the web composer ops.
pub(crate) fn embed_reference_ranges(text: &str, index: &Utf16Index) -> Vec<(usize, usize)> {
    embed_reference_byte_ranges(text)
        .into_iter()
        .map(|(s, e)| (index.at(s), index.at(e)))
        .collect()
}

/// True when the UTF-16 span `[s, e)` touches any of `ranges`.
pub(crate) fn overlaps_any(ranges: &[(usize, usize)], s: usize, e: usize) -> bool {
    ranges.iter().any(|&(rs, re)| s < re && e > rs)
}
