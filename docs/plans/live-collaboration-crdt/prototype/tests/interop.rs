//! Wire compatibility: a yrs state is read by Yjs 13 (JS), Yjs edits come back and
//! merge in yrs, and UTF-16 offsets agree across both runtimes (needs `npm i` in js/).

mod common;

use common::*;
use crdt_spike::model::*;
use std::path::Path;
use std::process::Command;
use yrs::updates::decoder::Decode;
use yrs::{Array, Text, Transact, Update};

#[test]
fn yrs_state_round_trips_through_yjs_with_utf16_offsets() {
    let js = Path::new(env!("CARGO_MANIFEST_DIR")).join("js");
    assert!(
        js.join("node_modules/yjs").exists(),
        "run `npm install` in {js:?} first"
    );

    let a = new_replica(1);
    let _seed = edit(&a, |t| {
        push_block(t, "heading", "Plan");
        push_block(t, "paragraph", "The fox jumps.");
        let s = sheet(t);
        s.rows.insert(t, 0, "r1");
        s.cols.insert(t, 0, "c1");
        s.cols.insert(t, 1, "c2");
        set_cell(t, &s, "r1", "c1", "21");
        let d = deck(t);
        let els = add_slide(t, &d, "s1");
        add_text_element(t, &els, "e1", [0.0, 0.0, 100.0, 50.0], "Hi");
    });

    let dir = std::env::temp_dir().join(format!("om-crdt-interop-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let (inp, out) = (dir.join("rust.bin"), dir.join("js.bin"));
    std::fs::write(&inp, state(&a)).unwrap();

    let res = Command::new("node")
        .arg(js.join("interop.mjs"))
        .arg(&inp)
        .arg(&out)
        .output()
        .unwrap();
    assert!(
        res.status.success(),
        "{}",
        String::from_utf8_lossy(&res.stderr)
    );
    let seen: serde_json::Value = serde_json::from_slice(&res.stdout).unwrap();
    println!("Yjs sees: {seen}");
    assert_eq!(
        seen["doc"],
        "<heading>Plan</heading><paragraph>The fox jumps.</paragraph>"
    );
    assert_eq!(seen["cells"]["r1:c1"], "21");
    assert_eq!(seen["order"][0], "s1");

    let js_update = std::fs::read(&out).unwrap();
    a.transact_mut()
        .apply_update(Update::decode_v1(&js_update).unwrap())
        .unwrap();
    // Rust inserts right after the emoji + space: index 3 in UTF-16 code units.
    {
        let mut t = a.transact_mut();
        let root = doc_root(&mut t);
        block_text(&t, &root, 1).unwrap().insert(&mut t, 3, "red ");
    }
    let doc_text = serialise_doc(&a);
    assert!(
        doc_text.contains("paragraph: 🙂 red The fox jumps!."),
        "{doc_text}"
    );
    assert!(serialise_sheet(&a).contains("| 21 | =r1c1*2 |"));
    assert!(
        serialise_deck(&a).contains("y=640 "),
        "{}",
        serialise_deck(&a)
    );
    std::fs::remove_dir_all(&dir).ok();
}
