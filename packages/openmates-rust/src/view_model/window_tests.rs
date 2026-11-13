//! The core chat window over the `actor_tests` fixture (real cache directory,
//! unreachable API): cached window before recovery and network, paging order
//! and de-duplication, live data for the open chat versus another chat,
//! closing, and mark-read.
use super::actor_tests::{API, CHAT, Fixture, OWNER, Sink, fixture, names, persisted, session};
use super::window::{merge_latest, merge_older};
use super::*;
use crate::{
    client::{ChatModels, ChatSelectionUpdate},
    error::Error,
    model::{Chat, Item, Message},
};
use serde_json::json;
use tokio_util::sync::CancellationToken;

const OTHER: &str = "33333333-3333-4333-8333-333333333333";

fn message(id: &str) -> MessageRecord {
    MessageRecord {
        id: id.into(),
        role: MessageRole::User,
        status: MessageStatus::Complete,
        content: format!("synthetic {id}"),
        sender: String::new(),
        thinking: String::new(),
        embeds: Vec::new(),
        send_state: None,
        metadata: MessageMetadata::default(),
    }
}

fn ids(messages: &[MessageRecord]) -> Vec<&str> {
    messages.iter().map(|message| message.id.as_str()).collect()
}

fn chat(id: &str, content: &str) -> Chat {
    Chat {
        id: id.into(),
        title: "Synthetic live title".into(),
        category: String::new(),
        messages: vec![Message {
            id: "44444444-4444-4444-8444-444444444444".into(),
            role: "assistant".into(),
            content: content.into(),
            ..Message::default()
        }],
    }
}

fn row(id: &str) -> Item {
    Item {
        id: id.into(),
        title: "Synthetic row".into(),
        fields: json!({}),
        ..Item::default()
    }
}

fn live(selection: ChatSelectionUpdate) -> ChatModels {
    ChatModels {
        items: vec![row(CHAT), row(OTHER)],
        selection,
    }
}

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

fn window_events(events: &[ViewEvent]) -> Vec<(RequestId, ChatWindowRecord)> {
    events
        .iter()
        .filter_map(|event| match event {
            ViewEvent::ChatWindow { request, window } => Some((*request, window.clone())),
            _ => None,
        })
        .collect()
}

#[test]
fn older_page_is_prepended_oldest_first_without_repeating_known_ids() {
    let mut messages = vec![message("c"), message("d")];
    let added = merge_older(
        &mut messages,
        vec![message("a"), message("b"), message("b"), message("c")],
    );
    assert_eq!(added, 2);
    assert_eq!(ids(&messages), ["a", "b", "c", "d"]);
    assert_eq!(merge_older(&mut messages, vec![message("a")]), 0);
    assert_eq!(ids(&messages), ["a", "b", "c", "d"]);
}

#[test]
fn latest_page_appends_only_replies_the_window_does_not_show() {
    let mut messages = vec![message("a"), message("b")];
    assert_eq!(
        merge_latest(&mut messages, vec![message("b"), message("c")]),
        1
    );
    assert_eq!(ids(&messages), ["a", "b", "c"]);
}

#[tokio::test]
async fn open_emits_the_cached_window_before_recovery_and_any_network() {
    let (mut f, sink) = started().await;
    let before = sink.events().len();
    let open = ViewCommand::OpenChat {
        request: RequestId(3),
        chat_id: CHAT.into(),
    };
    // The strict read cannot reach the synthetic origin; its outcome is not
    // the subject here, only what precedes it.
    let _strict = handle(&mut f.host, open, &sink, &CancellationToken::new()).await;
    let events = sink.events();
    let ViewEvent::ChatWindow { request, window } = &events[before] else {
        panic!("cached window expected first: {events:?}");
    };
    assert_eq!(*request, RequestId(3));
    assert_eq!(window.source, ChatWindowSource::Cached);
    assert_eq!(window.chat_id, CHAT);
    assert_eq!(window.messages[0].content, "synthetic body");
    // Message facts come from the held row (`created_at`); absent ones stay `None`.
    assert_eq!(window.messages[0].metadata.created_at, Some(1));
    assert_eq!(window.messages[0].metadata.model_name, None);
    assert_eq!(window.has_more_after, None);
    let recover = f
        .host
        .calls
        .iter()
        .find(|(name, _)| name == &format!("recover open {CHAT}"))
        .expect("selected-chat recovery runs");
    assert_eq!(recover.1, before + 1, "recovery follows the cached window");
    assert_eq!(f.host.core().open_chat_id(), Some(CHAT));
}

