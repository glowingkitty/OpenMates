//! Start-screen workflow suggestions of the Workflows page: turns the decrypted
//! chat Recommendations states of many chats into an ordered, de-duplicated list.
//!
//! Shared core policy; the web shell decrypts each chat's
//! `encrypted_recommendations` and passes plaintext states in (parse unit).
//! Spec: `specifications/features/workflows-ui/specification.yml`
//! (`workflows-ui.home.prompt-suggestions`).
use super::recommendations::{
    normalize_title, ChatRecommendationsState, RecommendationAction, RecommendationKind,
};
use crate::error::{Error, Result};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

/// Largest number of suggestions ever returned.
const MAX_LIMIT: u32 = 10;

/// Input of [`workflow_start_suggestions`].
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkflowStartSuggestionsInput {
    /// Decrypted Recommendations states, one per chat, in any order.
    pub states: Vec<ChatRecommendationsState>,
    /// Wanted count; clamped to 1..=10.
    pub limit: u32,
}

/// One start-screen workflow suggestion.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkflowStartSuggestion {
    /// Short workflow title.
    pub title: String,
    /// One or two sentences describing it.
    pub summary: String,
}

/// Picks workflow `create` recommendations, newest chat first.
///
/// Skips states with `schema_version != 1`, items dismissed or resolved in their
/// own state, and duplicates by normalized title (the newest chat wins). Item
/// order inside a state is kept; the result is capped at the clamped limit.
pub fn workflow_start_suggestions(
    input: &WorkflowStartSuggestionsInput,
) -> Vec<WorkflowStartSuggestion> {
    let limit = input.limit.clamp(1, MAX_LIMIT) as usize;
    let mut states: Vec<&ChatRecommendationsState> = input
        .states
        .iter()
        .filter(|s| s.schema_version == 1)
        .collect();
    // Stable sort keeps the caller's order for equal timestamps.
    states.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));
    let mut seen: BTreeSet<String> = BTreeSet::new();
    let mut out = Vec::new();
    for state in states {
        let blocked: BTreeSet<String> = state
            .dismissed
            .iter()
            .chain(state.resolved.iter())
            .map(|t| normalize_title(t))
            .collect();
        for item in &state.items {
            if item.kind != RecommendationKind::Workflow
                || item.action != RecommendationAction::Create
            {
                continue;
            }
            let norm = normalize_title(&item.title);
            if norm.is_empty() || blocked.contains(&norm) || !seen.insert(norm) {
                continue;
            }
            out.push(WorkflowStartSuggestion {
                title: item.title.clone(),
                summary: item.summary.clone(),
            });
            if out.len() >= limit {
                return out;
            }
        }
    }
    out
}

/// JSON wrapper of [`workflow_start_suggestions`] for the browser binding.
///
/// # Errors
/// [`Error::Protocol`] for malformed input JSON.
pub fn workflow_start_suggestions_json(input_json: &str) -> Result<String> {
    let input: WorkflowStartSuggestionsInput =
        serde_json::from_str(input_json).map_err(|_| Error::Protocol)?;
    serde_json::to_string(&workflow_start_suggestions(&input)).map_err(|_| Error::Protocol)
}

#[cfg(test)]
#[path = "workflow_start_suggestions_tests.rs"]
mod tests;
