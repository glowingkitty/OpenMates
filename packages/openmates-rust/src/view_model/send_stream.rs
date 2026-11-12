//! A send split in two so the actor is not busy for a whole streamed reply:
//! [`begin_send_with`] runs the short admission on the actor (optimistic
//! message, mentions, socket, `chat_turn_admit`) and returns a
//! [`TurnStream`]; its [`TurnStream::run`] streams on the shell's task and
//! locks the actor through a [`ViewLease`] only per client phase and per
//! relayed update. Other calls, a second send (the server queues it), stop
//! and cancel are served meanwhile. Native only; spec `client-core`, plan
//! `apple-client-core-migration`.
use super::{
    RequestId,
    actor::ViewCore,
    actor_host::{ViewHost, ViewSink},
    live_turns::{LiveTurnGuard, LiveTurns},
    send_flows::{ClientDispatch, STREAM_CAPACITY},
    send_relay::{Relay, Windows},
    send_request::{SendReceipt, SendTurnOptions, TurnSummary},
    send_turn::SendTurn,
};
use crate::{
    client::{AdmittedTurn, Client, ClientLease, LeasedClient},
    error::{Error, Result},
    local_cache::ByteStore,
    model::{Chat, StreamUpdate},
};
use futures_util::future::BoxFuture;
use std::ops::{Deref, DerefMut};
use std::sync::Arc;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

/// The shell's way back to its actor state from a turn's stream step: lock
/// the one [`ViewCore`] the actor serves commands on, exactly as a command
/// would, and release it when the guard drops.
pub trait ViewLease<S: ByteStore + 'static>: Send + Sync + 'static {
    /// Lock the actor state.
    ///
    /// # Errors
    /// `Authentication` when the actor is signed out.
    fn lease(&self) -> BoxFuture<'_, Result<LeasedCore<'_, S>>>;
}

/// The locked actor state of one stream phase.
pub type LeasedCore<'a, S> = Box<dyn DerefMut<Target = ViewCore<S>> + Send + 'a>;

/// The actor lease of one turn, bound to the actor that admitted it: after a
/// sign-out or a new session the lease refuses with `Cancelled`, so a stale
/// turn never touches the next session's state.
pub(super) struct CoreLease<S: ByteStore + 'static> {
    view: Arc<dyn ViewLease<S>>,
    turns: Arc<LiveTurns>,
}

impl<S: ByteStore + 'static> CoreLease<S> {
    /// Lock the admitting actor's state.
    ///
    /// # Errors
    /// As [`ViewLease::lease`]; `Cancelled` when another session's actor
    /// state is installed now.
    pub(super) async fn core(&self) -> Result<LeasedCore<'_, S>> {
        let core = self.view.lease().await?;
        if !Arc::ptr_eq(&core.foreground, &self.turns) {
            return Err(Error::Cancelled);
        }
        Ok(core)
    }
}

/// The client inside a locked actor state.
struct ClientOf<'a, S: ByteStore + 'static>(LeasedCore<'a, S>);

impl<S: ByteStore + 'static> Deref for ClientOf<'_, S> {
    type Target = Client;
    fn deref(&self) -> &Client {
        &self.0.client
    }
}

impl<S: ByteStore + 'static> DerefMut for ClientOf<'_, S> {
    fn deref_mut(&mut self) -> &mut Client {
        &mut self.0.client
    }
}

impl<S: ByteStore + 'static> ClientLease for CoreLease<S> {
    fn lease(&self) -> BoxFuture<'_, Result<LeasedClient<'_>>> {
        Box::pin(async move {
            let core = self.core().await?;
            Ok(Box::new(ClientOf(core)) as LeasedClient<'_>)
        })
    }
}

/// The client admission of one split turn. The production admitter is
/// `Client::admit_send`; tests script admission and stream.
pub(super) trait TurnAdmit: Send {
    /// Admit `text` into `chat_id` (`None`: a new chat), reporting progress
    /// on `updates`, and return the stream step.
    fn admit<'a>(
        &'a mut self,
        client: &'a mut Client,
        chat_id: Option<&'a str>,
        text: &'a str,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> BoxFuture<'a, Result<Box<dyn TurnStep>>>;

    /// The user message id the shell reserved for this turn.
    fn reserved_user_id(&self) -> Option<&str> {
        None
    }
}

/// The stream half of an admitted turn: it owns the turn's transport and
/// reaches the client only through `client`.
pub(super) trait TurnStep: Send {
    /// Stream the reply; return the sent chat and the delivery facts.
    fn stream(
        self: Box<Self>,
        client: Arc<dyn ClientLease>,
    ) -> BoxFuture<'static, Result<(Chat, TurnSummary)>>;
}

/// The saved turn's stream on its own socket.
struct Streaming(AdmittedTurn);

impl TurnStep for Streaming {
    fn stream(
        self: Box<Self>,
        client: Arc<dyn ClientLease>,
    ) -> BoxFuture<'static, Result<(Chat, TurnSummary)>> {
        Box::pin(async move {
            let outcome = self.0.stream(&*client).await?;
            let summary = TurnSummary::from_outcome(&outcome);
            Ok((outcome.chat, summary))
        })
    }
}

