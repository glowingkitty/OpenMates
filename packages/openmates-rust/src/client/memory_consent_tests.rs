//! Answers to `memory-<id>` requests on a real socket: Auto include silently, Ask first through consent.
use super::super::plaintext::Plain;
use super::super::sync_capability::AsyncCryptoScope;
use super::super::transport::Socket;
use super::super::*;
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::Message as Frame;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const NOW: i64 = 1_793_000_000_000;
const AUTO: &str = "---\ntitle: Diet\n---\nVegetarian.\n";
const ASK: &str = "---\ntitle: Career profile\nload_mode: ask_first\n---\nSenior Rust engineer.\n";
const MENTION: &str = "---\ntitle: Health\nload_mode: mention_only\n---\nPrivate.\n";

fn client() -> Client {
    let session = Session {
        api_url: "http://127.0.0.1:9".into(),
        session_id: "synthetic-memory-consent".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new("http://127.0.0.1:9", Some(session)).unwrap();
    client.user = json!({"id":"33333333-3333-4333-8333-333333333333"});
    client
}

/// Confirms every system message and records each frame the client sent.
async fn peer() -> (Socket, tokio::task::JoinHandle<Vec<Value>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let mut frames = vec![];
        while let Some(Ok(frame)) = ws.next().await {
            if !frame.is_text() {
                continue;
            }
            let request: Value = serde_json::from_str(frame.to_text().unwrap()).unwrap();
            if request["type"] == "chat_system_message_added" {
                let id = &request["payload"]["message"]["message_id"];
                ws.send(Frame::text(
                    json!({"type":"system_message_confirmed","payload":{"message_id":id}})
                        .to_string(),
                ))
                .await
                .unwrap();
            }
            frames.push(request);
        }
        frames
    });
    let (ws, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    (super::super::transport::test_socket(ws), server)
}

/// The next stream update; a prompt that never comes fails the test instead
/// of hanging it (the sender lives in the test, so `recv` would never end).
async fn consent_prompt(receiver: &mut mpsc::Receiver<StreamUpdate>) -> StreamUpdate {
    tokio::time::timeout(std::time::Duration::from_secs(10), receiver.recv())
        .await
        .expect("a consent prompt within 10 s")
        .expect("the updates channel stays open")
}

fn decision(ids: &[&str]) -> Plain<MemoryRequestDecision> {
    let documents = [
        ("personal:auto", AUTO),
        ("personal:ask", ASK),
        ("personal:mention", MENTION),
    ]
    .map(|(id, document)| PersonalMemoryDocument {
        id: id.into(),
        document: Zeroizing::new(document.into()),
    });
    let ids: Vec<String> = ids.iter().map(|id| (*id).to_owned()).collect();
    Plain::new(decide_memory_request(&ids, &documents, NOW))
}

fn content(frame: &Value) -> Value {
    serde_json::from_str(
        &crate::crypto::decrypt_combined(
            frame["payload"]["message"]["encrypted_content"]
                .as_str()
                .unwrap(),
            &[9; 32],
        )
        .unwrap(),
    )
    .unwrap()
}

#[tokio::test]
async fn auto_include_memories_are_answered_without_a_request_to_approve() {
    let (mut ws, server) = peer().await;
    let mut client = client();
    let scope = AsyncCryptoScope::begin(&client).unwrap();
    let (updates, _receiver) = mpsc::channel(1);
    let event = json!({"request_id":"r1","requested_keys":["memory-personal:auto","memory-personal:mention"]});
    let (deferred, record) = client
        .memory_consent_decided(
            &mut ws,
            &scope,
            &event,
            CHAT,
            "message",
            &[9; 32],
            &[],
            decision(&["personal:auto", "personal:mention"]),
            &updates,
            &CancellationToken::new(),
            SendConsentPolicy::Reject,
        )
        .await
        .unwrap();
    assert!(deferred.is_empty());
    assert_eq!(record.approved_keys, ["memory-personal:auto"]);
    assert_eq!(record.entry_count, 1);
    drop(ws);
    let frames = server.await.unwrap();
    let kinds: Vec<_> = frames.iter().map(|f| f["type"].as_str().unwrap()).collect();
    assert_eq!(
        kinds,
        [
            "app_settings_memories_confirmed",
            "chat_system_message_added"
        ]
    );
    assert_eq!(
        frames[0]["payload"]["app_settings_memories"],
        json!([{"app_id":"memory","item_key":"personal:auto","content":AUTO}])
    );
    let response = content(&frames[1]);
    assert_eq!(response["action"], "included");
    assert_eq!(
        response["categories"],
        json!([{"appId":"memory","itemType":"memories","entryCount":1}])
    );
}

