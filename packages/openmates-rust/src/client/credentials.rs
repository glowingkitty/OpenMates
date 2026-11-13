//! Internal credential metadata is separate from master-key capability.
//! Public native Session wire/source layout is unchanged. Browser credentials
//! are never represented by a native Session or placeholder key material.
use super::*;
use crate::crypto::master::MasterCapability;
use zeroize::Zeroize;
pub(super) struct BrowserCredentials {
    pub(super) api_url: String,
    pub(super) session_id: String,
    pub(super) cookies: BTreeMap<String, String>,
    pub(super) ws_token: Option<String>,
    pub(super) master: MasterCapability,
    pub(super) hashed_email: String,
    pub(super) user_email_salt: String,
    pub(super) email_encryption_key: Option<String>,
    pub(super) created_at: u64,
    pub(super) paired_session_expires_at: Option<u64>,
    pub(super) active_team_id: Option<String>,
}
impl BrowserCredentials {
    pub(super) fn from_native_session(mut session: Session) -> Self {
        Self {
            api_url: std::mem::take(&mut session.api_url),
            session_id: std::mem::take(&mut session.session_id),
            cookies: std::mem::take(&mut session.cookies),
            ws_token: session.ws_token.take(),
            master: MasterCapability::from_browser_raw(session.master_key.clone()),
            hashed_email: std::mem::take(&mut session.hashed_email),
            user_email_salt: std::mem::take(&mut session.user_email_salt),
            email_encryption_key: session.email_encryption_key.take(),
            created_at: session.created_at,
            paired_session_expires_at: session.paired_session_expires_at,
            active_team_id: session.active_team_id.take(),
        }
    }
}
impl Drop for BrowserCredentials {
    fn drop(&mut self) {
        self.master.invalidate();
        self.api_url.zeroize();
        self.session_id.zeroize();
        self.ws_token.zeroize();
        self.hashed_email.zeroize();
        self.user_email_salt.zeroize();
        self.email_encryption_key.zeroize();
        self.active_team_id.zeroize();
        for cookie in self.cookies.values_mut() {
            cookie.zeroize();
        }
    }
}
/// Borrowed common transport metadata. This value cannot authenticate or import
/// a session; serde is used only inside Rust's zeroizing fresh-context digest.
#[derive(serde::Serialize)]
pub(super) struct CredentialScope<'a> {
    pub(super) api_url: &'a String,
    pub(super) session_id: &'a String,
    pub(super) cookies: &'a BTreeMap<String, String>,
    pub(super) ws_token: &'a Option<String>,
    pub(super) hashed_email: &'a String,
    pub(super) user_email_salt: &'a String,
    pub(super) email_encryption_key: &'a Option<String>,
    pub(super) created_at: u64,
    pub(super) paired_session_expires_at: Option<u64>,
    pub(super) active_team_id: &'a Option<String>,
}
impl<'a> From<&'a Session> for CredentialScope<'a> {
    fn from(session: &'a Session) -> Self {
        Self {
            api_url: &session.api_url,
            session_id: &session.session_id,
            cookies: &session.cookies,
            ws_token: &session.ws_token,
            hashed_email: &session.hashed_email,
            user_email_salt: &session.user_email_salt,
            email_encryption_key: &session.email_encryption_key,
            created_at: session.created_at,
            paired_session_expires_at: session.paired_session_expires_at,
            active_team_id: &session.active_team_id,
        }
    }
}
impl<'a> From<&'a BrowserCredentials> for CredentialScope<'a> {
    fn from(session: &'a BrowserCredentials) -> Self {
        Self {
            api_url: &session.api_url,
            session_id: &session.session_id,
            cookies: &session.cookies,
            ws_token: &session.ws_token,
            hashed_email: &session.hashed_email,
            user_email_salt: &session.user_email_salt,
            email_encryption_key: &session.email_encryption_key,
            created_at: session.created_at,
            paired_session_expires_at: session.paired_session_expires_at,
            active_team_id: &session.active_team_id,
        }
    }
}
/// Restricting local key binding; an opaque instance never attests account/key
/// ownership. Canonical server/key admission remains separate and mandatory.
pub(super) enum MasterBinding {
    Native(Key),
    Browser(MasterCapability),
}
impl MasterBinding {
    /// Restrictive captured-resource observation only. Native material has no
    /// separate resource instance; owner/context checks remain mandatory.
    pub(super) fn ensure_resource_current(&self) -> Result<()> {
        match self {
            Self::Native(_) => Ok(()),
            Self::Browser(master) => master.ensure_current(),
        }
    }
    pub(super) fn check(&self, client: &Client) -> Result<()> {
        match self {
            Self::Native(key) if client.browser_credentials.is_none() => {
                if client.require_session()?.master_key.as_ref() == key.as_ref() {
                    Ok(())
                } else {
                    Err(Error::Cancelled)
                }
            }
            Self::Browser(master) => {
                let current = client
                    .browser_credentials
                    .as_ref()
                    .ok_or(Error::Cancelled)?;
                if master.same_instance(&current.master) {
                    current.master.ensure_current()?;
                    Ok(())
                } else {
                    Err(Error::Cancelled)
                }
            }
            _ => Err(Error::Cancelled),
        }
    }
}
impl Client {
    pub(super) fn check_browser_credential_deadline(&self)->Result<()> {
        if !self.browser_cookies(){return Ok(());}
        let deadline=self.browser_credentials.as_ref().and_then(|credentials|credentials.paired_session_expires_at)
            .or_else(||self.session.as_ref().and_then(|session|session.paired_session_expires_at));
        if deadline.is_some_and(|deadline|deadline<=now_ms()){
            if let Some(credentials)=&self.browser_credentials{credentials.master.invalidate();}
            self.operation_cancel.cancel();self.task_watch_authority.cancel.cancel();self.browser_prepared_transport_cancel.cancel();
            if let Some(cancel)=&self.monitor_cancel{cancel.cancel();}
            if let Some(mode)=&self.completion_recovery_mode{mode.cancel();}
            return Err(Error::Expired);
        }
        Ok(())
    }
    pub(super) fn browser_operation_current(&self,token:&CancellationToken)->Result<()> {
        self.check_browser_credential_deadline()?;
        if token.is_cancelled()||self.operation_cancel.is_cancelled()||self.operation_cancel!=*token {return Err(Error::Cancelled);}
        Ok(())
    }
    // Prepared socket requests hold URLs containing an earlier WS token. Retire
    // those requests separately from a healthy running owner/monitor authority.
    pub(super) fn retire_browser_prepared_transports(&mut self) {
        self.browser_prepared_transport_cancel.cancel();
        self.browser_prepared_transport_cancel=CancellationToken::new();
    }
    pub(super) fn clear_browser_transport_grant(&mut self) {
        self.retire_browser_prepared_transports();
        if let Some(authority)=self.browser_authority.as_mut(){authority.owner_guards=false;}
        let mut changed=false;
        if let Some(browser)=self.browser_credentials.as_mut(){
            if let Some(token)=browser.ws_token.as_mut(){token.zeroize();changed=true;}
            browser.ws_token=None;
        }
        // Existing native unit protocol fixtures may model browser transport
        // with a real native Session; no dummy/placeholder key is introduced.
        if self.browser_cookies() && let Some(session)=self.session.as_mut(){
            if let Some(token)=session.ws_token.as_mut(){token.zeroize();changed=true;}
            session.ws_token=None;
        }
        if let Some(cancel)=self.monitor_cancel.take(){cancel.cancel();}
        if let Some(mode)=self.completion_recovery_mode.as_ref(){mode.cancel();}
        self.task_watch_authority=std::sync::Arc::new(self.task_watch_authority.revoke_transport_grant());
        if changed{self.credentials_changed();}
    }
    pub(super) fn enter_browser_local_read_only(&mut self) {
        self.browser_local_read_only=true;
        self.clear_browser_transport_grant();
        // clear_browser_transport_grant already revokes the same prepared and
        // running scopes for outage AND cancellation; encrypted data is retained.
    }

