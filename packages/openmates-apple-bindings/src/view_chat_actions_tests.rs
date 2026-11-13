//! ViewModelCore chat and message actions over a seeded cache and a loopback server that only admits the session: signed out is `Authentication`, malformed input is `Invalid` before any network, a refused socket is a typed error that keeps the session, a cancelled call is `Cancelled`, and no failure publishes an event.
use crate::test_api::{LoopbackApi, Reply, serve};
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::{CHAT, core, seed_cache, session};
use crate::*;
use serde_json::json;
use std::sync::Arc;

const MESSAGE: &str = "22222222-2222-4222-8222-222222222222";

async fn admitting_api() -> LoopbackApi {
    serve(|line, _| {
        if line.starts_with("POST /v1/auth/session ") {
            return Reply::Json(json!({"success": true, "ws_token": "synthetic",
                "user": {"id": "synthetic-user"}}));
        }
        Reply::Close
    })
    .await
}

async fn signed_in() -> (
    tempfile::TempDir,
    LoopbackApi,
    Arc<Events>,
    Arc<ViewModelCore>,
) {
    let dir = private_dir();
    let api = admitting_api().await;
    let stored = session(&api.url, "synthetic-session");
    seed_cache(dir.path(), &stored).await;
    let keychain = Keychain::holding(&stored, true);
    let events = Arc::new(Events::default());
    let core = core(dir.path(), &api.url, &keychain, &events);
    core.start(None).await.unwrap();
    (dir, api, events, core)
}

fn invalid<T: std::fmt::Debug>(result: Result<T, CoreError>) {
    assert!(
        matches!(result, Err(CoreError::Invalid { .. })),
        "not Invalid: {result:?}"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn every_action_while_signed_out_is_authentication() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), "http://127.0.0.1:9", &keychain, &events);
    core.start(None).await.unwrap();
    let auth = Err(CoreError::Authentication);
    assert_eq!(core.delete_chat(CHAT.into(), None).await, auth);
    assert_eq!(
        core.delete_message(1, CHAT.into(), MESSAGE.into(), None)
            .await,
        auth
    );
    assert_eq!(
        core.edit_message(2, CHAT.into(), MESSAGE.into(), "New text".into(), None)
            .await
            .map(drop),
        auth
    );
    assert_eq!(
        core.retry_last_turn(3, CHAT.into(), None).await.map(drop),
        auth
    );
    assert_eq!(
        core.fork_chat(CHAT.into(), MESSAGE.into(), None, None)
            .await
            .map(drop),
        auth
    );
    assert_eq!(
        core.save_draft(None, "Draft".into(), None).await.map(drop),
        auth
    );
    assert_eq!(core.clear_draft(CHAT.into(), None).await, auth);
    assert_eq!(
        core.stop_reply(CHAT.into(), "synthetic-task".into(), None)
            .await,
        auth
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn malformed_input_is_invalid_before_any_network() {
    let (_dir, api, events, core) = signed_in().await;
    let (requests, published) = (api.requests.lock().unwrap().len(), events.all().len());
    let bad = || "not-a-uuid".to_owned();
    invalid(core.delete_chat(bad(), None).await);
    invalid(core.delete_message(1, bad(), MESSAGE.into(), None).await);
    invalid(
        core.delete_message(1, CHAT.into(), String::new(), None)
            .await,
    );
    invalid(
        core.edit_message(2, CHAT.into(), MESSAGE.into(), "   ".into(), None)
            .await,
    );
    invalid(core.retry_last_turn(3, bad(), None).await);
    invalid(core.fork_chat(bad(), MESSAGE.into(), None, None).await);
    invalid(core.save_draft(Some(bad()), "Draft".into(), None).await);
    invalid(core.clear_draft(bad(), None).await);
    invalid(core.stop_reply(CHAT.into(), String::new(), None).await);
    assert_eq!(api.requests.lock().unwrap().len(), requests);
    assert_eq!(events.all().len(), published, "a refusal publishes nothing");
}

#[tokio::test(flavor = "multi_thread")]
async fn a_refused_socket_is_a_typed_error_without_events_or_sign_out() {
    let (_dir, _api, events, core) = signed_in().await;
    let published = events.all().len();
    for result in [
        core.delete_message(1, CHAT.into(), MESSAGE.into(), None)
            .await,
        core.stop_reply(CHAT.into(), "synthetic-task".into(), None)
            .await,
        core.delete_chat(CHAT.into(), None).await,
    ] {
        // The loopback closes the upgrade: the core reports a refused socket
        // handshake as `Authentication` (the stored session is kept).
        assert_eq!(result, Err(CoreError::Authentication));
    }
    assert!(
        core.session_info().await.unwrap().is_some(),
        "still signed in"
    );
    assert_eq!(
        events.all().len(),
        published,
        "a failed action publishes nothing"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_cancelled_call_is_cancelled() {
    let (_dir, _api, _events, core) = signed_in().await;
    let cancellation = CoreCancellation::new();
    cancellation.cancel();
    assert_eq!(
        core.stop_reply(
            CHAT.into(),
            "synthetic-task".into(),
            Some(cancellation.clone())
        )
        .await,
        Err(CoreError::Cancelled)
    );
    assert_eq!(
        core.delete_message(1, CHAT.into(), MESSAGE.into(), Some(cancellation))
            .await,
        Err(CoreError::Cancelled)
    );
}
