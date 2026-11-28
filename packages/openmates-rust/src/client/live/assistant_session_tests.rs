//! Assistant changes in a `LiveSession` with a fake server: merge, outcomes, queue, presence,
//! suggestions and undo.

use super::assistant::{AssistantResult, PinnedBase, apply_assistant_change};
use super::ops_json::{AssistantOp, parse_assistant_op};
use super::session::LiveSession;
use super::session_types::{Action, Event};
use super::support::ID;
use super::{LiveItemKind, LocalOp, SheetOp};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};

const CODE: &str = "line a\nline b\nline c\nline d\nline e\nline f\nline g\nline h\n";
const SHEET: &str = "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |";

fn open(kind: LiveItemKind, text: &str) -> LiveSession {
    let mut s = LiveSession::default();
    s.set_connected(true);
    s.open(ID, kind);
    s.provide_keys(
        ID,
        super::driver::LiveKeys {
            epoch: 1,
            current: zeroize::Zeroizing::new(super::support::KEY),
            previous: vec![],
        },
        Vec::new(),
    )
    .unwrap();
    let state = json!({"item_id": ID, "role": "edit", "updates": [], "head_seq": 0});
    let out = s.on_frame("live_item_state", &state, 0).unwrap();
    assert!(out.iter().any(|a| matches!(a, Action::NeedContent { .. })));
    s.provide_content(ID, text, 0).unwrap();
    s
}

fn change(turn: &str, base: &str, new: &str) -> Value {
    json!({"embed_id": ID, "turn_id": turn, "base_text_form": base, "new_text_form": new,
        "mate_name": "Sophia", "scope": ["@@ -1,1 +1,1 @@"]})
}

fn outcomes(actions: &[Action]) -> Vec<&Value> {
    actions
        .iter()
        .filter_map(|a| match a {
            Action::PostAssistantOutcome { body, .. } => Some(body),
            _ => None,
        })
        .collect()
}

fn update_ids(actions: &[Action]) -> Vec<String> {
    actions
        .iter()
        .filter_map(|a| match a {
            Action::Send {
                message_type: "live_item_update",
                payload,
            } => payload["client_msg_id"].as_str().map(str::to_string),
            _ => None,
        })
        .collect()
}

fn ack(s: &mut LiveSession, id: &str, seq: u64) -> Vec<Action> {
    s.on_frame(
        "live_item_update_ack",
        &json!({"item_id": ID, "client_msg_id": id, "seq": seq}),
        5,
    )
    .unwrap()
}

fn text(s: &LiveSession) -> String {
    s.slots[ID].item.as_ref().unwrap().text_form().unwrap()
}

fn with_line(t: &str, n: usize, new: &str) -> String {
    let mut l: Vec<&str> = t.split('\n').collect();
    l[n] = new;
    l.join("\n")
}

fn type_line(s: &mut LiveSession, n: usize, v: &str) {
    s.apply_local_op(
        ID,
        LocalOp::CodeReplaceLines {
            start: n,
            end: n + 1,
            text: v.into(),
        },
        1,
    )
    .unwrap();
}

#[test]
fn change_while_user_types_elsewhere_keeps_both_and_posts_applied() {
    let mut s = open(LiveItemKind::Code, CODE);
    type_line(&mut s, 0, "HUMAN a");
    let out = s
        .on_frame(
            "embed_assistant_change",
            &change("t1", CODE, &with_line(CODE, 6, "BOT g")),
            2,
        )
        .unwrap();
    let t = text(&s);
    assert!(t.starts_with("HUMAN a\n") && t.contains("BOT g"));
    let body = outcomes(&out)[0].clone();
    assert_eq!(body["outcome"], "applied");
    assert_eq!(body["turn_id"], "t1");
    assert_eq!(body["details"]["current_text_form"], t);
    assert!(!update_ids(&out).is_empty());
}

