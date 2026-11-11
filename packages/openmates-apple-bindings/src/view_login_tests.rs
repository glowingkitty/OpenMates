//! ViewModelCore core-performed login against a loopback API built from the core's synthetic password-v2 vector (`tests/crypto_fixtures/account.json`): password success hands over and starts, wrong password and missing second factor store nothing, a signed-in core refuses another login, and the pair login steps up to the key bundle.
use crate::test_api::{LoopbackApi, Reply, serve};
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::core;
use crate::*;
use openmates_sdk::session::Session;
use serde_json::{Value, json};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

const USER: &str = "synthetic-user";
const PAIR_TOKEN: &str = "SYNTH4";
const PIN: &str = "W4P3KQ";

fn vector() -> Value {
    serde_json::from_str(include_str!(
        "../../openmates-rust/tests/crypto_fixtures/account.json"
    ))
    .unwrap()
}

fn admitted_reply() -> Reply {
    Reply::Json(json!({"success": true, "ws_token": "synthetic",
        "user": {"id": USER, "username": "Synthetic Tester"}}))
}

/// The password endpoints of the vector account. With `tfa`, the login
/// asks for a second factor until a code is sent.
async fn password_api(tfa: bool) -> LoopbackApi {
    let v = vector();
    serve(move |line, body| {
        let path = line.split(' ').nth(1).unwrap_or_default();
        match (line.split(' ').next().unwrap_or_default(), path) {
            ("POST", "/v1/auth/session") => admitted_reply(),
            ("POST", "/v1/auth/lookup") => {
                Reply::Json(json!({"user_email_salt": v["password_v2_salt"]}))
            }
            ("POST", "/v1/auth/password-v2/challenge") => {
                Reply::Json(json!({"challenge_id": "synthetic-challenge", "nonce": v["nonce_v2"]}))
            }
            ("POST", "/v1/auth/login") => {
                if tfa && body["tfa_code"].is_null() {
                    return Reply::Json(json!({"success": false, "tfa_required": true}));
                }
                if body["password_proof"] != v["login_proof_v2"] {
                    return Reply::Json(json!({"success": false}));
                }
                Reply::JsonWithCookie(json!({"success": true, "ws_token": "synthetic",
                    "user": {"id": USER, "credential_version": 2,
                        "user_email_salt": v["password_v2_salt"], "salt": v["password_v2_salt"],
                        "encrypted_key": v["password_v2_wrapped_master"], "key_iv": v["iv"]}}))
            }
            _ => Reply::Close,
        }
    })
    .await
}

/// An empty Keychain stand-in that stores and acknowledges.
fn acknowledging() -> Arc<Keychain> {
    Arc::new(Keychain {
        acknowledge: true,
        ..Keychain::default()
    })
}

fn stored(keychain: &Keychain) -> Option<Session> {
    let payload = keychain.payload.lock().unwrap().clone()?;
    Some(serde_json::from_slice(&payload).unwrap())
}

fn admitted(events: &[ViewEventRecord]) -> bool {
    events.iter().any(|event| {
        matches!(
            event,
            ViewEventRecord::Session {
                event: SessionEventRecord::Admitted { .. }
            }
        )
    })
}

#[tokio::test(flavor = "multi_thread")]
async fn password_login_stores_acknowledges_and_starts_the_session() {
    let (dir, v) = (private_dir(), vector());
    let api = password_api(false).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let (email, password) = (
        v["email"].as_str().unwrap(),
        v["password_v2"].as_str().unwrap(),
    );
    core.login_password(email.into(), password.into(), None, false, None)
        .await
        .unwrap();
    // Stored through the Keychain and acknowledged; the master key is the
    // vector's, unwrapped in the core.
    let session = stored(&keychain).expect("session stored");
    assert_eq!(keychain.changed.lock().unwrap().len(), 1);
    assert_eq!(
        openmates_sdk::crypto::encode_key(&session.master_key),
        v["legacy_master"].as_str().unwrap()
    );
    assert_eq!(session.cookies["auth_refresh_token"], "synthetic-refresh");
    // A fresh profile has no cached index, so `start` emits no `Restored`
    // or cached list: only the admitted session (`bootSync` reads the list).
    assert_eq!(
        events.all(),
        [ViewEventRecord::Session {
            event: SessionEventRecord::Admitted {
                username: "Synthetic Tester".into(),
                expires_at: None
            }
        }]
    );
    // Signed in: another login is refused before any request.
    let lookups = api.count("POST /v1/auth/lookup ");
    assert!(matches!(
        core.login_password(email.into(), password.into(), None, false, None)
            .await,
        Err(CoreError::Invalid { .. })
    ));
    assert!(matches!(
        core.begin_pair_login().await,
        Err(CoreError::Invalid { .. })
    ));
    assert_eq!(api.count("POST /v1/auth/lookup "), lookups);
    // A later start restores the stored session.
    core.start(None).await.unwrap();
    assert!(admitted(&events.all()));
}

