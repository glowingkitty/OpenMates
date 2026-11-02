//! PRIVATE DRAFT supporting primitive/race tests, not actual three-SDK proof.
use super::*;
use std::sync::atomic::{AtomicBool, AtomicU64};

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completed_worker_is_fenced_again_after_paused_caller_resumes() {
    // Deterministically pause AFTER the worker has completed its own checks but
    // BEFORE the consumer's foreign-return continuation. Exercise all controls.
    for change in ["source-revoke", "session-reset", "cancel"] {
        let valid = Arc::new(AtomicBool::new(true));
        let epoch = Arc::new(AtomicU64::new(1));
        let cancel = CancellationToken::new();
        let resume = Arc::new(Notify::new());
        let (completed, observed) = oneshot::channel();
        let (v, e, c, r) = (valid.clone(), epoch.clone(), cancel.clone(), resume.clone());
        let consumer = tokio::spawn(async move {
            let mut encoded = tokio::task::spawn_blocking(|| {
                Zeroizing::new("synthetic-private-output".to_owned())
            })
            .await
            .unwrap();
            let _ = completed.send(());
            r.notified().await;
            let result = release_encoded(&mut encoded, || {
                if !v.load(Ordering::Acquire) || e.load(Ordering::Acquire) != 1 || c.is_cancelled()
                {
                    Err(Error::Cancelled.into())
                } else {
                    Ok(())
                }
            });
            (result, encoded.is_empty())
        });
        observed.await.unwrap();
        match change {
            "source-revoke" => valid.store(false, Ordering::Release),
            "session-reset" => {
                epoch.fetch_add(1, Ordering::AcqRel);
            }
            _ => cancel.cancel(),
        }
        resume.notify_one();
        let (result, wiped) = consumer.await.unwrap();
        assert_eq!(result.unwrap_err().code, "cancelled");
        assert!(
            wiped,
            "rejected serialized output must be wiped before return"
        );
    }
}

fn queued_commit() -> (mpsc::Sender<Commit>, mpsc::Receiver<Commit>) {
    let (tx, rx) = mpsc::channel(4);
    let (ack, _wait) = oneshot::channel();
    tx.try_send(Commit {
        receipt: TaskSyncCommit {
            batch_id: "synthetic".into(),
            cursor: "durable".into(),
        },
        ack,
    })
    .unwrap_or_else(|_| panic!("queue"));
    (tx, rx)
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test]
async fn continuously_ready_idle_frames_cannot_starve_exact_commit() {
    let (_tx, mut commits) = queued_commit();
    let cancel = CancellationToken::new();
    let suspend = Notify::new();
    let mut polls = 0;
    for _ in 0..=SOCKET_BURST {
        let step = select_step(
            polls >= SOCKET_BURST,
            &cancel,
            &suspend,
            &mut commits,
            std::future::ready(Ok(ProjectTaskWatchPoll::Idle)),
        )
        .await;
        match step {
            ActorStep::Poll(Ok(ProjectTaskWatchPoll::Idle)) => polls += 1,
            ActorStep::Commit(Some(commit)) => {
                assert_eq!(polls, SOCKET_BURST);
                assert_eq!(commit.receipt.cursor, "durable");
                return;
            }
            _ => panic!("unexpected scheduler state"),
        }
    }
    panic!("commit starved behind continuously ready unrelated frames");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test]
