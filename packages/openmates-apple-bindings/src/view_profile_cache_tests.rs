//! The cached admitted user payload against a loopback API that can go offline: an offline restore returns the last admitted payload flagged not fresh, the next admission replaces it and flags it fresh, sign-out wipes it, and another account's restore never sees it.
use crate::test_api::{LoopbackApi, Reply, serve};
use crate::view_core_tests::{Events, Keychain, cache_files, private_dir};
use crate::view_window_tests::{core, session};
use crate::*;
use openmates_sdk::session::Session;
use serde_json::{Value, json};
use std::sync::Arc;
use std::sync::atomic::{AtomicU8, Ordering};
use zeroize::Zeroizing;

/// Server states of [`api`].
const OFFLINE: u8 = 0;
const FIRST_NAME: u8 = 1;
const SECOND_NAME: u8 = 2;

/// The session check admits with the username of `state`, or drops the
/// connection (offline); logout answers.
async fn api(state: Arc<AtomicU8>) -> LoopbackApi {
    serve(move |line, _body| {
        if line.starts_with("POST /v1/auth/session ") {
            let username = match state.load(Ordering::SeqCst) {
                FIRST_NAME => "Synthetic Tester",
                SECOND_NAME => "Synthetic Renamed",
                _ => return Reply::Close,
            };
            return Reply::Json(json!({"success": true, "ws_token": "synthetic",
                "user": {"id": "synthetic-user", "username": username}}));
        }
        if line.starts_with("POST /v1/auth/logout ") {
            return Reply::Json(json!({"success": true}));
        }
        Reply::Close
    })
    .await
}

fn account(url: &str) -> Session {
    let mut stored = session(url, "synthetic-session-1");
    stored
        .cookies
        .insert("auth_refresh_token".into(), "synthetic-refresh".into());
    stored
}

/// A fresh core on `dir` whose Keychain holds `stored`, started once.
async fn started(dir: &tempfile::TempDir, url: &str, stored: &Session) -> Arc<ViewModelCore> {
    let (keychain, events) = (Keychain::holding(stored, true), Arc::new(Events::default()));
    let core = core(dir.path(), url, &keychain, &events);
    // Offline the start reports `Offline` and keeps the restored session.
    let _ = core.start(None).await;
    core
}

async fn profile(core: &ViewModelCore) -> (Value, bool) {
    let record = core.user_profile().await.unwrap();
    (serde_json::from_slice(&record.json).unwrap(), record.fresh)
}

#[tokio::test(flavor = "multi_thread")]
async fn an_offline_restore_shows_the_cached_profile_until_the_next_admission() {
    let (dir, state) = (private_dir(), Arc::new(AtomicU8::new(FIRST_NAME)));
    let api = api(state.clone()).await;
    let first = started(&dir, &api.url, &account(&api.url)).await;
    let (user, fresh) = profile(&first).await;
    assert_eq!(
        (user["username"].as_str(), fresh),
        (Some("Synthetic Tester"), true)
    );
    drop(first);

    state.store(OFFLINE, Ordering::SeqCst);
    let restored = started(&dir, &api.url, &account(&api.url)).await;
    let info = restored.session_info().await.unwrap().unwrap();
    assert!(!info.admitted);
    let (user, fresh) = profile(&restored).await;
    assert_eq!(
        (user["id"].as_str(), fresh),
        (Some("synthetic-user"), false)
    );
    assert_eq!(user["username"], "Synthetic Tester");
    // The plain accessor returns the same cached payload.
    let plain: Value =
        serde_json::from_slice(&restored.user_profile_json().await.unwrap()).unwrap();
    assert_eq!(plain, user);

    // Admission replaces the cached payload and flags it fresh.
    state.store(SECOND_NAME, Ordering::SeqCst);
    restored.start(None).await.unwrap();
    let (user, fresh) = profile(&restored).await;
    assert_eq!(
        (user["username"].as_str(), fresh),
        (Some("Synthetic Renamed"), true)
    );
    drop(restored);

    state.store(OFFLINE, Ordering::SeqCst);
    let again = started(&dir, &api.url, &account(&api.url)).await;
    let (user, fresh) = profile(&again).await;
    assert_eq!(
        (user["username"].as_str(), fresh),
        (Some("Synthetic Renamed"), false)
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn sign_out_wipes_the_cached_profile() {
    let (dir, state) = (private_dir(), Arc::new(AtomicU8::new(FIRST_NAME)));
    let api = api(state.clone()).await;
    let core = started(&dir, &api.url, &account(&api.url)).await;
    assert!(profile(&core).await.1);
    assert!(cache_files(dir.path()) > 0);
    core.logout().await.unwrap();
    assert_eq!(cache_files(dir.path()), 0);
    assert!(matches!(
        core.user_profile().await,
        Err(CoreError::Authentication)
    ));
}

#[tokio::test(flavor = "multi_thread")]
async fn another_account_never_sees_the_cached_profile() {
    let (dir, state) = (private_dir(), Arc::new(AtomicU8::new(FIRST_NAME)));
    let api = api(state.clone()).await;
    let first = started(&dir, &api.url, &account(&api.url)).await;
    assert!(profile(&first).await.1);
    drop(first);

    state.store(OFFLINE, Ordering::SeqCst);
    let mut other = account(&api.url);
    other.session_id = "synthetic-session-2".into();
    other.hashed_email = "synthetic-other-owner".into();
    other.master_key = Zeroizing::new([8; 32]);
    let core = started(&dir, &api.url, &other).await;
    let info = core.session_info().await.unwrap().unwrap();
    assert_eq!(info.hashed_email, "synthetic-other-owner");
    assert!(matches!(
        core.user_profile().await,
        Err(CoreError::Authentication)
    ));
    assert_eq!(
        core.user_profile_json().await,
        Err(CoreError::Authentication)
    );
}
