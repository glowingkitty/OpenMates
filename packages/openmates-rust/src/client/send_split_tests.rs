//! The split saved turn over a loopback socket with synthetic credentials: the client lease is free while the reply streams, a queued admission ends `Queued`, and a cancel withdraws the task on the turn's own socket.
use super::*;
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tokio::sync::{Mutex, oneshot};
use tokio_tungstenite::tungstenite::Message as Frame;

const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const TURN: &str = "33333333-3333-4333-8333-333333333333";
const MESSAGE: &str = "44444444-4444-4444-8444-444444444444";
const TASK: &str = "synthetic-task";

type Peer = tokio_tungstenite::WebSocketStream<tokio::net::TcpStream>;

/// The actor's client behind a lock, as a shell actor holds it.
struct Locked(Mutex<Client>);

impl ClientLease for Locked {
    fn lease(&self) -> BoxFuture<'_, Result<LeasedClient<'_>>> {
        Box::pin(async move { Ok(Box::new(self.0.lock().await) as LeasedClient<'_>) })
    }
}

fn client() -> Client {
    let mut session = super::super::super::sdk_boundary_tests::session();
    session.api_url = "http://127.0.0.1:1".into();
    session.master_key = zeroize::Zeroizing::new([7; 32]);
    let mut c = Client::new("http://127.0.0.1:1", Some(session)).unwrap();
    c.user = json!({"id":OWNER});
    c
}

async fn emit(ws: &mut Peer, kind: &str, payload: Value) {
    ws.send(Frame::Text(
        json!({"type":kind,"payload":payload}).to_string().into(),
    ))
    .await
    .unwrap();
}

async fn next(ws: &mut Peer) -> Option<Value> {
    loop {
        match ws.next().await? {
            Ok(Frame::Text(text)) => return Some(serde_json::from_str(&text).unwrap()),
            Ok(Frame::Close(_)) | Err(_) => return None,
            Ok(_) => {}
        }
    }
}

/// Answer the admission frames, then the admit with the preflight ack and
/// the confirmation.
async fn admit_peer(ws: &mut Peer) {
    while let Some(event) = next(ws).await {
        match event["type"].as_str().unwrap() {
            "set_active_chat" => assert_eq!(event["payload"]["chat_id"], CHAT),
            "personal_send_context_snapshot" => {
                let settings =
                    crypto::server_fields::encrypt_text("{\"rule_documents\":[]}", &[7; 32], &[])
                        .unwrap();
                emit(
                    ws,
                    "personal_send_context_snapshot_result",
                    json!({"success":true,
                    "unchanged":false,"request_id":event["payload"]["request_id"],"turn_id":TURN,
                    "receipt_id":"synthetic-receipt","privacy_generation":1,"project_candidates":[],
                    "personal_memories":{"memories":[],"encrypted_settings":settings}}),
                )
                .await;
            }
            "chat_turn_admit" => {
                emit(
                    ws,
                    "chat_turn_preflight_ack",
                    json!({"turn_id":TURN,
                    "preflight_id":"synthetic-preflight","committed_messages_v":1}),
                )
                .await;
                emit(
                    ws,
                    "chat_message_confirmed",
                    json!({"chat_id":CHAT,
                    "message_id":MESSAGE,"new_messages_v":1}),
                )
                .await;
                return;
            }
            other => panic!("unexpected admission frame {other}"),
        }
    }
    panic!("the admission ended early");
}

/// A loopback turn socket and its peer task running `script`.
async fn socket<F, Fut>(script: F) -> (Socket, tokio::task::JoinHandle<Option<Value>>)
where
    F: FnOnce(Peer) -> Fut + Send + 'static,
    Fut: std::future::Future<Output = Option<Value>> + Send,
{
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        script(tokio_tungstenite::accept_async(stream).await.unwrap()).await
    });
    let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    (transport::test_socket(inner), peer)
}

/// Admit the synthetic turn on the locked client.
async fn admit(
    lease: &Locked,
    ws: Socket,
    updates: mpsc::Sender<StreamUpdate>,
    cancel: CancellationToken,
) -> AdmittedTurn {
    let mut c = lease.0.lock().await;
    let cap = c.cached_wrapping_capability().unwrap();
    let (key, wrapped) = c
        .turn_chat_material_with_capability(None, &cap)
        .await
        .unwrap();
    let admission = Admission {
        id: CHAT.into(),
        turn: TURN.into(),
        message: MESSAGE.into(),
        input: "synthetic input",
        key,
        wrapped,
        baseline: 0,
        new_chat: true,
        chat: Plain::new(Chat {
            id: CHAT.into(),
            ..Default::default()
        }),
        generation: c.generation,
        release_scope: AsyncCryptoScope::begin(&c).unwrap(),
    };
    let options = SendOptions {
        pii_detection: false,
        task_update_jobs: false,
        response_timeout_ms: Some(5_000),
        ..Default::default()
    };
    c.admit_on_socket(ws, admission, vec![], None, options, updates, cancel)
        .await
        .unwrap()
}

/// Wait for `Admitted`: the stream step has handled the server's frames.
async fn admitted(updates: &mut mpsc::Receiver<StreamUpdate>) {
    while let Some(update) = updates.recv().await {
        if matches!(update, StreamUpdate::Admitted { .. }) {
            return;
        }
    }
    panic!("the turn ended before its admission");
}

#[tokio::test]
async fn the_client_is_free_while_the_reply_streams_and_a_queued_turn_ends_queued() {
    let (go, wait) = oneshot::channel::<()>();
    let (ws, peer) = socket(|mut ws| async move {
        admit_peer(&mut ws).await;
        // Hold the turn open until the test has used the client.
        wait.await.unwrap();
        emit(
            &mut ws,
            "message_queued",
            json!({"chat_id":CHAT,"message_id":MESSAGE,
            "user_message_id":MESSAGE,"turn_id":TURN,"recovery_turn_id":TURN,
            "queue_mode":"follow_up","queue_revision":2}),
        )
        .await;
        next(&mut ws).await
    })
    .await;
    let lease = Arc::new(Locked(Mutex::new(client())));
    let (tx, mut rx) = mpsc::channel(16);
    let turn = admit(&lease, ws, tx, CancellationToken::new()).await;
    let streaming = {
        let lease = lease.clone();
        tokio::spawn(async move { turn.stream(&*lease).await })
    };
    admitted(&mut rx).await;
    // Another call gets the client while the turn waits for the server.
    {
        let c = crate::platform::time::timeout(Duration::from_secs(2), lease.0.lock())
            .await
            .expect("the stream step holds the client only per phase");
        assert!(c.require_credentials().is_ok());
    }
    go.send(()).unwrap();
    let outcome = crate::platform::time::timeout(Duration::from_secs(5), streaming)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert!(matches!(outcome.status, SendStatus::Queued));
    assert_eq!(outcome.queue_revision, Some(2));
    assert_eq!(outcome.chat.messages[0].content, "synthetic input");
    // The socket was closed after the turn.
    assert!(peer.await.unwrap().is_none());
}

#[tokio::test]
async fn cancel_during_the_stream_withdraws_the_task_on_the_turn_socket() {
    let (ws, peer) = socket(|mut ws| async move {
        admit_peer(&mut ws).await;
        emit(
            &mut ws,
            "ai_typing_started",
            json!({"chat_id":CHAT,
            "user_message_id":MESSAGE,"recovery_turn_id":TURN,"task_id":TASK}),
        )
        .await;
        next(&mut ws).await
    })
    .await;
    let lease = Arc::new(Locked(Mutex::new(client())));
    let (tx, mut rx) = mpsc::channel(16);
    let cancel = CancellationToken::new();
    let turn = admit(&lease, ws, tx, cancel.clone()).await;
    let streaming = {
        let lease = lease.clone();
        tokio::spawn(async move { turn.stream(&*lease).await })
    };
    admitted(&mut rx).await;
    // Let the stream step take the task id frame.
    tokio::time::sleep(Duration::from_millis(100)).await;
    cancel.cancel();
    let result = crate::platform::time::timeout(Duration::from_secs(5), streaming)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(result, Err(Error::Cancelled)));
    let withdrawal = peer
        .await
        .unwrap()
        .expect("a withdrawal on the turn socket");
    assert_eq!(withdrawal["type"], "cancel_ai_task");
    assert_eq!(withdrawal["payload"]["task_id"], TASK);
    assert_eq!(withdrawal["payload"]["chat_id"], CHAT);
}

