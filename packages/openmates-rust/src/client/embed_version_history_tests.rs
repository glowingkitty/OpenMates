//! Version-history pages of `GET /v1/embeds/{id}/versions`: provenance, timestamps, cursor and fail-closed shapes.
use super::*;
use serde_json::json;

const EMBED: &str = "embed-history-1";

fn page(versions: Value, current: i64, next: Value) -> Value {
    json!({"embed_id": EMBED, "current_version": current, "versions": versions,
        "next_cursor": next, "readonly": false})
}

#[test]
fn reads_origin_action_and_created_at_of_each_version() {
    let parsed = parse_version_history_page(
        EMBED,
        &page(
            json!([
                {"version_number": 1, "created_at": 1_700_000_000, "revision_origin": "assistant"},
                {"version_number": 2, "created_at": 1_704_067_200_000_i64,
                    "revision_origin": "user", "revision_action": "enhance"},
                {"version_number": 3, "created_at": null, "revision_origin": null}
            ]),
            3,
            Value::Null,
        ),
    )
    .expect("page");
    assert_eq!(parsed.current_version, 3);
    assert_eq!(parsed.next_cursor, None);
    assert_eq!(parsed.entries.len(), 3);
    assert_eq!(parsed.entries[0].origin, RevisionOrigin::Assistant);
    assert_eq!(parsed.entries[0].created_at, Some(1_700_000_000));
    assert_eq!(parsed.entries[1].origin, RevisionOrigin::User);
    assert_eq!(parsed.entries[1].action, Some(EmbedUpdateAction::Enhance));
    assert_eq!(parsed.entries[1].created_at, Some(1_704_067_200));
    assert_eq!(parsed.entries[2].origin, RevisionOrigin::Assistant);
    assert_eq!(parsed.entries[2].created_at, None);
}

#[test]
fn a_cursor_continues_after_the_last_listed_version() {
    let parsed = parse_version_history_page(
        EMBED,
        &page(
            json!([{"version_number": 1}, {"version_number": 2}]),
            5,
            json!(2),
        ),
    )
    .expect("page");
    assert_eq!(parsed.next_cursor, Some(2));
}

#[test]
fn refuses_pages_that_do_not_match_the_embed_or_its_order() {
    let other = json!({"embed_id": "other", "current_version": 1, "versions": []});
    let descending = page(
        json!([{"version_number": 2}, {"version_number": 1}]),
        2,
        Value::Null,
    );
    let above_head = page(json!([{"version_number": 4}]), 3, Value::Null);
    let stale_cursor = page(
        json!([{"version_number": 1}, {"version_number": 2}]),
        4,
        json!(1),
    );
    let unknown_origin = page(
        json!([{"version_number": 1, "revision_origin": "robot"}]),
        1,
        Value::Null,
    );
    let no_head = json!({"embed_id": EMBED, "versions": []});
    for bad in [
        other,
        descending,
        above_head,
        stale_cursor,
        unknown_origin,
        no_head,
    ] {
        assert!(
            matches!(
                parse_version_history_page(EMBED, &bad),
                Err(Error::Protocol)
            ),
            "{bad}"
        );
    }
}

#[test]
fn scope_query_names_the_chat_or_project_and_team() {
    assert_eq!(scope_query(None), "");
    let chat = RevisionScope::Chat {
        chat_id: "chat-1".into(),
        team_id: None,
    };
    assert_eq!(scope_query(Some(&chat)), "&chat_id=chat-1");
    let project = RevisionScope::Project {
        project_id: "project-1".into(),
        team_id: Some("team-1".into()),
    };
    assert_eq!(
        scope_query(Some(&project)),
        "&project_id=project-1&team_id=team-1"
    );
}
