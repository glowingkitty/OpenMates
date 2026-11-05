//! Thin fixed inventory adapter. All route/projection/scope/header policy is Core.
use super::*;
use openmates_sdk::client::AppsInventoryPublication;
use super::work::{WorkGuard,work_authority};
pub(crate) struct AppsInventoryOutput {state:Arc<State>,guard:Arc<WorkGuard>,publication:AppsInventoryPublication}
impl AppsInventoryOutput {
    pub(crate) fn encode_with<T>(self,encode:impl FnOnce(&str)->Result<T>)->Result<T>{
        work_authority(&self.guard)?;
        // Safe owned B bypasses ONLY the legacy lane; original scope still
        // checks actual current credentials/owner/key/denial at final allocation.
        let client=self.state.client.try_lock().map_err(|_|BindingError::from(Error::Conflict))?;
        self.publication.check(&client).map_err(BindingError::from)?;
        let encoded=self.publication.encode_json(&client).map_err(BindingError::from)?;
        work_authority(&self.guard)?;
        let value=encode(&encoded)?;
        self.publication.check(&client).map_err(BindingError::from)?;
        work_authority(&self.guard)?;Ok(value)
    }
    pub(super) fn release_json(self)->Result<String>{
        let mut value=self.encode_with(|text|Ok(Zeroizing::new(text.to_owned())))?;
        Ok(std::mem::take(&mut *value))
    }
}
pub(crate) struct PreparedAppsInventory {bridge:SessionBridge,guard:Arc<WorkGuard>}
impl PreparedAppsInventory {
    pub(crate) fn cancellation_request(&self)->CancellationToken{self.guard.token()}
    pub(crate) async fn run(self)->Result<AppsInventoryOutput>{self.bridge.apps_inventory_prepare_admitted(self.guard).await}
}
struct Caller {guard:Arc<WorkGuard>,returned:bool}
impl Drop for Caller {fn drop(&mut self){if !self.returned{self.guard.cancel();}}}
impl SessionBridge {
    pub(crate) fn prepare_apps_inventory(&self)->Result<PreparedAppsInventory>{
        Ok(PreparedAppsInventory{bridge:self.clone(),guard:Arc::new(self.admit_work()?)})
    }
    pub(super) async fn apps_inventory_prepare(&self)->Result<AppsInventoryOutput>{self.prepare_apps_inventory()?.run().await}
    pub(super) async fn apps_inventory_prepare_admitted(&self,guard:Arc<WorkGuard>)->Result<AppsInventoryOutput>{
        work_authority(&guard)?;
        let mut caller=Caller{guard:guard.clone(),returned:false};
        let state=self.state.clone();let output_state=state.clone();let worker=guard.clone();
        let result=self.transaction(async move{
            work_authority(&worker)?;
            let prepared={
                let mut client=state.client.lock().await;work_authority(&worker)?;
                client.prepare_owned_apps_inventory(worker.token()).map_err(BindingError::from)?
            };
            let publication=if let Some(prepared)=prepared{
                let headers=prepared.receive_headers().await.map_err(BindingError::from)?;
                // Real matched headers apply BEFORE rechecking local caller
                // cancellation. Core retains actual rotations for both A and B.
                let body={let mut client=state.client.lock().await;
                    client.apply_owned_apps_inventory_headers(headers).map_err(BindingError::from)?};
                let completed=body.receive_body().await.map_err(BindingError::from)?;
                let mut client=state.client.lock().await;work_authority(&worker)?;
                client.finish_owned_apps_inventory(completed).map_err(BindingError::from)?
            }else{
                // Preserve imported-session/no-principal behavior through the
                // SAME original stream drain/legacy lane; no failure fallback.
                let mut client=Self::live_client(&state).await?;work_authority(&worker)?;
                client.list_apps_inventory_compatibility(worker.token()).await.map_err(BindingError::from)?
            };
            work_authority(&worker)?;
            Ok(AppsInventoryOutput{state:output_state,guard:worker,publication})
        }).await;
        work_authority(&guard)?;caller.returned=true;result
    }
    #[cfg(any(feature="napi-bindings",feature="python-bindings",test))]
    pub(crate) fn capture_apps_inventory_prepare(&self)->impl Future<Output=Result<AppsInventoryOutput>>+Send+'static{
        let prepared=self.prepare_apps_inventory();
        async move{prepared?.run().await}
    }
}
