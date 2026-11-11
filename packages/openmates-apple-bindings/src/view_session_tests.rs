//! Session ownership for un-migrated Swift code against a loopback API: the HTTP passthrough carries and rotates the core's cookie, refuses absolute URLs, core auth routes and signed-out use, and a 401 signs out with a wipe; session adoption stores, acknowledges and starts, refuses while signed in or malformed, and wipes on a cancel after the store; the legacy grants are refused while signed out.
use crate::view_core_tests::{Events, Keychain, SIGNED_OUT, private_dir};
use crate::view_window_tests::{core, read_request, session};
use crate::*;
use openmates_sdk::session::Session;
use serde_json::json;
use std::sync::{Arc, Mutex};
use tokio::io::AsyncWriteExt;

const SESSION_ID: &str = "synthetic-session-1";

/// Raw requests (lower-cased header block plus body) in arrival order.
type Log = Arc<Mutex<Vec<String>>>;

fn reply(status: &str, extra: &str, body: &str) -> String {
    format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nETag: \"v1\"\r\n{extra}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
}

/// Admission, a settings read that rotates `first` to `second`, a 404, a 401
/// and the logout.
async fn api() -> (String, Log) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = format!("http://{}", listener.local_addr().unwrap());
    let log: Log = Arc::default();
    let requests = log.clone();
    tokio::spawn(async move {
        while let Ok((mut stream, _)) = listener.accept().await {
            let requests = requests.clone();
            tokio::spawn(async move {
                let raw = read_request(&mut stream).await;
                let lowered = raw.to_ascii_lowercase();
                requests.lock().unwrap().push(lowered.clone());
                let line = lowered.lines().next().unwrap_or_default().to_owned();
                let admitted = json!({"success": true, "ws_token": "synthetic-ws",
                    "user": {"id": "synthetic-user", "username": "Synthetic Tester"}})
                .to_string();
                let answer = if line.starts_with("post /v1/auth/session ") {
                    reply("200 OK", "", &admitted)
                } else if line.starts_with("post /v1/auth/logout ") {
                    reply("200 OK", "", "{}")
                } else if line.starts_with("get /v1/settings/example") {
                    if lowered.contains("cookie: auth_refresh_token=first") {
                        reply(
                            "200 OK",
                            "Set-Cookie: auth_refresh_token=second; Path=/\r\n",
                            "{\"round\":1}",
                        )
                    } else {
                        reply("200 OK", "", "{\"round\":2}")
                    }
                } else if line.starts_with("get /v1/settings/missing ") {
                    reply("404 Not Found", "", "{\"detail\":\"Not found\"}")
                } else if line.starts_with("get /v1/settings/rejected ") {
                    reply("401 Unauthorized", "", "{}")
                } else {
                    return;
                };
                let _ = stream.write_all(answer.as_bytes()).await;
            });
        }
    });
    (url, log)
}

fn count(log: &Log, prefix: &str) -> usize {
    log.lock()
        .unwrap()
        .iter()
        .filter(|request| request.starts_with(prefix))
        .count()
}

fn stored(keychain: &Keychain) -> Option<Session> {
    let payload = keychain.payload.lock().unwrap().clone()?;
    Some(serde_json::from_slice(&payload).unwrap())
}

fn get(path: &str) -> HttpRequestRecord {
    HttpRequestRecord {
        method: "GET".into(),
        path: path.into(),
        query: vec![],
        headers: vec![],
        body: None,
    }
}

/// A started core whose stored session carries the cookie `first`.
async fn signed_in() -> (
    tempfile::TempDir,
    Log,
    Arc<Keychain>,
    Arc<Events>,
    Arc<ViewModelCore>,
) {
    let dir = private_dir();
    let (url, log) = api().await;
    let mut session = session(&url, SESSION_ID);
    session
        .cookies
        .insert("auth_refresh_token".into(), "first".into());
    let (keychain, events) = (
        Keychain::holding(&session, true),
        Arc::new(Events::default()),
    );
    let core = core(dir.path(), &url, &keychain, &events);
    core.start(None).await.unwrap();
    (dir, log, keychain, events, core)
}

