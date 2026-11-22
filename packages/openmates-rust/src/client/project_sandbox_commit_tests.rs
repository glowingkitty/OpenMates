//! Parsing of sandbox commit events and the change card they become.
use super::*;

fn event(kind: &str) -> Value {
    json!({"embed_id": "e1", "current_revision": 2, "operation_id": "op-1", "chat_id": "c1",
           "project_id": "p1", "kind": kind, "source": "project_sandbox"})
}

#[test]
fn creates_and_updates_become_applied_change_cards() {
    let raw = event("create");
    let parsed = parse_event(&raw).expect("a sandbox create is shown");
    let card = change_card(&parsed, "web-app/package.json", "{}");
    assert_eq!(
        card,
        json!({"projectId": "p1", "chatId": "c1", "mutation": {
        "operation": "create_file", "operation_id": "op-1:e1", "path": "web-app/package.json",
        "expected_base": null, "content": "{}"}})
    );
    let raw = event("update");
    assert_eq!(parse_event(&raw).expect("update").operation, "update_file");
}

#[test]
fn ignores_other_sources_link_moves_and_missing_ids() {
    assert!(parse_event(&event("delete")).is_none());
    assert!(parse_event(&event("move")).is_none());
    let mut device = event("update");
    device["source"] = json!("device");
    assert!(parse_event(&device).is_none());
    let mut old = event("update");
    old.as_object_mut().expect("object").remove("project_id");
    assert!(parse_event(&old).is_none());
}
