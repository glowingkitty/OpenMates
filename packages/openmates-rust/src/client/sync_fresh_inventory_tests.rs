// contract-test: supporting surface=sdk assertions=sdk.library.explicit-headless,sdk.encryption.local-only
//! PRIVATE UNRUN: actual core guards and deterministic loopback protocol counts.
use super::*;
use futures_util::{SinkExt, StreamExt};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message;
fn inventory_fixture() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/fixtures/fresh-chat-inventory.json"
    ))
    .unwrap()
}

// A connection is classified by its complete bounded HTTP request, never by
// whichever completed WebSocket happens to win a select scheduling race.
enum PeerHttpRoute {
    SessionAuth,
    TaskMetadataPreflight,
}
fn peer_http_route(request: &[u8]) -> Option<PeerHttpRoute> {
    match std::str::from_utf8(request)
        .unwrap()
        .lines()
        .next()
        .unwrap()
    {
        "POST /v1/auth/session HTTP/1.1" => Some(PeerHttpRoute::SessionAuth),
        "POST /v1/chats/metadata/batch HTTP/1.1" => Some(PeerHttpRoute::TaskMetadataPreflight),
        _ => None,
    }
}
async fn read_peer_http(http: &mut tokio::net::TcpStream) -> Vec<u8> {
    let mut request = Vec::new();
    loop {
        let mut buffer = [0; 2048];
        let size = http.read(&mut buffer).await.unwrap();
        assert!(size > 0);
        request.extend_from_slice(&buffer[..size]);
        assert!(request.len() < 16_384);
        if let Some(end) = request.windows(4).position(|p| p == b"\r\n\r\n") {
            let headers = std::str::from_utf8(&request[..end]).unwrap();
            let length = headers
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|v| v.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            assert!(length < 16_384);
            if request.len() >= end + 4 + length {
                assert_eq!(
                    request.len(),
                    end + 4 + length,
                    "No pipelined fixture requests"
                );
                return request;
            }
        }
    }
}
fn peer_session_owner_matches(request: &[u8]) -> bool {
    let Some(end) = request.windows(4).position(|p| p == b"\r\n\r\n") else {
        return false;
    };
    let Ok(body) = serde_json::from_slice::<Value>(&request[end + 4..]) else {
        return false;
    };
    // Every Client is explicitly constructed from this synthetic session.
    body == json!({"session_id": "fixture"})
}
fn assert_peer_session_auth(request: &[u8]) {
    assert!(matches!(
        peer_http_route(request),
        Some(PeerHttpRoute::SessionAuth)
    ));
    // Another session cannot silently inherit the fixture's owner response.
    assert!(peer_session_owner_matches(request));
}

