//! Bounded immutable cached transcript views for responsive platform rendering.
//! Staging owns no network effect and creates no auth/cache/durability receipt.
//! Plaintext is decoded only by shared Rust under an authenticated SDK owner.
//! The independent reader retains no Session, master key or wrapping key.
//! Queued views retain the actual owner epoch, expiry and known denial fences.
//! A platform must close its reader before changing profile/API/key context.
//! Cached windows never reconcile pending sends or replace canonical recovery.
//! Team/Direct and unavailable caches retain their normal canonical reader.
use super::{ChatMonitor, ChatMonitorAccessDenial, MonitorFence};
use crate::client::plaintext::{Plain,replace_text};
use crate::{
    client::{
        Client,
        sync::{decode_chat_message, decrypt_optional},
    },
    error::{Error, Result},
    model::Chat,
};
use serde::Serialize;
use serde_json::Value;
use std::{
    collections::{BTreeMap, HashSet},
    io::Write,
    sync::{Arc, Mutex},
};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroize;

#[path = "cache_settlement.rs"]
mod settlement;
pub use settlement::{CacheSettlementCandidate, CacheSettlementPublication};
#[path = "chat_first_page.rs"]
mod first_page;
pub use first_page::{ChatFirstPageCandidate, ChatFirstPagePublication, ChatFirstPageSink};
pub(in crate::client) use first_page::FirstPageRead;
#[path = "cached_view_open.rs"]
mod open;
pub use open::ChatOwnerLease;

const MAX_CACHED_CHATS: usize = 20;
const MAX_CACHED_MESSAGES: usize = 30;
const MAX_WINDOW_BYTES: usize = 256 * 1024;
const MAX_READER_BYTES: usize = 4 * 1024 * 1024;

