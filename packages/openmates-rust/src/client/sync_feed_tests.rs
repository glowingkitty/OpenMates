//! Incremental chat sync feed client (architecture.sync@2): page application,
//! cold-start adoption, persistence scoping and the WebSocket protocol.
use super::*;
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

/// Fake HTTP server: records each request line and answers `replies` in order
/// (`(status, body)`), keeping the connection open between requests.
async fn feed_peer(replies: Vec<(u16, Value)>) -> (String, Arc<Mutex<Vec<String>>>, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let seen = Arc::new(Mutex::new(Vec::new()));
    let log = seen.clone();
    let task = tokio::spawn(async move {
        let mut replies = replies.into_iter();
        loop {
            let (mut stream, _) = listener.accept().await.unwrap();
            loop {
                let mut data = vec![];
                let mut buf = [0; 4096];
                let ok = loop {
                    let Ok(n) = stream.read(&mut buf).await else { break false };
                    if n == 0 { break false }
                    data.extend_from_slice(&buf[..n]);
                    if data.windows(4).any(|w| w == b"\r\n\r\n") { break true }
                };
                if !ok { break }
                let request = String::from_utf8(data).unwrap();
                log.lock().unwrap().push(request.lines().next().unwrap().to_owned());
                assert!(request.to_ascii_lowercase().contains("cookie:"), "session cookie attached");
                let Some((status, body)) = replies.next() else { return };
                let body = body.to_string();
                stream.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
            }
        }
    });
    (api, seen, task)
}

fn delta(has_more: bool, next: &str, changes: Value, overview: Value) -> (u16, Value) {
    (200, json!({"reset":false,"has_more":has_more,"next_cursor":next,"changes":changes,"overview":overview,"team_id":null}))
}

// contract-test: direct surface=sdks.rust assertions=sync.delta.cursor-gap-free,sync.delta.live-hint
#[tokio::test]
async fn catch_up_pages_until_has_more_is_false_over_one_connection() {
    let first = delta(true, "e1:7|e2:1", json!([{"chat_id":C,"hashed_chat_id":super::hashed(C),"kinds":["metadata"],"chat_details":row(C, 1, 30)}]), Value::Null);
    let second = delta(false, "e1:8|e2:2", json!([{"hashed_chat_id":super::hashed(A),"kinds":["deleted"]}]), json!({"last_opened_chat_id":B}));
    let (api, seen, task) = feed_peer(vec![first, second]).await;
    let mut client = client_at(&api);
    client.chats.insert(A.into(), row(A, 1, 10));
    client.chat_arrival_order = Some(vec![A.into()]);
    client.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
    let outcome = client.catch_up_chat_sync_feed().await.unwrap();
    assert_eq!(outcome, FeedCatchUp::Applied { pages: 2, changes: 2 });
    let requests = seen.lock().unwrap().clone();
    assert_eq!(requests.len(), 2, "no session validation or socket handshake in between: {requests:?}");
    assert!(requests[0].starts_with("GET /v1/chats/changes?cursor=e1%3A5%7Ce2%3A1&limit=200 "), "{}", requests[0]);
    assert!(requests[1].contains("cursor=e1%3A7%7Ce2%3A1"));
    assert!(client.chats.contains_key(C) && !client.chats.contains_key(A));
    assert_eq!(client.chat_sync_feed.last_opened_chat_id.as_deref(), Some(B));
    assert_eq!(client.chat_sync_feed.cursor.as_deref(), Some("e1:8|e2:2"));
    task.abort();
}

// contract-test: direct surface=sdks.rust assertions=sync.delta.reset
#[tokio::test]
async fn reset_discards_the_cursor_without_pruning() {
    let reset = (200, json!({"reset":true,"has_more":false,"next_cursor":null,"changes":[],"team_id":null}));
    let (api, _, task) = feed_peer(vec![reset]).await;
    let mut client = client_at(&api);
    client.chats.insert(A.into(), row(A, 1, 10));
    client.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
    assert_eq!(client.catch_up_chat_sync_feed().await.unwrap(), FeedCatchUp::ColdStartRequired);
    assert!(!client.has_chat_sync_cursor() && client.chats.contains_key(A));
    // Without a cursor no request is made at all.
    assert_eq!(client.catch_up_chat_sync_feed().await.unwrap(), FeedCatchUp::ColdStartRequired);
    task.abort();
}

// contract-test: direct surface=sdks.rust assertions=sync.delta.scope-revocation
#[tokio::test]
async fn deferral_and_rate_limit_fall_back_and_keep_state() {
    for status in [429u16, 503] {
        let (api, _, task) = feed_peer(vec![(status, json!({"detail":"sync_deferred"}))]).await;
        let mut client = client_at(&api);
        client.chats.insert(A.into(), row(A, 1, 10));
        client.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
        assert_eq!(client.catch_up_chat_sync_feed().await.unwrap(), FeedCatchUp::Unavailable, "{status}");
        assert!(client.has_chat_sync_cursor() && client.chats.contains_key(A));
        task.abort();
    }
}

