//! Test harness: a replica edits inside one transaction, emits one sealed packet, and
//! peers open and apply packets (the "server" is just a Vec of ciphertext packets).
#![allow(dead_code)] // shared by several test binaries; each uses a subset

use crdt_spike::envelope::{open, seal, Kind, Packet};
use yrs::updates::decoder::Decode;
use yrs::{Doc, ReadTxn, StateVector, Transact, TransactionMut, Update};

pub const KEY: [u8; 32] = [7u8; 32];
pub const ITEM: &str = "embed-0001";

/// Runs `f` in one local transaction (origin "local") and returns its sealed update.
pub fn edit(doc: &Doc, f: impl FnOnce(&mut TransactionMut)) -> Packet {
    let mut txn = doc.transact_mut_with("local");
    f(&mut txn);
    let update = txn.encode_update_v1();
    drop(txn);
    seal(&KEY, ITEM, Kind::Update, &update)
}

/// Opens and applies a packet (updates and snapshots alike).
pub fn deliver(doc: &Doc, p: &Packet) {
    deliver_with(doc, p, "remote");
}

/// Opens and applies a packet in a transaction with the given origin.
pub fn deliver_with(doc: &Doc, p: &Packet, origin: &str) {
    let plain = open(&KEY, ITEM, p).expect("authentic packet");
    let u = Update::decode_v1(&plain).expect("valid update");
    doc.transact_mut_with(origin)
        .apply_update(u)
        .expect("apply");
}

/// Client-made encrypted snapshot of the full state (compaction unit).
pub fn snapshot(doc: &Doc) -> Packet {
    let state = doc
        .transact()
        .encode_state_as_update_v1(&StateVector::default());
    seal(&KEY, ITEM, Kind::Snapshot, &state)
}

/// Full plaintext state, e.g. the base an assistant read.
pub fn state(doc: &Doc) -> Vec<u8> {
    doc.transact()
        .encode_state_as_update_v1(&StateVector::default())
}
