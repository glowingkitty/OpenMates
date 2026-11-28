//! Streamed sends beside the terminal actor (runtime adapter, no core logic).
//!
//! The actor owns the one `ViewCore` behind a tokio mutex ([`CoreCell`]): it
//! holds the lock while it serves a request and releases it before it waits for
//! the next one, so a turn's stream task (`TurnStream::run`) can lock the core
//! per phase while the actor keeps accepting commands. That is what lets a
//! second send into the same chat reach the server while a reply streams,
//! with its own receipt. Spec: `specifications/features/chat-queued-followups`.
use super::Stamp;
use futures_util::future::BoxFuture;
use openmates::{
    error::Result,
    storage::CacheBytes,
};
use openmates_sdk::view_model::{LeasedCore, RequestId, SendReceipt, TurnStream, ViewCore, ViewLease};
use std::{
    ops::{Deref, DerefMut},
    sync::Arc,
};
use tokio::sync::{Mutex, OwnedMutexGuard, mpsc};

use super::core_host::TerminalSink;

/// The terminal's view core plus the lock state of the actor that owns it.
///
/// While `held` is `Some` the actor has exclusive use of the core and derefs to
/// it like a plain field; between requests the actor calls [`Self::release`] so
/// stream tasks can lock it, and [`Self::acquire`] when the next request starts.
pub(super) struct CoreCell {
    shared: Arc<Mutex<ViewCore<CacheBytes>>>,
    held: Option<OwnedMutexGuard<ViewCore<CacheBytes>>>,
}

impl CoreCell {
    /// A cell that starts held by the actor (nothing can contend yet).
    pub(super) fn new(core: ViewCore<CacheBytes>) -> Self {
        let shared = Arc::new(Mutex::new(core));
        let held = shared.clone().try_lock_owned().ok();
        debug_assert!(held.is_some(), "a fresh mutex is unlocked");
        Self { shared, held }
    }

    /// Let stream tasks lock the core; call before waiting for work.
    pub(super) fn release(&mut self) {
        self.held = None;
    }

    /// Take the core back for one request (waits for a stream phase to end).
    pub(super) async fn acquire(&mut self) {
        if self.held.is_none() {
            self.held = Some(self.shared.clone().lock_owned().await);
        }
    }

    /// Whether the chat monitor is open and valid, without waiting: `false`
    /// while a stream phase holds the lock (the next tick asks again).
    pub(super) fn monitor_valid(&self) -> bool {
        let check = |core: &ViewCore<CacheBytes>| core.chat_monitor().is_some_and(|m| m.is_valid());
        match &self.held {
            Some(core) => check(core),
            None => self.shared.try_lock().is_ok_and(|core| check(&core)),
        }
    }

    /// The lease a turn's stream task uses to lock this core.
    pub(super) fn lease(&self) -> Arc<dyn ViewLease<CacheBytes>> {
        Arc::new(TuiLease(self.shared.clone()))
    }
}

impl Deref for CoreCell {
    type Target = ViewCore<CacheBytes>;
    fn deref(&self) -> &Self::Target {
        self.held.as_deref().expect("the actor holds its core while it serves a request")
    }
}

impl DerefMut for CoreCell {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.held.as_deref_mut().expect("the actor holds its core while it serves a request")
    }
}

/// Locks the actor's core for one stream phase, as a command would.
struct TuiLease(Arc<Mutex<ViewCore<CacheBytes>>>);

impl ViewLease<CacheBytes> for TuiLease {
    fn lease(&self) -> BoxFuture<'_, Result<LeasedCore<'_, CacheBytes>>> {
        Box::pin(async move { Ok(Box::new(self.0.lock().await) as LeasedCore<'_, CacheBytes>) })
    }
}

/// The end of a streamed send, sent back to the actor loop which settles it
/// exactly like the end of any other request (`Work::SendFinished`).
pub(super) type SendOutcome = (Stamp, RequestId, Result<SendReceipt>);

/// Stream an admitted turn on its own task; its outcome returns to the actor
/// through `finished`. A closed channel means the actor is gone: drop quietly.
pub(super) fn spawn(
    stream: TurnStream<CacheBytes, TerminalSink>,
    finished: mpsc::UnboundedSender<SendOutcome>,
    epoch: Stamp,
    request: RequestId,
) {
    tokio::spawn(async move {
        let result = stream.run().await;
        let _ = finished.send((epoch, request, result));
    });
}
