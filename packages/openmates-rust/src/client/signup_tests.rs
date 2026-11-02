// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

/// Loopback HTTP double; the auth endpoints also set a refresh cookie.
async fn mock(responses: Vec<Value>) -> (String, tokio::task::JoinHandle<Vec<String>>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api = format!("http://{}", listener.local_addr().unwrap());
    let handle = tokio::spawn(async move {
        let mut requests = vec![];
        for body in responses {
            let (mut socket, _) = listener.accept().await.unwrap();
            let mut buf = Vec::new();
            loop {
                let mut bytes = [0; 8192];
                let n = socket.read(&mut bytes).await.unwrap();
                assert!(n > 0);
                buf.extend_from_slice(&bytes[..n]);
                if let Some(end) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                    let head = String::from_utf8_lossy(&buf[..end]).to_ascii_lowercase();
                    let size = head
                        .lines()
                        .find_map(|l| {
                            l.strip_prefix("content-length:")
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
            socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=signup-cookie; Path=/; HttpOnly\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
        }
        requests
    });
    (api, handle)
}
fn body(request: &str) -> Value {
    serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap()
}

#[tokio::test]
async fn signup_sends_only_hashes_and_wrapped_keys_then_installs_the_session() {
    let (api, server) = mock(vec![
        json!({"success":true}),
        json!({"success":true,"signup_transaction_token":"txn"}),
        json!({"success":true,"message":"Account created.","user":{"id":"new-user","username":"alice"}}),
        json!({"success":true,"secret":"JBSWY3DPEHPK3PXP","otpauth_url":"otpauth://totp/x"}),
        json!({"success":true}),
        json!({"success":true}),
        json!({"success":true,"backup_codes":["one","two"]}),
        json!({"success":true}),
        json!({"success":true}),
    ])
    .await;
    let mut client = Client::new(&api, None).unwrap();
    let password = "correct horse battery staple";
    client
        .request_signup_email_code(" Alice@Example.org", "INVITE", "en")
        .await
        .unwrap();
    let verified = client
        .verify_signup_email_code("Alice@Example.org", "alice", "INVITE", "123456", "en")
        .await
        .unwrap();
    let token = verified["signup_transaction_token"]
        .as_str()
        .unwrap()
        .to_owned();
    let created = client
        .setup_password_account(
            SignupAccount {
                email: " Alice@Example.org",
                username: "alice",
                password,
                invite_code: "INVITE",
                language: "en",
            },
            Some(&token),
        )
        .await
        .unwrap();
    assert_eq!(created["user"]["id"], "new-user");
    let session = client.session().unwrap().clone();
    assert_eq!(
        session.hashed_email,
        crypto::hash_email("alice@example.org")
    );
    assert_eq!(
        session
            .cookies
            .get("auth_refresh_token")
            .map(String::as_str),
        Some("signup-cookie")
    );
    assert_eq!(client.user()["id"], "new-user");
    let setup = client.start_totp_setup().await.unwrap();
    assert_eq!(setup["secret"], "JBSWY3DPEHPK3PXP");
    client.verify_totp_setup("654321").await.unwrap();
    client.set_totp_provider("Authenticator app").await.unwrap();
    let codes = client.request_backup_codes().await.unwrap();
    assert_eq!(
        codes.iter().map(|c| c.as_str()).collect::<Vec<_>>(),
        ["one", "two"]
    );
    client.confirm_backup_codes_stored().await.unwrap();
    let recovery = client.create_and_confirm_recovery_key().await.unwrap();
    let requests = server.await.unwrap();
    let lines = requests
        .iter()
        .map(|r| r.lines().next().unwrap().to_owned())
        .collect::<Vec<_>>();
    for (line, expected) in lines.iter().zip([
        "POST /v1/auth/request_confirm_email_code ",
        "POST /v1/auth/check_confirm_email_code ",
        "POST /v1/auth/setup_password ",
        "POST /v1/auth/2fa/setup/initiate ",
        "POST /v1/auth/2fa/setup/verify-signup ",
        "POST /v1/auth/2fa/setup/provider ",
        "GET /v1/auth/2fa/setup/request-backup-codes ",
        "POST /v1/auth/2fa/setup/confirm-codes-stored ",
        "POST /v1/auth/recovery-key/confirm-stored ",
    ]) {
        assert!(line.starts_with(expected), "{line} != {expected}");
    }
    assert_eq!(body(&requests[0])["email"], "alice@example.org");
    assert_eq!(
        body(&requests[0])["hashed_email"],
        crypto::hash_email("alice@example.org")
    );
    let setup = body(&requests[2]);
    assert_eq!(setup["credential_version"], 2);
    assert_eq!(setup["signup_transaction_token"], "txn");
    assert!(!requests[2].contains(password));
    assert!(!requests[2].contains("alice@example.org"));
    // The server-held wrapper opens to the locally installed master key.
    let opened = crypto::unwrap_password_master_key(
        password,
        2,
        setup["encrypted_master_key"].as_str().unwrap(),
        setup["salt"].as_str().unwrap(),
        setup["key_iv"].as_str().unwrap(),
    )
    .unwrap();
    assert_eq!(opened.as_ref(), session.master_key.as_ref());
    assert_eq!(
        body(&requests[3])["email_encryption_key"],
        session.email_encryption_key.clone().unwrap()
    );
    let stored = body(&requests[8]);
    assert_eq!(stored["lookup_hash"], recovery.lookup_hash);
    assert!(!requests[8].contains(recovery.recovery_key.as_str()));
}

#[tokio::test]
async fn server_rejections_keep_their_message_and_existing_sessions_are_refused() {
    let (api, server) = mock(vec![
        json!({"success":false,"message":"Invalid invite code."}),
    ])
    .await;
    let mut client = Client::new(&api, None).unwrap();
    assert_eq!(
        client
            .request_signup_email_code("a@example.org", "bad", "en")
            .await,
        Err(SignupError::Rejected("Invalid invite code.".into()))
    );
    server.await.unwrap();
    let (api, server) = mock(vec![json!({"message":"no success flag"})]).await;
    let mut client = Client::new(&api, None).unwrap();
    let result = client
        .setup_password_account(
            SignupAccount {
                email: "a@example.org",
                username: "a",
                password: "pw",
                invite_code: "",
                language: "en",
            },
            None,
        )
        .await;
    assert_eq!(
        result.err(),
        Some(SignupError::Rejected("no success flag".into()))
    );
    assert!(client.session().is_none());
    server.await.unwrap();
    let session = Session {
        api_url: "http://127.0.0.1:1".into(),
        session_id: "s".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: zeroize::Zeroizing::new([1; 32]),
        hashed_email: "h".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 0,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut existing = Client::new("http://127.0.0.1:1", Some(session)).unwrap();
    assert!(matches!(
        existing
            .request_signup_email_code("a@example.org", "", "en")
            .await,
        Err(SignupError::Core(Error::Invalid(_)))
    ));
}
