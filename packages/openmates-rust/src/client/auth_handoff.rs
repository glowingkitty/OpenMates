//! One-use transport authentication handoff, never cache/read authorization.
use super::*;
use crate::platform::time::Instant;
use sha2::{Digest, Sha256};
use std::sync::{Arc, atomic::Ordering};
use zeroize::{Zeroize, Zeroizing};
const MAX_HANDOFF_AGE: Duration = Duration::from_secs(5);

/// Actual fresh server validation, consumable only by this Client's first
/// explicit foreground-recovery socket in the same live caller operation.
/// Private fields, no Clone/Debug/serde; cannot be persisted or restored.
/// Possession never authorizes a server request without its ordinary session.
///
/// ```compile_fail
/// use openmates_sdk::client::FreshSessionHandoff;
/// let forged = FreshSessionHandoff {};
/// ```
/// ```compile_fail
/// use openmates_sdk::client::FreshSessionHandoff;
/// fn duplicate(value: FreshSessionHandoff) { let _ = value.clone(); }
/// ```
/// ```compile_fail
/// use openmates_sdk::client::FreshSessionHandoff;
/// fn persist(value: FreshSessionHandoff) { let _ = serde_json::to_vec(&value); }
/// ```
pub struct FreshSessionHandoff {
    issuer: Arc<super::project_task_watch::WatchAuthority>,
    network: Arc<std::sync::atomic::AtomicU64>,
    network_revision: u64,
    credential_revision: u64,
    generation: u64,
    operation_epoch: u64,
    caller: CancellationToken,
    binding: [u8; 32],
    validated_at: Instant,
}
impl Drop for FreshSessionHandoff {
    fn drop(&mut self) {
        self.binding.zeroize();
    }
}
#[derive(Default)]
pub(super) struct FreshAuthState {
    pending: Option<FreshSessionHandoff>,
    operation_epoch: u64,
}
impl FreshAuthState {
    pub(super) fn operation_epoch(&self) -> u64 {
        self.operation_epoch
    }
    pub(super) fn advance_operation(&mut self) {
        self.pending = None;
        self.operation_epoch = self.operation_epoch.wrapping_add(1);
    }
}
impl Client {
    /// Validate exactly as validate_session does, then optionally retain proof
    /// for an explicitly installed matching operation-parent cancel token.
    /// This always contacts the server; cached credentials never issue proof.
    /// Ordinary validation callers, SessionBridge and browser adapters keep
    /// their existing behavior and do not arm a future operation implicitly.
    pub async fn validate_session_for_recovery(
        &mut self,
        cancel: &CancellationToken,
    ) -> Result<Option<FreshSessionHandoff>> {
        self.fresh_auth.pending = None;
        if cancel.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        self.validate_session().await?;
        if cancel.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        // A fresh ordinary validation is still valid without an explicit caller
        // operation, but cannot be reused by another operation or browser lane.
        if self.operation_parent != *cancel || self.browser_authority.is_some() {
            return Ok(None);
        }
        Ok(Some(FreshSessionHandoff {
            issuer: self.task_watch_authority.clone(),
            network: self.inventory_network.clone(),
            network_revision: self.inventory_network.load(Ordering::SeqCst),
            credential_revision: self.credential_revision,
            generation: self.generation,
            operation_epoch: self.fresh_auth.operation_epoch,
            caller: cancel.clone(),
            binding: self.fresh_auth_binding()?,
            validated_at: Instant::now(),
        }))
    }
    /// Arm only the first recovery socket. Stale/foreign evidence is discarded
    /// and the normal socket path validates again. Cancellation/expiry fails
    /// closed. The adapter must finish its protected-account/durable admission
    /// before consuming this value; no native profile discovery lives here.
    pub fn use_fresh_session_for_recovery(
        &mut self,
        handoff: FreshSessionHandoff,
        cancel: &CancellationToken,
    ) -> Result<()> {
        self.fresh_auth.pending = None;
        self.require_credentials()?;
        if cancel.is_cancelled() || self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if handoff.caller == *cancel && self.fresh_auth_matches(&handoff, Instant::now())? {
            self.fresh_auth.pending = Some(handoff);
        }
        Ok(())
    }
    /// Permission reduction only for the owned NORMAL-auth route. Discarding
    /// an optimization never consults another ordinary child's cancellation,
    /// authenticates, resets a token or waives the caller's full scope checks.
    pub(super) fn discard_fresh_handoff_for_owned_normal_auth(&mut self){
        self.fresh_auth.pending.take();
    }
    pub(super) fn take_fresh_session_for_recovery(&mut self, recovery: bool) -> Result<bool> {
        // Every socket attempt consumes/discards the armed handoff, including
        // unsupported socket modes and failed connection attempts.
        let Some(handoff) = self.fresh_auth.pending.take() else {
            return Ok(false);
        };
        self.require_credentials()?;
        if self.operation_cancel.is_cancelled()
            || self.operation_parent.is_cancelled()
            || handoff.caller.is_cancelled()
        {
            return Err(Error::Cancelled);
        }
        if !recovery
            || self
                .completion_recovery_mode
                .as_ref()
                .is_none_or(CancellationToken::is_cancelled)
        {
            return Ok(false);
        }
        self.fresh_auth_matches(&handoff, Instant::now())
    }
    fn fresh_auth_matches(&self, handoff: &FreshSessionHandoff, now: Instant) -> Result<bool> {
        self.require_credentials()?;
        Ok(!handoff.issuer.cancel.is_cancelled()
            && !handoff.caller.is_cancelled()
            && !self.operation_cancel.is_cancelled()
            && !self.operation_parent.is_cancelled()
            && self.operation_parent == handoff.caller
            && Arc::ptr_eq(&handoff.issuer, &self.task_watch_authority)
            && Arc::ptr_eq(&handoff.network, &self.inventory_network)
            && self.inventory_network.load(Ordering::SeqCst) == handoff.network_revision
            && self.credential_revision == handoff.credential_revision
            && self.generation == handoff.generation
            && self.fresh_auth.operation_epoch == handoff.operation_epoch
            && now
                .checked_duration_since(handoff.validated_at)
                .is_some_and(|age| age <= MAX_HANDOFF_AGE)
            && self.browser_authority.is_none()
            && self.fresh_auth_binding()? == handoff.binding)
    }
    pub(super) fn fresh_auth_binding(&self) -> Result<[u8;32]> {
        if self.browser_credentials.is_none(){return self.native_fresh_auth_binding();}
        let scope=self.require_credentials()?;
        let master=self.master_capability()?;
        let principal=self.user["id"].as_str().filter(|id|!id.is_empty()).or_else(||self.user["user_id"].as_str().filter(|id|!id.is_empty())).ok_or(Error::Protocol)?;
        let encoded=Zeroizing::new(serde_json::to_vec(&("browser-opaque-credential-context-v1",self.browser_local_read_only,scope,master.instance_binding(),self.generation,&self.cookies,principal,self.base.as_str(),self.app_url(),self.options.identity.header(),self.options.interactive))?);
        master.ensure_current()?;
        Ok(Sha256::digest(encoded.as_slice()).into())
    }
    fn native_fresh_auth_binding(&self) -> Result<[u8; 32]> {
        let session = self.require_session()?;
        let principal = self.user["id"]
            .as_str()
            .filter(|id| !id.is_empty())
            .or_else(|| self.user["user_id"].as_str().filter(|id| !id.is_empty()))
            .ok_or(Error::Protocol)?;
        // Exact session includes API/master/Team/session identity, ws token,
        // paired deadline and cookies. Also bind the live transport cookie jar,
        // canonical origin, app origin, SDK identity and foreground declaration.
        let encoded = Zeroizing::new(serde_json::to_vec(&(
            session,
            &self.cookies,
            principal,
            self.base.as_str(),
            self.app_url(),
            self.options.identity.header(),
            self.options.interactive,
        ))?);
        Ok(Sha256::digest(encoded.as_slice()).into())
    }
}
#[cfg(test)]
#[path = "auth_handoff_tests.rs"]
mod tests;
