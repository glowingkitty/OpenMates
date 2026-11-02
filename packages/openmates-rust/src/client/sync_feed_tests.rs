//! Incremental chat sync feed client (architecture.sync@2): page application,
//! cold-start adoption, persistence scoping and the WebSocket protocol.
use super::*;
use futures_util::{SinkExt, StreamExt};
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const A: &str = "11111111-1111-4111-8111-111111111111";
const B: &str = "22222222-2222-4222-8222-222222222222";
const C: &str = "33333333-3333-4333-8333-333333333333";

fn row(id: &str, messages_v: i64, edited: i64) -> Value {
    json!({"id":id,"encrypted_title":"cipher","encrypted_chat_key":"wrapped","messages_v":messages_v,"title_v":1,"metadata_v":1,"last_edited_overall_timestamp":edited,"updated_at":edited,"pinned":false})
}

fn client_at(api: &str) -> Client {
    let mut session = crate::client::sdk_boundary_tests::session();
    session.api_url = api.into();
    session.cookies.insert("auth_refresh_token".into(), "synthetic-cookie".into());
    let mut client = Client::new(api, Some(session)).unwrap();
    client.user = json!({"id":"synthetic-owner"});
    client
}

fn seeded() -> Client {
    let mut client = client_at("https://api.example.test");
    for (id, edited) in [(A, 10), (B, 20)] {
        client.chats.insert(id.into(), row(id, 1, edited));
    }
    client.chat_arrival_order = Some(vec![A.into(), B.into()]);
    client.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
    client
}

fn page(changes: Value, next: &str) -> Value {
    json!({"reset":false,"has_more":false,"next_cursor":next,"changes":changes,"overview":null,"team_id":null})
}

// contract-test: direct surface=sdks.rust assertions=sync.delta.cursor-gap-free,sync.delta.metadata-only
#[test]
fn pages_apply_idempotently_with_version_guards() {
    let mut client = seeded();
    let update = page(json!([
        {"chat_id":A,"hashed_chat_id":super::hashed(A),"kinds":["messages","metadata"],"chat_details":row(A, 3, 99),
         "chat_key_wrappers":[{"id":"w1","hashed_chat_id":super::hashed(A),"encrypted_chat_key":"wrap"}]},
        {"chat_id":C,"hashed_chat_id":super::hashed(C),"kinds":["metadata"],"chat_details":row(C, 1, 5)},
    ]), "e1:9|e2:1");
    assert_eq!(client.apply_chat_sync_page(&update).unwrap(), 2);
    let snapshot = client.clone_for_assert();
    // Replaying the same page changes nothing (at-least-once delivery).
    client.apply_chat_sync_page(&update).unwrap();
    assert_eq!(client.clone_for_assert(), snapshot);
    assert_eq!(client.chats[A]["messages_v"], 3);
    assert_eq!(client.chat_arrival_order.as_ref().unwrap(), &vec![A.to_string(), B.into(), C.into()]);
    assert_eq!(client.wrappers.len(), 1);
    assert_eq!(client.chat_sync_feed.cursor.as_deref(), Some("e1:9|e2:1"));
    // An older replayed row never overwrites newer cached state.
    client.apply_chat_sync_page(&page(json!([{"chat_id":A,"hashed_chat_id":super::hashed(A),"kinds":["metadata"],"chat_details":row(A, 2, 50)}]), "e1:10|e2:1")).unwrap();
    assert_eq!(client.chats[A]["messages_v"], 3);
}

// contract-test: direct surface=sdks.rust assertions=sync.deletion.partial-window-not-authoritative,sync.delta.scope-revocation
#[test]
fn hash_only_removals_prune_only_the_named_chat() {
    let mut client = seeded();
    client.history.insert(B.into(), vec![json!({"id":"m"})]);
    let removal = page(json!([
        {"hashed_chat_id":super::hashed(B),"kinds":["deleted"]},
        {"hashed_chat_id":super::hashed("unknown"),"kinds":["revoked"]},
        {"hashed_chat_id":super::hashed(A),"kinds":["metadata"]},
    ]), "e1:6|e2:1");
    client.apply_chat_sync_page(&removal).unwrap();
    assert!(client.chats.contains_key(A) && !client.chats.contains_key(B));
    assert!(!client.history.contains_key(B));
    assert_eq!(client.chat_arrival_order.as_ref().unwrap(), &vec![A.to_string()]);
}

