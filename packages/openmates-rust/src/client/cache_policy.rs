//! PRIVATE, UNCOMPILED integration. Explicit IO adapters; no CLI discovery.
use super::chat_list_freshness::{
    CacheReadRequirements, CacheScope, CanonicalRecoveryState, SnapshotTrust,
};
use super::*;

/// Adapter-owned loader for the not-yet-restored remainder of a partially
/// restored native cache. Called with the Chat IDs already restored; returns
/// `{"shared": <section>|null, "chats": {<chat id>: <section>}}` in the
/// `snapshot_sections` layout. It must apply the same owner/key/epoch checks as
/// the original authenticated read; it grants no freshness or authority.
pub type CachedContentLoader =
    std::sync::Arc<dyn Fn(&[String]) -> Result<Value> + Send + Sync>;

/// Restoration state of native cache content. Default: complete (every
/// ordinary restore, reset, Team change and logout). Partial: only the index
/// and the listed Chats were restored; the remainder is on durable storage.
#[derive(Default)]
pub(super) struct CachedContentState {
    loader: Option<CachedContentLoader>,
    loaded: std::collections::BTreeSet<String>,
}

impl Client {
    /// Restore only the Chat-list index section (see `snapshot_sections`) from
    /// an authenticated owner envelope, deferring all per-Chat and shared
    /// content to `loader`. Same trust boundary as the full authenticated
    /// restore; content is loaded per Chat with `restore_cached_chat_content`
    /// or completely by `ensure_cached_content_loaded` (global sync does this).
    pub fn restore_authenticated_ciphertext_index(
        &mut self,
        index: &Value,
        loader: CachedContentLoader,
    ) -> Result<()> {
        self.restore_authenticated_ciphertext_snapshot(index)?;
        self.cached_content = CachedContentState { loader: Some(loader), loaded: Default::default() };
        Ok(())
    }

    /// Chat IDs whose cached content is restored, or None when the client holds
    /// its complete cache (the persisted state may then be replaced wholesale).
    pub fn partially_restored_chats(&self) -> Option<Vec<String>> {
        self.cached_content
            .loader
            .as_ref()
            .map(|_| self.cached_content.loaded.iter().cloned().collect())
    }

    /// Restore one Chat's cached content section (None: no cached content).
    /// Content the client already holds for that Chat wins over the cached
    /// section field by field; embeds/keys merge by identifier. A complete
    /// client ignores this call. Invalid sections are refused unchanged.
    pub fn restore_cached_chat_content(&mut self, chat: &str, section: Option<&Value>) -> Result<()> {
        if self.cached_content.loader.is_none() {
            return Ok(());
        }
        if let Some(section) = section {
            let partial = super::snapshot_sections::chat_partial_snapshot(chat, section)?;
            self.merge_cached_content(&partial, Some(chat))?;
        }
        self.cached_content.loaded.insert(chat.to_owned());
        Ok(())
    }

    /// Complete a partial restore before any operation that reads or replaces
    /// cached content beyond the restored Chats. No-op for complete clients.
    pub fn ensure_cached_content_loaded(&mut self) -> Result<()> {
        let Some(loader) = self.cached_content.loader.clone() else {
            return Ok(());
        };
        let loaded: Vec<String> = self.cached_content.loaded.iter().cloned().collect();
        let remainder = loader(&loaded)?;
        if let Some(shared) = remainder.get("shared").filter(|value| !value.is_null()) {
            let shared = shared.as_object().ok_or(Error::Protocol)?;
            let partial = json!({
                "embeds": shared.get("embeds").cloned().unwrap_or_else(|| json!({})),
                "embed_keys": shared.get("embed_keys").cloned().unwrap_or_else(|| json!([])),
            });
            self.merge_cached_content(&partial, None)?;
            if matches!(self.saved_embed_cache, super::saved_embed_selector::SelectorCache::Legacy) {
                self.saved_embed_cache = super::saved_embed_selector::SelectorCache::restore(
                    shared.get(super::saved_embed_selector::CACHE_FIELD),
                    self.saved_embed_unsynced_empty(),
                );
            }
        }
        if let Some(chats) = remainder.get("chats").filter(|value| !value.is_null()) {
            for (chat, section) in chats.as_object().ok_or(Error::Protocol)? {
                if !self.cached_content.loaded.contains(chat) {
                    let partial = super::snapshot_sections::chat_partial_snapshot(chat, section)?;
                    self.merge_cached_content(&partial, Some(chat))?;
                }
            }
        }
        self.cached_content = CachedContentState::default();
        Ok(())
    }

