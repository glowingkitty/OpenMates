//! State machine tests of `LiveSession` with a fake server (frames in, actions out).

use super::engine::{LiveItem, LocalOp, RemoteUpdate};
use super::session::{LiveSession, SNAPSHOT_UPDATE_THRESHOLD};
use super::session_types::{Action, CheckpointResult, Event, Status};
use super::support::{ID, KEY, create, snapshot_of};
use super::{LiveItemKind, SheetOp};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};

const SHEET: &str = "| A | B |\n| --- | --- |\n| 1 | 2 |";

fn connected_session(kind: LiveItemKind) -> (LiveSession, Vec<Action>) {
    let mut session = LiveSession::default();
    session.set_connected(true);
    session.open(ID, kind);
    let actions = session
        .provide_keys(
            ID,
            super::driver::LiveKeys {
                epoch: 1,
                current: zeroize::Zeroizing::new(KEY),
                previous: vec![],
            },
            Vec::new(),
        )
        .expect("key");
    (session, actions)
}

fn state(role: &str, snapshot: Option<&RemoteUpdate>, updates: &[RemoteUpdate]) -> Value {
    let wire = |u: &RemoteUpdate| json!({"seq": u.seq, "sender": "p", "epoch": 1, "payload": STANDARD.encode(&u.sealed), "ts": 0});
    let mut body = json!({"item_id": ID, "role": role,
        "updates": updates.iter().map(wire).collect::<Vec<_>>(),
        "head_seq": updates.last().map_or(snapshot.map_or(0, |s| s.seq), |u| u.seq)});
    if let Some(s) = snapshot {
        body["snapshot"] = json!({"seq": s.seq, "epoch": 1, "payload": STANDARD.encode(&s.sealed)});
    }
    body
}

fn sends<'a>(actions: &'a [Action], ty: &str) -> Vec<&'a Value> {
    actions
        .iter()
        .filter_map(|a| match a {
            Action::Send {
                message_type,
                payload,
            } if *message_type == ty => Some(payload),
            _ => None,
        })
        .collect()
}

fn statuses(actions: &[Action]) -> Vec<Status> {
    actions
        .iter()
        .filter_map(|a| match a {
            Action::Emit(Event::Status { status, .. }) => Some(*status),
            _ => None,
        })
        .collect()
}

fn views(actions: &[Action]) -> Vec<&Value> {
    actions
        .iter()
        .filter_map(|a| match a {
            Action::Emit(Event::View { view, .. }) => Some(view),
            _ => None,
        })
        .collect()
}

/// A session on an existing sheet, acknowledged and saved.
fn open_sheet() -> (LiveSession, LiveItem) {
    let peer = create(LiveItemKind::Sheet, SHEET);
    let snapshot = snapshot_of(&peer);
    let (mut session, actions) = connected_session(LiveItemKind::Sheet);
    assert_eq!(sends(&actions, "live_item_subscribe")[0]["item_id"], ID);
    let out = session
        .on_frame("live_item_state", &state("edit", Some(&snapshot), &[]), 0)
        .expect("state");
    assert_eq!(views(&out).len(), 1);
    assert_eq!(statuses(&out), vec![Status::Saved]);
    (session, peer)
}

fn first_cell_op(item: &LiveItem, value: &str) -> LocalOp {
    let (rows, cols) = item.sheet_ids().expect("ids");
    LocalOp::Sheet(SheetOp::SetCell {
        row_id: rows[0].clone(),
        col_id: cols[0].clone(),
        value: value.to_string(),
    })
}

#[test]
fn subscribe_state_opens_and_fills_the_mirror() {
    let peer = create(LiveItemKind::Code, "fn main() {}\n");
    let snapshot = snapshot_of(&peer);
    let (mut session, actions) = connected_session(LiveItemKind::Code);
    assert_eq!(sends(&actions, "live_item_subscribe").len(), 1);
    assert!(
        sends(&actions, "live_item_subscribe")[0]
            .get("since_seq")
            .is_none()
    );
    let out = session
        .on_frame("live_item_state", &state("edit", Some(&snapshot), &[]), 0)
        .unwrap();
    assert!(out.iter().any(
        |a| matches!(a, Action::Emit(Event::RemoteUpdate { bytes, .. }) if !bytes.is_empty())
    ));
    assert_eq!(statuses(&out), vec![Status::Saved]);
}

