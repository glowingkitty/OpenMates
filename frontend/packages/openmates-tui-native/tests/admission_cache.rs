//! Controlled-peer native admission evidence; synthetic encrypted cache only.
//! Intended for isolated GitHub CI. No installed profile, keyring or AI access.
use openmates::{
    cli::{self, CliError, Invocation},
    client::Client,
    error::Error,
    runtime_store::RuntimeStore,
    session_runtime::{self, FreshSessionAdmission},
    storage::{CredentialBackend, KeyringFailure, Session, Store},
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

struct NoKeyring;
impl CredentialBackend for NoKeyring {
    fn get(&self, _: &str) -> Result<Zeroizing<Vec<u8>>, KeyringFailure> {
        Err(KeyringFailure::Unavailable)
    }
    fn set(&self, _: &str, _: &[u8]) -> Result<(), KeyringFailure> {
        Err(KeyringFailure::Unavailable)
    }
    fn delete(&self, _: &str) -> Result<(), KeyringFailure> {
        Err(KeyringFailure::Unavailable)
    }
}
fn private_dir() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        builder.permissions(std::fs::Permissions::from_mode(0o700));
    }
    builder.tempdir().unwrap()
}
fn session(api: &str) -> Session {
    Session {
        api_url: api.into(),
        session_id: "synthetic-session".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "synthetic-original".into())]),
        ws_token: None,
        master_key: Zeroizing::new([7; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: "synthetic-salt".into(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}
fn snapshot() -> Value {
    json!({"chats":{"11111111-1111-4111-8111-111111111111":{
        "id":"11111111-1111-4111-8111-111111111111", "encrypted_title":"synthetic-ciphertext"}},
        "wrappers":[], "history":{}, "embeds":{}, "embed_keys":[], "team_wrapped_key":null})
}
fn seed(path: &Path, session: &Session) {
    let store = Store::with_backend(path.to_path_buf(), Arc::new(NoKeyring)).unwrap();
    store.save_session(session, None).unwrap();
    store
        .write_cache(
            &session.hashed_email,
            &session_runtime::cache_key(session),
            &session.master_key,
            &snapshot(),
        )
        .unwrap();
}
fn cache_path(path: &Path) -> PathBuf {
    std::fs::read_dir(path)
        .unwrap()
        .filter_map(Result::ok)
        .map(|v| v.path())
        .find(|p| {
            p.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("cache-")
                && p.extension().is_some_and(|v| v == "json")
        })
        .unwrap()
}
fn whoami() -> Invocation {
    Invocation {
        path: vec!["whoami".into()],
        positionals: vec![],
        flags: BTreeMap::from([("json".into(), json!(true))]),
    }
}
struct Peer {
    api: String,
    requests: Arc<AtomicUsize>,
    stop: CancellationToken,
    sabotage: Arc<std::sync::Mutex<Option<PathBuf>>>,
    response: Arc<std::sync::Mutex<(u16, &'static str)>>,
    task: tokio::task::JoinHandle<()>,
}
impl Peer {
    async fn new(body: &'static str, sabotage: Option<PathBuf>) -> Self {
        Self::with_status(200, body, sabotage).await
    }
    async fn with_status(status: u16, body: &'static str, sabotage: Option<PathBuf>) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let api = format!("http://{}", listener.local_addr().unwrap());
        let requests = Arc::new(AtomicUsize::new(0));
        let counter = requests.clone();
        let stop = CancellationToken::new();
        let cancelled = stop.clone();
        let sabotage = Arc::new(std::sync::Mutex::new(sabotage));
        let block_cache = sabotage.clone();
        let response = Arc::new(std::sync::Mutex::new((status, body)));
        let response_for_peer = response.clone();
        let task = tokio::spawn(async move {
            loop {
                let (mut socket, _) = tokio::select! {
                    _ = cancelled.cancelled() => return,
                    result = listener.accept() => result.unwrap(),
                };
                let mut bytes = vec![];
                let mut chunk = [0u8; 2048];
                let end = loop {
                    let n = socket.read(&mut chunk).await.unwrap();
                    assert_ne!(n, 0);
                    bytes.extend_from_slice(&chunk[..n]);
                    if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
                        break end + 4;
                    }
                };
                let headers = std::str::from_utf8(&bytes[..end]).unwrap();
                assert!(headers.starts_with("POST /v1/auth/session HTTP/1.1\r\n"));
                let length: usize = headers
                    .lines()
                    .filter_map(|v| v.split_once(':'))
                    .find(|(key, _)| key.eq_ignore_ascii_case("content-length"))
                    .unwrap()
                    .1
                    .trim()
                    .parse()
                    .unwrap();
                while bytes.len() < end + length {
                    let n = socket.read(&mut chunk).await.unwrap();
                    assert_ne!(n, 0);
                    bytes.extend_from_slice(&chunk[..n]);
                }
                let payload: Value = serde_json::from_slice(&bytes[end..end + length]).unwrap();
                assert_eq!(payload["session_id"], "synthetic-session");
                let request = counter.fetch_add(1, Ordering::SeqCst);
                #[cfg(unix)]
                if request == 0 {
                    if let Some(cache) = block_cache.lock().unwrap().clone() {
                        // Admission already restored this cache before reaching
                        // the peer. Fail only its subsequent durable publication.
                        let blocked = cache.with_extension("blocked");
                        std::fs::rename(&cache, &blocked).unwrap();
                        std::os::unix::fs::symlink(&blocked, &cache).unwrap();
                    }
                }
                #[cfg(not(unix))]
                let _ = (request, &block_cache);
                let (status, body) = *response_for_peer.lock().unwrap();
                socket.write_all(format!("HTTP/1.1 {status} Synthetic\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=synthetic-rotated; Path=/; HttpOnly\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
            }
        });
        Self {
            api,
            requests,
            stop,
            sabotage,
            response,
            task,
        }
    }
    async fn finish(self) -> usize {
        self.stop.cancel();
        self.task.await.unwrap();
        self.requests.load(Ordering::SeqCst)
    }
}
const VALID: &str = r#"{"success":true,"ws_token":"synthetic-ws","user":{"id":"synthetic-account","name":"Synthetic user"}}"#;
async fn command(api: &str, state: &Path) -> std::process::Output {
    command_args(api, state, &["whoami", "--json"]).await
}
async fn command_args(api: &str, state: &Path, args: &[&str]) -> std::process::Output {
    let mut cmd = tokio::process::Command::new(env!("CARGO_BIN_EXE_openmates"));
    cmd.args(["--api-url", api, "--state-dir", state.to_str().unwrap()])
        .args(args);
    for name in [
        "OPENMATES_API_KEY",
        "OPENMATES_PROFILE",
        "OPENMATES_STATE_DIR",
        "OPENMATES_API_URL",
        "OPENMATES_ACCOUNT_GUARD",
        "OPENMATES_REQUIRE_TRUSTED_ACCOUNT",
        "OPENMATES_APP_URL",
    ] {
        cmd.env_remove(name);
    }
    cmd.stdin(std::process::Stdio::null());
    tokio::time::timeout(
        std::time::Duration::from_secs(10),
        cmd.kill_on_drop(true).output(),
    )
    .await
    .unwrap()
    .unwrap()
}

#[tokio::test]
async fn actual_whoami_admits_once_preserves_warm_cache_and_direct_handler_stays_fresh() {
    let peer = Peer::new(VALID, None).await;
    let temp = private_dir();
    let saved = session(&peer.api);
    seed(temp.path(), &saved);
    let result = command(&peer.api, temp.path()).await;
    assert!(result.status.success());
    assert!(result.stderr.is_empty());
    assert_eq!(
        serde_json::from_slice::<Value>(&result.stdout).unwrap()["id"],
        "synthetic-account"
    );
    assert_eq!(
        peer.requests.load(Ordering::SeqCst),
        1,
        "runtime whoami must reuse its exact admission"
    );
    let store = RuntimeStore::new(Some(temp.path().to_path_buf()), false)
        .await
        .unwrap();
    let loaded = store.load(None).await.unwrap().unwrap();
    assert_eq!(loaded.cookies["auth_refresh_token"], "synthetic-rotated");
    assert_eq!(
        store
            .read_cache(
                loaded.hashed_email.clone(),
                session_runtime::cache_key(&loaded),
                loaded.master_key.clone()
            )
            .await
            .unwrap(),
        Some(snapshot())
    );
    let mut client = Client::new(&peer.api, Some(loaded)).unwrap();
    let direct = cli::execute(&whoami(), &mut client, CancellationToken::new())
        .await
        .unwrap_or_else(|_| panic!("direct whoami must authenticate"));
    assert_eq!(
        serde_json::from_str::<Value>(&direct.stdout).unwrap()["id"],
        "synthetic-account"
    );
    assert_eq!(
        peer.finish().await,
        2,
        "direct callers still require their own fresh request"
    );
}

#[tokio::test]
async fn header_first_rotation_survives_invalid_body_without_output_or_cache_loss() {
    let peer = Peer::new("not-json", None).await;
    let temp = private_dir();
    let saved = session(&peer.api);
    seed(temp.path(), &saved);
    let result = command(&peer.api, temp.path()).await;
    assert!(!result.status.success());
    assert!(result.stdout.is_empty());
    let store = RuntimeStore::new(Some(temp.path().to_path_buf()), false)
        .await
        .unwrap();
    let loaded = store.load(None).await.unwrap().unwrap();
    assert_eq!(loaded.cookies["auth_refresh_token"], "synthetic-rotated");
    assert_eq!(
        store
            .read_cache(
                loaded.hashed_email.clone(),
                session_runtime::cache_key(&loaded),
                loaded.master_key.clone()
            )
            .await
            .unwrap(),
        Some(snapshot())
    );
    assert_eq!(peer.finish().await, 1);
}

#[cfg(unix)]
#[tokio::test]
async fn cache_publication_failure_withholds_whoami_and_keeps_rotated_credentials_durable() {
    let peer = Peer::new(VALID, None).await;
    let temp = private_dir();
    let saved = session(&peer.api);
    seed(temp.path(), &saved);
    let cache = cache_path(temp.path());
    *peer.sabotage.lock().unwrap() = Some(cache.clone());
    let result = command(&peer.api, temp.path()).await;
    assert!(!result.status.success());
    assert!(result.stdout.is_empty());
    let store = RuntimeStore::new(Some(temp.path().to_path_buf()), false)
        .await
        .unwrap();
    let loaded = store.load(None).await.unwrap().unwrap();
    assert_eq!(loaded.cookies["auth_refresh_token"], "synthetic-rotated");
    assert!(
        store
            .read_cache(
                loaded.hashed_email.clone(),
                session_runtime::cache_key(&loaded),
                loaded.master_key.clone()
            )
            .await
            .is_err()
    );
    assert!(
        std::fs::symlink_metadata(&cache)
            .unwrap()
            .file_type()
            .is_symlink()
    );
    // The target is the exact pre-admission protected ciphertext; the failing
    // publication cannot replace or follow it and cannot release user output.
    let target: Value =
        serde_json::from_slice(&std::fs::read(cache.with_extension("blocked")).unwrap()).unwrap();
    assert_eq!(target["version"], 1);
    assert!(!target["ciphertext"].as_str().unwrap().is_empty());
    assert_eq!(peer.finish().await, 1);
}

#[tokio::test]
async fn cache_restore_rejects_foreign_profile_context_before_installing_ciphertext() {
    let temp = private_dir();
    let saved = session("https://api.example.test");
    seed(temp.path(), &saved);
    let store = RuntimeStore::new(Some(temp.path().to_path_buf()), false)
        .await
        .unwrap();
    for field in [
        "owner", "api", "session", "created", "team", "key", "expiry",
    ] {
        let mut foreign = saved.clone();
        match field {
            "owner" => foreign.hashed_email = "other-owner".into(),
            "api" => foreign.api_url = "https://other-api.example.test".into(),
            "session" => foreign.session_id = "other-session".into(),
            "created" => foreign.created_at += 1,
            "team" => foreign.active_team_id = Some("22222222-2222-4222-8222-222222222222".into()),
            "key" => foreign.master_key = Zeroizing::new([8; 32]),
            "expiry" => foreign.paired_session_expires_at = Some(u64::MAX),
            _ => unreachable!(),
        }
        let mut client = Client::new(&foreign.api_url.clone(), Some(foreign)).unwrap();
        let empty = client.ciphertext_snapshot();
        assert!(
            session_runtime::restore_protected_cache(
                &mut client,
                &store,
                None,
                &CancellationToken::new()
            )
            .await
            .is_err(),
            "{field}"
        );
        assert_eq!(client.ciphertext_snapshot(), empty, "{field}");
    }
    assert_eq!(
        store
            .read_cache(
                saved.hashed_email.clone(),
                session_runtime::cache_key(&saved),
                saved.master_key.clone()
            )
            .await
            .unwrap(),
        Some(snapshot())
    );
}

#[tokio::test]
async fn corrupt_expired_revoked_and_cancelled_cache_never_installs_ciphertext() {
    for failure in ["corrupt", "expired", "revoked", "cancelled", "bad-shape"] {
        let temp = private_dir();
        let saved = session("https://api.example.test");
        seed(temp.path(), &saved);
        let store = RuntimeStore::new(Some(temp.path().to_path_buf()), false)
            .await
            .unwrap();
        let mut client = Client::new(&saved.api_url, Some(saved.clone())).unwrap();
        let cancel = CancellationToken::new();
        match failure {
            "corrupt" => {
                std::fs::write(cache_path(temp.path()), b"corrupt ciphertext envelope").unwrap()
            }
            "expired" => {
                let file = temp.path().join("session.json");
                let mut envelope: Value =
                    serde_json::from_slice(&std::fs::read(&file).unwrap()).unwrap();
                envelope["expires_at"] = json!(0);
                std::fs::write(file, serde_json::to_vec(&envelope).unwrap()).unwrap();
            }
            "revoked" => store.revoke().await.unwrap(),
            "cancelled" => cancel.cancel(),
            "bad-shape" => store
                .write_cache(
                    saved.hashed_email.clone(),
                    session_runtime::cache_key(&saved),
                    saved.master_key.clone(),
                    json!({"chats":{},"wrappers":false,"history":{},"embeds":{},"embed_keys":[]}),
                )
                .await
                .unwrap(),
            _ => unreachable!(),
        }
        let cache = cache_path(temp.path());
        let original = std::fs::read(&cache).unwrap();
        assert!(
            session_runtime::restore_protected_cache(&mut client, &store, None, &cancel)
                .await
                .is_err(),
            "{failure}"
        );
        assert!(
            client.ciphertext_snapshot()["chats"]
                .as_object()
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            std::fs::read(cache).unwrap(),
            original,
            "restore failure cannot erase cache evidence"
        );
    }
}

#[tokio::test]
async fn borrowed_admission_is_bound_to_original_cancel_and_store_fence() {
    let peer = Peer::new(VALID, None).await;
    for failure in ["cancel", "revoke"] {
        let temp = private_dir();
        let saved = session(&peer.api);
        seed(temp.path(), &saved);
        let store = RuntimeStore::new(Some(temp.path().to_path_buf()), false)
            .await
            .unwrap();
        let mut client = Client::new(&peer.api, Some(saved)).unwrap();
        let cancel = CancellationToken::new();
        let admission = FreshSessionAdmission::admit(&mut client, &store, None, &cancel)
            .await
            .unwrap();
        match failure {
            "cancel" => cancel.cancel(),
            "revoke" => store.revoke().await.unwrap(),
            _ => unreachable!(),
        }
        assert!(
            matches!(
                admission.whoami_output(&whoami()),
                Err(CliError::Client(Error::Cancelled))
            ),
            "{failure}"
        );
    }
    assert_eq!(peer.finish().await, 2);
}

#[tokio::test]
async fn actual_whoami_preserves_trusted_account_rejection_before_output() {
    let peer = Peer::new(VALID, None).await;
    let temp = private_dir();
    let saved = session(&peer.api);
    seed(temp.path(), &saved);
    cli::trusted_account::save(temp.path(), "different-account")
        .unwrap_or_else(|_| panic!("synthetic trust pin"));
    let result = command(&peer.api, temp.path()).await;
    assert!(!result.status.success());
    assert!(result.stdout.is_empty());
    assert_eq!(peer.finish().await, 1);
}

#[tokio::test]
async fn actual_whoami_401_and_403_reject_without_account_output_or_anonymous_fallback() {
    for status in [401, 403] {
        // Even a success-shaped private body cannot authorize an HTTP denial.
        let peer = Peer::with_status(status, VALID, None).await;
        let temp = private_dir();
        let saved = session(&peer.api);
        seed(temp.path(), &saved);
        let result = command(&peer.api, temp.path()).await;
        assert!(!result.status.success(), "HTTP {status}");
        assert!(result.stdout.is_empty(), "HTTP {status}");
        let error: Value = serde_json::from_slice(&result.stderr).unwrap();
        assert_eq!(error["error"]["code"], "session_expired", "HTTP {status}");
        assert!(!String::from_utf8_lossy(&result.stderr).contains("synthetic-account"));
        let store = RuntimeStore::new(Some(temp.path().to_path_buf()), false)
            .await
            .unwrap();
        assert!(store.load(None).await.unwrap().is_none(), "HTTP {status}");
        assert!(!temp.path().join("credential-key").exists());
        assert!(
            !std::fs::read_dir(temp.path())
                .unwrap()
                .filter_map(Result::ok)
                .any(
                    |entry| entry.file_name().to_string_lossy().starts_with("cache-")
                        && entry
                            .path()
                            .extension()
                            .is_some_and(|extension| extension == "json")
                )
        );
        assert_eq!(
            peer.finish().await,
            1,
            "HTTP {status} must never retry anonymously"
        );
    }
}

#[tokio::test]
async fn actual_whoami_keeps_text_output_and_rejects_unknown_flags_before_account_access() {
    let peer = Peer::new(VALID, None).await;
    let temp = private_dir();
    let saved = session(&peer.api);
    seed(temp.path(), &saved);
    let text = command_args(&peer.api, temp.path(), &["whoami"]).await;
    assert!(text.status.success());
    assert!(text.stderr.is_empty());
    let stdout = String::from_utf8(text.stdout).unwrap();
    assert!(stdout.contains("synthetic-account"));
    assert!(stdout.ends_with('\n'));
    let rejected = command_args(
        &peer.api,
        temp.path(),
        &["whoami", "--not-a-native-flag", "--json"],
    )
    .await;
    assert!(!rejected.status.success());
    assert!(rejected.stdout.is_empty());
    assert!(!String::from_utf8_lossy(&rejected.stderr).contains("synthetic-account"));
    assert_eq!(
        peer.finish().await,
        1,
        "invalid parser flags must not authenticate"
    );
}

#[tokio::test]
async fn borrowed_admission_formats_only_original_client_despite_other_client_account_or_team() {
    const OTHER_ACCOUNT: &str = r#"{"success":true,"ws_token":"synthetic-ws","user":{"id":"different-account","name":"Synthetic user"}}"#;
    let peer = Peer::new(VALID, None).await;
    for replacement in ["client", "account", "team"] {
        *peer.response.lock().unwrap() = (200, VALID);
        let temp = private_dir();
        let original_session = session(&peer.api);
        seed(temp.path(), &original_session);
        let store = RuntimeStore::new(Some(temp.path().to_path_buf()), false)
            .await
            .unwrap();
        let mut original = Client::new(&peer.api, Some(original_session.clone())).unwrap();
        let cancel = CancellationToken::new();
        let admission = FreshSessionAdmission::admit(&mut original, &store, None, &cancel)
            .await
            .unwrap();
        let original_user = admission.user().unwrap().clone();
        let mut substitute_session = original_session;
        if replacement == "team" {
            substitute_session.active_team_id = Some("22222222-2222-4222-8222-222222222222".into());
        }
        if replacement == "account" {
            *peer.response.lock().unwrap() = (200, OTHER_ACCOUNT);
        }
        let mut substitute = Client::new(&peer.api, Some(substitute_session)).unwrap();
        substitute.validate_session().await.unwrap();
        assert_eq!(admission.user().unwrap(), &original_user);
        // There is no replacement-Client parameter. The compile-fail API cases
        // additionally prove retargeting and mutation cannot compile in safe Rust.
        let output = admission
            .whoami_output(&whoami())
            .unwrap_or_else(|_| panic!("original bound output"));
        assert_eq!(
            serde_json::from_str::<Value>(&output.stdout).unwrap(),
            original_user
        );
        assert_eq!(
            original.credential_snapshot().unwrap().revision,
            substitute.credential_snapshot().unwrap().revision
        );
        if replacement != "team" {
            assert_eq!(
                serde_json::to_value(original.session()).unwrap(),
                serde_json::to_value(substitute.session()).unwrap()
            );
        }
        if replacement == "account" {
            assert_ne!(original.user(), substitute.user());
        } else {
            assert_eq!(original.user(), substitute.user());
        }
    }
    assert_eq!(peer.finish().await, 6);
}

#[tokio::test]
async fn actual_corrupt_cache_logout_still_revokes_and_clears_locally_without_authentication() {
    let peer = Peer::new(VALID, None).await;
    let temp = private_dir();
    let mut saved = session(&peer.api);
    // Empty Cookie deliberately exercises the existing local-only logout path;
    // the disposable peer proves no auth refresh or remote logout was attempted.
    saved.cookies.clear();
    seed(temp.path(), &saved);
    std::fs::write(cache_path(temp.path()), b"corrupt protected cache").unwrap();
    let result = command_args(&peer.api, temp.path(), &["logout", "--json"]).await;
    assert!(result.status.success());
    assert!(result.stderr.is_empty());
    let output: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(output["success"], true);
    assert_eq!(output["local_credentials_cleared"], true);
    let store = RuntimeStore::new(Some(temp.path().to_path_buf()), false)
        .await
        .unwrap();
    assert!(store.load(None).await.unwrap().is_none());
    assert!(!temp.path().join("session.json").exists());
    assert!(!temp.path().join("credential-key").exists());
    assert!(
        !std::fs::read_dir(temp.path())
            .unwrap()
            .filter_map(Result::ok)
            .any(
                |entry| entry.file_name().to_string_lossy().starts_with("cache-")
                    && entry
                        .path()
                        .extension()
                        .is_some_and(|extension| extension == "json")
            )
    );
    let fence: Value =
        serde_json::from_slice(&std::fs::read(temp.path().join("revocation.json")).unwrap())
            .unwrap();
    assert_eq!(fence["revoked"], true);
    assert_eq!(peer.finish().await, 0);
}
