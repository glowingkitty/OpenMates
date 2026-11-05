//! Online selected-chat cache settlement. This is a restrictive read proof,
//! never canonical history, recovery admission, a mutation or export receipt.
//! The immediate bounded preview stays independent and read-only.
use super::*;
use crate::client::{sync_capability::AsyncCryptoScope, ChatRefreshDurableReceipt};
use crate::client::{text, segment};
use reqwest::Method;

pub struct CacheSettlementCandidate {
    fence: Arc<CachedOwnerFence>,
    request: CancellationToken,
    operation: CancellationToken,
    parent: CancellationToken,
    scope: AsyncCryptoScope,
    epoch: u64,
    binding: [u8; 32],
    revision: u64,
    ciphertext: Value,
    chat: Option<Chat>,
    id: String,
    denial_revision: u64,
}
pub struct CacheSettlementPublication {
    fence: Arc<CachedOwnerFence>,
    request: CancellationToken,
    operation: CancellationToken,
    parent: CancellationToken,
    scope: AsyncCryptoScope,
    private_gate: Option<Arc<dyn Fn() -> Result<()> + Send + Sync>>,
    revision: u64,
    ciphertext: Value,
    window: Option<CachedChatWindow>,
    id: String,
    denial_revision: u64,
}
impl Drop for CacheSettlementCandidate {
    fn drop(&mut self) {
        self.binding.zeroize();
        if let Some(chat) = &mut self.chat { wipe_chat(chat); }
    }
}
impl Drop for CacheSettlementPublication {
    fn drop(&mut self) {
        if let Some(window) = &mut self.window { window.zeroize(); }
    }
}
impl CacheSettlementCandidate {
    pub fn credential_revision(&self) -> u64 { self.revision }
    pub fn ciphertext_sha256(&self) -> Result<String> {
        if !cached_owner_valid(&self.fence) || self.request.is_cancelled()
            || self.operation.is_cancelled() || self.parent.is_cancelled()
            || self.fence.owner.cached_denial_revision()? != self.denial_revision {
            return Err(Error::Cancelled);
        }
        Ok(crate::client::sha256(&serde_json::to_string(&self.ciphertext)?))
    }
}
impl CacheSettlementPublication {
    pub fn is_valid(&self) -> bool {
        cached_owner_valid(&self.fence)
            && self.scope.ensure_resource_current().is_ok()
            && self.fence.monitor.as_ref().is_none_or(|monitor| monitor.valid())
            && self.private_gate.as_ref().is_none_or(|gate| gate().is_ok())
            && !self.request.is_cancelled()
            && !self.operation.is_cancelled() && !self.parent.is_cancelled()
            && self.fence.owner.cached_chat_allowed(&self.id)
            && self.fence.owner.cached_denial_revision()
                .is_ok_and(|revision| revision == self.denial_revision)
    }
    /// Borrow the original sealed model while encoding. Keep private output in
    /// a zeroizing owner inside the callback: late rejection drops that owner.
    /// The original selected-chat denial/resource fence is checked AFTER render.
    pub fn with_window<T>(&self, render: impl FnOnce(&CachedChatWindow) -> Result<T>) -> Result<T> {
        if !self.is_valid() { return Err(Error::Cancelled); }
        let output = render(self.window.as_ref().ok_or(Error::Cancelled)?)?;
        if !self.is_valid() { return Err(Error::Cancelled); }
        Ok(output)
    }
    pub fn into_window(mut self) -> Result<CachedChatWindow> {
        if !self.is_valid() { return Err(Error::Cancelled); }
        let mut window = self.window.take().ok_or(Error::Cancelled)?;
        if !self.is_valid() { window.zeroize(); return Err(Error::Cancelled); }
        Ok(window)
    }
}
impl Client {
    pub(super) fn capture_cache_settlement(
        &self, fence: Arc<CachedOwnerFence>, request: CancellationToken,
        id: &str, denial_revision: u64, chat: Chat,
    ) -> Result<CacheSettlementCandidate> {
        let chat = Plain::new(chat);
        let candidate = CacheSettlementCandidate {
            fence, request, operation: self.operation_cancel.clone(),
            parent: self.operation_parent.clone(), scope: AsyncCryptoScope::begin(self)?,
            epoch: self.fresh_auth.operation_epoch(), binding: self.fresh_auth_binding()?,
            revision: self.credential_revision, ciphertext: self.ciphertext_snapshot(),
            chat: Some(chat.into_inner()), id: id.to_owned(), denial_revision,
        };
        self.validate_cache_settlement(&candidate)?;
        Ok(candidate)
    }
    pub fn validate_cache_settlement(&self, candidate: &CacheSettlementCandidate) -> Result<()> {
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        self.check_cached_view_owner(&candidate.fence)?;
        candidate.scope.check_chat(self, &candidate.id)?;
        if candidate.request.is_cancelled() || candidate.operation.is_cancelled()
            || candidate.parent.is_cancelled() || self.operation_cancel != candidate.operation
            || self.operation_parent != candidate.parent
            || self.fresh_auth.operation_epoch() != candidate.epoch
            || self.fresh_auth_binding()? != candidate.binding
            || self.credential_revision != candidate.revision
            || self.ciphertext_snapshot() != candidate.ciphertext
            || candidate.fence.owner.cached_denial_revision()? != candidate.denial_revision
            || !candidate.fence.owner.cached_chat_allowed(&candidate.id)
            || candidate.fence.monitor.as_ref().is_some_and(|monitor| !monitor.valid()) {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    pub fn commit_cache_settlement(
        &self, mut candidate: CacheSettlementCandidate, receipt: ChatRefreshDurableReceipt,
    ) -> Result<CacheSettlementPublication> {
        self.validate_cache_settlement(&candidate)?;
        if self.credential_ack != candidate.revision
            || receipt.credential_revision != candidate.revision
            || receipt.ciphertext_sha256 != candidate.ciphertext_sha256()? {
            return Err(Error::Cancelled);
        }
        // Deliberately no commit_cached_chat_recovery or freshness promotion.
        let publication = CacheSettlementPublication {
            fence: candidate.fence.clone(), request: candidate.request.clone(),
            operation: candidate.operation.clone(), parent: candidate.parent.clone(),
            scope: AsyncCryptoScope::begin(self)?,
            private_gate: self.options.private_operation_gate.clone(),
            revision: candidate.revision, ciphertext: std::mem::take(&mut candidate.ciphertext),
            window: candidate.chat.take().map(|chat| CachedChatWindow {
                chat, has_more_before: None,
                // A metadata count match remains a cache heuristic only.
                history_complete: false, cached: true, refreshing: false,
                pii_restoration: "all_cached_user_rows",
            }), id: candidate.id.clone(),
            denial_revision: candidate.denial_revision,
        };
        if !publication.is_valid() { return Err(Error::Cancelled); }
        Ok(publication)
    }
    /// Foreign adapters check again under their existing Client lock immediately
    /// before encoding a delayed publication. This only restricts a saved read.
    pub fn validate_cache_settlement_publication(&self, publication: &CacheSettlementPublication) -> Result<()> {
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        self.check_cached_view_owner(&publication.fence)?;
        publication.scope.check_chat(self, &publication.id)?;
        if !publication.is_valid() || self.credential_revision != publication.revision
            || self.credential_ack != publication.revision
            || self.ciphertext_snapshot() != publication.ciphertext {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    /// Fresh exact-ID authorization followed by ALL available owned cache rows.
    /// Live invalidations request only the existing latest-20 window and retain
    /// older ciphertext; strict reads and rewind confirmation remain separate.
    pub(in crate::client) async fn open_chat_cache_preferred(
        &mut self, id: &str, refresh_latest: bool,
    ) -> Result<Option<Chat>> {
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        if self.is_ephemeral_chat(id) { return Err(Error::Invalid("Volatile chat history exists only in the caller's memory.")); }
        if !self.task_watch_authority.cached_chat_allowed(id) { return Ok(None); }
        let scope = AsyncCryptoScope::begin(self)?;
        let old = self.chats.get(id).cloned();
        let Some(metadata) = self.request_chat_metadata(id).await? else { return Ok(None); };
        scope.check_chat(self, id)?;
        let row = metadata["chats"].as_array().ok_or(Error::Protocol)?.iter()
            .find(|row| text(row, "id") == id).ok_or(Error::Forbidden)?.clone();
        let count = row["messages_v"].as_u64().unwrap_or(0);
        // A rewind/rotation can invalidate cached rows. Its existing strict
        // full-history path remains authoritative and is never count-inferred.
        if old.as_ref().is_some_and(|old| old["messages_v"].as_u64().unwrap_or(0) > count
            || old["encrypted_chat_key"] != row["encrypted_chat_key"]
            || old["chat_visibility"] != row["chat_visibility"]) {
            self.selected_first_pages.remove(id);
            return Ok(None);
        }
        let mut rows = match self.owned_settlement_rows(&row) {
            Ok(rows) => rows,
            Err(Error::Offline) => return Ok(None),
            Err(error) => return Err(error),
        };
        if rows.is_empty() { return Ok(None); }
        let wrapping = self.wrapping_capability().await?;
        scope.check_chat(self, id)?;
        if text(&row, "chat_visibility") == "direct" { self.load_direct_identity().await?; }
        let key = self.chat_key_with_capability(&row, &wrapping).await?;
        scope.check_chat(self, id)?;
        if refresh_latest {
            let path = self.scoped(&format!("/v1/chats/{}/messages/window?direction=latest&limit=20&respect_compression_boundary=false", segment(id)))?;
            let page = self.request(Method::GET, &path, None).await?;
            scope.check_chat(self, id)?;
            // Admission validates the normal server page, keeps ALL older cache
            // rows encrypted, and never moves them to complete-history state.
            self.retain_settlement_page(&row, &page)?;
            rows = self.owned_settlement_rows(&row)?;
        }
        let mut seen = HashSet::new();
        let mut messages = Plain::new(Vec::<crate::model::Message>::new());
        let mut mappings = Plain::new(Vec::<Value>::new());
        for raw in &rows {
            if raw.get("large_payload").is_some() && raw.get("encrypted_content").is_none_or(Value::is_null) {
                return Ok(None);
            }
            let (raw, message) = decode_chat_message(raw, id, &key, &mut seen)?;
            let message = Plain::new(message);
            if message.role == "user" {
                let mapping = zeroize::Zeroizing::new(decrypt_optional(&raw, "encrypted_pii_mappings", &key)?);
                if !mapping.is_empty() { mappings.extend(serde_json::from_str::<Vec<Value>>(&mapping)?); }
            }
            messages.push(message.into_inner());
        }
        for message in messages.iter_mut() {
            let restored = crate::privacy::restore(&message.content, &mappings)?;
            replace_text(&mut message.content, restored);
            let restored = crate::privacy::restore(&message.thinking, &mappings)?;
            replace_text(&mut message.thinking, restored);
        }
        let mut item = Plain::new(self.chat_item(&row, &key)?);
        let chat = Plain::new(Chat { id: id.into(), title: std::mem::take(&mut item.title),
            category: std::mem::take(&mut item.category), messages: messages.into_inner() });
        scope.check_chat(self, id)?;
        self.require_canonical_read_profile()?;
        self.verify_private_operation()?;
        self.insert_chat_row(id.to_owned(), row);
        self.active_chat = Some(id.to_owned());
        Ok(Some(chat.into_inner()))
    }
}
