//! Actual executable, real explicit encrypted-vault unlock, loopback HTTP and
//! production timer. No fake auth, transport, retry clock or application sidecar.
//! Linux CI uses util-linux script solely as a terminal fixture for the prompt.
#![cfg(target_os = "linux")]
use openmates_tui_native::storage::{Session, Store};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, VecDeque},
    process::Stdio,
    sync::{Arc, Mutex, atomic::{AtomicU8, Ordering}},
    time::{Duration, Instant},
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;
const PASSWORD: &str = "synthetic reminders fixture vault";
struct Fixture {
    state: tempfile::TempDir,
    api: String,
    stop: CancellationToken,
    task: tokio::task::JoinHandle<()>,
    requests: Arc<Mutex<Vec<String>>>,
    first: Arc<tokio::sync::Notify>,
    phase: Arc<AtomicU8>,
}
impl Fixture {
    async fn new(responses: Vec<(u16, &str)>) -> Self {
        // Own synthetic response strings before spawning; shared raw-wire fixture
        // bodies remain unmodified and no production parser is duplicated here.
        let responses = responses.into_iter().map(|(status, body)| (status, body.to_owned())).collect::<Vec<_>>();
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let mut state_builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            state_builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let state = state_builder.tempdir().unwrap();
        {
            let store = Store::encrypted_vault(state.path().to_path_buf()).unwrap();
            store
                .save_session(
                    &Session {
                        api_url: api.clone(),
                        session_id: "synthetic-reminders-session".into(),
                        cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture".into())]),
                        ws_token: None,
                        master_key: Zeroizing::new([3; 32]),
                        hashed_email: "synthetic-owner".into(),
                        user_email_salt: String::new(),
                        email_encryption_key: None,
                        created_at: 1,
                        paired_session_expires_at: None,
                        active_team_id: Some("00000000-0000-4000-8000-000000000001".into()),
                    },
                    Some(PASSWORD),
                )
                .unwrap();
        }
        let stop = CancellationToken::new();
        let token = stop.clone();
        let requests = Arc::new(Mutex::new(Vec::new()));
        let captured = requests.clone();
        let first = Arc::new(tokio::sync::Notify::new());
        let notified = first.clone();
        let phase = Arc::new(AtomicU8::new(0));
        let server_phase = phase.clone();
        let task = tokio::spawn(async move {
            let mut responses: VecDeque<_> = responses.into();
            let mut rotated = false;
            loop {
                let (mut socket, _) =
                    tokio::select! {_=token.cancelled()=>return, v=listener.accept()=>v.unwrap()};
                server_phase.store(1, Ordering::SeqCst); // accepted, reading original request
                let request = tokio::time::timeout(Duration::from_secs(10), async {
                    let mut bytes = Vec::new();
                    let mut chunk = [0u8; 4096];
                    loop {
                        let n = socket.read(&mut chunk).await.unwrap();
                        assert!(n > 0);
                        bytes.extend_from_slice(&chunk[..n]);
                        assert!(bytes.len() <= 8192);
                        if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
                            let head = String::from_utf8_lossy(&bytes[..end]);
                            let len = head
                                .lines()
                                .filter_map(|v| v.split_once(':'))
                                .find(|(k, _)| k.eq_ignore_ascii_case("content-length"))
                                .map(|(_, v)| v.trim().parse::<usize>().unwrap())
                                .unwrap_or(0);
                            if bytes.len() >= end + 4 + len {
                                return String::from_utf8(bytes).unwrap();
                            }
                        }
                    }
                })
                .await
                .unwrap();
                server_phase.store(2, Ordering::SeqCst); // original request complete
                let settings = request.starts_with("GET /v1/settings/reminders HTTP/1.1\r\n");
                let (status, body) = if settings {
                    let head = request.to_ascii_lowercase();
                    assert!(!head.contains("authorization:"));
                    assert!(!head.contains("team_id="));
                    assert!(!head.contains("x-team"));
                    assert!(!head.contains("content-length:"));
                    assert!(!head.contains("content-type:"));
                    assert!(head.contains(if rotated {
                        "auth_refresh_token=rotated"
                    } else {
                        "auth_refresh_token=fixture"
                    }));
                    responses
                        .pop_front()
                        .expect("no retry or request beyond fixed response vector")
                } else {
                    assert!(request.starts_with("POST /v1/auth/session HTTP/1.1\r\n"));
                    (
                        200,
                        r#"{"success":true,"ws_token":"synthetic-ws","user":{"id":"synthetic-owner","name":"Synthetic"}}"#.to_owned(),
                    )
                };
                captured.lock().unwrap().push(request);
                let header = if settings {
                    rotated = true;
                    "Set-Cookie: auth_refresh_token=rotated; Path=/; HttpOnly\r\n"
                } else {
                    ""
                };
                socket.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\n{header}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
                server_phase.store(3, Ordering::SeqCst); // actual response write completed
                if settings {
                    notified.notify_one();
                }
            }
        });
        Self {
            state,
            api,
            stop,
            task,
            requests,
            first,
            phase,
        }
    }
    async fn run(&self, json: bool, cancel_wait: bool) -> (std::process::ExitStatus, String) {
        self.run_with_vector(json, cancel_wait, "non-numeric").await
    }
    async fn run_with_vector(&self, json: bool, cancel_wait: bool, vector: &str) -> (std::process::ExitStatus, String) {
        // Fixed synthetic fixture IDs only; never log wire bodies, output or secrets.
        assert!(vector.len() <= 64 && vector.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-'));
        eprintln!("settings_fixture vector={vector} json={json} stage=spawn");
        fn quote(value: &str) -> String {
            format!("'{}'", value.replace('\'', "'\\''"))
        }
        let shell = format!(
            "stty -echo; /usr/bin/tty; exec {} --api-url {} --state-dir {} --encrypted-vault settings reminders list{}",
            quote(env!("CARGO_BIN_EXE_openmates")),
            quote(&self.api),
            quote(self.state.path().to_str().unwrap()),
            if json { " --json" } else { "" }
        );
        let mut cmd = tokio::process::Command::new("/usr/bin/script");
        cmd.env_clear()
            .env("PATH", "/usr/bin:/bin")
            .env("HOME", self.state.path())
            .env("XDG_CONFIG_HOME", self.state.path())
            .env("XDG_DATA_HOME", self.state.path())
            .env("XDG_CACHE_HOME", self.state.path())
            .env("LANG", "C.UTF-8")
            .env("TERM", "dumb")
            .args(["--quiet", "--return", "--command", &shell, "/dev/null"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        let mut child = cmd.spawn().unwrap();
        let mut stdin = child.stdin.take().unwrap();
        let mut stdout = child.stdout.take().unwrap();
        let stderr = child.stderr.take().unwrap();
        let err = tokio::spawn(async move {
            let mut bytes = Vec::new();
            stderr.take(8193).read_to_end(&mut bytes).await.unwrap();
            assert!(bytes.len() <= 8192);
            bytes
        });
        tokio::time::timeout(Duration::from_secs(20), async {
            let mut prefix = Vec::new();
            while !prefix.ends_with(b"Credential vault passphrase: ") {
                let byte = stdout.read_u8().await.unwrap();
                prefix.push(byte);
                assert!(prefix.len() < 4096);
            }
            // The terminal fixture supplies its own exact PTY endpoint before
            // exec. Inspect actual terminal flags at the native readiness label,
            // before sending any synthetic secret. This never changes the mode.
            let prefix = String::from_utf8(prefix).unwrap();
            let pty = prefix.lines().next().unwrap().trim_end_matches('\r');
            let suffix = pty.strip_prefix("/dev/pts/").expect("original fixture PTY");
            assert!(!suffix.is_empty() && suffix.bytes().all(|b| b.is_ascii_digit()));
            let mode = tokio::time::timeout(Duration::from_secs(2),
                tokio::process::Command::new("/usr/bin/stty")
                    .env_clear().env("LANG", "C")
                    .args(["--file", pty, "--all"])
                    .kill_on_drop(true).output()).await.expect("bounded original PTY flags").unwrap();
            assert!(mode.status.success() && mode.stderr.is_empty());
            assert!(mode.stdout.len() <= 8192);
            let mode = String::from_utf8(mode.stdout).unwrap();
            let flags = mode.split_whitespace().map(|flag| flag.trim_end_matches(';')).collect::<Vec<_>>();
            let echo_off = flags.contains(&"-echo");
            let canonical_off = flags.contains(&"-icanon");
            eprintln!("settings_fixture vector={vector} json={json} stage=prompt-ready echo_off={echo_off} canonical_off={canonical_off}");
            assert!(echo_off && canonical_off, "native secret prompt must be raw/no-echo before its label");
            stdin
                .write_all(format!("{PASSWORD}\r").as_bytes())
                .await
                .unwrap();
            stdin.flush().await.unwrap();
            eprintln!("settings_fixture vector={vector} json={json} stage=passphrase-sent");
        })
        .await
        .expect("bounded real vault prompt");
        let output = tokio::spawn(async move {
            let mut bytes = Vec::new();
            stdout
                .take(128 * 1024 + 1)
                .read_to_end(&mut bytes)
                .await
                .unwrap();
            assert!(bytes.len() <= 128 * 1024);
            String::from_utf8(bytes).unwrap().replace("\r\n", "\n")
        });
        if cancel_wait {
            tokio::time::timeout(Duration::from_secs(20), self.first.notified())
                .await
                .unwrap();
            stdin.write_all(&[3]).await.unwrap();
            stdin.flush().await.unwrap();
        }
        let bound = if cancel_wait { 10 } else { 100 };
        eprintln!("settings_fixture vector={vector} json={json} stage=child-wait bound={bound}");
        let waited = tokio::time::timeout(Duration::from_secs(bound), child.wait()).await;
        if waited.is_err() {
            let (auth_requests, settings_requests) = {
                let requests = self.requests.lock().unwrap();
                (requests.iter().filter(|v| v.starts_with("POST /v1/auth/session ")).count(),
                 requests.iter().filter(|v| v.starts_with("GET /v1/settings/reminders ")).count())
            };
            let child_state = match child.try_wait() {
                Ok(Some(status)) => if status.success() { "exited-success" } else { "exited-failure" },
                Ok(None) => "running",
                Err(_) => "status-unavailable",
            };
            eprintln!("settings_fixture vector={vector} json={json} stage=child-timeout child={child_state} server_phase={} auth_requests={auth_requests} settings_requests={settings_requests} server_finished={} output_finished={} stderr_finished={}",
                self.phase.load(Ordering::SeqCst), self.task.is_finished(), output.is_finished(), err.is_finished());
        }
        // Preserve the original deadline, panic and kill-on-drop cleanup after diagnostics.
        let status = waited.expect("bounded actual native command").unwrap();
        eprintln!("settings_fixture vector={vector} json={json} stage=child-exited success={}", status.success());
        drop(stdin);
        let output = output.await.unwrap();
        let output = output.strip_prefix('\n').unwrap_or(&output).to_owned();
        assert!(err.await.unwrap().is_empty());
        assert!(!output.contains(PASSWORD));
        (status, output)
    }
    fn settings_count(&self) -> usize {
        self.requests
            .lock()
            .unwrap()
            .iter()
            .filter(|v| v.starts_with("GET /v1/settings/reminders "))
            .count()
    }
    async fn finish(self) {
        self.stop.cancel();
        self.task.await.unwrap();
    }
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust,sdk.encryption.local-only
#[tokio::test]
async fn actual_command_retains_raw_json_encrypted_extensions_scalar_and_malformed_defaults() {
    for (body, expected) in [
        (
            r#"{"encrypted_metadata":"opaque","reminders":[{"encrypted_content":"cipher","id":"r1"}],"unknown_future":7}"#,
            json!({"encrypted_metadata":"opaque","reminders":[{"encrypted_content":"cipher","id":"r1"}],"unknown_future":7}),
        ),
        ("null", Value::Null),
        ("[1,false]", json!([1, false])),
        ("malformed", json!({})),
    ] {
        let f = Fixture::new(vec![(200, body)]).await;
        let (status, text) = f.run(true, false).await;
        assert_eq!(status.code(), Some(0));
        assert_eq!(serde_json::from_str::<Value>(&text).unwrap(), expected);
        assert_eq!(f.settings_count(), 1);
        f.finish().await;
    }
    // Core captures the wire order; CLI consumes its view rather than parsing
    // or sorting the response. Exact JSON and ordinary expectations are from TS.
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/settings-reminders-root-order.json")).unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let body: &'static str = match case["id"].as_str().unwrap() {
            "non-index-insertion" => r#"{"z":1,"a":2}"#,
            "numeric-index-and-duplicate" => r#"{"z":1,"10":10,"2":2,"a":3,"z":4,"01":5}"#,
            "billing-unknown-root-order" => r#"{"z":1,"payment_tier":"free","invoices":[],"a":2}"#,
            _ => panic!("unexpected root-order fixture"),
        };
        assert_eq!(body, case["wire_body"].as_str().unwrap());
        for json in [true, false] {
            let f = Fixture::new(vec![(200, body)]).await;
            let (status, text) = f.run(json, false).await;
            assert_eq!(status.code(), Some(0));
            assert_eq!(
                text,
                case[if json { "json" } else { "ordinary" }]
                    .as_str()
                    .unwrap(),
                "{}",
                case["id"]
            );
            assert_eq!(f.settings_count(), 1);
            f.finish().await;
        }
    }
    let f = Fixture::new(vec![(200, "[]")]).await;
    let (status, text) = f.run(false, false).await;
    assert!(status.success());
    assert_eq!(text, "(empty list)\n");
    f.finish().await;
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust
#[tokio::test]
async fn actual_command_displays_typed_http_failure_without_response_body() {
    for json in [true, false] {
        let f = Fixture::new(vec![(
            500,
            r#"{"detail":"private-error-body-not-displayable"}"#,
        )])
        .await;
        let (status, text) = f.run(json, false).await;
        assert_eq!(status.code(), Some(1));
        if json {
            assert_eq!(
                serde_json::from_str::<Value>(&text).unwrap(),
                json!({"error":{"code":"command_failed","message":"Settings GET failed with HTTP 500"}})
            );
        } else {
            assert_eq!(text, "Error: Settings GET failed with HTTP 500\n");
        }
        assert!(!text.contains("private-error-body"));
        assert_eq!(f.settings_count(), 1);
        f.finish().await;
    }
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust
#[tokio::test]
async fn actual_command_uses_production_61000ms_wait_and_only_one_retry() {
    for last in [200, 429] {
        let f = Fixture::new(vec![(429, "{}"), (last, r#"{"reminders":[]}"#)]).await;
        let start = Instant::now();
        let (status, text) = f.run(true, false).await;
        assert!(start.elapsed() >= Duration::from_millis(61_000));
        if last == 200 {
            assert!(status.success());
            assert_eq!(
                serde_json::from_str::<Value>(&text).unwrap(),
                json!({"reminders":[]})
            );
        } else {
            assert_eq!(status.code(), Some(1));
            assert_eq!(
                serde_json::from_str::<Value>(&text).unwrap(),
                json!({"error":{"code":"command_failed","message":"Settings GET failed with HTTP 429"}})
            );
        }
        assert_eq!(f.settings_count(), 2);
        f.finish().await;
    }
}
// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust
#[tokio::test]
async fn actual_ctrl_c_cancels_production_retry_without_second_request_or_success_output() {
    let f = Fixture::new(vec![(429, "{}")]).await;
    let (status, text) = f.run(true, true).await;
    assert_eq!(status.code(), Some(130));
    assert!(!text.contains("\"reminders\""));
    assert_eq!(f.settings_count(), 1);
    let value = serde_json::from_str::<Value>(text.trim_start_matches("^C")).unwrap();
    assert_eq!(value["error"]["code"], "cancelled");
    {
        let store = Store::encrypted_vault(f.state.path().to_path_buf()).unwrap();
        let saved = store.load_session(Some(PASSWORD)).unwrap().unwrap();
        assert_eq!(
            saved.cookies.get("auth_refresh_token").map(String::as_str),
            Some("rotated")
        );
    }
    f.finish().await;
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust,sdk.encryption.local-only
#[tokio::test]
async fn actual_command_refuses_shared_valid_json_limits_without_empty_success_or_private_diagnostics() {
    let fixture: Value = serde_json::from_str(include_str!(
        "fixtures/session-settings-reminders-read.json"
    )).unwrap();
    assert_eq!(fixture["cases"].as_array().unwrap().len(), 28);
    for id in ["valid-depth129-refuses", "valid-numeric-range-refuses"] {
        let case = fixture["cases"].as_array().unwrap().iter().find(|case| case["id"] == id).unwrap();
        let body = case["responses"][0]["body"].as_str().unwrap();
        let message = case["expected"]["message"].as_str().unwrap();
        assert_eq!(case["expected"]["ok"], false);
        assert_eq!(case["expected"]["http_status"], Value::Null);
        for json in [true, false] {
            let f = Fixture::new(vec![(200, body)]).await;
            let (status, text) = f.run(json, false).await;
            assert_eq!(status.code(), Some(1), "{id}");
            if json {
                assert_eq!(
                    serde_json::from_str::<Value>(&text).unwrap(),
                    json!({"error":{"code":"settings_json_unsupported","message":message}}),
                    "{id}"
                );
            } else {
                assert_eq!(text, format!("Error: {message}\n"), "{id}");
            }
            assert!(!text.contains(body));
            assert!(!text.contains("recursion limit"));
            assert!(!text.contains("number out of range"));
            assert_eq!(f.settings_count(), 1);
            // Response-header cookie bookkeeping still persists on decode refusal.
            {
                let store = Store::encrypted_vault(f.state.path().to_path_buf()).unwrap();
                let saved = store.load_session(Some(PASSWORD)).unwrap().unwrap();
                assert_eq!(saved.cookies.get("auth_refresh_token").map(String::as_str), Some("rotated"));
            }
            f.finish().await;
        }
    }
}

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity,cli.runtime.native-rust,sdk.encryption.local-only
#[tokio::test]
async fn actual_command_matches_original_node_number_oracles_in_json_and_ordinary_output() {
    let fixture: Value = serde_json::from_str(include_str!("fixtures/settings-reminders-numeric.json")).unwrap();
    assert_eq!(fixture["cases"].as_array().unwrap().len(), 10);
    for case in fixture["cases"].as_array().unwrap() {
        let body = case["wire_body"].as_str().unwrap();
        for json in [true, false] {
            let f = Fixture::new(vec![(200, body)]).await;
            let (status, text) = f.run_with_vector(json, false, case["id"].as_str().unwrap()).await;
            assert_eq!(status.code(), Some(0), "{}", case["id"]);
            assert_eq!(text, case[if json { "json" } else { "ordinary" }].as_str().unwrap(), "{}", case["id"]);
            assert_eq!(f.settings_count(), 1);
            f.finish().await;
        }
    }
}
