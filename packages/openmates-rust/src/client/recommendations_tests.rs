//! Unit tests of the Recommendations reconcile rules and the context_entry event codec.
use super::*;

fn rec(
    id: &str,
    kind: RecommendationKind,
    action: RecommendationAction,
    target: Option<&str>,
    title: &str,
) -> ChatRecommendation {
    ChatRecommendation {
        id: id.into(),
        kind,
        action,
        target_id: target.map(str::to_owned),
        title: title.into(),
        summary: "s".into(),
    }
}
fn mem(id: &str, title: &str, when: &str) -> LocalMemoryMetadata {
    LocalMemoryMetadata {
        id: id.into(),
        title: title.into(),
        when_to_use: when.into(),
    }
}
fn create_memory(id: &str, title: &str) -> ChatRecommendation {
    rec(
        id,
        RecommendationKind::Memory,
        RecommendationAction::Create,
        None,
        title,
    )
}
fn input(incoming: Vec<ChatRecommendation>) -> ReconcileRecommendationsInput {
    ReconcileRecommendationsInput {
        incoming,
        dismissed: vec![],
        resolved: vec![],
        local_memories: vec![],
    }
}

#[test]
fn normalizes_case_punctuation_and_whitespace() {
    assert_eq!(
        normalize_title("  Prefer: Rust, ASAP!! "),
        "prefer rust asap"
    );
    assert_eq!(normalize_title("Café--Time"), "café time");
    assert_eq!(normalize_title("ÜBER Konferenzen"), "über konferenzen");
    assert_eq!(normalize_title("***"), "");
}

#[test]
fn drops_dismissed_and_resolved_titles_after_normalizing() {
    let mut i = input(vec![
        create_memory("1", "Prefer Rust!"),
        create_memory("2", "Use tabs"),
        create_memory("3", "Keep me"),
    ]);
    i.dismissed = vec!["prefer rust".into()];
    i.resolved = vec!["USE   TABS".into()];
    let out = reconcile_recommendations(&i).unwrap();
    assert_eq!(out.iter().map(|r| r.id.as_str()).collect::<Vec<_>>(), ["3"]);
}

#[test]
fn drops_in_list_duplicates_per_kind_but_keeps_cross_kind_titles() {
    let out = reconcile_recommendations(&input(vec![
        create_memory("1", "Weekly review"),
        create_memory("2", "weekly  review!"),
        rec(
            "3",
            RecommendationKind::Workflow,
            RecommendationAction::Create,
            None,
            "Weekly review",
        ),
    ]))
    .unwrap();
    assert_eq!(
        out.iter().map(|r| r.id.as_str()).collect::<Vec<_>>(),
        ["1", "3"]
    );
}

#[test]
fn drops_second_update_of_the_same_target() {
    let out = reconcile_recommendations(&input(vec![
        rec(
            "1",
            RecommendationKind::Workflow,
            RecommendationAction::Update,
            Some("w1"),
            "Digest",
        ),
        rec(
            "2",
            RecommendationKind::Workflow,
            RecommendationAction::Update,
            Some("w1"),
            "Digest v2",
        ),
    ]))
    .unwrap();
    assert_eq!(out.len(), 1);
    assert_eq!(out[0].id, "1");
}

#[test]
fn equal_title_turns_create_into_update_and_keeps_local_title() {
    let mut i = input(vec![create_memory("1", "dark mode preference")]);
    i.local_memories = vec![mem("m9", "Dark Mode Preference", "")];
    let out = reconcile_recommendations(&i).unwrap();
    assert_eq!(out[0].action, RecommendationAction::Update);
    assert_eq!(out[0].target_id.as_deref(), Some("m9"));
    assert_eq!(out[0].title, "Dark Mode Preference");
}

