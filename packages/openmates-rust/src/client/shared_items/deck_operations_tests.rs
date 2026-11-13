//! Typed deck operations on one replica: each operation, its validation, undo/redo and Clear all.

use super::deck::DeckDocument;
use super::deck_error::DeckError;
use super::deck_markup::{ElementContent, ElementModel, TodoItem};
use super::deck_markup_tests::{CLASSIC_DECK, FULL_DECK, NOTEPAD_DECK};
use super::deck_operations::{DeckOperation, DeckOutcome, ElementSpec, TextStyle};
use super::deck_values::ElementKind;
use std::collections::BTreeMap;

fn deck() -> DeckDocument {
    DeckDocument::from_markup(FULL_DECK, 7).expect("fixture hydrates")
}

fn element(deck: &DeckDocument, slide: &str, id: &str) -> ElementModel {
    deck.model()
        .slides
        .into_iter()
        .find(|s| s.id == slide)
        .and_then(|s| s.elements.into_iter().find(|e| e.id == id))
        .expect("element exists")
}

fn slide_ids(deck: &DeckDocument) -> Vec<String> {
    deck.model().slides.into_iter().map(|s| s.id).collect()
}

fn apply(deck: &mut DeckDocument, op: DeckOperation) -> DeckOutcome {
    deck.apply(op).expect("operation applies")
}

fn ids(slide: &str, element: &str) -> (String, String) {
    (slide.to_string(), element.to_string())
}

// contract-test: supporting surface=sdks.rust assertions=slides.editor.direct-manipulation,live-collab.core.one-shared-model
#[test]
fn text_content_and_style_operations_write_normalised_values() {
    let mut deck = deck();
    let (slide_id, element_id) = ids("s1", "e1");
    let outcome = apply(
        &mut deck,
        DeckOperation::SetTextContent {
            slide_id: slide_id.clone(),
            element_id: element_id.clone(),
            markup: "  New   <b>bold</b>\n title <ul> <li>a</li> <li>b</li> </ul> ".into(),
        },
    );
    assert_eq!(outcome, DeckOutcome::Applied);
    assert_eq!(
        element(&deck, "s1", "e1").content,
        ElementContent::RichText("New <b>bold</b> title <ul><li>a</li><li>b</li></ul>".into())
    );
    let style = TextStyle {
        font: Some("times new roman".into()),
        size: Some(1000),
        color: Some("#ABCDEF".into()),
        remove: vec!["weight".into()],
        ..TextStyle::default()
    };
    apply(
        &mut deck,
        DeckOperation::SetTextStyle {
            slide_id: slide_id.clone(),
            element_id: element_id.clone(),
            style,
        },
    );
    let attrs = element(&deck, "s1", "e1").attributes;
    assert_eq!(
        attrs.get("font").map(String::as_str),
        Some("Times New Roman")
    );
    assert_eq!(attrs.get("size").map(String::as_str), Some("400"));
    assert_eq!(attrs.get("color").map(String::as_str), Some("#abcdef"));
    assert!(!attrs.contains_key("weight"));
    let markup = deck.to_markup().expect("saves");
    assert!(
        markup.contains(
            r##"font="Times New Roman" size="400" color="#abcdef" align="center" animate="fade""##
        ),
        "{markup}"
    );
    // The saved markup hydrates again unchanged.
    assert_eq!(
        DeckDocument::from_markup(&markup, 8)
            .expect("normalised")
            .to_markup()
            .expect("saves"),
        markup
    );

    let bad = deck.apply(DeckOperation::SetTextContent {
        slide_id: slide_id.clone(),
        element_id: element_id.clone(),
        markup: "<script>x</script>".into(),
    });
    assert_eq!(bad.expect_err("refused").code(), "slides_invalid_value");
    let wrong_kind = deck.apply(DeckOperation::SetTextContent {
        slide_id,
        element_id: "e2".into(),
        markup: "x".into(),
    });
    assert!(matches!(
        wrong_kind,
        Err(DeckError::WrongElementKind { .. })
    ));
}

