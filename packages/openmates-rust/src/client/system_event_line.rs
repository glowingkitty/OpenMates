//! One readable transcript line per decrypted `role: system` chat row (shared
//! core; used by the CLI's human `chats show`). Mirrors which system rows the web
//! `ChatHistory.svelte` hides or shows: memory request/response rows and Undo
//! markers never render as bubbles, `context_entry` events render as one line.
//! A line never contains a row's raw JSON or its `pii_mappings` (real personal
//! details restored from placeholders), so a terminal never prints them.
//! spec: specifications/features/app-memories `app-memories.suggestions.post-processor`.

use std::collections::HashSet;

use serde_json::Value;

use super::memory_write_jobs::parse_memory_write_undone_event;
use super::recommendations::{
    ContextEntryAction, ContextEntrySource, RecommendationKind, parse_context_entry_event,
};

/// Type literal of the memory permission request system row.
const MEMORY_REQUEST_TYPE: &str = "app_settings_memories_request";
/// Type literal of the memory permission response system row.
const MEMORY_RESPONSE_TYPE: &str = "app_settings_memories_response";

/// How one system row appears in a text transcript.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SystemEventLine {
    /// Not shown (an Undo marker, folded into its `context_entry` line).
    Hidden,
    /// One line of text, without the row's raw content.
    Line(String),
}

/// Job ids of every `memory_write_undone` marker among `contents`, so the
/// matching `context_entry` line reads "(undone)" wherever the marker sits.
pub fn undone_memory_write_jobs<'a>(
    contents: impl IntoIterator<Item = &'a str>,
) -> HashSet<String> {
    contents
        .into_iter()
        .filter_map(parse_memory_write_undone_event)
        .map(|event| event.job_id)
        .collect()
}

/// The transcript line of one decrypted system row.
///
/// `undone_jobs` comes from [`undone_memory_write_jobs`] over the same
/// history. Plain-text system content is shown as is; an unrecognised JSON
/// event shows only its `type`, never its fields.
pub fn system_event_line(content: &str, undone_jobs: &HashSet<String>) -> SystemEventLine {
    if parse_memory_write_undone_event(content).is_some() {
        return SystemEventLine::Hidden;
    }
    if let Some(event) = parse_context_entry_event(content) {
        let kind = match event.kind {
            RecommendationKind::Memory => "Memory",
            RecommendationKind::Workflow => "Workflow",
        };
        let action = match event.action {
            ContextEntryAction::Created => "created",
            ContextEntryAction::Updated => "updated",
        };
        let by = match event.source {
            Some(ContextEntrySource::Assistant) => " by the assistant",
            None => "",
        };
        let undone = event
            .undo
            .as_ref()
            .is_some_and(|undo| undone_jobs.contains(&undo.job_id));
        let suffix = if undone { " (undone)" } else { "" };
        return SystemEventLine::Line(format!("{kind} {action}{by}: {}{suffix}", event.title));
    }
    let Ok(Value::Object(object)) = serde_json::from_str::<Value>(content) else {
        return SystemEventLine::Line(content.trim().to_owned());
    };
    match object.get("type").and_then(Value::as_str) {
        Some(MEMORY_REQUEST_TYPE) => {
            SystemEventLine::Line("The assistant asked to use your memories".to_owned())
        }
        Some(MEMORY_RESPONSE_TYPE) => SystemEventLine::Line(memory_response_line(&object)),
        Some(other) => SystemEventLine::Line(format!("System event: {other}")),
        None => SystemEventLine::Line("System event".to_owned()),
    }
}

/// "Memories shared with the assistant (3)" or "Memory request declined",
/// from the response's `action` and category counts only.
fn memory_response_line(object: &serde_json::Map<String, Value>) -> String {
    if object.get("action").and_then(Value::as_str) != Some("included") {
        return "Memory request declined".to_owned();
    }
    let count: u64 = object
        .get("categories")
        .and_then(Value::as_array)
        .map(|categories| {
            categories
                .iter()
                .filter_map(|category| category.get("entryCount").and_then(Value::as_u64))
                .sum()
        })
        .unwrap_or(0);
    if count == 0 {
        "Memories shared with the assistant".to_owned()
    } else {
        format!("Memories shared with the assistant ({count})")
    }
}

#[cfg(test)]
#[path = "system_event_line_tests.rs"]
mod tests;
