//! Catalog identity of a replayed sealed root embed (web `catalogContextFromSealedEmbed`).
use super::*;

fn sealed(content: &str, extra: Value) -> Value {
    let mut c = json!({"content": content, "type": "focus_mode_activation"});
    for (key, value) in extra.as_object().expect("object fixture") {
        c[key] = value.clone();
    }
    c
}

#[test]
fn focus_activation_naming_only_its_app_is_stored_without_catalog_identity() {
    // The jobs focus activation embed of a focused turn: no skill produced it.
    let c = sealed(
        "app_id: jobs\nfocus_id: jobs-write_application\nstatus: finished",
        json!({}),
    );
    let mut payload = json!({"embed_id": "embed"});
    store_catalog_identity(&mut payload, &c).unwrap();
    assert!(payload.get("app_id").is_none() && payload.get("skill_id").is_none());
}

#[test]
fn skill_embed_takes_app_and_skill_from_its_content() {
    let c = sealed(
        "app_id: docs\nskill_id: create_document\ntitle: Letter",
        json!({}),
    );
    let mut payload = json!({});
    store_catalog_identity(&mut payload, &c).unwrap();
    assert_eq!(payload["app_id"], "docs");
    assert_eq!(payload["skill_id"], "create_document");
}

#[test]
fn producer_ids_win_over_content_and_null_counts_as_absent() {
    let c = sealed(
        "app_id: other\nskill_id: other_skill",
        json!({"app_id": "web", "skill_id": null}),
    );
    let mut payload = json!({});
    store_catalog_identity(&mut payload, &c).unwrap();
    assert_eq!(payload["app_id"], "web");
    assert_eq!(payload["skill_id"], "other_skill");
}

#[test]
fn refuses_producer_app_without_skill_and_malformed_ids() {
    let half = sealed("title: x", json!({"app_id": "jobs"}));
    assert_eq!(
        store_catalog_identity(&mut json!({}), &half),
        Err(Error::Protocol)
    );
    let bad = sealed("app_id: Jobs\nskill_id: search", json!({}));
    assert_eq!(
        store_catalog_identity(&mut json!({}), &bad),
        Err(Error::Protocol)
    );
}

#[test]
fn embed_without_any_catalog_field_is_stored_without_identity() {
    let c = sealed("title: Plain result", json!({}));
    let mut payload = json!({});
    store_catalog_identity(&mut payload, &c).unwrap();
    assert!(payload.get("app_id").is_none());
}
