// Supporting SDK primitive/loopback coverage; no end-to-end or native execution claim.
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
use super::*;
use futures_util::{SinkExt, StreamExt};
use tokio::net::{TcpListener, TcpStream};
use tokio_tungstenite::{WebSocketStream, tungstenite::Message};
const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
struct ReadAdapter;
impl SourceHostAdapter for ReadAdapter {
    fn implemented_capabilities(&self) -> Vec<ProjectSourceCapability> {
        vec![ProjectSourceCapability::Read]
    }
    fn supports_operation(&self, op: SourceHostOperation) -> bool {
        matches!(
            op,
            SourceHostOperation::List
                | SourceHostOperation::ReadText
                | SourceHostOperation::ReadImageChunk
                | SourceHostOperation::ReadFileChunk
        )
    }
}
fn client(api: &str) -> Client {
    let mut client = Client::new(
        api,
        Some(Session {
            api_url: api.into(),
            session_id: "cookie-session".into(),
            cookies: Default::default(),
            ws_token: Some("fixture-token".into()),
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "private-fixture".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap();
    client.user = json!({"id":"host"});
    client
}
fn binding(client: &Client) -> SourceHostBinding {
    client
        .bind_source_host(
            SourceHostScope {
                api: client.base.as_str().trim_end_matches('/').into(),
                owner: "host".into(),
                team: None,
                project: PROJECT.into(),
                source: "source".into(),
                key_epoch: 1,
            },
            zeroize::Zeroizing::new([8; 32]),
            Arc::new(ReadAdapter),
            vec![ProjectSourceCapability::Read],
        )
        .unwrap()
}
struct CheckHostHandshake;
impl tokio_tungstenite::tungstenite::handshake::server::Callback for CheckHostHandshake {
    fn on_request(
        self,
        request: &tokio_tungstenite::tungstenite::handshake::server::Request,
        response: tokio_tungstenite::tungstenite::handshake::server::Response,
    ) -> std::result::Result<
        tokio_tungstenite::tungstenite::handshake::server::Response,
        tokio_tungstenite::tungstenite::handshake::server::ErrorResponse,
    > {
        let url = url::Url::parse(&format!("http://mock{}", request.uri())).unwrap();
        assert_eq!(
            url.query_pairs()
                .find(|(k, _)| k == "client_capabilities")
                .unwrap()
                .1,
            ""
        );
        Ok(response)
    }
}
struct Peer(WebSocketStream<TcpStream>);
impl Peer {
    async fn send(&mut self, kind: &str, value: Value) {
        self.0
            .send(Message::Text(
                json!({"type":kind,"payload":value}).to_string().into(),
            ))
            .await
            .unwrap()
    }
    async fn read(&mut self) -> Value {
        match self.0.next().await.unwrap().unwrap() {
            Message::Text(v) => serde_json::from_str(&v).unwrap(),
            other => panic!("unexpected mock frame {other:?}"),
        }
    }
}
async fn pair() -> (Client, SourceHostSession, Peer) {
    pair_with_cancel(CancellationToken::new()).await
}
async fn pair_with_cancel(caller: CancellationToken) -> (Client, SourceHostSession, Peer) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let client = client(&api);
    let start = client
        .prepare_source_host(
            vec![binding(&client)],
            SourceHostOptions {
                source_session_id: "source-session".into(),
                confirmed_takeover: false,
            },
            caller,
        )
        .unwrap();
    let server = async {
        let (socket, _) = listener.accept().await.unwrap();
        let ws = tokio_tungstenite::accept_hdr_async(socket, CheckHostHandshake)
            .await
            .unwrap();
        let mut peer = Peer(ws);
        let lifecycle = peer.read().await;
        assert_eq!(lifecycle["type"], "native_client_lifecycle");
        assert_eq!(lifecycle["payload"]["interactive"], false);
        let register = peer.read().await;
        assert_eq!(register["type"], "project_remote_access_register");
        assert_eq!(register["payload"]["confirmed_takeover"], false);
        // npm registers `import` alongside `read` (imports are host reads).
        assert_eq!(
            register["payload"]["bindings"][0]["capabilities"],
            json!(["read", "import"])
        );
        peer.send("project_remote_access_registered",json!({"source_session_id":"source-session","heartbeat_interval_seconds":15,"deadline_at":now_ms()/1000+45,"replaced_session_id":null})).await;
        peer
    };
    let (host, peer) = tokio::join!(start.connect(), server);
    (client, host.unwrap(), peer)
}
fn request(id: &str) -> Value {
    json!({"request_id":id,"project_id":PROJECT,"source_id":"source","source_session_id":"source-session","requesting_client_id":"requester","operation":"read_text","key_epoch":1,"encrypted_envelope":"opaque-ciphertext"})
}
async fn next_read(host: &mut SourceHostSession) -> SourceHostRead {
    loop {
        if let SourceHostPoll::Read(value) = host.poll(&CancellationToken::new()).await.unwrap() {
            return value;
        }
    }
}
async fn bounded(future: impl std::future::Future<Output = ()>) {
    tokio::time::timeout(Duration::from_secs(5), future)
        .await
        .unwrap()
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn exact_register_and_one_use_opaque_completion_preserve_ciphertext() {
    bounded(async {
        let (mut client, mut host, mut peer) = pair().await;
        peer.send("project_remote_access_request", request("r1"))
            .await;
        let read = next_read(&mut host).await;
        let pending = client.finish_source_host_read(&host, read).unwrap();
        assert_eq!(
            pending.provisional_envelope().unwrap().encrypted_envelope,
            "opaque-ciphertext"
        );
        assert!(pending.server_acknowledgement_required());
        let cancel = CancellationToken::new();
        let completion = host.complete(pending, "opaque-result".into(), &cancel);
        let server = async {
            let sent = peer.read().await;
            assert_eq!(sent["type"], "project_remote_access_complete");
            assert_eq!(sent["payload"]["encrypted_envelope"], "opaque-result");
            assert_eq!(sent["payload"]["request_id"], "r1");
            peer.send(
                "project_remote_access_completion_ack",
                json!({"request_id":"r1","accepted":true}),
            )
            .await;
        };
        let (result, ()) = tokio::join!(completion, server);
        result.unwrap();
        assert!(host.pending.is_empty());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn heartbeat_ack_is_correlated_and_never_implicitly_grants_request_permission() {
    bounded(async {
        let (_client, mut host, mut peer) = pair().await;
        assert!(host.check().is_ok());
        assert!(matches!(
            host.heartbeat(&CancellationToken::new()).await,
            Err(Error::Invalid(_))
        ));
        host.heartbeat_sent = Instant::now() - HEARTBEAT_INTERVAL;
        let cancel = CancellationToken::new();
        let heartbeat = host.heartbeat(&cancel);
        let server = async {
            assert_eq!(peer.read().await["type"], "project_remote_access_heartbeat");
            peer.send(
                "project_remote_access_heartbeat_ack",
                json!({"accepted":true,"deadline_at":now_ms()/1000+45}),
            )
            .await;
        };
        let (result, ()) = tokio::join!(heartbeat, server);
        result.unwrap();
        assert!(host.pending.is_empty());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn full_pending_bound_and_scope_or_unsupported_operation_fail_closed() {
    bounded(async {
        let (_client, mut host, _peer) = pair().await;
        assert!(host.check().is_ok());
        let mut foreign = request("foreign");
        foreign["source_id"] = json!("other");
        assert!(host.queue_request(foreign).is_err());
        let mut unsupported = request("unsupported");
        unsupported["operation"] = json!("search");
        assert!(host.queue_request(unsupported).is_err());
        for i in 0..4 {
            host.queue_request(request(&format!("r{i}"))).unwrap()
        }
        assert_eq!(host.queued.len(), 4);
        assert!(matches!(
            host.queue_request(request("overflow")),
            Err(Error::Conflict)
        ));
        assert_eq!(host.queued.len(), 4);
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn logout_and_close_fence_provisional_handles() {
    bounded(async {
        let (mut client, mut host, mut peer) = pair().await;
        peer.send("project_remote_access_request", request("r1"))
            .await;
        let read = next_read(&mut host).await;
        let handle = client.finish_source_host_read(&host, read).unwrap();
        host.close();
        assert!(handle.provisional_envelope().is_err());
        let (mut client, mut host, mut peer) = pair().await;
        peer.send("project_remote_access_request", request("r2"))
            .await;
        let read = next_read(&mut host).await;
        let handle = client.finish_source_host_read(&host, read).unwrap();
        client.forget_session();
        assert!(handle.provisional_envelope().is_err());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn source_handshake_reuses_sdk_identity_bound_crypto_and_replay_protection() {
    bounded(async {
        use crate::remote_access_crypto::{HandshakeState, Identity, Role};
        let (mut client, mut host, mut peer) = pair().await;
        peer.send("project_remote_access_request", request("r1"))
            .await;
        let read = next_read(&mut host).await;
        let handle = client.finish_source_host_read(&host, read).unwrap();
        let source = host.source_handshake(&handle).unwrap();
        let requester = HandshakeState::new(
            &[8; 32],
            Identity {
                owner_id: "host".into(),
                context_type: None,
                context_id: None,
                project_id: PROJECT.into(),
                source_id: "source".into(),
                source_session_id: "source-session".into(),
                requesting_client_id: "requester".into(),
                host_member_id: None,
                host_device_id: None,
                requester_member_id: None,
                requester_device_id: None,
                key_epoch: 1,
            },
            Role::Requester,
        )
        .unwrap();
        let source_handshake = source.handshake().unwrap();
        let requester_handshake = requester.handshake();
        let mut source = source.finish(&requester_handshake).unwrap();
        let mut requester = requester.finish(&source_handshake).unwrap();
        let envelope = requester.seal("r1", b"opaque operation").unwrap();
        assert_eq!(&*source.open(&envelope).unwrap(), b"opaque operation");
        assert!(source.open(&envelope).is_err());
        let response = source.seal(b"opaque result").unwrap();
        assert_eq!(&*requester.open("r1", &response).unwrap(), b"opaque result");
        host.close();
        assert!(source.seal(b"after close").is_err());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn reset_fences_old_host_and_late_logout_never_clears_new_identity() {
    bounded(async {
        let (mut client, host, _peer) = pair().await;
        let session = client.clone_session().unwrap();
        let api = session.api_url.clone();
        client.reset(&api, Some(session)).unwrap();
        assert!(matches!(
            client.finish_source_host_failure(&host, Error::Expired),
            Err(Error::Cancelled)
        ));
        assert!(client.session().is_some());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn generic_control_error_and_wrong_completion_ack_close_without_retry() {
    bounded(async {
        for forbidden in [false, true] {
            let (mut client, mut host, mut peer) = pair().await;
            peer.send("project_remote_access_request", request("r1"))
                .await;
            let read = next_read(&mut host).await;
            let handle = client.finish_source_host_read(&host, read).unwrap();
            let cancel = CancellationToken::new();
            let completion = host.complete(handle, "opaque-result".into(), &cancel);
            let server = async {
                let sent = peer.read().await;
                assert_eq!(sent["type"], "project_remote_access_complete");
                if forbidden {
                    peer.send("error", json!({"code":"request_scope_mismatch"}))
                        .await;
                } else {
                    peer.send(
                        "project_remote_access_completion_ack",
                        json!({"request_id":"other","accepted":true}),
                    )
                    .await;
                }
            };
            let (result, ()) = tokio::join!(completion, server);
            assert_eq!(
                result.err(),
                Some(if forbidden {
                    Error::Forbidden
                } else {
                    Error::Protocol
                })
            );
            assert!(host.terminal);
            assert!(host.pending.is_empty());
        }
    })
    .await
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn caller_cancellation_immediately_fences_issued_read_request_handshake_and_crypto_without_poll()
 {
    bounded(async {
        use crate::remote_access_crypto::{HandshakeState, Identity, Role};
        let caller = CancellationToken::new();
        let unrelated = CancellationToken::new();
        let (mut client, mut host, mut peer) = pair_with_cancel(caller.clone()).await;
        peer.send("project_remote_access_request", request("opaque-read"))
            .await;
        let opaque_read = next_read(&mut host).await;
        peer.send("project_remote_access_request", request("request"))
            .await;
        let r = next_read(&mut host).await;
        let pending = client.finish_source_host_read(&host, r).unwrap();
        peer.send("project_remote_access_request", request("handshake"))
            .await;
        let r = next_read(&mut host).await;
        let handshake_request = client.finish_source_host_read(&host, r).unwrap();
        let handshake = host.source_handshake(&handshake_request).unwrap();
        peer.send("project_remote_access_request", request("crypto"))
            .await;
        let r = next_read(&mut host).await;
        let crypto_request = client.finish_source_host_read(&host, r).unwrap();
        let source = host.source_handshake(&crypto_request).unwrap();
        let requester = HandshakeState::new(
            &[8; 32],
            Identity {
                owner_id: "host".into(),
                context_type: None,
                context_id: None,
                project_id: PROJECT.into(),
                source_id: "source".into(),
                source_session_id: "source-session".into(),
                requesting_client_id: "requester".into(),
                host_member_id: None,
                host_device_id: None,
                requester_member_id: None,
                requester_device_id: None,
                key_epoch: 1,
            },
            Role::Requester,
        )
        .unwrap();
        let source_handshake = source.handshake().unwrap();
        let requester_handshake = requester.handshake();
        let mut crypto = source.finish(&requester_handshake).unwrap();
        let mut requester = requester.finish(&source_handshake).unwrap();
        let envelope = requester.seal("crypto", b"provisional").unwrap();
        caller.cancel();
        // No Session poll/close/heartbeat/complete is called between cancellation
        // and the issued-object checks; downward propagation must be sufficient.
        assert!(matches!(
            pending.provisional_envelope(),
            Err(Error::Cancelled)
        ));
        assert!(matches!(handshake.handshake(), Err(Error::Cancelled)));
        assert!(matches!(
            handshake.finish(&requester_handshake),
            Err(Error::Cancelled)
        ));
        assert!(matches!(crypto.seal(b"result"), Err(Error::Cancelled)));
        assert!(matches!(crypto.open(&envelope), Err(Error::Cancelled)));
        assert!(matches!(
            client.finish_source_host_read(&host, opaque_read),
            Err(Error::Cancelled)
        ));
        assert!(!unrelated.is_cancelled());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn local_close_never_cancels_caller_or_other_caller_child() {
    bounded(async {
        let caller = CancellationToken::new();
        let sibling = caller.child_token();
        let (_client, mut host, _peer) = pair_with_cancel(caller.clone()).await;
        assert!(host.check().is_ok());
        host.close();
        assert!(!caller.is_cancelled());
        assert!(!sibling.is_cancelled());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn whole_io_budget_includes_an_initial_blocked_phase_before_ack_processing() {
    bounded(async {
        let caller = CancellationToken::new();
        let owner = CancellationToken::new();
        let lifetime = caller.child_token();
        // This pure boundary fixture blocks the first awaited phase. Production
        // wraps send+ACK, and connect+initial lifecycle, inside this same boundary.
        let started = Instant::now();
        let result: Result<()> = bounded_host_io(
            Duration::from_millis(20),
            &caller,
            &owner,
            &lifetime,
            None,
            None,
            std::future::pending(),
        )
        .await;
        assert_eq!(result, Err(Error::Offline));
        assert!(started.elapsed() < Duration::from_secs(1));
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn real_pending_websocket_handshake_observes_caller_cancellation() {
    bounded(async {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let client = client(&api);
        let caller = CancellationToken::new();
        let start = client
            .prepare_source_host(
                vec![binding(&client)],
                SourceHostOptions {
                    source_session_id: "source-session".into(),
                    confirmed_takeover: false,
                },
                caller.clone(),
            )
            .unwrap();
        let stalled_peer = async {
            let (_socket, _) = listener.accept().await.unwrap();
            caller.cancel();
            tokio::time::sleep(Duration::from_millis(50)).await;
        };
        let (result, ()) = tokio::join!(start.connect(), stalled_peer);
        assert!(matches!(result, Err(Error::Cancelled)));
        assert!(!client.task_watch_authority.cancel.is_cancelled());
    })
    .await
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only,auth.session.authoritative-enforcement,auth.session.isolation
#[tokio::test]
async fn real_control_ack_wait_observes_parent_cancellation_and_fences_issued_handles() {
    bounded(async {
        let caller = CancellationToken::new();
        let (mut client, mut host, mut peer) = pair_with_cancel(caller.clone()).await;
        peer.send("project_remote_access_request", request("r1"))
            .await;
        let r = next_read(&mut host).await;
        let handle = client.finish_source_host_read(&host, r).unwrap();
        host.heartbeat_sent = Instant::now() - HEARTBEAT_INTERVAL;
        let operation_cancel = CancellationToken::new();
        let heartbeat = host.heartbeat(&operation_cancel);
        let server = async {
            assert_eq!(peer.read().await["type"], "project_remote_access_heartbeat");
            caller.cancel();
        };
        let (result, ()) = tokio::join!(heartbeat, server);
        assert_eq!(result, Err(Error::Cancelled));
        assert!(matches!(
            handle.provisional_envelope(),
            Err(Error::Cancelled)
        ));
        assert!(!operation_cancel.is_cancelled());
        assert!(host.terminal);
    })
    .await
}