/// Presentation data only. Unknown older history is never reported complete.
#[derive(Clone)]
pub struct CachedChatWindow {
    pub chat: Chat,
    pub has_more_before: Option<bool>,
    pub history_complete: bool,
    pub cached: bool,
    pub refreshing: bool,
    pub pii_restoration: &'static str,
}
// Retained cached plaintext is wiped when a reader closes, including queued
// publications sharing the same window. UI-owned accepted models keep their
// existing presentation lifecycle; no credentials ever enter this container.
struct CachedWindowData {
    window: Mutex<Option<CachedChatWindow>>,
}
impl Zeroize for CachedChatWindow {
    fn zeroize(&mut self) {
        wipe_chat(&mut self.chat);
    }
}
impl CachedWindowData {
    fn clear(&self) {
        let mut slot = self
            .window
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(mut window) = slot.take() {
            window.zeroize();
        }
    }
}
impl Drop for CachedWindowData {
    fn drop(&mut self) {
        self.clear();
    }
}
// A disconnected socket does not revoke previously owned cached data. Actual
// owner/key/context cancellation, absolute expiry and recorded access denial do.
// This is cached-display provenance, never an authenticated network permission.
struct CachedOwnerFence {
    owner: Arc<crate::client::project_task_watch::WatchAuthority>,
    generation: u64,
    team: Option<String>,
    expires_at: Option<u64>,
    monitor: Option<Arc<MonitorFence>>,
}
fn cached_owner_valid(fence: &CachedOwnerFence) -> bool {
    !fence.owner.cancel.is_cancelled()
        && fence
            .expires_at
            .is_none_or(|at| at > crate::client::now_ms())
        && fence
            .monitor
            .as_ref()
            .is_none_or(|monitor| monitor.denial.lock().is_ok_and(|denial| denial.is_none()))
}
/// Preserve the existing open_chat fallback contract while letting a platform
/// distinguish genuine canonical completion from read-only offline cache data.
pub enum ChatViewRead {
    Canonical(CanonicalChatCandidate),
    /// Online authorized cached content; never a complete-history receipt.
    CacheSettled(CacheSettlementCandidate),
    CachedOffline(CachedChatPublication),
}
/// Immutable independent read lane; no credentials, keys or effect admission.
/// It remains cached data while the main Client performs canonical operations.
pub struct CachedChatViews {
    denial_revision: u64,
    fence: Arc<CachedOwnerFence>,
    lifetime: CancellationToken,
    windows: BTreeMap<String, Arc<CachedWindowData>>,
}
/// A queued bounded window stays sealed until its true lifecycle is checked.
pub struct CachedChatPublication {
    denial_revision: u64,
    fence: Arc<CachedOwnerFence>,
    lifetime: CancellationToken,
    request: CancellationToken,
    window: Arc<CachedWindowData>,
    id: String,
}
impl CachedChatViews {
    /// Negative owner/context observer only: no authentication, freshness,
    /// model publication or effect grant. Closing a cache reader cannot extend
    /// this captured owner epoch, expiry or retained negative-history revision.
    pub fn is_owner_current(&self) -> bool {
        cached_owner_valid(&self.fence)
            && self
                .fence
                .owner
                .cached_denial_revision()
                .is_ok_and(|revision| revision == self.denial_revision)
    }
    pub fn is_valid(&self) -> bool {
        self.is_owner_current() && !self.lifetime.is_cancelled()
    }
    /// Local cached display only. No mutation, credential ACK or fresh receipt.
    pub fn publish(
        &self,
        id: &str,
        request: CancellationToken,
    ) -> Result<Option<CachedChatPublication>> {
        if !self.is_valid() || request.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let parsed =
            uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        if parsed.hyphenated().to_string() != id {
            return Err(Error::Invalid("A canonical full chat ID is required."));
        }
        let Some(window) = self.windows.get(id) else {
            return Ok(None);
        };
        let publication = CachedChatPublication {
            denial_revision: self.denial_revision,
            fence: self.fence.clone(),
            lifetime: self.lifetime.clone(),
            request,
            window: window.clone(),
            id: id.to_owned(),
        };
        if !publication.is_valid() {
            return Err(Error::Cancelled);
        }
        Ok(Some(publication))
    }
    pub fn close(&self) {
        self.lifetime.cancel();
        for window in self.windows.values() {
            window.clear();
        }
    }
}
impl Drop for CachedChatViews {
    fn drop(&mut self) {
        self.close();
    }
}
impl CachedChatPublication {
    pub fn is_valid(&self) -> bool {
        cached_owner_valid(&self.fence)
            && self
                .fence
                .owner
                .cached_denial_revision()
                .is_ok_and(|revision| revision == self.denial_revision)
            && self.fence.owner.cached_chat_allowed(&self.id)
            && !self.lifetime.is_cancelled()
            && !self.request.is_cancelled()
    }
    /// Serialize by borrowing the original guarded cache, without cloning its
    /// plaintext. The callback keeps output zeroizing and must not reenter this
    /// reader's window lock. Late denial/cancel is rechecked after encoding.
    pub fn with_window<T>(&self, render: impl FnOnce(&CachedChatWindow) -> Result<T>) -> Result<T> {
        if !self.is_valid() { return Err(Error::Cancelled); }
        let slot = self.window.window.lock().map_err(|_| Error::Cancelled)?;
        let output = render(slot.as_ref().ok_or(Error::Cancelled)?)?;
        if !self.is_valid() { return Err(Error::Cancelled); }
        Ok(output)
    }
    pub fn into_window(self) -> Result<CachedChatWindow> {
        if !self.is_valid() {
            return Err(Error::Cancelled);
        }
        let mut window = self
            .window
            .window
            .lock()
            .map_err(|_| Error::Cancelled)?
            .as_ref()
            .ok_or(Error::Cancelled)?
            .clone();
        if !self.is_valid() {
            window.zeroize();
            return Err(Error::Cancelled);
        }
        Ok(window)
    }
}

