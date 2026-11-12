//! Native passkey sign-in and passkey device verification against a loopback API with a synthetic PRF output and a master key wrapped by the crate's own helpers: success admits with the PRF-derived lookup hash, refusals and a missing PRF are typed and send nothing further, and device verification clears or keeps the pending request.
use super::*;
use crate::session::Session;
use std::sync::{Arc, Mutex};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const EMAIL: &str = "synthetic@example.org";
const CHALLENGE: &str = "c3ludGhldGljLWNoYWxsZW5nZS0wMDAwMDAwMDAwMDA";
const CREDENTIAL: &str = "c3ludGhldGljLWNyZWRlbnRpYWw";
const PRF: [u8; 32] = [0x42; 32];
const SALT: [u8; 16] = [9; 16];
const MASTER: [u8; 32] = [5; 32];

/// How one request is answered: the JSON body and whether the reply sets the
/// refresh cookie.
type Route = dyn Fn(&str, &Value) -> (Value, bool) + Send + Sync;

/// A loopback API answering by `route` and recording each request.
struct Api {
    base: String,
    seen: Arc<Mutex<Vec<(String, Value)>>>,
}

impl Api {
    fn bodies(&self, path: &str) -> Vec<Value> {
        let prefix = format!("POST {path} ");
        self.seen
            .lock()
            .unwrap()
            .iter()
            .filter(|(line, _)| line.starts_with(&prefix))
            .map(|(_, body)| body.clone())
            .collect()
    }
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

async fn serve(route: Box<Route>) -> Api {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let seen = Arc::new(Mutex::new(Vec::new()));
    let log = seen.clone();
    tokio::spawn(async move {
        while let Ok((mut stream, _)) = listener.accept().await {
            let (line, body) = read(&mut stream).await;
            log.lock().unwrap().push((line.clone(), body.clone()));
            let (reply, cookie) = route(&line, &body);
            let body = reply.to_string();
            let cookie = if cookie {
                "Set-Cookie: auth_refresh_token=synthetic-refresh; Path=/\r\n"
            } else {
                ""
            };
            let head = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n{cookie}Content-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            let _ = stream.write_all(head.as_bytes()).await;
            let _ = stream.write_all(body.as_bytes()).await;
        }
    });
    Api { base, seen }
}

fn options() -> Value {
    json!({"success": true, "challenge": CHALLENGE, "rp": {"id": "example.org", "name": "OpenMates"},
        "timeout": 60000, "allowCredentials": [], "userVerification": "required",
        "extensions": {"prf": {"eval": {"first": "c3ludGhldGljLXByZi1zYWx0"}}}})
}

/// The account's passkey wrapper, built with the crate's own helpers.
fn verified(email: &str) -> Value {
    let wrapping = crypto::web_formats::passkey_wrapping_key(&PRF, &SALT).unwrap();
    let (key, iv) = crypto::wrap_master_key_with_wrapping_key(&MASTER, &wrapping).unwrap();
    json!({"success": true, "message": "Passkey verified. Please complete authentication.",
        "user_id": OWNER, "hashed_email": crypto::hash_email(email),
        "encrypted_email": crypto::encrypt_bytes(email.as_bytes(), &MASTER).unwrap(),
        "encrypted_master_key": key, "key_iv": iv, "salt": null,
        "user_email_salt": STANDARD.encode(SALT), "user_email": null, "auth_session": null})
}

fn expected_lookup_hash() -> String {
    let mut input = PRF.to_vec();
    input.extend_from_slice(&SALT);
    STANDARD.encode(sha2::Sha256::digest(&input))
}

/// The passkey account: initiate, verify answering `verify`, and a login
/// that accepts only the PRF-derived lookup hash of the verified session.
async fn login_api(verify: Value) -> Api {
    serve(Box::new(move |line, body| {
        let path = line.split(' ').nth(1).unwrap_or_default();
        match path {
            "/v1/auth/passkey/assertion/initiate" => (options(), false),
            "/v1/auth/passkey/assertion/verify" => (verify.clone(), false),
            "/v1/auth/login" => {
                if body["login_method"] != "passkey" || body["lookup_hash"] != expected_lookup_hash() || body["credential_id"] != CREDENTIAL {
                    return (json!({"success": false, "message": "login.failed"}), false);
                }
                (json!({"success": true, "ws_token": "synthetic", "user": {"id": OWNER, "username": "Synthetic",
                    "user_email_salt": STANDARD.encode(SALT)}}), true)
            }
            "/v1/auth/logout" => (json!({"success": true}), false),
            _ => (json!({}), false),
        }
    }))
    .await
}

fn assertion(challenge: &str) -> Vec<u8> {
    let client_data =
        json!({"type": "webauthn.get", "challenge": challenge, "origin": "https://example.org"});
    serde_json::to_vec(&json!({"credential_id": CREDENTIAL,
        "client_data_json": STANDARD.encode(client_data.to_string()),
        "authenticator_data": STANDARD.encode([1u8; 37]), "signature": STANDARD.encode([2u8; 70]),
        "user_handle": STANDARD.encode(OWNER)}))
    .unwrap()
}

fn stay() -> PasswordLoginOptions {
    PasswordLoginOptions {
        stay_logged_in: true,
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.keys.independent-unlock,auth.keys.client-wrapped
#[tokio::test]
async fn passkey_login_unwraps_with_the_prf_output_and_signs_in_with_the_lookup_hash() {
    let api = login_api(verified(EMAIL)).await;
    let mut client = Client::new(&api.base, None).unwrap();
    let challenge = client.passkey_login_begin(None).await.unwrap();
    let options_json: Value = serde_json::from_slice(&challenge.options_json).unwrap();
    assert_eq!(options_json["rp"]["id"], "example.org");
    client
        .passkey_login_finish(challenge.continuation, &assertion(CHALLENGE), &PRF, stay())
        .await
        .unwrap();
    let session = client.session().unwrap();
    assert_eq!(*session.master_key, MASTER);
    assert_eq!(session.hashed_email, crypto::hash_email(EMAIL));
    assert_eq!(session.user_email_salt, STANDARD.encode(SALT));
    assert_eq!(client.user()["id"], OWNER);
    // Discoverable credential: no account hint; verify and login share one session id.
    assert_eq!(
        api.bodies("/v1/auth/passkey/assertion/initiate"),
        [json!({})]
    );
    let verify = &api.bodies("/v1/auth/passkey/assertion/verify")[0];
    let login = &api.bodies("/v1/auth/login")[0];
    assert!(verify.get("hashed_email").is_none() && verify.get("email_encryption_key").is_none());
    assert_eq!(
        verify["assertion_response"]["userHandle"],
        STANDARD.encode(OWNER)
    );
    assert_eq!(verify["stay_logged_in"], true);
    assert_eq!(verify["session_id"], login["session_id"]);
    assert_eq!(session.session_id, login["session_id"].as_str().unwrap());
    assert_eq!(
        login["email_encryption_key"],
        crypto::derive_email_key(EMAIL, &STANDARD.encode(SALT)).unwrap()
    );
    // The PRF output itself never leaves the core.
    let prf = STANDARD.encode(PRF);
    assert!(
        api.seen
            .lock()
            .unwrap()
            .iter()
            .all(|(_, body)| !body.to_string().contains(&prf))
    );
}

#[tokio::test]
async fn a_refused_verification_is_authentication_and_never_logs_in() {
    let api = login_api(
        json!({"success": false, "message": "Passkey verification failed. Invalid signature."}),
    )
    .await;
    let mut client = Client::new(&api.base, None).unwrap();
    let challenge = client.passkey_login_begin(None).await.unwrap();
    assert_eq!(
        client
            .passkey_login_finish(challenge.continuation, &assertion(CHALLENGE), &PRF, stay())
            .await,
        Err(Error::Authentication)
    );
    assert!(client.session().is_none());
    assert!(api.bodies("/v1/auth/login").is_empty());
}

#[tokio::test]
async fn a_missing_prf_output_is_typed_and_sends_nothing() {
    let api = login_api(verified(EMAIL)).await;
    let mut client = Client::new(&api.base, None).unwrap();
    for prf in [&[][..], &[1u8; 15][..], &[1u8; 65][..]] {
        let challenge = client.passkey_login_begin(None).await.unwrap();
        assert_eq!(
            client
                .passkey_login_finish(challenge.continuation, &assertion(CHALLENGE), prf, stay())
                .await,
            Err(Error::Invalid(PASSKEY_PRF_UNAVAILABLE))
        );
    }
    assert!(api.bodies("/v1/auth/passkey/assertion/verify").is_empty());
}

#[tokio::test]
async fn an_assertion_of_another_challenge_is_refused_before_any_request() {
    let api = login_api(verified(EMAIL)).await;
    let mut client = Client::new(&api.base, None).unwrap();
    let challenge = client.passkey_login_begin(None).await.unwrap();
    assert_eq!(
        client
            .passkey_login_finish(
                challenge.continuation,
                &assertion("b3RoZXItY2hhbGxlbmdl"),
                &PRF,
                stay()
            )
            .await,
        Err(Error::Invalid(PASSKEY_OTHER_REQUEST))
    );
    let challenge = client.passkey_login_begin(None).await.unwrap();
    assert!(matches!(
        client
            .passkey_login_finish(
                challenge.continuation,
                b"{\"credential_id\":1}",
                &PRF,
                stay()
            )
            .await,
        Err(Error::Invalid(_))
    ));
    assert!(api.bodies("/v1/auth/passkey/assertion/verify").is_empty());
}

#[tokio::test]
async fn another_accounts_passkey_is_typed_from_the_server_and_from_the_email_hint() {
    let api = login_api(json!({"success": false, "message": PASSKEY_WRONG_ACCOUNT})).await;
    let mut client = Client::new(&api.base, None).unwrap();
    let challenge = client
        .passkey_login_begin(Some(" Synthetic@Example.org "))
        .await
        .unwrap();
    assert_eq!(
        client
            .passkey_login_finish(challenge.continuation, &assertion(CHALLENGE), &PRF, stay())
            .await,
        Err(Error::Invalid(PASSKEY_WRONG_ACCOUNT))
    );
    let hint = json!({"hashed_email": crypto::hash_email(EMAIL)});
    assert_eq!(
        api.bodies("/v1/auth/passkey/assertion/initiate"),
        [hint.clone()]
    );
    assert_eq!(
        api.bodies("/v1/auth/passkey/assertion/verify")[0]["hashed_email"],
        hint["hashed_email"]
    );
    // A server that unlocks another account than the hint is refused locally.
    let api = login_api(verified("other@example.org")).await;
    let mut client = Client::new(&api.base, None).unwrap();
    let challenge = client.passkey_login_begin(Some(EMAIL)).await.unwrap();
    assert_eq!(
        client
            .passkey_login_finish(challenge.continuation, &assertion(CHALLENGE), &PRF, stay())
            .await,
        Err(Error::Invalid(PASSKEY_WRONG_ACCOUNT))
    );
    assert!(client.session().is_none() && api.bodies("/v1/auth/login").is_empty());
}

#[tokio::test]
async fn a_wrapper_that_does_not_open_with_the_prf_key_is_a_crypto_error() {
    let api = login_api(verified(EMAIL)).await;
    let mut client = Client::new(&api.base, None).unwrap();
    let challenge = client.passkey_login_begin(None).await.unwrap();
    assert_eq!(
        client
            .passkey_login_finish(
                challenge.continuation,
                &assertion(CHALLENGE),
                &[0x43; 32],
                stay()
            )
            .await,
        Err(Error::Crypto)
    );
    assert!(client.session().is_none() && api.bodies("/v1/auth/login").is_empty());
}

/// A signed-in client whose session check asks for a passkey; the device
/// check accepts only `CREDENTIAL` while `accept` holds.
async fn device_api(accept: Arc<Mutex<bool>>) -> Api {
    serve(Box::new(move |line, body| {
        let path = line.split(' ').nth(1).unwrap_or_default();
        match path {
            "/v1/auth/session" => (json!({"success": false, "re_auth_required": "passkey", "re_auth_reason": "new_device"}), false),
            "/v1/auth/passkey/assertion/initiate" => (options(), false),
            "/v1/auth/passkey/verify/device" => {
                if !*accept.lock().unwrap() {
                    return (json!({"success": false, "message": PASSKEY_WRONG_ACCOUNT}), false);
                }
                (json!({"success": body["credential_id"] == CREDENTIAL, "message": "synthetic"}), false)
            }
            _ => (json!({}), false),
        }
    }))
    .await
}

fn signed_in(base: &str) -> Client {
    let mut cookies = BTreeMap::new();
    cookies.insert("auth_refresh_token".into(), "cookie".into());
    Client::new(
        base,
        Some(Session {
            api_url: base.into(),
            session_id: "synthetic-session".into(),
            cookies,
            ws_token: Some("old".into()),
            master_key: zeroize::Zeroizing::new(MASTER),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        }),
    )
    .unwrap()
}

// contract-test: supporting surface=sdks.rust assertions=client-core.shell.allowed-responsibilities
#[tokio::test]
async fn passkey_device_verification_clears_on_success_and_stays_pending_on_refusal() {
    let accept = Arc::new(Mutex::new(false));
    let api = device_api(accept.clone()).await;
    let mut client = signed_in(&api.base);
    // Nothing pending yet: refused without a request.
    assert!(matches!(
        client.passkey_device_verification_begin().await,
        Err(Error::Invalid(_))
    ));
    assert_eq!(
        client.validate_session().await,
        Err(Error::VerificationRequired)
    );
    let challenge = client.passkey_device_verification_begin().await.unwrap();
    assert_eq!(
        api.bodies("/v1/auth/passkey/assertion/initiate"),
        [json!({"hashed_email": "synthetic-owner"})]
    );
    assert_eq!(
        client
            .passkey_device_verification_finish(challenge.continuation, &assertion(CHALLENGE))
            .await,
        Err(Error::Invalid(PASSKEY_WRONG_ACCOUNT))
    );
    assert!(client.session_verification().is_some() && client.session().is_some());
    // A login continuation never answers a device verification.
    let login = client.passkey_login_begin(None).await.unwrap();
    assert_eq!(
        client
            .passkey_device_verification_finish(login.continuation, &assertion(CHALLENGE))
            .await,
        Err(Error::Invalid(PASSKEY_OTHER_REQUEST))
    );
    *accept.lock().unwrap() = true;
    let challenge = client.passkey_device_verification_begin().await.unwrap();
    client
        .passkey_device_verification_finish(challenge.continuation, &assertion(CHALLENGE))
        .await
        .unwrap();
    assert!(client.session_verification().is_none());
    let sent = api.bodies("/v1/auth/passkey/verify/device");
    assert_eq!(sent.len(), 2);
    assert_eq!(sent[1]["session_id"], "synthetic-session");
    assert_eq!(
        sent[1]["authenticator_data"],
        sent[1]["assertion_response"]["authenticatorData"]
    );
}
