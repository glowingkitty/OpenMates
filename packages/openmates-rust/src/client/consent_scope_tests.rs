//! Authored source-only synthetic peer regressions. Runtime UNRUN here.
//! Requires the reviewed projected delivery/Plain and guarded-transport seams.
// contract-test-file: tooling
use super::*;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use futures_util::{SinkExt, StreamExt};
use std::{
    future::{Future, poll_fn},
    sync::Arc,
    task::Poll,
};
use tokio::task::JoinHandle;
use tokio_tungstenite::tungstenite::Message as Frame;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const OWNER: &str = "33333333-3333-4333-8333-333333333333";
struct Port(Key);
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            crypto::encrypt_aead(plain, &self.0, iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::decrypt_aead(cipher, &self.0, iv, &[]) })
    }
}
fn client(opaque: bool, expiry: Option<u64>) -> Client {
    let session = Session {
        api_url: "http://127.0.0.1:9".into(),
        session_id: "synthetic-consent".into(),
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
    // Model credentials expiring after admission: the public constructor
    // correctly rejects a session that is already expired at admission.
    client.session.as_mut().unwrap().paired_session_expires_at = expiry;
    client.user = json!({"id":OWNER});
    if opaque {
        let mut credentials =
            credentials::BrowserCredentials::from_native_session(client.session.take().unwrap());
        credentials.master =
            MasterCapability::opaque_for_test(Arc::new(Port(zeroize::Zeroizing::new([7; 32]))));
        client.browser_credentials = Some(credentials);
        client.browser_authority = Some(browser::BrowserAuthority {
            principal: OWNER.into(),
            persistence: browser::BrowserPersistence::MemoryOnly,
            owner_guards: true,
        });
    }
    client
}
async fn peer(flood: usize) -> (Socket, JoinHandle<Vec<Value>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let mut frames = vec![];
        let mut flooded = false;
        while let Some(Ok(frame)) = ws.next().await {
            if !frame.is_text() {
                continue;
            }
            let request: Value = serde_json::from_str(frame.to_text().unwrap()).unwrap();
            if request["type"] == "chat_system_message_added" {
                let message = &request["payload"]["message"];
                ws.send(Frame::text(json!({"type":"system_message_confirmed","payload":{"message_id":message["message_id"]}}).to_string())).await.unwrap();
                if !flooded {
                    flooded = true;
                    for index in 0..flood {
                        if ws.send(Frame::text(json!({"type":"synthetic_deferred","payload":{"private":"Synthetic deferred value","index":index}}).to_string())).await.is_err(){break;}
                    }
                }
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
fn proposals() -> Value {
    json!({"sub_chats":[{"title":"Synthetic title","prompt":"Synthetic private prompt","mate":"Synthetic mate"}],"remaining_sub_chats":1})
}
fn memory_event() -> Value {
    json!({"request_id":"synthetic-memory-request","requested_keys":["notes-private","notes-private"]})
}
fn memories() -> Vec<Value> {
    vec![
        json!({"app_id":"notes","item_type":"private","data":{"private":"Synthetic private memory"}}),
    ]
}
#[tokio::test]
async fn bounded_consent_queue_never_transfers_plaintext_after_any_revocation() {
    for mode in ["user", "operation", "owner", "master", "denial"] {
        let (mut ws, server) = peer(0).await;
        let expiry = None;
        let mut client = client(true, expiry);
        let operation = client.operation_cancel.clone();
        let owner = client.task_watch_authority.clone();
        let master = client.master_capability().unwrap();
        let cancel = CancellationToken::new();
        let (updates, mut receiver) = mpsc::channel(1);
        updates
            .try_send(StreamUpdate::Status("prefill".into()))
            .unwrap();
        let event = proposals();
        let mut call = Box::pin(client.subchat_consent(
            &mut ws,
            &event,
            CHAT,
            "task",
            &updates,
            &cancel,
            SendConsentPolicy::Caller,
        ));
        poll_fn(|cx| match call.as_mut().poll(cx) {
            Poll::Pending => Poll::Ready(()),
            Poll::Ready(_) => panic!("must wait behind bounded prefill"),
        })
        .await;
        match mode {
            "user" => cancel.cancel(),
            "operation" => operation.cancel(),
            "owner" => owner.cancel.cancel(),
            "master" => master.invalidate(),
            "denial" => {
                owner.deny_cached_chat(Some(CHAT)).unwrap();
                let _ = receiver.recv().await;
            }
            _ => unreachable!(),
        };
        let result = crate::platform::time::timeout(Duration::from_secs(2), call.as_mut())
            .await
            .unwrap();
        assert!(matches!(
            result,
            Err(Error::Cancelled | Error::Expired | Error::Forbidden)
        ));
        drop(call);
        if mode != "denial" {
            assert!(matches!(
                receiver.recv().await,
                Some(StreamUpdate::Status(_))
            ));
        }
        assert!(receiver.try_recv().is_err());
        assert_eq!(client.credential_ack, 0);
        drop(ws);
        assert!(server.await.unwrap().is_empty());
    }
}
#[tokio::test]
async fn dropping_backpressured_consent_cannot_publish_when_capacity_returns() {
    let (mut ws, server) = peer(0).await;
    let mut client = client(true, None);
    let cancel = CancellationToken::new();
    let (updates, mut receiver) = mpsc::channel(1);
    updates
        .try_send(StreamUpdate::Status("prefill".into()))
        .unwrap();
    let event = proposals();
    let mut call = Box::pin(client.subchat_consent(
        &mut ws,
        &event,
        CHAT,
        "task",
        &updates,
        &cancel,
        SendConsentPolicy::Caller,
    ));
    poll_fn(|cx| match call.as_mut().poll(cx) {
        Poll::Pending => Poll::Ready(()),
        Poll::Ready(_) => panic!("must wait behind bounded prefill"),
    })
    .await;
    drop(call);
    let _ = receiver.recv().await;
    assert!(receiver.try_recv().is_err());
    drop(ws);
    assert!(server.await.unwrap().is_empty());
}
#[tokio::test]
async fn caller_approval_cannot_outlive_original_subchat_or_memory_authority() {
    for memory in [false, true] {
        for mode in ["operation", "owner", "master", "denial"] {
            let (mut ws, server) = peer(0).await;
            let mut client = client(true, None);
            let operation = client.operation_cancel.clone();
            let owner = client.task_watch_authority.clone();
            let master = client.master_capability().unwrap();
            let (decisions, decision_rx) = mpsc::unbounded_channel();
            client.set_consent_receiver(decision_rx);
            let (updates, mut receiver) = mpsc::channel(1);
            let cancel = CancellationToken::new();
            let event = if memory { memory_event() } else { proposals() };
            let memories = memories();
            let decision = async {
                let update = Plain::new(receiver.recv().await.unwrap());
                let StreamUpdate::Consent { request_id, items } = &*update else {
                    panic!("expected consent")
                };
                assert!(!items.is_empty());
                match mode {
                    "operation" => operation.cancel(),
                    "owner" => owner.cancel.cancel(),
                    "master" => master.invalidate(),
                    "denial" => owner.deny_cached_chat(Some(CHAT)).unwrap(),
                    _ => unreachable!(),
                };
                decisions
                    .send((
                        request_id.clone(),
                        vec![if memory {
                            "notes-private".into()
                        } else {
                            "start_sub_chats".into()
                        }],
                    ))
                    .unwrap();
            };
            let run = async {
                if memory {
                    client
                        .memory_consent(
                            &mut ws,
                            &event,
                            CHAT,
                            "message",
                            &[9; 32],
                            &memories,
                            &updates,
                            &cancel,
                            SendConsentPolicy::Caller,
                        )
                        .await
                        .map(|_| ())
                } else {
                    client
                        .subchat_consent(
                            &mut ws,
                            &event,
                            CHAT,
                            "task",
                            &updates,
                            &cancel,
                            SendConsentPolicy::Caller,
                        )
                        .await
                        .map(|_| ())
                }
            };
            let (result, _) = tokio::join!(run, decision);
            assert!(matches!(result, Err(Error::Cancelled | Error::Forbidden)));
            drop(ws);
            let frames = server.await.unwrap();
            assert_eq!(frames.len(), usize::from(memory));
            assert!(
                frames
                    .iter()
                    .all(|v| v["type"] == "chat_system_message_added")
            );
            assert_eq!(client.credential_ack, 0);
        }
    }
}
#[tokio::test]
async fn native_and_opaque_memory_policies_preserve_ids_dedup_and_system_metadata_order() {
    for opaque in [false, true] {
        for policy in [
            SendConsentPolicy::Caller,
            SendConsentPolicy::Reject,
            SendConsentPolicy::ApproveRequested,
        ] {
            let (mut ws, server) = peer(0).await;
            let mut client = client(opaque, None);
            let (decisions, decision_rx) = mpsc::unbounded_channel();
            client.set_consent_receiver(decision_rx);
            let (updates, mut receiver) = mpsc::channel(1);
            let cancel = CancellationToken::new();
            let event = memory_event();
            let memories = memories();
            let decide = async {
                if policy == SendConsentPolicy::Caller {
                    let update = Plain::new(receiver.recv().await.unwrap());
                    let StreamUpdate::Consent { request_id, items } = &*update else {
                        panic!("expected consent")
                    };
                    assert_eq!(request_id, "synthetic-memory-request");
                    assert_eq!(items.len(), 1);
                    assert_eq!(
                        items[0].fields["entries"][0]["private"],
                        "Synthetic private memory"
                    );
                    decisions
                        .send(("unrelated-request".into(), vec!["foreign-key".into()]))
                        .unwrap();
                    decisions
                        .send((
                            request_id.clone(),
                            vec!["notes-private".into(), "notes-private".into()],
                        ))
                        .unwrap();
                }
            };
            let (result, _) = tokio::join!(
                client.memory_consent(
                    &mut ws, &event, CHAT, "message", &[9; 32], &memories, &updates, &cancel,
                    policy
                ),
                decide
            );
            let (deferred, record) = result.unwrap();
            assert!(deferred.is_empty());
            let approved = policy != SendConsentPolicy::Reject;
            assert_eq!(record.requested_keys, ["notes-private"]);
            assert_eq!(record.approved_keys.len(), usize::from(approved));
            assert_eq!(record.entry_count, u64::from(approved));
            drop(ws);
            let frames = server.await.unwrap();
            assert_eq!(
                frames
                    .iter()
                    .map(|v| v["type"].as_str().unwrap())
                    .collect::<Vec<_>>(),
                [
                    "chat_system_message_added",
                    "app_settings_memories_confirmed",
                    "chat_system_message_added"
                ]
            );
            let decode = |frame: &Value| -> Value {
                serde_json::from_str(
                    &crypto::decrypt_combined(
                        frame["payload"]["message"]["encrypted_content"]
                            .as_str()
                            .unwrap(),
                        &[9; 32],
                    )
                    .unwrap(),
                )
                .unwrap()
            };
            assert_eq!(decode(&frames[0])["type"], "app_settings_memories_request");
            assert_eq!(decode(&frames[2])["type"], "app_settings_memories_response");
            assert_eq!(
                decode(&frames[2])["action"],
                if approved { "included" } else { "rejected" }
            );
            assert_eq!(
                frames[1]["payload"]["app_settings_memories"]
                    .as_array()
                    .unwrap()
                    .len(),
                usize::from(approved)
            );
            assert_eq!(client.credential_ack, 0);
            if opaque {
                assert!(client.native_master_key().is_err());
            }
        }
    }
}
#[tokio::test]
async fn deferred_frame_limit_still_refuses_without_confirmation_or_response_metadata() {
    let (mut ws, server) = peer(257).await;
    let mut client = client(true, None);
    let (_decisions, decision_rx) = mpsc::unbounded_channel();
    client.set_consent_receiver(decision_rx);
    let (updates, _receiver) = mpsc::channel(1);
    let event = memory_event();
    let memories = memories();
    let result = client
        .memory_consent(
            &mut ws,
            &event,
            CHAT,
            "message",
            &[9; 32],
            &memories,
            &updates,
            &CancellationToken::new(),
            SendConsentPolicy::Caller,
        )
        .await;
    assert!(matches!(result, Err(Error::Protocol)));
    drop(ws);
    let frames = server.await.unwrap();
    assert_eq!(frames.len(), 1);
    assert_eq!(frames[0]["type"], "chat_system_message_added");
}
#[tokio::test]
async fn closed_consent_consumer_preserves_cancellation_instead_of_silent_delivery_success() {
    for memory in [false, true] {
        let (mut ws, server) = peer(0).await;
        let mut client = client(true, None);
        let (updates, receiver) = mpsc::channel(1);
        drop(receiver);
        let cancel = CancellationToken::new();
        let event = if memory { memory_event() } else { proposals() };
        let memories = memories();
        let result = if memory {
            client
                .memory_consent(
                    &mut ws,
                    &event,
                    CHAT,
                    "message",
                    &[9; 32],
                    &memories,
                    &updates,
                    &cancel,
                    SendConsentPolicy::Caller,
                )
                .await
                .map(|_| ())
        } else {
            client
                .subchat_consent(
                    &mut ws,
                    &event,
                    CHAT,
                    "task",
                    &updates,
                    &cancel,
                    SendConsentPolicy::Caller,
                )
                .await
                .map(|_| ())
        };
        assert!(matches!(result, Err(Error::Cancelled)));
        drop(ws);
        assert_eq!(server.await.unwrap().len(), usize::from(memory));
    }
}

#[tokio::test]
async fn known_expired_credentials_never_deliver_or_confirm_consent() {
    for opaque in [false, true] {
        let (mut ws, server) = peer(0).await;
        let mut client = client(opaque, Some(now_ms().saturating_sub(1)));
        let (updates, mut receiver) = mpsc::channel(1);
        let event = proposals();
        let result = client
            .subchat_consent(
                &mut ws,
                &event,
                CHAT,
                "task",
                &updates,
                &CancellationToken::new(),
                SendConsentPolicy::Caller,
            )
            .await;
        assert!(matches!(result, Err(Error::Expired)));
        assert!(receiver.try_recv().is_err());
        drop(ws);
        assert!(server.await.unwrap().is_empty());
    }
}
