//! PRIVATE UNRUN: actual detached source transaction post-join regressions.
//! Requires the separately owned source-authoring synthetic peer and SDK patch.
use super::*;
use tokio::time::{Duration, timeout};
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
        let fixture = root.join("tests/sdk-conformance/fixtures/session-project-sources.json");
        let fixture_json: Value =
            serde_json::from_slice(&std::fs::read(&fixture).unwrap()).unwrap();
        let python =
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into());
        let directory = std::env::var_os("OPENMATES_SDK_SOURCE_TEST_LOG_DIR")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(std::env::temp_dir);
        let log = directory.join(format!(
            "project-source-peer-{}.stderr.log",
            uuid::Uuid::new_v4()
        ));
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let stderr = options.open(&log).expect("private fixture stderr");
        let mut child = std::process::Command::new(python)
            .arg(root.join("tests/sdk-conformance/session_project_sources_server.py"))
            .arg("--fixture")
            .arg(fixture)
            .args([
                "--vector",
                "personal-create-full-metadata",
                "--identity",
                "rust",
            ])
            .current_dir(root)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::piped())
            .stderr(stderr)
            .spawn()
            .expect("private source peer launch");
        let stdout = child.stdout.take().unwrap();
        let (tx, rx) = std::sync::mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut line = String::new();
            let result = std::io::BufReader::new(stdout)
                .read_line(&mut line)
                .map(|_| line);
            let _ = tx.send(result);
        });
        let ready = match rx.recv_timeout(Duration::from_secs(2)) {
            Ok(Ok(line)) => line,
            _ => {
                let _ = child.kill();
                let exit = child.wait();
                panic!(
                    "source peer bounded startup exit={exit:?}; stderr={}",
                    log.display()
                );
            }
        };
        let ready: Value = serde_json::from_str(&ready).unwrap();
        let endpoint = ready["endpoint"].as_str().unwrap().to_owned();
        assert!(
            endpoint
                .strip_prefix("http://127.0.0.1:")
                .and_then(|port| port.parse::<u16>().ok())
                .is_some_and(|port| port > 0)
        );
        Self {
            child,
            endpoint,
            suite: fixture_json["capabilities"]["session.project-source-authoring.v1"].clone(),
        }
    }
    fn session(&self, replacement: bool) -> String {
        let account = &self.suite["account"];
        json!({"api_url":self.endpoint,"session_id":if replacement{"synthetic-replacement-session"}else{account["session_id"].as_str().unwrap()},"cookies":{"auth_refresh_token":account["cookie"]},"ws_token":"synthetic-source-ws","master_key":if replacement{"W1tbW1tbW1tbW1tbW1tbW1tbW1tbW1tbW1tbW1tbW1s="}else{account["master_key"].as_str().unwrap()},"hashed_email":if replacement{"synthetic-replacement-email"}else{"synthetic-source-email"},"user_email_salt":"synthetic-salt","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null}).to_string()
    }
    fn input(&self) -> ProjectSourceCreate {
        let vector = self.suite["vectors"]
            .as_array()
            .unwrap()
            .iter()
            .find(|vector| vector["id"] == "personal-create-full-metadata")
            .unwrap();
        serde_json::from_value(vector["cases"][0]["input"].clone())
            .unwrap_or_else(|_| panic!("actual fixture input"))
    }
}
struct Resume(Arc<WorkReturnBarrier>);
impl Drop for Resume {
    fn drop(&mut self) {
        self.0.resume.notify_one();
    }
}
// Preserve only the fixed public classification of an already-failed baseline.
// No private output, error message, JSON or Debug representation is emitted.
fn diagnose_source_baseline_failure(error: &BindingError) -> ! {
    match error.code {
        "invalid_argument" => panic!("source-lifecycle-diag phase=baseline_result code=invalid_argument"),
        "crypto" => panic!("source-lifecycle-diag phase=baseline_result code=crypto"),
        "authentication" => panic!("source-lifecycle-diag phase=baseline_result code=authentication"),
        "two_factor_required" => panic!("source-lifecycle-diag phase=baseline_result code=two_factor_required"),
        "signup_required" => panic!("source-lifecycle-diag phase=baseline_result code=signup_required"),
        "unavailable" => panic!("source-lifecycle-diag phase=baseline_result code=unavailable"),
        "locked" => panic!("source-lifecycle-diag phase=baseline_result code=locked"),
        "offline" => panic!("source-lifecycle-diag phase=baseline_result code=offline"),
        "forbidden" => panic!("source-lifecycle-diag phase=baseline_result code=forbidden"),
        "expired" => panic!("source-lifecycle-diag phase=baseline_result code=expired"),
        "cancelled" => panic!("source-lifecycle-diag phase=baseline_result code=cancelled"),
        "io" => panic!("source-lifecycle-diag phase=baseline_result code=io"),
        "protocol" => panic!("source-lifecycle-diag phase=baseline_result code=protocol"),
        "conflict" => panic!("source-lifecycle-diag phase=baseline_result code=conflict"),
        _ => panic!("source-lifecycle-diag phase=baseline_result code=unclassified"),
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_source_completion_is_fenced_after_join_before_foreign_return() {
    timeout(Duration::from_secs(12),async{
        for action in ["cancel","reset","logout","identity-replacement"]{
            let peer=tokio::task::spawn_blocking(Peer::start).await.unwrap();
            let bridge=SessionBridge::new(&json!({"api_url":peer.endpoint,"app_url":"https://app.example.invalid","enhanced_privacy":false,"allow_private_operations":false}).to_string()).unwrap_or_else(|_|panic!("bridge"));
            bridge.import_session(peer.session(false)).await.unwrap_or_else(|_|panic!("session import"));
            let barrier=Arc::new(WorkReturnBarrier::default());let _resume=Resume(barrier.clone());
            *bridge.state.work_return_barrier.lock().unwrap()=Some(barrier.clone());
            let caller=bridge.clone();let input=peer.input();let project=peer.suite["project_id"].as_str().unwrap().to_owned();
            let pending=tokio::spawn(async move{caller.projects_create_source(project,input,ProjectFilters{personal:true,..Default::default()}).await});
            barrier.completed.notified().await;
            if !barrier.completed_success.load(Ordering::Acquire) {
                // The original failed transaction is already joined. Release its
                // existing test barrier and classify that SAME result before any
                // intentional lifecycle revocation can mask its public error.
                barrier.resume.notify_one();
                match pending.await {
                    Ok(Err(error)) => diagnose_source_baseline_failure(&error),
                    Ok(Ok(mut unexpected)) => {
                        zeroize::Zeroize::zeroize(&mut unexpected);
                        panic!("source-lifecycle-diag phase=baseline_result code=unexpected_success");
                    }
                    Err(_) => panic!("source-lifecycle-diag phase=baseline_result code=join_failure"),
                }
            }
            assert!(barrier.completed_success.load(Ordering::Acquire),"real encrypted source mutation must complete successfully before lifecycle race");
            assert!(bridge.state.client.try_lock().is_ok(),"transaction has released Client before caller continuation");
            assert_eq!(bridge.state.work_operations.lock().unwrap().len(),1,"completed source operation stays registered through post-join fence");
            match action{
                "cancel"=>bridge.cancel().unwrap_or_else(|_|panic!("cancel")),
                "logout"=>bridge.logout().await.unwrap_or_else(|_|panic!("actual logout")),
                "identity-replacement"=>bridge.import_session(peer.session(true)).await.unwrap_or_else(|_|panic!("replace identity")),
                _=>bridge.import_session(peer.session(false)).await.unwrap_or_else(|_|panic!("reset identity")),
            }
            barrier.resume.notify_one();
            let result=pending.await.unwrap();assert_eq!(result.expect_err("old private source output must be rejected").code,"cancelled");
            assert!(barrier.rejected_output_wiped.load(Ordering::Acquire),"actual completed private buffer must be wiped before rejection");
            assert!(bridge.state.work_operations.lock().unwrap().is_empty(),"release registration only after caller fence");
            if action=="identity-replacement"{
                let current=bridge.export_session(true).await.unwrap_or_else(|_|panic!("explicit test export"));let current:Value=serde_json::from_str(&current).unwrap();
                assert_eq!(current["session"]["session_id"],"synthetic-replacement-session");
            }
            bridge.close().await.unwrap_or_else(|_|panic!("close"));
        }
    }).await.expect("bounded actual source join lifecycle races");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[test]
fn rejected_source_encoded_output_is_wiped_before_release() {
    let bridge=SessionBridge::new(r#"{"api_url":"https://example.invalid","app_url":null,"enhanced_privacy":false,"allow_private_operations":false}"#).unwrap_or_else(|_|panic!("bridge"));
    let guard = bridge.admit_work().unwrap_or_else(|_| panic!("admit"));
    guard.token.cancel();
    let mut encoded = Zeroizing::new("synthetic-private-metadata".to_owned());
    assert_eq!(
        release_work_output(&guard, &mut encoded)
            .err()
            .unwrap()
            .code,
        "cancelled"
    );
    assert!(encoded.is_empty());
}
