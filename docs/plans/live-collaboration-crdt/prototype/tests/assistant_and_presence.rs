//! Assistant diff merges as a minimal change set that keeps concurrent member edits,
//! is one undo step for the requester, and presence travels encrypted and ephemeral.

mod common;

use common::*;
use crdt_spike::diff_apply::change_set_from_text;
use crdt_spike::envelope::{open, seal, Kind};
use crdt_spike::model::*;
use yrs::sync::{Awareness, AwarenessUpdate};
use yrs::undo::{Options as UndoOptions, UndoManager};
use yrs::updates::decoder::Decode;
use yrs::updates::encoder::Encode;
use yrs::{Assoc, IndexedSequence, ReadTxn, StickyIndex, Text, Transact, XmlFragment};

fn lines(doc: &yrs::Doc) -> Vec<String> {
    doc_plain_lines(&doc.transact())
}

fn base_doc() -> (yrs::Doc, yrs::Doc) {
    let a = new_replica(1);
    let b = new_replica(2);
    let p = edit(&a, |t| {
        push_block(t, "heading", "Project plan");
        push_block(t, "paragraph", "We ship in March.");
        push_block(t, "paragraph", "Budget is small.");
    });
    deliver(&b, &p);
    (a, b)
}

#[test]
fn assistant_diff_keeps_edits_members_made_after_the_assistant_read_the_text() {
    let (a, b) = base_doc();
    // The version the assistant reads; the server applies its unified diff to this text.
    let base = state(&a);
    let patched: Vec<String> = [
        "Project plan",
        "We ship in April.",
        "Budget is small.",
        "Risks: none.",
    ]
    .map(String::from)
    .to_vec();

    // Meanwhile member B types in both paragraphs the assistant touches or borders.
    let b_edit = edit(&b, |t| {
        let root = doc_root(t);
        block_text(t, &root, 1).unwrap().insert(t, 0, "Team: ");
        let p2 = block_text(t, &root, 2).unwrap();
        let n = p2.len(t);
        p2.insert(t, n - 1, " but fine");
    });
    deliver(&a, &b_edit);

    // Requester A turns the patched text into a change set against the base fork.
    let change = change_set_from_text(&base, &patched, 0xA551_0001).unwrap();
    let packet = seal(&KEY, ITEM, Kind::Update, &change);
    deliver_with(&a, &packet, "assistant");
    deliver(&b, &packet);

    let expected = [
        "Project plan",
        "Team: We ship in April.",
        "Budget is small but fine.",
        "Risks: none.",
    ];
    assert_eq!(lines(&a), expected);
    assert_eq!(lines(&b), expected);
    println!("change set: {} B plaintext for a 4-block doc", change.len());

    // Contrast: a naive full replace with the patched text drops B's work.
    let naive = new_replica(9);
    deliver(&naive, &snapshot(&a));
    {
        let mut t = naive.transact_mut();
        let root = doc_root(&mut t);
        let n = root.len(&t);
        root.remove_range(&mut t, 0, n);
        for l in &patched {
            push_block(&mut t, "paragraph", l);
        }
    }
    assert!(!lines(&naive)
        .iter()
        .any(|l| l.contains("Team:") || l.contains("but fine")));
}

