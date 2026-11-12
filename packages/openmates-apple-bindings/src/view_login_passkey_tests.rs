//! ViewModelCore passkey login and passkey device verification against a loopback API built from the TS passkey PRF wrapping vector (`tests/crypto_fixtures/ts_web_formats.json`): success stores the unwrapped master key and starts, a refused assertion or a missing PRF output stores nothing, a cancel after the Keychain store leaves nothing, and device verification admits on an accepted assertion and stays pending on a refusal.
use crate::test_api::{LoopbackApi, Reply, serve};
use crate::view_core_tests::{Events, Keychain, SIGNED_OUT, private_dir};
use crate::view_login_tests::{CancellingKeychain, acknowledging, admitted, stored};
use crate::view_window_tests::{core, session};
use crate::*;
use base64::{Engine as _, engine::general_purpose::STANDARD};
use openmates_sdk::{client::PASSKEY_PRF_UNAVAILABLE, crypto};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

const USER: &str = "synthetic-user";
const EMAIL: &str = "synthetic@example.org";
const CHALLENGE: &str = "c3ludGhldGljLWNoYWxsZW5nZS0wMDAwMDAwMDAwMDA";
const CREDENTIAL: &str = "c3ludGhldGljLWNyZWRlbnRpYWw";

/// The TS passkey (PRF) master wrapping case and the vector's master key.
fn prf_vector() -> (Value, Value) {
    let formats: Value = serde_json::from_str(include_str!(
        "../../openmates-rust/tests/crypto_fixtures/ts_web_formats.json"
    ))
    .unwrap();
    let case = formats["master_wrapping"]
        .as_array()
        .unwrap()
        .iter()
        .find(|case| case["kind"] == "prf")
        .unwrap()
        .clone();
    (case, formats["keys"].clone())
}

fn raw(value: &Value) -> Vec<u8> {
    STANDARD.decode(value.as_str().unwrap()).unwrap()
}

fn master() -> Vec<u8> {
    raw(&prf_vector().1["master_b64"])
}

fn prf() -> Vec<u8> {
    raw(&prf_vector().0["prf_b64"])
}

fn options() -> Value {
    json!({"success": true, "challenge": CHALLENGE, "rp": {"id": "example.org", "name": "OpenMates"},
        "timeout": 60000, "allowCredentials": [], "userVerification": "required",
        "extensions": {"prf": {"eval": {"first": "c3ludGhldGljLXByZi1zYWx0"}}}})
}

fn verified() -> Value {
    let (case, _) = prf_vector();
    let master: [u8; 32] = master().try_into().unwrap();
    json!({"success": true, "message": "Passkey verified. Please complete authentication.",
        "user_id": USER, "hashed_email": crypto::hash_email(EMAIL),
        "encrypted_email": crypto::encrypt_bytes(EMAIL.as_bytes(), &master).unwrap(),
        "encrypted_master_key": case["ciphertext"], "key_iv": case["iv"],
        "user_email_salt": case["email_salt_b64"]})
}

fn lookup_hash() -> String {
    let mut input = prf();
    input.extend(raw(&prf_vector().0["email_salt_b64"]));
    STANDARD.encode(Sha256::digest(&input))
}

/// The passkey account; `accept` decides the assertion verification.
async fn passkey_api(accept: bool) -> LoopbackApi {
    let salt = prf_vector().0["email_salt_b64"].clone();
    serve(move |line, body| {
        let path = line.split(' ').nth(1).unwrap_or_default();
        match path {
            "/v1/auth/session" => Reply::Json(json!({"success": true, "ws_token": "synthetic",
                "user": {"id": USER, "username": "Synthetic Tester"}})),
            "/v1/auth/passkey/assertion/initiate" => Reply::Json(options()),
            "/v1/auth/passkey/assertion/verify" if accept => Reply::Json(verified()),
            "/v1/auth/passkey/assertion/verify" => Reply::Json(
                json!({"success": false, "message": "Passkey verification failed. Invalid signature."}),
            ),
            "/v1/auth/login" if body["lookup_hash"] == lookup_hash() => {
                Reply::JsonWithCookie(json!({"success": true, "ws_token": "synthetic",
                    "user": {"id": USER, "username": "Synthetic Tester", "user_email_salt": salt}}))
            }
            "/v1/auth/login" => Reply::Json(json!({"success": false})),
            "/v1/auth/logout" => Reply::Json(json!({"success": true})),
            _ => Reply::Close,
        }
    })
    .await
}

fn assertion() -> Vec<u8> {
    let client_data =
        json!({"type": "webauthn.get", "challenge": CHALLENGE, "origin": "https://example.org"});
    serde_json::to_vec(&json!({"credential_id": CREDENTIAL,
        "client_data_json": STANDARD.encode(client_data.to_string()),
        "authenticator_data": STANDARD.encode([1u8; 37]), "signature": STANDARD.encode([2u8; 70]),
        "user_handle": STANDARD.encode(USER)}))
    .unwrap()
}