#[test]
fn geometry_is_clamped_like_the_normaliser_and_undo_restores_it() {
    let mut deck = deck();
    let before = deck.to_markup().expect("saves");
    apply(
        &mut deck,
        DeckOperation::SetGeometry {
            slide_id: "s1".into(),
            element_id: "e2".into(),
            x: 1800,
            y: -40,
            w: 900,
            h: 5000,
        },
    );
    let image = element(&deck, "s1", "e2");
    assert_eq!(
        (image.x, image.y, image.w, image.h),
        (Some(1800), Some(0), Some(120), Some(1080))
    );
    assert!(deck.can_undo());
    assert!(deck.undo());
    assert_eq!(deck.to_markup().expect("saves"), before);
    assert!(deck.can_redo());
    assert!(deck.redo());
    assert_eq!(element(&deck, "s1", "e2").w, Some(120));
    // Same values again: valid, but no new undo step.
    let again = apply(
        &mut deck,
        DeckOperation::SetGeometry {
            slide_id: "s1".into(),
            element_id: "e2".into(),
            x: 1800,
            y: 0,
            w: 120,
            h: 1080,
        },
    );
    assert_eq!(again, DeckOutcome::Unchanged);
}

#[test]
fn image_source_can_be_replaced_with_an_embed_only() {
    let mut deck = deck();
    apply(
        &mut deck,
        DeckOperation::SetImageSource {
            slide_id: "s1".into(),
            element_id: "e2".into(),
            src: "embed:new-photo".into(),
            alt: Some(String::new()),
        },
    );
    let image = element(&deck, "s1", "e2");
    assert_eq!(
        image.attributes.get("src").map(String::as_str),
        Some("embed:new-photo")
    );
    assert!(!image.attributes.contains_key("alt"));
    let external = deck.apply(DeckOperation::SetImageSource {
        slide_id: "s1".into(),
        element_id: "e2".into(),
        src: "https://evil.example/x.png".into(),
        alt: None,
    });
    assert_eq!(
        external.expect_err("refused").code(),
        "slides_invalid_value"
    );
}

#[test]
fn elements_are_added_duplicated_and_deleted_with_fresh_ids() {
    let mut deck = deck();
    let added = apply(
        &mut deck,
        DeckOperation::AddElement {
            slide_id: "s2".into(),
            index: None,
            element: ElementSpec {
                kind: ElementKind::Shape,
                x: Some(10),
                y: Some(20),
                w: Some(3000),
                h: Some(30),
                attributes: BTreeMap::from([("kind".into(), "Triangle".into())]),
                content: ElementContent::Empty,
            },
        },
    );
    assert_eq!(
        added,
        DeckOutcome::ElementCreated {
            element_id: "e9".into()
        }
    );
    let shape = element(&deck, "s2", "e9");
    assert_eq!(
        (shape.w, shape.attributes.get("kind").map(String::as_str)),
        (Some(1910), Some("triangle"))
    );

    let duplicated = apply(
        &mut deck,
        DeckOperation::DuplicateElement {
            slide_id: "s1".into(),
            element_id: "e1".into(),
        },
    );
    assert_eq!(
        duplicated,
        DeckOutcome::ElementCreated {
            element_id: "e10".into()
        }
    );
    let slide = deck.model().slides.into_iter().next().expect("first slide");
    assert_eq!(slide.elements[1].id, "e10");
    assert_eq!(slide.elements[1].content, slide.elements[0].content);

    apply(
        &mut deck,
        DeckOperation::DeleteElement {
            slide_id: "s1".into(),
            element_id: "e1".into(),
        },
    );
    assert!(deck.model().slides[0].elements.iter().all(|e| e.id != "e1"));

    let unknown_attr = deck.apply(DeckOperation::AddElement {
        slide_id: "s2".into(),
        index: None,
        element: ElementSpec {
            kind: ElementKind::Image,
            x: None,
            y: None,
            w: None,
            h: None,
            attributes: BTreeMap::from([("onload".into(), "x".into())]),
            content: ElementContent::Empty,
        },
    });
    assert_eq!(
        unknown_attr,
        Err(DeckError::UnknownAttribute("onload".into()))
    );
    let missing_src = deck.apply(DeckOperation::AddElement {
        slide_id: "s2".into(),
        index: None,
        element: ElementSpec {
            kind: ElementKind::Image,
            x: None,
            y: None,
            w: None,
            h: None,
            attributes: BTreeMap::new(),
            content: ElementContent::Empty,
        },
    });
    assert_eq!(
        missing_src.expect_err("refused").code(),
        "slides_invalid_value"
    );
}

