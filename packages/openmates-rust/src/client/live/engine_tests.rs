//! Engine: open from snapshot and log, outbox, ack, rekey, snapshots, wrong-kind refusals.

use super::engine::{LiveItem, LocalOp, RemoteUpdate};
use super::support::*;
use super::{LiveError, LiveItemKind};

#[test]
fn kind_wire_strings_round_trip() {
    for kind in [
        LiveItemKind::Doc,
        LiveItemKind::Sheet,
        LiveItemKind::Deck,
        LiveItemKind::Code,
    ] {
        assert_eq!(LiveItemKind::parse(kind.as_str()), Ok(kind));
    }
    assert!(matches!(
        LiveItemKind::parse("pdf"),
        Err(LiveError::UnknownKind(_))
    ));
}

#[test]
fn open_from_snapshot_plus_log_and_outbox_ack() {
    let mut a = create(LiveItemKind::Code, "one\ntwo\n");
    assert_eq!(a.outbox().len(), 1);
    let first = a.outbox()[0].clone();
    a.ack(&first.client_msg_id, 1);
    assert!(a.outbox().is_empty());
    assert_eq!(a.head_seq(), 1);
    // The server's snapshot covers the acknowledged position.
    let snapshot = snapshot_of(&a);

    let change = a
        .apply_local_op(LocalOp::CodeReplaceLines {
            start: 1,
            end: 2,
            text: "TWO".into(),
        })
        .expect("edits");
    let update = change.update.expect("changed");
    let log = [RemoteUpdate {
        seq: 2,
        sealed: update.sealed.clone(),
    }];
    let b = LiveItem::open(LiveItemKind::Code, ID, &KEY, 1, Some(&snapshot), &log).expect("opens");
    assert_eq!(b.text_form().unwrap(), "one\nTWO\n");
    assert_eq!(b.head_seq(), 2);
    // No-op edits produce no update.
    let same = a
        .apply_local_op(LocalOp::CodeSetText("one\nTWO\n".into()))
        .unwrap();
    assert!(same.update.is_none());
}

#[test]
fn the_head_stops_below_a_missing_position_until_it_arrives() {
    let mut a = create(LiveItemKind::Code, "x");
    let first = a.outbox()[0].clone();
    a.ack(&first.client_msg_id, 3);
    assert_eq!(a.head_seq(), 0, "positions 1 and 2 are still missing");
    assert!(a.has_seq(3) && !a.has_seq(2));
    let peer_update = |text: &str| {
        let mut p = create(LiveItemKind::Code, text);
        p.outbox()[0].sealed.clone()
    };
    a.apply_remote(1, &peer_update("y")).unwrap();
    assert_eq!(a.head_seq(), 1);
    a.apply_remote(2, &peer_update("z")).unwrap();
    assert_eq!(
        a.head_seq(),
        3,
        "the hole is filled, so the head moves over 3 too"
    );
}

#[test]
fn outbox_survives_a_restart() {
    let mut a = create(LiveItemKind::Code, "x");
    let snapshot_before = snapshot_of(&a);
    let pending = a.outbox().to_vec();
    // Restart: the server never saw the initial update, so a fresh replica gets it back.
    let mut restarted = LiveItem::open(LiveItemKind::Code, ID, &KEY, 1, None, &[]).unwrap();
    restarted.restore_outbox(pending).unwrap();
    assert_eq!(restarted.text_form().unwrap(), "x");
    assert_eq!(restarted.outbox().len(), 1);
    let _ = snapshot_before;
    a.ack("nothing", 1);
}

#[test]
fn rotation_reseals_the_outbox_under_the_new_epoch() {
    let mut a = create(LiveItemKind::Code, "hello");
    let new_key = [3u8; 32];
    a.rekey(&new_key, 2).unwrap();
    let entry = a.outbox()[0].clone();
    assert_eq!(entry.epoch, 2);
    assert!(matches!(
        super::open_packet(
            &KEY,
            ID,
            LiveItemKind::Code,
            2,
            super::PacketType::Update,
            &entry.sealed
        ),
        Err(LiveError::Authentication)
    ));
    let b = LiveItem::open(
        LiveItemKind::Code,
        ID,
        &new_key,
        2,
        None,
        &[RemoteUpdate {
            seq: 1,
            sealed: entry.sealed,
        }],
    )
    .unwrap();
    assert_eq!(b.text_form().unwrap(), "hello");
}