#[tokio::test(flavor = "multi_thread")]
async fn passthrough_carries_the_session_cookie_and_applies_a_rotated_cookie() {
    let (_dir, log, keychain, _events, core) = signed_in().await;
    let mut request = get("/v1/settings/example");
    request.query = vec![HttpFieldRecord {
        name: "team".into(),
        value: "a b".into(),
    }];
    request.headers = vec![HttpFieldRecord {
        name: "Cache-Control".into(),
        value: "no-cache".into(),
    }];
    let first = core.http_request(request, None).await.unwrap();
    assert_eq!(
        (first.status, first.body.as_slice()),
        (200, &b"{\"round\":1}"[..])
    );
    assert!(
        first
            .headers
            .iter()
            .any(|h| h.name == "etag" && h.value == "\"v1\"")
    );
    assert!(first.headers.iter().all(|h| h.name != "set-cookie"));
    // The rotated cookie is stored through the Keychain before the answer.
    assert_eq!(
        stored(&keychain).unwrap().cookies["auth_refresh_token"],
        "second"
    );
    let second = core
        .http_request(get("/v1/settings/example"), None)
        .await
        .unwrap();
    assert_eq!(second.body, b"{\"round\":2}");
    let requests = log.lock().unwrap().clone();
    let sent: Vec<&String> = requests
        .iter()
        .filter(|r| r.starts_with("get /v1/settings/example"))
        .collect();
    assert!(sent[0].starts_with("get /v1/settings/example?team=a+b "));
    assert!(sent[0].contains("cache-control: no-cache"));
    assert!(sent[1].contains("cookie: auth_refresh_token=second"));
    // Other statuses come back as they are.
    let missing = core
        .http_request(get("/v1/settings/missing"), None)
        .await
        .unwrap();
    assert_eq!(missing.status, 404);
}

#[tokio::test(flavor = "multi_thread")]
async fn passthrough_refuses_absolute_urls_core_routes_and_core_headers() {
    let (_dir, log, _keychain, _events, core) = signed_in().await;
    let before = log.lock().unwrap().len();
    for path in [
        "https://example.org/v1/settings",
        "//example.org/v1/settings",
        "/v1/../v1/settings",
        "/v1/settings?x=1",
        "v1/settings",
    ] {
        assert!(
            matches!(
                core.http_request(get(path), None).await,
                Err(CoreError::Invalid { .. })
            ),
            "{path}"
        );
    }
    for path in ["/v1/auth/session", "/v1/auth/logout", "/v1/auth/login"] {
        let mut request = get(path);
        request.method = "POST".into();
        assert!(matches!(
            core.http_request(request, None).await,
            Err(CoreError::Forbidden)
        ));
    }
    let mut cookie = get("/v1/settings/example");
    cookie.headers = vec![HttpFieldRecord {
        name: "Cookie".into(),
        value: "auth_refresh_token=other".into(),
    }];
    assert!(matches!(
        core.http_request(cookie, None).await,
        Err(CoreError::Invalid { .. })
    ));
    let mut body = get("/v1/settings/example");
    body.body = Some(b"{}".to_vec());
    assert!(matches!(
        core.http_request(body, None).await,
        Err(CoreError::Invalid { .. })
    ));
    // Nothing reached the server.
    assert_eq!(log.lock().unwrap().len(), before);
}

#[tokio::test(flavor = "multi_thread")]
async fn a_rejected_session_signs_out_wipes_and_reports_expired() {
    let (_dir, _log, keychain, events, core) = signed_in().await;
    assert!(matches!(
        core.http_request(get("/v1/settings/rejected"), None).await,
        Err(CoreError::Expired)
    ));
    assert!(stored(&keychain).is_none());
    assert_eq!(
        events.all().last(),
        Some(&ViewEventRecord::Session {
            event: SessionEventRecord::Expired
        })
    );
    assert_eq!(core.session_info().await.unwrap(), None);
    assert!(matches!(
        core.http_request(get("/v1/settings/example"), None).await,
        Err(CoreError::Authentication)
    ));
    // A later start finds nothing stored.
    core.start(None).await.unwrap();
    assert_eq!(events.all().last(), Some(&SIGNED_OUT));
}

#[tokio::test(flavor = "multi_thread")]
async fn signed_out_passthrough_and_legacy_grants_are_refused() {
    let dir = private_dir();
    let (url, log) = api().await;
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), &url, &keychain, &events);
    assert!(matches!(
        core.http_request(get("/v1/settings/example"), None).await,
        Err(CoreError::Authentication)
    ));
    assert!(matches!(
        core.legacy_socket_grant().await,
        Err(CoreError::Authentication)
    ));
    assert_eq!(
        core.legacy_master_key().await,
        Err(CoreError::Authentication)
    );
    assert_eq!(core.session_info().await.unwrap(), None);
    assert!(log.lock().unwrap().is_empty());
}

