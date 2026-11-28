//! Pending update recovery preserves other replicas' writes and avoids stale replays.
use super::*;

fn entry(id: &str, epoch: u32) -> SealedUpdate {
    SealedUpdate {
        client_msg_id: id.into(),
        epoch,
        sealed: vec![epoch as u8],
    }
}

#[test]
fn acknowledgement_removes_only_the_settled_message() {
    let local = entry("local", 1);
    let other = entry("other", 1);
    let stored = vec![local.clone(), other.clone()];
    assert_eq!(merge(stored, &[local], &[]), vec![other]);
}

#[test]
fn restart_and_rekey_keeps_order_without_resurrecting_acknowledged_writes() {
    let acknowledged = entry("acknowledged", 1);
    let queued = entry("queued", 1);
    let other = entry("other", 1);
    let rotated = entry("queued", 2);
    let new = entry("new", 2);
    let stored = vec![queued.clone(), other.clone()];
    assert_eq!(
        merge(
            stored,
            &[acknowledged.clone(), queued],
            &[acknowledged, rotated.clone(), new.clone()]
        ),
        vec![rotated, other, new]
    );
}

#[test]
fn older_replica_cannot_replace_a_resealed_pending_packet() {
    let old = entry("pending", 1);
    let latest = entry("pending", 3);
    assert_eq!(
        merge(vec![latest.clone()], &[old], &[entry("pending", 2)]),
        vec![latest]
    );
}

#[test]
fn durable_copies_follow_pending_messages_and_keep_other_writers() {
    let first = entry("first", 1);
    let second = entry("second", 2);
    let mut stored = StoredOutbox {
        entries: vec![first, second.clone()],
        copies: vec![],
    };
    let a = RecoveryCopy {
        writer: "writer-a".into(),
        messages: vec!["first".into()],
        sealed: "account-sealed-first".into(),
    };
    let b = RecoveryCopy {
        writer: "writer-b".into(),
        messages: vec!["second".into()],
        sealed: "account-sealed-second".into(),
    };
    reconcile_copies(&mut stored, Some(&a));
    reconcile_copies(&mut stored, Some(&b));
    let mut restored = StoredOutbox::parse(stored.encode().as_deref()).unwrap();
    assert_eq!(restored.copies, [a, b]);
    restored.entries = vec![second];
    reconcile_copies(&mut restored, None);
    assert_eq!(restored.copies.len(), 1);
    assert_eq!(restored.copies[0].writer, "writer-b");
    restored.entries.clear();
    reconcile_copies(&mut restored, None);
    assert!(restored.encode().is_none());
}

#[test]
fn original_packet_arrays_remain_readable() {
    let entries = [entry("old", 1)];
    let record = outbox_to_json(&entries).to_string();
    let decoded = StoredOutbox::parse(Some(&record)).unwrap();
    assert_eq!(decoded.entries, entries);
    assert!(decoded.copies.is_empty());
}
