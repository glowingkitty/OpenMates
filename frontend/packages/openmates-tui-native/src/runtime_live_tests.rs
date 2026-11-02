//! PRIVATE DRAFT native durability/order regressions — not executed.
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
#[tokio::test]
async fn idle_actor_has_no_monitor_and_cannot_schedule_live_profile_io() {
    let (_directory, actor) = super::tests::fixture().await;
    assert!(actor.live_monitor.is_none());
    assert!(actor.recovery_hints.is_empty());
}
#[tokio::test]
async fn cancelled_live_tick_does_not_touch_storage_or_publish_model() {
    let (_directory, mut actor) = super::tests::fixture().await;
    let (send, mut receive) = mpsc::channel(4);
    actor.live_cancel.cancel();
    let before = actor.client.ciphertext_snapshot();
    actor.live_update(&send).await.unwrap();
    assert_eq!(actor.client.ciphertext_snapshot(), before);
    assert!(receive.try_recv().is_err());
}
#[test]
fn live_model_reply_is_owner_fenced_but_presentation_decides_selected_identity() {
    // A background item list may update a cache across navigation; it cannot
    // cross account/Team security epochs. UI tests separately prove ID checks.
    let current = Stamp {
        security: 4,
        view: 9,
    };
    assert!(!current.accepts(&Reply {
        epoch: Stamp {
            security: 3,
            view: 9
        },
        view: View::Items(Workspace::Chats, vec![])
    }));
    assert!(current.accepts(&Reply {
        epoch: Stamp {
            security: 4,
            view: 8
        },
        view: View::Items(Workspace::Chats, vec![])
    }));
}

