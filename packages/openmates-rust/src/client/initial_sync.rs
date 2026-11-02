//! Explicit first-party initial synchronization on an actual original monitor.
//! Operation selection is intent, not authentication or a native commit/ACK.
//! No implicit CLI, selected-open, reconnect or metadata-only auth upgrade.
use super::*;
use crate::client::owned_operation::OwnedOperationScope;
use crate::client::plaintext::Plain;
use std::sync::Arc;

/// Original queued startup IO. No Client/auth lock is borrowed while waiting.
/// The actor privately issues its one-use intent only after actual dispatch.
pub struct PreparedInitialSync {
    pending:Option<PreparedMonitorRead>,original:Arc<OwnedOperationScope>,monitor:Arc<ChatMonitor>,
}
/// Clones retain only the same original negative cancellation/current checks.
/// They cannot issue a command, replace intent or release metadata/ACK.
#[derive(Clone)]
pub struct InitialSyncControl {original:Arc<OwnedOperationScope>,monitor:Arc<ChatMonitor>}
impl InitialSyncControl {
    pub(in crate::client) async fn cancelled(&self){self.original.cancelled().await}
    pub(in crate::client) fn check_original_negative(&self)->Result<()>{
        self.original.observer().check_release()?;
        if !self.monitor.is_valid(){return Err(Error::Cancelled)}Ok(())
    }
    pub fn cancel(&self){self.original.observer().cancel();}
    pub fn ensure_current(&self,client:&Client)->Result<()>{check(client,&self.original,&self.monitor)}
}
impl PreparedInitialSync {
    pub fn control(&self)->InitialSyncControl {InitialSyncControl{original:self.original.clone(),monitor:self.monitor.clone()}}
    /// Cancellation affects this original operation, never another startup.
    pub fn cancel(&self){self.original.observer().cancel();}
    pub fn ensure_current(&self,client:&Client)->Result<()>{check(client,&self.original,&self.monitor)}
    /// Await actual existing socket/request/response IO. Err/Drop never asserts
    /// physical/global/native settlement or releases a full-hint completion.
    pub async fn wait(mut self)->Result<InitialSyncRead>{
        let receipt=self.pending.take().ok_or(Error::Conflict)?.wait().await?;
        Ok(InitialSyncRead{receipt:Some(receipt),original:self.original,monitor:self.monitor})
    }
}
/// Actual one-use original actor receipt. Neither JSON nor a caller-provided
/// readiness flag can construct this resource or attach a replacement Client.
pub struct InitialSyncRead {
    receipt:Option<MonitorReadReceipt>,original:Arc<OwnedOperationScope>,monitor:Arc<ChatMonitor>,
}
impl InitialSyncRead {
    pub fn cancel(&self){self.original.observer().cancel();}
    pub fn ensure_current(&self,client:&Client)->Result<()>{check(client,&self.original,&self.monitor)}
    /// Retain opaque received metadata under the original scope. This performs
    /// no Client merge, physical store, decryption, UI publication or hint ACK.
    pub fn retain(mut self,client:&Client)->Result<InitialSyncMetadataBatch>{
        self.ensure_current(client)?;
        let receipt=self.receipt.take().ok_or(Error::Conflict)?;
        let MonitorReadData::RecentSync(data)=receipt.take(client,&self.monitor,&self.original)?else{return Err(Error::Protocol)};
        check(client,&self.original,&self.monitor)?;
        Ok(InitialSyncMetadataBatch{data,original:self.original,monitor:self.monitor})
    }
}
/// Retained actual-source DATA. Per-row native IO/source binding is still
/// required before persistence. No public row DTO or IO-grant getter exists.
pub struct InitialSyncMetadataBatch {
    data:Plain<crate::client::sync::SyncPhaseReadData>,original:Arc<OwnedOperationScope>,monitor:Arc<ChatMonitor>,
}
impl InitialSyncMetadataBatch {
    pub(in crate::client) fn retained_navigation_bytes(&self)->Result<usize>{self.data.retained_navigation_bytes()}
    pub(in crate::client) fn original_control(&self)->InitialSyncControl{InitialSyncControl{original:self.original.clone(),monitor:self.monitor.clone()}}
    pub(in crate::client) fn original_rows(&self)->(&BTreeMap<String,Value>,&[String],&BTreeSet<String>){(&self.data.chats,&self.data.chat_arrival_order,&self.data.expanded_only_chat_ids)}
    pub(in crate::client) fn original_team(&self)->Option<&str>{self.monitor.fence.team.as_deref()}
    pub fn cancel(&self){self.original.observer().cancel();}
    pub fn ensure_current(&self,client:&Client)->Result<()>{check(client,&self.original,&self.monitor)}
    /// Observed count only, never account coverage, storage/readiness or ACK.
    pub fn received_metadata_count(&self,client:&Client)->Result<usize>{self.ensure_current(client)?;Ok(self.data.chats.len())}
}
fn check(client:&Client,original:&OwnedOperationScope,monitor:&ChatMonitor)->Result<()>{
    original.check(client)?;client.check_chat_monitor_fence(&monitor.fence)?;original.check(client)
}
impl Client {
    /// Explicit initial-sync operation on the supplied genuine authenticated
    /// monitor. Its first actual command boundary is enforced inside the actor.
    /// Existing ordinary CLI/selected-read methods never invoke this operation.
    pub fn prepare_initial_sync(&self,monitor:Arc<ChatMonitor>,request:CancellationToken)->Result<PreparedInitialSync>{
        let original=Arc::new(OwnedOperationScope::capture(self,request)?);
        check(self,&original,&monitor)?;
        // Exclusions are actual retained Client navigation DATA, not grants or
        // proof that IndexedDB has committed them. No extra inventory is fetched.
        let existing=self.chats.keys().cloned().collect();
        let pending=self.prepare_monitor_read(&monitor,&original,MonitorReadRequest::InitialStartup(existing))?;
        check(self,&original,&monitor)?;
        Ok(PreparedInitialSync{pending:Some(pending),original,monitor})
    }
}