#[test]
fn reopening_after_rotation_replays_and_reseals_older_packets() {
    let mut a = create(LiveItemKind::Code, "recipe");
    let old_snapshot = snapshot_of(&a);
    a.ack(&a.outbox()[0].client_msg_id.clone(), 1);
    a.apply_local_op(LocalOp::CodeSetText("recipe and notes".into()))
        .unwrap();
    let pending = a.outbox().to_vec();

    let current = [3; 32];
    let mut reopened = LiveItem::open_with_history(
        LiveItemKind::Code,
        ID,
        &current,
        2,
        &[(1, zeroize::Zeroizing::new(KEY))],
        Some(&old_snapshot),
        &[],
    )
    .unwrap();
    reopened.restore_outbox(pending).unwrap();
    assert_eq!(reopened.text_form().unwrap(), "recipe and notes");
    assert_eq!(reopened.outbox()[0].epoch, 2);
    assert!(matches!(
        super::open_packet(
            &KEY,
            ID,
            LiveItemKind::Code,
            2,
            super::PacketType::Update,
            &reopened.outbox()[0].sealed
        ),
        Err(LiveError::Authentication)
    ));
}

#[test]
fn stale_epoch_and_foreign_item_are_typed_errors() {
    let a = create(LiveItemKind::Code, "hello");
    let sealed = a.outbox()[0].sealed.clone();
    let stale = LiveItem::open(
        LiveItemKind::Code,
        ID,
        &KEY,
        2,
        None,
        &[RemoteUpdate {
            seq: 1,
            sealed: sealed.clone(),
        }],
    );
    assert!(matches!(stale, Err(LiveError::EpochMismatch { .. })));
    let other = LiveItem::open(
        LiveItemKind::Code,
        "other-item",
        &KEY,
        1,
        None,
        &[RemoteUpdate { seq: 1, sealed }],
    );
    assert!(matches!(other, Err(LiveError::Authentication)));
}

#[test]
fn operations_of_other_kinds_are_refused() {
    let mut code = create(LiveItemKind::Code, "x");
    assert!(matches!(
        code.apply_local_op(LocalOp::Sheet(super::SheetOp::DeleteRow {
            row_id: "r1".into()
        })),
        Err(LiveError::WrongKind { .. })
    ));
    let mut sheet = create(LiveItemKind::Sheet, "| a |\n| --- |\n| 1 |");
    assert!(matches!(
        sheet.apply_mirror_update(&[0, 0]),
        Err(LiveError::WrongKind { .. })
    ));
    assert!(matches!(code.sheet_ids(), Err(LiveError::WrongKind { .. })));
}

const DECK: &str = r##"<deck title="T" aspect="16:9" template="builtin:plain">
  <slide id="s1">
    <text id="e1" x="80" y="60" w="1200" h="120">Hello</text>
  </slide>
</deck>
"##;

#[test]
fn deck_items_sync_through_sealed_updates() {
    let mut items = replicas(LiveItemKind::Deck, DECK, 2);
    assert_eq!(items[1].text_form().unwrap(), DECK);
    let op = crate::client::shared_items::DeckOperation::SetGeometry {
        slide_id: "s1".into(),
        element_id: "e1".into(),
        x: 10,
        y: 20,
        w: 30,
        h: 40,
    };
    let change = items[0].apply_local_op(LocalOp::Deck(op)).unwrap();
    assert!(change.update.is_some());
    exchange(&mut items, in_order);
    assert_eq!(assert_converged(&items).matches("x=\"10\"").count(), 1);
}

// contract-test: supporting surface=sdk assertions=live-collab.sync.concurrent-convergence
#[test]
fn two_devices_creating_the_same_item_at_once_merge_into_one_copy() {
    let cases = [
        (
            LiveItemKind::Sheet,
            "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |",
        ),
        (LiveItemKind::Code, "one\ntwo\n"),
        (LiveItemKind::Doc, "<p>Pumpkin soup</p>"),
        (LiveItemKind::Deck, DECK),
    ];
    for (kind, text) in cases {
        let mut a = create(kind, text);
        let mut b = create(kind, text);
        let expected = a.text_form().unwrap();
        let from_a = a.outbox()[0].sealed.clone();
        let from_b = b.outbox()[0].sealed.clone();
        a.apply_remote(1, &from_b).unwrap();
        b.apply_remote(1, &from_a).unwrap();
        assert_eq!(a.text_form().unwrap(), expected, "{kind:?} doubled on a");
        assert_eq!(b.text_form().unwrap(), expected, "{kind:?} doubled on b");
    }
}
