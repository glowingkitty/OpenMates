//! The split send over the `actor_tests` fixture behind a test lease, with a scripted admission and reply stream (a synthetic server that queues a second turn into a busy chat): other calls, a queued second send, a concurrent send into another chat, stop and cancel while a reply streams.
use super::actor_tests::{CHAT, Fixture, Sink, fixture, persisted, session};
use super::send_request::TurnSummary;
use super::send_stream::{LeasedCore, TurnAdmit, TurnStep, TurnStream, ViewLease};
use super::*;
use crate::{
    client::{Client, ClientLease, SendQueueMode, SendStatus},
    error::{Error, Result},
    local_cache::FileByteStore,
    model::{Chat, Message, StreamUpdate},
};
use futures_util::future::BoxFuture;
use std::collections::HashSet;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use tokio::sync::{Mutex, MutexGuard, mpsc};
use tokio_util::sync::CancellationToken;

const OTHER: &str = "33333333-3333-4333-8333-333333333333";
const QUESTION: &str = "synthetic question";
const ANSWER: &str = "Hello there";

/// The fixture as a shell actor holds it.
struct Actor(Mutex<Fixture>);

struct Lease(Arc<Actor>);

impl ViewLease<FileByteStore> for Lease {
    fn lease(&self) -> BoxFuture<'_, Result<LeasedCore<'_, FileByteStore>>> {
        Box::pin(async move {
            let fixture = self.0.0.lock().await;
            let core = MutexGuard::map(fixture, |f| &mut f.host.core);
            Ok(Box::new(core) as LeasedCore<'_, FileByteStore>)
        })
    }
}

/// The recording sink, shared by the actor and the stream steps.
#[derive(Clone)]
struct Events(Arc<Sink>);

impl ViewSink for Events {
    fn emit(&self, event: ViewEvent) -> BoxFuture<'_, Result<()>> {
        self.0.emit(event)
    }
}

/// The synthetic server: chats with a running reply queue the next turn.
#[derive(Default)]
struct Server {
    busy: std::sync::Mutex<HashSet<String>>,
    turns: AtomicU64,
}

/// Admits a turn like the server would; its reply streams until `release`.
struct Admit {
    server: Arc<Server>,
    release: CancellationToken,
}

impl TurnAdmit for Admit {
    fn admit<'a>(
        &'a mut self,
        _client: &'a mut Client,
        chat_id: Option<&'a str>,
        _text: &'a str,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> BoxFuture<'a, Result<Box<dyn TurnStep>>> {
        Box::pin(async move {
            let chat = chat_id.ok_or(Error::Invalid("A chat id is required."))?;
            let n = self.server.turns.fetch_add(1, Ordering::SeqCst);
            let user = format!("66666666-6666-4666-8666-{n:012}");
            for update in [
                StreamUpdate::Started {
                    chat_id: chat.into(),
                    message_id: user.clone(),
                    expects_reply: true,
                },
                StreamUpdate::Submitted {
                    chat_id: chat.into(),
                    message_id: user.clone(),
                },
            ] {
                updates.send(update).await.map_err(|_| Error::Cancelled)?;
            }
            let queued = !self.server.busy.lock().unwrap().insert(chat.into());
            let reply = Reply {
                chat: chat.into(),
                user,
                updates,
                cancel,
                release: self.release.clone(),
                server: self.server.clone(),
            };
            Ok(if queued {
                Box::new(Queued(reply)) as Box<dyn TurnStep>
            } else {
                Box::new(reply) as Box<dyn TurnStep>
            })
        })
    }
}

struct Reply {
    chat: String,
    user: String,
    updates: mpsc::Sender<StreamUpdate>,
    cancel: CancellationToken,
    release: CancellationToken,
    server: Arc<Server>,
}

impl Reply {
    fn summary(&self, status: SendStatus) -> TurnSummary {
        let queued = status == SendStatus::Queued;
        TurnSummary {
            status,
            chat_id: self.chat.clone(),
            user_message_id: Some(self.user.clone()),
            assistant_message_id: (!queued).then(|| format!("reply-{}", self.user)),
            queue_mode: queued.then_some(SendQueueMode::FollowUp),
            queue_revision: queued.then_some(1),
        }
    }

    fn chat(&self, reply: bool) -> Chat {
        let message = |id: &str, role: &str, content: &str| Message {
            id: id.into(),
            role: role.into(),
            content: content.into(),
            ..Message::default()
        };
        let mut messages = vec![message(&self.user, "user", QUESTION)];
        if reply {
            messages.push(message(
                &format!("reply-{}", self.user),
                "assistant",
                ANSWER,
            ));
        }
        Chat {
            id: self.chat.clone(),
            title: "Synthetic sent title".into(),
            category: String::new(),
            messages,
        }
    }
}

