//! Chat Recommendations policy of the shared client core: duplicate/dismiss
//! reconcile and the `context_entry` history event codec.
//!
//! Shared core logic used by every shell (web via the shared Worker `parse`
//! unit, TUI/CLI directly). Mirrors the TypeScript contract in
//! `frontend/packages/ui/src/types/recommendations.ts`; the server sends
//! metadata only, so matching against the user's decrypted memories happens
//! here and local memories never reach the server.
//! Spec: `specifications/features/app-memories/specification.yml`
//! (`app-memories.recommendations.*`); plan: `docs/plans/chat-recommendations/plan.yml`.
use crate::error::{Error, Result};
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;

/// Maximum recommendations kept per kind after reconcile.
pub const MAX_PER_KIND: usize = 3;
/// Jaccard threshold (3/5) above which a proposed memory counts as an existing one.
const SIMILARITY_NUM: usize = 3;
const SIMILARITY_DEN: usize = 5;
/// Bound on every list in a reconcile input; larger inputs are a protocol error.
const MAX_LIST: usize = 4096;

/// Kind of entry a recommendation would create or update.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RecommendationKind {
    /// A memory entry.
    Memory,
    /// A workflow.
    Workflow,
}

/// Whether a recommendation creates a new entry or updates an existing one.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RecommendationAction {
    /// Create a new entry.
    Create,
    /// Update an existing entry (`target_id` names it).
    Update,
}

/// One recommendation as produced by post-processing (metadata only).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChatRecommendation {
    /// Stable id derived server-side from task id, kind and index.
    pub id: String,
    /// Memory or workflow.
    pub kind: RecommendationKind,
    /// Create or update.
    pub action: RecommendationAction,
    /// Existing memory/workflow id when updating, else `None`.
    pub target_id: Option<String>,
    /// Short title (at most 80 characters).
    pub title: String,
    /// One or two sentences (at most 200 characters).
    pub summary: String,
}

/// Plaintext of `chats.encrypted_recommendations` (encrypted with the chat key by the shell).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChatRecommendationsState {
    /// Always 1.
    pub schema_version: u8,
    /// Open recommendations of the latest completed turn, after reconcile.
    pub items: Vec<ChatRecommendation>,
    /// Normalized titles dismissed in this chat.
    pub dismissed: Vec<String>,
    /// Normalized titles saved from this chat.
    pub resolved: Vec<String>,
    /// Unix seconds of the last change.
    pub updated_at: i64,
}

/// Local memory metadata used for matching; never sent to the server.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalMemoryMetadata {
    /// Memory id.
    pub id: String,
    /// Memory title.
    pub title: String,
    /// The memory's "when to use" text.
    pub when_to_use: String,
}

/// Input of [`reconcile_recommendations`].
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReconcileRecommendationsInput {
    /// Recommendations of the completed turn.
    pub incoming: Vec<ChatRecommendation>,
    /// Normalized (or raw; re-normalized here) titles the user dismissed.
    pub dismissed: Vec<String>,
    /// Normalized (or raw) titles the user saved.
    pub resolved: Vec<String>,
    /// All locally decrypted memories, including Mention-only ones.
    pub local_memories: Vec<LocalMemoryMetadata>,
}

/// Memory/workflow entry a saved recommendation produced.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ContextEntryAction {
    /// A new entry was created.
    Created,
    /// An existing entry was updated.
    Updated,
}

/// Plaintext of the encrypted `role: system` chat message written when the user saves.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContextEntryHistoryEvent {
    /// Always 1.
    pub schema_version: u8,
    /// Always `context_entry`.
    #[serde(rename = "type")]
    pub event_type: String,
    /// Memory or workflow.
    pub kind: RecommendationKind,
    /// Created or updated.
    pub action: ContextEntryAction,
    /// Id of the saved memory/workflow.
    pub entry_id: String,
    /// Title shown in the history line.
    pub title: String,
    /// Unix seconds.
    pub created_at: i64,
}

