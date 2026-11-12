//! The view-model actor's `Send` and `Cancel` (lane L9): mention resolution,
//! the optimistic user message, the streamed reply relayed in order as
//! `Stream` events and applied to the open window (`send_turn.rs`),
//! persistence even after a cancel, and the completed, failed or cancelled
//! end state. This joined send keeps the actor for the whole turn; the split
//! turn that streams beside the actor is `send_stream.rs`. Moved from the
//! TUI `runtime.rs` (`send_message` and its relay task, now `send_relay.rs`);
//! spec `a2-design.md` (View model) and `architecture.sync` (send).
use super::{
    ChatWindowRecord, ChatWindowSource, ListCompleteness, PiiRestoration, RequestId, ViewErrorKind,
    ViewEvent,
    actor::ViewCore,
    actor_host::{ViewHost, ViewSink},
    chat_window_from_chat,
    live_turns::LiveTurns,
    send_relay::{Relay, Windows},
    send_request::{SendTurnOptions, TurnSummary},
    send_turn::SendTurn,
    window::OpenWindow,
};
use crate::{
    client::{Client, SendOptions, server_region::ServerRegionPreference},
    error::{Error, Result},
    local_cache::ByteStore,
    model::{Chat, StreamUpdate},
};
use futures_util::future::BoxFuture;
use std::sync::Arc;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

/// Capacity of the client-to-actor stream channel; a slow sink applies
/// back-pressure to the client's reader instead of buffering without bound.
pub(super) const STREAM_CAPACITY: usize = 64;

/// Cancels the running sends without borrowing the actor (a shell's priority
/// lane holds it while the actor is busy, and a streaming turn runs beside
/// the actor). Cheap to clone.
#[derive(Clone)]
pub struct SendCancelHandle {
    turns: Arc<LiveTurns>,
}

impl SendCancelHandle {
    pub(super) fn new(turns: Arc<LiveTurns>) -> Self {
        Self { turns }
    }

    /// Cancel every running send; returns whether one was running. Each send
    /// then persists what was admitted, publishes its cancelled end state and
    /// ends with `Cancelled`.
    pub fn cancel(&self) -> bool {
        self.turns.cancel_all()
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

    /// The user message id the shell reserved for this turn, shown on the
    /// optimistic message from the start (`None`: a provisional id until
    /// `Started`).
    fn reserved_user_id(&self) -> Option<&str> {
        None
    }

    /// The delivery facts of the finished dispatch (status, ids, queue
    /// position), taken once after a successful dispatch.
    fn take_summary(&mut self) -> Option<TurnSummary> {
        None
    }
}

/// `Client::send`, the encrypted turn over the chat socket, with the actor's
/// Memory-write opt-in and server region plus the shell's per-turn options
/// (`SendTurnOptions`; default: today's `Client::send_message` turn).
pub(super) struct ClientDispatch {
    memory_write_jobs: bool,
    server_region: ServerRegionPreference,
    turn: SendTurnOptions,
    summary: Option<TurnSummary>,
}

impl ClientDispatch {
    /// The dispatcher of one turn of `core` with `turn` options.
    pub(super) fn new<S: ByteStore + 'static>(core: &ViewCore<S>, turn: SendTurnOptions) -> Self {
        Self {
            memory_write_jobs: core.memory_write_jobs,
            server_region: core.server_region,
            turn,
            summary: None,
        }
    }

    /// The client options of the turn: the shell's per-turn options plus the
    /// actor's Memory-write opt-in and server region.
    pub(super) fn options(&self) -> SendOptions {
        SendOptions {
            memory_write_jobs: self.memory_write_jobs,
            server_region: self.server_region,
            ..self.turn.send_options()
        }
    }

    /// The user message id the shell reserved for this turn.
    pub(super) fn reserved(&self) -> Option<&str> {
        self.turn.reserved.message_id.as_deref()
    }

    /// Keep the delivery facts of a finished turn.
    pub(super) fn set_summary(&mut self, summary: TurnSummary) {
        self.summary = Some(summary);
    }
}

