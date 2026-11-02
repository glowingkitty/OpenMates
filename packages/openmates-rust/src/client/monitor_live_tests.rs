//! PRIVATE DRAFT — synthetic protocol and authority checks; NOT RUN.
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message as Frame;
const CHAT: &str = "11111111-1111-4111-8111-111111111111";
const OTHER: &str = "22222222-2222-4222-8222-222222222222";

fn fixture() -> Client {
    Client::new(
        "https://api.example.com",
        Some(Session {
            api_url: "https://api.example.com".into(),
            session_id: OTHER.into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: now_ms(),
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}
fn monitor(client: &Client) -> ChatMonitor {
    ChatMonitor {
        fence: Arc::new(MonitorFence {
            owner: client.task_watch_authority.clone(),
            generation: client.generation,
            team: client.session.as_ref().unwrap().active_team_id.clone(),
            expires_at: client.session.as_ref().unwrap().paired_session_expires_at,
            cancel: CancellationToken::new(),
            alive: AtomicBool::new(true),
            denial: Mutex::new(None),
        }),
        changes: Arc::new(Changes::default()),
    }
}
fn stage(client: &Client, monitor: &ChatMonitor) -> ChatRefresh {
    ChatRefresh {
        confirmed_rewinds: BTreeSet::new(),
        fence: monitor.fence.clone(),
        revision: client.credential_revision,
        ciphertext: client.ciphertext_snapshot(),
        models: Plain::new(ChatModels {
            items: vec![],
            selection: ChatSelectionUpdate::Unchanged,
        }),
        cache_scope: None,
    }
}
fn receipt(refresh: &ChatRefresh) -> ChatRefreshDurableReceipt {
    ChatRefreshDurableReceipt {
        ciphertext_sha256: refresh.ciphertext_sha256().unwrap(),
        credential_revision: refresh.credential_revision(),
    }
}
async fn peer(frames: Vec<Value>) -> (transport::Socket, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        for frame in frames {
            ws.send(Frame::Text(frame.to_string().into()))
                .await
                .unwrap();
        }
        tokio::time::timeout(Duration::from_secs(4), async {
            while let Some(frame) = ws.next().await {
                if matches!(frame.unwrap(), Frame::Close(_)) {
                    return;
                }
            }
        })
        .await
        .unwrap();
    });
    let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    (transport::test_socket(inner), server)
}
async fn collect(frames: Vec<Value>) -> (Error, Arc<Changes>, Arc<MonitorFence>) {
    collect_in_scope(frames, None).await
}
async fn collect_in_scope(
    frames: Vec<Value>,
    team: Option<&str>,
) -> (Error, Arc<Changes>, Arc<MonitorFence>) {
    let mut client = fixture();
    if let Some(team) = team {
        client.set_team(Some(team)).unwrap();
    }
    let handle = monitor(&client);
    let changes = handle.changes.clone();
    let fence = handle.fence.clone();
    let (socket, server) = peer(frames).await;
    let (tx, mut rx) = mpsc::channel(1);
    let task = tokio::spawn(monitor_socket_mode(
        socket,
        handle.fence.cancel.clone(),
        tx,
        team.map(sha256),
        json!({"client_type":"rust","interactive":false,"is_foreground":true}),
        Duration::from_secs(25),
        Some(changes.clone()),
        Some(fence.clone()),
        None,
    ));
    let error = tokio::time::timeout(Duration::from_secs(4), rx.recv())
        .await
        .unwrap()
        .unwrap();
    task.await.unwrap();
    server.await.unwrap();
    (error, changes, fence)
}
#[tokio::test]
async fn mixed_canonical_event_and_type_frames_refresh_without_retaining_contents() {
    let (error,changes,fence)=collect(vec![
        json!({"event":"chat_draft_updated","chat_id":CHAT,"data":{"encrypted_draft_md":"opaque-fixture"},"versions":{"draft_v":3}}),
        json!({"event":"chat_title_updated","chat_id":CHAT,"data":{"encrypted_title":"opaque-fixture"},"versions":{"metadata_v":7}}),
        json!({"type":"new_chat_message","payload":{"chat_id":OTHER,"content":"SYNTHETIC MUST NOT ENTER MAILBOX","messages_v":2}}),
        json!({"type":"force_logout","payload":{}}),
    ]).await;
    assert_eq!(error, Error::Expired);
    assert!(!fence.valid());
    let pending = changes.pending.lock().unwrap();
    assert!(pending.refresh);
    assert_eq!(pending.chats.len(), 2);
    assert_eq!(pending.versions[CHAT].draft_v, 3);
    assert_eq!(pending.versions[CHAT].metadata_v, 7);
}
#[tokio::test]
async fn per_token_frames_do_not_schedule_http_but_final_frame_does() {
    let changes = Changes::default();
    for _ in 0..1000 {
        record_change(&changes,"ai_message_update",&json!({"chat_id":CHAT,"is_final_chunk":false,"full_content_so_far":"synthetic transient"})).unwrap();
    }
    assert!(!changes.pending.lock().unwrap().refresh);
    let (error, changes, _) = collect(vec![
        json!({"type":"ai_message_update","payload":{"chat_id":CHAT,"is_final_chunk":true}}),
        json!({"type":"force_logout","payload":{}}),
    ])
    .await;
    assert_eq!(error, Error::Expired);
    assert!(changes.pending.lock().unwrap().refresh);
}
#[tokio::test]
async fn undrained_full_hint_mailbox_cannot_hide_force_logout() {
    let mut frames = Vec::new();
    for i in 1..=250 {
        frames.push(json!({"type":"new_chat_message","payload":{"chat_id":uuid::Uuid::from_u128(i).to_string(),"messages_v":1}}));
    }
    frames.push(json!({"type":"force_logout","payload":{}}));
    let (error, changes, fence) = collect(frames).await;
    assert_eq!(error, Error::Expired);
    assert!(!fence.valid());
    let pending = changes.pending.lock().unwrap();
    assert_eq!(pending.chats.len(), MAX_HINTS);
    assert!(pending.versions.len() <= MAX_HINTS);
}
#[tokio::test]
async fn malformed_or_unknown_event_layout_is_not_generic_passthrough() {
    for frame in [
        json!({"event":"unknown_event","chat_id":CHAT,"data":{},"versions":{}}),
        json!({"event":"chat_title_updated","chat_id":"not-a-chat","data":{},"versions":{}}),
        json!({"event":"chat_draft_updated","chat_id":CHAT,"data":[],"versions":{}}),
        json!({"event":"force_logout","chat_id":CHAT,"data":{},"versions":{}}),
    ] {
        let (mut socket, server) = peer(vec![frame]).await;
        assert!(matches!(
            transport::receive_monitor(&mut socket).await,
            Err(Error::Protocol)
        ));
        close(&mut socket).await;
        server.await.unwrap();
    }
}
#[tokio::test]
async fn ordinary_receipt_receiver_keeps_its_original_wire_contract() {
    let (mut socket, server) = peer(vec![
        json!({"event":"chat_title_updated","chat_id":CHAT,"data":{},"versions":{}}),
    ])
    .await;
    assert!(matches!(
        transport::receive(&mut socket).await,
        Err(Error::Protocol)
    ));
    close(&mut socket).await;
    server.await.unwrap();
}
#[test]
fn recovery_hints_are_bounded_validated_ids_and_never_authority() {
    let changes = Changes::default();
    record_change(
        &changes,
        "metadata_jobs_available",
        &json!({"jobs":[{"job_id":OTHER,"chat_id":CHAT,"sealed_payload":"discarded"}]}),
    )
    .unwrap();
    assert!(!changes.pending.lock().unwrap().refresh);
    assert_eq!(
        changes
            .pending
            .lock()
            .unwrap()
            .recovery
            .iter()
            .cloned()
            .collect::<Vec<_>>(),
        vec![CHAT.to_owned()]
    );
    assert!(matches!(
        record_change(
            &changes,
            "recovery_jobs_available",
            &json!({"jobs":[{"job_id":"bad","chat_id":CHAT}]})
        ),
        Err(Error::Protocol)
    ));
    let too_many = (0..101)
        .map(|_| json!({"job_id":OTHER,"chat_id":CHAT}))
        .collect::<Vec<_>>();
    assert!(matches!(
        record_change(
            &changes,
            "recovery_jobs_available",
            &json!({"jobs":too_many})
        ),
        Err(Error::Protocol)
    ));
}
#[test]
fn invalid_versions_reject_before_merging_or_publishing() {
    let changes = Changes::default();
    assert!(matches!(
        record_change(
            &changes,
            "chat_draft_updated",
            &json!({"chat_id":CHAT,"versions":{"draft_v":"7"}})
        ),
        Err(Error::Protocol)
    ));
    assert!(!changes.pending.lock().unwrap().refresh);
}
#[test]
fn commit_requires_exact_durable_receipt_and_current_credential_ack() {
    let mut client = fixture();
    let handle = monitor(&client);
    let refresh = stage(&client, &handle);
    let ack = receipt(&refresh);
    assert!(matches!(
        client.commit_chat_refresh(refresh, ack),
        Err(Error::Cancelled)
    ));
    client
        .acknowledge_credentials(client.credential_revision)
        .unwrap();
    let refresh = stage(&client, &handle);
    let mut ack = receipt(&refresh);
    ack.ciphertext_sha256 = "0".repeat(64);
    assert!(matches!(
        client.commit_chat_refresh(refresh, ack),
        Err(Error::Cancelled)
    ));
    let refresh = stage(&client, &handle);
    let ack = receipt(&refresh);
    let publication = client.commit_chat_refresh(refresh, ack).unwrap();
    client.validate_chat_publication(&publication).unwrap();
    assert!(publication.into_models().is_ok());
}
#[test]
fn same_owner_data_mutation_rejects_staged_commit_without_undoing_newer_state() {
    let mut client = fixture();
    client
        .acknowledge_credentials(client.credential_revision)
        .unwrap();
    let handle = monitor(&client);
    let refresh = stage(&client, &handle);
    let ack = receipt(&refresh);
    let generation = client.generation;
    let revision = client.credential_revision;
    client.history.insert(
        CHAT.into(),
        vec![json!({"id":OTHER,"encrypted_content":"newer-ciphertext"})],
    );
    let newer = client.ciphertext_snapshot();
    assert_eq!(client.generation, generation);
    assert_eq!(client.credential_revision, revision);
    assert!(matches!(
        client.validate_chat_refresh(&refresh),
        Err(Error::Cancelled)
    ));
    assert!(matches!(
        client.commit_chat_refresh(refresh, ack),
        Err(Error::Cancelled)
    ));
    assert_eq!(client.ciphertext_snapshot(), newer);
}
#[test]
fn delayed_publication_requires_short_lane_data_revalidation() {
    let mut client = fixture();
    client
        .acknowledge_credentials(client.credential_revision)
        .unwrap();
    let handle = monitor(&client);
    let refresh = stage(&client, &handle);
    let ack = receipt(&refresh);
    let publication = client.commit_chat_refresh(refresh, ack).unwrap();
    client.chats.insert(
        CHAT.into(),
        json!({"id":CHAT,"encrypted_title":"later-ciphertext"}),
    );
    assert!(matches!(
        client.validate_chat_publication(&publication),
        Err(Error::Cancelled)
    ));
    // is_valid is only the negative owner/instance/TTL seal. It is deliberately
    // not a claim that this immutable read is current after another operation.
    assert!(publication.is_valid());
}
#[test]
fn team_change_logout_and_monitor_replacement_invalidate_pending_plaintext() {
    let mut client = fixture();
    let handle = monitor(&client);
    let refresh = stage(&client, &handle);
    client.set_team(Some(OTHER)).unwrap();
    assert!(matches!(
        refresh.ciphertext_snapshot(),
        Err(Error::Cancelled)
    ));
    let handle = monitor(&client);
    let refresh = stage(&client, &handle);
    handle.close();
    assert!(matches!(
        client.validate_chat_refresh(&refresh),
        Err(Error::Cancelled)
    ));
    let handle = monitor(&client);
    let refresh = stage(&client, &handle);
    client.clear_account_cache();
    assert!(matches!(
        client.validate_chat_refresh(&refresh),
        Err(Error::Cancelled)
    ));
}
#[test]
fn absolute_paired_expiry_invalidates_stage_independent_of_cookie_rotation() {
    let mut client = fixture();
    client.session.as_mut().unwrap().paired_session_expires_at = Some(0);
    let handle = monitor(&client);
    assert!(!handle.is_valid());
}

async fn metadata_peer(rows: Vec<Value>) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = Vec::new();
        let mut chunk = [0; 2048];
        let end = loop {
            let n = stream.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            bytes.extend_from_slice(&chunk[..n]);
            if let Some(end) = bytes.windows(4).position(|x| x == b"\r\n\r\n") {
                break end + 4;
            }
        };
        let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
        assert!(headers.starts_with("POST /v1/chats/metadata/batch "));
        let len = headers
            .lines()
            .find_map(|line| {
                line.to_ascii_lowercase()
                    .strip_prefix("content-length:")
                    .map(|n| n.trim().parse::<usize>().unwrap())
            })
            .unwrap();
        while bytes.len() < end + len {
            let n = stream.read(&mut chunk).await.unwrap();
            assert!(n > 0);
            bytes.extend_from_slice(&chunk[..n]);
        }
        assert_eq!(
            serde_json::from_slice::<Value>(&bytes[end..end + len]).unwrap(),
            json!({"chat_ids":[CHAT]})
        );
        let body = json!({"chats":rows}).to_string();
        let response = format!(
            "HTTP/1.1 200 OK\r\nConnection: close\r\nSet-Cookie: auth_refresh_token=rotated-fixture; Path=/\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            body
        );
        stream.write_all(response.as_bytes()).await.unwrap();
    });
    (format!("http://{address}"), task)
}
#[tokio::test]
async fn strict_selected_absence_hides_view_but_retains_encrypted_history_and_rotation() {
    let (api, server) = metadata_peer(vec![]).await;
    let mut client = fixture();
    client.base = transport::validate_base(&api).unwrap();
    client.session.as_mut().unwrap().api_url = api;
    client.history.insert(
        CHAT.into(),
        vec![json!({"id":OTHER,"encrypted_content":"retained-ciphertext"})],
    );
    // Empty current recent list is insufficient by itself; refresh must perform
    // the exact authenticated POST verified by metadata_peer above.
    let handle = monitor(&client);
    let hint = ChatInvalidation {
        fence: handle.fence.clone(),
        pending: Pending::default(),
    };
    let refresh = client
        .refresh_chat_monitor(&handle, &hint, Some(CHAT))
        .await
        .unwrap();
    assert!(
        matches!(refresh.models.selection,ChatSelectionUpdate::Unavailable{ref chat_id} if chat_id==CHAT)
    );
    assert_eq!(
        client.history[CHAT][0]["encrypted_content"],
        "retained-ciphertext"
    );
    assert_eq!(client.cookies["auth_refresh_token"], "rotated-fixture");
    assert_eq!(refresh.credential_revision(), client.credential_revision);
    server.await.unwrap();
}