/// Event type literal of [`ContextEntryHistoryEvent::event_type`].
pub const CONTEXT_ENTRY_TYPE: &str = "context_entry";

/// Unicode-lowercase, replace every non-alphanumeric character (`char::is_alphanumeric`)
/// with a space, collapse whitespace and trim. Non-Latin titles stay distinct;
/// a result of `""` never matches anything (callers must check).
pub fn normalize_title(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    let mut gap = true;
    for ch in value.to_lowercase().chars() {
        if ch.is_alphanumeric() {
            out.push(ch);
            gap = false;
        } else if !gap {
            out.push(' ');
            gap = true;
        }
    }
    out.truncate(out.trim_end().len());
    out
}

fn tokens(value: &str) -> BTreeSet<String> {
    normalize_title(value)
        .split(' ')
        .filter(|t| !t.is_empty())
        .map(str::to_owned)
        .collect()
}

/// Jaccard >= 0.6 without floating point; two empty sets never match.
fn similar(a: &BTreeSet<String>, b: &BTreeSet<String>) -> bool {
    let inter = a.intersection(b).count();
    let union = a.len() + b.len() - inter;
    union > 0 && inter * SIMILARITY_DEN >= union * SIMILARITY_NUM
}

/// Local memory a proposed memory `create` duplicates, if any. Equal normalized
/// title wins over a fuzzy match; among fuzzy matches the first memory wins.
fn matching_memory<'a>(
    title: &str,
    memories: &'a [LocalMemoryMetadata],
) -> Option<&'a LocalMemoryMetadata> {
    let norm = normalize_title(title);
    if norm.is_empty() {
        return None;
    }
    if let Some(exact) = memories.iter().find(|m| normalize_title(&m.title) == norm) {
        return Some(exact);
    }
    let wanted = tokens(title);
    memories
        .iter()
        .find(|m| similar(&wanted, &tokens(&m.title)) || similar(&wanted, &tokens(&m.when_to_use)))
}

/// Applies the Recommendations duplicate/dismiss policy to a turn's recommendations.
///
/// Order of rules, per incoming item in order: drop titles
/// whose normalized form is dismissed or resolved; convert a memory `create`
/// that matches a local memory (equal normalized title, title-token Jaccard
/// >= 0.6, or title tokens vs `when_to_use` tokens Jaccard >= 0.6) into an
/// `update` of that memory, keeping the memory's own title; re-check
/// dismissed/resolved against the resulting title; drop in-list duplicates
/// (same kind and normalized title, or same kind and update target); cap
/// [`MAX_PER_KIND`] per kind. Output order follows the incoming order.
///
/// # Errors
/// [`Error::Protocol`] when an input list exceeds the 4096-item bound.
pub fn reconcile_recommendations(
    input: &ReconcileRecommendationsInput,
) -> Result<Vec<ChatRecommendation>> {
    if [
        input.incoming.len(),
        input.dismissed.len(),
        input.resolved.len(),
        input.local_memories.len(),
    ]
    .iter()
    .any(|n| *n > MAX_LIST)
    {
        return Err(Error::Protocol);
    }
    let blocked: BTreeSet<String> = input
        .dismissed
        .iter()
        .chain(&input.resolved)
        .map(|t| normalize_title(t))
        .filter(|t| !t.is_empty())
        .collect();
    let mut seen_titles: BTreeSet<(bool, String)> = BTreeSet::new();
    let mut seen_targets: BTreeSet<(bool, String)> = BTreeSet::new();
    let (mut memories, mut workflows) = (0usize, 0usize);
    let mut out = Vec::new();
    for item in &input.incoming {
        let norm = normalize_title(&item.title);
        if !norm.is_empty() && blocked.contains(&norm) {
            continue;
        }
        let is_memory = item.kind == RecommendationKind::Memory;
        let mut item = item.clone();
        if is_memory && item.action == RecommendationAction::Create {
            if let Some(memory) = matching_memory(&item.title, &input.local_memories) {
                item.action = RecommendationAction::Update;
                item.target_id = Some(memory.id.clone());
                item.title = memory.title.clone();
            }
        }
        let final_norm = normalize_title(&item.title);
        if !final_norm.is_empty() {
            if blocked.contains(&final_norm) || !seen_titles.insert((is_memory, final_norm)) {
                continue;
            }
        }
        if item.action == RecommendationAction::Update
            && let Some(target) = &item.target_id
            && !seen_targets.insert((is_memory, target.clone()))
        {
            continue;
        }
        let count = if is_memory {
            &mut memories
        } else {
            &mut workflows
        };
        if *count >= MAX_PER_KIND {
            continue;
        }
        *count += 1;
        out.push(item);
    }
    Ok(out)
}