// contract-test: direct surface=sdks.rust assertions=sync.phase2.drafts.authoritative-encrypted
#[test]
fn draft_entries_create_update_and_remove_draft_only_chats() {
    let mut client = seeded();
    let draft = |version: i64, md: Option<&str>| json!({"draft_v":version,"encrypted_draft_md":md,"encrypted_draft_preview":null});
    client.apply_chat_sync_page(&page(json!([{"chat_id":C,"hashed_chat_id":super::hashed(C),"kinds":["draft"],"draft":draft(2, Some("cipher-draft"))}]), "e1:6|e2:2")).unwrap();
    assert!(super::super::sync::draft_only(&client.chats[C]));
    client.apply_chat_sync_page(&page(json!([{"chat_id":A,"hashed_chat_id":super::hashed(A),"kinds":["draft"],"draft":draft(4, Some("cipher-a"))}]), "e1:6|e2:3")).unwrap();
    assert_eq!(client.chats[A]["encrypted_draft_md"], "cipher-a");
    client.apply_chat_sync_page(&page(json!([
        {"chat_id":C,"hashed_chat_id":super::hashed(C),"kinds":["draft"],"draft":draft(0, None)},
        {"chat_id":A,"hashed_chat_id":super::hashed(A),"kinds":["draft"],"draft":draft(0, None)},
    ]), "e1:6|e2:4")).unwrap();
    assert!(!client.chats.contains_key(C), "draft-only chat removed with its draft");
    assert_eq!(client.chats[A]["draft_v"], 0);
    assert!(client.chats[A]["encrypted_draft_md"].is_null());
}

// contract-test: direct surface=sdks.rust assertions=sync.startup.bounded-phases,sync.overview.cross-device
#[test]
fn cold_start_capture_and_snapshot_stay_in_their_context() {
    let mut client = client_at("https://api.example.test");
    let mut capture = ColdStartCapture::default();
    observe_cold_start("chat_overview_priority_ready", &json!({"team_id":null,"last_opened_chat_id":A,
        "due_soon":{"reminders":[{"reminder_id":"r","prompt_preview":"private text","trigger_at":1,"status":"pending","target_type":"existing_chat","target_chat_id":A}],
        "saved_items":[{"id":"m","encrypted_item_json":"cipher"}],"generated_at":7}}), None, &mut capture);
    observe_cold_start("phased_sync_complete", &json!({"team_id":"other-team","sync_cursor":"x:1|y:1"}), None, &mut capture);
    observe_cold_start("phased_sync_complete", &json!({"team_id":null,"sync_cursor":"e1:3|e2:4"}), None, &mut capture);
    client.adopt_cold_start_feed(capture).unwrap();
    assert!(client.has_chat_sync_cursor());
    let snapshot = client.ciphertext_snapshot();
    let feed = &snapshot[SNAPSHOT_FIELD];
    assert_eq!(feed["cursor"], "e1:3|e2:4");
    assert!(!feed.to_string().contains("private text"), "reminder previews are never persisted");
    assert!(crate::client::snapshot_sections::index_fields().contains(&SNAPSHOT_FIELD));
    let mut restored = client_at("https://api.example.test");
    restored.restore_ciphertext_snapshot(&snapshot).unwrap();
    assert_eq!(restored.chat_sync_feed, client.chat_sync_feed);
    // Another context never adopts this cursor.
    let mut team_snapshot = snapshot.clone();
    team_snapshot[SNAPSHOT_FIELD]["team"] = json!("some-team");
    restored.restore_ciphertext_snapshot(&team_snapshot).unwrap();
    assert!(!restored.has_chat_sync_cursor());
    // A cold start without a cursor leaves no replay authority.
    restored.adopt_cold_start_feed(ColdStartCapture::default()).unwrap();
    assert!(!restored.has_chat_sync_cursor());
}

