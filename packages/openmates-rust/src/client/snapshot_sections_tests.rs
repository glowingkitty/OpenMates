// contract-test-file: tooling
use super::*;
use crate::client::Client;
use crate::session::Session;
use serde_json::json;

const A: &str = "11111111-1111-4111-8111-111111111111";
const B: &str = "22222222-2222-4222-8222-222222222222";

fn client() -> Client {
    Client::new(
        "https://api.example.test",
        Some(Session {
            api_url: "https://api.example.test".into(),
            session_id: "synthetic-session".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}
fn snapshot() -> Value {
    json!({
        "chats": {A: {"id": A, "encrypted_title": "ta"}, B: {"id": B, "encrypted_title": "tb"}},
        "wrappers": [{"hashed_chat_id": hex_sha256(A)}],
        "history": {A: [{"message_id": "m1", "encrypted_content": "x"}]},
        "embeds": {
            "e-a": {"embed_id": "e-a", "hashed_chat_id": hex_sha256(A)},
            "e-b": {"embed_id": "e-b", "hashed_chat_id": hex_sha256(B)},
            "e-free": {"embed_id": "e-free", "hashed_chat_id": null},
        },
        "embed_keys": [
            {"id": "k-a", "hashed_chat_id": hex_sha256(A)},
            {"id": "k-master", "hashed_chat_id": null},
        ],
        "team_wrapped_key": null,
        "sync_message_windows": {B: {"chat_id": B, "messages": []}},
        "future_top_level": {"kept": true},
    })
}
fn sorted_keys(mut value: Value) -> Value {
    if let Some(keys) = value.get_mut("embed_keys").and_then(Value::as_array_mut) {
        keys.sort_by(|a, b| a["id"].as_str().cmp(&b["id"].as_str()));
    }
    value
}

#[test]
fn split_places_list_inputs_per_chat_content_and_shared_rest_and_assembles_back() {
    let sections = split(snapshot()).unwrap();
    let index: Vec<_> = sections.index.keys().cloned().collect();
    assert_eq!(index, ["chats", "team_wrapped_key", "wrappers"]);
    assert_eq!(sections.chats.keys().cloned().collect::<Vec<_>>(), [A, B]);
    assert!(sections.chats[A]["history"].is_array());
    assert!(sections.chats[A]["embeds"]["e-a"].is_object());
    assert_eq!(sections.chats[A]["embed_keys"][0]["id"], "k-a");
    assert!(sections.chats[B]["sync_message_windows"].is_object());
    assert!(sections.shared["embeds"]["e-free"].is_object());
    assert_eq!(sections.shared["embed_keys"][0]["id"], "k-master");
    assert_eq!(sections.shared["future_top_level"]["kept"], true);
    let assembled = assemble(sections.index, Some(sections.shared), sections.chats).unwrap();
    assert_eq!(sorted_keys(assembled), sorted_keys(snapshot()));
}

#[test]
fn split_refuses_malformed_content_shapes() {
    for (field, value) in [("history", json!([])), ("embeds", json!([])), ("embed_keys", json!({}))] {
        let mut broken = snapshot();
        broken[field] = value;
        assert!(split(broken).is_err(), "{field}");
    }
    assert!(split(json!([])).is_err());
}

#[test]
fn partial_restore_loads_one_chat_then_completes_to_the_full_snapshot() {
    let mut full = client();
    let mut original = snapshot();
    original.as_object_mut().unwrap().remove("sync_message_windows");
    original.as_object_mut().unwrap().remove("future_top_level");
    full.restore_authenticated_ciphertext_snapshot(&original).unwrap();
    let expected = full.ciphertext_snapshot();
    let sections = split(expected.clone()).unwrap();
    let remainder = json!({
        "shared": sections.shared,
        "chats": {B: sections.chats[B]},
    });
    let calls = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let seen = calls.clone();
    let loader: crate::client::CachedContentLoader = std::sync::Arc::new(move |loaded: &[String]| {
        seen.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        assert_eq!(loaded, [A.to_owned()]);
        Ok(remainder.clone())
    });
    let mut partial = client();
    partial
        .restore_authenticated_ciphertext_index(&Value::Object(sections.index.clone()), loader)
        .unwrap();
    assert_eq!(partial.partially_restored_chats(), Some(vec![]));
    let only_index = partial.ciphertext_snapshot();
    assert!(only_index["embeds"].as_object().unwrap().is_empty());
    assert!(only_index["history"].as_object().unwrap().is_empty());
    partial
        .restore_cached_chat_content(A, Some(&Value::Object(sections.chats[A].clone())))
        .unwrap();
    assert_eq!(partial.partially_restored_chats(), Some(vec![A.to_owned()]));
    let one = partial.ciphertext_snapshot();
    assert_eq!(one["history"][A], expected["history"][A]);
    assert!(one["embeds"]["e-a"].is_object() && one["embeds"].get("e-b").is_none());
    partial.ensure_cached_content_loaded().unwrap();
    partial.ensure_cached_content_loaded().unwrap();
    assert_eq!(calls.load(std::sync::atomic::Ordering::SeqCst), 1);
    assert_eq!(partial.partially_restored_chats(), None);
    assert_eq!(sorted_keys(partial.ciphertext_snapshot()), sorted_keys(expected));
}

#[test]
fn held_content_wins_and_foreign_or_complete_restores_are_inert() {
    let mut partial = client();
    let sections = split(snapshot()).unwrap();
    let loader: crate::client::CachedContentLoader = std::sync::Arc::new(|_: &[String]| Ok(json!({"shared":null,"chats":{}})));
    partial
        .restore_authenticated_ciphertext_index(&Value::Object(sections.index.clone()), loader)
        .unwrap();
    // A section naming another Chat's history is refused unchanged.
    let foreign = json!({"history": [{"message_id": "m9"}]});
    let mut wrong = Map::new();
    wrong.insert("history".into(), foreign["history"].clone());
    let partial_a = chat_partial_snapshot(B, &Value::Object(wrong)).unwrap();
    assert!(partial_a["history"].get(B).is_some());
    assert!(partial.restore_cached_chat_content(A, Some(&json!({"embeds": []}))).is_err());
    assert_eq!(partial.partially_restored_chats(), Some(vec![]));
    // Complete clients ignore per-Chat restores.
    let mut complete = client();
    complete.restore_authenticated_ciphertext_snapshot(&json!({"chats":{},"wrappers":[]})).unwrap();
    complete
        .restore_cached_chat_content(A, Some(&Value::Object(sections.chats[A].clone())))
        .unwrap();
    assert!(complete.ciphertext_snapshot()["history"].as_object().unwrap().is_empty());
}
