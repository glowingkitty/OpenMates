//! Consuming, local full-history transaction. Never persisted or a permission.
use super::*;
use std::sync::{Arc, atomic::Ordering};

// Only the shared canonical full-history loader can construct and advance this.
// Existing FreshChatInventory list guards remain; exact session/operation binding
// additionally protects the original discovery-to-read boundary.
pub(in crate::client) struct ReadFreshnessTransaction {
    proof: FreshChatInventory,
    selected_id: String,
    parent: CancellationToken,
    binding: [u8; 32],
    operation_epoch: u64,
    expected_network: u64,
    outside_selected_digest: String,
    eligible: bool,
    pub(in crate::client) terminal: bool,
    /// A bounded selected read that left every list input byte-identical (the
    /// server row matched the cached canonical row). Like a terminal read it
    /// may rebind the inventory's original receipt; history is not a list input.
    pub(in crate::client) list_neutral: bool,
}
impl Drop for ReadFreshnessTransaction {
    fn drop(&mut self) {
        use zeroize::Zeroize;
        self.binding.zeroize();
    }
}
impl ReadFreshnessTransaction {
    pub(in crate::client) fn begin(
        client: &Client,
        id: &str,
        proof: FreshChatInventory,
        cancel: &CancellationToken,
    ) -> Result<Option<Self>> {
        if !client.chat_inventory_is_current(&proof)?
            || proof.caller != *cancel
            || proof.operation != client.operation_cancel
            || !Self::selected_is_supported(client, id)
        {
            return Ok(None);
        }
        Ok(Some(Self {
            expected_network: proof.network_revision,
            proof,
            selected_id: id.to_owned(),
            parent: client.operation_parent.clone(),
            binding: client.fresh_auth_binding()?,
            operation_epoch: client.fresh_auth.operation_epoch(),
            outside_selected_digest: Self::outside_selected_digest(client, id)?,
            eligible: true,
            terminal: false,
            list_neutral: false,
        }))
    }
    fn selected_is_supported(client: &Client, id: &str) -> bool {
        client.supports_cached_default_chat_list()
            && client
                .chats
                .get(id)
                .is_some_and(|row| !draft_only(row) && text(row, "chat_visibility") != "direct")
    }
    fn outside_selected_digest(client: &Client, id: &str) -> Result<String> {
        let chats: BTreeMap<_, _> = client
            .chats
            .iter()
            .filter(|(key, _)| key.as_str() != id)
            .collect();
        let history: BTreeMap<_, _> = client
            .history
            .iter()
            .filter(|(key, _)| key.as_str() != id)
            .collect();
        let windows: BTreeMap<_, _> = client.snapshot_sync_windows().into_iter()
            .filter(|(key,_)|key.as_str()!=id).collect();
        let selected_pages: BTreeMap<_, _> = client.snapshot_selected_first_pages().into_iter()
            .filter(|(key,_)|key.as_str()!=id).collect();
        if !selected_pages.is_empty() {
            return Ok(sha256(&serde_json::to_string(&(
                chats, history, &client.wrappers, &client.embeds, &client.embed_keys,
                &client.team_wrapped_key, windows, selected_pages,
            ))?));
        }
        if !windows.is_empty() {
            return Ok(sha256(&serde_json::to_string(&(
                chats, history, &client.wrappers, &client.embeds,
                &client.embed_keys, &client.team_wrapped_key, windows,
            ))?));
        }
        Ok(sha256(&serde_json::to_string(&(
            chats,
            history,
            &client.wrappers,
            &client.embeds,
            &client.embed_keys,
            &client.team_wrapped_key,
        ))?))
    }
    fn current(&self, client: &Client, id: &str) -> Result<bool> {
        client.require_session()?;
        let proof = &self.proof;
        Ok(self.eligible
            && self.selected_id == id
            && !proof.issuer.cancel.is_cancelled()
            && !proof.caller.is_cancelled()
            && !proof.operation.is_cancelled()
            && !self.parent.is_cancelled()
            && !client.operation_cancel.is_cancelled()
            && client.operation_cancel == proof.operation
            && client.operation_parent == self.parent
            && Arc::ptr_eq(&proof.issuer, &client.task_watch_authority)
            && Arc::ptr_eq(&proof.network, &client.inventory_network)
            && proof.network.load(Ordering::SeqCst) == self.expected_network
            && client.generation == proof.generation
            && client.credential_revision == proof.credential_revision
            && client.fresh_auth.operation_epoch() == self.operation_epoch
            && client.fresh_auth_binding()? == self.binding
            && Self::selected_is_supported(client, id)
            && Self::outside_selected_digest(client, id)? == self.outside_selected_digest)
    }
    pub(in crate::client) fn before_request(&mut self, client: &Client, id: &str) {
        self.eligible = self.current(client, id).unwrap_or(false);
        match self.expected_network.checked_add(1) {
            Some(next) => self.expected_network = next,
            None => self.eligible = false,
        }
    }
    pub(in crate::client) fn after_request(&mut self, client: &Client, id: &str) {
        self.eligible = self.current(client, id).unwrap_or(false);
    }
    pub(in crate::client) fn commit(self, client: &mut Client, id: &str) -> Result<()> {
        if (self.terminal || self.list_neutral) && self.current(client, id)? {
            // Final hash covers every ciphertext field including selected full
            // history. Never sample a later clock or reuse the pre-read digest.
            client.record_complete_chat_list_at(self.proof.canonical_completed_clock.as_ref());
        }
        Ok(())
    }
}
#[cfg(test)]
#[path = "sync_read_freshness_tests.rs"]
mod tests;
