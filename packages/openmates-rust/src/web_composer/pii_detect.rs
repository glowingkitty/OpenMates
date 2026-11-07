//! Synchronous PII detection of the web composer: regex patterns, URL and
//! coding-identifier exclusion, exclusions by stable id, disabled categories and
//! user-defined personal data entries. Port of `detectPII` in
//! `piiDetectionService.ts` (UTF-16 offsets, TS-bug-compatible overlap rules).
//! spec: specifications/features/pii-protection#pii.composer.detect-redact-exclude
use super::pii_table::{category, fit, patterns, secret_suffix, valid};
use super::protocol;
use super::utf16::{Utf16Index, WS_CLASS, index_of, js_trim, len16, units};
use regex::Regex;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

const MIN_PII_TEXT_LENGTH: usize = 6;

/// One detected span; `text[start..end]` (UTF-16) is the matched text.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Match {
    /// `PIIType`.
    pub kind: String,
    /// UTF-16 start offset.
    pub start: usize,
    /// UTF-16 end offset (exclusive; personal-data matches may exceed the text like the TS original).
    pub end: usize,
    /// Replacement placeholder.
    pub placeholder: String,
    /// Stable id (`pii-TYPE-start`, `pii-PERSONAL_DATA-<entry>-start`).
    pub id: String,
}

/// A user-defined personal data entry (`PersonalDataForDetection`).
#[derive(Clone, Debug)]
pub(crate) struct PersonalEntry {
    id: String,
    text_to_hide: String,
    replace_with: String,
    additional: Vec<String>,
    kind: String,
}

/// Detection options (`PIIDetectionOptions`).
#[derive(Clone, Debug, Default)]
pub(crate) struct Options {
    /// Match ids the user excluded.
    pub excluded_ids: HashSet<String>,
    /// Disabled settings categories.
    pub disabled_categories: HashSet<String>,
    entries: Vec<PersonalEntry>,
}

impl Options {
    /// Options with only disabled categories (internal callers).
    pub(crate) fn with_disabled(categories: &[&str]) -> Self {
        Self { disabled_categories: categories.iter().map(|c| (*c).to_string()).collect(), ..Self::default() }
    }

    /// Same options without exclusions (`{...options, excludedIds: undefined}`).
    pub(crate) fn without_exclusions(&self) -> Self {
        Self { excluded_ids: HashSet::new(), ..self.clone() }
    }

    /// The configured replacement tokens (`knownCustomPlaceholderRanges` input).
    pub(crate) fn replacement_tokens(&self) -> impl Iterator<Item = &str> {
        self.entries.iter().map(|e| e.replace_with.as_str()).filter(|t| !t.is_empty())
    }

    /// Parses the JSON `options` object of the unit protocol.
    ///
    /// # Errors
    /// `protocol` when a member has the wrong type.
    pub(crate) fn from_json(value: Option<&Value>) -> Result<Self, String> {
        let Some(value) = value.filter(|v| !v.is_null()) else { return Ok(Self::default()) };
        let strings = |key: &str| -> Result<HashSet<String>, String> {
            match value.get(key) {
                None | Some(Value::Null) => Ok(HashSet::new()),
                Some(Value::Array(items)) => items.iter().map(|i| i.as_str().map(str::to_string).ok_or_else(|| protocol(()))).collect(),
                Some(_) => Err(protocol(())),
            }
        };
        let mut entries = Vec::new();
        match value.get("personalDataEntries") {
            None | Some(Value::Null) => {}
            Some(Value::Array(items)) => {
                for item in items {
                    let text = |key: &str| item.get(key).and_then(Value::as_str).map(str::to_string);
                    let additional = match item.get("additionalTexts") {
                        None | Some(Value::Null) => Vec::new(),
                        Some(Value::Array(list)) => list.iter().filter_map(|t| t.as_str().map(str::to_string)).collect(),
                        Some(_) => return Err(protocol(())),
                    };
                    entries.push(PersonalEntry {
                        id: text("id").ok_or_else(|| protocol(()))?,
                        text_to_hide: text("textToHide").unwrap_or_default(),
                        replace_with: text("replaceWith").ok_or_else(|| protocol(()))?,
                        additional,
                        kind: text("type").unwrap_or_else(|| "EMAIL".to_string()),
                    });
                }
            }
            Some(_) => return Err(protocol(())),
        }
        Ok(Self { excluded_ids: strings("excludedIds")?, disabled_categories: strings("disabledCategories")?, entries })
    }
}

fn identifier_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"(?i-u:\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\b[0-9a-f]{40,64}\b|\[[A-Z][A-Z0-9_]*\])")
            .expect("fixed identifier pattern compiles")
    })
}

fn url_regex() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(&format!(r"https?://[^{WS_CLASS}]+")).expect("fixed url pattern compiles"))
}

fn overlaps_covered(covered: &[(usize, usize)], s: usize, e: usize) -> bool {
    covered.iter().any(|&(rs, re)| (s >= rs && s < re) || (e > rs && e <= re) || (s <= rs && e >= re))
}

