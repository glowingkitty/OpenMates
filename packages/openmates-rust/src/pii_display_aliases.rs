//! Pure port of `piiDisplayAliases.ts::createPIIDisplayAliases`.
//!
//! Presentation only: aliases never replace canonical message/mapping tokens.
use regex::Regex;
use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

/// Message content tree. Objects are ordered `{"$entries": [[key, node], ...]}`
/// so JavaScript `Object.values` order survives the JSON boundary.
#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
pub enum SourceNode {
    Text(String),
    List(Vec<SourceNode>),
    Object {
        #[serde(rename = "$entries")]
        entries: Vec<(String, SourceNode)>,
    },
    Other(serde::de::IgnoredAny),
}

/// One PII mapping (`PIIMapping`); `original` may be absent or empty.
#[derive(Debug, Clone, Deserialize)]
pub struct PiiMapping {
    pub placeholder: String,
    #[serde(default)]
    pub original: Option<String>,
    #[serde(rename = "type")]
    pub kind: String,
}

fn collect(node: &SourceNode, out: &mut Vec<String>) {
    match node {
        SourceNode::Text(s) => out.push(s.clone()),
        SourceNode::List(items) => items.iter().for_each(|n| collect(n, out)),
        SourceNode::Object { entries } => entries.iter().for_each(|(_, n)| collect(n, out)),
        SourceNode::Other(_) => {}
    }
}

fn enhanced_token() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| {
        Regex::new(r"^\[([A-Z][A-Z0-9_]*?)_[1-9][0-9]*_[0-9a-f]{16}(?:_[1-9][0-9]*_[0-9a-f]{32})*\]$").expect("static regex")
    })
}

fn bracket_token() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\[[^\[\]\r\n]+\]").expect("static regex"))
}

fn bracketed(value: &str) -> String {
    if value.starts_with('[') { value.to_string() } else { format!("[{value}]") }
}

/// Returns `(placeholder, alias)` pairs in Map insertion order.
pub fn create_pii_display_aliases(
    source_content: Option<&SourceNode>,
    mappings: &[PiiMapping],
    configured_replacements: &[String],
) -> Vec<(String, String)> {
    let mut parts = Vec::new();
    if let Some(node) = source_content {
        collect(node, &mut parts);
    }
    let source = parts.join("\n");
    let mut reserved: HashSet<String> = bracket_token().find_iter(&source).map(|m| m.as_str().to_string()).collect();
    for value in configured_replacements.iter().filter(|v| !v.is_empty()) {
        reserved.insert(bracketed(value));
    }
    for mapping in mappings {
        reserved.insert(mapping.placeholder.clone());
    }
    let configured: HashSet<String> = configured_replacements.iter().map(|v| bracketed(v)).collect();
    let mut candidates: Vec<(String, String, usize)> = Vec::new();
    for mapping in mappings {
        let Some(caps) = enhanced_token().captures(&mapping.placeholder) else { continue };
        if caps[1] != mapping.kind || configured.contains(&mapping.placeholder) {
            continue;
        }
        let token_index = source.find(&mapping.placeholder);
        let original_index = mapping
            .original
            .as_deref()
            .filter(|o| !o.is_empty())
            .and_then(|o| source.find(o));
        if let Some(index) = token_index.or(original_index) {
            candidates.push((mapping.placeholder.clone(), caps[1].to_string(), index));
        }
    }
    candidates.sort_by_key(|c| c.2);
    let mut counters: HashMap<String, u64> = HashMap::new();
    let mut aliases: Vec<(String, String)> = Vec::new();
    let mut seen: HashSet<String> = HashSet::new();
    for (placeholder, kind, _) in candidates {
        if seen.contains(&placeholder) {
            continue;
        }
        let mut counter = counters.get(&kind).copied().unwrap_or(0);
        let alias = loop {
            counter += 1;
            let alias = format!("[{kind}_{counter}]");
            if !reserved.contains(&alias) {
                break alias;
            }
        };
        counters.insert(kind, counter);
        reserved.insert(alias.clone());
        seen.insert(placeholder.clone());
        aliases.push((placeholder, alias));
    }
    aliases
}
