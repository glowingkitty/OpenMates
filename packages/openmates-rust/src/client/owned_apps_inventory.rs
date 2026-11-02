//! Fixed existing Apps inventory. Same result projection, endpoint and flags as
//! Client::list(Apps); separate original sibling, no private-operation prerequisite.
use super::*;
use super::owned_operation::OwnedOperationLease;
use super::sync_capability::AsyncCryptoScope;
use super::plaintext::Plain;
use super::transport::{self,OwnedReadRoute,PreparedOwnedRead,OwnedReadHeaders,OwnedReadBody,CompletedOwnedRead};
use std::sync::Arc;
use zeroize::Zeroizing;
struct Scope {crypto:AsyncCryptoScope,lease:Option<OwnedOperationLease>,request:CancellationToken}
impl Scope {
    fn check(&self,client:&Client)->Result<()> {
        client.require_canonical_read_profile()?;self.crypto.check(client)?;self.negative()
    }
    fn negative(&self)->Result<()> {
        if self.request.is_cancelled(){return Err(Error::Cancelled)}
        self.crypto.check_original_operation_negative()
    }
    async fn cancelled(&self){tokio::select!{biased;_=self.request.cancelled()=>{},_=self.crypto.original_operation_cancelled()=>{}}}
}
impl Drop for Scope {fn drop(&mut self){self.request.cancel();if let Some(lease)=&self.lease{lease.cancel();}}}
#[derive(Clone)]
#[doc(hidden)]
pub struct OwnedAppsInventoryControl {scope:Arc<Scope>}
impl OwnedAppsInventoryControl {
    /// Negative only: retires this B request, never A or the ordinary Client lane.
    pub fn cancel(&self){self.scope.request.cancel();if let Some(lease)=&self.scope.lease{lease.cancel();}}
}
#[doc(hidden)]
pub struct PreparedOwnedAppsInventory {scope:Arc<Scope>,request:PreparedOwnedRead}
#[doc(hidden)]
pub struct OwnedAppsInventoryHeaders {scope:Arc<Scope>,headers:OwnedReadHeaders}
#[doc(hidden)]
pub struct OwnedAppsInventoryBody {scope:Arc<Scope>,body:OwnedReadBody}
#[doc(hidden)]
pub struct CompletedOwnedAppsInventory {scope:Arc<Scope>,body:CompletedOwnedRead}
/// Exact original scope and wiping shared projection, no raw constructor/Clone.
#[doc(hidden)]
pub struct AppsInventoryPublication {scope:Arc<Scope>,items:Plain<Vec<Item>>}
impl PreparedOwnedAppsInventory {
    pub fn control(&self)->OwnedAppsInventoryControl{OwnedAppsInventoryControl{scope:self.scope.clone()}}
    pub async fn receive_headers(self)->Result<OwnedAppsInventoryHeaders>{
        let Self{scope,request}=self;
        let headers=tokio::select!{biased;_=scope.cancelled()=>return Err(Error::Cancelled),
            value=transport::send_owned_read_headers(request,&scope.request,||scope.negative())=>value?};
        // Received headers MUST reach the actual Client before any new local
        // cancellation check; their real rotation cannot be rolled back.
        Ok(OwnedAppsInventoryHeaders{scope,headers})
    }
}
impl OwnedAppsInventoryBody {
    pub async fn receive_body(self)->Result<CompletedOwnedAppsInventory>{
        let Self{scope,body}=self;
        let body=tokio::select!{biased;_=scope.cancelled()=>return Err(Error::Cancelled),
            value=transport::drive_owned_read_body(body,&scope.request,||scope.negative())=>value?};
        Ok(CompletedOwnedAppsInventory{scope,body})
    }
}
impl AppsInventoryPublication {
    pub fn check(&self,client:&Client)->Result<()>{self.scope.check(client)}
    pub fn encode_json(&self,client:&Client)->Result<Zeroizing<String>>{
        self.check(client)?;
        let encoded=Zeroizing::new(serde_json::to_string(&*self.items)?);
        self.check(client)?;Ok(encoded)
    }
    pub fn take_items(mut self,client:&Client)->Result<Vec<Item>>{
        self.check(client)?;Ok(std::mem::take(&mut *self.items))
    }
}
impl Client {
    /// None means this legacy imported session has no admitted principal yet.
    /// Only that exact compatibility case uses the old serialized list path.
    /// A denied/expired/changed owned context always returns Err, never fallback.
    #[doc(hidden)]
    pub fn prepare_owned_apps_inventory(&mut self,request:CancellationToken)->Result<Option<PreparedOwnedAppsInventory>>{
        self.require_canonical_read_profile()?;
        let owner=self.user["id"].as_str().filter(|v|!v.is_empty())
            .or_else(||self.user["user_id"].as_str().filter(|v|!v.is_empty()));
        if owner.is_none(){
            // Existing native imported-session case only. A missing browser
            // owner or any retained owned lease is an error, never fallback.
            self.require_session()?;
            if self.browser_cookies(){return Err(Error::Protocol)}
            self.owned_operations.require_empty_import_compatibility()?;
            return Ok(None)
        }
        let original=AsyncCryptoScope::begin(self)?;
        let lease=self.owned_operations.issue(&self.operation_parent,request.clone(),self.credential_revision,
            self.owned_operations.checked_auth_binding(self)?)?;
        let crypto=original.into_owned(self,lease.clone())?;
        let scope=Arc::new(Scope{crypto,lease:Some(lease),request});scope.check(self)?;
        let prepared=self.prepare_owned_read(OwnedReadRoute::AppsInventory)?;scope.check(self)?;
        Ok(Some(PreparedOwnedAppsInventory{scope,request:prepared}))
    }
    /// Synchronous matched-header merge. No body/IO await under Client.
    #[doc(hidden)]
    pub fn apply_owned_apps_inventory_headers(&mut self,headers:OwnedAppsInventoryHeaders)->Result<OwnedAppsInventoryBody>{
        let OwnedAppsInventoryHeaders{scope,headers}=headers;
        // Ignore ONLY this already-dispatched B child's/request's stop while
        // applying matched real credentials. Parent/owner/key/denial stay strict.
        scope.crypto.check_dispatched_credential_observation(self)?;
        let body=self.apply_owned_read_headers(headers)?;
        scope.check(self)?;
        Ok(OwnedAppsInventoryBody{scope,body})
    }
    #[doc(hidden)]
    pub fn finish_owned_apps_inventory(&mut self,completed:CompletedOwnedAppsInventory)->Result<AppsInventoryPublication>{
        let CompletedOwnedAppsInventory{scope,body}=completed;scope.check(self)?;
        let value=Plain::new(self.finish_owned_read(body)?.ok_or(Error::Protocol)?);
        scope.check(self)?;
        let items=Plain::new(super::workspaces::app_inventory_items(&value)?);
        scope.check(self)?;Ok(AppsInventoryPublication{scope,items})
    }
    /// Legacy no-principal compatibility only: actual original list, unchanged
    /// authentication/network behavior. Its result still retains final guards.
    #[doc(hidden)]
    pub async fn list_apps_inventory_compatibility(&mut self,request:CancellationToken)->Result<AppsInventoryPublication>{
        if request.is_cancelled(){return Err(Error::Cancelled)}
        let items=Plain::new(self.list(Workspace::Apps).await?);
        let scope=Arc::new(Scope{crypto:AsyncCryptoScope::begin(self)?,lease:None,request});
        scope.check(self)?;Ok(AppsInventoryPublication{scope,items})
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="owned_apps_inventory_tests.rs"]
mod tests;