/// Successive non-overlapping matches like a JS global `exec` loop, after `fit` removed lookaheads.
fn scan(re: &Regex, kind: &str, text: &str) -> Vec<(usize, usize)> {
    let (mut found, mut pos) = (Vec::new(), 0);
    while pos <= text.len() {
        let Some(m) = re.find_at(text, pos) else { break };
        match fit(kind, text, m.start(), m.end()) {
            Some(end) => {
                found.push((m.start(), end));
                pos = end;
            }
            None => pos = m.start() + text[m.start()..].chars().next().map_or(1, char::len_utf8),
        }
    }
    found
}

/// `detectPII(text, options)`.
pub(crate) fn detect(text: &str, options: &Options) -> Vec<Match> {
    if text.is_empty() || (len16(text) < MIN_PII_TEXT_LENGTH && options.entries.is_empty()) {
        return Vec::new();
    }
    let index = Utf16Index::new(text);
    let mut matches: Vec<Match> = Vec::new();
    let mut covered: Vec<(usize, usize)> = Vec::new();
    let mut counts: HashMap<&str, usize> = HashMap::new();
    if len16(text) >= MIN_PII_TEXT_LENGTH {
        let identifiers: Vec<(usize, usize)> = identifier_regex().find_iter(text).map(|m| (index.at(m.start()), index.at(m.end()))).collect();
        let urls: Vec<(usize, usize)> = url_regex().find_iter(text).map(|m| (index.at(m.start()), index.at(m.end()))).collect();
        for pattern in patterns() {
            if category(pattern.kind).is_some_and(|c| options.disabled_categories.contains(c)) {
                continue;
            }
            for (bs, be) in scan(&pattern.regex, pattern.kind, text) {
                let (s, e) = (index.at(bs), index.at(be));
                if pattern.kind == "PHONE" && identifiers.iter().any(|&(rs, re)| s < re && e > rs) {
                    continue;
                }
                if urls.iter().any(|&(zs, ze)| s >= zs && e <= ze) || overlaps_covered(&covered, s, e) {
                    continue;
                }
                let matched = &text[bs..be];
                if !valid(pattern.kind, matched) {
                    continue;
                }
                let id = format!("pii-{}-{s}", pattern.kind);
                if options.excluded_ids.contains(&id) {
                    continue;
                }
                let count = counts.entry(pattern.kind).or_insert(0);
                *count += 1;
                matches.push(Match {
                    kind: pattern.kind.to_string(),
                    start: s,
                    end: e,
                    placeholder: format!("[{}_{}_{}]", pattern.prefix, count, secret_suffix(matched)),
                    id,
                });
                covered.push((s, e));
            }
        }
    }
    personal_pass(text, options, &mut matches, &mut covered);
    matches.sort_by_key(|m| m.start);
    matches
}

/// Phase 2: case-insensitive substring detection of user-defined entries (JS `toLowerCase` + `indexOf`).
fn personal_pass(text: &str, options: &Options, matches: &mut Vec<Match>, covered: &mut Vec<(usize, usize)>) {
    if options.entries.is_empty() {
        return;
    }
    let lower = units(&text.to_lowercase());
    for entry in &options.entries {
        let mut searches: Vec<&str> = Vec::new();
        if !js_trim(&entry.text_to_hide).is_empty() {
            searches.push(&entry.text_to_hide);
        }
        searches.extend(entry.additional.iter().map(String::as_str).filter(|t| !js_trim(t).is_empty()));
        for search in searches {
            let needle = units(&search.to_lowercase());
            let width = len16(search);
            let mut from = 0;
            while from < lower.len() {
                let Some(at) = index_of(&lower, &needle, from) else { break };
                let (s, e) = (at, at + width);
                if !overlaps_covered(covered, s, e) {
                    let id = format!("pii-PERSONAL_DATA-{}-{s}", entry.id);
                    if !options.excluded_ids.contains(&id) {
                        let placeholder =
                            if entry.replace_with.starts_with('[') { entry.replace_with.clone() } else { format!("[{}]", entry.replace_with) };
                        matches.push(Match { kind: entry.kind.clone(), start: s, end: e, placeholder, id });
                        covered.push((s, e));
                    }
                }
                from = at + width.max(1);
            }
        }
    }
}

/// Wire form of a match: no matched text, the page slices its own string.
pub(crate) fn match_json(m: &Match) -> Value {
    json!({"type": m.kind, "startIndex": m.start, "endIndex": m.end, "placeholder": m.placeholder, "id": m.id})
}

/// `{text, options?}` -> `[{type, startIndex, endIndex, placeholder, id}]`.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn detect_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let text = value.get("text").and_then(Value::as_str).ok_or("protocol")?;
    let options = Options::from_json(value.get("options"))?;
    Ok(Value::Array(detect(text, &options).iter().map(match_json).collect()).to_string())
}