/// Actual canonical read, sealed until the exact credentials/cache save commits.
/// No Clone/Debug/serde or plaintext getter; it cannot be fabricated by adapters.
pub struct CanonicalChatCandidate {
    fence: Arc<CachedOwnerFence>,
    request: CancellationToken,
    operation: CancellationToken,
    parent: CancellationToken,
    epoch: u64,
    binding: [u8; 32],
    revision: u64,
    ciphertext: Value,
    chat: Option<Chat>,
    id: String,
    denial_revision: u64,
}
/// A committed canonical result remains sealed through bounded reply queues.
pub struct CanonicalChatPublication {
    fence: Arc<CachedOwnerFence>,
    request: CancellationToken,
    chat: Option<Chat>,
    id: String,
    denial_revision: u64,
}
pub(in crate::client) fn wipe_chat(chat: &mut Chat) {
    chat.id.zeroize();
    chat.title.zeroize();
    chat.category.zeroize();
    for message in &mut chat.messages {
        message.id.zeroize();
        message.role.zeroize();
        message.content.zeroize();
        message.sender.zeroize();
        message.thinking.zeroize();
        for item in &mut message.embeds {
            item.id.zeroize();
            item.title.zeroize();
            item.description.zeroize();
            item.status.zeroize();
            item.category.zeroize();
            crate::model::zeroize_json(&mut item.fields);
        }
        message.embeds.clear();
    }
}
impl Drop for CanonicalChatCandidate {
    fn drop(&mut self) {
        self.binding.zeroize();
        if let Some(chat) = &mut self.chat {
            wipe_chat(chat);
        }
    }
}
impl Drop for CanonicalChatPublication {
    fn drop(&mut self) {
        if let Some(chat) = &mut self.chat {
            wipe_chat(chat);
        }
    }
}
impl CanonicalChatCandidate {
    pub fn ciphertext_sha256(&self) -> Result<String> {
        if !cached_owner_valid(&self.fence)
            || self.request.is_cancelled()
            || self.operation.is_cancelled()
            || self.fence.owner.cached_denial_revision()? != self.denial_revision
        {
            return Err(Error::Cancelled);
        }
        Ok(crate::client::sha256(&serde_json::to_string(
            &self.ciphertext,
        )?))
    }
    pub fn credential_revision(&self) -> u64 {
        self.revision
    }
}
impl CanonicalChatPublication {
    pub fn is_valid(&self) -> bool {
        cached_owner_valid(&self.fence)
            && !self.request.is_cancelled()
            && self.fence.owner.cached_chat_allowed(&self.id)
            && self
                .fence
                .owner
                .cached_denial_revision()
                .is_ok_and(|revision| revision == self.denial_revision)
    }
    /// Borrow only this committed model; serialized private output stays in a
    /// zeroizing owner until the original request/owner/denial fence rechecks.
    pub fn with_chat<T>(&self, render: impl FnOnce(&Chat) -> Result<T>) -> Result<T> {
        if !self.is_valid() { return Err(Error::Cancelled); }
        let output = render(self.chat.as_ref().ok_or(Error::Cancelled)?)?;
        if !self.is_valid() { return Err(Error::Cancelled); }
        Ok(output)
    }
    pub fn into_chat(mut self) -> Result<Chat> {
        if !self.is_valid() {
            return Err(Error::Cancelled);
        }
        self.chat.take().ok_or(Error::Cancelled)
    }
}
impl Client {
    pub fn validate_chat_view(&self, candidate: &CanonicalChatCandidate) -> Result<()> {
        self.check_cached_view_owner(&candidate.fence)?;
        if candidate.request.is_cancelled()
            || candidate.operation.is_cancelled()
            || self.operation_cancel != candidate.operation
            || self.operation_parent != candidate.parent
            || self.fresh_auth.operation_epoch() != candidate.epoch
            || self.fresh_auth_binding()? != candidate.binding
            || self.credential_revision != candidate.revision
            || self.ciphertext_snapshot() != candidate.ciphertext
            || candidate.fence.owner.cached_denial_revision()? != candidate.denial_revision
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    /// The platform attests only its existing exact durable save. The actual SDK
    /// read, current owner/request and credential ACK are independently checked.
    pub fn commit_chat_view(
        &self,
        mut candidate: CanonicalChatCandidate,
        receipt: super::ChatRefreshDurableReceipt,
    ) -> Result<CanonicalChatPublication> {
        self.validate_chat_view(&candidate)?;
        if self.credential_ack != candidate.revision
            || receipt.credential_revision != candidate.revision
            || receipt.ciphertext_sha256 != candidate.ciphertext_sha256()?
        {
            return Err(Error::Cancelled);
        }
        candidate.fence.owner.commit_cached_chat_recovery(
            &candidate.id,
            candidate.fence.team.is_some(),
            candidate.denial_revision,
        )?;
        let publication = CanonicalChatPublication {
            fence: candidate.fence.clone(),
            request: candidate.request.clone(),
            chat: candidate.chat.take(),
            id: candidate.id.clone(),
            denial_revision: candidate.denial_revision,
        };
        if !publication.is_valid() {
            return Err(Error::Cancelled);
        }
        Ok(publication)
    }
}

// Bound input and output before retaining another model. Counting serialization
// borrows data and never allocates an unbounded intermediate JSON buffer.
struct BoundedBytes {
    used: usize,
    limit: usize,
}
impl Write for BoundedBytes {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > self.limit.saturating_sub(self.used) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                "cached view bound",
            ));
        }
        self.used += bytes.len();
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
pub(in crate::client) fn bounded_bytes(value: &impl Serialize, limit: usize) -> Option<usize> {
    let mut counter = BoundedBytes { used: 0, limit };
    serde_json::to_writer(&mut counter, value).ok()?;
    Some(counter.used)
}
impl Client {
    fn check_cached_view_owner(&self, fence: &CachedOwnerFence) -> Result<()> {
        self.require_session()?;
        if !cached_owner_valid(fence)
            || self.operation_cancel.is_cancelled()
            || !Arc::ptr_eq(&self.task_watch_authority, &fence.owner)
            || self.generation != fence.generation
            || self.team()? != fence.team.as_deref()
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    fn cached_view_owner(&self, monitor: Option<&ChatMonitor>) -> Result<Arc<CachedOwnerFence>> {
        let session = self.require_session()?;
        // Only a principal adopted by actual SDK authentication can establish
        // cached ownership. Raw Session/cache restoration never fills this ID.
        let owner = self.user["id"]
            .as_str()
            .filter(|id| !id.is_empty())
            .or_else(|| self.user["user_id"].as_str().filter(|id| !id.is_empty()))
            .ok_or(Error::Authentication)?;
        if self.task_watch_owner.as_deref() != Some(owner) {
            return Err(Error::Authentication);
        }
        let mut expires_at = session.paired_session_expires_at;
        if let Some(monitor) = monitor {
            if !Arc::ptr_eq(&self.task_watch_authority, &monitor.fence.owner)
                || self.generation != monitor.fence.generation
                || self.team()? != monitor.fence.team.as_deref()
            {
                return Err(Error::Cancelled);
            }
            if let Some(captured) = monitor.fence.expires_at {
                expires_at = Some(expires_at.map_or(captured, |current| current.min(captured)));
            }
        }
        let fence = Arc::new(CachedOwnerFence {
            owner: self.task_watch_authority.clone(),
            generation: self.generation,
            team: session.active_team_id.clone(),
            expires_at,
            monitor: monitor.map(|monitor| monitor.fence.clone()),
        });
        self.check_cached_view_owner(&fence)?;
        Ok(fence)
    }
    /// Same single canonical read and Offline fallback as open_chat, with an
    /// explicit source tag. A cached fallback never clears mutation uncertainty.
    /// The platform still persists exact credentials before publishing either
    /// result; this method performs no ACK, cache write or inference operation.
    pub async fn read_chat_view(
        &mut self,
        monitor: Option<&ChatMonitor>,
        id: &str,
        request: CancellationToken,
    ) -> Result<ChatViewRead> {
        self.read_chat_view_policy(monitor, id, request, false, None).await
    }
    /// Match the interactive cache-preferred contract: all owned cached rows,
    /// strict history only for an empty/unusable cache. No export authority.
    pub async fn read_chat_view_prefer_cache(
        &mut self, monitor: Option<&ChatMonitor>, id: &str, request: CancellationToken,
    ) -> Result<ChatViewRead> {
        self.read_chat_view_policy(monitor, id, request, true, None).await
    }
    /// Interactive cold-cache preview only. The sink must explicitly admit the
    /// total prospective checkpoint against its real adapter capacity BEFORE
    /// retention; unknown/refused capacity skips only this optional preview.
    /// An accepted sink must durably persist and
    /// ACK the exact ciphertext before committing its sealed first-page view.
    /// Warm cache/default readers and the final strict result stay unchanged.
    /// SDK-required partial: foreign continuation/receipt adapters must be added
    /// before this opt-in capability is release-complete across supported SDKs.
    pub async fn read_chat_view_prefer_cache_with_first_page(
        &mut self, monitor: Option<&ChatMonitor>, id: &str, request: CancellationToken,
        sink: &mut dyn ChatFirstPageSink,
    ) -> Result<ChatViewRead> {
        self.read_chat_view_policy(monitor, id, request, true, Some(sink)).await
    }
    async fn read_chat_view_policy(
        &mut self, monitor: Option<&ChatMonitor>, id: &str, request: CancellationToken,
        prefer_cache: bool, sink: Option<&mut dyn ChatFirstPageSink>,
    ) -> Result<ChatViewRead> {
        let fence = self.cached_view_owner(monitor)?;
        self.verify_private_operation()?;
        if request.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let denial_revision = fence.owner.cached_denial_revision()?;
        let mut first_page = sink.map(|sink| FirstPageRead::new(
            sink, fence.clone(), request.clone(), denial_revision,
        ));
        let result = if prefer_cache {
            match self.open_chat_cache_preferred(id, false).await {
                Ok(Some(chat)) => Ok((chat, true)),
                Ok(None) => self.open_chat_live_with_first_page(id, first_page.as_mut()).await.map(|chat| (chat, false)),
                Err(error) => Err(error),
            }
        } else { self.open_chat_live(id).await.map(|chat| (chat, false)) };
        match result {
            Ok((chat, from_cache)) => {
                let chat=Plain::new(chat);
                self.check_cached_view_owner(&fence)?;
                if request.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                if fence.owner.cached_denial_revision()? != denial_revision {
                    return Err(Error::Cancelled);
                }
                if from_cache {
                    return Ok(ChatViewRead::CacheSettled(self.capture_cache_settlement(
                        fence, request, id, denial_revision, chat.into_inner(),
                    )?));
                }
                Ok(ChatViewRead::Canonical(CanonicalChatCandidate {
                    fence,
                    request,
                    operation: self.operation_cancel.clone(),
                    parent: self.operation_parent.clone(),
                    epoch: self.fresh_auth.operation_epoch(),
                    binding: self.fresh_auth_binding()?,
                    revision: self.credential_revision,
                    ciphertext: self.ciphertext_snapshot(),
                    chat: Some(chat.into_inner()),
                    id: id.to_owned(),
                    denial_revision,
                }))
            }
            Err(Error::Offline) if self.history.contains_key(id) || self.sync_message_windows.contains_key(id) => {
                self.check_cached_view_owner(&fence)?;
                if request.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                let row = self.chats.get(id).ok_or(Error::Offline)?;
                let wrapping = self.cached_wrapping_key()?;
                let (mut window, _) = self.decode_cached_window(row, &wrapping)?;
                window.refreshing = false;
                let publication = CachedChatPublication {
                    denial_revision,
                    fence: fence.clone(),
                    id: id.to_owned(),
                    lifetime: CancellationToken::new(),
                    request,
                    window: Arc::new(CachedWindowData {
                        window: Mutex::new(Some(window)),
                    }),
                };
                if !publication.is_valid() {
                    return Err(Error::Cancelled);
                }
                Ok(ChatViewRead::CachedOffline(publication))
            }
            Err(error @ (Error::Expired | Error::Authentication | Error::Forbidden)) => {
                if matches!(error, Error::Expired | Error::Authentication) || fence.team.is_some() {
                    self.selected_first_pages.clear();
                } else { self.selected_first_pages.remove(id); }
                let denial = if matches!(error, Error::Expired | Error::Authentication) {
                    ChatMonitorAccessDenial::Expired
                } else if fence.team.is_some() {
                    ChatMonitorAccessDenial::ScopeRevoked
                } else {
                    ChatMonitorAccessDenial::ChatUnavailable {
                        chat_id: id.to_owned(),
                    }
                };
                if matches!(error, Error::Expired | Error::Authentication) {
                    self.task_watch_authority.cancel.cancel();
                }
                match &denial {
                    ChatMonitorAccessDenial::Expired => fence.owner.cancel.cancel(),
                    ChatMonitorAccessDenial::ScopeRevoked => fence.owner.deny_cached_chat(None)?,
                    ChatMonitorAccessDenial::ChatUnavailable { chat_id } => {
                        fence.owner.deny_cached_chat(Some(chat_id))?
                    }
                }
                if let Some(monitor) = monitor {
                    monitor.deny(denial)?;
                }
                Err(error)
            }
            Err(error) => Err(error),
        }
    }
    /// Stage only already-owned encrypted cache data after platform admission.
    /// Caller must cancel lifetime before changing profile/API/key context. The
    /// actual SDK monitor independently rejects owner reset, expiry and denial.
    /// This operation performs no request, cache mutation or receipt promotion.
    pub fn stage_cached_chat_views(
        &self,
        monitor: Option<&ChatMonitor>,
        lifetime: CancellationToken,
    ) -> Result<CachedChatViews> {
        let fence = self.cached_view_owner(monitor)?;
        self.verify_private_operation()?;
        // Dropping this reader may close only its own child, never the caller's
        // broader lifetime or a foreground send/recovery operation.
        let lifetime = lifetime.child_token();
        if lifetime.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // Require the caller's existing exact credential durability admission;
        // staging never acknowledges a revision or writes any persisted grant.
        if self.credential_ack != self.credential_revision {
            return Err(Error::Cancelled);
        }
        let denial_revision = fence.owner.cached_denial_revision()?;
        let mut windows = BTreeMap::new();
        let mut retained = 0usize;
        if self.supports_cached_default_chat_list() {
            let wrapping = self.cached_wrapping_key()?;
            // The server's bounded initial parent/pin selection is the first
            // cached-display budget, rather than unrelated older full caches.
            let mut ranked=self.sync_message_windows.iter().filter_map(|(id,window)|
                window.source_rank.map(|rank|(rank,id))).collect::<Vec<_>>();
            ranked.sort();
            let mut rows=Vec::new();let mut selected=std::collections::BTreeSet::new();
            for (_,id) in ranked {if let Some(row)=self.chats.get(id){rows.push(row);selected.insert(id.as_str());}}
            for row in self.chat_rows_by_recency(){
                if row.get("id").and_then(Value::as_str).is_none_or(|id|!selected.contains(id)){rows.push(row);}
            }
            for row in rows {
                if windows.len() >= MAX_CACHED_CHATS {
                    break;
                }
                self.check_cached_view_owner(&fence)?;
                if lifetime.is_cancelled() {
                    return Err(Error::Cancelled);
                }
                let Some(id) = row["id"].as_str() else {
                    continue;
                };
                if !fence.owner.cached_chat_allowed(id) {
                    continue;
                }
                let Ok((window, bytes)) = self.decode_cached_window(row, &wrapping) else {
                    continue;
                };
                let window=Plain::new(window);
                if bytes > MAX_READER_BYTES.saturating_sub(retained) {
                    break;
                }
                retained += bytes;
                windows.insert(
                    window.chat.id.clone(),
                    Arc::new(CachedWindowData {
                        window: Mutex::new(Some(window.into_inner())),
                    }),
                );
            }
        }
        self.check_cached_view_owner(&fence)?;
        if lifetime.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if fence.owner.cached_denial_revision()? != denial_revision {
            return Err(Error::Cancelled);
        }
        Ok(CachedChatViews {
            denial_revision,
            fence,
            lifetime,
            windows,
        })
    }
    fn decode_cached_window(
        &self,
        row: &Value,
        wrapping: &[u8; 32],
    ) -> Result<(CachedChatWindow, usize)> {
        let id = row
            .get("id")
            .and_then(Value::as_str)
            .ok_or(Error::Protocol)?;
        let parsed = uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
        if parsed.hyphenated().to_string() != id {
            return Err(Error::Protocol);
        }
        // Reuse the existing keyless Personal draft display rule only for an
        // actually empty draft shell. No message key ever aliases the master.
        if self.team()?.is_none() && self.cached_draft_shell(id)? {
            bounded_bytes(row, MAX_WINDOW_BYTES).ok_or(Error::Protocol)?;
            let mut item=Plain::new(self.chat_item(row,wrapping)?);
            let chat=Plain::new(Chat {
                id: id.into(),
                title:std::mem::take(&mut item.title),
                category:std::mem::take(&mut item.category),
                messages:vec![],
            });
            let bytes=bounded_bytes(&*chat,MAX_WINDOW_BYTES).ok_or(Error::Protocol)?;
            return Ok((
                CachedChatWindow {
                    chat:chat.into_inner(),
                    has_more_before: None,
                    history_complete: false,
                    cached: true,
                    refreshing: true,
                    pii_restoration: "page_local",
                },
                bytes,
            ));
        }
        let synced = self.synced_window(row)?;
        let (rows,has_more_before) = if let Some(window)=synced {
            if window.messages.iter().any(|row|row.get("large_payload").is_some()
                && row.get("encrypted_content").is_none_or(Value::is_null)) {
                // Keep the encrypted reference and all other received rows in
                // storage; do not paint an invented blank exact-body message.
                return Err(Error::Offline);
            }
            (window.messages.as_slice(),Some(window.has_more_before))
        } else {
            let history=self.history.get(id).ok_or(Error::Offline)?;
            let start=history.len().saturating_sub(MAX_CACHED_MESSAGES);
            (&history[start..],(start>0).then_some(true))
        };
        let metadata_bytes = bounded_bytes(row, MAX_WINDOW_BYTES).ok_or(Error::Protocol)?;
        if synced.is_some() {
            // The server page budget covers encrypted message payload, not its
            // separate metadata header. Canonical ID projection adds only the
            // bounded addressing overhead shared with the ingress validator.
            bounded_bytes(&rows,crate::client::sync_windows::MAX_NORMALIZED_BYTES).ok_or(Error::Protocol)?;
        } else {
            bounded_bytes(&rows, MAX_WINDOW_BYTES.saturating_sub(metadata_bytes)).ok_or(Error::Protocol)?;
        }
        let key = self.chat_key(row, wrapping)?;
        let mut item=Plain::new(self.chat_item(row,&key)?);
        let mut seen = HashSet::new();
        let mut messages=Plain::new(Vec::<crate::model::Message>::new());
        let mut mappings=Plain::new(Vec::<Value>::new());
        for row in rows {
            let (raw,message)=decode_chat_message(row,id,&key,&mut seen)?;
            let message=Plain::new(message);
            if message.role == "user" {
                let mapping=zeroize::Zeroizing::new(decrypt_optional(&raw,"encrypted_pii_mappings",&key)?);
                if !mapping.is_empty() {
                    mappings.extend(serde_json::from_str::<Vec<Value>>(&mapping)?);
                }
            }
            mappings.extend(crate::client::memory_privacy::response_mappings(&message)?);
            messages.push(message.into_inner());
        }
        // Same explicit page-local policy as bounded saved reads: mappings from
        // loaded user rows only; unknown/unloaded tokens remain literal.
        let mut output_bytes = 0usize;
        for message in messages.iter_mut() {
            let restored=crate::privacy::restore_page(&message.content,&mappings)?;replace_text(&mut message.content,restored);
            let restored=crate::privacy::restore_page(&message.thinking,&mappings)?;replace_text(&mut message.thinking,restored);
            output_bytes = output_bytes
                .checked_add(message.content.len())
                .and_then(|n| n.checked_add(message.thinking.len()))
                .ok_or(Error::Protocol)?;
            if output_bytes > MAX_WINDOW_BYTES {
                return Err(Error::Protocol);
            }
        }
        let chat=Plain::new(Chat {
            id: id.into(),
            title:std::mem::take(&mut item.title),
            category:std::mem::take(&mut item.category),
            messages:messages.into_inner(),
        });
        let bytes=bounded_bytes(&*chat,MAX_WINDOW_BYTES).ok_or(Error::Protocol)?;
        Ok((
            CachedChatWindow {
                chat:chat.into_inner(),
                has_more_before,
                history_complete: false,
                cached: true,
                refreshing: true,
                pii_restoration: "page_local",
            },
            bytes,
        ))
    }
}

#[cfg(test)]
#[path = "cached_view_tests.rs"]
mod tests;