use futures_util::{SinkExt, StreamExt};
use serde_json::{Value, json};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;
const CHAT: &str = "11111111-1111-4111-8111-111111111111";
async fn read_http(stream: &mut tokio::net::TcpStream) -> String {
    let mut bytes = Vec::new();
    let mut part = [0; 2048];
    loop {
        let count = stream.read(&mut part).await.unwrap();
        assert!(count > 0);
        bytes.extend_from_slice(&part[..count]);
        if let Some(end) = bytes.windows(4).position(|b| b == b"\r\n\r\n") {
            let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
            let len = headers
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|n| n.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            if bytes.len() >= end + 4 + len {
                return headers.lines().next().unwrap().to_owned();
            }
        }
    }
}
async fn respond_http(stream: &mut tokio::net::TcpStream, body: Value) {
    respond_http_status(stream, 200, body).await
}
async fn respond_http_status(stream: &mut tokio::net::TcpStream, status: u16, body: Value) {
    let body = body.to_string();
    stream.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=rotated-synthetic; Path=/\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
}
async fn live_peer() -> (
    String,
    tokio::sync::oneshot::Sender<()>,
    tokio::task::JoinHandle<()>,
) {
    let (api, release, task, _requests) = live_peer_observed(false).await;
    (api, release, task)
}
async fn live_peer_mode(
    reject_validation: bool,
) -> (
    String,
    tokio::sync::oneshot::Sender<()>,
    tokio::task::JoinHandle<()>,
) {
    let (api, release, task, _requests) = live_peer_observed(reject_validation).await;
    (api, release, task)
}
async fn live_peer_observed(
    reject_validation: bool,
) -> (
    String,
    tokio::sync::oneshot::Sender<()>,
    tokio::task::JoinHandle<()>,
    std::sync::Arc<std::sync::atomic::AtomicUsize>,
) {
    live_peer_observed_with_hold(reject_validation, None).await
}
async fn live_peer_observed_with_hold(
    reject_validation: bool,
    held_auth: Option<(std::sync::Arc<tokio::sync::Notify>, std::sync::Arc<tokio::sync::Notify>)>,
) -> (
    String,
    tokio::sync::oneshot::Sender<()>,
    tokio::task::JoinHandle<()>,
    std::sync::Arc<std::sync::atomic::AtomicUsize>,
) {
    live_peer_observed_config(reject_validation, held_auth, false).await
}
async fn live_peer_observed_config(
    reject_validation: bool,
    held_auth: Option<(std::sync::Arc<tokio::sync::Notify>, std::sync::Arc<tokio::sync::Notify>)>,
    complete_inventory: bool,
) -> (
    String,
    tokio::sync::oneshot::Sender<()>,
    tokio::task::JoinHandle<()>,
    std::sync::Arc<std::sync::atomic::AtomicUsize>,
) {
    live_peer_observed_config_with_cache(reject_validation, held_auth, complete_inventory, None).await
}
async fn live_peer_observed_config_with_cache(
    reject_validation: bool,
    mut held_auth: Option<(std::sync::Arc<tokio::sync::Notify>, std::sync::Arc<tokio::sync::Notify>)>,
    complete_inventory: bool,
    warm_snapshot: Option<Value>,
) -> (String, tokio::sync::oneshot::Sender<()>, tokio::task::JoinHandle<()>, std::sync::Arc<std::sync::atomic::AtomicUsize>) {
    use std::sync::{Arc, atomic::{AtomicUsize, Ordering}};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let (release, mut trigger) = tokio::sync::oneshot::channel();
    let requests = Arc::new(AtomicUsize::new(0));
    let observed = requests.clone();
    let server = tokio::spawn(async move {
        let (mut auth, _) = listener.accept().await.unwrap();
        assert_eq!(read_http(&mut auth).await, "POST /v1/auth/session HTTP/1.1");
        observed.fetch_add(1, Ordering::SeqCst);
        respond_http(
            &mut auth,
            json!({"success":true,"ws_token":"synthetic-token","user":{"id":"fixture-owner","username":"FixtureOwner"}}),
        )
        .await;
        drop(auth);
        let (stream, _) = listener.accept().await.unwrap();
        let mut monitor = tokio_tungstenite::accept_async(stream).await.unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(
                &monitor.next().await.unwrap().unwrap().into_text().unwrap()
            )
            .unwrap()["type"],
            "native_client_lifecycle"
        );
        let closed = CancellationToken::new();
        let monitor_closed = closed.clone();
        let monitor_task = tokio::spawn(async move {
            let mut triggered = false;
            loop {
                tokio::select! {
                    result=&mut trigger,if !triggered=>{triggered=true;if result.is_ok(){monitor.send(Frame::Text(json!({"type":"new_chat_message","payload":{"chat_id":CHAT,"messages_v":1,"content":"transient must not persist"}}).to_string().into())).await.unwrap();}},
                    frame=monitor.next()=>{if frame.is_none_or(|frame|matches!(frame.unwrap(),Frame::Close(_))){monitor_closed.cancel();return;}},
                }
            }
        });
        loop {
            let accepted = tokio::select! {biased;_=closed.cancelled()=>break,accepted=listener.accept()=>accepted.unwrap()};
            let (mut http, _) = accepted;
            let request = read_http(&mut http).await;
            observed.fetch_add(1, Ordering::SeqCst);
            if request == "POST /v1/auth/session HTTP/1.1" {
                if reject_validation {
                    respond_http_status(&mut http, 401, json!({"detail":"expired"})).await;
                    drop(http);
                    break;
                }
                if let Some((started, release)) = held_auth.take() {
                    started.notify_one();
                    release.notified().await;
                }
                respond_http(&mut http,json!({"success":true,"ws_token":"synthetic-token","user":{"id":"fixture-owner","username":"FixtureOwner"}})).await;
                drop(http);
                let accepted = tokio::select! {biased;_=closed.cancelled()=>break,accepted=listener.accept()=>accepted.unwrap()};
                let (stream, _) = accepted;
                let mut sync = tokio_tungstenite::accept_async(stream).await.unwrap();
                assert_eq!(
                    serde_json::from_str::<Value>(
                        &sync.next().await.unwrap().unwrap().into_text().unwrap()
                    )
                    .unwrap()["type"],
                    "native_client_lifecycle"
                );
                // Selected (chat-open) discovery sends no request: it waits for
                // the startup offers on its authenticated socket.
                let next = tokio::time::timeout(Duration::from_millis(400), sync.next()).await;
                let Ok(next) = next else {
                    for frame in [
                        json!({"type":"native_client_lifecycle_ack","payload":{"is_foreground":true}}),
                        json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"completed"}}),
                        json!({"type":"recovery_jobs_available","payload":{"jobs":[]}}),
                        json!({"type":"metadata_jobs_available","payload":{"jobs":[]}}),
                    ] {
                        sync.send(Frame::Text(frame.to_string().into())).await.unwrap();
                    }
                    while let Some(Ok(frame)) = sync.next().await {
                        if matches!(frame, Frame::Close(_)) { break; }
                    }
                    continue;
                };
                let mut request: Value =
                    serde_json::from_str(&next.unwrap().unwrap().into_text().unwrap())
                        .unwrap();
                if request["type"] == "set_active_chat" {
                    request = serde_json::from_str(
                        &sync.next().await.unwrap().unwrap().into_text().unwrap(),
                    )
                    .unwrap();
                }
                assert_eq!(request["type"], "phased_sync_request");
                let mut frames = vec![
                    json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":[]}}),
                    json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"disabled"}}),
                    json!({"type":"recovery_jobs_available","payload":{"jobs":[]}}),
                    json!({"type":"metadata_jobs_available","payload":{"jobs":[]}}),
                    json!({"type":"phased_sync_complete","payload":{}}),
                ];
                if complete_inventory {
                    let nonce = request["payload"]["inventory_request_id"].as_str();
                    if let Some(nonce) = nonce {
                    assert_eq!(uuid::Uuid::parse_str(nonce).unwrap().get_version_num(), 4);
                    }
                    let snapshot = warm_snapshot.clone().unwrap_or_else(|| owned_cached_snapshot(6));
                    frames[0]["payload"]["chats"] = json!([{"chat_details":snapshot["chats"][CHAT].clone()}]);
                    frames[1]["payload"]["status"] = json!("completed");
                    frames[4]["payload"]["phase"] = json!(request["payload"]["phase"].as_str().unwrap_or("all"));
                    frames.push(json!({"type":"task_update_jobs_available","payload":{"jobs":[],"complete":true}}));
                    frames.insert(0,json!({"type":"server_capabilities","payload":{"capabilities":["task_update_jobs_inventory_v1"]}}));
                    if let Some(nonce) = nonce {
                        for frame in &mut frames { frame["payload"]["inventory_request_id"] = json!(nonce); }
                    }
                }
                for frame in frames {
                    sync.send(Frame::Text(frame.to_string().into()))
                        .await
                        .unwrap();
                }
                assert!(matches!(
                    sync.next().await.unwrap().unwrap(),
                    Frame::Close(_)
                ));
            } else if request.starts_with(&format!("GET /v1/chats/{CHAT}/messages/window?")) {
                assert!(warm_snapshot.is_none(), "warm Actor::dispatch must settle cache without any history-window request");
                assert_eq!(request, format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1"));
                let snapshot = owned_cached_snapshot(6);
                respond_http(&mut http, json!({"messages":snapshot["history"][CHAT].clone(),"has_more_before":false})).await;
            } else {
                assert_eq!(request, "POST /v1/chats/metadata/batch HTTP/1.1");
                let row = warm_snapshot.as_ref().map(|snapshot| snapshot["chats"][CHAT].clone()).unwrap_or_else(||
                    json!({"id":CHAT,"messages_v":1,"encrypted_chat_key":openmates_sdk::crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap(),"encrypted_title":openmates_sdk::crypto::encrypt_combined("Durable external title",&[9;32]).unwrap()}));
                respond_http(&mut http, json!({"chats":[row]})).await;
            }
        }
        monitor_task.await.unwrap();
    });
    (format!("http://{address}"), release, server, requests)
}
async fn prepared_actor() -> (tempfile::TempDir, Actor, tokio::task::JoinHandle<()>) {
    prepared_actor_mode(false).await
}
async fn prepared_actor_mode(
    reject_validation: bool,
) -> (tempfile::TempDir, Actor, tokio::task::JoinHandle<()>) {
    let (directory, mut actor) = super::tests::fixture().await;
    let (api, release, server) = if reject_validation {
        live_peer_mode(true).await
    } else {
        live_peer().await
    };
    let mut session = actor.client.clone_session().unwrap();
    session.api_url = api.clone();
    actor.client.reset(&api, Some(session)).unwrap();
    let (send, _receive) = mpsc::channel(32);
    actor.monitor(&send, Stamp::default()).await.unwrap();
    let monitor = actor.live_monitor.as_ref().unwrap();
    assert!(monitor.take_pending().unwrap().is_some());
    release.send(()).unwrap();
    tokio::time::timeout(Duration::from_secs(4), monitor.changed())
        .await
        .unwrap()
        .unwrap();
    (directory, actor, server)
}
#[tokio::test]
async fn actual_live_read_persists_encrypted_snapshot_and_exact_credentials_before_model_publication()
 {
    let (_directory, mut actor, server) = prepared_actor().await;
    let (send, mut receive) = mpsc::channel(8);
    tokio::time::timeout(Duration::from_secs(8), actor.live_update(&send))
        .await
        .unwrap()
        .unwrap();
    let reply = receive.recv().await.unwrap();
    let View::Live(publication) = reply.view else {
        panic!("expected durable live publication")
    };
    actor
        .client
        .validate_chat_publication(&publication)
        .unwrap();
    let session = actor.client.clone_session().unwrap();
    let durable = actor
        .store
        .read_cache(
            session.hashed_email.clone(),
            cache_key(&session),
            session.master_key.clone(),
        )
        .await
        .unwrap()
        .unwrap();
    assert_eq!(durable, actor.client.ciphertext_snapshot());
    assert!(!durable.to_string().contains("Durable external title"));
    assert!(!durable.to_string().contains("transient must not persist"));
    assert_eq!(
        publication.models().unwrap().items[0].title,
        "Durable external title"
    );
    let stored = actor
        .store
        .load(actor.passphrase.clone())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        stored.cookies.get("auth_refresh_token").map(String::as_str),
        Some("rotated-synthetic")
    );
    actor.live_monitor.take();
    tokio::time::timeout(Duration::from_secs(4), server)
        .await
        .unwrap()
        .unwrap();
}
#[tokio::test]
async fn durable_revocation_failure_has_no_plaintext_publication_or_old_state_restore() {
    let (_directory, mut actor, server) = prepared_actor().await;
    let (send, mut receive) = mpsc::channel(8);
    actor.store.revoke().await.unwrap();
    let result = tokio::time::timeout(Duration::from_secs(8), actor.live_update(&send))
        .await
        .unwrap();
    assert!(result.is_err());
    assert!(receive.try_recv().is_err());
    // The authoritative in-memory rotated cookie remains available for the
    // existing actor error/persistence policy; no stale snapshot rollback.
    assert_eq!(
        actor
            .client
            .clone_session()
            .unwrap()
            .cookies
            .get("auth_refresh_token")
            .map(String::as_str),
        Some("rotated-synthetic")
    );
    actor.live_monitor.take();
    tokio::time::timeout(Duration::from_secs(4), server)
        .await
        .unwrap()
        .unwrap();
}

