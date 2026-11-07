//! Mention and saved-embed suggestion ranking: score/filter/sort/cut of @-mention
//! results and of the saved-embed index. Ports of `rankMentionResults`
//! (`mentionRanking.ts`) and `rankSavedEmbedIndex` (`embedSuggestionSearch.ts`).
//! Both ops return indices into the caller's list, never text; the page keeps its
//! result objects and reorders them, so no string leaves the Worker.
//! spec: specifications/features/message-input#message-input.suggestions.contextual
use super::protocol;
use serde_json::{Value, json};
use std::cmp::Ordering;

const SETTINGS_MEMORY_BOOST: i64 = 30;
const PROJECT_BOOST: i64 = 40;

/// `calculateMatchScore(query, terms, type)`.
fn match_score(query: &str, terms: &[&str], kind: Option<&str>) -> i64 {
    if query.is_empty() {
        return 1;
    }
    let lower = query.to_lowercase();
    let mut score = 0;
    for term in terms {
        if *term == lower {
            score += 100;
        } else if term.starts_with(&lower) {
            score += 50;
        } else if term.contains(&lower) {
            score += 25;
        }
    }
    if score > 0 && matches!(kind, Some("settings_memory" | "settings_memory_entry")) {
        score += SETTINGS_MEMORY_BOOST;
    }
    if score > 0 && matches!(kind, Some("project" | "project_folder" | "project_file")) {
        score += PROJECT_BOOST;
    }
    score
}

/// `Array.prototype.slice(0, limit)` length for a possibly negative `limit`.
fn slice_end(len: usize, limit: i64) -> usize {
    if limit < 0 { len.saturating_sub(limit.unsigned_abs() as usize) } else { len.min(limit as usize) }
}

/// `rankMentionResults`: `{query, limit, candidates:[{searchTerms:[str], type?}]}`
/// -> `[{index, score}]`, best first, stable among equal scores.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn rank_mentions_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let query = value.get("query").and_then(Value::as_str).ok_or("protocol")?;
    let limit = value.get("limit").and_then(Value::as_i64).ok_or("protocol")?;
    let candidates = value.get("candidates").and_then(Value::as_array).ok_or("protocol")?;
    let mut scored: Vec<(usize, i64)> = Vec::new();
    for (index, candidate) in candidates.iter().enumerate() {
        let terms: Vec<&str> = candidate
            .get("searchTerms")
            .and_then(Value::as_array)
            .ok_or("protocol")?
            .iter()
            .map(|t| t.as_str().ok_or_else(|| protocol(())))
            .collect::<Result<_, _>>()?;
        let kind = candidate.get("type").and_then(Value::as_str);
        let score = match_score(query, &terms, kind);
        if score > 0 {
            scored.push((index, score));
        }
    }
    scored.sort_by(|a, b| b.1.cmp(&a.1));
    scored.truncate(slice_end(scored.len(), limit));
    Ok(Value::Array(scored.into_iter().map(|(index, score)| json!({"index": index, "score": score})).collect()).to_string())
}

/// `rankSavedEmbedIndex`: `{query, limit, entries:[{title, searchText, updatedAt}]}`
/// -> indices of the kept entries. `query` is already trimmed and lowercased by the
/// page and `searchText` is the lowercased index text.
///
/// # Errors
/// `protocol` for a malformed payload.
pub fn rank_saved_embeds_json(input: &str) -> Result<String, String> {
    let value: Value = serde_json::from_str(input).map_err(protocol)?;
    let query = value.get("query").and_then(Value::as_str).ok_or("protocol")?;
    let limit = value.get("limit").and_then(Value::as_i64).ok_or("protocol")?;
    let entries = value.get("entries").and_then(Value::as_array).ok_or("protocol")?;
    let mut matches: Vec<(usize, bool, f64)> = Vec::new();
    for (index, entry) in entries.iter().enumerate() {
        let text = entry.get("searchText").and_then(Value::as_str).ok_or("protocol")?;
        let title = entry.get("title").and_then(Value::as_str).ok_or("protocol")?;
        let updated = entry.get("updatedAt").and_then(Value::as_f64).ok_or("protocol")?;
        if text.contains(query) {
            matches.push((index, title.to_lowercase().contains(query), updated));
        }
    }
    matches.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| b.2.partial_cmp(&a.2).unwrap_or(Ordering::Equal)));
    matches.truncate(slice_end(matches.len(), limit));
    Ok(Value::Array(matches.into_iter().map(|(index, _, _)| json!(index)).collect()).to_string())
}
