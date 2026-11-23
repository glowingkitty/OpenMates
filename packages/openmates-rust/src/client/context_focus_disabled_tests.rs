//! A server with Projects switched off (404 `FEATURE_DISABLED` on the focus
//! route) means "no Project focus", so a turn is not refused (issue F74ES).
// contract-test-file: tooling
use super::*;

const CHAT: &str = "33333333-3333-4333-8333-333333333333";

// Bounded inert transport fixture, no product server or automatic credentials.
fn signed_in(api: &str) -> Client {
    Client::new(
        api,
        Some(Session {
            api_url: api.into(),
            session_id: "synthetic-context".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "synthetic-context".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}

/// One-shot HTTP server answering each request with the next `(status, body)`.
async fn mock(responses: Vec<(u16, Value)>) -> (String, tokio::task::JoinHandle<Vec<String>>) {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let mut requests = vec![];
        for (status, response) in responses {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut bytes = vec![];
            loop {
                let mut chunk = [0; 4096];
                let count = socket.read(&mut chunk).await.unwrap();
                assert!(count > 0 && bytes.len() + count <= 65536);
                bytes.extend_from_slice(&chunk[..count]);
                if bytes.windows(4).any(|w| w == b"\r\n\r\n") {
                    break;
                }
            }
            requests.push(String::from_utf8(bytes).unwrap());
            let body = response.to_string();
            let reason = if status == 200 { "OK" } else { "Error" };
            socket
                .write_all(format!("HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes())
                .await
                .unwrap();
        }
        requests
    });
    (api, server)
}

#[tokio::test]
async fn projects_disabled_on_the_server_means_no_active_project_context() {
    let (api, server) = mock(vec![(404, json!({"detail": "FEATURE_DISABLED"}))]).await;
    let mut client = signed_in(&api);
    let out = client.active_project_context(CHAT, "How does a black hole work?").await.unwrap();
    assert_eq!(out, json!({}));
    let requests = server.await.unwrap();
    assert_eq!(requests.len(), 1);
    assert!(requests[0].starts_with("GET /v1/projects/focus/current?chat_id="));
}

#[tokio::test]
async fn other_focus_failures_still_fail_the_turn() {
    let (api, server) = mock(vec![(400, json!({"detail": "bad"}))]).await;
    let mut client = signed_in(&api);
    assert!(matches!(
        client.active_project_context(CHAT, "Hello").await,
        Err(Error::Invalid(_))
    ));
    let (api403, server403) = mock(vec![(403, json!({"detail": "forbidden"}))]).await;
    let mut client403 = signed_in(&api403);
    assert!(matches!(
        client403.active_project_context(CHAT, "Hello").await,
        Err(Error::Forbidden)
    ));
    server.await.unwrap();
    server403.await.unwrap();
}