impl TurnStep for Reply {
    fn stream(
        self: Box<Self>,
        client: Arc<dyn ClientLease>,
    ) -> BoxFuture<'static, Result<(Chat, TurnSummary)>> {
        Box::pin(async move {
            let content = StreamUpdate::Content {
                content: "Hel".into(),
                thinking: String::new(),
                mate: "Synthetic mate".into(),
            };
            let _ = self.updates.send(content).await;
            let released = tokio::select! {
                () = self.release.cancelled() => true,
                () = self.cancel.cancelled() => false,
            };
            self.server.busy.lock().unwrap().remove(&self.chat);
            if !released {
                return Err(Error::Cancelled);
            }
            // One client phase, as the real stream's artifact write.
            drop(client.lease().await?);
            let completed = StreamUpdate::Completed {
                chat_id: self.chat.clone(),
                message_id: format!("reply-{}", self.user),
                content: ANSWER.into(),
            };
            let _ = self.updates.send(completed).await;
            Ok((self.chat(true), self.summary(SendStatus::Completed)))
        })
    }
}

/// A turn the server queued behind the running reply.
struct Queued(Reply);

impl TurnStep for Queued {
    fn stream(
        self: Box<Self>,
        _client: Arc<dyn ClientLease>,
    ) -> BoxFuture<'static, Result<(Chat, TurnSummary)>> {
        Box::pin(async move {
            let status = StreamUpdate::Status("Message saved and queued.".into());
            let _ = self.0.updates.send(status).await;
            Ok((self.0.chat(false), self.0.summary(SendStatus::Queued)))
        })
    }
}