struct Peer {
    base: String,
    auth: Arc<AtomicUsize>,
    sync: Arc<AtomicUsize>,
    task_preflights: Arc<AtomicUsize>,
    metadata_retries: Arc<AtomicUsize>,
    terminal_barriers: Arc<AtomicUsize>,
    auth_handoffs: Arc<AtomicUsize>,
    cached_baseline: Option<Value>,
    stop: CancellationToken,
    task: tokio::task::JoinHandle<()>,
}
impl Peer {
    async fn start(include_main: bool, complete_markers: bool) -> Self {
        Self::start_with_task(include_main, complete_markers, 0).await
    }
    // 0=successful empty, 1=missing/old backend, 2=owned pending job.
    async fn start_with_task(include_main: bool, complete_markers: bool, task_offer: u8) -> Self {
        Self::start_with_correlation(include_main, complete_markers, task_offer, 0, 0).await
    }
    // correlation: 0=current, 1=missing, 2=foreign, 3=replay previous request.
    // target: 0=all, 1=main, 2=metadata, 3=Task.
    async fn start_with_correlation(
        include_main: bool,
        complete_markers: bool,
        task_offer: u8,
        correlation: u8,
        target: u8,
    ) -> Self {
        Self::start_mode(
            include_main,
            complete_markers,
            task_offer,
            correlation,
            target,
            false,
        )
        .await
    }
    async fn start_with_deferred_metadata() -> Self {
        Self::start_mode(true, true, 0, 0, 0, true).await
    }
    async fn start_mode(
        include_main: bool,
        complete_markers: bool,
        task_offer: u8,
        correlation: u8,
        target: u8,
        defer_metadata: bool,
    ) -> Self {
        Self::start_protocol(
            include_main,
            complete_markers,
            task_offer,
            correlation,
            target,
            defer_metadata,
            0,
        )
        .await
    }
    // protocol: 0=correlated, 1=old welcome, 2=no welcome, 3=foreign phase noise,
    // 4=current disabled terminal, 5=foreign/unbound typed terminal before current.
    // 8=force next-auth accept before polling the completed old proof socket.
    // 9=wrapper-only protected cache, 10=populated metadata/history without sidecars.
    async fn start_protocol(
        include_main: bool,
        complete_markers: bool,
        task_offer: u8,
        correlation: u8,
        target: u8,
        defer_metadata: bool,
        protocol: u8,
    ) -> Self {
        let mut cached_baseline = if matches!(protocol, 6 | 7 | 9 | 10) {
            let chat = "22222222-2222-4222-8222-222222222222";
            let embed = "33333333-3333-4333-8333-333333333333";
            Some(json!({"chats":{(chat):{"id":chat,"messages_v":7,
                "encrypted_chat_key":crypto::encrypt_bytes(&[8;32], &[1;32]).unwrap(),
                "encrypted_title":crypto::encrypt_combined("Current cached chat", &[8;32]).unwrap()}},
                "wrappers":[], "history":{(chat):[{"id":"44444444-4444-4444-8444-444444444444", "role":"assistant",
                    "encrypted_content":crypto::encrypt_combined("Protected cached history", &[8;32]).unwrap()}]},
                "embeds":{(embed):{"embed_id":embed,"encrypted_content":crypto::encrypt_combined("Protected embed", &[9;32]).unwrap()}},
                "embed_keys":[{"embed_id":embed,"encrypted_embed_key":crypto::encrypt_bytes(&[9;32], &[8;32]).unwrap()}],
                "team_wrapped_key":null}))
        } else {
            None
        };
        if matches!(protocol, 9 | 10) {
            let baseline = cached_baseline.as_mut().unwrap();
            baseline["embeds"] = json!({});
            baseline["embed_keys"] = json!([]);
            let row = &mut baseline["chats"]["22222222-2222-4222-8222-222222222222"];
            row["encrypted_draft_md"] = json!(crypto::encrypt_combined("Protected draft", &[1;32]).unwrap());
            row["draft_v"] = json!(11);
            row["encrypted_active_focus_id"] = json!(crypto::encrypt_combined("Protected focus", &[8;32]).unwrap());
            row["encrypted_follow_up_request_suggestions"] = json!(crypto::encrypt_combined("[]", &[8;32]).unwrap());
            let encrypted_chat_key = row["encrypted_chat_key"].clone();
            if protocol == 9 {
                baseline["wrappers"] = json!([{"hashed_chat_id":sha256("22222222-2222-4222-8222-222222222222"),
                    "key_type":"master", "encrypted_chat_key":encrypted_chat_key}]);
            }
        }
        let server_baseline = cached_baseline.clone();
        let auth_handoffs = Arc::new(AtomicUsize::new(0));
        let handoff_count = auth_handoffs.clone();
        let terminal_barriers = Arc::new(AtomicUsize::new(0));
        let barrier_count = terminal_barriers.clone();
        let metadata_retries = Arc::new(AtomicUsize::new(0));
        let retry_count = metadata_retries.clone();
        let task_preflights = Arc::new(AtomicUsize::new(0));
        let preflight_count = task_preflights.clone();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let auth = Arc::new(AtomicUsize::new(0));
        let sync = Arc::new(AtomicUsize::new(0));
        let stop = CancellationToken::new();
        let (auth_count, sync_count, stopping) = (auth.clone(), sync.clone(), stop.clone());
        let task = tokio::spawn(async move {
            let mut previous_request_id: Option<String> = None;
            let mut pending_auth = None;
            loop {
                let (mut http, request) = if let Some(pending) = pending_auth.take() {
                    pending
                } else {
                    let (mut http, _) = tokio::select! {
                        biased;
                        _ = stopping.cancelled() => return,
                        stream = listener.accept() => stream.unwrap(),
                    };
                    let request = read_peer_http(&mut http).await;
                    (http, request)
                };
                assert_peer_session_auth(&request);
                auth_count.fetch_add(1, Ordering::SeqCst);
                let user = if matches!(protocol, 9 | 10) {
                    non_embed_inventory_user()
                } else {
                    json!({"id":"synthetic-owner"})
                };
                let body = json!({"success":true,"ws_token":"synthetic-token","user":user}).to_string();
                http.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
                drop(http);
                let (stream, _) = listener.accept().await.unwrap();
                let mut proof_socket = false;
                let mut inventory_request_id = None;
                let mut socket = tokio_tungstenite::accept_hdr_async(
                    stream,
                    |request: &tokio_tungstenite::tungstenite::handshake::server::Request,
                     response| {
                        let query = request.uri().query().unwrap();
                        proof_socket = query.contains("task_update_jobs_inventory_v1");
                        if proof_socket || !query.contains("chat_metadata_recovery") {
                            assert!(query.contains("task_update_jobs"));
                        }
                        if proof_socket {
                            assert!(query.contains("chat_metadata_recovery"));
                            let parameters = url::form_urlencoded::parse(query.as_bytes())
                                .into_owned()
                                .collect::<BTreeMap<_, _>>();
                            let request_id = parameters
                                .get("inventory_request_id")
                                .expect("bound inventory request");
                            let parsed = uuid::Uuid::parse_str(request_id).unwrap();
                            assert!(
                                parsed.get_version_num() == 4 && parsed.to_string() == *request_id
                            );
                            inventory_request_id = Some(request_id.clone());
                        }
                        Ok(response)
                    },
                )
                .await
                .unwrap();
                let lifecycle: Value = serde_json::from_str(
                    &socket.next().await.unwrap().unwrap().into_text().unwrap(),
                )
                .unwrap();
                assert_eq!(lifecycle["type"], "native_client_lifecycle");
                assert_eq!(lifecycle["payload"]["client_type"], "rust");
                assert_eq!(lifecycle["payload"]["is_foreground"], true);
                if matches!(protocol, 9 | 10) {
                    assert!(proof_socket, "populated-state fixture uses inventory admission");
                    let active: Value = serde_json::from_str(
                        &socket.next().await.unwrap().unwrap().into_text().unwrap(),
                    ).unwrap();
                    assert_eq!(active, json!({"type":"set_active_chat","payload":{
                        "chat_id":"22222222-2222-4222-8222-222222222222"}}));
                }
                let request: Value = serde_json::from_str(
                    &socket.next().await.unwrap().unwrap().into_text().unwrap(),
                )
                .unwrap();
                assert_eq!(request["type"], "phased_sync_request");
                // Existing protected sidecars keep the original full-startup path.
                // Every empty headless proof peer must request the metadata-only route.
                let expected_phase = if proof_socket && (server_baseline.is_none() || protocol == 10) { "phase2" } else { "all" };
                assert_eq!(request["payload"]["phase"], expected_phase);
                if matches!(protocol, 9 | 10) {
                    assert!(request["payload"].get("team_id").is_none(), "personal inventory scope");
                }
                if proof_socket {
                    assert!(
                        request["payload"]["inventory_request_id"].as_str()
                            == inventory_request_id.as_deref()
                    );
                }
                sync_count.fetch_add(1, Ordering::SeqCst);
                let mut phase_payload = json!({"chats":[]});
                if let Some(baseline) = &server_baseline {
                    phase_payload["chats"] = json!([{"chat_details":baseline["chats"]["22222222-2222-4222-8222-222222222222"]}]);
                    if expected_phase == "all" {
                        phase_payload["embeds"] = json!(
                            baseline["embeds"]
                                .as_object()
                                .unwrap()
                                .values()
                                .collect::<Vec<_>>()
                        );
                        phase_payload["embed_keys"] = baseline["embed_keys"].clone();
                    }
                }
                let mut frames =
                    vec![json!({"type":"phase_2_last_20_chats_ready","payload":phase_payload})];
                if expected_phase == "all" && protocol == 9 {
                    frames.push(json!({"type":"phase_1b_messages_ready","payload":{
                        "chat_key_wrappers":server_baseline.as_ref().unwrap()["wrappers"]}}));
                }
                if include_main {
                    frames.push(inventory_fixture()["mainEmpty"].clone());
                }
                if protocol == 11 && proof_socket {
                    let pending=json!({"job_id":"44444444-4444-4444-8444-444444444444","chat_id":"22222222-2222-4222-8222-222222222222","turn_id":"55555555-5555-4555-8555-555555555555","assistant_message_id":"66666666-6666-4666-8666-666666666666","chat_key_version":1,"state":"LEASED","created_at":1_800_000_001u64});
                    for frame in &mut frames {if frame["type"]=="recovery_jobs_available" {frame["payload"]["pending_jobs"]=json!([pending]);}}
                }
                if task_offer != 1 && (proof_socket || task_offer == 2) {
                    let jobs = if task_offer == 2 {
                        vec![json!({
                            "job_id":"owned-pending-task", "task_id":"11111111-1111-4111-8111-111111111111",
                            "chat_id":"22222222-2222-4222-8222-222222222222", "revision":1,
                            "task_key_version":1, "expires_at":now_ms()/1000+120,
                        })]
                    } else {
                        vec![]
                    };
                    let mut payload = json!({"jobs":jobs});
                    if proof_socket {
                        payload["complete"] = json!(true);
                    }
                    frames.push(if proof_socket && task_offer == 0 {
                        inventory_fixture()["taskEmptyComplete"].clone()
                    } else {
                        json!({"type":"task_update_jobs_available","payload":payload})
                    });
                }
                if !defer_metadata {
                    frames.push(inventory_fixture()["metadataEmpty"].clone());
                }
                frames.extend([
                    // Deliberately opposite completion order from many fixtures.
                    json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"completed"}}),
                    json!({"type":"phased_sync_complete","payload":{"phase":expected_phase}}),
                ]);
                if !complete_markers {
                    frames.retain(|frame| frame["type"] != "recovery_outputs_discovery_complete");
                }
                if proof_socket && protocol != 2 {
                    let mut welcome =
                        json!({"type":"server_capabilities","payload":{"capabilities":[]}});
                    if protocol != 1 {
                        welcome["payload"]["inventory_request_id"] = json!(inventory_request_id);
                    }
                    frames.insert(0, welcome);
                }
                if protocol == 4 {
                    for frame in &mut frames {
                        if frame["type"] == "recovery_outputs_discovery_complete" {
                            frame["payload"]["status"] = json!("disabled");
                        }
                    }
                }
                let wrong_response = proof_socket
                    && correlation != 0
                    && (correlation != 3 || previous_request_id.is_some());
                for frame in &mut frames {
                    let kind = match frame["type"].as_str() {
                        Some("recovery_jobs_available") => 1,
                        Some("metadata_jobs_available") => 2,
                        Some("task_update_jobs_available") => 3,
                        Some(
                            "phase_2_last_20_chats_ready"
                            | "phase_1b_messages_ready"
                            | "phased_sync_complete"
                            | "recovery_outputs_discovery_complete",
                        ) => 4,
                        _ => continue,
                    };
                    if let Some(current) = &inventory_request_id {
                        let request_id =
                            if kind <= 3 && wrong_response && (target == 0 || target == kind) {
                                match correlation {
                                    1 => None,
                                    2 => Some(uuid::Uuid::new_v4().to_string()),
                                    3 => previous_request_id.clone(),
                                    _ => unreachable!(),
                                }
                            } else {
                                Some(current.clone())
                            };
                        if let Some(request_id) = request_id {
                            frame["payload"]["inventory_request_id"] = json!(request_id);
                        }
                    }
                }
                if proof_socket && (protocol == 1 || protocol == 2) {
                    for frame in &mut frames {
                        frame["payload"]
                            .as_object_mut()
                            .unwrap()
                            .remove("inventory_request_id");
                    }
                }
                let mut delayed_frames = vec![];
                if proof_socket && (protocol == 3 || protocol == 5) {
                    let held: &[&str] = if protocol == 3 {
                        &["phase_2_last_20_chats_ready", "phased_sync_complete"]
                    } else {
                        &["recovery_outputs_discovery_complete"]
                    };
                    let mut early = vec![];
                    for frame in frames {
                        if held.iter().any(|kind| frame["type"] == *kind) {
                            delayed_frames.push(frame);
                        } else {
                            early.push(frame);
                        }
                    }
                    frames = early;
                    let foreign = uuid::Uuid::new_v4().to_string();
                    if protocol == 3 {
                        let poison = json!({"type":"phase_2_last_20_chats_ready","payload":{"chats":[{"chat_details":{"id":"11111111-1111-4111-8111-111111111111","encrypted_chat_key":"invalid-stale-ciphertext"}}]}});
                        // Pre-welcome legacy readiness must be discarded on strict upgrade.
                        frames.insert(0, poison.clone());
                        frames.push(poison.clone());
                        let mut foreign_poison = poison;
                        foreign_poison["payload"]["inventory_request_id"] = json!(foreign);
                        frames.push(foreign_poison);
                        frames
                            .push(json!({"type":"phased_sync_complete","payload":{"phase":"all"}}));
                        frames.push(json!({"type":"phased_sync_complete","payload":{"phase":"all","inventory_request_id":foreign}}));
                    } else {
                        frames.push(json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"completed"}}));
                        frames.push(json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"completed","inventory_request_id":foreign}}));
                    }
                }
                if proof_socket && protocol == 7 {
                    frames.insert(0, json!({"type":"phase_2_last_20_chats_ready","payload":{
                        "chats":[{"chat_details":{"id":"55555555-5555-4555-8555-555555555555","encrypted_chat_key":"foreign"}}],
                        "embeds":[{"embed_id":"66666666-6666-4666-8666-666666666666","encrypted_content":"foreign"}],
                        "embed_keys":[{"encrypted_embed_key":"foreign"}]}}));
                }
                if inventory_request_id.is_some() {
                    previous_request_id = inventory_request_id.clone();
                }
                for frame in frames {
                    socket
                        .send(Message::Text(frame.to_string().into()))
                        .await
                        .unwrap();
                }
                if !delayed_frames.is_empty() {
                    socket
                        .send(Message::Ping(vec![1, 2, 3].into()))
                        .await
                        .unwrap();
                    // A terminal from another transaction must not finish the
                    // SDK future before it services this protocol barrier.
                    assert!(matches!(
                        socket.next().await.unwrap().unwrap(),
                        Message::Pong(_)
                    ));
                    barrier_count.fetch_add(1, Ordering::SeqCst);
                    for frame in delayed_frames {
                        socket
                            .send(Message::Text(frame.to_string().into()))
                            .await
                            .unwrap();
                    }
                }
                if !complete_markers {
                    let _ = socket.close(None).await;
                    return;
                }
                if wrong_response {
                    // Close after complete phased markers, so invalid proof
                    // falls back without waiting on a test-only wall clock.
                    let _ = socket.close(None).await;
                    continue;
                }
                let mut metadata_complete = !defer_metadata || !proof_socket;
                loop {
                    let incoming = if protocol == 8 && proof_socket {
                        // Deterministic lifecycle barrier: never poll the old
                        // completed socket until the next fresh auth has arrived.
                        // Its Close and next TCP can both be pending, but either
                        // ordering must retain the same strict protocol checks.
                        assert!(metadata_complete && task_offer == 0);
                        Some(listener.accept().await.unwrap().0)
                    } else {
                        tokio::select! {
                            frame = socket.next() => {
                                match frame.unwrap().unwrap() {
                                    Message::Close(_) => break,
                                    Message::Text(text) if defer_metadata && proof_socket => {
                                        let request: Value = serde_json::from_str(&text).unwrap();
                                        assert_eq!(request["type"], "metadata_jobs_request");
                                        // Compare opaque IDs without generated diagnostic values.
                                        assert!(request["payload"]["inventory_request_id"].as_str()
                                            == inventory_request_id.as_deref());
                                        assert_eq!(retry_count.fetch_add(1, Ordering::SeqCst), 0);
                                        let mut reply = inventory_fixture()["metadataEmpty"].clone();
                                        reply["payload"]["inventory_request_id"] = json!(inventory_request_id);
                                        socket.send(Message::Text(reply.to_string().into())).await.unwrap();
                                        metadata_complete = true;
                                    },
                                    _ => panic!("Discovery cannot claim or persist Task work"),
                                }
                                None
                            },
                            stream = listener.accept() => Some(stream.unwrap().0),
                        }
                    };
                    let Some(mut http) = incoming else {
                        continue;
                    };
                    let request = read_peer_http(&mut http).await;
                    match peer_http_route(&request).expect("Unexpected inventory peer HTTP route") {
                        PeerHttpRoute::SessionAuth => {
                            assert!(
                                metadata_complete,
                                "Deferred metadata must finish before next auth"
                            );
                            if !proof_socket && task_offer == 2 {
                                assert_eq!(preflight_count.load(Ordering::SeqCst), 1);
                            }
                            assert!(pending_auth.is_none());
                            // The unchanged outer admission responds and counts
                            // exactly once; this slot owns the accepted stream.
                            assert_peer_session_auth(&request);
                            pending_auth = Some((http, request));
                            handoff_count.fetch_add(1, Ordering::SeqCst);
                            break;
                        }
                        PeerHttpRoute::TaskMetadataPreflight => {
                            assert!(
                                !proof_socket && task_offer == 2,
                                "only ordinary fallback may preflight Task"
                            );
                            assert_eq!(preflight_count.fetch_add(1, Ordering::SeqCst), 0);
                            http.write_all(b"HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}").await.unwrap();
                        }
                    }
                }
                if pending_auth.is_some() {
                    // The SDK sends Close before beginning the next validation.
                    // Retain strict old-frame checks: staging auth is not a way
                    // to discard a queued claim/persist/unknown WebSocket frame.
                    assert!(
                        matches!(socket.next().await.unwrap().unwrap(), Message::Close(_)),
                        "Completed discovery must close before next authentication"
                    );
                }
                let _ = socket.close(None).await;
            }
        });
        Self {
            base,
            auth,
            sync,
            task_preflights,
            metadata_retries,
            terminal_barriers,
            auth_handoffs,
            cached_baseline,
            stop,
            task,
        }
    }
    fn client(&self) -> Client {
        let mut session = crate::client::sdk_boundary_tests::session();
        session.api_url = self.base.clone();
        let mut client = Client::new(&self.base, Some(session)).unwrap();
        if let Some(baseline) = &self.cached_baseline {
            client.restore_ciphertext_snapshot(baseline).unwrap();
        }
        client
    }
    async fn finish(self, expected: usize) {
        self.stop.cancel();
        self.task.await.unwrap();
        assert_eq!(self.auth.load(Ordering::SeqCst), expected);
        assert_eq!(self.sync.load(Ordering::SeqCst), expected);
    }
}