fn element_ids(deck: &DeckDocument, slide: &str) -> Vec<String> {
    deck.model()
        .slides
        .into_iter()
        .find(|s| s.id == slide)
        .map(|s| s.elements.into_iter().map(|e| e.id).collect())
        .expect("slide exists")
}

// contract-test: supporting surface=sdks.rust assertions=slides.editor.direct-manipulation
#[test]
fn elements_change_paint_order_and_the_order_saves_and_undoes() {
    let mut deck = deck();
    let start = element_ids(&deck, "s1");
    assert_eq!(start, ["e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8"]);
    // Bring forward one step, then to the top (index past the end).
    apply(
        &mut deck,
        DeckOperation::MoveElement {
            slide_id: "s1".into(),
            element_id: "e2".into(),
            to_index: 2,
        },
    );
    assert_eq!(
        element_ids(&deck, "s1"),
        ["e1", "e3", "e2", "e4", "e5", "e6", "e7", "e8"]
    );
    apply(
        &mut deck,
        DeckOperation::MoveElement {
            slide_id: "s1".into(),
            element_id: "e1".into(),
            to_index: 99,
        },
    );
    assert_eq!(
        element_ids(&deck, "s1"),
        ["e3", "e2", "e4", "e5", "e6", "e7", "e8", "e1"]
    );
    // Send to the back.
    apply(
        &mut deck,
        DeckOperation::MoveElement {
            slide_id: "s1".into(),
            element_id: "e8".into(),
            to_index: 0,
        },
    );
    let moved = element_ids(&deck, "s1");
    assert_eq!(moved, ["e8", "e3", "e2", "e4", "e5", "e6", "e7", "e1"]);
    // Already there: valid, no undo step.
    assert_eq!(
        apply(
            &mut deck,
            DeckOperation::MoveElement {
                slide_id: "s1".into(),
                element_id: "e8".into(),
                to_index: 0,
            },
        ),
        DeckOutcome::Unchanged
    );
    // The paint order is the element order of the saved markup.
    let markup = deck.to_markup().expect("saves");
    let reopened = DeckDocument::from_markup(&markup, 9).expect("normalised");
    assert_eq!(element_ids(&reopened, "s1"), moved);
    assert_eq!(
        reopened.model().slides[0].elements[7],
        element(&deck, "s1", "e1")
    );

    assert!(deck.undo());
    assert_eq!(
        element_ids(&deck, "s1"),
        ["e3", "e2", "e4", "e5", "e6", "e7", "e8", "e1"]
    );
    assert!(deck.undo() && deck.undo());
    assert_eq!(element_ids(&deck, "s1"), start);
    assert!(deck.redo());
    assert_eq!(
        element_ids(&deck, "s1"),
        ["e1", "e3", "e2", "e4", "e5", "e6", "e7", "e8"]
    );

    let missing = deck
        .apply(DeckOperation::MoveElement {
            slide_id: "s1".into(),
            element_id: "nope".into(),
            to_index: 0,
        })
        .expect_err("unknown element");
    assert_eq!(missing.code(), "slides_element_not_found");
}

