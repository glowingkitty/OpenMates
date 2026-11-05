//! Actual authenticated work return-boundary regressions using synthetic peer.
use super::*;
use tokio::time::{Duration, timeout};
#[derive(Clone, Copy)]
enum Family {
    Tasks,
    Plans,
    Projects,
    Workflows,
}
impl Family {
    fn name(self) -> &'static str {
        match self {
            Self::Tasks => "tasks",
            Self::Plans => "plans",
            Self::Projects => "projects",
            Self::Workflows => "workflows",
        }
    }
}
async fn read(bridge: &SessionBridge, family: Family) -> Result<String> {
    match family {
        Family::Tasks => {
            bridge
                .tasks_list(TaskFilters {
                    personal: true,
                    ..Default::default()
                })
                .await
        }
        Family::Plans => {
            bridge
                .plans_list(PlanFilters {
                    personal: true,
                    ..Default::default()
                })
                .await
        }
        Family::Projects => {
            bridge
                .projects_list(ProjectFilters {
                    personal: true,
                    ..Default::default()
                })
                .await
        }
        Family::Workflows => {
            bridge
                .workflows_list(WorkflowFilters {
                    personal: true,
                    ..Default::default()
                })
                .await
        }
    }
}
struct Peer {
    child: std::process::Child,
    ready: Value,
}
impl Drop for Peer {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
impl Peer {
    fn start(family: Family) -> Self {
        use std::io::{BufRead, Read};
        let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap();
        let python =
            std::env::var("OPENMATES_SDK_CONFORMANCE_PYTHON").unwrap_or_else(|_| "python3".into());
        let directory = std::env::var_os("OPENMATES_SDK_WORK_TEST_LOG_DIR")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(std::env::temp_dir);
        let log = directory.join(format!(
            "work-return-peer-{}.stderr.log",
            uuid::Uuid::new_v4()
        ));
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let stderr = options.open(&log).expect("private work fixture stderr");
        let mut child = std::process::Command::new(python)
            .arg(root.join("tests/sdk-conformance/work_return_server.py"))
            .args(["--family", family.name(), "--identity", "rust"])
            .current_dir(root)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::piped())
            .stderr(stderr)
            .spawn()
            .expect("private work peer launch");
        let stdout = child.stdout.take().unwrap();
        let (tx, rx) = std::sync::mpsc::sync_channel(1);
        std::thread::spawn(move || {
            let mut line = String::new();
            let result = std::io::BufReader::new(stdout)
                .take(65537)
                .read_line(&mut line)
                .map(|_| line);
            let _ = tx.send(result);
        });
        let ready = match rx.recv_timeout(Duration::from_secs(2)) {
            Ok(Ok(line)) if line.len() <= 65536 => line,
            _ => {
                let _ = child.kill();
                let exit = child.wait();
                panic!(
                    "work peer bounded startup exit={exit:?}; stderr={}",
                    log.display()
                );
            }
        };
        let ready: Value = serde_json::from_str(&ready).unwrap();
        assert!(
            ready["endpoint"]
                .as_str()
                .unwrap()
                .strip_prefix("http://127.0.0.1:")
                .and_then(|port| port.parse::<u16>().ok())
                .is_some_and(|port| port > 0)
        );
        Self { child, ready }
    }
    async fn replace(&self) {
        let endpoint = self.ready["endpoint"].as_str().unwrap().to_owned();
        tokio::task::spawn_blocking(move||{
            use std::io::{Read,Write};
            let port=endpoint.strip_prefix("http://127.0.0.1:").unwrap().parse::<u16>().unwrap();
            let mut socket=std::net::TcpStream::connect_timeout(&std::net::SocketAddr::from(([127,0,0,1],port)),Duration::from_secs(1)).unwrap();socket.set_read_timeout(Some(Duration::from_secs(1))).unwrap();socket.set_write_timeout(Some(Duration::from_secs(1))).unwrap();
            let body=br#"{"op":"replace"}"#;
            write!(socket,"POST /__test/control HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",body.len()).unwrap();socket.write_all(body).unwrap();
            let mut response=Vec::new();socket.take(65536).read_to_end(&mut response).unwrap();assert!(response.starts_with(b"HTTP/1.1 200")||response.starts_with(b"HTTP/1.0 200"));
            let body=response.windows(4).position(|part|part==b"\r\n\r\n").unwrap()+4;let body:Value=serde_json::from_slice(&response[body..]).unwrap();assert_eq!(body["replaced"],true);
        }).await.unwrap();
    }
}
struct Resume(Arc<WorkReturnBarrier>);
impl Drop for Resume {
    fn drop(&mut self) {
        self.0.resume.notify_one();
    }
}
async fn lifecycle_case(family: Family, action: &str) {
    let peer = tokio::task::spawn_blocking(move || Peer::start(family))
        .await
        .unwrap();
    let bridge=SessionBridge::new(&json!({"api_url":peer.ready["endpoint"],"app_url":"https://app.example.invalid","enhanced_privacy":false,"allow_private_operations":false}).to_string()).unwrap_or_else(|_|panic!("bridge"));
    bridge
        .import_session(peer.ready["initial_session"].to_string())
        .await
        .unwrap_or_else(|_| panic!("initial explicit session"));
    bridge
        .validate_session()
        .await
        .unwrap_or_else(|_| panic!("initial authenticated identity"));
    let initial_owner = bridge.state.client.lock().await.user()["id"]
        .as_str()
        .unwrap()
        .to_owned();
    let barrier = Arc::new(WorkReturnBarrier::default());
    let _resume = Resume(barrier.clone());
    *barrier.expected_private_marker.lock().unwrap() = Some(
        peer.ready["initial_private_marker"]
            .as_str()
            .unwrap()
            .to_owned(),
    );
    *bridge.state.work_return_barrier.lock().unwrap() = Some(barrier.clone());
    let caller = bridge.clone();
    let pending = tokio::spawn(async move { read(&caller, family).await });
    barrier.completed.notified().await;
    assert!(
        barrier.completed_success.load(Ordering::Acquire),
        "real private work read must complete before lifecycle race"
    );
    assert!(
        barrier.completed_private_marker.load(Ordering::Acquire),
        "completed result contains independently seeded private account data"
    );
    assert!(
        bridge.state.client.try_lock().is_ok(),
        "Client lane released before caller return"
    );
    assert_eq!(
        bridge.state.work_operations.lock().unwrap().len(),
        1,
        "completed work remains registered until final caller fence"
    );
    if matches!(family, Family::Tasks) && action == "cancel" {
        let capacity = (0..31)
            .map(|_| {
                bridge
                    .admit_work()
                    .unwrap_or_else(|_| panic!("remaining bounded admission"))
            })
            .collect::<Vec<_>>();
        assert_eq!(bridge.state.work_operations.lock().unwrap().len(), 32);
        assert_eq!(
            read(&bridge, family)
                .await
                .expect_err("33rd work operation must be refused")
                .code,
            "conflict"
        );
        drop(capacity);
        assert_eq!(bridge.state.work_operations.lock().unwrap().len(), 1);
    }
    match action {
        "cancel" => bridge.cancel().unwrap_or_else(|_| panic!("cancel pending")),
        "logout" => bridge
            .logout()
            .await
            .unwrap_or_else(|_| panic!("actual HTTP logout")),
        "replace" => {
            peer.replace().await;
            bridge
                .import_session(peer.ready["replacement_session"].to_string())
                .await
                .unwrap_or_else(|_| panic!("distinct account replacement"));
        }
        _ => bridge
            .import_session(peer.ready["initial_session"].to_string())
            .await
            .unwrap_or_else(|_| panic!("same account snapshot reset")),
    }
    barrier.resume.notify_one();
    let result = pending.await.unwrap();
    assert_eq!(
        result
            .expect_err("old private work output must fail closed")
            .code,
        "cancelled"
    );
    assert!(
        barrier.rejected_output_wiped.load(Ordering::Acquire),
        "actual rejected private result wiped before caller observes error"
    );
    assert!(
        bridge.state.work_operations.lock().unwrap().is_empty(),
        "work admission released exactly after result rejection"
    );
    if action == "replace" {
        bridge
            .validate_session()
            .await
            .unwrap_or_else(|_| panic!("replacement authenticated identity remains usable"));
        let replacement_owner = bridge.state.client.lock().await.user()["id"]
            .as_str()
            .unwrap()
            .to_owned();
        assert_ne!(
            replacement_owner, initial_owner,
            "replacement is a distinct authenticated account"
        );
        let fresh = read(&bridge, family)
            .await
            .unwrap_or_else(|_| panic!("replacement legitimate typed read"));
        assert!(fresh.contains(peer.ready["replacement_private_marker"].as_str().unwrap()));
        assert!(
            !fresh.contains(peer.ready["initial_private_marker"].as_str().unwrap()),
            "old account plaintext never replaces new account data"
        );
        assert!(bridge.state.work_operations.lock().unwrap().is_empty());
    }
    bridge.close().await.unwrap_or_else(|_| panic!("close"));
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_private_tasks_plans_projects_workflows_returns_are_fenced_after_join() {
    for family in [
        Family::Tasks,
        Family::Plans,
        Family::Projects,
        Family::Workflows,
    ] {
        for action in ["cancel", "reset", "logout", "replace"] {
            timeout(Duration::from_secs(5), lifecycle_case(family, action))
                .await
                .unwrap_or_else(|_| {
                    panic!(
                        "bounded actual work return case: {} {action}",
                        family.name()
                    )
                });
        }
    }
}
