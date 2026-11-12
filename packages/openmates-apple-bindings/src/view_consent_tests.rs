//! `answerConsent` on a signed-in and a signed-out ViewModelCore: no running turn means no pending request (`Invalid`), and signed out is refused.
use crate::test_api::{LoopbackApi, Reply, serve};
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::{CHAT, core, seed_cache, session};
use crate::*;
use serde_json::json;
use std::sync::Arc;

async fn api() -> LoopbackApi {
    serve(|line, _| {
        if line.starts_with("POST /v1/auth/session ") {
            return Reply::Json(json!({"success": true, "ws_token": "synthetic",
                "user": {"id": "synthetic-user"}}));
        }
        Reply::Close
    })
    .await
}

#[tokio::test(flavor = "multi_thread")]
async fn an_unknown_consent_request_is_invalid() {
    let dir = private_dir();
    let api = api().await;
    let stored = session(&api.url, "synthetic-session");
    seed_cache(dir.path(), &stored).await;
    let keychain = Keychain::holding(&stored, true);
    let events = Arc::new(Events::default());
    let core = core(dir.path(), &api.url, &keychain, &events);
    core.start(None).await.unwrap();
    let result = core.answer_consent(CHAT.into(), "unknown-request".into(), vec![]);
    assert!(
        matches!(result, Err(CoreError::Invalid { .. })),
        "not Invalid: {result:?}"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn answering_while_signed_out_is_refused() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), "http://127.0.0.1:9", &keychain, &events);
    core.start(None).await.unwrap();
    assert!(
        core.answer_consent(CHAT.into(), "request".into(), vec![])
            .is_err()
    );
}
