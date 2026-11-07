//! Known-original placeholder rewrite of an outbound prompt: previously redacted
//! originals typed again are replaced by their stored placeholders, longest
//! original first, never inside embed JSON blocks or existing placeholders.
//! Port of `rewriteKnownPIIPlaceholders` in `placeholderRewriteService.ts`.
//! spec: specifications/features/pii-protection#pii.outbound.known-original-rewrite
use super::protocol;
use super::utf16::{index_of, string, units};
use regex::Regex;
use serde_json::{Value, json};
use std::collections::HashSet;
use std::sync::OnceLock;

type Range = (usize, usize);

struct Mapping {
    placeholder: Vec<u16>,
    original: Vec<u16>,
}

/// Linear merge of two start-sorted range batches (`mergeSortedRanges`).
fn merge_sorted(previous: &[Range], added: &[Range]) -> Vec<Range> {
    let (mut result, mut p, mut a): (Vec<Range>, usize, usize) = (Vec::new(), 0, 0);
    while p < previous.len() || a < added.len() {
        let range = if a >= added.len() || (p < previous.len() && previous[p].0 <= added[a].0) {
            p += 1;
            previous[p - 1]
        } else {
            a += 1;
            added[a - 1]
        };
        match result.last_mut() {
            Some(last) if range.0 <= last.1 => last.1 = last.1.max(range.1),
            _ => result.push(range),
        }
    }
    result
}

fn json_block() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?s)```json\n(.*?)\n```").expect("fixed pattern compiles"))
}

fn generated_token() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\[[A-Z][A-Z0-9_]*_[0-9]+(?:_[A-Za-z0-9_-]+)?\]").expect("fixed pattern compiles"))
}

fn protected_ranges(markdown: &str, units16: &[u16], all: &[Mapping]) -> Vec<Range> {
    let index = super::utf16::Utf16Index::new(markdown);
    let mut ranges = Vec::new();
    for m in json_block().captures_iter(markdown) {
        let whole = m.get(0).expect("group 0 always exists");
        let body = super::utf16::js_trim(&m[1]);
        // `in` on a non-object throws in JS and the block keeps ordinary rewrite behaviour.
        if let Ok(Value::Object(object)) = serde_json::from_str::<Value>(body)
            && (object.contains_key("embed_id") || object.contains_key("embed_ids"))
        {
            ranges.push((index.at(whole.start()), index.at(whole.end())));
        }
    }
    for m in generated_token().find_iter(markdown) {
        ranges.push((index.at(m.start()), index.at(m.end())));
    }
    let mut seen: HashSet<&[u16]> = HashSet::new();
    for mapping in all {
        let p = &mapping.placeholder;
        let bracketed = p.len() >= 2 && p.first() == Some(&0x5b) && p.last() == Some(&0x5d);
        if mapping.original.is_empty() || p.is_empty() || !bracketed || mapping.original == *p || !seen.insert(p) {
            continue;
        }
        let mut from = 0;
        while let Some(start) = index_of(units16, p, from) {
            ranges.push((start, start + p.len()));
            from = start + 1;
        }
    }
    ranges.sort_by_key(|r| r.0);
    ranges
}

/// `{markdown, mappings:[{placeholder, original}], excludedOriginals?, excludedPlaceholders?}`
/// -> `{markdown, applied: [mapping index]}`.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn rewrite_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let markdown = value.get("markdown").and_then(Value::as_str).ok_or("protocol")?;
    let list = value.get("mappings").and_then(Value::as_array).ok_or("protocol")?;
    let all: Vec<Mapping> = list
        .iter()
        .map(|m| {
            let get = |k: &str| m.get(k).and_then(Value::as_str).map(units).ok_or_else(|| protocol(()));
            Ok::<Mapping, String>(Mapping { placeholder: get("placeholder")?, original: get("original")? })
        })
        .collect::<Result<_, String>>()?;
    let strings = |key: &str| -> HashSet<Vec<u16>> {
        value.get(key).and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_str).map(units).collect()).unwrap_or_default()
    };
    if markdown.is_empty() || all.is_empty() {
        return Ok(json!({"markdown": markdown, "applied": []}).to_string());
    }
    let (excluded_originals, excluded_placeholders) = (strings("excludedOriginals"), strings("excludedPlaceholders"));
    let text = units(markdown);

    let mut seen: HashSet<&[u16]> = HashSet::new();
    let mut order: Vec<usize> = (0..all.len())
        .filter(|&i| {
            let m = &all[i];
            !m.original.is_empty()
                && !m.placeholder.is_empty()
                && m.original != m.placeholder
                && !excluded_originals.contains(&m.original)
                && !excluded_placeholders.contains(&m.placeholder)
                && seen.insert(&m.original)
        })
        .collect();
    order.sort_by_key(|&i| std::cmp::Reverse(all[i].original.len()));

    let mut reserved = merge_sorted(&[], &protected_ranges(markdown, &text, &all));
    let mut spans: Vec<(usize, usize, usize)> = Vec::new();
    let mut applied: Vec<usize> = Vec::new();
    let mut applied_keys: HashSet<(&[u16], &[u16])> = HashSet::new();
    for &mi in &order {
        let mapping = &all[mi];
        let (mut search_from, mut reserved_index, mut new_ranges, mut did) = (0, 0, Vec::new(), false);
        while let Some(start) = index_of(&text, &mapping.original, search_from) {
            let end = start + mapping.original.len();
            while reserved_index < reserved.len() && reserved[reserved_index].1 <= start {
                reserved_index += 1;
            }
            if reserved_index < reserved.len() && reserved[reserved_index].0 < end {
                search_from = start + 1;
                continue;
            }
            spans.push((start, end, mi));
            new_ranges.push((start, end));
            did = true;
            search_from = end;
        }
        if did {
            reserved = merge_sorted(&reserved, &new_ranges);
            if applied_keys.insert((mapping.placeholder.as_slice(), mapping.original.as_slice())) {
                applied.push(mi);
            }
        }
    }
    spans.sort_by_key(|s| s.0);
    let (mut out, mut cursor) = (Vec::with_capacity(text.len()), 0);
    for (start, end, mi) in spans {
        out.extend_from_slice(&text[cursor..start]);
        out.extend_from_slice(&all[mi].placeholder);
        cursor = end;
    }
    out.extend_from_slice(&text[cursor..]);
    Ok(json!({"markdown": string(&out)?, "applied": applied}).to_string())
}