#[tokio::test]
async fn no_job_discovery_list_uses_one_authenticated_metadata_only_phased_sync() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let peer = Peer::start(true, true).await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).unwrap();
        let (jobs, proof) = client
            .completion_recovery_jobs_with_inventory(&cancel)
            .await
            .unwrap();
        assert!(jobs.is_empty());
        let proof = proof.expect("explicit complete discoveries");
        // Metadata completion never fabricates cached transcript/sidecar completeness.
        let snapshot = client.ciphertext_snapshot();
        assert!(snapshot["history"].as_object().unwrap().is_empty());
        assert!(snapshot["embeds"].as_object().unwrap().is_empty());
        assert!(snapshot["embed_keys"].as_array().unwrap().is_empty());
        client.set_foreground_completion_recovery(false).unwrap();
        assert!(
            client
                .list_with_fresh_chat_inventory(Workspace::Chats, proof, &cancel)
                .await
                .unwrap()
                .is_empty()
        );
        peer.finish(1).await;
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn incomplete_job_discovery_never_issues_inventory_proof() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let peer = Peer::start(false, true).await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).unwrap();
        let (jobs, proof) = client
            .completion_recovery_jobs_with_inventory(&cancel)
            .await
            .unwrap();
        assert!(jobs.is_empty());
        assert!(proof.is_none());
        client.set_foreground_completion_recovery(false).unwrap();
        client.list(Workspace::Chats).await.unwrap();
        peer.finish(2).await;
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn intervening_failed_transport_invalidates_proof_and_list_authenticates_again() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let peer = Peer::start(true, true).await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).unwrap();
        let (_, proof) = client
            .completion_recovery_jobs_with_inventory(&cancel)
            .await
            .unwrap();
        let proof = proof.unwrap();
        // The shared transport rejects this URL before dispatch; even an
        // unsuccessful intervening operation conservatively forfeits reuse.
        assert!(matches!(
            client
                .request(Method::GET, "https://foreign.invalid/", None)
                .await,
            Err(Error::Protocol)
        ));
        assert!(!client.chat_inventory_is_current(&proof).unwrap());
        client.set_foreground_completion_recovery(false).unwrap();
        client
            .list_with_fresh_chat_inventory(Workspace::Chats, proof, &cancel)
            .await
            .unwrap();
        peer.finish(2).await;
    })
    .await
    .unwrap();
}