#[tokio::test]
async fn canonical_encrypted_metadata_is_decrypted_only_in_foreground_refresh() {
    let key = [9; 32];
    let row = json!({"id":CHAT,"messages_v":2,"metadata_v":3,
        "encrypted_chat_key":crypto::encrypt_bytes(&key,&[7;32]).unwrap(),
        "encrypted_title":crypto::encrypt_combined("Canonical encrypted title",&key).unwrap()});
    let (api, server) = metadata_peer(vec![row]).await;
    let mut client = fixture();
    client.base = transport::validate_base(&api).unwrap();
    client.session.as_mut().unwrap().api_url = api;
    let handle = monitor(&client);
    let mut pending = Pending::default();
    pending.chats.insert(CHAT.into());
    let hint = ChatInvalidation {
        fence: handle.fence.clone(),
        pending,
    };
    let refresh = client
        .refresh_chat_monitor(&handle, &hint, None)
        .await
        .unwrap();
    assert_eq!(refresh.models.items[0].title, "Canonical encrypted title");
    assert!(
        !refresh
            .ciphertext_snapshot()
            .unwrap()
            .to_string()
            .contains("Canonical encrypted title")
    );
    assert!(matches!(
        client.commit_chat_refresh(
            refresh,
            ChatRefreshDurableReceipt {
                ciphertext_sha256: "0".repeat(64),
                credential_revision: 0
            }
        ),
        Err(Error::Cancelled)
    ));
    server.await.unwrap();
}
#[test]
fn canonical_team_create_uses_nested_chat_id_and_completion_has_no_plaintext_dependency() {
    let changes = Changes::default();
    record_change(
        &changes,
        "team_chat_created",
        &json!({"team_id":OTHER,"chat":{"id":CHAT,"encrypted_chat_key":"opaque"}}),
    )
    .unwrap();
    record_change(
        &changes,
        "team_ai_response_completed",
        &json!({"team_id":OTHER,"chat_id":CHAT,"encrypted_content":"opaque"}),
    )
    .unwrap();
    assert_eq!(
        changes
            .pending
            .lock()
            .unwrap()
            .chats
            .iter()
            .cloned()
            .collect::<Vec<_>>(),
        vec![CHAT.to_owned()]
    );
}

