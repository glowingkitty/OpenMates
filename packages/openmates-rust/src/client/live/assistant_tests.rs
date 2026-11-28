//! Assistant change sets: merge with human edits, conflicts, lock, one-step undo.

use super::assistant::*;
use super::support::*;
use super::{LiveItem, LiveItemKind, LocalOp, SheetOp};
use yrs::updates::decoder::Decode;
use yrs::{Doc, ReadTxn, Text, Transact, Update, Xml, XmlFragment, XmlOut};

const CODE: &str =
    "line a\nline b\nline c\nline d\nline e\nline f\nline g\nline h\nline i\nline j\n";
const SHEET: &str = "\
| Item | Qty | Price | Total |
| --- | :---: | ---: | --- |
| Apple | 2 | 1.5 | =B1*C1 |
| Pear | 3 | 2 | =B2*C2 |
| Sum |  |  | =SUM(D1:D2) |";
const DOC: &str = "<p>one</p><p>two</p><p>three</p><p>four</p><p>five</p><p>six</p><p>seven</p><p>eight</p><p>nine</p><p>ten</p>";

fn code_set(item: &mut LiveItem, line: usize, text: &str) {
    item.apply_local_op(LocalOp::CodeReplaceLines {
        start: line,
        end: line + 1,
        text: text.into(),
    })
    .unwrap();
}

fn assistant(item: &mut LiveItem, base: &PinnedBase, new: &str, turn: &str) -> AssistantOutcome {
    match apply_assistant_change(item, base, new, turn).unwrap() {
        AssistantResult::Applied(outcome) => outcome,
        AssistantResult::Busy => panic!("unexpected Busy"),
    }
}

fn with_line(text: &str, line: usize, new: &str) -> String {
    let mut lines: Vec<&str> = text.split('\n').collect();
    lines[line] = new;
    lines.join("\n")
}

#[test]
fn code_user_keeps_typing_elsewhere_and_both_edits_stay() {
    let mut item = create(LiveItemKind::Code, CODE);
    let base = PinnedBase::pin(&item).unwrap();
    code_set(&mut item, 0, "HUMAN a");
    let out = assistant(&mut item, &base, &with_line(CODE, 7, "BOT h"), "t1");
    assert_eq!(out.applied_hunks, 1);
    assert!(out.same_spot.is_empty() && out.target_deleted.is_empty() && !out.needs_recheck);
    assert_eq!(out.updates.len(), 1);
    let text = item.text_form().unwrap();
    assert!(text.starts_with("HUMAN a\n") && text.contains("BOT h\n") && !text.contains("line h"));
}

#[test]
fn code_same_line_changed_is_same_spot_and_human_text_is_intact() {
    let mut item = create(LiveItemKind::Code, CODE);
    let base = PinnedBase::pin(&item).unwrap();
    code_set(&mut item, 1, "human b");
    let out = assistant(&mut item, &base, &with_line(CODE, 1, "bot b"), "t1");
    assert_eq!(out.applied_hunks, 0);
    assert_eq!(out.same_spot.len(), 1);
    assert_eq!(out.same_spot[0].assistant_value, "bot b\n");
    assert_eq!(out.same_spot[0].human_value, "human b\n");
    assert!(out.updates.is_empty());
    assert!(item.text_form().unwrap().contains("human b\n"));
}

#[test]
fn code_deleted_target_is_dropped_and_not_re_added() {
    let mut item = create(LiveItemKind::Code, CODE);
    let base = PinnedBase::pin(&item).unwrap();
    item.apply_local_op(LocalOp::CodeReplaceLines {
        start: 1,
        end: 2,
        text: String::new(),
    })
    .unwrap();
    let out = assistant(&mut item, &base, &with_line(CODE, 1, "bot b"), "t1");
    assert_eq!(out.target_deleted, ["line 2"]);
    assert_eq!(out.applied_hunks, 0);
    let text = item.text_form().unwrap();
    assert!(!text.contains("bot b") && !text.contains("line b"));
}