fn guard_client() -> Client {
    let mut client = Client::new(
        "https://api.example.org",
        Some(crate::client::sdk_boundary_tests::session()),
    )
    .unwrap();
    client.user = json!({"id":"synthetic-owner"});
    client
}
fn proof(client: &Client) -> FreshChatInventory {
    client
        .fresh_chat_inventory(&CancellationToken::new())
        .unwrap()
        .unwrap()
}
#[test]
fn inventory_guard_binds_issuer_api_owner_generation_credentials_and_exact_ciphertext() {
    let owner = guard_client();
    let issued = proof(&owner);
    let other = guard_client();
    assert!(
        !other.chat_inventory_is_current(&issued).unwrap(),
        "same owner, different Client"
    );
    for change in 0..10 {
        let mut client = guard_client();
        let issued = proof(&client);
        match change {
            0 => client.user = json!({"id":"different-owner"}),
            1 => client.base = url::Url::parse("https://other.example.org").unwrap(),
            2 => client.generation += 1,
            3 => client.credentials_changed(),
            4 => client
                .wrappers
                .push(json!({"encrypted_chat_key":"changed"})),
            5 => {
                client.chats.insert(
                    "new".into(),
                    json!({"id":"new","encrypted_title":"changed"}),
                );
            }
            6 => client.invalidate_task_watches(),
            7 => {
                client
                    .history
                    .insert("chat".into(), vec![json!({"encrypted_content":"changed"})]);
            }
            8 => client.options.identity = ClientIdentity::Cli,
            _ => client.options.app_url = Some("https://different.example.org".into()),
        }
        assert!(!client.chat_inventory_is_current(&issued).unwrap());
    }
}
#[test]
fn scope_reset_cancel_expiry_and_revocation_reject_proof() {
    let mut client = guard_client();
    let issued = proof(&client);
    client
        .set_team(Some("11111111-1111-4111-8111-111111111111"))
        .unwrap();
    assert!(!client.chat_inventory_is_current(&issued).unwrap());
    assert!(
        client
            .fresh_chat_inventory(&CancellationToken::new())
            .unwrap()
            .is_none()
    );
    let mut client = guard_client();
    let issued = proof(&client);
    client
        .reset(
            "https://api.example.org",
            Some(crate::client::sdk_boundary_tests::session()),
        )
        .unwrap();
    assert!(!client.chat_inventory_is_current(&issued).unwrap());
    let client = guard_client();
    let cancel = CancellationToken::new();
    let issued = client.fresh_chat_inventory(&cancel).unwrap().unwrap();
    cancel.cancel();
    assert!(matches!(
        client.chat_inventory_is_current(&issued),
        Err(Error::Cancelled)
    ));
    let mut client = guard_client();
    let issued = proof(&client);
    client.session.as_mut().unwrap().paired_session_expires_at = Some(1);
    assert!(matches!(
        client.chat_inventory_is_current(&issued),
        Err(Error::Expired)
    ));
    let mut client = guard_client();
    let issued = proof(&client);
    client.forget_session();
    assert!(matches!(
        client.chat_inventory_is_current(&issued),
        Err(Error::Authentication)
    ));
}