/// A started actor with `CHAT` open.
async fn started() -> (Arc<Actor>, Arc<Sink>) {
    let mut f = fixture();
    persisted(&mut f).await;
    let sink = Arc::new(Sink::default());
    start(&mut f.host, session(), &*sink, &CancellationToken::new())
        .await
        .unwrap();
    let record = chat_window_from_chat(
        &Chat {
            id: CHAT.into(),
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
    core.begin_window(RequestId(5), CHAT);
    assert!(core.publish_window(RequestId(5), record).is_some());
    (Arc::new(Actor(Mutex::new(f))), sink)
}

/// Admit `request` into `chat` on the actor, then release it.
async fn begin(
    actor: &Arc<Actor>,
    sink: &Arc<Sink>,
    admit: &mut Admit,
    request: u64,
    chat: &str,
) -> Result<TurnStream<FileByteStore, Events>> {
    let lease: Arc<dyn ViewLease<FileByteStore>> = Arc::new(Lease(actor.clone()));
    let mut f = actor.0.lock().await;
    f.host
        .core
        .admit_turn(
            RequestId(request),
            Some(chat.into()),
            QUESTION.into(),
            Events(sink.clone()),
            &CancellationToken::new(),
            lease,
            admit,
        )
        .await
}

/// Wait until the reply of `request` streams ("Hel" relayed).
async fn streaming(sink: &Sink, request: u64) {
    for _ in 0..400 {
        let relayed = sink.events().iter().any(|event| {
            matches!(event, ViewEvent::Stream { request: r, event: StreamEvent::Content { content, .. }, .. }
                if *r == RequestId(request) && content == "Hel")
        });
        if relayed {
            return;
        }
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    panic!("request {request} never streamed");
}

/// The actor, locked within a short bound: no turn holds it while streaming.
async fn lock(actor: &Actor) -> MutexGuard<'_, Fixture> {
    tokio::time::timeout(Duration::from_secs(2), actor.0.lock())
        .await
        .expect("a streaming turn holds the actor only per phase")
}

fn admitter(server: &Arc<Server>) -> Admit {
    Admit {
        server: server.clone(),
        release: CancellationToken::new(),
    }
}

/// The send state of the last window message of `request` with `content`.
fn send_state(sink: &Sink, request: u64) -> Option<SendState> {
    sink.events().iter().rev().find_map(|event| match event {
        ViewEvent::ChatWindow { request: r, window } if *r == RequestId(request) => window
            .messages
            .iter()
            .find(|message| message.content == QUESTION)
            .and_then(|message| message.send_state.clone()),
        _ => None,
    })
}

#[tokio::test]
async fn another_call_completes_while_a_reply_streams() {
    let (actor, sink) = started().await;
    let server = Arc::new(Server::default());
    let mut admit = admitter(&server);
    let first = begin(&actor, &sink, &mut admit, 1, CHAT).await.unwrap();
    let first = tokio::spawn(first.run());
    streaming(&sink, 1).await;
    {
        let mut f = lock(&actor).await;
        handle(
            &mut f.host,
            ViewCommand::CloseChat {
                chat_id: OTHER.into(),
            },
            &*sink,
            &CancellationToken::new(),
        )
        .await
        .unwrap();
        f.host.core_mut().persist().await.unwrap();
    }
    assert!(!first.is_finished(), "the reply still streams");
    admit.release.cancel();
    let receipt = first.await.unwrap().unwrap();
    assert!(receipt.status == SendStatus::Completed);
    assert_eq!(receipt.window.source, ChatWindowSource::Canonical);
    assert_eq!(receipt.window.messages[1].content, ANSWER);
    let f = lock(&actor).await;
    assert_eq!(f.host.core().open_window(), Some(&receipt.window));
    assert!(
        !f.host.core().send_cancel_handle().cancel(),
        "nothing runs after the end"
    );
}

#[tokio::test]
async fn a_second_send_into_the_streaming_chat_comes_back_queued() {
    let (actor, sink) = started().await;
    let server = Arc::new(Server::default());
    let mut admit = admitter(&server);
    let first = tokio::spawn(
        begin(&actor, &sink, &mut admit, 1, CHAT)
            .await
            .unwrap()
            .run(),
    );
    streaming(&sink, 1).await;
    let mut again = admitter(&server);
    let second = begin(&actor, &sink, &mut again, 2, CHAT).await.unwrap();
    let queued = tokio::time::timeout(Duration::from_secs(2), second.run())
        .await
        .expect("a second send never waits for the running reply")
        .unwrap();
    assert!(queued.status == SendStatus::Queued);
    assert!(queued.queue_mode == Some(SendQueueMode::FollowUp));
    assert_eq!(queued.queue_revision, Some(1));
    assert!(queued.assistant_message_id.is_none());
    assert!(!first.is_finished(), "the first reply still streams");
    admit.release.cancel();
    let completed = first.await.unwrap().unwrap();
    assert!(completed.status == SendStatus::Completed);
}

#[tokio::test]
async fn a_send_into_another_chat_streams_concurrently() {
    let (actor, sink) = started().await;
    let server = Arc::new(Server::default());
    let mut admit = admitter(&server);
    let first = tokio::spawn(
        begin(&actor, &sink, &mut admit, 1, CHAT)
            .await
            .unwrap()
            .run(),
    );
    streaming(&sink, 1).await;
    let mut other = admitter(&server);
    let second = tokio::spawn(
        begin(&actor, &sink, &mut other, 2, OTHER)
            .await
            .unwrap()
            .run(),
    );
    streaming(&sink, 2).await;
    other.release.cancel();
    let receipt = tokio::time::timeout(Duration::from_secs(2), second)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert!(receipt.status == SendStatus::Completed);
    assert_eq!(receipt.chat_id, OTHER);
    assert!(!first.is_finished(), "the first reply still streams");
    admit.release.cancel();
    assert!(first.await.unwrap().unwrap().status == SendStatus::Completed);
}

#[tokio::test]
async fn stop_reply_during_the_stream_ends_the_turn_cancelled() {
    let (actor, sink) = started().await;
    let server = Arc::new(Server::default());
    let mut admit = admitter(&server);
    let first = tokio::spawn(
        begin(&actor, &sink, &mut admit, 1, CHAT)
            .await
            .unwrap()
            .run(),
    );
    streaming(&sink, 1).await;
    {
        let mut f = lock(&actor).await;
        // The synthetic API is unreachable: the server stop itself fails,
        // the local turn has ended already.
        let stopped = tokio::time::timeout(
            Duration::from_secs(30),
            stop_reply(
                &mut f.host,
                CHAT.into(),
                "synthetic-task".into(),
                &CancellationToken::new(),
            ),
        )
        .await
        .expect("stop answers");
        assert!(stopped.is_err());
    }
    let result = tokio::time::timeout(Duration::from_secs(2), first)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(result.err(), Some(Error::Cancelled));
    assert_eq!(
        send_state(&sink, 1),
        Some(SendState::Cancelled { submitted: true })
    );
    assert!(server.busy.lock().unwrap().is_empty());
}

#[tokio::test]
async fn cancel_handle_ends_a_streaming_turn_without_the_actor() {
    let (actor, sink) = started().await;
    let server = Arc::new(Server::default());
    let mut admit = admitter(&server);
    let cancel = lock(&actor).await.host.core().send_cancel_handle();
    let first = tokio::spawn(
        begin(&actor, &sink, &mut admit, 1, CHAT)
            .await
            .unwrap()
            .run(),
    );
    streaming(&sink, 1).await;
    // Hold the actor: cancelling needs no actor lock.
    let held = lock(&actor).await;
    assert!(cancel.cancel(), "a streaming turn is cancellable");
    drop(held);
    let result = tokio::time::timeout(Duration::from_secs(2), first)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(result.err(), Some(Error::Cancelled));
    assert_eq!(
        send_state(&sink, 1),
        Some(SendState::Cancelled { submitted: true })
    );
    assert!(!cancel.cancel(), "nothing runs after the end");
}