#[tokio::test]
async fn ask_first_memories_need_approval_and_auto_ones_survive_a_rejection() {
    for (policy, released) in [
        (SendConsentPolicy::Reject, false),
        (SendConsentPolicy::ApproveRequested, true),
        (SendConsentPolicy::Caller, true),
    ] {
        let (mut ws, server) = peer().await;
        let mut client = client();
        let (decisions, decision_rx) = mpsc::unbounded_channel();
        client.set_consent_receiver(decision_rx);
        let scope = AsyncCryptoScope::begin(&client).unwrap();
        let (updates, mut receiver) = mpsc::channel(1);
        let event = json!({"request_id":"r2","requested_keys":["memory-personal:auto","memory-personal:ask"]});
        let decide = async {
            if policy == SendConsentPolicy::Caller {
                let update = Plain::new(consent_prompt(&mut receiver).await);
                let StreamUpdate::Consent { request_id, items } = &*update else {
                    panic!("expected consent")
                };
                // Only the Ask first Memory is asked about, by title, without its body.
                assert_eq!(items.len(), 1);
                assert_eq!(items[0].id, "memory-personal:ask");
                assert_eq!(items[0].title, "Career profile");
                assert!(!format!("{:?}", items[0].fields).contains("Senior"));
                // An Auto include key is not the caller's to approve.
                decisions
                    .send((request_id.clone(), vec![items[0].id.clone()]))
                    .unwrap();
            }
        };
        let cancel = CancellationToken::new();
        let (result, ()) = tokio::join!(
            client.memory_consent_decided(
                &mut ws,
                &scope,
                &event,
                CHAT,
                "message",
                &[9; 32],
                &[],
                decision(&["personal:auto", "personal:ask"]),
                &updates,
                &cancel,
                policy,
            ),
            decide
        );
        let (_, record) = result.unwrap();
        assert_eq!(record.entry_count, if released { 2 } else { 1 });
        drop(ws);
        let frames = server.await.unwrap();
        let kinds: Vec<_> = frames.iter().map(|f| f["type"].as_str().unwrap()).collect();
        assert_eq!(
            kinds,
            [
                "chat_system_message_added",
                "app_settings_memories_confirmed",
                "chat_system_message_added"
            ]
        );
        let request = content(&frames[0]);
        assert_eq!(request["requested_keys"], json!(["memory-personal:ask"]));
        assert_eq!(request["auto_memory_ids"], json!(["personal:auto"]));
        let sent = frames[1]["payload"]["app_settings_memories"]
            .as_array()
            .unwrap();
        assert_eq!(sent[0]["item_key"], "personal:auto");
        assert_eq!(sent.len(), if released { 2 } else { 1 });
        if released {
            assert_eq!(sent[1]["content"], ASK);
        }
        assert_eq!(content(&frames[2])["action"], "included");
    }
}

#[tokio::test]
async fn caller_cannot_release_a_withheld_memory_through_the_dialog() {
    let (mut ws, _server) = peer().await;
    let mut client = client();
    let (decisions, decision_rx) = mpsc::unbounded_channel();
    client.set_consent_receiver(decision_rx);
    let scope = AsyncCryptoScope::begin(&client).unwrap();
    let (updates, mut receiver) = mpsc::channel(1);
    let event = json!({"request_id":"r3","requested_keys":["memory-personal:mention","memory-personal:ask"]});
    let decide = async {
        let update = Plain::new(consent_prompt(&mut receiver).await);
        let StreamUpdate::Consent { request_id, .. } = &*update else {
            panic!("expected consent")
        };
        decisions
            .send((request_id.clone(), vec!["memory-personal:mention".into()]))
            .unwrap();
    };
    let cancel = CancellationToken::new();
    let (result, ()) = tokio::join!(
        client.memory_consent_decided(
            &mut ws,
            &scope,
            &event,
            CHAT,
            "message",
            &[9; 32],
            &[],
            decision(&["personal:mention", "personal:ask"]),
            &updates,
            &cancel,
            SendConsentPolicy::Caller,
        ),
        decide
    );
    assert!(matches!(result, Err(Error::Forbidden)));
}
