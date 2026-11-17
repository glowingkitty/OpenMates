//! Voice turn split: payload equals the socket path's, validation and refusals.
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::Message as Frame;

const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const TURN: &str = "33333333-3333-4333-8333-333333333333";

fn client(api: &str) -> Client {
    let mut session = crate::client::sdk_boundary_tests::session();
    session.api_url = api.into();
    session.master_key = zeroize::Zeroizing::new([7; 32]);
    let mut c = Client::new(api, Some(session)).unwrap();
    c.user = json!({"id": OWNER});
    c
}

fn options() -> SendOptions {
    let mut o = SendOptions::default();
    o.voice_call = Some(VoiceCallTurn {
        call_id: "call-1".into(),
        turn_id: TURN.into(),
        heard_boundary: None,
    });
    o
}

fn result(request_id: &str, turn: &str, success: bool) -> Value {
    json!({"success": success, "unchanged": false, "request_id": request_id, "turn_id": turn,
        "receipt_id": "synthetic-receipt", "privacy_generation": 1,
        "project_candidates": [], "personal_memories": {"memories": []}})
}

/// Drop per-call random/time fields and ciphertexts so shapes compare.
fn normalize(v: &mut Value) {
    match v {
        Value::Object(map) => {
            map.remove("created_at");
            map.remove("updated_at");
            for (k, x) in map.iter_mut() {
                if k.starts_with("encrypted_") && x.is_string() {
                    *x = json!("<enc>");
                } else {
                    normalize(x);
                }
            }
        }
        Value::Array(items) => items.iter_mut().for_each(normalize),
        _ => {}
    }
}

fn keys() -> (crypto::Key, String) {
    let key = crypto::random_key();
    let wrapped = crypto::server_fields::encrypt_bytes(key.as_ref(), &[7; 32], &[]).unwrap();
    (key, wrapped)
}

/// The admit payload one real socket-path preparation sends to a synthetic peer.
async fn socket_admit(key: &crypto::Key, wrapped: &str, input: &str) -> Value {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let mut admitted = None;
        while let Some(raw) = ws.next().await {
            let raw = raw.unwrap();
            if matches!(raw, Frame::Close(_)) {
                return admitted.expect("admission");
            }
            let event: Value = serde_json::from_str(&raw.into_text().unwrap()).unwrap();
            match event["type"].as_str().unwrap() {
                "set_active_chat" => {}
                "personal_send_context_snapshot" => {
                    let rid = event["payload"]["request_id"].as_str().unwrap().to_owned();
                    let reply = json!({"type": "personal_send_context_snapshot_result", "payload": result(&rid, TURN, true)});
                    ws.send(Frame::Text(reply.to_string().into()))
                        .await
                        .unwrap();
                }
                "chat_turn_admit" => admitted = Some(event["payload"].clone()),
                other => panic!("unexpected frame {other}"),
            }
        }
        panic!("missing close")
    });
    let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    let mut socket = transport::test_socket(inner);
    let mut c = client("http://127.0.0.1:1");
    let chat = Chat {
        id: CHAT.into(),
        ..Default::default()
    };
    let (tx, _rx) = mpsc::channel(16);
    let scope = AsyncCryptoScope::begin(&c).unwrap();
    let generation = c.generation;
    c.prepare_turn_on_socket(
        &mut socket,
        CHAT,
        TURN,
        TURN,
        input,
        key,
        wrapped,
        0,
        true,
        &[],
        &chat,
        &tx,
        &CancellationToken::new(),
        generation,
        None,
        &options(),
        &scope,
    )
    .await
    .unwrap();
    let _ = socket.close(None).await;
    crate::platform::time::timeout(Duration::from_secs(3), peer)
        .await
        .unwrap()
        .unwrap()
}

async fn prepared(c: &Client) -> PreparedVoiceTurn {
    let (rid, frame) = c.voice_turn_snapshot_frame(CHAT, TURN);
    assert_eq!(frame["purpose"], "send");
    assert_eq!(frame["turn_id"], TURN);
    c.prepare_voice_turn(CHAT, TURN, &rid, result(&rid, TURN, true))
        .await
        .unwrap()
}

#[tokio::test]
async fn commit_builds_same_admit_payload_as_socket_path() {
    let (key, wrapped) = keys();
    let mut expected = socket_admit(&key, &wrapped, "hello there").await;
    let mut c = client("http://127.0.0.1:1");
    let turn = prepared(&c).await;
    let committed = c
        .commit_voice_turn(
            turn,
            "hello there",
            None,
            &key,
            &wrapped,
            0,
            true,
            &[],
            &options(),
        )
        .await
        .unwrap();
    let mut actual = (*committed.admit).clone();
    assert!(committed.wait_ai);
    assert_eq!(*committed.user_message, actual["encrypted_user_message"]);
    assert_eq!(
        actual["inference_request"]["message"]["voice_turn_id"],
        TURN
    );
    assert_eq!(actual["message_id"], TURN);
    normalize(&mut expected);
    normalize(&mut actual);
    assert_eq!(actual, expected);
}

#[tokio::test]
async fn snapshot_validation_rejects_wrong_turn_and_failure() {
    let c = client("http://127.0.0.1:1");
    let (rid, _) = c.voice_turn_snapshot_frame(CHAT, TURN);
    let other = "99999999-9999-4999-8999-999999999999";
    assert!(matches!(
        c.prepare_voice_turn(CHAT, TURN, &rid, result(&rid, other, true))
            .await,
        Err(Error::Protocol)
    ));
    assert!(matches!(
        c.prepare_voice_turn(CHAT, TURN, &rid, result(&rid, TURN, false))
            .await,
        Err(Error::Protocol)
    ));
    assert!(matches!(
        c.prepare_voice_turn(CHAT, TURN, "another-request", result(&rid, TURN, true))
            .await,
        Err(Error::Protocol)
    ));
}

