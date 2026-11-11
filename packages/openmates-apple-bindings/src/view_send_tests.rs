//! ViewModelCore send over a seeded cache and a loopback server without AI: refused while signed out or for empty text, a failed send keeps the user message as `Failed`, `cancelSend` ends a running send as `Cancelled`.
use crate::test_api::{Reply, serve};
use crate::view_core_tests::{Events, Keychain, private_dir};
use crate::view_window_tests::{CHAT, core, seed_cache, session, windows};
use crate::*;
use serde_json::json;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

const QUESTION: &str = "Synthetic question for the kitchen renovation";

/// Admitted over a seeded cache; chat requests are unanswered (or, once
/// `hang` is set, held for a while first). The chat is open as request 1.
async fn opened(dir: &std::path::Path, hang: Arc<AtomicBool>) -> (Arc<ViewModelCore>, Arc<Events>) {
    let api = serve(move |line, _| {
        if line.starts_with("POST /v1/auth/session ") {
            return Reply::Json(json!({"success": true, "ws_token": "synthetic",
                "user": {"id": "synthetic-user"}}));
        }
        if hang.load(Ordering::SeqCst) {
            return Reply::Hang(Duration::from_millis(1500));
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

/// The user message of the last window of `request`.
fn user_message(events: &[ViewEventRecord], request: u64) -> Option<MessageViewRecord> {
    windows(events)
        .into_iter()
        .rfind(|(id, _)| *id == request)?
        .1
        .messages
        .into_iter()
        .find(|message| message.content == QUESTION)
}

#[tokio::test(flavor = "multi_thread")]
async fn send_while_signed_out_is_refused() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), "http://127.0.0.1:9", &keychain, &events);
    core.start(None).await.unwrap();
    assert_eq!(
        core.send(1, None, QUESTION.into(), None).await,
        Err(CoreError::Authentication)
    );
    assert!(!core.cancel_send());
}

#[tokio::test(flavor = "multi_thread")]
async fn empty_text_is_refused_before_anything_is_sent() {
    let dir = private_dir();
    let (core, _events) = opened(dir.path(), Arc::default()).await;
    assert!(matches!(
        core.send(2, Some(CHAT.into()), "   ".into(), None).await,
        Err(CoreError::Invalid { .. })
    ));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_failed_send_keeps_the_user_message_as_failed() {
    let dir = private_dir();
    let (core, events) = opened(dir.path(), Arc::default()).await;
    let before = events.all().len();
    let result = core.send(2, Some(CHAT.into()), QUESTION.into(), None).await;
    assert!(
        result.is_err() && result != Err(CoreError::Cancelled),
        "{result:?}"
    );
    let all = events.all();
    // The optimistic message comes first, before any network answer.
    let first = windows(&all[before..]).into_iter().next().unwrap();
    assert_eq!(first.0, 2);
    let sending = first.1.messages.last().unwrap();
    assert_eq!(sending.content, QUESTION);
    assert_eq!(sending.role, MessageRoleRecord::User);
    assert_eq!(sending.send_state, Some(SendStateRecord::Sending));
    let failed = user_message(&all, 2).expect("the user message stays");
    assert!(
        matches!(failed.send_state, Some(SendStateRecord::Failed { .. })),
        "{failed:?}"
    );
    assert!(!core.cancel_send());
}

#[tokio::test(flavor = "multi_thread")]
async fn cancel_send_ends_a_running_send_as_cancelled() {
    let dir = private_dir();
    let hang = Arc::new(AtomicBool::new(false));
    let (core, events) = opened(dir.path(), hang.clone()).await;
    hang.store(true, Ordering::SeqCst);
    let running = {
        let core = core.clone();
        tokio::spawn(async move { core.send(3, Some(CHAT.into()), QUESTION.into(), None).await })
    };
    // Cancel once the optimistic message is shown.
    for _ in 0..400 {
        if user_message(&events.all(), 3).is_some() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    assert!(user_message(&events.all(), 3).is_some());
    assert!(core.cancel_send());
    assert_eq!(running.await.unwrap(), Err(CoreError::Cancelled));
    let cancelled = user_message(&events.all(), 3).unwrap();
    assert!(
        matches!(
            cancelled.send_state,
            Some(SendStateRecord::Cancelled { .. })
        ),
        "{cancelled:?}"
    );
    assert!(!core.cancel_send());
}