#[test]
fn empty_log_asks_for_content_then_sends_the_initial_update() {
    let (mut session, _) = connected_session(LiveItemKind::Sheet);
    let out = session
        .on_frame("live_item_state", &state("edit", None, &[]), 0)
        .unwrap();
    assert!(out.contains(&Action::NeedContent {
        item_id: ID.to_string()
    }));
    let out = session.provide_content(ID, SHEET, 10).unwrap();
    assert_eq!(sends(&out, "live_item_update").len(), 1);
    assert!(
        out.iter()
            .any(|a| matches!(a, Action::PersistOutbox { entries, .. } if entries.len() == 1))
    );
    assert_eq!(views(&out).len(), 1);
}

#[test]
fn local_op_is_sent_acked_and_saved() {
    let (mut session, peer) = open_sheet();
    let out = session
        .apply_local_op(ID, first_cell_op(&peer, "9"), 5)
        .unwrap();
    let update = sends(&out, "live_item_update")[0].clone();
    assert_eq!(update["epoch"], 1);
    assert_eq!(statuses(&out), vec![Status::Saving]);
    assert_eq!(views(&out).len(), 1);
    let ack = json!({"item_id": ID, "client_msg_id": update["client_msg_id"], "seq": 4});
    let out = session.on_frame("live_item_update_ack", &ack, 6).unwrap();
    assert_eq!(statuses(&out), vec![Status::Saved]);
    assert!(
        out.iter()
            .any(|a| matches!(a, Action::PersistOutbox { entries, .. } if entries.is_empty()))
    );
}

#[test]
fn remote_update_emits_a_view() {
    let (mut session, mut peer) = open_sheet();
    let sealed = peer
        .apply_local_op(first_cell_op(&peer, "77"))
        .unwrap()
        .update
        .unwrap();
    let frame = json!({"item_id": ID, "seq": 1, "sender": "p", "epoch": 1,
        "payload": STANDARD.encode(&sealed.sealed), "ts": 0});
    let out = session.on_frame("live_item_update", &frame, 1).unwrap();
    let view = views(&out)[0].clone();
    assert!(view["cells"].to_string().contains("77"));
}

#[test]
fn refusals_set_the_status() {
    let (mut session, _) = open_sheet();
    let out = session
        .on_frame(
            "live_item_refused",
            &json!({"item_id": ID, "reason": "read_only"}),
            0,
        )
        .unwrap();
    assert_eq!(statuses(&out), vec![Status::ReadOnly]);
    assert!(
        session
            .apply_local_op(ID, LocalOp::CodeSetText(String::new()), 0)
            .is_err()
    );
    let out = session
        .on_frame(
            "live_item_refused",
            &json!({"item_id": ID, "reason": "access_revoked"}),
            0,
        )
        .unwrap();
    assert_eq!(statuses(&out), vec![Status::AccessRevoked]);
    assert!(session.is_empty());
}

#[test]
fn view_only_role_reports_read_only_and_refuses_edits() {
    let peer = create(LiveItemKind::Sheet, SHEET);
    let (mut session, _) = connected_session(LiveItemKind::Sheet);
    let out = session
        .on_frame(
            "live_item_state",
            &state("view", Some(&snapshot_of(&peer)), &[]),
            0,
        )
        .unwrap();
    assert_eq!(statuses(&out), vec![Status::ReadOnly]);
    assert!(
        session
            .apply_local_op(ID, first_cell_op(&peer, "x"), 0)
            .is_err()
    );
}

