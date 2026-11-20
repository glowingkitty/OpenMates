//! Web (opaque WebCrypto master) Project file jobs: the privacy layer installs and the job is answered within seconds.
// contract-test: supporting surface=web assertions=projects.files.executor-answers
use super::approvals_tests::{CHAT, PROJECT, request};
use crate::client::*;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use crate::session::Session;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const OWNER: &str = "33333333-3333-4333-8333-333333333333";

/// Synthetic WebCrypto stand-in: AES with a fixed master that never leaves it.
struct Port;
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], bytes: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            crypto::encrypt_aead(bytes, &[9; 32], iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], bytes: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::decrypt_aead(bytes, &[9; 32], iv, &[]) })
    }
}

/// A one-route API stub: every `POST /v1/chats/metadata/batch` returns `chats`;
/// anything else is a 404. Returns the base URL.
async fn stub(chats: Value) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    tokio::spawn(async move {
        loop {
            let Ok((mut socket, _)) = listener.accept().await else {
                return;
            };
            let mut bytes = Vec::new();
            let mut part = [0; 4096];
            let (end, length) = loop {
                let n = socket.read(&mut part).await.unwrap_or(0);
                if n == 0 {
                    break (0, 0);
                }
                bytes.extend_from_slice(&part[..n]);
                if let Some(end) = bytes.windows(4).position(|v| v == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&bytes[..end]).to_string();
                    let length = head
                        .lines()
                        .filter_map(|v| v.split_once(':'))
                        .find(|(k, _)| k.eq_ignore_ascii_case("content-length"))
                        .and_then(|(_, v)| v.trim().parse::<usize>().ok())
                        .unwrap_or(0);
                    break (end + 4, length);
                }
            };
            while end > 0 && bytes.len() < end + length {
                let n = socket.read(&mut part).await.unwrap_or(0);
                if n == 0 {
                    break;
                }
                bytes.extend_from_slice(&part[..n]);
            }
            let head = String::from_utf8_lossy(&bytes[..end]).to_string();
            let (status, body) = if head.starts_with("POST /v1/chats/metadata/batch ") {
                (200, json!({"chats": chats}).to_string())
            } else {
                (404, json!({"detail": "not found"}).to_string())
            };
            let reply = format!(
                "HTTP/1.1 {status} Fixture\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = socket.write_all(reply.as_bytes()).await;
        }
    });
    base
}

/// A web Client: browser credentials whose master is an opaque capability.
fn web_client(base: &str) -> Client {
    let session = Session {
        api_url: base.into(),
        session_id: "synthetic-web-session".into(),
        cookies: Default::default(),
        ws_token: Some("synthetic".into()),
        master_key: zeroize::Zeroizing::new([9; 32]),
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new(base, Some(session)).unwrap();
    client.user = json!({"id": OWNER, "username": "synthetic"});
    let mut credentials =
        credentials::BrowserCredentials::from_native_session(client.session.take().unwrap());
    credentials.master = MasterCapability::opaque_for_test(Arc::new(Port));
    client.browser_credentials = Some(credentials);
    client.browser_authority = Some(browser::BrowserAuthority {
        principal: OWNER.into(),
        persistence: browser::BrowserPersistence::MemoryOnly,
        owner_guards: true,
    });
    client.browser_transport = true;
    client
}

fn chat_row() -> Value {
    json!({"id": CHAT,
        "encrypted_chat_key": crypto::server_fields::encrypt_bytes(&[5; 32], &[9; 32], &[]).unwrap()})
}

#[tokio::test]
async fn web_master_installs_the_privacy_layer_and_the_offered_read_is_claimed_within_seconds() {
    let mut web = web_client(&stub(json!([chat_row()])).await);
    assert!(web.native_master_key().is_err());
    let started = Instant::now();
    web.project_file_job_set_privacy(CHAT, PROJECT, true, Vec::new(), None)
        .await
        .expect("the opaque web master opens the chat key");
    let step = web
        .project_file_job_step(
            "project_file_operation_available",
            &request("read_text"),
            true,
        )
        .await
        .unwrap();
    assert!(started.elapsed() < Duration::from_secs(3));
    assert_eq!(step.frames.len(), 1);
    assert_eq!(step.frames[0].name, "project_file_operation_claim");
}

#[tokio::test]
async fn unavailable_chat_key_drops_the_layer_and_the_request_is_answered_failed_at_once() {
    let mut web = web_client(&stub(json!([chat_row()])).await);
    web.project_file_job_set_privacy(CHAT, PROJECT, true, Vec::new(), None)
        .await
        .unwrap();
    // The chat is no longer visible: the earlier layer must not be reused.
    let mut gone = web_client(&stub(json!([])).await);
    std::mem::swap(&mut gone.file_job_chats, &mut web.file_job_chats);
    let refused = gone
        .project_file_job_set_privacy(CHAT, PROJECT, true, Vec::new(), None)
        .await;
    assert!(matches!(refused, Err(Error::Forbidden)));
    let started = Instant::now();
    let step = gone
        .project_file_job_step(
            "project_file_operation_request",
            &request("read_text"),
            true,
        )
        .await
        .unwrap();
    assert!(started.elapsed() < Duration::from_secs(3));
    assert_eq!(step.frames.len(), 1);
    assert_eq!(step.frames[0].payload["status"], "failed");
    assert_eq!(
        step.frames[0].payload["result"]["code"],
        "pii_mapping_unavailable"
    );
}
