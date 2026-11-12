//! ViewModelCore draft versions and the unowned-frame passthrough over a seeded cache and a loopback server that only admits the session: signed out is a typed error, a signed-in core without a live monitor is `Offline`, and a send of a core-owned socket type is refused before the socket is looked at.
use crate::test_api::{Reply, serve};
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::{CHAT, core, seed_cache, session};
use crate::*;
use serde_json::json;
use std::sync::Arc;

fn query() -> Vec<DraftVersionQueryRecord> {
    vec![DraftVersionQueryRecord {
        chat_id: CHAT.into(),
        client_draft_v: 0,
    }]
}

#[tokio::test(flavor = "multi_thread")]
async fn draft_versions_while_signed_out_is_refused() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), "http://127.0.0.1:9", &keychain, &events);
    core.start(None).await.unwrap();
    assert_eq!(
        core.draft_versions(query(), None).await,
        Err(CoreError::Authentication)
    );
    assert_eq!(
        core.send_unowned_frame("my_feature".into(), "{}".into(), None)
            .await,
        Err(CoreError::Offline)
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn signed_in_without_monitor_is_offline_and_core_owned_frames_are_refused() {
    let dir = private_dir();
    let api = serve(|line, _| {
        if line.starts_with("POST /v1/auth/session ") {
            return Reply::Json(json!({"success": true, "ws_token": "synthetic",
                "user": {"id": "synthetic-user"}}));
        }
        Reply::Close
    })
    .await;
    let stored = session(&api.url, "synthetic-session");
    seed_cache(dir.path(), &stored).await;
    let keychain = Keychain::holding(&stored, true);
    let events = Arc::new(Events::default());
    let core = core(dir.path(), &api.url, &keychain, &events);
    core.start(None).await.unwrap();
    core.forward_unowned_frames().await.unwrap();
    assert_eq!(
        core.draft_versions(query(), None).await,
        Err(CoreError::Offline)
    );
    assert_eq!(
        core.send_unowned_frame("phased_sync_request".into(), "{}".into(), None)
            .await,
        Err(CoreError::Unavailable {
            code: "socket_frame_core_owned".into(),
            reason: "SHELL_SEND_OF_CORE_OWNED_SOCKET_EVENT".into(),
        })
    );
    assert_eq!(
        core.send_unowned_frame("my_feature".into(), "{}".into(), None)
            .await,
        Err(CoreError::Offline)
    );
}
