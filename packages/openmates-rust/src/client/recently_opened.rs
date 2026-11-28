//! Shared opened-chat recency for startup and the encrypted native cache.
//! Only an intentional, admitted open can record account activity. Startup
//! resume and text prefetch consume the ordered set without writing activity.
use super::*;
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

pub(super) const SNAPSHOT_FIELD: &str = "recently_opened_chats_v1";
/// Maximum integer revision that the JSON protocol can compare across all shells.
pub(crate) const MAX_OPENED_WIRE_VERSION: u64 = (1 << 53) - 1;

/// Choose whether the foreground or offline cohort needs a fresh latest page.
/// Each caller first proves completeness with its storage backend. With no
/// same-connection proof, an absent or changed revision always needs a read.
pub(crate) fn opened_tail_needs_read(
    force_latest: bool,
    verified_on_connection: bool,
    confirmed: Option<u64>,
    offered: Option<u64>,
) -> bool {
    force_latest || (!verified_on_connection && (confirmed.is_none() || confirmed != offered))
}

pub(crate) fn opened_wire_version(value: &Value) -> Option<u64> {
    value.as_u64().filter(|v| *v <= MAX_OPENED_WIRE_VERSION)
}

/// One shared startup deadline for waiting on response headers. A timeout
/// releases the actor before any response cookies or durable write is pending.
pub(crate) struct StartupForegroundBudget {
    deadline: Option<crate::platform::time::Instant>,
    cancel: CancellationToken,
    deferred: std::sync::atomic::AtomicBool,
}

impl StartupForegroundBudget {
    pub(crate) fn new(duration: std::time::Duration, cancel: &CancellationToken) -> Self {
        Self {
            deadline: Some(crate::platform::time::Instant::now() + duration),
            cancel: cancel.clone(),
            deferred: std::sync::atomic::AtomicBool::new(false),
        }
    }

    /// Honor operation cancellation at the safe header boundary without adding
    /// a deadline on retries, ordinary warm startup or replacement connections.
    pub(crate) fn cancellable(cancel: &CancellationToken) -> Self {
        Self {
            deadline: None,
            cancel: cancel.clone(),
            deferred: std::sync::atomic::AtomicBool::new(false),
        }
    }

    /// True only for a timeout imposed by startup, distinct from network outage.
    pub(crate) fn deferred(&self) -> bool {
        self.deferred.load(std::sync::atomic::Ordering::Relaxed)
    }

    pub(super) async fn headers<F: std::future::Future>(&self, response: F) -> Result<F::Output> {
        let wait = async {
            let Some(deadline) = self.deadline else {
                return Ok(response.await);
            };
            match crate::platform::time::timeout_at(deadline, response).await {
                Ok(value) => Ok(value),
                Err(_) => {
                    self.deferred.store(true, std::sync::atomic::Ordering::Relaxed);
                    Err(Error::Offline)
                }
            }
        };
        tokio::select! {
            biased;
            result = wait => result,
            _ = self.cancel.cancelled() => Err(Error::Cancelled),
        }
    }
}

const RETAINED: usize = 100;
const STARTUP_HISTORY: usize = 11;
const PROTECTED_RETAINED: usize = 1_000;

