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
fn other_system_rows_and_invalid_payloads_stay_ordinary_messages() {
    let messages = vec![
        message(
            "s1",
            "system",
            "{\"type\":\"embed_updated\",\"embed_id\":\"bad id\"}".into(),
        ),
        message("s2", "system", "plain note".into()),
    ];
    let out = lines(&messages);
    assert_eq!(out.len(), 2);
    assert!(out.iter().all(|line| line.starts_with("system: ")));
}
