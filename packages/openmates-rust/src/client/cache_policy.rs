//! PRIVATE, UNCOMPILED integration. Explicit IO adapters; no CLI discovery.
use super::chat_list_freshness::{
    CacheReadRequirements, CacheScope, CanonicalRecoveryState, SnapshotTrust,
};
use super::*;

impl Client {
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
        let snapshot = self.ciphertext_snapshot();
        let now = self.cache_clock_evidence();
        Ok(self.chat_list_freshness.may_read(
            &scope,
            &snapshot,
            now.as_ref(),
            CacheReadRequirements {
                force_refresh: false,
                own_pending_or_uncertain_recovery,
            },
        ))
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
        let snapshot = self.ciphertext_snapshot();
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
            &snapshot,
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