#[tokio::test]
async fn task_assigned_is_emitted_before_content_and_again_only_for_a_continuation_task() {
    let (ws, peer) = socket(|mut ws| async move {
        admit_peer(&mut ws).await;
        let frame = |kind: &'static str, task: &'static str, text: &'static str| {
            (
                kind,
                json!({"chat_id":CHAT,"user_message_id":MESSAGE,"recovery_turn_id":TURN,
                "task_id":task,"full_content_so_far":text}),
            )
        };
        for (kind, payload) in [
            frame("ai_typing_started", "task-one", ""),
            frame("ai_message_update", "task-one", "first"),
            frame("ai_message_update", "task-one", "first part"),
            // A continuation task replaces the first one.
            frame("ai_message_update", "task-two", "second"),
            frame("ai_message_update", "task-two", "second part"),
        ] {
            emit(&mut ws, kind, payload).await;
        }
        next(&mut ws).await
    })
    .await;
    let lease = Arc::new(Locked(Mutex::new(client())));
    let (tx, mut rx) = mpsc::channel(32);
    let cancel = CancellationToken::new();
    let turn = admit(&lease, ws, tx, cancel.clone()).await;
    let streaming = {
        let lease = lease.clone();
        tokio::spawn(async move { turn.stream(&*lease).await })
    };
    // Let the stream step take every scripted frame.
    tokio::time::sleep(Duration::from_millis(300)).await;
    cancel.cancel();
    let result = crate::platform::time::timeout(Duration::from_secs(5), streaming)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(result, Err(Error::Cancelled)));
    drop(peer);
    let mut assigned = Vec::new();
    let mut first_content = None;
    let mut position = 0;
    while let Some(update) = rx.recv().await {
        match update {
            StreamUpdate::TaskAssigned {
                chat_id,
                message_id,
                task_id,
            } => {
                assert_eq!((chat_id.as_str(), message_id.as_str()), (CHAT, MESSAGE));
                assigned.push((position, task_id));
            }
            StreamUpdate::Content { .. } => {
                first_content.get_or_insert(position);
            }
            _ => {}
        }
        position += 1;
    }
    let tasks: Vec<&str> = assigned.iter().map(|(_, task)| task.as_str()).collect();
    assert_eq!(tasks, ["task-one", "task-two"]);
    assert!(assigned[0].0 < first_content.expect("content was streamed"));
}