#[test]
fn reconnect_resubscribes_and_resends_the_outbox() {
    let (mut session, peer) = open_sheet();
    let out = session
        .apply_local_op(ID, first_cell_op(&peer, "5"), 1)
        .unwrap();
    let id = sends(&out, "live_item_update")[0]["client_msg_id"].clone();
    let out = session.set_connected(false);
    assert_eq!(statuses(&out), vec![Status::Offline]);
    let out = session
        .apply_local_op(ID, first_cell_op(&peer, "6"), 2)
        .unwrap();
    assert!(
        sends(&out, "live_item_update").is_empty(),
        "offline edits wait"
    );
    let out = session.set_connected(true);
    assert_eq!(sends(&out, "live_item_subscribe")[0]["since_seq"], 0);
    let out = session
        .on_frame("live_item_state", &state("edit", None, &[]), 3)
        .unwrap();
    let resent = sends(&out, "live_item_update");
    assert_eq!(resent.len(), 2);
    assert_eq!(resent[0]["client_msg_id"], id);
}

#[test]
fn stale_epoch_fetches_a_key_and_reseals_the_outbox() {
    let (mut session, peer) = open_sheet();
    session
        .apply_local_op(ID, first_cell_op(&peer, "5"), 1)
        .unwrap();
    let out = session
        .on_frame(
            "live_item_refused",
            &json!({"item_id": ID, "reason": "key_epoch_stale"}),
            2,
        )
        .unwrap();
    assert!(out.contains(&Action::NeedKey {
        item_id: ID.to_string(),
        stale: true
    }));
    let out = session
        .provide_keys(
            ID,
            super::driver::LiveKeys {
                epoch: 2,
                current: zeroize::Zeroizing::new([3; 32]),
                previous: vec![],
            },
            Vec::new(),
        )
        .unwrap();
    assert_eq!(sends(&out, "live_item_subscribe").len(), 1);
    assert!(sends(&out, "live_item_update").is_empty());
    let late_refusal = session
        .on_frame(
            "live_item_refused",
            &json!({"item_id": ID, "reason": "key_epoch_stale", "rejected_epoch": 1}),
            3,
        )
        .unwrap();
    assert!(late_refusal.is_empty());
    let out = session
        .on_frame("live_item_state", &state("edit", None, &[]), 4)
        .unwrap();
    let resent = sends(&out, "live_item_update");
    assert_eq!(resent.len(), 1);
    assert_eq!(resent[0]["epoch"], 2);
}

#[test]
fn snapshot_is_sealed_after_the_update_threshold() {
    let peer = create(LiveItemKind::Code, "a\n");
    let snapshot = snapshot_of(&peer);
    let mut peer = LiveItem::open(LiveItemKind::Code, ID, &KEY, 1, Some(&snapshot), &[]).unwrap();
    let (mut session, _) = connected_session(LiveItemKind::Code);
    session
        .on_frame("live_item_state", &state("edit", Some(&snapshot), &[]), 0)
        .unwrap();
    let mut snapshots = 0;
    for seq in 1..=SNAPSHOT_UPDATE_THRESHOLD as u64 {
        let op = LocalOp::CodeSetText(format!("line {seq}\n"));
        let sealed = peer.apply_local_op(op).unwrap().update.unwrap();
        let frame = json!({"item_id": ID, "seq": seq, "sender": "p", "epoch": 1,
            "payload": STANDARD.encode(&sealed.sealed), "ts": 0});
        let out = session.on_frame("live_item_update", &frame, seq).unwrap();
        snapshots += sends(&out, "live_item_snapshot").len();
    }
    assert_eq!(snapshots, 1);
}

#[test]
fn snapshot_available_is_loaded_and_confirmed() {
    let (mut session, peer) = open_sheet();
    let out = session
        .on_frame(
            "live_item_snapshot_available",
            &json!({"item_id": ID, "covers_seq": 9, "epoch": 1}),
            0,
        )
        .unwrap();
    assert!(
        sends(&out, "live_item_subscribe")[0]
            .get("since_seq")
            .is_none()
    );
    let (_, sealed) = peer.seal_snapshot().unwrap();
    let snapshot = RemoteUpdate { seq: 9, sealed };
    let out = session
        .on_frame("live_item_state", &state("edit", Some(&snapshot), &[]), 1)
        .unwrap();
    assert_eq!(
        sends(&out, "live_item_snapshot_confirm")[0],
        &json!({"item_id": ID, "covers_seq": 9, "epoch": 1})
    );
}

