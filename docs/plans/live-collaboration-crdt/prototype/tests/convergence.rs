//! Two replicas edit a doc, a sheet and a deck concurrently, exchange individually
//! encrypted packets out of order and twice, and converge; snapshots compact the log.

mod common;

use common::*;
use crdt_spike::envelope::{open, seal, EnvelopeError, Kind};
use crdt_spike::model::*;
use yrs::{Map, ReadTxn, Text, Transact};

fn seed(a: &yrs::Doc) -> crdt_spike::envelope::Packet {
    edit(a, |t| {
        let p = push_block(t, "heading", "Plan");
        bold(t, &p, 0, 4);
        push_block(t, "paragraph", "The fox jumps.");
        let s = sheet(t);
        for (arr, id) in [
            (&s.rows, "r1"),
            (&s.rows, "r2"),
            (&s.cols, "c1"),
            (&s.cols, "c2"),
        ] {
            let n = yrs::Array::len(arr, t);
            yrs::Array::insert(arr, t, n, id);
        }
        set_cell(t, &s, "r1", "c1", "Item");
        set_cell(t, &s, "r1", "c2", "Cost");
        set_cell(t, &s, "r2", "c1", "Rent");
        set_cell(t, &s, "r2", "c2", "100");
        let d = deck(t);
        let els = add_slide(t, &d, "s1");
        add_text_element(t, &els, "e1", [100.0, 100.0, 800.0, 200.0], "Hello");
        add_slide(t, &d, "s2");
    })
}

#[test]
fn concurrent_edits_in_doc_sheet_and_deck_converge_over_encrypted_packets() {
    let a = new_replica(1);
    let b = new_replica(2);
    let seed = seed(&a);
    deliver(&b, &seed);

    let mut from_a = vec![];
    let mut from_b = vec![];
    // Same paragraph, different positions.
    from_a.push(edit(&a, |t| {
        let root = doc_root(t);
        block_text(t, &root, 1).unwrap().insert(t, 4, "quick ");
    }));
    from_b.push(edit(&b, |t| {
        let root = doc_root(t);
        let txt = block_text(t, &root, 1).unwrap();
        let n = txt.len(t);
        txt.insert(t, n - 1, " high");
    }));
    // Same cell: one value must win everywhere.
    from_a.push(edit(&a, |t| {
        let s = sheet(t);
        set_cell(t, &s, "r2", "c2", "=SUM(B1:B1)")
    }));
    from_b.push(edit(&b, |t| {
        let s = sheet(t);
        set_cell(t, &s, "r2", "c2", "250")
    }));
    // Concurrent row insert above must not re-target A's cell edit.
    from_b.push(edit(&b, |t| {
        let s = sheet(t);
        yrs::Array::insert(&s.rows, t, 1, "r3");
        set_cell(t, &s, "r3", "c1", "Food");
    }));
    // Same element property (x) conflicts; a different property (fill) is kept.
    from_a.push(edit(&a, |t| {
        let d = deck(t);
        element(t, &d, "s1", "e1").unwrap().insert(t, "x", 400.0);
    }));
    from_b.push(edit(&b, |t| {
        let d = deck(t);
        let el = element(t, &d, "s1", "e1").unwrap();
        el.insert(t, "x", 900.0);
        el.insert(t, "fill", "#ff0000");
    }));
    // Both move s2 to the front at the same time (duplicate id case).
    from_a.push(edit(&a, |t| {
        let d = deck(t);
        move_slide(t, &d, 1, 0)
    }));
    from_b.push(edit(&b, |t| {
        let d = deck(t);
        move_slide(t, &d, 1, 0)
    }));

    // Out-of-order and duplicated delivery: yrs buffers updates with missing deps.
    for p in from_b.iter().rev() {
        deliver(&a, p);
    }
    for p in from_a.iter().chain(from_a.iter()) {
        deliver(&b, p);
    }

    assert_eq!(serialise_doc(&a), serialise_doc(&b));
    assert_eq!(serialise_sheet(&a), serialise_sheet(&b));
    assert_eq!(serialise_deck(&a), serialise_deck(&b));
    assert_eq!(a.transact().state_vector(), b.transact().state_vector());

    let doc_text = serialise_doc(&a);
    assert!(doc_text.contains("heading: **Plan**"), "{doc_text}");
    assert!(doc_text.contains("The quick fox jumps high."), "{doc_text}");

    let sheet_text = serialise_sheet(&a);
    let won_formula = sheet_text.contains("| Rent | =SUM(B1:B1) |");
    let won_number = sheet_text.contains("| Rent | 250 |");
    assert!(won_formula ^ won_number, "{sheet_text}");
    assert!(sheet_text.contains("| Food |  |"), "{sheet_text}");

    let deck_text = serialise_deck(&a);
    assert!(
        deck_text.contains("x=400 ") ^ deck_text.contains("x=900 "),
        "{deck_text}"
    );
    assert!(deck_text.contains("fill=\"#ff0000\""), "{deck_text}");
    let order = {
        let mut t = a.transact_mut();
        let d = deck(&mut t);
        effective_order(&t, &d)
    };
    assert_eq!(order, vec!["s2", "s1"]);
    println!("--- converged doc\n{doc_text}--- sheet\n{sheet_text}--- deck\n{deck_text}");
}

#[test]
fn packet_for_another_item_or_kind_is_refused() {
    let p = seal(&KEY, ITEM, Kind::Update, b"update-bytes");
    assert_eq!(
        open(&KEY, "embed-0002", &p),
        Err(EnvelopeError::Unauthentic)
    );
    let mut relabelled = p.clone();
    relabelled.kind = Kind::Snapshot;
    assert_eq!(
        open(&KEY, ITEM, &relabelled),
        Err(EnvelopeError::Unauthentic)
    );
    let mut flipped = p.clone();
    let last = flipped.bytes.len() - 1;
    flipped.bytes[last] ^= 1;
    assert_eq!(open(&KEY, ITEM, &flipped), Err(EnvelopeError::Unauthentic));
}

#[test]
fn snapshot_plus_log_tail_rebuilds_the_same_state_and_is_smaller_than_the_log() {
    let a = new_replica(1);
    let mut log = vec![seed(&a)];
    // 300 keystrokes, one packet each (worst case: no batching).
    for i in 0..300u32 {
        log.push(edit(&a, |t| {
            let root = doc_root(t);
            let txt = block_text(t, &root, 1).unwrap();
            txt.insert(t, 4 + i, "x");
        }));
    }
    let snap = snapshot(&a);
    let tail: Vec<_> = (0..5)
        .map(|_| {
            edit(&a, |t| {
                let s = sheet(t);
                set_cell(t, &s, "r1", "c1", "Item!")
            })
        })
        .collect();

    let joiner = new_replica(3);
    deliver(&joiner, &snap);
    // A late joiner may also replay log entries already covered by the snapshot.
    for p in log.iter().rev().take(10).chain(tail.iter()) {
        deliver(&joiner, p);
    }
    assert_eq!(serialise_doc(&a), serialise_doc(&joiner));
    assert_eq!(serialise_sheet(&a), serialise_sheet(&joiner));

    let log_bytes: usize = log.iter().map(|p| p.bytes.len()).sum();
    println!(
        "log {} packets = {log_bytes} B ciphertext; snapshot = {} B",
        log.len(),
        snap.bytes.len()
    );
    assert!(snap.bytes.len() * 5 < log_bytes);
}
