//! The view-model actor's `Send` and `Cancel` (lane L9): mention resolution,
//! the optimistic user message, the streamed reply relayed in order as
//! `Stream` events and applied to the open window (`send_turn.rs`),
//! persistence even after a cancel, and the completed, failed or cancelled
//! end state. Moved from the TUI `runtime.rs` (`send_message` and its relay
//! task); spec `a2-design.md` (View model) and `architecture.sync` (send).
//!
//! Ordering: every stream update is emitted before the window it changed;
//! updates the client queued before a dropped send (a shell's cancel grace
//! ran out) still reach [`ViewSink::emit_detached`], so a `Submitted` fence
//! is never lost and a shell never resends a turn that may have committed.
use super::{
    ChatWindowRecord, ChatWindowSource, ListCompleteness, PiiRestoration, RequestId, ViewErrorKind,
    ViewEvent,
    actor::ViewCore,
    actor_host::{ViewHost, ViewSink},
    chat_window_from_chat,
    send_turn::SendTurn,
    stream_event_from_update,
    window::OpenWindow,
};
use crate::{
    client::Client,
    error::{Error, Result},
    local_cache::ByteStore,
    model::{Chat, StreamUpdate},
};
use futures_util::future::BoxFuture;
use std::sync::{Arc, Mutex, PoisonError};
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

/// Capacity of the client-to-actor stream channel; a slow sink applies
/// back-pressure to the client's reader instead of buffering without bound.
const STREAM_CAPACITY: usize = 64;

/// The cancel token of the running send, shared with [`SendCancelHandle`].
pub(super) type ForegroundSlot = Arc<Mutex<Option<CancellationToken>>>;

/// Cancels the running send without borrowing the actor (a shell's priority
/// lane holds it while the actor is busy with the send). Cheap to clone.
#[derive(Clone)]
pub struct SendCancelHandle {
    slot: ForegroundSlot,
}

impl SendCancelHandle {
    pub(super) fn new(slot: ForegroundSlot) -> Self {
        Self { slot }
    }

    /// Cancel the running send; returns whether one was running. The send
    /// then persists what was admitted, publishes its cancelled end state and
    /// ends with `Cancelled`.
    pub fn cancel(&self) -> bool {
        // A poisoned lock only means a panic elsewhere; the token stays valid.
        let slot = self.slot.lock().unwrap_or_else(PoisonError::into_inner);
        slot.as_ref().map(CancellationToken::cancel).is_some()
    }
}

/// Clears the foreground slot when the send ends or is dropped.
struct Foreground(ForegroundSlot);

impl Foreground {
    fn register(slot: &ForegroundSlot, token: CancellationToken) -> Self {
        *slot.lock().unwrap_or_else(PoisonError::into_inner) = Some(token);
        Self(slot.clone())
    }
}

impl Drop for Foreground {
    fn drop(&mut self) {
        *self.0.lock().unwrap_or_else(PoisonError::into_inner) = None;
    }
}

/// The client call of one turn. The production dispatcher is
/// `Client::send_message`; tests script the stream.
pub(super) trait TurnDispatch: Send {
    /// Submit `text` to `chat_id` (`None`: a new chat), reporting progress on
    /// `updates`, and return the sent chat.
    fn dispatch<'a>(
        &'a mut self,
        client: &'a mut Client,
        chat_id: Option<&'a str>,
        text: &'a str,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> BoxFuture<'a, Result<Chat>>;
}

/// `Client::send_message`, the encrypted turn over the chat socket.
pub(super) struct ClientDispatch;

impl TurnDispatch for ClientDispatch {
    fn dispatch<'a>(
        &'a mut self,
        client: &'a mut Client,
        chat_id: Option<&'a str>,
        text: &'a str,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> BoxFuture<'a, Result<Chat>> {
        Box::pin(client.send_message(chat_id, text, updates, cancel))
    }
}

