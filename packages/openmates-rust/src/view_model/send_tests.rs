//! Send, stream and cancel in the core actor over the `actor_tests` fixture
//! with a scripted client stream (and the real client against the
//! unreachable API for failure): window and list events and their order.
use super::actor_tests::{CHAT, Fixture, Sink, fixture, persisted, session};
use super::send_flows::TurnDispatch;
use super::*;
use crate::{
    client::Client,
    error::{Error, Result},
    model::{Chat, Message, StreamUpdate},
};
use futures_util::future::BoxFuture;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

const NEW_CHAT: &str = "55555555-5555-4555-8555-555555555555";
const OTHER: &str = "33333333-3333-4333-8333-333333333333";
const USER: &str = "66666666-6666-4666-8666-666666666666";
const REPLY: &str = "77777777-7777-4777-8777-777777777777";
const SEND: RequestId = RequestId(9);

/// Plays `updates`, then optionally cancels through the handle and waits
/// for the cancel, then returns `result`.
struct Script {
    updates: Vec<StreamUpdate>,
    cancel_after: Option<SendCancelHandle>,
    result: Option<Result<Chat>>,
}

impl TurnDispatch for Script {
    fn dispatch<'a>(
        &'a mut self,
        _client: &'a mut Client,
        _chat_id: Option<&'a str>,
        _text: &'a str,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> BoxFuture<'a, Result<Chat>> {
        Box::pin(async move {
            for update in std::mem::take(&mut self.updates) {
                updates.send(update).await.unwrap();
            }
            // Let the relay publish everything before the scripted cancel.
            while updates.capacity() < updates.max_capacity() {
                tokio::task::yield_now().await;
            }
            if let Some(handle) = self.cancel_after.take() {
                assert!(handle.cancel(), "a running send is cancellable");
                cancel.cancelled().await;
                // Late progress after the cancel changes no window.
                let _ = updates
                    .send(StreamUpdate::Content {
                        content: "after cancel".into(),
                        thinking: String::new(),
                        mate: String::new(),
                    })
                    .await;
                return Err(Error::Cancelled);
            }
            self.result.take().expect("one dispatch per script")
        })
    }
}

fn reply_stream(chat_id: &str) -> Vec<StreamUpdate> {
    let content = |text: &str| StreamUpdate::Content {
        content: text.into(),
        thinking: String::new(),
        mate: "Synthetic mate".into(),
    };
    vec![
        StreamUpdate::Started {
            chat_id: chat_id.into(),
            message_id: USER.into(),
            expects_reply: true,
        },
        StreamUpdate::Submitted {
            chat_id: chat_id.into(),
            message_id: USER.into(),
        },
        content("Hel"),
        content("Hello"),
        StreamUpdate::Completed {
            chat_id: chat_id.into(),
            message_id: REPLY.into(),
            content: "Hello there".into(),
        },
    ]
}

fn sent_chat(chat_id: &str) -> Chat {
    let message = |id: &str, role: &str, content: &str| Message {
        id: id.into(),
        role: role.into(),
        content: content.into(),
        ..Message::default()
    };
    Chat {
        id: chat_id.into(),
        title: "Synthetic sent title".into(),
        category: String::new(),
        messages: vec![
            message(USER, "user", "synthetic question"),
            message(REPLY, "assistant", "Hello there"),
        ],
    }
}

async fn started() -> (Fixture, Sink) {
    let mut f = fixture();
    persisted(&mut f).await;
    let sink = Sink::default();
    start(&mut f.host, session(), &sink, &CancellationToken::new())
        .await
        .unwrap();
    (f, sink)
}

/// `chat_id` as the open window of an earlier `OpenChat`.
fn open(f: &mut Fixture, chat_id: &str) {
    let record = chat_window_from_chat(
        &Chat {
            id: chat_id.into(),
            title: "Synthetic open title".into(),
            category: String::new(),
            messages: Vec::new(),
        },
        ChatWindowSource::Canonical,
        Some(false),
        true,
        false,
        PiiRestoration::AllCachedUserRows,
    )
    .unwrap();
    let core = f.host.core_mut();
    core.begin_window(RequestId(5), chat_id);
    assert!(core.publish_window(RequestId(5), record).is_some());
}