#[cfg(unix)]
struct RestoreProfilePermissions(std::path::PathBuf, std::fs::Permissions);
#[cfg(unix)]
impl Drop for RestoreProfilePermissions {
    fn drop(&mut self) {
        let _ = std::fs::set_permissions(&self.0, self.1.clone());
    }
}
#[cfg(unix)]
fn deny_fixture_profile_writes(directory: &tempfile::TempDir) -> RestoreProfilePermissions {
    use std::os::unix::fs::PermissionsExt;
    let path = directory.path().join("profile");
    let previous = std::fs::metadata(&path).unwrap().permissions();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o500)).unwrap();
    RestoreProfilePermissions(path, previous)
}
#[cfg(unix)]
#[tokio::test]
async fn known_validation_expiry_security_notification_precedes_failing_store_clear() {
    let (directory, mut actor, server) = prepared_actor_mode(true).await;
    let (send, mut receive) = mpsc::channel(8);
    let _permissions = deny_fixture_profile_writes(&directory);
    let result = tokio::time::timeout(
        Duration::from_secs(8),
        actor.monitor(&send, Stamp::default()),
    )
    .await
    .unwrap();
    assert!(result.is_err());
    assert!(matches!(
        receive.recv().await.unwrap().view,
        View::Monitor(Error::Expired, _)
    ));
    assert!(actor.client.session().is_none());
    tokio::time::timeout(Duration::from_secs(4), server)
        .await
        .unwrap()
        .unwrap();
}
#[cfg(unix)]
#[tokio::test]
async fn known_start_expiry_security_notification_precedes_failing_store_clear() {
    let (directory, mut actor) = super::tests::fixture().await;
    actor.persist().await.unwrap();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        assert_eq!(
            read_http(&mut stream).await,
            "POST /v1/auth/session HTTP/1.1"
        );
        respond_http_status(&mut stream, 401, json!({"detail":"expired"})).await;
    });
    let mut session = actor.client.clone_session().unwrap();
    session.api_url = api.clone();
    actor.client.reset(&api, Some(session)).unwrap();
    let _permissions = deny_fixture_profile_writes(&directory);
    let (send, mut receive) = mpsc::channel(8);
    let result = tokio::time::timeout(
        Duration::from_secs(8),
        actor.monitor(&send, Stamp::default()),
    )
    .await
    .unwrap();
    assert!(result.is_err());
    assert!(matches!(
        receive.recv().await.unwrap().view,
        View::Monitor(Error::Expired, _)
    ));
    server.await.unwrap();
}

#[tokio::test]
async fn dropped_live_read_future_retains_hint_and_cancelled_tick_waits_fresh_token() {
    let (_directory, mut actor, server) = prepared_actor().await;
    let (send, mut receive) = mpsc::channel(8);
    let mut read = Box::pin(actor.live_update(&send));
    assert!(matches!(
        futures_util::poll!(&mut read),
        std::task::Poll::Pending
    ));
    drop(read); // equivalent to outer bounded-cancellation grace exhausting
    assert!(actor.live_pending.is_some());
    actor.live_cancel.cancel();
    actor.live_update(&send).await.unwrap();
    assert!(actor.live_pending.is_some());
    assert!(receive.try_recv().is_err());
    actor.live_cancel = CancellationToken::new();
    assert!(!actor.live_cancel.is_cancelled());
    assert!(actor.live_pending.is_some());
    // Only this local test's partial peer is stopped; no runtime/backend exists.
    actor.live_monitor.take();
    server.abort();
    let _ = server.await;
}

#[tokio::test]
async fn foreground_recovery_grant_is_removed_when_future_is_dropped() {
    let (_directory, mut actor) = super::tests::fixture().await;
    let mut operation = Box::pin(async {
        let _grant = ForegroundRecoveryGrant::new(&mut actor.client).unwrap();
        std::future::pending::<()>().await;
    });
    assert!(matches!(
        futures_util::poll!(&mut operation),
        std::task::Poll::Pending
    ));
    drop(operation);
    assert!(matches!(
        actor
            .client
            .completion_recovery_jobs(&CancellationToken::new())
            .await,
        Err(Error::Unavailable {
            code: "completion_recovery_unavailable",
            ..
        })
    ));
}
#[tokio::test]
async fn cold_authenticated_start_pumps_once_without_hint_and_idle_ticks_do_not_poll_http() {
    use std::sync::atomic::Ordering;
    let (_directory, mut actor) = super::tests::fixture().await;
    let (api, release, server, requests) = live_peer_observed(false).await;
    let mut session = actor.client.clone_session().unwrap();
    session.api_url = api.clone();
    actor.client.reset(&api, Some(session)).unwrap();
    let (send, _receive) = mpsc::channel(32);
    actor.monitor(&send, Stamp::default()).await.unwrap();
    assert!(
        actor
            .live_monitor
            .as_ref()
            .unwrap()
            .take_pending()
            .unwrap()
            .is_some()
    );
    let before = requests.load(Ordering::SeqCst);
    actor
        .recover_before_view(&send, Stamp::default(), None, false)
        .await
        .unwrap();
    assert!(!actor.recovery_start_needed);
    assert!(requests.load(Ordering::SeqCst) > before);
    let after = requests.load(Ordering::SeqCst);
    for _ in 0..3 {
        actor.live_update(&send).await.unwrap();
    }
    assert_eq!(requests.load(Ordering::SeqCst), after);
    actor.live_monitor.take();
    drop(release);
    tokio::time::timeout(Duration::from_secs(4), server)
        .await
        .unwrap()
        .unwrap();
}
#[tokio::test]
async fn deferred_revisit_waits_deadline_and_security_cancel_without_http() {
    let (_directory, mut actor) = super::tests::fixture().await;
    actor.recovery_start_needed = false;
    actor.recovery_hints.insert(CHAT.into());
    actor.recovery_retry_at = Some(tokio::time::Instant::now() + Duration::from_secs(5));
    assert!(!actor.recovery_due());
    actor.live_cancel.cancel();
    let (send, mut receive) = mpsc::channel(2);
    actor.live_update(&send).await.unwrap();
    assert!(receive.try_recv().is_err());
    assert!(actor.recovery_hints.contains(CHAT));
}