    /// Validate a content-only partial snapshot exactly like the full restore,
    /// then add only what the client does not already hold.
    fn merge_cached_content(&mut self, partial: &Value, chat: Option<&str>) -> Result<()> {
        self.require_session()?;
        let windows = super::sync_windows::restore_windows(partial.get(super::sync_windows::SNAPSHOT_FIELD))?;
        let selected = super::selected_first_page::restore(partial.get(super::selected_first_page::SNAPSHOT_FIELD))?;
        let history: BTreeMap<String, Vec<Value>> = serde_json::from_value(
            partial.get("history").cloned().unwrap_or_else(|| json!({})),
        )?;
        let embeds: BTreeMap<String, Value> = serde_json::from_value(
            partial.get("embeds").cloned().unwrap_or_else(|| json!({})),
        )?;
        let embed_keys: Vec<Value> = serde_json::from_value(
            partial.get("embed_keys").cloned().unwrap_or_else(|| json!([])),
        )?;
        let foreign = |id: &String| chat.is_some_and(|chat| chat != id);
        if windows.keys().chain(selected.keys()).chain(history.keys()).any(foreign) {
            return Err(Error::Protocol);
        }
        // Sync windows carry globally unique source ranks; a conflicting cached
        // rank is refused rather than allowed to shadow a held window.
        let held_ranks: std::collections::BTreeSet<u8> = self
            .sync_message_windows
            .values()
            .filter_map(|window| window.source_rank)
            .collect();
        for (id, window) in windows {
            if self.sync_message_windows.contains_key(&id) {
                continue;
            }
            if window.source_rank.is_some_and(|rank| held_ranks.contains(&rank)) {
                return Err(Error::Protocol);
            }
            self.sync_message_windows.insert(id, window);
        }
        for (id, page) in selected {
            self.selected_first_pages.entry(id).or_insert(page);
        }
        for (id, rows) in history {
            self.history.entry(id).or_insert(rows);
        }
        for (id, row) in embeds {
            self.embeds.entry(id).or_insert(row);
        }
        let held: std::collections::BTreeSet<String> = self
            .embed_keys
            .iter()
            .filter_map(|row| row.get("id").and_then(Value::as_str).map(str::to_owned))
            .collect();
        for row in embed_keys {
            let id = row.get("id").and_then(Value::as_str);
            if id.is_none_or(|id| !held.contains(id)) {
                self.embed_keys.push(row);
            }
        }
        Ok(())
    }

    /// Explicitly revoke only cached-list freshness. The caller must durably
    /// publish the next ciphertext snapshot before uncertain remote effects.
    /// Ciphertext and credentials remain available through their existing APIs.
    pub fn invalidate_chat_list_freshness(&mut self) {
        self.chat_list_freshness.invalidate();
    }

    /// Profile eligibility only; this grants neither freshness nor authority.
    pub fn supports_cached_default_chat_list(&self) -> bool {
        self.require_credentials().is_ok_and(|session| session.active_team_id.is_none())
            && !self
                .chats
                .values()
                .any(|row| text(row, "chat_visibility") == "direct")
    }

    /// Supply a trusted, suspend-inclusive boot clock explicitly. Unknown clock
    /// support keeps the normal canonical path. Installing/replacing an adapter
    /// cannot promote existing data; restore its protected receipt separately.
    pub fn set_chat_cache_clock_provider(
        &mut self,
        provider: Option<std::sync::Arc<dyn Fn() -> Option<CacheClockEvidence> + Send + Sync>>,
    ) {
        self.chat_list_freshness.invalidate();
        self.cache_clock = provider;
    }

    pub(super) fn cache_clock_evidence(&self) -> Option<CacheClockEvidence> {
        self.cache_clock.as_ref().and_then(|clock| clock())
    }

    /// Explicit adapter trust boundary: caller has authenticated the encrypted
    /// owner/master-key/API/Team envelope. Ordinary JSON snapshot restoration
    /// intentionally cannot import a freshness receipt. This is offline cache
    /// provenance, never a login, permission lease, or server authorization.
    pub fn restore_authenticated_ciphertext_snapshot(&mut self, snapshot: &Value) -> Result<()> {
        self.restore_ciphertext_snapshot(snapshot)?;
        // Same explicit authenticated-envelope boundary as the existing cache.
        // Ordered identities/timestamp are DATA, never restored server/key proof.
        self.saved_embed_cache=super::saved_embed_selector::SelectorCache::restore(snapshot.get(super::saved_embed_selector::CACHE_FIELD),self.saved_embed_unsynced_empty());
        let session = self.require_credentials()?;
        let origin = self.base.as_str().to_owned();
        let owner = session.hashed_email.clone();
        let team = session.active_team_id.clone();
        let scope = CacheScope {
            canonical_api_origin: &origin,
            hashed_owner: &owner,
            active_team_id: team.as_deref(),
            authenticated_principal: None,
        };
        self.chat_list_freshness.restore(
            &scope,
            snapshot,
            SnapshotTrust::AuthenticatedOwnerEnvelope,
        );
        Ok(())
    }