#[tokio::test]
async fn missing_recovery_terminal_marker_retains_the_existing_offline_error() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let peer = Peer::start(true, false).await;
        let mut client = peer.client();
        client.set_foreground_completion_recovery(true).unwrap();
        assert!(matches!(
            client
                .completion_recovery_jobs_with_inventory(&CancellationToken::new())
                .await,
            Err(Error::Offline)
        ));
        peer.finish(1).await;
    })
    .await
    .unwrap();
}

#[test]
fn restoring_even_identical_ciphertext_cannot_restore_live_inventory_authority() {
    let mut client = guard_client();
    let issued = proof(&client);
    let saved_data = client.ciphertext_snapshot();
    client.restore_ciphertext_snapshot(&saved_data).unwrap();
    assert!(!client.chat_inventory_is_current(&issued).unwrap());
    client.chats.insert(
        "direct".into(),
        json!({"id":"direct","chat_visibility":"direct"}),
    );
    assert!(
        client
            .fresh_chat_inventory(&CancellationToken::new())
            .unwrap()
            .is_none()
    );
}

#[tokio::test]
async fn missing_task_completeness_never_issues_proof_and_uses_fresh_list() {
    tokio::time::timeout(Duration::from_secs(6), async {
        let peer = Peer::start_with_task(true, true, 1).await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).unwrap();
        let (_, proof) = client
            .completion_recovery_jobs_with_inventory(&cancel)
            .await
            .unwrap();
        assert!(proof.is_none());
        client.set_foreground_completion_recovery(false).unwrap();
        client.list(Workspace::Chats).await.unwrap();
        peer.finish(2).await;
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn owned_task_offer_is_read_only_then_ordinary_list_preflights_it_once() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let peer = Peer::start_with_task(true, true, 2).await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).unwrap();
        let (_, proof) = client
            .completion_recovery_jobs_with_inventory(&cancel)
            .await
            .unwrap();
        assert!(
            proof.is_none(),
            "pending Task prevents idle inventory proof"
        );
        assert_eq!(peer.task_preflights.load(Ordering::SeqCst), 0);
        client.set_foreground_completion_recovery(false).unwrap();
        client.list(Workspace::Chats).await.unwrap();
        assert_eq!(peer.task_preflights.load(Ordering::SeqCst), 1);
        peer.finish(2).await;
    })
    .await
    .unwrap();
}

