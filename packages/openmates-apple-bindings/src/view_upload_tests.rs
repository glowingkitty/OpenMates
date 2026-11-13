//! `uploadFile` against a loopback API that is also its upload host: the core's refresh cookie and a streamed multipart body reach it, signed-out use is `Authentication`, hosts and endpoints outside the allow-list are refused before any request, and a cancelled upload settles as `Cancelled` with the session kept.
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::{core, read_request, session};
use crate::*;
use serde_json::json;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::io::AsyncWriteExt;

/// Raw requests (header block plus body) in arrival order.
type Log = Arc<Mutex<Vec<String>>>;

const FILE_TEXT: &str = "synthetic file content for an upload";

fn reply(status: &str, body: &str) -> String {
    format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )
}

/// Admission and logout; `/v1/upload/file` answers, `/v1/upload/profile-image`
/// hangs (the cancel case).
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
                requests.lock().unwrap().push(raw.clone());
                let line = raw.lines().next().unwrap_or_default().to_owned();
                let admitted = json!({"success": true, "ws_token": "synthetic-ws",
                    "user": {"id": "synthetic-user", "username": "Synthetic Tester"}});
                let answer = if line.starts_with("POST /v1/auth/session ") {
                    reply("200 OK", &admitted.to_string())
                } else if line.starts_with("POST /v1/auth/logout ") {
                    reply("200 OK", "{}")
                } else if line.starts_with("POST /v1/upload/file ") {
                    reply("200 OK", "{\"embed_id\":\"synthetic-embed\"}")
                } else if line.starts_with("POST /v1/upload/profile-image ") {
                    tokio::time::sleep(Duration::from_secs(30)).await;
                    return;
                } else {
                    return;
                };
                let _ = stream.write_all(answer.as_bytes()).await;
            });
        }
    });
    (url, log)
}

fn uploads(log: &Log) -> Vec<String> {
    log.lock()
        .unwrap()
        .iter()
        .filter(|request| request.starts_with("POST /v1/upload/"))
        .cloned()
        .collect()
}

fn upload(url: &str, path: &std::path::Path) -> UploadRequestRecord {
    UploadRequestRecord {
        url: url.into(),
        file_path: path.to_string_lossy().into_owned(),
        filename: "notes \"draft\".txt".into(),
        content_type: "text/plain".into(),
        fields: vec![HttpFieldRecord {
            name: "chat_id".into(),
            value: "synthetic-chat".into(),
        }],
    }
}

/// A started core whose stored session carries the refresh cookie `first`,
/// plus a file to upload.
async fn signed_in() -> (
    tempfile::TempDir,
    String,
    Log,
    Arc<ViewModelCore>,
    std::path::PathBuf,
) {
    let dir = private_dir();
    let (url, log) = api().await;
    let mut stored = session(&url, "synthetic-session-1");
    stored
        .cookies
        .insert("auth_refresh_token".into(), "first".into());
    let (keychain, events) = (
        Keychain::holding(&stored, true),
        Arc::new(Events::default()),
    );
    let core = core(dir.path(), &url, &keychain, &events);
    core.start(None).await.unwrap();
    let file = dir.path().join("upload.txt");
    std::fs::write(&file, FILE_TEXT).unwrap();
    (dir, url, log, core, file)
}

#[tokio::test(flavor = "multi_thread")]
async fn an_upload_carries_the_refresh_cookie_and_a_streamed_multipart_body() {
    let (_dir, url, log, core, file) = signed_in().await;
    let request = upload(&format!("{url}/v1/upload/file"), &file);
    let response = core.upload_file(request, None).await.unwrap();
    assert_eq!(response.status, 200);
    assert_eq!(response.body, b"{\"embed_id\":\"synthetic-embed\"}");
    let sent = uploads(&log);
    assert_eq!(sent.len(), 1);
    let lowered = sent[0].to_ascii_lowercase();
    assert!(lowered.contains("cookie: auth_refresh_token=first"));
    assert!(lowered.contains("content-type: multipart/form-data; boundary="));
    assert!(lowered.contains("x-openmates-sdk: apple"));
    let (_, body) = sent[0].split_once("\r\n\r\n").unwrap();
    let declared: usize = lowered
        .lines()
        .find_map(|line| line.strip_prefix("content-length:"))
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    assert_eq!(body.len(), declared);
    // The field precedes the file part; the filename is FormData-escaped.
    let field = body
        .find("name=\"chat_id\"\r\n\r\nsynthetic-chat\r\n")
        .unwrap();
    let part = body
        .find(
            "name=\"file\"; filename=\"notes %22draft%22.txt\"\r\nContent-Type: text/plain\r\n\r\n",
        )
        .unwrap();
    assert!(field < part);
    assert!(body.contains(&format!("{FILE_TEXT}\r\n--")));
    assert!(body.trim_end().ends_with("--"));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_signed_out_upload_is_refused_as_authentication() {
    let dir = private_dir();
    let (url, log) = api().await;
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), &url, &keychain, &events);
    let file = dir.path().join("upload.txt");
    std::fs::write(&file, FILE_TEXT).unwrap();
    let request = upload(&format!("{url}/v1/upload/file"), &file);
    assert!(matches!(
        core.upload_file(request, None).await,
        Err(CoreError::Authentication)
    ));
    assert!(log.lock().unwrap().is_empty());
}

#[tokio::test(flavor = "multi_thread")]
async fn hosts_endpoints_and_fields_outside_the_allow_list_are_refused() {
    let (_dir, url, log, core, file) = signed_in().await;
    let before = log.lock().unwrap().len();
    for target in [
        "https://example.org/v1/upload/file".to_owned(),
        "https://upload.example.org/v1/upload/file".to_owned(),
        format!("{url}/v1/settings"),
        format!("{url}/v1/upload/other"),
    ] {
        assert!(
            matches!(
                core.upload_file(upload(&target, &file), None).await,
                Err(CoreError::Forbidden)
            ),
            "{target}"
        );
    }
    let target = format!("{url}/v1/upload/file");
    let query = upload(&format!("{target}?x=1"), &file);
    let mut field = upload(&target, &file);
    field.fields.push(HttpFieldRecord {
        name: "auth_refresh_token".into(),
        value: "other".into(),
    });
    let mut relative = upload(&target, &file);
    relative.file_path = "upload.txt".into();
    for request in [query, field, relative] {
        assert!(matches!(
            core.upload_file(request, None).await,
            Err(CoreError::Invalid { .. })
        ));
    }
    // Nothing reached the server.
    assert_eq!(log.lock().unwrap().len(), before);
}

#[tokio::test(flavor = "multi_thread")]
async fn a_cancelled_upload_settles_as_cancelled_and_keeps_the_session() {
    let (_dir, url, _log, core, file) = signed_in().await;
    let cancellation = CoreCancellation::new();
    let cancel = cancellation.clone();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(200)).await;
        cancel.cancel();
    });
    let hanging = upload(&format!("{url}/v1/upload/profile-image"), &file);
    let outcome = tokio::time::timeout(
        Duration::from_secs(10),
        core.upload_file(hanging, Some(cancellation)),
    )
    .await
    .expect("the cancelled upload settles");
    assert!(matches!(outcome, Err(CoreError::Cancelled)));
    // The session is untouched: the next upload succeeds.
    let next = upload(&format!("{url}/v1/upload/file"), &file);
    assert_eq!(core.upload_file(next, None).await.unwrap().status, 200);
}