    pub(super) fn is_local_browser_profile(&self)->bool {
        self.browser_local_read_only&&self.browser_credentials.is_some()&&self.browser_authority.is_some()
    }
    /// Online browser session reading its own retained IndexedDB rows. This is
    /// a read-only cached view mode; it grants no local-profile or server authority.
    pub(super) fn is_online_browser_cache_profile(&self) -> bool {
        !self.browser_local_read_only
            && self.browser_transport
            && self.browser_credentials.is_some()
            && self.browser_authority.is_some()
    }

    pub(super) fn require_credentials(&self) -> Result<CredentialScope<'_>> {
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if let Some(original)=&self.browser_configured_native{original.check_client(self)?;}
        let scope = match (&self.session, &self.browser_credentials) {
            (Some(native), None) => CredentialScope::from(native),
            (None, Some(browser)) => CredentialScope::from(browser),
            (None, None) => return Err(Error::Authentication),
            _ => return Err(Error::Protocol), // two credential authorities are never admitted
        };
        if scope
            .paired_session_expires_at
            .is_some_and(|value| value <= now_ms())
        {
            self.check_browser_credential_deadline()?;
            return Err(Error::Expired);
        }
        if let Some(browser)=&self.browser_credentials {browser.master.ensure_current()?;}
        Ok(scope)
    }
    pub(super) fn master_capability(&self) -> Result<MasterCapability> {
        self.require_credentials()?;
        match &self.browser_credentials {
            Some(browser) => Ok(browser.master.clone()),
            None => Ok(MasterCapability::from_native(
                self.require_session()?.master_key.clone(),
            )),
        }
    }
    pub(super) fn native_master_key(&self) -> Result<&Key> {
        self.require_credentials()?;
        match &self.browser_credentials {
            Some(browser) => browser.master.native_key(),
            None => Ok(&self.require_session()?.master_key),
        }
    }
    pub(super) fn master_binding(&self) -> Result<MasterBinding> {
        self.require_credentials()?;
        match &self.browser_credentials {
            Some(browser) => Ok(MasterBinding::Browser(browser.master.clone())),
            None => Ok(MasterBinding::Native(
                self.require_session()?.master_key.clone(),
            )),
        }
    }
    pub(super) fn refresh_transport_token(&mut self, token: String) -> Result<()> {
        if let Some(browser) = self.browser_credentials.as_mut() {
            browser.ws_token = Some(token);
            return Ok(());
        }
        let native = self.session.as_mut().ok_or(Error::Expired)?;
        native.ws_token = Some(token);
        native.cookies = self.cookies.clone();
        Ok(())
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "credentials_tests.rs"]
mod tests;
