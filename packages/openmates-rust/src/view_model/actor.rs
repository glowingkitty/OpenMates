//! The view-model actor state of the shared client core: the one `Client`
//! of a shell profile, its `ShellSession` (cache, persistence, logout), the
//! shell's credential backend, the live chat monitor and the open chat
//! window. Shells drive it with `ViewCommand`s through [`super::handle`] and
//! receive `ViewEvent`s through a [`super::ViewSink`].
//!
//! Lanes L6b, L7 and L9 of `docs/plans/apple-client-core-migration/a2-design.md`
//! (moved from the TUI `runtime.rs` actor). Native only. Spec: `client-core`
//! (one core, thin shells) and `client-core.cache`.
use crate::{
    client::{ChatMonitor, ChatRefreshDurableReceipt, Client},
    error::{Error, Result},
    local_cache::ByteStore,
    model::Item,
    shell_session::{CredentialPersistence, DurableCandidate, ShellSession},
};
use futures_util::future::BoxFuture;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

use super::{
    ChatWindowRecord, ListCompleteness, ViewEvent, arrange::arrange_chat_list,
    chat_list_row_from_item, send_flows::ForegroundSlot, window::OpenWindow,
};

/// The actor state a shell owns exactly once per profile. The `Client` is
/// reachable only through this value, so restore, persistence, receipts and
/// logout always use the same session runtime and credential backend.
pub struct ViewCore<S: ByteStore + 'static> {
    pub(super) client: Client,
    pub(super) session: ShellSession<S>,
    pub(super) credentials: Arc<dyn CredentialPersistence>,
    eager_cached_content: bool,
    /// The admitted live chat monitor; chat reads use it as their owner and
    /// denial witness. Started by the shell host during admission.
    pub(super) monitor: Option<ChatMonitor>,
    /// The one open chat window (`OpenChat` until `CloseChat`).
    pub(super) window: Option<OpenWindow>,
    /// Cancel token of the running send (`SendCancelHandle`).
    pub(super) foreground: ForegroundSlot,
}