#[test]
fn same_spot_posts_same_spot_and_keeps_human_text() {
    let mut s = open(LiveItemKind::Code, CODE);
    type_line(&mut s, 1, "human b");
    let out = s
        .on_frame(
            "embed_assistant_change",
            &change("t1", CODE, &with_line(CODE, 1, "bot b")),
            2,
        )
        .unwrap();
    let body = outcomes(&out)[0];
    assert_eq!(body["outcome"], "same_spot");
    assert_eq!(body["details"]["same_spot"][0]["human_value"], "human b\n");
    assert!(text(&s).contains("human b") && !text(&s).contains("bot b"));
}

#[test]
fn deleted_target_posts_target_deleted() {
    let mut s = open(LiveItemKind::Code, CODE);
    s.apply_local_op(
        ID,
        LocalOp::CodeReplaceLines {
            start: 2,
            end: 3,
            text: String::new(),
        },
        1,
    )
    .unwrap();
    let out = s
        .on_frame(
            "embed_assistant_change",
            &change("t1", CODE, &with_line(CODE, 2, "bot c")),
            2,
        )
        .unwrap();
    assert_eq!(outcomes(&out)[0]["outcome"], "target_deleted");
    assert!(!text(&s).contains("bot c"));
}

#[test]
fn second_change_queues_until_the_first_is_acknowledged() {
    let mut s = open(LiveItemKind::Code, CODE);
    let one = s
        .on_frame(
            "embed_assistant_change",
            &change("t1", CODE, &with_line(CODE, 0, "one")),
            2,
        )
        .unwrap();
    let two_base = text(&s);
    let queued = s
        .on_frame(
            "embed_assistant_change",
            &change("t2", &two_base, &with_line(&two_base, 7, "two")),
            3,
        )
        .unwrap();
    assert!(outcomes(&queued).is_empty() && !text(&s).contains("two"));
    let id = update_ids(&one).remove(0);
    let done = ack(&mut s, &id, 1);
    assert_eq!(outcomes(&done)[0]["turn_id"], "t2");
    assert!(text(&s).contains("two") && text(&s).contains("one"));
}

#[test]
fn foreign_lock_retries_on_tick_after_finish() {
    let mut s = open(LiveItemKind::Code, CODE);
    let item = s.slots.get_mut(ID).unwrap().item.as_mut().unwrap();
    let base = PinnedBase::pin(item).unwrap();
    assert!(matches!(
        apply_assistant_change(item, &base, &with_line(CODE, 0, "x"), "foreign").unwrap(),
        AssistantResult::Applied(_)
    ));
    let held = s
        .on_frame(
            "embed_assistant_change",
            &change("t1", CODE, &with_line(CODE, 7, "late")),
            2,
        )
        .unwrap();
    assert!(outcomes(&held).is_empty());
    super::assistant::finish_assistant_change(
        s.slots.get_mut(ID).unwrap().item.as_mut().unwrap(),
        "foreign",
    );
    let out = s.tick(3);
    assert_eq!(outcomes(&out)[0]["turn_id"], "t1");
}

#[test]
fn version_only_change_asks_for_the_base_then_applies() {
    let mut s = open(LiveItemKind::Code, CODE);
    let frame = json!({"embed_id": ID, "turn_id": "t1", "base_version": 4,
        "new_text_form": with_line(CODE, 7, "BOT h"), "mate_name": "Sophia", "scope": []});
    let out = s.on_frame("embed_assistant_change", &frame, 2).unwrap();
    assert!(matches!(
        &out[0],
        Action::AssistantNeedBase {
            base_version: 4,
            ..
        }
    ));
    let out = s.provide_assistant_base(ID, "t1", CODE, 3).unwrap();
    assert_eq!(outcomes(&out)[0]["outcome"], "applied");
    let mut s = open(LiveItemKind::Code, CODE);
    s.on_frame("embed_assistant_change", &frame, 2).unwrap();
    let out = s.fail_assistant_base(ID, "t1", 3);
    assert_eq!(outcomes(&out)[0]["outcome"], "needs_recheck");
}

#[test]
fn unopened_item_returns_not_open() {
    let mut s = LiveSession::default();
    let out = s
        .on_frame("embed_assistant_change", &change("t1", CODE, CODE), 0)
        .unwrap();
    assert!(matches!(out[0], Action::AssistantChangeNotOpen { .. }));
}

