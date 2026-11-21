//! Presentation write rules: locks, one-time refresh, backfill, dominant category, normalisation.
use super::presentation::*;

fn proposal(description: &str, icon: &str, category: &str) -> PresentationFields {
    PresentationFields {
        description: Some(description.into()),
        icon: Some(icon.into()),
        category: Some(category.into()),
    }
}

fn chat(category: Option<&str>, updated_at: u64) -> PresentationChat {
    PresentationChat {
        category: category.map(str::to_owned),
        updated_at,
    }
}

#[test]
fn manual_lock_survives_spec_approval() {
    let state = PresentationState {
        sources: PresentationSources {
            icon: Some(PresentationSource::User),
            ..Default::default()
        },
        ..Default::default()
    };
    let write = plan_write(
        PresentationOrigin::SpecificationApproval,
        Some(&state),
        &PresentationValues::default(),
        &proposal("Keeps recipes", "chef-hat", "cooking_food"),
        0,
        &[],
    )
    .unwrap();
    assert_eq!(write.fields.icon, None);
    assert_eq!(write.fields.description.as_deref(), Some("Keeps recipes"));
    assert_eq!(write.state.sources.icon, Some(PresentationSource::User));
    assert_eq!(
        write.state.sources.category,
        Some(PresentationSource::Assistant)
    );
}

#[test]
fn spec_refresh_only_once() {
    let current = PresentationValues::default();
    let first = plan_write(
        PresentationOrigin::SpecificationApproval,
        None,
        &current,
        &PresentationFields::default(),
        0,
        &[],
    )
    .unwrap();
    assert!(
        first.state.specification_refreshed,
        "set even when nothing was written"
    );
    let second = plan_write(
        PresentationOrigin::SpecificationApproval,
        Some(&first.state),
        &current,
        &proposal("x", "box", "design"),
        0,
        &[],
    );
    assert_eq!(second, None);
}

#[test]
fn backfill_only_without_state_and_with_items() {
    let current = PresentationValues::default();
    let p = proposal("A shop", "store", "finance");
    assert!(plan_write(PresentationOrigin::Backfill, None, &current, &p, 0, &[]).is_none());
    let state = PresentationState::default();
    assert!(
        plan_write(
            PresentationOrigin::Backfill,
            Some(&state),
            &current,
            &p,
            3,
            &[]
        )
        .is_none()
    );
    let write = plan_write(PresentationOrigin::Backfill, None, &current, &p, 3, &[]).unwrap();
    assert!(write.state.backfilled);
    assert_eq!(write.fields.icon.as_deref(), Some("store"));
    assert_eq!(write.state.sources.icon, Some(PresentationSource::Backfill));
}

#[test]
fn backfill_keeps_a_legacy_non_empty_description() {
    let current = PresentationValues {
        description: "My own words".into(),
        icon: "folder".into(),
        category: String::new(),
    };
    let write = plan_write(
        PresentationOrigin::Backfill,
        None,
        &current,
        &proposal("Model words", "store", "finance"),
        2,
        &[],
    )
    .unwrap();
    assert_eq!(write.fields.description, None);
    assert_eq!(write.fields.icon.as_deref(), Some("store"));
    assert_eq!(
        write.state.sources.description,
        Some(PresentationSource::User)
    );
}

#[test]
fn backfill_category_prefers_the_dominant_chat_category() {
    let chats = [
        chat(Some("design"), 1),
        chat(Some("design"), 2),
        chat(Some("finance"), 3),
    ];
    let write = plan_write(
        PresentationOrigin::Backfill,
        None,
        &PresentationValues::default(),
        &proposal("", "", "science"),
        1,
        &chats,
    )
    .unwrap();
    assert_eq!(write.fields.category.as_deref(), Some("design"));
}

#[test]
fn dominant_category_tie_goes_to_most_recent_chat() {
    let chats = [
        chat(Some("design"), 10),
        chat(Some("finance"), 20),
        chat(Some("design"), 5),
        chat(Some("finance"), 6),
        chat(None, 99),
    ];
    assert_eq!(dominant_category(&chats).as_deref(), Some("finance"));
    assert_eq!(dominant_category(&[chat(None, 1)]), None);
}

#[test]
fn dominant_category_ignores_categories_projects_cannot_use() {
    let chats = [
        chat(Some("openmates_official"), 30),
        chat(Some("openmates_official"), 20),
        chat(Some("cooking_food"), 10),
    ];
    assert_eq!(dominant_category(&chats).as_deref(), Some("cooking_food"));
}

#[test]
fn creation_writes_every_field_and_marks_state() {
    let write = plan_write(
        PresentationOrigin::Creation,
        None,
        &PresentationValues::default(),
        &proposal("Tracks recipes", "chef-hat", "cooking_food"),
        0,
        &[],
    )
    .unwrap();
    assert_eq!(write.fields.category.as_deref(), Some("cooking_food"));
    assert!(write.state.backfilled && !write.state.specification_refreshed);
    assert_eq!(
        write.state.sources.description,
        Some(PresentationSource::Assistant)
    );
}

#[test]
fn user_origin_writes_an_empty_description_and_locks_it() {
    let write = plan_write(
        PresentationOrigin::User,
        None,
        &PresentationValues::default(),
        &PresentationFields {
            description: Some(String::new()),
            ..Default::default()
        },
        0,
        &[],
    )
    .unwrap();
    assert_eq!(write.fields.description.as_deref(), Some(""));
    assert_eq!(
        write.state.sources.description,
        Some(PresentationSource::User)
    );
    assert!(
        plan_write(
            PresentationOrigin::User,
            None,
            &PresentationValues::default(),
            &PresentationFields::default(),
            0,
            &[]
        )
        .is_none()
    );
}

#[test]
fn normalisation_cuts_collapses_and_validates() {
    assert_eq!(
        normalize_description("  one\n two   three "),
        "one two three"
    );
    let long = "word ".repeat(40);
    let cut = normalize_description(&long);
    assert!(
        cut.chars().count() <= 140 && cut.ends_with("word…"),
        "{cut}"
    );
    let solid = "x".repeat(200);
    assert_eq!(normalize_description(&solid).chars().count(), 140);
    assert_eq!(normalize_icon(" Chef-Hat ").as_deref(), Some("chef-hat"));
    assert_eq!(normalize_icon("bad icon"), None);
    assert_eq!(normalize_icon("-x"), None);
    assert_eq!(normalize_icon(&"a".repeat(41)), None);
    assert_eq!(normalize_category("Finance").as_deref(), Some("finance"));
    assert_eq!(normalize_category("cooking"), None);
}
