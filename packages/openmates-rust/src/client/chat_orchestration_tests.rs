//! Unit tests of the chat orchestration core: parsing bounds, expiry, planning,
//! refusal, frames, event round trip, event lines and read bounding.
use super::*;

const JOB: &str = "11111111-1111-4111-8111-111111111111";
const CREATOR: &str = "22222222-2222-4222-8222-222222222222";
const SPAWNED: &str = "33333333-3333-4333-8333-333333333333";

fn job(kind: &str, payload: Value) -> Value {
    json!({"job_id": JOB, "kind": kind, "payload": payload, "created_at": 1000, "expires_at": 2000})
}

fn start() -> Value {
    job(
        "start_chat",
        json!({"spawned_chat_id": SPAWNED, "creator_chat_id": CREATOR, "title": "Research",
        "brief": "Find things", "event_message_id": "evt-1"}),
    )
}

fn read(limit: u64) -> Value {
    job(
        "read_chat",
        json!({"spawned_chat_id": SPAWNED, "creator_chat_id": CREATOR, "limit": limit}),
    )
}

fn send() -> Value {
    job(
        "send_message",
        json!({"spawned_chat_id": SPAWNED, "creator_chat_id": CREATOR, "text": "hello"}),
    )
}

fn creator_event(action: &str, text: Option<&str>) -> Value {
    let mut payload = json!({"creator_chat_id": CREATOR, "spawned_chat_id": SPAWNED, "action": action,
        "title": "Research", "event_message_id": "evt-2", "created_at": 1500});
    if let Some(text) = text {
        payload["text"] = json!(text);
    }
    job("creator_event", payload)
}

#[test]
fn parses_all_four_kinds() {
    for value in [
        start(),
        read(5),
        send(),
        creator_event("finished", None),
        creator_event("report", Some("done")),
    ] {
        let parsed = parse_job(&value, Some(1500)).expect("valid job");
        assert_eq!(parsed.to_value(), value);
    }
}

#[test]
fn rejects_expired_job_and_accepts_without_clock() {
    assert_eq!(
        parse_job(&start(), Some(2000)),
        Err(OrchestrationError::Expired)
    );
    assert_eq!(OrchestrationError::Expired.code(), "job_expired");
    assert!(parse_job(&start(), None).is_ok());
}

#[test]
fn rejects_bad_ids_kinds_and_bounds() {
    let mut bad = start();
    bad["job_id"] = json!("nope");
    assert_eq!(parse_job(&bad, None), Err(OrchestrationError::Invalid));
    assert!(parse_job(&job("other", json!({})), None).is_err());
    assert!(parse_job(&read(0), None).is_err());
    assert!(parse_job(&read(21), None).is_err());
    assert!(parse_job(&read(20), None).is_ok());
    let mut long_title = start();
    long_title["payload"]["title"] = json!("t".repeat(201));
    assert!(parse_job(&long_title, None).is_err());
    long_title["payload"]["title"] = json!("t".repeat(200));
    assert!(parse_job(&long_title, None).is_ok());
    let mut long_brief = start();
    long_brief["payload"]["brief"] = json!("b".repeat(8001));
    assert!(parse_job(&long_brief, None).is_err());
    let mut long_text = send();
    long_text["payload"]["text"] = json!("x".repeat(2001));
    assert!(parse_job(&long_text, None).is_err());
    let mut blank = send();
    blank["payload"]["text"] = json!("  ");
    assert!(parse_job(&blank, None).is_err());
    assert!(parse_job(&creator_event("bogus", None), None).is_err());
    assert!(parse_job(&creator_event("report", None), None).is_err());
    assert!(parse_job(&creator_event("finished", Some("x")), None).is_err());
}