/// JSON form of [`reconcile_recommendations`] for bindings: input
/// `ReconcileRecommendationsInput`, output a `ChatRecommendation[]` array.
///
/// # Errors
/// [`Error::Protocol`] for malformed JSON or oversized input.
pub fn reconcile_recommendations_json(input_json: &str) -> Result<String> {
    let input: ReconcileRecommendationsInput =
        serde_json::from_str(input_json).map_err(|_| Error::Protocol)?;
    serde_json::to_string(&reconcile_recommendations(&input)?).map_err(|_| Error::Protocol)
}

fn valid_event(event: &ContextEntryHistoryEvent) -> bool {
    event.schema_version == 1
        && event.event_type == CONTEXT_ENTRY_TYPE
        && !event.entry_id.trim().is_empty()
        && !event.title.trim().is_empty()
        && event.created_at >= 0
}

/// Serializes a validated `context_entry` event as the system message content.
///
/// # Errors
/// [`Error::Protocol`] when `schema_version` is not 1, the type is not
/// `context_entry`, `entry_id`/`title` is blank or `created_at` is negative.
pub fn build_context_entry_event(event: &ContextEntryHistoryEvent) -> Result<String> {
    if !valid_event(event) {
        return Err(Error::Protocol);
    }
    serde_json::to_string(event).map_err(|_| Error::Protocol)
}

/// Parses system message content; `None` for anything that is not a valid
/// `context_entry` event (other system events, plain text, wrong schema).
pub fn parse_context_entry_event(content: &str) -> Option<ContextEntryHistoryEvent> {
    serde_json::from_str::<ContextEntryHistoryEvent>(content)
        .ok()
        .filter(valid_event)
}

/// JSON form of [`build_context_entry_event`] for bindings.
///
/// # Errors
/// [`Error::Protocol`] for malformed JSON or an invalid event.
pub fn build_context_entry_event_json(event_json: &str) -> Result<String> {
    let event: ContextEntryHistoryEvent =
        serde_json::from_str(event_json).map_err(|_| Error::Protocol)?;
    build_context_entry_event(&event)
}

/// JSON form of [`parse_context_entry_event`] for bindings: the event object or `null`.
pub fn parse_context_entry_event_json(content: &str) -> String {
    match parse_context_entry_event(content) {
        Some(event) => serde_json::to_string(&event).unwrap_or_else(|_| "null".into()),
        None => "null".into(),
    }
}

/// Keeps well-formed `ChatRecommendation` objects of a server payload (at most
/// 2 x [`MAX_PER_KIND`]); used by the send observer so CLI output never shows
/// malformed rows.
pub fn recommendations_from_payload(rows: &[serde_json::Value]) -> Vec<ChatRecommendation> {
    rows.iter()
        .filter_map(|row| serde_json::from_value::<ChatRecommendation>(row.clone()).ok())
        .take(2 * MAX_PER_KIND)
        .collect()
}

#[cfg(test)]
#[path = "recommendations_tests.rs"]
mod tests;
