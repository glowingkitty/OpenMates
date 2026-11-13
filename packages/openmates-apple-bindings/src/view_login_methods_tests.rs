//! ViewModelCore backup-code and recovery-key logins and the password v1→v2 migration after a legacy login, against a loopback API built from the core's synthetic account vector: success stores and starts, a wrong code or key stores nothing, a cancel after the Keychain store leaves nothing, and the migration completes, is refused, or is interrupted and resumed by the next login without any local state.
use crate::test_api::{LoopbackApi, Reply, serve};
use crate::view_core_tests::{Events, private_dir};
use crate::view_login_tests::{CancellingKeychain, acknowledging, admitted, stored, vector};
use crate::view_window_tests::core;
use crate::*;
use base64::{Engine as _, engine::general_purpose::STANDARD};
use openmates_sdk::crypto;
use serde_json::{Value, json};
use std::sync::{Arc, Mutex};

const USER: &str = "synthetic-user";
const BACKUP_CODE: &str = "SYNTH-BACKUP-0001";

fn account_user(v: &Value, version: u8) -> Value {
    let (key, salt) = if version == 1 {
        (&v["legacy_wrapped_master"], &v["legacy_salt"])
    } else {
        (&v["password_v2_wrapped_master"], &v["password_v2_salt"])
    };
    json!({"id": USER, "username": "Synthetic Tester", "credential_version": version,
        "user_email_salt": v["password_v2_salt"], "salt": salt, "encrypted_key": key,
        "key_iv": v["iv"]})
}

fn lookup_hash(secret: &str, v: &Value) -> String {
    let salt = STANDARD
        .decode(v["password_v2_salt"].as_str().unwrap())
        .unwrap();
    crypto::hash_key(secret, &salt).unwrap()
}

/// Routes every account needs: lookup, the v2 challenge, session and logout.
fn common(line: &str, v: &Value) -> Option<Reply> {
    let path = line.split(' ').nth(1).unwrap_or_default();
    Some(match path {
        "/v1/auth/session" => Reply::Json(json!({"success": true, "ws_token": "synthetic",
            "user": {"id": USER, "username": "Synthetic Tester"}})),
        "/v1/auth/lookup" => Reply::Json(json!({"user_email_salt": v["password_v2_salt"]})),
        "/v1/auth/password-v2/challenge" => {
            Reply::Json(json!({"challenge_id": "synthetic-challenge", "nonce": v["nonce_v2"]}))
        }
        "/v1/auth/logout" => Reply::Json(json!({"success": true})),
        _ => return None,
    })
}

/// A v2 account with second factor that accepts `BACKUP_CODE` once.
async fn backup_api() -> LoopbackApi {
    let v = vector();
    serve(move |line, body| {
        if let Some(reply) = common(line, &v) {
            return reply;
        }
        if !line.starts_with("POST /v1/auth/login ") {
            return Reply::Close;
        }
        if body["password_proof"] != v["login_proof_v2"] || body["code_type"] != "backup" {
            return Reply::Json(json!({"success": false, "tfa_required": true}));
        }
        if body["tfa_code"] != BACKUP_CODE {
            return Reply::Json(
                json!({"success": false, "tfa_required": true, "message": "login.code_wrong"}),
            );
        }
        Reply::JsonWithCookie(json!({"success": true, "ws_token": "synthetic",
            "backup_code_used": true, "remaining_backup_codes": 4, "user": account_user(&v, 2)}))
    })
    .await
}

/// A legacy account whose recovery key is the vector's legacy password.
async fn recovery_api() -> LoopbackApi {
    let v = vector();
    serve(move |line, body| {
        if let Some(reply) = common(line, &v) {
            return reply;
        }
        if !line.starts_with("POST /v1/auth/login ") || body["login_method"] != "recovery_key" {
            return Reply::Close;
        }
        if body["lookup_hash"] != lookup_hash(v["legacy_password"].as_str().unwrap(), &v) {
            return Reply::Json(json!({"success": false, "message": "login.recovery_key_wrong"}));
        }
        Reply::JsonWithCookie(
            json!({"success": true, "ws_token": "synthetic", "user": account_user(&v, 1)}),
        )
    })
    .await
}

fn email() -> String {
    vector()["email"].as_str().unwrap().to_owned()
}

fn master(keychain: &crate::view_core_tests::Keychain) -> String {
    crypto::encode_key(&stored(keychain).expect("session stored").master_key)
}

