//! A turn persists only finished streamed embeds; processing placeholders and
//! their descendants are left to the sealed recovery replay.

use super::{drop_other_turns, drop_unfinished};
use serde_json::{Value, json};
use std::collections::BTreeMap;

fn rows(items: &[(&str, Value)]) -> BTreeMap<String, Value> {
    items
        .iter()
        .map(|(id, row)| ((*id).to_owned(), row.clone()))
        .collect()
}

// contract-test: supporting surface=sdks.rust assertions=chats.surface.semantic-parity
#[test]
fn processing_placeholder_is_never_persisted_as_finished() {
    let mut turn = rows(&[
        (
            "doc",
            json!({"status": "processing", "content": "type: document\nstatus: processing"}),
        ),
        (
            "search",
            json!({"status": "finished", "content": "type: app_skill_use"}),
        ),
    ]);
    drop_unfinished(&mut turn);
    assert_eq!(turn.keys().collect::<Vec<_>>(), ["search"]);
}

#[test]
fn finished_frame_that_replaced_its_placeholder_is_kept() {
    // `capture_artifact` keeps the latest frame per embed; once the finished
    // frame arrived, the row is persisted as before.
    let mut turn = rows(&[(
        "doc",
        json!({"status": "finished", "content": "type: document"}),
    )]);
    drop_unfinished(&mut turn);
    assert!(turn.contains_key("doc"));
}

#[test]
fn children_of_a_processing_parent_wait_for_recovery_too() {
    let mut turn = rows(&[
        ("parent", json!({"status": "processing"})),
        (
            "child",
            json!({"status": "finished", "parent_embed_id": "parent"}),
        ),
        (
            "grandchild",
            json!({"status": "finished", "parent_embed_id": "child"}),
        ),
        ("other", json!({"status": "finished"})),
    ]);
    drop_unfinished(&mut turn);
    assert_eq!(turn.keys().collect::<Vec<_>>(), ["other"]);
}

#[test]
fn child_of_an_unstreamed_parent_keeps_its_existing_handling() {
    let mut turn = rows(&[(
        "child",
        json!({"status": "finished", "parent_embed_id": "elsewhere"}),
    )]);
    drop_unfinished(&mut turn);
    assert!(turn.contains_key("child"));
}

#[test]
fn rows_without_status_are_kept() {
    let mut turn = rows(&[("legacy", json!({"content": "type: code"}))]);
    drop_unfinished(&mut turn);
    assert!(turn.contains_key("legacy"));
}

// contract-test: supporting surface=sdks.rust assertions=chats.surface.semantic-parity
#[test]
fn a_late_row_of_another_turn_is_left_out_with_its_children() {
    let mut turn = rows(&[
        ("mine", json!({"message_id": "assistant", "task_id": ""})),
        ("tasked", json!({"message_id": "human", "task_id": "task"})),
        (
            "late",
            json!({"message_id": "earlier-human", "task_id": ""}),
        ),
        (
            "late-child",
            json!({"message_id": "earlier-human", "task_id": "", "parent_embed_id": "late"}),
        ),
        (
            "other-task",
            json!({"message_id": "earlier-human", "task_id": "other"}),
        ),
        ("unowned", json!({"task_id": ""})),
    ]);
    drop_other_turns(&mut turn, "assistant");
    // A row naming a task, or naming no message, stays for persistence to judge.
    assert_eq!(
        turn.keys().collect::<Vec<_>>(),
        ["mine", "other-task", "tasked", "unowned"]
    );
}
