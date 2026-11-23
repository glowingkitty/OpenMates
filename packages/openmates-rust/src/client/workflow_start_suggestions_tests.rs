//! Ordering, filtering, dedupe and limit behaviour of the start-screen workflow suggestions.
use super::*;
use crate::client::recommendations::ChatRecommendation;

fn item(
    id: &str,
    kind: RecommendationKind,
    action: RecommendationAction,
    title: &str,
) -> ChatRecommendation {
    ChatRecommendation {
        id: id.into(),
        kind,
        action,
        target_id: None,
        title: title.into(),
        summary: format!("about {title}"),
    }
}

fn wf(title: &str) -> ChatRecommendation {
    item(
        title,
        RecommendationKind::Workflow,
        RecommendationAction::Create,
        title,
    )
}

fn state(updated_at: i64, items: Vec<ChatRecommendation>) -> ChatRecommendationsState {
    ChatRecommendationsState {
        schema_version: 1,
        items,
        dismissed: vec![],
        resolved: vec![],
        updated_at,
    }
}

fn titles(states: Vec<ChatRecommendationsState>, limit: u32) -> Vec<String> {
    workflow_start_suggestions(&WorkflowStartSuggestionsInput { states, limit })
        .into_iter()
        .map(|s| s.title)
        .collect()
}

#[test]
fn orders_newest_chat_first_keeping_item_order() {
    let r = titles(
        vec![
            state(1, vec![wf("Old A")]),
            state(9, vec![wf("New A"), wf("New B")]),
        ],
        5,
    );
    assert_eq!(r, vec!["New A", "New B", "Old A"]);
}

#[test]
fn keeps_only_workflow_create_items() {
    let r = titles(
        vec![state(
            1,
            vec![
                item(
                    "1",
                    RecommendationKind::Memory,
                    RecommendationAction::Create,
                    "Mem",
                ),
                item(
                    "2",
                    RecommendationKind::Workflow,
                    RecommendationAction::Update,
                    "Upd",
                ),
                wf("Keep"),
            ],
        )],
        5,
    );
    assert_eq!(r, vec!["Keep"]);
}

#[test]
fn dedupes_by_normalized_title_newest_wins() {
    let r = titles(
        vec![
            state(1, vec![wf("daily  report!")]),
            state(2, vec![wf("Daily Report")]),
        ],
        5,
    );
    assert_eq!(r, vec!["Daily Report"]);
}

#[test]
fn skips_dismissed_and_resolved_of_own_state() {
    let mut s = state(1, vec![wf("One"), wf("Two"), wf("Three")]);
    s.dismissed = vec!["one".into()];
    s.resolved = vec!["Two".into()];
    assert_eq!(titles(vec![s], 5), vec!["Three"]);
}

#[test]
fn clamps_limit_to_one_through_ten() {
    let many: Vec<_> = (0..15).map(|i| wf(&format!("W{i}"))).collect();
    assert_eq!(titles(vec![state(1, many.clone())], 0).len(), 1);
    assert_eq!(titles(vec![state(1, many)], 99).len(), 10);
}

#[test]
fn skips_states_with_unknown_schema_version() {
    let mut bad = state(9, vec![wf("Bad")]);
    bad.schema_version = 2;
    assert_eq!(
        titles(vec![bad, state(1, vec![wf("Good")])], 5),
        vec!["Good"]
    );
}

#[test]
fn json_wrapper_rejects_malformed_input() {
    assert!(workflow_start_suggestions_json("nope").is_err());
    assert_eq!(
        workflow_start_suggestions_json(r#"{"states":[],"limit":3}"#).unwrap(),
        "[]"
    );
}
