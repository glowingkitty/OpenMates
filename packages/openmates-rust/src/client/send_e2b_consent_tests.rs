//! Behaviour of E2B upload consent requests raised while a turn streams.
// contract-test: supporting surface=sdks.rust assertions=code-run.e2b.upload-consent
use super::*;
use crate::client::e2b_consent::E2bConsentChoice;
use futures_util::{SinkExt, StreamExt};
use tokio::task::JoinHandle;
use tokio_tungstenite::tungstenite::Message as Frame;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const OWNER: &str = "33333333-3333-4333-8333-333333333333";
const KEY: [u8; 32] = [9; 32];

fn client() -> Client {
    let session = Session {
        api_url: "http://127.0.0.1:9".into(),
        session_id: "synthetic-e2b-consent".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new("http://127.0.0.1:9", Some(session)).unwrap();
    client.user = json!({"id": OWNER});
    client
}

/// A peer that confirms every system message and records all frames.
async fn peer() -> (Socket, JoinHandle<Vec<Value>>) {
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

fn frame() -> Value {
    json!({"request_id":"req-1","chat_id":CHAT,"version":1})
}

fn decode(frame: &Value) -> Value {
    let cipher = frame["payload"]["message"]["encrypted_content"]
        .as_str()
        .unwrap();
    serde_json::from_str(&crypto::decrypt_combined(cipher, &KEY).unwrap()).unwrap()
}

async fn run(
    policy: E2bConsentPolicy,
) -> (Option<SendE2bConsentRequest>, Vec<StreamUpdate>, Vec<Value>) {
    let (mut ws, server) = peer().await;
    let mut client = client();
    let (updates, mut receiver) = mpsc::channel(4);
    let cancel = CancellationToken::new();
    let result = client
        .send_e2b_consent(&mut ws, &frame(), CHAT, &KEY, &updates, &cancel, policy)
        .await
        .unwrap();
    drop(updates);
    let mut seen = vec![];
    while let Some(update) = receiver.recv().await {
        seen.push(update);
    }
    drop(ws);
    (result, seen, server.await.unwrap())
}

fn types(frames: &[Value]) -> Vec<&str> {
    frames.iter().map(|f| f["type"].as_str().unwrap()).collect()
}

#[tokio::test]
async fn approve_persists_the_request_and_answers_allow() {
    let (result, updates, frames) = run(E2bConsentPolicy::Approve).await;
    assert!(result.is_none() && updates.is_empty());
    assert_eq!(
        types(&frames),
        [
            "chat_system_message_added",
            "e2b_upload_consent_answer",
            "chat_system_message_added"
        ]
    );
    assert_eq!(decode(&frames[0])["type"], "e2b_upload_consent_request");
    assert_eq!(
        frames[1]["payload"]["choice"],
        E2bConsentChoice::Allow.as_wire()
    );
    assert_eq!(frames[1]["payload"]["request_id"], "req-1");
    assert_eq!(decode(&frames[2])["choice"], "allow");
}

#[tokio::test]
async fn reject_persists_the_request_and_answers_not_now() {
    let (result, updates, frames) = run(E2bConsentPolicy::Reject).await;
    assert!(result.is_none() && updates.is_empty());
    assert_eq!(decode(&frames[0])["type"], "e2b_upload_consent_request");
    assert_eq!(frames[1]["payload"]["choice"], "not_now");
}

#[tokio::test]
async fn caller_policy_surfaces_the_request_and_sends_no_answer() {
    let (result, updates, frames) = run(E2bConsentPolicy::Caller).await;
    let request = result.expect("pending request");
    assert_eq!(request.request_id, "req-1");
    assert_eq!((request.chat_id.as_str(), request.version), (CHAT, 1));
    assert_eq!(types(&frames), ["chat_system_message_added"]);
    assert_eq!(decode(&frames[0])["type"], "e2b_upload_consent_request");
    let [StreamUpdate::Status(status)] = &updates[..] else {
        panic!("expected one status update")
    };
    let json = status.strip_prefix(E2B_CONSENT_STATUS_PREFIX).unwrap();
    assert_eq!(
        serde_json::from_str::<SendE2bConsentRequest>(json).unwrap(),
        request
    );
}

#[tokio::test]
async fn caller_with_receiver_answers_the_chosen_wire_string_and_continues() {
    let (mut ws, server) = peer().await;
    let mut client = client();
    let (choices, receiver) = mpsc::unbounded_channel();
    client.set_e2b_consent_receiver(receiver);
    // A stale answer for another request must be ignored.
    choices
        .send(("other".into(), E2bConsentChoice::NotNow))
        .unwrap();
    choices
        .send(("req-1".into(), E2bConsentChoice::OwnMachine))
        .unwrap();
    let (updates, mut seen) = mpsc::channel(4);
    let cancel = CancellationToken::new();
    let result = client
        .send_e2b_consent(
            &mut ws,
            &frame(),
            CHAT,
            &KEY,
            &updates,
            &cancel,
            E2bConsentPolicy::Caller,
        )
        .await
        .unwrap();
    assert!(result.is_none());
    assert!(matches!(seen.recv().await, Some(StreamUpdate::Status(_))));
    drop(ws);
    let frames = server.await.unwrap();
    assert_eq!(
        types(&frames),
        [
            "chat_system_message_added",
            "e2b_upload_consent_answer",
            "chat_system_message_added"
        ]
    );
    assert_eq!(frames[1]["payload"]["choice"], "own_machine");
    assert_eq!(decode(&frames[2])["choice"], "own_machine");
}

#[tokio::test]
async fn caller_with_receiver_stops_waiting_on_cancellation() {
    let (mut ws, _server) = peer().await;
    let mut client = client();
    let (_choices, receiver) = mpsc::unbounded_channel();
    client.set_e2b_consent_receiver(receiver);
    let (updates, _seen) = mpsc::channel(4);
    let cancel = CancellationToken::new();
    cancel.cancel();
    let result = client
        .send_e2b_consent(
            &mut ws,
            &frame(),
            CHAT,
            &KEY,
            &updates,
            &cancel,
            E2bConsentPolicy::Caller,
        )
        .await;
    assert!(matches!(result, Err(Error::Cancelled)));
}

#[test]
fn a_request_frame_is_handled_once_and_only_for_this_chat() {
    let mut seen = std::collections::HashSet::new();
    assert!(admit_e2b_request(&frame(), CHAT, &mut seen));
    assert!(!admit_e2b_request(&frame(), CHAT, &mut seen));
    assert!(!admit_e2b_request(
        &json!({"request_id":"r2","chat_id":"other"}),
        CHAT,
        &mut seen
    ));
    assert!(!admit_e2b_request(
        &json!({"chat_id":CHAT}),
        CHAT,
        &mut seen
    ));
}
