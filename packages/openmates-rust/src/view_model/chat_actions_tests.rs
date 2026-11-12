//! Chat and message actions over the `actor_tests` fixture (real cache directory, unreachable API): refusals before any network, failed actions publish nothing and keep the open window.
use super::actor_tests::{CHAT, Fixture, Sink, fixture, persisted, session};
use super::*;
use crate::error::Error;
use tokio_util::sync::CancellationToken;

/// A started fixture: cached index restored, session admitted.
async fn started() -> (Fixture, Sink) {
    let mut f = fixture();
    persisted(&mut f).await;
    let sink = Sink::default();
    start(&mut f.host, session(), &sink, &CancellationToken::new())
        .await
        .unwrap();
    (f, sink)
}

#[tokio::test]
async fn malformed_ids_and_empty_edits_are_refused_without_events() {
    let (mut f, sink) = started().await;
    let cancel = CancellationToken::new();
    let before = sink.events().len();
    let bad = || "not-a-uuid".to_owned();
    assert!(matches!(
        delete_chat(&mut f.host, bad(), &sink, &cancel).await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        delete_message(&mut f.host, RequestId(1), bad(), "m".into(), &sink, &cancel).await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        edit_message(
            &mut f.host,
            RequestId(2),
            CHAT.into(),
            "m".into(),
            "  ".into(),
            &sink,
            &cancel
        )
        .await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        retry_turn(&mut f.host, RequestId(3), bad(), &sink, &cancel).await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        fork_chat(&mut f.host, bad(), "m".into(), None, &sink, &cancel).await,
        Err(Error::Invalid(_))
    ));
    assert!(matches!(
        stop_reply(&mut f.host, CHAT.into(), String::new(), &cancel).await,
        Err(Error::Invalid(_))
    ));
    assert_eq!(sink.events().len(), before, "a refusal publishes nothing");
}

#[tokio::test]
async fn an_unreachable_server_fails_the_action_and_keeps_the_open_window() {
    let (mut f, sink) = started().await;
    let cancel = CancellationToken::new();
    // The cached window opens even though the network read fails.
    let _ = open_chat(&mut f.host, RequestId(5), CHAT.into(), &sink, &cancel).await;
    let opened = f.host.core.open_chat_id().map(str::to_owned);
    let before = sink.events().len();
    let result = delete_message(
        &mut f.host,
        RequestId(6),
        CHAT.into(),
        "22222222-2222-4222-8222-222222222222".into(),
        &sink,
        &cancel,
    )
    .await;
    assert!(result.is_err(), "nothing can be deleted offline");
    assert!(!matches!(result, Err(Error::Invalid(_))));
    assert_eq!(f.host.core.open_chat_id().map(str::to_owned), opened);
    let result = delete_chat(&mut f.host, CHAT.into(), &sink, &cancel).await;
    assert!(result.is_err(), "nothing can be deleted offline");
    assert_eq!(f.host.core.open_chat_id().map(str::to_owned), opened);
    assert_eq!(
        sink.events().len(),
        before,
        "a failed action publishes nothing"
    );
}
