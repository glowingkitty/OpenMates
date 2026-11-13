//! The shell passthrough of the view-model actor: forwarded frames in order,
//! owned frames kept back, the explicit drop report for a slow shell, socket
//! replacement order, and shell sends refused or settled without a socket.
use super::{
    SocketPassthrough, UnownedFrameError, ViewCommand, ViewEvent, ViewHost, ViewSink,
    actor_tests::fixture, handle, unowned_flows::UnownedSeam,
};
use crate::error::{Error, Result};
use futures_util::future::BoxFuture;
use serde_json::json;
use std::sync::{Arc, Mutex};
use tokio::sync::Notify;
use tokio_util::sync::CancellationToken;

/// Records every event and wakes waiters.
#[derive(Default)]
struct Recorder {
    events: Mutex<Vec<ViewEvent>>,
    changed: Notify,
}

impl Recorder {
    fn events(&self) -> Vec<ViewEvent> {
        self.events.lock().unwrap().clone()
    }

    async fn wait_for(&self, count: usize) -> Vec<ViewEvent> {
        loop {
            let changed = self.changed.notified();
            let events = self.events();
            if events.len() >= count {
                return events;
            }
            tokio::time::timeout(std::time::Duration::from_secs(4), changed)
                .await
                .expect("forwarder delivered too few events");
        }
    }
}

impl ViewSink for Recorder {
    fn emit(&self, event: ViewEvent) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            self.events.lock().unwrap().push(event);
            self.changed.notify_one();
            Ok(())
        })
    }
}

fn frame(event_type: &str, n: u64) -> ViewEvent {
    ViewEvent::UnownedSocketFrame {
        event_type: event_type.into(),
        payload_json: json!({ "n": n }).to_string(),
    }
}

fn seam_with(sink: &Arc<Recorder>) -> (UnownedSeam, Arc<SocketPassthrough>) {
    let mut seam = UnownedSeam::default();
    seam.forward_to(sink.clone());
    let passthrough = Arc::new(SocketPassthrough::default());
    seam.replace(Some(passthrough.clone()));
    (seam, passthrough)
}

#[tokio::test]
async fn forwards_unowned_frames_in_arrival_order_and_keeps_owned_ones_back() {
    let sink = Arc::new(Recorder::default());
    let (_seam, socket) = seam_with(&sink);
    socket.observe("embed_update", &json!({ "n": 1 }));
    socket.observe("phase_2_last_20_chats_ready", &json!({ "n": 2 }));
    socket.observe("chat_deleted", &json!({ "n": 3 }));
    socket.observe("ai_message_update", &json!({ "n": 4 }));
    socket.observe("reminder_fired", &json!({ "n": 5 }));
    socket.close_inbound();
    let events = sink.wait_for(3).await;
    assert_eq!(
        events,
        [
            frame("embed_update", 1),
            frame("chat_deleted", 3),
            frame("reminder_fired", 5)
        ]
    );
}

#[tokio::test]
async fn a_slow_shell_gets_an_explicit_drop_report_at_the_gap() {
    let sink = Arc::new(Recorder::default());
    let (_seam, socket) = seam_with(&sink);
    // The forwarder task has not run yet: the shell drains nothing while
    // the socket delivers more than the queue holds.
    let total = super::INBOUND_FRAME_LIMIT as u64 + 44;
    for n in 0..total {
        socket.observe("synthetic_shell_event", &json!({ "n": n }));
    }
    let limit = super::INBOUND_FRAME_LIMIT;
    sink.wait_for(limit + 1).await;
    // Drained: the next frame queues again, after the report.
    socket.observe("synthetic_shell_event", &json!({ "n": total }));
    socket.close_inbound();
    let delivered = sink.wait_for(limit + 2).await;
    assert_eq!(delivered.len(), limit + 2);
    for (n, event) in delivered[..limit].iter().enumerate() {
        assert_eq!(*event, frame("synthetic_shell_event", n as u64));
    }
    assert_eq!(
        delivered[limit],
        ViewEvent::UnownedSocketFramesDropped { count: 44 }
    );
    assert_eq!(delivered[limit + 1], frame("synthetic_shell_event", total));
}

