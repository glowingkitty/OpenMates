//! Transcript lines of system rows: memory events read as text, Undo folds into
//! its notice, and no line carries raw JSON or placeholder mappings.

use std::collections::HashSet;

use super::*;
use crate::client::memory_write_jobs::build_memory_write_undone_event;
use crate::client::recommendations::{
    ContextEntryHistoryEvent, ContextEntryUndo, RecommendationAction, build_context_entry_event,
};

const JOB: &str = "memory-write-job-00000000-0000-4000-8000-000000000001";

fn assistant_memory_event() -> ContextEntryHistoryEvent {
    ContextEntryHistoryEvent {
        schema_version: 1,
        event_type: "context_entry".into(),
        kind: RecommendationKind::Memory,
        action: ContextEntryAction::Created,
        entry_id: "memory-1".into(),
        title: "Career profile".into(),
        created_at: 1_700_000_000,
        source: Some(ContextEntrySource::Assistant),
        undo: Some(ContextEntryUndo {
            job_id: JOB.into(),
            action: RecommendationAction::Create,
            written_document_sha256: "a".repeat(64),
            encrypted_previous_document: None,
        }),
    }
}

#[test]
fn assistant_memory_write_reads_as_one_line() {
    let content = build_context_entry_event(&assistant_memory_event()).expect("valid event");
    assert_eq!(
        system_event_line(&content, &HashSet::new()),
        SystemEventLine::Line("Memory created by the assistant: Career profile".into())
    );
}

#[test]
fn undone_marker_is_hidden_and_marks_its_notice_undone() {
    let event = assistant_memory_event();
    let notice = build_context_entry_event(&event).expect("valid event");
    let marker = build_memory_write_undone_event(&event, 1_700_000_100).expect("undoable");
    let undone = undone_memory_write_jobs([notice.as_str(), marker.as_str()]);
    assert_eq!(system_event_line(&marker, &undone), SystemEventLine::Hidden);
    assert_eq!(
        system_event_line(&notice, &undone),
        SystemEventLine::Line("Memory created by the assistant: Career profile (undone)".into())
    );
}

#[test]
fn user_saved_workflow_has_no_assistant_attribution() {
    let content = build_context_entry_event(&ContextEntryHistoryEvent {
        kind: RecommendationKind::Workflow,
        action: ContextEntryAction::Updated,
        source: None,
        undo: None,
        title: "Weekly report".into(),
        ..assistant_memory_event()
    })
    .expect("valid event");
    assert_eq!(
        system_event_line(&content, &HashSet::new()),
        SystemEventLine::Line("Workflow updated: Weekly report".into())
    );
}

#[test]
fn memory_response_never_prints_its_placeholder_mappings() {
    let content = serde_json::json!({
        "type": "app_settings_memories_response",
        "user_message_id": "m1",
        "action": "included",
        "categories": [{"appId": "memory", "itemType": "memory-1", "entryCount": 1},
                       {"appId": "memory", "itemType": "memories", "entryCount": 2}],
        "pii_mappings": [{"placeholder": "[OM_PII_EMAIL_1]", "original": "someone@example.org"}]
    })
    .to_string();
    let SystemEventLine::Line(line) = system_event_line(&content, &HashSet::new()) else {
        panic!("response is shown as a line");
    };
    assert_eq!(line, "Memories shared with the assistant (3)");
    assert!(!line.contains("example.org") && !line.contains('{'));
}

#[test]
fn declined_memory_request_and_request_rows_are_readable() {
    let declined =
        r#"{"type":"app_settings_memories_response","action":"rejected","categories":[]}"#;
    assert_eq!(
        system_event_line(declined, &HashSet::new()),
        SystemEventLine::Line("Memory request declined".into())
    );
    let request =
        r#"{"type":"app_settings_memories_request","requested_keys":["memory-memories"]}"#;
    assert_eq!(
        system_event_line(request, &HashSet::new()),
        SystemEventLine::Line("The assistant asked to use your memories".into())
    );
}

#[test]
fn unknown_json_event_shows_only_its_type_and_plain_text_stays() {
    let unknown = r#"{"type":"code_run_event","secret_field":"value"}"#;
    assert_eq!(
        system_event_line(unknown, &HashSet::new()),
        SystemEventLine::Line("System event: code_run_event".into())
    );
    assert_eq!(
        system_event_line("  Chat moved to a Project. ", &HashSet::new()),
        SystemEventLine::Line("Chat moved to a Project.".into())
    );
}
