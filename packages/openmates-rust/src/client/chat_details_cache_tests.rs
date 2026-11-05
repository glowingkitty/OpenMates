// contract-test-file: tooling
//! Cache-then-delta for the selected rich read against a stateful local peer:
//! a cached read equals a fresh read, merges a tail delta, and every
//! inconsistency (stale version, wrong key, corrupt record, other bounds) is a
//! miss that takes the fresh path and still returns the fresh answer.
use super::*;
use crate::client::chat_details::{ChatDetailsHistory, ChatDetailsOptions};
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const CHAT: &str = "22222222-2222-4222-8222-222222222222";

fn chat_key() -> String {
    crypto::encrypt_bytes(&[8; 32], &[1; 32]).unwrap()
}
fn message(n: i64) -> Value {
    let enc = |text: &str| crypto::encrypt_combined(text, &[1; 32]).unwrap();
    json!({"id":format!("row-{n}"),"client_message_id":format!("m{n}"),"chat_id":CHAT,
        "role":if n % 2 == 0 {"assistant"} else {"user"},"created_at":1000 + n,
        "encrypted_content":enc(&format!("text {n}")),"encrypted_sender_name":enc(""),
        "encrypted_category":enc(""),"encrypted_model_name":enc("")})
}
fn page_bytes(rows: &[Value]) -> u64 {
    rows.iter().map(|row| monitor::cached_view::bounded_bytes(row, 256 * 1024).unwrap() as u64).sum()
}
#[derive(Default)]
struct State {
    messages: Vec<Value>,
    messages_v: u64,
    embeds: Vec<Value>,
    routes: Vec<String>,
}
struct Peer {
    api: String,
    state: Arc<Mutex<State>>,
    task: tokio::task::JoinHandle<()>,
}
impl Drop for Peer {
    fn drop(&mut self) {
        self.task.abort();
    }
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
fn query(line: &str, name: &str) -> Option<String> {
    let target = line.split(' ').nth(1)?;
    let query = target.split_once('?')?.1;
    query.split('&').find_map(|pair| pair.strip_prefix(&format!("{name}=")).map(str::to_owned))
}
impl Peer {
    async fn start(messages: i64) -> Self {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let state = Arc::new(Mutex::new(State {
            messages: (1..=messages).map(message).collect(),
            messages_v: messages as u64,
            ..Default::default()
        }));
        let shared = state.clone();
        let task = tokio::spawn(async move {
            loop {
                let (mut stream, _) = listener.accept().await.unwrap();
                let state = shared.clone();
                tokio::spawn(async move {
                    let request = read_request(&mut stream).await;
                    let line = request.lines().next().unwrap().to_owned();
                    let body = {
                        let mut state = state.lock().unwrap();
                        state.routes.push(line.split(' ').take(2).collect::<Vec<_>>().join(" "));
                        if line.starts_with("POST /v1/chats/metadata/batch") {
                            let row = json!({"id":CHAT,"messages_v":state.messages_v,"chat_visibility":"private","pinned":false,
                                "encrypted_chat_key":chat_key(),"created_at":"1700000000","updated_at":"1700000201",
                                "last_edited_overall_timestamp":"1700000200",
                                "encrypted_title":crypto::encrypt_combined("Cached show",&[1;32]).unwrap(),
                                "read_details":{"created_at":1_700_000_000u64,"updated_at":1_700_000_201u64,
                                    "last_edited_overall_timestamp":1_700_000_200u64,"encrypted_follow_up_request_suggestions":null},
                                "team_id":null,"chat_key_wrappers":[],"is_sub_chat":false});
                            json!({"chats":[row]})
                        } else if line.contains(&format!("/v1/chats/{CHAT}/messages/window")) {
                            let limit: usize = query(&line, "limit").unwrap().parse().unwrap();
                            if line.contains("direction=after") {
                                let after = (
                                    query(&line, "after_timestamp").unwrap().parse::<i64>().unwrap(),
                                    query(&line, "after_message_id").unwrap(),
                                );
                                let rows: Vec<Value> = state
                                    .messages
                                    .iter()
                                    .filter(|m| (m["created_at"].as_i64().unwrap(), m["client_message_id"].as_str().unwrap().to_owned()) > after)
                                    .take(limit)
                                    .cloned()
                                    .collect();
                                json!({"chat_id":CHAT,"messages":rows,"has_more_before":true,"has_more_after":false,"payload_bytes":page_bytes(&rows)})
                            } else {
                                assert!(line.contains("direction=latest"), "{line}");
                                let skip = state.messages.len().saturating_sub(limit);
                                let rows: Vec<Value> = state.messages[skip..].to_vec();
                                let first = rows.first().cloned();
                                json!({"chat_id":CHAT,"messages":rows,"has_more_before":skip > 0,"has_more_after":false,
                                    "payload_bytes":page_bytes(&state.messages[skip..]),
                                    "start_cursor":first.map(|m| json!({"created_at":m["created_at"],"message_id":m["client_message_id"]}))})
                            }
                        } else if line.contains(&format!("/v1/embeds/chats/{CHAT}/window")) {
                            json!({"chat_id":CHAT,"embeds":state.embeds,"has_more_before":false})
                        } else {
                            panic!("unexpected request {line}");
                        }
                    }
                    .to_string();
                    let _ = stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await;
                });
            }
        });
        Self { api, state, task }
    }
    fn client(&self) -> Client {
        let mut session = crate::client::sdk_boundary_tests::session();
        session.api_url = self.api.clone();
        let mut client = Client::new(&self.api, Some(session)).unwrap();
        client.user = json!({"id":"synthetic-principal"});
        client
    }
    fn take_routes(&self) -> Vec<String> {
        std::mem::take(&mut self.state.lock().unwrap().routes)
    }
}
async fn show_with(client: &mut Client, history: ChatDetailsHistory) -> Value {
    let read = tokio::time::timeout(
        Duration::from_secs(8),
        client.read_chat_details(CHAT, ChatDetailsOptions { history, ..Default::default() }),
    )
    .await
    .unwrap()
    .unwrap();
    json!({"messages": read.messages.iter().map(|m| json!([m.client_message_id, m.content, m.created_at, m.embed_ids])).collect::<Vec<_>>(),
        "title": read.chat.title, "more": read.has_more_before})
}
async fn show(client: &mut Client, limit: usize) -> Value {
    show_with(client, ChatDetailsHistory::Latest { limit }).await
}
fn has(routes: &[String], needle: &str) -> bool {
    routes.iter().any(|r| r.contains(needle))
}

#[tokio::test]
async fn cached_show_equals_fresh_and_sends_only_tail_delta() {
    let peer = Peer::start(5).await;
    let mut client = peer.client();
    let fresh = show(&mut client, 30).await;
    assert!(has(&peer.take_routes(), "/messages/window"));
    let cached = show(&mut client, 30).await;
    assert_eq!(cached, fresh);
    let routes = peer.take_routes();
    assert_eq!(routes.len(), 3, "{routes:?}");
    let mut restored = peer.client();
    restored.restore_authenticated_ciphertext_snapshot(&client.ciphertext_snapshot()).unwrap();
    assert_eq!(show(&mut restored, 30).await, fresh);
    assert_eq!(peer.take_routes().len(), 3);
    // A smaller window is served from the same cache and equals a fresh read.
    let three = show(&mut restored, 3).await;
    let mut cold = peer.client();
    assert_eq!(three, show(&mut cold, 3).await);
}

#[tokio::test]
async fn new_message_arrives_through_the_delta_and_matches_a_fresh_read() {
    let peer = Peer::start(4).await;
    let mut client = peer.client();
    show(&mut client, 30).await;
    {
        let mut state = peer.state.lock().unwrap();
        state.messages.push(message(5));
        state.messages_v = 5;
    }
    peer.take_routes();
    let merged = show(&mut client, 30).await;
    let routes = peer.take_routes();
    assert!(!routes.iter().any(|r| r.contains("direction=latest")), "{routes:?}");
    let mut cold = peer.client();
    assert_eq!(merged, show(&mut cold, 30).await);
    assert_eq!(merged["messages"].as_array().unwrap().len(), 5);
    // The merged record is the new anchor.
    assert_eq!(show(&mut client, 30).await, merged);
}

#[tokio::test]
async fn stale_or_inconsistent_cache_falls_back_to_the_fresh_path() {
    let peer = Peer::start(4).await;
    let mut client = peer.client();
    show(&mut client, 30).await;
    // An edit bumps messages_v without a new tail message.
    peer.state.lock().unwrap().messages_v = 9;
    peer.take_routes();
    let fresh = show(&mut client, 30).await;
    let routes = peer.take_routes();
    assert_eq!(routes.len(), 4, "tail delta then the fresh window: {routes:?}");
    let mut cold = peer.client();
    assert_eq!(fresh, show(&mut cold, 30).await);
    // A cache read at other bounds (full history) is never reused.
    let mut full = peer.client();
    full.restore_authenticated_ciphertext_snapshot(&client.ciphertext_snapshot()).unwrap();
    peer.take_routes();
    let all = show_with(&mut full, ChatDetailsHistory::Full).await;
    assert_eq!(all["messages"].as_array().unwrap().len(), 4);
    assert!(peer.take_routes().iter().any(|r| r.contains("/messages/window")));
    // Larger window than a truncated cache holds: a miss, not a short answer.
    let peer2 = Peer::start(6).await;
    let mut small = peer2.client();
    assert_eq!(show(&mut small, 2).await["messages"].as_array().unwrap().len(), 2);
    assert_eq!(show(&mut small, 5).await["messages"].as_array().unwrap().len(), 5);
}

#[tokio::test]
async fn corrupt_or_wrongly_keyed_cache_is_a_miss_with_the_fresh_answer() {
    let peer = Peer::start(3).await;
    let mut client = peer.client();
    let fresh = show(&mut client, 30).await;
    let snapshot = client.ciphertext_snapshot();
    let record = snapshot[SNAPSHOT_FIELD][CHAT].clone();
    let corruptions: Vec<Box<dyn Fn(&mut Value)>> = vec![
        Box::new(|r| r["rows"][1]["encrypted_content"] = json!("not-ciphertext")),
        Box::new(|r| r["rows"][2]["created_at"] = json!(5)),
        Box::new(|r| r["rows"].as_array_mut().unwrap().swap(0, 2)),
        Box::new(|r| r["version"] = json!(2)),
        Box::new(|r| r["messages_v"] = json!(99)),
    ];
    for corrupt in corruptions {
        let mut broken = snapshot.clone();
        corrupt(&mut broken[SNAPSHOT_FIELD][CHAT]);
        let mut restored = peer.client();
        restored.restore_authenticated_ciphertext_snapshot(&broken).unwrap();
        assert_eq!(show(&mut restored, 30).await, fresh);
    }
    let mut unrelated = snapshot.clone();
    unrelated[SNAPSHOT_FIELD] = json!({"not-a-chat-id": record});
    let mut restored = peer.client();
    restored.restore_authenticated_ciphertext_snapshot(&unrelated).unwrap();
    assert!(restored.chat_details_cache.is_empty());
}

#[tokio::test]
async fn embed_inventory_is_reused_only_while_the_first_page_is_unchanged() {
    let peer = Peer::start(3).await;
    peer.state.lock().unwrap().embeds = vec![json!({"embed_id":"e1","hashed_message_id":sha256("m2"),"hashed_chat_id":sha256(CHAT)})];
    let mut client = peer.client();
    let fresh = show(&mut client, 30).await;
    assert_eq!(fresh["messages"][1][3], json!(["e1"]));
    assert_eq!(show(&mut client, 30).await, fresh);
    peer.state.lock().unwrap().embeds.push(json!({"embed_id":"e2","hashed_message_id":sha256("m3"),"hashed_chat_id":sha256(CHAT)}));
    let changed = show(&mut client, 30).await;
    assert_eq!(changed["messages"][2][3], json!(["e2"]));
    let mut cold = peer.client();
    assert_eq!(changed, show(&mut cold, 30).await);
}

async fn routes_reach(peer: &Peer, count: usize) {
    tokio::time::timeout(Duration::from_secs(8), async {
        while peer.state.lock().unwrap().routes.len() < count {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
}
fn latest(limit: usize) -> ChatDetailsOptions {
    ChatDetailsOptions { history: ChatDetailsHistory::Latest { limit }, ..Default::default() }
}

#[tokio::test]
async fn overlapped_round_is_consumed_once_and_costs_no_second_request() {
    let peer = Peer::start(5).await;
    let mut client = peer.client();
    let fresh = show(&mut client, 30).await;
    peer.take_routes();
    client.prefetch_chat_details(CHAT, &latest(30));
    assert!(client.chat_details_overlap.is_some());
    routes_reach(&peer, 3).await;
    // The command's admission and recovery discovery would run here.
    assert_eq!(show(&mut client, 30).await, fresh);
    assert!(client.chat_details_overlap.is_none());
    assert_eq!(peer.take_routes().len(), 3, "only the overlapped round");
    // Without a new prefetch the next read sends its own round.
    assert_eq!(show(&mut client, 30).await, fresh);
    assert_eq!(peer.take_routes().len(), 3);
}

#[tokio::test]
async fn overlapped_round_for_another_context_or_after_discard_is_never_used() {
    let peer = Peer::start(4).await;
    let mut client = peer.client();
    let fresh = show(&mut client, 30).await;
    // Other bounds (full history): the request paths differ, so the round is discarded.
    peer.take_routes();
    client.prefetch_chat_details(CHAT, &latest(30));
    routes_reach(&peer, 3).await;
    assert_eq!(show_with(&mut client, ChatDetailsHistory::Full).await["messages"].as_array().unwrap().len(), 4);
    assert_eq!(peer.take_routes().len(), 6, "discarded round plus a fresh round");
    // Another session owner never consumes it.
    client.prefetch_chat_details(CHAT, &latest(30));
    routes_reach(&peer, 3).await;
    client.session.as_mut().unwrap().hashed_email = "another-owner".into();
    let other = client.read_chat_details(CHAT, latest(30)).await;
    assert!(other.is_ok(), "{:?}", other.err());
    assert!(client.chat_details_overlap.is_none());
    assert_eq!(peer.take_routes().len(), 6);
    // Recovery work discards it before the read.
    let mut client = peer.client();
    show(&mut client, 30).await;
    peer.take_routes();
    client.prefetch_chat_details(CHAT, &latest(30));
    routes_reach(&peer, 3).await;
    client.discard_chat_details_prefetch();
    assert_eq!(show(&mut client, 30).await, fresh);
    assert_eq!(peer.take_routes().len(), 6);
    // An invalid limit sends nothing.
    client.prefetch_chat_details(CHAT, &latest(0));
    assert!(client.chat_details_overlap.is_none());
}
