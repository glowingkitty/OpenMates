//! Loopback HTTP double and synthetic session for account SDK tests only.
use crate::Session;
use serde_json::Value;
use std::collections::BTreeMap;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

pub(in crate::account) fn session(origin: &str, email_key: Option<&str>) -> Session {
    Session {
        api_url: origin.into(),
        session_id: "synthetic-settings-session".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture".into())]),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: "c2FsdA==".into(),
        email_encryption_key: email_key.map(str::to_owned),
        created_at: 0,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}
/// Loopback HTTP double: answers each request in order and records it.
pub(in crate::account) async fn mock(
    responses: Vec<(u16, Value)>,
) -> (String, tokio::task::JoinHandle<Vec<String>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let handle = tokio::spawn(async move {
        let mut requests = vec![];
        for (status, body) in responses {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = Vec::new();
            loop {
                let mut bytes = [0; 4096];
                let n = socket.read(&mut bytes).await.unwrap();
                assert!(n > 0);
                buf.extend_from_slice(&bytes[..n]);
                if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
                    let size = head
                        .lines()
                        .find_map(|line| {
                            line.strip_prefix("content-length:")
                                .and_then(|n| n.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if buf.len() >= end + 4 + size {
                        break;
                    }
                }
            }
            requests.push(String::from_utf8(buf).unwrap());
            let body = body.to_string();
            socket.write_all(format!("HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    (api, handle)
}
