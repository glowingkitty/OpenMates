//! Negative original browser-root binding for the actual private native port.
//! No foreground mode, operation/read grant, key export or mutable rebind.
use super::*;
pub(crate) struct BrowserRecoveryPortRoot {
    binding:Arc<super::super::super::credentials::MasterBinding>,master:MasterCapability,
    authority:Arc<WatchAuthority>,parent:CancellationToken,generation:u64,
    credential_context:String,owner_context:String,denial_revision:u64,expires_at:Option<u64>,
    api_url:String,session_id:String,principal:String,team:Option<String>,
    private_gate:Option<Arc<dyn Fn()->Result<()>+Send+Sync>>,
}
fn owner_context(client:&Client)->Result<String>{Ok(sha256(&serde_json::to_string(&(&client.user["id"],&client.user["user_id"],&client.user["username"]))?))}
impl Client {
    pub(crate) fn capture_browser_recovery_port_root(&self)->Result<BrowserRecoveryPortRoot>{
        self.require_canonical_read_profile()?;
        self.verify_private_operation()?;
        if self.browser_credentials.is_none(){return Err(Error::Authentication)}
        let credentials=self.require_credentials()?;
        let principal=super::super::owner(self)?;canonical_uuid(&principal)?;
        let root=BrowserRecoveryPortRoot {
            binding:Arc::new(self.master_binding()?),master:self.master_capability()?,authority:self.task_watch_authority.clone(),parent:self.operation_parent.clone(),generation:self.generation,
            credential_context:recovery_credential_context(self)?,owner_context:owner_context(self)?,denial_revision:self.task_watch_authority.cached_denial_revision()?,expires_at:credentials.paired_session_expires_at,
            api_url:self.browser_transport_api_identity(),session_id:credentials.session_id.as_str().to_owned(),principal,team:self.team()?.map(str::to_owned),private_gate:self.options.private_operation_gate.clone(),
        };
        root.check_original(self)?;Ok(root)
    }
}
impl BrowserRecoveryPortRoot {
    /// Callback-free original resources only; always combine with actual Ticket.
    pub(crate) fn check_negative(&self)->Result<()>{
        self.binding.ensure_resource_current()?;self.master.ensure_current()?;
        if self.parent.is_cancelled()||self.authority.cancel.is_cancelled()||self.authority.try_cached_denial_revision()?!=self.denial_revision||self.expires_at.is_some_and(|at|at<=now_ms()){return Err(Error::Cancelled)}Ok(())
    }
    /// Original caller gate followed by callback-free original negatives.
    pub(crate) fn check_release(&self)->Result<()>{
        self.check_negative()?;if let Some(gate)=&self.private_gate{gate()?;}self.check_negative()
    }
    pub(crate) fn check_original(&self,client:&Client)->Result<()>{
        self.check_negative()?;client.require_canonical_read_profile()?;
        if client.browser_credentials.is_none(){return Err(Error::Cancelled)}
        self.binding.check(client)?;
        let credentials=client.require_credentials()?;
        if !self.master.same_instance(&client.master_capability()?)||!Arc::ptr_eq(&self.authority,&client.task_watch_authority)||self.parent!=client.operation_parent||self.generation!=client.generation
            ||self.credential_context!=recovery_credential_context(client)?||self.owner_context!=owner_context(client)?||self.principal!=super::super::owner(client)?||self.team.as_deref()!=client.team()?
            ||self.api_url!=client.browser_transport_api_identity()||self.session_id.as_str()!=credentials.session_id.as_str()||!super::super::super::same_private_gate(&self.private_gate,&client.options.private_operation_gate){return Err(Error::Cancelled)}
        client.verify_private_operation()?;
        self.check_negative()
    }
    /// Bootstrap fields restrict this actual resource; they never mint it.
    pub(crate) fn check_bootstrap(&self,api_url:&str,session_id:&str,expected_principal:&str)->Result<()>{
        self.check_negative()?;
        if api_url.trim_end_matches('/')!=self.api_url||session_id!=self.session_id||expected_principal!=self.principal{return Err(Error::Cancelled)}
        self.check_negative()
    }
    pub(crate) async fn cancelled(&self){
        let expiry=async{match self.expires_at{Some(at)=>crate::platform::time::sleep(std::time::Duration::from_millis(at.saturating_sub(now_ms()))).await,None=>std::future::pending::<()>().await}};
        tokio::select!{_=self.parent.cancelled()=>{},_=self.authority.cancel.cancelled()=>{},_=self.master.cancelled()=>{},_=expiry=>{}}
    }
}
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="completion_recovery/owned_port_root_tests.rs"]
mod tests;