/// Send `text` as the turn of `request` to `chat_id` (`None` creates a chat)
/// and return the sent chat as a window record (`Canonical`).
///
/// Events: the optimistic user message in the open window, then per stream
/// update a `Stream` event plus the changed window (`Live`), then the sent
/// chat's window (`Canonical`) and the chat list. A turn into a chat that is
/// not open emits `Stream` events and the list only. A failed send keeps the
/// user message with `SendState::Failed`; a cancel (through `cancel` or a
/// [`SendCancelHandle`]) publishes `SendState::Cancelled`, stops all window
/// updates and ends with `Cancelled`. Credentials and admitted encrypted
/// state are persisted in every case before the end state.
///
/// # Errors
/// `Invalid` for an unknown `@mention` (nothing is sent) or a refused turn;
/// send, persistence and sink errors; `Cancelled` when cancelled.
pub fn send<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: Option<String>,
    text: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<ChatWindowRecord>> {
    Box::pin(async move {
        host.core_mut()
            .send_turn(request, chat_id, text, sink, cancel, &mut ClientDispatch)
            .await
    })
}

/// `Cancel` as a queued command: cancels a running send, if any. The actor
/// serves commands one at a time, so a shell that must interrupt a running
/// send uses [`ViewCore::send_cancel_handle`] instead.
pub fn cancel_send<S: ByteStore + 'static, H: ViewHost<S>>(host: &H) -> bool {
    host.core().send_cancel_handle().cancel()
}

impl<S: ByteStore + 'static> ViewCore<S> {
    /// A handle that cancels the running send without the actor.
    pub fn send_cancel_handle(&self) -> SendCancelHandle {
        SendCancelHandle::new(self.foreground.clone())
    }

    /// [`send`] with an explicit dispatcher (tests script the client).
    pub(super) async fn send_turn<K: ViewSink, D: TurnDispatch>(
        &mut self,
        request: RequestId,
        chat_id: Option<String>,
        text: String,
        sink: &K,
        cancel: &CancellationToken,
        dispatch: &mut D,
    ) -> Result<ChatWindowRecord> {
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let turn_cancel = cancel.child_token();
        let _foreground = Foreground::register(&self.foreground, turn_cancel.clone());
        let mut turn = SendTurn::new(request, chat_id.clone(), &text, self.open_chat_id());
        if let Some(event) = turn.begin(&mut self.window) {
            sink.emit(event).await?;
        }
        let sent = self
            .dispatch_turn(
                &mut turn,
                chat_id.as_deref(),
                &text,
                sink,
                &turn_cancel,
                dispatch,
            )
            .await;
        // Preserve rotated cookies and any admitted encrypted state, also
        // after a cancel.
        let persisted = self.persist().await;
        if turn_cancel.is_cancelled() {
            if let Some(event) = turn.cancel(&mut self.window) {
                // Best effort: the shell may already have stopped listening
                // to a cancelled request; the result is `Cancelled` anyway.
                let _ = sink.emit(event).await;
            }
            return Err(Error::Cancelled);
        }
        let chat = match persisted.and(sent) {
            Ok(chat) => chat,
            Err(error) => {
                if let Some(event) = turn.fail(ViewErrorKind::from(&error), &mut self.window) {
                    sink.emit(event).await?;
                }
                return Err(error);
            }
        };
        let record = chat_window_from_chat(
            &chat,
            ChatWindowSource::Canonical,
            None,
            false,
            false,
            PiiRestoration::PageLocal,
        )
        .map_err(|_| Error::Protocol)?;
        if turn.tracked() {
            // The sent chat replaces the stream; paging restarts from it.
            self.window = Some(OpenWindow {
                request,
                chat_id: chat.id.clone(),
                record: Some(record.clone()),
                older: None,
            });
            sink.emit(ViewEvent::ChatWindow {
                request,
                window: record.clone(),
            })
            .await?;
        }
        let items = self.client.cached_chat_items()?;
        sink.emit(self.chat_list_event(items, ListCompleteness::Partial)?)
            .await?;
        Ok(record)
    }

    /// Resolve mentions, then run the client's send and the relay of its
    /// updates concurrently (the client and the window are disjoint fields).
    async fn dispatch_turn<K: ViewSink, D: TurnDispatch>(
        &mut self,
        turn: &mut SendTurn,
        chat_id: Option<&str>,
        text: &str,
        sink: &K,
        cancel: &CancellationToken,
        dispatch: &mut D,
    ) -> Result<Chat> {
        // Same send-time mention resolution as `chats send`: an unknown
        // mention fails before dispatch.
        let resolved = self.client.resolve_mentions(text).await?;
        if !resolved.unresolved.is_empty() {
            return Err(Error::Invalid(
                "Unknown @mention. Nothing was sent; check the mention name.",
            ));
        }
        let (updates, receiver) = mpsc::channel(STREAM_CAPACITY);
        let mut relay = Relay {
            sink,
            receiver,
            request: turn.request(),
            chat_id: turn.chat_id().to_owned(),
            pending: None,
            malformed: None,
            finished: false,
        };
        let (client, window) = (&mut self.client, &mut self.window);
        let (sent, relayed) = futures_util::join!(
            dispatch.dispatch(
                client,
                chat_id,
                &resolved.processed_message,
                updates,
                cancel.clone()
            ),
            relay.run(turn, window, cancel),
        );
        let chat = sent?;
        relayed?;
        Ok(chat)
    }
}

