//! The terminal's sink of a core send (lane L9): stream events become the UI's stream updates, send windows and lists are not painted, and updates of a dropped send still arrive in order through the relay slot.
use super::*;
use core_view::{ChatWindowSource, StreamEvent, ViewEvent, ViewSink};

const CHAT: &str = "11111111-1111-4111-8111-111111111111";

fn submitted(message_id: &str) -> ViewEvent {
    ViewEvent::Stream { request: RequestId(3), chat_id: CHAT.into(),
        event: StreamEvent::Submitted { chat_id: CHAT.into(), message_id: message_id.into() } }
}

#[tokio::test]
async fn send_sink_paints_stream_updates_but_not_send_windows_or_lists() {
    let (_directory, actor) = super::tests::fixture().await;
    let (replies, mut received) = mpsc::channel(8);
    let relay = core_host::RelaySlot::default();
    let sink = core_host::TerminalSink::new(&replies, Stamp::default(), actor.store.generation_guard(), &CancellationToken::new())
        .sending(&relay);
    sink.emit(submitted("synthetic-user")).await.unwrap();
    let chat = Chat { id: CHAT.into(), title: "Synthetic".into(), ..Default::default() };
    let window = openmates_sdk::view_model::chat_window_from_chat(&chat, ChatWindowSource::Live, None, false, false,
        openmates_sdk::view_model::PiiRestoration::PageLocal).unwrap();
    sink.emit(ViewEvent::ChatWindow { request: RequestId(3), window }).await.unwrap();
    sink.emit(ViewEvent::ChatList { rows: Vec::new(), completeness: core_view::ListCompleteness::Partial }).await.unwrap();
    let reply = received.try_recv().unwrap();
    assert!(matches!(reply.view, View::Stream(StreamUpdate::Submitted { ref message_id, .. }) if message_id == "synthetic-user"));
    assert!(received.try_recv().is_err(), "the terminal paints a send's turn from its stream updates");
}

#[tokio::test]
async fn updates_of_a_dropped_send_arrive_in_order_before_the_relay_ends() {
    let (_directory, actor) = super::tests::fixture().await;
    let (replies, mut received) = mpsc::channel(8);
    let relay = core_host::RelaySlot::default();
    let sink = core_host::TerminalSink::new(&replies, Stamp::default(), actor.store.generation_guard(), &CancellationToken::new())
        .sending(&relay);
    sink.emit_detached(vec![submitted("first"), submitted("second")]);
    drop(sink);
    let task = relay.lock().unwrap().take().expect("the dropped send's delivery task is retained");
    task.await.unwrap();
    let ids: Vec<String> = std::iter::from_fn(|| received.try_recv().ok()).map(|reply| match reply.view {
        View::Stream(StreamUpdate::Submitted { message_id, .. }) => message_id,
        _ => panic!("only stream updates are relayed"),
    }).collect();
    assert_eq!(ids, ["first", "second"]);
}
