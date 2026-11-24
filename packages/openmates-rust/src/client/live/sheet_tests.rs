//! Sheet adapter: markdown round trip, A1 formulas stored with ids, #REF!, concurrency.

use super::support::*;
use super::{LiveError, LiveItem, LiveItemKind, LocalOp, SheetOp};

const SHEET: &str = "\
| Item | Qty | Price | Total |
| --- | :---: | ---: | --- |
| Apple | 2 | 1.5 | =B1*C1 |
| Pear | 3 | 2 | =B2*C2 |
| Sum |  |  | =SUM(D1:D2) |";

fn op(item: &mut LiveItem, op: SheetOp) -> Option<String> {
    item.apply_local_op(LocalOp::Sheet(op)).unwrap().new_id
}

fn set(item: &mut LiveItem, row: &str, col: &str, value: &str) {
    op(
        item,
        SheetOp::SetCell {
            row_id: row.into(),
            col_id: col.into(),
            value: value.into(),
        },
    );
}

#[test]
fn canonical_markdown_round_trips() {
    assert_eq!(
        create(LiveItemKind::Sheet, SHEET).text_form().unwrap(),
        SHEET
    );
    assert!(matches!(
        LiveItem::create(LiveItemKind::Sheet, ID, &KEY, 1, "just text"),
        Err(LiveError::InvalidText(_))
    ));
}

#[test]
fn deleting_a_row_or_column_renders_ref_errors_but_keeps_other_formulas() {
    let mut item = create(LiveItemKind::Sheet, SHEET);
    op(
        &mut item,
        SheetOp::DeleteRow {
            row_id: "r1".into(),
        },
    );
    let text = item.text_form().unwrap();
    assert!(text.contains("| Pear | 3 | 2 | =B1*C1 |"));
    assert!(text.contains("=SUM(#REF!:D1)"));
    op(
        &mut item,
        SheetOp::DeleteCol {
            col_id: "c2".into(),
        },
    );
    let text = item.text_form().unwrap();
    assert!(text.contains("| Pear | 2 | =#REF!*B1 |"));
}

#[test]
fn inserting_rows_and_columns_shifts_a1_references_without_rewriting_formulas() {
    let mut item = create(LiveItemKind::Sheet, SHEET);
    let new_row = op(&mut item, SheetOp::InsertRow { after_row_id: None }).unwrap();
    assert!(
        item.text_form()
            .unwrap()
            .contains("| Pear | 3 | 2 | =B3*C3 |")
    );
    op(&mut item, SheetOp::InsertCol { after_col_id: None });
    let text = item.text_form().unwrap();
    assert!(text.contains("| Apple | 2 | 1.5 | =C2*D2 |"));
    set(&mut item, &new_row, "c1", "New");
    assert!(
        item.text_form().unwrap().contains("|  | New |")
            || item.text_form().unwrap().contains("|  |  | New")
    );
    assert!(matches!(
        item.apply_local_op(LocalOp::Sheet(SheetOp::SetCell {
            row_id: "r1".into(),
            col_id: "c1".into(),
            value: "a|b".into()
        })),
        Err(LiveError::InvalidCell(_))
    ));
    assert!(matches!(
        item.apply_local_op(LocalOp::Sheet(SheetOp::DeleteRow {
            row_id: "nope".into()
        })),
        Err(LiveError::RowNotFound(_))
    ));
}

#[test]
fn different_cells_are_kept_and_the_same_cell_has_one_winner() {
    let mut items = replicas(LiveItemKind::Sheet, SHEET, 3);
    set(&mut items[0], "r1", "c1", "Apricot");
    set(&mut items[1], "r2", "c1", "Plum");
    set(&mut items[0], "r3", "c2", "10");
    set(&mut items[1], "r3", "c2", "20");
    set(&mut items[2], "r3", "c2", "30");
    exchange(&mut items, reversed);
    let text = assert_converged(&items);
    assert!(text.contains("| Apricot |") && text.contains("| Plum |"));
    assert_eq!(
        ["10", "20", "30"]
            .iter()
            .filter(|v| text.contains(&format!("| Sum | {v} |")))
            .count(),
        1
    );
}

#[test]
fn concurrent_structure_changes_converge() {
    let mut items = replicas(LiveItemKind::Sheet, SHEET, 2);
    op(
        &mut items[0],
        SheetOp::DeleteRow {
            row_id: "r2".into(),
        },
    );
    op(
        &mut items[1],
        SheetOp::DeleteRow {
            row_id: "r2".into(),
        },
    );
    op(
        &mut items[1],
        SheetOp::InsertRow {
            after_row_id: Some("r1".into()),
        },
    );
    exchange(&mut items, in_order);
    let text = assert_converged(&items);
    assert!(!text.contains("Pear"));
    assert_eq!(items[0].sheet_ids().unwrap().0.len(), 3);
}
