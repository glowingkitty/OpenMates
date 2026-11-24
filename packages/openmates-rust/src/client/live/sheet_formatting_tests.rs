//! Formatting follows stable cells through merges, encrypted delivery, undo and stored snapshots.

use super::assistant::{AssistantResult, PinnedBase, apply_assistant_change, undo_assistant};
use super::ops_json::{parse_op, view_json};
use super::support::{create, exchange, in_order, replicas};
use super::{LiveItem, LiveItemKind};
use serde_json::{Value, json};

const TABLE: &str = "| Crop | Count |\n| --- | --- |\n| Peas | 2 |\n| Corn | 3 |";

fn stored(formatting: Value) -> String {
    format!("{TABLE}\n<!-- openmates-sheet-format-v1: {formatting} -->")
}

fn apply(item: &mut LiveItem, op: Value) {
    item.apply_local_op(parse_op(&op.to_string()).unwrap())
        .unwrap();
}

fn style(patch: Value) -> Value {
    json!({"kind":"cellStyle", "cell":{"rowId":"r1", "colId":"c1"}, "patch":patch})
}

fn formatting(item: &LiveItem) -> Value {
    view_json(item).unwrap().unwrap()["formatting"].clone()
}

#[test]
fn formatting_follows_stable_cells_and_undo_replicates() {
    let text = stored(json!({"cells":{"A2":{"bold":true}},"columnWidths":{"A":160}}));
    let mut pair = replicas(LiveItemKind::Sheet, &text, 2);
    apply(
        &mut pair[0],
        json!({"op":"sheet_format", "changes":[style(json!({"italic":true}))]}),
    );
    apply(
        &mut pair[1],
        json!({"op":"insert_row", "after_row_id":null}),
    );
    exchange(&mut pair, in_order);
    for item in &pair {
        assert_eq!(
            formatting(item)["cells"]["A3"],
            json!({"bold":true, "italic":true})
        );
        let reopened = create(LiveItemKind::Sheet, &item.text_form().unwrap());
        assert_eq!(formatting(&reopened), formatting(item));
    }
    assert!(pair[0].can_undo_sheet_formatting());
    assert!(!pair[1].can_undo_sheet_formatting());
    apply(&mut pair[0], json!({"op":"sheet_undo_formatting"}));
    exchange(&mut pair, in_order);
    for item in &pair {
        assert_eq!(formatting(item)["cells"]["A3"], json!({"bold":true}));
    }
}

#[test]
fn an_overlapping_merge_rejects_the_whole_batch_and_null_clears() {
    let text = stored(json!({"cells":{"A2":{"bold":true}},"merges":[{"start":"A2","end":"B2"}]}));
    let mut item = create(LiveItemKind::Sheet, &text);
    let invalid = parse_op(
        &json!({"op":"sheet_format","changes":[
            style(json!({"bold":null})),
            {"kind":"merge","start":{"rowId":"r1","colId":"c2"},"end":{"rowId":"r2","colId":"c2"}}
        ]})
        .to_string(),
    )
    .unwrap();
    assert!(item.apply_local_op(invalid).is_err());
    assert_eq!(item.text_form().unwrap(), text);
    apply(
        &mut item,
        json!({"op":"sheet_format","changes":[style(json!({"bold":null}))]}),
    );
    assert!(formatting(&item)["cells"].is_null());
    assert!(!formatting(&item)["merges"].is_null());
}

#[test]
fn assistant_formatting_preserves_omitted_and_human_properties() {
    let initial = stored(json!({"cells":{"A2":{"bold":true,"textColor":"#0000ff"}}}));
    let mut item = create(LiveItemKind::Sheet, &initial);
    let base = PinnedBase::pin(&item).unwrap();
    apply(
        &mut item,
        json!({"op":"sheet_format","changes":[style(json!({"textColor":"#00ff00"}))]}),
    );
    let next = stored(json!({"cells":{"A2":{"textColor":"#ff0000","italic":true}}}));
    let AssistantResult::Applied(outcome) =
        apply_assistant_change(&mut item, &base, &next, "turn").unwrap()
    else {
        panic!("assistant edit stayed busy");
    };
    assert_eq!(outcome.applied_hunks, 1);
    assert_eq!(outcome.same_spot.len(), 1);
    assert_eq!(
        formatting(&item)["cells"]["A2"],
        json!({"bold":true,"italic":true,"textColor":"#00ff00"})
    );
    undo_assistant(&mut item, "turn").unwrap();
    assert_eq!(
        formatting(&item)["cells"]["A2"],
        json!({"bold":true,"textColor":"#00ff00"})
    );
}

#[test]
fn invalid_assistant_footer_leaves_the_existing_sheet_unchanged() {
    let mut item = create(LiveItemKind::Sheet, TABLE);
    let base = PinnedBase::pin(&item).unwrap();
    let invalid = stored(json!({"cells":{"A2":{"numberFormat":{}}}})).replace("Peas", "Beans");
    assert!(apply_assistant_change(&mut item, &base, &invalid, "invalid").is_err());
    assert_eq!(item.text_form().unwrap(), TABLE);
}