async fn http_script(
    steps: Vec<(&'static str, String, u16, Value)>,
) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        for (method, path, status, body) in steps {
            let (mut stream, _) = tokio::time::timeout(Duration::from_secs(4), listener.accept())
                .await
                .unwrap()
                .unwrap();
            let mut bytes = Vec::new();
            let mut chunk = [0; 2048];
            let end = loop {
                let n = stream.read(&mut chunk).await.unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&chunk[..n]);
                if let Some(end) = bytes.windows(4).position(|x| x == b"\r\n\r\n") {
                    break end + 4;
                }
            };
            let headers = String::from_utf8(bytes[..end].to_vec()).unwrap();
            assert!(headers.starts_with(&format!("{method} {path} ")));
            let len = headers
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|n| n.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            while bytes.len() < end + len {
                let n = stream.read(&mut chunk).await.unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&chunk[..n]);
            }
            if method == "POST" {
                assert_eq!(
                    serde_json::from_slice::<Value>(&bytes[end..end + len]).unwrap(),
                    json!({"chat_ids":[CHAT]})
                );
            }
            let body = body.to_string();
            let response = format!(
                "HTTP/1.1 {status} Fixture\r\nConnection: close\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=rotated-fixture; Path=/\r\nContent-Length: {}\r\n\r\n{}",
                body.len(),
                body
            );
            stream.write_all(response.as_bytes()).await.unwrap();
        }
    });
    (format!("http://{address}"), task)
}
fn point_hint(handle: &ChatMonitor) -> ChatInvalidation {
    let mut pending = Pending::default();
    pending.chats.insert(CHAT.into());
    ChatInvalidation {
        fence: handle.fence.clone(),
        pending,
    }
}
fn attach_api(client: &mut Client, api: &str) {
    client.base = transport::validate_base(api).unwrap();
    client.session.as_mut().unwrap().api_url = api.into();
}
#[tokio::test]
async fn canonical_saved_absence_404_keeps_history_and_does_not_fallback_to_draft() {
    let (api, server) = http_script(vec![(
        "POST",
        "/v1/chats/metadata/batch".into(),
        404,
        json!({"detail":"Chat not found"}),
    )])
    .await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    client.chats.insert(
        CHAT.into(),
        json!({"id":CHAT,"encrypted_chat_key":"old-wrapper","messages_v":1}),
    );
    client
        .history
        .insert(CHAT.into(), vec![json!({"encrypted_content":"preserved"})]);
    let handle = monitor(&client);
    let refreshed = client
        .refresh_chat_monitor(&handle, &point_hint(&handle), Some(CHAT))
        .await
        .unwrap();
    assert!(matches!(
        refreshed.models.selection,
        ChatSelectionUpdate::Unavailable { .. }
    ));
    assert_eq!(client.history[CHAT][0]["encrypted_content"], "preserved");
    server.await.unwrap();
}
#[tokio::test]
async fn existing_personal_draft_refresh_reuses_strict_authoritative_draft_path() {
    let old = crypto::encrypt_combined("old draft", &[7; 32]).unwrap();
    let encrypted = crypto::encrypt_combined("External canonical draft", &[7; 32]).unwrap();
    let (api, server) = http_script(vec![
        ("POST", "/v1/chats/metadata/batch".into(), 404, json!({})),
        ("POST", "/v1/chats/metadata/batch".into(), 404, json!({})),
        (
            "GET",
            format!("/v1/drafts/{CHAT}"),
            200,
            json!({"draft":{"chat_id":CHAT,"draft_v":3,"encrypted_draft_md":encrypted}}),
        ),
    ])
    .await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    client.user = json!({"id":"fixture-owner"});
    client.chats.insert(
        CHAT.into(),
        json!({"id":CHAT,"draft_v":2,"encrypted_draft_md":old}),
    );
    let handle = monitor(&client);
    let refresh = client
        .refresh_chat_monitor(&handle, &point_hint(&handle), Some(CHAT))
        .await
        .unwrap();
    assert!(
        matches!(refresh.models.selection,ChatSelectionUpdate::Updated(ref chat) if chat.title=="External canonical draft")
    );
    assert_eq!(client.chats[CHAT]["draft_v"], 3);
    assert!(client.chats[CHAT].get("encrypted_chat_key").is_none());
    assert!(
        !refresh
            .ciphertext_snapshot()
            .unwrap()
            .to_string()
            .contains("External canonical draft")
    );
    server.await.unwrap();
}
#[tokio::test]
async fn strict_draft_null_clears_only_proven_keyless_shell() {
    let (api, server) = http_script(vec![
        ("POST", "/v1/chats/metadata/batch".into(), 404, json!({})),
        ("POST", "/v1/chats/metadata/batch".into(), 404, json!({})),
        (
            "GET",
            format!("/v1/drafts/{CHAT}"),
            200,
            json!({"draft":null}),
        ),
    ])
    .await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    client.user = json!({"id":"fixture-owner"});
    client.chats.insert(CHAT.into(),json!({"id":CHAT,"draft_v":2,"encrypted_draft_md":crypto::encrypt_combined("old",&[7;32]).unwrap()}));
    client.history.insert(CHAT.into(), vec![]);
    let handle = monitor(&client);
    let refresh = client
        .refresh_chat_monitor(&handle, &point_hint(&handle), Some(CHAT))
        .await
        .unwrap();
    assert!(matches!(
        refresh.models.selection,
        ChatSelectionUpdate::Unavailable { .. }
    ));
    assert!(!client.chats.contains_key(CHAT));
    server.await.unwrap();
}
#[tokio::test]
async fn absent_recent_row_with_exact_authorized_saved_chat_is_not_deleted() {
    let key = [9; 32];
    let row = json!({"id":CHAT,"messages_v":1,"encrypted_chat_key":crypto::encrypt_bytes(&key,&[7;32]).unwrap(),"encrypted_title":crypto::encrypt_combined("Old valid chat",&key).unwrap()});
    let (api,server)=http_script(vec![
        ("POST","/v1/chats/metadata/batch".into(),200,json!({"chats":[row.clone()]})),
        ("POST","/v1/chats/metadata/batch".into(),200,json!({"chats":[row]})),
        ("GET",format!("/v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false"),200,json!({"messages":[],"has_more_before":false})),
    ]).await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    assert!(client.chats.is_empty());
    let handle = monitor(&client);
    let refresh = client
        .refresh_chat_monitor(&handle, &point_hint(&handle), Some(CHAT))
        .await
        .unwrap();
    assert!(
        matches!(refresh.models.selection,ChatSelectionUpdate::Updated(ref chat) if chat.title=="Old valid chat")
    );
    server.await.unwrap();
}
#[tokio::test]
async fn canonical_read_below_announced_version_has_no_plaintext_publication() {
    let row = json!({"id":CHAT,"messages_v":1});
    let (api, server) = metadata_peer(vec![row]).await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    let handle = monitor(&client);
    let mut hint = point_hint(&handle);
    hint.pending.versions.insert(
        CHAT.into(),
        VersionFloor {
            messages_v: 2,
            ..Default::default()
        },
    );
    assert!(matches!(
        client.refresh_chat_monitor(&handle, &hint, None).await,
        Err(Error::Offline)
    ));
    server.await.unwrap();
}

#[tokio::test]
async fn selected_team_accepts_own_encrypted_hints_but_not_foreign_team_hints() {
    let selected = "33333333-3333-4333-8333-333333333333";
    let (error,changes,_)=collect_in_scope(vec![
        json!({"type":"team_chat_message_created","payload":{"team_id":OTHER,"chat_id":OTHER,"encrypted_content":"foreign opaque"}}),
        json!({"type":"team_chat_message_created","payload":{"team_id":selected,"chat_id":CHAT,"encrypted_content":"selected opaque"}}),
        json!({"type":"force_logout","payload":{}}),
    ],Some(selected)).await;
    assert_eq!(error, Error::Expired);
    assert_eq!(
        changes
            .pending
            .lock()
            .unwrap()
            .chats
            .iter()
            .cloned()
            .collect::<Vec<_>>(),
        vec![CHAT.to_owned()]
    );
}
#[tokio::test]
async fn ping_pong_control_is_preserved_by_new_monitor_decoder() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (stream, _) = listener.accept().await.unwrap();
        let mut socket = tokio_tungstenite::accept_async(stream).await.unwrap();
        socket
            .send(Frame::Ping(vec![1, 2, 3].into()))
            .await
            .unwrap();
        assert!(
            matches!(tokio::time::timeout(Duration::from_secs(2),socket.next()).await.unwrap().unwrap().unwrap(),Frame::Pong(bytes) if bytes.as_ref()==[1,2,3])
        );
        socket
            .send(Frame::Text(
                json!({"type":"force_logout","payload":{}})
                    .to_string()
                    .into(),
            ))
            .await
            .unwrap();
        assert!(matches!(
            socket.next().await.unwrap().unwrap(),
            Frame::Close(_)
        ));
    });
    let (inner, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
        .await
        .unwrap();
    let mut socket = transport::test_socket(inner);
    assert!(matches!(
        transport::receive_monitor(&mut socket).await,
        Err(Error::Expired)
    ));
    close(&mut socket).await;
    server.await.unwrap();
}

