//! Status polling of the session Code Run: finish, timeout, consent refusal and path policy.
// contract-test: supporting surface=sdks.rust assertions=code-run.e2b.upload-consent
use super::*;
use std::sync::{Arc, Mutex, atomic::{AtomicUsize, Ordering}};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

fn client(endpoint: &str) -> Client {
    let session = serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic-session","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).unwrap();
    let mut c = Client::new(endpoint, Some(session)).unwrap();
    c.user = json!({"id":"synthetic-owner"});
    c
}

/// Loopback server answering every request through `handle(request_line)`.
async fn serve(
    handle: impl Fn(&str) -> (u16, Value) + Send + Sync + 'static,
) -> (String, Arc<Mutex<Vec<String>>>, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let seen = Arc::new(Mutex::new(Vec::new()));
    let log = seen.clone();
    let task = tokio::spawn(async move {
        loop {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = Vec::new();
            let end = loop {
                let mut chunk = [0u8; 2048];
                let n = socket.read(&mut chunk).await.unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&chunk[..n]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    break end + 4;
                }
            };
            let head = String::from_utf8_lossy(&bytes[..end]).into_owned();
            let length = head
                .lines()
                .find_map(|l| {
                    let (k, v) = l.split_once(':')?;
                    k.eq_ignore_ascii_case("content-length").then(|| v.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            while bytes.len() < end + length {
                let mut chunk = [0u8; 2048];
                let n = socket.read(&mut chunk).await.unwrap();
                assert!(n > 0);
                bytes.extend_from_slice(&chunk[..n]);
            }
            let line = head.lines().next().unwrap().to_owned();
            let (status, body) = handle(&line);
            log.lock().unwrap().push(line);
            let raw = serde_json::to_vec(&body).unwrap();
            let reply = format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", raw.len());
            let _ = socket.write_all(reply.as_bytes()).await;
            let _ = socket.write_all(&raw).await;
        }
    });
    (base, seen, task)
}

fn accepted() -> Value {
    json!({"success":true,"data":{"results":[{"status_path":"/v1/code/run/run-1"},{"note":"no status"}]}})
}

#[tokio::test]
async fn polls_the_status_path_until_finished_and_stores_final() {
    let polls = Arc::new(AtomicUsize::new(0));
    let counter = polls.clone();
    let (base, seen, server) = serve(move |line| {
        if line.starts_with("POST /v1/apps/code/skills/run ") {
            (200, accepted())
        } else if counter.fetch_add(1, Ordering::SeqCst) == 0 {
            (200, json!({"status":"running"}))
        } else {
            (200, json!({"status":"finished","exit_code":0,"stdout":"ok"}))
        }
    })
    .await;
    let mut c = client(&base);
    let admission = c.direct_app_skill_admission().unwrap();
    let out = c
        .run_code_polled(json!({"requests":[{}]}), &admission, Duration::from_millis(5), Duration::from_secs(5))
        .await
        .unwrap();
    assert_eq!(out["data"]["results"][0]["final"]["status"], "finished");
    assert_eq!(out["data"]["results"][0]["final"]["stdout"], "ok");
    assert!(out["data"]["results"][1].get("final").is_none());
    let lines = seen.lock().unwrap().clone();
    assert_eq!(lines.iter().filter(|l| l.starts_with("POST ")).count(), 1);
    assert_eq!(lines.iter().filter(|l| l.starts_with("GET /v1/code/run/run-1 ")).count(), 2);
    server.abort();
}

#[tokio::test]
async fn a_run_that_never_ends_times_out_without_reposting() {
    let (base, seen, server) = serve(|line| {
        if line.starts_with("POST ") { (200, accepted()) } else { (200, json!({"status":"running"})) }
    })
    .await;
    let mut c = client(&base);
    let admission = c.direct_app_skill_admission().unwrap();
    let error = c
        .run_code_polled(json!({"requests":[{}]}), &admission, Duration::from_millis(5), Duration::from_millis(60))
        .await
        .unwrap_err();
    assert_eq!(error, Error::Offline);
    assert_eq!(seen.lock().unwrap().iter().filter(|l| l.starts_with("POST ")).count(), 1);
    server.abort();
}

#[tokio::test]
async fn consent_refusals_surface_as_typed_errors() {
    for code in ["e2b_consent_required", "e2b_consent_declined"] {
        let (base, _, server) = serve(move |_| (403, json!({"detail":{"code":code}}))).await;
        let mut c = client(&base);
        let admission = c.direct_app_skill_admission().unwrap();
        let error = c.run_code_with_status(json!({"requests":[{}]}), &admission).await.unwrap_err();
        assert_eq!(error.sdk_code(), Some(code));
        server.abort();
    }
}

#[tokio::test]
async fn foreign_status_paths_are_refused_before_any_poll() {
    let (base, seen, server) = serve(|_| {
        (200, json!({"results":[{"status_path":"/v1/other/run-1"}]}))
    })
    .await;
    let mut c = client(&base);
    let admission = c.direct_app_skill_admission().unwrap();
    let error = c.run_code_with_status(json!({"requests":[{}]}), &admission).await.unwrap_err();
    assert_eq!(error, Error::Protocol);
    assert_eq!(seen.lock().unwrap().len(), 1);
    server.abort();
}

#[test]
fn status_paths_keep_positions_and_bound_the_result_count() {
    let data = json!({"results":[{"x":1},{"status_path":"/v1/code/run/a"}]});
    assert_eq!(status_paths(&data).unwrap(), vec![(1, "/v1/code/run/a".to_owned())]);
    let many = json!({"results": vec![json!({}); 101]});
    assert_eq!(status_paths(&many), Err(Error::Protocol));
    assert!(status_paths(&json!({})).unwrap().is_empty());
}