// contract-test: direct surface=sdks.rust assertions=sync.overview.priority-order
#[test]
fn list_order_and_overview_follow_the_overview_comparator() {
    let mut client = seeded();
    client.chats.insert(C.into(), json!({"id":C,"pinned":true,"last_edited_overall_timestamp":1,"encrypted_chat_key":"k"}));
    client.chat_arrival_order.as_mut().unwrap().push(C.into());
    client.chat_sync_feed.last_opened_chat_id = Some(A.into());
    let now = 1_800_000_000_000;
    client.chat_sync_feed.reminders = vec![super::super::overview::ReminderInput {
        reminder_id: "r".into(), trigger_at: now / 1000 + 600, status: "pending".into(),
        target_type: "existing_chat".into(), target_chat_id: Some(B.into()), target_embed_id: None,
    }];
    let items = [A, B, C].map(|id| Item { id: id.into(), ..Item::default() }).to_vec();
    let ordered: Vec<String> = client.order_chat_list_items(items, now, 0).into_iter().map(|i| i.id).collect();
    assert_eq!(ordered, [B, A, C]);
    let overview = client.workspace_overview(now, 0, &[]);
    assert!(matches!(&overview.entries[0], OverviewEntry::DueChat { chat_id, .. } if chat_id == B));
    assert!(matches!(&overview.entries[1], OverviewEntry::LastOpenedChat { chat_id } if chat_id == A));
}

impl Client {
    fn clone_for_assert(&self) -> (BTreeMap<String, Value>, Option<Vec<String>>, Vec<Value>, Option<String>) {
        (self.chats.clone(), self.chat_arrival_order.clone(), self.wrappers.clone(), self.chat_sync_feed.cursor.clone())
    }
}

async fn http_request(stream: &mut tokio::net::TcpStream) -> String {
    let mut data = vec![];
    loop {
        let mut buf = [0; 4096];
        let n = stream.read(&mut buf).await.unwrap();
        assert!(n > 0);
        data.extend_from_slice(&buf[..n]);
        if let Some(end) = data.windows(4).position(|v| v == b"\r\n\r\n") {
            let headers = String::from_utf8_lossy(&data[..end]).to_ascii_lowercase();
            let len = headers.lines().find_map(|l| l.strip_prefix("content-length:").map(|v| v.trim().parse::<usize>().unwrap())).unwrap_or(0);
            if data.len() == end + 4 + len {
                return String::from_utf8(data).unwrap();
            }
        }
    }
}

/// Fake server: session auth, then one WebSocket answering delta requests from `replies`.
async fn feed_peer(replies: Vec<Value>) -> (String, Arc<Mutex<Vec<Value>>>, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let seen = Arc::new(Mutex::new(Vec::new()));
    let log = seen.clone();
    let task = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        assert!(http_request(&mut stream).await.starts_with("POST /v1/auth/session "));
        let body = json!({"success":true,"ws_token":"synthetic","user":{"id":"synthetic-owner"}}).to_string();
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
        drop(stream);
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_hdr_async(stream, |req: &tokio_tungstenite::tungstenite::handshake::server::Request, response| {
            let query = url::form_urlencoded::parse(req.uri().query().unwrap().as_bytes()).collect::<BTreeMap<_, _>>();
            assert!(query["client_capabilities"].split(',').any(|c| c == CAPABILITY));
            Ok(response)
        }).await.unwrap();
        let mut replies = replies.into_iter();
        while let Some(Ok(frame)) = ws.next().await {
            let Ok(raw) = frame.to_text() else { continue };
            let Ok(frame) = serde_json::from_str::<Value>(raw) else { continue };
            if frame["type"] != "chat_sync_delta_request" {
                continue;
            }
            log.lock().unwrap().push(frame["payload"].clone());
            let Some(mut reply) = replies.next() else { break };
            reply["payload"]["context_epoch"] = frame["payload"]["context_epoch"].clone();
            // An unrelated frame first: correlation must skip it.
            ws.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":"server_capabilities","payload":{}}).to_string().into())).await.unwrap();
            ws.send(tokio_tungstenite::tungstenite::Message::Text(reply.to_string().into())).await.unwrap();
        }
    });
    (api, seen, task)
}