    /// Explicit cached read for default Personal list only. The application
    /// retains live session/protected-account admission and final durable output
    /// fencing. Owned/uncertain recovery always takes its foreground path.
    /// Team, Direct and unknown clock profiles conservatively return None.
    pub fn try_cached_default_chat_list(
        &self,
        own_pending_or_uncertain_recovery: bool,
    ) -> Result<Option<Vec<Item>>> {
        if !self.may_read_cached_default_chat_inventory(own_pending_or_uncertain_recovery)? {
            return Ok(None);
        }
        // The same renderer preserves current title/order/locked-row semantics.
        // Damaged/unavailable local keys take the unchanged canonical path.
        let items = match self.render_chat_inventory() {
            Ok(items) => items,
            Err(_) => return Ok(None),
        };
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok(Some(items))
    }

    /// Eligibility only: identical existing receipt/scope/key/epoch/clock checks,
    /// without decrypting or rendering unrelated Chat list items.
    pub(super) fn may_read_cached_default_chat_inventory(
        &self,
        own_pending_or_uncertain_recovery: bool,
    ) -> Result<bool> {
        let session = self.require_credentials()?;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if !self.supports_cached_default_chat_list() {
            return Ok(false);
        }
        let scope = CacheScope {
            canonical_api_origin: self.base.as_str(),
            hashed_owner: &session.hashed_email,
            active_team_id: session.active_team_id.as_deref(),
            authenticated_principal: self.user["id"]
                .as_str()
                .filter(|id| !id.is_empty())
                .or_else(|| self.user["user_id"].as_str().filter(|id| !id.is_empty())),
        };
        // Streams only the list inputs; never clones/serializes the full cache.
        let digest = self.chat_list_inputs_digest();
        let now = self.cache_clock_evidence();
        Ok(self.chat_list_freshness.may_read(
            &scope,
            digest.as_deref(),
            now.as_ref(),
            CacheReadRequirements {
                force_refresh: false,
                own_pending_or_uncertain_recovery,
            },
        ))
    }

    /// Exact list-rendering inputs only: rows, arrival order, key wrappers and
    /// the Team wrapped key. Same bytes as the persisted snapshot projection.
    pub(super) fn chat_list_inputs_digest(&self) -> Option<String> {
        super::chat_list_freshness::client_list_digest(
            &self.chats,
            self.current_chat_arrival_order(),
            &self.wrappers,
            &self.team_wrapped_key,
        )
    }

