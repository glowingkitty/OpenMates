//! Requires isolated product CI. These tests drive the actual existing auth
//! request, body validation and credential merge; they never construct receipts.
use super::*;
use super::super::owned_operation::OwnedOperationScope;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const OWNER: &str = "11111111-1111-4111-8111-111111111111";
async fn fixture(body: Value, cookie: bool) -> (Client, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut request = Vec::new();
        loop {
            let mut bytes = [0u8; 1024];
            let n = stream.read(&mut bytes).await.unwrap(); assert!(n > 0);
            request.extend_from_slice(&bytes[..n]); assert!(request.len() < 8192);
            if request.windows(4).any(|v| v == b"\r\n\r\n") { break; }
        }
        assert!(String::from_utf8_lossy(&request).starts_with("POST /v1/auth/session "));
        let body = body.to_string();
        let cookie = if cookie { "Set-Cookie: auth_refresh_token=rotated; Path=/\r\n" } else { "" };
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n{cookie}Content-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
    });
    let mut c = Client::new(&base, Some(Session { api_url: base.clone(), session_id: "fixture".into(),
        cookies: BTreeMap::new(), ws_token: Some("old-token".into()), master_key: zeroize::Zeroizing::new([7;32]),
        hashed_email: "fixture".into(), user_email_salt: String::new(), email_encryption_key: None,
        created_at: 1, paired_session_expires_at: None, active_team_id: None })).unwrap();
    c.user = json!({"id":OWNER});
    (c, server)
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn actual_success_token_rotation_with_or_without_cookie_preserves_original_siblings() {
    for cookie in [false, true] {
        let (mut c, server) = fixture(json!({"success":true,"ws_token":"fresh-token","user":{"id":OWNER}}), cookie).await;
        let a = OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap();
        let b = OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap();
        let parent = c.operation_parent.clone();
        let (tx, mut updates) = mpsc::unbounded_channel(); c.set_credential_updates(tx);
        while updates.try_recv().is_ok() {}
        c.validate_session().await.expect("existing real validation");
        assert_eq!(c.session().unwrap().ws_token.as_deref(), Some("fresh-token"));
        a.check(&c).expect("original A lineage"); b.check(&c).expect("original B lineage");
        assert_eq!(c.operation_parent, parent); assert!(!parent.is_cancelled());
        assert!(updates.try_recv().is_ok(), "existing credential durability publication");
        c.credentials_changed();
        assert!(a.check(&c).is_err()); assert!(b.observer().check_release().is_err());
        server.await.unwrap();
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn changed_success_principal_revokes_live_originals_after_real_credential_publication() {
    let (mut c, server) = fixture(json!({"success":true,"ws_token":"fresh-token","user":{"id":"different-owner"}}), false).await;
    let a = OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap();
    let b = OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap();
    let (tx, mut updates) = mpsc::unbounded_channel(); c.set_credential_updates(tx);
    while updates.try_recv().is_ok() {}
    assert_eq!(c.validate_session().await, Err(Error::Cancelled));
    assert_eq!(c.session().unwrap().ws_token.as_deref(), Some("fresh-token"));
    assert_eq!(c.user["id"], "different-owner");
    assert!(updates.try_recv().is_ok());
    assert!(a.observer().check_release().is_err()); assert!(b.observer().check_release().is_err());
    server.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn truly_empty_ordinary_auth_keeps_existing_principal_response_behavior() {
    let (mut c, server) = fixture(json!({"success":true,"ws_token":"fresh-token","user":{"id":"different-owner"}}), false).await;
    c.validate_session().await.unwrap();
    assert_eq!(c.session().unwrap().ws_token.as_deref(), Some("fresh-token"));
    assert_eq!(c.user["id"], "different-owner");
    server.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn failed_or_malformed_body_cannot_witness_token_transition() {
    for (case, body) in [json!({"success":false}), json!({"success":true,"user":{"id":OWNER}}),
        json!({"success":true,"ws_token":"fresh-token","user":{}})].into_iter().enumerate() {
        let (mut c, server) = fixture(body, false).await;
        let a = OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap();
        assert!(c.validate_session().await.is_err());
        if let Some(session) = c.session() { assert_eq!(session.ws_token.as_deref(), Some("old-token")); }
        if case == 1 { a.check(&c).expect("missing token performs no credential/body merge"); }
        else { assert!(a.check(&c).is_err()); assert!(a.observer().check_release().is_err()); }
        server.await.unwrap();
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn canceled_original_stays_canceled_while_success_durably_refreshes_healthy_sibling() {
    let (mut c, server) = fixture(json!({"success":true,"ws_token":"fresh-token","user":{"id":OWNER}}), true).await;
    let request = CancellationToken::new();
    let a = OwnedOperationScope::capture(&c, request.clone()).unwrap();
    let b = OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap();
    request.cancel();
    c.validate_session().await.unwrap();
    assert_eq!(c.session().unwrap().ws_token.as_deref(), Some("fresh-token"));
    assert_eq!(c.session().unwrap().cookies.get("auth_refresh_token").map(String::as_str), Some("rotated"));
    assert!(a.observer().check_release().is_err());
    b.check(&c).expect("healthy original sibling survives witnessed refresh");
    server.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn changed_success_username_cannot_rebase_original_owner_context() {
    let (mut c, server) = fixture(json!({"success":true,"ws_token":"fresh-token","user":{"id":OWNER,"username":"changed"}}), false).await;
    let a = OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap();
    assert_eq!(c.validate_session().await, Err(Error::Cancelled));
    assert_eq!(c.session().unwrap().ws_token.as_deref(), Some("fresh-token"));
    assert!(a.observer().check_release().is_err());
    server.await.unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sdk.encryption.local-only
#[tokio::test]
async fn malformed_success_user_revokes_live_peers_immediately_and_keeps_real_header_merge() {
    for live in [false, true] {
        let (mut c, server) = fixture(json!({"success":true,"ws_token":"fresh-token","user":{}}), true).await;
        let peers = if live {
            Some((OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap(),
                OwnedOperationScope::capture(&c, CancellationToken::new()).unwrap()))
        } else { None };
        assert_eq!(c.validate_session().await, Err(Error::Protocol));
        assert!(c.user.as_object().unwrap().is_empty());
        assert_eq!(c.session().unwrap().ws_token.as_deref(), Some("old-token"));
        assert_eq!(c.cookies.get("auth_refresh_token").map(String::as_str), Some("rotated"));
        assert_eq!(c.session().unwrap().cookies.get("auth_refresh_token").map(String::as_str), Some("rotated"));
        if let Some((a, b)) = &peers {
            // Negative-only observers must already refuse; no scope check or
            // external actor cleanup is allowed to cause this revocation.
            assert!(a.observer().check_release().is_err());
            assert!(b.observer().check_release().is_err());
        }
        c.user = json!({"id":OWNER});
        if let Some((a, b)) = &peers {
            assert!(a.observer().check_release().is_err());
            assert!(b.observer().check_release().is_err());
            assert!(a.check(&c).is_err()); assert!(b.check(&c).is_err());
        }
        server.await.unwrap();
    }
}
