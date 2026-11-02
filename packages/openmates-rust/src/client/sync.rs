use super::plaintext::{Plain, replace_text};
use super::transport::{receive, send};
use super::*;

#[path="sync_read_phase.rs"]
mod read_phase;
pub(in crate::client) use read_phase::{ReadOnlySyncPhase,SyncPhaseReadData};

#[path="sync/canonical_history.rs"]
mod canonical_history;
#[path="sync/canonical_owned.rs"]
pub(in crate::client) mod canonical_owned;

#[derive(Clone, Copy, PartialEq, Eq)]
enum ChatSyncPolicy {
    Ordinary,
    InventoryDiscovery,
    MonitorReadOnly,
}
impl ChatSyncPolicy {
    fn allows_effects(self) -> bool {
        self != Self::MonitorReadOnly
    }
    fn requested_phase(self, headless: bool, personal: bool, has_content_cache: bool) -> &'static str {
        // Discovery consumes metadata, not startup transcript/sidecar content.
        // Preserve the old refresh path if optional content already exists;
        // phase2 has no authority to refresh or merge those cached sidecars.
        if self == Self::InventoryDiscovery && headless && personal && !has_content_cache {
            "phase2"
        } else {
            "all"
        }
    }
}
// No plaintext key and no Debug; ambiguity is observed only by saved-send.
pub(super) struct SelectedChatKeyCiphertext<'a> {
    pub(super) ciphertext: &'a str,
    pub(super) ambiguous: bool,
}
/// Opaque proof of one fully reconciled, authenticated personal Chat inventory.
/// Issued by discovery, consumed only by the same Client. No Clone, Debug or
/// serde: neither restored ciphertext nor host-created data grants authority.
/// This is a one-use read result for the same saved-read batch, not a permission
/// lease or a freshness guarantee across commands. It carries no plaintext and
/// never substitutes for durable output admission.
pub struct FreshChatInventory {
    issuer: std::sync::Arc<super::project_task_watch::WatchAuthority>,
    network: std::sync::Arc<std::sync::atomic::AtomicU64>,
    network_revision: u64,
    caller: CancellationToken,
    operation: CancellationToken,
    api_url: String,
    client_identity: ClientIdentity,
    app_url: String,
    owner_id: String,
    generation: u64,
    credential_revision: u64,
    credential_binding: [u8; 32],
    operation_epoch: u64,
    ciphertext_digest: String,
    canonical_completed_clock: Option<CacheClockEvidence>,
}
impl FreshChatInventory {
    /// Consume same-batch evidence without rendering, caching or minting any
    /// authority. Native adapters use this only to cover an immediately adjacent
    /// empty-recovery check. The caller still owns local journal/generation and
    /// durability admission. Keyless monitor traffic can invalidate this value
    /// even while the originating Client remains exclusively borrowed.
    pub fn consume_if_current(self, client: &Client, cancel: &CancellationToken) -> Result<bool> {
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // A replaced operation means the proof is stale, but must not hide a
        // known missing/expired current session (forget_session replaces this
        // token too). Keep caller cancellation first and recheck the full exact
        // inventory binding below before returning any usable proof.
        client.require_session()?;
        if self.caller != *cancel || self.operation != client.operation_cancel {
            return Ok(false);
        }
        let current = client.chat_inventory_is_current(&self)?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok(current)
    }
}
impl Drop for FreshChatInventory {
    fn drop(&mut self) {
        use zeroize::Zeroize;
        self.credential_binding.zeroize();
    }
}
impl Client {
    pub(super) fn invalidate_chat_inventory_proofs(&self) {
        self.inventory_network
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    }
    fn chat_inventory_digest(&self) -> Result<String> {
        let digest = self.chat_inventory_data_digest()?;
        match self.current_chat_arrival_order() {
            Some(order) => Ok(sha256(&serde_json::to_string(&(digest,1u32,order))?)),
            None => Ok(digest),
        }
    }
    fn chat_inventory_data_digest(&self) -> Result<String> {
        // Hash the exact ciphertext, including wrappers and embed state; never
        // hash a lossy display list or compare only versions/Chat identifiers.
        let selected = self.snapshot_selected_first_pages();
        let windows = self.snapshot_sync_windows();
        if !selected.is_empty() {
            return Ok(sha256(&serde_json::to_string(&(
                &self.chats, &self.wrappers, &self.history, &self.embeds,
                &self.embed_keys, &self.team_wrapped_key, &windows, &selected,
            ))?));
        }
        if !windows.is_empty() {
            return Ok(sha256(&serde_json::to_string(&(
                &self.chats, &self.wrappers, &self.history, &self.embeds,
                &self.embed_keys, &self.team_wrapped_key, &windows,
            ))?));
        }
        Ok(sha256(&serde_json::to_string(&(
            &self.chats,
            &self.wrappers,
            &self.history,
            &self.embeds,
            &self.embed_keys,
            &self.team_wrapped_key,
        ))?))
    }
    fn chat_inventory_owner(&self) -> Result<&str> {
        self.user["id"]
            .as_str()
            .filter(|id| !id.is_empty())
            .or_else(|| self.user["user_id"].as_str().filter(|id| !id.is_empty()))
            .ok_or(Error::Authentication)
    }
    pub(super) fn fresh_chat_inventory(
        &self,
        cancel: &CancellationToken,
    ) -> Result<Option<FreshChatInventory>> {
        self.require_session()?;
        if cancel.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // Team/direct key lifecycle support is intentionally outside this first
        // optimization. Those callers retain the existing fresh-sync behavior.
        if self.team()?.is_some()
            || self
                .chats
                .values()
                .any(|row| text(row, "chat_visibility") == "direct")
        {
            return Ok(None);
        }
        Ok(Some(FreshChatInventory {
            issuer: self.task_watch_authority.clone(),
            network: self.inventory_network.clone(),
            network_revision: self
                .inventory_network
                .load(std::sync::atomic::Ordering::SeqCst),
            caller: cancel.clone(),
            operation: self.operation_cancel.clone(),
            api_url: self.base.as_str().to_owned(),
            client_identity: self.options.identity,
            app_url: self.app_url(),
            owner_id: self.chat_inventory_owner()?.to_owned(),
            generation: self.generation,
            credential_revision: self.credential_revision,
            credential_binding: self.fresh_auth_binding()?,
            operation_epoch: self.fresh_auth.operation_epoch(),
            ciphertext_digest: self.chat_inventory_digest()?,
            canonical_completed_clock: self.cache_clock_evidence(),
        }))
    }
    pub(super) fn record_complete_chat_list(&mut self, proof: &FreshChatInventory) {
        if matches!(self.chat_inventory_is_current(proof), Ok(true)) {
            self.record_complete_chat_list_at(proof.canonical_completed_clock.as_ref());
        }
    }
    pub(super) fn chat_inventory_is_current(&self, proof: &FreshChatInventory) -> Result<bool> {
        self.require_session()?;
        if self.operation_cancel.is_cancelled() || proof.caller.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok(!proof.issuer.cancel.is_cancelled()
            && std::sync::Arc::ptr_eq(&proof.network, &self.inventory_network)
            && !proof.operation.is_cancelled()
            && std::sync::Arc::ptr_eq(&proof.issuer, &self.task_watch_authority)
            && self.team()?.is_none()
            && self.base.as_str() == proof.api_url
            && self.options.identity == proof.client_identity
            && self.app_url() == proof.app_url
            && self.chat_inventory_owner()? == proof.owner_id
            && self.generation == proof.generation
            && self.credential_revision == proof.credential_revision
            && self.fresh_auth_binding()? == proof.credential_binding
            && self.fresh_auth.operation_epoch() == proof.operation_epoch
            && self.chat_inventory_digest()? == proof.ciphertext_digest
            && proof.network.load(std::sync::atomic::Ordering::SeqCst) == proof.network_revision)
    }
    pub(super) async fn wrapping_key(&mut self) -> Result<Key> {
        let s = self.require_session()?;
        let Some(team) = s.active_team_id.clone() else {
            return Ok(s.master_key.clone());
        };
        if let Some((id, key)) = &self.team_key
            && *id == team
        {
            return Ok(key.clone());
        }
        let master = s.master_key.clone();
        let result = self
            .request(Method::GET, &format!("/v1/teams/{}", segment(&team)), None)
            .await?;
        let row = result.get("team").ok_or(Error::Protocol)?;
        if text(row, "team_id") != team {
            return Err(Error::Forbidden);
        }
        let key = key_from_bytes(&crypto::decrypt_bytes(
            required(row, "encrypted_team_key")?,
            &master,
        )?)?;
        self.team_wrapped_key = Some((
            team.clone(),
            required(row, "encrypted_team_key")?.to_owned(),
        ));
        self.team_key = Some((team, key.clone()));
        Ok(key)
    }
    pub(super) fn chat_key(&self, details: &Value, wrapping: &[u8; 32]) -> Result<Key> {
        // Preserve structural/session validation order for the Direct branch.
        let _ = required(details, "id")?;
        let _ = self.team()?;
        if text(details, "chat_visibility") == "direct" {
            return self.direct_chat_key(details);
        }
        let selected = self.chat_key_ciphertext(details, false)?;
        key_from_bytes(&crypto::decrypt_bytes(selected.ciphertext, wrapping)?)
    }
    pub(super) fn chat_key_ciphertext<'a>(
        &'a self,
        details: &'a Value,
        require_unambiguous: bool,
    ) -> Result<SelectedChatKeyCiphertext<'a>> {
        self.chat_key_ciphertext_from(details, require_unambiguous, &self.wrappers)
    }
    pub(super) fn chat_key_ciphertext_from<'a>(
        &'a self, details: &'a Value, require_unambiguous: bool, source_wrappers: &'a [Value],
    ) -> Result<SelectedChatKeyCiphertext<'a>> {
        let id = required(details, "id")?;
        let team = self.team()?;
        if text(details, "chat_visibility") == "direct" {
            return Err(Error::Forbidden);
        }
        if let Some(team) = team {
            if details
                .get("team_id")
                .and_then(Value::as_str)
                .is_some_and(|v| v != team)
                || details
                    .get("hashed_team_id")
                    .and_then(Value::as_str)
                    .is_some_and(|v| v != sha256(team))
            {
                return Err(Error::Forbidden);
            }
        } else if details
            .get("team_id")
            .and_then(Value::as_str)
            .is_some_and(|v| !v.is_empty())
            || details
                .get("hashed_team_id")
                .and_then(Value::as_str)
                .is_some_and(|v| !v.is_empty())
        {
            return Err(Error::Forbidden);
        }
        let chat_hash = sha256(id);
        let team_hash = team.map(sha256);
        let mut wrappers = source_wrappers
            .iter()
            .chain(
                details
                    .get("chat_key_wrappers")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten(),
            )
            .filter(|w| {
                text(w, "hashed_chat_id") == chat_hash
                    && text(w, "key_type") == if team.is_some() { "team" } else { "master" }
                    && team_hash
                        .as_ref()
                        .is_none_or(|t| text(w, "hashed_team_id") == t)
            });
        // Object keys never alias the account master key. Draft rendering has
        // its own display-only decryption path and cannot expose a share key.
        let encrypted = if let Some(w) = wrappers.next() {
            required(w, "encrypted_chat_key")?
        } else if team.is_some() {
            return Err(Error::Forbidden);
        } else {
            required(details, "encrypted_chat_key")?
        };
        // Reads retain their first-match semantics. A saved send additionally
        // refuses conflicting ciphertext candidates rather than selecting a
        // different wrapper or re-encrypting around canonical immutability.
        let ambiguous = require_unambiguous
            && wrappers.any(|row| {
                row.get("encrypted_chat_key").and_then(Value::as_str) != Some(encrypted)
            });
        Ok(SelectedChatKeyCiphertext {
            ciphertext: encrypted,
            ambiguous,
        })
    }
    pub(super) fn chat_item(&self, row: &Value, key: &[u8; 32]) -> Result<Item> {
        if draft_only(row) && self.team()?.is_none() {
            let mut preview = zeroize::Zeroizing::new(decrypt_optional(
                row,
                "encrypted_draft_preview",
                &self.require_session()?.master_key,
            )?);
            return Ok(Item {
                id: required(row, "id")?.into(),
                title: if preview.is_empty() {
                    "Draft".into()
                } else {
                    std::mem::take(&mut *preview)
                },
                status: "draft".into(),
                fields: json!({"chat_list_title":null}),
                ..Item::default()
            });
        }
        canonical_history::saved_item(row,key)
    }

    pub(super) async fn sync_chats(&mut self) -> Result<Vec<Item>> {
        self.sync_chats_with_policy(ChatSyncPolicy::Ordinary).await
    }
    pub(super) async fn sync_chats_for_monitor(&mut self) -> Result<Vec<Item>> {
        self.sync_chats_with_policy(ChatSyncPolicy::MonitorReadOnly)
            .await
    }
    async fn sync_chats_with_policy(&mut self, policy: ChatSyncPolicy) -> Result<Vec<Item>> {
        self.refresh_chat_metadata_with_policy(0, policy).await?;
        self.render_chat_inventory_with_capability().await
    }
    // Stable timestamp ties preserve the original authenticated response order.
    // Legacy snapshots explicitly lack that order and keep their readable map order.
    pub(super) fn chat_rows_by_recency(&self) -> Vec<&Value> {
        let mut rows = self.chat_rows_in_arrival_order();
        let timestamp = |row: &Value| row["last_edited_overall_timestamp"].as_f64().unwrap_or(0.0);
        rows.sort_by(|a, b| {
            timestamp(b)
                .partial_cmp(&timestamp(a))
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        rows
    }
    pub(super) fn render_chat_inventory(&self) -> Result<Vec<Item>> {
        let wrapping = self.cached_wrapping_key()?;
        let mut items = vec![];
        for row in self.chat_rows_by_recency() {
            // Direct recipient envelopes are an independent protocol; expose a
            // locked row rather than ever trying the Team group key against it.
            if draft_only(row) && self.team()?.is_none() {
                items.push(self.chat_item(row, &wrapping)?);
                continue;
            }
            let key = match self.chat_key(row, &wrapping) {
                Ok(key) => key,
                Err(Error::Forbidden) => {
                    items.push(Item {
                        id: required(row, "id")?.into(),
                        title: "Locked chat".into(),
                        status: "locked".into(),
                        fields: json!({"chat_list_title":null}),
                        ..Item::default()
                    });
                    continue;
                }
                Err(e) => return Err(e),
            };
            items.push(self.chat_item(row, &key)?);
        }
        Ok(items)
    }
    // Metadata consumers share the authenticated sync/recovery transaction,
    // without first rendering synthetic draft or locked-row display titles.
    pub(super) async fn refresh_chat_metadata(&mut self, refreshes: u8) -> Result<()> {
        self.refresh_chat_metadata_with_policy(refreshes, ChatSyncPolicy::Ordinary)
            .await
            .map(|_| ())
    }
    pub(super) async fn refresh_chat_metadata_for_inventory(&mut self) -> Result<bool> {
        self.refresh_chat_metadata_with_policy(0, ChatSyncPolicy::InventoryDiscovery)
            .await
    }
    // Monitor snapshots read canonical ciphertext but never acquire background
    // leases, persist deliveries or replay recovery outputs as an implicit write.
    async fn refresh_chat_metadata_with_policy(
        &mut self,
        refreshes: u8,
        policy: ChatSyncPolicy,
    ) -> Result<bool> {
        // A global sync replaces content wholesale: complete any partially
        // restored native cache first (no-op for complete clients).
        self.ensure_cached_content_loaded()?;
        let generation = self.generation;
        let cancel = self.operation_cancel.clone();
        let wrapping = self.wrapping_capability().await?;
        drop(wrapping);
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        let team = self.team()?.map(str::to_owned);
        if team.is_some() && self.direct_identity.is_none() {
            match self.load_direct_identity().await {
                Ok(()) | Err(Error::Invalid(_)) => {}
                Err(error) => return Err(error),
            }
        }
        let inventory_discovery = policy == ChatSyncPolicy::InventoryDiscovery;
        // Existing secure v4 generation; one unpredictable request ID per fresh
        // transaction, never restored from cache or selected by a host caller.
        let inventory_request_id = inventory_discovery.then(|| uuid::Uuid::new_v4().to_string());
        let matches_inventory_request = |payload: &Value| {
            inventory_request_id.as_deref().is_some_and(|request_id| {
                payload["inventory_request_id"].as_str() == Some(request_id)
            })
        };
        let completion_enabled = policy.allows_effects()
            && self
                .completion_recovery_mode
                .as_ref()
                .is_some_and(|token| !token.is_cancelled());
        let mut ws = if !policy.allows_effects() {
            self.passive_chat_monitor_socket().await?
        } else if policy == ChatSyncPolicy::InventoryDiscovery {
            self.completion_recovery_inventory_socket(
                inventory_request_id.as_deref().ok_or(Error::Protocol)?,
            )
            .await?
        } else if completion_enabled {
            self.completion_recovery_socket().await?
        } else {
            self.socket().await?
        };
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        let phase = policy.requested_phase(
            !self.options.interactive && self.browser_authority.is_none(),
            team.is_none(),
            !self.embeds.is_empty() || !self.embed_keys.is_empty() || !self.wrappers.is_empty(),
        );
        let mut payload = json!({"phase":phase,"context_epoch":super::sync_windows::REQUEST_CONTEXT_EPOCH,"client_chat_versions":{},"client_chat_ids":[],"client_embed_ids":[]});
        if let Some(team) = team {
            payload["team_id"] = json!(team)
        }
        if let Some(request_id) = &inventory_request_id {
            payload["inventory_request_id"] = json!(request_id);
        }
        send(&mut ws, "phased_sync_request", payload).await?;
        let mut chats = BTreeMap::new();
        let mut chat_arrival_order = Vec::new();
        let mut wrappers = vec![];
        let mut embeds = BTreeMap::new();
        // Original live frame order DATA only. Map/snapshot order cannot supply
        // TS's first matching short-ID/alias semantics or fresh source admission.
        self.saved_embed_selectors=None;
        self.saved_embed_cache=super::saved_embed_selector::SelectorCache::Legacy;
        let mut embed_selectors=super::saved_embed_selector::SelectorFrames::default();
        let mut embed_keys = vec![];
        let mut metadata_seen = false;
        let mut phase1_windows = super::sync_windows::Phase1Windows::default();
        let mut sync_done = false;
        let mut recovery_done = false;
        let mut recovery_outputs = BTreeMap::new();
        let mut workflow_deliveries = BTreeMap::new();
        let mut task_jobs = BTreeMap::new();
        let mut main_jobs = BTreeMap::new();
        let mut metadata_jobs = BTreeMap::new();
        let mut task_seen_jobs = false;
        let mut main_seen_jobs = false;
        let mut main_pending_jobs_seen = false;
        let mut metadata_seen_jobs = false;
        // A matching authenticated startup echo selects strict transaction mode.
        // Older/missing welcomes retain the same socket's legacy parser, with
        // proof minting closed. Tentative legacy metadata is cleared on upgrade.
        let mut inventory_correlation_supported = false;
        let mut feed_capture = super::sync_feed::ColdStartCapture::default();
        let deadline = crate::platform::time::Instant::now() + Duration::from_secs(120);
        loop {
            let (k, p) = tokio::select! {
                biased;
                _ = cancel.cancelled() => return Err(Error::Cancelled),
                result = crate::platform::time::timeout_at(deadline, receive(&mut ws)) => result.map_err(|_| Error::Offline)??,
            };
            if cancel.is_cancelled() || self.generation != generation {
                return Err(Error::Cancelled);
            }
            if inventory_discovery
                && !inventory_correlation_supported
                && k == "server_capabilities"
                && matches_inventory_request(&p)
            {
                inventory_correlation_supported = true;
                chats.clear();
                chat_arrival_order.clear();
                phase1_windows = super::sync_windows::Phase1Windows::default();
                wrappers.clear();
                embeds.clear();
                embed_selectors=super::saved_embed_selector::SelectorFrames::default();
                embed_keys.clear();
                metadata_seen = false;
                sync_done = false;
                recovery_done = false;
                main_seen_jobs = false;
                main_pending_jobs_seen = false;
                metadata_seen_jobs = false;
                task_seen_jobs = false;
            }
            if completion_enabled {
                super::completion_recovery::capture(&k, &p, &mut main_jobs, &mut metadata_jobs)?;
                let bound = !inventory_discovery
                    || !inventory_correlation_supported
                    || matches_inventory_request(&p);
                if bound { main_pending_jobs_seen |= super::completion_recovery::has_pending_main_jobs(&k, &p)?; }
                main_seen_jobs |= k == "recovery_jobs_available" && bound;
                metadata_seen_jobs |= k == "metadata_jobs_available" && bound;
            }
            if policy.allows_effects() {
                super::workflow_delivery::capture(&k, &p, &mut workflow_deliveries)?;
                super::task_jobs::capture(&k, &p, &mut task_jobs)?;
                task_seen_jobs |= k == "task_update_jobs_available"
                    && p["complete"] == true
                    && (!inventory_discovery
                        || !inventory_correlation_supported
                        || matches_inventory_request(&p));
            }
            // Retain strict completion-marker validation in both policies, but
            // read-only sync does not collect or decrypt offered recovery work.
            if (policy.allows_effects() || k == "recovery_outputs_discovery_complete")
                && let Some(done) = super::recovery::capture(&k, &p, &mut recovery_outputs)?
            {
                if !inventory_discovery
                    || !inventory_correlation_supported
                    || matches_inventory_request(&p)
                {
                    recovery_done = done;
                }
            }
            if !inventory_discovery
                || !inventory_correlation_supported
                || matches_inventory_request(&p)
            {
                read_phase::accept_sync_ciphertext_frame(&k,&p,self.team()?,
                    &mut phase1_windows,&mut chats,&mut chat_arrival_order,&mut wrappers,
                    &mut embeds,&mut embed_keys,&mut metadata_seen,&mut sync_done)?;
                embed_selectors.observe(&k,&p);
                super::sync_feed::observe_cold_start(&k, &p, self.team()?, &mut feed_capture);
            }
            if sync_done && recovery_done {
                break;
            }
        }
        if !metadata_seen {
            return Err(Error::Protocol);
        }
        // Metadata has its own bounded discovery response. Failure/defer cannot
        // turn a valid main sync/recovered reply into a new inference request.
        if completion_enabled
            && self.team()?.is_none()
            && (!metadata_seen_jobs
                || (inventory_discovery
                    && inventory_correlation_supported
                    && (!main_seen_jobs || !task_seen_jobs)))
        {
            let metadata_deadline = crate::platform::time::Instant::now() + Duration::from_secs(3);
            // Reuse the existing bounded window. Do not resend metadata work
            // when only independently scheduled main/Task discovery is pending.
            let mut metadata_request = json!({"protocol_version":1});
            if let Some(request_id) = &inventory_request_id {
                metadata_request["inventory_request_id"] = json!(request_id);
            }
            let sent = if metadata_seen_jobs {
                Ok(Ok(()))
            } else {
                tokio::select! {biased;_=cancel.cancelled()=>return Err(Error::Cancelled),result=crate::platform::time::timeout_at(metadata_deadline,send(&mut ws,"metadata_jobs_request",metadata_request))=>result}
            };
            if matches!(sent, Ok(Ok(()))) {
                while crate::platform::time::Instant::now() < metadata_deadline {
                    let frame = tokio::select! {biased;_=cancel.cancelled()=>return Err(Error::Cancelled),result=crate::platform::time::timeout_at(metadata_deadline,super::transport::receive_ephemeral(&mut ws))=>result};
                    match frame {
                        Ok(Ok((kind, payload))) => {
                            super::completion_recovery::capture(
                                &kind,
                                &payload,
                                &mut main_jobs,
                                &mut metadata_jobs,
                            )?;
                            let bound = !inventory_discovery
                                || !inventory_correlation_supported
                                || matches_inventory_request(&payload);
                            if bound { main_pending_jobs_seen |= super::completion_recovery::has_pending_main_jobs(&kind, &payload)?; }
                            main_seen_jobs |= kind == "recovery_jobs_available" && bound;
                            metadata_seen_jobs |= kind == "metadata_jobs_available" && bound;
                            if inventory_discovery {
                                super::workflow_delivery::capture(
                                    &kind,
                                    &payload,
                                    &mut workflow_deliveries,
                                )?;
                                let _ = super::recovery::capture(
                                    &kind,
                                    &payload,
                                    &mut recovery_outputs,
                                )?;
                                super::task_jobs::capture(&kind, &payload, &mut task_jobs)?;
                                task_seen_jobs |= kind == "task_update_jobs_available"
                                    && payload["complete"] == true
                                    && bound;
                            }
                            if metadata_seen_jobs
                                && (!inventory_discovery || (main_seen_jobs && task_seen_jobs))
                            {
                                break;
                            }
                        }
                        Ok(Err(Error::Expired)) => {
                            self.forget_session();
                            return Err(Error::Expired);
                        }
                        Ok(Err(Error::Cancelled)) => return Err(Error::Cancelled),
                        _ => break,
                    }
                }
            }
        }
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        // Validate the entire phase before publishing any new partial window.
        // Window crypto uses staged wrappers, never a temporary mutation of the
        // live Client, and cannot replace its complete selected history.
        phase1_windows.merge_metadata_ordered(&mut chats, &mut chat_arrival_order);
        let sync_message_windows = self.finish_sync_windows_with_capability(phase1_windows, &chats, &wrappers).await?;
        if completion_enabled {
            self.completion_recovery_jobs = main_jobs;
            self.metadata_recovery_jobs = metadata_jobs;
        }
        let mut chats = chats;
        let mut chat_arrival_order = chat_arrival_order;
        let mut sync_message_windows = sync_message_windows;
        self.drop_deleted_chats(&mut chats, &mut chat_arrival_order);
        sync_message_windows.retain(|id, _| !self.is_deleted_chat(id));
        self.chats = chats;
        self.chat_arrival_order = Some(chat_arrival_order);
        self.sync_message_windows = sync_message_windows;
        self.wrappers = wrappers;
        self.embeds = embeds;
        self.embed_keys = embed_keys;
        self.adopt_cold_start_feed(feed_capture)?;
        // Optional bounded selector support must not restrict any maintained
        // content workload. Missing/overflow/malformed order remains unavailable.
        self.saved_embed_selectors=embed_selectors.clone().bind(self).ok().map(std::sync::Arc::new);
        let (task_updates, delivered) = if policy.allows_effects() {
            self.replay_outputs(&mut ws, &recovery_outputs, None)
                .await?;
            let task_updates = if inventory_discovery {
                0
            } else {
                Box::pin(self.persist_task_jobs(&mut ws, &task_jobs, &[], None, &cancel))
                    .await?
                    .len()
            };
            let delivered = self
                .persist_workflow_deliveries(&mut ws, &workflow_deliveries)
                .await?;
            (task_updates, delivered)
        } else {
            (0, 0)
        };
        let _ = ws.close(None).await;
        if delivered > 0 || task_updates > 0 {
            if refreshes >= 3 {
                return Err(Error::Invalid(
                    "Background encrypted updates kept arriving during sync. Refresh again to load their canonical metadata.",
                ));
            }
            return Box::pin(self.refresh_chat_metadata_with_policy(refreshes + 1, policy)).await;
        }
        if self.saved_embed_selectors.as_ref().is_some_and(|original| {
            let stored=original.identities.iter().try_fold(embed_selectors.bytes,|n,(id,row)|n.checked_add(id.len())?.checked_add(row.bytes()));
            stored.is_some_and(|n|n<=super::saved_embed_selector::MAX_SELECTOR_BYTES-512)
        }) {
            self.saved_embed_cache=super::saved_embed_selector::SelectorCache::Ordered { at:now_ms(), owner:self.user["id"].as_str().or_else(||self.user["user_id"].as_str()).unwrap_or("").to_owned(), frames:embed_selectors, identities:self.saved_embed_selectors.as_ref().unwrap().identities.clone() };
        }
        // Omitted/timed-out discovery and any offered background effects may
        // still satisfy the historical read API, but cannot authorize reuse.
        Ok(inventory_discovery
            && inventory_correlation_supported
            && completion_enabled
            && main_seen_jobs
            && !main_pending_jobs_seen
            && metadata_seen_jobs
            && task_seen_jobs
            && self.completion_recovery_jobs.is_empty()
            && self.metadata_recovery_jobs.is_empty()
            && recovery_outputs.is_empty()
            && workflow_deliveries.is_empty()
            && task_jobs.is_empty())
    }
    pub async fn open_chat(&mut self, id: &str) -> Result<Chat> {
        self.require_canonical_read_profile()?;
        match self.open_chat_live(id).await {
            Err(Error::Offline) if self.history.contains_key(id) => self.cached_chat_with_capability(id).await,
            result => result,
        }
    }
    pub(super) fn cached_chat(&self, id: &str) -> Result<Chat> {
        let wrapping = self.cached_wrapping_key()?;
        let row = self.chats.get(id).ok_or(Error::Offline)?;
        if draft_only(row) && self.team()?.is_none() {
            let mut item = Plain::new(self.chat_item(row, &wrapping)?);
            return Ok(Chat {
                id: id.into(),
                title: std::mem::take(&mut item.title),
                ..Chat::default()
            });
        }
        let key = self.chat_key(row, &wrapping)?;
        let mut item = Plain::new(self.chat_item(row, &key)?);
        let mut messages = Plain::new(Vec::<Message>::new());
        for raw in self.history.get(id).ok_or(Error::Offline)? {
            let mut message = Plain::new(Message {
                id: ["client_message_id", "message_id", "id"]
                    .into_iter()
                    .map(|field| text(raw, field))
                    .find(|id| !id.is_empty())
                    .ok_or(Error::Protocol)?
                    .into(),
                role: required(raw, "role")?.into(),
                ..Message::default()
            });
            message.content = decrypt_optional(raw, "encrypted_content", &key)?;
            message.sender = decrypt_optional(raw, "encrypted_sender_name", &key)?;
            message.thinking = decrypt_optional(raw, "encrypted_thinking_content", &key)?;
            messages.push(message.into_inner());
        }
        let mut chat = Plain::new(Chat {
            id: id.into(),
            title: std::mem::take(&mut item.title),
            category: std::mem::take(&mut item.category),
            messages: messages.into_inner(),
        });
        self.restore_chat_tokens(&mut chat, &key)?;
        Ok(chat.into_inner())
    }
    pub(super) fn cached_wrapping_key(&self) -> Result<Key> {
        let s = self.require_session()?;
        if let Some(team) = &s.active_team_id {
            self.team_key
                .as_ref()
                .filter(|(id, _)| id == team)
                .map(|(_, key)| key.clone())
                .ok_or(Error::Forbidden)
        } else {
            Ok(s.master_key.clone())
        }
    }
    pub fn cached_chat_items(&self) -> Result<Vec<Item>> {
        self.cached_chats()
    }
    pub(super) fn cached_chats(&self) -> Result<Vec<Item>> {
        let wrapping = self.cached_wrapping_key()?;
        let mut items = Plain::new(Vec::<Item>::new());
        for row in self.chat_rows_by_recency() {
            let item = if draft_only(row) && self.team()?.is_none() {
                self.chat_item(row, &wrapping)?
            } else {
                let key = self.chat_key(row, &wrapping)?;
                self.chat_item(row, &key)?
            };
            items.push(item);
        }
        Ok(items.into_inner())
    }
    /// Consume a complete correlated global inventory before reading full live
    /// history. A final receipt uses only the original discovery clock; stale
    /// or unsupported evidence retains the ordinary open_chat fallback.
    /// The caller still owns local pending/restart-journal clearance and durable
    /// save-before-output. This receipt is cached-data freshness, never authority.
    pub async fn open_chat_with_fresh_chat_inventory(
        &mut self,
        id: &str,
        proof: FreshChatInventory,
        cancel: &CancellationToken,
    ) -> Result<Chat> {
        self.require_canonical_read_profile()?;
        if cancel.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let transaction = read_freshness::ReadFreshnessTransaction::begin(self, id, proof, cancel)?;
        let Some(mut transaction) = transaction else {
            return tokio::select! {
                biased;
                _ = cancel.cancelled() => Err(Error::Cancelled),
                result = self.open_chat(id) => result,
            };
        };
        let live = tokio::select! {
            biased;
            _ = cancel.cancelled() => return Err(Error::Cancelled),
            result = self.open_chat_live_in_transaction(id, Some(&mut transaction), None) => result.map(Plain::new),
        };
        if cancel.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.require_session()?;
        match live {
            Ok(chat) => {
                transaction.commit(self, id)?;
                Ok(chat.into_inner())
            }
            Err(Error::Offline) if self.history.contains_key(id) => self.cached_chat_with_capability(id).await,
            Err(error) => Err(error),
        }
    }
    pub(super) async fn open_chat_live(&mut self, id: &str) -> Result<Chat> {
        self.open_chat_live_in_transaction(id, None, None).await
    }
    pub(super) async fn open_chat_live_with_first_page(
        &mut self, id: &str,
        first_page: Option<&mut monitor::cached_view::FirstPageRead<'_>>,
    ) -> Result<Chat> {
        self.open_chat_live_in_transaction(id, None, first_page).await
    }
    async fn open_chat_live_in_transaction(
        &mut self,
        id: &str,
        mut transaction: Option<&mut read_freshness::ReadFreshnessTransaction>,
        mut first_page: Option<&mut monitor::cached_view::FirstPageRead<'_>>,
    ) -> Result<Chat> {
        self.require_canonical_read_profile()?;
        if self.is_ephemeral_chat(id) {
            return Err(Error::Invalid(
                "Volatile chat history exists only in the caller's memory.",
            ));
        }
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        let crypto_scope = super::sync_capability::AsyncCryptoScope::begin(self)?;
        if let Some(transaction) = transaction.as_deref_mut() {
            transaction.before_request(self, id);
        }
        let metadata = self.request_chat_metadata(id).await;
        if let Some(transaction) = transaction.as_deref_mut() {
            transaction.after_request(self, id);
        }
        let metadata = match metadata? {
            Some(metadata) => metadata,
            None => return self.open_canonical_personal_draft(id).await,
        };
        let row = metadata["chats"]
            .as_array()
            .ok_or(Error::Protocol)?
            .iter()
            .find(|r| text(r, "id") == id)
            .ok_or(Error::Forbidden)?
            .clone();
        crypto_scope.check(self)?;
        let wrapping = self.wrapping_capability().await?;
        crypto_scope.check(self)?;
        self.active_chat = Some(id.to_owned());
        self.insert_chat_row(id.to_owned(), row.clone());
        if draft_only(&row) && self.team()?.is_none() {
            let mut item = Plain::new(self.draft_item_with_capability(&row).await?);
            self.history.insert(id.into(), vec![]);
            self.sync_message_windows.remove(id);
            self.selected_first_pages.remove(id);
            return Ok(Chat {
                id: id.into(),
                title: std::mem::take(&mut item.title),
                category: std::mem::take(&mut item.category),
                messages: vec![],
            });
        }
        if text(&row, "chat_visibility") == "direct" {
            self.load_direct_identity().await?;
        }
        let key = self.chat_key_with_capability(&row, &wrapping).await?;
        let mut item = Plain::new(self.chat_item(&row, &key)?);
        let mut history=canonical_history::CanonicalHistory::new(id);
        for _ in 0..100 {
            let mut url = self.url(&format!("/v1/chats/{}/messages/window", segment(id)))?;
            {
                let mut q = url.query_pairs_mut();
                q.append_pair("direction",if history.cursor().is_some(){"before"}else{"latest"})
                    .append_pair("limit","100").append_pair("respect_compression_boundary","false");
                if let Some(c)=history.cursor(){
                    q.append_pair("before_timestamp",&c["created_at"].to_string())
                        .append_pair("before_message_id",required(c,"message_id")?);
                }
            }
            let path=self.scoped(&format!("{}?{}",self.request_route_path(&url)?,url.query().unwrap_or("")))?;
            if let Some(transaction)=transaction.as_deref_mut(){transaction.before_request(self,id);}
            let page=self.request(Method::GET,&path,None).await;
            if let Some(transaction)=transaction.as_deref_mut(){transaction.after_request(self,id);}
            let page=page?;crypto_scope.check(self)?;
            let decoded=history.decode_page(page,&key)?;
            if decoded.first()&&decoded.more()
                &&let Some(first_page)=first_page.as_deref_mut()
            {
                self.publish_chat_first_page(first_page,&row,decoded.page(),decoded.decoded(),decoded.encrypted(),&key).await?;
                crypto_scope.check_chat(self,id)?;
            }
            if history.append_page(decoded)? {
                let(messages,encrypted_history,explicit_terminal)=history.into_parts()?;
                self.history.insert(id.to_owned(),encrypted_history);
                let mut chat=Plain::new(Chat{id:id.to_owned(),title:std::mem::take(&mut item.title),category:std::mem::take(&mut item.category),messages:messages.into_inner()});
                self.restore_chat_tokens(&mut chat,&key)?;
                if let Err(error)=crypto_scope.check(self).and_then(|_|self.require_canonical_read_profile()){
                    crate::client::monitor::cached_view::wipe_chat(&mut chat);return Err(error);
                }
                self.sync_message_windows.remove(id);self.selected_first_pages.remove(id);
                if let Some(transaction)=transaction.as_deref_mut(){transaction.terminal=explicit_terminal;}
                return Ok(chat.into_inner());
            }
        }
        Err(Error::Invalid(
            "Chat history exceeds the supported window limit.",
        ))
    }
    fn restore_chat_tokens(&self, chat: &mut Chat, key: &[u8; 32]) -> Result<()> {
        let rows = self.history.get(&chat.id).map(Vec::as_slice).unwrap_or(&[]);
        restore_chat_tokens_from_rows(chat, key, rows)
    }
    /// Cache snapshots contain only server ciphertext and non-private metadata.
    pub fn ciphertext_snapshot(&self) -> Value {
        let mut snapshot = json!({"chats":self.chats,"wrappers":self.wrappers,"history":self.history,"embeds":self.embeds,"embed_keys":self.embed_keys,"team_wrapped_key":self.team_wrapped_key});
        if let Some(order) = self.current_chat_arrival_order() {
            snapshot[chat_arrival_order::SNAPSHOT_FIELD] = json!({"version":1,"ids":order});
        }
        if let Some(data)=self.saved_embed_cache.snapshot(self.saved_embed_unsynced_empty()) { snapshot[super::saved_embed_selector::CACHE_FIELD]=data; }
        let selected = self.snapshot_selected_first_pages();
        if !selected.is_empty() { snapshot[super::selected_first_page::SNAPSHOT_FIELD] = json!(selected); }
        let windows = self.snapshot_sync_windows();
        if !windows.is_empty() {
            snapshot[super::sync_windows::SNAPSHOT_FIELD] = json!(windows);
        }
        if let Some(metadata) = self.chat_list_freshness.snapshot_metadata() {
            snapshot[chat_list_freshness::SNAPSHOT_FIELD] = metadata;
        }
        if let Some(tombstones) = self.deleted_chats_snapshot() {
            snapshot[super::chat_tombstones::SNAPSHOT_FIELD] = tombstones;
        }
        if let Some(feed) = self.chat_sync_feed_snapshot() {
            snapshot[super::sync_feed::SNAPSHOT_FIELD] = feed;
        }
        snapshot
    }
    pub fn restore_ciphertext_snapshot(&mut self, snapshot: &Value) -> Result<()> {
        self.cached_content = Default::default();
        self.saved_embed_selectors=None;
        self.saved_embed_cache=super::saved_embed_selector::SelectorCache::Legacy;
        self.chat_list_freshness.invalidate();
        // Restored data cannot restore authority from an earlier live read.
        self.invalidate_chat_inventory_proofs();
        self.require_session()?;
        let chats: BTreeMap<String, Value> = serde_json::from_value(snapshot["chats"].clone())?;
        let chat_arrival_order = chat_arrival_order::restore(snapshot.get(chat_arrival_order::SNAPSHOT_FIELD), &chats)?;
        let sync_message_windows = super::sync_windows::restore_windows(snapshot.get(super::sync_windows::SNAPSHOT_FIELD))?;
        let selected_first_pages = super::selected_first_page::restore(snapshot.get(super::selected_first_page::SNAPSHOT_FIELD))?;
        for (id, row) in &chats {
            if text(row, "id") != id {
                return Err(Error::Protocol);
            }
        }
        if let Some(wrapper) = snapshot.get("team_wrapped_key").filter(|v| !v.is_null()) {
            let (team, encrypted): (String, String) = serde_json::from_value(wrapper.clone())?;
            if self.team()? != Some(team.as_str()) {
                return Err(Error::Forbidden);
            }
            let key = key_from_bytes(&crypto::decrypt_bytes(
                &encrypted,
                &self.require_session()?.master_key,
            )?)?;
            self.team_key = Some((team.clone(), key));
            self.team_wrapped_key = Some((team, encrypted));
        }
        self.embeds =
            serde_json::from_value(snapshot.get("embeds").cloned().unwrap_or_else(|| json!({})))?;
        self.embed_keys = serde_json::from_value(
            snapshot
                .get("embed_keys")
                .cloned()
                .unwrap_or_else(|| json!([])),
        )?;
        self.sync_message_windows = sync_message_windows;
        self.selected_first_pages = selected_first_pages;
        self.history = serde_json::from_value(
            snapshot
                .get("history")
                .cloned()
                .unwrap_or_else(|| json!({})),
        )?;
        self.chats = chats;
        self.chat_arrival_order = chat_arrival_order;
        self.deleted_chats = super::chat_tombstones::restore(snapshot.get(super::chat_tombstones::SNAPSHOT_FIELD));
        self.restore_chat_sync_feed(snapshot)?;
        self.wrappers = snapshot["wrappers"]
            .as_array()
            .ok_or(Error::Protocol)?
            .clone();
        Ok(())
    }
}
pub(super) fn decrypt_optional(row: &Value, name: &str, key: &[u8; 32]) -> Result<String> {
    match row.get(name) {
        None | Some(Value::Null) => Ok(String::new()),
        Some(Value::String(s)) if s.is_empty() => Ok(String::new()),
        Some(Value::String(s)) => crypto::decrypt_combined(s, key),
        _ => Err(Error::Protocol),
    }
}

impl Client {
    // A draft is a user-specific record and can exist before a shared chat row.
    // This path is admitted only after exact metadata 404, never after denied,
    // malformed or successful saved-chat metadata (including promotion).
    async fn open_canonical_personal_draft(&mut self, id: &str) -> Result<Chat> {
        let crypto_scope=super::sync_capability::AsyncCryptoScope::begin(self)?;
        let generation = self.generation;
        let cancel = self.operation_cancel.clone();
        if self.team()?.is_some() {
            return Err(Error::Invalid("The requested item is unavailable."));
        }
        let mut row = self
            .chats
            .get(id)
            .cloned()
            .ok_or(Error::Invalid("The requested item is unavailable."))?;
        let owner = text(&self.user, "id").to_owned();
        if !draft_only(&row)
            || text(&row, "id") != id
            || !personal_draft_scope(&row, &owner)
            || row
                .get("messages_v")
                .is_some_and(|v| !v.is_null() && v.as_u64() != Some(0))
            || self
                .history
                .get(id)
                .is_some_and(|messages| !messages.is_empty())
            || self
                .wrappers
                .iter()
                .chain(row["chat_key_wrappers"].as_array().into_iter().flatten())
                .any(|wrapper| text(wrapper, "hashed_chat_id") == sha256(id))
        {
            return Err(Error::Invalid("The requested item is unavailable."));
        }
        let old_version = row["draft_v"]
            .as_u64()
            .filter(|v| *v > 0)
            .ok_or(Error::Protocol)?;
        let response = self
            .request(Method::GET, &format!("/v1/drafts/{}", segment(id)), None)
            .await?;
        // Finish transport credential rotation, then fence local deletion and
        // plaintext publication against cancellation of this exact operation.
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        let draft = response.get("draft").ok_or(Error::Protocol)?;
        if draft.is_null() {
            self.remove_chat_row(id);
            self.history.remove(id);
            self.selected_first_pages.remove(id);
            if self.active_chat.as_deref() == Some(id) {
                self.active_chat = None;
            }
            return Err(Error::Invalid("The requested draft is unavailable."));
        }
        if !draft.is_object()
            || required(draft, "chat_id")? != id
            || !personal_draft_scope(draft, &owner)
        {
            return Err(Error::Forbidden);
        }
        let version = draft["draft_v"]
            .as_u64()
            .filter(|v| *v > 0)
            .ok_or(Error::Protocol)?;
        let encrypted = required(draft, "encrypted_draft_md")?;
        let preview_ciphertext = draft_preview_ciphertext(draft)?;
        if version < old_version
            || (version == old_version
                && (encrypted != text(&row, "encrypted_draft_md")
                    || preview_ciphertext != draft_preview_ciphertext(&row)?))
        {
            return Err(Error::Conflict);
        }
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        let master = self.master_capability()?;
        let markdown = zeroize::Zeroizing::new(master.decrypt_text(encrypted).await?);
        crypto_scope.check(self)?;
        if markdown.is_empty() || markdown.len() > 1_000_000 {
            return Err(Error::Protocol);
        }
        let preview = match preview_ciphertext {
            None => None,
            Some(ciphertext) => Some(zeroize::Zeroizing::new(master.decrypt_text(ciphertext).await?)),
        };
        let mut title = zeroize::Zeroizing::new(
            preview
                .as_deref()
                .filter(|text| !text.is_empty())
                .map(String::as_str)
                .unwrap_or(&markdown)
                .chars()
                .take(200)
                .collect::<String>(),
        );
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        crypto_scope.check(self)?;
        // Persist ciphertext only. No object key or key wrapper is synthesized.
        row["encrypted_draft_md"] = json!(encrypted);
        row["encrypted_draft_preview"] = draft["encrypted_draft_preview"].clone();
        row["draft_v"] = json!(version);
        self.insert_chat_row(id.into(), row);
        self.history.insert(id.into(), vec![]);
        self.sync_message_windows.remove(id);
        self.selected_first_pages.remove(id);
        self.active_chat = Some(id.into());
        Ok(Chat {
            id: id.into(),
            title: std::mem::take(&mut *title),
            ..Chat::default()
        })
    }
    /// Save an encrypted draft without invoking inference. Drafts use the account
    /// master key until the first admitted turn establishes a chat key.
    pub async fn save_draft(&mut self, chat_id: Option<&str>, markdown: &str) -> Result<String> {
        let generation = self.generation;
        let cancel = self.operation_cancel.clone();
        if chat_id.is_some_and(|id| self.is_ephemeral_chat(id)) {
            return Err(Error::Invalid("Volatile chats do not have saved drafts."));
        }
        if self.team()?.is_some() {
            return Err(Error::Forbidden);
        }
        super::browser_draft::validate_draft_markdown(markdown)?;
        let id = chat_id
            .map(str::to_owned)
            .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
        uuid::Uuid::parse_str(&id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        let old_version = self
            .chats
            .get(&id)
            .and_then(|row| row["draft_v"].as_u64())
            .unwrap_or(0);
        let mut ws = self.socket().await?;
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        let crypto_scope=super::sync_capability::AsyncCryptoScope::begin(self)?;
        let (encrypted, preview) = self.encrypt_draft_fields(markdown, &crypto_scope).await?;
        send(
            &mut ws,
            "update_draft",
            json!({"chat_id":id,"encrypted_draft_md":encrypted,"encrypted_draft_preview":preview}),
        )
        .await?;
        let receipt = transport::wait(&mut ws, "draft_update_receipt", "chat_id", &id).await?;
        let _ = ws.close(None).await;
        if cancel.is_cancelled() || self.generation != generation {
            return Err(Error::Cancelled);
        }
        crypto_scope.check(self)?;
        if receipt["success"] != true {
            return Err(Error::Protocol);
        }
        let version = receipt["draft_v"]
            .as_u64()
            .filter(|v| *v > 0)
            .ok_or(Error::Protocol)?;
        if receipt["superseded"] == true || version <= old_version {
            return Err(Error::Conflict);
        }
        if receipt
            .get("team_id")
            .is_some_and(|team| !team.is_null() && team != "")
        {
            return Err(Error::Forbidden);
        }
        if !self.chats.contains_key(&id) {
            self.insert_chat_row(id.clone(), json!({"id":id}));
        }
        let row = self.chats.get_mut(&id).ok_or(Error::Protocol)?;
        row["encrypted_draft_md"] = json!(encrypted);
        row["encrypted_draft_preview"] = json!(preview);
        row["draft_v"] = json!(version);
        Ok(id)
    }
}

pub(super) fn draft_only(row: &Value) -> bool {
    text(row, "encrypted_chat_key").is_empty()
        && !text(row, "encrypted_draft_md").is_empty()
        && text(row, "chat_visibility") != "direct"
}

fn personal_draft_scope(row: &Value, owner: &str) -> bool {
    ["team_id", "hashed_team_id", "encrypted_chat_key"]
        .into_iter()
        .all(|field| {
            row.get(field)
                .is_none_or(|v| v.is_null() || v.as_str() == Some(""))
        })
        && row
            .get("chat_visibility")
            .is_none_or(|v| v.is_null() || matches!(v.as_str(), Some("" | "personal")))
        && row
            .get("user_id")
            .is_none_or(|v| v.is_null() || (!owner.is_empty() && v.as_str() == Some(owner)))
}

fn draft_preview_ciphertext(row: &Value) -> Result<Option<&str>> {
    match row.get("encrypted_draft_preview") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(ciphertext)) if !ciphertext.is_empty() => Ok(Some(ciphertext)),
        _ => Err(Error::Protocol),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    include!("sync_legacy_layout_tests.rs");
    fn client(team: Option<&str>) -> Client {
        Client::new(
            "https://api.example.com",
            Some(Session {
                api_url: "https://api.example.com".into(),
                session_id: "session".into(),
                cookies: BTreeMap::new(),
                ws_token: Some("token".into()),
                master_key: zeroize::Zeroizing::new([7; 32]),
                hashed_email: "owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: team.map(str::to_owned),
            }),
        )
        .unwrap()
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn team_never_falls_back_to_personal_wrapper() {
        let c = client(Some("team-a"));
        let row = json!({"id":"chat","encrypted_chat_key":crypto::encrypt_bytes(&[8;32],&[7;32]).unwrap()});
        assert!(matches!(c.chat_key(&row, &[7; 32]), Err(Error::Forbidden)));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn direct_chat_never_uses_group_key() {
        let c = client(Some("team-a"));
        let row = json!({"id":"chat","chat_visibility":"direct","encrypted_chat_key":"opaque-recipient-envelope"});
        assert!(matches!(c.chat_key(&row, &[7; 32]), Err(Error::Forbidden)));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn personal_view_rejects_team_rows() {
        let c = client(None);
        let row = json!({"id":"chat","hashed_team_id":sha256("team-a"),"encrypted_chat_key":crypto::encrypt_bytes(&[8;32],&[7;32]).unwrap()});
        assert!(matches!(c.chat_key(&row, &[7; 32]), Err(Error::Forbidden)));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn scoped_team_wrapper_authenticates_key() {
        let mut c = client(Some("team-a"));
        let encrypted = crypto::encrypt_bytes(&[8; 32], &[9; 32]).unwrap();
        c.wrappers.push(json!({"key_type":"team","hashed_team_id":sha256("team-a"),"hashed_chat_id":sha256("chat"),"encrypted_chat_key":encrypted}));
        let key = c.chat_key(&json!({"id":"chat"}), &[9; 32]).unwrap();
        assert_eq!(*key, [8; 32]);
        assert!(c.chat_key(&json!({"id":"other"}), &[9; 32]).is_err());
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn list_title_provenance_distinguishes_missing_null_empty_cipher_and_empty_plaintext() {
        let c = client(None);
        for encrypted in [None, Some(Value::Null), Some(json!(""))] {
            let mut row = json!({"id":"synthetic-chat"});
            if let Some(encrypted) = encrypted {
                row["encrypted_title"] = encrypted;
            }
            let item = c.chat_item(&row, &[8; 32]).unwrap();
            assert_eq!(item.title, "");
            assert!(
                item.fields
                    .as_object()
                    .unwrap()
                    .contains_key("chat_list_title")
            );
            assert!(item.fields["chat_list_title"].is_null());
            assert!(item.status.is_empty());
        }
        for plain in ["", "Synthetic title", "Draft", "Locked chat"] {
            let row = json!({"id":"synthetic-chat",
                "encrypted_title":crypto::encrypt_combined(plain,&[8;32]).unwrap(),
                "created_at":11,"updated_at":22,"pinned":true,"messages_v":3});
            let item = c.chat_item(&row, &[8; 32]).unwrap();
            assert_eq!(item.title, plain);
            assert_eq!(item.fields["chat_list_title"].as_str(), Some(plain));
            assert_eq!(item.fields["created_at"], 11);
            assert_eq!(item.fields["updated_at"], 22);
            assert_eq!(item.fields["pinned"], true);
            assert_eq!(item.fields["messages_v"], 3);
            assert!(item.status.is_empty());
        }
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn draft_and_locked_list_metadata_do_not_relabel_display_or_try_other_keys() {
        let mut c = client(None);
        for preview in [None, Some("Synthetic draft preview")] {
            let mut row = json!({"id":"synthetic-draft",
                "encrypted_draft_md":crypto::encrypt_combined("Synthetic draft body",&[7;32]).unwrap()});
            if let Some(preview) = preview {
                row["encrypted_draft_preview"] =
                    json!(crypto::encrypt_combined(preview, &[7; 32]).unwrap());
            }
            let item = c.chat_item(&row, &[8; 32]).unwrap();
            assert_eq!(item.title, preview.unwrap_or("Draft"));
            assert_eq!(item.status, "draft");
            assert!(
                item.fields
                    .as_object()
                    .unwrap()
                    .contains_key("chat_list_title")
            );
            assert!(item.fields["chat_list_title"].is_null());
        }
        c.chats.insert(
            "synthetic-direct".into(),
            json!({"id":"synthetic-direct",
            "chat_visibility":"direct","encrypted_chat_key":"opaque-recipient-envelope",
            "encrypted_title":crypto::encrypt_combined("Must stay locked",&[7;32]).unwrap()}),
        );
        let before = c.ciphertext_snapshot();
        let items = c.render_chat_inventory().unwrap();
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].title, "Locked chat");
        assert_eq!(items[0].status, "locked");
        assert!(
            items[0]
                .fields
                .as_object()
                .unwrap()
                .contains_key("chat_list_title")
        );
        assert!(items[0].fields["chat_list_title"].is_null());
        assert_eq!(c.ciphertext_snapshot(), before);
        assert!(c.cached_chat_items().is_err()); // no new Direct key fallback
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn nullable_list_title_does_not_swallow_shape_or_decryption_failures() {
        let c = client(None);
        for invalid in [
            json!(123),
            json!(false),
            json!({}),
            json!([]),
            json!("invalid-ciphertext"),
        ] {
            assert!(
                c.chat_item(
                    &json!({"id":"synthetic-chat","encrypted_title":invalid}),
                    &[8; 32]
                )
                .is_err()
            );
        }
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn cached_history_contains_only_ciphertext() {
        let mut c = client(None);
        let encrypted_key = crypto::encrypt_bytes(&[8; 32], &[7; 32]).unwrap();
        c.chats.insert("chat".into(),json!({"id":"chat","encrypted_chat_key":encrypted_key,"encrypted_title":crypto::encrypt_combined("private title",&[8;32]).unwrap()}));
        let ciphertext = c.ciphertext_snapshot().to_string();
        assert!(!ciphertext.contains("private title"));
        let item = c.cached_chats().unwrap();
        assert_eq!(item[0].title, "private title");
    }
}

#[cfg(test)]
#[path = "sync_draft_tests.rs"]
mod draft_tests;

#[cfg(test)]
#[path = "sync_fresh_inventory_tests.rs"]
mod fresh_inventory_tests;

#[cfg(test)]
#[path = "sync_list_order_tests.rs"]
mod list_order_tests;

/// Same authenticated row decoder used by full history and one-page presentation.
pub(super) fn decode_chat_message(
    raw: &Value,
    id: &str,
    key: &[u8; 32],
    seen: &mut std::collections::HashSet<String>,
) -> Result<(Value, Message)> {
    decode_chat_message_projection(raw,id,key,seen,true)
}
/// Rich stored JSON shares content/identity validation; its nullable metadata
/// decoder owns sender once, and skips unused legacy thinking.
/// Identity/chat/duplicate-row validation stays in the same shared decoder.
pub(super) fn decode_chat_message_stored(raw:&Value,id:&str,key:&[u8;32],seen:&mut std::collections::HashSet<String>)->Result<(Value,Message)> {
    decode_chat_message_projection(raw,id,key,seen,false)
}
fn decode_chat_message_projection(raw:&Value,id:&str,key:&[u8;32],seen:&mut std::collections::HashSet<String>,thinking:bool)->Result<(Value,Message)> {
    let raw: Value = if let Some(s) = raw.as_str() {
        serde_json::from_str(s)?
    } else {
        raw.clone()
    };
    decode_chat_message_owned_projection(raw, id, key, seen, thinking)
}
/// Already normalized ciphertext row owned by the bounded page decoder.
/// Identity, duplicate and crypto checks are identical to the reference entry point.
pub(super) fn decode_chat_message_owned(
    raw: Value, id: &str, key: &[u8; 32],
    seen: &mut std::collections::HashSet<String>,
) -> Result<(Value, Message)> {
    decode_chat_message_owned_projection(raw, id, key, seen, true)
}
fn decode_chat_message_owned_projection(
    raw: Value, id: &str, key: &[u8; 32],
    seen: &mut std::collections::HashSet<String>, thinking: bool,
) -> Result<(Value, Message)> {
    if raw
        .get("chat_id")
        .and_then(Value::as_str)
        .is_some_and(|c| c != id)
    {
        return Err(Error::Forbidden);
    }
    let message_id = ["client_message_id", "message_id", "id"]
        .into_iter()
        .map(|field| text(&raw, field))
        .find(|id| !id.is_empty())
        .ok_or(Error::Protocol)?;
    if !seen.insert(message_id.to_owned()) {
        return Err(Error::Protocol);
    }
    let mut message = Plain::new(Message {
        id: message_id.to_owned(),
        role: required(&raw, "role")?.to_owned(),
        ..Message::default()
    });
    if thinking {
        message.content=decrypt_optional(&raw,"encrypted_content",key)?;
        message.sender=decrypt_optional(&raw,"encrypted_sender_name",key)?;
        message.thinking=decrypt_optional(&raw,"encrypted_thinking_content",key)?;
    } else {
        message.content=saved_chat_read::metadata::projection_message_text(&raw,"encrypted_content",key)?.unwrap_or_default();

    }
    Ok((raw, message.into_inner()))
}

pub(super) fn restore_chat_tokens_from_rows(
    chat: &mut Chat,
    key: &[u8; 32],
    rows: &[Value],
) -> Result<()> {
    let mut mappings = Plain::new(Vec::<Value>::new());
    for row in rows {
        let value = zeroize::Zeroizing::new(decrypt_optional(row, "encrypted_pii_mappings", key)?);
        if !value.is_empty() {
            mappings.extend(serde_json::from_str::<Vec<Value>>(&value)?);
        }
    }
    for message in &mut chat.messages {
        let restored = crate::privacy::restore(&message.content, &mappings)?;
        replace_text(&mut message.content, restored);
        let restored = crate::privacy::restore(&message.thinking, &mappings)?;
        replace_text(&mut message.thinking, restored);
    }
    Ok(())
}

#[path = "sync_read_freshness.rs"]
pub(super) mod read_freshness;

#[cfg(test)]
mod inventory_phase_tests {
    use super::ChatSyncPolicy;
    // contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,sdk.encryption.local-only
    #[test]
    fn metadata_discovery_is_only_for_headless_personal_empty_sidecar_cache() {
        assert_eq!(ChatSyncPolicy::InventoryDiscovery.requested_phase(true, true, false), "phase2");
        for (headless, personal, cached) in [(false, true, false), (true, false, false), (true, true, true)] {
            assert_eq!(ChatSyncPolicy::InventoryDiscovery.requested_phase(headless, personal, cached), "all");
        }
        for policy in [ChatSyncPolicy::Ordinary, ChatSyncPolicy::MonitorReadOnly] {
            assert_eq!(policy.requested_phase(true, true, false), "all");
        }
    }
}