#[test]
fn start_chat_plans_chat_creation_and_started_event() {
    let parsed = parse_job(&start(), Some(1500)).unwrap();
    let Effect::StartChat {
        chat_id,
        creator_chat_id,
        sender_name,
        job_id,
        started_event,
        ..
    } = plan_job(&parsed, None)
    else {
        panic!("expected start_chat");
    };
    assert_eq!(
        (chat_id.as_str(), creator_chat_id.as_str(), job_id.as_str()),
        (SPAWNED, CREATOR, JOB)
    );
    assert_eq!(sender_name, format!("chat:{CREATOR}"));
    assert_eq!(started_event.chat_id, CREATOR);
    assert_eq!(started_event.message_id, "evt-1");
    let event = parse_event(&started_event.content).unwrap();
    assert_eq!(
        (event.action, event.chat_id.as_str(), event.title.as_deref()),
        (Action::Started, SPAWNED, Some("Research"))
    );
}

#[test]
fn creator_event_stores_event_in_creator_chat() {
    let parsed = parse_job(&creator_event("report", Some("found it")), None).unwrap();
    let Effect::StoreEvent(store) = plan_job(&parsed, None) else {
        panic!("expected store_event")
    };
    assert_eq!(
        (
            store.chat_id.as_str(),
            store.message_id.as_str(),
            store.created_at
        ),
        (CREATOR, "evt-2", 1500)
    );
    assert_eq!(
        parse_event(&store.content).unwrap().text.as_deref(),
        Some("found it")
    );
}

#[test]
fn read_and_send_refuse_without_matching_local_link() {
    for value in [read(3), send()] {
        let parsed = parse_job(&value, None).unwrap();
        for local in [None, Some("44444444-4444-4444-8444-444444444444")] {
            assert_eq!(
                plan_job(&parsed, local),
                Effect::Reject {
                    job_id: JOB.into(),
                    error_code: "not_spawned_by_this_chat"
                }
            );
        }
    }
}

#[test]
fn read_and_send_run_with_matching_link() {
    let read_job = parse_job(&read(3), None).unwrap();
    assert_eq!(
        plan_job(&read_job, Some(CREATOR)),
        Effect::ReadChat {
            chat_id: SPAWNED.into(),
            limit: 3,
            job_id: JOB.into()
        }
    );
    let send_job = parse_job(&send(), None).unwrap();
    assert_eq!(
        plan_job(&send_job, Some(CREATOR)),
        Effect::SendMessage {
            chat_id: SPAWNED.into(),
            text: "hello".into(),
            sender_name: format!("chat:{CREATOR}"),
            job_id: JOB.into()
        }
    );
}

#[test]
fn effect_json_matches_web_contract() {
    let parsed = parse_job(&start(), None).unwrap();
    let value = plan_job(&parsed, None).to_value();
    assert_eq!(value["kind"], "start_chat");
    assert_eq!(value["started_event"]["kind"], "store_event");
    let reject = plan_job(&parse_job(&send(), None).unwrap(), None).to_value();
    assert_eq!(
        reject,
        json!({"kind": "reject", "job_id": JOB, "error_code": "not_spawned_by_this_chat"})
    );
}

#[test]
fn frames_and_answers() {
    assert_eq!(claim_frame(JOB), json!({"job_id": JOB}));
    assert_eq!(
        result_frame(JOB, true, None, Some(&json!({"a": 1}))),
        json!({"job_id": JOB, "ok": true, "result": {"a": 1}})
    );
    assert_eq!(
        result_frame(JOB, false, Some("user_active"), None)["error_code"],
        "user_active"
    );
    assert_eq!(
        result_frame(JOB, false, Some("weird"), None)["error_code"],
        "job_failed"
    );
    assert_eq!(
        result_frame(JOB, false, None, None)["error_code"],
        "job_failed"
    );
    let claim =
        parse_claim_result(&json!({"job_id": JOB, "granted": false, "reason": "taken"})).unwrap();
    assert!(!claim.granted && claim.reason.as_deref() == Some("taken"));
    assert!(parse_claim_result(&json!({"job_id": JOB})).is_err());
    let ack = parse_result_ack(&json!({"job_id": JOB, "accepted": true})).unwrap();
    assert!(ack.accepted && ack.reason.is_none());
    assert!(parse_result_ack(&json!({"job_id": "x", "accepted": true})).is_err());
}

