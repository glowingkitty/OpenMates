//! The admitted account on ViewModelCore against a loopback API: the user payload after login, restore and adoption and gone after logout; device verification and re-auth at the session check are typed, announced and keep the stored session; `verifyDevice2fa` admits on a good code and reports a refused code as `Authentication`.
use crate::test_api::{LoopbackApi, Reply, serve};
use crate::view_core_tests::{Events, Keychain, SIGNED_OUT, private_dir};
use crate::view_login_tests::{acknowledging, password_api_with, stored, vector};
use crate::view_window_tests::{core, session};
use crate::*;
use serde_json::{Value, json};
use std::sync::Arc;
use std::sync::atomic::{AtomicU8, Ordering};

const USER: &str = "synthetic-user";
const CODE: &str = "123456";

fn admitted_reply() -> Reply {
    Reply::Json(json!({"success": true, "ws_token": "synthetic",
        "user": {"id": USER, "username": "Synthetic Tester", "language": "en", "darkmode": true}}))
}

fn two_factor_reply() -> Reply {
    Reply::Json(
        json!({"success": false, "message": "Device verification required",
        "re_auth_required": "2fa", "re_auth_reason": "new_device",
        "user": {"id": USER, "username": "Synthetic Tester"}}),
    )
}

/// Session check states of [`account_api`].
const ADMIT: u8 = 0;
const TWO_FACTOR: u8 = 1;
const PASSKEY: u8 = 2;
const REAUTH: u8 = 3;

/// Session check per `state`; the device check accepts only [`CODE`] and
/// then admits; logout answers.
async fn account_api(state: Arc<AtomicU8>) -> LoopbackApi {
    serve(move |line, body| {
        if line.starts_with("POST /v1/auth/session ") {
            return match state.load(Ordering::SeqCst) {
                TWO_FACTOR => two_factor_reply(),
                PASSKEY => Reply::Json(json!({"success": false, "re_auth_required": "passkey",
                    "re_auth_reason": "location_change", "password_fallback_available": true,
                    "password_credential_version": 2})),
                REAUTH => {
                    Reply::Json(json!({"success": false, "re_auth_reason": "session_verification"}))
                }
                _ => admitted_reply(),
            };
        }
        if line.starts_with("POST /v1/auth/2fa/verify/device ") {
            let accepted = body["tfa_code"] == CODE;
            if accepted {
                state.store(ADMIT, Ordering::SeqCst);
            }
            return Reply::Json(json!({"success": accepted, "message": "synthetic"}));
        }
        if line.starts_with("POST /v1/auth/logout ") {
            return Reply::Json(json!({"success": true}));
        }
        Reply::Close
    })
    .await
}

fn stored_session(url: &str) -> openmates_sdk::session::Session {
    let mut stored = session(url, "synthetic-session-1");
    stored
        .cookies
        .insert("auth_refresh_token".into(), "synthetic-refresh".into());
    stored
}

async fn profile(core: &ViewModelCore) -> Value {
    serde_json::from_slice(&core.user_profile_json().await.unwrap()).unwrap()
}

