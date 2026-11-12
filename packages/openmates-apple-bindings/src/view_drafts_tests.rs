//! ViewModelCore `draft` over a seeded cache and a loopback server: signed out is `Authentication`, a malformed id is `Invalid` before any request, the server's draft (typed on another device) is returned and refreshes `ChatList`, and a server without a draft answers `nil`.
use crate::test_api::{LoopbackApi, Reply, serve};
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::{CHAT, core, seed_cache, session};
use crate::*;
use serde_json::{Value, json};
use std::sync::Arc;

/// Loopback API that admits the session and answers `GET /v1/drafts/{CHAT}`
/// with `draft` (`Null`: the chat has none).
async fn drafts_api(draft: Value) -> LoopbackApi {
    serve(move |line, _| {
        if line.starts_with("POST /v1/auth/session ") {
            return Reply::Json(json!({"success": true, "ws_token": "synthetic",
                "user": {"id": "synthetic-user"}}));
        }
        if line.starts_with(&format!("GET /v1/drafts/{CHAT} ")) {
            return Reply::Json(json!({ "draft": draft }));
        }
        Reply::Close
    })
    .await
}

async fn signed_in(api: &LoopbackApi) -> (tempfile::TempDir, Arc<Events>, Arc<ViewModelCore>) {
    let dir = private_dir();
    let stored = session(&api.url, "synthetic-session");
    seed_cache(dir.path(), &stored).await;
    let keychain = Keychain::holding(&stored, true);
    let events = Arc::new(Events::default());
    let core = core(dir.path(), &api.url, &keychain, &events);
    core.start(None).await.unwrap();
    (dir, events, core)
}

fn remote_draft() -> Value {
    use openmates_sdk::crypto::encrypt_combined;
    json!({"chat_id": CHAT, "draft_v": 4,
        "encrypted_draft_md": encrypt_combined("Typed on the laptop", &[7; 32]).unwrap(),
        "encrypted_draft_preview": encrypt_combined("Typed on the", &[7; 32]).unwrap()})
}

#[tokio::test(flavor = "multi_thread")]
async fn draft_while_signed_out_is_authentication() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), "http://127.0.0.1:9", &keychain, &events);
    core.start(None).await.unwrap();
    assert_eq!(
        core.draft(CHAT.into(), None).await,
        Err(CoreError::Authentication)
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_malformed_chat_id_is_invalid_before_any_request() {
    let api = drafts_api(Value::Null).await;
    let (_dir, events, core) = signed_in(&api).await;
    let (requests, published) = (api.requests.lock().unwrap().len(), events.all().len());
    let result = core.draft("not-a-uuid".into(), None).await;
    assert!(
        matches!(result, Err(CoreError::Invalid { .. })),
        "not Invalid: {result:?}"
    );
    assert_eq!(api.requests.lock().unwrap().len(), requests);
    assert_eq!(events.all().len(), published, "a refusal publishes nothing");
}

#[tokio::test(flavor = "multi_thread")]
async fn the_servers_draft_from_another_device_is_returned_and_refreshes_the_list() {
    let api = drafts_api(remote_draft()).await;
    let (_dir, events, core) = signed_in(&api).await;
    let published = events.all().len();
    let draft = core.draft(CHAT.into(), None).await.unwrap();
    assert_eq!(
        draft,
        Some(DraftViewRecord {
            chat_id: CHAT.into(),
            markdown: "Typed on the laptop".into(),
            preview: Some("Typed on the".into()),
            draft_v: 4,
        })
    );
    assert_eq!(api.count(&format!("GET /v1/drafts/{CHAT} ")), 1);
    let later = &events.all()[published..];
    assert!(
        later
            .iter()
            .any(|event| matches!(event, ViewEventRecord::ChatList { .. })),
        "the new draft reaches the chat list: {later:?}"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_chat_without_a_server_draft_answers_nil() {
    let api = drafts_api(Value::Null).await;
    let (_dir, _events, core) = signed_in(&api).await;
    assert_eq!(core.draft(CHAT.into(), None).await, Ok(None));
}

#[test]
fn draft_changed_maps_one_to_one_including_a_cleared_draft() {
    use openmates_sdk::view_model::{DraftView, ViewEvent};
    let saved = ViewEvent::DraftChanged {
        chat_id: CHAT.into(),
        draft: Some(DraftView {
            chat_id: CHAT.into(),
            markdown: "Remote".into(),
            preview: None,
            draft_v: 9,
        }),
    };
    assert_eq!(
        ViewEventRecord::from(saved),
        ViewEventRecord::DraftChanged {
            chat_id: CHAT.into(),
            draft: Some(DraftViewRecord {
                chat_id: CHAT.into(),
                markdown: "Remote".into(),
                preview: None,
                draft_v: 9,
            }),
        }
    );
    let cleared = ViewEvent::DraftChanged {
        chat_id: CHAT.into(),
        draft: None,
    };
    assert_eq!(
        ViewEventRecord::from(cleared),
        ViewEventRecord::DraftChanged {
            chat_id: CHAT.into(),
            draft: None,
        }
    );
}