#[test]
fn slides_are_added_duplicated_reordered_and_deleted() {
    let mut deck = deck();
    let added = apply(
        &mut deck,
        DeckOperation::AddSlide {
            index: Some(0),
            layout: Some("Title".into()),
        },
    );
    assert_eq!(
        added,
        DeckOutcome::SlideCreated {
            slide_id: "s3".into()
        }
    );
    assert_eq!(slide_ids(&deck), ["s3", "s1", "s2"]);
    assert_eq!(deck.model().slides[0].layout.as_deref(), Some("title"));

    let copy = apply(
        &mut deck,
        DeckOperation::DuplicateSlide {
            slide_id: "s1".into(),
        },
    );
    assert_eq!(
        copy,
        DeckOutcome::SlideCreated {
            slide_id: "s4".into()
        }
    );
    assert_eq!(slide_ids(&deck), ["s3", "s1", "s4", "s2"]);
    let copied = &deck.model().slides[2];
    let copied_ids: Vec<&str> = copied.elements.iter().map(|e| e.id.as_str()).collect();
    assert_eq!(
        copied_ids,
        ["e9", "e10", "e11", "e12", "e13", "e14", "e15", "e16"]
    );
    assert_eq!(copied.notes, deck.model().slides[1].notes);
    // The copy saves as valid normalised markup (no duplicate ids).
    let markup = deck.to_markup().expect("saves");
    DeckDocument::from_markup(&markup, 9).expect("normalised");

    apply(
        &mut deck,
        DeckOperation::MoveSlide {
            slide_id: "s3".into(),
            to_index: 99,
        },
    );
    assert_eq!(slide_ids(&deck), ["s1", "s4", "s2", "s3"]);
    apply(
        &mut deck,
        DeckOperation::MoveSlide {
            slide_id: "s2".into(),
            to_index: 0,
        },
    );
    assert_eq!(slide_ids(&deck), ["s2", "s1", "s4", "s3"]);

    for id in ["s2", "s1", "s4"] {
        apply(
            &mut deck,
            DeckOperation::DeleteSlide {
                slide_id: id.into(),
            },
        );
    }
    assert_eq!(slide_ids(&deck), ["s3"]);
    let last = deck.apply(DeckOperation::DeleteSlide {
        slide_id: "s3".into(),
    });
    assert_eq!(last, Err(DeckError::LastSlide));
    // Undo walks back one operation at a time.
    assert!(deck.undo());
    assert_eq!(slide_ids(&deck), ["s4", "s3"]);
}

#[test]
fn layout_and_speaker_notes_are_set_and_removed() {
    let mut deck = deck();
    apply(
        &mut deck,
        DeckOperation::SetSlideLayout {
            slide_id: "s2".into(),
            layout: Some("two-column".into()),
        },
    );
    apply(
        &mut deck,
        DeckOperation::SetSpeakerNotes {
            slide_id: "s2".into(),
            notes: "  Say <hello> & wave \n".into(),
        },
    );
    let markup = deck.to_markup().expect("saves");
    assert!(markup.contains("  <slide id=\"s2\" layout=\"two-column\">\n    <notes>Say &lt;hello&gt; &amp; wave</notes>\n  </slide>\n"), "{markup}");
    apply(
        &mut deck,
        DeckOperation::SetSpeakerNotes {
            slide_id: "s1".into(),
            notes: String::new(),
        },
    );
    apply(
        &mut deck,
        DeckOperation::SetSlideLayout {
            slide_id: "s1".into(),
            layout: None,
        },
    );
    let slide = &deck.model().slides[0];
    assert!(slide.notes.is_empty() && slide.layout.is_none());
    let bad = deck.apply(DeckOperation::SetSlideLayout {
        slide_id: "s1".into(),
        layout: Some("no spaces".into()),
    });
    assert_eq!(bad.expect_err("refused").code(), "slides_invalid_value");
}

