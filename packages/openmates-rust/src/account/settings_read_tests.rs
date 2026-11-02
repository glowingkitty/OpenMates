use super::*;
use crate::{Client, Session};
use std::collections::BTreeMap;
use tokio_util::sync::CancellationToken;
#[path = "../../tests/support/settings_reminders_fixture.rs"]
mod fixture;
fn session(origin: &str) -> Session {
    Session {
        api_url: origin.into(),
        session_id: "synthetic-settings-session".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "fixture".into())]),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([0; 32]),
        hashed_email: "synthetic".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 0,
        paired_session_expires_at: None,
        active_team_id: Some("00000000-0000-4000-8000-000000000001".into()),
    }
}
fn vectors() -> Value {
    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/sdk-conformance/fixtures/session-settings-reminders-read.json");
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn shared_reminders_vectors_preserve_raw_results_and_original_refusals() {
    for case in vectors()["cases"].as_array().unwrap().iter().take(20) {
        let (origin, peer) = fixture::peer(case).await;
        let creds = case["session"].as_bool().unwrap().then(|| session(&origin));
        let mut client = Client::new(&origin, creds).unwrap();
        let mut waits = Vec::new();
        let result = client
            .account()
            .reminders_with_wait(|delay| {
                waits.push(delay.as_millis() as u64);
                async {}
            })
            .await;
        let expected = &case["expected"];
        assert_eq!(
            serde_json::json!(waits),
            expected["wait_ms"],
            "{}",
            case["id"]
        );
        match result {
            Ok(value) => {
                assert_eq!(expected["ok"], true);
                assert_eq!(value, expected["value"], "{}", case["id"]);
            }
            Err(error) => {
                assert_eq!(expected["ok"], false, "{}", case["id"]);
                assert_eq!(
                    format!("{:?}", error.core_error()),
                    expected["error"].as_str().unwrap(),
                    "{}",
                    case["id"]
                );
                assert_eq!(
                    serde_json::json!(error.http_status()),
                    expected["http_status"],
                    "{}",
                    case["id"]
                );
                if let Some(status) = error.http_status() {
                    assert_eq!(
                        error.to_string(),
                        format!("Settings GET failed with HTTP {status}")
                    );
                }
            }
        }
        if case["id"] == "cookie-rotation-malformed-body"
            || case["id"] == "one-429-retry-cookie-preserved"
        {
            assert_eq!(
                client
                    .session()
                    .unwrap()
                    .cookies
                    .get("auth_refresh_token")
                    .map(String::as_str),
                Some("rotated")
            );
        }
        if case["id"] == "expired-malformed-body" || case["id"] == "owner-denial" {
            assert!(client.session().is_none());
        }
        assert_eq!(
            peer.await.unwrap() as u64,
            expected["requests"].as_u64().unwrap()
        );
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn cancelled_original_refuses_malformed_body_before_dispatch() {
    let case = serde_json::json!({"responses":[],"expected":{"requests":0}});
    let (origin, peer) = fixture::peer(&case).await;
    let mut client = Client::new(&origin, Some(session(&origin))).unwrap();
    let cancel = CancellationToken::new();
    client.set_operation_cancel(cancel.clone());
    cancel.cancel();
    let error = client.account().reminders().await.unwrap_err();
    assert_eq!(error.core_error(), Error::Cancelled);
    assert_eq!(error.http_status(), None);
    peer.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn cancel_during_retry_wait_never_sends_second_request() {
    let case = serde_json::json!({"responses":[{"status":429,"body":"{","headers":[]}],"expected":{"requests":1}});
    let (origin, peer) = fixture::peer(&case).await;
    let mut client = Client::new(&origin, Some(session(&origin))).unwrap();
    let cancel = CancellationToken::new();
    client.set_operation_cancel(cancel.clone());
    let mut waits = 0;
    let error = client
        .account()
        .reminders_with_wait(|delay| {
            assert_eq!(delay, RETRY_DELAY);
            waits += 1;
            cancel.cancel();
            std::future::pending::<()>()
        })
        .await
        .unwrap_err();
    assert_eq!(waits, 1);
    assert_eq!(error.core_error(), Error::Cancelled);
    assert_eq!(error.http_status(), None);
    peer.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn generic_transport_malformed_json_still_refuses() {
    let case = serde_json::json!({"responses":[{"status":200,"body":"{","headers":[]}],"expected":{"requests":1}});
    let (origin, peer) = fixture::peer(&case).await;
    let mut client = Client::new(&origin, Some(session(&origin))).unwrap();
    // Even the same route is strict through the ordinary transport entry point.
    assert_eq!(
        client
            .request(reqwest::Method::GET, "/v1/settings/reminders", None)
            .await,
        Err(Error::Protocol)
    );
    peer.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn cancelled_malformed_response_retains_cookie_header_but_refuses_output() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let cancel = CancellationToken::new();
    let peer_cancel = cancel.clone();
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut req = [0; 8192];
        assert!(socket.read(&mut req).await.unwrap() > 0);
        peer_cancel.cancel();
        socket.write_all(b"HTTP/1.1 200 OK\r\nSet-Cookie: auth_refresh_token=rotated; Path=/\r\nContent-Length: 1\r\nConnection: close\r\n\r\n{").await.unwrap();
    });
    let mut client = Client::new(&origin, Some(session(&origin))).unwrap();
    client.set_operation_cancel(cancel);
    let error = client.account().reminders().await.unwrap_err();
    assert_eq!(error.core_error(), Error::Cancelled);
    assert_eq!(error.http_status(), None);
    assert_eq!(
        client
            .session()
            .unwrap()
            .cookies
            .get("auth_refresh_token")
            .map(String::as_str),
        Some("rotated")
    );
    peer.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn truncated_malformed_body_is_transport_failure_not_empty_json() {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let peer = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut req = [0; 8192];
        assert!(socket.read(&mut req).await.unwrap() > 0);
        socket
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nConnection: close\r\n\r\n{")
            .await
            .unwrap();
    });
    let mut client = Client::new(&origin, Some(session(&origin))).unwrap();
    let error = client.account().reminders().await.unwrap_err();
    assert_eq!(error.core_error(), Error::Offline);
    assert_eq!(error.http_status(), None);
    peer.await.unwrap();
}
