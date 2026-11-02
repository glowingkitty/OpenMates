//! Inactive bounded browser metadata restore and cached projection.
//! Existing chats_db/chats IO + actual admitted master capability only. No
//! native Session/credential ACK, complete inventory, messages or recovery proof.
//! Rust/WASM execution UNRUN. Host/worker wiring and monitor commit remain required.
use super::*;

const MAX_RESTORE_CHATS: usize = 20;
fn selected_ids(ids: &[String]) -> Result<std::collections::BTreeSet<&str>> {
    if ids.is_empty() || ids.len() > MAX_RESTORE_CHATS { return Err(Error::Protocol); }
    let mut selected = std::collections::BTreeSet::new();
    for id in ids {
        if !uuid::Uuid::parse_str(id).is_ok_and(|v| v.to_string() == *id)
            || !selected.insert(id.as_str()) { return Err(Error::Protocol); }
    }
    Ok(selected)
}
fn restore_fence(client: &Client, principal: &str, id: &str) -> Result<Fence> {
    client.metadata_cache_scope(principal, id, BrowserMetadataCacheMode::Restore)?;
    client.verify_private_operation()?;
    let fence = Fence {
        parent: client.operation_parent.clone(),
        private_gate: client.options.private_operation_gate.clone(),
        scope: AsyncCryptoScope::begin(client)?,
        epoch: client.fresh_auth.operation_epoch(),
        binding: Zeroizing::new(client.fresh_auth_binding()?),
        source_stamp: source_stamp(client, id)?,
        revision: client.credential_revision,
    };
    client.metadata_cache_check(&fence, principal, id, BrowserMetadataCacheMode::Restore)?;
    Ok(fence)
}
fn cached_output(rows: &BTreeMap<String, Value>, mut items: Plain<Vec<Item>>, restored: bool)
    -> Result<Zeroizing<String>> {
    // Match existing chat_rows_by_recency: stable descending timestamp; initial
    // BTreeMap order provides the same ID tie order. No account-total inference.
    items.sort_by(|a, b| {
        let timestamp = |id: &str| rows[id]["last_edited_overall_timestamp"].as_f64().unwrap_or(0.0);
        timestamp(&b.id).partial_cmp(&timestamp(&a.id)).unwrap_or(std::cmp::Ordering::Equal)
    });
    let output = Plain::new(json!({"source":"browser_cached_metadata","cached":true,
        "fresh":false,"readOnly":true,"selected":true,"inventoryComplete":false,
        "historyComplete":false,"messagesPersisted":false,"metadataOnly":true,
        "metadataRestored":restored,"credentialAcknowledged":false,
        "nativeDurabilityAcknowledged":false,"recoveryProof":false,"items":&*items}));
    if crate::client::monitor::cached_view::bounded_bytes(&*output, 256 * 1024).is_none() {
        return Err(Error::Protocol);
    }
    let encoded = Zeroizing::new(serde_json::to_string(&*output)?);
    local_json::validate(&encoded)?;
    Ok(encoded)
}
impl Client {
    /// Read selected existing browser rows through the original owned IO adapter.
    /// Every captured row is decrypted and read back in the SAME database/store
    /// before publication. Different selected rows are NOT an atomic inventory.
    /// Nothing is inserted until all original owner/key/request/store fences pass.
    /// Existing conflicting memory rows are never overwritten or downgraded.
    /// This restores closed Personal metadata only, never a native snapshot,
    /// history/windows, stale freshness receipts, credentials, or durable ACKs.
    pub async fn browser_restore_cached_metadata_json<F, Fut>(
        &mut self, principal: &str, ids: &[String], host_scope: BrowserMetadataCacheScope,
        include_private_output: bool, mut io: F,
    ) -> Result<Zeroizing<String>>
    where F: FnMut(String) -> Fut, Fut: Future<Output = Result<String>> {
        if !include_private_output { return Err(Error::Invalid("Explicit private output consent is required.")); }
        selected_ids(ids)?;
        if host_scope.lifecycle_generation == 0 || host_scope.lifecycle_generation > MAX_SAFE
            || host_scope.workspace_epoch > MAX_SAFE { return Err(Error::Protocol); }
        let mut staged = Plain::new(BTreeMap::<String, Value>::new());
        let mut items = Plain::new(Vec::<Item>::new());
        let mut fences = Vec::new();
        // Capture ALL operation fences before the first await. Capturing a new
        // fence per later row would accidentally admit an epoch/key/denial ABA.
        for id in ids { fences.push((id.clone(), restore_fence(self, principal, id)?)); }
        for (id, fence) in &fences {
            for (other, captured) in &fences {
                self.metadata_cache_check(captured, principal, other, BrowserMetadataCacheMode::Restore)?;
            }
            let operation = uuid::Uuid::new_v4().to_string();
            let mut plan = Plain::new(json!({"version":1,"kind":"capture","operationId":operation,
                "scope":&host_scope,"owner":principal,"chatId":id,"database":"chats_db","store":"chats",
                "databaseVersion":null,"compareFields":PREDICATES,"expected":null,"patch":null}));
            let captured = self.metadata_cache_io(fence, principal, id, BrowserMetadataCacheMode::Restore, &plan, &mut io).await?;
            if !captured["before"].is_null() { return Err(Error::Protocol); }
            let old = projection(&captured["record"], id, principal, true)?;
            let row = normalized(&old, id, principal, false)?;
            if let Some(current) = self.chats.get(id) {
                if *normalized(current, id, principal, false)? != *row { return Err(Error::Conflict); }
            }
            let key = self.validate_metadata_cache_row(fence, principal, id, BrowserMetadataCacheMode::Restore, &row).await?;
            let item = Plain::new(self.chat_item(&row, &key)?);
            plan["kind"] = json!("readback");
            plan["databaseVersion"] = captured["databaseVersion"].clone();
            plan["expected"] = old.clone();
            let readback = self.metadata_cache_io(fence, principal, id, BrowserMetadataCacheMode::Restore, &plan, &mut io).await?;
            if !readback["before"].is_null() || readback["record"] != captured["record"] {
                return Err(Error::Conflict);
            }
            // Revalidate the closed physical projection after the owned readback.
            if *projection(&readback["record"], id, principal, true)? != *old { return Err(Error::Conflict); }
            staged.insert(id.clone(), row.into_inner());
            items.push(item.into_inner());
        }
        // Start in map order so ties match existing cached list presentation.
        items.sort_by(|a, b| a.id.cmp(&b.id));
        let output = cached_output(&staged, items, true)?;
        for (id, fence) in &fences {
            self.metadata_cache_check(fence, principal, id, BrowserMetadataCacheMode::Restore)?;
        }
        let prior_arrival_order = self.chat_arrival_order.clone();
        let mut missing = BTreeMap::new();
        for (id, row) in std::mem::take(&mut *staged) {
            if !self.chats.contains_key(&id) { missing.insert(id, row); }
            else { let _guard = Plain::new(row); }
        }
        let inserted:Vec<String> = missing.keys().cloned().collect();
        // Staged map order is not original IDB response arrival evidence.
        self.extend_chat_rows_without_arrival(missing);
        if !inserted.is_empty() {
            self.chat_list_freshness.invalidate();
            self.invalidate_chat_inventory_proofs();
        }
        // No await after commit. Original source stamps necessarily change for
        // newly inserted rows; all lifetime/revocation fences still must hold.
        let final_check = fences.iter().try_for_each(|(id, fence)|
            self.metadata_cache_lifetime(fence, principal, id, BrowserMetadataCacheMode::Restore));
        if let Err(error) = final_check {
            for id in inserted { if let Some(row) = self.remove_chat_row(&id) { let _guard = Plain::new(row); } }
            self.chat_arrival_order = prior_arrival_order;
            return Err(error);
        }
        Ok(output)
    }
    /// Tagged selected cached Items through real browser master capability.
    /// Includes explicit local-profile mode; no native raw master is requested.
    /// Unsupported Team/Direct/draft envelopes refuse under existing policy.
    pub async fn browser_cached_chat_items_json(&self, principal: &str, ids: &[String],
        include_private_output: bool) -> Result<Zeroizing<String>> {
        if !include_private_output { return Err(Error::Invalid("Explicit private output consent is required.")); }
        let selected = selected_ids(ids)?;
        let mut fences = Vec::new();
        for id in &selected { fences.push((*id, restore_fence(self, principal, id)?)); }
        let mut rows = Plain::new(BTreeMap::<String, Value>::new());
        let mut items = Plain::new(Vec::<Item>::new());
        for (id, fence) in &fences {
            let original = self.chats.get(*id).ok_or(Error::Unavailable {
                code:"browser_cached_metadata_missing", reason:"SELECTED_METADATA_NOT_RESTORED" })?;
            let row = normalized(original, id, principal, false)?;
            let key = self.validate_metadata_cache_row(fence, principal, id, BrowserMetadataCacheMode::Restore, &row).await?;
            items.push(self.chat_item(&row, &key)?);
            rows.insert((*id).into(), row.into_inner());
        }
        let output = cached_output(&rows, items, false)?;
        for (id, fence) in &fences {
            self.metadata_cache_check(fence, principal, id, BrowserMetadataCacheMode::Restore)?;
        }
        Ok(output)
    }
}
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "browser_cache_restore_tests.rs"]
mod tests;
