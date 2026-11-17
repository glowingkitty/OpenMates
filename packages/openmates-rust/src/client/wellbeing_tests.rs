//! Wellbeing history: round trip, event persistence effect, validation, clearing, payload inclusion.
use super::focus::FocusPersistencePlan;
use super::wellbeing::{EVENT_KIND, FIELD, encrypt_event};
use super::*;

fn scores() -> Value {
    json!([{"t":1700000000u64,"s":{"suicidal":0.25,"hopelessness_isolation":0.5}}])
}
fn event() -> Value {
    json!({"chat_id":"chat","scores":scores()})
}

#[test]
fn encrypted_history_round_trips() {
    let key = [3; 32];
    let encrypted = encrypt_event(&event(), "chat", &key).unwrap().unwrap();
    let plain = crypto::decrypt_combined(&encrypted, &key).unwrap();
    assert_eq!(serde_json::from_str::<Value>(&plain).unwrap(), scores());
}

#[test]
fn event_persistence_sends_encrypted_metadata_and_updates_row() {
    let key = [4; 32];
    let mut previous = json!({"focus": {"keep": true}});
    let mut plan =
        FocusPersistencePlan::prepare(EVENT_KIND, &event(), "chat", &key, &mut previous).unwrap();
    let (kind, payload, ack) = plan
        .next_effect(&key, || Ok(Some("team".into())))
        .unwrap()
        .unwrap()
        .into_wire();
    assert_eq!(kind, "encrypted_chat_metadata");
    assert_eq!(payload["team_id"], "team");
    let plain = crypto::decrypt_combined(payload[FIELD].as_str().unwrap(), &key).unwrap();
    assert_eq!(serde_json::from_str::<Value>(&plain).unwrap(), scores());
    assert_eq!(
        ack.unwrap().wire_parts(),
        ("encrypted_metadata_stored", "chat_id", "chat")
    );
    assert!(plan.next_effect(&key, || Ok(None)).unwrap().is_none());
    let mut chats = BTreeMap::from([("chat".into(), json!({"keep": true}))]);
    plan.into_update()
        .unwrap()
        .apply_to_chats("chat", &mut chats, &mut previous)
        .unwrap();
    assert_eq!(chats["chat"][FIELD], payload[FIELD]);
    assert_eq!(
        previous,
        json!({"focus": {"keep": true}}),
        "focus state untouched"
    );
}

#[test]
fn empty_list_clears_the_field() {
    let key = [5; 32];
    let mut previous = json!({});
    let mut plan = FocusPersistencePlan::prepare(
        EVENT_KIND,
        &json!({"chat_id":"chat","scores":[]}),
        "chat",
        &key,
        &mut previous,
    )
    .unwrap();
    let (_, payload, _) = plan
        .next_effect(&key, || Ok(None))
        .unwrap()
        .unwrap()
        .into_wire();
    assert!(payload[FIELD].is_null());
    plan.next_effect(&key, || Ok(None)).unwrap();
    let mut chats = BTreeMap::from([("chat".into(), json!({FIELD: "old"}))]);
    plan.into_update()
        .unwrap()
        .apply_to_chats("chat", &mut chats, &mut previous)
        .unwrap();
    assert!(chats["chat"][FIELD].is_null());
}

#[test]
fn malformed_history_is_rejected() {
    let key = [6; 32];
    let bad = [
        json!([{"t":1,"s":{"unknown":0.5}}]),
        json!([{"t":1,"s":{"suicidal":1.5}}]),
        json!([{"t":1,"s":{"suicidal":-0.1}}]),
        json!([{"t":"x","s":{}}]),
        json!([{"t":1,"s":{},"extra":1}]),
        json!({"t":1}),
        Value::Array((0..9).map(|_| json!({"t":1,"s":{}})).collect()),
    ];
    for scores in bad {
        let event = json!({"chat_id":"chat","scores":scores});
        assert_eq!(
            encrypt_event(&event, "chat", &key).err(),
            Some(Error::Protocol)
        );
    }
    assert_eq!(
        encrypt_event(&json!({"chat_id":"other","scores":[]}), "chat", &key).err(),
        Some(Error::Forbidden)
    );
}

#[test]
fn stored_history_decrypts_and_empty_means_none() {
    let key = [7; 32];
    let endpoint = "http://127.0.0.1:9";
    let session = serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).unwrap();
    let mut client = Client::new(endpoint, Some(session)).unwrap();
    assert!(
        client
            .current_wellbeing_scores("chat", &key)
            .unwrap()
            .is_none()
    );
    let encrypted = encrypt_event(&event(), "chat", &key).unwrap().unwrap();
    client
        .chats
        .insert("chat".into(), json!({FIELD: encrypted}));
    assert_eq!(
        client.current_wellbeing_scores("chat", &key).unwrap(),
        Some(scores())
    );
    client.chats.insert("chat".into(), json!({FIELD: null}));
    assert!(
        client
            .current_wellbeing_scores("chat", &key)
            .unwrap()
            .is_none()
    );
}
