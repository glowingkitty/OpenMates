// contract-test-file: tooling
//! Real-Client selected rich read against a local HTTP peer: the three first
//! requests are in flight together, and an unchanged server row keeps the
//! cached Chat list fresh while a real server change still invalidates it.
use super::*;
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU64, AtomicUsize, Ordering},
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
const OTHER: &str = "33333333-3333-4333-8333-333333333333";

fn chat_key() -> String {
    crypto::encrypt_bytes(&[8; 32], &[1; 32]).unwrap()
}
/// Canonical sync-shaped cached row (numeric clocks, no read projection).
fn cached_row(id: &str, key: &str, title: &str) -> Value {
    json!({"id":id,"messages_v":3,"chat_visibility":"private","pinned":false,
        "encrypted_chat_key":key,"created_at":1_700_000_000u64,"updated_at":1_700_000_201u64,
        "last_edited_overall_timestamp":1_700_000_200u64,
        "encrypted_title":crypto::encrypt_combined(title,&[8;32]).unwrap()})
}
/// The HTTP watch projection: stringified clocks, extra fields, read_details.
fn server_row(cached: &Value) -> Value {
    let mut row = cached.clone();
    for field in ["created_at", "updated_at", "last_edited_overall_timestamp"] {
        row[field] = json!(cached[field].to_string());
    }
    row["read_details"] = json!({"created_at":cached["created_at"],"updated_at":cached["updated_at"],
        "last_edited_overall_timestamp":cached["last_edited_overall_timestamp"],
        "encrypted_follow_up_request_suggestions":null});
    row["team_id"] = Value::Null;
    row["chat_key_wrappers"] = json!([]);
    row["is_sub_chat"] = json!(false);
    row
}