#[test]
fn title_token_jaccard_at_threshold_matches_and_below_does_not() {
    // {a,b,c} vs {a,b,c,d,e}: 3/5 = 0.6 matches.
    let mut i = input(vec![create_memory("1", "alpha beta gamma")]);
    i.local_memories = vec![mem("m1", "alpha beta gamma delta epsilon", "")];
    assert_eq!(
        reconcile_recommendations(&i).unwrap()[0].action,
        RecommendationAction::Update
    );
    // 3/6 = 0.5 does not.
    i.local_memories = vec![mem("m1", "alpha beta gamma delta epsilon zeta", "")];
    let out = reconcile_recommendations(&i).unwrap();
    assert_eq!(out[0].action, RecommendationAction::Create);
    assert_eq!(out[0].title, "alpha beta gamma");
}

#[test]
fn title_versus_when_to_use_matches_mention_only_memories() {
    let mut i = input(vec![create_memory("1", "Reply in German")]);
    i.local_memories = vec![mem("m2", "Language rule", "reply in german")];
    let out = reconcile_recommendations(&i).unwrap();
    assert_eq!(
        (
            out[0].action,
            out[0].target_id.as_deref(),
            out[0].title.as_str()
        ),
        (RecommendationAction::Update, Some("m2"), "Language rule")
    );
}

#[test]
fn converted_title_that_was_dismissed_is_dropped() {
    let mut i = input(vec![create_memory("1", "reply in german")]);
    i.local_memories = vec![mem("m2", "Language rule", "reply in german")];
    i.dismissed = vec!["language rule".into()];
    assert!(reconcile_recommendations(&i).unwrap().is_empty());
}

#[test]
fn workflow_create_is_never_matched_against_memories() {
    let mut i = input(vec![rec(
        "1",
        RecommendationKind::Workflow,
        RecommendationAction::Create,
        None,
        "Dark mode",
    )]);
    i.local_memories = vec![mem("m1", "Dark mode", "")];
    assert_eq!(
        reconcile_recommendations(&i).unwrap()[0].action,
        RecommendationAction::Create
    );
}

#[test]
fn caps_three_per_kind_in_stable_order() {
    let mut rows = Vec::new();
    for n in 0..5 {
        rows.push(create_memory(
            &format!("m{n}"),
            &format!("memory topic {n} unique{n}"),
        ));
        rows.push(rec(
            &format!("w{n}"),
            RecommendationKind::Workflow,
            RecommendationAction::Create,
            None,
            &format!("flow {n} x{n}"),
        ));
    }
    let ids: Vec<String> = reconcile_recommendations(&input(rows))
        .unwrap()
        .into_iter()
        .map(|r| r.id)
        .collect();
    assert_eq!(ids, ["m0", "w0", "m1", "w1", "m2", "w2"]);
}

#[test]
fn oversized_input_is_a_protocol_error() {
    let mut i = input(vec![]);
    i.dismissed = vec![String::new(); MAX_LIST + 1];
    assert!(matches!(
        reconcile_recommendations(&i),
        Err(Error::Protocol)
    ));
}

#[test]
fn reconcile_json_round_trips_and_rejects_malformed_json() {
    let json = serde_json::json!({"incoming":[{"id":"1","kind":"memory","action":"create","target_id":null,"title":"T","summary":"S"}],
        "dismissed":[],"resolved":[],"local_memories":[]});
    let out: Vec<ChatRecommendation> =
        serde_json::from_str(&reconcile_recommendations_json(&json.to_string()).unwrap()).unwrap();
    assert_eq!(out.len(), 1);
    assert!(reconcile_recommendations_json("{").is_err());
}

fn event() -> ContextEntryHistoryEvent {
    ContextEntryHistoryEvent {
        schema_version: 1,
        event_type: CONTEXT_ENTRY_TYPE.into(),
        kind: RecommendationKind::Memory,
        action: ContextEntryAction::Created,
        entry_id: "e1".into(),
        title: "Dark mode".into(),
        created_at: 1_700_000_000,
        source: None,
        undo: None,
    }
}

#[test]
fn context_entry_event_round_trips_with_the_wire_field_order() {
    let text = build_context_entry_event(&event()).unwrap();
    assert_eq!(
        text,
        r#"{"schema_version":1,"type":"context_entry","kind":"memory","action":"created","entry_id":"e1","title":"Dark mode","created_at":1700000000}"#
    );
    assert_eq!(parse_context_entry_event(&text), Some(event()));
    assert_eq!(parse_context_entry_event_json(&text), text);
}

