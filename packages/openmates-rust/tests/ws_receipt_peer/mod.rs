//! Synthetic loopback-only WebSocket peer for private receipt boundaries.
use crate::client::transport::{Socket, test_socket};
use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use tokio::task::JoinHandle;
use tokio_tungstenite::tungstenite::Message;

pub(in crate::client) async fn once<F>(respond: F) -> (Socket, JoinHandle<()>)
where
    F: FnOnce(Value) -> Vec<Value> + Send + 'static,
{
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    assert!(address.ip().is_loopback());
    let peer = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let frame = ws.next().await.unwrap().unwrap();
        let request = serde_json::from_str(frame.to_text().unwrap()).unwrap();
        for response in respond(request) {
            ws.send(Message::text(response.to_string())).await.unwrap();
        }
    });
    let (ws, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    (test_socket(ws), peer)
}