struct Peer {
    api: String,
    metadata: Arc<Mutex<Value>>,
    arrivals: Arc<AtomicUsize>,
    order: Arc<Mutex<Vec<String>>>,
    task: tokio::task::JoinHandle<()>,
}
async fn read_request(stream: &mut tokio::net::TcpStream) -> String {
    let mut data = vec![];
    loop {
        let mut part = [0; 4096];
        let n = stream.read(&mut part).await.unwrap();
        assert!(n > 0 && data.len() + n < 16384);
        data.extend_from_slice(&part[..n]);
        if let Some(end) = data.windows(4).position(|v| v == b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&data[..end]).to_ascii_lowercase();
            let length = headers
                .lines()
                .find_map(|line| line.strip_prefix("content-length:").map(|n| n.trim().parse::<usize>().unwrap()))
                .unwrap_or(0);
            if data.len() == end + 4 + length {
                return String::from_utf8(data).unwrap();
            }
        }
    }
}
impl Peer {
    /// Every response waits until all three first requests have arrived, so a
    /// sequential client can never complete (it times out with 503 instead).
    async fn start(metadata: Value) -> Self {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let metadata = Arc::new(Mutex::new(metadata));
        let arrivals = Arc::new(AtomicUsize::new(0));
        let order = Arc::new(Mutex::new(Vec::new()));
        let all_arrived = Arc::new(tokio::sync::Notify::new());
        let (m, a, o) = (metadata.clone(), arrivals.clone(), order.clone());
        let task = tokio::spawn(async move {
            loop {
                let (mut stream, _) = listener.accept().await.unwrap();
                let (m, a, o, all) = (m.clone(), a.clone(), o.clone(), all_arrived.clone());
                tokio::spawn(async move {
                    let request = read_request(&mut stream).await;
                    let line = request.lines().next().unwrap().to_owned();
                    let route = line.split(' ').take(2).collect::<Vec<_>>().join(" ");
                    let route = route.split('?').next().unwrap().to_owned();
                    o.lock().unwrap().push(route.clone());
                    let waiting = all.notified();
                    tokio::pin!(waiting);
                    waiting.as_mut().enable();
                    if a.fetch_add(1, Ordering::SeqCst) % 3 == 2 {
                        all.notify_waiters();
                    } else if tokio::time::timeout(Duration::from_secs(3), waiting).await.is_err() {
                        let _ = stream.write_all(b"HTTP/1.1 503 Sequential\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await;
                        return;
                    }
                    let body = if route.starts_with("POST /v1/chats/metadata/batch") {
                        assert!(request.contains("\"include_read_details\":true"));
                        json!({"chats":[m.lock().unwrap().clone()]})
                    } else if route.starts_with(&format!("GET /v1/chats/{CHAT}/messages/window")) {
                        assert!(line.contains("direction=latest"));
                        json!({"chat_id":CHAT,"messages":[],"has_more_before":false,"payload_bytes":0})
                    } else if route.starts_with(&format!("GET /v1/embeds/chats/{CHAT}/window")) {
                        json!({"chat_id":CHAT,"embeds":[],"has_more_before":false})
                    } else {
                        panic!("unexpected request {line}");
                    }
                    .to_string();
                    let _ = stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await;
                });
            }
        });
        Self { api, metadata, arrivals, order, task }
    }
    fn client(&self, ticks: &Arc<AtomicU64>, key: &str, selected: &Value) -> Client {
        let mut session = crate::client::sdk_boundary_tests::session();
        session.api_url = self.api.clone();
        let mut client = Client::new(&self.api, Some(session)).unwrap();
        client.user = json!({"id":"synthetic-principal"});
        let ticks = ticks.clone();
        client.set_chat_cache_clock_provider(Some(Arc::new(move || {
            CacheClockEvidence::from_platform("boot".into(), ticks.load(Ordering::SeqCst), ticks.load(Ordering::SeqCst))
        })));
        client.insert_chat_row(CHAT.into(), selected.clone());
        client.insert_chat_row(OTHER.into(), cached_row(OTHER, key, "Synthetic other"));
        client.record_complete_chat_list_at(Some(&CacheClockEvidence::from_platform("boot".into(), 1_000, 1_000).unwrap()));
        assert!(client.try_cached_default_chat_list(false).unwrap().is_some());
        client
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        self.task.abort();
    }
}

#[tokio::test]
async fn show_issues_metadata_messages_and_embeds_concurrently_then_list_stays_cached() {
    let key = chat_key();
    let selected = cached_row(CHAT, &key, "Synthetic selected");
    let peer = Peer::start(server_row(&selected)).await;
    let ticks = Arc::new(AtomicU64::new(1_100));
    let mut client = peer.client(&ticks, &key, &selected);
    let before = client.ciphertext_snapshot();
    let read = tokio::time::timeout(
        Duration::from_secs(8),
        client.read_chat_details(CHAT, ChatDetailsOptions::default()),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(read.chat.title.as_deref(), Some("Synthetic selected"));
    assert_eq!(peer.arrivals.load(Ordering::SeqCst), 3);
    let mut routes = peer.order.lock().unwrap().clone();
    routes.sort();
    assert_eq!(
        routes,
        vec![
            format!("GET /v1/chats/{CHAT}/messages/window"),
            format!("GET /v1/embeds/chats/{CHAT}/window"),
            "POST /v1/chats/metadata/batch".to_owned(),
        ]
    );
    // The canonical row is retained byte-for-byte; the HTTP projection with
    // stringified clocks never reorders the cached list.
    assert_eq!(client.chats[CHAT], before["chats"][CHAT]);
    let items = client.try_cached_default_chat_list(false).unwrap().expect("cache hit after show");
    assert_eq!(items.len(), 2);
    // The persisted receipt survives the same-boot restart path too.
    let snapshot = client.ciphertext_snapshot();
    let mut restored = peer.client(&ticks, &key, &selected);
    restored.restore_authenticated_ciphertext_snapshot(&snapshot).unwrap();
    assert!(restored.try_cached_default_chat_list(false).unwrap().is_some());
    // No TTL renewal from the read: the original receipt still expires.
    ticks.store(301_000, Ordering::SeqCst);
    assert!(client.try_cached_default_chat_list(false).unwrap().is_none());
}

#[tokio::test]
async fn show_observing_a_real_server_change_invalidates_the_cached_list() {
    let key = chat_key();
    let mut changed = cached_row(CHAT, &key, "Renamed on another device");
    changed["messages_v"] = json!(4);
    changed["last_edited_overall_timestamp"] = json!(1_700_000_300u64);
    let peer = Peer::start(server_row(&changed)).await;
    let ticks = Arc::new(AtomicU64::new(1_100));
    let unchanged = cached_row(CHAT, &key, "Synthetic selected");
    let mut client = peer.client(&ticks, &key, &unchanged);
    let read = tokio::time::timeout(
        Duration::from_secs(8),
        client.read_chat_details(CHAT, ChatDetailsOptions::default()),
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(read.chat.title.as_deref(), Some("Renamed on another device"));
    assert!(client.chats[CHAT].get("read_details").is_some(), "changed row replaces as before");
    assert!(client.try_cached_default_chat_list(false).unwrap().is_none());
    // A clock-only difference (canonical read_details) also counts as a change.
    let mut moved = server_row(&unchanged);
    moved["read_details"]["last_edited_overall_timestamp"] = json!(1_700_000_999u64);
    *peer.metadata.lock().unwrap() = moved;
    let mut client = peer.client(&ticks, &key, &unchanged);
    client.read_chat_details(CHAT, ChatDetailsOptions::default()).await.unwrap();
    assert!(client.try_cached_default_chat_list(false).unwrap().is_none());
}

#[test]
fn list_equivalence_compares_rendered_output_key_versions_drafts_and_canonical_clocks() {
    let key = chat_key();
    let mut session = crate::client::sdk_boundary_tests::session();
    session.api_url = "http://127.0.0.1:9".into();
    let client = Client::new("http://127.0.0.1:9", Some(session)).unwrap();
    let equivalent = |cached: &Value, server: &Value| {
        client.selected_row_list_equivalent(cached, server, &[8; 32]).unwrap()
    };
    let cached = cached_row(CHAT, &key, "Synthetic");
    let server = server_row(&cached);
    assert!(equivalent(&cached, &server));
    // Re-encrypted identical plaintext renders the same list output.
    let mut reencrypted = server.clone();
    reencrypted["encrypted_title"] = json!(crypto::encrypt_combined("Synthetic", &[8; 32]).unwrap());
    assert!(equivalent(&cached, &reencrypted));
    let mut without_details = server.clone();
    without_details.as_object_mut().unwrap().remove("read_details");
    assert!(!equivalent(&cached, &without_details));
    for (field, value) in [
        ("encrypted_title", json!(crypto::encrypt_combined("Renamed", &[8; 32]).unwrap())),
        ("encrypted_title", json!("undecryptable")),
        ("encrypted_chat_key", json!(crypto::encrypt_bytes(&[8; 32], &[1; 32]).unwrap())),
        ("messages_v", json!(9)),
        ("pinned", json!(true)),
        ("encrypted_draft_md", json!("draft")),
        ("draft_v", json!(2)),
        ("chat_visibility", json!("direct")),
    ] {
        let mut changed = server.clone();
        changed[field] = value;
        assert!(!equivalent(&cached, &changed), "{field}");
    }
    let mut missing_clock = server.clone();
    missing_clock["read_details"].as_object_mut().unwrap().remove("updated_at");
    assert!(!equivalent(&cached, &missing_clock));
    let mut moved = server.clone();
    moved["read_details"]["last_edited_overall_timestamp"] = json!(1_700_000_999u64);
    assert!(!equivalent(&cached, &moved));
    let mut string_clock_only = cached.clone();
    string_clock_only["created_at"] = json!("1700000000");
    assert!(!equivalent(&string_clock_only, &server));
}
