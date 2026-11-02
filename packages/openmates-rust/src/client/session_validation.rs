//! Local evidence of the existing successful /auth/session merge. This is
//! neither server authority nor a fresh operation/key/account admission.
use super::*;
use std::sync::Arc;
use zeroize::Zeroizing;

// Only token/cookies may change within this particular transition. Preserve the
// complete other credential metadata and exact transport/account/key context.
fn root(client: &Client) -> Result<Zeroizing<String>> {
    let c = client.require_credentials()?;
    let principal = client.user["id"].as_str().filter(|id| !id.is_empty())
        .or_else(|| client.user["user_id"].as_str().filter(|id| !id.is_empty()))
        .ok_or(Error::Protocol)?;
    let encoded = Zeroizing::new(serde_json::to_string(&(
        (c.api_url, c.session_id, c.hashed_email, c.user_email_salt,
            c.email_encryption_key, c.created_at, c.paired_session_expires_at, c.active_team_id),
        (principal, &client.user["id"], &client.user["user_id"], &client.user["username"],
            client.base.as_str(), client.app_url(), client.options.identity.header(),
            client.options.interactive, client.browser_transport, client.browser_password_transport,
            client.browser_password_stay_logged_in, client.browser_local_read_only),
    ))?);
    Ok(Zeroizing::new(sha256(&encoded)))
}

pub(in crate::client) struct BeforeSessionValidation {
    revision: u64,
    binding: Zeroizing<[u8; 32]>,
    authority: Arc<project_task_watch::WatchAuthority>,
    parent: CancellationToken,
    generation: u64,
    root: Zeroizing<String>,
    master: credentials::MasterBinding,
}
impl BeforeSessionValidation {
    pub(super) fn capture(client: &Client) -> Result<Self> {
        Ok(Self { revision: client.credential_revision,
            binding: Zeroizing::new(client.fresh_auth_binding()?),
            authority: client.task_watch_authority.clone(), parent: client.operation_parent.clone(),
            generation: client.generation, root: root(client)?, master: client.master_binding()? })
    }
    pub(in crate::client) fn revision(&self) -> u64 { self.revision }
    pub(in crate::client) fn binding(&self) -> &[u8; 32] { &self.binding }
    pub(in crate::client) fn check_original_client(&self, client: &Client) -> Result<()> {
        self.master.check(client)?;
        if self.generation != client.generation || !Arc::ptr_eq(&self.authority, &client.task_watch_authority)
            || self.parent != client.operation_parent || self.root.as_str() != root(client)?.as_str() {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    pub(super) fn endpoint_matches(&self, client:&Client) -> Result<bool> {
        Ok(self.revision==client.credential_revision && *self.binding==client.fresh_auth_binding()?)
    }
    // This combined operation alone may advance the existing token. The registry
    // accepts only this sealed capture and proves the complete actual edge path.
    pub(super) fn advance_over_original_owned_lineage(&mut self, client:&Client,
        original:&owned_operation::OwnedOperationScope) -> Result<()> {
        original.check_dispatched_session_validation_lineage(client,self)?;
        self.revision=client.credential_revision;
        self.binding=Zeroizing::new(client.fresh_auth_binding()?);
        self.check_original_client(client)?;
        original.check_dispatched_session_validation_lineage(client,self)
    }
    // Called only after the real response success/principal/body checks and the
    // existing credential installation/publication. Never accepts caller epochs.
    pub(super) fn finish(self, client: &Client) -> Result<ActualSessionValidationTransition> {
        let receipt = ActualSessionValidationTransition {
            before_revision: self.revision, after_revision: client.credential_revision,
            before_binding: self.binding, after_binding: Zeroizing::new(client.fresh_auth_binding()?),
            authority: self.authority, parent: self.parent, generation: self.generation,
            root: self.root, master: self.master,
        };
        receipt.check_applied_state(client)?;
        Ok(receipt)
    }
}

// No Clone/Debug/serde, public constructor, foreign input or auth material export.
// Only this private auth submodule can construct the receipt's private fields.
pub(in crate::client) struct ActualSessionValidationTransition {
    before_revision: u64, after_revision: u64,
    before_binding: Zeroizing<[u8; 32]>, after_binding: Zeroizing<[u8; 32]>,
    authority: Arc<project_task_watch::WatchAuthority>, parent: CancellationToken,
    generation: u64, root: Zeroizing<String>, master: credentials::MasterBinding,
}
impl ActualSessionValidationTransition {
    pub(in crate::client) fn revisions(&self) -> (u64, u64) { (self.before_revision, self.after_revision) }
    pub(in crate::client) fn binding_pair(&self) -> (&[u8; 32], &[u8; 32]) { (&self.before_binding, &self.after_binding) }
    pub(in crate::client) fn check_original_client(&self, client: &Client) -> Result<()> {
        self.master.check(client)?;
        if self.generation != client.generation || !Arc::ptr_eq(&self.authority, &client.task_watch_authority)
            || self.parent != client.operation_parent || self.root.as_str() != root(client)?.as_str() {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    pub(in crate::client) fn check_applied_state(&self, client: &Client) -> Result<()> {
        self.check_original_client(client)?;
        if self.after_revision != client.credential_revision || *self.after_binding != client.fresh_auth_binding()?
            || self.before_revision.checked_add(1) != Some(self.after_revision) {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