#[test]
fn invalid_events_are_refused_on_build_and_null_on_parse() {
    for broken in [
        ContextEntryHistoryEvent {
            schema_version: 2,
            ..event()
        },
        ContextEntryHistoryEvent {
            event_type: "voice_call".into(),
            ..event()
        },
        ContextEntryHistoryEvent {
            entry_id: " ".into(),
            ..event()
        },
        ContextEntryHistoryEvent {
            title: String::new(),
            ..event()
        },
        ContextEntryHistoryEvent {
            created_at: -1,
            ..event()
        },
    ] {
        assert!(matches!(
            build_context_entry_event(&broken),
            Err(Error::Protocol)
        ));
        let text = serde_json::to_string(&broken).unwrap();
        assert_eq!(parse_context_entry_event(&text), None);
        assert_eq!(parse_context_entry_event_json(&text), "null");
    }
    assert_eq!(parse_context_entry_event("plain text"), None);
    assert_eq!(parse_context_entry_event(r#"{"type":"voice_call"}"#), None);
}

#[test]
fn payload_filter_keeps_only_well_formed_rows_and_caps_six() {
    let good = serde_json::json!({"id":"1","kind":"workflow","action":"update","target_id":"w1","title":"T","summary":"S"});
    let mut rows = vec![serde_json::json!({"id":"x"}), serde_json::json!("str")];
    rows.extend(std::iter::repeat(good).take(9));
    assert_eq!(recommendations_from_payload(&rows).len(), 6);
}

#[test]
fn chinese_titles_dedupe_and_dismiss_independently() {
    let mut i = input(vec![
        create_memory("1", "开源会议"),
        create_memory("2", "欧洲开源会议"),
        create_memory("3", "开源会议!"),
    ]);
    let ids = |i: &ReconcileRecommendationsInput| {
        reconcile_recommendations(i)
            .unwrap()
            .into_iter()
            .map(|r| r.id)
            .collect::<Vec<_>>()
    };
    assert_eq!(ids(&i), ["1", "2"]);
    i.dismissed = vec!["开源会议".into()];
    assert_eq!(ids(&i), ["2"]);
}

#[test]
fn german_titles_match_case_insensitively_and_stay_distinct() {
    let mut i = input(vec![
        create_memory("1", "Über Konferenzen"),
        create_memory("2", "ÜBER konferenzen"),
        create_memory("3", "Uber Konferenzen"),
    ]);
    let ids = |i: &ReconcileRecommendationsInput| {
        reconcile_recommendations(i)
            .unwrap()
            .into_iter()
            .map(|r| r.id)
            .collect::<Vec<_>>()
    };
    assert_eq!(ids(&i), ["1", "3"]);
    i.resolved = vec!["über konferenzen".into()];
    assert_eq!(ids(&i), ["3"]);
}

#[test]
fn non_latin_create_matches_local_memory_by_equal_title() {
    let mut i = input(vec![create_memory("1", "开源会议")]);
    i.local_memories = vec![mem("m2", "欧洲开源会议", ""), mem("m1", "开源会议", "")];
    let out = reconcile_recommendations(&i).unwrap();
    assert_eq!(
        (out[0].action, out[0].target_id.as_deref()),
        (RecommendationAction::Update, Some("m1"))
    );
}

#[test]
fn empty_normalized_titles_never_match_anything() {
    let mut i = input(vec![
        create_memory("1", "!!!"),
        create_memory("2", "???"),
        create_memory("3", ""),
    ]);
    i.dismissed = vec!["***".into(), String::new()];
    i.resolved = vec!["...".into()];
    i.local_memories = vec![mem("m1", "!!!", "???"), mem("m2", "", "")];
    let out = reconcile_recommendations(&i).unwrap();
    assert_eq!(
        out.iter().map(|r| r.id.as_str()).collect::<Vec<_>>(),
        ["1", "2", "3"]
    );
    assert!(
        out.iter()
            .all(|r| r.action == RecommendationAction::Create && r.target_id.is_none())
    );
}