/// Forwards the client's stream updates to the sink in order.
struct Relay<'k, K: ViewSink> {
    sink: &'k K,
    receiver: mpsc::Receiver<StreamUpdate>,
    request: RequestId,
    chat_id: String,
    /// A `Stream` event whose emit is in flight; re-delivered on drop.
    pending: Option<ViewEvent>,
    /// The first update that could not be shown (malformed consent item).
    malformed: Option<Error>,
    finished: bool,
}

impl<K: ViewSink> Relay<'_, K> {
    fn stream_event(&mut self, update: &StreamUpdate) -> Result<ViewEvent> {
        if let StreamUpdate::Started { chat_id, .. } = update {
            self.chat_id.clone_from(chat_id);
        }
        let event = stream_event_from_update(update).map_err(|_| Error::Protocol)?;
        Ok(ViewEvent::Stream {
            request: self.request,
            chat_id: self.chat_id.clone(),
            event,
        })
    }

    /// Relay until the client closes the channel. After a cancel no window
    /// is published and no reply text is applied, but `Stream` events and
    /// the delivery facts (`Started`, `Submitted`, `Admitted`) still count.
    /// A malformed update is skipped (and reported at the end) so later
    /// fences still go out. After a sink error the rest is drained without
    /// publishing, so the client never blocks on a full channel.
    async fn run(
        &mut self,
        turn: &mut SendTurn,
        window: &mut Option<OpenWindow>,
        cancel: &CancellationToken,
    ) -> Result<()> {
        let mut outcome = Ok(());
        while let Some(update) = self.receiver.recv().await {
            if outcome.is_err() {
                continue;
            }
            let apply = !cancel.is_cancelled();
            outcome = self.publish(&update, turn, window, apply).await;
        }
        self.finished = true;
        match self.malformed.take() {
            Some(error) => outcome.and(Err(error)),
            None => outcome,
        }
    }

    async fn publish(
        &mut self,
        update: &StreamUpdate,
        turn: &mut SendTurn,
        window: &mut Option<OpenWindow>,
        apply: bool,
    ) -> Result<()> {
        let event = match self.stream_event(update) {
            Ok(event) => event,
            Err(error) => {
                self.malformed.get_or_insert(error);
                return Ok(());
            }
        };
        self.pending = Some(event.clone());
        self.sink.emit(event).await?;
        self.pending = None;
        if !apply {
            // Cancelled: delivery facts still count for the end state.
            turn.apply_fence(update, window);
        } else if let Some(changed) = turn.apply(update, window) {
            self.sink.emit(changed).await?;
        }
        Ok(())
    }
}

impl<K: ViewSink> Drop for Relay<'_, K> {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        // The send was dropped mid-stream: hand every queued update to the
        // shell so its delivery fences survive the drop.
        self.receiver.close();
        let mut events: Vec<ViewEvent> = self.pending.take().into_iter().collect();
        while let Ok(update) = self.receiver.try_recv() {
            // A malformed consent update cannot be shown; the fences around
            // it still go out.
            if let Ok(event) = self.stream_event(&update) {
                events.push(event);
            }
        }
        if !events.is_empty() {
            self.sink.emit_detached(events);
        }
    }
}