/// A turn that finished during admission: a volatile (incognito) turn runs
/// whole on the actor through `Client::send`, as before the split.
struct Finished(Chat, TurnSummary);

impl TurnStep for Finished {
    fn stream(
        self: Box<Self>,
        _client: Arc<dyn ClientLease>,
    ) -> BoxFuture<'static, Result<(Chat, TurnSummary)>> {
        Box::pin(async move { Ok((self.0, self.1)) })
    }
}

impl TurnAdmit for ClientDispatch {
    fn admit<'a>(
        &'a mut self,
        client: &'a mut Client,
        chat_id: Option<&'a str>,
        text: &'a str,
        updates: mpsc::Sender<StreamUpdate>,
        cancel: CancellationToken,
    ) -> BoxFuture<'a, Result<Box<dyn TurnStep>>> {
        let options = self.options();
        Box::pin(async move {
            if options.incognito {
                let outcome = client.send(chat_id, text, options, updates, cancel).await?;
                let summary = TurnSummary::from_outcome(&outcome);
                self.set_summary(summary.clone());
                return Ok(Box::new(Finished(outcome.chat, summary)) as Box<dyn TurnStep>);
            }
            let admitted = client
                .admit_send(chat_id, text, options, updates, cancel)
                .await?;
            Ok(Box::new(Streaming(admitted)) as Box<dyn TurnStep>)
        })
    }

    fn reserved_user_id(&self) -> Option<&str> {
        self.reserved()
    }
}

/// Which actor admitted a turn (to settle its result on that actor only).
#[derive(Clone)]
pub struct TurnOwner(Arc<LiveTurns>);

impl TurnOwner {
    /// Whether `core` is the actor state that admitted the turn.
    pub fn owns<S: ByteStore + 'static>(&self, core: &ViewCore<S>) -> bool {
        Arc::ptr_eq(&self.0, &core.foreground)
    }
}

/// An admitted turn whose reply has not streamed yet. Run it with
/// [`TurnStream::run`] after releasing the actor; dropping it unrun cancels
/// the turn (its queued fences reach `ViewSink::emit_detached`).
pub struct TurnStream<S: ByteStore + 'static, K: ViewSink + 'static> {
    step: Box<dyn TurnStep>,
    relay: Relay<K>,
    turn: SendTurn,
    live: Arc<LiveTurnGuard>,
    cancel: CancellationToken,
    lease: Arc<CoreLease<S>>,
    sink: K,
    request: RequestId,
}

/// [`super::send_with`] split for a streamed reply beside the actor. Runs
/// the admission on `host` and returns the stream step; same events, errors
/// and cancel as `send_with`. `lease` must lock the same actor state `host`
/// exposes; `sink` must deliver where `host`'s sink does.
///
/// While the turn streams, a second send into the same chat is admitted and
/// comes back `Queued` from the server; a send into another chat streams
/// concurrently; `SendCancelHandle`, `stop_reply` and logout end it.
///
/// # Errors
/// `Invalid` for refused options (before anything is shown) or an unknown
/// `@mention`; admission errors after the optimistic message (which then
/// shows `Failed`); `Cancelled` when cancelled.
#[allow(clippy::too_many_arguments)]
pub fn begin_send_with<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: Option<String>,
    text: String,
    options: SendTurnOptions,
    sink: H::Sink,
    cancel: &'a CancellationToken,
    lease: Arc<dyn ViewLease<S>>,
) -> BoxFuture<'a, Result<TurnStream<S, H::Sink>>>
where
    H::Sink: Clone + 'static,
{
    Box::pin(async move {
        options.check(chat_id.as_deref())?;
        let mut dispatch = ClientDispatch::new(host.core(), options);
        host.core_mut()
            .admit_turn(request, chat_id, text, sink, cancel, lease, &mut dispatch)
            .await
    })
}

impl<S: ByteStore + 'static, K: ViewSink + Clone + 'static> TurnStream<S, K> {
    /// The actor that admitted this turn.
    pub fn owner(&self) -> TurnOwner {
        TurnOwner(self.lease.turns.clone())
    }