impl<S: ByteStore + 'static> ViewCore<S> {
    /// Actor state over an unauthenticated or restored `client`. Cached chat
    /// content is loaded eagerly after `Start` (see
    /// [`Self::set_eager_cached_content`]).
    pub fn new(
        client: Client,
        session: ShellSession<S>,
        credentials: Arc<dyn CredentialPersistence>,
    ) -> Self {
        Self {
            client,
            session,
            credentials,
            eager_cached_content: true,
            monitor: None,
            window: None,
            foreground: ForegroundSlot::default(),
        }
    }

    /// The admitted live chat monitor, when one is running.
    pub fn chat_monitor(&self) -> Option<&ChatMonitor> {
        self.monitor.as_ref()
    }

    /// Install (or with `None` retire) the live chat monitor the shell host
    /// admitted; returns the previous one. Retiring it does not close the
    /// open window: chat reads then run without a monitor witness.
    pub fn set_chat_monitor(&mut self, monitor: Option<ChatMonitor>) -> Option<ChatMonitor> {
        std::mem::replace(&mut self.monitor, monitor)
    }

    /// Re-check the installed monitor's session and scope admission with the
    /// server (`Client::validate_chat_monitor`).
    ///
    /// # Errors
    /// `Cancelled` without a monitor, else as `Client::validate_chat_monitor`.
    pub fn validate_chat_monitor(&mut self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            let monitor = self.monitor.as_ref().ok_or(Error::Cancelled)?;
            self.client.validate_chat_monitor(monitor).await
        })
    }

    /// Id of the open chat window, if any. Recovery and live reads treat it
    /// as the selected chat.
    pub fn open_chat_id(&self) -> Option<&str> {
        self.window.as_ref().map(|window| window.chat_id.as_str())
    }

    /// The last window published for the open chat; `None` before its first
    /// page or when no chat is open.
    pub fn open_window(&self) -> Option<&ChatWindowRecord> {
        self.window
            .as_ref()
            .and_then(|window| window.record.as_ref())
    }

    /// Whether `Start` loads the remainder of the cache (every chat's content)
    /// from disk after the cached chat list was emitted and before admission.
    /// Shells that read cached chat views before any open (the terminal UI's
    /// instant cached open) keep it on; a shell that opens chats through the
    /// on-demand `ShellSession::load_cached_chat` path may switch it off.
    pub fn set_eager_cached_content(&mut self, eager: bool) {
        self.eager_cached_content = eager;
    }

    pub(super) fn eager_cached_content(&self) -> bool {
        self.eager_cached_content
    }

    /// The client.
    pub fn client(&self) -> &Client {
        &self.client
    }

    /// The client, for shell-implemented steps (host hooks, terminal-only
    /// commands). Every durable write must still go through
    /// [`Self::persist`] or [`Self::persist_for`].
    pub fn client_mut(&mut self) -> &mut Client {
        &mut self.client
    }

    /// The session runtime (cache façade and ordered queue).
    pub fn shell(&self) -> &ShellSession<S> {
        &self.session
    }

    /// The shell's credential backend.
    pub fn credentials(&self) -> &dyn CredentialPersistence {
        &*self.credentials
    }

    /// A handle that announces revocation without borrowing this actor; the
    /// shell's priority lane uses it while the actor is busy.
    pub fn revocation_handle(&self) -> RevocationHandle<S> {
        RevocationHandle {
            session: self.session.clone(),
            credentials: self.credentials.clone(),
        }
    }

    /// Persist credentials and the protected cache (`ShellSession::persist`).
    ///
    /// # Errors
    /// As `ShellSession::persist`.
    pub fn persist(&mut self) -> BoxFuture<'_, Result<()>> {
        self.session.persist(&mut self.client, &*self.credentials)
    }

    /// Persist and mint the durable receipt for `candidate`; the only receipt
    /// path of the actor (`ShellSession::persist_for`).
    ///
    /// # Errors
    /// As `ShellSession::persist_for`.
    pub fn persist_for<'a, C: DurableCandidate + Sync>(
        &'a mut self,
        candidate: &'a C,
    ) -> BoxFuture<'a, Result<ChatRefreshDurableReceipt>> {
        self.session
            .persist_for(&mut self.client, &*self.credentials, candidate)
    }

    /// Durable pre-dispatch fence before monitors, recovery or other uncertain
    /// effects (`ShellSession::revoke_list_freshness_before_dispatch`).
    ///
    /// # Errors
    /// As `ShellSession::revoke_list_freshness_before_dispatch`.
    pub fn revoke_list_freshness_before_dispatch<'a>(
        &'a mut self,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<()>> {
        self.session.revoke_list_freshness_before_dispatch(
            &mut self.client,
            &*self.credentials,
            cancel,
        )
    }

    /// Restore only the chat-list index of the shell-loaded `credentials`
    /// (`ShellSession::restore_loaded` with `CacheLoad::Index`). Performs no
    /// network IO. Returns whether a cached index existed.
    pub(super) fn restore_index<'a>(
        &'a mut self,
        credentials: &'a crate::session::Session,
        cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<bool>> {
        self.session.restore_loaded(
            &mut self.client,
            credentials,
            cancel,
            crate::shell_session::CacheLoad::Index,
        )
    }

    /// Local sign-out without remote logout: generation advanced, revocation
    /// durable, then credential cleanup (`ShellSession::clear_credentials`).
    ///
    /// # Errors
    /// As `ShellSession::clear_credentials`.
    pub fn clear_credentials(&self) -> BoxFuture<'_, Result<()>> {
        self.session.clear_credentials(&*self.credentials)
    }

    /// Local and remote sign-out (`ShellSession::logout`).
    ///
    /// # Errors
    /// The local error first, else the remote one.
    pub fn logout(&mut self) -> BoxFuture<'_, Result<()>> {
        self.session.logout(&mut self.client, &*self.credentials)
    }

    /// A `ChatList` event for chat inventory `items`, arranged in display
    /// order (`arrange_chat_list`) and converted to typed rows.
    ///
    /// # Errors
    /// `Protocol` when an item is not a well-formed chat row (a malformed core
    /// value is never shown with defaulted fields).
    pub fn chat_list_event(
        &self,
        items: Vec<Item>,
        completeness: ListCompleteness,
    ) -> Result<ViewEvent> {
        let rows = arrange_chat_list(&self.client, items)
            .iter()
            .map(chat_list_row_from_item)
            .collect::<std::result::Result<Vec<_>, _>>()
            .map_err(|_| Error::Protocol)?;
        Ok(ViewEvent::ChatList { rows, completeness })
    }
}

/// Revocation without the actor: advance the queue generation and make the
/// revocation durable (`ShellSession::revoke_credentials`). Cheap to clone.
pub struct RevocationHandle<S: ByteStore + 'static> {
    session: ShellSession<S>,
    credentials: Arc<dyn CredentialPersistence>,
}

impl<S: ByteStore + 'static> Clone for RevocationHandle<S> {
    fn clone(&self) -> Self {
        Self {
            session: self.session.clone(),
            credentials: self.credentials.clone(),
        }
    }
}

impl<S: ByteStore + 'static> RevocationHandle<S> {
    /// Announce revocation durably; the later logout repeats it harmlessly.
    ///
    /// # Errors
    /// Revocation errors from the credential backend.
    pub fn revoke(&self) -> BoxFuture<'_, Result<()>> {
        self.session.revoke_credentials(&*self.credentials)
    }
}
