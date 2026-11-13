use super::*;
use crate::client::recommendations::{RecommendationAction, RecommendationKind};
use crate::model::Message;

fn msg(id: &str, role: &str, content: &str) -> Message {
    Message {
        id: id.into(),
        role: role.into(),
        content: content.into(),
        sender: String::new(),
        thinking: String::new(),
        embeds: Vec::new(),
    }
}

fn rec(id: &str, title: &str) -> ChatRecommendation {
    ChatRecommendation {
        id: id.into(),
        kind: RecommendationKind::Memory,
        action: RecommendationAction::Create,
        target_id: None,
        title: title.into(),
        summary: "Why".into(),
    }
}

const DOC: &str = "---\ntitle: Tea\nwhen_to_use: Drinks\n---\nLikes green tea";

#[test]
fn embed_blocks_are_stripped_but_other_code_stays() {
    let text = "Hi\n```json\n{\"embed_id\":\"x\"}\n```\nbye ```json\n[1]\n```";
    let out = strip_embed_blocks(text);
    assert!(!out.contains("embed_id"));
    assert!(out.contains("[1]") && out.contains("Hi"));
}

#[test]
fn latest_turn_picks_last_assistant_and_preceding_user() {
    let messages = turn_messages(&[
        msg("u1", "user", "first"),
        msg("a1", "assistant", "one"),
        msg("u2", "user", "second"),
        msg("s", "system", "ignored"),
        msg("a2", "assistant", "two"),
    ]);
    let (user, assistant, id) = latest_turn(&messages);
    assert_eq!((user.as_str(), assistant.as_str()), ("second", "two"));
    assert_eq!(id.as_deref(), Some("u2"));
}

#[test]
fn create_body_carries_request_id_and_message_id() {
    let messages = turn_messages(&[msg("u", "user", "q"), msg("a", "assistant", "r")]);
    let body = create_draft_body("chat", &rec("r1", "Tea"), &messages, "req-1");
    assert_eq!(body["request_id"], "req-1");
    assert_eq!(body["message_id"], "u");
    assert_eq!(body["user_message"], "q");
    assert_eq!(body["title"], "Tea");
}

#[test]
fn update_body_caps_messages_at_24() {
    let rows: Vec<Message> = (0..40)
        .map(|i| msg(&format!("m{i}"), if i % 2 == 0 { "user" } else { "assistant" }, "t"))
        .collect();
    let body = update_preview_body("c", "personal:1", DOC, &turn_messages(&rows), "r");
    assert_eq!(body["messages"].as_array().map(Vec::len), Some(24));
    assert_eq!(body["memory_id"], "personal:1");
}

#[test]
fn create_response_requires_a_parseable_document_and_valid_app_id() {
    let ok = parse_create_draft_response(&json!({"body": DOC, "app_id": "travel"}));
    assert_eq!(ok, Some((DOC.to_owned(), Some("travel".into()))));
    let dropped = parse_create_draft_response(&json!({"body": DOC, "app_id": "Bad Id"}));
    assert_eq!(dropped, Some((DOC.to_owned(), None)));
    assert_eq!(parse_create_draft_response(&json!({"body": "no frontmatter"})), None);
    assert_eq!(parse_create_draft_response(&json!({})), None);
}

#[test]
fn update_response_maps_updated_unchanged_and_garbage() {
    assert_eq!(
        parse_update_preview_response(&json!({"status": "updated", "body": DOC})),
        Some(Some(DOC.to_owned()))
    );
    assert_eq!(parse_update_preview_response(&json!({"status": "unchanged"})), Some(None));
    assert_eq!(parse_update_preview_response(&json!({"status": "updated"})), None);
    assert_eq!(parse_update_preview_response(&json!({"status": "x"})), None);
}

#[test]
fn statuses_map_to_failures() {
    use RecommendationDraftFailure::*;
    assert_eq!(failure_for_status(Some(402)), InsufficientCredits);
    assert_eq!(failure_for_status(Some(409)), NetworkUnavailable);
    assert_eq!(failure_for_status(None), NetworkUnavailable);
    assert_eq!(failure_for_status(Some(502)), RequestFailed);
}

#[test]
fn resolving_removes_the_item_and_remembers_its_title() {
    let state = ChatRecommendationsState {
        schema_version: 1,
        items: vec![rec("a", "Green Tea!"), rec("b", "Other")],
        dismissed: vec![],
        resolved: vec![],
        updated_at: 1,
    };
    let next = state_with_resolved(&state, "a", 9).expect("open item");
    assert_eq!(next.items.len(), 1);
    assert_eq!(next.resolved, vec!["Green Tea!".to_owned()]);
    assert_eq!(next.updated_at, 9);
    assert!(state_with_resolved(&state, "missing", 9).is_none());
}
