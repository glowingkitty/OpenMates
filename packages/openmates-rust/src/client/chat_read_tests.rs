// contract-test: supporting surface=cli assertions=chat-unread.reply.read-at-last-line,chat-unread.persistence.cross-device
use super::*;
use crate::client::workspaces::delete_tests::client;
use futures_util::StreamExt;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const ID: &str = "11111111-1111-4111-8111-111111111111";

struct Peer {
    api: String,
    frames: Arc<Mutex<Vec<Value>>>,
    metadata_reads: Arc<Mutex<usize>>,
    task: tokio::task::JoinHandle<()>,
}
impl Drop for Peer {
    fn drop(&mut self) {
        self.task.abort();
    }
}

/// Local server: the session refresh, the WebSocket write and the REST
/// metadata readback that confirms it. `counts` is what successive readbacks
/// report for the chat's stored counter.
async fn peer(counts: Vec<Value>) -> Peer {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let frames = Arc::new(Mutex::new(Vec::new()));
    let metadata_reads = Arc::new(Mutex::new(0usize));
    let (seen, reads) = (frames.clone(), metadata_reads.clone());
    let task = tokio::spawn(async move {
        loop {
            let (mut stream, _) = listener.accept().await.unwrap();
            let mut head = [0u8; 4096];
            let n = loop {
                let n = stream.peek(&mut head).await.unwrap();
                if head[..n].windows(4).any(|window| window == b"\r\n\r\n") {
                    break n;
                }
            };
            let first = String::from_utf8_lossy(&head[..n]).lines().next().unwrap().to_owned();
            if first.starts_with("GET ") {
                // The client keeps its socket open while it polls the REST
                // readback, so the socket is served beside the HTTP requests.
                let seen = seen.clone();
                tokio::spawn(async move {
                    let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
                    while let Some(Ok(frame)) = ws.next().await {
                        if let Ok(text) = frame.to_text()
                            && let Ok(value) = serde_json::from_str::<Value>(text)
                        {
                            seen.lock().unwrap().push(value);
                        }
                    }
                });
                continue;
            }
            let mut data = vec![];
            loop {
                let mut part = [0; 4096];
                let n = stream.read(&mut part).await.unwrap();
                data.extend_from_slice(&part[..n]);
                if let Some(end) = data.windows(4).position(|window| window == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&data[..end]).to_ascii_lowercase();
                    let length = headers
                        .lines()
                        .find_map(|line| line.strip_prefix("content-length:").map(|v| v.trim().parse::<usize>().unwrap()))
                        .unwrap_or(0);
                    if data.len() >= end + 4 + length {
                        break;
                    }
                }
            }
            let (extra, body) = if first.starts_with("POST /v1/auth/session ") {
                ("Set-Cookie: auth_refresh_token=rotated; HttpOnly\r\n", json!({"success":true,"ws_token":"fresh-token","user":{"id":"owner"}}))
            } else if first.starts_with("POST /v1/chats/metadata/batch ") {
                assert!(String::from_utf8_lossy(&data).contains("\"include_read_details\":true"));
                let index = {
                    let mut reads = reads.lock().unwrap();
                    *reads += 1;
                    (*reads - 1).min(counts.len() - 1)
                };
                ("", json!({"chats":[{"id":ID,"read_details":{"unread_count":counts[index]}}]}))
            } else {
                panic!("unexpected request {first}");
            };
            let body = body.to_string();
            stream
                .write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n{extra}Content-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes())
                .await
                .unwrap();
        }
    });
    Peer { api, frames, metadata_reads, task }
}
/// The mock confirms from its REST counters, independent of the socket frame,
/// so the frame is awaited rather than assumed to have arrived already.
async fn wait_for_read_write(peer: &Peer) {
    for _ in 0..100 {
        if !read_writes(peer).is_empty() {
            return;
        }
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
    }
}
fn read_writes(peer: &Peer) -> Vec<Value> {
    peer.frames
        .lock()
        .unwrap()
        .iter()
        .filter(|frame| frame["type"] == "chat_read_status_update")
        .cloned()
        .collect()
}

#[tokio::test]
async fn marking_an_unread_chat_read_waits_for_the_server_then_clears_the_cached_counter() {
    let peer = peer(vec![json!(2), json!(0)]).await;
    let mut client = client(&peer.api, false, false);
    client.chats.get_mut(ID).unwrap()["unread_count"] = json!(2);
    client.mark_chat_read(ID).await.unwrap();
    assert_eq!(client.chats[ID]["unread_count"], 0);
    wait_for_read_write(&peer).await;
    assert_eq!(read_writes(&peer)[0]["payload"], json!({"chat_id":ID,"unread_count":0}));
    assert_eq!(*peer.metadata_reads.lock().unwrap(), 2, "the write is confirmed from the server, not assumed");
}

#[tokio::test]
async fn marking_read_fails_and_keeps_the_cached_counter_when_the_server_never_confirms() {
    let peer = peer(vec![json!(2)]).await;
    let mut client = client(&peer.api, false, false);
    client.chats.get_mut(ID).unwrap()["unread_count"] = json!(2);
    assert!(client.mark_chat_read(ID).await.is_err());
    assert_eq!(client.chats[ID]["unread_count"], 2);
}

#[tokio::test]
async fn an_already_read_cached_chat_sends_nothing() {
    let mut client = client("http://127.0.0.1:9", false, false);
    client.chats.get_mut(ID).unwrap()["unread_count"] = json!(0);
    client.mark_chat_read(ID).await.unwrap();
    assert!(client.mark_chat_read("not-a-uuid").await.is_err());
}

#[tokio::test]
async fn a_cached_chat_without_a_counter_still_sends_the_read_write() {
    let peer = peer(vec![json!(0)]).await;
    let mut client = client(&peer.api, false, false);
    client.chats.get_mut(ID).unwrap()["unread_count"] = Value::Null;
    client.mark_chat_read(ID).await.unwrap();
    assert_eq!(client.chats[ID]["unread_count"], 0);
    wait_for_read_write(&peer).await;
    assert_eq!(read_writes(&peer).len(), 1);
}

#[test]
fn a_refetched_row_without_a_counter_keeps_the_cached_unread_count() {
    let mut client = client("http://127.0.0.1:9", false, false);
    client.chats.get_mut(ID).unwrap()["unread_count"] = json!(1);
    let mut omitted = json!({"id": ID, "messages_v": 2});
    client.carry_cached_unread_count(ID, &mut omitted);
    assert_eq!(omitted["unread_count"], 1);
    let mut nulled = json!({"id": ID, "unread_count": null});
    client.carry_cached_unread_count(ID, &mut nulled);
    assert_eq!(nulled["unread_count"], 1);
    let mut stated = json!({"id": ID, "unread_count": 0});
    client.carry_cached_unread_count(ID, &mut stated);
    assert_eq!(stated["unread_count"], 0, "a server-stated count always wins");
}
