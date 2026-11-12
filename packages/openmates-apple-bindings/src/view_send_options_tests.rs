//! ViewModelCore `sendWithOptions` over a seeded cache and a loopback server without AI: refused while signed out, refused option combinations and malformed reserved ids show nothing, an already cancelled caller ends as `Cancelled`, a reserved message id keys the optimistic and the failed user message.
use crate::test_api::{Reply, serve};
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::{CHAT, core, seed_cache, session, windows};
use crate::*;
use serde_json::json;
use std::sync::Arc;

const QUESTION: &str = "Synthetic question for the garden shed";
const NEW_CHAT: &str = "55555555-5555-4555-8555-555555555555";
const MESSAGE: &str = "44444444-4444-4444-8444-444444444444";

pub(crate) fn options() -> SendOptionsRecord {
    SendOptionsRecord {
        pii_detection: true,
        incognito: false,
        slug: None,
        reserved_chat_id: None,
        reserved_message_id: None,
        embeds: vec![],
        excluded_pii_originals: vec![],
        excluded_pii_placeholders: vec![],
        pii_mappings: vec![],
    }
}

/// Admitted over a seeded cache; chat requests are unanswered. The chat is
/// open as request 1.
pub(crate) async fn opened(dir: &std::path::Path) -> (Arc<ViewModelCore>, Arc<Events>) {
    let api = serve(move |line, _| {
        if line.starts_with("POST /v1/auth/session ") {
            return Reply::Json(json!({"success": true, "ws_token": "synthetic",
                "user": {"id": "synthetic-user"}}));
        }
        Reply::Close
    })
    .await;
    let stored = session(&api.url, "synthetic-session");
    seed_cache(dir, &stored).await;
    let keychain = Keychain::holding(&stored, true);
    let events = Arc::new(Events::default());
    let core = core(dir, &api.url, &keychain, &events);
    core.start(None).await.unwrap();
    core.open_chat(1, CHAT.into(), None).await.unwrap();
    (core, events)
}

#[tokio::test(flavor = "multi_thread")]
async fn send_with_options_while_signed_out_is_refused() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), "http://127.0.0.1:9", &keychain, &events);
    core.start(None).await.unwrap();
    assert_eq!(
        core.send_with_options(1, None, QUESTION.into(), options(), None)
            .await,
        Err(CoreError::Authentication)
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn refused_options_and_malformed_ids_show_nothing() {
    let dir = private_dir();
    let (core, events) = opened(dir.path()).await;
    let before = events.all().len();
    let into_chat = [
        SendOptionsRecord {
            incognito: true,
            ..options()
        },
        SendOptionsRecord {
            slug: Some("garden-shed".into()),
            ..options()
        },
        SendOptionsRecord {
            reserved_chat_id: Some(NEW_CHAT.into()),
            ..options()
        },
        SendOptionsRecord {
            reserved_message_id: Some("not-a-uuid".into()),
            ..options()
        },
        SendOptionsRecord {
            reserved_message_id: Some("AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA".into()),
            ..options()
        },
    ];
    for refused in into_chat {
        let result = core
            .send_with_options(2, Some(CHAT.into()), QUESTION.into(), refused, None)
            .await;
        assert!(
            matches!(result, Err(CoreError::Invalid { .. })),
            "{result:?}"
        );
    }
    let new_chat = SendOptionsRecord {
        reserved_chat_id: Some(NEW_CHAT.into()),
        reserved_message_id: Some(NEW_CHAT.into()),
        ..options()
    };
    let result = core
        .send_with_options(3, None, QUESTION.into(), new_chat, None)
        .await;
    assert!(
        matches!(result, Err(CoreError::Invalid { .. })),
        "{result:?}"
    );
    assert_eq!(events.all().len(), before, "nothing is shown or sent");
}

#[tokio::test(flavor = "multi_thread")]
async fn an_already_cancelled_caller_ends_as_cancelled() {
    let dir = private_dir();
    let (core, _events) = opened(dir.path()).await;
    let cancellation = CoreCancellation::new();
    cancellation.cancel();
    assert_eq!(
        core.send_with_options(
            4,
            Some(CHAT.into()),
            QUESTION.into(),
            options(),
            Some(cancellation)
        )
        .await,
        Err(CoreError::Cancelled)
    );
    assert!(!core.cancel_send());
}

#[tokio::test(flavor = "multi_thread")]
async fn a_reserved_message_id_keys_the_optimistic_and_the_failed_user_message() {
    let dir = private_dir();
    let (core, events) = opened(dir.path()).await;
    let before = events.all().len();
    let reserved = SendOptionsRecord {
        reserved_message_id: Some(MESSAGE.into()),
        ..options()
    };
    let result = core
        .send_with_options(5, Some(CHAT.into()), QUESTION.into(), reserved, None)
        .await;
    assert!(
        result.is_err() && result != Err(CoreError::Cancelled),
        "{result:?}"
    );
    let all = events.all();
    let shown = windows(&all[before..]);
    let optimistic = shown.first().unwrap().1.messages.last().unwrap().clone();
    assert_eq!(optimistic.id, MESSAGE);
    assert_eq!(optimistic.send_state, Some(SendStateRecord::Sending));
    let failed = shown
        .last()
        .unwrap()
        .1
        .messages
        .iter()
        .find(|message| message.id == MESSAGE)
        .cloned()
        .expect("the reserved user message stays");
    assert!(
        matches!(failed.send_state, Some(SendStateRecord::Failed { .. })),
        "{failed:?}"
    );
}