// contract-test: supporting surface=sdks.rust assertions=slides.interactive.notepad-and-todo
#[test]
fn todo_items_are_set_checked_and_cleared() {
    let mut deck = deck();
    apply(
        &mut deck,
        DeckOperation::SetTodoItems {
            slide_id: "s1".into(),
            element_id: "e6".into(),
            items: vec![
                TodoItem {
                    text: " Pack  bags ".into(),
                    done: false,
                },
                TodoItem {
                    text: "Leave".into(),
                    done: false,
                },
            ],
        },
    );
    apply(
        &mut deck,
        DeckOperation::SetTodoItemDone {
            slide_id: "s1".into(),
            element_id: "e6".into(),
            index: 1,
            done: true,
        },
    );
    assert!(deck.to_markup().expect("saves").contains(
        "<todo id=\"e6\" x=\"1000\" y=\"760\" w=\"800\" h=\"240\" title=\"Next\"><item done=\"false\">Pack bags</item><item done=\"true\">Leave</item></todo>"
    ));
    let out_of_range = deck.apply(DeckOperation::SetTodoItemDone {
        slide_id: "s1".into(),
        element_id: "e6".into(),
        index: 5,
        done: true,
    });
    assert_eq!(out_of_range, Err(DeckError::ItemOutOfRange(5)));

    let cleared = apply(
        &mut deck,
        DeckOperation::ClearInteractiveElement {
            slide_id: "s1".into(),
            element_id: "e6".into(),
        },
    );
    assert_eq!(cleared, DeckOutcome::Applied);
    assert_eq!(
        element(&deck, "s1", "e6").content,
        ElementContent::Items(Vec::new())
    );
    // Cleared content comes back with undo.
    assert!(deck.undo());
    assert!(
        matches!(element(&deck, "s1", "e6").content, ElementContent::Items(items) if items.len() == 2)
    );

    let not_interactive = deck.apply(DeckOperation::ClearInteractiveElement {
        slide_id: "s1".into(),
        element_id: "e1".into(),
    });
    assert!(matches!(
        not_interactive,
        Err(DeckError::WrongElementKind { .. })
    ));
}

// contract-test: supporting surface=sdks.rust assertions=slides.interactive.notepad-and-todo
#[test]
fn clear_all_empties_every_todo_and_keeps_slides_and_elements() {
    let mut deck = DeckDocument::from_markup(FULL_DECK, 3).expect("hydrates");
    // A second to-do list on the other slide.
    apply(
        &mut deck,
        DeckOperation::AddElement {
            slide_id: "s2".into(),
            index: None,
            element: ElementSpec {
                kind: ElementKind::Todo,
                x: None,
                y: None,
                w: None,
                h: None,
                attributes: BTreeMap::new(),
                content: ElementContent::Items(vec![TodoItem {
                    text: "x".into(),
                    done: true,
                }]),
            },
        },
    );
    let before = deck.model();
    let outcome = apply(&mut deck, DeckOperation::ClearAllInteractive);
    assert_eq!(outcome, DeckOutcome::Cleared { elements: 2 });
    let after = deck.model();
    assert_eq!(slide_ids(&deck), ["s1", "s2"]);
    for (old, new) in before.slides.iter().zip(&after.slides) {
        let old_ids: Vec<&str> = old.elements.iter().map(|e| e.id.as_str()).collect();
        let new_ids: Vec<&str> = new.elements.iter().map(|e| e.id.as_str()).collect();
        assert_eq!(old_ids, new_ids);
        for element in &new.elements {
            if element.kind == ElementKind::Todo {
                assert_eq!(element.content, ElementContent::Items(Vec::new()));
            }
        }
        assert_eq!(old.notes, new.notes);
    }
    assert_eq!(
        apply(&mut deck, DeckOperation::ClearAllInteractive),
        DeckOutcome::Cleared { elements: 0 }
    );
    // Clear all is one undo step.
    assert!(deck.undo());
    assert_eq!(deck.model(), before);

    let classic = DeckDocument::from_markup(CLASSIC_DECK, 4).expect("hydrates");
    assert!(!classic.can_undo(), "hydration is not an undo step");
}