#[tokio::test(flavor = "multi_thread")]
async fn wrong_password_is_an_authentication_error_and_stores_nothing() {
    let (dir, v) = (private_dir(), vector());
    let api = password_api(false).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let email = v["email"].as_str().unwrap();
    assert_eq!(
        core.login_password(
            email.into(),
            "Wrong Synthetic Password".into(),
            None,
            true,
            None
        )
        .await,
        Err(CoreError::Authentication)
    );
    assert!(stored(&keychain).is_none());
    assert!(keychain.changed.lock().unwrap().is_empty());
    assert!(events.all().is_empty());
    // Still signed out.
    core.start(None).await.unwrap();
    assert_eq!(events.all(), [crate::view_core_tests::SIGNED_OUT]);
}

#[tokio::test(flavor = "multi_thread")]
async fn a_missing_second_factor_is_reported_and_the_code_completes_the_login() {
    let (dir, v) = (private_dir(), vector());
    let api = password_api(true).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let (email, password) = (
        v["email"].as_str().unwrap(),
        v["password_v2"].as_str().unwrap(),
    );
    assert_eq!(
        core.login_password(email.into(), password.into(), None, false, None)
            .await,
        Err(CoreError::TwoFactorRequired)
    );
    assert!(stored(&keychain).is_none());
    core.login_password(
        email.into(),
        password.into(),
        Some("123456".into()),
        false,
        None,
    )
    .await
    .unwrap();
    assert!(stored(&keychain).is_some());
    assert!(admitted(&events.all()));
}

/// Pair relay up to the key bundle: `approved` once `approve` is set, then
/// `pending` while the authorizer has not answered the PIN request.
async fn pair_api(approve: Arc<AtomicBool>) -> LoopbackApi {
    let context: Arc<Mutex<Value>> = Arc::default();
    let expires = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + 600;
    serve(move |line, body| {
        let receiver = format!("GET /v1/auth/pair/v2/receiver/{PAIR_TOKEN} ");
        if line.starts_with("POST /v1/auth/pair/v2/initiate ") {
            *context.lock().unwrap() = json!({"session_id": body["session_id"],
                "receiver_token_hash": body["receiver_token_hash"],
                "authorizer_user_id": USER, "auto_logout_minutes": null});
            return Reply::Json(
                json!({"protocol_version": 2, "token": PAIR_TOKEN, "expires_at": expires}),
            );
        }
        if line.starts_with(&receiver) {
            if !approve.load(Ordering::SeqCst) {
                return Reply::Json(json!({"status": "pending", "expires_at": expires}));
            }
            let mut state = context.lock().unwrap().clone();
            let pin_sent = state["pin_sent"].as_bool() == Some(true);
            state["status"] = json!(if pin_sent { "pending" } else { "approved" });
            state["expires_at"] = json!(expires);
            if let Some(map) = state.as_object_mut() {
                map.remove("pin_sent");
            }
            return Reply::Json(state);
        }
        if line.starts_with(&format!(
            "POST /v1/auth/pair/v2/receiver/{PAIR_TOKEN}/message "
        )) {
            context.lock().unwrap()["pin_sent"] = json!(true);
            return Reply::Json(json!({"success": true}));
        }
        if line.starts_with(&format!("DELETE /v1/auth/pair/v2/{PAIR_TOKEN} ")) {
            return Reply::Json(json!({}));
        }
        Reply::Close
    })
    .await
}