async fn priority_cancel_suspend_and_observed_terminal_read_win() {
    for prefer_commit in [false, true] {
        let (_tx, mut commits) = queued_commit();
        let cancel = CancellationToken::new();
        let suspend = Notify::new();
        cancel.cancel();
        assert!(matches!(
            select_step(
                prefer_commit,
                &cancel,
                &suspend,
                &mut commits,
                std::future::ready(Ok(ProjectTaskWatchPoll::Idle))
            )
            .await,
            ActorStep::Cancel
        ));
        let cancel = CancellationToken::new();
        suspend.notify_one();
        assert!(matches!(
            select_step(
                prefer_commit,
                &cancel,
                &suspend,
                &mut commits,
                std::future::ready(Ok(ProjectTaskWatchPoll::Idle))
            )
            .await,
            ActorStep::Suspend
        ));
    }
    let (_tx, mut commits) = queued_commit();
    let cancel = CancellationToken::new();
    let suspend = Notify::new();
    assert!(matches!(
        select_step(
            false,
            &cancel,
            &suspend,
            &mut commits,
            std::future::ready(Err(Error::Expired))
        )
        .await,
        ActorStep::Poll(Err(Error::Expired))
    ));
}

// Real sealed actor regressions below consume the shared independent peer. They
// are drafted only: no generic helper/static receipt substitutes for execution.
struct Peer {
    child: std::process::Child,
    endpoint: String,
    suite: Value,
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
impl Peer {
    fn start() -> Self {
        use std::io::BufRead;
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        let fixture = root.join("tests/sdk-conformance/fixtures/session-project-task-watch.json");
        let data: Value = serde_json::from_slice(&std::fs::read(&fixture).unwrap()).unwrap();
        let python =
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into());
        let stderr_directory = std::env::var_os("OPENMATES_SDK_WATCH_TEST_LOG_DIR")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(std::env::temp_dir);
        let stderr_path =
            stderr_directory.join(format!("watch-peer-{}.stderr.log", uuid::Uuid::new_v4()));
        let mut stderr_options = std::fs::OpenOptions::new();
        stderr_options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            stderr_options.mode(0o600);
        }
        let stderr = stderr_options
            .open(&stderr_path)
            .expect("private peer stderr");
        let mut child = std::process::Command::new(python)
            .arg(root.join("tests/sdk-conformance/session_project_task_watch_server.py"))
            .arg("--fixture")
            .arg(&fixture)
            .args(["--vector", "personal-21-final", "--identity", "rust"])
            .current_dir(root)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::from(stderr))
            .spawn()
            .expect("launch private shared peer");
        let stdout = child.stdout.take().unwrap();
        let (tx, rx) = std::sync::mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut ready = String::new();
            let result = std::io::BufReader::new(stdout)
                .read_line(&mut ready)
                .map(|_| ready);
            let _ = tx.send(result);
        });
        let ready = match rx.recv_timeout(Duration::from_secs(2)) {
            Ok(Ok(value)) => value,
            _ => {
                let _ = child.kill();
                let exit = child.wait();
                panic!(
                    "bounded peer startup; exit={exit:?}; stderr={}",
                    stderr_path.display()
                );
            }
        };
        let ready: Value = serde_json::from_str(&ready).unwrap();
        let endpoint = ready["endpoint"].as_str().unwrap().to_owned();
        assert!(
            endpoint
                .strip_prefix("http://127.0.0.1:")
                .and_then(|p| p.parse::<u16>().ok())
                .is_some_and(|p| p > 0)
        );
        Self {
            child,
            endpoint,
            suite: data["capabilities"]["session.project-task-watch.v1"].clone(),
        }
    }
    async fn control(&self, value: Value) {
        self.control_report(value).await;
    }
    async fn control_report(&self, value: Value) -> Value {
        use std::io::{Read, Write};
        let endpoint = self.endpoint.clone();
        tokio::task::spawn_blocking(move||{
            let port=endpoint.strip_prefix("http://127.0.0.1:").unwrap().parse::<u16>().unwrap();
            let mut socket=std::net::TcpStream::connect_timeout(&std::net::SocketAddr::from(([127,0,0,1],port)),Duration::from_secs(2)).unwrap();
            socket.set_read_timeout(Some(Duration::from_secs(2))).unwrap();socket.set_write_timeout(Some(Duration::from_secs(2))).unwrap();
            let bytes=serde_json::to_vec(&value).unwrap();
            write!(socket,"POST /__test/control HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",bytes.len()).unwrap();socket.write_all(&bytes).unwrap();
            let mut response=Vec::new();socket.take(1024*1024).read_to_end(&mut response).unwrap();
            assert!(response.starts_with(b"HTTP/1.0 200")||response.starts_with(b"HTTP/1.1 200"),"fixture control refused");
            let body=response.windows(4).position(|window|window==b"\r\n\r\n").unwrap()+4;
            let report:Value=serde_json::from_slice(&response[body..]).unwrap();
            assert!(report["failure"].is_null(),"fixture peer failed");
            report
        }).await.unwrap()
    }
    fn session(&self) -> String {
        let account = &self.suite["account"];
        json!({"api_url":self.endpoint,"session_id":account["session_id"],"cookies":{"auth_refresh_token":account["cookie"]},"ws_token":"synthetic-watch-ws","master_key":account["master_key"],"hashed_email":"synthetic-watch-email","user_email_salt":"synthetic-watch-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()
    }
    async fn bridge_watch(&self) -> (SessionBridge, String, Arc<Handle>) {
        let bridge=SessionBridge::new(&json!({"api_url":self.endpoint,"app_url":"https://app.example.invalid","enhanced_privacy":false,"allow_private_operations":false}).to_string()).unwrap_or_else(|_|panic!("bridge"));
        bridge
            .import_session(self.session())
            .await
            .unwrap_or_else(|_| panic!("session import"));
        let opened = bridge
            .project_task_watch_open(
                self.suite["project_id"].as_str().unwrap().into(),
                json!({"source_id":self.suite["source_id"],"checkpoint":null}).to_string(),
                json!({"personal":true}).to_string(),
            )
            .await
            .unwrap_or_else(|_| panic!("watch admission"));
        let id: Value = serde_json::from_str(&opened).unwrap();
        let id = id["id"].as_str().unwrap().to_owned();
        let handle = bridge
            .state
            .project_task_watches
            .get(&id)
            .unwrap_or_else(|_| panic!("owned handle"));
        tokio::select! {
            _ = self.control(json!({"op":"beacon","key":"subscriptions","minimum":1})) => {},
            _ = observed_terminal(&handle) => {
                let error=*handle.last_error.lock().unwrap();
                panic!("watch setup terminated before subscription: {error:?}");
            }
        }
        (bridge, id, handle)
    }
}
async fn observed_terminal(handle: &Handle) {
    // next() owns its consumer receiver while awaiting the serializer. Subscribe
    // independently so observation never waits on that receiver's mutex.
    let mut status = { handle.control.lock().unwrap().tx.subscribe() };
    while !status.borrow().terminal() {
        status.changed().await.expect("sticky terminal observation");
    }
}
async fn after_worker_case(reset: bool) {
    timeout(Duration::from_secs(5), async move {
        let peer = tokio::task::spawn_blocking(Peer::start).await.unwrap();
        let (bridge, id, handle) = peer.bridge_watch().await;
        let barrier = Arc::new(ReturnBarrier::default());
        *handle.return_barrier.lock().unwrap() = Some(barrier.clone());
        let caller = bridge.clone();
        let next = tokio::spawn(async move { caller.project_task_watch_next(id).await });
        peer.control(json!({"op":"send","watch":"a","kind":"baseline"}))
            .await;
        barrier.completed.notified().await;
        if reset {
            bridge
                .import_session(peer.session())
                .await
                .unwrap_or_else(|_| panic!("reset"));
        } else {
            peer.control(json!({"op":"revoke","watch":"a"})).await;
        }
        // Control dispatch is not evidence: wait for this actor's sticky state.
        observed_terminal(&handle).await;
        barrier.resume.notify_one();
        assert_eq!(next.await.unwrap().unwrap_err().code, "cancelled");
        bridge.close().await.unwrap_or_else(|_| panic!("close"));
    })
    .await
    .expect("bounded sealed actor completion race");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completed_worker_source_revoke_actual_sealed_actor() {
    after_worker_case(false).await;
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn completed_worker_session_reset_actual_sealed_actor() {
    after_worker_case(true).await;
}
struct ResumeSerialize(Arc<SerializeBarrier>);
impl Drop for ResumeSerialize {
    fn drop(&mut self) {
        if let Ok(mut resumed) = self.0.resume.0.lock() {
            *resumed = true;
            self.0.resume.1.notify_all();
        }
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancel_serialization_actual_sealed_actor() {
    timeout(Duration::from_secs(5), async {
        let peer = tokio::task::spawn_blocking(Peer::start).await.unwrap();
        let (bridge, id, handle) = peer.bridge_watch().await;
        let barrier = Arc::new(SerializeBarrier::default());
        let _resume_on_failure = ResumeSerialize(barrier.clone());
        *handle.serialize_barrier.lock().unwrap() = Some(barrier.clone());
        let caller = bridge.clone();
        let next = tokio::spawn(async move { caller.project_task_watch_next(id).await });
        peer.control(json!({"op":"send","watch":"a","kind":"baseline"}))
            .await;
        barrier.started.notified().await;
        peer.control(json!({"op":"revoke","watch":"a"})).await;
        observed_terminal(&handle).await;
        *barrier.resume.0.lock().unwrap() = true;
        barrier.resume.1.notify_all();
        assert_eq!(next.await.unwrap().unwrap_err().code, "cancelled");
        bridge.close().await.unwrap_or_else(|_| panic!("close"));
    })
    .await
    .expect("bounded actual sealed serde invalidation");
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn full_capacity_four_pending_candidate_prioritizes_terminal_controls() {
    timeout(Duration::from_secs(5), async {
        for action in ["revoke", "force_logout", "cancel"] {
            let peer = tokio::task::spawn_blocking(Peer::start).await.unwrap();
            let (bridge, id, handle) = peer.bridge_watch().await;
            handle.hold_commits.store(true, Ordering::Release);
            peer.control(json!({"op":"send","watch":"a","kind":"baseline"}))
                .await;
            let event = bridge
                .project_task_watch_next(id.clone())
                .await
                .unwrap_or_else(|_| panic!("actual pending candidate"));
            let event: Value = serde_json::from_str(&event).unwrap();
            assert_eq!(event["kind"], "snapshot");
            assert_eq!(event["tasks"].as_array().unwrap().len(), 21);
            let receipt: TaskSyncCommit = serde_json::from_value(event["receipt"].clone()).unwrap();
            handle.commits_paused.notified().await;
            assert_eq!(handle.commits.capacity(), 4);
            let mut acknowledgements = Vec::new();
            for _ in 0..4 {
                let (ack, wait) = oneshot::channel();
                handle
                    .commits
                    .try_send(Commit {
                        receipt: receipt.clone(),
                        ack,
                    })
                    .unwrap_or_else(|_| panic!("fill exact four slots"));
                acknowledgements.push(wait);
            }
            assert_eq!(handle.commits.capacity(), 0);
            let (ack, _wait) = oneshot::channel();
            assert!(matches!(
                handle.commits.try_send(Commit { receipt, ack }),
                Err(mpsc::error::TrySendError::Full(_))
            ));
            if action == "cancel" {
                bridge
                    .project_task_watch_close(id)
                    .unwrap_or_else(|_| panic!("independent selected close"));
            } else {
                peer.control(json!({"op":action,"watch":"a"})).await;
            }
            observed_terminal(&handle).await;
            let phase = handle.control.lock().unwrap().status.state;
            assert!(matches!(
                (action, phase),
                ("revoke", Phase::Revoked)
                    | ("force_logout", Phase::Expired)
                    | ("cancel", Phase::Closed)
            ));
            for acknowledgement in acknowledgements {
                assert!(acknowledgement.await.is_err(), "no queued commit succeeds");
            }
            bridge.close().await.unwrap_or_else(|_| panic!("close"));
        }
    })
    .await
    .expect("full commit channel cannot stall priority terminal controls");
}

// Release a real held HTTP request even if a bounded assertion unwinds. The
// peer remains alive until this guard drops; failure cleanup never waits on SDK.
struct ReleaseList(Option<String>);
impl Drop for ReleaseList {
    fn drop(&mut self) {
        use std::io::Write;
        let Some(endpoint) = self.0.take() else {
            return;
        };
        let Some(port) = endpoint
            .strip_prefix("http://127.0.0.1:")
            .and_then(|p| p.parse::<u16>().ok())
        else {
            return;
        };
        if let Ok(mut socket) = std::net::TcpStream::connect_timeout(
            &std::net::SocketAddr::from(([127, 0, 0, 1], port)),
            Duration::from_secs(1),
        ) {
            let _ = socket.set_write_timeout(Some(Duration::from_secs(1)));
            let body = br#"{"op":"release_list"}"#;
            let _ = write!(
                socket,
                "POST /__test/control HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            let _ = socket.write_all(body);
        }
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn pending_next_delivers_reconnecting_while_real_client_http_is_held() {
    timeout(Duration::from_secs(5), async {
        let peer = tokio::task::spawn_blocking(Peer::start)
            .await
            .unwrap_or_else(|_| panic!("bounded watch operation"));
        let (bridge, id, _handle) = peer.bridge_watch().await;
        peer.control(json!({"op":"send","watch":"a","kind":"baseline"}))
            .await;
        let snapshot: Value = serde_json::from_str(
            &bridge
                .project_task_watch_next(id.clone())
                .await
                .unwrap_or_else(|_| panic!("bounded watch operation")),
        )
        .unwrap();
        assert_eq!(snapshot["kind"], "snapshot");
        bridge
            .project_task_watch_commit(id.clone(), snapshot["receipt"].to_string())
            .await
            .unwrap_or_else(|_| panic!("bounded watch operation"));
        let connected: Value = serde_json::from_str(
            &bridge
                .project_task_watch_next(id.clone())
                .await
                .unwrap_or_else(|_| panic!("bounded watch operation")),
        )
        .unwrap();
        assert_eq!(connected["state"], "connected");

        let mut next = Box::pin(bridge.project_task_watch_next(id.clone()));
        // Poll the actual consumer through its queue before the transition;
        // merely spawning a future would not establish that it was waiting.
        assert!(
            std::future::poll_fn(|cx| std::task::Poll::Ready(next.as_mut().poll(cx).is_pending()))
                .await
        );
        peer.control(json!({"op":"hold_list"})).await;
        let mut release = ReleaseList(Some(peer.endpoint.clone()));
        let caller = bridge.clone();
        let ordinary = tokio::spawn(async move {
            caller
                .projects_list(ProjectFilters {
                    personal: true,
                    ..Default::default()
                })
                .await
        });
        peer.control(json!({"op":"beacon","key":"list_entered","minimum":1}))
            .await;
        peer.control(json!({"op":"send","watch":"a","kind":"baseline"}))
            .await;
        let state: Value = serde_json::from_str(
            &timeout(Duration::from_secs(1), &mut next)
                .await
                .expect("pending next must expose contention before HTTP release")
                .unwrap_or_else(|_| panic!("bounded watch operation")),
        )
        .unwrap();
        assert_eq!(state["state"], "reconnecting");
        assert_eq!(state["cursor"], snapshot["cursor"]);
        assert!(!ordinary.is_finished(), "ordinary HTTP request still held");
        assert!(
            bridge.state.client.try_lock().is_err(),
            "real Client lane still held"
        );
        drop(next);
        peer.control(json!({"op":"release_list"})).await;
        release.0 = None;
        let listed: Value = serde_json::from_str(
            &ordinary
                .await
                .unwrap_or_else(|_| panic!("bounded watch operation"))
                .unwrap_or_else(|_| panic!("bounded ordinary operation")),
        )
        .unwrap();
        assert_eq!(listed, json!([]));
        let report = peer
            .control_report(json!({"op":"beacon","key":"subscriptions","minimum":2}))
            .await;
        assert_eq!(
            report["resumes"].as_array().unwrap().last().unwrap(),
            &snapshot["cursor"],
            "reconnect resumes only durable committed cursor"
        );
        peer.control(
            json!({"op":"bind_watch","watch":"a","after":1,"source_id":peer.suite["source_id"]}),
        )
        .await;
        let generations = report["active_generations"].as_array().unwrap();
        assert_eq!(generations.len(), 1, "only reconnected watch is live");
        peer.control(json!({"op":"send","watch":"a","generation":generations[0],"kind":"delta"}))
            .await;
        loop {
            let event: Value = serde_json::from_str(
                &bridge
                    .project_task_watch_next(id.clone())
                    .await
                    .unwrap_or_else(|_| panic!("bounded watch operation")),
            )
            .unwrap();
            if event["kind"] == "snapshot" {
                assert_eq!(event["cursor"], "epoch:2");
                bridge
                    .project_task_watch_commit(id.clone(), event["receipt"].to_string())
                    .await
                    .unwrap_or_else(|_| panic!("bounded watch operation"));
                break;
            }
            assert!(
                !["closed", "failed", "expired", "revoked"]
                    .contains(&event["state"].as_str().unwrap_or(""))
            );
        }
        bridge
            .close()
            .await
            .unwrap_or_else(|_| panic!("bounded watch operation"));
    })
    .await
    .expect("bounded pending-next contention recovery");
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn pending_status_wake_prioritizes_cancel_reset_and_old_expiry() {
    timeout(Duration::from_secs(5), async {
        for change in ["cancel", "reset", "expired-reset"] {
            let peer = tokio::task::spawn_blocking(Peer::start).await.unwrap();
            let (bridge, id, handle) = peer.bridge_watch().await;
            let barrier = Arc::new(ReturnBarrier::default());
            *handle.status_barrier.lock().unwrap() = Some(barrier.clone());
            let caller = bridge.clone();
            let selected = id.clone();
            let mut pending =
                Box::pin(async move { caller.project_task_watch_next(selected).await });
            assert!(
                std::future::poll_fn(|cx| std::task::Poll::Ready(
                    pending.as_mut().poll(cx).is_pending()
                ))
                .await
            );
            let next = tokio::spawn(pending);
            handle.transition(Phase::Reconnecting, None);
            barrier.completed.notified().await;
            if change == "cancel" {
                bridge
                    .project_task_watch_close(id)
                    .unwrap_or_else(|_| panic!("selected cancel"));
            } else {
                if change == "expired-reset" {
                    handle.stop(Phase::Expired);
                }
                bridge
                    .import_session(peer.session())
                    .await
                    .unwrap_or_else(|_| panic!("identity reset"));
            }
            barrier.resume.notify_one();
            let result = next.await.unwrap();
            if change == "cancel" {
                let state: Value = serde_json::from_str(
                    &result.unwrap_or_else(|_| panic!("selected terminal state")),
                )
                .unwrap();
                assert_eq!(
                    state["state"], "closed",
                    "terminal replaces queued nonterminal state"
                );
            } else {
                assert_eq!(
                    result
                        .expect_err("old watch identity must fail closed")
                        .code,
                    "cancelled",
                    "old expired status cannot clear newer identity"
                );
            }
            bridge.close().await.unwrap_or_else(|_| panic!("close"));
        }
    })
    .await
    .expect("bounded post-wake status lifecycle races");
}
