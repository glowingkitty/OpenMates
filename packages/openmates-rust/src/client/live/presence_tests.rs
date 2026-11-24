use super::presence::*;
use super::{LiveError, LiveItemKind};

fn who(id: &str, cursor: Option<Cursor>) -> Presence {
    Presence {
        user_id: id.into(),
        display_name: format!("User {id}"),
        color: color_for(id),
        cursor,
        mate: None,
    }
}

#[test]
fn colour_is_deterministic_and_a_hex_colour() {
    assert_eq!(color_for("u1"), color_for("u1"));
    assert_ne!(color_for("u1"), color_for("u2"));
    let c = color_for("u1");
    assert!(c.len() == 7 && c.starts_with('#') && c[1..].chars().all(|x| x.is_ascii_hexdigit()));
}

#[test]
fn payload_round_trips_for_every_cursor_kind_and_the_mate_lock() {
    let key = [3u8; 32];
    let cursors = [
        Cursor::Doc {
            anchor: "{\"a\":1}".into(),
            head: "{\"a\":2}".into(),
        },
        Cursor::Code {
            anchor: "x".into(),
            head: "y".into(),
        },
        Cursor::Sheet {
            row_id: "r1".into(),
            col_id: "c1".into(),
        },
        Cursor::Deck {
            slide_id: "s1".into(),
            element_id: Some("e1".into()),
        },
        Cursor::Deck {
            slide_id: "s1".into(),
            element_id: None,
        },
    ];
    for cursor in cursors {
        let mut p = who("u1", Some(cursor));
        p.mate = Some(MatePresence {
            mate_name: "Sophia".into(),
            editing_scope: "section 2".into(),
        });
        let sealed = seal_presence(&key, "item", LiveItemKind::Doc, 1, &p).unwrap();
        assert_eq!(
            open_presence(&key, "item", LiveItemKind::Doc, 1, &sealed).unwrap(),
            p
        );
    }
}

#[test]
fn a_presence_packet_for_another_item_does_not_open() {
    let key = [3u8; 32];
    let sealed = seal_presence(&key, "a", LiveItemKind::Code, 1, &who("u1", None)).unwrap();
    assert_eq!(
        open_presence(&key, "b", LiveItemKind::Code, 1, &sealed),
        Err(LiveError::Authentication)
    );
}

#[test]
fn entries_expire_thirty_seconds_after_the_last_heartbeat() {
    let mut table = PresenceTable::new();
    table.heartbeat(who("u1", None), 1_000);
    table.heartbeat(who("u2", None), 20_000);
    assert_eq!(table.active(30_999).len(), 2);
    assert_eq!(table.active(31_000).len(), 1);
    table.heartbeat(who("u1", None), 40_000);
    let ids: Vec<_> = table
        .active(45_000)
        .iter()
        .map(|p| p.user_id.clone())
        .collect();
    assert_eq!(ids, ["u1", "u2"]);
    let ids: Vec<_> = table
        .active(60_000)
        .iter()
        .map(|p| p.user_id.clone())
        .collect();
    assert_eq!(ids, ["u1"]);
    assert!(table.active(80_000).is_empty());
}
