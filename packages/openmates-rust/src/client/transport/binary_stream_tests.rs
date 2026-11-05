use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

fn session(api: &str) -> Session {
    Session {
        api_url: api.into(),
        session_id: "fixture".into(),
        cookies: BTreeMap::from([("auth_refresh_token".to_owned(), "fixture".to_owned())]),
        ws_token: None,
        master_key: Zeroizing::new([1; 32]),
        hashed_email: "hash".into(),
        user_email_salt: "salt".into(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}
/// One-connection mock server: returns the raw request head and replies.
async fn serve(chunks: Vec<Vec<u8>>) -> (String, tokio::task::JoinHandle<String>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut head = Vec::new();
        let mut byte = [0u8; 1];
        while !head.ends_with(b"\r\n\r\n") {
            stream.read_exact(&mut byte).await.unwrap();
            head.push(byte[0]);
        }
        for chunk in chunks {
            stream.write_all(&chunk).await.unwrap();
            stream.flush().await.unwrap();
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
        String::from_utf8_lossy(&head).to_lowercase()
    });
    (api, server)
}
fn signed_client(api: &str) -> Client {
    let mut client = Client::new(api, None).unwrap();
    client
        .cookies
        .insert("auth_refresh_token".into(), "fixture".into());
    client.session = Some(session(api));
    client
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn binary_download_replaces_accept_keeps_credentials_and_rotates_cookie() {
    let body = b"%PDF-1.7 binary\x00\xff";
    let mut response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=\"Invoice_1.pdf\"\r\nSet-Cookie: auth_refresh_token=rotated; Path=/\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    )
    .into_bytes();
    response.extend_from_slice(body);
    let (api, server) = serve(vec![response]).await;
    let mut client = signed_client(&api);
    let download = client
        .get_binary(
            "/v1/payments/invoices/1/download",
            "application/pdf,application/octet-stream",
        )
        .await
        .unwrap();
    assert!(download.ok());
    assert_eq!(download.data.as_slice(), body);
    assert_eq!(download.content_type.as_deref(), Some("application/pdf"));
    assert_eq!(
        download.content_disposition.as_deref(),
        Some("attachment; filename=\"Invoice_1.pdf\"")
    );
    assert_eq!(
        client.cookies.get("auth_refresh_token").map(String::as_str),
        Some("rotated")
    );
    let head = server.await.unwrap();
    assert!(head.starts_with("get /v1/payments/invoices/1/download "));
    assert_eq!(head.matches("\r\naccept:").count(), 1);
    assert!(head.contains("\r\naccept: application/pdf,application/octet-stream\r\n"));
    assert!(head.contains("cookie: auth_refresh_token=fixture"));
    assert!(head.contains("origin: http://localhost:5173"));
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn binary_download_reports_failure_status_and_expires_on_401() {
    let (api, server) = serve(vec![
        b"HTTP/1.1 404 Not Found\r\nContent-Length: 9\r\nConnection: close\r\n\r\nnot found"
            .to_vec(),
    ])
    .await;
    let mut client = signed_client(&api);
    let missing = client
        .get_binary("/v1/teams/t/profile-image", "image/png")
        .await
        .unwrap();
    assert_eq!(missing.status, 404);
    assert!(missing.data.is_empty());
    server.await.unwrap();

    let (api, server) = serve(vec![
        b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec(),
    ])
    .await;
    let mut client = signed_client(&api);
    assert!(matches!(
        client.get_binary("/v1/x", "image/png").await,
        Err(Error::Expired)
    ));
    assert!(client.session().is_none());
    server.await.unwrap();

    let (api, server) = serve(vec![b"HTTP/1.1 302 Found\r\nLocation: https://attacker.example/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec()]).await;
    let mut client = signed_client(&api);
    assert!(matches!(
        client.get_binary("/v1/x", "image/png").await,
        Err(Error::Forbidden)
    ));
    server.await.unwrap();
}

#[tokio::test]
async fn binary_download_rejects_oversized_declared_body() {
    let head = format!(
        "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        MAX_BODY + 1
    );
    let (api, server) = serve(vec![head.into_bytes()]).await;
    let mut client = signed_client(&api);
    assert!(matches!(
        client.get_binary("/v1/x", "image/png").await,
        Err(Error::Protocol)
    ));
    drop(server);
}

#[test]
fn sse_parser_matches_npm_framing() {
    let mut parser = SseParser::default();
    parser
        .push(b": keepalive\n\nid: 7\nevent: notification\ndata: {\"a\"")
        .unwrap();
    assert!(parser.pop().is_none());
    parser
        .push(b":1}\ndata:second\n\nevent: ping\n\ndata: tail")
        .unwrap();
    assert_eq!(
        parser.pop(),
        Some(SseMessage {
            id: Some("7".into()),
            event: Some("notification".into()),
            data: "{\"a\":1}\nsecond".into()
        })
    );
    // An event without data is dropped; the unterminated tail stays pending.
    assert!(parser.pop().is_none());
    assert_eq!(parse_sse_message("data"), None);
    assert_eq!(
        parse_sse_message("data:  x").map(|m| m.data),
        Some(" x".into())
    );
    let mut big = SseParser::default();
    assert!(matches!(
        big.push(&vec![b'a'; MAX_SSE_EVENT + 1]),
        Err(Error::Protocol)
    ));
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn sse_stream_yields_events_across_chunks_and_reports_status() {
    let (api, server) = serve(vec![
        b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n".to_vec(),
        b"event: notification\ndata: {\"id\":1}\n".to_vec(),
        b"\nevent: notification\ndata: {\"id\":2}\n\n".to_vec(),
    ])
    .await;
    let mut client = signed_client(&api);
    let SseOpen::Stream(mut stream) = client.open_sse("/v1/notifications/stream").await.unwrap()
    else {
        panic!("stream")
    };
    assert_eq!(stream.next().await.unwrap().unwrap().data, "{\"id\":1}");
    assert_eq!(stream.next().await.unwrap().unwrap().data, "{\"id\":2}");
    assert!(stream.next().await.unwrap().is_none());
    let head = server.await.unwrap();
    assert!(head.contains("\r\naccept: text/event-stream\r\n"));
    assert!(head.contains("cookie: auth_refresh_token=fixture"));

    let (api, server) = serve(vec![
        b"HTTP/1.1 503 Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec(),
    ])
    .await;
    let mut client = signed_client(&api);
    assert!(matches!(
        client.open_sse("/v1/notifications/stream").await.unwrap(),
        SseOpen::Status(503)
    ));
    server.await.unwrap();
}

#[tokio::test]
async fn non_json_transport_requires_a_session() {
    let mut client = Client::new("http://127.0.0.1:9", None).unwrap();
    assert!(client.get_binary("/v1/x", "image/png").await.is_err());
    assert!(client.open_sse("/v1/x").await.is_err());
}
