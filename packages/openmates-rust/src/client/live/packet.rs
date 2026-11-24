//! Sealed live packets: `version(1)=1 | packet_type(1) | epoch(u32 BE) | nonce(12) |
//! ciphertext+tag`, AES-256-GCM with the item's embed key and the AAD
//! `om-live-v1|{item_id}|{kind}|{epoch}|{packet_type}`. A packet for another item, kind,
//! epoch or type fails to open with a typed error.
//!
//! `crypto/aead.rs` primitives take no associated data and are async, so this pure module
//! uses the same RustCrypto AES-256-GCM (`aes-gcm`) directly with the AAD bound.

use super::{LiveError, LiveItemKind};
use aes_gcm::{
    Aes256Gcm, KeyInit, Nonce,
    aead::{Aead, Payload},
};
use rand::{RngCore, rngs::OsRng};

/// Packet format version.
pub const VERSION: u8 = 1;
/// Header length: version, type, epoch, nonce.
pub const HEADER_LEN: usize = 1 + 1 + 4 + 12;

/// What a packet carries.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PacketType {
    /// A Yjs v1 update.
    Update = 1,
    /// A full-state Yjs v1 update.
    Snapshot = 2,
    /// Presence (never stored).
    Presence = 3,
}

impl PacketType {
    fn from_byte(byte: u8) -> Result<Self, LiveError> {
        match byte {
            1 => Ok(Self::Update),
            2 => Ok(Self::Snapshot),
            3 => Ok(Self::Presence),
            other => Err(LiveError::UnknownPacketType(other)),
        }
    }
}

fn aad(item_id: &str, kind: LiveItemKind, epoch: u32, packet_type: u8) -> Vec<u8> {
    format!(
        "om-live-v1|{item_id}|{}|{epoch}|{packet_type}",
        kind.as_str()
    )
    .into_bytes()
}

/// Seals `plaintext` under `key` with a fresh random nonce.
///
/// # Errors
/// [`LiveError::Randomness`] or [`LiveError::Authentication`] (encryption failure).
pub fn seal_packet(
    key: &[u8; 32],
    item_id: &str,
    kind: LiveItemKind,
    epoch: u32,
    packet_type: PacketType,
    plaintext: &[u8],
) -> Result<Vec<u8>, LiveError> {
    let mut nonce = [0u8; 12];
    OsRng
        .try_fill_bytes(&mut nonce)
        .map_err(|_| LiveError::Randomness)?;
    let cipher = Aes256Gcm::new(key.into());
    let aad = aad(item_id, kind, epoch, packet_type as u8);
    let sealed = cipher
        .encrypt(
            Nonce::from_slice(&nonce),
            Payload {
                msg: plaintext,
                aad: &aad,
            },
        )
        .map_err(|_| LiveError::Authentication)?;
    let mut out = Vec::with_capacity(HEADER_LEN + sealed.len());
    out.push(VERSION);
    out.push(packet_type as u8);
    out.extend_from_slice(&epoch.to_be_bytes());
    out.extend_from_slice(&nonce);
    out.extend_from_slice(&sealed);
    Ok(out)
}

/// Opens a packet for `item_id`/`kind` at `epoch`, which must be of `expected` type.
///
/// # Errors
/// [`LiveError::PacketTooShort`], [`LiveError::UnsupportedVersion`],
/// [`LiveError::UnknownPacketType`], [`LiveError::WrongPacketType`],
/// [`LiveError::EpochMismatch`] and [`LiveError::Authentication`] (wrong key, item or
/// kind, or a modified packet).
pub fn open_packet(
    key: &[u8; 32],
    item_id: &str,
    kind: LiveItemKind,
    epoch: u32,
    expected: PacketType,
    packet: &[u8],
) -> Result<Vec<u8>, LiveError> {
    if packet.len() < HEADER_LEN + 16 {
        return Err(LiveError::PacketTooShort);
    }
    if packet[0] != VERSION {
        return Err(LiveError::UnsupportedVersion(packet[0]));
    }
    let found = PacketType::from_byte(packet[1])?;
    if found != expected {
        return Err(LiveError::WrongPacketType {
            expected: expected as u8,
            found: found as u8,
        });
    }
    let header_epoch = packet_epoch(packet)?;
    if header_epoch != epoch {
        return Err(LiveError::EpochMismatch {
            expected: epoch,
            found: header_epoch,
        });
    }
    let aad = aad(item_id, kind, epoch, found as u8);
    Aes256Gcm::new(key.into())
        .decrypt(
            Nonce::from_slice(&packet[6..HEADER_LEN]),
            Payload {
                msg: &packet[HEADER_LEN..],
                aad: &aad,
            },
        )
        .map_err(|_| LiveError::Authentication)
}

/// Read the epoch to select an authentication key. This header is untrusted
/// until `open_packet` verifies its AEAD tag.
pub(super) fn packet_epoch(packet: &[u8]) -> Result<u32, LiveError> {
    if packet.len() < HEADER_LEN + 16 {
        return Err(LiveError::PacketTooShort);
    }
    if packet[0] != VERSION {
        return Err(LiveError::UnsupportedVersion(packet[0]));
    }
    Ok(u32::from_be_bytes([
        packet[2], packet[3], packet[4], packet[5],
    ]))
}
