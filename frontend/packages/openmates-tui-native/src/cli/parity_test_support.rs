//! Loopback HTTP double shared by the parity command tests: never a real
//! account. Answers each request in order with the supplied JSON and records
//! the raw request text.
use super::Invocation;
use crate::client::Client;
use openmates_sdk::Session;
use serde_json::Value;
use std::collections::BTreeMap;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

pub(super) fn parsed(args: &[&str]) -> Invocation {
    super::parse_from(args.iter().copied())
        .unwrap_or_else(|e| panic!("{e}"))
        .invocation
        .unwrap()
}

pub(super) async fn mock(responses: Vec<Value>) -> (Client, tokio::task::JoinHandle<Vec<String>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let handle = tokio::spawn(async move {
        let mut requests = vec![];
        for body in responses {
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
                        .find_map(|l| l.strip_prefix("content-length:").and_then(|n| n.trim().parse::<usize>().ok()))
                        .unwrap_or(0);
                    if buf.len() >= end + 4 + size {
                        break;
                    }
                }
            }
            requests.push(String::from_utf8(buf).unwrap());
            let body = body.to_string();
            socket
                .write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes())
                .await
                .unwrap();
        }
        requests
    });
    let session = Session {
        api_url: api.clone(),
        session_id: "synthetic-cli-parity".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture".into())]),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([7; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: "c2FsdA==".into(),
        email_encryption_key: Some("synthetic-email-key".into()),
        created_at: 0,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    (Client::new(&api, Some(session)).unwrap(), handle)
}