#[tokio::test]
async fn a_replaced_socket_delivers_all_its_frames_before_the_new_one() {
    let sink = Arc::new(Recorder::default());
    let (mut seam, old) = seam_with(&sink);
    old.observe("synthetic_shell_event", &json!({ "n": 1 }));
    old.observe("synthetic_shell_event", &json!({ "n": 2 }));
    let new = Arc::new(SocketPassthrough::default());
    seam.replace(Some(new.clone()));
    new.observe("synthetic_shell_event", &json!({ "n": 3 }));
    // The replaced socket's queue was closed: late frames are not kept.
    old.observe("synthetic_shell_event", &json!({ "n": 99 }));
    new.close_inbound();
    let events = sink.wait_for(3).await;
    assert_eq!(
        events,
        [
            frame("synthetic_shell_event", 1),
            frame("synthetic_shell_event", 2),
            frame("synthetic_shell_event", 3)
        ]
    );
}

#[tokio::test]
async fn without_a_forwarder_nothing_is_kept() {
    let mut seam = UnownedSeam::default();
    let socket = Arc::new(SocketPassthrough::default());
    seam.replace(Some(socket.clone()));
    socket.observe("synthetic_shell_event", &json!({ "n": 1 }));
    assert!(socket.attach().is_none(), "forwarding was disabled");
}

#[tokio::test]
async fn frames_buffered_before_the_shell_opts_in_are_delivered_first() {
    let mut seam = UnownedSeam::default();
    let socket = Arc::new(SocketPassthrough::default());
    socket.observe("synthetic_shell_event", &json!({ "n": 1 }));
    let sink = Arc::new(Recorder::default());
    seam.forward_to(sink.clone());
    seam.replace(Some(socket.clone()));
    socket.observe("synthetic_shell_event", &json!({ "n": 2 }));
    socket.close_inbound();
    assert_eq!(
        sink.wait_for(2).await,
        [
            frame("synthetic_shell_event", 1),
            frame("synthetic_shell_event", 2)
        ]
    );
}

#[tokio::test]
async fn send_refuses_core_owned_types_before_checking_the_socket() {
    let f = fixture();
    let sender = f.host.core().unowned_frame_sender();
    for owned in [
        "phased_sync_request",
        "get_draft_versions",
        "chat_message_added",
        "chat_deleted",
    ] {
        assert_eq!(
            sender.send(owned, "{}").await,
            Err(UnownedFrameError::CoreOwned {
                event_type: owned.into()
            })
        );
    }
    assert_eq!(
        sender.send("Not A Type", "{}").await,
        Err(UnownedFrameError::InvalidEventType)
    );
    assert_eq!(
        sender.send("update_draft", "[1]").await,
        Err(UnownedFrameError::InvalidPayload)
    );
}

#[tokio::test]
async fn send_without_a_socket_settles_disconnected_through_the_command_too() {
    let mut f = fixture();
    let sender = f.host.core().unowned_frame_sender();
    assert_eq!(
        sender.send("update_draft", "{}").await,
        Err(UnownedFrameError::Disconnected)
    );
    let sink = super::actor_tests::Sink::default();
    let command = ViewCommand::SendUnownedFrame {
        event_type: "update_draft".into(),
        payload_json: "{}".into(),
    };
    let result = handle(&mut f.host, command, &sink, &CancellationToken::new()).await;
    assert_eq!(result, Err(Error::Offline));
    let owned = ViewCommand::SendUnownedFrame {
        event_type: "set_active_chat".into(),
        payload_json: "{}".into(),
    };
    let result = handle(&mut f.host, owned, &sink, &CancellationToken::new()).await;
    assert!(matches!(
        result,
        Err(Error::Unavailable {
            code: "socket_frame_core_owned",
            ..
        })
    ));
}

#[tokio::test]
async fn queued_sends_settle_disconnected_when_the_socket_ends_and_overflow_is_busy() {
    let mut seam = UnownedSeam::default();
    let socket = Arc::new(SocketPassthrough::default());
    seam.replace(Some(socket.clone()));
    let sender = seam.sender();
    let waiting: Vec<_> = (0..super::OUTBOUND_QUEUE_LIMIT)
        .map(|_| {
            let sender = sender.clone();
            tokio::spawn(async move { sender.send("update_draft", "{}").await })
        })
        .collect();
    // Let every spawned send queue its frame (nobody serves the socket).
    for _ in 0..8 {
        tokio::task::yield_now().await;
    }
    assert_eq!(
        sender.send("update_draft", "{}").await,
        Err(UnownedFrameError::Busy)
    );
    socket.close().await;
    for task in waiting {
        assert_eq!(task.await.unwrap(), Err(UnownedFrameError::Disconnected));
    }
    assert_eq!(
        sender.send("update_draft", "{}").await,
        Err(UnownedFrameError::Disconnected)
    );
}
