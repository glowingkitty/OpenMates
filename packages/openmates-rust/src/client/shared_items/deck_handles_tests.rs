//! `DeckDocuments` handle table (JSON in/out, stable error codes) and the deck wire fixture
//! (`deck_wire_fixture.json`) that pins the serde shapes the web TS types mirror.

use super::deck::DeckDocument;
use super::deck_error::DeckError;
use super::deck_handles::{DeckDocuments, DeckHandleError};
use super::deck_markup::{ElementContent, TodoItem};
use super::deck_markup_tests::FULL_DECK;
use super::deck_operations::{DeckOperation, DeckOutcome, ElementSpec, TextStyle};
use super::deck_values::ElementKind;
use serde_json::{Value, json};
use std::collections::BTreeMap;

const FIXTURE_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/src/client/shared_items/deck_wire_fixture.json"
);

const DRIFT_HELP: &str = "deck wire shapes changed: rerun with OPENMATES_UPDATE_DECK_WIRE_FIXTURE=1, then update deckDocumentTypes.ts (frontend/packages/ui/src/services/rustCore/deckDocument/) and deckDocumentWire.test.ts";

fn parse(json: &str) -> Value {
    serde_json::from_str(json).expect("table answers JSON")
}

fn open(table: &mut DeckDocuments) -> u32 {
    let opened = parse(&table.open(FULL_DECK).expect("fixture hydrates"));
    u32::try_from(opened["handle"].as_u64().expect("numeric handle")).expect("u32 handle")
}

// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
#[test]
fn applies_operations_and_undoes_back_to_the_original_markup() {
    let mut table = DeckDocuments::new();
    let handle = open(&mut table);
    assert_eq!(table.len(), 1);
    let geometry = json!({"op":"set_geometry","slide_id":"s1","element_id":"e2","x":10,"y":20,"w":300,"h":200});
    let applied = parse(&table.apply(handle, &geometry.to_string()).expect("applies"));
    assert_eq!(applied["outcome"], json!({"outcome":"applied"}));
    assert_eq!(applied["view"]["can_undo"], json!(true));
    assert_eq!(applied["view"]["slides"][0]["elements"][1]["x"], json!(10));
    let text = json!({"op":"set_text_content","slide_id":"s1","element_id":"e1","markup":"New <b>title</b>"});
    let applied = parse(&table.apply(handle, &text.to_string()).expect("applies"));
    assert_eq!(
        applied["view"]["slides"][0]["elements"][0]["content"],
        json!({"type":"rich_text","value":"New <b>title</b>"})
    );
    assert_ne!(table.to_markup(handle).expect("saves"), FULL_DECK);
    for _ in 0..2 {
        let stepped = parse(&table.undo(handle).expect("undoes"));
        assert_eq!(stepped["changed"], json!(true));
    }
    let stepped = parse(&table.undo(handle).expect("answers"));
    assert_eq!(stepped["changed"], json!(false));
    assert_eq!(stepped["view"]["can_undo"], json!(false));
    assert_eq!(stepped["view"]["can_redo"], json!(true));
    assert_eq!(table.to_markup(handle).expect("saves"), FULL_DECK);
    let redone = parse(&table.redo(handle).expect("redoes"));
    assert_eq!(redone["changed"], json!(true));
    assert_eq!(
        parse(&table.view(handle).expect("views"))["view"]["slides"][0]["elements"][1]["x"],
        json!(10)
    );
}

// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
#[test]
fn refuses_unknown_handles_bad_operations_and_deck_errors_with_stable_codes() {
    let mut table = DeckDocuments::new();
    let handle = open(&mut table);
    let unknown = table.undo(handle + 1).expect_err("unknown handle");
    assert_eq!(unknown.code(), "shared_item_unknown_handle");
    let bad = table
        .apply(handle, r#"{"op":"teleport"}"#)
        .expect_err("unknown op");
    assert_eq!(bad.code(), "slides_invalid_operation");
    let missing = table
        .apply(handle, r#"{"op":"delete_slide","slide_id":"nope"}"#)
        .expect_err("missing slide");
    assert_eq!(
        missing,
        DeckHandleError::Deck(DeckError::SlideNotFound("nope".into()))
    );
    assert_eq!(missing.code(), "slides_slide_not_found");
    let markup = DeckDocuments::new()
        .open("<deck>")
        .expect_err("not normalised");
    assert_eq!(markup.code(), "slides_markup_not_normalised");
    let update = table
        .apply_update(handle, &[0xff, 0xff])
        .expect_err("not an update");
    assert_eq!(update.code(), "shared_item_invalid_update");
    let vector = table
        .encode_update_since(handle, &[0xff, 0xff, 0xff])
        .expect_err("not a state vector");
    assert_eq!(vector.code(), "shared_item_invalid_update");
    // A refused operation left no undo step behind.
    assert_eq!(
        parse(&table.view(handle).expect("views"))["view"]["can_undo"],
        json!(false)
    );
}

// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
#[test]
fn exchanges_update_bytes_and_closes_handles_without_reuse() {
    let mut table = DeckDocuments::new();
    let first = open(&mut table);
    let second = open(&mut table);
    assert_ne!(first, second);
    let vector = table.state_vector(first).expect("state vector");
    assert!(!vector.is_empty());
    let everything = table.encode_update_since(first, &[0]).expect("full diff");
    // Re-applying a replica's own state is idempotent.
    let viewed = parse(&table.apply_update(first, &everything).expect("applies"));
    assert_eq!(viewed["view"]["slides"].as_array().map(Vec::len), Some(2));
    assert_eq!(table.to_markup(first).expect("saves"), FULL_DECK);
    assert!(table.close(first));
    assert!(!table.close(first));
    assert_eq!(
        table.to_markup(first).expect_err("closed").code(),
        "shared_item_unknown_handle"
    );
    let third = open(&mut table);
    assert!(third != first && third != second);
    assert_eq!(table.len(), 2);
}

fn spec() -> ElementSpec {
    ElementSpec {
        kind: ElementKind::Text,
        x: Some(10),
        y: None,
        w: Some(400),
        h: None,
        attributes: BTreeMap::from([("role".to_string(), "body".to_string())]),
        content: ElementContent::RichText("Hi".into()),
    }
}

/// One exemplar per operation variant; [`operation_name`] makes a new variant a compile
/// error here until it is added to the fixture.
fn operations() -> Vec<DeckOperation> {
    let (s, e) = ("s1".to_string(), "e1".to_string());
    vec![
        DeckOperation::SetTextContent {
            slide_id: s.clone(),
            element_id: e.clone(),
            markup: "<b>x</b>".into(),
        },
        DeckOperation::SetTextStyle {
            slide_id: s.clone(),
            element_id: e.clone(),
            style: TextStyle {
                font: Some("heading".into()),
                size: Some(32),
                color: Some("#112233".into()),
                align: Some("center".into()),
                weight: Some("bold".into()),
                remove: vec!["role".into()],
            },
        },
        DeckOperation::SetGeometry {
            slide_id: s.clone(),
            element_id: e.clone(),
            x: 1,
            y: 2,
            w: 3,
            h: 4,
        },
        DeckOperation::SetImageSource {
            slide_id: s.clone(),
            element_id: e.clone(),
            src: "embed:a".into(),
            alt: None,
        },
        DeckOperation::AddElement {
            slide_id: s.clone(),
            index: Some(0),
            element: spec(),
        },
        DeckOperation::DeleteElement {
            slide_id: s.clone(),
            element_id: e.clone(),
        },
        DeckOperation::DuplicateElement {
            slide_id: s.clone(),
            element_id: e.clone(),
        },
        DeckOperation::MoveElement {
            slide_id: s.clone(),
            element_id: e.clone(),
            to_index: 1,
        },
        DeckOperation::AddSlide {
            index: None,
            layout: Some("title".into()),
        },
        DeckOperation::DuplicateSlide {
            slide_id: s.clone(),
        },
        DeckOperation::DeleteSlide {
            slide_id: s.clone(),
        },
        DeckOperation::MoveSlide {
            slide_id: s.clone(),
            to_index: 2,
        },
        DeckOperation::SetSlideLayout {
            slide_id: s.clone(),
            layout: None,
        },
        DeckOperation::SetSpeakerNotes {
            slide_id: s.clone(),
            notes: "Notes".into(),
        },
        DeckOperation::SetNotepadText {
            slide_id: s.clone(),
            element_id: e.clone(),
            text: "Idea".into(),
        },
        DeckOperation::SetTodoItems {
            slide_id: s.clone(),
            element_id: e.clone(),
            items: vec![TodoItem {
                text: "Do".into(),
                done: false,
            }],
        },
        DeckOperation::SetTodoItemDone {
            slide_id: s.clone(),
            element_id: e.clone(),
            index: 0,
            done: true,
        },
        DeckOperation::ClearInteractiveElement {
            slide_id: s.clone(),
            element_id: e.clone(),
        },
        DeckOperation::ClearAllInteractive,
        DeckOperation::SetInteractiveHidden {
            slide_id: s,
            element_id: e,
            hidden: true,
        },
        DeckOperation::SetAllInteractiveHidden { hidden: false },
    ]
}

fn operation_name(operation: &DeckOperation) -> &'static str {
    match operation {
        DeckOperation::SetTextContent { .. } => "set_text_content",
        DeckOperation::SetTextStyle { .. } => "set_text_style",
        DeckOperation::SetGeometry { .. } => "set_geometry",
        DeckOperation::SetImageSource { .. } => "set_image_source",
        DeckOperation::AddElement { .. } => "add_element",
        DeckOperation::DeleteElement { .. } => "delete_element",
        DeckOperation::DuplicateElement { .. } => "duplicate_element",
        DeckOperation::MoveElement { .. } => "move_element",
        DeckOperation::AddSlide { .. } => "add_slide",
        DeckOperation::DuplicateSlide { .. } => "duplicate_slide",
        DeckOperation::DeleteSlide { .. } => "delete_slide",
        DeckOperation::MoveSlide { .. } => "move_slide",
        DeckOperation::SetSlideLayout { .. } => "set_slide_layout",
        DeckOperation::SetSpeakerNotes { .. } => "set_speaker_notes",
        DeckOperation::SetNotepadText { .. } => "set_notepad_text",
        DeckOperation::SetTodoItems { .. } => "set_todo_items",
        DeckOperation::SetTodoItemDone { .. } => "set_todo_item_done",
        DeckOperation::ClearInteractiveElement { .. } => "clear_interactive_element",
        DeckOperation::ClearAllInteractive => "clear_all_interactive",
        DeckOperation::SetInteractiveHidden { .. } => "set_interactive_hidden",
        DeckOperation::SetAllInteractiveHidden { .. } => "set_all_interactive_hidden",
    }
}

fn outcomes() -> Vec<DeckOutcome> {
    let all = vec![
        DeckOutcome::Applied,
        DeckOutcome::Unchanged,
        DeckOutcome::SlideCreated {
            slide_id: "s3".into(),
        },
        DeckOutcome::ElementCreated {
            element_id: "e9".into(),
        },
        DeckOutcome::Cleared { elements: 2 },
    ];
    // Exhaustiveness guard: a new outcome variant fails to compile until listed above.
    for outcome in &all {
        match outcome {
            DeckOutcome::Applied
            | DeckOutcome::Unchanged
            | DeckOutcome::SlideCreated { .. }
            | DeckOutcome::ElementCreated { .. }
            | DeckOutcome::Cleared { .. } => {}
        }
    }
    all
}

fn error_codes() -> Vec<&'static str> {
    let errors = [
        DeckError::MarkupNotNormalised {
            offset: 0,
            reason: "x",
        },
        DeckError::NoSlides,
        DeckError::SlideNotFound(String::new()),
        DeckError::ElementNotFound(String::new()),
        DeckError::WrongElementKind {
            element_id: String::new(),
            expected: "text",
        },
        DeckError::UnknownAttribute(String::new()),
        DeckError::InvalidValue {
            field: String::new(),
            reason: "x",
        },
        DeckError::LimitReached("x"),
        DeckError::LastSlide,
        DeckError::ItemOutOfRange(0),
        DeckError::InvalidUpdate(String::new()),
    ];
    let mut codes: Vec<&'static str> = errors.iter().map(DeckError::code).collect();
    codes.push(DeckHandleError::UnknownHandle(0).code());
    codes.push(DeckHandleError::InvalidOperation(String::new()).code());
    codes
}

