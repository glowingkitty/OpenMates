//! Test-only loopback monitor: a real local WebSocket peer and a running
//! live-monitor socket task with its read actor and shell passthrough, as
//! `start_chat_monitor` builds them, for monitor and view-model tests.
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{WebSocketStream, tungstenite::Message as Frame};

/// The server end of the loopback socket.
pub(crate) type Peer = WebSocketStream<tokio::net::TcpStream>;

/// A live monitor of `client` over a fresh loopback socket.
pub(crate) struct LoopbackMonitor {
    /// The monitor handle (install it in a view core or keep it).
    pub(crate) monitor: ChatMonitor,
    /// The server end.
    pub(crate) peer: Peer,
    /// The socket task; ends when the socket retires.
    pub(crate) task: tokio::task::JoinHandle<()>,
    /// Errors the socket task reports when it ends.
    pub(crate) errors: mpsc::Receiver<Error>,
}

/// A signed-in client with synthetic credentials and principal; it never
/// reaches a network origin.
pub(crate) fn signed_in_client() -> Client {
    let session = Session {
        api_url: "https://example.invalid".into(),
        session_id: "synthetic-session".into(),
        cookies: BTreeMap::new(),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: now_ms(),
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new("https://example.invalid", Some(session)).unwrap();
    client.user = json!({"id":"11111111-1111-4111-8111-111111111111"});
    client
}

/// Connect a loopback socket and run the monitor socket task with a read
/// actor and passthrough on it, fenced to `client`'s current generation.
pub(crate) async fn live_monitor(client: &Client) -> LoopbackMonitor {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let connect = tokio_tungstenite::connect_async(format!("ws://{address}"));
    let accept = async {
        let (stream, _) = listener.accept().await.unwrap();
        tokio_tungstenite::accept_async(stream).await.unwrap()
    };
    let (connected, peer) = tokio::join!(connect, accept);
    let socket = transport::test_socket(connected.unwrap().0);
    let fence = Arc::new(MonitorFence {
        owner: client.task_watch_authority.clone(),
        generation: client.generation,
        team: client.team().unwrap().map(str::to_owned),
        expires_at: None,
        cancel: CancellationToken::new(),
        alive: AtomicBool::new(true),
        denial: Mutex::new(None),
    });
    let (port, receiver) = actor::channel(&socket);
    let changes = Arc::new(Changes::default());
    *changes.read_port.lock().unwrap() = Some(port);
    let (events, errors) = mpsc::channel(8);
    let task = tokio::spawn(monitor_socket_mode(
        socket,
        fence.cancel.clone(),
        events,
        None,
        json!({}),
        Duration::from_secs(25),
        Some(changes.clone()),
        Some(fence.clone()),
        Some(receiver),
    ));
    LoopbackMonitor {
        monitor: ChatMonitor { fence, changes },
        peer,
        task,
        errors,
    }
}

/// Send one `{"type","payload"}` frame from the server.
pub(crate) async fn send(peer: &mut Peer, kind: &str, payload: Value) {
    peer.send(Frame::Text(
        json!({"type":kind,"payload":payload}).to_string().into(),
    ))
    .await
    .unwrap();
}

/// The next client frame other than the lifecycle heartbeat; `None` once the
/// client closed the socket.
pub(crate) async fn request(peer: &mut Peer) -> Option<Value> {
    loop {
        let frame = tokio::time::timeout(Duration::from_secs(4), peer.next())
            .await
            .unwrap();
        match frame {
            Some(Ok(Frame::Text(text))) => {
                let value: Value = serde_json::from_str(&text).unwrap();
                if value["type"] != "native_client_lifecycle" {
                    return Some(value);
                }
            }
            Some(Ok(Frame::Ping(data))) => peer.send(Frame::Pong(data)).await.unwrap(),
            Some(Ok(Frame::Close(_))) | None | Some(Err(_)) => return None,
            Some(Ok(_)) => {}
        }
    }
}