#[tokio::test]
async fn undrained_hints_do_not_hide_selected_team_revocation() {
    let team = "33333333-3333-4333-8333-333333333333";
    let (error,changes,fence)=collect_in_scope(vec![
        json!({"type":"team_chat_message_created","payload":{"team_id":team,"chat_id":CHAT,"encrypted_content":"opaque"}}),
        json!({"type":"project_remote_access_revoked","payload":{"context_type":"team","context_id_hash":sha256(team)}}),
    ],Some(team)).await;
    assert_eq!(error, Error::Forbidden);
    assert!(!fence.valid());
    assert!(changes.pending.lock().unwrap().refresh);
}

#[tokio::test]
async fn legacy_error_only_monitor_does_not_validate_unrelated_payload_team_fields() {
    let (socket, server) = peer(vec![
        json!({"type":"unrelated_status","payload":{"team_id":17}}),
        json!({"type":"force_logout","payload":{}}),
    ])
    .await;
    let (tx, mut rx) = mpsc::channel(1);
    let task = tokio::spawn(monitor_socket(
        socket,
        CancellationToken::new(),
        tx,
        None,
        json!({"client_type":"rust"}),
        Duration::from_secs(25),
    ));
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(4), rx.recv())
            .await
            .unwrap(),
        Some(Error::Expired)
    );
    task.await.unwrap();
    server.await.unwrap();
}

#[tokio::test]
async fn exact_team_metadata_403_invalidates_existing_publication_before_return() {
    let (api, server) = http_script(vec![(
        "POST",
        format!("/v1/chats/metadata/batch?team_id={OTHER}"),
        403,
        json!({"detail":"TEAM_PERMISSION_DENIED"}),
    )])
    .await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    client.set_team(Some(OTHER)).unwrap();
    client.history.insert(
        CHAT.into(),
        vec![json!({"encrypted_content":"retain encrypted history"})],
    );
    client
        .acknowledge_credentials(client.credential_revision)
        .unwrap();
    let handle = monitor(&client);
    let staged = stage(&client, &handle);
    let ack = receipt(&staged);
    let publication = client.commit_chat_refresh(staged, ack).unwrap();
    let before = client.ciphertext_snapshot();
    assert!(matches!(
        client
            .refresh_chat_monitor(&handle, &point_hint(&handle), Some(CHAT))
            .await,
        Err(Error::Forbidden)
    ));
    assert!(!handle.is_valid());
    assert!(!publication.is_valid());
    assert!(publication.models().is_err());
    assert!(matches!(
        handle.access_denial().unwrap(),
        Some(ChatMonitorAccessDenial::ScopeRevoked)
    ));
    assert_eq!(before, client.ciphertext_snapshot());
    assert_eq!(client.cookies["auth_refresh_token"], "rotated-fixture");
    server.await.unwrap();
}
#[tokio::test]
async fn personal_metadata_denial_closes_publication_but_does_not_revoke_whole_owner() {
    let (api, server) = http_script(vec![(
        "POST",
        "/v1/chats/metadata/batch".into(),
        403,
        json!({"detail":"denied"}),
    )])
    .await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    let handle = monitor(&client);
    let owner = client.task_watch_authority.clone();
    assert!(matches!(
        client
            .refresh_chat_monitor(&handle, &point_hint(&handle), Some(CHAT))
            .await,
        Err(Error::Forbidden)
    ));
    assert!(
        matches!(handle.access_denial().unwrap(),Some(ChatMonitorAccessDenial::ChatUnavailable{chat_id}) if chat_id==CHAT)
    );
    assert!(!handle.is_valid());
    assert!(!owner.cancel.is_cancelled());
    assert!(client.session.is_some());
    server.await.unwrap();
}
#[tokio::test]
async fn unconfirmed_lower_count_preserves_prior_cache_on_read_failure() {
    let (api, server) = metadata_peer(vec![json!({"id":CHAT,"messages_v":1})]).await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    client.chats.insert(
        CHAT.into(),
        json!({"id":CHAT,"messages_v":5,"encrypted_title":"known-newer-ciphertext"}),
    );
    let before = client.ciphertext_snapshot();
    let handle = monitor(&client);
    let mut hint = point_hint(&handle);
    hint.pending.versions.insert(
        CHAT.into(),
        VersionFloor {
            messages_v: 5,
            ..Default::default()
        },
    );
    assert!(matches!(
        client.refresh_chat_monitor(&handle, &hint, None).await,
        Err(Error::Offline)
    ));
    assert_eq!(client.ciphertext_snapshot(), before);
    server.await.unwrap();
}
#[test]
fn cancelled_read_hint_can_be_requeued_only_for_its_same_valid_instance() {
    let mut client = fixture();
    let handle = monitor(&client);
    record_change(
        &handle.changes,
        "new_chat_message",
        &json!({"chat_id":CHAT,"versions":{"messages_v":3}}),
    )
    .unwrap();
    let hint = handle.take_pending().unwrap().unwrap();
    client.operation_cancel.cancel();
    handle.requeue(hint).unwrap();
    let retried = handle.take_pending().unwrap().unwrap();
    assert!(retried.pending.refresh);
    assert!(retried.pending.chats.contains(CHAT));
    assert_eq!(retried.pending.versions.get(CHAT).unwrap().messages_v, 3);
    client.set_team(Some(OTHER)).unwrap();
    assert!(matches!(handle.requeue(retried), Err(Error::Cancelled)));
}

