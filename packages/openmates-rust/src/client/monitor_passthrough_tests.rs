//! The shell passthrough hook of the live monitor socket over a real local
//! WebSocket peer: frames the core does not own reach the shell in arrival
//! order, owned frames do not, and raw shell frames are written and settled.
use super::*;
use crate::view_model::UnownedSocketItem;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::tungstenite::Message as Frame;

const CHAT: &str = "11111111-1111-4111-8111-111111111111";

/// The client must outlive the monitor: dropping it cancels the owner epoch
/// the fence checks.
fn monitor() -> (Client, ChatMonitor) {
    let client = Client::new("https://api.example.com", None).unwrap();
    let monitor = ChatMonitor {
        fence: Arc::new(MonitorFence {
            owner: client.task_watch_authority.clone(),
            generation: client.generation,
            team: None,
            expires_at: None,
            cancel: CancellationToken::new(),
            alive: AtomicBool::new(true),
            denial: Mutex::new(None),
        }),
        changes: Arc::new(Changes::default()),
    };
    (client, monitor)
}

/// A peer that answers each client text frame of type `synthetic_shell_ping`
/// with `synthetic_shell_pong`, sends `frames` first and `force_logout` after
/// the first answer (or at once without a ping), then waits for the close.
async fn peer(
    frames: Vec<Value>,
    answer_ping: bool,
) -> (transport::Socket, tokio::task::JoinHandle<Vec<Value>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        for frame in frames {
            ws.send(Frame::Text(frame.to_string().into()))
                .await
                .unwrap();
        }
        let logout = json!({"type":"force_logout","payload":{}}).to_string();
        if !answer_ping {
            ws.send(Frame::Text(logout.clone().into())).await.unwrap();
        }
        let mut received = Vec::new();
        tokio::time::timeout(Duration::from_secs(4), async {
            while let Some(frame) = ws.next().await {
                match frame.unwrap() {
                    Frame::Text(text) => {
                        let value: Value = serde_json::from_str(&text).unwrap();
                        if value["type"] == "synthetic_shell_ping" {
                            let pong = json!({"type":"synthetic_shell_pong","payload":{"n":value["payload"]["n"]}});
                            ws.send(Frame::Text(pong.to_string().into())).await.unwrap();
                            ws.send(Frame::Text(logout.clone().into())).await.unwrap();
                        }
                        received.push(value);
                    }
                    Frame::Close(_) => return,
                    _ => {}
                }
            }
        })
        .await
        .unwrap();
        received
    });
    let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    (transport::test_socket(inner), server)
}

fn run(
    handle: &ChatMonitor,
    socket: transport::Socket,
) -> (tokio::task::JoinHandle<()>, mpsc::Receiver<Error>) {
    let (errors, receiver) = mpsc::channel(1);
    let task = tokio::spawn(monitor_socket_mode(
        socket,
        handle.fence.cancel.clone(),
        errors,
        None,
        json!({"client_type":"rust","interactive":false,"is_foreground":true}),
        Duration::from_secs(25),
        Some(handle.changes.clone()),
        Some(handle.fence.clone()),
        None,
    ));
    (task, receiver)
}

fn item(event_type: &str, payload: Value) -> UnownedSocketItem {
    UnownedSocketItem::Frame {
        event_type: event_type.into(),
        payload_json: payload.to_string(),
    }
}

#[tokio::test]
async fn unowned_frames_reach_the_shell_in_order_and_owned_ones_do_not() {
    let (_client, handle) = monitor();
    let frames = vec![
        json!({"type":"embed_update","payload":{"embed_id":"synthetic-embed"}}),
        json!({"type":"chat_sync_hint","payload":{"revision":4}}),
        json!({"type":"chat_deleted","payload":{"chat_id":CHAT}}),
        json!({"type":"ai_message_update","payload":{"chat_id":CHAT,"is_final_chunk":false}}),
        json!({"event":"chat_title_updated","chat_id":CHAT,"data":{"encrypted_title":"opaque-fixture"},"versions":{"metadata_v":2}}),
        json!({"type":"reminder_fired","payload":{"reminder_id":"synthetic-reminder"}}),
    ];
    let (socket, server) = peer(frames, false).await;
    let (task, mut errors) = run(&handle, socket);
    assert_eq!(errors.recv().await, Some(Error::Expired));
    task.await.unwrap();
    server.await.unwrap();
    // Attached after the socket ended: the frames buffered since it opened
    // come first, then the stream ends.
    let frames = handle.socket_passthrough().attach().unwrap();
    let mut seen = Vec::new();
    while let Some(next) = frames.recv().await {
        seen.push(next);
    }
    assert_eq!(
        seen,
        [
            item("embed_update", json!({"embed_id":"synthetic-embed"})),
            item("chat_deleted", json!({"chat_id":CHAT})),
            item(
                "reminder_fired",
                json!({"reminder_id":"synthetic-reminder"})
            ),
        ]
    );
    // The core still handled its own frames.
    assert!(handle.changes.pending.lock().unwrap().refresh);
}

#[tokio::test]
async fn a_shell_frame_is_written_between_core_frames_and_later_sends_disconnect() {
    let (_client, handle) = monitor();
    let (socket, server) = peer(Vec::new(), true).await;
    let passthrough = handle.socket_passthrough();
    let (task, mut errors) = run(&handle, socket);
    assert_eq!(
        passthrough.send("synthetic_shell_ping", r#"{"n":7}"#).await,
        Ok(())
    );
    assert_eq!(errors.recv().await, Some(Error::Expired));
    task.await.unwrap();
    let received = server.await.unwrap();
    assert!(
        received
            .iter()
            .any(|frame| frame == &json!({"type":"synthetic_shell_ping","payload":{"n":7}}))
    );
    let frames = passthrough.attach().unwrap();
    assert_eq!(
        frames.recv().await,
        Some(item("synthetic_shell_pong", json!({"n":7})))
    );
    assert_eq!(frames.recv().await, None);
    assert_eq!(
        passthrough.send("synthetic_shell_ping", "{}").await,
        Err(crate::view_model::UnownedFrameError::Disconnected)
    );
}