// contract-test: direct surface=sdks.rust assertions=sync.delta.scope-revocation
#[tokio::test]
async fn revoked_team_prunes_only_that_context_and_keeps_the_error() {
    let (api, seen, task) = feed_peer(vec![(403, json!({"detail":"team_access_revoked"}))]).await;
    let team = "44444444-4444-4444-8444-444444444444";
    let mut client = client_at(&api);
    client.set_team(Some(team)).unwrap();
    for (id, edited) in [(A, 10), (B, 20)] {
        client.chats.insert(id.into(), row(id, 1, edited));
    }
    client.chat_arrival_order = Some(vec![A.into(), B.into()]);
    client.wrappers.push(json!({"id":"w","hashed_chat_id":super::hashed(A)}));
    client.chat_sync_feed.team = Some(team.into());
    client.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
    client.chat_sync_feed.last_opened_chat_id = Some(A.into());
    let error = client.catch_up_chat_sync_feed().await.unwrap_err();
    assert_eq!(error, Error::Forbidden);
    assert!(client.chats.is_empty() && client.wrappers.is_empty() && client.chat_arrival_order == Some(vec![]));
    assert!(!client.has_chat_sync_cursor() && client.chat_sync_feed.last_opened_chat_id.is_none());
    assert!(seen.lock().unwrap()[0].contains(&format!("team_id={team}")), "Team scoped request");
    // The personal context is a different cache and is untouched: a personal
    // client with the same feed shape keeps its rows after a 403 on a Personal call.
    let (api, _, task2) = feed_peer(vec![(403, json!({"detail":"forbidden"}))]).await;
    let mut personal = client_at(&api);
    personal.chats.insert(A.into(), row(A, 1, 10));
    personal.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
    assert_eq!(personal.catch_up_chat_sync_feed().await.unwrap(), FeedCatchUp::Unavailable);
    assert!(personal.chats.contains_key(A) && personal.has_chat_sync_cursor());
    task.abort();
    task2.abort();
}

// contract-test: direct surface=sdks.rust assertions=sync.overview.ready-fast,sync.delta.cursor-gap-free
#[tokio::test]
async fn prefetched_first_page_is_used_once_and_costs_no_second_request() {
    let page = delta(false, "e1:8|e2:2", json!([{"hashed_chat_id":super::hashed(A),"kinds":["deleted"]}]), Value::Null);
    let (api, seen, task) = feed_peer(vec![page]).await;
    let mut client = client_at(&api);
    client.chats.insert(A.into(), row(A, 1, 10));
    client.chat_arrival_order = Some(vec![A.into()]);
    client.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
    client.prefetch_chat_sync_feed();
    assert!(client.feed_prefetch.is_some());
    // The command's own admission would run here; the page is consumed afterwards.
    let outcome = client.catch_up_chat_sync_feed().await.unwrap();
    assert_eq!(outcome, FeedCatchUp::Applied { pages: 1, changes: 1 });
    assert!(client.feed_prefetch.is_none() && !client.chats.contains_key(A));
    assert_eq!(seen.lock().unwrap().len(), 1, "exactly the prefetched request");
    task.abort();
}

// contract-test: direct surface=sdks.rust assertions=sync.delta.scope-revocation
#[tokio::test]
async fn prefetch_for_another_cursor_or_owner_is_discarded() {
    let page = || delta(false, "e1:9|e2:3", json!([]), Value::Null);
    let (api, seen, task) = feed_peer(vec![page(), page(), page()]).await;
    let mut client = client_at(&api);
    client.chat_sync_feed.cursor = Some("e1:5|e2:1".into());
    client.prefetch_chat_sync_feed();
    // The cache was replaced (new cursor) before the page was consumed.
    client.chat_sync_feed.cursor = Some("e1:6|e2:1".into());
    client.catch_up_chat_sync_feed().await.unwrap();
    assert!(seen.lock().unwrap().last().unwrap().contains("cursor=e1%3A6%7Ce2%3A1"), "{:?}", seen.lock().unwrap());
    assert_eq!(client.chat_sync_feed.cursor.as_deref(), Some("e1:9|e2:3"));
    // A different session owner never consumes it either.
    client.chat_sync_feed.cursor = Some("e1:9|e2:3".into());
    client.prefetch_chat_sync_feed();
    client.session.as_mut().unwrap().hashed_email = "another-owner".into();
    client.catch_up_chat_sync_feed().await.unwrap();
    assert!(client.feed_prefetch.is_none());
    task.abort();
}