impl TurnDispatch for ClientDispatch {
    fn dispatch<'a>(
        &'a mut self,
        client: &'a mut Client,
        chat_id: Option<&'a str>,
        text: &'a str,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> BoxFuture<'a, Result<Chat>> {
        let options = self.options();
        Box::pin(async move {
            let outcome = client.send(chat_id, text, options, updates, cancel).await?;
            self.summary = Some(TurnSummary::from_outcome(&outcome));
            Ok(outcome.chat)
        })
    }

    fn reserved_user_id(&self) -> Option<&str> {
        self.reserved()
    }

    fn take_summary(&mut self) -> Option<TurnSummary> {
        self.summary.take()
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
        let mut dispatch = ClientDispatch::new(host.core(), SendTurnOptions::default());
        host.core_mut()
            .send_turn(request, chat_id, text, sink, cancel, &mut dispatch)
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

    /// Opt sends in to assistant Memory writes: the turn advertises
    /// `memory_write_jobs`, and the core claims, stores and announces (with
    /// the encrypted `context_entry` notice carrying Undo data) each Memory
    /// the assistant saves (`client::memory_write_jobs`). Off by default:
    /// only a shell that shows the notice and its Undo may switch it on.
    pub fn set_memory_write_jobs(&mut self, enabled: bool) {
        self.memory_write_jobs = enabled;
    }

    /// The server region preference of the following sends (the shell keeps
    /// the device-local setting; EU until it is set).
    pub fn set_server_region(&mut self, preference: ServerRegionPreference) {
        self.server_region = preference;
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
        let live = Arc::new(
            self.foreground
                .register(chat_id.as_deref(), turn_cancel.clone()),
        );
        let mut turn = SendTurn::new(request, chat_id.clone(), &text, self.open_chat_id());
        if let Some(id) = dispatch.reserved_user_id() {
            turn.reserve_user_id(id);
        }
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
                live.clone(),
            )
            .await;
        let record = self
            .finish_turn(request, &mut turn, sent, &turn_cancel, sink)
            .await;
        drop(live);
        record
    }

    /// The end of a turn on the actor: persist, then publish the cancelled,
    /// failed or sent state (`send_turn` and the stream step of
    /// `send_stream.rs`).
    ///
    /// # Errors
    /// `Cancelled` after a cancel; the send or persistence error; sink errors.
    pub(super) async fn finish_turn<K: ViewSink>(
        &mut self,
        request: RequestId,
        turn: &mut SendTurn,
        sent: Result<Chat>,
        turn_cancel: &CancellationToken,
        sink: &K,
    ) -> Result<ChatWindowRecord> {
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
        let mut record = chat_window_from_chat(
            &chat,
            ChatWindowSource::Canonical,
            None,
            false,
            false,
            PiiRestoration::PageLocal,
        )
        .map_err(|_| Error::Protocol)?;
        super::enrich::enrich_window(&self.client, &mut record)?;
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

    /// The turn text with resolved mentions, as `chats send` resolves them:
    /// an unknown mention fails before dispatch.
    ///
    /// # Errors
    /// `Invalid` for an unknown `@mention`; mention lookup errors.
    pub(super) async fn resolve_turn_text(&mut self, text: &str) -> Result<String> {
        let resolved = self.client.resolve_mentions(text).await?;
        if !resolved.unresolved.is_empty() {
            return Err(Error::Invalid(
                "Unknown @mention. Nothing was sent; check the mention name.",
            ));
        }
        Ok(resolved.processed_message)
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
        live: Arc<super::live_turns::LiveTurnGuard>,
    ) -> Result<Chat> {
        let text = self.resolve_turn_text(text).await?;
        let (updates, receiver) = mpsc::channel(STREAM_CAPACITY);
        let mut relay = Relay::new(sink, receiver, turn, live);
        let (client, window) = (&mut self.client, &mut self.window);
        let (sent, relayed) = futures_util::join!(
            dispatch.dispatch(client, chat_id, &text, updates, cancel.clone()),
            relay.run::<S>(turn, Windows::Owned(window), cancel),
        );
        let chat = sent?;
        relayed?;
        Ok(chat)
    }
}