#[test]
fn assistant_change_is_one_undo_step_for_the_requester_only() {
    let (a, b) = base_doc();
    let base = state(&a);
    let mut opts = UndoOptions::default();
    opts.capture_timeout_millis = 0; // every transaction is its own step in this test
    let mut undo: UndoManager<()> = UndoManager::with_options(opts);
    let root = doc_root(&mut a.transact_mut());
    undo.expand_scope(&a, &root);
    undo.include_origin("local");
    undo.include_origin("assistant");

    // A's own typing is a step; B's concurrent typing is not in A's history.
    deliver(
        &b,
        &edit(&a, |t| {
            let root = doc_root(t);
            block_text(t, &root, 0).unwrap().insert(t, 12, " v2");
        }),
    );
    deliver(
        &a,
        &edit(&b, |t| {
            let root = doc_root(t);
            block_text(t, &root, 1).unwrap().insert(t, 0, "Team: ");
        }),
    );

    // Multi-hunk assistant change (edit + insert + edit) arrives as one transaction.
    let patched: Vec<String> = [
        "Project plan",
        "We ship in April.",
        "New line.",
        "Budget is large.",
    ]
    .map(String::from)
    .to_vec();
    let change = change_set_from_text(&base, &patched, 0xA551_0002).unwrap();
    let p = seal(&KEY, ITEM, Kind::Update, &change);
    deliver_with(&a, &p, "assistant");
    deliver(&b, &p);
    assert_eq!(
        lines(&a),
        [
            "Project plan v2",
            "Team: We ship in April.",
            "New line.",
            "Budget is large."
        ]
    );

    // One undo removes the whole assistant change and nothing else.
    let sv = a.transact().state_vector();
    assert!(undo.undo_blocking());
    assert_eq!(
        lines(&a),
        [
            "Project plan v2",
            "Team: We ship in March.",
            "Budget is small."
        ]
    );
    // The undo is an ordinary update that peers receive.
    let undo_update = a.transact().encode_diff_v1(&sv);
    deliver(&b, &seal(&KEY, ITEM, Kind::Update, &undo_update));
    assert_eq!(lines(&b), lines(&a));
    // The next undo step is A's own typing, not B's.
    assert!(undo.undo_blocking());
    assert_eq!(lines(&a)[0], "Project plan");
    assert_eq!(lines(&a)[1], "Team: We ship in March.");
}

#[test]
fn presence_is_encrypted_relative_to_content_and_vanishes_on_leave() {
    let (a, b) = base_doc();
    // A's cursor before "March" as a sticky index: it survives B's concurrent typing.
    let cursor = {
        let t = a.transact();
        let root = t.get_xml_fragment(DOC_ROOT).unwrap();
        block_text(&t, &root, 1)
            .unwrap()
            .sticky_index(&t, 11, Assoc::After)
            .unwrap()
    };
    let mut aw_a = Awareness::new(a.clone());
    let mut aw_b = Awareness::new(b.clone());
    aw_a.set_local_state(serde_json::json!({
        "user": {"name": "Ada", "color": "#e91e63"},
        "cursor": {"block": 1, "anchor": cursor.encode_v1()},
    }))
    .unwrap();

    // Presence rides the same envelope with kind Presence; the server relays, never stores.
    let pkt = seal(
        &KEY,
        ITEM,
        Kind::Presence,
        &aw_a.update().unwrap().encode_v1(),
    );
    let upd = AwarenessUpdate::decode_v1(&open(&KEY, ITEM, &pkt).unwrap()).unwrap();
    aw_b.apply_update(upd).unwrap();
    let seen: serde_json::Value = aw_b.state(aw_a.client_id()).unwrap();
    assert_eq!(seen["user"]["name"], "Ada");

    // B types before A's cursor; the decoded anchor still points before "March".
    deliver(
        &a,
        &edit(&b, |t| {
            let root = doc_root(t);
            block_text(t, &root, 1).unwrap().insert(t, 0, "Team: ");
        }),
    );
    let bytes: Vec<u8> = serde_json::from_value(seen["cursor"]["anchor"].clone()).unwrap();
    let anchor = StickyIndex::decode_v1(&bytes).unwrap();
    let off = anchor.get_offset(&b.transact()).unwrap();
    assert_eq!(off.index, 17);

    // Leaving clears the state for everyone.
    // `update()` omits removed states, so the leave packet names the client explicitly
    // (same as y-protocols `removeAwarenessStates`).
    aw_a.clean_local_state();
    let leave = aw_a.update_with_clients([aw_a.client_id()]).unwrap();
    let pkt = seal(&KEY, ITEM, Kind::Presence, &leave.encode_v1());
    aw_b.apply_update(AwarenessUpdate::decode_v1(&open(&KEY, ITEM, &pkt).unwrap()).unwrap())
        .unwrap();
    assert!(aw_b.state::<serde_json::Value>(aw_a.client_id()).is_none());
}
