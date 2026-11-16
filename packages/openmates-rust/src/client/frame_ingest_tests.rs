// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
//! Frame ingest and `admit_chat`: message add, version bumps, ordering counter,
//! ignored frames, principal/team refusal, deletion and typed admit failures.
use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const CHAT: &str = "11111111-1111-4111-8111-111111111111";
const OTHER: &str = "33333333-3333-4333-8333-333333333333";
const OWNER: &str = "22222222-2222-4222-8222-222222222222";
const MASTER: [u8; 32] = [7; 32];
const KEY: [u8; 32] = [9; 32];

fn session(api: &str, team: Option<&str>) -> Session {
    Session {
        api_url: api.into(),
        session_id: "fixture-session".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture-cookie".into())]),
        ws_token: None,
        master_key: zeroize::Zeroizing::new(MASTER),
        hashed_email: "fixture-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: team.map(str::to_owned),
    }
}
fn client(api: &str, team: Option<&str>) -> Client {
    let mut client = Client::new(api, Some(session(api, team))).unwrap();
    client.user = json!({"id": OWNER});
    client
}
fn known() -> Client {
    let mut c = client("https://api.example.org", None);
    c.insert_chat_row(
        CHAT.into(),
        json!({"id": CHAT, "messages_v": 2,
            "encrypted_chat_key": crypto::encrypt_bytes(&KEY, &MASTER).unwrap()}),
    );
    c
}
fn added(id: &str, v: u64) -> Value {
    json!({"type":"new_chat_message","payload":{"chat_id":CHAT,"message_id":id,"role":"user",
        "encrypted_content":"sealed","created_at":5,"messages_v":v}})
}

#[tokio::test]
async fn message_added_stores_row_and_bumps_messages_v() {
    let mut c = known();
    let summary = c.ingest_socket_frames(&[added("m1", 3), added("m1", 3)]).await.unwrap();
    assert_eq!(summary.applied_seq, 2);
    assert_eq!(summary.changed_chats, vec![ChangedChat { chat_id: CHAT.into(), messages_v: Some(3) }]);
    assert_eq!(c.history[CHAT].len(), 1, "the same message id is stored once");
    assert_eq!(c.chats[CHAT]["messages_v"], 3);
}

#[tokio::test]
async fn plaintext_content_is_sealed_with_the_chat_key() {
    let mut c = known();
    let frame = json!({"type":"new_chat_message","payload":{"chat_id":CHAT,"message_id":"m1",
        "role":"assistant","content":"Hello","created_at":5,"messages_v":3}});
    c.ingest_socket_frames(&[frame]).await.unwrap();
    let sealed = c.history[CHAT][0]["encrypted_content"].as_str().unwrap();
    assert_ne!(sealed, "Hello");
    assert_eq!(crypto::decrypt_combined(sealed, &KEY).unwrap(), "Hello");
}

#[tokio::test]
async fn applied_seq_increments_in_frame_order() {
    let mut c = known();
    assert_eq!(c.frame_applied_seq(), 0);
    let first = c.ingest_socket_frames(&[added("m1", 3), added("m2", 4)]).await.unwrap();
    assert_eq!(first.applied_seq, 2);
    assert_eq!(c.history[CHAT][0]["message_id"], "m1");
    assert_eq!(c.history[CHAT][1]["message_id"], "m2");
    let second = c.ingest_socket_frames(&[added("m3", 5)]).await.unwrap();
    assert_eq!(second.applied_seq, 3);
    assert_eq!(c.frame_applied_seq(), 3);
}

#[tokio::test]
async fn ack_and_confirmation_raise_messages_v_forward_only() {
    let mut c = known();
    let frames = [
        json!({"type":"chat_turn_preflight_ack","payload":{"chat_id":CHAT,"committed_messages_v":5}}),
        json!({"type":"chat_message_confirmed","payload":{"chat_id":CHAT,"message_id":"m1","new_messages_v":4}}),
    ];
    let summary = c.ingest_socket_frames(&frames).await.unwrap();
    assert_eq!(summary.applied_seq, 2);
    assert_eq!(c.chats[CHAT]["messages_v"], 5, "a lower version never lowers the row");
}

#[tokio::test]
async fn call_and_queue_receipts_raise_messages_v_only_from_their_version_field() {
    let mut c = known();
    let frames = [
        json!({"type":"call_message_confirmed","payload":{"chat_id":CHAT,"request_id":"r1","revision":99,"messages_v":4}}),
        json!({"type":"call_message_changed","payload":{"chat_id":CHAT,"revision":120}}),
        json!({"type":"message_queued","payload":{"chat_id":CHAT,"versions":{"messages_v":5}}}),
        json!({"type":"message_deleted","payload":{"chat_id":CHAT,"new_messages_v":6}}),
        json!({"type":"call_message_changed","payload":{"chat_id":CHAT,"messages_v":3}}),
    ];
    let summary = c.ingest_socket_frames(&frames).await.unwrap();
    assert_eq!(summary.ignored, 1, "a call receipt without messages_v is not applied; revision is no substitute");
    assert_eq!(summary.applied_seq, 4);
    assert_eq!(c.chats[CHAT]["messages_v"], 6, "versions only move forward");
    assert!(c.history.get(CHAT).is_none_or(Vec::is_empty), "receipts never add history rows");
}

