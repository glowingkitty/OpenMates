//! Packet sealing: round trip and every binding of the AAD.

use super::packet::{HEADER_LEN, PacketType, open_packet, seal_packet};
use super::{LiveError, LiveItemKind};

const KEY: [u8; 32] = [7; 32];

fn sealed() -> Vec<u8> {
    seal_packet(
        &KEY,
        "item-1",
        LiveItemKind::Doc,
        3,
        PacketType::Update,
        b"hello",
    )
    .unwrap()
}

#[test]
fn round_trip_and_header_layout() {
    let packet = sealed();
    assert_eq!(&packet[..2], &[1, 1]);
    assert_eq!(&packet[2..6], &3u32.to_be_bytes());
    assert_eq!(packet.len(), HEADER_LEN + 5 + 16);
    let open = open_packet(
        &KEY,
        "item-1",
        LiveItemKind::Doc,
        3,
        PacketType::Update,
        &packet,
    );
    assert_eq!(open.unwrap(), b"hello");
}

#[test]
fn nonces_are_fresh() {
    assert_ne!(sealed()[6..18], sealed()[6..18]);
}

#[test]
fn other_item_kind_or_key_fails_authentication() {
    let packet = sealed();
    let open =
        |key: &[u8; 32], id: &str, kind| open_packet(key, id, kind, 3, PacketType::Update, &packet);
    assert_eq!(
        open(&KEY, "item-2", LiveItemKind::Doc),
        Err(LiveError::Authentication)
    );
    assert_eq!(
        open(&KEY, "item-1", LiveItemKind::Code),
        Err(LiveError::Authentication)
    );
    assert_eq!(
        open(&[8; 32], "item-1", LiveItemKind::Doc),
        Err(LiveError::Authentication)
    );
}

#[test]
fn other_epoch_or_type_fails_with_typed_error() {
    let packet = sealed();
    assert_eq!(
        open_packet(
            &KEY,
            "item-1",
            LiveItemKind::Doc,
            4,
            PacketType::Update,
            &packet
        ),
        Err(LiveError::EpochMismatch {
            expected: 4,
            found: 3
        })
    );
    assert_eq!(
        open_packet(
            &KEY,
            "item-1",
            LiveItemKind::Doc,
            3,
            PacketType::Snapshot,
            &packet
        ),
        Err(LiveError::WrongPacketType {
            expected: 2,
            found: 1
        })
    );
    // A forged header (type or epoch rewritten) fails the AAD check.
    let mut forged = packet.clone();
    forged[1] = 2;
    assert_eq!(
        open_packet(
            &KEY,
            "item-1",
            LiveItemKind::Doc,
            3,
            PacketType::Snapshot,
            &forged
        ),
        Err(LiveError::Authentication)
    );
    let mut forged = packet;
    forged[2..6].copy_from_slice(&4u32.to_be_bytes());
    assert_eq!(
        open_packet(
            &KEY,
            "item-1",
            LiveItemKind::Doc,
            4,
            PacketType::Update,
            &forged
        ),
        Err(LiveError::Authentication)
    );
}

#[test]
fn tampered_byte_and_short_packets_fail() {
    let packet = sealed();
    for index in [HEADER_LEN, packet.len() - 1, 8] {
        let mut bad = packet.clone();
        bad[index] ^= 1;
        assert_eq!(
            open_packet(
                &KEY,
                "item-1",
                LiveItemKind::Doc,
                3,
                PacketType::Update,
                &bad
            ),
            Err(LiveError::Authentication)
        );
    }
    assert_eq!(
        open_packet(
            &KEY,
            "item-1",
            LiveItemKind::Doc,
            3,
            PacketType::Update,
            &packet[..10]
        ),
        Err(LiveError::PacketTooShort)
    );
    let mut version = packet;
    version[0] = 9;
    assert_eq!(
        open_packet(
            &KEY,
            "item-1",
            LiveItemKind::Doc,
            3,
            PacketType::Update,
            &version
        ),
        Err(LiveError::UnsupportedVersion(9))
    );
}