#[tokio::test(flavor = "multi_thread")]
async fn backup_code_login_sends_the_backup_kind_stores_and_reports_codes_left() {
    let (dir, v) = (private_dir(), vector());
    let api = backup_api().await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let password = v["password_v2"].as_str().unwrap();
    let login = core
        .login_backup_code(email(), password.into(), BACKUP_CODE.into(), false, None)
        .await
        .unwrap();
    assert_eq!(login.remaining_backup_codes, Some(4));
    assert_eq!(login.password_migration, PasswordMigrationRecord::NotNeeded);
    assert_eq!(master(&keychain), v["legacy_master"].as_str().unwrap());
    assert!(admitted(&events.all()));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_wrong_backup_code_is_an_authentication_error_and_stores_nothing() {
    let (dir, v) = (private_dir(), vector());
    let api = backup_api().await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let password = v["password_v2"].as_str().unwrap();
    assert_eq!(
        core.login_backup_code(email(), password.into(), "SYNTH-WRONG".into(), false, None)
            .await,
        Err(CoreError::Authentication)
    );
    assert!(stored(&keychain).is_none());
    assert!(events.all().is_empty());
}

#[tokio::test(flavor = "multi_thread")]
async fn recovery_key_login_unwraps_the_master_key_in_the_core_and_starts() {
    let (dir, v) = (private_dir(), vector());
    let api = recovery_api().await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let key = v["legacy_password"].as_str().unwrap();
    let login = core
        .login_recovery_key(email(), key.into(), true, None)
        .await
        .unwrap();
    assert_eq!(login.password_migration, PasswordMigrationRecord::NotNeeded);
    assert_eq!(master(&keychain), v["legacy_master"].as_str().unwrap());
    assert!(admitted(&events.all()));
    // A recovery key never starts the password migration.
    assert_eq!(
        api.count("GET /v1/auth/password-v2/migration-capabilities "),
        0
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_wrong_recovery_key_is_an_authentication_error_and_stores_nothing() {
    let dir = private_dir();
    let api = recovery_api().await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    assert_eq!(
        core.login_recovery_key(email(), "Synthetic Wrong Key".into(), false, None)
            .await,
        Err(CoreError::Authentication)
    );
    assert!(stored(&keychain).is_none());
    assert!(events.all().is_empty());
}

#[tokio::test(flavor = "multi_thread")]
async fn a_recovery_login_cancelled_after_the_keychain_store_leaves_nothing_stored() {
    let (dir, v) = (private_dir(), vector());
    let api = recovery_api().await;
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
    let key = v["legacy_password"].as_str().unwrap();
    assert_eq!(
        core.login_recovery_key(email(), key.into(), false, Some(cancel))
            .await,
        Err(CoreError::Cancelled)
    );
    assert_eq!(inner.changed.lock().unwrap().len(), 1);
    assert!(stored(&inner).is_none());
    assert_eq!(api.count("POST /v1/auth/logout "), 1);
    assert_eq!(events.all(), [crate::view_core_tests::SIGNED_OUT]);
}

/// How the fake server's migration routes behave.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Migration {
    /// Every step succeeds.
    Accept,
    /// `/migrate` asks for a recent strong verification (428).
    NeedsVerification,
    /// The server only offers an older protocol.
    OldProtocol,
    /// The first confirmation never answers (connection dropped).
    DropFirstConfirm,
}

/// Server-side migration state of the legacy account.
#[derive(Default)]
struct Staged {
    /// `encrypted_master_key`/`key_iv` the client staged.
    wrapper: Option<(Value, Value)>,
    /// The v2 auth key the client sent (proof check).
    auth_key: Option<String>,
    confirms: usize,
}

/// A legacy (v1) password account plus the staged migration routes.
async fn legacy_api(mode: Migration) -> (LoopbackApi, Arc<Mutex<Staged>>) {
    let v = vector();
    let state = Arc::new(Mutex::new(Staged::default()));
    let shared = state.clone();
    let api = serve(move |line, body| {
        if let Some(reply) = common(line, &v) {
            return reply;
        }
        let path = line.split(' ').nth(1).unwrap_or_default();
        let password = v["legacy_password"].as_str().unwrap();
        let mut state = shared.lock().unwrap();
        match path {
            "/v1/auth/login" => {
                // A legacy account: the v2 proof never matches, v1 does.
                if body["lookup_hash"] != lookup_hash(password, &v) {
                    return Reply::Json(json!({"success": false}));
                }
                Reply::JsonWithCookie(
                    json!({"success": true, "ws_token": "synthetic", "user": account_user(&v, 1)}),
                )
            }
            "/v1/auth/password-v2/migration-capabilities" => {
                let protocol = if mode == Migration::OldProtocol { 1 } else { 2 };
                Reply::Json(json!({"staged_protocol": protocol, "confirm_required": true}))
            }
            "/v1/auth/password-v2/staged-challenge" => match state.wrapper {
                None => Reply::Status(409, json!({"detail": "No pending password migration"})),
                Some(_) => Reply::Json(
                    json!({"challenge_id": "synthetic-staged-challenge-000000000",
                    "nonce": v["nonce_v2"], "expires_in": 60}),
                ),
            },
            "/v1/auth/password-v2/migrate" => {
                if mode == Migration::NeedsVerification {
                    return Reply::Status(
                        428,
                        json!({"detail": {"error": "recent_verification_required"}}),
                    );
                }
                if body["old_lookup_hash"] != lookup_hash(password, &v)
                    || body["salt"] != v["password_v2_salt"]
                {
                    return Reply::Status(
                        401,
                        json!({"detail": "Invalid password migration request"}),
                    );
                }
                state.wrapper =
                    Some((body["encrypted_master_key"].clone(), body["key_iv"].clone()));
                state.auth_key = body["password_auth_key"].as_str().map(str::to_owned);
                Reply::Json(
                    json!({"success": true, "migration_status": "pending_confirmation",
                    "legacy_password_retained": false}),
                )
            }
            "/v1/auth/password-v2/verify-staged" => {
                let auth = crypto::decode_key(state.auth_key.as_deref().unwrap()).unwrap();
                let proof =
                    crypto::password_proof_v2(&auth, v["nonce_v2"].as_str().unwrap(), "migration")
                        .unwrap();
                if body["password_proof"] != proof.as_str() {
                    return Reply::Status(401, json!({"detail": "Invalid password proof"}));
                }
                let (key, iv) = state.wrapper.clone().unwrap();
                Reply::Json(json!({"encrypted_key": key, "key_iv": iv,
                    "salt": v["password_v2_salt"], "credential_version": 2}))
            }
            "/v1/auth/password-v2/confirm-migration" => {
                state.confirms += 1;
                if mode == Migration::DropFirstConfirm && state.confirms == 1 {
                    return Reply::Close;
                }
                Reply::Json(json!({"success": true, "migration_status": "typed_retired",
                    "legacy_password_retained": false}))
            }
            _ => Reply::Close,
        }
    })
    .await;
    (api, state)
}

async fn legacy_login(core: &ViewModelCore) -> LoginRecord {
    let password = vector()["legacy_password"].as_str().unwrap().to_owned();
    core.login_password(email(), password, None, false, None)
        .await
        .unwrap()
}

#[tokio::test(flavor = "multi_thread")]
async fn a_legacy_password_login_migrates_to_v2_in_the_core_and_keeps_the_session() {
    let (dir, v) = (private_dir(), vector());
    let (api, state) = legacy_api(Migration::Accept).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let login = legacy_login(&core).await;
    assert_eq!(login.password_migration, PasswordMigrationRecord::Completed);
    // The staged wrapper opens with the v2 key of the same password to the
    // same master key, and the auth key is that password's v2 auth key.
    let salt = STANDARD
        .decode(v["password_v2_salt"].as_str().unwrap())
        .unwrap();
    let (auth, wrap) =
        crypto::derive_password_keys_v2(v["legacy_password"].as_str().unwrap(), &salt).unwrap();
    let staged = state.lock().unwrap();
    let (key, iv) = staged.wrapper.clone().unwrap();
    let expected = crypto::decode_key(v["legacy_master"].as_str().unwrap()).unwrap();
    let unwrapped = crypto::unwrap_password_master_key(
        v["legacy_password"].as_str().unwrap(),
        2,
        key.as_str().unwrap(),
        v["password_v2_salt"].as_str().unwrap(),
        iv.as_str().unwrap(),
    )
    .unwrap();
    assert_eq!(*unwrapped, *expected);
    assert_eq!(
        *crypto::decode_key(staged.auth_key.as_deref().unwrap()).unwrap(),
        *auth
    );
    drop(wrap);
    assert_eq!(master(&keychain), v["legacy_master"].as_str().unwrap());
    assert!(admitted(&events.all()));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_refused_migration_reports_the_reason_and_the_login_stands() {
    let (dir, v) = (private_dir(), vector());
    let (api, state) = legacy_api(Migration::NeedsVerification).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let login = legacy_login(&core).await;
    assert_eq!(
        login.password_migration,
        PasswordMigrationRecord::DeferredRecentVerification
    );
    assert!(state.lock().unwrap().wrapper.is_none());
    assert_eq!(api.count("POST /v1/auth/password-v2/confirm-migration "), 0);
    assert_eq!(master(&keychain), v["legacy_master"].as_str().unwrap());
    assert!(admitted(&events.all()));
}

#[tokio::test(flavor = "multi_thread")]
async fn an_older_server_protocol_is_never_driven() {
    let dir = private_dir();
    let (api, _state) = legacy_api(Migration::OldProtocol).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let login = legacy_login(&core).await;
    assert_eq!(
        login.password_migration,
        PasswordMigrationRecord::Unsupported
    );
    assert_eq!(api.count("POST /v1/auth/password-v2/migrate "), 0);
    assert!(stored(&keychain).is_some());
}

#[tokio::test(flavor = "multi_thread")]
async fn an_interrupted_migration_is_resumed_by_the_next_login_without_local_state() {
    let dir = private_dir();
    let (api, state) = legacy_api(Migration::DropFirstConfirm).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let first = legacy_login(&core).await;
    assert_eq!(
        first.password_migration,
        PasswordMigrationRecord::PendingConfirmation
    );
    assert!(stored(&keychain).is_some());
    core.logout().await.unwrap();
    assert!(stored(&keychain).is_none());
    // The server still has the staged wrapper: the next legacy login probes
    // it, proves the password and confirms, without staging again.
    let second = legacy_login(&core).await;
    assert_eq!(
        second.password_migration,
        PasswordMigrationRecord::Completed
    );
    assert_eq!(api.count("POST /v1/auth/password-v2/migrate "), 1);
    assert_eq!(state.lock().unwrap().confirms, 2);
}