fn verification(events: &[ViewEventRecord]) -> Option<SessionVerificationRecord> {
    events.iter().find_map(|event| match event {
        ViewEventRecord::Session {
            event: SessionEventRecord::VerificationRequired { verification },
        } => Some(verification.clone()),
        _ => None,
    })
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
async fn the_profile_follows_restore_and_is_gone_after_logout() {
    let dir = private_dir();
    let api = account_api(Arc::new(AtomicU8::new(ADMIT))).await;
    let (keychain, events) = (
        Keychain::holding(&stored_session(&api.url), true),
        Arc::new(Events::default()),
    );
    let core = core(dir.path(), &api.url, &keychain, &events);
    // Not started: no profile.
    assert_eq!(
        core.user_profile_json().await,
        Err(CoreError::Authentication)
    );
    core.start(None).await.unwrap();
    assert!(admitted(&events.all()));
    let user = profile(&core).await;
    assert_eq!(user["id"], USER);
    assert_eq!(user["darkmode"], true);
    assert_eq!(core.pending_verification().await.unwrap(), None);
    core.logout().await.unwrap();
    assert_eq!(
        core.user_profile_json().await,
        Err(CoreError::Authentication)
    );
    assert_eq!(events.all().last(), Some(&SIGNED_OUT));
}

#[tokio::test(flavor = "multi_thread")]
async fn the_profile_is_available_after_a_password_login() {
    let (dir, v) = (private_dir(), vector());
    let api = password_api_with(false, admitted_reply).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let (email, password) = (
        v["email"].as_str().unwrap(),
        v["password_v2"].as_str().unwrap(),
    );
    core.login_password(email.into(), password.into(), None, false, None)
        .await
        .unwrap();
    // The session check's payload, not the login's.
    assert_eq!(profile(&core).await["language"], "en");
}

#[tokio::test(flavor = "multi_thread")]
async fn the_profile_is_available_after_an_adoption() {
    let dir = private_dir();
    let api = account_api(Arc::new(AtomicU8::new(ADMIT))).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let record = AdoptedSessionRecord {
        session_id: "synthetic-session-1".into(),
        cookies: vec![SessionCookieRecord {
            name: "auth_refresh_token".into(),
            value: "synthetic-refresh".into(),
        }],
        ws_token: None,
        master_key: vec![7; 32],
        hashed_email: "synthetic-owner".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        paired_session_expires_at: None,
    };
    core.adopt_session(record, None).await.unwrap();
    assert_eq!(profile(&core).await["username"], "Synthetic Tester");
}

#[tokio::test(flavor = "multi_thread")]
async fn device_verification_is_typed_keeps_the_session_and_a_good_code_admits() {
    let dir = private_dir();
    let api = account_api(Arc::new(AtomicU8::new(TWO_FACTOR))).await;
    let (keychain, events) = (
        Keychain::holding(&stored_session(&api.url), true),
        Arc::new(Events::default()),
    );
    let core = core(dir.path(), &api.url, &keychain, &events);
    assert_eq!(core.start(None).await, Err(CoreError::VerificationRequired));
    let expected = SessionVerificationRecord::Device {
        method: DeviceVerificationMethodRecord::TwoFactor,
        reason: "new_device".into(),
        password_fallback_available: false,
    };
    assert_eq!(verification(&events.all()), Some(expected.clone()));
    assert_eq!(core.pending_verification().await.unwrap(), Some(expected));
    assert!(!admitted(&events.all()));
    // The server kept the session: the stored credentials stay.
    assert!(stored(&keychain).is_some());
    assert_eq!(*keychain.deletes.lock().unwrap(), 0);
    // The minimal verification profile is never published.
    assert_eq!(
        core.user_profile_json().await,
        Err(CoreError::Authentication)
    );
    // A refused code is typed, stays pending and deletes nothing.
    assert_eq!(
        core.verify_device_2fa("654321".into(), None).await,
        Err(CoreError::Authentication)
    );
    assert!(core.pending_verification().await.unwrap().is_some());
    assert!(stored(&keychain).is_some());
    // The good code admits the session.
    core.verify_device_2fa(CODE.into(), None).await.unwrap();
    assert!(admitted(&events.all()));
    assert_eq!(core.pending_verification().await.unwrap(), None);
    assert_eq!(profile(&core).await["id"], USER);
    assert_eq!(api.count("POST /v1/auth/2fa/verify/device "), 2);
}

#[tokio::test(flavor = "multi_thread")]
async fn a_login_that_needs_device_verification_reports_it_and_keeps_the_session() {
    let (dir, v) = (private_dir(), vector());
    let api = password_api_with(false, two_factor_reply).await;
    let (keychain, events) = (acknowledging(), Arc::new(Events::default()));
    let core = core(dir.path(), &api.url, &keychain, &events);
    let (email, password) = (
        v["email"].as_str().unwrap(),
        v["password_v2"].as_str().unwrap(),
    );
    assert_eq!(
        core.login_password(email.into(), password.into(), None, false, None)
            .await,
        Err(CoreError::VerificationRequired)
    );
    assert!(matches!(
        verification(&events.all()),
        Some(SessionVerificationRecord::Device {
            method: DeviceVerificationMethodRecord::TwoFactor,
            ..
        })
    ));
    assert!(stored(&keychain).is_some());
    assert_eq!(api.count("POST /v1/auth/logout "), 0);
}

#[tokio::test(flavor = "multi_thread")]
async fn passkey_verification_and_reauth_are_typed_and_keep_the_session() {
    let dir = private_dir();
    let state = Arc::new(AtomicU8::new(PASSKEY));
    let api = account_api(state.clone()).await;
    let (keychain, events) = (
        Keychain::holding(&stored_session(&api.url), true),
        Arc::new(Events::default()),
    );
    let core = core(dir.path(), &api.url, &keychain, &events);
    assert_eq!(core.start(None).await, Err(CoreError::VerificationRequired));
    assert_eq!(
        core.pending_verification().await.unwrap(),
        Some(SessionVerificationRecord::Device {
            method: DeviceVerificationMethodRecord::Passkey,
            reason: "location_change".into(),
            password_fallback_available: true,
        })
    );
    // A passkey check is not answered with a code; nothing is sent.
    assert!(matches!(
        core.verify_device_2fa(CODE.into(), None).await,
        Err(CoreError::Invalid { .. })
    ));
    assert_eq!(api.count("POST /v1/auth/2fa/verify/device "), 0);
    // The next check asks for a new sign-in instead.
    state.store(REAUTH, Ordering::SeqCst);
    assert_eq!(
        core.refresh_chats(None).await,
        Err(CoreError::VerificationRequired)
    );
    assert!(stored(&keychain).is_some());
    let reauth = SessionVerificationRecord::ReAuth {
        reason: "session_verification".into(),
    };
    assert_eq!(core.pending_verification().await.unwrap(), Some(reauth));
    assert_eq!(*keychain.deletes.lock().unwrap(), 0);
}
