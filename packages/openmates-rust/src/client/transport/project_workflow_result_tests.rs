//! AUTHORED UNRUN: real response paths, no runtime proof implied.
use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
const PROJECT: &str = "22222222-2222-4222-8222-222222222222";
const REQUEST: &str = "33333333-3333-4333-8333-333333333333";
const REQUESTER: &str = "44444444-4444-4444-8444-444444444444";
fn client(api: &str) -> Client {
    Client::new(
        api,
        Some(crate::Session {
            api_url: api.into(),
            session_id: "fixture".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([1; 32]),
            hashed_email: "fixture".into(),
            user_email_salt: "fixture".into(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}
async fn read_request(socket: &mut tokio::net::TcpStream) {
    let mut bytes = Vec::new();
    let mut part = [0; 1024];
    while !bytes.windows(4).any(|v| v == b"\r\n\r\n") {
        let count = socket.read(&mut part).await.unwrap();
        assert!(count > 0);
        bytes.extend_from_slice(&part[..count]);
        assert!(bytes.len() < 16384);
    }
    let text = std::str::from_utf8(&bytes).unwrap();
    assert!(text.starts_with("GET /v1/projects/"));
    assert!(text.contains("requesting_client_id="));
}
async fn peer(status: u16, body: &str) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let body = body.to_owned();
    let task = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        read_request(&mut socket).await;
        socket.write_all(format!("HTTP/1.1 {status} fixture\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
    });
    (api, task)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.secrets.lifecycle
#[test]
fn finite_pending_marker_rejects_unknown_malformed_duplicate_and_private_shapes() {
    assert!(project_request_pending(
        404,
        br#"{"detail":"request_not_found"}"#
    ));
    for body in [
        br#"{"detail":"Source not found"}"#.as_slice(),
        br#"{"detail":{"code":"request_not_found"}}"#,
        br#"{"code":"request_not_found"}"#,
        br#"{"detail":"request_not_found","private":"never echo"}"#,
        br#"{"detail":"request_not_found","detail":"Source not found"}"#,
        b"private invalid JSON",
        br#"{"detail":null}"#,
    ] {
        assert!(!project_request_pending(404, body));
    }
    for status in [200, 400, 401, 403, 409, 410, 429, 500] {
        assert!(!project_request_pending(
            status,
            br#"{"detail":"request_not_found"}"#
        ));
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.secrets.lifecycle
#[tokio::test]
async fn actual_exact_pending_is_negative_only_and_other_404_stays_secret_safe_error() {
    for body in [
        r#"{"detail":"request_not_found"}"#,
        r#"{"detail":"Source not found"}"#,
        r#"{"detail":"private unexpected text"}"#,
        r#"{"detail":{"code":"request_not_found"}}"#,
        "not JSON",
    ] {
        let (api, server) = peer(404, body).await;
        let mut c = client(&api);
        let value = c
            .project_workflow_result(PROJECT, "source", REQUEST, REQUESTER, None)
            .await;
        server.await.unwrap();
        if body == r#"{"detail":"request_not_found"}"# {
            assert!(matches!(value, Ok(None)));
        } else {
            assert!(matches!(
                value,
                Err(Error::Invalid("The requested item is unavailable."))
            ));
            assert!(!format!("{:?}", value.err()).contains("private"));
        }
    }
    let (api, server) = peer(
        200,
        r#"{"status":"completed","encrypted_envelope":"opaque"}"#,
    )
    .await;
    let value = client(&api)
        .project_workflow_result(PROJECT, "source", REQUEST, REQUESTER, None)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(value["encrypted_envelope"], "opaque");
    server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.authoritative-enforcement
#[tokio::test]
async fn ordinary_caller_keeps_original_404_mapping_for_same_response() {
    let (api, server) = peer(404, r#"{"detail":"request_not_found"}"#).await;
    let mut c = client(&api);
    let route = format!(
        "/v1/projects/{PROJECT}/sources/source/requests/{REQUEST}?requesting_client_id={REQUESTER}"
    );
    assert!(matches!(
        c.request_task_headers(Method::GET, &route, None, None, None, None)
            .await,
        Err(Error::Invalid("The requested item is unavailable."))
    ));
    server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.secrets.lifecycle,streams.cancellation.original-owner
#[tokio::test]
async fn cancellation_after_headers_waits_actual_body_terminal_then_cannot_issue_pending() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let (sent, received) = tokio::sync::oneshot::channel();
    let (release, held) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        read_request(&mut socket).await;
        let body = r#"{"detail":"request_not_found"}"#;
        socket
            .write_all(
                format!(
                    "HTTP/1.1 404 fixture\r\ncontent-length: {}\r\nconnection: close\r\n\r\n",
                    body.len()
                )
                .as_bytes(),
            )
            .await
            .unwrap();
        sent.send(()).unwrap();
        held.await.unwrap();
        socket.write_all(body.as_bytes()).await.unwrap();
    });
    let cancel = tokio_util::sync::CancellationToken::new();
    let mut c = client(&api);
    c.set_operation_cancel(cancel.clone());
    let mut call = tokio::spawn(async move {
        c.project_workflow_result(PROJECT, "source", REQUEST, REQUESTER, None)
            .await
    });
    received.await.unwrap();
    cancel.cancel();
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut call)
            .await
            .is_err()
    );
    release.send(()).unwrap();
    assert!(matches!(call.await.unwrap(), Err(Error::Cancelled)));
    server.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.secrets.lifecycle
#[tokio::test]
async fn declared_body_limit_and_pre_cancel_never_produce_pending() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        read_request(&mut socket).await;
        socket
            .write_all(
                format!(
                    "HTTP/1.1 404 fixture\r\ncontent-length: {}\r\nconnection: close\r\n\r\n",
                    MAX_BODY + 1
                )
                .as_bytes(),
            )
            .await
            .unwrap();
    });
    assert!(matches!(
        client(&api)
            .project_workflow_result(PROJECT, "source", REQUEST, REQUESTER, None)
            .await,
        Err(Error::Protocol)
    ));
    server.await.unwrap();
    let mut c = client("http://127.0.0.1:1");
    let cancel = tokio_util::sync::CancellationToken::new();
    cancel.cancel();
    c.set_operation_cancel(cancel);
    assert!(matches!(
        c.project_workflow_result(PROJECT, "source", REQUEST, REQUESTER, None)
            .await,
        Err(Error::Cancelled)
    ));
}
