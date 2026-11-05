//! Actual Rust executable + loopback HTTP + real encrypted Project-name fixture.
//! AUTHORED UNRUN; no real account/backend or provider/inference acceptance claim.
use aes_gcm::{Aes256Gcm, KeyInit, Nonce, aead::Aead};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::{
    sync::{
        Arc, Mutex,
        atomic::{AtomicU8, Ordering},
    },
    time::Duration,
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio_util::sync::CancellationToken;
const PROJECT: &str = "bbaaccdd-1111-4111-8111-aabbccddeeff";
fn key_credential() -> String {
    format!("sk-api-{}.{}", "b".repeat(32), "s".repeat(32))
}
fn encrypted(text: &str) -> String {
    openmates_sdk::crypto::encrypt_combined(text, &[8; 32]).unwrap()
}
fn project() -> Value {
    json!({"project_id":PROJECT,"encrypted_name":encrypted("Fixture Project"),"encrypted_project_key":"unused-limited-grant-wrapper","key_wrappers":[],"hashed_team_id":null})
}
fn grant_session() -> Value {
    let (salt, iv) = ([5u8; 16], [4u8; 12]);
    let mut wrapping = [0u8; 32];
    pbkdf2::pbkdf2_hmac::<sha2::Sha256>("s".repeat(32).as_bytes(), &salt, 100_000, &mut wrapping);
    let ciphertext = Aes256Gcm::new_from_slice(&wrapping)
        .unwrap()
        .encrypt(Nonce::from_slice(&iv), [8u8; 32].as_slice())
        .unwrap();
    zeroize::Zeroize::zeroize(&mut wrapping);
    json!({"resource_key_grants":[{"resource_type":"project","resource_id":PROJECT,"salt":STANDARD.encode(salt),"key_iv":STANDARD.encode(iv),"encrypted_key":STANDARD.encode(ciphertext)}]})
}
fn source_rows() -> Vec<Value> {
    vec![
        json!({"source_id":"source-one","source_type":"remote_folder","encrypted_display_name":encrypted("Remote folder"),"encrypted_metadata":"invalid encrypted metadata must remain opaque","capabilities":["read","search"],"status":"connected","ownership_label":"Attached by you","created_at":7,"unknown_future":"must-not-output"}),
        json!({"source_id":"source-two","source_type":"local_folder","encrypted_display_name":null,"encrypted_metadata":"invalid but irrelevant"}),
    ]
}
struct Fixture {
    state: tempfile::TempDir,
    api: String,
    mode: Arc<AtomicU8>,
    requests: Arc<Mutex<Vec<String>>>,
    stop: CancellationToken,
    task: tokio::task::JoinHandle<()>,
}
impl Fixture {
    async fn new() -> Self {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let stop = CancellationToken::new();
        let token = stop.clone();
        let requests = Arc::new(Mutex::new(Vec::new()));
        let captured = requests.clone();
        let mode = Arc::new(AtomicU8::new(0));
        let selected = mode.clone();
        let project = project();
        let session = grant_session();
        let sources = source_rows();
        let task = tokio::spawn(async move {
            loop {
                let (mut socket, _) = tokio::select! {_=token.cancelled()=>break,accepted=listener.accept()=>accepted.unwrap()};
                let mut bytes = Vec::new();
                loop {
                    let mut chunk = [0u8; 4096];
                    let n = socket.read(&mut chunk).await.unwrap();
                    assert!(n > 0);
                    bytes.extend_from_slice(&chunk[..n]);
                    assert!(bytes.len() <= 64 * 1024);
                    if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
                        let head = String::from_utf8_lossy(&bytes[..end]).to_ascii_lowercase();
                        let size = head
                            .lines()
                            .find_map(|line| {
                                line.strip_prefix("content-length:")
                                    .and_then(|value| value.trim().parse::<usize>().ok())
                            })
                            .unwrap_or(0);
                        if bytes.len() >= end + 4 + size {
                            break;
                        }
                    }
                }
                let request = String::from_utf8(bytes).unwrap();
                let route = request
                    .lines()
                    .next()
                    .unwrap()
                    .split_whitespace()
                    .nth(1)
                    .unwrap()
                    .split('?')
                    .next()
                    .unwrap();
                let (status, value) = if route == format!("/v1/projects/{PROJECT}") {
                    (200, json!({"project":project}))
                } else if route == "/v1/sdk/session" {
                    (200, session.clone())
                } else if route == format!("/v1/projects/{PROJECT}/sources") {
                    match selected.load(Ordering::SeqCst) {
                        0 => (200, json!({"sources":sources})),
                        1 => (200, json!({"sources":[]})),
                        _ => (403, json!({"detail":"synthetic source denial"})),
                    }
                } else {
                    panic!("unexpected fixture route");
                };
                captured.lock().unwrap().push(request);
                let body = value.to_string();
                let response = format!(
                    "HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                socket.write_all(response.as_bytes()).await.unwrap();
            }
        });
        // Explicit API-key startup still verifies an existing profile root's
        // privacy before choosing its separate key namespace.
        let mut state_builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            state_builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        Self {
            state: state_builder.tempdir().unwrap(),
            api,
            mode,
            requests,
            stop,
            task,
        }
    }
    async fn run(&self, json_output: bool, selector: Option<&str>) -> std::process::Output {
        self.run_with_extra(json_output, selector, &[]).await
    }
    async fn run_with_extra(&self, json_output: bool, selector: Option<&str>, extra: &[&str]) -> std::process::Output {
        let mut command = tokio::process::Command::new(env!("CARGO_BIN_EXE_openmates"));
        command
            .env_clear()
            .env("PATH", "")
            .env("HOME", self.state.path())
            .env("XDG_CONFIG_HOME", self.state.path())
            .env("XDG_DATA_HOME", self.state.path())
            .env("XDG_CACHE_HOME", self.state.path())
            .env("OPENMATES_STATE_DIR", self.state.path())
            .env("LANG", "C.UTF-8")
            .kill_on_drop(true)
            .args([
                "--api-url",
                &self.api,
                "--api-key",
                &key_credential(),
                "projects",
                "sources",
                "list",
            ]);
        if let Some(selector) = selector {
            command.arg(selector);
        }
        command.args(extra);
        command.arg("--personal");
        if json_output {
            command.arg("--json");
        }
        tokio::time::timeout(Duration::from_secs(30), command.output())
            .await
            .expect("bounded native fixture command")
            .unwrap()
    }
    async fn finish(self) {
        self.stop.cancel();
        self.task.await.unwrap();
    }
}
// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity,cli.runtime.native-rust,sdk.encryption.local-only
#[tokio::test]
async fn actual_rust_command_uses_shared_name_decryption_and_exact_six_field_output_without_metadata()
 {
    let f = Fixture::new().await;
    let output = f.run(true, Some(PROJECT)).await;
    assert!(output.status.success(), "native source list failed");
    assert!(output.stderr.is_empty());
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        value,
        json!({"project_id":PROJECT,"sources":[{"source_id":"source-one","source_type":"remote_folder","display_name":"Remote folder","capabilities":["read","search"],"status":"connected","ownership_label":"Attached by you"},{"source_id":"source-two","source_type":"local_folder","display_name":"","capabilities":[],"status":"offline","ownership_label":null}]})
    );
    let text = f.run(false, Some(PROJECT)).await;
    assert!(text.status.success());
    assert!(text.stderr.is_empty());
    assert_eq!(
        String::from_utf8(text.stdout).unwrap(),
        "source-one  Remote folder  connected\nsource-two    offline\n"
    );
    f.mode.store(1, Ordering::SeqCst);
    let empty = f.run(false, Some(PROJECT)).await;
    assert!(empty.status.success());
    assert_eq!(empty.stdout, b"No Project sources.\n");
    let requests = f.requests.lock().unwrap();
    assert_eq!(requests.len(), 9);
    for request in requests.iter() {
        assert!(
            request
                .to_ascii_lowercase()
                .contains(&format!("authorization: bearer sk-api-{}", "b".repeat(32)))
        );
        assert!(!request.contains(&"s".repeat(32)));
        assert!(!request.contains("team_id="));
    }
    drop(requests);
    f.finish().await;
}
// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity,cli.runtime.native-rust,sdk.encryption.local-only
#[tokio::test]
async fn actual_command_preserves_missing_project_exit_and_propagates_shared_source_denial_without_rows()
 {
    let f = Fixture::new().await;
    for selector in [None, Some("   ")] {
        let missing = f.run(true, selector).await;
        assert_eq!(missing.status.code(), Some(1));
        assert!(missing.stdout.is_empty());
        let error: Value = serde_json::from_slice(&missing.stderr).unwrap();
        assert_eq!(
            error,
            json!({"error":{"code":"command_failed","message":"Missing project."}})
        );
        assert!(f.requests.lock().unwrap().is_empty());
    }
    f.mode.store(2, Ordering::SeqCst);
    let denied = f.run(true, Some(PROJECT)).await;
    assert_eq!(denied.status.code(), Some(1));
    assert!(denied.stdout.is_empty());
    let error: Value = serde_json::from_slice(&denied.stderr).unwrap();
    assert_eq!(error["error"]["code"], "forbidden");
    assert!(!String::from_utf8_lossy(&denied.stderr).contains("synthetic source denial"));
    assert_eq!(f.requests.lock().unwrap().len(), 3);
    f.finish().await;
}

// contract-test: supporting surface=cli assertions=projects.surface.semantic-parity,cli.surface.semantic-parity,cli.runtime.native-rust,sdk.encryption.local-only
#[tokio::test]
async fn actual_command_uses_first_project_selector_and_ignores_later_positionals() {
    let f = Fixture::new().await;
    let output = f.run_with_extra(true, Some(PROJECT), &["ignored-later-selector"]).await;
    assert!(output.status.success(), "source list with original extra positional failed");
    assert!(output.stderr.is_empty());
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["project_id"], PROJECT);
    assert_eq!(value["sources"].as_array().unwrap().len(), 2);
    assert!(value["sources"].as_array().unwrap().iter().all(|row| row.as_object().unwrap().len() == 6));
    assert!(!String::from_utf8_lossy(&output.stdout).contains("encrypted_metadata"));
    let requests = f.requests.lock().unwrap();
    assert_eq!(requests.len(), 3);
    assert!(requests.iter().all(|request| !request.contains("ignored-later-selector")));
    drop(requests);
    f.finish().await;
}