    /// Called exclusively by the checked, consuming V2 inventory boundary.
    /// The timestamp came from canonical completion, never this later read.
    pub(super) fn record_complete_chat_list_at(&mut self, completed: Option<&CacheClockEvidence>) {
        let Ok(session) = self.require_credentials() else {
            return;
        };
        let origin = self.base.as_str().to_owned();
        let owner = session.hashed_email.clone();
        let team = session.active_team_id.clone();
        let digest = self.chat_list_inputs_digest();
        let scope = CacheScope {
            canonical_api_origin: &origin,
            hashed_owner: &owner,
            active_team_id: team.as_deref(),
            authenticated_principal: self.user["id"]
                .as_str()
                .filter(|id| !id.is_empty())
                .or_else(|| self.user["user_id"].as_str().filter(|id| !id.is_empty())),
        };
        self.chat_list_freshness.canonical_committed(
            &scope,
            digest.as_deref(),
            completed,
            completed,
            CanonicalRecoveryState::Settled,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::Session;
    use std::collections::BTreeMap;
    use zeroize::Zeroizing;
    fn client() -> Client {
        let mut client = Client::new(
            "https://api.example.test",
            Some(Session {
                api_url: "https://api.example.test".into(),
                session_id: "synthetic-session".into(),
                cookies: BTreeMap::new(),
                ws_token: None,
                master_key: Zeroizing::new([7; 32]),
                hashed_email: "synthetic-owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: None,
            }),
        )
        .unwrap();
        client.user = json!({"id":"synthetic-principal"});
        client
    }
    fn clock(tick: u64) -> CacheClockEvidence {
        CacheClockEvidence::from_platform("synthetic-boot".into(), tick, tick).unwrap()
    }
    #[test]
    fn protected_roundtrip_and_cookie_rotation_preserve_original_expiry() {
        let mut original = client();
        original.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| Some(clock(1_100)))));
        original.record_complete_chat_list_at(Some(&clock(1_000)));
        let snapshot = original.ciphertext_snapshot();
        let mut restored = client();
        restored.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| Some(clock(1_200)))));
        restored
            .restore_authenticated_ciphertext_snapshot(&snapshot)
            .unwrap();
        assert!(
            restored
                .try_cached_default_chat_list(false)
                .unwrap()
                .unwrap()
                .is_empty()
        );
        restored
            .session
            .as_mut()
            .unwrap()
            .cookies
            .insert("auth_refresh_token".into(), "rotated".into());
        restored.credentials_changed();
        assert!(
            restored
                .try_cached_default_chat_list(false)
                .unwrap()
                .is_some()
        );
        assert!(
            restored
                .try_cached_default_chat_list(true)
                .unwrap()
                .is_none()
        );
        restored.user = json!({"id":"different-live-principal"});
        assert!(
            restored
                .try_cached_default_chat_list(false)
                .unwrap()
                .is_none()
        );
        restored.user = json!({"id":"synthetic-principal"});
        restored.cache_clock = Some(std::sync::Arc::new(|| Some(clock(301_000))));
        assert!(
            restored
                .try_cached_default_chat_list(false)
                .unwrap()
                .is_none()
        );
    }
    #[test]
    fn ordinary_restore_direct_team_change_clear_and_cancellation_never_admit() {
        let mut original = client();
        original.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| Some(clock(1_100)))));
        original.record_complete_chat_list_at(Some(&clock(1_000)));
        let snapshot = original.ciphertext_snapshot();
        let mut restored = client();
        restored.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| Some(clock(1_200)))));
        restored.restore_ciphertext_snapshot(&snapshot).unwrap();
        assert!(
            restored
                .try_cached_default_chat_list(false)
                .unwrap()
                .is_none()
        );
        restored
            .restore_authenticated_ciphertext_snapshot(&snapshot)
            .unwrap();
        restored.chats.insert(
            "synthetic-direct".into(),
            json!({"id":"synthetic-direct","chat_visibility":"direct"}),
        );
        assert!(
            restored
                .try_cached_default_chat_list(false)
                .unwrap()
                .is_none()
        );
        restored
            .restore_authenticated_ciphertext_snapshot(&snapshot)
            .unwrap();
        restored
            .set_team(Some("00000000-0000-4000-8000-000000000007"))
            .unwrap();
        assert!(
            restored
                .try_cached_default_chat_list(false)
                .unwrap()
                .is_none()
        );
        restored.set_team(None).unwrap();
        assert!(
            restored
                .try_cached_default_chat_list(false)
                .unwrap()
                .is_none()
        );
        restored
            .restore_authenticated_ciphertext_snapshot(&snapshot)
            .unwrap();
        restored.operation_cancel.cancel();
        assert!(matches!(
            restored.try_cached_default_chat_list(false),
            Err(Error::Cancelled)
        ));
        restored.forget_session();
        assert!(restored.chat_list_freshness.snapshot_metadata().is_none());
    }
    #[tokio::test]
    async fn observed_access_denial_revokes_freshness_but_public_not_found_does_not() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        for (code, path, should_remain_fresh) in [
            (403, "/v1/embeds/synthetic", false),
            (404, "/v1/chats/synthetic/messages/window", false),
            (410, "/v1/teams/synthetic", false),
            (404, "/v1/apps/synthetic-public-missing", true),
        ] {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let endpoint = format!("http://{}", listener.local_addr().unwrap());
            let peer = tokio::spawn(async move {
                let (mut socket, _) = listener.accept().await.unwrap();
                let mut request = Vec::new();
                loop {
                    let mut buffer = [0; 1024];
                    let n = socket.read(&mut buffer).await.unwrap();
                    assert!(n > 0);
                    request.extend_from_slice(&buffer[..n]);
                    assert!(request.len() < 16_384);
                    if request.windows(4).any(|v| v == b"\r\n\r\n") {
                        break;
                    }
                }
                socket.write_all(format!("HTTP/1.1 {code} Test\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}").as_bytes()).await.unwrap();
            });
            let mut session = client().take_session().unwrap();
            session.api_url = endpoint.clone();
            let mut client = Client::new(&endpoint, Some(session)).unwrap();
            client.user = json!({"id":"synthetic-principal"});
            client.set_chat_cache_clock_provider(Some(std::sync::Arc::new(|| Some(clock(1_100)))));
            client.record_complete_chat_list_at(Some(&clock(1_000)));
            assert!(
                client
                    .try_cached_default_chat_list(false)
                    .unwrap()
                    .is_some()
            );
            assert!(client.request(Method::GET, path, None).await.is_err());
            assert_eq!(
                client
                    .try_cached_default_chat_list(false)
                    .unwrap()
                    .is_some(),
                should_remain_fresh
            );
            assert!(
                client.session().is_some(),
                "denial does not invent logout semantics"
            );
            peer.await.unwrap();
        }
    }
}