#[test]
fn large_human_changes_elsewhere_ask_for_a_recheck() {
    let mut item = create(LiveItemKind::Code, CODE);
    let base = PinnedBase::pin(&item).unwrap();
    for line in 0..4 {
        code_set(&mut item, line, "human");
    }
    let out = assistant(&mut item, &base, &with_line(CODE, 9, "bot j"), "t1");
    assert!(out.needs_recheck);
    assert_eq!(out.applied_hunks, 1);
}

#[test]
fn one_undo_removes_the_whole_assistant_edit_and_keeps_the_human_text() {
    let mut item = create(LiveItemKind::Code, CODE);
    let base = PinnedBase::pin(&item).unwrap();
    let new = with_line(
        &with_line(&with_line(CODE, 2, "bot c"), 5, "bot f"),
        8,
        "bot i",
    );
    let out = assistant(&mut item, &base, &new, "t1");
    assert_eq!(out.applied_hunks, 3);
    code_set(&mut item, 0, "HUMAN a");
    let update = undo_assistant(&mut item, "t1").unwrap();
    assert!(update.is_some());
    assert_eq!(item.text_form().unwrap(), with_line(CODE, 0, "HUMAN a"));
}

#[test]
fn a_second_change_set_is_busy_until_the_first_is_released() {
    let mut item = create(LiveItemKind::Code, CODE);
    let base = PinnedBase::pin(&item).unwrap();
    assistant(&mut item, &base, &with_line(CODE, 2, "bot c"), "t1");
    let second = with_line(CODE, 6, "other g");
    assert_eq!(
        apply_assistant_change(&mut item, &base, &second, "t2").unwrap(),
        AssistantResult::Busy
    );
    finish_assistant_change(&mut item, "t1");
    let out = assistant(&mut item, &base, &second, "t2");
    assert_eq!(out.applied_hunks, 1);
    let text = item.text_form().unwrap();
    assert!(text.contains("bot c") && text.contains("other g"));
}

#[test]
fn code_hunks_apply_while_another_replica_inserts_lines_above_and_replicas_converge() {
    let mut items = replicas(LiveItemKind::Code, CODE, 2);
    let base = PinnedBase::pin(&items[0]).unwrap();
    items[1]
        .apply_local_op(LocalOp::CodeReplaceLines {
            start: 0,
            end: 0,
            text: "above 1\nabove 2".into(),
        })
        .unwrap();
    assistant(&mut items[0], &base, &with_line(CODE, 7, "BOT h"), "t1");
    exchange(&mut items, in_order);
    let text = assert_converged(&items);
    assert!(text.starts_with("above 1\nabove 2\nline a\n"));
    assert!(text.contains("BOT h\n") && !text.contains("line h"));
}

fn mirror_edit(item: &mut LiveItem, edit: impl FnOnce(&Doc, &yrs::XmlFragmentRef)) {
    let doc = Doc::new();
    let fragment = doc.get_or_insert_xml_fragment("default");
    let state = item.encode_update_since(&[0]).unwrap();
    doc.transact_mut()
        .apply_update(Update::decode_v1(&state).unwrap())
        .unwrap();
    let before = doc.transact().state_vector();
    edit(&doc, &fragment);
    let update = doc.transact().encode_diff_v1(&before);
    item.apply_mirror_update(&update).unwrap();
}

fn append_to_block(item: &mut LiveItem, block: u32, suffix: &str) {
    mirror_edit(item, |doc, fragment| {
        let mut txn = doc.transact_mut();
        let Some(XmlOut::Element(el)) = fragment.get(&txn, block) else {
            panic!("no block")
        };
        let Some(XmlOut::Text(text)) = el.get(&txn, 0) else {
            panic!("no text")
        };
        let len = text.len(&txn);
        text.insert(&mut txn, len, suffix);
    });
}

fn doc_with(index: usize, html: &str) -> String {
    let mut blocks: Vec<String> = DOC.split_inclusive("</p>").map(str::to_string).collect();
    blocks[index] = html.to_string();
    blocks.concat()
}