#[tokio::test]
async fn title_update_changes_the_row_and_metadata_version() {
    let mut c = known();
    let frame = json!({"event":"chat_title_updated","chat_id":CHAT,"data":{"encrypted_title":"t2"},"versions":{"metadata_v":7}});
    c.ingest_socket_frames(&[frame]).await.unwrap();
    assert_eq!(c.chats[CHAT]["encrypted_title"], "t2");
    assert_eq!(c.chats[CHAT]["metadata_v"], 7);
}

#[tokio::test]
async fn unknown_shell_and_streaming_frames_are_ignored() {
    let mut c = known();
    let frames = [
        json!({"type":"some_future_frame","payload":{"chat_id":CHAT}}),
        json!({"type":"ai_message_update","payload":{"chat_id":CHAT,"message_id":"a","is_final_chunk":false,"full_content_so_far":"x"}}),
        json!({"nothing": true}),
    ];
    let summary = c.ingest_socket_frames(&frames).await.unwrap();
    assert_eq!((summary.applied_seq, summary.ignored), (0, 3));
    assert!(summary.changed_chats.is_empty());
    assert!(c.history.is_empty());
}

#[tokio::test]
async fn other_principal_and_other_team_frames_are_refused() {
    let mut c = known();
    let other_user = json!({"type":"new_chat_message","payload":{"chat_id":CHAT,"message_id":"a","user_id":"someone-else","encrypted_content":"s"}});
    let team = json!({"type":"new_chat_message","payload":{"chat_id":CHAT,"message_id":"b","team_id":OTHER,"encrypted_content":"s"}});
    let summary = c.ingest_socket_frames(&[other_user, team]).await.unwrap();
    assert_eq!((summary.applied_seq, summary.ignored), (0, 2));
    assert!(c.history.is_empty());
}

#[tokio::test]
async fn chat_deleted_removes_row_and_history() {
    let mut c = known();
    c.ingest_socket_frames(&[added("m1", 3)]).await.unwrap();
    let summary = c.ingest_socket_frames(&[json!({"type":"chat_deleted","payload":{"chat_id":CHAT}})]).await.unwrap();
    assert_eq!(summary.changed_chats[0].chat_id, CHAT);
    assert!(!c.chats.contains_key(CHAT) && !c.history.contains_key(CHAT));
}

async fn serve(replies: Vec<(u16, Value)>) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        for (status, body) in replies {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buffer = vec![0u8; 8192];
            let mut seen = 0;
            while !buffer[..seen].windows(4).any(|w| w == b"\r\n\r\n") {
                seen += socket.read(&mut buffer[seen..]).await.unwrap();
            }
            let body = body.to_string();
            let head = format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len());
            socket.write_all(head.as_bytes()).await.unwrap();
            socket.write_all(body.as_bytes()).await.unwrap();
        }
    });
    (api, task)
}

#[tokio::test]
async fn admit_chat_makes_a_new_chat_known() {
    let draft = crypto::encrypt_combined("Draft", &MASTER).unwrap();
    let row = json!({"id":CHAT,"type":"new_chat","messages_v":0,"user_id":OWNER,"draft_v":1,
        "encrypted_draft_md":draft,"encrypted_draft_preview":draft});
    let (api, server) = serve(vec![(200, json!({"chats":[row]}))]).await;
    let mut c = client(&api, None);
    assert!(!c.chats.contains_key(CHAT));
    let admission = c.admit_chat(CHAT, None).await.unwrap();
    assert_eq!(admission, ChatAdmission { chat_id: CHAT.into(), messages_v: 0, history_rows: 0 });
    assert!(c.chats.contains_key(CHAT));
    server.await.unwrap();
}

#[tokio::test]
async fn admit_chat_fails_with_typed_codes() {
    let mut c = known();
    assert_eq!(c.admit_chat("not-a-uuid", None).await.unwrap_err().code(), "invalid_chat_id");
    assert_eq!(c.admit_chat(CHAT, Some(OTHER)).await.unwrap_err().code(), "forbidden");
    // The metadata batch names no row for the chat: never an empty success.
    let (api, server) = serve(vec![(200, json!({"chats":[]}))]).await;
    let mut c = client(&api, None);
    assert_eq!(c.admit_chat(CHAT, None).await.unwrap_err().code(), "forbidden");
    server.await.unwrap();
    let (api, server) = serve(vec![(404, json!({"detail":"x"})), (404, json!({"detail":"x"}))]).await;
    let mut c = client(&api, None);
    assert!(matches!(c.admit_chat(CHAT, None).await.unwrap_err().code(), "chat_unknown" | "unavailable"));
    drop(server);
    let mut c = client("http://127.0.0.1:1", None);
    assert_eq!(c.admit_chat(CHAT, None).await.unwrap_err().code(), "unavailable");
}
