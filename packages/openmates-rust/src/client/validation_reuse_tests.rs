//! Session-validation request counting for one native command lane.
use super::*;
use std::sync::{Arc, atomic::{AtomicUsize, Ordering}};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
const OWNER: &str = "11111111-1111-4111-8111-111111111111";

async fn counting_server() -> (String, Arc<AtomicUsize>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let calls = Arc::new(AtomicUsize::new(0));
    let counter = calls.clone();
    tokio::spawn(async move {
        loop {
            let Ok((mut stream, _)) = listener.accept().await else { return };
            let mut bytes = Vec::new();
            let mut buffer = [0u8; 2048];
            loop {
                let n = stream.read(&mut buffer).await.unwrap();
                bytes.extend_from_slice(&buffer[..n]);
                if n == 0 || bytes.windows(4).any(|w| w == b"\r\n\r\n") && bytes.ends_with(b"}") {
                    break;
                }
            }
            assert!(bytes.starts_with(b"POST /v1/auth/session "));
            counter.fetch_add(1, Ordering::SeqCst);
            let body = json!({"success":true,"ws_token":"token","user":{"id":OWNER}}).to_string();
            let head = format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len());
            stream.write_all(head.as_bytes()).await.unwrap();
            stream.write_all(body.as_bytes()).await.unwrap();
        }
    });
    (base, calls)
}

fn client(base: &str) -> Client {
    let mut cookies = BTreeMap::new();
    cookies.insert("auth_refresh_token".into(), "cookie".into());
    let mut client = Client::new(base, Some(Session {
        api_url: base.into(), session_id: "session".into(), cookies, ws_token: Some("old".into()),
        master_key: zeroize::Zeroizing::new([7; 32]), hashed_email: "owner".into(), user_email_salt: String::new(),
        email_encryption_key: None, created_at: 1, paired_session_expires_at: None, active_team_id: None,
    })).unwrap();
    client.user = json!({"id": OWNER});
    client
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement
#[tokio::test]
async fn one_command_validates_its_session_once_and_recovery_always_revalidates() {
    let (base, calls) = counting_server().await;
    let mut client = client(&base);
    // Command admission always contacts the server.
    let cancel = client.operation_parent.clone();
    client.validate_session_for_recovery(&cancel).await.unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    // HTTP handlers (app skills, workspace reads) reuse it within the same lane.
    client.validate_session_for_request().await.unwrap();
    client.validate_session_for_request().await.unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    // Sockets keep their fresh validation.
    client.validate_session().await.unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 2);
    // A recovery admission is never served from the reuse window.
    client.validate_session_for_recovery(&cancel).await.unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 3);
    // Credential changes (cookie rotation, sign-out) invalidate reuse.
    client.credentials_changed();
    client.validate_session_for_request().await.unwrap();
    assert_eq!(calls.load(Ordering::SeqCst), 4);
    client.forget_session();
    assert!(client.validate_session_for_request().await.is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 4);
}
