//! The view-model actor's draft read and remote draft change events: `draft`
//! reads one chat's saved draft for the composer (`Client::get_draft`, the
//! cached row offline), and `DraftSnapshot` plus `publish_draft_changes` turn
//! a draft that another device saved or cleared into `ViewEvent::DraftChanged`
//! once a live refresh applied it. Saves and clears are in `chat_actions.rs`.
//! Native only; plan `apple-client-core-migration` A5, spec `client-core`.
use super::{
    DraftView, ListCompleteness, ViewEvent,
    actor_host::{ViewHost, ViewSink},
};
use crate::{
    client::{Client, DraftFingerprint},
    error::{Error, Result},
    local_cache::ByteStore,
};
use futures_util::future::BoxFuture;
use std::collections::BTreeMap;
use tokio_util::sync::CancellationToken;

/// Read the saved draft of Personal chat `chat_id` for its composer; `None`
/// when it has none. Online this is the server's current draft (one
/// `GET /v1/drafts/{id}`, so a draft typed on another device is restored);
/// the read row is cached and persisted, and the chat list is emitted when
/// the draft differs from the cached one. Offline, and only when the host
/// admits the offline cache, the cached draft is returned instead.
///
/// # Errors
/// `Invalid` for a malformed or volatile id (before any network);
/// `Unavailable(team_draft_read_unavailable)` in a team scope;
/// `Authentication`; `Conflict` for a server draft older than the cached
/// one; `Offline` when offline and the host refuses the offline cache;
/// `Crypto`, `Protocol`; `Cancelled`; persistence and sink errors.
pub fn draft<'a, S: ByteStore + 'static, H: ViewHost<S>>(
    host: &'a mut H,
    chat_id: String,
    sink: &'a H::Sink,
    cancel: &'a CancellationToken,
) -> BoxFuture<'a, Result<Option<DraftView>>> {
    Box::pin(async move {
        uuid::Uuid::parse_str(&chat_id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        let before = DraftSnapshot::capture(host.core().client())?;
        host.core_mut().begin_client_operation(cancel);
        let offline_allowed = host.offline_cache_allowed();
        let client = host.core_mut().client_mut();
        let read = match client.get_draft(&chat_id, true).await {
            Err(Error::Offline) if offline_allowed => {
                return Ok(client.cached_draft(&chat_id).await?.map(DraftView::from));
            }
            read => read?,
        };
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let draft = read.map(DraftView::from);
        if before.changed(host.core().client())?.is_empty() {
            return Ok(draft);
        }
        host.core_mut().persist().await?;
        let event: ViewEvent = {
            let core = host.core();
            let items = core.client().cached_chat_items()?;
            core.chat_list_event(items, ListCompleteness::Partial)?
        };
        sink.emit(event).await?;
        Ok(draft)
    })
}

/// The cached drafts before a remote change is applied (ciphertext
/// fingerprints only, no plaintext).
pub(super) struct DraftSnapshot(BTreeMap<String, DraftFingerprint>);

impl DraftSnapshot {
    /// Fingerprint every cached Personal draft of `client` (none in a team
    /// scope).
    ///
    /// # Errors
    /// `Authentication` without credentials; `Protocol` for a malformed row.
    pub(super) fn capture(client: &Client) -> Result<Self> {
        client.draft_fingerprints().map(Self)
    }

    /// Chats whose cached draft differs now: saved, replaced or cleared
    /// (a row that lost its draft or disappeared), in chat id order.
    fn changed(&self, client: &Client) -> Result<Vec<String>> {
        let now = client.draft_fingerprints()?;
        let mut changed: Vec<String> = now
            .iter()
            .filter(|(id, fingerprint)| self.0.get(*id) != Some(*fingerprint))
            .map(|(id, _)| id.clone())
            .collect();
        changed.extend(self.0.keys().filter(|id| !now.contains_key(*id)).cloned());
        changed.sort();
        Ok(changed)
    }
}

/// Emit one `ViewEvent::DraftChanged` per chat whose cached draft differs
/// from `before`, after a live refresh or sync applied server rows: the
/// decrypted draft, or `None` when it was cleared or its chat is gone. A
/// server echo of this client's own save or clear carries the same version
/// and ciphertext the save already cached, so it compares equal and is not
/// reported. Follows the chat list and window events of the same refresh.
///
/// # Errors
/// `Crypto`, `Forbidden`, `Protocol` when a changed draft does not decrypt
/// in the owner's Personal scope (the refresh itself is already committed);
/// draft read admission errors; sink errors.
pub(super) async fn publish_draft_changes<K: ViewSink>(
    client: &Client,
    before: DraftSnapshot,
    sink: &K,
) -> Result<()> {
    for chat_id in before.changed(client)? {
        // Volatile chats have no saved draft a composer could restore.
        if client.is_ephemeral_chat(&chat_id) {
            continue;
        }
        let draft = client.cached_draft(&chat_id).await?.map(DraftView::from);
        sink.emit(ViewEvent::DraftChanged { chat_id, draft })
            .await?;
    }
    Ok(())
}
