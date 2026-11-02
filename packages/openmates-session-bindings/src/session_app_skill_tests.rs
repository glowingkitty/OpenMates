//! Actual synthetic peer/private final-allocation tests; authored UNRUN.
use super::*;
use sha2::Digest;
use std::{
    io::{BufRead, BufReader, Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    time::Duration,
};
fn ok<T>(result: Result<T>) -> T {
    let Ok(value) = result else {
        panic!("direct skill fixture setup");
    };
    value
}
struct Peer {
    child: Child,
    endpoint: String,
    suite: Value,
}
impl Peer {
    fn new(mode: &str) -> Self {
        Self::selected(mode, false)
    }
    fn named(id: &str) -> Self {
        Self::selected(id, true)
    }
    fn selected(selector: &str, by_id: bool) -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .unwrap()
            .to_owned();
        let fixture = root.join("tests/sdk-conformance/fixtures/session-direct-app-skill.json");
        let document: Value = serde_json::from_slice(&std::fs::read(&fixture).unwrap()).unwrap();
        let suite = document["capabilities"]["sdk.apps"].clone();
        let vector = suite["vectors"]
            .as_array()
            .unwrap()
            .iter()
            .find(|v| {
                if by_id {
                    v["id"] == selector
                } else {
                    v["mode"] == selector && v["credential"] == "cookie"
                }
            })
            .unwrap();
        let python =
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into());
        let mut child = Command::new(python)
            .arg(root.join("tests/sdk-conformance/session_direct_app_skill_peer.py"))
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
        panic!("direct skill protocol barrier")
    }
    fn session(&self) -> String {
        let account = &self.suite["account"];
        json!({"api_url":self.endpoint,"session_id":account["session_id"],"cookies":{"auth_refresh_token":account["cookie"]},"ws_token":null,"master_key":account["master_key"],"hashed_email":"synthetic-email-hash","user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()
    }
    async fn bridge(&self) -> SessionBridge {
        let bridge=ok(SessionBridge::new(&json!({"api_url":self.endpoint,"app_url":self.endpoint,"enhanced_privacy":false,"allow_private_operations":true}).to_string()));
        ok(bridge.import_session(self.session()).await);
        bridge
    }
    async fn prepare(&self, b: &SessionBridge) -> DirectSkillOutput {
        ok(b.run_skill_prepare(
            "web".into(),
            "search".into(),
            self.suite["request"]["input"].to_string(),
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

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_direct_positive_retains_structured_bytes_wipes_and_validates_imported_owner() {
    let p = Peer::new("sync");
    let b = p.bridge().await;
    let mut output = p.prepare(&b).await;
    let raw = ok(output.encode_checked(|text| Ok(text.to_owned())));
    assert_eq!(
        serde_json::from_str::<Value>(&raw).unwrap(),
        p.suite["sync_expected"]
    );
    assert!(output.output.is_empty());
    assert!(
        output
            .encode_checked::<()>(|_| panic!("one-use admission allocated twice"))
            .is_err()
    );
    let status = p.get("/__test/status");
    assert_eq!(status["skill_posts"], 1);
    assert!(status["auth"].as_u64().unwrap() >= 3);
    assert_eq!(status["downloads"], 0);
    assert_eq!(status["retention_posts"], 0);
    ok(b.close().await);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_queued_cancel_import_malformed_close_and_key_reset_refuse_before_allocator() {
    for change in ["cancel", "import", "malformed", "close", "key"] {
        let p = Peer::new("sync");
        let b = p.bridge().await;
        let mut output = p.prepare(&b).await;
        match change {
            "cancel" => ok(b.cancel()),
            "close" => ok(b.close().await),
            "malformed" => assert!(b.import_session("{}".into()).await.is_err()),
            "key" => {
                let mut session: Value = serde_json::from_str(&p.session()).unwrap();
                session["master_key"] = json!("CQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQkJCQk=");
                ok(b.import_session(session.to_string()).await);
            }
            _ => ok(b.import_session(p.session()).await),
        }
        assert!(
            output
                .encode_checked::<()>(|_| panic!("retired direct output allocated"))
                .is_err()
        );
        assert!(output.output.is_empty());
        assert_eq!(p.get("/__test/status")["skill_posts"], 1);
        ok(b.close().await);
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_cancellation_inside_encoder_refuses_postallocation_and_wipes() {
    let p = Peer::new("sync");
    let b = p.bridge().await;
    let mut output = p.prepare(&b).await;
    let result = output.encode_checked(|text| {
        let value = Zeroizing::new(text.to_owned());
        ok(b.cancel());
        Ok(value)
    });
    assert!(matches!(
        result,
        Err(BindingError {
            code: "cancelled",
            ..
        })
    ));
    assert!(output.output.is_empty());
    ok(b.close().await);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_original_gate_survives_permissive_replacement_and_revokes_before_or_during_allocation()
 {
    for during in [false, true] {
        let p = Peer::new("sync");
        let b = p.bridge().await;
        let allowed = Arc::new(AtomicBool::new(true));
        let original = allowed.clone();
        b.state
            .client
            .lock()
            .await
            .set_private_operation_gate(Some(Arc::new(move || {
                if original.load(Ordering::Acquire) {
                    Ok(())
                } else {
                    Err(Error::Forbidden)
                }
            })));
        let mut output = p.prepare(&b).await;
        b.state
            .client
            .lock()
            .await
            .set_private_operation_gate(Some(Arc::new(|| Ok(()))));
        if !during {
            allowed.store(false, Ordering::Release);
        }
        let result = output.encode_checked(|text| {
            assert!(during);
            let value = Zeroizing::new(text.to_owned());
            allowed.store(false, Ordering::Release);
            Ok(value)
        });
        assert!(matches!(
            result,
            Err(BindingError {
                code: "forbidden",
                ..
            })
        ));
        assert!(output.output.is_empty());
        ok(b.close().await);
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_stale_a_never_cancels_or_resets_exact_explicit_b() {
    let p = Peer::new("queued_successor");
    let b = p.bridge().await;
    let mut a = p.prepare(&b).await;
    let mut successor = ok(b
        .run_skill_prepare(
            "web".into(),
            "search".into(),
            json!({"query":"synthetic explicit successor B"}).to_string(),
        )
        .await);
    assert!(
        a.encode_checked::<()>(|_| panic!("stale A allocated"))
            .is_err()
    );
    assert!(a.output.is_empty());
    drop(a);
    {
        let c = b.state.client.lock().await;
        assert!(successor.admission.check(&*c).is_ok());
    }
    let raw = ok(successor.encode_checked(|text| Ok(text.to_owned())));
    assert_eq!(
        serde_json::from_str::<Value>(&raw).unwrap(),
        p.suite["sync_expected"]
    );
    assert!(successor.output.is_empty());
    assert_eq!(p.get("/__test/status")["skill_posts"], 2);
    ok(b.close().await);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_sync_finish_refuses_contended_client_lock_without_waiting_or_allocating() {
    let p = Peer::new("sync");
    let b = p.bridge().await;
    let mut output = p.prepare(&b).await;
    let locked = b.state.client.lock().await;
    let result = output.encode_checked::<()>(|_| panic!("contended allocator entered"));
    assert!(matches!(
        result,
        Err(BindingError {
            code: "conflict",
            ..
        })
    ));
    assert!(output.output.is_empty());
    drop(locked);
    ok(b.close().await);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_encoder_failure_and_current_privacy_tightening_wipe_owned_output() {
    for privacy in [false, true] {
        let p = Peer::new("sync");
        let b = p.bridge().await;
        let mut output = p.prepare(&b).await;
        if privacy {
            b.state
                .client
                .lock()
                .await
                .set_privacy_options(PrivacyOptions { enhanced: true });
        }
        let result = output.encode_checked::<()>(|_| {
            assert!(!privacy);
            Err(Error::Protocol.into())
        });
        assert!(result.is_err());
        assert!(output.output.is_empty());
        ok(b.close().await);
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[test]
fn existing_recursive_wiper_clears_nested_input_and_result_object_keys() {
    let mut value =
        Pending(json!({"private-key":[{"private-child":"synthetic private value"},"tail"]}));
    super::super::embed_versions::wipe(&mut value.0);
    assert!(value.0.is_null());
}

// Fixed genuine Rust conformance entry. The Python runner verifies this exact
// named suite ran (1 passed/0 ignored), this marker and every shared vector ID.
// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn shared_direct_skill_vectors() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .unwrap()
        .to_owned();
    let fixture_bytes =
        std::fs::read(root.join("tests/sdk-conformance/fixtures/session-direct-app-skill.json"))
            .unwrap();
    let fixture_hash = format!("{:x}", sha2::Sha256::digest(&fixture_bytes));
    let document: Value = serde_json::from_slice(&fixture_bytes).unwrap();
    let suite = &document["capabilities"]["sdk.apps"];
    let mut outcomes = Vec::new();
    for vector in suite["vectors"].as_array().unwrap() {
        let p = Peer::named(vector["id"].as_str().unwrap());
        let request = &suite["request"];
        let mode = vector["mode"].as_str().unwrap();
        let evidence;
        if vector["credential"] == "api_key" {
            let a = &suite["account"];
            let sdk = openmates_sdk::OpenMates::new(openmates_sdk::SdkOptions {
                api_url: p.endpoint.clone(),
                credentials: openmates_sdk::SdkCredentials::ApiKey(
                    openmates_sdk::ApiKey::new(a["api_key"].as_str().unwrap()).unwrap(),
                ),
                device_id: a["device_id"].as_str().unwrap().into(),
                client_options: openmates_sdk::ClientOptions {
                    app_url: Some(p.endpoint.clone()),
                    ..Default::default()
                },
            })
            .unwrap();
            let value = sdk
                .apps()
                .web()
                .search(request["input"].clone())
                .await
                .unwrap();
            assert_eq!(value, vector["expected"]);
            evidence = "maintained-public-api-key-library";
        } else {
            let b = p.bridge().await;
            if mode.starts_with("queued_") {
                let mut held = p.prepare(&b).await;
                if mode == "queued_successor" {
                    let mut successor = ok(b
                        .run_skill_prepare(
                            "web".into(),
                            "search".into(),
                            json!({"query":"synthetic explicit successor B"}).to_string(),
                        )
                        .await);
                    assert!(
                        held.encode_checked::<()>(|_| panic!("stale A allocated"))
                            .is_err()
                    );
                    assert!(held.output.is_empty());
                    drop(held);
                    let encoded = ok(successor.encode_checked(|raw| Ok(raw.to_owned())));
                    assert_eq!(
                        serde_json::from_str::<Value>(&encoded).unwrap(),
                        suite["sync_expected"]
                    );
                    assert!(successor.output.is_empty());
                } else {
                    match mode {
                        "queued_cancel" => ok(b.cancel()),
                        "queued_import" => ok(b.import_session(p.session()).await),
                        "queued_malformed" => {
                            assert!(matches!(
                                b.import_session("{}".into()).await,
                                Err(BindingError {
                                    code: "invalid_argument",
                                    ..
                                })
                            ));
                        }
                        "queued_close" => ok(b.close().await),
                        _ => panic!("unknown exact queue vector"),
                    }
                    assert!(matches!(
                        held.encode_checked::<()>(|_| panic!("retired allocation")),
                        Err(BindingError {
                            code: "cancelled",
                            ..
                        })
                    ));
                    assert!(held.output.is_empty());
                }
                evidence = "actual-private-opaque-final-allocation";
            } else if mode == "cancel_after_dispatch" {
                let other = b.clone();
                let input = request["input"].to_string();
                let call = tokio::spawn(async move {
                    other.run_skill("web".into(), "search".into(), input).await
                });
                p.wait(|r| r["skill_posts"] == 1).await;
                ok(b.cancel());
                p.get("/__test/release");
                let joined = call.await.unwrap_or_else(|_| panic!("direct join"));
                assert!(matches!(
                    joined,
                    Err(BindingError {
                        code: "cancelled",
                        ..
                    })
                ));
                evidence = "actual-public-inflight-cancellation";
            } else {
                let result = b
                    .run_skill("web".into(), "search".into(), request["input"].to_string())
                    .await;
                if let Some(code) = vector["expected_error"].as_str() {
                    match result {
                        Err(error) => {
                            assert_eq!(error.code, code);
                            assert!(!error.message.contains("synthetic-private"));
                        }
                        Ok(_) => panic!("expected direct error"),
                    }
                } else {
                    let encoded = ok(result);
                    assert_eq!(
                        serde_json::from_str::<Value>(&encoded).unwrap(),
                        vector["expected"]
                    );
                    let credentials = ok(b.export_session(true).await);
                    let snapshot: Value = serde_json::from_str(&credentials).unwrap();
                    assert_eq!(
                        snapshot["session"]["master_key"],
                        suite["account"]["master_key"]
                    );
                    assert_eq!(
                        snapshot["session"]["session_id"],
                        suite["account"]["session_id"]
                    );
                }
                evidence = "actual-public-cookie-operation";
            }
            ok(b.close().await);
        }
        let report = p.get("/__test/status");
        assert!(report["failure"].is_null());
        assert_eq!(report["skill_posts"], vector["expected_skill_posts"]);
        assert_eq!(report["downloads"], 0);
        assert_eq!(report["retention_posts"], 0);
        if mode == "pending_a_failed_b" {
            assert_eq!(report["polls"]["task_a"], 1);
            assert_eq!(report["polls"]["task_b"], 1);
        }
        outcomes
            .push(json!({"id":vector["id"],"status":"passed","evidence":evidence,"peer":report}));
    }
    assert_eq!(outcomes.len(), 18);
    println!(
        "OPENMATES_DIRECT_SKILL_CONFORMANCE={}",
        json!({"capability":"sdk.apps","language":"rust","status":"passed","fixtureSha256":fixture_hash,"results":outcomes})
    );
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn final_successful_wrapper_callback_cannot_cancel_independent_original_sdk_parent() {
    for retire in [false, true] {
        let p = Peer::new("sync");
        let b = p.bridge().await;
        let guard = Arc::new(ok(b.admit_work()));
        // The actual production encoder receives synthetic queued bytes; this
        // test makes no skill-HTTP or VM-allocation claim. Initial owner is still
        // genuinely observed, and the SDK parent is independent of WorkGuard.
        let parent = CancellationToken::new();
        let captured = parent.clone();
        let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let target = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let (count, trigger) = (calls.clone(), target.clone());
        let (admission, privacy, gate) = {
            let mut client = b.state.client.lock().await;
            ok(client.validate_session().await.map_err(BindingError::from));
            client.set_operation_cancel(parent.clone());
            client.set_private_operation_gate(Some(Arc::new(move || {
                if count.fetch_add(1, Ordering::SeqCst) + 1 == trigger.load(Ordering::SeqCst) {
                    captured.cancel();
                }
                Ok(()) // Successful policy callback, but original SDK scope retired.
            })));
            let privacy = client.options().privacy.clone();
            let gate = client.options().private_operation_gate.clone();
            (ok(client.direct_app_skill_admission().map_err(BindingError::from)), privacy, gate)
        };
        let expected = p.suite["sync_expected"].to_string();
        let mut output = DirectSkillOutput {
            state: b.state.clone(), guard: guard.clone(), admission,
            original_privacy: privacy, original_gate: gate,
            output: Zeroizing::new(expected.clone()),
        };
        let result = output.encode_checked(|text| {
            assert_eq!(text, expected);
            calls.store(0, Ordering::SeqCst);
            target.store(if retire {6} else {0}, Ordering::SeqCst);
            Ok(Zeroizing::new(text.to_owned()))
        });
        assert_eq!(calls.load(Ordering::SeqCst), 6);
        assert!(!guard.token().is_cancelled());
        assert!(work_authority(&guard).is_ok());
        assert!(output.output.is_empty());
        if retire {
            assert!(parent.is_cancelled());
            assert_eq!(result.err().map(|error| error.code), Some("cancelled"));
        } else {
            assert!(!parent.is_cancelled());
            assert_eq!(ok(result).as_str(), expected);
        }
        assert_eq!(p.get("/__test/status")["skill_posts"], 0);
        drop(output);
        ok(b.close().await);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_peer_final_wrapper_callback_order_and_count_are_preserved() {
    let p = Peer::new("sync");
    let b = p.bridge().await;
    let log = Arc::new(std::sync::Mutex::new(Vec::new()));
    let original = log.clone();
    b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(move || {
        original.lock().map_err(|_| Error::Protocol)?.push("original");
        Ok(())
    })));
    let mut output = p.prepare(&b).await;
    let current = log.clone();
    b.state.client.lock().await.set_private_operation_gate(Some(Arc::new(move || {
        current.lock().map_err(|_| Error::Protocol)?.push("current");
        Ok(())
    })));
    let encoded = ok(output.encode_checked(|text| {
        log.lock().unwrap().clear();
        Ok(Zeroizing::new(text.to_owned()))
    }));
    assert_eq!(*log.lock().unwrap(), vec!["original", "original", "current", "current", "original", "original"]);
    assert_eq!(serde_json::from_str::<Value>(&encoded).unwrap(), p.suite["sync_expected"]);
    assert!(output.output.is_empty());
    assert_eq!(p.get("/__test/status")["skill_posts"], 1);
    drop(output);
    ok(b.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_direct_admission_exists_before_first_poll_cancel_refuses_all_http_and_fresh_b_succeeds() {
    let p = Peer::new("sync");
    let b = p.bridge().await;
    let a = b.run_skill_prepare("web".into(), "search".into(), p.suite["request"]["input"].to_string());
    // Merely creating the actual bridge future registers its original authority.
    assert_eq!(b.state.work_operations.lock().unwrap().len(), 1);
    ok(b.cancel());
    assert_eq!(a.await.err().map(|error| error.code), Some("cancelled"));
    let before = p.get("/__test/status");
    assert!(before["failure"].is_null());
    assert_eq!(before["auth"], 0);
    assert_eq!(before["skill_posts"], 0);
    assert_eq!(before["downloads"], 0);
    assert_eq!(before["retention_posts"], 0);
    assert!(b.state.work_operations.lock().unwrap().is_empty());
    let output = p.prepare(&b).await;
    assert_eq!(serde_json::from_str::<Value>(&ok(output.release_json())).unwrap(), p.suite["sync_expected"]);
    assert_eq!(p.get("/__test/status")["skill_posts"], 1);
    ok(b.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn old_cancelled_unpolled_a_cannot_reset_or_cancel_b_original_opaque_output() {
    let p = Peer::new("sync");
    let b = p.bridge().await;
    let a = b.run_skill_prepare("web".into(), "search".into(), p.suite["request"]["input"].to_string());
    ok(b.cancel());
    let output_b = p.prepare(&b).await;
    let actual_b = p.get("/__test/status");
    assert_eq!(actual_b["skill_posts"], 1);
    assert_eq!(a.await.err().map(|error| error.code), Some("cancelled"));
    assert_eq!(p.get("/__test/status"), actual_b);
    assert_eq!(serde_json::from_str::<Value>(&ok(output_b.release_json())).unwrap(), p.suite["sync_expected"]);
    assert!(b.state.work_operations.lock().unwrap().is_empty());
    ok(b.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn public_direct_future_also_registers_before_poll_and_cancellation_starts_no_http() {
    let p = Peer::new("sync");
    let b = p.bridge().await;
    let pending = b.run_skill("web".into(), "search".into(), p.suite["request"]["input"].to_string());
    assert_eq!(b.state.work_operations.lock().unwrap().len(), 1);
    ok(b.cancel());
    assert_eq!(pending.await.err().map(|error| error.code), Some("cancelled"));
    let status = p.get("/__test/status");
    assert_eq!(status["auth"], 0);
    assert_eq!(status["skill_posts"], 0);
    assert!(status["failure"].is_null());
    assert!(b.state.work_operations.lock().unwrap().is_empty());
    ok(b.close().await);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
#[test]
fn unpolled_native_queue_drop_wipes_owned_input_and_retires_only_original_admission() {
    let b = ok(SessionBridge::new(r#"{"api_url":"http://127.0.0.1:1","app_url":null,"enhanced_privacy":false,"allow_private_operations":true}"#));
    let wiped = Arc::new(AtomicBool::new(false));
    let mut a = ok(b.capture_direct_skill("web".into(), "search".into(), r#"{"query":"private queued A"}"#.into()));
    a.input_json.wiped_on_drop = Some(wiped.clone());
    let original_a = a.guard.clone();
    let future = a.run();
    assert!(!wiped.load(Ordering::Acquire));
    assert_eq!(b.state.work_operations.lock().unwrap().len(), 1);
    let successor_b = ok(b.capture_direct_skill("web".into(), "search".into(), r#"{"query":"independent B"}"#.into()));
    assert_eq!(b.state.work_operations.lock().unwrap().len(), 2);
    drop(future);
    assert!(wiped.load(Ordering::Acquire));
    // The extra test-held A guard is an actual owner, so retire that too.
    drop(original_a);
    assert_eq!(b.state.work_operations.lock().unwrap().len(), 1);
    assert!(work_authority(&successor_b.guard).is_ok());
    drop(successor_b);
    assert!(b.state.work_operations.lock().unwrap().is_empty());
}
