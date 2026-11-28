//! Native startup over real cache sections and controlled HTTP replies.
use super::*;
use crate::view_model::{
    ListCompleteness,
    actor_tests::{CHAT, Fixture, Sink, fixture, session, snapshot},
    start,
};
use serde_json::{Value, json};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
};

const OTHER: &str = "33333333-3333-4333-8333-333333333333";
const THIRD: &str = "44444444-4444-4444-8444-444444444444";
const BUDGET: Duration = Duration::from_secs(10);

async fn start_fixture(listener: &TcpListener) -> (Fixture, Sink, CancellationToken) {
    let mut fixture = fixture();
    let sink = Sink::default();
    let cancel = CancellationToken::new();
    let mut credentials = session();
    credentials.api_url = format!("http://{}", listener.local_addr().unwrap());
    fixture.host.core.enable_recently_opened_chats();
    start(&mut fixture.host, credentials, &sink, &cancel)
        .await
        .unwrap();
    fixture
        .host
        .core
        .client_mut()
        .restore_ciphertext_snapshot(&snapshot())
        .unwrap();
    (fixture, sink, cancel)
}

async fn request(listener: &TcpListener, route: &str) -> TcpStream {
    let (mut stream, _) = listener.accept().await.unwrap();
    let mut data = Vec::new();
    while !data.windows(4).any(|window| window == b"\r\n\r\n") {
        let mut buf = [0; 2048];
        let size = stream.read(&mut buf).await.unwrap();
        assert_ne!(size, 0);
        data.extend_from_slice(&buf[..size]);
    }
    let request = std::str::from_utf8(&data).unwrap().lines().next().unwrap();
    assert!(request.contains(route), "{request}");
    stream
}

async fn respond(mut stream: TcpStream, status: u16, reply: Value) {
    let body = reply.to_string();
    let response = format!(
        "HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{body}",
        body.len(),
    );
    stream.write_all(response.as_bytes()).await.unwrap();
}

fn preview() -> Value {
    let source = snapshot();
    let base = &source["chats"][CHAT];
    let row = |id: &str| {
        let mut row = base.clone();
        row["id"] = json!(id);
        row["chat_key_wrappers"] = json!([]);
        row
    };
    json!({"chats":[row(CHAT), row(OTHER), row(THIRD)]})
}

fn has_partial_sidebar(sink: &Sink) -> bool {
    sink.events().iter().any(|event| {
        matches!(
            event,
            ViewEvent::ChatList { rows, completeness: ListCompleteness::Partial, .. }
            if rows.len() == 3 && rows.iter().any(|row| row.id == CHAT)
        )
    })
}

#[tokio::test]
async fn startup_open_receipt_requires_a_true_server_acknowledgment() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let (mut fixture, _, cancel) = start_fixture(&listener).await;
    let route = format!("/v1/chats/{CHAT}/opened");
    for (status, payload, expected) in [
        (403, json!({}), Ok(false)),
        (200, json!({"recorded":false}), Err(Error::Protocol)),
        (200, json!({"recorded":true}), Ok(true)),
    ] {
        let core = &mut fixture.host.core;
        core.begin_client_operation(&cancel);
        let client = core.client_mut();
        client.remember_user_chat_open(CHAT).unwrap();
        let peer = async {
            let stream = request(&listener, &route).await;
            respond(stream, status, payload).await;
        };
        let (result, ()) = tokio::time::timeout(Duration::from_secs(5), async {
            tokio::join!(client.submit_user_chat_open(CHAT), peer)
        })
        .await
        .unwrap();
        assert_eq!(result, expected);
    }
}

