//! In-memory embed_ref index (`embedRefIndex.ts`). Never persisted: embed_ref
//! slugs can reveal private content hints for encrypted chats.
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct EmbedRefIndexEntry {
    pub embed_id: String,
    #[serde(default)]
    pub app_id: Option<String>,
    #[serde(default)]
    pub skill_id: Option<String>,
    #[serde(default, rename = "type")]
    pub embed_type: Option<String>,
}
#[derive(Clone, PartialEq, Eq, Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct ResolvedEmbedRef {
    pub embed_ref: String,
    pub entry: EmbedRefIndexEntry,
}

/// Insertion-ordered like a JS `Map`: re-registering a key keeps its position,
/// which decides the first suffix candidate exactly as the web index does.
#[derive(Default)]
pub struct EmbedRefIndex {
    order: Vec<(String, EmbedRefIndexEntry)>,
    positions: HashMap<String, usize>,
    version: u64,
}

fn is_unicode_dash(c: char) -> bool {
    matches!(c, '\u{2010}'..='\u{2015}' | '\u{2212}')
}
/// ECMAScript `String.prototype.trim` set: White_Space minus U+0085, plus U+FEFF.
fn is_js_trim(c: char) -> bool {
    (c.is_whitespace() && c != '\u{0085}') || c == '\u{feff}'
}
fn normalize_token(value: &str) -> String {
    value
        .trim_matches(is_js_trim)
        .chars()
        .map(|c| if is_unicode_dash(c) { '-' } else { c })
        .collect()
}
fn is_suffix_only(value: &str) -> bool {
    let Some(rest) = value.strip_prefix('-') else { return false };
    (2..=4).contains(&rest.len()) && rest.bytes().all(|b| b.is_ascii_alphanumeric())
}

impl EmbedRefIndex {
    pub fn new() -> Self {
        Self::default()
    }
    /// Subscribers refresh when this increases (`embedRefIndexVersion`).
    pub fn version(&self) -> u64 {
        self.version
    }
    fn set(&mut self, key: String, entry: EmbedRefIndexEntry) -> Option<EmbedRefIndexEntry> {
        match self.positions.get(&key) {
            Some(&at) => Some(std::mem::replace(&mut self.order[at].1, entry)),
            None => {
                self.positions.insert(key.clone(), self.order.len());
                self.order.push((key, entry));
                None
            }
        }
    }
    fn get(&self, key: &str) -> Option<&EmbedRefIndexEntry> {
        self.positions.get(key).map(|&at| &self.order[at].1)
    }
    /// `registerEmbedRefIndex`; returns whether subscribers must refresh.
    pub fn register(&mut self, embed_ref: &str, entry: EmbedRefIndexEntry) -> bool {
        if embed_ref.is_empty() || entry.embed_id.is_empty() {
            return false;
        }
        let normalized = normalize_token(embed_ref);
        if normalized.is_empty() {
            return false;
        }
        let embed_id = entry.embed_id.clone();
        let previous_ref = self.set(normalized, entry.clone());
        let previous_id = self.set(embed_id, entry.clone());
        let changed = previous_ref.as_ref() != Some(&entry) || previous_id.as_ref() != Some(&entry);
        if changed {
            self.version += 1;
        }
        changed
    }
    /// `resolveEmbedRefIndexReference`: exact match, else an unambiguous
    /// case-insensitive `-XXXX` suffix match across human-readable refs.
    pub fn resolve(&self, embed_ref: &str) -> Option<ResolvedEmbedRef> {
        let normalized = normalize_token(embed_ref);
        if let Some(entry) = self.get(&normalized) {
            return Some(ResolvedEmbedRef { embed_ref: normalized, entry: entry.clone() });
        }
        if !is_suffix_only(&normalized) {
            return None;
        }
        let suffix = normalized.to_lowercase();
        let mut resolved: Option<ResolvedEmbedRef> = None;
        for (candidate, entry) in &self.order {
            if *candidate == entry.embed_id || !candidate.to_lowercase().ends_with(&suffix) {
                continue;
            }
            match &resolved {
                Some(found) if found.entry.embed_id != entry.embed_id => return None,
                Some(_) => {}
                None => {
                    resolved = Some(ResolvedEmbedRef { embed_ref: candidate.clone(), entry: entry.clone() })
                }
            }
        }
        resolved
    }
    /// `clearEmbedRefIndexEntries` (the web store keeps its version counter).
    pub fn clear(&mut self) {
        self.order.clear();
        self.positions.clear();
    }
}
/// `String.prototype.trim` for adapters that mirror JS identifier handling.
pub(crate) fn js_trim(value: &str) -> &str {
    value.trim_matches(is_js_trim)
}