// contract-test: direct surface=sdks.rust assertions=sync.delta.cursor-gap-free,sync.delta.live-hint
#[tokio::test]
async fn catch_up_pages_until_has_more_is_false() {
    let first = json!({"type":"chat_sync_delta","payload":{"reset":false,"has_more":true,"next_cursor":"e1:7|e2:1","team_id":null,
        "changes":[{"chat_id":C,"hashed_chat_id":super::hashed(C),"kinds":["metadata"],"chat_details":row(C, 1, 30)}]}});
    let second = json!({"type":"chat_sync_delta","payload":{"reset":false,"has_more":false,"next_cursor":"e1:8|e2:2","team_id":null,
        "changes":[{"hashed_chat_id":super::hashed(A),"kinds":["deleted"]}],"overview":{"last_opened_chat_id":B}}});
    let (api, seen, task) = feed_peer(vec![first, second]).await;
    let mut client = client_at(&api);
    client.chats.insert(A.into(), row(A, 1, 10));
    client.chat_arrival_order = Some(vec![A.into()]);
    client.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
    let outcome = client.catch_up_chat_sync_feed().await.unwrap();
    assert_eq!(outcome, FeedCatchUp::Applied { pages: 2, changes: 2 });
    let requests = seen.lock().unwrap().clone();
    assert_eq!(requests.iter().map(|r| r["cursor"].clone()).collect::<Vec<_>>(), [json!("e1:5|e2:1"), json!("e1:7|e2:1")]);
    assert!(requests.iter().all(|r| r["limit"] == 200 && r.get("team_id").is_none()));
    assert!(client.chats.contains_key(C) && !client.chats.contains_key(A));
    assert_eq!(client.chat_sync_feed.last_opened_chat_id.as_deref(), Some(B));
    assert_eq!(client.chat_sync_feed.cursor.as_deref(), Some("e1:8|e2:2"));
    task.abort();
}

// contract-test: direct surface=sdks.rust assertions=sync.delta.reset
#[tokio::test]
async fn reset_discards_the_cursor_without_pruning() {
    let reset = json!({"type":"chat_sync_delta","payload":{"reset":true,"has_more":false,"next_cursor":null,"changes":[],"team_id":null}});
    let (api, _, task) = feed_peer(vec![reset]).await;
    let mut client = client_at(&api);
    client.chats.insert(A.into(), row(A, 1, 10));
    client.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
    assert_eq!(client.catch_up_chat_sync_feed().await.unwrap(), FeedCatchUp::ColdStartRequired);
    assert!(!client.has_chat_sync_cursor() && client.chats.contains_key(A));
    // Without a cursor no socket is opened at all.
    assert_eq!(client.catch_up_chat_sync_feed().await.unwrap(), FeedCatchUp::ColdStartRequired);
    task.abort();
}

// contract-test: direct surface=sdks.rust assertions=sync.delta.scope-revocation
#[tokio::test]
async fn deferred_feed_falls_back_and_keeps_state() {
    let deferred = json!({"type":"chat_sync_delta_error","payload":{"code":"sync_deferred","team_id":null}});
    let (api, _, task) = feed_peer(vec![deferred]).await;
    let mut client = client_at(&api);
    client.chats.insert(A.into(), row(A, 1, 10));
    client.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
    assert_eq!(client.catch_up_chat_sync_feed().await.unwrap(), FeedCatchUp::Unavailable);
    assert!(client.has_chat_sync_cursor() && client.chats.contains_key(A));
    task.abort();
}
