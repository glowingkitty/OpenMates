//! Session verification: the shared classifier of unsuccessful session bodies and the native client keeping its session for device verification and re-auth, answering a two-factor check and still forgetting a plainly rejected session.
use super::*;
use crate::session::Session;
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const OWNER: &str = "11111111-1111-4111-8111-111111111111";

/// Answers for the loopback API: the current session body and whether the
/// device code is accepted. Records each request line and body.
#[derive(Default)]
struct Api {
    session: Mutex<Value>,
    accept_code: Mutex<bool>,
    seen: Mutex<Vec<(String, Value)>>,
}

async fn read(stream: &mut tokio::net::TcpStream) -> (String, Value) {
    let mut bytes = Vec::new();
    let mut buffer = [0u8; 4096];
    loop {
        let n = stream.read(&mut buffer).await.unwrap();
        bytes.extend_from_slice(&buffer[..n]);
        let text = String::from_utf8_lossy(&bytes).to_string();
        if let Some((head, body)) = text.split_once("\r\n\r\n") {
            let length = head
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|v| v.trim().parse::<usize>().unwrap())
                })
                .unwrap_or(0);
            if body.len() >= length || n == 0 {
                let line = head.lines().next().unwrap_or_default().to_owned();
                return (line, serde_json::from_str(body).unwrap_or(Value::Null));
            }
        }
        if n == 0 {
            return (String::new(), Value::Null);
        }
    }
}

async fn serve(api: Arc<Api>) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    tokio::spawn(async move {
        while let Ok((mut stream, _)) = listener.accept().await {
            let (line, body) = read(&mut stream).await;
            api.seen.lock().unwrap().push((line.clone(), body));
            let reply = if line.starts_with("POST /v1/auth/session ") {
                api.session.lock().unwrap().clone()
            } else if line.starts_with("POST /v1/auth/2fa/verify/device ") {
                json!({"success": *api.accept_code.lock().unwrap(), "message": "synthetic"})
            } else {
                json!({})
            };
            let body = reply.to_string();
            let head = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            let _ = stream.write_all(head.as_bytes()).await;
            let _ = stream.write_all(body.as_bytes()).await;
        }
    });
    base
}

