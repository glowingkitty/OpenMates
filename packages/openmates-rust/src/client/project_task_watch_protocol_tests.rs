//! Synthetic loopback only. These tests exercise the staged task socket/reducer,
//! not backend authorization or a native/foreign foreground actor.
use super::*;
use crate::project_task_sync::TaskSyncFrame;
use futures_util::{SinkExt, StreamExt};
use sha2::{Digest, Sha256};
use std::future::Future;
use tokio::{
    net::{TcpListener, TcpStream},
    sync::{Mutex, oneshot},
};
use tokio_tungstenite::{
    WebSocketStream,
    tungstenite::{
        Message,
        handshake::server::{ErrorResponse, Request, Response},
    },
};

const OWNER: &str = "synthetic-owner";
const PROJECT: &str = "11111111-1111-4111-8111-111111111111";
const SOURCE: &str = "synthetic-source";
const TEAM: &str = "22222222-2222-4222-8222-222222222222";
const PROJECT_KEY: [u8; 32] = [3; 32];
const TASK_KEY: [u8; 32] = [7; 32];

async fn bounded<T>(future: impl Future<Output = T>) -> T {
    tokio::time::timeout(Duration::from_secs(5), future)
        .await
        .expect("bounded synthetic Task watch fixture")
}
fn hash(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}
fn current_seconds() -> u64 {
    now_ms() / 1000
}
fn raw_task(id: &str, workspace: &TaskSyncWorkspace, expires: Option<u64>) -> Value {
    json!({"task_id":id,"version":1,"status":"todo", "hashed_user_id":hash(OWNER),
        "hashed_team_id":match workspace { TaskSyncWorkspace::Personal => Value::Null,
            TaskSyncWorkspace::Team(team) => json!(hash(team)) },
        "encrypted_title":crypto::encrypt_combined(&format!("Synthetic task {id}"), &TASK_KEY).unwrap(),
        "encrypted_description":crypto::encrypt_combined("Synthetic private description", &TASK_KEY).unwrap(),
        "key_wrappers":[{"key_type":"project","hashed_project_id":hash(PROJECT),
            "hashed_task_id":hash(id),"hashed_user_id":hash(OWNER),"expires_at":expires,
            "encrypted_task_key":crypto::encrypt_bytes(&TASK_KEY,&PROJECT_KEY).unwrap()}],
        "dependencies":[]})
}
fn frame(
    batch: &str,
    sequence: u64,
    part: u32,
    final_part: bool,
    reset: bool,
    tasks: Vec<Value>,
    removed: Vec<String>,
) -> Value {
    serde_json::to_value(TaskSyncFrame {
        project_id: PROJECT.into(),
        batch_id: batch.into(),
        part,
        final_part,
        reset,
        cursor: format!("epoch:{sequence}"),
        tasks,
        removed_task_ids: removed,
    })
    .unwrap()
}
struct Peer {
    listener: TcpListener,
    endpoint: String,
}
struct PeerSocket(WebSocketStream<TcpStream>);
// Tungstenite requires its large HTTP ErrorResponse in this callback signature.
// No secret-bearing response or error content is logged by the fixture.
#[allow(clippy::result_large_err)]
fn handshake(
    request: &Request,
    response: Response,
) -> std::result::Result<Response, ErrorResponse> {
    let url = url::Url::parse(&format!("http://127.0.0.1{}", request.uri())).unwrap();
    assert_eq!(url.path(), "/v1/ws");
    let parameters = url.query_pairs().collect::<BTreeMap<_, _>>();
    assert_eq!(parameters.len(), 3);
    assert_eq!(
        parameters.get("client_capabilities").map(|v| v.as_ref()),
        Some("")
    );
    assert_eq!(
        parameters.get("token").map(|v| v.as_ref()),
        Some("synthetic-ws")
    );
    assert!(
        parameters
            .get("sessionId")
            .is_some_and(|id| uuid::Uuid::parse_str(id).is_ok())
    );
    assert_eq!(request.headers()["x-openmates-sdk"], "rust");
    assert_eq!(request.headers()["origin"], "https://app.example.invalid");
    assert_eq!(
        request.headers()["cookie"],
        "auth_refresh_token=synthetic-cookie"
    );
    assert!(!request.headers().contains_key("authorization"));
    Ok(response)
}
impl Peer {
    async fn new() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let endpoint = format!("http://{}", listener.local_addr().unwrap());
        Self { listener, endpoint }
    }
    fn client(&self) -> Client {
        let mut client = Client::with_options(
            &self.endpoint,
            Some(Session {
                api_url: self.endpoint.clone(),
                session_id: "synthetic-session".into(),
                cookies: BTreeMap::from([("auth_refresh_token".into(), "synthetic-cookie".into())]),
                ws_token: Some("synthetic-ws".into()),
                master_key: zeroize::Zeroizing::new(PROJECT_KEY),
                hashed_email: "synthetic-email-hash".into(),
                user_email_salt: "".into(),
                email_encryption_key: None,
                created_at: now_ms(),
                paired_session_expires_at: None,
                active_team_id: None,
            }),
            ClientOptions {
                app_url: Some("https://app.example.invalid".into()),
                ..Default::default()
            },
        )
        .unwrap();
        // The actual source-authorization HTTP contract requires a separate
        // fixture. This private seam supplies explicit already-authorized owner.
        client.user = json!({"id":OWNER});
        client.credentials_changed();
        client
    }
    async fn accept(&self, workspace: &TaskSyncWorkspace, cursor: Option<&str>) -> PeerSocket {
        self.accept_project(workspace, cursor, PROJECT).await
    }
    async fn accept_project(
        &self,
        workspace: &TaskSyncWorkspace,
        cursor: Option<&str>,
        project: &str,
    ) -> PeerSocket {
        let (stream, address) = self.listener.accept().await.unwrap();
        assert!(address.ip().is_loopback());
        let mut socket = PeerSocket(
            tokio_tungstenite::accept_hdr_async(stream, handshake)
                .await
                .unwrap(),
        );
        let lifecycle = socket.read().await;
        assert_eq!(
            lifecycle,
            json!({"type":"native_client_lifecycle","payload":{
            "client_type":"rust","is_foreground":false,"interactive":false}})
        );
        let subscription = socket.read().await;
        let mut expected = json!({"type":"project_task_sync_subscribe","payload":{"bindings":[{
            "project_id":project,"source_id":SOURCE,"cursor":cursor}]}});
        if let TaskSyncWorkspace::Team(team) = workspace {
            expected["payload"]["team_id"] = json!(team);
        }
        assert_eq!(subscription, expected);
        socket
    }
    fn prepare(
        &self,
        client: &Client,
        workspace: TaskSyncWorkspace,
        cancel: CancellationToken,
    ) -> ProjectTaskWatchStart {
        let binding = client
            .bind_project_task_source(
                workspace,
                PROJECT,
                SOURCE,
                zeroize::Zeroizing::new(PROJECT_KEY),
            )
            .unwrap();
        let sync = binding.new_sync(None, current_seconds()).unwrap();
        client
            .prepare_project_task_watch(binding, sync, cancel)
            .unwrap()
    }
    async fn connect(
        &self,
        start: ProjectTaskWatchStart,
        workspace: &TaskSyncWorkspace,
    ) -> (ProjectTaskWatch, PeerSocket) {
        let (watch, peer) = tokio::join!(start.connect(), self.accept(workspace, None));
        (watch.unwrap(), peer)
    }
    async fn open(
        &self,
        client: &Client,
        workspace: TaskSyncWorkspace,
    ) -> (ProjectTaskWatch, PeerSocket) {
        let start = self.prepare(client, workspace.clone(), CancellationToken::new());
        self.connect(start, &workspace).await
    }
    async fn reconnect(
        &self,
        client: &Client,
        watch: &mut ProjectTaskWatch,
        expected_cursor: &str,
    ) -> PeerSocket {
        // Socket cursor plumbing uses explicit same-authority setup. Fresh REST
        // Project/source reauthorization remains a separate required fixture.
        let prepared = ProjectTaskWatchReconnect {
            socket: client.prepare_task_socket().unwrap(),
            authority: watch.binding.authority.clone(),
            scope: watch.scope().clone(),
        };
        let workspace = watch.scope().workspace().clone();
        let cancel = CancellationToken::new();
        let (result, peer) = tokio::join!(
            watch.reconnect(prepared, &cancel),
            self.accept(&workspace, Some(expected_cursor))
        );
        result.unwrap();
        peer
    }
}
impl PeerSocket {
    async fn read(&mut self) -> Value {
        loop {
            match self.0.next().await.unwrap().unwrap() {
                Message::Text(text) => return serde_json::from_str(&text).unwrap(),
                Message::Ping(bytes) => self.0.send(Message::Pong(bytes)).await.unwrap(),
                _ => panic!("unexpected synthetic peer setup frame"),
            }
        }
    }
    async fn send(&mut self, kind: &str, payload: Value) {
        self.0
            .send(Message::Text(
                json!({"type":kind,"payload":payload}).to_string().into(),
            ))
            .await
            .unwrap();
    }
    async fn batch(&mut self, payload: Value) {
        self.send("project_task_sync", payload).await;
    }
    async fn no_task_writes(&mut self) {
        // commit is local. No invented ACK, host registration/heartbeat,
        // active-chat or mutation message may be emitted after subscription.
        match tokio::time::timeout(Duration::from_millis(30), self.0.next()).await {
            Err(_) | Ok(None) | Ok(Some(Ok(Message::Close(_)))) => {}
            // Revocation synchronously drops the detached socket. Its TCP EOF
            // is a terminal transport outcome, never an application write.
            Ok(Some(Err(tokio_tungstenite::tungstenite::Error::Protocol(
                tokio_tungstenite::tungstenite::error::ProtocolError::ResetWithoutClosingHandshake,
            )))) => {}
            other => panic!("unexpected task-only application write: {other:?}"),
        }
    }
}
async fn next_read(watch: &mut ProjectTaskWatch) -> ProjectTaskWatchRead {
    let cancel = CancellationToken::new();
    loop {
        match watch.poll(&cancel, current_seconds()).await.unwrap() {
            ProjectTaskWatchPoll::Idle => {}
            ProjectTaskWatchPoll::Read(read) => return read,
        }
    }
}
async fn publication(client: &mut Client, watch: &mut ProjectTaskWatch) -> ProjectTaskPublication {
    let read = next_read(watch).await;
    client
        .finish_project_task_watch_read(watch, read)
        .unwrap()
        .expect("final candidate")
}
async fn seed(client: &mut Client, watch: &mut ProjectTaskWatch, peer: &mut PeerSocket) {
    let task = raw_task("original", watch.scope().workspace(), None);
    peer.batch(frame("seed", 1, 0, true, true, vec![task], vec![]))
        .await;
    let ready = publication(client, watch).await;
    watch.commit(ready.receipt().unwrap()).unwrap();
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn personal_and_team_twenty_one_records_publish_contiguous_final_then_delta_and_empty_ready()
{
    bounded(async {
        for workspace in [
            TaskSyncWorkspace::Personal,
            TaskSyncWorkspace::Team(TEAM.into()),
        ] {
            let peer = Peer::new().await;
            let mut client = peer.client();
            let (mut watch, mut server) = peer.open(&client, workspace.clone()).await;
            let records = (0..21)
                .map(|id| raw_task(&id.to_string(), &workspace, None))
                .collect::<Vec<_>>();
            server
                .batch(frame(
                    "multipart",
                    1,
                    0,
                    false,
                    true,
                    records[..20].to_vec(),
                    vec![],
                ))
                .await;
            let read = next_read(&mut watch).await;
            assert!(
                client
                    .finish_project_task_watch_read(&watch, read)
                    .unwrap()
                    .is_none()
            );
            assert_eq!(watch.committed_cursor(), None);
            server
                .batch(frame(
                    "multipart",
                    1,
                    1,
                    true,
                    true,
                    records[20..].to_vec(),
                    vec![],
                ))
                .await;
            let ready = publication(&mut client, &mut watch).await;
            assert_eq!(ready.snapshot().unwrap().tasks.len(), 21);
            assert_eq!(
                ready.snapshot().unwrap().tasks["20"].decrypted()["title"],
                "Synthetic task 20"
            );
            assert!(watch.connection() == TaskSyncConnection::Reconnecting);
            watch.commit(ready.receipt().unwrap()).unwrap();
            assert_eq!(watch.committed_cursor(), Some("epoch:1"));
            server.no_task_writes().await;
            server
                .batch(frame(
                    "delta",
                    2,
                    0,
                    true,
                    false,
                    vec![raw_task("21", &workspace, None)],
                    vec!["0".into()],
                ))
                .await;
            let ready = publication(&mut client, &mut watch).await;
            assert!(!ready.snapshot().unwrap().tasks.contains_key("0"));
            assert!(ready.snapshot().unwrap().tasks.contains_key("21"));
            assert_eq!(ready.snapshot().unwrap().tasks.len(), 21);
            watch.commit(ready.receipt().unwrap()).unwrap();
            watch.sync.reconnecting();
            server
                .batch(frame("empty-readiness", 2, 0, true, false, vec![], vec![]))
                .await;
            let ready = publication(&mut client, &mut watch).await;
            assert_eq!(ready.snapshot().unwrap().tasks.len(), 21);
            let stale = TaskSyncCommit {
                batch_id: "delta".into(),
                cursor: "epoch:2".into(),
            };
            assert!(matches!(watch.commit(&stale), Err(Error::Conflict)));
            assert!(watch.connection() == TaskSyncConnection::Reconnecting);
            watch.commit(ready.receipt().unwrap()).unwrap();
            assert!(watch.connection() == TaskSyncConnection::Connected);
            server.no_task_writes().await;
        }
    })
    .await;
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn reconnect_subscribes_only_durable_cursor_and_discards_queued_uncommitted_snapshot() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let (mut watch, mut server) = peer.open(&client, TaskSyncWorkspace::Personal).await;
        seed(&mut client, &mut watch, &mut server).await;
        server
            .batch(frame(
                "uncommitted",
                2,
                0,
                true,
                true,
                vec![raw_task("uncommitted", watch.scope().workspace(), None)],
                vec![],
            ))
            .await;
        let uncommitted = publication(&mut client, &mut watch).await;
        assert_eq!(watch.committed_cursor(), Some("epoch:1"));
        watch.suspend();
        assert!(!watch.lifetime.is_cancelled());
        drop(server);
        assert!(uncommitted.snapshot().is_err());
        let mut server = peer.reconnect(&client, &mut watch, "epoch:1").await;
        server
            .batch(frame("ready-reconnect", 1, 0, true, false, vec![], vec![]))
            .await;
        let ready = publication(&mut client, &mut watch).await;
        assert!(ready.snapshot().unwrap().tasks.contains_key("original"));
        assert!(!ready.snapshot().unwrap().tasks.contains_key("uncommitted"));
        watch.commit(ready.receipt().unwrap()).unwrap();
        server
            .batch(frame(
                "committed-next",
                3,
                0,
                true,
                true,
                vec![raw_task("next", watch.scope().workspace(), None)],
                vec![],
            ))
            .await;
        let ready = publication(&mut client, &mut watch).await;
        watch.commit(ready.receipt().unwrap()).unwrap();
        watch.suspend();
        assert!(!watch.lifetime.is_cancelled());
        drop(server);
        let mut server = peer.reconnect(&client, &mut watch, "epoch:3").await;
        server
            .batch(frame("ready-final", 3, 0, true, false, vec![], vec![]))
            .await;
        let ready = publication(&mut client, &mut watch).await;
        assert!(ready.snapshot().unwrap().tasks.contains_key("next"));
        watch.commit(ready.receipt().unwrap()).unwrap();
        server.no_task_writes().await;
    })
    .await;
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn source_revoke_and_force_logout_interrupt_full_publication_queue_without_cursor_advance() {
    bounded(async {
        for force_logout in [false, true] {
            let peer = Peer::new().await;
            let mut client = peer.client();
            let (mut watch, mut server) = peer.open(&client, TaskSyncWorkspace::Personal).await;
            seed(&mut client, &mut watch, &mut server).await;
            server
                .batch(frame(
                    "slow-publication",
                    2,
                    0,
                    true,
                    true,
                    vec![raw_task("queued", watch.scope().workspace(), None)],
                    vec![],
                ))
                .await;
            let ready = publication(&mut client, &mut watch).await;
            let (sender, mut receiver) = mpsc::channel(1);
            assert!(sender.try_send(ready).is_ok()); // consumer deliberately idle
            if force_logout {
                server.send("force_logout", json!({})).await;
            } else {
                server
                    .send(
                        "project_task_sync_error",
                        json!({"project_id":PROJECT,"code":"access_revoked"}),
                    )
                    .await;
            }
            let read = next_read(&mut watch).await;
            let result = client.finish_project_task_watch_read(&watch, read);
            assert!(
                matches!(result, Err(Error::Expired)) && force_logout
                    || matches!(result, Err(Error::Forbidden)) && !force_logout
            );
            let queued = receiver.recv().await.unwrap();
            assert!(queued.snapshot().is_err());
            if force_logout {
                assert!(client.session().is_none());
            } else {
                assert!(client.session().is_some());
                assert!(watch.connection() == TaskSyncConnection::Revoked);
                assert!(watch.owner_authority_valid());
                assert_eq!(watch.committed_cursor(), None);
                assert!(watch.sync.snapshot().tasks.is_empty());
            }
            server.no_task_writes().await;
        }
    })
    .await;
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn bounded_pending_data_and_publication_deadline_discard_without_new_resume_cursor() {
    bounded(async {
        for another_batch in [true, false] {
            let peer = Peer::new().await;
            let mut client = peer.client();
            let (mut watch, mut server) = peer.open(&client, TaskSyncWorkspace::Personal).await;
            seed(&mut client, &mut watch, &mut server).await;
            server
                .batch(frame(
                    "staged",
                    2,
                    0,
                    true,
                    true,
                    vec![raw_task("pending", watch.scope().workspace(), None)],
                    vec![],
                ))
                .await;
            let ready = publication(&mut client, &mut watch).await;
            if another_batch {
                server
                    .batch(frame("would-overflow", 3, 0, true, true, vec![], vec![]))
                    .await;
                let read = next_read(&mut watch).await;
                assert!(matches!(
                    client.finish_project_task_watch_read(&watch, read),
                    Err(Error::Conflict)
                ));
            } else {
                // Explicit monotonic seam, no five-second real sleep.
                watch.pending_at = Some(Instant::now() - PUBLICATION_DEADLINE);
                assert!(matches!(
                    watch
                        .poll(&CancellationToken::new(), current_seconds())
                        .await,
                    Err(Error::Offline)
                ));
            }
            assert!(ready.snapshot().is_err());
            assert_eq!(watch.committed_cursor(), Some("epoch:1"));
            assert!(watch.sync.snapshot().tasks.contains_key("original"));
            assert!(watch.connection() == TaskSyncConnection::Reconnecting);
        }
    })
    .await;
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn foreign_project_owner_team_tamper_or_expired_wrapper_never_publishes() {
    bounded(async {
        for case in 0..5 {
            let peer = Peer::new().await;
            let mut client = peer.client();
            let workspace = if case == 2 {
                TaskSyncWorkspace::Team(TEAM.into())
            } else {
                TaskSyncWorkspace::Personal
            };
            let (mut watch, mut server) = peer.open(&client, workspace.clone()).await;
            seed(&mut client, &mut watch, &mut server).await;
            let mut task = raw_task("denied", &workspace, None);
            let mut payload = frame("denied", 2, 0, true, true, vec![], vec![]);
            match case {
                0 => payload["project_id"] = json!("foreign-project"),
                1 => task["hashed_user_id"] = json!(hash("foreign-owner")),
                2 => task["hashed_team_id"] = json!(hash("foreign-team")),
                3 => task["encrypted_title"] = json!("tampered"),
                _ => task["key_wrappers"][0]["expires_at"] = json!(current_seconds()),
            }
            payload["tasks"] = json!([task]);
            server.batch(payload).await;
            let read = next_read(&mut watch).await;
            assert!(client.finish_project_task_watch_read(&watch, read).is_err());
            assert_eq!(watch.committed_cursor(), Some("epoch:1"));
            assert!(watch.sync.snapshot().tasks.contains_key("original"));
            assert!(!watch.sync.snapshot().tasks.contains_key("denied"));
            assert!(watch.connection() == TaskSyncConnection::Reconnecting);
        }
    })
    .await;
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn wrapper_ttl_is_carried_into_publication_and_commit_deadline() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let (mut watch, mut server) = peer.open(&client, TaskSyncWorkspace::Personal).await;
        seed(&mut client, &mut watch, &mut server).await;
        let expiry = current_seconds() + 60;
        server
            .batch(frame(
                "ttl",
                2,
                0,
                true,
                true,
                vec![raw_task("expires", watch.scope().workspace(), Some(expiry))],
                vec![],
            ))
            .await;
        let ready = publication(&mut client, &mut watch).await;
        assert_eq!(ready.expires_at, Some(expiry * 1000));
        assert_eq!(watch.pending_expiry, Some(expiry * 1000));
        let receipt = ready.receipt().unwrap().clone();
        // Wall-clock boundary seam, distinct from the five-second monotonic cap.
        watch.pending_expiry = Some(now_ms() - 1);
        assert!(matches!(watch.commit(&receipt), Err(Error::Conflict)));
        assert!(ready.snapshot().is_err());
        assert_eq!(watch.committed_cursor(), Some("epoch:1"));
    })
    .await;
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn two_idle_watch_reads_do_not_hold_shared_client_lane_or_block_ordinary_operation() {
    bounded(async {
        let peer = Peer::new().await;
        let client = Arc::new(Mutex::new(peer.client()));
        let first_workspace = TaskSyncWorkspace::Personal;
        let second_workspace = TaskSyncWorkspace::Team(TEAM.into());
        let first_start = {
            let guard = client.lock().await;
            peer.prepare(&guard, first_workspace.clone(), CancellationToken::new())
        };
        let second_start = {
            let guard = client.lock().await;
            peer.prepare(&guard, second_workspace.clone(), CancellationToken::new())
        };
        let (one, _server_one) = peer.connect(first_start, &first_workspace).await;
        let (two, _server_two) = peer.connect(second_start, &second_workspace).await;
        let (one_started, one_ready) = oneshot::channel();
        let (two_started, two_ready) = oneshot::channel();
        let one = tokio::spawn(async move {
            let mut watch = one;
            let _ = one_started.send(());
            let read = watch
                .poll(&CancellationToken::new(), current_seconds())
                .await;
            (watch, read)
        });
        let two = tokio::spawn(async move {
            let mut watch = two;
            let _ = two_started.send(());
            let read = watch
                .poll(&CancellationToken::new(), current_seconds())
                .await;
            (watch, read)
        });
        one_ready.await.unwrap();
        two_ready.await.unwrap();
        // The reads each remain idle for250ms. An ordinary Client operation
        // must acquire the same lane and finish before either timeout expires.
        tokio::time::timeout(Duration::from_millis(100), async {
            let mut guard = client.lock().await;
            guard.set_interactive(true);
            assert!(guard.credential_snapshot().is_some());
        })
        .await
        .expect("idle watches must not occupy Client lane");
        let (_, first) = one.await.unwrap();
        let (_, second) = two.await.unwrap();
        assert!(matches!(first, Ok(ProjectTaskWatchPoll::Idle)));
        assert!(matches!(second, Ok(ProjectTaskWatchPoll::Idle)));
    })
    .await;
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn cancel_during_handshake_or_pending_publication_leaves_caller_and_other_watch_owned() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let parent = CancellationToken::new();
        let binding = client
            .bind_project_task_source(
                TaskSyncWorkspace::Personal,
                PROJECT,
                SOURCE,
                zeroize::Zeroizing::new(PROJECT_KEY),
            )
            .unwrap();
        let sync = binding.new_sync(None, current_seconds()).unwrap();
        let start = client
            .prepare_project_task_watch(binding, sync, parent.child_token())
            .unwrap();
        let connecting = tokio::spawn(start.connect());
        // Accept TCP only; deliberately withhold the WebSocket upgrade.
        let (_held_tcp, _) = peer.listener.accept().await.unwrap();
        parent.cancel();
        assert!(matches!(connecting.await.unwrap(), Err(Error::Cancelled)));
        let caller = CancellationToken::new();
        let own = caller.child_token();
        let start = peer.prepare(&client, TaskSyncWorkspace::Personal, own.clone());
        let (mut watch, mut server) = peer.connect(start, &TaskSyncWorkspace::Personal).await;
        seed(&mut client, &mut watch, &mut server).await;
        server
            .batch(frame(
                "pending-cancel",
                2,
                0,
                true,
                true,
                vec![raw_task("cancelled", watch.scope().workspace(), None)],
                vec![],
            ))
            .await;
        let ready = publication(&mut client, &mut watch).await;
        let (other, _other_server) = peer.open(&client, TaskSyncWorkspace::Personal).await;
        own.cancel();
        assert!(ready.snapshot().is_err());
        assert!(!caller.is_cancelled());
        assert!(other.check().is_ok());
        assert!(matches!(
            watch
                .poll(&CancellationToken::new(), current_seconds())
                .await,
            Err(Error::Cancelled)
        ));
    })
    .await;
}