#[tokio::test(flavor = "multi_thread")]
async fn pair_login_runs_its_steps_in_the_core_until_the_bundle_and_cancels() {
    let dir = private_dir();
    let approve = Arc::new(AtomicBool::new(false));
    let api = pair_api(approve.clone()).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    assert!(matches!(
        core.poll_pair_login().await,
        Err(CoreError::Invalid { .. })
    ));
    let challenge = core.begin_pair_login().await.unwrap();
    assert_eq!(challenge.token, PAIR_TOKEN);
    assert!(
        challenge
            .login_url
            .ends_with(&format!("#pair={PAIR_TOKEN}"))
    );
    assert_eq!(core.poll_pair_login().await.unwrap(), "pending");
    // No PIN before the authorizer approved.
    assert_eq!(
        core.submit_pair_pin(PIN.into()).await,
        Err(CoreError::Protocol)
    );
    approve.store(true, Ordering::SeqCst);
    assert_eq!(core.poll_pair_login().await.unwrap(), "approved");
    core.submit_pair_pin(PIN.into()).await.unwrap();
    // The authorizer has not answered: not finished, nothing stored.
    assert_eq!(core.finish_pair_login(None).await, Ok(false));
    assert!(stored(&keychain).is_none());
    core.cancel_pair_login().await.unwrap();
    assert_eq!(
        api.count(&format!("DELETE /v1/auth/pair/v2/{PAIR_TOKEN} ")),
        1
    );
    // Nothing was prepared, so no local sign-out ran.
    assert!(events.all().is_empty());
    assert!(matches!(
        core.finish_pair_login(None).await,
        Err(CoreError::Invalid { .. })
    ));
}

#[tokio::test(flavor = "multi_thread")]
async fn an_unacknowledged_keychain_store_fails_as_locked_and_logs_the_new_session_out() {
    let (dir, v) = (private_dir(), vector());
    let api = password_api(false).await;
    // Stores nothing and never acknowledges (a locked device).
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let (email, password) = (
        v["email"].as_str().unwrap(),
        v["password_v2"].as_str().unwrap(),
    );
    assert_eq!(
        core.login_password(email.into(), password.into(), None, false, None)
            .await,
        Err(CoreError::Locked)
    );
    assert_eq!(api.count("POST /v1/auth/logout "), 1);
    assert!(!admitted(&events.all()));
    assert!(matches!(
        core.send(1, None, "Synthetic".into(), None).await,
        Err(CoreError::Authentication)
    ));
}

/// Cancels the login's `CoreCancellation` when the store arrives, then
/// stores and acknowledges a little later (the cancel lands after the store
/// began but before the login continues).
struct CancellingKeychain {
    inner: Arc<Keychain>,
    cancel: Arc<CoreCancellation>,
}

impl CredentialStore for CancellingKeychain {
    fn load(&self) -> std::result::Result<Option<Vec<u8>>, CoreError> {
        self.inner.load()
    }
    fn credentials_changed(&self, snapshot: CredentialSnapshotRecord) {
        self.cancel.cancel();
        let inner = self.inner.clone();
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(50));
            inner.credentials_changed(snapshot);
        });
    }
    fn delete(&self) -> std::result::Result<(), CoreError> {
        self.inner.delete()
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn a_login_cancelled_after_the_keychain_store_leaves_nothing_stored() {
    let (dir, v) = (private_dir(), vector());
    let api = password_api(false).await;
    let (inner, events) = (acknowledging(), Arc::new(Events::default()));
    let cancel = CoreCancellation::new();
    let store = Arc::new(CancellingKeychain {
        inner: inner.clone(),
        cancel: cancel.clone(),
    });
    let config = CoreConfig {
        api_url: api.url.clone(),
        app_url: None,
        cache_container: Some(dir.path().to_str().unwrap().to_owned()),
        cache_directory_name: Some(crate::view_core_tests::NAME.into()),
    };
    let core = ViewModelCore::build(
        config,
        store,
        events.clone(),
        std::time::Duration::from_secs(5),
    )
    .unwrap();
    inner.core.set(Arc::downgrade(&core)).unwrap();
    let (email, password) = (
        v["email"].as_str().unwrap(),
        v["password_v2"].as_str().unwrap(),
    );
    assert_eq!(
        core.login_password(email.into(), password.into(), None, false, Some(cancel))
            .await,
        Err(CoreError::Cancelled)
    );
    // It was stored once, then wiped; the new server session was logged out.
    assert_eq!(inner.changed.lock().unwrap().len(), 1);
    assert!(stored(&inner).is_none());
    assert_eq!(api.count("POST /v1/auth/logout "), 1);
    assert_eq!(events.all(), [crate::view_core_tests::SIGNED_OUT]);
    assert!(!admitted(&events.all()));
    core.start(None).await.unwrap();
    assert_eq!(
        events.all().last(),
        Some(&crate::view_core_tests::SIGNED_OUT)
    );
}