#[test]
fn doc_edit_in_another_paragraph_and_in_the_same_paragraph() {
    let mut item = create(LiveItemKind::Doc, DOC);
    let base = PinnedBase::pin(&item).unwrap();
    append_to_block(&mut item, 8, "!");
    let out = assistant(&mut item, &base, &doc_with(0, "<p>ONE</p>"), "t1");
    assert_eq!(out.applied_hunks, 1);
    let text = item.text_form().unwrap();
    assert!(text.starts_with("<p>ONE</p><p>two</p>") && text.contains("<p>nine!</p>"));

    finish_assistant_change(&mut item, "t1");
    let base = PinnedBase::pin(&item).unwrap();
    append_to_block(&mut item, 3, " human");
    let out = assistant(&mut item, &base, &doc_with(3, "<p>FOUR</p>"), "t2");
    assert_eq!(out.same_spot.len(), 1);
    assert_eq!(out.same_spot[0].human_value, "<p>four human</p>");
    assert!(item.text_form().unwrap().contains("<p>four human</p>"));
}

#[test]
fn doc_deleted_section_is_dropped_and_undo_restores_the_human_text() {
    let mut item = create(LiveItemKind::Doc, DOC);
    let base = PinnedBase::pin(&item).unwrap();
    mirror_edit(&mut item, |doc, fragment| {
        fragment.remove_range(&mut doc.transact_mut(), 2, 1)
    });
    let out = assistant(&mut item, &base, &doc_with(2, "<p>THREE</p>"), "t1");
    assert_eq!(out.target_deleted, ["block 3"]);
    assert!(out.updates.is_empty());
    assert!(!item.text_form().unwrap().contains("THREE"));
    let out = assistant(&mut item, &base, &doc_with(5, "<p>SIX</p>"), "t2");
    assert_eq!(out.applied_hunks, 1);
    assert!(item.text_form().unwrap().contains("<p>SIX</p>"));
    undo_assistant(&mut item, "t2").unwrap();
    let text = item.text_form().unwrap();
    assert!(text.contains("<p>six</p>") && !text.contains("<p>three</p>"));
}

#[test]
fn sheet_column_recalculation_turns_the_human_changed_cell_into_a_suggestion() {
    let mut item = create(LiveItemKind::Sheet, SHEET);
    let base = PinnedBase::pin(&item).unwrap();
    item.apply_local_op(LocalOp::Sheet(SheetOp::SetCell {
        row_id: "r2".into(),
        col_id: "c4".into(),
        value: "99".into(),
    }))
    .unwrap();
    let new = SHEET
        .replace("=B1*C1", "=B1*C1*2")
        .replace("=B2*C2", "=B2*C2*2");
    let out = assistant(&mut item, &base, &new, "t1");
    assert_eq!(out.applied_hunks, 1);
    assert_eq!(out.suggestions.len(), 1);
    assert_eq!(out.suggestions[0].anchor, "r2:c4");
    assert_eq!(out.suggestions[0].assistant_value, "=B2*C2*2");
    assert_eq!(out.suggestions[0].human_value, "99");
    let text = item.text_form().unwrap();
    assert!(text.contains("=B1*C1*2") && text.contains("| Pear | 3 | 2 | 99 |"));
}

#[test]
fn sheet_formula_that_refers_to_a_deleted_row_renders_ref_and_undo_is_one_step() {
    let mut item = create(LiveItemKind::Sheet, SHEET);
    let base = PinnedBase::pin(&item).unwrap();
    let new = SHEET
        .replace("=B2*C2", "=B1*C1")
        .replace("| Apple | 2 |", "| Apple | 20 |");
    let out = assistant(&mut item, &base, &new, "t1");
    assert_eq!(out.applied_hunks, 2);
    item.apply_local_op(LocalOp::Sheet(SheetOp::DeleteRow {
        row_id: "r1".into(),
    }))
    .unwrap();
    assert!(item.text_form().unwrap().contains("#REF!"));
    // Undo removes the assistant edits (the cells that still exist) and keeps the human row delete.
    undo_assistant(&mut item, "t1").unwrap();
    let text = item.text_form().unwrap();
    assert!(!text.contains("Apple") && !text.contains("20") && text.contains("Pear"));
}
