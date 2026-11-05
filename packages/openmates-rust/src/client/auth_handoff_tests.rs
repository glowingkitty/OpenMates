// contract-test: supporting surface=cli assertions=chats.persistence.client-encrypted,chats.completion.recovery-takeover
//! Draft real-Client HTTP/WebSocket units; no application/runtime auth bypass.
use super::*;
use futures_util::StreamExt;
use std::sync::atomic::{AtomicBool, AtomicUsize};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_tungstenite::tungstenite::Message;

struct Peer {
    api: String,
    auth: Arc<AtomicUsize>,
    sockets: Arc<AtomicUsize>,
    deny: Arc<AtomicBool>,
    stop: CancellationToken,
    task: tokio::task::JoinHandle<()>,
}
async fn read_request(stream: &mut tokio::net::TcpStream) -> Vec<u8> {
    let mut data = vec![];
    let mut chunk = [0; 4096];
    let end = loop {
        let n = stream.read(&mut chunk).await.unwrap();
        assert!(n > 0);
        data.extend_from_slice(&chunk[..n]);
        if let Some(i) = data.windows(4).position(|v| v == b"\r\n\r\n") {
            break i + 4;
        }
    };
    let head = String::from_utf8_lossy(&data[..end]);
    let length = head
        .lines()
        .find_map(|line| {
            line.to_ascii_lowercase()
                .strip_prefix("content-length:")
                .and_then(|v| v.trim().parse::<usize>().ok())
        })
        .unwrap_or(0);
    while data.len() < end + length {
        let n = stream.read(&mut chunk).await.unwrap();
        assert!(n > 0);
        data.extend_from_slice(&chunk[..n]);
    }
    data
}
impl Peer {
    async fn start() -> Self {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let auth = Arc::new(AtomicUsize::new(0));
        let sockets = Arc::new(AtomicUsize::new(0));
        let deny = Arc::new(AtomicBool::new(false));
        let stop = CancellationToken::new();
        let (auth_count, socket_count, denied, stopping) =
            (auth.clone(), sockets.clone(), deny.clone(), stop.clone());
        let task = tokio::spawn(async move {
            loop {
                let (mut stream, _) = tokio::select! {biased;_=stopping.cancelled()=>break,result=listener.accept()=>result.unwrap()};
                let mut head = [0; 4096];
                let n = loop {
                    let n = stream.peek(&mut head).await.unwrap();
                    assert!(n > 0);
                    if n >= 4 {
                        break n;
                    }
                    tokio::task::yield_now().await;
                };
                if head[..n].starts_with(b"POST ") {
                    let request = read_request(&mut stream).await;
                    let request = String::from_utf8(request).unwrap();
                    assert!(request.starts_with("POST /v1/auth/session HTTP/1.1\r\n"));
                    let headers = request.to_ascii_lowercase();
                    assert!(
                        headers.contains("x-openmates-sdk: rust")
                            || headers.contains("x-openmates-sdk: cli")
                    );
                    let body = request.split_once("\r\n\r\n").unwrap().1;
                    assert_eq!(
                        serde_json::from_str::<Value>(body).unwrap(),
                        json!({"session_id":"fixture"})
                    );
                    let index = auth_count.fetch_add(1, Ordering::SeqCst) + 1;
                    let status = if denied.load(Ordering::SeqCst) {
                        403
                    } else {
                        200
                    };
                    let body=json!({"success":status==200,"ws_token":format!("token-{index}"),"user":{"id":"11111111-1111-4111-8111-111111111111"},"client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]}).to_string();
                    stream.write_all(format!("HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=rotated-{index}; HttpOnly\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
                } else {
                    assert!(head[..n].starts_with(b"GET "));
                    let current = auth_count.load(Ordering::SeqCst);
                    let mut ws=tokio_tungstenite::accept_hdr_async(stream, |request: &tokio_tungstenite::tungstenite::handshake::server::Request, response: tokio_tungstenite::tungstenite::handshake::server::Response| {
                        assert_eq!(request.uri().path(),"/v1/ws");
                        assert!(request.uri().query().unwrap().contains(&format!("token=token-{current}")));
                        Ok(response)
                    }).await.unwrap();
                    socket_count.fetch_add(1, Ordering::SeqCst);
                    let lifecycle: Value =
                        serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap())
                            .unwrap();
                    assert_eq!(lifecycle["type"], "native_client_lifecycle");
                    while let Some(frame) = ws.next().await {
                        if matches!(frame.unwrap(), Message::Close(_)) {
                            let _ = ws.close(None).await;
                            break;
                        }
                    }
                }
            }
        });
        Self {
            api,
            auth,
            sockets,
            deny,
            stop,
            task,
        }
    }
    fn client(&self, cancel: &CancellationToken) -> Client {
        let mut session = super::super::sdk_boundary_tests::session();
        session.api_url = self.api.clone();
        let mut c = Client::new(&self.api, Some(session)).unwrap();
        c.set_operation_cancel(cancel.clone());
        c
    }
    async fn finish(self, auth: usize, sockets: usize) {
        self.stop.cancel();
        self.task.await.unwrap();
        assert_eq!(self.auth.load(Ordering::SeqCst), auth);
        assert_eq!(self.sockets.load(Ordering::SeqCst), sockets);
    }
}
async fn socket(c: &mut Client) {
    c.set_foreground_completion_recovery(true).unwrap();
    c.completion_recovery_socket()
        .await
        .unwrap()
        .close(None)
        .await
        .unwrap();
}
#[tokio::test]
async fn real_validation_issues_one_use_for_live_same_parent_child_rebind() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let p = Peer::start().await;
        let cancel = CancellationToken::new();
        let mut c = p.client(&cancel);
        let token = c
            .validate_session_for_recovery(&cancel)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(p.auth.load(Ordering::SeqCst), 1);
        // Exact revision acknowledgement and no-effect cache revocation stay local.
        c.acknowledge_credentials(c.credential_revision).unwrap();
        c.invalidate_chat_list_freshness();
        c.use_fresh_session_for_recovery(token, &cancel).unwrap();
        c.set_operation_cancel(cancel.clone()); // native's intentional child replacement
        socket(&mut c).await;
        assert_eq!(p.auth.load(Ordering::SeqCst), 1);
        socket(&mut c).await; // consumed; second socket MUST validate normally
        p.finish(2, 2).await;
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn regular_validation_and_unmatched_operation_never_arm_implicit_reuse() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let p = Peer::start().await;
        let cancel = CancellationToken::new();
        let mut c = p.client(&cancel);
        c.validate_session().await.unwrap();
        socket(&mut c).await;
        assert!(
            c.validate_session_for_recovery(&CancellationToken::new())
                .await
                .unwrap()
                .is_none()
        );
        socket(&mut c).await;
        p.finish(4, 2).await;
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn issued_but_unarmed_token_does_not_change_direct_socket_semantics() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let p = Peer::start().await;
        let cancel = CancellationToken::new();
        let mut c = p.client(&cancel);
        let _unused = c
            .validate_session_for_recovery(&cancel)
            .await
            .unwrap()
            .unwrap();
        socket(&mut c).await;
        p.finish(2, 1).await;
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn foreign_identical_client_restart_and_nonrecovery_socket_cannot_inherit_handoff() {
    tokio::time::timeout(Duration::from_secs(8), async {
        for scenario in 0..3 {
            let p = Peer::start().await;
            let cancel = CancellationToken::new();
            let mut original = p.client(&cancel);
            let token = original
                .validate_session_for_recovery(&cancel)
                .await
                .unwrap()
                .unwrap();
            if scenario < 2 {
                let snapshot = original.ciphertext_snapshot();
                let mut c = Client::new(&p.api, original.clone_session()).unwrap();
                c.set_operation_cancel(cancel.clone());
                c.user = original.user.clone();
                if scenario == 1 {
                    c.restore_authenticated_ciphertext_snapshot(&snapshot)
                        .unwrap();
                }
                c.use_fresh_session_for_recovery(token, &cancel).unwrap();
                socket(&mut c).await;
            } else {
                original
                    .use_fresh_session_for_recovery(token, &cancel)
                    .unwrap();
                original
                    .passive_chat_monitor_socket()
                    .await
                    .unwrap()
                    .close(None)
                    .await
                    .unwrap();
                socket(&mut original).await;
            }
            p.finish(
                if scenario < 2 { 2 } else { 3 },
                if scenario < 2 { 1 } else { 2 },
            )
            .await;
        }
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn identity_credential_network_scope_time_and_rebound_cancellation_mutations_fallback() {
    tokio::time::timeout(Duration::from_secs(15), async {
        for scenario in 0..18 {
            let p = Peer::start().await;
            let cancel = CancellationToken::new();
            let mut c = p.client(&cancel);
            let mut token = c
                .validate_session_for_recovery(&cancel)
                .await
                .unwrap()
                .unwrap();
            match scenario {
                0 => c.set_identity(ClientIdentity::Cli),
                1 => c
                    .set_app_origin(Some("https://changed.example".into()))
                    .unwrap(),
                2 => c.session.as_mut().unwrap().master_key = Zeroizing::new([9; 32]),
                3 => {
                    c.cookies.insert("fixture".into(), "changed".into());
                }
                4 => c.session.as_mut().unwrap().ws_token = Some("changed".into()),
                5 => c.credentials_changed(),
                6 => assert!(
                    c.request(Method::GET, "//127.0.0.1:1/blocked", None)
                        .await
                        .is_err()
                ),
                7 => c
                    .set_team(Some("11111111-1111-4111-8111-111111111111"))
                    .unwrap(),
                8 => token.validated_at = Instant::now() - Duration::from_secs(6),
                9 => token.validated_at = Instant::now() + Duration::from_secs(1),
                10 => {
                    c.operation_cancel.cancel();
                    c.set_operation_cancel(cancel.clone());
                }
                11 => {
                    let snapshot = c.ciphertext_snapshot();
                    c.restore_ciphertext_snapshot(&snapshot).unwrap();
                }
                12 => c.user["id"] = json!("changed-owner"),
                13 => c.session.as_mut().unwrap().created_at = 2,
                14 => {
                    c.set_interactive(true);
                    c.set_interactive(false);
                }
                15 => {
                    c.set_identity(ClientIdentity::Cli);
                    c.set_identity(ClientIdentity::Rust);
                }
                16 => {
                    c.set_app_origin(Some("https://changed.example".into()))
                        .unwrap();
                    c.set_app_origin(None).unwrap();
                }
                _ => c.set_team(None).unwrap(), // Public same-scope setter still invalidates.
            }
            c.use_fresh_session_for_recovery(token, &cancel).unwrap();
            if scenario == 12 {
                // A real cookie merge observes the changed live principal and
                // retires its old authority. That original auth response must
                // not cross into a replacement owner or open a socket.
                let original = c.task_watch_authority.clone();
                c.set_foreground_completion_recovery(true).unwrap();
                assert!(matches!(c.completion_recovery_socket().await, Err(Error::Cancelled)));
                assert!(original.cancel.is_cancelled());
                assert!(!Arc::ptr_eq(&original, &c.task_watch_authority));
                assert_eq!(c.cookies.get("auth_refresh_token").map(String::as_str), Some("rotated-2"));
                assert_eq!(c.session.as_ref().unwrap().ws_token.as_deref(), Some("token-1"));
                assert_eq!(c.user["id"], "changed-owner");
                assert!(!cancel.is_cancelled());
                assert!(!c.operation_parent.is_cancelled());
                p.finish(2, 0).await;
                continue;
            }
            socket(&mut c).await;
            p.finish(2, 1).await;
        }
    })
    .await
    .unwrap();
}
#[tokio::test]
async fn cancelled_or_expired_operation_and_server_denial_never_authorize_socket() {
    tokio::time::timeout(Duration::from_secs(8), async {
        for scenario in 0..4 {
            let p = Peer::start().await;
            let cancel = CancellationToken::new();
            let mut c = p.client(&cancel);
            let token = c
                .validate_session_for_recovery(&cancel)
                .await
                .unwrap()
                .unwrap();
            match scenario {
                0 => cancel.cancel(),
                1 => c.operation_cancel.cancel(),
                2 => c.session.as_mut().unwrap().paired_session_expires_at = Some(1),
                _ => {
                    p.deny.store(true, Ordering::SeqCst);
                    c.invalidate_chat_inventory_proofs();
                }
            }
            if scenario < 3 {
                assert!(matches!(
                    c.use_fresh_session_for_recovery(token, &cancel),
                    Err(Error::Cancelled | Error::Expired)
                ));
                p.finish(1, 0).await;
            } else {
                c.use_fresh_session_for_recovery(token, &cancel).unwrap();
                c.set_foreground_completion_recovery(true).unwrap();
                assert!(matches!(
                    c.completion_recovery_socket().await,
                    Err(Error::Expired)
                ));
                assert!(c.session().is_none());
                p.finish(2, 0).await;
            }
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn armed_proof_cannot_cross_actual_cancellation_expiry_or_next_parent() {
    tokio::time::timeout(Duration::from_secs(8), async {
        for scenario in 0..4 {
            let p = Peer::start().await;
            let cancel = CancellationToken::new();
            let mut c = p.client(&cancel);
            let token = c
                .validate_session_for_recovery(&cancel)
                .await
                .unwrap()
                .unwrap();
            c.use_fresh_session_for_recovery(token, &cancel).unwrap();
            c.set_foreground_completion_recovery(true).unwrap();
            match scenario {
                0 => cancel.cancel(),
                1 => c.operation_cancel.cancel(),
                2 => c.session.as_mut().unwrap().paired_session_expires_at = Some(1),
                _ => c.set_operation_cancel(CancellationToken::new()),
            }
            if scenario < 3 {
                assert!(matches!(
                    c.completion_recovery_socket().await,
                    Err(Error::Cancelled | Error::Expired)
                ));
                p.finish(1, 0).await;
            } else {
                c.completion_recovery_socket()
                    .await
                    .unwrap()
                    .close(None)
                    .await
                    .unwrap();
                p.finish(2, 1).await;
            }
        }
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn browser_authority_does_not_issue_or_reuse_native_recovery_admission() {
    tokio::time::timeout(Duration::from_secs(5), async {
        let p = Peer::start().await;
        let cancel = CancellationToken::new();
        let mut c = p.client(&cancel);
        c.browser_authority = Some(super::super::browser::BrowserAuthority {
            principal: "11111111-1111-4111-8111-111111111111".into(),
            persistence: super::super::BrowserPersistence::MemoryOnly,
            owner_guards: false,
        });
        assert!(
            c.validate_session_for_recovery(&cancel)
                .await
                .unwrap()
                .is_none()
        );
        socket(&mut c).await;
        p.finish(2, 1).await;
    })
    .await
    .unwrap();
}

#[tokio::test]
async fn changed_session_or_api_binding_discards_token_even_when_restored_before_socket() {
    tokio::time::timeout(Duration::from_secs(5), async {
        for change_api in [false, true] {
            let p = Peer::start().await;
            let cancel = CancellationToken::new();
            let mut c = p.client(&cancel);
            let token = c
                .validate_session_for_recovery(&cancel)
                .await
                .unwrap()
                .unwrap();
            let old = c.session.as_ref().unwrap().clone();
            if change_api {
                c.session.as_mut().unwrap().api_url = "https://different.example".into();
            } else {
                c.session.as_mut().unwrap().session_id = "another-session".into();
            }
            c.use_fresh_session_for_recovery(token, &cancel).unwrap();
            c.session = Some(old); // Consumed mismatch cannot resurrect on restore.
            socket(&mut c).await;
            p.finish(2, 1).await;
        }
    })
    .await
    .unwrap();
}
