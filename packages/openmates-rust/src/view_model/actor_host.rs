//! The two seams between the core view-model actor and a shell: the event
//! sink the shell listens on, and the host hooks for the parts a shell still
//! implements during the migration (profile origin, account checks, session
//! admission that starts the live monitor, completion recovery). Every
//! command, including send and cancel (lane L9), runs in the core.
//! Spec: `a2-design.md` (View model); native only.
use super::{ViewEvent, actor::ViewCore};
use crate::{client::FreshChatInventory, error::Result, local_cache::ByteStore, session::Session};
use futures_util::future::BoxFuture;

/// Where the actor delivers events. A bounded shell channel applies
/// back-pressure by awaiting inside `emit`.
pub trait ViewSink: Send + Sync {
    /// Deliver one event in order.
    ///
    /// # Errors
    /// `Cancelled` when the shell stopped listening; a shell may refuse an
    /// event kind it does not route with `Invalid`.
    fn emit(&self, event: ViewEvent) -> BoxFuture<'_, Result<()>>;

    /// Deliver `events`, in order, after the operation that produced them was
    /// dropped mid-way (a shell's cancel grace ran out during a send). They
    /// are the `Stream` updates the client had already queued, among them the
    /// `Submitted` fence that forbids an automatic resend, so a shell whose
    /// operations can be dropped must deliver them without blocking (for
    /// example from a spawned task). The default discards them: right for a
    /// shell that never drops a running send.
    fn emit_detached(&self, events: Vec<ViewEvent>) {
        drop(events);
    }
}

/// A borrowed sink delivers to the sink it borrows (the joined send's relay
/// borrows the caller's sink; a streaming turn owns a clone).
impl<K: ViewSink + ?Sized> ViewSink for &K {
    fn emit(&self, event: ViewEvent) -> BoxFuture<'_, Result<()>> {
        (**self).emit(event)
    }

    fn emit_detached(&self, events: Vec<ViewEvent>) {
        (**self).emit_detached(events);
    }
}

/// Which chat list read a recovery pass precedes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ListRecovery {
    /// The background sync after `Start`: global recovery that may return a
    /// complete inventory the list read then reuses.
    BootSync,
    /// An explicit `RefreshChats`: forced recovery, selected chat first.
    Refresh,
}

/// The shell side of the actor. It owns the [`ViewCore`] (so hooks can use
/// the client between core steps without a second owner) and implements the
/// steps that have not moved into the core yet.
///
/// Every hook runs on the actor task with exclusive access; the core never
/// holds a borrow of the core state across a hook call.
pub trait ViewHost<S: ByteStore + 'static>: Send {
    /// The shell's event sink type (it may carry shell request stamps).
    type Sink: ViewSink;

    /// The actor state.
    fn core(&self) -> &ViewCore<S>;

    /// The actor state, mutably.
    fn core_mut(&mut self) -> &mut ViewCore<S>;

    /// The API origin the client is reset to for `credentials`, after the
    /// shell applied its profile settings (explicit API/app origin).
    ///
    /// # Errors
    /// Invalid profile configuration.
    fn prepare_start(&mut self, credentials: &Session) -> Result<String>;

    /// Shell checks after the client holds the credentials and before any
    /// cached data is read or shown (the terminal's enforced trusted account).
    ///
    /// # Errors
    /// Refusal of the restored account.
    fn verify_start(&mut self) -> BoxFuture<'_, Result<()>>;

    /// Admit the restored session with the server: durable freshness fence,
    /// live monitor, cached-view staging and the admitted-session
    /// notification (bridged until the live window moves in L7).
    ///
    /// # Errors
    /// Authentication, access denial and persistence errors.
    fn admit<'a>(&'a mut self, sink: &'a Self::Sink) -> BoxFuture<'a, Result<()>>;

    /// Completion recovery before a chat list read (bridged until the
    /// recovery pump moves in L5). `BootSync` may return a complete inventory.
    ///
    /// # Errors
    /// Recovery and security errors.
    fn recover_before_list<'a>(
        &'a mut self,
        sink: &'a Self::Sink,
        recovery: ListRecovery,
    ) -> BoxFuture<'a, Result<Option<FreshChatInventory>>>;

    /// Whether no completion recovery is pending, so a refresh may use the
    /// sync-feed catch-up instead of recovery and the phased sync.
    fn recovery_idle(&mut self) -> BoxFuture<'_, bool>;

    /// Completion recovery of `chat_id` alone, after its cached window was
    /// emitted and before its strict read (bridged until the recovery pump
    /// moves in L5). A host without recovery returns `Ok(())`.
    ///
    /// # Errors
    /// Recovery and security errors; they fail the open.
    fn recover_before_open<'a>(
        &'a mut self,
        sink: &'a Self::Sink,
        chat_id: &'a str,
    ) -> BoxFuture<'a, Result<()>>;

    /// Whether a read-only cached window may be shown when the strict read
    /// is offline. A host returns `false` after a known authentication or
    /// access denial, so the open fails with `Forbidden` instead.
    fn offline_cache_allowed(&self) -> bool;
}
