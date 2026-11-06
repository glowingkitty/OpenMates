//! API-key chat rewrite: state decoding from `/v1/sdk/chats/{id}` rows and the shared fork/rewind/retry bodies.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use crate::client::chat_rewrite::{self, ChatRewriteState, PERSONAL_ONLY};
use crate::crypto;
use serde_json::{Value, json};

const CHAT: &str = "11111111-1111-4111-8111-111111111111";
const SOURCE: [u8; 32] = [5; 32];
const MASTER: [u8; 32] = [6; 32];

fn enc(text: &str) -> String {
    crypto::encrypt_combined(text, &SOURCE).unwrap()
}
fn chat_row() -> Value {
    json!({"id": CHAT, "encrypted_title": enc("Synthetic"), "encrypted_chat_key": "wrapped", "messages_v": 3})
}
fn rows() -> Vec<Value> {
    vec![
        json!({"message_id":"m1","chat_id":CHAT,"role":"user","encrypted_content":enc("first"),"created_at":1}),
        // The server may return rows as JSON strings; the shared decoder accepts both.
        Value::String(
            json!({"message_id":"m2","chat_id":CHAT,"role":"assistant","encrypted_content":enc("answer"),"created_at":2})
                .to_string(),
        ),
        json!({"message_id":"m3","chat_id":CHAT,"role":"user","encrypted_content":enc("retry me"),"created_at":3}),
    ]
}
fn state() -> ChatRewriteState {
    ChatRewriteState::from_encrypted_rows(CHAT, &chat_row(), &rows(), &SOURCE).unwrap()
}

#[test]
fn decodes_owner_rows_with_the_shared_decoder() {
    let s = state();
    assert_eq!(s.chat_id(), CHAT);
    assert_eq!(s.title(), "Synthetic");
    assert_eq!(s.messages_v(), 3);
    let contents: Vec<&str> = s.messages().iter().map(|m| m.content.as_str()).collect();
    assert_eq!(contents, ["first", "answer", "retry me"]);
    assert_eq!(s.boundary_index("m2"), Some(1));
    assert_eq!(s.server_message_id(1).unwrap(), "m2");
}

#[test]
fn refuses_team_direct_keyless_and_foreign_rows_before_any_request() {
    let mut team = chat_row();
    team["hashed_team_id"] = json!("team-hash");
    let err = ChatRewriteState::from_encrypted_rows(CHAT, &team, &rows(), &SOURCE).err().unwrap();
    assert_eq!(err.to_string(), PERSONAL_ONLY);
    let mut direct = chat_row();
    direct["chat_visibility"] = json!("direct");
    assert!(ChatRewriteState::from_encrypted_rows(CHAT, &direct, &rows(), &SOURCE).is_err());
    let mut keyless = chat_row();
    keyless["encrypted_chat_key"] = Value::Null;
    assert!(ChatRewriteState::from_encrypted_rows(CHAT, &keyless, &rows(), &SOURCE).is_err());
    let other = "22222222-2222-4222-8222-222222222222";
    assert!(ChatRewriteState::from_encrypted_rows(other, &chat_row(), &rows(), &SOURCE).is_err());
    let mut foreign = rows();
    foreign[0]["chat_id"] = json!(other);
    assert!(ChatRewriteState::from_encrypted_rows(CHAT, &chat_row(), &foreign, &SOURCE).is_err());
    assert!(ChatRewriteState::from_encrypted_rows(CHAT, &chat_row(), &rows(), &[9; 32]).is_err());
}

#[test]
fn fork_body_copies_the_slice_under_a_key_wrapped_by_the_account_key() {
    let s = state();
    let key = crypto::random_key();
    let wrapped = crypto::encrypt_bytes(&key[..], &MASTER).unwrap();
    let body = chat_rewrite::fork_request(&s, 1, None, &SOURCE, &key, wrapped).unwrap();
    assert_eq!(body["from_message_id"], "m2");
    assert_eq!(body["expected_source_messages_v"], 3);
    let messages = body["encrypted_messages"].as_array().unwrap();
    assert_eq!(messages.len(), 2);
    let metadata = &body["encrypted_chat_metadata"];
    assert_eq!(metadata["id"], body["new_chat_id"]);
    let opened = crypto::decrypt_bytes(metadata["encrypted_chat_key"].as_str().unwrap(), &MASTER).unwrap();
    assert_eq!(opened.as_slice(), &key[..]);
    let title = crypto::decrypt_combined(metadata["encrypted_title"].as_str().unwrap(), &key).unwrap();
    assert_eq!(title, "Fork of Synthetic");
    let text = body.to_string();
    assert!(!text.contains("answer") && !text.contains("first"));
}