#[test]
fn prepared_task_and_source_lanes_invalidate_inventory_proof() {
    let mut client = guard_client();
    client.session.as_mut().unwrap().ws_token = Some("synthetic-token".into());
    let issued = proof(&client);
    let _prepared = client.prepare_task_socket().unwrap();
    assert!(!client.chat_inventory_is_current(&issued).unwrap());
    let issued = proof(&client);
    let _prepared = client.prepare_source_host_socket().unwrap();
    assert!(!client.chat_inventory_is_current(&issued).unwrap());
}

#[tokio::test]
async fn legacy_completion_jobs_api_keeps_its_existing_discovery_mode() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let peer = Peer::start(true, true).await;
        let mut client = peer.client();
        client.set_foreground_completion_recovery(true).unwrap();
        assert!(
            client
                .completion_recovery_jobs(&CancellationToken::new())
                .await
                .unwrap()
                .is_empty()
        );
        peer.finish(1).await;
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn missing_or_foreign_nonce_on_any_completeness_ack_forces_fresh_list() {
    tokio::time::timeout(Duration::from_secs(20), async {
        for correlation in [1, 2] {
            for target in [1, 2, 3] {
                let peer = Peer::start_with_correlation(true, true, 0, correlation, target).await;
                let mut client = peer.client();
                let cancel = CancellationToken::new();
                client.set_foreground_completion_recovery(true).unwrap();
                let (_, proof) = client
                    .completion_recovery_jobs_with_inventory(&cancel)
                    .await
                    .unwrap();
                assert!(
                    proof.is_none(),
                    "all three acknowledgments must name this request"
                );
                client.set_foreground_completion_recovery(false).unwrap();
                client.list(Workspace::Chats).await.unwrap();
                peer.finish(2).await;
            }
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn acknowledgments_replayed_from_an_earlier_request_cannot_mint_new_proof() {
    tokio::time::timeout(Duration::from_secs(10), async {
        let peer = Peer::start_with_correlation(true, true, 0, 3, 0).await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).unwrap();
        let (_, first) = client
            .completion_recovery_jobs_with_inventory(&cancel)
            .await
            .unwrap();
        assert!(first.is_some());
        drop(first);
        let (_, replay) = client
            .completion_recovery_jobs_with_inventory(&cancel)
            .await
            .unwrap();
        assert!(replay.is_none());
        client.set_foreground_completion_recovery(false).unwrap();
        client.list(Workspace::Chats).await.unwrap();
        peer.finish(3).await;
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn deferred_metadata_retry_uses_same_socket_nonce_and_matching_reply_completes_proof() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let peer = Peer::start_with_deferred_metadata().await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).unwrap();
        let (jobs, proof) = client
            .completion_recovery_jobs_with_inventory(&cancel)
            .await
            .unwrap();
        assert!(jobs.is_empty());
        let proof = proof.expect("matching retry settles the original discovery");
        assert_eq!(peer.metadata_retries.load(Ordering::SeqCst), 1);
        client.set_foreground_completion_recovery(false).unwrap();
        assert!(
            client
                .list_with_fresh_chat_inventory(Workspace::Chats, proof, &cancel)
                .await
                .unwrap()
                .is_empty()
        );
        peer.finish(1).await;
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn legacy_backend_welcome_or_missing_welcome_keeps_functional_same_socket_without_proof() {
    tokio::time::timeout(Duration::from_secs(10), async {
        for protocol in [1, 2] {
            let peer = Peer::start_protocol(true, true, 0, 0, 0, false, protocol).await;
            let mut client = peer.client();
            let cancel = CancellationToken::new();
            client.set_foreground_completion_recovery(true).unwrap();
            let (jobs, proof) = client
                .completion_recovery_jobs_with_inventory(&cancel)
                .await
                .unwrap();
            assert!(jobs.is_empty() && proof.is_none());
            client.set_foreground_completion_recovery(false).unwrap();
            assert!(client.list(Workspace::Chats).await.unwrap().is_empty());
            peer.finish(2).await;
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn foreign_or_unbound_canonical_and_typed_terminal_noise_cannot_poison_or_release_proof() {
    tokio::time::timeout(Duration::from_secs(10), async {
        for protocol in [3, 5] {
            let peer = Peer::start_protocol(true, true, 0, 0, 0, false, protocol).await;
            let mut client = peer.client();
            let cancel = CancellationToken::new();
            client.set_foreground_completion_recovery(true).unwrap();
            let (_, proof) = client
                .completion_recovery_jobs_with_inventory(&cancel)
                .await
                .unwrap();
            assert_eq!(peer.terminal_barriers.load(Ordering::SeqCst), 1);
            let proof = proof.expect("only the current complete snapshot may prove freshness");
            client.set_foreground_completion_recovery(false).unwrap();
            assert!(
                client
                    .list_with_fresh_chat_inventory(Workspace::Chats, proof, &cancel)
                    .await
                    .unwrap()
                    .is_empty()
            );
            peer.finish(1).await;
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn current_disabled_recovery_terminal_still_proves_read_only_empty_inventory() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let peer = Peer::start_protocol(true, true, 0, 0, 0, false, 4).await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).unwrap();
        let (_, proof) = client
            .completion_recovery_jobs_with_inventory(&cancel)
            .await
            .unwrap();
        let proof = proof.expect("disabled recovery does not activate or offer work");
        client.set_foreground_completion_recovery(false).unwrap();
        assert!(
            client
                .list_with_fresh_chat_inventory(Workspace::Chats, proof, &cancel)
                .await
                .unwrap()
                .is_empty()
        );
        peer.finish(1).await;
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn strict_welcome_upgrade_preserves_same_version_protected_cache_and_discards_foreign_staging()
 {
    tokio::time::timeout(Duration::from_secs(10), async {
        for protocol in [6, 7] {
            let peer = Peer::start_protocol(true, true, 0, 0, 0, false, protocol).await;
            let mut client = peer.client();
            let cancel = CancellationToken::new();
            let baseline = client.ciphertext_snapshot();
            client.set_foreground_completion_recovery(true).unwrap();
            let (_, proof) = client
                .completion_recovery_jobs_with_inventory(&cancel)
                .await
                .unwrap();
            let proof = proof.expect("valid current inventory remains provable after welcome");
            let current = client.ciphertext_snapshot();
            assert!(current["history"] == baseline["history"]);
            assert!(current["embeds"] == baseline["embeds"]);
            assert!(current["embed_keys"] == baseline["embed_keys"]);
            assert_eq!(
                current["chats"]["22222222-2222-4222-8222-222222222222"]["messages_v"],
                7
            );
            assert!(
                current["chats"]
                    .get("55555555-5555-4555-8555-555555555555")
                    .is_none()
            );
            assert!(
                current["embeds"]
                    .get("66666666-6666-4666-8666-666666666666")
                    .is_none()
            );
            client.set_foreground_completion_recovery(false).unwrap();
            let items = client
                .list_with_fresh_chat_inventory(Workspace::Chats, proof, &cancel)
                .await
                .unwrap();
            assert_eq!(items.len(), 1);
            assert_eq!(items[0].title, "Current cached chat");
            peer.finish(1).await;
        }
    })
    .await
    .unwrap();
}


fn non_embed_inventory_user() -> Value {
    json!({"id":"synthetic-owner", "last_opened":"chat/22222222-2222-4222-8222-222222222222",
        "preferences":{"synthetic_preservation_marker":true}})
}

#[tokio::test]
async fn phase2_preserves_non_embed_state_and_wrapper_only_cache_falls_back_to_all() {
    tokio::time::timeout(Duration::from_secs(10), async {
        for protocol in [9, 10] {
            let peer = Peer::start_protocol(true, true, 0, 0, 0, false, protocol).await;
            let mut client = peer.client();
            let cancel = CancellationToken::new();
            let baseline = client.ciphertext_snapshot();
            assert!(client.embeds.is_empty() && client.embed_keys.is_empty());
            assert_eq!(client.wrappers.is_empty(), protocol == 10);
            client.active_chat = Some("22222222-2222-4222-8222-222222222222".into());
            client.user = non_embed_inventory_user();
            let active = client.active_chat.clone();
            let user = client.user.clone();
            client.set_foreground_completion_recovery(true).unwrap();
            let (_, proof) = client.completion_recovery_jobs_with_inventory(&cancel).await.unwrap();
            let proof = proof.expect("complete correlated inventory remains valid");
            assert_eq!(client.active_chat, active);
            assert_eq!(client.user, user);
            let current = client.ciphertext_snapshot();
            for field in ["chats", "wrappers", "history", "embeds", "embed_keys", "team_wrapped_key"] {
                assert_eq!(current[field], baseline[field], "protected field: {field}, protocol: {protocol}");
            }
            client.set_foreground_completion_recovery(false).unwrap();
            assert_eq!(client.list_with_fresh_chat_inventory(Workspace::Chats, proof, &cancel).await.unwrap().len(), 1);
            peer.finish(1).await;
        }
    }).await.unwrap();
}

#[test]
fn peer_http_classifier_rejects_task_claim_persist_and_unknown_routes() {
    for route in [
        "POST /v1/tasks/claim HTTP/1.1",
        "POST /v1/chats/persist HTTP/1.1",
        "GET /v1/auth/session HTTP/1.1",
        "POST /v1/auth/session?other=1 HTTP/1.1",
        "POST /v1/unexpected HTTP/1.1",
    ] {
        let request = format!("{route}\r\nContent-Length: 2\r\n\r\n{{}}");
        assert!(peer_http_route(request.as_bytes()).is_none());
    }
    let foreign =
        b"POST /v1/auth/session HTTP/1.1\r\nContent-Length: 22\r\n\r\n{\"session_id\":\"other\"}";
    assert!(!peer_session_owner_matches(foreign));
}

#[tokio::test]
async fn completed_socket_next_auth_overlap_keeps_fallback_and_replay_guards() {
    tokio::time::timeout(Duration::from_secs(10), async {
        for replay in [false, true] {
            let peer =
                Peer::start_protocol(replay, true, 0, if replay { 3 } else { 0 }, 0, false, 8)
                    .await;
            let mut client = peer.client();
            let cancel = CancellationToken::new();
            client.set_foreground_completion_recovery(true).unwrap();
            let (jobs, first) = client
                .completion_recovery_jobs_with_inventory(&cancel)
                .await
                .unwrap();
            assert!(jobs.is_empty());
            if replay {
                assert!(first.is_some());
                drop(first);
                let (jobs, replayed) = client
                    .completion_recovery_jobs_with_inventory(&cancel)
                    .await
                    .unwrap();
                assert!(jobs.is_empty() && replayed.is_none());
            } else {
                assert!(first.is_none());
            }
            client.set_foreground_completion_recovery(false).unwrap();
            assert!(client.list(Workspace::Chats).await.unwrap().is_empty());
            assert_eq!(peer.auth_handoffs.load(Ordering::SeqCst), 1);
            assert_eq!(peer.task_preflights.load(Ordering::SeqCst), 0);
            assert_eq!(peer.metadata_retries.load(Ordering::SeqCst), 0);
            assert_eq!(peer.terminal_barriers.load(Ordering::SeqCst), 0);
            peer.finish(if replay { 3 } else { 2 }).await;
        }
    })
    .await
    .unwrap();
}

// Consuming validation is a no-grant host guard, not a cached read or receipt.
#[tokio::test]
async fn consuming_current_empty_inventory_does_not_render_or_promote_cache() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let peer = Peer::start(true, true).await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).unwrap();
        let (jobs, issued) = client.completion_recovery_jobs_with_inventory(&cancel).await.unwrap();
        assert!(jobs.is_empty());
        let before = client.ciphertext_snapshot();
        assert!(before.get(chat_list_freshness::SNAPSHOT_FIELD).is_none());
        assert!(issued.unwrap().consume_if_current(&client, &cancel).unwrap());
        assert_eq!(client.ciphertext_snapshot(), before);
        peer.finish(1).await;
    }).await.unwrap();
}
#[tokio::test]
async fn asynchronously_shared_monitor_network_revision_invalidates_empty_consumption() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let peer = Peer::start(true, true).await;
        let mut client = peer.client();
        let cancel = CancellationToken::new();
        client.set_foreground_completion_recovery(true).unwrap();
        let (_, issued) = client.completion_recovery_jobs_with_inventory(&cancel).await.unwrap();
        let before = client.ciphertext_snapshot();
        // This is the exact Arc shared by every real Socket and the keyless
        // monitor's send/receive paths. No mutable Client access is necessary.
        let network = client.inventory_network.clone();
        tokio::spawn(async move { network.fetch_add(1, Ordering::SeqCst); }).await.unwrap();
        assert!(!issued.unwrap().consume_if_current(&client, &cancel).unwrap());
        assert_eq!(client.ciphertext_snapshot(), before);
        peer.finish(1).await;
    }).await.unwrap();
}
#[test]
fn consuming_inventory_rechecks_owner_key_epoch_and_exact_ciphertext() {
    for change in 0..8 {
        let mut client = guard_client();
        let cancel = CancellationToken::new();
        let issued = client.fresh_chat_inventory(&cancel).unwrap().unwrap();
        match change {
            0 => client.user = json!({"id":"changed-owner"}),
            1 => client.session.as_mut().unwrap().master_key = zeroize::Zeroizing::new([9;32]),
            2 => client.generation += 1,
            3 => client.credentials_changed(),
            4 => client.invalidate_task_watches(),
            5 => { client.history.insert("changed".into(), vec![json!({"encrypted_content":"changed"})]); },
            6 => client.fresh_auth.advance_operation(),
            _ => { client.inventory_network.fetch_add(1, Ordering::SeqCst); },
        }
        assert!(!issued.consume_if_current(&client, &cancel).unwrap(), "change {change}");
    }
}
#[test]
fn consuming_inventory_rejects_different_client_caller_cancel_expiry_and_revocation() {
    let owner = guard_client();
    let cancel = CancellationToken::new();
    let issued = owner.fresh_chat_inventory(&cancel).unwrap().unwrap();
    assert!(!issued.consume_if_current(&guard_client(), &cancel).unwrap());
    let client = guard_client();
    let issued = client.fresh_chat_inventory(&cancel).unwrap().unwrap();
    assert!(!issued.consume_if_current(&client, &CancellationToken::new()).unwrap());
    let client = guard_client();
    let stopped = CancellationToken::new();
    let issued = client.fresh_chat_inventory(&stopped).unwrap().unwrap();
    stopped.cancel();
    assert!(matches!(issued.consume_if_current(&client, &stopped), Err(Error::Cancelled)));
    let mut client = guard_client();
    let issued = client.fresh_chat_inventory(&cancel).unwrap().unwrap();
    client.session.as_mut().unwrap().paired_session_expires_at = Some(1);
    assert!(matches!(issued.consume_if_current(&client, &cancel), Err(Error::Expired)));
    let mut client = guard_client();
    let issued = client.fresh_chat_inventory(&cancel).unwrap().unwrap();
    client.forget_session();
    assert!(matches!(issued.consume_if_current(&client, &cancel), Err(Error::Authentication)));

    // Session errors remain errors even when another stale-binding shortcut
    // applies; callers must not turn a known denial into ordinary no-proof.
    let mut client = guard_client();
    let issued = client.fresh_chat_inventory(&cancel).unwrap().unwrap();
    client.set_operation_cancel(CancellationToken::new());
    client.session.as_mut().unwrap().paired_session_expires_at = Some(1);
    assert!(matches!(issued.consume_if_current(&client, &cancel), Err(Error::Expired)));

    let mut client = guard_client();
    let issued = client.fresh_chat_inventory(&cancel).unwrap().unwrap();
    client.forget_session();
    assert!(matches!(issued.consume_if_current(&client, &CancellationToken::new()), Err(Error::Authentication)));

    // Caller cancellation retains its original precedence even after logout.
    let mut client = guard_client();
    let stopped = CancellationToken::new();
    let issued = client.fresh_chat_inventory(&stopped).unwrap().unwrap();
    client.forget_session();
    stopped.cancel();
    assert!(matches!(issued.consume_if_current(&client, &stopped), Err(Error::Cancelled)));

    // A still-valid session with only a replaced operation is stale, not an
    // authentication failure, and must never receive reusable inventory.
    let mut client = guard_client();
    let issued = client.fresh_chat_inventory(&cancel).unwrap().unwrap();
    client.set_operation_cancel(CancellationToken::new());
    assert!(!issued.consume_if_current(&client, &cancel).unwrap());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,auth.session.authoritative-enforcement
#[tokio::test]
async fn original_pending_main_lease_prevents_empty_inventory_without_offer_or_claim() {
    tokio::time::timeout(Duration::from_secs(6),async {
        let peer=Peer::start_protocol(true,true,0,0,0,false,11).await;
        let mut client=peer.client();let cancel=CancellationToken::new();client.set_foreground_completion_recovery(true).unwrap();
        let(jobs,proof)=client.completion_recovery_jobs_with_inventory(&cancel).await.unwrap();
        assert!(jobs.is_empty());assert!(proof.is_none(),"a live pending lease is not absence");
        client.set_foreground_completion_recovery(false).unwrap();client.list(Workspace::Chats).await.unwrap();peer.finish(2).await;
    }).await.unwrap();
}