#[tokio::test]
async fn startup_prioritizes_head_then_publishes_sparse_sidebar_while_head_is_stalled() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let (mut fixture, sink, cancel) = start_fixture(&listener).await;
    let peer = async {
        let selector = request(&listener, "/v1/chats/startup-opened").await;
        respond(selector, 200, json!({"chat_ids":[CHAT]})).await;
        let stalled_head = request(&listener, "/v1/chats/metadata/batch").await;

        // The first head request is already in flight. Advance its deadline
        // without relying on real time and keep its response withheld.
        tokio::time::pause();
        tokio::time::advance(BUDGET).await;
        tokio::time::resume();
        let sidebar = request(&listener, "/v1/chats?limit=10").await;
        respond(sidebar, 200, preview()).await;
        let retry = request(&listener, "/v1/chats/metadata/batch").await;
        assert!(has_partial_sidebar(&sink));
        drop(stalled_head);
        respond(retry, 403, json!({})).await;
    };
    let startup =
        resume_startup_with_budget(&mut fixture.host, RequestId(1), &sink, &cancel, BUDGET);
    let (result, ()) = tokio::time::timeout(Duration::from_secs(30), async {
        tokio::join!(startup, peer)
    })
    .await
    .unwrap();
    assert_eq!(result.unwrap(), Vec::<String>::new());
    assert!(fixture.host.core.startup_sidebar_published);
    assert!(sink.events().iter().any(|event| matches!(
        event, ViewEvent::ChatUnavailable { chat_id } if chat_id == CHAT
    )));
}

#[tokio::test]
async fn sparse_personal_sidebar_publishes_ten_rows_with_absent_and_wrapper_only_keys() {
    use sha2::{Digest, Sha256};

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let (mut fixture, sink, cancel) = start_fixture(&listener).await;
    let no_key = "55555555-5555-4555-8555-000000000000";
    let wrapper_only = "55555555-5555-4555-8555-000000000001";
    let source = snapshot();
    let base = &source["chats"][CHAT];
    let mut rows = vec![base.clone()];
    rows[0]["chat_key_wrappers"] = json!([]);
    for index in 0..9 {
        let id = format!("55555555-5555-4555-8555-{index:012}");
        let mut row = base.clone();
        row["id"] = json!(id);
        row["created_at"] = json!("1");
        row["updated_at"] = json!("2");
        row["last_edited_overall_timestamp"] = json!("2");
        row["chat_key_wrappers"] = json!([]);
        match id.as_str() {
            id if id == no_key => row["encrypted_chat_key"] = Value::Null,
            id if id == wrapper_only => {
                row["chat_key_wrappers"] = json!([{
                    "hashed_chat_id": format!("{:x}", Sha256::digest(id.as_bytes())),
                    "key_type": "master",
                    "encrypted_chat_key": base["encrypted_chat_key"],
                }]);
                row["encrypted_chat_key"] = Value::Null;
            }
            _ => {}
        }
        rows.push(row);
    }
    let peer = async {
        let selector = request(&listener, "/v1/chats/startup-opened").await;
        respond(selector, 200, json!({"chat_ids":[],"messages_versions":{}})).await;
        let sidebar = request(&listener, "/v1/chats?limit=10").await;
        respond(sidebar, 200, json!({"chats":rows,"limit":10})).await;
    };
    let startup =
        resume_startup_with_budget(&mut fixture.host, RequestId(2), &sink, &cancel, BUDGET);
    let (result, ()) = tokio::time::timeout(Duration::from_secs(30), async {
        tokio::join!(startup, peer)
    }).await.unwrap();
    assert!(result.unwrap().is_empty());
    let verify_sidebar = |sink: &Sink, completeness| {
        let events = sink.events();
        let rows = events
            .iter()
            .find_map(|event| match event {
                ViewEvent::ChatList { rows, completeness: observed, .. } if *observed == completeness => Some(rows),
                _ => None,
            })
            .expect("valid neighbors render alongside the locked row");
        assert_eq!(rows.len(), 10);
        let locked = rows.iter().find(|row| row.id == no_key).unwrap();
        assert_eq!(locked.status, super::super::ChatRowStatus::Locked);
        assert_eq!(locked.title, "Locked chat");
        assert_eq!(locked.chat_list_title, None);
        let readable = rows.iter().find(|row| row.id == wrapper_only).unwrap();
        assert_eq!(readable.status, super::super::ChatRowStatus::Ready);
        assert_eq!(readable.title, "Synthetic cached title");
    };
    verify_sidebar(&sink, ListCompleteness::Partial);

    // Re-enter through the normal shell startup, which resets the client and
    // reads the durably saved index before admission. No server is responding.
    let mut credentials = session();
    credentials.api_url = format!("http://{}", listener.local_addr().unwrap());
    drop(listener);
    let restored = Sink::default();
    start(&mut fixture.host, credentials, &restored, &cancel)
        .await
        .unwrap();
    verify_sidebar(&restored, ListCompleteness::Cached);
}