#[test]
fn presence_round_trips_and_expires() {
    let (mut session, _) = open_sheet();
    let out = session.set_presence(ID, r#"{"user_id":"u"}"#).unwrap();
    let payload = sends(&out, "live_item_presence")[0]["payload"].clone();
    let frame = json!({"item_id": ID, "sender": "s", "connection": "c1", "payload": payload});
    let out = session
        .on_frame("live_item_presence", &frame, 1_000)
        .unwrap();
    assert!(
        matches!(&out[0], Action::Emit(Event::Presence { peers, .. }) if peers.as_array().unwrap().len() == 1)
    );
    assert!(session.tick(10_000).is_empty());
    let out = session.tick(31_001);
    assert!(
        matches!(&out[0], Action::Emit(Event::Presence { peers, .. }) if peers.as_array().unwrap().is_empty())
    );
}

// contract-test: supporting surface=sdk assertions=live-collab.presence.who-and-where
#[test]
fn presence_carries_the_hashed_user_and_a_stable_colour_from_the_core() {
    let (mut session, _) = open_sheet();
    session.set_user("user-1");
    let out = session
        .set_presence(
            ID,
            r#"{"kind_cursor":{"a":1},"display_name":"Ana","user_id":"forged"}"#,
        )
        .unwrap();
    let payload = sends(&out, "live_item_presence")[0]["payload"].clone();
    let frame = json!({"item_id": ID, "sender": "s", "connection": "c1", "payload": payload});
    let out = session
        .on_frame("live_item_presence", &frame, 1_000)
        .unwrap();
    let Action::Emit(Event::Presence { peers, .. }) = &out[0] else {
        panic!("presence event expected")
    };
    let peer = &peers[0];
    assert_eq!(peer["display_name"], "Ana");
    assert_eq!(peer["kind_cursor"], json!({"a": 1}));
    let user = peer["user_id"].as_str().unwrap();
    assert!(
        user.len() == 64 && user != "user-1" && user != "forged",
        "core stamps the hashed id"
    );
    assert!(peer["color"].as_str().unwrap().starts_with('#'));
    let again = session.set_presence(ID, "{}").unwrap();
    let frame = json!({"item_id": ID, "sender": "s", "connection": "c1",
        "payload": sends(&again, "live_item_presence")[0]["payload"].clone()});
    let out = session
        .on_frame("live_item_presence", &frame, 2_000)
        .unwrap();
    let Action::Emit(Event::Presence { peers, .. }) = &out[0] else {
        panic!("presence event expected")
    };
    assert_eq!(peers[0]["color"], peer["color"], "same person, same colour");
}

// contract-test: supporting surface=sdk assertions=live-collab.sync.concurrent-convergence,live-collab.saving.automatic
#[test]
fn updates_and_presence_refused_for_the_rate_limit_are_sent_again_on_the_next_tick() {
    let (mut session, peer) = open_sheet();
    let out = session
        .apply_local_op(ID, first_cell_op(&peer, "9"), 5)
        .unwrap();
    let update = sends(&out, "live_item_update")[0].clone();
    let refused =
        json!({"item_id": ID, "reason": "rate_limited", "client_msg_id": update["client_msg_id"]});
    session.on_frame("live_item_refused", &refused, 6).unwrap();
    let presence = session
        .set_presence(ID, r#"{"kind_cursor":{"a":1}}"#)
        .unwrap();
    assert_eq!(sends(&presence, "live_item_presence").len(), 1);
    let refused = json!({"item_id": ID, "reason": "rate_limited"});
    session.on_frame("live_item_refused", &refused, 7).unwrap();
    let out = session.tick(2_000);
    let resent = sends(&out, "live_item_update");
    assert_eq!(resent.len(), 1, "the refused update goes out again");
    assert_eq!(resent[0]["client_msg_id"], update["client_msg_id"]);
    assert_eq!(resent[0]["payload"], update["payload"]);
    assert_eq!(
        sends(&out, "live_item_presence").len(),
        1,
        "the latest presence too"
    );
    let out = session.tick(4_000);
    assert!(
        sends(&out, "live_item_update").is_empty(),
        "sent once per refusal"
    );
    assert!(sends(&out, "live_item_presence").is_empty());
}

// contract-test: supporting surface=sdk assertions=live-collab.offline.merge-on-reconnect
#[test]
fn frames_arriving_while_disconnected_are_ignored_until_the_resubscribe() {
    let (mut session, _) = open_sheet();
    session.set_presence(ID, "{}").unwrap();
    let presence = session.set_presence(ID, "{}").unwrap();
    let payload = sends(&presence, "live_item_presence")[0]["payload"].clone();
    let frame = json!({"item_id": ID, "sender": "s", "connection": "c1", "payload": payload});
    let out = session.set_connected(false);
    assert!(sends(&out, "live_item_subscribe").is_empty());
    assert!(
        session
            .on_frame("live_item_presence", &frame, 1_000)
            .unwrap()
            .is_empty()
    );
    let out = session.set_connected(true);
    assert_eq!(
        sends(&out, "live_item_subscribe").len(),
        1,
        "resubscribes on reconnect"
    );
}

// contract-test: supporting surface=sdk assertions=live-collab.offline.merge-on-reconnect,live-collab.sync.concurrent-convergence
#[test]
fn a_missed_update_is_replayed_after_reconnect_and_fills_the_hole() {
    let (mut session, mut peer) = open_sheet();
    let sealed: Vec<_> = ["a", "b", "c"]
        .iter()
        .map(|v| {
            let op = first_cell_op(&peer, v);
            peer.apply_local_op(op).unwrap().update.unwrap()
        })
        .collect();
    let wire = |seq: u64| {
        json!({"item_id": ID, "seq": seq, "sender": "p", "epoch": 1,
            "payload": STANDARD.encode(&sealed[(seq - 1) as usize].sealed), "ts": 0})
    };
    session.on_frame("live_item_update", &wire(1), 1).unwrap();
    // Update 2 is lost (e.g. it arrived while the connection was reported down).
    session.on_frame("live_item_update", &wire(3), 2).unwrap();
    session.set_connected(false);
    let out = session.set_connected(true);
    assert_eq!(
        sends(&out, "live_item_subscribe")[0]["since_seq"],
        1,
        "resubscribes from the last position without a hole"
    );
    let replay: Vec<RemoteUpdate> = (1..=3)
        .map(|seq| RemoteUpdate {
            seq,
            sealed: sealed[(seq - 1) as usize].sealed.clone(),
        })
        .collect();
    let out = session
        .on_frame("live_item_state", &state("edit", None, &replay[1..]), 3)
        .unwrap();
    let view = views(&out)
        .last()
        .cloned()
        .expect("the filled hole changes the view");
    assert!(view["cells"].to_string().contains("\"c\""), "{view}");
}

// contract-test: supporting surface=sdk assertions=live-collab.saving.automatic
#[test]
fn leaving_the_editor_writes_the_version_of_unsaved_edits_at_once() {
    let (mut session, peer) = open_sheet();
    assert!(
        session.checkpoint_before_close(ID).is_empty(),
        "nothing edited"
    );
    session
        .apply_local_op(ID, first_cell_op(&peer, "42"), 0)
        .unwrap();
    let out = session.checkpoint_before_close(ID);
    let Some(Action::WriteCheckpoint(request)) = out.first() else {
        panic!("leaving with edits writes a version: {out:?}")
    };
    assert!(request.text.contains("42"));
    assert!(
        session.checkpoint_before_close(ID).is_empty(),
        "one write at a time"
    );
    assert!(
        session
            .checkpoint_result(ID, CheckpointResult::Written(2), 1)
            .is_empty()
    );
    assert!(
        session.checkpoint_before_close(ID).is_empty(),
        "saved: nothing left to write"
    );
}

#[test]
fn checkpoint_retries_on_conflict_with_the_servers_version() {
    let (mut session, peer) = open_sheet();
    session.set_user("user-1");
    session.set_base_version(ID, Some(3));
    let out = session
        .apply_local_op(ID, first_cell_op(&peer, "9"), 0)
        .unwrap();
    let id = sends(&out, "live_item_update")[0]["client_msg_id"].clone();
    assert!(session.tick(60_000).is_empty(), "not idle long enough");
    assert!(session.tick(200_000).is_empty(), "outbox still pending");
    session
        .on_frame(
            "live_item_update_ack",
            &json!({"item_id": ID, "client_msg_id": id, "seq": 1}),
            1,
        )
        .unwrap();
    let out = session.tick(200_000);
    let Some(Action::WriteCheckpoint(request)) = out.first() else {
        panic!("checkpoint due: {out:?}")
    };
    assert_eq!(
        (request.base_version, request.version_kind),
        (Some(3), "session")
    );
    assert_eq!(request.contributors, vec!["user-1".to_string()]);
    assert!(request.text.contains('9'));
    assert!(session.tick(210_000).is_empty(), "one write at a time");
    let out = session.checkpoint_result(ID, CheckpointResult::Conflict(7), 220_000);
    assert!(matches!(&out[0], Action::WriteCheckpoint(r) if r.base_version == Some(7)));
    assert!(
        session
            .checkpoint_result(ID, CheckpointResult::Written(8), 230_000)
            .is_empty()
    );
    assert!(
        session.tick(900_000).is_empty(),
        "clean after a written version"
    );
}

// contract-test: supporting surface=sdk assertions=live-collab.versions.named-snapshots
#[test]
fn restoring_a_document_keeps_a_concurrent_append_and_checkpoints_the_restore() {
    let base = "<p>Soup</p><p>Too much salt</p>";
    let peer = create(
        LiveItemKind::Doc,
        "<p>Soup</p><p>Too much salt plus lemon</p>",
    );
    let (mut session, _) = connected_session(LiveItemKind::Doc);
    let snapshot = snapshot_of(&peer);
    session
        .on_frame("live_item_state", &state("edit", Some(&snapshot), &[]), 0)
        .unwrap();
    session.set_base_version(ID, Some(3));
    assert!(
        session
            .prepare_version_restore(ID, 1, 2, base, "<p>Soup</p>")
            .is_err()
    );

    let prepared = session
        .prepare_version_restore(ID, 2, 3, base, "<p>Soup</p>")
        .unwrap();
    let request = &prepared.checkpoint;
    assert_eq!(request.text, "<p>Soup</p><p> plus lemon</p>");
    assert_eq!(request.base_version, Some(3));
    assert_eq!(request.restored_from, Some(2));
    assert_eq!(request.version_kind, "restore");
    assert!(
        session.slots[ID]
            .item
            .as_ref()
            .unwrap()
            .text_form()
            .unwrap()
            .contains("Too much salt")
    );
    let actions = session.finish_version_restore(&prepared, 4, 2).unwrap();
    assert!(!sends(&actions, "live_item_update").is_empty());
    assert_eq!(
        session.slots[ID]
            .item
            .as_ref()
            .unwrap()
            .text_form()
            .unwrap(),
        request.text
    );
}

// contract-test: supporting surface=sdk assertions=live-collab.versions.named-snapshots
#[test]
fn restoring_a_sheet_writes_and_broadcasts_a_formatted_checkpoint() {
    let previous = format!(
        "{SHEET}\n<!-- openmates-sheet-format-v1: {{\"cells\":{{\"A2\":{{\"bold\":true}}}}}} -->"
    );
    let current =
        format!("{SHEET}\n<!-- openmates-sheet-format-v1: {{\"columnWidths\":{{\"A\":200}}}} -->");
    let peer = create(LiveItemKind::Sheet, &current);
    let (mut session, _) = connected_session(LiveItemKind::Sheet);
    let snapshot = snapshot_of(&peer);
    session
        .on_frame("live_item_state", &state("edit", Some(&snapshot), &[]), 0)
        .unwrap();
    session.set_base_version(ID, Some(3));
    let prepared = session
        .prepare_version_restore(ID, 2, 3, &current, &previous)
        .unwrap();
    assert_eq!(prepared.checkpoint.text, previous);
    let actions = session.finish_version_restore(&prepared, 4, 2).unwrap();
    assert!(!sends(&actions, "live_item_update").is_empty());
    assert_eq!(
        views(&actions)[0]["formatting"],
        json!({"cells":{"A2":{"bold":true}}})
    );
}

// contract-test: supporting surface=sdk assertions=live-collab.assistant.live-edits,live-collab.assistant.human-wins
#[test]
fn project_commit_reaches_the_open_document_once_and_can_be_undone() {
    let base = "<p>Soup</p><p>Onions</p>";
    let peer = create(LiveItemKind::Doc, "<p>Soup with lemon</p><p>Onions</p>");
    let (mut session, _) = connected_session(LiveItemKind::Doc);
    let snapshot = snapshot_of(&peer);
    session
        .on_frame("live_item_state", &state("edit", Some(&snapshot), &[]), 0)
        .unwrap();
    session.set_base_version(ID, Some(3));
    let actions = session
        .adopt_project_commit(ID, "turn", 4, base, "<p>Soup</p><p>Carrots</p>", 1)
        .unwrap();
    assert_eq!(sends(&actions, "live_item_update").len(), 1);
    assert!(
        session
            .adopt_project_commit(ID, "turn", 4, base, "<p>Soup</p><p>Carrots</p>", 2)
            .unwrap()
            .is_empty()
    );
    let text = session.slots[ID]
        .item
        .as_ref()
        .unwrap()
        .text_form()
        .unwrap();
    assert_eq!(text, "<p>Soup with lemon</p><p>Carrots</p>");

    let turn_id = session.take_assistant_undo(ID).unwrap();
    session
        .apply_assistant_op(ID, super::ops_json::AssistantOp::Undo { turn_id }, 3)
        .unwrap();
    let text = session.slots[ID]
        .item
        .as_ref()
        .unwrap()
        .text_form()
        .unwrap();
    assert_eq!(text, "<p>Soup with lemon</p><p>Onions</p>");
}

#[test]
fn revoked_reconnect_offers_pending_text_without_sending_the_outbox() {
    for reason in ["not_found", "access_revoked"] {
        let (mut session, peer) = open_sheet();
        session.set_connected(false);
        let offline = session
            .apply_local_op(ID, first_cell_op(&peer, "offline draft"), 5)
            .unwrap();
        assert!(sends(&offline, "live_item_update").is_empty());
        let pending_id = offline
            .iter()
            .find_map(|action| match action {
                Action::PersistOutbox { entries, .. } => entries.last(),
                _ => None,
            })
            .unwrap()
            .client_msg_id
            .clone();
        let reconnect = session.set_connected(true);
        assert_eq!(sends(&reconnect, "live_item_subscribe").len(), 1);
        assert!(sends(&reconnect, "live_item_update").is_empty());
        let refused = json!({"item_id": ID, "reason": reason});
        let out = session.on_frame("live_item_refused", &refused, 6).unwrap();
        assert!(out.iter().any(|action| matches!(action,
            Action::Emit(Event::PrivateCopy { copy_id, text, .. })
                if copy_id == &pending_id && text.contains("offline draft")
        )));
        assert_eq!(statuses(&out), [Status::AccessRevoked]);
        assert!(sends(&out, "live_item_update").is_empty());
        assert!(
            session
                .on_frame("live_item_refused", &refused, 7)
                .unwrap()
                .is_empty()
        );
    }
}