async fn run(
    f: &mut Fixture,
    sink: &Sink,
    chat_id: Option<&str>,
    script: &mut Script,
) -> Result<ChatWindowRecord> {
    f.host
        .core_mut()
        .send_turn(
            SEND,
            chat_id.map(str::to_owned),
            "synthetic question".into(),
            sink,
            &CancellationToken::new(),
            script,
        )
        .await
}

fn windows(events: &[ViewEvent]) -> Vec<ChatWindowRecord> {
    events
        .iter()
        .filter_map(|event| match event {
            ViewEvent::ChatWindow { request, window } => {
                assert_eq!(*request, SEND, "send windows answer the send request");
                Some(window.clone())
            }
            _ => None,
        })
        .collect()
}

fn streams(events: &[ViewEvent]) -> Vec<StreamEvent> {
    events
        .iter()
        .filter_map(|event| match event {
            ViewEvent::Stream { event, .. } => Some(event.clone()),
            _ => None,
        })
        .collect()
}

#[tokio::test]
async fn send_into_the_open_chat_streams_in_order_and_the_sent_chat_replaces_the_stream() {
    let (mut f, sink) = started().await;
    open(&mut f, CHAT);
    let before = sink.events().len();
    let mut script = Script {
        updates: reply_stream(CHAT),
        cancel_after: None,
        result: Some(Ok(sent_chat(CHAT))),
    };
    let record = run(&mut f, &sink, Some(CHAT), &mut script).await.unwrap();
    let events = sink.events()[before..].to_vec();
    let windows = windows(&events);

    // Optimistic user message before any stream update.
    assert!(matches!(events[0], ViewEvent::ChatWindow { .. }));
    let optimistic = &windows[0].messages[0];
    assert_eq!(optimistic.content, "synthetic question");
    assert_eq!(optimistic.send_state, Some(SendState::Sending));
    // Started names the message; Submitted is the delivery fence.
    assert_eq!(windows[1].messages[0].id, USER);
    assert_eq!(
        windows[2].messages[0].send_state,
        Some(SendState::Submitted)
    );
    // Deltas in order, each replacing the reply text so far.
    let replies: Vec<(&str, MessageStatus)> = windows[3..6]
        .iter()
        .map(|window| {
            (
                window.messages[1].content.as_str(),
                window.messages[1].status,
            )
        })
        .collect();
    assert_eq!(
        replies,
        [
            ("Hel", MessageStatus::Streaming),
            ("Hello", MessageStatus::Streaming),
            ("Hello there", MessageStatus::Complete)
        ]
    );
    assert!(
        windows[3..6]
            .iter()
            .all(|window| window.messages.len() == 2)
    );
    assert!(
        windows[..6]
            .iter()
            .all(|window| window.source == ChatWindowSource::Live)
    );
    // Each stream event precedes the window it changed.
    let position = |wanted: &dyn Fn(&ViewEvent) -> bool| events.iter().position(wanted).unwrap();
    let content = position(
        &|event| matches!(event, ViewEvent::Stream { event: StreamEvent::Content { content, .. }, .. } if content == "Hel"),
    );
    assert!(
        matches!(&events[content + 1], ViewEvent::ChatWindow { window, .. } if window.messages[1].content == "Hel")
    );

    // The sent chat replaces the stream, then the list follows.
    let last = windows.last().unwrap();
    assert_eq!(last.source, ChatWindowSource::Canonical);
    assert_eq!(*last, record);
    assert_eq!(last.messages[0].send_state, None);
    assert_eq!(last.messages[1].id, REPLY);
    assert!(matches!(events.last(), Some(ViewEvent::ChatList { .. })));
    assert_eq!(streams(&events).len(), 5);
    assert_eq!(f.host.core().open_window(), Some(&record));
}