#[test]
fn event_round_trips_and_rejects_bad_content() {
    let event = OrchestrationEvent {
        action: Action::Report,
        chat_id: SPAWNED.into(),
        title: Some("Research".into()),
        text: Some("done".into()),
        event_id: "e1".into(),
        created_at: 7,
    };
    assert_eq!(
        parse_event(&build_event(&event).unwrap()),
        Some(event.clone())
    );
    let mut no_text = event.clone();
    no_text.text = None;
    assert!(build_event(&no_text).is_err());
    assert!(parse_event("plain text").is_none());
    assert!(parse_event(r#"{"schema_version":1,"type":"context_entry"}"#).is_none());
    let content = build_event(&event)
        .unwrap()
        .replace("\"report\"", "\"explode\"");
    assert!(parse_event(&content).is_none());
    let content = build_event(&event)
        .unwrap()
        .replace("\"schema_version\":1", "\"schema_version\":2");
    assert!(parse_event(&content).is_none());
}

#[test]
fn sender_name_round_trips() {
    let name = creator_sender_name(CREATOR);
    assert_eq!(
        creator_from_sender_name(Some(&name)).as_deref(),
        Some(CREATOR)
    );
    assert_eq!(creator_from_sender_name(Some("chat:not-a-uuid")), None);
    assert_eq!(creator_from_sender_name(Some("User")), None);
    assert_eq!(creator_from_sender_name(None), None);
}

#[test]
fn event_lines_use_resolved_then_event_title() {
    let mut event = OrchestrationEvent {
        action: Action::Started,
        chat_id: SPAWNED.into(),
        title: Some("Old".into()),
        text: None,
        event_id: "e".into(),
        created_at: 1,
    };
    assert_eq!(event_line(&event, Some("New")), "Started chat New");
    assert_eq!(event_line(&event, None), "Started chat Old");
    event.title = None;
    assert_eq!(event_line(&event, None), "Started chat a chat");
    event.action = Action::Finished;
    assert_eq!(event_line(&event, Some("X")), "X finished");
    event.action = Action::WaitingForUser;
    assert_eq!(event_line(&event, Some("X")), "X is waiting for you");
    event.action = Action::UserWrote;
    assert_eq!(event_line(&event, Some("X")), "You wrote in X");
    event.action = Action::Report;
    event.text = Some("hi".into());
    assert_eq!(event_line(&event, Some("X")), "Report from X: hi");
}

fn msg(role: &str, content: &str, at: i64) -> ReadMessage {
    ReadMessage {
        role: role.into(),
        content: content.into(),
        created_at: at,
    }
}

#[test]
fn read_result_keeps_last_messages_and_drops_unknown_roles() {
    let messages = vec![
        msg("user", "a", 1),
        msg("tool", "skip", 2),
        msg("assistant", "b", 3),
        msg("system", "c", 4),
    ];
    let result = bound_read_result(&messages, 2);
    let rows = result["messages"].as_array().unwrap();
    assert_eq!(rows.len(), 2);
    assert_eq!(
        (rows[0]["content"].as_str(), rows[1]["role"].as_str()),
        (Some("b"), Some("system"))
    );
    assert_eq!(rows[0]["created_at"], 3);
}

#[test]
fn read_result_bounds_each_message_and_total_on_char_boundaries() {
    let big = "é".repeat(5000);
    let result = bound_read_result(&[msg("user", &big, 1)], 5);
    assert_eq!(
        result["messages"][0]["content"]
            .as_str()
            .unwrap()
            .chars()
            .count(),
        2000
    );
    let many: Vec<ReadMessage> = (0..10).map(|i| msg("user", &"x".repeat(2000), i)).collect();
    let result = bound_read_result(&many, 20);
    let total: usize = result["messages"]
        .as_array()
        .unwrap()
        .iter()
        .map(|m| m["content"].as_str().unwrap().chars().count())
        .sum();
    assert_eq!(total, 12_000);
    assert_eq!(result["messages"].as_array().unwrap().len(), 6);
    assert_eq!(bound_read_result(&[], 5), json!({"messages": []}));
}