fn peers(actions: &[Action]) -> Vec<&Value> {
    actions
        .iter()
        .filter_map(|a| match a {
            Action::Emit(Event::Presence { peers, .. }) => Some(peers),
            _ => None,
        })
        .collect()
}

#[test]
fn editing_event_shows_mate_presence_until_applied_or_sixty_seconds() {
    let mut s = open(LiveItemKind::Code, CODE);
    let edit = json!({"embed_id": ID, "scope": ["@@ -1,2 +1,2 @@"], "mate_name": "Sophia"});
    let out = s.on_frame("embed_assistant_editing", &edit, 100).unwrap();
    assert_eq!(peers(&out)[0][0]["mate_name"], "Sophia");
    assert_eq!(peers(&out)[0][0]["mate"]["mate_name"], "Sophia");
    assert_eq!(
        peers(&out)[0][0]["mate"]["editing_scope"],
        "@@ -1,2 +1,2 @@"
    );
    assert!(peers(&s.tick(100 + 59_000)).is_empty());
    assert!(
        peers(&s.tick(100 + 60_000))[0]
            .as_array()
            .unwrap()
            .is_empty()
    );
    s.on_frame("embed_assistant_editing", &edit, 200_000)
        .unwrap();
    let out = s
        .on_frame(
            "embed_assistant_change",
            &change("t1", CODE, &with_line(CODE, 0, "x")),
            200_001,
        )
        .unwrap();
    assert!(peers(&out)[0].as_array().unwrap().is_empty());
}

fn sheet_ids(s: &LiveSession) -> (Vec<String>, Vec<String>) {
    s.slots[ID].item.as_ref().unwrap().sheet_ids().unwrap()
}

fn sheet_view(actions: &[Action]) -> Option<&Value> {
    actions.iter().rev().find_map(|a| match a {
        Action::Emit(Event::View { view, .. }) => Some(view),
        _ => None,
    })
}

#[test]
fn sheet_suggestion_is_in_the_view_and_can_be_dismissed() {
    let mut s = open(LiveItemKind::Sheet, SHEET);
    let (rows, cols) = sheet_ids(&s);
    s.apply_local_op(
        ID,
        LocalOp::Sheet(SheetOp::SetCell {
            row_id: rows[0].clone(),
            col_id: cols[0].clone(),
            value: "human".into(),
        }),
        1,
    )
    .unwrap();
    let new = "| A | B |\n| --- | --- |\n| bot | 2 |\n| 3 | 40 |";
    let out = s
        .on_frame("embed_assistant_change", &change("t1", SHEET, new), 2)
        .unwrap();
    let key = format!("{}:{}", rows[0], cols[0]);
    let view = sheet_view(&out).expect("view");
    assert_eq!(view["cells"][&key]["suggestion"]["assistant_value"], "bot");
    assert_eq!(view["cells"][&key]["display"], "human");
    assert_eq!(
        outcomes(&out)[0]["details"]["suggestions"][0]["anchor"],
        key
    );
    let op = parse_assistant_op(&format!(
        r#"{{"op":"dismiss_suggestion","row_id":"{}","col_id":"{}"}}"#,
        rows[0], cols[0]
    ))
    .unwrap()
    .unwrap();
    let out = s.apply_assistant_op(ID, op, 3).unwrap();
    assert!(
        sheet_view(&out).unwrap()["cells"][&key]
            .get("suggestion")
            .is_none()
    );
}

#[test]
fn sheet_base_version_text_reconstructs_ids_after_a_row_was_inserted() {
    let mut s = open(LiveItemKind::Sheet, SHEET);
    let (rows, _) = sheet_ids(&s);
    s.apply_local_op(
        ID,
        LocalOp::Sheet(SheetOp::InsertRow { after_row_id: None }),
        1,
    )
    .unwrap();
    let new = "| A | B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 40 |";
    let out = s
        .on_frame("embed_assistant_change", &change("t1", SHEET, new), 2)
        .unwrap();
    assert_eq!(outcomes(&out)[0]["outcome"], "applied");
    assert!(text(&s).contains("40"));
    let _ = rows;
}