// contract-test: supporting surface=sdks.rust assertions=slides.interactive.notepad-and-todo,live-collab.core.one-shared-model
#[test]
fn notepad_text_and_hidden_flags_are_saved_cleared_and_undone() {
    let mut deck = deck();
    let before = deck.to_markup().expect("saves");
    let (s, n) = ids("s1", "e5");
    let set_text = |text: &str| DeckOperation::SetNotepadText {
        slide_id: s.clone(),
        element_id: n.clone(),
        text: text.into(),
    };
    assert_eq!(
        apply(&mut deck, set_text("  idea <1>\nnext  ")),
        DeckOutcome::Applied
    );
    assert_eq!(
        element(&deck, "s1", "e5").content,
        ElementContent::Plain("idea <1>\nnext".into())
    );
    assert_eq!(
        apply(&mut deck, set_text("idea <1>\nnext")),
        DeckOutcome::Unchanged
    );
    let saved = deck.to_markup().expect("saves");
    assert!(saved.contains(">idea &lt;1&gt;\nnext</notepad>"));
    let reloaded = DeckDocument::from_markup(&saved, 9).expect("reloads");
    assert_eq!(element(&reloaded, "s1", "e5"), element(&deck, "s1", "e5"));

    let hide = |hidden| DeckOperation::SetInteractiveHidden {
        slide_id: "s1".into(),
        element_id: "e6".into(),
        hidden,
    };
    assert_eq!(apply(&mut deck, hide(true)), DeckOutcome::Applied);
    assert_eq!(apply(&mut deck, hide(true)), DeckOutcome::Unchanged);
    assert!(
        deck.to_markup()
            .expect("saves")
            .contains("title=\"Next\" hidden=\"true\">")
    );
    assert_eq!(apply(&mut deck, hide(false)), DeckOutcome::Applied);
    assert!(!deck.to_markup().expect("saves").contains("hidden"));

    assert_eq!(
        apply(
            &mut deck,
            DeckOperation::SetAllInteractiveHidden { hidden: true }
        ),
        DeckOutcome::Applied
    );
    assert!(element(&deck, "s1", "e5").attributes.contains_key("hidden"));
    assert!(element(&deck, "s1", "e6").attributes.contains_key("hidden"));
    assert_eq!(
        apply(
            &mut deck,
            DeckOperation::SetAllInteractiveHidden { hidden: true }
        ),
        DeckOutcome::Unchanged
    );
    // Hidden elements keep their content; clearing the notepad empties only the text.
    assert_eq!(
        apply(
            &mut deck,
            DeckOperation::ClearInteractiveElement {
                slide_id: "s1".into(),
                element_id: "e5".into(),
            },
        ),
        DeckOutcome::Applied
    );
    let cleared = element(&deck, "s1", "e5");
    assert_eq!(cleared.content, ElementContent::Plain(String::new()));
    assert!(cleared.attributes.contains_key("hidden"));

    // Undo walks back every step to the original markup.
    while deck.undo() {}
    assert_eq!(deck.to_markup().expect("saves"), before);

    // Wrong element kinds are still refused.
    let error = deck
        .apply(DeckOperation::SetNotepadText {
            slide_id: "s1".into(),
            element_id: "e6".into(),
            text: "x".into(),
        })
        .expect_err("to-do is not a notepad");
    assert_eq!(error.code(), "slides_wrong_element_kind");
}

#[test]
fn clear_all_interactive_also_empties_notepad_text() {
    let mut deck = DeckDocument::from_markup(NOTEPAD_DECK, 3).expect("hydrates");
    assert_eq!(
        apply(&mut deck, DeckOperation::ClearAllInteractive),
        DeckOutcome::Cleared { elements: 2 }
    );
    assert_eq!(
        element(&deck, "s1", "e1").content,
        ElementContent::Plain(String::new())
    );
    assert!(deck.undo());
    assert_eq!(deck.to_markup().expect("saves"), NOTEPAD_DECK);
}

#[test]
fn operations_and_view_serialise_as_tagged_json() {
    let op: DeckOperation = serde_json::from_str(
        r##"{"op":"set_geometry","slide_id":"s1","element_id":"e1","x":1,"y":2,"w":3,"h":4}"##,
    )
    .expect("tagged operation");
    let mut deck = deck();
    assert_eq!(apply(&mut deck, op), DeckOutcome::Applied);
    let view = deck.view();
    assert!(view.can_undo && !view.can_redo);
    assert_eq!((view.canvas_width, view.canvas_height), (1920, 1080));
    let json = serde_json::to_value(&view).expect("view serialises");
    assert_eq!(json["aspect"], "16:9");
    assert_eq!(json["slides"][0]["elements"][0]["kind"], "text");
    assert_eq!(json["slides"][0]["elements"][5]["content"]["type"], "items");
    let outcome = serde_json::to_value(DeckOutcome::SlideCreated {
        slide_id: "s9".into(),
    })
    .expect("serialises");
    assert_eq!(
        outcome,
        serde_json::json!({"outcome": "slide_created", "slide_id": "s9"})
    );
}