#[tokio::test]
async fn open_refuses_a_volatile_or_malformed_chat_without_host_calls() {
    let (mut f, sink) = started().await;
    let calls = f.host.calls.len();
    let result = open_chat(
        &mut f.host,
        RequestId(1),
        "chat-1".into(),
        &sink,
        &CancellationToken::new(),
    )
    .await;
    assert!(matches!(result, Err(Error::Invalid(_))));
    assert_eq!(f.host.calls.len(), calls);
    assert_eq!(f.host.core().open_chat_id(), None);
}

#[tokio::test]
async fn live_data_updates_only_the_open_chat_window() {
    let (mut f, sink) = started().await;
    f.host.core_mut().begin_window(RequestId(5), CHAT);
    let before = sink.events().len();
    let core = f.host.core_mut();
    core.apply_live_models(
        live(ChatSelectionUpdate::Updated(chat(OTHER, "other"))),
        &sink,
    )
    .await
    .unwrap();
    let events = sink.events();
    assert!(matches!(events[before], ViewEvent::ChatList { .. }));
    assert!(
        window_events(&events[before..]).is_empty(),
        "another chat never changes the window"
    );

    let before = events.len();
    let core = f.host.core_mut();
    core.apply_live_models(
        live(ChatSelectionUpdate::Updated(chat(CHAT, "live reply"))),
        &sink,
    )
    .await
    .unwrap();
    let windows = window_events(&sink.events()[before..]);
    assert_eq!(windows.len(), 1);
    let (request, window) = &windows[0];
    assert_eq!(
        *request,
        RequestId(5),
        "live windows answer the open request"
    );
    assert_eq!(window.source, ChatWindowSource::Live);
    assert_eq!(window.messages[0].content, "live reply");
    assert_eq!(f.host.core().open_window(), Some(window));

    let before = sink.events().len();
    let settled = ChatSelectionUpdate::CacheSettled(chat(CHAT, "settled"));
    f.host
        .core_mut()
        .apply_live_models(live(settled), &sink)
        .await
        .unwrap();
    let windows = window_events(&sink.events()[before..]);
    assert_eq!(windows[0].1.source, ChatWindowSource::LiveSettled);
}

#[tokio::test]
async fn unavailable_open_chat_closes_its_window() {
    let (mut f, sink) = started().await;
    f.host.core_mut().begin_window(RequestId(5), CHAT);
    let before = sink.events().len();
    let gone = ChatSelectionUpdate::Unavailable {
        chat_id: CHAT.into(),
    };
    f.host
        .core_mut()
        .apply_live_models(live(gone), &sink)
        .await
        .unwrap();
    assert_eq!(
        sink.events().last(),
        Some(&ViewEvent::ChatUnavailable {
            chat_id: CHAT.into()
        })
    );
    assert_eq!(sink.events().len(), before + 2);
    assert_eq!(f.host.core().open_chat_id(), None);
}

