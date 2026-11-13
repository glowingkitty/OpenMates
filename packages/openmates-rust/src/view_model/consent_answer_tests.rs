//! Consent answers: one answer per request, unknown requests and items are `Invalid`, a request ends with its turn.
use super::consent_answer::ConsentAnswerer;
use super::live_turns::LiveTurns;
use crate::error::Error;
use std::sync::Arc;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

const CHAT: &str = "22222222-2222-4222-8222-222222222222";

fn setup() -> (
    ConsentAnswerer,
    Arc<LiveTurns>,
    mpsc::UnboundedReceiver<(String, Vec<String>)>,
) {
    let turns = Arc::new(LiveTurns::default());
    let (tx, rx) = mpsc::unbounded_channel();
    (ConsentAnswerer::new(turns.clone(), tx), turns, rx)
}

#[test]
fn an_answer_reaches_the_client_once() {
    let (answerer, turns, mut rx) = setup();
    let guard = turns.register(Some(CHAT), CancellationToken::new());
    guard.add_consent(CHAT, "request-1", vec!["a".into(), "b".into()]);
    answerer
        .answer(CHAT, "request-1", vec!["a".into()])
        .unwrap();
    assert_eq!(
        rx.try_recv().unwrap(),
        ("request-1".into(), vec!["a".into()])
    );
    assert!(matches!(
        answerer.answer(CHAT, "request-1", vec![]),
        Err(Error::Invalid(_))
    ));
}

#[test]
fn unknown_request_other_chat_and_unlisted_item_are_invalid() {
    let (answerer, turns, mut rx) = setup();
    let guard = turns.register(Some(CHAT), CancellationToken::new());
    guard.add_consent(CHAT, "request-1", vec!["a".into()]);
    for (chat, request, items) in [
        (CHAT, "other", vec![]),
        ("33333333-3333-4333-8333-333333333333", "request-1", vec![]),
        (CHAT, "request-1", vec!["zzz".into()]),
    ] {
        assert!(matches!(
            answerer.answer(chat, request, items),
            Err(Error::Invalid(_))
        ));
    }
    assert!(rx.try_recv().is_err());
    // The rejected attempts left the request answerable (a decline).
    answerer.answer(CHAT, "request-1", vec![]).unwrap();
}

#[test]
fn a_request_ends_with_its_turn_and_a_closed_client_cancels() {
    let (answerer, turns, rx) = setup();
    let guard = turns.register(Some(CHAT), CancellationToken::new());
    guard.add_consent(CHAT, "request-1", vec![]);
    drop(guard);
    assert!(matches!(
        answerer.answer(CHAT, "request-1", vec![]),
        Err(Error::Invalid(_))
    ));
    let guard = turns.register(Some(CHAT), CancellationToken::new());
    guard.add_consent(CHAT, "request-2", vec![]);
    drop(rx);
    assert!(matches!(
        answerer.answer(CHAT, "request-2", vec![]),
        Err(Error::Cancelled)
    ));
}
