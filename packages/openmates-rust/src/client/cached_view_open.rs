//! Single-chat cached open: the bounded cached window of one chat under the
//! same authenticated owner, monitor and denial fences as
//! `stage_cached_chat_views`, without decoding every other cached chat. The
//! core view-model `OpenChat` uses it for the cached first page before any
//! network request (`a2-design.md`, lane L7). Performs no request, cache
//! write, credential acknowledgement or receipt.
use super::*;

/// The owner fence of queued chat plaintext: a shell that paints chat data
/// later than the core produced it (the terminal's UI thread) holds this next
/// to the data and drops the data unless the lease is still valid.
///
/// Valid while the same authenticated owner authority is live (no reset,
/// logout or owner-key change), its session has not expired, the captured
/// chat monitor has no access denial, and the cached-denial ledger is
/// unchanged and, when a chat is named, still allows that chat. Carries no
/// key or credential.
pub struct ChatOwnerLease {
    fence: Arc<CachedOwnerFence>,
    chat_id: Option<String>,
    denial_revision: u64,
}

impl ChatOwnerLease {
    /// Whether data produced under this lease may still be shown.
    pub fn is_valid(&self) -> bool {
        cached_owner_valid(&self.fence)
            && self
                .chat_id
                .as_deref()
                .is_none_or(|id| self.fence.owner.cached_chat_allowed(id))
            && self
                .fence
                .owner
                .cached_denial_revision()
                .is_ok_and(|revision| revision == self.denial_revision)
    }
}

impl Client {
    /// A lease on the current authenticated owner (and `chat_id`, when
    /// given) for fencing chat data queued for later display.
    ///
    /// # Errors
    /// `Authentication` without a principal established by actual
    /// authentication; `Cancelled` when the owner, team or `monitor` context
    /// has moved.
    pub fn chat_owner_lease(
        &self,
        monitor: Option<&ChatMonitor>,
        chat_id: Option<&str>,
    ) -> Result<ChatOwnerLease> {
        let fence = self.cached_view_owner(monitor)?;
        let denial_revision = fence.owner.cached_denial_revision()?;
        Ok(ChatOwnerLease {
            fence,
            chat_id: chat_id.map(str::to_owned),
            denial_revision,
        })
    }
}

impl Client {
    /// The cached window of `id` alone, sealed exactly like a publication of
    /// a staged reader (owner epoch, expiry, known denials, `request`).
    /// `Ok(None)` when the chat has no usable cache: a scope without the
    /// cached default list, a denied chat, no cached row, or a row that does
    /// not decode (the caller's canonical read still runs and reports).
    ///
    /// # Errors
    /// `Invalid` for a non-canonical id, `Authentication` without a principal
    /// established by actual authentication, `Cancelled` for unacknowledged
    /// credentials, a cancelled `request` or a moved owner/monitor context.
    pub(crate) fn cached_chat_publication(
        &self,
        monitor: Option<&ChatMonitor>,
        id: &str,
        request: CancellationToken,
    ) -> Result<Option<CachedChatPublication>> {
        let parsed =
            uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        if parsed.hyphenated().to_string() != id {
            return Err(Error::Invalid("A canonical full chat ID is required."));
        }
        let fence = self.cached_view_owner(monitor)?;
        self.verify_private_operation()?;
        if request.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // Same durability admission as staging: never show cache before the
        // current credential revision is durably acknowledged.
        if self.credential_ack != self.credential_revision {
            return Err(Error::Cancelled);
        }
        let denial_revision = fence.owner.cached_denial_revision()?;
        if !self.supports_cached_default_chat_list() || !fence.owner.cached_chat_allowed(id) {
            return Ok(None);
        }
        let Some(row) = self.chats.get(id) else {
            return Ok(None);
        };
        let wrapping = self.cached_wrapping_key()?;
        // The staged reader skips an undecodable row the same way; the
        // optional preview is dropped, never repaired or defaulted.
        let Ok((window, _)) = self.decode_cached_window(row, &wrapping) else {
            return Ok(None);
        };
        let publication = CachedChatPublication {
            denial_revision,
            fence,
            lifetime: CancellationToken::new(),
            request,
            window: Arc::new(CachedWindowData {
                window: Mutex::new(Some(window)),
            }),
            id: id.to_owned(),
        };
        self.check_cached_view_owner(&publication.fence)?;
        if !publication.is_valid() {
            return Err(Error::Cancelled);
        }
        Ok(Some(publication))
    }
}

#[cfg(test)]
impl Client {
    /// Test-only stand-in for actual authentication: adopt `owner` as the
    /// authenticated principal and acknowledge the credential revision, so
    /// view-model tests can open cached chats without a server.
    pub(crate) fn adopt_test_principal(&mut self, owner: &str) -> Result<()> {
        self.user = serde_json::json!({ "id": owner });
        self.credentials_changed();
        self.acknowledge_credentials(self.credential_revision)
    }
}
