//! The relay of one turn's stream updates to the shell: each update becomes a
//! `Stream` event, then the window change it caused (`send_turn.rs`). It runs
//! beside the client's send on the actor (`send_flows.rs`) or, for a turn
//! streaming beside the actor (`send_stream.rs`), locks the actor per update.
//! Moved from `send_flows.rs`; spec `a2-design.md` (View model).
//!
//! Ordering: every stream update is emitted before the window it changed;
//! updates the client queued before a dropped turn still reach
//! [`ViewSink::emit_detached`], so a `Submitted` fence is never lost.
use super::{
    RequestId, ViewEvent, actor_host::ViewSink, live_turns::LiveTurnGuard, send_stream::CoreLease,
    send_turn::SendTurn, stream_event_from_update, window::OpenWindow,
};
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
    model::StreamUpdate,
};
use std::sync::Arc;
use tokio::sync::mpsc;
use tokio_util::sync::CancellationToken;

/// Where the relay applies window changes.
pub(super) enum Windows<'w, S: ByteStore + 'static> {
    /// The actor's window, borrowed for the whole relay (the joined send).
    Owned(&'w mut Option<OpenWindow>),
    /// The actor's window behind its lease, locked per update.
    Leased(&'w CoreLease<S>),
}

/// Forwards the client's stream updates to the sink in order.
pub(super) struct Relay<K: ViewSink> {
    sink: K,
    receiver: mpsc::Receiver<StreamUpdate>,
    request: RequestId,
    chat_id: String,
    /// The turn's registry entry; renamed at `Started`.
    live: Arc<LiveTurnGuard>,
    /// A `Stream` event whose emit is in flight; re-delivered on drop.
    pending: Option<ViewEvent>,
    /// The first update that could not be shown (malformed consent item).
    malformed: Option<Error>,
    /// The first sink or lease error; later updates are drained unpublished.
    failed: Option<Error>,
    finished: bool,
}

impl<K: ViewSink> Relay<K> {
    /// The relay of `turn`'s updates arriving on `receiver`.
    pub(super) fn new(
        sink: K,
        receiver: mpsc::Receiver<StreamUpdate>,
        turn: &SendTurn,
        live: Arc<LiveTurnGuard>,
    ) -> Self {
        Self {
            sink,
            receiver,
            request: turn.request(),
            chat_id: turn.chat_id().to_owned(),
            live,
            pending: None,
            malformed: None,
            failed: None,
            finished: false,
        }
    }

    fn stream_event(&mut self, update: &StreamUpdate) -> Result<ViewEvent> {
        if let StreamUpdate::Started { chat_id, .. } = update {
            self.chat_id.clone_from(chat_id);
            self.live.set_chat(chat_id);
        }
        let event = stream_event_from_update(update).map_err(|_| Error::Protocol)?;
        if let StreamUpdate::Consent { request_id, items } = update {
            // Registered before the event is emitted, so an answer can never
            // race ahead of its request.
            let ids = items.iter().map(|item| item.id.clone()).collect();
            self.live.add_consent(&self.chat_id, request_id, ids);
        }
        Ok(ViewEvent::Stream {
            request: self.request,
            chat_id: self.chat_id.clone(),
            event,
        })
    }

    /// Relay until the client closes the channel, then report the first
    /// error. After a cancel no window is published and no reply text is
    /// applied, but `Stream` events and the delivery facts (`Started`,
    /// `Submitted`, `Admitted`) still count. A malformed update is skipped
    /// (and reported at the end) so later fences still go out.
    ///
    /// # Errors
    /// The first sink or lease error, else `Protocol` for a malformed update.
    pub(super) async fn run<S: ByteStore + 'static>(
        &mut self,
        turn: &mut SendTurn,
        mut windows: Windows<'_, S>,
        cancel: &CancellationToken,
    ) -> Result<()> {
        while let Some(update) = self.receiver.recv().await {
            self.relay(&update, turn, &mut windows, cancel).await;
        }
        self.finished = true;
        match (self.failed.take(), self.malformed.take()) {
            (Some(error), _) | (None, Some(error)) => Err(error),
            (None, None) => Ok(()),
        }
    }

    /// Relay until `admitted` fires, then the updates already queued; the
    /// channel stays open for the stream step's [`Self::run`].
    pub(super) async fn run_until<S: ByteStore + 'static>(
        &mut self,
        turn: &mut SendTurn,
        mut windows: Windows<'_, S>,
        cancel: &CancellationToken,
        admitted: &CancellationToken,
    ) {
        loop {
            tokio::select! {biased;
                update = self.receiver.recv() => match update {
                    Some(update) => self.relay(&update, turn, &mut windows, cancel).await,
                    None => return,
                },
                () = admitted.cancelled() => break,
            }
        }
        while let Ok(update) = self.receiver.try_recv() {
            self.relay(&update, turn, &mut windows, cancel).await;
        }
    }

    async fn relay<S: ByteStore + 'static>(
        &mut self,
        update: &StreamUpdate,
        turn: &mut SendTurn,
        windows: &mut Windows<'_, S>,
        cancel: &CancellationToken,
    ) {
        if self.failed.is_some() {
            return;
        }
        let apply = !cancel.is_cancelled();
        let published = match windows {
            Windows::Owned(window) => self.publish(update, turn, window, apply).await,
            Windows::Leased(lease) => match lease.core().await {
                Ok(mut core) => self.publish(update, turn, &mut core.window, apply).await,
                Err(error) => Err(error),
            },
        };
        if let Err(error) = published {
            self.failed = Some(error);
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
            turn.apply_fence(update, window);
        } else if let Some(changed) = turn.apply(update, window) {
            self.sink.emit(changed).await?;
        }
        Ok(())
    }
}

impl<K: ViewSink> Drop for Relay<K> {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        self.receiver.close();
        let mut events: Vec<ViewEvent> = self.pending.take().into_iter().collect();
        while let Ok(update) = self.receiver.try_recv() {
            if let Ok(event) = self.stream_event(&update) {
                events.push(event);
            }
        }
        if !events.is_empty() {
            self.sink.emit_detached(events);
        }
    }
}