#[tokio::test(flavor = "multi_thread")]
async fn passkey_login_unwraps_with_the_prf_output_stores_and_starts() {
    let dir = private_dir();
    let api = passkey_api(true).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let challenge = core.begin_passkey_login(None, None).await.unwrap();
    let options: Value = serde_json::from_slice(&challenge.options_json).unwrap();
    assert_eq!(options["challenge"], CHALLENGE);
    let login = core
        .finish_passkey_login(assertion(), prf(), true, None)
        .await
        .unwrap();
    assert_eq!(login.password_migration, PasswordMigrationRecord::NotNeeded);
    assert_eq!(login.remaining_backup_codes, None);
    let session = stored(&keychain).expect("session stored");
    assert_eq!(session.master_key.to_vec(), master());
    assert_eq!(session.hashed_email, crypto::hash_email(EMAIL));
    assert!(admitted(&events.all()));
    // The continuation was used up.
    core.logout().await.unwrap();
    assert!(matches!(
        core.finish_passkey_login(assertion(), prf(), true, None)
            .await,
        Err(CoreError::Invalid { .. })
    ));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_refused_passkey_is_an_authentication_error_and_stores_nothing() {
    let dir = private_dir();
    let api = passkey_api(false).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    core.begin_passkey_login(Some(EMAIL.into()), None)
        .await
        .unwrap();
    assert_eq!(
        core.finish_passkey_login(assertion(), prf(), false, None)
            .await,
        Err(CoreError::Authentication)
    );
    assert!(stored(&keychain).is_none());
    assert!(events.all().is_empty());
    assert_eq!(api.count("POST /v1/auth/login "), 0);
}

#[tokio::test(flavor = "multi_thread")]
async fn a_missing_prf_output_is_typed_and_sends_nothing() {
    let dir = private_dir();
    let api = passkey_api(true).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    core.begin_passkey_login(None, None).await.unwrap();
    assert_eq!(
        core.finish_passkey_login(assertion(), Vec::new(), false, None)
            .await,
        Err(CoreError::Invalid {
            message: PASSKEY_PRF_UNAVAILABLE.to_owned()
        })
    );
    assert_eq!(api.count("POST /v1/auth/passkey/assertion/verify "), 0);
    assert!(stored(&keychain).is_none());
    // Cancelled before finishing: no continuation is left.
    core.begin_passkey_login(None, None).await.unwrap();
    core.cancel_passkey_login().await;
    assert!(matches!(
        core.finish_passkey_login(assertion(), prf(), false, None)
            .await,
        Err(CoreError::Invalid { .. })
    ));
    assert!(events.all().is_empty());
}

#[tokio::test(flavor = "multi_thread")]
async fn a_passkey_login_cancelled_after_the_keychain_store_leaves_nothing_stored() {
    let dir = private_dir();
    let api = passkey_api(true).await;
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
    core.begin_passkey_login(None, None).await.unwrap();
    assert_eq!(
        core.finish_passkey_login(assertion(), prf(), false, Some(cancel))
            .await,
        Err(CoreError::Cancelled)
    );
    assert_eq!(inner.changed.lock().unwrap().len(), 1);
    assert!(stored(&inner).is_none());
    assert_eq!(api.count("POST /v1/auth/logout "), 1);
    assert_eq!(events.all(), [SIGNED_OUT]);
}

/// A stored session whose check asks for a passkey until the device check
/// accepted an assertion (only while `accept` holds).
async fn device_api(accept: Arc<AtomicBool>) -> LoopbackApi {
    let verified = Arc::new(AtomicBool::new(false));
    serve(move |line, _body| {
        let path = line.split(' ').nth(1).unwrap_or_default();
        match path {
            "/v1/auth/session" if verified.load(Ordering::SeqCst) => {
                Reply::Json(json!({"success": true, "ws_token": "synthetic",
                    "user": {"id": USER, "username": "Synthetic Tester"}}))
            }
            "/v1/auth/session" => Reply::Json(json!({"success": false,
                "re_auth_required": "passkey", "re_auth_reason": "new_device"})),
            "/v1/auth/passkey/assertion/initiate" => Reply::Json(options()),
            "/v1/auth/passkey/verify/device" => {
                let accepted = accept.load(Ordering::SeqCst);
                verified.store(accepted, Ordering::SeqCst);
                Reply::Json(json!({"success": accepted, "message": "synthetic"}))
            }
            "/v1/auth/logout" => Reply::Json(json!({"success": true})),
            _ => Reply::Close,
        }
    })
    .await
}

#[tokio::test(flavor = "multi_thread")]
async fn passkey_device_verification_admits_on_acceptance_and_stays_pending_on_refusal() {
    let dir = private_dir();
    let accept = Arc::new(AtomicBool::new(false));
    let api = device_api(accept.clone()).await;
    let mut held = session(&api.url, "synthetic-session-1");
    held.cookies
        .insert("auth_refresh_token".into(), "synthetic-refresh".into());
    let (keychain, events) = (Keychain::holding(&held, true), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    assert_eq!(core.start(None).await, Err(CoreError::VerificationRequired));
    core.begin_passkey_device_verification(None).await.unwrap();
    assert_eq!(
        core.finish_passkey_device_verification(assertion(), None)
            .await,
        Err(CoreError::Authentication)
    );
    assert!(core.pending_verification().await.unwrap().is_some());
    assert!(stored(&keychain).is_some());
    accept.store(true, Ordering::SeqCst);
    core.begin_passkey_device_verification(None).await.unwrap();
    core.finish_passkey_device_verification(assertion(), None)
        .await
        .unwrap();
    assert_eq!(core.pending_verification().await.unwrap(), None);
    assert!(admitted(&events.all()));
    assert_eq!(api.count("POST /v1/auth/passkey/verify/device "), 2);
}