fn team_row() -> Value {
    let key = [9; 32];
    json!({"id":CHAT,"team_id":OTHER,"messages_v":1,
        "encrypted_title":crypto::encrypt_combined("Team canonical title",&key).unwrap(),
        "chat_key_wrappers":[{"hashed_chat_id":sha256(CHAT),"hashed_team_id":sha256(OTHER),"key_type":"team","encrypted_chat_key":crypto::encrypt_bytes(&key,&[8;32]).unwrap()}]})
}
async fn nested_team_denial(steps: Vec<(&'static str, String, u16, Value)>, cached_key: bool) {
    let (api, server) = http_script(steps).await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    client.set_team(Some(OTHER)).unwrap();
    if cached_key {
        client.team_key = Some((OTHER.into(), zeroize::Zeroizing::new([8; 32])));
    }
    client.history.insert(
        CHAT.into(),
        vec![json!({"encrypted_content":"prior encrypted history"})],
    );
    client
        .acknowledge_credentials(client.credential_revision)
        .unwrap();
    let handle = monitor(&client);
    let staged = stage(&client, &handle);
    let ack = receipt(&staged);
    let queued = client.commit_chat_refresh(staged, ack).unwrap();
    assert!(matches!(
        client
            .refresh_chat_monitor(&handle, &point_hint(&handle), Some(CHAT))
            .await,
        Err(Error::Forbidden)
    ));
    assert!(!queued.is_valid());
    assert!(queued.models().is_err());
    assert!(matches!(
        handle.access_denial().unwrap(),
        Some(ChatMonitorAccessDenial::ScopeRevoked)
    ));
    assert_eq!(
        client.history[CHAT][0]["encrypted_content"],
        "prior encrypted history"
    );
    assert_eq!(client.cookies["auth_refresh_token"], "rotated-fixture");
    server.await.unwrap();
}
#[tokio::test]
async fn second_selected_metadata_http403_invalidates_prior_publication() {
    let path = format!("/v1/chats/metadata/batch?team_id={OTHER}");
    nested_team_denial(
        vec![
            ("POST", path.clone(), 200, json!({"chats":[team_row()]})),
            (
                "POST",
                path,
                403,
                json!({"detail":"TEAM_PERMISSION_DENIED"}),
            ),
        ],
        true,
    )
    .await;
}
#[tokio::test]
async fn selected_history_window_http403_invalidates_prior_publication() {
    let path = format!("/v1/chats/metadata/batch?team_id={OTHER}");
    nested_team_denial(vec![
        ("POST",path.clone(),200,json!({"chats":[team_row()]})),("POST",path,200,json!({"chats":[team_row()]})),
        ("GET",format!("/v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false&team_id={OTHER}"),403,json!({"detail":"TEAM_PERMISSION_DENIED"})),
    ],true).await;
}
#[tokio::test]
async fn nested_team_wrapping_key_http403_invalidates_prior_publication() {
    let path = format!("/v1/chats/metadata/batch?team_id={OTHER}");
    nested_team_denial(
        vec![
            ("POST", path.clone(), 200, json!({"chats":[team_row()]})),
            ("POST", path, 200, json!({"chats":[team_row()]})),
            (
                "GET",
                format!("/v1/teams/{OTHER}"),
                403,
                json!({"detail":"TEAM_PERMISSION_DENIED"}),
            ),
        ],
        false,
    )
    .await;
}
#[test]
fn noncanonical_direct_permission_or_crypto_failure_is_not_team_revocation() {
    let mut client = fixture();
    client.set_team(Some(OTHER)).unwrap();
    let handle = monitor(&client);
    let mut transaction = LiveReadTransaction::new(&mut client, handle.fence.clone()).unwrap();
    assert!(
        transaction
            .monitor_read_origin(&Method::GET, "/v1/direct-chats/identity", None)
            .is_none()
    );
    assert!(!transaction.note_monitor_http_denial(403, None).unwrap());
    assert!(transaction.denied().is_none());
    assert!(handle.is_valid());
    drop(transaction);
    assert!(handle.access_denial().unwrap().is_none());
}
async fn sync_read_http(stream: &mut tokio::net::TcpStream) -> String {
    let mut bytes = Vec::new();
    let mut chunk = [0; 2048];
    loop {
        let n = stream.read(&mut chunk).await.unwrap();
        assert!(n > 0);
        bytes.extend_from_slice(&chunk[..n]);
        if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
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
async fn sync_reply(stream: &mut tokio::net::TcpStream, body: Value) {
    let body = body.to_string();
    stream.write_all(format!("HTTP/1.1 200 OK\r\nConnection: close\r\nSet-Cookie: auth_refresh_token=rotated-sync; Path=/\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
}
async fn partial_sync_peer(
    row: Value,
    stall_point_read: bool,
) -> (
    String,
    tokio::sync::oneshot::Receiver<()>,
    tokio::task::JoinHandle<()>,
) {
    partial_sync_peer_with_window(row, stall_point_read, false).await
}
async fn partial_sync_peer_with_window(
    row: Value,
    stall_point_read: bool,
    phase1_window: bool,
) -> (String,tokio::sync::oneshot::Receiver<()>,tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let (ready, seen) = tokio::sync::oneshot::channel();
    let task = tokio::spawn(async move {
        let (mut auth, _) = listener.accept().await.unwrap();
        assert_eq!(
            sync_read_http(&mut auth).await,
            "POST /v1/auth/session HTTP/1.1"
        );
        sync_reply(&mut auth,json!({"success":true,"ws_token":"synthetic-token","user":{"id":"newly-confirmed-owner"}})).await;
        drop(auth);
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
        let first: Value =
            serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap()).unwrap();
        assert_eq!(first["type"], "native_client_lifecycle");
        let requested: Value =
            serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap()).unwrap();
        assert_eq!(requested["type"], "phased_sync_request");
        if phase1_window {
            let encrypted=crypto::encrypt_combined("synthetic bounded row",&[9;32]).unwrap();
            for frame in [
                json!({"type":"phase_1_last_chat_ready","payload":{"chat_id":CHAT,"chat_details":row.clone(),"team_id":null,"context_epoch":0}}),
                json!({"type":"phase_1b_chat_content_ready","payload":{"team_id":null,"context_epoch":0,"chats":[{"chat_id":CHAT,"messages":[json!({"id":OTHER,"chat_id":CHAT,"created_at":1,"role":"assistant","encrypted_content":encrypted}).to_string()],"server_message_count":1,"message_window":{"has_more_before":false,"start_cursor":{"created_at":1,"message_id":OTHER},"oversized_message":false,"oversized_message_cursor":null}}]}}),
            ] {ws.send(Frame::Text(frame.to_string().into())).await.unwrap();}
        }
        for frame in [
            json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":[{"chat_details":row.clone()}],"embeds":[{"embed_id":OTHER,"encrypted_content":"candidate embed"}],"embed_keys":[]}}),
            json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"disabled"}}),
            json!({"type":"phased_sync_complete","payload":{}}),
        ] {
            ws.send(Frame::Text(frame.to_string().into()))
                .await
                .unwrap();
        }
        assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
        let (mut point, _) = listener.accept().await.unwrap();
        assert_eq!(
            sync_read_http(&mut point).await,
            "POST /v1/chats/metadata/batch HTTP/1.1"
        );
        let _ = ready.send(());
        if stall_point_read {
            std::future::pending::<()>().await;
        }
        // aborted by bounded owning test
        else {
            sync_reply(&mut point, json!({"chats":[row]})).await;
        }
    });
    (format!("http://{address}"), seen, task)
}
fn older_sync_row() -> Value {
    let key = [9; 32];
    json!({"id":CHAT,"messages_v":1,"encrypted_chat_key":crypto::encrypt_bytes(&key,&[7;32]).unwrap(),"encrypted_title":crypto::encrypt_combined("older candidate",&key).unwrap()})
}
fn prior_cache(client: &mut Client) {
    client.chats.insert(
        CHAT.into(),
        json!({"id":CHAT,"messages_v":5,
        "encrypted_chat_key":crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap(),
        "encrypted_title":crypto::encrypt_combined("Known newer valid title",&[9;32]).unwrap()}),
    );
    client.history.insert(CHAT.into(),vec![json!({"id":OTHER,"role":"assistant",
        "encrypted_content":crypto::encrypt_combined("Known newer valid message",&[9;32]).unwrap()})]);
    client.embeds.insert(
        CHAT.into(),
        json!({"embed_id":CHAT,"encrypted_content":"prior embed ciphertext"}),
    );
    client
        .embed_keys
        .push(json!({"embed_id":CHAT,"encrypted_key":"prior encrypted embed key"}));
}
fn full_hint(handle: &ChatMonitor) -> ChatInvalidation {
    let mut hint = point_hint(handle);
    hint.pending.refresh = true;
    hint.pending.versions.insert(
        CHAT.into(),
        VersionFloor {
            messages_v: 5,
            ..Default::default()
        },
    );
    hint
}
#[tokio::test]
async fn rejected_floor_after_real_sync_restores_only_data_and_retains_rotated_credentials() {
    let (api, _seen, server) = partial_sync_peer(older_sync_row(), false).await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    prior_cache(&mut client);
    let before = client.ciphertext_snapshot();
    let revision = client.credential_revision;
    let handle = monitor(&client);
    assert!(matches!(
        tokio::time::timeout(
            Duration::from_secs(4),
            client.refresh_chat_monitor(&handle, &full_hint(&handle), None)
        )
        .await
        .unwrap(),
        Err(Error::Offline)
    ));
    assert_eq!(client.ciphertext_snapshot(), before);
    assert_eq!(client.cookies["auth_refresh_token"], "rotated-sync");
    assert_eq!(
        client.cached_chat_items().unwrap()[0].title,
        "Known newer valid title"
    );
    assert!(client.credential_revision > revision);
    assert_eq!(client.user["id"], "newly-confirmed-owner");
    assert!(client.monitor_read_audit.is_none());
    server.await.unwrap();
}
#[tokio::test]
async fn dropped_future_after_sync_cache_assignment_restores_data_but_never_old_cookie() {
    let (api, seen, server) = partial_sync_peer(older_sync_row(), true).await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    prior_cache(&mut client);
    let before = client.ciphertext_snapshot();
    let handle = monitor(&client);
    let hint = full_hint(&handle);
    let mut read = Box::pin(client.refresh_chat_monitor(&handle, &hint, None));
    tokio::time::timeout(Duration::from_secs(4),async {
        tokio::select! {result=&mut read=>{let _=result;panic!("point read must remain pending");},result=seen=>result.unwrap(),}
    }).await.unwrap();
    drop(read);
    assert_eq!(client.ciphertext_snapshot(), before);
    assert_eq!(client.cookies["auth_refresh_token"], "rotated-sync");
    assert!(client.monitor_read_audit.is_none());
    assert!(handle.is_valid());
    server.abort();
    let _ = server.await;
}
#[test]
fn data_rollback_never_restores_logged_out_or_changed_team_context() {
    let mut client = fixture();
    prior_cache(&mut client);
    let handle = monitor(&client);
    {
        let mut transaction = LiveReadTransaction::new(&mut client, handle.fence.clone()).unwrap();
        transaction.forget_session();
    }
    assert!(client.session.is_none());
    assert!(client.chats.is_empty());
    assert!(client.monitor_read_audit.is_none());
    let mut client = fixture();
    prior_cache(&mut client);
    let handle = monitor(&client);
    {
        let mut transaction = LiveReadTransaction::new(&mut client, handle.fence.clone()).unwrap();
        transaction.set_team(Some(OTHER)).unwrap();
        transaction.chats.clear();
        transaction
            .chats
            .insert(OTHER.into(), json!({"id":OTHER,"team_id":OTHER}));
    }
    assert!(!client.chats.contains_key(CHAT));
    assert!(client.chats.contains_key(OTHER));
    assert!(client.monitor_read_audit.is_none());
}
#[test]
fn known_denial_is_never_undone_by_data_rollback_guard() {
    let mut client = fixture();
    prior_cache(&mut client);
    let handle = monitor(&client);
    {
        let mut transaction = LiveReadTransaction::new(&mut client, handle.fence.clone()).unwrap();
        transaction.chats.clear();
        assert!(
            transaction
                .note_monitor_http_denial(403, Some(MonitorReadOrigin::Chat(CHAT.into())))
                .unwrap()
        );
    }
    assert!(!handle.is_valid());
    assert!(matches!(
        handle.access_denial().unwrap(),
        Some(ChatMonitorAccessDenial::ChatUnavailable { .. })
    ));
    assert!(client.chats.is_empty());
    assert!(client.monitor_read_audit.is_none());
}