fn fixture_file_hashes(
    root: &std::path::Path,
) -> std::collections::BTreeMap<std::path::PathBuf, String> {
    use sha2::{Digest, Sha256};
    let mut found = std::collections::BTreeMap::new();
    let mut directories = vec![root.to_path_buf()];
    while let Some(directory) = directories.pop() {
        for entry in std::fs::read_dir(directory).unwrap() {
            let entry = entry.unwrap();
            let kind = entry.file_type().unwrap();
            if kind.is_dir() {
                directories.push(entry.path());
            } else if kind.is_file() {
                found.insert(
                    entry.path(),
                    format!("{:x}", Sha256::digest(std::fs::read(entry.path()).unwrap())),
                );
            }
        }
    }
    found
}
#[tokio::test]
async fn malformed_local_checkpoint_authenticates_first_then_quiesces_without_rewriting_bytes() {
    use std::sync::atomic::Ordering;
    let (directory, mut actor) = super::tests::fixture().await;
    let (api, release, server, requests) = live_peer_observed(false).await;
    let mut session = actor.client.clone_session().unwrap();
    session.api_url = api.clone();
    actor.client.reset(&api, Some(session)).unwrap();
    let (send, _receive) = mpsc::channel(32);
    actor.monitor(&send, Stamp::default()).await.unwrap();
    actor.live_monitor.as_ref().unwrap().take_pending().unwrap();
    let session = actor.client.clone_session().unwrap();
    let before = fixture_file_hashes(directory.path());
    actor
        .store
        .write_cache(
            session.hashed_email.clone(),
            format!("completion-pending-{}", cache_key(&session)),
            session.master_key.clone(),
            json!({"invalid-local-record":{}}),
        )
        .await
        .unwrap();
    let after = fixture_file_hashes(directory.path());
    let pending_files = after
        .iter()
        .filter(|(path, _)| !before.contains_key(*path))
        .map(|(path, hash)| (path.clone(), hash.clone()))
        .collect::<std::collections::BTreeMap<_, _>>();
    assert!(!pending_files.is_empty());
    let before_requests = requests.load(Ordering::SeqCst);
    assert!(matches!(
        actor
            .recover_before_view(&send, Stamp::default(), None, false)
            .await,
        Err(Error::Unavailable {
            code: "completion_recovery_checkpoint_invalid",
            ..
        })
    ));
    assert!(requests.load(Ordering::SeqCst) > before_requests);
    assert!(actor.recovery_blocked);
    assert!(!actor.recovery_due());
    let after_requests = requests.load(Ordering::SeqCst);
    for _ in 0..3 {
        actor.live_update(&send).await.unwrap();
    }
    assert_eq!(requests.load(Ordering::SeqCst), after_requests);
    let preserved = fixture_file_hashes(directory.path());
    for (path, hash) in pending_files {
        assert_eq!(preserved.get(&path), Some(&hash));
    }
    actor.live_monitor.take();
    drop(release);
    tokio::time::timeout(Duration::from_secs(4), server)
        .await
        .unwrap()
        .unwrap();
}