#[tokio::test]
async fn first_send_creates_the_chat_window_at_started() {
    let (mut f, sink) = started().await;
    open(&mut f, CHAT);
    let before = sink.events().len();
    let mut script = Script {
        updates: reply_stream(NEW_CHAT),
        cancel_after: None,
        result: Some(Ok(sent_chat(NEW_CHAT))),
    };
    run(&mut f, &sink, None, &mut script).await.unwrap();
    let events = sink.events()[before..].to_vec();
    // No window before the server named the chat.
    assert!(matches!(
        &events[0],
        ViewEvent::Stream { chat_id, event: StreamEvent::Started { .. }, .. } if chat_id == NEW_CHAT
    ));
    let windows = windows(&events);
    assert_eq!(windows[0].chat_id, NEW_CHAT);
    assert_eq!(windows[0].messages.len(), 1);
    assert_eq!(windows[0].messages[0].id, USER);
    assert_eq!(windows[0].messages[0].content, "synthetic question");
    assert_eq!(f.host.core().open_chat_id(), Some(NEW_CHAT));
    assert_eq!(windows.last().unwrap().source, ChatWindowSource::Canonical);
}

#[tokio::test]
async fn failed_send_keeps_the_user_message_with_its_error() {
    let (mut f, sink) = started().await;
    open(&mut f, CHAT);
    let before = sink.events().len();
    // The real client: the synthetic API cannot be reached.
    let result = send(
        &mut f.host,
        SEND,
        Some(CHAT.into()),
        "synthetic question".into(),
        &sink,
        &CancellationToken::new(),
    )
    .await;
    let error = result.expect_err("an unreachable API fails the send");
    let windows = windows(&sink.events()[before..]);
    let last = windows.last().unwrap();
    assert_eq!(last.messages.len(), 1);
    assert_eq!(last.messages[0].content, "synthetic question");
    assert_eq!(
        last.messages[0].send_state,
        Some(SendState::Failed {
            error: ViewErrorKind::from(&error),
            submitted: false
        })
    );
    assert_eq!(f.host.core().open_window(), Some(last));
}

#[tokio::test]
async fn cancel_stops_window_updates_and_publishes_the_cancelled_state() {
    let (mut f, sink) = started().await;
    open(&mut f, CHAT);
    let before = sink.events().len();
    let mut updates = reply_stream(CHAT);
    updates.truncate(3);
    let mut script = Script {
        updates,
        cancel_after: Some(f.host.core().send_cancel_handle()),
        result: None,
    };
    let result = run(&mut f, &sink, Some(CHAT), &mut script).await;
    assert_eq!(result, Err(Error::Cancelled));
    let events = sink.events()[before..].to_vec();
    let windows = windows(&events);
    let last = windows.last().unwrap();
    assert_eq!(
        last.messages[0].send_state,
        Some(SendState::Cancelled { submitted: true })
    );
    assert_eq!(last.messages[1].content, "Hel");
    assert_eq!(last.messages[1].status, MessageStatus::Complete);
    assert!(
        windows
            .iter()
            .all(|window| window.messages.iter().all(|m| m.content != "after cancel")),
        "no window update after the cancel"
    );
    assert!(
        !events
            .iter()
            .any(|event| matches!(event, ViewEvent::ChatList { .. }))
    );
    assert!(
        !f.host.core().send_cancel_handle().cancel(),
        "nothing runs after the end"
    );
}

#[tokio::test]
async fn stream_for_a_chat_that_is_not_open_updates_only_the_list() {
    let (mut f, sink) = started().await;
    open(&mut f, CHAT);
    let shown = f.host.core().open_window().cloned();
    let before = sink.events().len();
    let mut script = Script {
        updates: reply_stream(OTHER),
        cancel_after: None,
        result: Some(Ok(sent_chat(OTHER))),
    };
    let record = run(&mut f, &sink, Some(OTHER), &mut script).await.unwrap();
    let events = sink.events()[before..].to_vec();
    assert!(
        windows(&events).is_empty(),
        "another chat never changes the window"
    );
    assert_eq!(streams(&events).len(), 5);
    assert!(matches!(events.last(), Some(ViewEvent::ChatList { .. })));
    assert_eq!(f.host.core().open_window().cloned(), shown);
    assert_eq!(record.chat_id, OTHER);
}

#[tokio::test]
async fn queued_cancel_without_a_running_send_does_nothing() {
    let (mut f, sink) = started().await;
    let before = sink.events().len();
    handle(
        &mut f.host,
        ViewCommand::Cancel,
        &sink,
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    assert_eq!(sink.events().len(), before);
}
