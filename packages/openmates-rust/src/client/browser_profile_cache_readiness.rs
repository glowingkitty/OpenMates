//! Narrow local-only continuation of a previously authenticated ORIGINAL Client.
//! Capture before a refresh retires general owner guards. No bootstrap/profile
//! DTO, server authority, cold fallback, persistence or general CryptoRoot escape.
use super::*;

/// Opaque original profile/credential/negative lineage, not a server-auth ticket.
/// Its scope is private and can be used only by the closed readonly local path.
#[doc(hidden)]
pub struct BrowserProfileCacheReadiness {pub(super) scope:Arc<OwnedOperationScope>,owner:String}
impl BrowserProfileCacheReadiness {
    pub fn ensure_current(&self,client:&Client)->Result<()> {
        self.scope.check(client)?;
        if client.browser_credentials.is_none()||client.user["id"].as_str()!=Some(self.owner.as_str())
            ||!client.browser_authority.as_ref().is_some_and(|a|a.principal==self.owner)
            ||client.is_local_browser_profile()||client.team()?.is_some(){return Err(Error::Cancelled)}
        self.scope.observer().check_release()
    }
    pub fn cancel(&self){self.scope.observer().cancel();}
    /// Negative notification only, so the selected local UI can clear promptly
    /// on original auth denial, key/parent retirement or profile invalidation.
    pub async fn wait_invalidated(&self){self.scope.cancelled().await;}
}
impl Client {
    /// This can only be issued after actual browser restore/login validated the
    /// original Client. A fresh unvalidated bootstrap has no such authority.
    #[doc(hidden)]
    pub fn prepare_browser_profile_cache_readiness(&self)->Result<Arc<BrowserProfileCacheReadiness>> {
        self.require_canonical_read_profile()?;self.require_browser_owner_guards()?;
        let owner=required(&self.user,"id")?.to_owned();
        if self.browser_credentials.is_none()||self.team()?.is_some()
            ||self.require_credentials()?.ws_token.is_none()
            ||!self.browser_authority.as_ref().is_some_and(|a|a.principal==owner){return Err(Error::Forbidden)}
        let scope=Arc::new(OwnedOperationScope::capture(self,CancellationToken::new())?);
        let result=Arc::new(BrowserProfileCacheReadiness{scope,owner});result.ensure_current(self)?;Ok(result)
    }
    /// Only readonly original native cursors and a bounded local projection.
    /// Cache absence is typed Offline; it cannot start HTTP or adopt an auth grant.
    #[doc(hidden)]
    pub fn begin_owned_browser_profile_cache_read(&mut self,readiness:Arc<BrowserProfileCacheReadiness>,request:CancellationToken,
        owner:&str,chat:&str,options:crate::client::message_window::MessageWindowOptions,
        host:BrowserMetadataCacheScope,now_seconds:u64,include_private_output:bool,
    )->Result<OwnedBrowserReadDriver>{
        readiness.ensure_current(self)?;
        if readiness.owner!=owner{return Err(Error::Forbidden)}
        self.begin_owned_browser_message_read(BeginMode::ProfileCache(readiness),request,owner,chat,options,host,now_seconds,include_private_output)
    }
}
