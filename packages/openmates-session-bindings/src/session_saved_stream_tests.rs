//! Authored actual-protocol private allocation tests. Isolated CI only; UNRUN.
// contract-test-file: tooling
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
use super::*;
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    time::Duration,
};
#[track_caller]
fn ok<T>(result: Result<T>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("saved stream fixture setup code={}", error.code),
    }
}
#[track_caller]
fn ok_at<T>(phase: &'static str, result: Result<T>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("saved-stream-diag phase={phase} code={}", error.code),
    }
}

struct Peer {
    child: Child,
    endpoint: String,
    suite: Value,
}
impl Peer {
    fn new(mode: &str) -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .unwrap()
            .to_owned();
        let fixture = root.join("tests/sdk-conformance/fixtures/session-work.json");
        let document: Value = serde_json::from_slice(&std::fs::read(&fixture).unwrap()).unwrap();
        let suite = document["capabilities"]["session.work-crud.v1"].clone();
        let vector = suite["vectors"]
            .as_array()
            .unwrap()
            .iter()
            .find(|v| v["mode"] == mode)
            .unwrap();
        let python =
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into());
        let mut child = Command::new(python)
            .arg(root.join("tests/sdk-conformance/session_work_server.py"))
            .arg("--fixture")
            .arg(&fixture)
            .arg("--vector")
            .arg(vector["id"].as_str().unwrap())
            .args(["--identity", "rust"])
            .current_dir(root)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let mut line = String::new();
        BufReader::new(child.stdout.take().unwrap())
            .read_line(&mut line)
            .unwrap();
        let ready: Value = serde_json::from_str(&line).unwrap();
        let endpoint = ready["endpoint"].as_str().unwrap().to_owned();
        assert!(endpoint.starts_with("http://127.0.0.1:"));
        Self {
            child,
            endpoint,
            suite,
        }
    }
    fn get(&self, path: &str) -> Value {
        let address = self.endpoint.strip_prefix("http://").unwrap();
        let mut socket = TcpStream::connect(address).unwrap();
        socket
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
        socket
            .write_all(
                format!("GET {path} HTTP/1.1\r\nHost: {address}\r\nConnection: close\r\n\r\n")
                    .as_bytes(),
            )
            .unwrap();
        let mut raw = String::new();
        socket.read_to_string(&mut raw).unwrap();
        assert!(raw.starts_with("HTTP/1.1 200"));
        serde_json::from_str(raw.split_once("\r\n\r\n").unwrap().1).unwrap()
    }
    async fn wait(&self, predicate: impl Fn(&Value) -> bool) {
        for _ in 0..500 {
            let report = self.get("/__test/status");
            assert!(report["failure"].is_null());
            if predicate(&report) {
                return;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        panic!("saved stream protocol barrier")
    }
    fn session(&self) -> String {
        let account = &self.suite["saved_stream"]["account"];
        json!({"api_url":self.endpoint,"session_id":account["session_id"],"cookies":{"auth_refresh_token":account["cookie"]},"ws_token":null,"master_key":account["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()
    }
    async fn bridge(&self) -> SessionBridge {
        let bridge=ok(SessionBridge::new(&json!({"api_url":self.endpoint,"app_url":self.suite["saved_stream"]["protocol"]["app_origin"],"enhanced_privacy":false,"allow_private_operations":true}).to_string()));
        ok(bridge.import_session(self.session()).await);
        bridge
    }
    async fn start(&self, bridge: &SessionBridge) -> String {
        ok(bridge
            .start_send(
                self.suite["saved_stream"]["protocol"]["input"]
                    .as_str()
                    .unwrap()
                    .into(),
                Some(
                    self.suite["saved_stream"]["protocol"]["initial_chat_id"]
                        .as_str()
                        .unwrap()
                        .into(),
                ),
            )
            .await)
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
async fn drain(bridge: &SessionBridge, id: &str) {
    loop {
        match bridge.next_event_prepare(id.into()).await {
            Ok(output) => {
                let terminal = output.is_terminal();
                drop(output);
                if terminal {
                    return;
                }
            }
            Err(error) => {
                assert_eq!(error.code, "cancelled");
                return;
            }
        }
    }
}
// Success-terminal callers retain fixed refusal diagnostics across default-parallel cases.
// Only PublicFailure payloads are inspected; no private completed Chat is parsed here.
fn diagnose_success_terminal(output: &SavedStreamOutput) {
    if !matches!(&output.release, Release::PublicFailure) { return; }
    let value: Value = serde_json::from_str(output.output.as_str())
        .unwrap_or_else(|_| panic!("saved-stream-diag phase=success_terminal code=malformed_failure"));
    match value["error"]["code"].as_str() {
        Some("invalid_argument") => panic!("saved-stream-diag phase=success_terminal code=invalid_argument"),
        Some("crypto") => panic!("saved-stream-diag phase=success_terminal code=crypto"),
        Some("authentication") => panic!("saved-stream-diag phase=success_terminal code=authentication"),
        Some("two_factor_required") => panic!("saved-stream-diag phase=success_terminal code=two_factor_required"),
        Some("signup_required") => panic!("saved-stream-diag phase=success_terminal code=signup_required"),
        Some("unavailable") => panic!("saved-stream-diag phase=success_terminal code=unavailable"),
        Some("locked") => panic!("saved-stream-diag phase=success_terminal code=locked"),
        Some("offline") => panic!("saved-stream-diag phase=success_terminal code=offline"),
        Some("forbidden") => panic!("saved-stream-diag phase=success_terminal code=forbidden"),
        Some("expired") => panic!("saved-stream-diag phase=success_terminal code=expired"),
        Some("cancelled") => panic!("saved-stream-diag phase=success_terminal code=cancelled"),
        Some("io") => panic!("saved-stream-diag phase=success_terminal code=io"),
        Some("protocol") => panic!("saved-stream-diag phase=success_terminal code=protocol"),
        Some("conflict") => panic!("saved-stream-diag phase=success_terminal code=conflict"),
        _ => panic!("saved-stream-diag phase=success_terminal code=unclassified"),
    }
}

async fn final_output(bridge: &SessionBridge, id: &str) -> SavedStreamOutput {
    loop {
        let output = ok_at("final_output_next", bridge.next_event_prepare(id.into()).await);
        if output.is_terminal() {
            diagnose_success_terminal(&output);
            return output;
        }
        ok_at("final_output_intermediate_encode", output.encode_with(|text| Ok(text.to_owned())));
    }
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_live_first_token_allocates_without_client_lock_and_successful_drop_does_not_cancel()
{
    let peer = Peer::new("saved_host_abort");
    let bridge = peer.bridge().await;
    let id = peer.start(&bridge).await;
    let mut output = ok(bridge.next_event_prepare(id.clone()).await);
    assert!(!output.is_terminal());
    assert!(bridge.state.legacy_client_lane.try_lock().is_err(), "legacy cancellation setters remain behind the original stream drain");
    let encoded = ok(output.encode_checked(|text| Ok(text.to_owned())));
    assert!(encoded.contains("Started"));
    assert!(output.output.is_empty());
    drop(output);
    assert!(!bridge
        .state
        .active
        .lock()
        .unwrap()
        .as_ref()
        .unwrap()
        .cancel
        .is_cancelled());
    peer.wait(|r| r["admissions"] == 1).await;
    ok(bridge.cancel_stream(id.clone()));
    drain(&bridge, &id).await;
    ok(bridge.close().await);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_queued_cancel_refuses_before_allocator_and_wipes_owned_scratch() {
    let peer = Peer::new("saved_host_abort");
    let bridge = peer.bridge().await;
    let id = peer.start(&bridge).await;
    let mut output = ok(bridge.next_event_prepare(id.clone()).await);
    peer.wait(|r| r["admissions"] == 1).await;
    ok(bridge.cancel_stream(id.clone()));
    let called = AtomicBool::new(false);
    let result = output.encode_checked(|_| {
        called.store(true, Ordering::SeqCst);
        Ok(())
    });
    assert_eq!(result.err().map(|e| e.code), Some("cancelled"));
    assert!(!called.load(Ordering::SeqCst));
    assert!(output.output.is_empty());
    drop(output);
    drain(&bridge, &id).await;
    ok(bridge.close().await);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_request_cancel_inside_allocator_refuses_after_allocation_and_wipes() {
    let peer = Peer::new("saved_host_abort");
    let bridge = peer.bridge().await;
    let id = peer.start(&bridge).await;
    let mut output = ok(bridge.next_event_prepare(id.clone()).await);
    let result = output.encode_checked(|text| {
        let value = text.to_owned();
        bridge.cancel_stream(id.clone())?;
        Ok(value)
    });
    assert_eq!(result.err().map(|e| e.code), Some("cancelled"));
    assert!(output.output.is_empty());
    drop(output);
    drain(&bridge, &id).await;
    ok(bridge.close().await);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_global_cancel_refuses_old_output_but_fresh_b_uses_unchanged_parent() {
    let peer = Peer::new("saved_global_cancel");
    let bridge = peer.bridge().await;
    let id = peer.start(&bridge).await;
    let identity = bridge.state.identity_epoch.load(Ordering::Acquire);
    let mut output = ok(bridge.next_event_prepare(id.clone()).await);
    peer.wait(|r| r["admissions"] == 1).await;
    ok(bridge.cancel());
    assert_eq!(
        bridge.state.identity_epoch.load(Ordering::Acquire),
        identity
    );
    assert_eq!(
        output.encode_checked(|_| Ok(())).err().map(|e| e.code),
        Some("cancelled")
    );
    assert!(output.output.is_empty());
    drop(output);
    drain(&bridge, &id).await;
    let snapshot: Value = serde_json::from_str(&ok(bridge.export_session(true).await)).unwrap();
    assert_eq!(
        snapshot["session"]["master_key"],
        peer.suite["saved_stream"]["account"]["master_key"]
    );
    let b = ok(bridge
        .start_send(
            peer.suite["saved_stream"]["protocol"]["input"]
                .as_str()
                .unwrap()
                .into(),
            None,
        )
        .await);
    let encoded = ok(final_output(&bridge, &b)
        .await
        .encode_with(|text| Ok(text.to_owned())));
    let chat: Value = serde_json::from_str(&encoded).unwrap();
    assert_eq!(chat["type"], "completed");
    let report = peer.get("/__test/status");
    assert_eq!(report["admissions"], 2);
    assert_eq!(chat["chat"]["id"], report["admitted_chats"][1]);
    ok(bridge.close().await);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_queued_explicit_import_or_key_reset_or_close_refuses_original_output() {
    for action in ["import", "key", "close"] {
        let peer = Peer::new("saved_queued_import_revoke");
        let bridge = peer.bridge().await;
        let id = peer.start(&bridge).await;
        let mut output = ok(bridge.next_event_prepare(id.clone()).await);
        peer.wait(|r| r["admissions"] == 1).await;
        if action == "close" {
            ok(bridge.close().await);
        } else {
            let mut session: Value = serde_json::from_str(&peer.session()).unwrap();
            if action == "key" {
                session["master_key"] =
                    Value::String("AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI=".into());
            }
            ok(bridge.import_session(session.to_string()).await);
        }
        assert_eq!(
            output.encode_checked(|_| Ok(())).err().map(|e| e.code),
            Some("cancelled")
        );
        assert!(output.output.is_empty());
        drop(output);
        drain(&bridge, &id).await;
        ok(bridge.close().await);
    }
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_stale_terminal_a_refuses_and_drop_does_not_cancel_actual_b() {
    let peer = Peer::new("saved_queued_successor_terminal");
    let bridge = peer.bridge().await;
    let a = peer.start(&bridge).await;
    let mut output = final_output(&bridge, &a).await;
    assert!(output.output.contains("completed"));
    peer.wait(|r| r["closed_sockets"] == 1).await;
    let b = peer.start(&bridge).await;
    loop {
        let event: Value = serde_json::from_str(&ok(bridge.next_event(b.clone()).await)).unwrap();
        if event["update"].get("Admitted").is_some() {
            break;
        }
    }
    assert_eq!(
        output.encode_checked(|_| Ok(())).err().map(|e| e.code),
        Some("cancelled")
    );
    assert!(output.output.is_empty());
    drop(output);
    {
        let active = bridge.state.active.lock().unwrap();
        assert_eq!(active.as_ref().unwrap().id, b);
        assert!(!active.as_ref().unwrap().cancel.is_cancelled());
    }
    assert_eq!(peer.get("/__test/status")["closed_sockets"], 1);
    peer.get("/__test/release-b");
    let terminal = final_output(&bridge, &b).await;
    ok(terminal.encode_with(|text| Ok(text.to_owned())));
    ok(bridge.close().await);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_original_policy_revoked_after_replacement_is_still_checked() {
    let peer = Peer::new("saved_queued_successor_terminal");
    let bridge = peer.bridge().await;
    let allowed = Arc::new(AtomicBool::new(true));
    let old = allowed.clone();
    bridge
        .state
        .client
        .lock()
        .await
        .set_private_operation_gate(Some(Arc::new(move || {
            if old.load(Ordering::SeqCst) {
                Ok(())
            } else {
                Err(Error::Forbidden)
            }
        })));
    let a = peer.start(&bridge).await;
    let mut output = final_output(&bridge, &a).await;
    bridge
        .state
        .client
        .lock()
        .await
        .set_private_operation_gate(Some(Arc::new(|| Ok(()))));
    allowed.store(false, Ordering::SeqCst);
    assert_eq!(
        output.encode_checked(|_| Ok(())).err().map(|e| e.code),
        Some("forbidden")
    );
    assert!(output.output.is_empty());
    drop(output);
    ok(bridge.close().await);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_terminal_contended_client_lock_refuses_nonblocking_before_allocator() {
    let peer = Peer::new("saved_queued_successor_terminal");
    let bridge = peer.bridge().await;
    let a = peer.start(&bridge).await;
    let mut output = final_output(&bridge, &a).await;
    let _held = bridge.state.client.lock().await;
    let called = AtomicBool::new(false);
    assert_eq!(
        output
            .encode_checked(|_| {
                called.store(true, Ordering::SeqCst);
                Ok(())
            })
            .err()
            .map(|e| e.code),
        Some("conflict")
    );
    assert!(!called.load(Ordering::SeqCst));
    assert!(output.output.is_empty());
    drop(_held);
    drop(output);
    ok(bridge.close().await);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_encoder_failure_wipes_without_releasing_a_foreign_value() {
    let peer = Peer::new("saved_host_abort");
    let bridge = peer.bridge().await;
    let id = peer.start(&bridge).await;
    let mut output = ok(bridge.next_event_prepare(id.clone()).await);
    assert_eq!(
        output
            .encode_checked::<()>(|_| Err(Error::Protocol.into()))
            .err()
            .map(|e| e.code),
        Some("protocol")
    );
    assert!(output.output.is_empty());
    drop(output);
    drain(&bridge, &id).await;
    ok(bridge.close().await);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_caller_parent_cancellation_refuses_terminal_rearm() {
    let peer = Peer::new("saved_global_cancel");
    eprintln!("saved-stream-diag phase=parent_bridge");
    let bridge = peer.bridge().await;
    let parent = CancellationToken::new();
    bridge
        .state
        .client
        .lock()
        .await
        .set_operation_cancel(parent.clone());
    eprintln!("saved-stream-diag phase=parent_start_a");
    let a = peer.start(&bridge).await;
    eprintln!("saved-stream-diag phase=parent_prepare_a");
    let mut output = ok(bridge.next_event_prepare(a.clone()).await);
    peer.wait(|r| r["admissions"] == 1).await;
    let release_kind = match &output.release {
        Release::Live { .. } => "live",
        Release::Terminal { .. } => "terminal",
        Release::PublicFailure => "public_failure",
        Release::Anonymous => "anonymous",
    };
    eprintln!("saved-stream-diag phase=parent_before_cancel release={release_kind}");
    parent.cancel();
    assert_eq!(
        output.encode_checked(|_| Ok(())).err().map(|e| e.code),
        Some("cancelled")
    );
    assert!(output.output.is_empty());
    drop(output);
    eprintln!("saved-stream-diag phase=parent_drain_a");
    drain(&bridge, &a).await;
    eprintln!("saved-stream-diag phase=parent_start_b");
    let b = peer.start(&bridge).await;
    eprintln!("saved-stream-diag phase=parent_event_b");
    let result = ok(bridge.next_event(b).await);
    let event: Value = serde_json::from_str(&result).unwrap();
    assert_eq!(event["type"], "error");
    assert_eq!(event["error"]["code"], "cancelled");
    assert_eq!(peer.get("/__test/status")["admissions"], 1);
    eprintln!("saved-stream-diag phase=parent_close");
    ok(bridge.close().await);
}
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_malformed_replacement_retires_old_scope_without_claiming_auth_changed() {
    for invalid in ["{not-json", "{}"] {
        let peer = Peer::new("saved_host_abort");
        let bridge = peer.bridge().await;
        let a = peer.start(&bridge).await;
        let identity = bridge.state.identity_epoch.load(Ordering::Acquire);
        let mut output = ok(bridge.next_event_prepare(a.clone()).await);
        peer.wait(|r| r["admissions"] == 1).await;
        assert_eq!(
            bridge
                .import_session(invalid.into())
                .await
                .err()
                .map(|e| e.code),
            Some("invalid_argument")
        );
        assert_ne!(
            bridge.state.identity_epoch.load(Ordering::Acquire),
            identity
        );
        assert_eq!(
            output.encode_checked(|_| Ok(())).err().map(|e| e.code),
            Some("cancelled")
        );
        assert!(output.output.is_empty());
        drop(output);
        drain(&bridge, &a).await;
        let snapshot: Value = serde_json::from_str(&ok(bridge.export_session(true).await)).unwrap();
        assert_eq!(
            snapshot["session"]["master_key"],
            peer.suite["saved_stream"]["account"]["master_key"]
        );
        assert_eq!(
            snapshot["session"]["session_id"],
            peer.suite["saved_stream"]["account"]["session_id"]
        );
        ok(bridge.close().await);
    }
}

#[path = "session_prepared_start_tests.rs"]
mod prepared_start_tests;

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_owned_receive_releases_client_while_legacy_read_waits_for_original_drain() {
    let peer = Peer::new("saved_host_abort");
    let bridge = peer.bridge().await;
    let id = peer.start(&bridge).await;
    // This peer leaves the original admitted receive pending until cancellation.
    peer.wait(|r| r["admissions"] == 1).await;
    let original=bridge.state.saved_driver.lock().unwrap().clone().unwrap();
    let client=tokio::time::timeout(Duration::from_secs(3),bridge.state.client.lock()).await.expect("receive owns no Client lock");
    drop(client);
    assert!(!original.is_settled());
    let waiting=bridge.clone();
    let read=tokio::spawn(async move { waiting.drafts_list_cached().await });
    tokio::task::yield_now().await;
    assert!(!read.is_finished(),"legacy list cannot replace A's cancellation lane");
    ok(bridge.cancel_stream(id.clone()));
    drain(&bridge,&id).await;
    original.settled().await;
    let _=read.await.expect("legacy operation joined");
    ok(bridge.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_owned_close_drains_same_driver_without_client_lock_or_foreign_update_ack() {
    let peer = Peer::new("saved_host_abort");
    let bridge = peer.bridge().await;
    let id=peer.start(&bridge).await;
    let mut output=ok(bridge.next_event_prepare(id).await);
    peer.wait(|r|r["admissions"]==1).await;
    let original=bridge.state.saved_driver.lock().unwrap().clone().unwrap();
    // Retain an actual native output across close. Its original guard must refuse
    // allocation; it cannot pin transport cleanup or borrow terminal authority.
    ok(tokio::time::timeout(Duration::from_secs(3),bridge.close()).await.expect("exact original driver drains"));
    assert!(original.is_settled());
    let called=AtomicBool::new(false);
    assert_eq!(output.encode_checked(|_| { called.store(true,Ordering::SeqCst); Ok(()) }).err().map(|e|e.code),Some("cancelled"));
    assert!(!called.load(Ordering::SeqCst));
    assert!(output.output.is_empty());
    // The peer counts the close on its own handler thread after the Core closes
    // the socket, so observe it through the protocol barrier, not a one-shot read.
    peer.wait(|r|r["closed_sockets"].as_u64().unwrap()>0).await;
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_owned_terminal_waits_for_original_live_output_allocation_before_retiring_child() {
    let peer=Peer::new("saved_queued_successor_terminal");
    let bridge=peer.bridge().await;
    let id=peer.start(&bridge).await;
    let mut output=ok(bridge.next_event_prepare(id.clone()).await);
    assert!(!output.is_terminal());
    let original=bridge.state.saved_driver.lock().unwrap().clone().unwrap();
    // The peer has seen the actual socket close: the Core receive returned.
    // This retained native output has not yet acknowledged its allocation.
    peer.wait(|r|r["closed_sockets"]==1).await;
    assert!(!original.is_settled(),"terminal cannot retire the original update child early");
    assert!(original.updates_outstanding.load(Ordering::Acquire)>0);
    ok(output.encode_checked(|text|Ok(text.to_owned())));
    drop(output);
    let terminal=final_output(&bridge,&id).await;
    assert!(original.is_settled());
    let encoded=ok(terminal.encode_with(|text|Ok(text.to_owned())));
    assert_eq!(serde_json::from_str::<Value>(&encoded).unwrap()["type"],"completed");
    ok(bridge.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_terminal_delivery_always_follows_original_join_before_rapid_successor_close() {
    let peer=Peer::new("saved_queued_successor_terminal");
    let bridge=peer.bridge().await;
    let a=peer.start(&bridge).await;
    let original=bridge.state.saved_driver.lock().unwrap().clone().unwrap();
    let terminal=final_output(&bridge,&a).await;
    assert!(original.is_settled(),"terminal publication is post actual join");
    ok(terminal.encode_with(|text|Ok(text.to_owned())));
    let b=peer.start(&bridge).await;
    let successor=bridge.state.saved_driver.lock().unwrap().clone().unwrap();
    assert!(!Arc::ptr_eq(&original,&successor));
    peer.wait(|r|r["admissions"]==2).await;
    ok(tokio::time::timeout(Duration::from_secs(3),bridge.close()).await.expect("close drains actual successor"));
    assert!(original.is_settled());
    assert!(successor.is_settled());
    assert!(bridge.state.closed.load(Ordering::Acquire));
    let _=b;
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_fixed_apps_b_read_and_own_cancel_preserve_rotated_headers_and_withheld_a_receive() {
    let peer=Peer::new("saved_host_abort");
    let bridge=peer.bridge().await;
    let a=peer.start(&bridge).await;
    peer.wait(|r|r["admissions"]==1).await;
    let original=bridge.state.saved_driver.lock().unwrap().clone().unwrap();
    let raw=ok(tokio::time::timeout(Duration::from_secs(3),bridge.list("apps".into())).await.expect("genuine B list during withheld A"));
    let apps:Value=serde_json::from_str(&raw).unwrap();
    assert_eq!(apps[0]["id"],"fixture-app");
    assert_eq!(apps[0]["title"],"Fixture inventory");
    assert_eq!(apps[0]["category"],"Apps");
    assert_eq!(apps[0]["fields"]["id"],"fixture-app");
    assert!(!original.is_settled());
    assert!(!original.request.is_cancelled());
    peer.get("/__test/inventory-hold-next");
    let guard=Arc::new(ok(bridge.admit_work()));
    let own=guard.clone();let b_bridge=bridge.clone();
    let b=tokio::spawn(async move{b_bridge.apps_inventory_prepare_admitted(own).await});
    peer.wait(|r|r["inventory_headers"]==2).await;
    // Wait for the actual matched-header merge, without using export_session's
    // intentionally serialized legacy lane or any reset/current-child mutation.
    tokio::time::timeout(Duration::from_secs(3),async {
        loop {
            let current=bridge.state.client.lock().await.credential_snapshot().unwrap();
            if current.session.cookies.get("auth_refresh_token").map(String::as_str)==Some("synthetic-inventory-rotation-2"){break;}
            tokio::task::yield_now().await;
        }
    }).await.expect("actual rotated header installed before held body");
    guard.cancel();
    let result=tokio::time::timeout(Duration::from_secs(3),b).await.expect("B own cancellation drains body future").unwrap();
    assert_eq!(result.err().map(|e|e.code),Some("cancelled"));
    assert!(!original.request.is_cancelled(),"B cancellation cannot cancel A");
    assert!(!original.is_settled(),"B does not fabricate A terminal or rearm");
    let current=bridge.state.client.lock().await.credential_snapshot().unwrap();
    assert_eq!(current.session.cookies.get("auth_refresh_token").map(String::as_str),Some("synthetic-inventory-rotation-2"));
    peer.get("/__test/inventory-release-body");
    peer.get("/__test/release-owned-a");
    let output=final_output(&bridge,&a).await;
    let encoded=ok(output.encode_with(|text|Ok(text.to_owned())));
    assert_eq!(serde_json::from_str::<Value>(&encoded).unwrap()["type"],"completed");
    assert!(original.is_settled());
    assert_eq!(peer.get("/__test/status")["inventory_requests"],2);
    ok(bridge.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_withheld_catalogue_allows_fixed_b_read_and_b_only_cancel_with_both_rotated_headers() {
    let peer=Peer::new("saved_host_abort");peer.get("/__test/catalogue-enable");
    let bridge=peer.bridge().await;let a=peer.start(&bridge).await;
    peer.wait(|r|r["catalogue_headers"]==1).await;
    let original=bridge.state.saved_driver.lock().unwrap().clone().unwrap();
    let client=tokio::time::timeout(Duration::from_secs(3),async {
        loop {
            let client=bridge.state.client.lock().await;
            let actual=client.credential_snapshot().unwrap();
            if actual.session.cookies.get("auth_refresh_token").map(String::as_str)==Some("synthetic-catalogue-rotation"){break client;}
            drop(client);
            tokio::task::yield_now().await;
        }
    }).await.expect("withheld catalogue HTTP body holds no Client");drop(client);
    let apps=ok(tokio::time::timeout(Duration::from_secs(3),bridge.list("apps".into())).await.expect("real fixed B completes during catalogue body wait"));
    assert_eq!(serde_json::from_str::<Value>(&apps).unwrap()[0]["id"],"fixture-app");
    assert!(!original.request.is_cancelled());assert!(!original.is_settled());
    peer.get("/__test/inventory-hold-next");
    let own=Arc::new(ok(bridge.admit_work()));let worker=own.clone();let b_bridge=bridge.clone();
    let b=tokio::spawn(async move{b_bridge.apps_inventory_prepare_admitted(worker).await});
    peer.wait(|r|r["inventory_headers"]==2).await;
    tokio::time::timeout(Duration::from_secs(3),async{loop{
        let actual=bridge.state.client.lock().await.credential_snapshot().unwrap();
        if actual.session.cookies.get("auth_refresh_token").map(String::as_str)==Some("synthetic-inventory-rotation-2"){break;}
        tokio::task::yield_now().await;
    }}).await.expect("B actual header merge");
    own.cancel();
    let result=tokio::time::timeout(Duration::from_secs(3),b).await.expect("only original B drains").unwrap();
    assert_eq!(result.err().map(|e|e.code),Some("cancelled"));
    assert!(!original.request.is_cancelled());assert!(!original.is_settled());
    assert_eq!(peer.get("/__test/status")["catalogue_results"],0);
    peer.get("/__test/inventory-release-body");peer.get("/__test/catalogue-release-body");
    peer.wait(|r|r["catalogue_results"]==1).await;
    assert!(!original.request.is_cancelled());assert!(!original.is_settled());
    peer.get("/__test/release-owned-a");
    let terminal=final_output(&bridge,&a).await;
    let encoded=ok(terminal.encode_with(|text|Ok(text.to_owned())));
    assert_eq!(serde_json::from_str::<Value>(&encoded).unwrap()["type"],"completed");
    assert!(original.is_settled());ok(bridge.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_a_catalogue_request_cancel_retains_real_headers_and_original_b_publication() {
    let peer=Peer::new("saved_host_abort");peer.get("/__test/catalogue-enable");
    let bridge=peer.bridge().await;let a=peer.start(&bridge).await;
    peer.wait(|r|r["catalogue_headers"]==1).await;
    let b=ok(tokio::time::timeout(Duration::from_secs(3),async {
        loop {
            let actual=bridge.state.client.lock().await.credential_snapshot().unwrap();
            if actual.session.cookies.get("auth_refresh_token").map(String::as_str)==Some("synthetic-catalogue-rotation"){break;}
            tokio::task::yield_now().await;
        }
        bridge.apps_inventory_prepare().await
    }).await.expect("real B during withheld catalogue"));
    let before=bridge.state.client.lock().await.credential_snapshot().unwrap();
    assert_eq!(before.session.cookies.get("auth_refresh_token").map(String::as_str),Some("synthetic-inventory-rotation-1"));
    ok(bridge.cancel_stream(a.clone()));drain(&bridge,&a).await;
    let encoded=ok(b.encode_with(|text|Ok(text.to_owned())));
    assert_eq!(serde_json::from_str::<Value>(&encoded).unwrap()[0]["id"],"fixture-app","A cancellation never retires original B");
    let after=bridge.state.client.lock().await.credential_snapshot().unwrap();
    assert_eq!(after.session.cookies,before.session.cookies,"held A body cancellation cannot restore stale header jar");
    assert_eq!(peer.get("/__test/status")["catalogue_results"],0);
    peer.get("/__test/catalogue-release-body");ok(bridge.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_withheld_version_body_allows_fixed_b_and_b_only_cancel_then_same_a_fenced_persist(){
    let peer=Peer::new("saved_host_abort");peer.get("/__test/version-enable");
    eprintln!("saved-stream-diag phase=version_bridge");
    let bridge=peer.bridge().await;
    eprintln!("saved-stream-diag phase=version_start_a");
    let a=peer.start(&bridge).await;
    eprintln!("saved-stream-diag phase=version_wait_headers");
    peer.wait(|r|r["version_headers"]==1).await;
    let original=bridge.state.saved_driver.lock().unwrap().clone().unwrap();
    eprintln!("saved-stream-diag phase=version_fixed_b_list");
    let apps=ok(tokio::time::timeout(Duration::from_secs(3),async{
        loop{
            let actual=bridge.state.client.lock().await.credential_snapshot().unwrap();
            if actual.session.cookies.get("auth_refresh_token").map(String::as_str)==Some("synthetic-version-rotation"){break;}
            tokio::task::yield_now().await;
        }
        bridge.list("apps".into()).await
    }).await.expect("same Client applied actual A headers; fixed B progresses while actual Version body held"));
    assert_eq!(serde_json::from_str::<Value>(&apps).unwrap()[0]["id"],"fixture-app");
    assert!(!original.request.is_cancelled());assert!(!original.is_settled());
    peer.get("/__test/inventory-hold-next");
    let own=Arc::new(ok(bridge.admit_work()));let worker=own.clone();let b_bridge=bridge.clone();
    let b=tokio::spawn(async move{b_bridge.apps_inventory_prepare_admitted(worker).await});
    eprintln!("saved-stream-diag phase=version_wait_b_headers");
    peer.wait(|r|r["inventory_headers"]==2).await;
    tokio::time::timeout(Duration::from_secs(3),async{loop{
        let actual=bridge.state.client.lock().await.credential_snapshot().unwrap();
        if actual.session.cookies.get("auth_refresh_token").map(String::as_str)==Some("synthetic-inventory-rotation-2"){break;}
        tokio::task::yield_now().await;
    }}).await.expect("actual B header merge before B cancel");
    eprintln!("saved-stream-diag phase=version_cancel_b_join");
    own.cancel();let result=tokio::time::timeout(Duration::from_secs(3),b).await.expect("B actual task returns").unwrap();
    assert_eq!(result.err().map(|e|e.code),Some("cancelled"));
    assert!(!original.request.is_cancelled());assert!(!original.is_settled());
    assert_eq!(peer.get("/__test/status")["persists"],0);
    peer.get("/__test/inventory-release-body");peer.get("/__test/version-release-body");
    eprintln!("saved-stream-diag phase=version_final_output_a");
    let output=final_output(&bridge,&a).await;
    eprintln!("saved-stream-diag phase=version_encode_terminal_a");
    let encoded=ok(output.encode_with(|text|Ok(text.to_owned())));
    let value:Value=serde_json::from_str(&encoded).unwrap();assert_eq!(value["type"],"completed");
    assert!(encoded.contains("Synthetic sealed Version reply"),"actual leased/decrypted canonical completion, never transient frame");
    assert!(!encoded.contains("Transient only"));assert!(original.is_settled());
    let status=peer.get("/__test/status");assert_eq!(status["claims"],1);assert_eq!(status["persists"],1);assert_eq!(status["version_requests"],1);
    let actual=bridge.state.client.lock().await.credential_snapshot().unwrap();assert_eq!(actual.session.cookies.get("auth_refresh_token").map(String::as_str),Some("synthetic-inventory-rotation-2"));
    eprintln!("saved-stream-diag phase=version_close");
    ok(bridge.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_a_version_cancel_preserves_b_publication_and_rotations_without_fenced_persist(){
    let peer=Peer::new("saved_host_abort");peer.get("/__test/version-enable");
    let bridge=peer.bridge().await;let a=peer.start(&bridge).await;
    peer.wait(|r|r["version_headers"]==1).await;
    let b=ok(tokio::time::timeout(Duration::from_secs(3),async{
        loop{
            let actual=bridge.state.client.lock().await.credential_snapshot().unwrap();
            if actual.session.cookies.get("auth_refresh_token").map(String::as_str)==Some("synthetic-version-rotation"){break;}
            tokio::task::yield_now().await;
        }
        bridge.apps_inventory_prepare().await
    }).await.expect("actual B progresses before A cancel"));
    let before=bridge.state.client.lock().await.credential_snapshot().unwrap();
    assert_eq!(before.session.cookies.get("auth_refresh_token").map(String::as_str),Some("synthetic-inventory-rotation-1"));
    ok(bridge.cancel_stream(a.clone()));drain(&bridge,&a).await;
    let encoded=ok(b.encode_with(|text|Ok(text.to_owned())));assert_eq!(serde_json::from_str::<Value>(&encoded).unwrap()[0]["id"],"fixture-app");
    let after=bridge.state.client.lock().await.credential_snapshot().unwrap();assert_eq!(after.session.cookies,before.session.cookies);
    assert_eq!(peer.get("/__test/status")["persists"],0);
    peer.get("/__test/version-release-body");ok(bridge.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_live_publication_reads_overlap_inside_original_policy_callback() {
    let peer = Peer::new("saved_host_abort");
    let bridge = peer.bridge().await;
    let hold_once = Arc::new(AtomicBool::new(false));
    let selected_thread = Arc::new(Mutex::new(None::<std::thread::ThreadId>));
    let (entered_send, entered_receive) = std::sync::mpsc::sync_channel(1);
    let (release_send, release_receive) = std::sync::mpsc::channel();
    let release_receive = Arc::new(Mutex::new(release_receive));
    let callback_once = hold_once.clone();
    let callback_thread = selected_thread.clone();
    bridge.state.client.lock().await.set_private_operation_gate(Some(Arc::new(move || {
        let selected = callback_thread.lock().map_err(|_| openmates_sdk::Error::Protocol)?
            .as_ref().is_some_and(|id| *id == std::thread::current().id());
        if selected && callback_once.swap(false, Ordering::AcqRel) {
            entered_send.send(()).map_err(|_| openmates_sdk::Error::Protocol)?;
            release_receive.lock().map_err(|_| openmates_sdk::Error::Protocol)?
                .recv_timeout(Duration::from_secs(3)).map_err(|_| openmates_sdk::Error::Protocol)?;
        }
        Ok(())
    })));
    let id = peer.start(&bridge).await;
    let output = ok(bridge.next_event_prepare(id.clone()).await);
    let original = match &output.release {
        Release::Live { scope, .. } => scope.clone(),
        _ => panic!("original live output required"),
    };
    let (entered, simultaneous, first) = std::thread::scope(|threads| {
        let original_check = &original;
        let checker = threads.spawn(move || {
            *selected_thread.lock().expect("test callback identity") = Some(std::thread::current().id());
            hold_once.store(true, Ordering::Release);
            original_check.check_live()
        });
        let entered = entered_receive.recv_timeout(Duration::from_secs(3));
        let simultaneous = original.check_live();
        // Always release the callback before checking either result.
        let _ = release_send.send(());
        (entered, simultaneous, checker.join().expect("original observer joined"))
    });
    assert!(entered.is_ok(), "actual original callback reached");
    ok(simultaneous);
    ok(first);
    assert!(!original.request.is_cancelled(), "read-only overlap cannot revoke original A");
    ok(output.encode_with(|text| Ok(text.to_owned())));
    ok(bridge.cancel_stream(id.clone()));
    assert_eq!(original.check_live().err().map(|error| error.code), Some("cancelled"));
    drain(&bridge, &id).await;
    ok(bridge.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless
#[test]
fn unproven_driver_drain_ends_the_stream_with_a_typed_terminal() {
    // A driver error without a returned-refusal proof previously parked the
    // stream forever (tests/sdk-conformance session-recovery lost_ack vector).
    // It now terminates: the caller's own cancel stays `cancelled`, otherwise
    // the lost transport is reported as `offline`.
    let request = CancellationToken::new();
    let context = CancellationToken::new();
    assert!(matches!(unproven_drain_error(&request, &context), Error::Offline));
    context.cancel();
    assert!(matches!(unproven_drain_error(&request, &context), Error::Cancelled));
    let context = CancellationToken::new();
    request.cancel();
    assert!(matches!(unproven_drain_error(&request, &context), Error::Cancelled));
}