#[tokio::test]
async fn commit_refuses_project_and_missing_voice_fields() {
    let (key, wrapped) = keys();
    let mut c = client("http://127.0.0.1:1");
    let mut with_project = options();
    with_project.project_id = Some("project".into());
    let turn = prepared(&c).await;
    assert!(matches!(
        c.commit_voice_turn(
            turn,
            "hi",
            None,
            &key,
            &wrapped,
            0,
            true,
            &[],
            &with_project
        )
        .await,
        Err(Error::Invalid(_))
    ));
    let turn = prepared(&c).await;
    assert!(matches!(
        c.commit_voice_turn(
            turn,
            "hi",
            None,
            &key,
            &wrapped,
            0,
            true,
            &[],
            &SendOptions::default()
        )
        .await,
        Err(Error::Invalid(_))
    ));
}

#[tokio::test]
async fn commit_from_state_refuses_unknown_or_keyless_chat_instead_of_minting_a_key() {
    let mut c = client("http://127.0.0.1:1");
    let turn = prepared(&c).await;
    assert!(matches!(
        c.commit_voice_turn_from_state(turn, "hi", None, &options())
            .await,
        Err(Error::Unavailable {
            code: "voice_turn_chat_unknown",
            ..
        })
    ));
    c.chats.insert(
        CHAT.into(),
        json!({"id": CHAT, "encrypted_draft_md": "synthetic"}),
    );
    let turn = prepared(&c).await;
    assert!(matches!(
        c.commit_voice_turn_from_state(turn, "hi", None, &options())
            .await,
        Err(Error::Unavailable {
            code: "voice_turn_chat_unknown",
            ..
        })
    ));
}

#[tokio::test]
async fn prepare_refuses_team_chat() {
    let mut c = client("http://127.0.0.1:1");
    c.session.as_mut().unwrap().active_team_id = Some("team-1".into());
    let (rid, _) = c.voice_turn_snapshot_frame(CHAT, TURN);
    assert!(matches!(
        c.prepare_voice_turn(CHAT, TURN, &rid, result(&rid, TURN, true))
            .await,
        Err(Error::Invalid(_))
    ));
}

#[tokio::test]
async fn dropping_prepared_turn_emits_nothing() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let c = client(&format!("http://{}", listener.local_addr().unwrap()));
    drop(prepared(&c).await);
    let accepted =
        crate::platform::time::timeout(Duration::from_millis(200), listener.accept()).await;
    assert!(accepted.is_err(), "discard must open no connection");
}

#[tokio::test]
async fn commit_from_state_refuses_a_chat_with_messages_but_no_history() {
    let (_, wrapped) = keys();
    let mut c = client("http://127.0.0.1:1");
    c.chats.insert(
        CHAT.into(),
        json!({"id": CHAT, "encrypted_chat_key": wrapped, "messages_v": 2}),
    );
    let turn = prepared(&c).await;
    assert!(matches!(
        c.commit_voice_turn_from_state(turn, "hi", None, &options())
            .await,
        Err(Error::Unavailable {
            code: "voice_turn_history_missing",
            ..
        })
    ));
}

#[tokio::test]
async fn commit_records_its_user_row_once_in_history() {
    let (key, wrapped) = keys();
    let mut c = client("http://127.0.0.1:1");
    let turn = prepared(&c).await;
    let committed = c
        .commit_voice_turn(
            turn,
            "hello there",
            None,
            &key,
            &wrapped,
            0,
            true,
            &[],
            &options(),
        )
        .await
        .unwrap();
    let rows = &c.history[CHAT];
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0]["message_id"], TURN);
    assert_eq!(rows[0]["role"], "user");
    assert_eq!(
        rows[0]["encrypted_content"],
        committed.user_message["encrypted_content"]
    );
    let again: Value = (*committed.user_message).clone();
    c.remember_voice_user_row(CHAT, TURN, &again);
    assert_eq!(
        c.history[CHAT].len(),
        1,
        "a known message id is not stored twice"
    );
}

#[test]
fn a_call_chat_without_a_title_asks_for_its_title_like_the_web_sender() {
    // The call bootstrap stores the chat (title_v 0) before the first turn, so
    // the turn is not a new chat but the chat still has no title.
    let (_, wrapped) = keys();
    let mut c = client("http://127.0.0.1:1");
    let row = |title_v: u64| json!({"id": CHAT, "encrypted_chat_key": wrapped, "title_v": title_v});
    c.chats.insert(CHAT.into(), row(0));
    assert!(!c.turn_chat_has_title(CHAT, false));
    assert!(!c.turn_chat_has_title(CHAT, true));
    c.chats.insert(CHAT.into(), row(1));
    assert!(c.turn_chat_has_title(CHAT, false));
    c.chats.remove(CHAT);
    assert!(
        c.turn_chat_has_title(CHAT, false),
        "an unknown row keeps the existing-chat meaning"
    );
}

#[tokio::test]
async fn commit_keeps_the_page_row_time_on_the_admitted_message() {
    // The page shows its optimistic row with the transcript's time; the
    // canonical row must carry the same time or reload sees two histories.
    let (key, wrapped) = keys();
    let mut c = client("http://127.0.0.1:1");
    let turn = prepared(&c).await;
    let committed = c
        .commit_voice_turn(
            turn,
            "hello there",
            Some(1_700_000_123),
            &key,
            &wrapped,
            0,
            true,
            &[],
            &options(),
        )
        .await
        .unwrap();
    assert_eq!(committed.user_message["created_at"], 1_700_000_123);
    assert_eq!(
        committed.admit["inference_request"]["message"]["created_at"],
        1_700_000_123
    );
}