#[test]
fn undo_assistant_op_reverts_the_turn_and_keeps_human_edits() {
    let mut s = open(LiveItemKind::Code, CODE);
    let out = s
        .on_frame(
            "embed_assistant_change",
            &change("t1", CODE, &with_line(CODE, 7, "BOT h")),
            2,
        )
        .unwrap();
    ack(&mut s, &update_ids(&out)[0], 1);
    type_line(&mut s, 0, "HUMAN a");
    let op = parse_assistant_op(r#"{"op":"undo_assistant","turn_id":"t1"}"#)
        .unwrap()
        .unwrap();
    assert_eq!(
        op,
        AssistantOp::Undo {
            turn_id: "t1".into()
        }
    );
    let out = s.apply_assistant_op(ID, op, 10).unwrap();
    assert!(!update_ids(&out).is_empty());
    let t = text(&s);
    assert!(t.contains("line h") && !t.contains("BOT h") && t.starts_with("HUMAN a"));
    assert!(
        parse_assistant_op(r#"{"op":"insert_row"}"#)
            .unwrap()
            .is_none()
    );
}

#[test]
fn deck_requester_undoes_the_whole_assistant_turn_and_keeps_peer_text() {
    let deck = r#"<deck title="Review" aspect="16:9" template="builtin:plain">
  <slide id="s1">
    <text id="e1" x="80" y="60" w="1200" h="120">First point</text>
    <text id="e2" x="80" y="260" w="1200" h="120">Second point</text>
    <text id="e3" x="80" y="460" w="1200" h="120">Human notes</text>
  </slide>
</deck>
"#;
    let mut session = open(LiveItemKind::Deck, deck);
    let mut peer =
        super::support::peer(LiveItemKind::Deck, session.slots[ID].item.as_ref().unwrap());
    let seed = session.slots[ID].item.as_ref().unwrap().outbox()[0]
        .client_msg_id
        .clone();
    ack(&mut session, &seed, 1);
    let assistant = deck
        .replace("First point", "New first")
        .replace("Second point", "New second");
    let actions = session
        .on_frame("embed_assistant_change", &change("t1", deck, &assistant), 2)
        .unwrap();
    let ids = update_ids(&actions);
    assert_eq!(ids.len(), 1);
    assert!(
        actions.iter().any(
            |a| matches!(a, Action::Emit(Event::View { view, .. }) if view["can_undo"] == true)
        )
    );
    let applied = &session.slots[ID].item.as_ref().unwrap().outbox()[0];
    peer.apply_remote(2, &applied.sealed).unwrap();
    ack(&mut session, &ids[0], 2);
    let added = peer
        .apply_local_op(LocalOp::Deck(
            crate::client::shared_items::DeckOperation::SetTextContent {
                slide_id: "s1".into(),
                element_id: "e3".into(),
                markup: "Keep this peer edit".into(),
            },
        ))
        .unwrap()
        .update
        .unwrap();
    let incoming = json!({
        "item_id": ID, "seq": 3, "epoch": 1, "sender": "peer",
        "payload": STANDARD.encode(&added.sealed),
    });
    session.on_frame("live_item_update", &incoming, 3).unwrap();

    let turn_id = session.take_assistant_undo(ID).unwrap();
    let actions = session
        .apply_assistant_op(ID, AssistantOp::Undo { turn_id }, 4)
        .unwrap();
    assert_eq!(update_ids(&actions).len(), 1);
    assert!(
        actions.iter().any(
            |a| matches!(a, Action::Emit(Event::View { view, .. }) if view["can_undo"] == false)
        )
    );
    let reverted = session.slots[ID]
        .item
        .as_ref()
        .unwrap()
        .outbox()
        .last()
        .unwrap();
    peer.apply_remote(4, &reverted.sealed).unwrap();
    let expected = deck.replace("Human notes", "Keep this peer edit");
    assert_eq!(text(&session), expected);
    assert_eq!(peer.text_form().unwrap(), expected);
    assert!(session.take_assistant_undo(ID).is_none());
}
