//! Deterministic PII detector shared by message preparation (`prepare`) and the
//! Project-file privacy layer (`file_privacy`). Lifted verbatim out of
//! `prepare_internal` so there is exactly one detector; it mirrors `detectPII`
//! in `piiDetectionService.ts`. Spec: specifications/features/pii-protection.
use super::{PiiExclusions, Range, RangeIndex, category, patterns, ranges_for, regex, valid};
use crate::error::{Error, Result};
use regex::Regex;
use serde_json::Value;
use std::collections::HashSet;

/// Reads the privacy settings memory: `(masterEnabled, disabled categories)`.
pub(super) fn detection_settings(memories: &[Value]) -> (bool, HashSet<String>) {
    let settings = memories
        .iter()
        .find(|m| m["app_id"] == "privacy" && m["item_type"] == "pii_detection_settings")
        .and_then(|m| m.get("data"));
    let enabled = settings
        .and_then(|s| s.get("masterEnabled"))
        .and_then(Value::as_bool)
        != Some(false);
    let disabled = settings
        .and_then(|s| s.get("categories"))
        .and_then(Value::as_object)
        .map(|m| {
            m.iter()
                .filter(|(_, v)| v.as_bool() == Some(false))
                .map(|(k, _)| k.clone())
                .collect()
        })
        .unwrap_or_default();
    (enabled, disabled)
}

/// Appends pattern and personal-entry matches to `ranges`, skipping anything
/// overlapping `token_index` (placeholders, embed refs) or `accepted` ranges.
pub(super) fn detect_into(
    text: &str,
    memories: &[Value],
    disabled: &HashSet<&str>,
    exclusions: &PiiExclusions,
    token_index: &RangeIndex,
    accepted: &mut RangeIndex,
    ranges: &mut Vec<Range>,
) -> Result<()> {
    let urls = ranges_for(&regex(r"https?://[^\s]+"), text);
    let url_index = RangeIndex::from_ranges(&urls);
    let identifiers = ranges_for(
        &regex(
            r"(?i)(?-u:\b)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?-u:\b)|(?-u:\b)[0-9a-f]{40,64}(?-u:\b)|\[[A-Z][A-Z0-9_]*\]",
        ),
        text,
    );
    let identifier_index = RangeIndex::from_ranges(&identifiers);
    if text.encode_utf16().count() >= 6 {
        for pattern in patterns() {
            if disabled.contains(category(pattern.kind)) {
                continue;
            }
            for matched in pattern.regex.find_iter(text) {
                let (start, end) = (matched.start(), matched.end());
                if url_index.contains(start, end)
                    || token_index.overlaps(start, end)
                    || accepted.overlaps(start, end)
                    || pattern.kind == "PHONE" && identifier_index.overlaps(start, end)
                    || pattern.kind == "PHONE" && in_version_component(text, start)
                    || exclusions.excludes_original(matched.as_str())
                    || !valid(pattern.kind, matched.as_str(), text[end..].chars().next())
                {
                    continue;
                }
                accepted.insert(start, end);
                ranges.push(Range {
                    start,
                    end,
                    kind: pattern.kind.into(),
                });
            }
        }
    }
    let mut personal = Vec::new();
    let mut personal_index = RangeIndex::default();
    for memory in memories
        .iter()
        .filter(|m| m["app_id"] == "privacy" && m["item_type"] == "personal_data_entry")
    {
        let data = &memory["data"];
        if data["enabled"] != true
            || data["textToHide"].as_str().is_none_or(str::is_empty)
            || data["replaceWith"].as_str().is_none_or(str::is_empty)
        {
            continue;
        }
        let mut values = vec![data["textToHide"].as_str().unwrap()];
        if let Some(lines) = data["addressLines"].as_object() {
            values.extend(lines.values().filter_map(Value::as_str));
        }
        for value in values.into_iter().filter(|v| !v.trim().is_empty()) {
            let search = Regex::new(&format!("(?i){}", regex::escape(value)))
                .map_err(|_| Error::Invalid("Personal privacy data could not be processed."))?;
            for m in search.find_iter(text) {
                if exclusions.excludes_original(m.as_str()) {
                    continue;
                }
                if !personal_index.overlaps(m.start(), m.end()) {
                    personal_index.insert(m.start(), m.end());
                    personal.push(Range {
                        start: m.start(),
                        end: m.end(),
                        kind: "EMAIL".into(),
                    });
                }
            }
        }
    }
    // Preserve the same uncovered personal-data suffixes, querying only
    // intersecting shield intervals instead of scanning every prior range.
    if !personal.is_empty() {
        let mut protected = token_index.clone();
        for range in ranges.iter() {
            protected.insert(range.start, range.end);
        }
        for range in personal {
            let fragments = protected.uncovered(range);
            for fragment in &fragments {
                protected.insert(fragment.start, fragment.end);
            }
            ranges.extend(fragments);
        }
    }
    Ok(())
}

/// A phone match inside one component of a dotted version number (the digit
/// run it starts in follows a `.` that follows a digit, as in `1.0.30001690`
/// of a lockfile) is part of that version, never a phone number. The regex has
/// no left boundary, so without this the tail of a version would be redacted
/// and the file would no longer parse. Long digit runs (IBANs, account
/// numbers) are not affected: they are still split into redacted matches.
/// Mirrors the web detector.
fn in_version_component(text: &str, start: usize) -> bool {
    let mut before = text[..start].chars().rev().skip_while(char::is_ascii_digit);
    before.next() == Some('.') && before.next().is_some_and(|c| c.is_ascii_digit())
}

/// Detected `(start, end, kind)` byte ranges of `text` that overlap neither
/// `shields` nor `existing`; honours masterEnabled, disabled categories and
/// personal-data entries of `memories`. Used by `FilePrivacy::redact_text`.
pub(crate) fn detect_ranges(
    text: &str,
    memories: &[Value],
    exclusions: &PiiExclusions,
    shields: &[(usize, usize)],
    existing: &[(usize, usize)],
) -> Result<Vec<(usize, usize, String)>> {
    let (enabled, disabled) = detection_settings(memories);
    if !enabled {
        return Ok(Vec::new());
    }
    let disabled: HashSet<&str> = disabled.iter().map(String::as_str).collect();
    let mut token_index = RangeIndex::default();
    for (s, e) in shields {
        token_index.insert(*s, *e);
    }
    let mut accepted = RangeIndex::default();
    let mut ranges: Vec<Range> = existing
        .iter()
        .map(|(start, end)| {
            accepted.insert(*start, *end);
            Range {
                start: *start,
                end: *end,
                kind: String::new(),
            }
        })
        .collect();
    detect_into(
        text,
        memories,
        &disabled,
        exclusions,
        &token_index,
        &mut accepted,
        &mut ranges,
    )?;
    Ok(ranges
        .into_iter()
        .skip(existing.len())
        .map(|r| (r.start, r.end, r.kind))
        .collect())
}
