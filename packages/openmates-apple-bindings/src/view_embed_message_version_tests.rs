//! Message-scoped embed version binding: pins, user versions, bad input.
use super::*;

fn msg(id: &str, parents: &[&str]) -> MessageParentsRecord {
    MessageParentsRecord {
        message_id: id.into(),
        parent_contents: parents.iter().map(|s| (*s).to_owned()).collect(),
    }
}

// TOON like the deployed `app_skill_use` parents.
const PIN2: &str =
    "app_id: images\nskill_id: generate\npinned_embeds[1]{embed_id,version}:\n  img,2";

#[test]
fn messages_follow_the_latest_pin() {
    let out = embed_versions_by_message(
        vec![msg("a", &[]), msg("b", &[PIN2]), msg("c", &[])],
        "img".into(),
        None,
    )
    .unwrap();
    let shown: Vec<(i64, bool)> = out.iter().map(|v| (v.version, v.pinned_here)).collect();
    assert_eq!(shown, vec![(1, false), (2, true), (2, false)]);
}

#[test]
fn user_versions_after_the_pin_are_followed() {
    let page = r#"{"versions":[{"version_number":1},{"version_number":2},{"version_number":3,"revision_origin":"user","revision_action":"enhance"}]}"#;
    let out = embed_versions_by_message(vec![msg("b", &[PIN2])], "img".into(), Some(page.into()))
        .unwrap();
    assert_eq!(out[0].version, 3);
}

#[test]
fn malformed_input_is_an_error() {
    assert!(
        embed_versions_by_message(vec![msg("a", &["not an object"])], "img".into(), None).is_err()
    );
    assert!(embed_versions_by_message(vec![], "img".into(), Some("{".into())).is_err());
}
