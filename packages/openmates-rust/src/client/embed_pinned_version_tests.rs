//! Which version each message shows when user-made versions follow assistant pins, and the versions-list provenance parser.
use super::*;
use serde_json::json;

const IMAGE: &str = "image-1";

fn message(id: &str, pin: Option<i64>) -> MessageParents {
    // TOON like the deployed `app_skill_use` parents.
    let parent_contents = pin
        .map(|version| {
            vec![format!(
                "app_id: images\nskill_id: generate\npinned_embeds[1]{{embed_id,version}}:\n  {IMAGE},{version}"
            )]
        })
        .unwrap_or_default();
    MessageParents {
        message_id: id.into(),
        parent_contents,
    }
}

fn versions(rows: &[(i64, &str, Option<&str>)]) -> Vec<VersionProvenance> {
    let page = json!({"versions": rows.iter().map(|(version, origin, action)| json!({
        "version_number": version, "revision_origin": origin, "revision_action": action,
        "has_snapshot": true, "archive_state": "hot",
    })).collect::<Vec<_>>()});
    parse_version_provenance(&page).expect("page")
}

fn shown(messages: &[MessageParents], provenance: &[VersionProvenance]) -> Vec<i64> {
    versions_by_message_with_provenance(messages, IMAGE, provenance)
        .expect("versions")
        .into_iter()
        .map(|row| row.version)
        .collect()
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.display.latest-follows-user-versions
#[test]
fn only_assistant_versions_keep_the_pinned_behaviour() {
    let messages = [
        message("a", None),
        message("b", Some(2)),
        message("c", None),
    ];
    let provenance = versions(&[(1, "assistant", None), (2, "assistant", None)]);
    assert_eq!(shown(&messages, &provenance), vec![1, 2, 2]);
    assert_eq!(
        versions_by_message(&messages, IMAGE).expect("plain"),
        versions_by_message_with_provenance(&messages, IMAGE, &provenance).expect("same")
    );
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.display.latest-follows-user-versions
#[test]
fn user_versions_after_the_last_assistant_version_are_followed() {
    let messages = [
        message("a", None),
        message("b", Some(2)),
        message("c", None),
    ];
    let provenance = versions(&[
        (1, "assistant", None),
        (2, "assistant", None),
        (3, "user", Some("edit")),
        (4, "user", Some("enhance")),
    ]);
    // The creating message keeps v1: v2 is the assistant's next version.
    assert_eq!(shown(&messages, &provenance), vec![1, 4, 4]);
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.display.latest-follows-user-versions
#[test]
fn user_versions_between_two_assistant_versions_stay_with_the_earlier_messages() {
    let messages = [
        message("a", None),
        message("b", Some(3)),
        message("c", None),
        message("d", Some(5)),
    ];
    let provenance = versions(&[
        (1, "assistant", None),
        (2, "user", Some("crop")),
        (3, "assistant", None),
        (4, "user", Some("enhance")),
        (5, "assistant", None),
        (6, "user", Some("edit")),
    ]);
    assert_eq!(shown(&messages, &provenance), vec![2, 4, 4, 6]);
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.display.latest-follows-user-versions,embed-user-edits.restore.creates-version
#[test]
fn a_restore_is_a_user_version_and_is_followed() {
    let messages = [message("a", None), message("b", Some(2))];
    let provenance = versions(&[
        (1, "assistant", None),
        (2, "assistant", None),
        (3, "user", Some("restore")),
    ]);
    assert_eq!(shown(&messages, &provenance), vec![1, 3]);
    assert_eq!(provenance[2].action, Some(EmbedUpdateAction::Restore));
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.display.latest-follows-user-versions
#[test]
fn an_unlisted_version_ends_the_followed_run() {
    let messages = [message("a", None)];
    let provenance = versions(&[
        (1, "assistant", None),
        (2, "user", Some("edit")),
        (4, "user", Some("edit")),
    ]);
    assert_eq!(shown(&messages, &provenance), vec![2]);
}

// contract-test: supporting surface=sdks.rust assertions=embed-user-edits.display.latest-follows-user-versions
#[test]
fn parses_null_origin_as_assistant_and_refuses_unknown_values() {
    let page = json!({"versions": [
        {"version_number": 1, "revision_origin": null, "revision_action": null},
        {"version_number": 2},
    ]});
    let rows = parse_version_provenance(&page).expect("page");
    assert!(
        rows.iter()
            .all(|row| row.origin == RevisionOrigin::Assistant && row.action.is_none())
    );
    for bad in [
        json!({"versions": [{"version_number": 1, "revision_origin": "robot"}]}),
        json!({"versions": [{"version_number": 1, "revision_action": "paint"}]}),
        json!({"versions": [{"version_number": 0}]}),
        json!({"versions": [{"version_number": 1}, {"version_number": 1}]}),
        json!({"items": []}),
    ] {
        assert!(
            matches!(parse_version_provenance(&bad), Err(Error::Protocol)),
            "{bad}"
        );
    }
}