#[tokio::test]
async fn lower_count_cannot_replace_known_history_without_strict_confirmation() {
    let (api, server) = metadata_peer(vec![older_sync_row()]).await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    prior_cache(&mut client);
    let before = client.ciphertext_snapshot();
    let handle = monitor(&client);
    assert!(matches!(
        client
            .refresh_chat_monitor(&handle, &point_hint(&handle), None)
            .await,
        Err(Error::Offline)
    ));
    assert_eq!(client.ciphertext_snapshot(), before);
    assert_eq!(
        client.cached_chat_items().unwrap()[0].title,
        "Known newer valid title"
    );
    server.await.unwrap();
}
#[tokio::test]
async fn saved_chat_authoritative_no_draft_omits_tombstone_but_preserves_history() {
    let key = [9; 32];
    let row = json!({"id":CHAT,"messages_v":1,"metadata_v":2,
        "encrypted_chat_key":crypto::encrypt_bytes(&key,&[7;32]).unwrap(),"encrypted_title":crypto::encrypt_combined("Saved chat",&key).unwrap()});
    let (api, server) = metadata_peer(vec![row.clone()]).await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    let mut previous = row;
    previous["draft_v"] = json!(5);
    previous["encrypted_draft_md"] =
        json!(crypto::encrypt_combined("old user draft", &[7; 32]).unwrap());
    client.chats.insert(CHAT.into(), previous);
    client.history.insert(CHAT.into(),vec![json!({"id":OTHER,"role":"assistant","encrypted_content":crypto::encrypt_combined("Saved history",&key).unwrap()})]);
    let history = client.history.clone();
    let handle = monitor(&client);
    let mut hint = point_hint(&handle);
    hint.pending.versions.insert(
        CHAT.into(),
        VersionFloor {
            draft_v: 6,
            ..Default::default()
        },
    );
    let refresh = client
        .refresh_chat_monitor(&handle, &hint, None)
        .await
        .unwrap();
    assert!(client.chats[CHAT].get("encrypted_draft_md").is_none());
    assert_eq!(client.history, history);
    assert_eq!(refresh.models.items[0].title, "Saved chat");
    server.await.unwrap();
}

fn counted_row(count: u64) -> Value {
    json!({"id":CHAT,"messages_v":count,"metadata_v":1,
        "encrypted_chat_key":crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap(),
        "encrypted_title":crypto::encrypt_combined("Canonical count chat",&[9;32]).unwrap()})
}
fn counted_history(count: u64) -> Vec<Value> {
    (1..=count).map(|n|json!({"id":uuid::Uuid::from_u128(u128::from(n)).to_string(),"chat_id":CHAT,"role":if n%2==0 {"assistant"} else {"user"},"encrypted_content":crypto::encrypt_combined(&format!("Synthetic canonical message {n}"),&[9;32]).unwrap()})).collect()
}
fn history_path() -> String {
    format!(
        "/v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false"
    )
}
#[tokio::test]
async fn final_selected_metadata_below_first_and_hinted_count_never_publishes() {
    let first = counted_row(9);
    let mut second = first.clone();
    second["messages_v"] = json!(8);
    let (api,server)=http_script(vec![
        ("POST","/v1/chats/metadata/batch".into(),200,json!({"chats":[first.clone()]})),
        ("POST","/v1/chats/metadata/batch".into(),200,json!({"chats":[second]})),
        ("GET",history_path(),200,json!({"chat_id":CHAT,"messages_v":8,"server_message_count":8,"messages":counted_history(8),"has_more_before":false})),
    ]).await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    let mut prior = first;
    prior["messages_v"] = json!(7);
    client.chats.insert(CHAT.into(), prior);
    client.history.insert(CHAT.into(), counted_history(7));
    let before = client.ciphertext_snapshot();
    let handle = monitor(&client);
    let mut hint = point_hint(&handle);
    hint.pending.versions.insert(
        CHAT.into(),
        VersionFloor {
            messages_v: 9,
            ..Default::default()
        },
    );
    assert!(matches!(
        client
            .refresh_chat_monitor(&handle, &hint, Some(CHAT))
            .await,
        Err(Error::Offline)
    ));
    assert_eq!(client.ciphertext_snapshot(), before);
    assert_eq!(client.cookies["auth_refresh_token"], "rotated-fixture");
    server.await.unwrap();
}
async fn verified_rewind(hint_count: u64, selected: bool) {
    let row = counted_row(6);
    let (api,server)=http_script(vec![
        ("POST","/v1/chats/metadata/batch".into(),200,json!({"chats":[row.clone()]})),
        ("POST","/v1/chats/metadata/batch".into(),200,json!({"chats":[row.clone()]})),
        ("GET",history_path(),200,json!({"chat_id":CHAT,"messages_v":6,"server_message_count":6,"messages":counted_history(6),"has_more_before":false})),
    ]).await;
    let mut client = fixture();
    attach_api(&mut client, &api);
    let mut previous = row;
    previous["messages_v"] = json!(10);
    client.chats.insert(CHAT.into(), previous);
    client.history.insert(CHAT.into(), counted_history(10));
    let handle = monitor(&client);
    let mut hint = point_hint(&handle);
    hint.pending.versions.insert(
        CHAT.into(),
        VersionFloor {
            messages_v: hint_count,
            ..Default::default()
        },
    );
    let refresh = client
        .refresh_chat_monitor(&handle, &hint, selected.then_some(CHAT))
        .await
        .unwrap();
    assert_eq!(client.chats[CHAT]["messages_v"], 6);
    assert_eq!(client.history[CHAT].len(), 6);
    assert!(refresh.confirmed_rewinds.contains(CHAT));
    if selected {
        assert!(
            matches!(refresh.models.selection,ChatSelectionUpdate::Updated(ref chat) if chat.messages.len()==6)
        );
    } else {
        assert!(matches!(
            refresh.models.selection,
            ChatSelectionUpdate::Unchanged
        ));
    }
    server.await.unwrap();
}
#[tokio::test]
async fn authoritative_rewind_reduces_cached_count_and_replaces_exact_selected_history() {
    verified_rewind(6, true).await;
}
#[tokio::test]
async fn stable_rewind_can_supersede_stale_higher_count_hint_without_inventing_epoch() {
    verified_rewind(9, true).await;
}
#[tokio::test]
async fn unselected_rewind_replaces_old_cached_tail_before_later_offline_open() {
    verified_rewind(6, false).await;
}

