//! Transcript folding and wording of `embed_updated` system events (CLI and TUI).
use super::*;
use openmates_sdk::client::embed_updated_event::{EmbedUpdatedEvent, build_embed_updated_event};

fn event(
    embed_id: &str,
    version: i64,
    action: EmbedUpdateAction,
    restored_from: Option<i64>,
) -> String {
    build_embed_updated_event(&EmbedUpdatedEvent {
        schema_version: 1,
        event_type: "embed_updated".into(),
        embed_id: embed_id.into(),
        embed_ref: "logo-sketch".into(),
        embed_kind: EmbedKind::Image,
        version,
        base_version: Some(version - 1),
        action,
        restored_from,
        surface: EmbedUpdateSurface::Chat,
        created_at: 1_700_000_000 + version,
    })
    .unwrap_or_else(|_| panic!("synthetic event"))
}

fn message(id: &str, role: &str, content: String) -> Message {
    Message {
        id: id.into(),
        role: role.into(),
        content,
        ..Message::default()
    }
}

fn lines(messages: &[Message]) -> Vec<String> {
    transcript_items(messages)
        .into_iter()
        .map(|item| match item {
            TranscriptItem::Message(message) => format!("{}: {}", message.role, message.content),
            TranscriptItem::Notice(line) => format!("notice: {line}"),
        })
        .collect()
}

// contract-test: supporting surface=cli assertions=embed-user-edits.event.chat-notice,embed-user-edits.enhance.faithful-2k
#[test]
fn single_enhance_event_is_one_quiet_line_not_a_message() {
    let messages = vec![
        message("u1", "user", "Draw a logo".into()),
        message("a1", "assistant", "Here it is".into()),
        message(
            "embed-updated-e1-v2",
            "system",
            event("e1", 2, EmbedUpdateAction::Enhance, None),
        ),
    ];
    assert_eq!(
        lines(&messages),
        vec![
            "user: Draw a logo",
            "assistant: Here it is",
            "notice: Image updated · version 2 (enhanced)"
        ]
    );
}

// contract-test: supporting surface=cli assertions=embed-user-edits.event.collapse,embed-user-edits.restore.creates-version
#[test]
fn consecutive_events_of_one_embed_fold_into_one_line_naming_the_newest() {
    let messages = vec![
        message(
            "embed-updated-e1-v2",
            "system",
            event("e1", 2, EmbedUpdateAction::Enhance, None),
        ),
        message(
            "embed-updated-e1-v3",
            "system",
            event("e1", 3, EmbedUpdateAction::Restore, Some(1)),
        ),
        message(
            "embed-updated-e1-v4",
            "system",
            event("e1", 4, EmbedUpdateAction::Restore, Some(2)),
        ),
        message("u2", "user", "Thanks".into()),
        message(
            "embed-updated-e1-v5",
            "system",
            event("e1", 5, EmbedUpdateAction::Edit, None),
        ),
    ];
    assert_eq!(
        lines(&messages),
        vec![
            "notice: Image updated, 3 changes · version 4 (restored version 2)",
            "user: Thanks",
            "notice: Image updated · version 5 (edited)"
        ]
    );
}

// contract-test: supporting surface=cli assertions=embed-user-edits.event.chat-notice
#[test]
fn other_system_rows_and_invalid_payloads_become_lines_without_raw_json() {
    let messages = vec![
        message(
            "s1",
            "system",
            "{\"type\":\"embed_updated\",\"embed_id\":\"bad id\"}".into(),
        ),
        message("s2", "system", "plain note".into()),
    ];
    assert_eq!(
        lines(&messages),
        vec!["notice: System event: embed_updated", "notice: plain note"]
    );
}

// contract-test: supporting surface=cli assertions=app-memories.privacy.client-encrypted
#[test]
fn memory_events_read_as_lines_and_never_print_placeholder_mappings() {
    let response = serde_json::json!({
        "type": "app_settings_memories_response",
        "user_message_id": "u1",
        "action": "included",
        "categories": [{"appId": "memory", "itemType": "memory-1", "entryCount": 1}],
        "pii_mappings": [{"placeholder": "[OM_PII_EMAIL_1]", "original": "someone@example.org"}]
    })
    .to_string();
    let messages = vec![
        message("u1", "user", "Write my cover letter".into()),
        message("u1-memory-response-r1", "system", response),
        message("a1", "assistant", "Here is your letter".into()),
    ];
    let out = lines(&messages);
    assert_eq!(
        out,
        vec![
            "user: Write my cover letter",
            "notice: Memories shared with the assistant (1)",
            "assistant: Here is your letter"
        ]
    );
    assert!(out.iter().all(|line| !line.contains("example.org")));
}

// contract-test: supporting surface=cli assertions=chat-orchestration.events.creator-system-events
#[test]
fn chat_orchestration_events_read_as_one_line_each() {
    let report = r#"{"schema_version":1,"type":"chat_orchestration","action":"report","chat_id":"11111111-1111-4111-8111-111111111111","title":"Kitchen quotes","text":"Three quotes found","event_id":"ev-1","created_at":1700000000}"#;
    let finished = report
        .replace(r#""action":"report""#, r#""action":"finished""#)
        .replace(r#","text":"Three quotes found""#, "")
        .replace("ev-1", "ev-2");
    let messages = vec![
        message("u1", "user", "Start a chat for kitchen quotes".into()),
        message("ev-1", "system", report.into()),
        message("ev-2", "system", finished),
    ];
    assert_eq!(
        lines(&messages),
        vec![
            "user: Start a chat for kitchen quotes".to_owned(),
            "notice: Report from Kitchen quotes: Three quotes found".to_owned(),
            "notice: Kitchen quotes finished".to_owned(),
        ]
    );
}