#[tokio::test]
async fn malformed_startup_selector_reports_error_after_publishing_sparse_sidebar() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let (mut fixture, sink, cancel) = start_fixture(&listener).await;
    let peer = async {
        let selector = request(&listener, "/v1/chats/startup-opened").await;
        respond(selector, 200, json!({"malformed":[] })).await;
        let sidebar = request(&listener, "/v1/chats?limit=10").await;
        respond(sidebar, 200, preview()).await;
    };
    let startup =
        resume_startup_with_budget(&mut fixture.host, RequestId(2), &sink, &cancel, BUDGET);
    let (result, ()) = tokio::time::timeout(Duration::from_secs(30), async {
        tokio::join!(startup, peer)
    })
    .await
    .unwrap();
    assert_eq!(result, Err(Error::Protocol));
    assert!(has_partial_sidebar(&sink));
}

#[tokio::test]
async fn startup_selector_admission_denial_never_publishes_network_sidebar() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let (mut fixture, sink, cancel) = start_fixture(&listener).await;
    let peer = async {
        let selector = request(&listener, "/v1/chats/startup-opened").await;
        respond(selector, 401, json!({})).await;
    };
    let startup =
        resume_startup_with_budget(&mut fixture.host, RequestId(3), &sink, &cancel, BUDGET);
    let (result, ()) = tokio::time::timeout(Duration::from_secs(30), async {
        tokio::join!(startup, peer)
    })
    .await
    .unwrap();
    assert_eq!(result, Err(Error::Expired));
    assert!(fixture.host.core.client().session().is_none());
    assert!(!has_partial_sidebar(&sink));
}

#[tokio::test]
async fn reconnect_rechecks_opened_cohort_once_without_replacing_selection() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let (mut fixture, sink, cancel) = start_fixture(&listener).await;
    let core = &mut fixture.host.core;
    core.begin_window(RequestId(4), CHAT);
    let before = sink.events();
    core.startup_monitor_cohort = StartupMonitorCohort::Refresh;
    let peer = async {
        let selector = request(&listener, "/v1/chats/startup-opened").await;
        respond(selector, 200, json!({"chat_ids":[OTHER]})).await;
        let hydrate = request(&listener, "/v1/chats/metadata/batch").await;
        respond(hydrate, 403, json!({})).await;
    };
    let (result, ()) = tokio::time::timeout(Duration::from_secs(30), async {
        tokio::join!(core.refresh_monitor_startup_cohort(&cancel), peer)
    })
    .await
    .unwrap();
    result.unwrap();
    assert_eq!(core.open_chat_id(), Some(CHAT));
    assert_eq!(sink.events(), before);
    assert!(core.startup_hydration.is_empty());
    assert!(matches!(
        core.startup_monitor_cohort,
        StartupMonitorCohort::Connected
    ));

    // No second selector starts for the same replacement monitor.
    tokio::time::timeout(
        Duration::from_millis(100),
        core.refresh_monitor_startup_cohort(&cancel),
    )
    .await
    .unwrap()
    .unwrap();
}

#[tokio::test]
async fn foreground_cancels_reconnect_selector_before_response_headers() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let (mut fixture, sink, cancel) = start_fixture(&listener).await;
    fixture.host.core.begin_window(RequestId(5), CHAT);
    let before = sink.events();
    let peer = async {
        let pending = request(&listener, "/v1/chats/startup-opened").await;
        cancel.cancel();
        pending
    };
    let (result, still_connected_peer) = tokio::time::timeout(Duration::from_secs(5), async {
        tokio::join!(refresh_startup_cohort(&mut fixture.host, &cancel), peer)
    })
    .await
    .unwrap();
    assert_eq!(result, Err(Error::Cancelled));
    assert_eq!(fixture.host.core.open_chat_id(), Some(CHAT));
    assert_eq!(sink.events(), before);
    assert!(fixture.host.core.startup_hydration.is_empty());
    drop(still_connected_peer);
}