// These draft tests drive the actual sync/monitor client against a bounded
// loopback peer. Offered background work must never become monitor authority.
async fn offered_work_sync_peer(
    read_only: bool,
    row: Value,
) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        let (mut auth, _) = listener.accept().await.unwrap();
        assert_eq!(
            sync_read_http(&mut auth).await,
            "POST /v1/auth/session HTTP/1.1"
        );
        sync_reply(
            &mut auth,
            json!({"success":true,"ws_token":"synthetic-token","user":{"id":OTHER}}),
        )
        .await;
        drop(auth);
        let (stream, _) = listener.accept().await.unwrap();
        let mut ws = tokio_tungstenite::accept_hdr_async(stream,
            move |request: &tokio_tungstenite::tungstenite::handshake::server::Request,
                  response: tokio_tungstenite::tungstenite::handshake::server::Response| {
                let query = url::form_urlencoded::parse(request.uri().query().unwrap().as_bytes())
                    .collect::<BTreeMap<_,_>>();
                let capabilities = query["client_capabilities"].split(',').collect::<BTreeSet<_>>();
                assert_eq!(capabilities.contains("task_update_jobs"), !read_only);
                assert!(!capabilities.contains("chat_metadata_recovery"));
                assert!(capabilities.contains("typed_recovery_outputs_v2"));
                Ok(response)
            }).await.unwrap();
        let expected_frames = if read_only {
            vec!["native_client_lifecycle", "phased_sync_request"]
        } else {
            vec![
                "native_client_lifecycle",
                "set_active_chat",
                "phased_sync_request",
            ]
        };
        for expected in expected_frames {
            let frame: Value =
                serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                    .unwrap();
            assert_eq!(frame["type"], expected);
        }
        let delivery = json!({"delivery_id":OTHER,"chat_id":CHAT,"message_id":OTHER,"status":"delivery_pending"});
        let mut frames = vec![
            json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":[{"chat_details":row.clone()}]}}),
            json!({"type":"workflow_chat_deliveries_available","payload":{"deliveries":[delivery]}}),
        ];
        if read_only {
            // Valid live task and replay summaries would trigger preflight /
            // claims / persistence in ordinary sync. Monitor must ignore them.
            frames.push(
                json!({"type":"task_update_jobs_available","payload":{"jobs":[{
                "job_id":"synthetic-live-job","task_id":OTHER,"chat_id":CHAT,
                "revision":1,"task_key_version":1,"expires_at":now_ms()/1000+60}]}}),
            );
            frames.push(json!({"type":"recovery_outputs_available","payload":{"outputs":[{
                "record_id":OTHER,"root_chat_id":CHAT,"target_chat_id":CHAT,"turn_id":OTHER,
                "subject_id":"synthetic-output","output_kind":"message","output_version":1,"chat_key_version":1}]}}));
            frames.push(json!({"type":"recovery_jobs_available","payload":{"jobs":[{"job_id":OTHER,"chat_id":CHAT}]}}));
            frames.push(json!({"type":"metadata_jobs_available","payload":{"jobs":[{"job_id":OTHER,"chat_id":CHAT}]}}));
        }
        frames.extend([
            json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"completed"}}),
            json!({"type":"phased_sync_complete","payload":{}}),
        ]);
        for frame in frames {
            ws.send(Frame::Text(frame.to_string().into()))
                .await
                .unwrap();
        }
        if !read_only {
            let claim: Value =
                serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap())
                    .unwrap();
            assert_eq!(claim["type"], "workflow_chat_delivery_claim");
            assert_eq!(claim["payload"]["delivery_id"], OTHER);
            ws.send(Frame::Text(
                json!({"type":"error","payload":{
                "code":"workflow_chat_delivery_rejected","reason":"WorkflowChatDeliveryStateError",
                "request_id":claim["payload"]["request_id"],"delivery_id":OTHER}})
                .to_string()
                .into(),
            ))
            .await
            .unwrap();
        }
        // Any implicit claim, replay, persist, ack or metadata discovery on the
        // read-only lane fails this exact next-frame assertion.
        assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
        if read_only {
            let (mut point, _) = listener.accept().await.unwrap();
            assert_eq!(
                sync_read_http(&mut point).await,
                "POST /v1/chats/metadata/batch HTTP/1.1"
            );
            sync_reply(&mut point, json!({"chats":[row]})).await;
        }
    });
    (format!("http://{address}"), task)
}

