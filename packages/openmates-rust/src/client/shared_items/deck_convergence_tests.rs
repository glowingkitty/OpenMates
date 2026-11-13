//! Two deck replicas apply concurrent typed operations, exchange Yjs v1 update bytes and converge.

use super::deck::DeckDocument;
use super::deck_markup::ElementContent;
use super::deck_markup_tests::FULL_DECK;
use super::deck_operations::{DeckOperation, TextStyle};

/// A hydrates the deck; B starts empty and receives A's full state.
fn pair() -> (DeckDocument, DeckDocument) {
    let a = DeckDocument::from_markup(FULL_DECK, 1).expect("hydrates");
    let b = DeckDocument::from_update(&a.encode_state(), 2).expect("valid state");
    (a, b)
}

/// Exchanges everything each side lacks, in both directions, delivering twice.
fn sync(a: &mut DeckDocument, b: &mut DeckDocument) {
    let to_b = a
        .encode_update_since(&b.state_vector())
        .expect("valid vector");
    let to_a = b
        .encode_update_since(&a.state_vector())
        .expect("valid vector");
    for _ in 0..2 {
        b.apply_update(&to_b).expect("applies");
        a.apply_update(&to_a).expect("applies");
    }
}

fn apply(deck: &mut DeckDocument, op: DeckOperation) {
    deck.apply(op).expect("operation applies");
}

// contract-test: supporting surface=sdks.rust assertions=live-collab.sync.concurrent-convergence,live-collab.core.one-shared-model
#[test]
fn replica_built_from_a_peer_state_saves_the_same_markup() {
    let (a, b) = pair();
    assert_eq!(b.to_markup().expect("synced"), FULL_DECK);
    assert_eq!(a.state_vector(), b.state_vector());
    assert!(
        DeckDocument::empty(3).to_markup().is_err(),
        "an unsynced replica has no deck"
    );
}

// contract-test: supporting surface=sdks.rust assertions=live-collab.sync.concurrent-convergence
#[test]
fn concurrent_operations_on_different_elements_both_survive() {
    let (mut a, mut b) = pair();
    apply(
        &mut a,
        DeckOperation::SetGeometry {
            slide_id: "s1".into(),
            element_id: "e2".into(),
            x: 10,
            y: 20,
            w: 30,
            h: 40,
        },
    );
    apply(
        &mut b,
        DeckOperation::SetTextContent {
            slide_id: "s1".into(),
            element_id: "e1".into(),
            markup: "From <i>B</i>".into(),
        },
    );
    apply(
        &mut b,
        DeckOperation::SetSpeakerNotes {
            slide_id: "s2".into(),
            notes: "B's notes".into(),
        },
    );
    sync(&mut a, &mut b);
    let markup = a.to_markup().expect("saves");
    assert_eq!(markup, b.to_markup().expect("saves"));
    assert!(
        markup.contains(r#"<image id="e2" x="10" y="20" w="30" h="40""#),
        "{markup}"
    );
    assert!(markup.contains(">From <i>B</i></text>"), "{markup}");
    assert!(markup.contains("<notes>B's notes</notes>"), "{markup}");
    assert_eq!(a.state_vector(), b.state_vector());
}

// contract-test: supporting surface=sdks.rust assertions=live-collab.sync.concurrent-convergence
#[test]
fn concurrent_writes_to_the_same_property_converge_on_one_value() {
    let (mut a, mut b) = pair();
    let style = |color: &str| DeckOperation::SetTextStyle {
        slide_id: "s1".into(),
        element_id: "e1".into(),
        style: TextStyle {
            color: Some(color.into()),
            ..TextStyle::default()
        },
    };
    apply(&mut a, style("#111111"));
    apply(&mut b, style("#222222"));
    // Same text box replaced on both sides: one content wins, never a concatenation.
    for (deck, text) in [(&mut a, "alpha"), (&mut b, "beta")] {
        apply(
            deck,
            DeckOperation::SetTextContent {
                slide_id: "s1".into(),
                element_id: "e1".into(),
                markup: text.into(),
            },
        );
    }
    sync(&mut a, &mut b);
    let (model_a, model_b) = (a.model(), b.model());
    assert_eq!(model_a, model_b);
    let text = &model_a.slides[0].elements[0];
    let color = text.attributes.get("color").map(String::as_str);
    assert!(
        matches!(color, Some("#111111") | Some("#222222")),
        "{color:?}"
    );
    assert!(
        matches!(&text.content, ElementContent::RichText(t) if t == "alpha" || t == "beta"),
        "{:?}",
        text.content
    );
}

// contract-test: supporting surface=sdks.rust assertions=live-collab.sync.concurrent-convergence
#[test]
fn concurrent_slide_moves_and_a_concurrent_delete_resolve_the_same_order_everywhere() {
    let (mut a, mut b) = pair();
    apply(
        &mut a,
        DeckOperation::AddSlide {
            index: None,
            layout: None,
        },
    );
    sync(&mut a, &mut b);
    // Both move s3 to the front; A also deletes s2 while B moves it.
    for deck in [&mut a, &mut b] {
        apply(
            deck,
            DeckOperation::MoveSlide {
                slide_id: "s3".into(),
                to_index: 0,
            },
        );
    }
    apply(
        &mut a,
        DeckOperation::DeleteSlide {
            slide_id: "s2".into(),
        },
    );
    apply(
        &mut b,
        DeckOperation::MoveSlide {
            slide_id: "s2".into(),
            to_index: 1,
        },
    );
    sync(&mut a, &mut b);
    let order = |deck: &DeckDocument| -> Vec<String> {
        deck.model().slides.into_iter().map(|s| s.id).collect()
    };
    assert_eq!(order(&a), order(&b));
    assert_eq!(order(&a), ["s3", "s1"]);
    // The converged deck still saves as normalised markup.
    DeckDocument::from_markup(&a.to_markup().expect("saves"), 5).expect("normalised");
}

#[test]
fn undo_reverts_only_local_operations_and_reaches_the_peer() {
    let (mut a, mut b) = pair();
    apply(
        &mut b,
        DeckOperation::SetSpeakerNotes {
            slide_id: "s2".into(),
            notes: "kept".into(),
        },
    );
    apply(
        &mut a,
        DeckOperation::SetSpeakerNotes {
            slide_id: "s1".into(),
            notes: "undone".into(),
        },
    );
    sync(&mut a, &mut b);
    assert!(a.undo());
    assert!(!a.can_undo(), "B's change is not on A's undo stack");
    sync(&mut a, &mut b);
    for deck in [&a, &b] {
        let model = deck.model();
        assert_eq!(model.slides[0].notes, "Speaker notes\nsecond line & more.");
        assert_eq!(model.slides[1].notes, "kept");
    }
}

#[test]
fn malformed_update_bytes_are_refused() {
    let mut deck = DeckDocument::empty(9);
    let error = deck.apply_update(&[0xff, 0xff, 0xff]).expect_err("invalid");
    assert_eq!(error.code(), "shared_item_invalid_update");
    assert!(deck.encode_update_since(&[0xff]).is_err());
}
