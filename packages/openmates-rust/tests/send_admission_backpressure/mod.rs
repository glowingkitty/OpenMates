//! Exact send-on-socket peer regression. Local synthetic IO only, no product or AI.
//! Queue capacity1 deterministically suspends Submitted behind Started. Polling
//! the real operation to Pending establishes the boundary without sleeps/hooks.
//! Actual Rust execution belongs to the parent guarded test run.
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
use super::*;
use futures_util::{SinkExt, StreamExt};
use std::{
    future::{Future, poll_fn},
    task::Poll,
};
use tokio_tungstenite::tungstenite::Message as Frame;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const TURN: &str = "33333333-3333-4333-8333-333333333333";
const MESSAGE: &str = "44444444-4444-4444-8444-444444444444";
const KEY: [u8; 32] = [9; 32];
const DEADLINE: Duration = Duration::from_secs(3);
#[derive(Clone, Copy)]
enum Case {
    CancelClose,
    CancelDrain,
    Normal,
}
async fn emit(
    ws: &mut tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>,
    kind: &str,
    payload: Value,
) {
    ws.send(Frame::Text(
        json!({"type":kind,"payload":payload}).to_string().into(),
    ))
    .await
    .unwrap();
}
async fn exercise(case: Case) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let mut frames = vec![];
        while let Some(raw) = ws.next().await {
            let raw = raw.unwrap();
            if matches!(raw, Frame::Close(_)) {
                return frames;
            }
            let event: Value = serde_json::from_str(&raw.into_text().unwrap()).unwrap();
            let kind = event["type"].as_str().unwrap().to_owned();
            frames.push(kind.clone());
            match kind.as_str() {
                "set_active_chat" => assert_eq!(event["payload"]["chat_id"], CHAT),
                "personal_send_context_snapshot" => {
                    assert_eq!(event["payload"]["turn_id"], TURN);
                    emit(&mut ws,"personal_send_context_snapshot_result",json!({
                        "success":true,"unchanged":false,"request_id":event["payload"]["request_id"],
                        "turn_id":TURN,"receipt_id":"synthetic-receipt","privacy_generation":1,
                        "project_candidates":[],"personal_memories":{"memories":[]}})).await;
                }
                "chat_turn_admit" => {
                    assert_eq!(event["payload"]["chat_id"], CHAT);
                    assert_eq!(event["payload"]["turn_id"], TURN);
                    assert_eq!(event["payload"]["message_id"], MESSAGE);
                    assert_eq!(event["payload"]["privacy_receipt_id"], "synthetic-receipt");
                    if matches!(case, Case::Normal) {
                        emit(&mut ws,"chat_turn_preflight_ack",json!({"turn_id":TURN,"preflight_id":"synthetic-preflight","committed_messages_v":1})).await;
                        emit(
                            &mut ws,
                            "chat_message_confirmed",
                            json!({"chat_id":CHAT,"message_id":MESSAGE,"new_messages_v":1}),
                        )
                        .await;
                        emit(&mut ws,"message_queued",json!({"chat_id":CHAT,"message_id":MESSAGE,"user_message_id":MESSAGE,"turn_id":TURN,"recovery_turn_id":TURN,"queue_mode":"follow_up","queue_revision":1})).await;
                    }
                }
                _ => panic!("unexpected protocol effect"),
            }
        }
        panic!("socket closed without explicit cleanup frame");
    });
    let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    let mut socket = transport::test_socket(inner);
    let api = "https://api.example.invalid";
    let mut client = Client::new(
        api,
        Some(Session {
            api_url: api.into(),
            session_id: MESSAGE.into(),
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
    .unwrap();
    client.user = json!({"id":OWNER});
    let wrapped = crypto::encrypt_bytes(&KEY, &[7; 32]).unwrap();
    let mut chat = Chat {
        id: CHAT.into(),
        ..Default::default()
    };
    let (updates, mut receiver) = mpsc::channel(1);
    let cancel = CancellationToken::new();
    let options = SendOptions {
        pii_detection: false,
        task_update_jobs: false,
        response_timeout_ms: Some(2_000),
        ..Default::default()
    };
    let generation = client.generation;
    let mut trace = SendTrace::new();
    let mut operation = Box::pin(client.send_on_socket(
        &mut socket,
        CHAT,
        TURN,
        MESSAGE,
        "synthetic input",
        &KEY,
        &wrapped,
        0,
        true,
        &[],
        &mut chat,
        &updates,
        &cancel,
        generation,
        None,
        &options,
        &mut trace,
    ));
    // Poll until the actual Started send filled the only slot and the actual
    // Submitted send returned Pending. No other pre-admission update is emitted.
    tokio::time::timeout(
        DEADLINE,
        poll_fn(|context| {
            if let Poll::Ready(_) = operation.as_mut().poll(context) {
                panic!("operation ended before Submitted backpressure");
            }
            if updates.capacity() == 0 {
                Poll::Ready(())
            } else {
                Poll::Pending
            }
        }),
    )
    .await
    .expect("bounded queue reached Submitted suspension");
    assert_eq!(receiver.len(), 1);
    let mut events = vec![];
    let result = match case {
        Case::CancelClose | Case::CancelDrain => {
            cancel.cancel();
            if matches!(case, Case::CancelClose) {
                receiver.close();
            } else {
                events.push(receiver.recv().await.expect("Started remains queued"));
            }
            tokio::time::timeout(DEADLINE, operation.as_mut())
                .await
                .expect("cancel plus receiver release must not deadlock")
        }
        Case::Normal => {
            // Drain the same real bounded queue while the operation proceeds.
            let observe = async {
                for _ in 0..4 {
                    events.push(receiver.recv().await.expect("normal update sequence"));
                }
            };
            let (result, ()) = tokio::time::timeout(DEADLINE, async {
                tokio::join!(operation.as_mut(), observe)
            })
            .await
            .expect("normal operation and event drain complete");
            result
        }
    };
    drop(operation);
    receiver.close();
    while let Ok(update) = receiver.try_recv() {
        events.push(update);
    }
    let _ = socket.close(None).await;
    let frames = tokio::time::timeout(DEADLINE, peer)
        .await
        .expect("peer cleanup does not deadlock")
        .unwrap();
    match case {
        Case::CancelClose | Case::CancelDrain => {
            assert!(matches!(result, Err(Error::Cancelled)));
            // Checking every emitted frame also excludes queue/admission/recovery
            // persistence/cancel-task effects, not just an absent completion event.
            assert_eq!(
                frames,
                vec!["set_active_chat", "personal_send_context_snapshot"]
            );
            assert!(chat.messages.is_empty());
            assert!(
                matches!(events.first(),Some(StreamUpdate::Started{chat_id,message_id,..}) if chat_id==CHAT&&message_id==MESSAGE)
            );
            if matches!(case, Case::CancelDrain) {
                assert_eq!(events.len(), 2);
                assert!(
                    matches!(&events[1],StreamUpdate::Submitted{chat_id,message_id} if chat_id==CHAT&&message_id==MESSAGE)
                );
            } else {
                assert_eq!(events.len(), 1);
            }
            assert!(!events.iter().any(|event| matches!(
                event,
                StreamUpdate::Admitted { .. } | StreamUpdate::Completed { .. }
            )));
        }
        Case::Normal => {
            let outcome = result.unwrap();
            assert!(matches!(outcome.status, SendStatus::Queued));
            assert_eq!(outcome.queue_revision, Some(1));
            assert_eq!(outcome.chat.messages.len(), 1);
            assert_eq!(outcome.chat.messages[0].id, MESSAGE);
            assert_eq!(
                frames,
                vec![
                    "set_active_chat",
                    "personal_send_context_snapshot",
                    "chat_turn_admit"
                ]
            );
            assert_eq!(events.len(), 4);
            assert!(
                matches!(&events[0],StreamUpdate::Started{chat_id,message_id,..} if chat_id==CHAT&&message_id==MESSAGE)
            );
            assert!(
                matches!(&events[1],StreamUpdate::Submitted{chat_id,message_id} if chat_id==CHAT&&message_id==MESSAGE)
            );
            assert!(
                matches!(&events[2],StreamUpdate::Admitted{chat_id,message_id} if chat_id==CHAT&&message_id==MESSAGE)
            );
            assert!(matches!(&events[3], StreamUpdate::Status(_)));
        }
    }
}
#[tokio::test]
async fn cancel_while_submitted_is_blocked_then_close_receiver_has_zero_admission_effects() {
    exercise(Case::CancelClose).await;
}
#[tokio::test]
async fn cancel_while_submitted_is_blocked_then_drain_preserves_uncertainty_without_admission() {
    exercise(Case::CancelDrain).await;
}
#[tokio::test]
async fn uncancelled_submitted_backpressure_preserves_original_events_and_one_wire_admission() {
    exercise(Case::Normal).await;
}