#[tokio::test]
async fn monitor_snapshot_ignores_pending_background_work_even_with_foreground_recovery_enabled() {
    tokio::time::timeout(Duration::from_secs(4), async {
        let (api, server) = offered_work_sync_peer(true, older_sync_row()).await;
        let mut client = fixture();
        attach_api(&mut client, &api);
        client.active_chat = Some(CHAT.into());
        client.completion_recovery_mode = Some(CancellationToken::new());
        let main_job = crate::client::completion_recovery::CompletionRecoveryJob {
            kind: crate::client::completion_recovery::CompletionRecoveryKind::Main,
            job_id: OTHER.into(),
            chat_id: CHAT.into(),
            turn_id: Some(OTHER.into()),
            assistant_message_id: Some(OTHER.into()),
            task_id: None,
            stage: None,
            chat_key_version: 1,created_at:None,
        };
        let metadata_job = crate::client::completion_recovery::CompletionRecoveryJob {
            kind: crate::client::completion_recovery::CompletionRecoveryKind::Metadata,
            job_id: CHAT.into(),
            chat_id: CHAT.into(),
            turn_id: None,
            assistant_message_id: None,
            task_id: Some(OTHER.into()),
            stage: Some("initial".into()),
            chat_key_version: 1,created_at:None,
        };
        client
            .completion_recovery_jobs
            .insert(main_job.job_id.clone(), main_job);
        client
            .metadata_recovery_jobs
            .insert(metadata_job.job_id.clone(), metadata_job);
        let existing_main = serde_json::to_vec(&client.completion_recovery_jobs).unwrap();
        let existing_metadata = serde_json::to_vec(&client.metadata_recovery_jobs).unwrap();
        let handle = monitor(&client);
        record_change(
            &handle.changes,
            "new_chat_message",
            &json!({"chat_id":CHAT}),
        )
        .unwrap();
        let hint = handle.take_pending().unwrap().unwrap();
        let refresh = client
            .refresh_chat_monitor(&handle, &hint, None)
            .await
            .unwrap();
        assert_eq!(client.active_chat.as_deref(), Some(CHAT));
        assert!(serde_json::to_vec(&client.completion_recovery_jobs).unwrap() == existing_main);
        assert!(serde_json::to_vec(&client.metadata_recovery_jobs).unwrap() == existing_metadata);
        assert_eq!(client.cookies["auth_refresh_token"], "rotated-sync");
        assert_eq!(
            refresh.ciphertext_snapshot().unwrap()["chats"][CHAT]["id"],
            CHAT
        );
        let durable = receipt(&refresh);
        client
            .acknowledge_credentials(durable.credential_revision)
            .unwrap();
        let publication = client.commit_chat_refresh(refresh, durable).unwrap();
        assert_eq!(
            publication.models().unwrap().items[0].title,
            "older candidate"
        );
        server.await.unwrap();
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn ordinary_sync_still_advertises_task_jobs_and_claims_offered_workflow_delivery() {
    tokio::time::timeout(Duration::from_secs(4), async {
        let (api, server) = offered_work_sync_peer(false, older_sync_row()).await;
        let mut client = fixture();
        attach_api(&mut client, &api);
        client.active_chat = Some(CHAT.into());
        let items = client.sync_chats().await.unwrap();
        assert_eq!(items[0].title, "older candidate");
        server.await.unwrap();
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn opening_monitor_with_active_chat_does_not_announce_selection() {
    tokio::time::timeout(Duration::from_secs(4), async {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (mut auth, _) = listener.accept().await.unwrap();
            assert_eq!(sync_read_http(&mut auth).await, "POST /v1/auth/session HTTP/1.1");
            sync_reply(&mut auth, json!({"success":true,"ws_token":"synthetic-token","user":{"id":OTHER}})).await;
            drop(auth);
            let (stream, _) = listener.accept().await.unwrap();
            let mut ws = tokio_tungstenite::accept_hdr_async(stream,
                |request: &tokio_tungstenite::tungstenite::handshake::server::Request,
                 response: tokio_tungstenite::tungstenite::handshake::server::Response| {
                    let query = url::form_urlencoded::parse(request.uri().query().unwrap().as_bytes())
                        .collect::<BTreeMap<_,_>>();
                    let capabilities = query["client_capabilities"].split(',').collect::<BTreeSet<_>>();
                    assert!(!capabilities.contains("task_update_jobs"));
                    assert!(!capabilities.contains("chat_metadata_recovery"));
                    Ok(response)
                }).await.unwrap();
            let frame: Value = serde_json::from_str(&ws.next().await.unwrap().unwrap().into_text().unwrap()).unwrap();
            assert_eq!(frame["type"], "native_client_lifecycle");
            assert!(matches!(ws.next().await.unwrap().unwrap(), Frame::Close(_)));
        });
        let mut client = fixture();
        attach_api(&mut client, &format!("http://{address}"));
        client.active_chat = Some(CHAT.into());
        let (errors, _receiver) = mpsc::channel(1);
        let handle = client.start_chat_monitor(CancellationToken::new(), errors).await.unwrap();
        assert_eq!(client.active_chat.as_deref(), Some(CHAT));
        handle.close();
        server.await.unwrap();
    }).await.unwrap();
}

// A successful phase1b merge remains candidate data until the entire monitor
// transaction accepts. Its owned peer reaches the real following point read.
#[tokio::test]
async fn rejected_floor_after_real_phase1b_restores_exact_ciphertext_windows(){
    let (api,_seen,server)=partial_sync_peer_with_window(older_sync_row(),false,true).await;
    let mut client=fixture();attach_api(&mut client,&api);prior_cache(&mut client);
    let before=client.ciphertext_snapshot();let revision=client.credential_revision;let handle=monitor(&client);
    assert!(matches!(tokio::time::timeout(Duration::from_secs(4),client.refresh_chat_monitor(&handle,&full_hint(&handle),None)).await.unwrap(),Err(Error::Offline)));
    assert_eq!(client.ciphertext_snapshot(),before);assert!(client.sync_message_windows.is_empty());
    assert_eq!(client.cookies["auth_refresh_token"],"rotated-sync");assert!(client.credential_revision>revision);
    assert_eq!(client.user["id"],"newly-confirmed-owner");assert!(client.monitor_read_audit.is_none());server.await.unwrap();
}
#[tokio::test]
async fn dropped_future_after_real_phase1b_restores_exact_ciphertext_windows(){
    let (api,seen,server)=partial_sync_peer_with_window(older_sync_row(),true,true).await;
    let mut client=fixture();attach_api(&mut client,&api);prior_cache(&mut client);let before=client.ciphertext_snapshot();let handle=monitor(&client);let hint=full_hint(&handle);
    let mut read=Box::pin(client.refresh_chat_monitor(&handle,&hint,None));
    tokio::time::timeout(Duration::from_secs(4),async{tokio::select!{result=&mut read=>{let _=result;panic!("point read must remain pending after actual phase1b merge");},result=seen=>result.unwrap(),}}).await.unwrap();
    drop(read);assert_eq!(client.ciphertext_snapshot(),before);assert!(client.sync_message_windows.is_empty());
    assert_eq!(client.cookies["auth_refresh_token"],"rotated-sync");assert!(client.monitor_read_audit.is_none());assert!(handle.is_valid());server.abort();let _=server.await;
}

#[tokio::test]
async fn actual_phase1b_candidate_is_visible_inside_transaction_and_rolls_back_on_drop(){
    let (api,_seen,server)=partial_sync_peer_with_window(older_sync_row(),true,true).await;
    let mut client=fixture();attach_api(&mut client,&api);prior_cache(&mut client);let before=client.ciphertext_snapshot();let handle=monitor(&client);
    {let mut transaction=LiveReadTransaction::new(&mut client,handle.fence.clone()).unwrap();
     tokio::time::timeout(Duration::from_secs(4),transaction.sync_chats_for_monitor()).await.unwrap().unwrap();
     assert_eq!(transaction.sync_message_windows.len(),1);assert_eq!(transaction.sync_message_windows[CHAT].messages.len(),1);
     assert!(transaction.ciphertext_snapshot()!=before);
    }
    assert_eq!(client.ciphertext_snapshot(),before);assert!(client.sync_message_windows.is_empty());assert_eq!(client.cookies["auth_refresh_token"],"rotated-sync");
    server.abort();let _=server.await;
}

#[cfg(not(target_arch = "wasm32"))]
struct MonitorOpaqueAesPort {
    key: crate::crypto::Key,
}
#[cfg(not(target_arch = "wasm32"))]
impl crate::crypto::master::MasterCrypto for MonitorOpaqueAesPort {
    fn encrypt<'a>(&'a self, iv: &'a [u8;12], plaintext: &'a [u8]) -> crate::crypto::master::MasterCryptoFuture<'a> {
        Box::pin(async move { crate::crypto::encrypt_aead(plaintext,&self.key,iv,&[]).map(zeroize::Zeroizing::new) })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8;12], ciphertext: &'a [u8]) -> crate::crypto::master::MasterCryptoFuture<'a> {
        Box::pin(async move { crate::crypto::decrypt_aead(ciphertext,&self.key,iv,&[]) })
    }
}
#[cfg(not(target_arch = "wasm32"))]
#[tokio::test]
async fn queued_monitor_release_rejects_genuine_opaque_resource_revocation_with_owner_operation_and_monitor_healthy() {
    // Restrictive queued-release UNIT fixture only. It fabricates no read,
    // authentication, canonical or durable ACK receipt. The actual captured
    // opaque resource decrypts the model; no native Session survives conversion.
    let mut client=fixture();client.user=json!({"id":OTHER});
    let mut browser=super::super::credentials::BrowserCredentials::from_native_session(client.session.take().unwrap());
    let master=crate::crypto::master::MasterCapability::opaque_for_test(Arc::new(MonitorOpaqueAesPort{key:zeroize::Zeroizing::new([7;32])}));
    browser.master=master.clone();client.browser_credentials=Some(browser);
    let handle=client.retain_browser_monitor_for_test().unwrap();
    assert!(client.session.is_none());
    assert!(matches!(client.native_master_key(),Err(Error::Unavailable{code:"master_key_extraction_unavailable",..})));
    let ciphertext=master.encrypt_bytes(b"OPAQUE_RESOURCE_PRIVATE_CONTENT").await.unwrap();
    let plaintext=master.decrypt_text(&ciphertext).await.unwrap();
    let publication=|body:String| ChatPublication{
        fence:handle.fence.clone(),cache_scope:Some(CacheMonitorReadScope::capture(&client,Some(CHAT)).unwrap()),
        revision:client.credential_revision,ciphertext:client.ciphertext_snapshot(),
        models:Plain::new(ChatModels{items:vec![],selection:ChatSelectionUpdate::CacheSettled(Chat{
            id:CHAT.into(),messages:vec![Message{id:OTHER.into(),role:"user".into(),content:body,..Message::default()}],..Chat::default()
        })}),
    };
    let borrowed=publication(plaintext.clone());let consumed=publication(plaintext);
    assert!(borrowed.models().is_ok() && consumed.models().is_ok());
    let owner=client.task_watch_authority.clone();let revision=owner.cached_denial_revision().unwrap();
    let child=client.operation_cancel.clone();let parent=client.operation_parent.clone();
    master.invalidate();
    // Only the actual opaque capability's revocation instance changed. The
    // previous owner/child/monitor/ledger checks all still pass independently.
    assert!(Arc::ptr_eq(&owner,&client.task_watch_authority));assert!(!owner.cancel.is_cancelled());
    assert!(!child.is_cancelled() && !parent.is_cancelled());assert!(handle.is_valid());
    assert_eq!(owner.cached_denial_revision().unwrap(),revision);assert!(owner.cached_chat_allowed(CHAT));
    assert!(client.browser_credentials.as_ref().unwrap().master.same_instance(&master));
    assert!(matches!(borrowed.models(),Err(Error::Cancelled)));
    assert!(matches!(borrowed.into_models(),Err(Error::Cancelled)));
    assert!(matches!(consumed.into_models(),Err(Error::Cancelled)));
    // Both consumed errors drop their original Plain<ChatModels> owner. The
    // V2 typed Drop probe verifies its shared nested plaintext wiper; no DTO is
    // promoted or plaintext owner moved out along either rejected path.
}

#[test]
fn cancelled_transaction_restores_original_arrival_index_with_its_rows() {
    let mut client=fixture();prior_cache(&mut client);
    client.chat_arrival_order=Some(client.chats.keys().cloned().collect());
    let before=client.chat_arrival_order.clone();let original=client.chats.clone();let handle=monitor(&client);
    {
        let mut transaction=LiveReadTransaction::new(&mut client,handle.fence.clone()).unwrap();
        transaction.insert_chat_row(OTHER.into(),json!({"id":OTHER}));
        transaction.remove_chat_row(CHAT);
        transaction.operation_cancel.cancel();
    }
    assert_eq!(client.chats,original);assert_eq!(client.chat_arrival_order,before);
}
