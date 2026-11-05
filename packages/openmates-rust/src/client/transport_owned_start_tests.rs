//! Native protocol regressions, authored UNRUN for isolated CI. Native Session
//! fixtures do not establish browser/opaque-master/local-profile acceptance.
use super::*;
use crate::client::owned_operation::{ActiveOwnedClient, OwnedOperationScope};
use futures_util::StreamExt;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::sync::oneshot;

const OWNER: &str = "11111111-1111-4111-8111-111111111111";
fn client(base: &str) -> Client {
    let mut c = Client::new(base, Some(Session { api_url: base.into(), session_id: "fixture-session".into(),
        cookies: BTreeMap::new(), ws_token: Some("old-token".into()), master_key: zeroize::Zeroizing::new([7;32]),
        hashed_email: "fixture".into(), user_email_salt: String::new(), email_encryption_key: None,
        created_at: 1, paired_session_expires_at: None, active_team_id: None })).unwrap();
    c.user = json!({"id":OWNER}); c
}

async fn real_auth_request(stream: &mut tokio::net::TcpStream) {
    let mut bytes = Vec::new();
    let header_end = loop {
        let mut chunk = [0u8; 1024]; let n = stream.read(&mut chunk).await.unwrap(); assert!(n > 0);
        bytes.extend_from_slice(&chunk[..n]); assert!(bytes.len() < 8192);
        if let Some(n) = bytes.windows(4).position(|v| v == b"\r\n\r\n") { break n + 4; }
    };
    let headers = String::from_utf8_lossy(&bytes[..header_end]);
    assert!(headers.starts_with("POST /v1/auth/session "));
    let length: usize = headers.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("content-length").then(|| value.trim().parse().unwrap())
    }).unwrap();
    while bytes.len() < header_end + length {
        let mut chunk = [0u8; 1024]; let n = stream.read(&mut chunk).await.unwrap(); assert!(n > 0);
        bytes.extend_from_slice(&chunk[..n]); assert!(bytes.len() < 8192);
    }
    let body: Value = serde_json::from_slice(&bytes[header_end..header_end + length]).unwrap();
    assert_eq!(body["session_id"], "fixture-session");
}

// Whole-test timeout is a deadlock watchdog only. The no-connection assertion
// comes from the actual accept queue raced against actual socket completion.
async fn protocol_case(cancel_kind: u8) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let (observed_tx, observed_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let (done_tx, mut done_rx) = oneshot::channel();
    let peer = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        real_auth_request(&mut stream).await;
        observed_tx.send(()).unwrap(); release_rx.await.unwrap();
        let body = json!({"success":true,"ws_token":"rotated-token","user":{"id":OWNER}}).to_string();
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=rotated-cookie; Path=/\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
        drop(stream);
        let mut connections = 0usize; let mut lifecycle = 0usize;
        loop {
            tokio::select! { biased;
                accepted = listener.accept() => {
                    let (stream, _) = accepted.unwrap(); connections += 1;
                    // If the guard regresses, complete the actual upgrade and
                    // observe the lifecycle rather than hanging the client.
                    let mut ws = tokio_tungstenite::accept_hdr_async(stream,
                        |request: &tokio_tungstenite::tungstenite::handshake::server::Request,
                         response: tokio_tungstenite::tungstenite::handshake::server::Response| {
                            assert!(request.uri().query().unwrap().contains("token=rotated-token"));
                            assert!(request.headers()["Cookie"].to_str().unwrap().contains("auth_refresh_token=rotated-cookie"));
                            Ok(response)
                        }).await.unwrap();
                    let frame = ws.next().await.unwrap().unwrap();
                    let event: Value = serde_json::from_str(frame.to_text().unwrap()).unwrap();
                    assert_eq!(event["type"], "native_client_lifecycle"); lifecycle += 1;
                },
                done = &mut done_rx => { done.unwrap(); break; },
            }
        }
        (connections, lifecycle)
    });
    let mut c = client(&base);
    let request = CancellationToken::new();
    let a = OwnedOperationScope::capture(&c, request.clone()).unwrap();
    let b = OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap();
    let original_child = a.child().clone();
    let parent = c.operation_parent.clone(); let global_child = c.operation_cancel.clone();
    let (result, ()) = {
        let mut active = ActiveOwnedClient::enter(&mut c, &a).unwrap();
        let socket = async {
            let result = active.socket_with_task_jobs(true).await;
            let _ = done_tx.send(());
            result.map(drop)
        };
        let control = async {
            observed_rx.await.unwrap();
            match cancel_kind { 0 => {}, 1 => request.cancel(), 2 => original_child.cancel(), _ => unreachable!() }
            release_tx.send(()).unwrap();
        };
        tokio::join!(socket, control)
    }; // Actual ActiveOwnedClient restores the previous owned phase here.
    let (connections, lifecycle) = peer.await.unwrap();
    if cancel_kind == 0 {
        result.expect("actual uncanceled original socket opens"); assert_eq!((connections, lifecycle), (1, 1));
        a.check(&c).unwrap();
    } else {
        assert_eq!(result, Err(Error::Cancelled)); assert_eq!((connections, lifecycle), (0, 0));
        assert!(a.observer().check_release().is_err());
    }
    assert_eq!(c.session().unwrap().ws_token.as_deref(), Some("rotated-token"));
    assert_eq!(c.cookies.get("auth_refresh_token").map(String::as_str), Some("rotated-cookie"));
    assert_eq!(c.session().unwrap().cookies.get("auth_refresh_token").map(String::as_str), Some("rotated-cookie"));
    b.check(&c).expect("original same-parent B accepts real witnessed rotation");
    assert_eq!(c.operation_parent, parent); assert!(!parent.is_cancelled());
    assert_eq!(c.operation_cancel, global_child); assert!(!global_child.is_cancelled());
    assert!(c.active_owned_operation.is_none());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn real_auth_held_request_cancel_preserves_credentials_and_peer_without_opening_socket() {
    tokio::time::timeout(Duration::from_secs(10), protocol_case(1)).await.expect("deadlock watchdog");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn real_auth_held_child_cancel_preserves_credentials_and_peer_without_opening_socket() {
    tokio::time::timeout(Duration::from_secs(10), protocol_case(2)).await.expect("deadlock watchdog");
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn uncanceled_original_opens_exactly_one_real_socket_and_lifecycle() {
    tokio::time::timeout(Duration::from_secs(10), protocol_case(0)).await.expect("deadlock watchdog");
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn post_validation_helper_rejects_original_root_policy_deadline_and_unknown_lineage() {
    for change in 0..4 {
        let mut c = client("https://example.invalid");
        let a = OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap();
        let b = OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap();
        {
            let mut active = ActiveOwnedClient::enter(&mut c, &a).unwrap();
            match change {
                0 => active.user = json!({"id":"different-owner"}),
                1 => active.set_private_operation_gate(None),
                2 => active.session.as_mut().unwrap().paired_session_expires_at = Some(now_ms().saturating_sub(1)),
                _ => { active.cookies.insert("auth_refresh_token".into(), "unwitnessed".into()); },
            }
            assert!(active.check_active_owned_socket_start().is_err());
        }
        assert!(a.observer().check_release().is_err());
        assert!(b.observer().check_release().is_err());
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation,auth.session.authoritative-enforcement
#[test]
fn no_actual_owned_phase_keeps_legacy_socket_policy() {
    let c = client("https://example.invalid");
    assert!(c.active_owned_operation.is_none());
    c.check_active_owned_socket_start().expect("ordinary path unchanged");
}
