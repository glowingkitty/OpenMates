//! Shared helpers of the live tests: replicas of one item, delivery in chosen orders and a
//! deterministic PRNG (no extra dependency).

use super::LiveItemKind;
use super::engine::{LiveItem, RemoteUpdate, SealedUpdate};

pub(super) const KEY: [u8; 32] = [9; 32];
pub(super) const ID: &str = "item-test";

pub(super) fn snapshot_of(item: &LiveItem) -> RemoteUpdate {
    let (seq, sealed) = item.seal_snapshot().expect("seals");
    RemoteUpdate { seq, sealed }
}

/// A replica of `source` built from its sealed snapshot.
pub(super) fn peer(kind: LiveItemKind, source: &LiveItem) -> LiveItem {
    LiveItem::open(kind, ID, &KEY, 1, Some(&snapshot_of(source)), &[]).expect("opens")
}

pub(super) fn create(kind: LiveItemKind, text: &str) -> LiveItem {
    LiveItem::create(kind, ID, &KEY, 1, text).expect("creates")
}

/// `n` replicas of one freshly created item.
pub(super) fn replicas(kind: LiveItemKind, text: &str, n: usize) -> Vec<LiveItem> {
    let first = create(kind, text);
    let mut all: Vec<LiveItem> = (1..n).map(|_| peer(kind, &first)).collect();
    all.insert(0, first);
    for item in &mut all {
        let ids: Vec<String> = item
            .outbox()
            .iter()
            .map(|e| e.client_msg_id.clone())
            .collect();
        for id in ids {
            item.ack(&id, 0);
        }
    }
    all
}

/// Takes every pending local update of every replica (and acknowledges it).
pub(super) fn take_outboxes(items: &mut [LiveItem]) -> Vec<(usize, SealedUpdate)> {
    let mut out = Vec::new();
    for (index, item) in items.iter_mut().enumerate() {
        for entry in item.outbox().to_vec() {
            item.ack(&entry.client_msg_id, 0);
            out.push((index, entry));
        }
    }
    out
}

/// Delivers all pending updates to every other replica in the order given by `order`.
pub(super) fn exchange(items: &mut [LiveItem], order: impl Fn(&mut Vec<(usize, SealedUpdate)>)) {
    let mut pending = take_outboxes(items);
    order(&mut pending);
    for (seq, (from, entry)) in pending.iter().enumerate() {
        for (index, item) in items.iter_mut().enumerate() {
            if index != *from {
                item.apply_remote(seq as u64 + 1, &entry.sealed)
                    .expect("applies");
            }
        }
    }
}

pub(super) fn in_order(_: &mut Vec<(usize, SealedUpdate)>) {}

pub(super) fn reversed(list: &mut Vec<(usize, SealedUpdate)>) {
    list.reverse();
}

/// Asserts every replica renders the same text form (or the same `Empty` refusal, which a
/// sheet reaches when concurrent deletes remove every column) and returns it.
pub(super) fn assert_converged(items: &[LiveItem]) -> String {
    let first = items[0].text_form();
    for item in &items[1..] {
        assert_eq!(item.text_form(), first);
    }
    first.unwrap_or_default()
}

/// xorshift64* PRNG.
pub(super) struct Rng(pub u64);

impl Rng {
    pub(super) fn next(&mut self) -> u64 {
        self.0 ^= self.0 >> 12;
        self.0 ^= self.0 << 25;
        self.0 ^= self.0 >> 27;
        self.0.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }

    pub(super) fn below(&mut self, n: usize) -> usize {
        (self.next() % n.max(1) as u64) as usize
    }

    pub(super) fn shuffle<T>(&mut self, list: &mut [T]) {
        for i in (1..list.len()).rev() {
            list.swap(i, self.below(i + 1));
        }
    }
}
