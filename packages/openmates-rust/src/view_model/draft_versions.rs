//! The view-model actor's draft versions call: the server's `draft_v` (and
//! deletion version) of chats a shell names, read on the live monitor
//! socket. For a shell whose drafts sync is not in the core yet (the Apple
//! drafts code until A5/A6 of `docs/plans/apple-client-core-migration/`):
//! the core owns `get_draft_versions` and its uncorrelated response
//! (`socket_frames.rs`), so such a shell cannot send it through the
//! passthrough. Request-response like `send`; no `ViewEvent`. Native only.
use super::{actor::ViewCore, actor_host::ViewHost};
use crate::{
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use tokio_util::sync::CancellationToken;

/// One chat of a draft versions request.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DraftVersionQuery {
    /// Chat id (canonical lowercase UUID).
    pub chat_id: String,
    /// The shell's stored `draft_v` of that chat (0: none). The server never
    /// answers a nonzero version below it (`Conflict` otherwise).
    pub client_draft_v: u64,
}

/// The server's draft state of one requested chat, as
/// `draft_versions_response` reports it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ServerDraftVersion {
    /// Chat id.
    pub chat_id: String,
    /// The server's current `draft_v`; 0 means it holds no draft (deleted on
    /// another device, when the shell's version is above 0).
    pub server_draft_v: u64,
    /// The server's authoritative deletion version, when it has one.
    pub tombstone_v: Option<u64>,
}

impl<S: ByteStore + 'static> ViewCore<S> {
    /// The server's draft versions of `chats` (`get_draft_versions`, 200 per
    /// frame) on the installed monitor's socket, sorted by chat id; chats the
    /// server does not report are absent. Opens no connection and changes no
    /// core state. An empty request answers at once without a frame.
    ///
    /// Cancelling `cancel` after a request frame was written retires the
    /// monitor socket (its uncorrelated response could answer a later read);
    /// the shell reconnects its monitor as after any socket loss.
    ///
    /// # Errors
    /// `Offline` without an installed monitor or when its socket fails;
    /// `Forbidden` in a team scope (drafts are personal) or above 10,000
    /// chats; `Protocol` for a malformed or repeated chat id or response;
    /// `Conflict` for a server version below the shell's or a full read
    /// queue; `Cancelled`; session errors when signed out.
    pub async fn draft_versions(
        &mut self,
        chats: Vec<DraftVersionQuery>,
        cancel: &CancellationToken,
    ) -> Result<Vec<ServerDraftVersion>> {
        // `&mut`: the future then needs the client to be `Send`, not `Sync`.
        let monitor = self.monitor.as_ref().ok_or(Error::Offline)?;
        let requested = chats
            .into_iter()
            .map(|chat| (chat.chat_id, chat.client_draft_v))
            .collect();
        let read = self
            .client
            .monitor_draft_versions(monitor, requested, cancel.clone())
            .await?;
        Ok(read
            .versions
            .into_iter()
            .map(|(chat_id, server_draft_v)| ServerDraftVersion {
                tombstone_v: read.tombstones.get(&chat_id).copied(),
                chat_id,
                server_draft_v,
            })
            .collect())
    }
}

/// [`ViewCore::draft_versions`] on the actor host, shaped like
/// [`super::send`] so a binding runs it on the actor.
///
/// # Errors
/// See [`ViewCore::draft_versions`].
pub fn draft_versions<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    chats: Vec<DraftVersionQuery>,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<Vec<ServerDraftVersion>>> {
    Box::pin(async move { host.core_mut().draft_versions(chats, cancel).await })
}
