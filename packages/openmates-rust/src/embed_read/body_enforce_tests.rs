//! spec: app-skills.answer.only-result-embeds-in-body
use super::body_enforce::{enforce_block_embeds, BodyEmbedRef, BodyEmbedSlot};

fn r(embed_ref: &str, id: Option<&str>, ty: Option<&str>, kids: Option<&[&str]>) -> BodyEmbedRef {
    BodyEmbedRef {
        embed_ref: embed_ref.into(),
        embed_id: id.map(Into::into),
        type_name: ty.map(Into::into),
        app_id: Some("web".into()),
        skill_id: Some("search".into()),
        child_ids: kids.map(|k| k.iter().map(|s| (*s).to_owned()).collect()),
    }
}

fn card(id: &str) -> BodyEmbedSlot {
    BodyEmbedSlot::Card {
        embed_ref: id.into(),
        embed_id: Some(id.into()),
    }
}

fn activity(id: &str, pending: bool) -> BodyEmbedSlot {
    BodyEmbedSlot::Activity {
        embed_id: id.into(),
        app_id: Some("web".into()),
        skill_id: Some("search".into()),
        results_pending: pending,
    }
}

#[test]
fn invocation_with_known_children_becomes_activity_plus_child_cards() {
    let g = vec![vec![r(
        "embed:p1",
        Some("p1"),
        Some("app-skill-use"),
        Some(&["c1", "c2"]),
    )]];
    assert_eq!(
        enforce_block_embeds(&g, &[]),
        vec![vec![activity("p1", false), card("c1"), card("c2")]]
    );
}

#[test]
fn child_already_shown_in_body_is_not_repeated() {
    let g = vec![vec![
        r(
            "embed:p1",
            Some("p1"),
            Some("app-skill-use"),
            Some(&["c1", "c2"]),
        ),
        r("c1", Some("c1"), Some("web-website"), None),
    ]];
    assert_eq!(
        enforce_block_embeds(&g, &[]),
        vec![vec![
            activity("p1", false),
            card("c2"),
            BodyEmbedSlot::Card {
                embed_ref: "c1".into(),
                embed_id: Some("c1".into())
            },
        ]]
    );
}

#[test]
fn unknown_children_leave_a_pending_activity() {
    let g = vec![vec![r("embed:p1", Some("p1"), Some("app-skill-use"), None)]];
    assert_eq!(
        enforce_block_embeds(&g, &[]),
        vec![vec![activity("p1", true)]]
    );
}

#[test]
fn echo_of_invocation_with_activity_node_is_dropped() {
    let g = vec![vec![r(
        "embed:p1",
        Some("p1"),
        Some("app-skill-use"),
        Some(&[]),
    )]];
    assert_eq!(
        enforce_block_embeds(&g, &["p1".to_owned()]),
        vec![Vec::<BodyEmbedSlot>::new()]
    );
}

#[test]
fn unknown_type_generated_media_slug_stays_hidden() {
    let slug = "embed:generated-media-images-0123456789ab";
    let g = vec![vec![r(slug, None, None, None)]];
    assert_eq!(
        enforce_block_embeds(&g, &[]),
        vec![vec![BodyEmbedSlot::Hidden {
            embed_id: "generated-media-images-0123456789ab".into()
        }]]
    );
}

#[test]
fn visible_cards_pass_through() {
    let g = vec![vec![r("embed:v1", Some("v1"), Some("web-website"), None)]];
    assert_eq!(
        enforce_block_embeds(&g, &[]),
        vec![vec![BodyEmbedSlot::Card {
            embed_ref: "embed:v1".into(),
            embed_id: Some("v1".into())
        }]]
    );
}

#[test]
fn group_count_is_preserved() {
    let g = vec![
        vec![r("embed:p1", Some("p1"), Some("app-skill-use"), Some(&[]))],
        vec![],
        vec![r("embed:v1", Some("v1"), Some("web-website"), None)],
    ];
    let out = enforce_block_embeds(&g, &["p1".to_owned()]);
    assert_eq!(out.len(), 3);
    assert!(out[0].is_empty() && out[1].is_empty());
}
