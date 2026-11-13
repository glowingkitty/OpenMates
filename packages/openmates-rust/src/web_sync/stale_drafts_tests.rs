//! Stale-draft probe eligibility and the plan applied to the server's answer.
use serde_json::{json, Value};

use super::{plan_json, probe_json, MIN_IDLE_SECONDS, PROBE_LIMIT};
use crate::web_sync::PROTOCOL;

const NOW: f64 = 1_800_000_000.0;
const STALE: &str = "00000000-0000-4000-8000-000000000001";

fn id(n: usize) -> String {
    format!("00000000-0000-4000-8000-{n:012}")
}

fn draft_only_row(chat_id: &str, touched: f64) -> Value {
    json!({
        "chat_id": chat_id, "messages_v": 0, "title_v": 0, "draft_v": 2,
        "encrypted_draft_md": "cipher", "encrypted_title": null, "team_id": null,
        "created_at": touched - 10.0, "updated_at": touched,
    })
}

fn probe(rows: Vec<Value>, pending: &[&str]) -> Value {
    let input = json!({"now": NOW, "rows": rows, "pendingChatIds": pending});
    serde_json::from_str(&probe_json(&input.to_string()).expect("valid input")).expect("json")
}

fn probed_ids(out: &Value) -> Vec<String> {
    out["wire"]
        .as_array()
        .expect("wire")
        .iter()
        .map(|e| e["chat_id"].as_str().expect("id").to_string())
        .collect()
}

// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
#[test]
fn selects_stale_draft_only_chat() {
    let out = probe(vec![draft_only_row(STALE, NOW - 3_600.0)], &[]);
    assert_eq!(out["wire"], json!([{"chat_id": STALE, "draft_v": 2}]));
    assert_eq!(
        out["probe"],
        json!([{"chatId": STALE, "draftV": 2, "draftOnly": true}])
    );
}

// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
#[test]
fn keeps_chat_with_pending_offline_change() {
    let out = probe(vec![draft_only_row(STALE, NOW - 3_600.0)], &[STALE]);
    assert!(probed_ids(&out).is_empty());
}

// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
#[test]
fn keeps_recently_saved_draft() {
    let young = draft_only_row(STALE, NOW - MIN_IDLE_SECONDS + 1.0);
    assert!(probed_ids(&probe(vec![young], &[])).is_empty());
    // Millisecond or skewed timestamps read as the future and stay local.
    let future = draft_only_row(STALE, NOW * 1000.0);
    assert!(probed_ids(&probe(vec![future], &[])).is_empty());
    let mut untimed = draft_only_row(STALE, NOW);
    for key in ["created_at", "updated_at"] {
        untimed.as_object_mut().expect("row").remove(key);
    }
    assert!(probed_ids(&probe(vec![untimed], &[])).is_empty());
}

// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
#[test]
fn keeps_team_and_private_scopes() {
    let base = draft_only_row(STALE, NOW - 3_600.0);
    for (key, value) in [
        ("team_id", json!("team-1")),
        ("team_draft_pending_sync", json!("update")),
        ("team_chat_pending_commit", json!(true)),
        ("chat_visibility", json!("direct")),
        ("is_incognito", json!(true)),
        ("is_anonymous", json!(true)),
        ("is_hidden_candidate", json!(true)),
    ] {
        let mut row = base.clone();
        row[key] = value;
        assert!(probed_ids(&probe(vec![row], &[])).is_empty(), "{key}");
    }
}

// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
#[test]
fn keeps_rows_without_a_draft_or_with_non_uuid_ids() {
    let mut no_cipher = draft_only_row(STALE, NOW - 3_600.0);
    no_cipher["encrypted_draft_md"] = json!("null");
    let mut zero = draft_only_row(STALE, NOW - 3_600.0);
    zero["draft_v"] = json!(0);
    let demo = draft_only_row("demo-for-everyone", NOW - 3_600.0);
    assert!(probed_ids(&probe(vec![no_cipher, zero, demo], &[])).is_empty());
}

// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
#[test]
fn marks_established_chat_drafts_as_not_draft_only() {
    let mut row = draft_only_row(STALE, NOW - 3_600.0);
    row["messages_v"] = json!(4);
    row["encrypted_title"] = json!("cipher-title");
    let out = probe(vec![row], &[]);
    assert_eq!(out["probe"][0]["draftOnly"], json!(false));
}

// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
#[test]
fn probes_oldest_first_and_bounded() {
    let rows: Vec<Value> = (0..PROBE_LIMIT + 25)
        .map(|n| draft_only_row(&id(n), NOW - 1_000.0 - n as f64))
        .collect();
    let ids = probed_ids(&probe(rows, &[]));
    assert_eq!(ids.len(), PROBE_LIMIT);
    assert_eq!(ids[0], id(PROBE_LIMIT + 24));
}

// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
#[test]
fn refuses_malformed_probe_input() {
    assert_eq!(probe_json(r#"{"rows":[]}"#), Err(PROTOCOL.to_string()));
    assert_eq!(
        probe_json(r#"{"now":1,"rows":[],"pendingChatIds":[1]}"#),
        Err(PROTOCOL.to_string())
    );
}

fn plan(probe: Value, result: Value) -> Value {
    let input = json!({"probe": probe, "result": result});
    serde_json::from_str(&plan_json(&input.to_string()).expect("valid input")).expect("json")
}

// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
#[test]
fn plans_deletion_only_for_probed_draft_only_absent_chats() {
    let probe = json!([
        {"chatId": id(1), "draftV": 2, "draftOnly": true},
        {"chatId": id(2), "draftV": 5, "draftOnly": false},
        {"chatId": id(3), "draftV": 1, "draftOnly": true},
        {"chatId": id(4), "draftV": 1, "draftOnly": true},
    ]);
    let result = json!({
        "absent_chat_ids": [id(1), id(2), id(9)],
        "draft_absent_chat_ids": [id(3)],
    });
    assert_eq!(
        plan(probe, result),
        json!([
            {"chatId": id(1), "action": "delete_draft_only", "draftV": 2},
            // Local content is never deleted on absence; only its draft clears.
            {"chatId": id(2), "action": "clear_draft", "draftV": 5},
            {"chatId": id(3), "action": "clear_draft", "draftV": 1},
        ])
    );
}

// contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
#[test]
fn unanswered_probe_changes_nothing() {
    let probe = json!([{"chatId": id(1), "draftV": 2, "draftOnly": true}]);
    assert_eq!(plan(probe, Value::Null), json!([]));
    assert_eq!(
        plan_json(r#"{"probe":[],"result":{"absent_chat_ids":"x","draft_absent_chat_ids":[]}}"#),
        Err(PROTOCOL.to_string())
    );
}