fn owned_cached_snapshot(count: usize) -> Value {
    let rows: Vec<Value>=(0..count).map(|index|json!({"id":format!("20000000-0000-4000-8000-{index:012}"),"chat_id":CHAT,
        "role":if index%2==0 {"user"}else{"assistant"},"created_at":index,
        "encrypted_content":openmates_sdk::crypto::encrypt_combined("CACHED_RENDER_READY",&[9;32]).unwrap()})).collect();
    let row=json!({"id":CHAT,"messages_v":count,"last_edited_overall_timestamp":1,
        "encrypted_chat_key":openmates_sdk::crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap(),
        "encrypted_title":openmates_sdk::crypto::encrypt_combined("Owned cached title",&[9;32]).unwrap()});
    let chats=std::collections::BTreeMap::from([(CHAT.to_owned(),row)]);
    let history=std::collections::BTreeMap::from([(CHAT.to_owned(),rows)]);
    json!({"chats":chats,"wrappers":[],"history":history,"embeds":{},"embed_keys":[],"team_wrapped_key":null})
}
async fn stage_owned_cached_actor(actor: &mut Actor) -> watch::Receiver<Option<NativeCachedChatViews>> {
    actor.client.restore_ciphertext_snapshot(&owned_cached_snapshot(6)).unwrap();
    actor.persist().await.unwrap();
    actor.stage_cached_views(Stamp::default());
    let receiver=actor.cached_views.subscribe();
    assert!(receiver.borrow().is_some());
    receiver
}
fn apply_owned_cached_reply(ui: &mut Ui, current: Stamp, reply: Reply) {
    if current.accepts(&reply) && let View::CachedChat(publication)=reply.view {
        apply_cached_chat(ui,publication);
    }
}
fn cached_frame(ui: &mut Ui) -> String {
    let mut terminal=Terminal::new(ratatui::backend::TestBackend::new(120,38)).unwrap();
    terminal.draw(|frame|ui.draw(frame)).unwrap();
    terminal.backend().buffer().content().iter().map(|cell|cell.symbol()).collect()
}
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted,auth.session.authoritative-enforcement
#[tokio::test]
async fn cached_frame_paints_while_real_background_auth_is_still_pending() {
    tokio::time::timeout(Duration::from_secs(12),async {
        use std::sync::{Arc,atomic::Ordering};
        let (_directory,mut actor)=super::tests::fixture().await;
        let started=Arc::new(tokio::sync::Notify::new());
        let release_auth=Arc::new(tokio::sync::Notify::new());
        let (api,release_hint,server,requests)=live_peer_observed_with_hold(false,Some((started.clone(),release_auth.clone()))).await;
        let mut session=actor.client.clone_session().unwrap();session.api_url=api.clone();
        actor.client.reset(&api,Some(session)).unwrap();
        let (send,_receive)=mpsc::channel(32);
        actor.monitor(&send,Stamp::default()).await.unwrap();
        let receiver=stage_owned_cached_actor(&mut actor).await;
        let lane=receiver.borrow().clone().unwrap();
        let mut background=Box::pin(actor.live_update(&send));
        tokio::select! {biased;_=started.notified()=>{},result=&mut background=>panic!("background must remain pending: {result:?}")}
        let before=requests.load(Ordering::SeqCst);
        let current=Stamp {security:0,view:1};
        let reply=lane.publish(CHAT,current,CancellationToken::new()).unwrap().unwrap();
        let mut ui=Ui::new();ui.set_authenticated(true);
        apply_owned_cached_reply(&mut ui,current,reply);
        assert!(ui.is_cached_chat_refreshing());
        let frame=cached_frame(&mut ui);
        assert!(frame.contains("CACHED_RENDER_READY"));
        assert_eq!(requests.load(Ordering::SeqCst),before,"cached rendering cannot request or await network");
        // The actor's genuine authenticated operation was not canceled, dropped
        // or replaced merely to make this earlier cached frame available.
        release_auth.notify_one();
        background.await.unwrap();
        actor.live_monitor.take();drop(release_hint);
        tokio::time::timeout(Duration::from_secs(4),server).await.unwrap().unwrap();
    }).await.unwrap();
}
#[tokio::test]
async fn native_store_revocation_rejects_already_queued_cached_plaintext() {
    tokio::time::timeout(Duration::from_secs(10),async {
        let (_directory,mut actor,server)=prepared_actor().await;
        let receiver=stage_owned_cached_actor(&mut actor).await;
        let lane=receiver.borrow().clone().unwrap();
        let reply=lane.publish(CHAT,Stamp::default(),CancellationToken::new()).unwrap().unwrap();
        actor.store.revoke().await.unwrap();
        let View::CachedChat(publication)=reply.view else {panic!("cached view")};
        assert!(matches!(publication.into_window(),Err(Error::Cancelled)));
        assert!(matches!(lane.publish(CHAT,Stamp::default(),CancellationToken::new()),Err(Error::Cancelled)));
        actor.live_monitor.take();
        tokio::time::timeout(Duration::from_secs(4),server).await.unwrap().unwrap();
    }).await.unwrap();
}
#[tokio::test]
async fn queued_cached_reply_requires_current_view_security_and_request_lifetime() {
    tokio::time::timeout(Duration::from_secs(10),async {
        let (_directory,mut actor,server)=prepared_actor().await;
        let receiver=stage_owned_cached_actor(&mut actor).await;
        let lane=receiver.borrow().clone().unwrap();
        let current=Stamp{security:0,view:4};
        let old=lane.publish(CHAT,Stamp{security:0,view:3},CancellationToken::new()).unwrap().unwrap();
        assert!(!current.accepts(&old));
        assert!(matches!(lane.publish(CHAT,Stamp{security:1,view:4},CancellationToken::new()),Err(Error::Cancelled)));
        let cancel=CancellationToken::new();
        let reply=lane.publish(CHAT,current,cancel.clone()).unwrap().unwrap();cancel.cancel();
        let mut ui=Ui::new();ui.set_authenticated(true);apply_owned_cached_reply(&mut ui,current,reply);
        assert!(!ui.is_cached_chat_refreshing());
        actor.live_monitor.take();
        tokio::time::timeout(Duration::from_secs(4),server).await.unwrap().unwrap();
    }).await.unwrap();
}
#[tokio::test]
async fn retired_reader_cannot_demote_a_later_canonical_view_or_cancel_actor_work() {
    tokio::time::timeout(Duration::from_secs(10),async {
        let (_directory,mut actor,server)=prepared_actor().await;
        let receiver=stage_owned_cached_actor(&mut actor).await;
        let old=receiver.borrow().clone().unwrap();
        let current=Stamp{security:0,view:1};
        let queued=old.publish(CHAT,current,CancellationToken::new()).unwrap().unwrap();
        actor.stage_cached_views(current);
        assert!(!actor.live_cancel.is_cancelled());
        assert!(actor.live_monitor.as_ref().unwrap().is_valid());
        let mut ui=Ui::new();ui.set_authenticated(true);
        ui.set_chat(Chat{id:CHAT.into(),title:"Owned cached title".into(),messages:vec![Message{content:"CANONICAL_STAYS".into(),..Default::default()}],..Default::default()});
        apply_owned_cached_reply(&mut ui,current,queued);
        assert!(!ui.is_cached_chat_refreshing());
        assert!(cached_frame(&mut ui).contains("CANONICAL_STAYS"));
        actor.live_monitor.take();
        tokio::time::timeout(Duration::from_secs(4),server).await.unwrap().unwrap();
    }).await.unwrap();
}
#[tokio::test]
async fn fresh_owner_reset_invalidates_independent_cached_lane_without_waiting_for_actor() {
    tokio::time::timeout(Duration::from_secs(10),async {
        let (_directory,mut actor,server)=prepared_actor().await;
        let receiver=stage_owned_cached_actor(&mut actor).await;
        let lane=receiver.borrow().clone().unwrap();
        let queued=lane.publish(CHAT,Stamp::default(),CancellationToken::new()).unwrap().unwrap();
        let mut replacement=actor.client.clone_session().unwrap();replacement.master_key=Zeroizing::new([8;32]);replacement.api_url="https://different.example.invalid".into();
        actor.client.reset("https://different.example.invalid",Some(replacement)).unwrap();
        let View::CachedChat(publication)=queued.view else {panic!("cached view")};
        assert!(matches!(publication.into_window(),Err(Error::Cancelled)));
        assert!(!lane.views.is_valid());
        actor.live_monitor.take();
        tokio::time::timeout(Duration::from_secs(4),server).await.unwrap().unwrap();
    }).await.unwrap();
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,chats.messages.client-encrypted
#[tokio::test]
async fn native_dispatch_future_keeps_request_state_within_one_stack_page() {
    let (_directory, mut actor) = super::tests::fixture().await;
    let (send, _receive) = mpsc::channel(4);
    let operation = actor.dispatch(Request {
        epoch: Stamp { security: 0, view: 1 },
        work: Work::Command(UiCommand::Open(Workspace::Chats, CHAT.into())),
        cancel: CancellationToken::new(),
    }, &send);
    // A regression that embeds process's large match state into this future
    // multiplies that state across caller/timeout/poll stack frames. The real
    // disconnected-owner case below retains its original offline/output rules.
    let bytes = std::mem::size_of_val(&operation);
    assert!(bytes <= 4096, "native dispatch inline future uses {bytes} bytes");
    drop(operation);
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,chats.messages.client-encrypted
#[tokio::test]
async fn native_process_selection_is_inert_and_has_bounded_inline_future_for_every_action() {
    let (_directory, mut actor) = super::tests::fixture().await;
    let checks = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let observed = checks.clone();
    actor.client.set_private_operation_gate(Some(std::sync::Arc::new(move || {
        observed.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        Err(Error::Forbidden)
    })));
    let before = actor.client.ciphertext_snapshot();
    let owner = actor.client.session().unwrap().session_id.clone();
    let generation = actor.store.generation_guard();
    let (send, mut receive) = mpsc::channel(4);
    let commands = vec![
        UiCommand::Login { email: "synthetic@example.invalid".into(),
            password: Zeroizing::new("synthetic password".into()), tfa: None },
        UiCommand::Unlock { passphrase: Zeroizing::new("synthetic passphrase".into()) },
        UiCommand::Logout, UiCommand::Cancel, UiCommand::BeginPair,
        UiCommand::PairPin { pin: Zeroizing::new("123456".into()), vault_passphrase: None },
        UiCommand::SwitchTeam(Some("33333333-3333-4333-8333-333333333333".into())),
        UiCommand::Refresh(Workspace::Chats), UiCommand::Open(Workspace::Chats, CHAT.into()),
        UiCommand::Mutate(Mutation::Delete { workspace: Workspace::Chats, id: CHAT.into() }),
        UiCommand::Send { chat_id: Some(CHAT.into()), text: "synthetic text".into() },
        UiCommand::Share { chat_id: CHAT.into(), expires_in: 3600,
            password: Zeroizing::new(String::new()), include_sensitive: false },
        UiCommand::Download { workspace: Workspace::Chats, id: CHAT.into(),
            destination: std::path::PathBuf::from("synthetic-unused-output"), overwrite: false },
        UiCommand::Quit,
    ];
    let mut work = vec![Work::Boot, Work::PairPoll, Work::Monitor, Work::Live];
    work.extend(commands.into_iter().map(Work::Command));
    for work in work {
        let cancel = CancellationToken::new();
        let operation = actor.process(Request { epoch: Stamp::default(), work, cancel: cancel.clone() }, &send);
        let bytes = std::mem::size_of_val(&operation);
        assert!(bytes <= 4096, "native process inline future uses {bytes} bytes");
        // Construction/drop must neither run the selected action nor cancel its
        // request: the original dispatch gate controls when polling starts.
        drop(operation);
        assert!(!cancel.is_cancelled());
        assert_eq!(checks.load(std::sync::atomic::Ordering::SeqCst), 0);
        assert_eq!(actor.client.ciphertext_snapshot(), before);
        assert_eq!(actor.client.session().unwrap().session_id, owner);
        assert_eq!(actor.pair_phase, 0);
        assert!(actor.passphrase.is_some());
        assert!(generation.is_current());
        assert!(receive.try_recv().is_err());
    }
}

#[tokio::test]
async fn genuine_disconnected_owner_keeps_cached_offline_read_only_without_canonical_promotion() {
    tokio::time::timeout(Duration::from_secs(10),async {
        let (_directory,mut actor,server)=prepared_actor().await;
        let _receiver=stage_owned_cached_actor(&mut actor).await;
        actor.live_monitor.as_ref().unwrap().close();
        // Close the actual peer listener before the selected read. This is a
        // genuine transport failure after authenticated owner admission, not
        // an injected success or a fabricated cached publication.
        tokio::time::timeout(Duration::from_secs(4),server).await.unwrap().unwrap();
        let current=Stamp{security:0,view:1};
        let (send,mut receive)=mpsc::channel(4);
        actor.dispatch(Request{epoch:current,work:Work::Command(UiCommand::Open(Workspace::Chats,CHAT.into())),cancel:CancellationToken::new()},&send).await.unwrap();
        let reply=receive.recv().await.unwrap();
        let View::CachedChatOffline(publication)=reply.view else {panic!("Offline cannot be normal canonical Chat")};
        let mut ui=Ui::new();ui.set_authenticated(true);
        apply_cached_chat_offline(&mut ui,publication);
        assert!(ui.is_cached_chat_read_only());
        assert!(!ui.is_cached_chat_refreshing());
        let frame=cached_frame(&mut ui);
        assert!(frame.contains("CACHED_RENDER_READY"));
        assert!(frame.to_ascii_lowercase().contains("offline"));
        assert!(actor.client.try_cached_default_chat_list(false).unwrap().is_none());
        assert_eq!(actor.client.ciphertext_snapshot()["history"][CHAT].as_array().unwrap().len(),6);
    }).await.unwrap();
}
#[test]
fn old_open_failure_cannot_hide_new_cached_navigation_but_security_and_send_errors_are_retained() {
    let current=Stamp{security:3,view:8};
    let old=Stamp{security:3,view:7};
    assert!(!current.accepts(&Reply{epoch:old,view:View::ChatOpenFailed(Error::Offline)}));
    assert!(!current.accepts(&Reply{epoch:old,view:View::ChatOpenFailed(Error::Cancelled)}));
    assert!(current.accepts(&Reply{epoch:old,view:View::ChatOpenFailed(Error::Expired)}));
    assert!(current.accepts(&Reply{epoch:old,view:View::ChatOpenFailed(Error::Forbidden)}));
    assert!(current.accepts(&Reply{epoch:old,view:View::Failed(Error::Io)}),"owned send/mutation uncertainty handling is not suppressed");
}

#[tokio::test]
async fn real_canonical_save_queue_checks_sdk_request_owner_and_native_generation_at_ui_consumption() {
    tokio::time::timeout(Duration::from_secs(15), async {
        for change in ["request", "owner-key", "store", "none"] {
            let (_directory,mut actor,server)=prepared_actor().await;
            let _receiver=stage_owned_cached_actor(&mut actor).await;
            let request=CancellationToken::new();actor.client.set_operation_cancel(request.clone());
            let ChatViewRead::Canonical(candidate)=actor.client.read_chat_view(actor.live_monitor.as_ref(),CHAT,request.clone()).await.unwrap()
                else {panic!("real metadata/history success cannot use cached provenance")};
            actor.client.validate_chat_view(&candidate).unwrap();
            let receipt=ChatRefreshDurableReceipt{ciphertext_sha256:candidate.ciphertext_sha256().unwrap(),credential_revision:candidate.credential_revision()};
            let generation=actor.store.generation_guard();actor.persist().await.unwrap();
            let publication=NativeCanonicalChatPublication{publication:actor.client.commit_chat_view(candidate,receipt).unwrap(),store_generation:generation};
            let mut ui=Ui::new();ui.set_authenticated(true);
            let cached=actor.cached_views.borrow().clone().unwrap().views.publish(CHAT,CancellationToken::new()).unwrap().unwrap().into_window().unwrap();
            ui.set_cached_chat(cached.chat);
            match change {
                "request"=>request.cancel(),
                "owner-key"=>{
                    let mut session=actor.client.clone_session().unwrap();session.master_key=zeroize::Zeroizing::new([8;32]);
                    let api=session.api_url.clone();actor.client.reset(&api,Some(session)).unwrap();
                },
                "store"=>actor.store.revoke().await.unwrap(),
                "none"=>{},_=>unreachable!(),
            }
            apply_canonical_chat(&mut ui,publication);
            assert!(!ui.is_cached_chat_read_only());
            if change=="none" {assert!(cached_frame(&mut ui).contains("CACHED_RENDER_READY"));}
            else {assert!(!cached_frame(&mut ui).contains("CACHED_RENDER_READY"),"rejected canonical must not reopen content: {change}");}
            actor.live_monitor.take();server.await.unwrap();
        }
    }).await.unwrap();
}

#[tokio::test]
async fn boot_admits_real_username_and_cached_home_before_pending_first_global_sync() {
    tokio::time::timeout(Duration::from_secs(20),async {
        let started=std::sync::Arc::new(tokio::sync::Notify::new());
        let release=std::sync::Arc::new(tokio::sync::Notify::new());
        // Preserve the original ordering/fallback contract and its third
        // canonical request using an unadvertised legacy inventory peer.
        // Complete correlated reuse is tested independently below.
        let (api,release_hint,server,requests)=live_peer_observed_config(false,Some((started.clone(),release.clone())),false).await;
        let (_directory,mut actor)=super::tests::fixture().await;
        let mut session=actor.client.clone_session().unwrap();session.api_url=api.clone();
        actor.client.reset(&api,Some(session)).unwrap();
        actor.client.restore_ciphertext_snapshot(&owned_cached_snapshot(6)).unwrap();
        actor.persist().await.unwrap();
        let receiver=actor.cached_views.subscribe();
        let (send,mut receive)=mpsc::channel(32);
        let boot=tokio::spawn(async move {let result=actor.boot(&send,Stamp::default()).await;(actor,result)});
        started.notified().await;
        assert!(!boot.is_finished(),"canonical global discovery must actually be pending");
        let mut auth_count=0;let mut cached_home=false;
        while let Ok(reply)=receive.try_recv() {
            match reply.view {
                View::AdmittedAuth(publication)=>{
                    auth_count+=1;let (username,_)=publication.into_auth().unwrap();
                    assert_eq!(username,"FixtureOwner","first greeting uses the actual first server principal");
                },
                View::Items(Workspace::Chats,items)=>{cached_home|=items.iter().any(|item|item.id==CHAT);},
                View::Done=>panic!("global completion cannot precede held global discovery"),
                _=>{},
            }
        }
        assert_eq!(auth_count,1);assert!(cached_home);
        let lane=receiver.borrow().clone().unwrap();
        let view=lane.views.publish(CHAT,CancellationToken::new()).unwrap().unwrap().into_window().unwrap();
        assert!(view.cached && view.refreshing && !view.history_complete);
        assert_eq!(view.chat.messages.len(),6);
        assert_eq!(requests.load(std::sync::atomic::Ordering::SeqCst),2,"one first admission + the held first global discovery auth");
        release.notify_one();
        let (mut actor,result)=boot.await.unwrap();result.unwrap();
        while let Ok(reply)=receive.try_recv(){assert!(!matches!(reply.view,View::AdmittedAuth(_)),"duplicate authorized/validate block must not reissue a greeting");}
        assert_eq!(requests.load(std::sync::atomic::Ordering::SeqCst),3,"first monitor + recovery + unchanged final canonical list; no middle validation or second monitor check");
        actor.live_monitor.take();drop(release_hint);server.await.unwrap();
    }).await.unwrap();
}
#[tokio::test]
async fn queued_initial_auth_is_negative_fenced_without_extending_cache_reader_lifetime() {
    tokio::time::timeout(Duration::from_secs(20),async {
        for change in ["cancel","owner-key","store","closed-reader-only","none"] {
            let (_directory,mut actor,server)=prepared_actor().await;
            let receiver=stage_owned_cached_actor(&mut actor).await;
            let owner=receiver.borrow().clone().unwrap();
            let request=CancellationToken::new();
            let publication=NativeAuthPublication{owner:owner.clone(),request:request.clone(),username:"FixtureOwner".into(),expires_at:None};
            match change {
                "cancel"=>request.cancel(),
                "owner-key"=>{let mut session=actor.client.clone_session().unwrap();session.master_key=Zeroizing::new([8;32]);let api=session.api_url.clone();actor.client.reset(&api,Some(session)).unwrap();},
                "store"=>actor.store.revoke().await.unwrap(),
                "closed-reader-only"=>owner.views.close(),
                "none"=>{},_=>unreachable!(),
            }
            if matches!(change,"closed-reader-only"|"none") {
                assert_eq!(publication.into_auth().unwrap().0,"FixtureOwner");
                if change=="closed-reader-only"{assert!(owner.views.publish(CHAT,CancellationToken::new()).is_err(),"negative observer cannot reopen cache model lifetime");}
            } else {assert!(publication.into_auth().is_err(),"{change}");}
            actor.live_monitor.take();server.await.unwrap();
        }
    }).await.unwrap();
}
#[tokio::test]
async fn known_initial_monitor_denial_never_issues_auth_even_before_global_recovery() {
    tokio::time::timeout(Duration::from_secs(15),async {
        let (_directory,mut actor,server)=prepared_actor_mode(true).await;
        let (send,mut receive)=mpsc::channel(16);
        assert!(actor.authorized(&send,Stamp::default()).await.is_err());
        let mut denial=false;
        while let Ok(reply)=receive.try_recv(){
            assert!(!matches!(reply.view,View::AdmittedAuth(_)));
            denial|=matches!(reply.view,View::Monitor(Error::Expired|Error::Forbidden|Error::Authentication,_));
        }
        assert!(denial);
        actor.live_monitor.take();server.await.unwrap();
    }).await.unwrap();
}

#[tokio::test]
async fn boot_consumes_one_current_empty_inventory_for_the_same_final_list_without_another_sync() {
    tokio::time::timeout(Duration::from_secs(15),async {
        let (api,release_hint,server,requests)=live_peer_observed_config(false,None,true).await;
        let (_directory,mut actor)=super::tests::fixture().await;
        let mut session=actor.client.clone_session().unwrap();session.api_url=api.clone();
        actor.client.reset(&api,Some(session)).unwrap();
        actor.client.set_interactive(true);actor.client.set_identity(openmates_sdk::ClientIdentity::Cli);
        actor.client.restore_ciphertext_snapshot(&owned_cached_snapshot(6)).unwrap();
        let history=actor.client.ciphertext_snapshot()["history"].clone();actor.persist().await.unwrap();
        let (send,mut receive)=mpsc::channel(32);
        actor.boot(&send,Stamp::default()).await.unwrap();
        let mut auth=0;let mut final_items=None;
        while let Ok(reply)=receive.try_recv(){match reply.view {
            View::AdmittedAuth(publication)=>{auth+=1;assert_eq!(publication.into_auth().unwrap().0,"FixtureOwner");},
            View::Items(Workspace::Chats,items)=>final_items=Some(items),_=>{},
        }}
        assert_eq!(auth,1);
        let items=final_items.unwrap();assert_eq!(items.len(),1);assert_eq!(items[0].id,CHAT);
        assert_eq!(requests.load(std::sync::atomic::Ordering::SeqCst),2,"first monitor + original complete recovery inventory; final list consumes the existing proof");
        assert_eq!(actor.client.ciphertext_snapshot()["history"],history,"metadata inventory cannot replace or promote selected full history");
        let durable=actor.store.load(actor.passphrase.clone()).await.unwrap().unwrap();
        let persisted=actor.store.read_cache(durable.hashed_email.clone(),cache_key(&durable),durable.master_key.clone()).await.unwrap().unwrap();
        assert_eq!(persisted,actor.client.ciphertext_snapshot(),"original final credential/cache save actually completed");
        let lane=actor.cached_views.borrow().clone().unwrap();
        let cached=lane.views.publish(CHAT,CancellationToken::new()).unwrap().unwrap().into_window().unwrap();
        assert!(cached.cached && !cached.history_complete);
        actor.live_monitor.take();drop(release_hint);server.await.unwrap();
    }).await.unwrap();
}
#[tokio::test]
async fn real_monitor_traffic_after_boot_inventory_forces_the_original_final_list_sync() {
    tokio::time::timeout(Duration::from_secs(15),async {
        let (api,release_hint,server,requests)=live_peer_observed_config(false,None,true).await;
        let (_directory,mut actor)=super::tests::fixture().await;
        let mut session=actor.client.clone_session().unwrap();session.api_url=api.clone();
        actor.client.reset(&api,Some(session)).unwrap();
        actor.client.set_interactive(true);actor.client.set_identity(openmates_sdk::ClientIdentity::Cli);
        actor.client.restore_ciphertext_snapshot(&owned_cached_snapshot(6)).unwrap();actor.persist().await.unwrap();
        let (send,_receive)=mpsc::channel(32);
        let proof=actor.authorized_with_inventory(&send,Stamp::default(),true).await.unwrap().expect("actual complete empty peer inventory");
        assert_eq!(requests.load(std::sync::atomic::Ordering::SeqCst),2);
        let monitor=actor.live_monitor.as_ref().unwrap();
        assert!(monitor.take_pending().unwrap().is_some());
        release_hint.send(()).unwrap();monitor.changed().await.unwrap();
        let items=actor.client.list_with_fresh_chat_inventory(Workspace::Chats,proof,&actor.live_cancel).await.unwrap();
        actor.persist().await.unwrap();
        assert_eq!(items.len(),1);assert_eq!(items[0].id,CHAT);
        assert_eq!(requests.load(std::sync::atomic::Ordering::SeqCst),3,"real keyless monitor frame invalidates reuse while Client stays exclusively owned");
        actor.live_monitor.take();server.await.unwrap();
    }).await.unwrap();
}

// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
#[tokio::test]
async fn cache_settlement_native_final_save_and_delayed_consumption_keep_store_request_and_key_fences() {
    tokio::time::timeout(Duration::from_secs(20),async {
        for change in ["request","owner-key","store","none"] {
            let (_directory,mut actor)=super::tests::fixture().await;
            let snapshot=owned_cached_snapshot(70);let metadata=snapshot["chats"][CHAT].clone();
            let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let api=format!("http://{}",listener.local_addr().unwrap());
            let server=tokio::spawn(async move {
                let (mut auth,_)=listener.accept().await.unwrap();
                assert_eq!(read_http(&mut auth).await,"POST /v1/auth/session HTTP/1.1");
                respond_http(&mut auth,json!({"success":true,"ws_token":"synthetic-token","user":{"id":"fixture-owner","username":"FixtureOwner"}})).await;
                let (mut wire,_)=listener.accept().await.unwrap();
                assert_eq!(read_http(&mut wire).await,"POST /v1/chats/metadata/batch HTTP/1.1");
                respond_http(&mut wire,json!({"chats":[metadata]})).await;
                // Closing after exactly one metadata read also denies any
                // accidental warm all-history request in this regression.
            });
            let mut session=actor.client.clone_session().unwrap();session.api_url=api.clone();
            actor.client.reset(&api,Some(session)).unwrap();actor.client.validate_session().await.unwrap();
            actor.client.restore_ciphertext_snapshot(&snapshot).unwrap();actor.persist().await.unwrap();
            let request=CancellationToken::new();actor.client.set_operation_cancel(request.clone());
            let ChatViewRead::CacheSettled(candidate)=actor.client.read_chat_view_prefer_cache(None,CHAT,request.clone()).await.unwrap()
                else {panic!("warm cache cannot wait for full history")};
            actor.client.validate_cache_settlement(&candidate).unwrap();
            let receipt=ChatRefreshDurableReceipt{ciphertext_sha256:candidate.ciphertext_sha256().unwrap(),credential_revision:candidate.credential_revision()};
            let generation=actor.store.generation_guard();actor.persist().await.unwrap();
            let publication=NativeCacheSettlementPublication{publication:actor.client.commit_cache_settlement(candidate,receipt).unwrap(),store_generation:generation};
            let session=actor.client.clone_session().unwrap();
            let persisted=actor.store.read_cache(session.hashed_email.clone(),cache_key(&session),session.master_key.clone()).await.unwrap().unwrap();
            assert_eq!(persisted["history"][CHAT].as_array().unwrap().len(),70);
            assert!(!persisted.to_string().contains("CACHED_RENDER_READY"));
            match change {
                "request"=>request.cancel(),
                "owner-key"=>{let mut session=actor.client.clone_session().unwrap();session.master_key=zeroize::Zeroizing::new([8;32]);let api=session.api_url.clone();actor.client.reset(&api,Some(session)).unwrap();},
                "store"=>actor.store.revoke().await.unwrap(),
                "none"=>{},_=>unreachable!(),
            }
            let result=publication.into_window();assert_eq!(result.is_ok(),change=="none","{change}");
            if let Ok(window)=result {
                assert_eq!(window.chat.messages.len(),70);assert!(!window.history_complete);
                let mut ui=Ui::new();ui.set_authenticated(true);ui.set_settled_chat(window.chat);
                assert!(!ui.is_cached_chat_read_only());assert!(cached_frame(&mut ui).contains("CACHED_RENDER_READY"));
            }
            server.await.unwrap();
        }
    }).await.unwrap();
}

#[tokio::test]
async fn actor_dispatch_open_runs_recovery_then_saves_and_queues_warm_settlement_without_history_io() {
    tokio::time::timeout(Duration::from_secs(20),async {
        let (_directory,mut actor)=super::tests::fixture().await;
        let snapshot=owned_cached_snapshot(70);
        let (api,release,server,requests)=live_peer_observed_config_with_cache(false,None,true,Some(snapshot.clone())).await;
        let mut session=actor.client.clone_session().unwrap();session.api_url=api.clone();
        actor.client.reset(&api,Some(session)).unwrap();
        let (send,mut receive)=mpsc::channel(32);
        actor.monitor(&send,Stamp::default()).await.unwrap();
        actor.live_monitor.as_ref().unwrap().take_pending().unwrap();
        actor.client.restore_ciphertext_snapshot(&snapshot).unwrap();actor.persist().await.unwrap();
        while receive.try_recv().is_ok() {}
        let before=requests.load(std::sync::atomic::Ordering::SeqCst);
        assert!(actor.recovery_start_needed);
        let epoch=Stamp{security:3,view:7};let cancel=CancellationToken::new();
        actor.dispatch(Request{epoch,work:Work::Command(UiCommand::Open(Workspace::Chats,CHAT.into())),cancel:cancel.clone()},&send).await.unwrap();
        assert!(!actor.recovery_start_needed && !actor.recovery_blocked,"Open must run its existing recovery gate before settling");
        assert_eq!(actor.live_selected.as_deref(),Some(CHAT));
        assert!(requests.load(std::sync::atomic::Ordering::SeqCst)>before+1,"recovery discovery and selected authorization must both run");
        let mut settlement=None;
        while let Ok(reply)=receive.try_recv() {
            assert!(!matches!(&reply.view,View::CanonicalChat(_)|View::Chat(_)),"warm cache may not become canonical history");
            if let View::CacheSettled(publication)=reply.view {assert!(reply.epoch==epoch);settlement=Some(publication);}
        }
        let publication=settlement.expect("actual dispatch must route a sealed cache-settlement reply");
        let session=actor.client.clone_session().unwrap();
        let persisted=actor.store.read_cache(session.hashed_email.clone(),cache_key(&session),session.master_key.clone()).await.unwrap().unwrap();
        assert_eq!(persisted["history"][CHAT].as_array().unwrap().len(),70);
        assert!(!persisted.to_string().contains("CACHED_RENDER_READY"));
        let stored=actor.store.load(actor.passphrase.clone()).await.unwrap().unwrap();
        assert_eq!(stored.cookies,session.cookies,"publication must follow the exact final credential save/ACK");
        let window=publication.into_window().unwrap();assert_eq!(window.chat.messages.len(),70);assert!(!window.history_complete);
        let mut ui=Ui::new();ui.set_authenticated(true);ui.set_settled_chat(window.chat);
        assert!(!ui.is_cached_chat_read_only());assert!(cached_frame(&mut ui).contains("CACHED_RENDER_READY"));
        actor.live_monitor.take();drop(release);server.await.unwrap();
    }).await.unwrap();
}
