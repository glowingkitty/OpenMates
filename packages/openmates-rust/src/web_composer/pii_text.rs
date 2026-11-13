//! Text transforms over PII matches and mappings: redaction by match offsets,
//! restoring placeholders (including bare tokens), re-hiding originals, highlight
//! positions and the "2 emails, 1 phone number" summary. Ports of
//! `replacePIIWithPlaceholders`, `restorePIIInText`, `replacePIIOriginalsWithPlaceholders`,
//! `findRestoredPIIPositions` and `createPIISummary` in `piiDetectionService.ts`.
//! spec: specifications/features/pii-protection#pii.message.owner-local-reveal
use super::pii_table::label;
use super::protocol;
use super::utf16::{index_of, split_join, string, substring, units};
use serde_json::{Value, json};

struct Mapping {
    placeholder: Vec<u16>,
    original: Vec<u16>,
    kind: Option<String>,
}

fn parse_mappings(value: Option<&Value>) -> Result<Vec<Mapping>, String> {
    let list = value.and_then(Value::as_array).ok_or("protocol")?;
    list.iter()
        .map(|m| {
            let get = |k: &str| m.get(k).and_then(Value::as_str).map(units).ok_or_else(|| protocol(()));
            Ok::<Mapping, String>(Mapping {
                placeholder: get("placeholder")?,
                original: get("original")?,
                kind: m.get("type").and_then(Value::as_str).map(str::to_string),
            })
        })
        .collect()
}

fn text_of(value: &Value) -> Result<Vec<u16>, String> {
    value.get("text").and_then(Value::as_str).map(units).ok_or_else(|| protocol(()))
}

/// `replacePIIWithPlaceholders`: `{text, matches:[{startIndex,endIndex,placeholder}]}` -> JSON string.
/// Matches apply from the highest start down to the lowest, each on the already rewritten text.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn replace_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let text = text_of(&value)?;
    let list = value.get("matches").and_then(Value::as_array).ok_or("protocol")?;
    let mut matches: Vec<(i64, i64, Vec<u16>)> = list
        .iter()
        .map(|m| {
            let num = |k: &str| m.get(k).and_then(Value::as_i64).ok_or_else(|| protocol(()));
            let placeholder = m.get("placeholder").and_then(Value::as_str).map(units).ok_or_else(|| protocol(()))?;
            Ok((num("startIndex")?, num("endIndex")?, placeholder))
        })
        .collect::<Result<_, String>>()?;
    if matches.is_empty() {
        return Ok(Value::String(string(&text)?).to_string());
    }
    matches.sort_by_key(|m| std::cmp::Reverse(m.0));
    let mut result = text;
    for (start, end, placeholder) in matches {
        let mut next = substring(&result, 0, start).to_vec();
        next.extend_from_slice(&placeholder);
        next.extend_from_slice(substring(&result, end, i64::MAX));
        result = next;
    }
    Ok(Value::String(string(&result)?).to_string())
}

fn is_bare_prefix_excluded(u: u16) -> bool {
    matches!(u, 0x30..=0x39 | 0x41..=0x5a | 0x61..=0x7a | 0x5f | 0x5b)
}

fn is_bare_follow_excluded(u: u16) -> bool {
    matches!(u, 0x30..=0x39 | 0x41..=0x5a | 0x61..=0x7a | 0x5f | 0x5d)
}

/// `/(^|[^A-Za-z0-9_\[])BARE(?![A-Za-z0-9_\]])/g` replaced by `prefix + original`.
fn replace_bare(text: &[u16], bare: &[u16], original: &[u16]) -> Vec<u16> {
    let fits = |at: usize| text[at..].starts_with(bare) && text.get(at + bare.len()).is_none_or(|u| !is_bare_follow_excluded(*u));
    let (mut out, mut cursor, mut i) = (Vec::with_capacity(text.len()), 0, 0);
    while i <= text.len() {
        if i == 0 && fits(0) {
            out.extend_from_slice(original);
            cursor = bare.len();
            i = cursor;
            continue;
        }
        if i < text.len() && !is_bare_prefix_excluded(text[i]) && i + 1 <= text.len() && fits(i + 1) {
            out.extend_from_slice(&text[cursor..=i]);
            out.extend_from_slice(original);
            cursor = i + 1 + bare.len();
            i = cursor;
            continue;
        }
        i += 1;
    }
    out.extend_from_slice(&text[cursor.min(text.len())..]);
    out
}

/// `restorePIIInText`: `{text, mappings}` -> JSON string.
///
/// # Errors
/// `protocol` for a malformed payload or a result that would need a lone surrogate.
pub fn restore_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let mut result = text_of(&value)?;
    for mapping in parse_mappings(value.get("mappings"))? {
        result = split_join(&result, &mapping.placeholder, &mapping.original);
        let p = &mapping.placeholder;
        if p.first() == Some(&0x5b) && p.last() == Some(&0x5d) && p.len() >= 2 {
            let bare = &p[1..p.len() - 1];
            if !bare.is_empty() {
                result = replace_bare(&result, bare, &mapping.original);
            }
        }
    }
    Ok(Value::String(string(&result)?).to_string())
}

/// `replacePIIOriginalsWithPlaceholders`: longest originals first.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn replace_originals_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let mut result = text_of(&value)?;
    let mut mappings = parse_mappings(value.get("mappings"))?;
    mappings.sort_by_key(|m| std::cmp::Reverse(m.original.len()));
    for mapping in mappings.iter().filter(|m| !m.original.is_empty()) {
        result = split_join(&result, &mapping.original, &mapping.placeholder);
    }
    Ok(Value::String(string(&result)?).to_string())
}

/// `findRestoredPIIPositions`: `[{startIndex, endIndex, type, label}]` sorted by start.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn find_restored_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let text = text_of(&value)?;
    let mappings = parse_mappings(value.get("mappings"))?;
    let mut positions: Vec<(usize, usize, String)> = Vec::new();
    if !text.is_empty() {
        for mapping in mappings.iter().filter(|m| !m.original.is_empty()) {
            let kind = mapping.kind.clone().unwrap_or_else(|| "PERSONAL_DATA".to_string());
            let mut from = 0;
            while from < text.len() {
                let Some(at) = index_of(&text, &mapping.original, from) else { break };
                positions.push((at, at + mapping.original.len(), kind.clone()));
                from = at + mapping.original.len();
            }
        }
    }
    positions.sort_by_key(|p| p.0);
    Ok(Value::Array(
        positions.into_iter().map(|(s, e, k)| json!({"startIndex": s, "endIndex": e, "label": label(&k), "type": k})).collect(),
    )
    .to_string())
}

/// `createPIISummary`: `{types:[type per match]}` -> "2 emails, 1 phone numbers" style JSON string.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn summary_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let types = value.get("types").and_then(Value::as_array).ok_or("protocol")?;
    let mut counts: Vec<(String, usize)> = Vec::new();
    for kind in types {
        let l = label(kind.as_str().ok_or("protocol")?);
        match counts.iter_mut().find(|(k, _)| *k == l) {
            Some((_, n)) => *n += 1,
            None => counts.push((l, 1)),
        }
    }
    let parts: Vec<String> =
        counts.iter().map(|(l, n)| format!("{n} {}{}", l.to_lowercase(), if *n > 1 { "s" } else { "" })).collect();
    Ok(Value::String(parts.join(", ")).to_string())
}
