//! Saved continuations must carry the exact authenticated immutable wrapper.
//! Synthetic keys and a bounded loopback peer exercise the public SDK send path.
//! The peer enforces canonical wrapper/recovery-key byte equality over two turns,
//! then supplies terminal receipts and canonical encrypted history for rereads.
//! Unit negatives retain scope selection, no fallback, ambiguity and Direct gates.
//! These test drafts require compilation and actual isolated CI execution.
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use futures_util::{SinkExt, StreamExt};
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const TEAM: &str = "33333333-3333-4333-8333-333333333333";
const OTHER: &str = "44444444-4444-4444-8444-444444444444";
fn client(api: &str) -> Client {
    Client::new(
        api,
        Some(Session {
            api_url: api.into(),
            session_id: OTHER.into(),
            cookies: BTreeMap::from([("auth_refresh_token".into(), "synthetic-refresh".into())]),
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
fn row(wrapper: &str) -> Value {
    json!({
    "id":CHAT,"messages_v":2,"encrypted_chat_key":wrapper}
    )
}
fn wrapper(cipher: &str, team: Option<&str>) -> Value {
    json!({
    "hashed_chat_id":sha256(CHAT),
        "key_type":if team.is_some(){
    "team"}
    else{
    "master"}
    ,"hashed_team_id":team.map(sha256),"encrypted_chat_key":cipher}
    )
}
#[test]
fn saved_personal_reuses_exact_wrapper_but_new_and_draft_wrap_independent_keys() {
    let c = client("https://api.example.invalid");
    let key = [9; 32];
    let canonical = crypto::encrypt_bytes(&key, &[7; 32]).unwrap();
    let details = row(&canonical);
    let (actual, cipher) = c.turn_chat_material(Some(&details), &[7; 32]).unwrap();
    assert_eq!(actual.as_ref(), &key);
    assert_eq!(cipher, canonical);
    let (again, same) = c.turn_chat_material(Some(&details), &[7; 32]).unwrap();
    assert_eq!(again.as_ref(), actual.as_ref());
    assert_eq!(same, cipher);
    let draft = json!({
    "id":CHAT,"encrypted_draft_md":crypto::encrypt_combined("synthetic draft",&[7;
    32]).unwrap()}
    );
    for details in [None, Some(&draft)] {
        let (fresh, wrapped) = c.turn_chat_material(details, &[7; 32]).unwrap();
        assert_ne!(fresh.as_ref(), &[7; 32]);
        assert_ne!(fresh.as_ref(), &key);
        assert_eq!(
            crypto::decrypt_bytes(&wrapped, &[7; 32])
                .unwrap()
                .as_slice(),
            fresh.as_ref()
        );
    }
}
#[test]
fn saved_send_rejects_different_and_ambiguous_ciphertexts_without_changing_read_selection() {
    let mut c = client("https://api.example.invalid");
    let canonical = crypto::encrypt_bytes(&[9; 32], &[7; 32]).unwrap();
    let different = crypto::encrypt_bytes(&[9; 32], &[7; 32]).unwrap();
    assert_ne!(canonical, different);
    let details = row(&canonical);
    c.wrappers = vec![wrapper(&different, None)];
    assert!(c.chat_key(&details, &[7; 32]).is_ok());
    assert!(matches!(
        c.turn_chat_material(Some(&details), &[7; 32]),
        Err(Error::Conflict)
    ));
    c.wrappers = vec![wrapper(&canonical, None), wrapper(&different, None)];
    assert!(c.chat_key(&details, &[7; 32]).is_ok());
    assert!(matches!(
        c.turn_chat_material(Some(&details), &[7; 32]),
        Err(Error::Conflict)
    ));
    c.wrappers = vec![
        wrapper("malformed-ciphertext", None),
        wrapper(&canonical, None),
    ];
    assert!(c.turn_chat_material(Some(&details), &[7; 32]).is_err());
}
#[test]
fn team_scope_and_direct_recipient_authority_never_fall_back_to_personal_ciphertext() {
    let mut c = client("https://api.example.invalid");
    c.set_team(Some(TEAM)).unwrap();
    let canonical = crypto::encrypt_bytes(&[9; 32], &[8; 32]).unwrap();
    let mut details = row(&canonical);
    details["team_id"] = json!(TEAM);
    c.wrappers = vec![wrapper(&canonical, Some(TEAM))];
    let (_, actual) = c.turn_chat_material(Some(&details), &[8; 32]).unwrap();
    assert_eq!(actual, canonical);
    c.wrappers = vec![wrapper(&canonical, None)];
    assert!(matches!(
        c.turn_chat_material(Some(&details), &[8; 32]),
        Err(Error::Forbidden)
    ));
    c.wrappers = vec![wrapper(&canonical, Some(OTHER))];
    assert!(matches!(
        c.turn_chat_material(Some(&details), &[8; 32]),
        Err(Error::Forbidden)
    ));
    c.wrappers = vec![wrapper(&canonical, Some(TEAM))];
    details["team_id"] = json!(OTHER);
    assert!(matches!(
        c.turn_chat_material(Some(&details), &[8; 32]),
        Err(Error::Forbidden)
    ));
    details["team_id"] = json!(TEAM);
    details["chat_visibility"] = json!("direct");
    assert!(matches!(
        c.turn_chat_material(Some(&details), &[8; 32]),
        Err(Error::Forbidden)
    ));
    c.session.as_mut().unwrap().paired_session_expires_at = Some(1);
    assert!(
        c.turn_chat_material(Some(&row(&canonical)), &[8; 32])
            .is_err()
    );
}
#[derive(Default)]
struct State {
    id: String,
    wrapper: String,
    recovery_key: String,
    history: Vec<Value>,
    admissions: usize,
    connections: usize,
}
async fn frame(
    ws: &mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>,
    kind: &str,
    payload: Value,
) {
    ws.send(Frame::Text(
        json!({
        "type":kind,"payload":payload}
        )
        .to_string()
        .into(),
    ))
    .await
    .unwrap();
}
async fn http(mut stream: tokio::net::TcpStream, state: Arc<Mutex<State>>) {
    let mut bytes = Vec::new();
    let mut chunk = [0; 2048];
    let end;
    loop {
        let n = stream.read(&mut chunk).await.unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&chunk[..n]);
        if let Some(found) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
            let headers = std::str::from_utf8(&bytes[..found]).unwrap();
            let length = headers
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|v| v.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            if bytes.len() >= found + 4 + length {
                end = found;
                break;
            }
        }
    }
    let headers = std::str::from_utf8(&bytes[..end]).unwrap();
    let route = headers.lines().next().unwrap();
    assert!(
        headers
            .to_ascii_lowercase()
            .contains("x-openmates-sdk: rust")
    );
    assert!(headers.contains("auth_refresh_token=synthetic-refresh"));
    let response = if route == "POST /v1/auth/session HTTP/1.1" {
        json!({
        "success":true,"ws_token":"synthetic-token","user":{
        "id":OTHER}
        }
        )
    } else if route == "POST /v1/chats/metadata/batch HTTP/1.1" {
        let st = state.lock().unwrap();
        let body: Value = serde_json::from_slice(&bytes[end + 4..]).unwrap();
        assert_eq!(body["chat_ids"], json!([st.id]));
        json!({
        "chats":[{
        "id":st.id,"encrypted_chat_key":st.wrapper,"messages_v":st.history.len()}
        ]}
        )
    } else if route.starts_with("GET /v1/chats/") && route.contains("/messages/window?") {
        let st = state.lock().unwrap();
        assert!(route.contains(&st.id));
        json!({
        "messages":st.history,"has_more_before":false}
        )
    } else if route.starts_with("GET /v1/projects/focus/current?chat_id=") {
        json!({
        "focus":null}
        )
    } else {
        panic!("Unexpected fixture route")
    };
    let body = response.to_string();
    stream.write_all(format!("HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
}
async fn websocket(stream: tokio::net::TcpStream, state: Arc<Mutex<State>>) {
    let mut ws = tokio_tungstenite::accept_hdr_async(
        stream,
        |request: &tokio_tungstenite::tungstenite::handshake::server::Request,
         response: tokio_tungstenite::tungstenite::handshake::server::Response| {
            assert_eq!(request.headers()["x-openmates-sdk"], "rust");
            assert_eq!(
                request.headers()["cookie"],
                "auth_refresh_token=synthetic-refresh"
            );
            Ok(response)
        },
    )
    .await
    .unwrap();
    state.lock().unwrap().connections += 1;
    let mut terminal = None;
    while let Some(raw) = ws.next().await {
        let raw = raw.unwrap();
        if matches!(raw, Frame::Close(_)) {
            return;
        }
        let event: Value = serde_json::from_str(&raw.into_text().unwrap()).unwrap();
        let p = &event["payload"];
        match event["type"].as_str().unwrap() {
            "native_client_lifecycle" | "set_active_chat" => {}
            "personal_send_context_snapshot" => {
                let response = json!({"success":true,"unchanged":false,
                    "request_id":p["request_id"],"turn_id":p["turn_id"],
                    "receipt_id":"synthetic-receipt","privacy_generation":1,
                    "project_candidates":[],"personal_memories":{"memories":[]}});
                frame(&mut ws, "personal_send_context_snapshot_result", response).await;
            }
            "chat_turn_admit" => {
                let (chat, turn, user, assistant, job, version) = {
                    let mut st = state.lock().unwrap();
                    let offered = required(p, "encrypted_chat_key").unwrap();
                    if st.admissions == 0 {
                        st.id = required(p, "chat_id").unwrap().into();
                        st.wrapper = offered.into();
                        st.recovery_key = required(p, "recovery_public_key").unwrap().into();
                    }
                    // Canonical immutability compares ciphertext bytes, not
                    // just successful decryption to the same object key.
                    assert_eq!(offered, st.wrapper);
                    assert_eq!(p["recovery_public_key"], st.recovery_key);
                    assert_eq!(p["chat_id"], st.id);
                    assert_eq!(
                        p["expected_messages_v"].as_u64().unwrap() as usize,
                        st.history.len()
                    );
                    let key =
                        key_from_bytes(&crypto::decrypt_bytes(&st.wrapper, &[7; 32]).unwrap())
                            .unwrap();
                    let user = required(p, "message_id").unwrap().to_owned();
                    st.history.push(p["encrypted_user_message"].clone());
                    st.admissions += 1;
                    let assistant = format!("55555555-5555-4555-8555-{:012}", st.admissions);
                    let job = format!("66666666-6666-4666-8666-{:012}", st.admissions);
                    let chat = st.id.clone();
                    let assistant_row = json!({"client_message_id":assistant,"chat_id":chat,
                        "role":"assistant","created_at":1,
                        "encrypted_content":crypto::encrypt_combined("synthetic canonical answer",&key).unwrap()});
                    st.history.push(assistant_row);
                    (
                        chat,
                        required(p, "turn_id").unwrap().to_owned(),
                        user,
                        assistant,
                        job,
                        st.history.len(),
                    )
                };
                frame(
                    &mut ws,
                    "chat_turn_preflight_ack",
                    json!({"turn_id":turn,
                    "preflight_id":"synthetic-preflight","committed_messages_v":version-1}),
                )
                .await;
                frame(
                    &mut ws,
                    "chat_message_confirmed",
                    json!({"chat_id":chat,
                    "message_id":user,"new_messages_v":version-1}),
                )
                .await;
                frame(
                    &mut ws,
                    "recovery_outputs_discovery_complete",
                    json!({"status":"completed"}),
                )
                .await;
                frame(
                    &mut ws,
                    "ai_message_update",
                    json!({"chat_id":chat,"user_message_id":user,
                    "recovery_turn_id":turn,"message_id":assistant,"recovery_job_id":job,
                    "recovery_protocol_version":1,"created_at":1,"is_final_chunk":true,
                    "full_content_so_far":"synthetic canonical answer"}),
                )
                .await;
                terminal = Some(json!({"job_id":job,"chat_id":chat,"turn_id":turn,
                    "assistant_message_id":assistant,"chat_key_version":1,"state":"TERMINAL"}));
            }
            "recovery_job_claim" => {
                let claim = terminal.take().unwrap();
                assert_eq!(p["job_id"], claim["job_id"]);
                frame(&mut ws, "recovery_job_claimed", claim).await;
            }
            _ => panic!("Unexpected fixture websocket operation"),
        }
    }
}
#[tokio::test]
async fn public_personal_two_turn_send_reuses_exact_canonical_wrapper_and_recovery_key() {
    tokio::time::timeout(Duration::from_secs(10), async {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let state = Arc::new(Mutex::new(State::default()));
        let shared = state.clone();
        let stop = CancellationToken::new();
        let stopped = stop.clone();
        let server = tokio::spawn(async move {
            let mut requests = tokio::task::JoinSet::new();
            loop {
                let (stream, _) = tokio::select! {
                    biased;
                    _ = stopped.cancelled() => break,
                    accepted = listener.accept() => accepted.unwrap(),
                };
                let state = shared.clone();
                requests.spawn(async move {
                    let mut head = [0; 4096];
                    loop {
                        let n = stream.peek(&mut head).await.unwrap();
                        assert!(n > 0);
                        if head[..n].windows(4).any(|w| w == b"\r\n\r\n") {
                            if head[..n].starts_with(b"GET /v1/ws?") {
                                websocket(stream, state).await;
                            } else {
                                http(stream, state).await;
                            }
                            break;
                        }
                        tokio::task::yield_now().await;
                    }
                });
            }
            while let Some(result) = requests.join_next().await {
                result.unwrap();
            }
        });
        let mut c = client(&api);
        let (updates, _receiver) = mpsc::channel(64);
        let opts = SendOptions {
            pii_detection: false,
            task_update_jobs: false,
            response_timeout_ms: Some(5_000),
            ..Default::default()
        };
        let first = c
            .send(
                None,
                "synthetic first",
                opts.clone(),
                updates.clone(),
                CancellationToken::new(),
            )
            .await
            .unwrap();
        assert!(matches!(first.status, SendStatus::Completed));
        let original = state.lock().unwrap().wrapper.clone();
        let second = c
            .send(
                Some(&first.chat_id),
                "synthetic second",
                opts,
                updates,
                CancellationToken::new(),
            )
            .await
            .unwrap();
        assert!(matches!(second.status, SendStatus::Completed));
        assert_eq!(second.assistant, "synthetic canonical answer");
        {
            let st = state.lock().unwrap();
            assert_eq!(st.admissions, 2);
            assert_eq!(st.wrapper, original);
            assert_eq!(st.history.len(), 4);
        }
        // Existing reads still choose their first valid scoped wrapper. Saved
        // send must refuse nonce ambiguity before opening an inference socket.
        let key = key_from_bytes(&crypto::decrypt_bytes(&original, &[7; 32]).unwrap()).unwrap();
        let different = crypto::encrypt_bytes(key.as_ref(), &[7; 32]).unwrap();
        let candidate = |cipher: &str| {
            json!({"hashed_chat_id":sha256(&first.chat_id),
            "key_type":"master","encrypted_chat_key":cipher})
        };
        for candidates in [
            vec![candidate(&different)],
            vec![candidate(&original), candidate(&different)],
        ] {
            c.wrappers = candidates;
            let (updates, _receiver) = mpsc::channel(64);
            let result = c
                .send(
                    Some(&first.chat_id),
                    "rejected third",
                    SendOptions {
                        pii_detection: false,
                        task_update_jobs: false,
                        ..Default::default()
                    },
                    updates,
                    CancellationToken::new(),
                )
                .await;
            assert!(matches!(result, Err(Error::Conflict)));
            let st = state.lock().unwrap();
            assert_eq!(st.admissions, 2);
            assert_eq!(st.connections, 2);
        }
        c.wrappers = vec![candidate("malformed-ciphertext"), candidate(&original)];
        let (updates, _receiver) = mpsc::channel(64);
        assert!(
            c.send(
                Some(&first.chat_id),
                "no fallback",
                SendOptions {
                    pii_detection: false,
                    task_update_jobs: false,
                    ..Default::default()
                },
                updates,
                CancellationToken::new()
            )
            .await
            .is_err()
        );
        {
            let st = state.lock().unwrap();
            assert_eq!(st.admissions, 2);
            assert_eq!(st.connections, 2);
        }
        stop.cancel();
        server.await.unwrap();
    })
    .await
    .unwrap();
}