async fn http_request(peer: &Peer, method: &str, path: &str) -> (TcpStream, Value) {
    use tokio::io::AsyncReadExt;
    let (mut stream, address) = peer.listener.accept().await.unwrap();
    assert!(address.ip().is_loopback());
    let mut headers = Vec::new();
    while !headers.ends_with(b"\r\n\r\n") {
        assert!(headers.len() < 16384, "bounded synthetic HTTP header");
        headers.push(stream.read_u8().await.unwrap());
    }
    let headers = String::from_utf8(headers).unwrap();
    assert_eq!(
        headers.lines().next(),
        Some(format!("{method} {path} HTTP/1.1").as_str())
    );
    let size = headers
        .lines()
        .filter_map(|line| line.split_once(':'))
        .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
        .map(|(_, value)| value.trim().parse::<usize>().unwrap())
        .unwrap_or(0);
    assert!(size <= 4096, "bounded synthetic HTTP request");
    let mut body = vec![0; size];
    stream.read_exact(&mut body).await.unwrap();
    let body = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(&body).unwrap()
    };
    (stream, body)
}
async fn http_response(stream: TcpStream, body: Value) {
    http_response_status(stream, 200, body).await;
}
async fn http_response_status(mut stream: TcpStream, status: u16, body: Value) {
    use tokio::io::AsyncWriteExt;
    let bytes = serde_json::to_vec(&body).unwrap();
    let header = format!(
        "HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        bytes.len()
    );
    stream.write_all(header.as_bytes()).await.unwrap();
    stream.write_all(&bytes).await.unwrap();
    stream.shutdown().await.unwrap();
}
async fn reconnect_authorization_peer(peer: &Peer, revoked: bool, changed_key: bool) {
    reconnect_authorization_peer_gated(peer, revoked, changed_key, None).await;
}
async fn reconnect_authorization_peer_gated(
    peer: &Peer,
    revoked: bool,
    changed_key: bool,
    gate: Option<(oneshot::Sender<()>, oneshot::Receiver<()>)>,
) {
    let (stream, body) = http_request(peer, "POST", "/v1/auth/session").await;
    assert_eq!(body, json!({"session_id":"synthetic-session"}));
    if let Some((entered, release)) = gate {
        entered.send(()).unwrap();
        release.await.unwrap();
    }
    http_response(
        stream,
        json!({"success":true,"ws_token":"synthetic-ws","user":{"id":OWNER}}),
    )
    .await;
    let (stream, _) = http_request(peer, "GET", &format!("/v1/projects/{PROJECT}")).await;
    let current_project_key = if changed_key { [4; 32] } else { PROJECT_KEY };
    let mut project = json!({"project_id":PROJECT,"version":1,"key_wrappers":[],
        "encrypted_project_key":crypto::encrypt_bytes(&current_project_key,&PROJECT_KEY).unwrap()});
    for (field, text) in [
        ("name", "Synthetic Project"),
        ("description", ""),
        ("icon", "folder"),
        ("color", "default"),
        ("slug", "synthetic-project"),
    ] {
        project[format!("encrypted_{field}")] =
            json!(crypto::encrypt_combined(text, &current_project_key).unwrap());
    }
    http_response(stream, json!({"project":project})).await;
    let (stream, _) = http_request(peer, "GET", &format!("/v1/projects/{PROJECT}/sources")).await;
    http_response(
        stream,
        json!({"sources":[{"source_id":SOURCE,"status":if revoked {"revoked"}else{"offline"}}]}),
    )
    .await;
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn busy_client_incoming_candidate_suspends_then_reauthorizes_without_losing_durable_cursor_or_revoke()
 {
    bounded(async {
        for queued_revoke in [false, true] {
            let peer = Peer::new().await;
            let mut initial = peer.client();
            let (mut watch, mut server) = peer.open(&initial, TaskSyncWorkspace::Personal).await;
            seed(&mut initial, &mut watch, &mut server).await;
            let client = Arc::new(Mutex::new(initial));
            let ordinary = client.clone();
            let ordinary = tokio::spawn(async move {
                let mut guard = ordinary.lock().await;
                guard
                    .projects()
                    .with_filters(crate::work::ProjectFilters {
                        personal: true,
                        ..Default::default()
                    })
                    .list()
                    .await
            });
            // A real typed Client request now holds the serialized lane while
            // its synthetic HTTP response is deliberately withheld.
            let (ordinary_response, _) = http_request(&peer, "GET", "/v1/projects").await;
            server
                .batch(frame(
                    "awaiting-finish",
                    2,
                    0,
                    true,
                    true,
                    vec![raw_task("not-durable", watch.scope().workspace(), None)],
                    vec![],
                ))
                .await;
            let read = next_read(&mut watch).await;
            let staged = read.result.as_ref().unwrap().as_ref().unwrap().clone();
            if queued_revoke {
                server
                    .send(
                        "project_task_sync_error",
                        json!({"project_id":PROJECT,"code":"access_revoked"}),
                    )
                    .await;
            }
            assert!(
                tokio::time::timeout(Duration::from_millis(10), client.lock())
                    .await
                    .is_err()
            );
            // Native actor must fence its cache/gate first. Suspend is local,
            // bounded and recoverable, unlike close; the unread control is not
            // interpreted as success, and fresh source auth is mandatory.
            watch.suspend();
            assert!(!watch.lifetime.is_cancelled());
            assert!(watch.connection() == TaskSyncConnection::Reconnecting);
            assert_eq!(watch.committed_cursor(), Some("epoch:1"));
            assert!(staged.snapshot().is_err());
            let receipt = TaskSyncCommit {
                batch_id: "awaiting-finish".into(),
                cursor: "epoch:2".into(),
            };
            assert!(watch.commit(&receipt).is_err());
            http_response(ordinary_response, json!({"projects":[]})).await;
            assert!(ordinary.await.unwrap().is_ok());
            {
                let mut guard = client.lock().await;
                assert!(matches!(
                    guard.finish_project_task_watch_read(&watch, read),
                    Err(Error::Cancelled)
                ));
            }
            drop(server);
            let preparation = async {
                let mut guard = client.lock().await;
                guard.prepare_project_task_watch_reconnect(&mut watch).await
            };
            let (prepared, ()) = tokio::join!(
                preparation,
                reconnect_authorization_peer(&peer, queued_revoke, false)
            );
            if queued_revoke {
                assert!(matches!(prepared, Err(Error::Forbidden)));
                // No empty readiness/candidate/commit follows denied source
                // auth. Native owner applies its durable revocation policy.
                assert!(watch.connection() == TaskSyncConnection::Reconnecting);
                assert_eq!(watch.committed_cursor(), Some("epoch:1"));
                assert!(staged.snapshot().is_err());
                continue;
            }
            let cancel = CancellationToken::new();
            let (result, mut server) = tokio::join!(
                watch.reconnect(prepared.unwrap(), &cancel),
                peer.accept(&TaskSyncWorkspace::Personal, Some("epoch:1"))
            );
            result.unwrap();
            server
                .batch(frame(
                    "ready-after-contention",
                    1,
                    0,
                    true,
                    false,
                    vec![],
                    vec![],
                ))
                .await;
            let read = next_read(&mut watch).await;
            let ready = {
                let mut guard = client.lock().await;
                guard
                    .finish_project_task_watch_read(&watch, read)
                    .unwrap()
                    .unwrap()
            };
            assert!(ready.snapshot().unwrap().tasks.contains_key("original"));
            assert!(!ready.snapshot().unwrap().tasks.contains_key("not-durable"));
            watch.commit(ready.receipt().unwrap()).unwrap();
            assert!(watch.connection() == TaskSyncConnection::Connected);
            server.no_task_writes().await;
        }
    })
    .await;
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn proactive_reauthorization_discards_live_read_or_seal_before_source_denial_or_key_change() {
    bounded(async {
        const OTHER_PROJECT: &str = "33333333-3333-4333-8333-333333333333";
        for changed_key in [false, true] {
            for hold_opaque_read in [false, true] {
                let peer = Peer::new().await;
                let mut client = peer.client();
                let (mut watch, mut server) = peer.open(&client, TaskSyncWorkspace::Personal).await;
                seed(&mut client, &mut watch, &mut server).await;
                server
                    .batch(frame(
                        "proactive-pending",
                        2,
                        0,
                        true,
                        true,
                        vec![raw_task(
                            "must-not-publish",
                            watch.scope().workspace(),
                            None,
                        )],
                        vec![],
                    ))
                    .await;
                let read = next_read(&mut watch).await;
                let candidate = read.result.as_ref().unwrap().as_ref().unwrap().clone();
                let receipt = candidate.receipt().clone();
                let (old_read, old_seal) = if hold_opaque_read {
                    (Some(read), None)
                } else {
                    (
                        None,
                        client.finish_project_task_watch_read(&watch, read).unwrap(),
                    )
                };
                assert!(candidate.snapshot().is_ok());
                if let Some(seal) = &old_seal {
                    assert!(seal.snapshot().is_ok());
                }
                assert!(watch.socket.is_some()); // no pre-suspend masks this case
                let other_binding = client
                    .bind_project_task_source(
                        TaskSyncWorkspace::Personal,
                        OTHER_PROJECT,
                        SOURCE,
                        zeroize::Zeroizing::new(PROJECT_KEY),
                    )
                    .unwrap();
                let other_sync = other_binding.new_sync(None, current_seconds()).unwrap();
                let other_start = client
                    .prepare_project_task_watch(other_binding, other_sync, CancellationToken::new())
                    .unwrap();
                let (other, mut other_server) = tokio::join!(
                    other_start.connect(),
                    peer.accept_project(&TaskSyncWorkspace::Personal, None, OTHER_PROJECT)
                );
                let mut other = other.unwrap();
                let mut other_task =
                    raw_task("other-project-task", &TaskSyncWorkspace::Personal, None);
                other_task["key_wrappers"][0]["hashed_project_id"] = json!(hash(OTHER_PROJECT));
                let mut initial = frame(
                    "other-seed",
                    1,
                    0,
                    true,
                    true,
                    vec![other_task.clone()],
                    vec![],
                );
                initial["project_id"] = json!(OTHER_PROJECT);
                other_server.batch(initial).await;
                let ready = publication(&mut client, &mut other).await;
                other.commit(ready.receipt().unwrap()).unwrap();
                let mut pending =
                    frame("other-current", 2, 0, true, true, vec![other_task], vec![]);
                pending["project_id"] = json!(OTHER_PROJECT);
                other_server.batch(pending).await;
                let other_ready = publication(&mut client, &mut other).await;
                assert!(other_ready.snapshot().is_ok());
                // Reauthorize directly with a live pending candidate: do not
                // manually suspend first or mask the reviewed failure path.
                let (entered_tx, entered_rx) = oneshot::channel();
                let (release_tx, release_rx) = oneshot::channel();
                let (prepared, (), ()) = tokio::join!(
                    client.prepare_project_task_watch_reconnect(&mut watch),
                    reconnect_authorization_peer_gated(
                        &peer,
                        !changed_key,
                        changed_key,
                        Some((entered_tx, release_rx)),
                    ),
                    async {
                        entered_rx.await.unwrap();
                        // The first canonical HTTP request is now awaiting its
                        // withheld response. Suspension must already fence the
                        // old candidate, before denial/key change can return.
                        assert!(candidate.snapshot().is_err());
                        if let Some(seal) = &old_seal {
                            assert!(seal.snapshot().is_err());
                            assert!(seal.receipt().is_err());
                            assert!(seal.checkpoint().is_err());
                        }
                        assert!(other_ready.snapshot().is_ok());
                        release_tx.send(()).unwrap();
                    }
                );
                assert!(matches!(prepared, Err(Error::Forbidden)));
                assert!(watch.socket.is_none());
                assert!(!watch.lifetime.is_cancelled());
                assert!(watch.connection() == TaskSyncConnection::Reconnecting);
                assert_eq!(watch.committed_cursor(), Some("epoch:1"));
                assert!(candidate.snapshot().is_err());
                if let Some(read) = old_read {
                    assert!(matches!(
                        client.finish_project_task_watch_read(&watch, read),
                        Err(Error::Cancelled)
                    ));
                }
                if let Some(seal) = old_seal {
                    assert!(seal.snapshot().is_err());
                    assert!(seal.receipt().is_err());
                    assert!(seal.checkpoint().is_err());
                }
                assert!(watch.commit(&receipt).is_err());
                assert_eq!(watch.committed_cursor(), Some("epoch:1"));
                assert!(watch.owner_authority_valid());
                assert!(other.owner_authority_valid());
                assert!(other.check().is_ok());
                assert_eq!(other.committed_cursor(), Some("epoch:1"));
                assert!(
                    other_ready
                        .snapshot()
                        .unwrap()
                        .tasks
                        .contains_key("other-project-task")
                );
                other.commit(other_ready.receipt().unwrap()).unwrap();
                assert_eq!(other.committed_cursor(), Some("epoch:2"));
                other_server.no_task_writes().await;
            }
        }
    })
    .await;
}

// contract-test: supporting surface=cli assertions=projects.remote-access.task-sync
#[tokio::test]
async fn task_mutation_forbidden_retains_owner_authority_but_actual_logout_invalidates_it() {
    bounded(async {
        let peer = Peer::new().await;
        let mut client = peer.client();
        let (mut watch, mut server) = peer.open(&client, TaskSyncWorkspace::Personal).await;
        seed(&mut client, &mut watch, &mut server).await;
        let observer = watch.binding.owner_authority();
        let mutation = async {
            client
                .tasks()
                .with_filters(crate::work::TaskFilters {
                    personal: true,
                    ..Default::default()
                })
                .create(crate::work::TaskCreate {
                    title: "Task create must not revoke".into(),
                    task_id: Some("44444444-4444-4444-8444-444444444444".into()),
                    ..Default::default()
                })
                .await
        };
        let response = async {
            let (stream, body) = http_request(&peer, "POST", "/v1/user-tasks").await;
            assert!(
                !serde_json::to_string(&body)
                    .unwrap()
                    .contains("Task create must not revoke")
            );
            http_response_status(stream, 403, json!({"detail":"Forbidden"})).await;
        };
        let (result, ()) = tokio::join!(mutation, response);
        assert!(matches!(result, Err(Error::Forbidden)));
        assert!(observer.is_valid());
        assert!(watch.owner_authority_valid());
        assert_eq!(watch.committed_cursor(), Some("epoch:1"));
        assert!(watch.sync.snapshot().tasks.contains_key("original"));
        let response = async {
            let (stream, body) = http_request(&peer, "POST", "/v1/auth/logout").await;
            assert_eq!(body, json!({}));
            // Logout invalidates locally before waiting for remote success.
            assert!(!observer.is_valid());
            http_response(stream, json!({"success":true})).await;
        };
        let (result, ()) = tokio::join!(client.logout(), response);
        result.unwrap();
        assert!(!watch.owner_authority_valid());
        assert!(!observer.is_valid());
        assert!(client.session().is_none());
    })
    .await;
}