#[derive(Default)]
pub(super) struct RecentlyOpened {
    remote: Vec<String>,
    remote_known: bool,
    // Authenticated hints for this connection only. Disk presence is insufficient.
    pub(super) offered_versions: BTreeMap<String, u64>,
    retained: Vec<String>,
    pending: Vec<String>,
    // Exact history receipts are process-local and never restored as authority.
    history_coverage: BTreeMap<String, [u8; 32]>,
    pub(super) metadata_offset: usize,
}
fn canonical_id(id: &str) -> bool {
    uuid::Uuid::parse_str(id).is_ok_and(|uuid| uuid.hyphenated().to_string() == id)
}
fn parse_ids(value: &Value, max: usize) -> Result<Vec<String>> {
    let ids = value
        .as_array()
        .filter(|ids| ids.len() <= max)
        .ok_or(Error::Protocol)?;
    let mut seen = BTreeSet::new();
    ids.iter()
        .map(|id| {
            let id = id
                .as_str()
                .filter(|id| canonical_id(id))
                .ok_or(Error::Protocol)?;
            if !seen.insert(id) {
                return Err(Error::Protocol);
            }
            Ok(id.to_owned())
        })
        .collect()
}
/// Decode the authoritative last-opened chat followed by up to ten distinct
/// recently opened chat IDs. Array order is the server's recency order.
///
/// # Errors
/// Noncanonical, duplicated, or over-budget identifiers are protocol errors.
pub fn parse_startup_opened_chat_ids(value: &Value) -> Result<Vec<String>> {
    parse_ids(value, STARTUP_HISTORY)
}

fn put_first(ids: &mut Vec<String>, id: &str) {
    ids.retain(|existing| existing != id);
    ids.insert(0, id.to_owned());
}
impl RecentlyOpened {
    fn reconcile_server(&mut self, ids: &[String]) {
        // A fresh account result wins over an offline click from this
        // device. Replaying it now would replace actual cross-device order.
        self.remote = ids.to_vec();
        self.remote_known = true;
        self.pending.clear();
    }

    pub(super) fn restore(value: Option<&Value>) -> Self {
        let Some(value) = value else {
            return Self::default();
        };
        Self {
            remote: parse_ids(&value["remote"], STARTUP_HISTORY).unwrap_or_default(),
            remote_known: value["remote_known"] == true,
            offered_versions: BTreeMap::new(),
            retained: parse_ids(&value["retained"], PROTECTED_RETAINED).unwrap_or_default(),
            pending: parse_ids(&value["pending"], RETAINED).unwrap_or_default(),
            metadata_offset: 0,
            history_coverage: BTreeMap::new(),
        }
    }

    pub(super) fn snapshot(&self) -> Option<Value> {
        (self.remote_known || !self.remote.is_empty() || !self.retained.is_empty() || !self.pending.is_empty())
            .then(|| json!({"remote":self.remote,"remote_known":self.remote_known,"retained":self.retained,"pending":self.pending}))
    }
}

impl Client {
    pub(crate) fn modified_chat_metadata_offset(&self) -> usize {
        self.recently_opened.metadata_offset.max(100)
    }

    pub(super) fn sidebar_chat_rows(&self) -> impl Iterator<Item = &Value> {
        let limit = if self.startup_opened_policy_enabled {
            self.modified_chat_metadata_offset()
        } else {
            usize::MAX
        };
        self.chat_rows_by_recency().into_iter().take(limit)
    }

    pub(crate) fn enable_opened_startup_policy(&mut self) {
        self.startup_opened_policy_enabled = true;
    }

    pub(super) fn has_retained_startup_history(&self, id: &str) -> bool {
        self.startup_opened_policy_enabled
            && (self
                .recently_opened
                .retained
                .iter()
                .any(|entry| entry == id)
                || self.recently_opened.remote.iter().any(|entry| entry == id))
            && self.history.contains_key(id)
            && !self.is_deleted_chat(id)
    }

    fn opened_history_fingerprint(&self, id: &str) -> Option<[u8; 32]> {
        struct HistoryHasher(Sha256);
        impl std::io::Write for HistoryHasher {
            fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
                self.0.update(bytes);
                Ok(bytes.len())
            }

            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }

        let row = self.chats.get(id)?;
        let version = row["messages_v"].as_u64()?;
        let key = if text(row, "chat_visibility") == "direct" {
            required(row, "encrypted_chat_key").ok()?
        } else {
            self.chat_key_ciphertext(row, false).ok()?.ciphertext
        };
        let scope = self.sync_window_scope().ok()?;
        let mut hash = HistoryHasher(Sha256::new());
        serde_json::to_writer(
            &mut hash,
            &(
                scope,
                id,
                version,
                &row["last_edited_overall_timestamp"],
                row["chat_visibility"].as_str(),
                key,
                self.history.get(id)?,
            ),
        ).ok()?;
        Some(hash.0.finalize().into())
    }

    pub(super) fn record_opened_history_coverage(&mut self, id: &str, complete: bool) {
        let coverage = &mut self.recently_opened.history_coverage;
        coverage.remove(id);
        if !complete || coverage.len() >= PROTECTED_RETAINED {
            return;
        }
        if let Some(proof) = self.opened_history_fingerprint(id) {
            self.recently_opened.history_coverage.insert(id.to_owned(), proof);
        }
    }

    pub(super) fn has_current_opened_history(&self, id: &str) -> bool {
        self.recently_opened.history_coverage.get(id).is_some_and(|proof| {
            self.opened_history_fingerprint(id).as_ref() == Some(proof)
        })
    }

    pub(super) fn has_current_cached_startup_history(&self, id: &str) -> bool {
        !self.is_deleted_chat(id)
            && (self.chats.get(id).is_some_and(|row| {
                self.synced_window(row).is_ok_and(|window| {
                    window.is_some_and(|window| window.covers_complete_history())
                })
            }) || self.has_current_opened_history(id))
    }

    /// Bounded lookup set for an explicit offline open outside the sidebar.
    pub(super) fn offline_cached_chat_ids(&self) -> impl Iterator<Item = &str> {
        self.recently_opened.remote.iter().chain(&self.recently_opened.retained)
            .take(STARTUP_HISTORY + RETAINED).map(String::as_str)
    }

    pub(crate) fn cached_startup_chat_id(&self) -> Option<String> {
        if !self.recently_opened.remote_known
            && self.recently_opened.remote.is_empty()
            && self.recently_opened.pending.is_empty()
        {
            return self
                .cached_feed_last_opened_chat()
                .filter(|id| canonical_id(id));
        }
        self.recently_opened
            .pending
            .first()
            .or_else(|| self.recently_opened.remote.first())
            .filter(|id| !self.is_deleted_chat(id))
            .cloned()
    }

    pub(crate) async fn refresh_startup_opened_chat_ids(
        &mut self,
        budget: Option<&StartupForegroundBudget>,
    ) -> Result<Vec<String>> {
        self.require_canonical_read_profile()?;
        let route = self.scoped("/v1/chats/startup-opened")?;
        use crate::startup_diagnostics::StartupPhase;
        let response = self.request_startup_first_party(Method::GET, &route, None, false, budget)
            .await.and_then(|value| value.ok_or(Error::Protocol));
        StartupPhase::SelectorRequest.record(&response);
        let response = response?;
        self.require_canonical_read_profile()?;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let ids = parse_startup_opened_chat_ids(&response["chat_ids"]);
        StartupPhase::SelectorDecode.record(&ids);
        let ids = ids?;
        self.recently_opened.reconcile_server(&ids);
        self.recently_opened.offered_versions = ids.iter().filter_map(|id| {
            Some((id.clone(), opened_wire_version(&response["messages_versions"][id.as_str()])?))
        }).collect();
        Ok(ids)
    }

    pub(crate) async fn validate_startup_team(&mut self) -> Result<()> {
        self.require_canonical_read_profile()?;
        let Some(team) = self.team()?.map(str::to_owned) else {
            return Ok(());
        };
        let path = format!("/v1/teams/{}", segment(&team));
        let response = self.request(Method::GET, &path, None).await?;
        if self.operation_cancel.is_cancelled() || self.team()? != Some(team.as_str()) {
            return Err(Error::Cancelled);
        }
        if response["team"]["team_id"].as_str() != Some(team.as_str()) {
            return Err(Error::Forbidden);
        }
        Ok(())
    }

    pub(crate) fn remember_user_chat_open(&mut self, id: &str) -> Result<()> {
        self.require_canonical_read_profile()?;
        if !canonical_id(id) || self.is_ephemeral_chat(id) || self.is_deleted_chat(id) {
            return Err(Error::Invalid("A saved chat is required."));
        }
        put_first(&mut self.recently_opened.pending, id);
        self.recently_opened.pending.truncate(1);
        Ok(())
    }

    pub(crate) async fn submit_user_chat_open(&mut self, id: &str) -> Result<bool> {
        if self
            .recently_opened
            .pending
            .first()
            .is_none_or(|pending| pending != id)
        {
            return Err(Error::Cancelled);
        }
        let route = self.scoped(&format!("/v1/chats/{}/opened", segment(id)))?;
        let result = self.request(Method::POST, &route, Some(json!({}))).await;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let recorded = match result {
            Ok(response) if response["recorded"] == true => {
                put_first(&mut self.recently_opened.remote, id);
                self.recently_opened.remote.truncate(STARTUP_HISTORY);
                self.recently_opened.remote_known = true;
                true
            }
            Err(Error::Forbidden | Error::Invalid("The requested item is unavailable.")) => false,
            Ok(_) => return Err(Error::Protocol),
            Err(error) => return Err(error),
        };
        self.recently_opened.pending.clear();
        Ok(recorded)
    }

    pub(crate) async fn hydrate_opened_chat(
        &mut self,
        monitor: Option<&ChatMonitor>,
        id: &str,
        cancel: &CancellationToken,
    ) -> Result<Option<super::monitor::cached_view::CanonicalChatCandidate>> {
        self.require_canonical_read_profile()?;
        self.verify_private_operation()?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let owner = self.chat_owner_lease(monitor, Some(id))?;
        let confirmed_version = self.chats.get(id).and_then(|row| opened_wire_version(&row["messages_v"]));
        let offered_version = self.recently_opened.offered_versions.get(id).copied();
        if self.has_current_cached_startup_history(id)
            && !opened_tail_needs_read(false, false, confirmed_version, offered_version)
            && owner.is_valid()
        {
            return if cancel.is_cancelled() { Err(Error::Cancelled) } else { Ok(None) };
        }
        match self.read_chat_view_for_startup_hydration(monitor, id, cancel.clone()).await? {
            super::monitor::cached_view::ChatViewRead::Canonical(candidate) => Ok(Some(candidate)),
            super::monitor::cached_view::ChatViewRead::CachedOffline(_) => Err(Error::Offline),
            super::monitor::cached_view::ChatViewRead::CacheSettled(_) => Err(Error::Protocol),
        }
    }

    pub(crate) fn retain_opened_history(&mut self, id: &str, evict: bool) {
        put_first(&mut self.recently_opened.retained, id);
        self.trim_opened_history(evict);
    }

    pub(crate) fn retain_automatically_hydrated_history(&mut self, id: &str, evict: bool) {
        if !self
            .recently_opened
            .retained
            .iter()
            .any(|entry| entry == id)
        {
            self.recently_opened.retained.push(id.to_owned());
        }
        self.trim_opened_history(evict);
    }

    fn trim_opened_history(&mut self, evict: bool) {
        // The queue order denotes use, while the server's startup set pins
        // the cross-device offline selection independently of that order.
        if self.recently_opened.retained.len() <= RETAINED {
            return;
        }
        while evict && self.recently_opened.retained.len() > RETAINED {
            let removable = self.recently_opened.retained.iter().rposition(|id| {
                !self.recently_opened.remote.contains(id)
                    && !self.recently_opened.pending.contains(id)
                    && self.chats.get(id).is_none_or(|row| !sync::has_draft(row))
            });
            let Some(index) = removable else { break };
            let removed = self.recently_opened.retained.remove(index);
            self.recently_opened.history_coverage.remove(&removed);
            self.discard_unneeded_native_transcript(&removed);
        }
    }
}

#[cfg(test)]
#[path = "recently_opened_tests.rs"]
mod tests;
