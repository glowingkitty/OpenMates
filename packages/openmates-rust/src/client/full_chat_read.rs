//! Full saved-chat JSON projection. The legacy Chat and bounded/browser shapes
//! are unchanged; this optional field is authenticated read metadata, not a slug
//! selector, cache/freshness receipt, history proof or durable-write acknowledgement.
use super::{
    plaintext::{Plain, Wipe},
    sync_capability::AsyncCryptoScope,
    *,
};
use serde::{Deserialize, Serialize};

#[derive(Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FullChatRead {
    #[serde(flatten)]
    pub chat: Chat,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slug: Option<String>,
    #[serde(skip)]
    admission: Option<FullChatReadAdmission>,
}
impl FullChatRead {
    /// Transfer the exact admission held by this actual completed read.
    /// No recapture after IO, decrypt or serialization.
    pub fn take_admission(&mut self, client: &Client) -> Result<FullChatReadAdmission> {
        self.check(client)?;
        self.admission.take().ok_or(Error::Forbidden)
    }
    /// Restrict final adapter serialization using the same ORIGINAL read policy.
    /// Deserialized/fabricated view data has no retained publication admission.
    pub fn check(&self, client: &Client) -> Result<()> {
        self.admission
            .as_ref()
            .ok_or(Error::Forbidden)?
            .check(client)
    }
}
/// Restrictive original-policy evidence only; no Clone/Debug/serde/read grant.
/// The actual authenticated full read must still complete before plaintext exists.
pub struct FullChatReadAdmission {
    saved: saved_chat_read::SavedChatReadAdmission,
    privacy: crate::privacy::PrivacyOptions,
    original_gate: Option<std::sync::Arc<dyn Fn() -> Result<()> + Send + Sync>>,
    chat_id: zeroize::Zeroizing<String>,
    // Captured before the read. Neither policy nor credential authority is
    // recaptured when a native caller restores its ambient Team context.
    original_identity: FullReadIdentity,
    restored_scope: Option<AsyncCryptoScope>,
}
struct FullReadIdentity {
    binding: credentials::MasterBinding,
    credentials: String,
    owner: String,
    parent: CancellationToken,
    authority: std::sync::Arc<project_task_watch::WatchAuthority>,
    denial_revision: u64,
    expires_at: Option<u64>,
}
impl FullReadIdentity {
    fn credentials(client: &Client) -> Result<String> {
        let s = client.require_credentials()?;
        Ok(sha256(&serde_json::to_string(&(
            s.api_url,
            s.session_id,
            s.hashed_email,
        ))?))
    }
    fn owner(client: &Client) -> Result<String> {
        Ok(sha256(&serde_json::to_string(&(
            &client.user["id"],
            &client.user["user_id"],
            &client.user["username"],
        ))?))
    }
    fn capture(client: &Client) -> Result<Self> {
        Ok(Self {
            binding: client.master_binding()?,
            credentials: Self::credentials(client)?,
            owner: Self::owner(client)?,
            parent: client.operation_parent.clone(),
            authority: client.task_watch_authority.clone(),
            denial_revision: client.task_watch_authority.cached_denial_revision()?,
            expires_at: client.require_credentials()?.paired_session_expires_at,
        })
    }
    fn check(&self, client: &Client) -> Result<()> {
        client.require_canonical_read_profile()?;
        self.binding.check(client)?;
        // Restoring Team cancels the old child/watch, never the original caller.
        // The old negative ledger stays restrictive even after its retirement.
        if self.expires_at.is_some_and(|expires| expires <= now_ms()) {
            return Err(Error::Expired);
        }
        if self.parent.is_cancelled()
            || self.parent != client.operation_parent
            || self.credentials != Self::credentials(client)?
            || self.owner != Self::owner(client)?
            || self.denial_revision != self.authority.cached_denial_revision()?
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
impl FullChatReadAdmission {
    /// Permit precisely one checked synchronous ambient-context restoration.
    /// Call only after completed read/decrypt/serialization/persistence checks.
    /// No await, fresh read admission, gate/privacy replacement or source grant.
    pub fn restore_team(&mut self, client: &mut Client, team: Option<&str>) -> Result<()> {
        if self.restored_scope.is_some() {
            return Err(Error::Cancelled);
        }
        self.check(client)?;
        if client.team()? == team {
            return Ok(());
        }
        self.original_identity.check(client)?;
        client.set_team(team)?;
        self.original_identity.check(client)?;
        // Observe exactly the scope this synchronous restoration produced.
        // All pre-read identity, key, caller, policy and negative evidence stays.
        self.restored_scope = Some(AsyncCryptoScope::begin(client)?);
        self.check(client)
    }
    pub fn check(&self, client: &Client) -> Result<()> {
        self.privacy.verify()?;
        if let Some(gate) = &self.original_gate {
            gate()?;
        }
        if let Some(scope) = &self.restored_scope {
            // Exact scope produced ONLY by our checked synchronous restoration.
            // It restricts subsequent changes; it does not replace original policy.
            self.original_identity.check(client)?;
            self.saved.ensure_resource_current()?;
            scope.check_chat(client, &self.chat_id)?;
        } else {
            self.saved.check(client)?; // Includes CURRENT privacy/gate/profile/context.
        }
        if !client
            .task_watch_authority
            .cached_chat_allowed(&self.chat_id)
        {
            return Err(Error::Forbidden);
        }
        self.privacy.verify()?;
        if let Some(gate) = &self.original_gate {
            gate()?;
        }
        client.verify_private_operation()?;
        // Caller gates may synchronously retire captured authority while still
        // returning success. No callback follows these original negative checks.
        if let Some(scope) = &self.restored_scope {
            self.original_identity.check(client)?;
            self.saved.ensure_resource_current()?;
            scope.check_chat(client, &self.chat_id)?;
        } else {
            self.saved.check_after_private_gate(client)?;
        }
        if !client.task_watch_authority.cached_chat_allowed(&self.chat_id) {
            return Err(Error::Forbidden);
        }
        Ok(())
    }
}
impl Drop for FullChatRead {
    fn drop(&mut self) {
        self.chat.wipe();
        self.slug.wipe();
    }
}
impl Client {
    /// Capture restrictive full-read policy BEFORE HTTP, including a copied
    /// privacy policy and the original private gate resource. Current policy
    /// replacement cannot retire the original gate's negative authority.
    pub fn full_chat_read_admission(&self, id: &str) -> Result<FullChatReadAdmission> {
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full chat ID is required."))?;
        let admission = FullChatReadAdmission {
            saved: self.original_full_chat_read_admission()?,
            privacy: self.options.privacy.clone(),
            original_gate: self.options.private_operation_gate.clone(),
            chat_id: zeroize::Zeroizing::new(id.to_owned()),
            original_identity: FullReadIdentity::capture(self)?,
            restored_scope: None,
        };
        admission.check(self)?;
        Ok(admission)
    }
    /// The original full-read scope, retained through queued foreign output.
    /// No recaptured admission after decrypt, no additional IO or new authority.
    pub async fn open_chat_with_metadata_and_admission(
        &mut self,
        id: &str,
    ) -> Result<(FullChatRead, FullChatReadAdmission)> {
        let mut read = self.open_chat_with_metadata(id).await?;
        let admission = read.admission.take().ok_or(Error::Forbidden)?;
        admission.check(self)?;
        Ok((read, admission))
    }
    /// Exactly one existing strict/full read. Optional slug is decrypted from
    /// that read's owned metadata using existing wrapper/Direct capability rules.
    /// Offline behavior remains the existing full-read fallback, not freshness.
    pub async fn open_chat_with_metadata(&mut self, id: &str) -> Result<FullChatRead> {
        let admission = self.full_chat_read_admission(id)?;
        self.require_canonical_read_profile()?;
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, id)?;
        let chat = Plain::new(self.open_chat(id).await?);
        self.full_chat_read_projection(id, chat, &scope, admission)
            .await
    }
    /// Preserve the native caller's exact one-use discovery/full-read lane.
    /// Output still awaits the caller's normal durable save-before-output gate.
    pub async fn open_chat_with_metadata_and_fresh_inventory(
        &mut self,
        id: &str,
        proof: FreshChatInventory,
        cancel: &CancellationToken,
    ) -> Result<FullChatRead> {
        let admission = self.full_chat_read_admission(id)?;
        self.require_canonical_read_profile()?;
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, id)?;
        let chat = Plain::new(
            self.open_chat_with_fresh_chat_inventory(id, proof, cancel)
                .await?,
        );
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        let result = self
            .full_chat_read_projection(id, chat, &scope, admission)
            .await?;
        if cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        Ok(result)
    }
    async fn full_chat_read_projection(
        &self,
        id: &str,
        chat: Plain<Chat>,
        scope: &AsyncCryptoScope,
        admission: FullChatReadAdmission,
    ) -> Result<FullChatRead> {
        admission.check(self)?;
        scope.check_chat(self, id)?;
        if chat.id != id {
            return Err(Error::Forbidden);
        }
        let row = self.chats.get(id).ok_or(Error::Offline)?;
        if row.get("id").and_then(Value::as_str) != Some(id) {
            return Err(Error::Forbidden);
        }
        // Draft-only rows have no established chat key. Never substitute a
        // wrapping/master key or a requested slug to manufacture saved metadata.
        let slug = if sync::draft_only(row) && self.team()?.is_none() {
            Plain::new(None)
        } else {
            // No HTTP here: full live/cached read already established this
            // exact wrapping capability. Reuse it without another metadata read.
            let wrapping = self.cached_wrapping_capability()?;
            let key = self.chat_key_with_capability(row, &wrapping).await?;
            scope.check_chat(self, id)?;
            admission.check(self)?;
            Plain::new(saved_chat_read::metadata::chat_slug(row, id, &key)?)
        };
        self.verify_private_operation()?;
        self.require_canonical_read_profile()?;
        scope.check_chat(self, id)?;
        admission.check(self)?;
        Ok(FullChatRead {
            chat: chat.into_inner(),
            slug: slug.into_inner(),
            admission: Some(admission),
        })
    }
}
#[cfg(test)]
#[path = "full_chat_read_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "full_chat_read_post_gate_tests.rs"]
mod post_gate_tests;
