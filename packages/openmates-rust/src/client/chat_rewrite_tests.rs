// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
use super::*;

const SOURCE: [u8; 32] = [3; 32];

fn message(id: &str, role: &str, content: &str) -> Message {
    Message {
        id: id.into(),
        role: role.into(),
        content: content.into(),
        ..Message::default()
    }
}
fn state(messages: Vec<Message>, rows: Vec<Value>) -> ChatRewriteState {
    ChatRewriteState {
        chat: Chat {
            id: "11111111-1111-4111-8111-111111111111".into(),
            title: "Synthetic".into(),
            category: String::new(),
            messages,
        },
        rows,
        messages_v: 4,
    }
}
fn enc(text: &str) -> String {
    crypto::encrypt_combined(text, &SOURCE).unwrap()
}

#[test]
fn boundary_matches_exact_or_prefix_and_refuses_empty() {
    let messages = vec![message("aaaa-1", "user", "a"), message("bbbb-2", "assistant", "b")];
    assert_eq!(find_message_boundary_index(&messages, "bbbb-2"), Some(1));
    assert_eq!(find_message_boundary_index(&messages, "aaaa"), Some(0));
    assert_eq!(find_message_boundary_index(&messages, "cccc"), None);
    assert_eq!(find_message_boundary_index(&messages, ""), None);
}

#[test]
fn retry_selects_newest_unanswered_user_turn() {
    let answered = vec![message("1", "user", "a"), message("2", "assistant", "b")];
    assert_eq!(find_retryable_user_message_index(&answered), None);
    let pending = vec![
        message("1", "user", "a"),
        message("2", "Assistant", "b"),
        message("3", "user", "retry me"),
        message("4", "system", "note"),
    ];
    assert_eq!(find_retryable_user_message_index(&pending), Some(2));
    let rows = (1..=4).map(|i| json!({"message_id": i.to_string()})).collect();
    let target = state(pending, rows).retry_target().unwrap();
    assert_eq!(target.boundary_index, 1);
    assert_eq!(target.prompt.as_str(), "retry me");
}

#[test]
fn retry_errors_keep_npm_wording() {
    let none = state(vec![message("1", "assistant", "a")], vec![json!({})]);
    assert_eq!(
        none.retry_target().err().unwrap().to_string(),
        "No retryable user message found for this chat."
    );
    let first = state(vec![message("1", "user", "a")], vec![json!({})]);
    assert_eq!(
        first.retry_target().err().unwrap().to_string(),
        "Cannot retry a chat whose first message is the failed user turn."
    );
}

#[test]
fn server_identity_prefers_message_id_like_the_backend() {
    let s = state(
        vec![message("client-1", "user", "a"), message("client-2", "user", "b")],
        vec![
            json!({"client_message_id":"client-1","message_id":"server-1"}),
            json!({}),
        ],
    );
    assert_eq!(s.server_message_id(0).unwrap(), "server-1");
    assert_eq!(s.server_message_id(1).unwrap(), "client-2");
    assert!(s.server_message_id(2).is_err());
    assert_eq!(s.messages_v(), 4);
}

#[test]
fn fork_reencrypts_each_field_under_the_new_key_and_maps_identity() {
    let rows = vec![
        json!({"message_id":"u1","role":"user","encrypted_content":enc("Hello [OM_PII_X]"),
               "encrypted_pii_mappings":enc("[{\"original\":\"Alice\"}]"),"created_at":10}),
        json!({"message_id":"a1","role":"assistant","encrypted_content":enc("Hi"),
               "encrypted_category":enc("general"),"encrypted_model_name":enc("synthetic-model"),
               "user_message_id":"u1","created_at":0}),
    ];
    let key = crypto::random_key();
    let out = fork_messages(&rows, &SOURCE, "new-chat", &key, 99).unwrap();
    assert_eq!(out.len(), 2);
    let decrypt = |v: &Value| crypto::decrypt_combined(v.as_str().unwrap(), &key).unwrap();
    assert_eq!(decrypt(&out[0]["encrypted_content"]), "Hello [OM_PII_X]");
    assert_eq!(decrypt(&out[0]["encrypted_sender_name"]), "User");
    assert_eq!(decrypt(&out[0]["encrypted_pii_mappings"]), "[{\"original\":\"Alice\"}]");
    assert_eq!(out[0]["created_at"], 10);
    assert_eq!(out[0]["chat_id"], "new-chat");
    assert_eq!(out[0]["message_id"], out[0]["client_message_id"]);
    assert_ne!(out[0]["message_id"], "u1");
    assert!(out[0].get("encrypted_category").is_none());
    assert_eq!(decrypt(&out[1]["encrypted_sender_name"]), "Assistant");
    assert_eq!(decrypt(&out[1]["encrypted_category"]), "general");
    assert_eq!(decrypt(&out[1]["encrypted_model_name"]), "synthetic-model");
    assert_eq!(out[1]["user_message_id"], out[0]["message_id"]);
    assert_eq!(out[1]["created_at"], 99);
    assert!(crypto::decrypt_combined(out[1]["encrypted_content"].as_str().unwrap(), &SOURCE).is_err());
    let text = serde_json::to_string(&out).unwrap();
    assert!(!text.contains("Alice") && !text.contains("Hello"));
}

#[test]
fn fork_refuses_rows_without_role() {
    let rows = vec![json!({"message_id":"u1","encrypted_content":enc("x")})];
    assert!(fork_messages(&rows, &SOURCE, "c", &crypto::random_key(), 1).is_err());
}

#[test]
fn boundary_selects_the_server_message_id_shown_by_chats_show() {
    let state = state(
        vec![message("client-a", "user", "hi"), message("client-b", "assistant", "hello")],
        vec![
            json!({"message_id": "server-a", "client_message_id": "client-a"}),
            json!({"message_id": "server-b", "client_message_id": "client-b"}),
        ],
    );
    assert_eq!(state.boundary_index("server-b"), Some(1));
    assert_eq!(state.boundary_index("server-a"), Some(0));
    assert_eq!(state.boundary_index("client-b"), Some(1));
    assert_eq!(state.boundary_index("server-"), Some(0));
    assert_eq!(state.boundary_index("missing"), None);
    assert_eq!(state.boundary_index(""), None);
}
