//! Draft versions on `ViewModelCore`: the server's draft state of a set of
//! chats (`openmates_sdk::view_model::draft_versions`), read on the core's
//! one monitor socket so Swift can reconcile its stored drafts. Bindings only
//! marshal. Plan `apple-client-core-migration`; spec `client-core`.
use crate::CoreError;
use crate::core::CoreCancellation;
use crate::view_core::ViewModelCore;
use openmates_sdk::view_model::{self, DraftVersionQuery, ServerDraftVersion};
use std::sync::Arc;

/// One chat of a draft versions request.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct DraftVersionQueryRecord {
    /// Chat id (canonical lowercase UUID).
    pub chat_id: String,
    /// Swift's stored `draft_v` of that chat (0: none).
    pub client_draft_v: u64,
}

/// The server's draft state of one requested chat.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ServerDraftVersionRecord {
    /// Chat id.
    pub chat_id: String,
    /// The server's current `draft_v`; 0 means it holds no draft.
    pub server_draft_v: u64,
    /// The server's authoritative deletion version, when it has one.
    pub tombstone_v: Option<u64>,
}

impl From<DraftVersionQueryRecord> for DraftVersionQuery {
    fn from(record: DraftVersionQueryRecord) -> Self {
        Self {
            chat_id: record.chat_id,
            client_draft_v: record.client_draft_v,
        }
    }
}

impl From<ServerDraftVersion> for ServerDraftVersionRecord {
    fn from(version: ServerDraftVersion) -> Self {
        Self {
            chat_id: version.chat_id,
            server_draft_v: version.server_draft_v,
            tombstone_v: version.tombstone_v,
        }
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// The server's draft versions of `chats`, sorted by chat id; chats the
    /// server does not report are absent. Uses the live monitor socket and
    /// changes no core state. Runs on the actor, so other commands wait for
    /// it. Cancelling after the request was written retires the monitor
    /// socket; the core reconnects it like after any socket loss.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Offline` without a live monitor;
    /// `Forbidden` in a team scope or above 10,000 chats; `Protocol` for a
    /// malformed chat id or response; `Conflict` for a server version below
    /// Swift's; `Cancelled`.
    pub async fn draft_versions(
        &self,
        chats: Vec<DraftVersionQueryRecord>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> Result<Vec<ServerDraftVersionRecord>, CoreError> {
        let (shared, token) = (self.shared.clone(), self.detached(cancellation));
        self.run(async move {
            let chats = chats.into_iter().map(DraftVersionQuery::from).collect();
            let versions = shared
                .signed_in(token, move |host, _sink, cancel| {
                    view_model::draft_versions(host, chats, cancel)
                })
                .await?;
            Ok(versions
                .into_iter()
                .map(ServerDraftVersionRecord::from)
                .collect())
        })
        .await
    }
}
