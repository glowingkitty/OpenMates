//! Convergence across replicas: three-way exchange in different orders, offline edits merged
//! through state vectors and a deterministic property test over random operation sequences.

use super::support::*;
use super::{LiveItem, LiveItemKind, LocalOp, SheetOp};

fn code_edit(rng: &mut Rng, item: &mut LiveItem) {
    let text = item.text_form().unwrap();
    let lines = text.split('\n').count();
    let start = rng.below(lines + 1);
    let end = (start + rng.below(3)).min(lines);
    let words = ["alpha", "b", "", "é😀", "line two", "x y z"];
    let replacement = words[rng.below(words.len())].to_string();
    let _ = item.apply_local_op(LocalOp::CodeReplaceLines {
        start,
        end,
        text: replacement,
    });
}

fn sheet_edit(rng: &mut Rng, item: &mut LiveItem) {
    let (rows, cols) = item.sheet_ids().unwrap();
    let pick = |rng: &mut Rng, list: &[String]| list.get(rng.below(list.len())).cloned();
    let op = match rng.below(8) {
        0 if rows.len() > 1 => pick(rng, &rows).map(|row_id| SheetOp::DeleteRow { row_id }),
        1 if cols.len() > 1 => pick(rng, &cols).map(|col_id| SheetOp::DeleteCol { col_id }),
        2 => Some(SheetOp::InsertRow {
            after_row_id: pick(rng, &rows),
        }),
        3 => Some(SheetOp::InsertCol {
            after_col_id: pick(rng, &cols),
        }),
        _ => match (pick(rng, &rows), pick(rng, &cols)) {
            (Some(row_id), Some(col_id)) => {
                let value = ["1", "two", "", "=A1+B1", "=SUM(A1:B2)"][rng.below(5)];
                Some(SheetOp::SetCell {
                    row_id,
                    col_id,
                    value: value.to_string(),
                })
            }
            _ => None,
        },
    };
    if let Some(op) = op {
        let _ = item.apply_local_op(LocalOp::Sheet(op));
    }
}

fn run_property(kind: LiveItemKind, seed_text: &str, edit: fn(&mut Rng, &mut LiveItem)) {
    for seed in 1..=12u64 {
        let mut rng = Rng(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1);
        let mut items = replicas(kind, seed_text, 3);
        for _round in 0..6 {
            for item in items.iter_mut() {
                for _ in 0..rng.below(4) {
                    edit(&mut rng, item);
                }
            }
            let mut pending = take_outboxes(&mut items);
            rng.shuffle(&mut pending);
            for (seq, (from, entry)) in pending.iter().enumerate() {
                for (index, item) in items.iter_mut().enumerate() {
                    if index != *from {
                        item.apply_remote(seq as u64 + 1, &entry.sealed).unwrap();
                    }
                }
            }
            assert_converged(&items);
        }
    }
}

#[test]
fn random_code_edits_converge_on_three_replicas() {
    run_property(LiveItemKind::Code, "one\ntwo\nthree\nfour", code_edit);
}

#[test]
fn random_sheet_operations_converge_on_three_replicas() {
    run_property(
        LiveItemKind::Sheet,
        "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |",
        sheet_edit,
    );
}

#[test]
fn delivery_order_does_not_matter_for_three_replicas() {
    let mut texts = Vec::new();
    for order in 0..3 {
        let mut items = replicas(LiveItemKind::Code, "a\nb\nc", 3);
        for (i, item) in items.iter_mut().enumerate() {
            let text = format!("edit{i}");
            item.apply_local_op(LocalOp::CodeReplaceLines {
                start: i,
                end: i,
                text,
            })
            .unwrap();
        }
        match order {
            0 => exchange(&mut items, in_order),
            1 => exchange(&mut items, reversed),
            _ => exchange(&mut items, |l| l.rotate_left(1)),
        }
        texts.push(assert_converged(&items));
    }
    assert_eq!(texts[0], texts[1]);
    assert_eq!(texts[1], texts[2]);
    assert!(texts[0].contains("edit0") && texts[0].contains("edit1") && texts[0].contains("edit2"));
}

#[test]
fn offline_replica_merges_through_state_vectors() {
    let mut items = replicas(LiveItemKind::Code, "one\ntwo\nthree", 2);
    // B is offline: its edits stay in its outbox while A keeps editing.
    items[1]
        .apply_local_op(LocalOp::CodeReplaceLines {
            start: 2,
            end: 3,
            text: "THREE".into(),
        })
        .unwrap();
    items[0]
        .apply_local_op(LocalOp::CodeReplaceLines {
            start: 0,
            end: 1,
            text: "ONE".into(),
        })
        .unwrap();
    let offline_state = items[1].state_vector();
    let missing = items[0].encode_update_since(&offline_state).unwrap();
    // On reconnect B receives what it lacks as update bytes, then sends its outbox.
    items[1].merge_update(&missing).unwrap();
    assert_eq!(items[1].outbox().len(), 1, "only B's own edit is pending");
    let for_a = items[1]
        .encode_update_since(&items[0].state_vector())
        .unwrap();
    items[0].merge_update(&for_a).unwrap();
    assert_eq!(assert_converged(&items), "ONE\ntwo\nTHREE");
}
