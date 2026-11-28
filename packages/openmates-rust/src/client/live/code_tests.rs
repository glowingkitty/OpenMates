//! Code adapter: round trip, minimal UTF-16 range edits, concurrent inserts.

use super::support::*;
use super::{LiveItemKind, LocalOp};

const FILE: &str = "fn main() {\n    println!(\"hi\");\n}\n";

fn edit(item: &mut super::LiveItem, start: usize, end: usize, text: &str) {
    item.apply_local_op(LocalOp::CodeReplaceLines {
        start,
        end,
        text: text.into(),
    })
    .unwrap();
}

#[test]
fn text_round_trips_including_astral_characters() {
    for text in [FILE, "", "a\r\nb", "emoji 😀 and é\n"] {
        assert_eq!(create(LiveItemKind::Code, text).text_form().unwrap(), text);
    }
}

#[test]
fn set_text_edits_a_minimal_range_and_keeps_surrogate_pairs() {
    let mut items = replicas(LiveItemKind::Code, "a😀b\nsecond", 2);
    // Both replicas edit different lines of the same file.
    items[0]
        .apply_local_op(LocalOp::CodeSetText("a😁b\nsecond".into()))
        .unwrap();
    items[1]
        .apply_local_op(LocalOp::CodeSetText("a😀b\nsecond line".into()))
        .unwrap();
    exchange(&mut items, in_order);
    assert_eq!(assert_converged(&items), "a😁b\nsecond line");
}

#[test]
fn concurrent_inserts_at_different_places_are_both_kept() {
    let mut items = replicas(LiveItemKind::Code, FILE, 3);
    edit(&mut items[0], 0, 0, "// header");
    edit(&mut items[1], 2, 3, "    return;\n}");
    exchange(&mut items, reversed);
    let text = assert_converged(&items);
    assert!(text.starts_with("// header\nfn main"));
    assert!(text.contains("    return;"));
}

#[test]
fn line_range_outside_the_file_is_refused() {
    let mut item = create(LiveItemKind::Code, "a\nb");
    let result = item.apply_local_op(LocalOp::CodeReplaceLines {
        start: 3,
        end: 9,
        text: "x".into(),
    });
    assert!(result.is_err());
    assert_eq!(item.text_form().unwrap(), "a\nb");
}
