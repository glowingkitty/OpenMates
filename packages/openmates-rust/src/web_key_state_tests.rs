//! Behaviour of the Worker chat-key store against the `ChatKeyManager.ts` rules it mirrors.
use crate::web_key_state::{Enqueue, KeyState, KeyStore, MAX_WAITERS_PER_CHAT};
use crate::web_keys::{InjectDecision, KeySource};

const A: [u8; 32] = [1; 32];
const B: [u8; 32] = [2; 32];

#[test]
fn first_key_is_set_ready_and_notifies_once() {
    let mut store = KeyStore::new();
    let first = store.offer("c", &A, KeySource::MasterKey, false, 1.0);
    assert_eq!(
        (first.decision, first.notify_ready),
        (InjectDecision::Set, true)
    );
    assert_eq!(store.state("c"), KeyState::Ready);
    let again = store.offer("c", &A, KeySource::MasterKey, false, 2.0);
    assert_eq!(
        (again.decision, again.notify_ready),
        (InjectDecision::Keep, false)
    );
}

#[test]
fn different_key_is_rejected_without_force_and_replaced_with_force() {
    let mut store = KeyStore::new();
    store.offer("c", &A, KeySource::MasterKey, false, 1.0);
    assert_eq!(
        store
            .offer("c", &B, KeySource::ServerSync, false, 2.0)
            .decision,
        InjectDecision::Reject
    );
    assert_eq!(store.key("c").as_deref().map(Vec::as_slice), Some(&A[..]));
    let rotated = store.offer("c", &B, KeySource::ServerSync, true, 3.0);
    assert_eq!(
        (rotated.decision, rotated.notify_ready),
        (InjectDecision::Replace, false)
    );
    assert_eq!(store.key("c").as_deref().map(Vec::as_slice), Some(&B[..]));
}

#[test]
fn identical_key_from_stronger_source_relabels_provenance() {
    let mut store = KeyStore::new();
    store.offer("c", &A, KeySource::ShareLink, false, 1.0);
    let upgraded = store.offer("c", &A, KeySource::MasterKey, false, 2.0);
    assert_eq!(upgraded.decision, InjectDecision::UpgradeSource);
    assert_eq!(
        store.handle("c").map(|h| h.source),
        Some(KeySource::MasterKey)
    );
}

#[test]
fn waiters_flush_in_arrival_order_when_the_key_arrives() {
    let mut store = KeyStore::new();
    let (Enqueue::Queued(first), Enqueue::Queued(second)) =
        (store.enqueue("c"), store.enqueue("c"))
    else {
        panic!("both waiters park");
    };
    assert_eq!(store.pending("c"), 2);
    assert_eq!(
        store
            .offer("c", &A, KeySource::ServerSync, false, 1.0)
            .flushed,
        vec![first, second]
    );
    assert_eq!(store.pending("c"), 0);
    assert_eq!(store.enqueue("c"), Enqueue::Ready);
}

#[test]
fn waiter_queue_is_bounded_and_timeouts_cancel() {
    let mut store = KeyStore::new();
    let mut last = 0;
    for _ in 0..MAX_WAITERS_PER_CHAT {
        let Enqueue::Queued(ticket) = store.enqueue("c") else {
            panic!("room left")
        };
        last = ticket;
    }
    assert_eq!(store.enqueue("c"), Enqueue::Full);
    assert!(store.cancel("c", last));
    assert!(!store.cancel("c", last));
    assert!(matches!(store.enqueue("c"), Enqueue::Queued(_)));
}

#[test]
fn created_key_is_provisional_until_marked_persisted() {
    let mut store = KeyStore::new();
    store.offer("c", &A, KeySource::Created, false, 1.0);
    assert_eq!(store.unpersisted(), 1);
    assert!(store.mark_persisted("c"));
    assert_eq!(store.unpersisted(), 0);
    assert!(!store.mark_persisted("missing"));
}

#[test]
fn remove_and_clear_drop_keys_and_return_waiters_to_reject() {
    let mut store = KeyStore::new();
    store.offer("a", &A, KeySource::MasterKey, false, 1.0);
    let Enqueue::Queued(t1) = store.enqueue("b") else {
        panic!()
    };
    let Enqueue::Queued(t2) = store.enqueue("c") else {
        panic!()
    };
    assert!(store.remove("a").is_empty());
    assert_eq!((store.size(), store.state("a")), (0, KeyState::Unloaded));
    assert_eq!(store.clear(), vec![t1, t2]);
    assert_eq!(store.pending("b"), 0);
}

#[test]
fn load_states_track_and_reset_retries() {
    let mut store = KeyStore::new();
    store.set_state("c", KeyState::Loading);
    assert_eq!(store.state("c"), KeyState::Loading);
    store.set_state("c", KeyState::Failed);
    assert_eq!(store.state("c"), KeyState::Failed);
    store.reset("c");
    assert_eq!(store.state("c"), KeyState::Unloaded);
    store.offer("c", &A, KeySource::MasterKey, false, 1.0);
    store.set_state("c", KeyState::Failed);
    assert_eq!(store.state("c"), KeyState::Ready);
    assert!(KeyState::parse_settable("ready").is_none());
}