#[test]
fn rewind_and_retry_require_confirmation_unless_dry_run() {
    let s = state();
    assert!(chat_rewrite::rewind_request(&s, 0, false, false).is_err());
    let dry = chat_rewrite::rewind_request(&s, 0, true, false).unwrap();
    assert_eq!(dry["to_message_id"], "m1");
    assert_eq!(dry["expected_messages_v"], 3);
    assert_eq!(dry["dry_run"], true);
    assert!(chat_rewrite::retry_plan(&s, false, false).is_err());
    let target = chat_rewrite::retry_plan(&s, true, false).unwrap();
    assert_eq!(target.boundary_index, 1);
    assert_eq!(target.prompt.as_str(), "retry me");
}

/// The API-key session response whose wrapper unwraps to `MASTER` with the
/// local setup suffix `"s" * 32` (the same derivation the SDK uses).
fn session_with_wrapper() -> Value {
    use base64::{Engine, engine::general_purpose::STANDARD};
    let (salt, iv) = ([3u8; 16], [4u8; 12]);
    let mut wrapping = zeroize::Zeroizing::new([0u8; 32]);
    pbkdf2::pbkdf2_hmac::<sha2::Sha256>("s".repeat(32).as_bytes(), &salt, 100_000, &mut *wrapping);
    let encrypted = crypto::encrypt_aead(&MASTER, &wrapping, &iv, &[]).unwrap();
    json!({"key_wrapper": {"salt": STANDARD.encode(salt), "key_iv": STANDARD.encode(iv), "encrypted_key": STANDARD.encode(encrypted)}})
}
fn sdk(api: String) -> crate::OpenMates {
    crate::OpenMates::new(crate::SdkOptions {
        api_url: api,
        credentials: crate::SdkCredentials::ApiKey(
            crate::ApiKey::new(&format!("sk-api-{}.{}", "b".repeat(32), "s".repeat(32))).unwrap(),
        ),
        device_id: "fixture-device".into(),
        client_options: crate::ClientOptions::default(),
    })
    .unwrap()
}
fn loaded_chat() -> Value {
    let mut chat = chat_row();
    chat["encrypted_chat_key"] = json!(crypto::encrypt_bytes(&SOURCE, &MASTER).unwrap());
    json!({"chat": chat, "messages": rows(), "embeds": [], "embed_keys": [], "chat_key_wrappers": []})
}

#[tokio::test]
async fn fork_reads_the_owner_chat_and_posts_to_the_sdk_route_without_plaintext() {
    let response = json!({"success": true, "chat_id": "new", "copied_message_count": 2});
    let (api, server) =
        crate::sdk::tests::server(vec![(200, loaded_chat()), (200, session_with_wrapper()), (200, response.clone())]).await;
    let mut client = sdk(api);
    let rewrite = client.chats().rewrite_state(CHAT).await.unwrap();
    let index = rewrite.state().boundary_index("m2").unwrap();
    let result = client.chats().fork(&rewrite, index, Some("Copy")).await.unwrap();
    assert_eq!(result, response);
    let requests = server.await.unwrap();
    assert!(requests[0].0.starts_with(&format!("GET /v1/sdk/chats/{CHAT} ")));
    assert!(requests[2].0.starts_with(&format!("POST /v1/sdk/chats/{CHAT}/fork ")));
    let sent = &requests[2].1;
    assert_eq!(sent["from_message_id"], "m2");
    assert_eq!(sent["encrypted_messages"].as_array().unwrap().len(), 2);
    let key = crypto::decrypt_bytes(sent["encrypted_chat_metadata"]["encrypted_chat_key"].as_str().unwrap(), &MASTER).unwrap();
    let key: [u8; 32] = key.as_slice().try_into().unwrap();
    assert_eq!(crypto::decrypt_combined(sent["encrypted_chat_metadata"]["encrypted_title"].as_str().unwrap(), &key).unwrap(), "Copy");
    for (header, body) in &requests {
        assert!(!header.to_ascii_lowercase().contains("cookie:"));
        assert!(!header.contains(&"s".repeat(32)) && !body.to_string().contains("answer"));
    }
}

#[tokio::test]
async fn dry_run_rewind_posts_the_shared_body_and_unconfirmed_rewind_sends_nothing() {
    let dry = json!({"success": true, "dry_run": true, "planned_deleted_message_count": 2});
    let (api, server) =
        crate::sdk::tests::server(vec![(200, loaded_chat()), (200, session_with_wrapper()), (200, dry.clone())]).await;
    let mut client = sdk(api);
    let rewrite = client.chats().rewrite_state(CHAT).await.unwrap();
    assert!(client.chats().rewind(&rewrite, 0, false, false).await.is_err());
    assert!(client.chats().retry(&rewrite, false, false).await.is_err());
    let (result, prompt) = client.chats().retry(&rewrite, true, false).await.unwrap();
    assert_eq!(result, dry);
    assert!(prompt.is_none());
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 3);
    assert!(requests[2].0.starts_with(&format!("POST /v1/sdk/chats/{CHAT}/rewind ")));
    assert_eq!(requests[2].1["to_message_id"], "m2");
    assert_eq!(requests[2].1["dry_run"], true);
}