fn wire_fixture() -> Value {
    let deck = DeckDocument::from_markup(FULL_DECK, 1).expect("fixture hydrates");
    let operations = operations();
    let names: Vec<&str> = operations.iter().map(operation_name).collect();
    json!({
        "view": deck.view(),
        "operations": operations,
        "operation_names": names,
        "outcomes": outcomes(),
        "error_codes": error_codes(),
    })
}

// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
#[test]
fn wire_fixture_matches_the_rust_serde_shapes() {
    let fresh = wire_fixture();
    let pretty = serde_json::to_string_pretty(&fresh).expect("fixture serialises") + "\n";
    if std::env::var_os("OPENMATES_UPDATE_DECK_WIRE_FIXTURE").is_some() {
        std::fs::write(FIXTURE_PATH, &pretty).expect("fixture writes");
    }
    let committed: Value =
        serde_json::from_str(&std::fs::read_to_string(FIXTURE_PATH).expect("fixture is committed"))
            .expect("fixture parses");
    assert_eq!(committed, fresh, "{DRIFT_HELP}");
    // Every operation in the fixture parses back into the same value (the binding's input path).
    for (operation, value) in operations()
        .iter()
        .zip(committed["operations"].as_array().expect("array"))
    {
        let parsed: DeckOperation =
            serde_json::from_value(value.clone()).expect("operation parses");
        assert_eq!(&parsed, operation);
    }
}
