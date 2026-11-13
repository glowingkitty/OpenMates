//! Server draft versions read on the installed live monitor socket, for a
//! shell whose drafts are not in the core yet (the Apple drafts sync, until
//! A5/A6 of `docs/plans/apple-client-core-migration/`). The core owns
//! `get_draft_versions` and its uncorrelated `draft_versions_response`
//! (`view_model::socket_frames`), so the shell asks the core instead of
//! sending the frame through the passthrough. Same request, chunking (200
//! chats per frame) and parser as `Client::reconcile_draft_versions`, but it
//! returns the server's numbers and changes no core draft state.
use super::actor::{MonitorReadData, MonitorReadRequest};
use super::*;
use crate::client::owned_operation::OwnedOperationScope;

/// What the server reported for the requested chats.
pub(crate) struct MonitorDraftVersionsRead {
    /// Current server `draft_v` per chat the server answered for (0: no
    /// draft); chats it does not report are absent.
    pub(crate) versions: BTreeMap<String, u64>,
    /// Authoritative deletion version per chat, where the server has one.
    pub(crate) tombstones: BTreeMap<String, u64>,
}

impl Client {
    /// Ask the server for its draft versions of `requested` (`chat_id`,
    /// client `draft_v`) on `monitor`'s socket; no second connection.
    ///
    /// Cancelling `cancel` after the request was written retires that socket
    /// (its uncorrelated response could otherwise answer a later read); the
    /// shell's monitor then reconnects as after any socket loss.
    ///
    /// # Errors
    /// `Forbidden` in a team scope (drafts are personal) and above 10,000
    /// chats; `Protocol` for a malformed or duplicate chat id or a malformed
    /// response; `Conflict` when the server reports a version below the
    /// client's, or the monitor's read queue is full; `Offline` when the
    /// monitor has no read port or the socket fails; `Cancelled`.
    pub(crate) async fn monitor_draft_versions(
        &mut self,
        monitor: &ChatMonitor,
        requested: Vec<(String, u64)>,
        cancel: CancellationToken,
    ) -> Result<MonitorDraftVersionsRead> {
        let original = OwnedOperationScope::capture(self, cancel)?;
        let pending = self.prepare_monitor_read(
            monitor,
            &original,
            MonitorReadRequest::DraftVersions(requested),
        )?;
        let receipt = pending.wait().await?;
        let MonitorReadData::DraftVersions(data) = receipt.take(self, monitor, &original)? else {
            return Err(Error::Protocol);
        };
        let mut data = data.into_inner();
        Ok(MonitorDraftVersionsRead {
            versions: std::mem::take(&mut data.versions),
            tombstones: std::mem::take(&mut data.tombstones),
        })
    }
}

#[cfg(test)]
#[path = "monitor_draft_versions_tests.rs"]
mod tests;