fn client(base: &str) -> Client {
    let mut cookies = BTreeMap::new();
    cookies.insert("auth_refresh_token".into(), "cookie".into());
    Client::new(
        base,
        Some(Session {
            api_url: base.into(),
            session_id: "session".into(),
            cookies,
            ws_token: Some("old".into()),
            master_key: zeroize::Zeroizing::new([7; 32]),
            hashed_email: "owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}

fn admitted() -> Value {
    json!({"success": true, "ws_token": "fresh", "user": {"id": OWNER, "username": "Synthetic"}})
}

#[test]
fn classifies_device_verification_reauth_and_plain_rejection() {
    let two = json!({"success": false, "re_auth_required": "2fa", "re_auth_reason": "location_change",
        "password_fallback_available": true});
    assert_eq!(
        SessionVerification::of_unsuccessful_session(&two),
        Some(SessionVerification::Device {
            method: DeviceVerificationMethod::TwoFactor,
            reason: "location_change".into(),
            password_fallback_available: false,
        })
    );
    let passkey = json!({"success": false, "re_auth_required": "passkey", "re_auth_reason": "",
        "password_fallback_available": true});
    assert_eq!(
        SessionVerification::of_unsuccessful_session(&passkey),
        Some(SessionVerification::Device {
            method: DeviceVerificationMethod::Passkey,
            reason: "new_device".into(),
            password_fallback_available: true,
        })
    );
    let truthy_only =
        json!({"success": false, "re_auth_required": "passkey", "password_fallback_available": 1});
    assert!(matches!(
        SessionVerification::of_unsuccessful_session(&truthy_only),
        Some(SessionVerification::Device {
            password_fallback_available: false,
            ..
        })
    ));
    let reauth = json!({"success": false, "re_auth_reason": "session_verification"});
    assert_eq!(
        SessionVerification::of_unsuccessful_session(&reauth),
        Some(SessionVerification::ReAuth {
            reason: "session_verification".into()
        })
    );
    assert_eq!(
        SessionVerification::of_unsuccessful_session(&json!({"success": false})),
        None
    );
}

#[test]
fn web_classifier_keeps_its_deployed_device_decision() {
    let reply = |body: Value| crate::web_auth::HttpReply {
        status: 200,
        body: Some(body),
    };
    let decision = crate::web_auth::classify_session(reply(
        json!({"success": false, "re_auth_required": "passkey",
        "password_fallback_available": true, "password_credential_version": 2}),
    ));
    assert!(
        matches!(decision, crate::web_auth::SessionDecision::DeviceVerification {
        ref verification, ref reason, password_fallback_available: true, ref password_credential_version, ..
    } if verification == "passkey" && reason == "new_device" && *password_credential_version == json!(2))
    );
    // A bare re-auth request stays unauthenticated on the web path.
    let decision = crate::web_auth::classify_session(reply(
        json!({"success": false, "re_auth_reason": "session_verification"}),
    ));
    assert!(matches!(
        decision,
        crate::web_auth::SessionDecision::Unauthenticated { .. }
    ));
}

// contract-test: supporting surface=sdks.rust assertions=client-core.shell.allowed-responsibilities
#[tokio::test]
async fn device_verification_keeps_the_session_and_a_good_code_clears_it() {
    let api = Arc::new(Api::default());
    *api.session.lock().unwrap() = json!({"success": false, "message": "Device verification required",
        "re_auth_required": "2fa", "re_auth_reason": "new_device", "user": {"id": OWNER}});
    let base = serve(api.clone()).await;
    let mut client = client(&base);
    assert_eq!(
        client.validate_session().await,
        Err(Error::VerificationRequired)
    );
    // The server kept the session: so does the client, without its profile.
    assert!(client.session().is_some());
    assert_eq!(client.user(), &Value::Null);
    assert!(matches!(
        client.session_verification(),
        Some(SessionVerification::Device {
            method: DeviceVerificationMethod::TwoFactor,
            ..
        })
    ));
    // Malformed codes are refused before any request.
    let before = api.seen.lock().unwrap().len();
    assert!(matches!(
        client.verify_device_2fa("12 34").await,
        Err(Error::Invalid(_))
    ));
    assert_eq!(api.seen.lock().unwrap().len(), before);
    // A refused code is an authentication error and stays pending.
    assert_eq!(
        client.verify_device_2fa("000000").await,
        Err(Error::Authentication)
    );
    assert!(client.session_verification().is_some() && client.session().is_some());
    *api.accept_code.lock().unwrap() = true;
    client.verify_device_2fa("123456").await.unwrap();
    assert!(client.session_verification().is_none());
    let sent = api
        .seen
        .lock()
        .unwrap()
        .iter()
        .filter(|(line, _)| line.starts_with("POST /v1/auth/2fa/verify/device "))
        .last()
        .cloned()
        .unwrap();
    assert_eq!(sent.1, json!({"tfa_code": "123456"}));
    // The next check admits.
    *api.session.lock().unwrap() = admitted();
    client.validate_session().await.unwrap();
    assert_eq!(client.user()["id"], OWNER);
    assert!(client.session_verification().is_none());
}

// contract-test: supporting surface=sdks.rust assertions=client-core.shell.allowed-responsibilities
#[tokio::test]
async fn reauth_keeps_the_session_and_a_plain_rejection_forgets_it() {
    let api = Arc::new(Api::default());
    *api.session.lock().unwrap() =
        json!({"success": false, "re_auth_reason": "session_verification"});
    let base = serve(api.clone()).await;
    let mut client = client(&base);
    assert_eq!(
        client.validate_session().await,
        Err(Error::VerificationRequired)
    );
    assert!(client.session().is_some());
    assert_eq!(
        client.session_verification(),
        Some(&SessionVerification::ReAuth {
            reason: "session_verification".into()
        })
    );
    // No factor can answer a re-auth request.
    assert!(matches!(
        client.verify_device_2fa("123456").await,
        Err(Error::Invalid(_))
    ));
    *api.session.lock().unwrap() = json!({"success": false});
    assert_eq!(client.validate_session().await, Err(Error::Expired));
    assert!(client.session().is_none() && client.session_verification().is_none());
}