#[tokio::test]
async fn closed_chat_receives_no_further_window_updates() {
    let (mut f, sink) = started().await;
    f.host.core_mut().begin_window(RequestId(5), CHAT);
    let close = ViewCommand::CloseChat {
        chat_id: CHAT.into(),
    };
    handle(&mut f.host, close, &sink, &CancellationToken::new())
        .await
        .unwrap();
    assert_eq!(f.host.core().open_chat_id(), None);
    let before = sink.events().len();
    f.host
        .core_mut()
        .apply_live_models(
            live(ChatSelectionUpdate::Updated(chat(CHAT, "late"))),
            &sink,
        )
        .await
        .unwrap();
    let events = sink.events();
    assert_eq!(events.len(), before + 1, "only the chat list changes");
    assert!(window_events(&events[before..]).is_empty());
}

#[tokio::test]
async fn load_older_needs_an_open_chat_and_keeps_a_complete_window_offline() {
    let (mut f, sink) = started().await;
    let cancel = CancellationToken::new();
    let older = load_older(&mut f.host, RequestId(9), CHAT.into(), &sink, &cancel).await;
    assert_eq!(older, Err(Error::Invalid("This chat is not open.")));

    let core = f.host.core_mut();
    core.begin_window(RequestId(5), CHAT);
    let complete = ChatWindowRecord {
        chat_id: CHAT.into(),
        title: "Synthetic".into(),
        category: String::new(),
        messages: vec![message("a")],
        source: ChatWindowSource::Canonical,
        has_more_before: Some(false),
        has_more_after: Some(false),
        history_complete: true,
        refreshing: false,
        pii_restoration: PiiRestoration::AllCachedUserRows,
    };
    assert!(
        core.publish_window(RequestId(5), complete.clone())
            .is_some()
    );
    let before = sink.events().len();
    // The API is unreachable: success proves no page was requested.
    load_older(&mut f.host, RequestId(9), CHAT.into(), &sink, &cancel)
        .await
        .unwrap();
    assert_eq!(
        sink.events()[before..],
        [ViewEvent::ChatWindow {
            request: RequestId(9),
            window: complete
        }]
    );
}

#[tokio::test]
async fn a_newer_open_supersedes_the_window_of_an_older_request() {
    let (mut f, _sink) = started().await;
    let core = f.host.core_mut();
    core.begin_window(RequestId(1), CHAT);
    core.begin_window(RequestId(2), OTHER);
    let stale = ChatWindowRecord {
        chat_id: CHAT.into(),
        title: String::new(),
        category: String::new(),
        messages: Vec::new(),
        source: ChatWindowSource::Cached,
        has_more_before: None,
        has_more_after: None,
        history_complete: false,
        refreshing: true,
        pii_restoration: PiiRestoration::PageLocal,
    };
    assert!(core.publish_window(RequestId(1), stale).is_none());
    assert_eq!(core.open_chat_id(), Some(OTHER));
}

#[tokio::test]
async fn mark_read_of_an_already_read_chat_sends_nothing_and_persists() {
    let mut f = fixture();
    let core = f.host.core_mut();
    let mut cached = super::actor_tests::snapshot();
    cached["chats"][CHAT]["unread_count"] = json!(0);
    core.client_mut().reset(API, Some(session())).unwrap();
    core.client_mut()
        .restore_ciphertext_snapshot(&cached)
        .unwrap();
    core.client_mut().adopt_test_principal(OWNER).unwrap();
    let cancel = CancellationToken::new();
    let command = ViewCommand::MarkRead {
        chat_id: CHAT.into(),
    };
    handle(&mut f.host, command, &Sink::default(), &cancel)
        .await
        .unwrap();
    assert!(f.credentials.stored.lock().unwrap().is_some(), "persisted");
    // A chat with an unknown counter needs the server, which is unreachable.
    let unknown = ViewCommand::MarkRead {
        chat_id: OTHER.into(),
    };
    let sent = handle(&mut f.host, unknown, &Sink::default(), &cancel).await;
    assert!(sent.is_err() && !matches!(sent, Err(Error::Invalid(_))));
    assert!(names(&f.host.calls).is_empty(), "mark-read is not bridged");
}