fn adopted(master_key: Vec<u8>) -> AdoptedSessionRecord {
    AdoptedSessionRecord {
        session_id: SESSION_ID.into(),
        cookies: vec![SessionCookieRecord {
            name: "auth_refresh_token".into(),
            value: "first".into(),
        }],
        ws_token: Some("swift-ws".into()),
        master_key,
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        paired_session_expires_at: None,
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn adoption_stores_acknowledges_starts_and_grants_the_session() {
    let dir = private_dir();
    let (url, log) = api().await;
    let keychain = Arc::new(Keychain {
        acknowledge: true,
        ..Keychain::default()
    });
    let events = Arc::new(Events::default());
    let core = core(dir.path(), &url, &keychain, &events);
    // Malformed input is refused before anything is stored or sent.
    assert!(matches!(
        core.adopt_session(adopted(vec![7; 31]), None).await,
        Err(CoreError::Invalid { .. })
    ));
    let mut no_cookie = adopted(vec![7; 32]);
    no_cookie.cookies[0].name = "other".into();
    assert!(matches!(
        core.adopt_session(no_cookie, None).await,
        Err(CoreError::Invalid { .. })
    ));
    assert!(keychain.changed.lock().unwrap().is_empty() && log.lock().unwrap().is_empty());

    core.adopt_session(adopted(vec![7; 32]), None)
        .await
        .unwrap();
    let session = stored(&keychain).expect("stored");
    // The adoption store, then the admission's refreshed `ws_token`.
    assert!(!keychain.changed.lock().unwrap().is_empty());
    assert_eq!(session.session_id, SESSION_ID);
    assert_eq!(*session.master_key, [7; 32]);
    assert_eq!(count(&log, "post /v1/auth/session "), 1);
    assert!(events.all().iter().any(|event| matches!(
        event,
        ViewEventRecord::Session {
            event: SessionEventRecord::Admitted { .. }
        }
    )));
    let info = core.session_info().await.unwrap().expect("signed in");
    assert_eq!(info.user_id.as_deref(), Some("synthetic-user"));
    assert_eq!(info.hashed_email, "synthetic-owner");
    assert!(info.admitted);
    assert_eq!(core.legacy_master_key().await.unwrap(), vec![7; 32]);
    let grant = core.legacy_socket_grant().await.unwrap();
    assert_eq!(grant.session_id, SESSION_ID);
    assert!(grant.ws_token.is_some());
    // Signed in: a second adoption is refused.
    assert!(matches!(
        core.adopt_session(adopted(vec![7; 32]), None).await,
        Err(CoreError::Invalid { .. })
    ));
}

/// Cancels the adoption when the store arrives, then stores and
/// acknowledges a little later.
struct CancellingKeychain {
    inner: Arc<Keychain>,
    cancel: Arc<CoreCancellation>,
}

impl CredentialStore for CancellingKeychain {
    fn load(&self) -> std::result::Result<Option<Vec<u8>>, CoreError> {
        self.inner.load()
    }
    fn credentials_changed(&self, snapshot: CredentialSnapshotRecord) {
        self.cancel.cancel();
        let inner = self.inner.clone();
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(50));
            inner.credentials_changed(snapshot);
        });
    }
    fn delete(&self) -> std::result::Result<(), CoreError> {
        self.inner.delete()
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn an_adoption_cancelled_after_the_store_leaves_nothing_stored() {
    let dir = private_dir();
    let (url, log) = api().await;
    let inner = Arc::new(Keychain {
        acknowledge: true,
        ..Keychain::default()
    });
    let (events, cancel) = (Arc::new(Events::default()), CoreCancellation::new());
    let store = Arc::new(CancellingKeychain {
        inner: inner.clone(),
        cancel: cancel.clone(),
    });
    let config = CoreConfig {
        api_url: url,
        app_url: None,
        cache_container: Some(dir.path().to_str().unwrap().to_owned()),
        cache_directory_name: Some(crate::view_core_tests::NAME.into()),
    };
    let core = ViewModelCore::build(
        config,
        store,
        events.clone(),
        std::time::Duration::from_secs(5),
    )
    .unwrap();
    inner.core.set(Arc::downgrade(&core)).unwrap();
    assert_eq!(
        core.adopt_session(adopted(vec![7; 32]), Some(cancel)).await,
        Err(CoreError::Cancelled)
    );
    assert_eq!(inner.changed.lock().unwrap().len(), 1);
    assert!(stored(&inner).is_none());
    assert_eq!(count(&log, "post /v1/auth/logout "), 1);
    assert_eq!(events.all(), [SIGNED_OUT]);
}
