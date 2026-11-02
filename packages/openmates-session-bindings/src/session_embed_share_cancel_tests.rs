//! Actual direct SessionBridge over owned loopback HTTP/WS; UNRUN until CI.
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement
use super::*;
use base64::{Engine, engine::general_purpose::STANDARD};
use futures_util::{SinkExt, StreamExt};
use std::time::Duration;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::Notify,
    task::{JoinHandle, JoinSet},
};
const EMBED: &str = "33333333-3333-4333-8333-333333333333";
struct Peer {
    endpoint: String,
    requested: Arc<Notify>,
    closed: Arc<Notify>,
    stop: CancellationToken,
    task: JoinHandle<()>,
}
impl Drop for Peer {
    fn drop(&mut self) {
        self.stop.cancel();
        self.task.abort();
    }
}
impl Peer {
    async fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint = format!("http://{}", listener.local_addr().unwrap());
        let requested = Arc::new(Notify::new());
        let closed = Arc::new(Notify::new());
        let stop = CancellationToken::new();
        let (r, c, s) = (requested.clone(), closed.clone(), stop.clone());
        let gets = Arc::new(AtomicU64::new(0));
        let task = tokio::spawn(async move {
            let mut children = JoinSet::new();
            loop {
                tokio::select! {biased;
                    _=s.cancelled()=>break,
                    result=listener.accept()=>{let(stream,_)=result.unwrap();let(r,c,g,s)=(r.clone(),c.clone(),gets.clone(),s.clone());children.spawn(async move{tokio::select!{biased;_=s.cancelled()=>{},_=serve(stream,r,c,g)=>{}}});},
                    _=children.join_next(),if !children.is_empty()=>{}
                }
            }
            children.abort_all();
            while children.join_next().await.is_some() {}
        });
        Self {
            endpoint,
            requested,
            closed,
            stop,
            task,
        }
    }
}
async fn serve(
    mut stream: TcpStream,
    requested: Arc<Notify>,
    closed: Arc<Notify>,
    _gets: Arc<AtomicU64>,
) {
    let mut peek = [0u8; 4096];
    let n = tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let n = stream.peek(&mut peek).await.unwrap();
            assert!(n > 0);
            if peek[..n].contains(&b'\n') {
                break n;
            }
            assert!(n < peek.len());
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
    if String::from_utf8_lossy(&peek[..n]).starts_with("GET /v1/ws?") {
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        while let Some(frame) = ws.next().await {
            let frame = match frame {
                Ok(frame) => frame,
                Err(_) => break,
            };
            if frame.is_close() {
                let _ = ws.close(None).await;
                break;
            }
            if !frame.is_text() {
                continue;
            }
            let value: Value = serde_json::from_str(frame.to_text().unwrap()).unwrap();
            match value["type"].as_str().unwrap() {
                "native_client_lifecycle" => assert_eq!(value["payload"]["interactive"], false),
                "request_embed" => {
                    assert_eq!(value["payload"]["embed_id"], EMBED);
                    requested.notify_one();
                }
                _ => panic!("unexpected synthetic Cookie event"),
            }
            // Deliberately NEVER answer request_embed. Cancellation must stop
            // the actual SDK wait and release its exclusive Client mutex.
        }
        closed.notify_one();
        return;
    }
    let mut bytes = Vec::new();
    let mut chunk = [0u8; 4096];
    let header_end;
    loop {
        let n = stream.read(&mut chunk).await.unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&chunk[..n]);
        assert!(bytes.len() <= 65536);
        if let Some(at) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
            header_end = at + 4;
            break;
        }
    }
    let headers = String::from_utf8_lossy(&bytes[..header_end]).into_owned();
    let first = headers.lines().next().unwrap();
    assert!(
        headers
            .to_ascii_lowercase()
            .contains("cookie: auth_refresh_token=synthetic-cookie")
    );
    assert!(!headers.to_ascii_lowercase().contains("authorization:"));
    let length = headers
        .lines()
        .find_map(|line| {
            line.to_ascii_lowercase()
                .strip_prefix("content-length:")
                .and_then(|v| v.trim().parse::<usize>().ok())
        })
        .unwrap_or(0);
    assert!(length <= 65536);
    while bytes.len() < header_end + length {
        let n = stream.read(&mut chunk).await.unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&chunk[..n]);
    }
    assert!(first.starts_with("POST /v1/auth/session "));
    assert_eq!(serde_json::from_slice::<Value>(&bytes[header_end..header_end+length]).unwrap(),json!({"session_id":"synthetic-session"}));
    let body = json!({"success":true,"ws_token":"synthetic-cookie-version-ws","user":{"id":"11111111-1111-4111-8111-111111111111"}});
    let raw = body.to_string();
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{raw}",
        raw.len()
    );
    stream.write_all(response.as_bytes()).await.unwrap();
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn withheld_real_saved_embed_socket_cancel_and_close_never_release_url_and_unlock_client() {
    for close_first in [false, true] {
        let peer = Peer::start().await;
        let bridge=SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":"http://localhost:5173","enhanced_privacy":false,"allow_private_operations":true}).to_string()).unwrap_or_else(|_|panic!("synthetic bridge"));
        bridge.import_session(json!({"api_url":peer.endpoint,"session_id":"synthetic-session","cookies":{"auth_refresh_token":"synthetic-cookie"},"ws_token":null,"master_key":STANDARD.encode([9;32]),"hashed_email":"synthetic-owner","user_email_salt":"","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()).await.unwrap_or_else(|_|panic!("synthetic import"));
        let active = bridge.clone();
        let read = tokio::spawn(async move {active.embeds_share_url(EMBED.into(), "0".into(), "synthetic-password".into()).await});
        tokio::time::timeout(Duration::from_secs(2),peer.requested.notified()).await.unwrap();
        if close_first {tokio::time::timeout(Duration::from_secs(1),bridge.close()).await.unwrap().unwrap_or_else(|_|panic!("close"));}
        else {bridge.cancel().unwrap_or_else(|_|panic!("cancel"));}
        let error=tokio::time::timeout(Duration::from_secs(1),read).await.unwrap().unwrap().err().unwrap_or_else(||panic!("held cancelled read released URL"));
        assert_eq!(error.code,"cancelled");
        assert!(!error.message.contains("synthetic-password"));
        tokio::time::timeout(Duration::from_secs(1),peer.closed.notified()).await.unwrap();
        // This is only a mutex/drain assertion, never an admission or ACK.
        let locked=tokio::time::timeout(Duration::from_secs(1),bridge.state.client.lock()).await.unwrap();
        drop(locked);
        assert!(bridge.state.work_operations.lock().unwrap().is_empty());
        if !close_first {bridge.close().await.unwrap_or_else(|_|panic!("final close"));}
    }
}
