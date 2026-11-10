//! Encrypted update packets: one AES-256-GCM envelope per CRDT update or snapshot.
//! Prototype of the Phase 2 wire unit. The server only ever sees `Packet` bytes;
//! it can order and store them but cannot read or alter them (AAD binds item and
//! packet kind, so a packet cannot be replayed into another item or relabelled).

use aes_gcm::aead::{Aead, AeadCore, KeyInit, OsRng, Payload};
use aes_gcm::{Aes256Gcm, Key, Nonce};

/// What a packet carries; part of the AAD so the server cannot relabel a packet.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    /// One Yjs v1 update (one local transaction).
    Update = 1,
    /// A full Yjs v1 state (`encode_state_as_update_v1`) used for compaction.
    Snapshot = 2,
    /// An ephemeral awareness (presence) update; relayed, never stored.
    Presence = 3,
}

/// Ciphertext unit the server relays and stores. `nonce || ciphertext+tag`.
#[derive(Clone, Debug)]
pub struct Packet {
    /// Packet kind, sent in clear so the server can route presence vs. log entries.
    pub kind: Kind,
    /// 12-byte random nonce followed by the AES-GCM ciphertext and tag.
    pub bytes: Vec<u8>,
}

/// Errors when opening a packet.
#[derive(Debug, PartialEq, Eq)]
pub enum EnvelopeError {
    /// Packet shorter than a nonce.
    Truncated,
    /// Authentication failed: wrong key, wrong item, wrong kind or tampered bytes.
    Unauthentic,
}

fn aad(item_id: &str, kind: Kind) -> Vec<u8> {
    // AAD layout: b"om-crdt-v1" || kind byte || item id (utf-8).
    let mut a = b"om-crdt-v1".to_vec();
    a.push(kind as u8);
    a.extend_from_slice(item_id.as_bytes());
    a
}

/// Encrypts `plain` for `item_id` with the item key.
///
/// # Panics
/// Never in practice: AES-GCM encryption only fails for plaintexts above ~64 GiB.
pub fn seal(key: &[u8; 32], item_id: &str, kind: Kind, plain: &[u8]) -> Packet {
    let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(key));
    let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
    let ct = cipher
        .encrypt(
            &nonce,
            Payload {
                msg: plain,
                aad: &aad(item_id, kind),
            },
        )
        .expect("AES-GCM encrypt cannot fail for packet-sized input");
    let mut bytes = nonce.to_vec();
    bytes.extend_from_slice(&ct);
    Packet { kind, bytes }
}

/// Decrypts a packet for `item_id`.
///
/// # Errors
/// [`EnvelopeError::Truncated`] or [`EnvelopeError::Unauthentic`].
pub fn open(key: &[u8; 32], item_id: &str, packet: &Packet) -> Result<Vec<u8>, EnvelopeError> {
    if packet.bytes.len() < 12 {
        return Err(EnvelopeError::Truncated);
    }
    let (nonce, ct) = packet.bytes.split_at(12);
    let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(key));
    cipher
        .decrypt(
            Nonce::from_slice(nonce),
            Payload {
                msg: ct,
                aad: &aad(item_id, packet.kind),
            },
        )
        .map_err(|_| EnvelopeError::Unauthentic)
}