    /// Stream the reply, then persist and publish the end state on the
    /// actor; returns the sent window and its receipt. Run it off the actor:
    /// it locks the actor itself, per phase.
    ///
    /// # Errors
    /// As `send_with`; `Authentication`/`Cancelled` when the actor signed
    /// out or changed session meanwhile.
    pub fn run(self) -> BoxFuture<'static, Result<SendReceipt>> {
        Box::pin(async move {
            let Self {
                step,
                mut relay,
                mut turn,
                live,
                cancel,
                lease,
                sink,
                request,
            } = self;
            let client: Arc<dyn ClientLease> = lease.clone();
            let (sent, relayed) = futures_util::join!(
                step.stream(client),
                relay.run(&mut turn, Windows::Leased(&lease), &cancel),
            );
            drop(relay);
            let (sent, summary) = match (sent, relayed) {
                (Ok((chat, summary)), Ok(())) => (Ok(chat), Some(summary)),
                (Err(error), _) | (Ok(_), Err(error)) => (Err(error), None),
            };
            let window = {
                let mut core = lease.core().await?;
                core.finish_turn(request, &mut turn, sent, &cancel, &sink)
                    .await?
            };
            drop(live);
            let summary = summary.ok_or(Error::Protocol)?;
            Ok(SendReceipt {
                window,
                status: summary.status,
                chat_id: summary.chat_id,
                user_message_id: summary.user_message_id,
                assistant_message_id: summary.assistant_message_id,
                queue_mode: summary.queue_mode,
                queue_revision: summary.queue_revision,
            })
        })
    }
}

impl<S: ByteStore + 'static> ViewCore<S> {
    /// [`begin_send_with`] with an explicit admitter (tests script it).
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn admit_turn<K: ViewSink + Clone + 'static, D: TurnAdmit>(
        &mut self,
        request: RequestId,
        chat_id: Option<String>,
        text: String,
        sink: K,
        cancel: &CancellationToken,
        lease: Arc<dyn ViewLease<S>>,
        dispatch: &mut D,
    ) -> Result<TurnStream<S, K>> {
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
        let (updates, receiver) = mpsc::channel(STREAM_CAPACITY);
        let mut relay = Relay::new(sink.clone(), receiver, &turn, live.clone());
        let admitted = match self.resolve_turn_text(&text).await {
            Ok(text) => {
                let admitted_signal = CancellationToken::new();
                let (client, window) = (&mut self.client, &mut self.window);
                let (admitted, ()) = futures_util::join!(
                    async {
                        let admitted = dispatch
                            .admit(
                                client,
                                chat_id.as_deref(),
                                &text,
                                updates,
                                turn_cancel.clone(),
                            )
                            .await;
                        admitted_signal.cancel();
                        admitted
                    },
                    relay.run_until::<S>(
                        &mut turn,
                        Windows::Owned(window),
                        &turn_cancel,
                        &admitted_signal
                    ),
                );
                admitted
            }
            Err(error) => Err(error),
        };
        match admitted {
            Ok(step) => Ok(TurnStream {
                step,
                relay,
                turn,
                live,
                cancel: turn_cancel,
                lease: Arc::new(CoreLease {
                    view: lease,
                    turns: self.foreground.clone(),
                }),
                sink,
                request,
            }),
            Err(error) => {
                // Admission dropped its sender: publish what it queued, then
                // the failed (or cancelled) end state.
                // The admission error takes precedence over a relay error,
                // as in the joined send.
                let _ = relay
                    .run::<S>(&mut turn, Windows::Owned(&mut self.window), &turn_cancel)
                    .await;
                let ended = self
                    .finish_turn(request, &mut turn, Err(error), &turn_cancel, &sink)
                    .await;
                drop(live);
                match ended {
                    Err(error) => Err(error),
                    // A failed admission never ends with a sent window.
                    Ok(_) => Err(Error::Protocol),
                }
            }
        }
    }
}

/// The receipt-less form of [`begin_send_with`] (`send`'s default options);
/// [`TurnStream::run`] still returns the receipt, whose `window` is what
/// `send` returns.
///
/// # Errors
/// As [`begin_send_with`].
pub fn begin_send<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    request: RequestId,
    chat_id: Option<String>,
    text: String,
    sink: H::Sink,
    cancel: &'a CancellationToken,
    lease: Arc<dyn ViewLease<S>>,
) -> BoxFuture<'a, Result<TurnStream<S, H::Sink>>>
where
    H::Sink: Clone + 'static,
{
    begin_send_with(
        host,
        request,
        chat_id,
        text,
        SendTurnOptions::default(),
        sink,
        cancel,
        lease,
    )
}
