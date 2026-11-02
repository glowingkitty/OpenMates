//! Authenticated original-context restore DATA before shared key/claim policy.
//! Issued only by the shared post-initial-auth hook; never a completion grant.
use super::*;
struct RestoreOrigin {context:Arc<OwnedRecoveryContext>,fence:RecoveryFence,master:MasterCapability,port:OriginalBrowserRecoveryPort,ticket:Arc<OriginalRecoveryCheckpointIoTicket>}
impl RestoreOrigin {
    fn negative(&self)->Result<()>{self.context.check_original_negative()?;self.fence.check()?;self.master.ensure_current()?;self.ticket.check_original_negative()?;self.port.check_negative()}
    fn check(&self,client:&Client)->Result<()>{self.context.check_row(client)?;self.fence.check_client(client)?;if !self.master.same_instance(&client.master_capability()?){return Err(Error::Cancelled)}self.port.check_original(client)?;self.ticket.check_original(client)?;self.negative()}
    async fn crypto<T>(&self,future:impl std::future::Future<Output=Result<T>>)->Result<T>{
        self.negative()?;
        let expiry=async{match self.fence.expires_at{Some(at)=>crate::platform::time::sleep(std::time::Duration::from_millis(at.saturating_sub(now_ms()))).await,None=>std::future::pending::<()>().await}};
        let result=tokio::select!{biased;_=self.context.cancel.cancelled()=>Err(Error::Cancelled),_=self.context.handoff.cancelled()=>Err(Error::Cancelled),_=self.fence.mode.cancelled()=>Err(Error::Cancelled),_=expiry=>Err(Error::Expired),result=future=>result};
        self.negative()?;result
    }
}
pub(in crate::client::completion_recovery::owned) struct OriginalRecoveryRestorePreparation {origin:RestoreOrigin}
pub(in crate::client::completion_recovery::owned) struct OriginalRecoveryRestoreReadiness {origin:RestoreOrigin,ready:Result<()>}
pub(in crate::client::completion_recovery::owned) struct OriginalRecoveryRestoreRead {origin:RestoreOrigin,native:NativeRecoveryPortPending}
pub(in crate::client::completion_recovery::owned) struct OriginalRecoveryRestoreReadResult {origin:RestoreOrigin,actual:Result<NativeRecoveryPortDelivery>}
pub(in crate::client::completion_recovery::owned) struct OriginalRecoveryRestoreCrypto {origin:RestoreOrigin,encoded:Option<String>}
pub(in crate::client::completion_recovery::owned) struct OriginalRecoveryRestoreDecoded {origin:RestoreOrigin,saved:Option<CompletionRecoveryCheckpoint>}
pub(in crate::client::completion_recovery::owned) fn prepare_restore(context:Arc<OwnedRecoveryContext>,client:&Client,port:OriginalBrowserRecoveryPort)->Result<OriginalRecoveryRestorePreparation>{
    context.check_row(client)?;port.check_original(client)?;
    let owner=owner(client)?;canonical_uuid(&owner)?;let operation_id=uuid::Uuid::new_v4().to_string();
    let effect=serde_json::to_string(&Effect::Read{version:1,operation_id:&operation_id,owner:&owner})?;
    let master=client.master_capability()?;let fence=context.fence.clone();
    let ticket=OriginalRecoveryCheckpointIoTicket::capture_original(context.clone(),fence.clone(),master.clone(),client,&operation_id,effect)?;
    let origin=RestoreOrigin{context,fence,master,port,ticket};origin.check(client)?;
    Ok(OriginalRecoveryRestorePreparation{origin})
}
impl OriginalRecoveryRestorePreparation {
    pub(in crate::client::completion_recovery::owned) async fn ready(self)->OriginalRecoveryRestoreReadiness{let ready=self.origin.crypto(self.origin.port.ready()).await;OriginalRecoveryRestoreReadiness{origin:self.origin,ready}}
}
impl OriginalRecoveryRestoreReadiness {
    pub(in crate::client::completion_recovery::owned) fn start(self,client:&Client)->Result<OriginalRecoveryRestoreRead>{
        self.ready?;self.origin.check(client)?;
        let native=self.origin.port.start(client,self.origin.ticket.clone())?;
        Ok(OriginalRecoveryRestoreRead{origin:self.origin,native})
    }
}
impl OriginalRecoveryRestoreRead {
    pub(in crate::client::completion_recovery::owned) async fn drive(self)->OriginalRecoveryRestoreReadResult{let actual=self.native.drive().await;OriginalRecoveryRestoreReadResult{origin:self.origin,actual}}
}
impl OriginalRecoveryRestoreReadResult {
    pub(in crate::client::completion_recovery::owned) fn readback(self,client:&Client)->Result<OriginalRecoveryRestoreCrypto>{
        self.origin.check(client)?;
        let encoded=self.actual?.consume_for(&self.origin.port,&self.origin.ticket)?;
        self.origin.negative()?;if let Some(encoded)=&encoded{bound_record(encoded)?;}
        Ok(OriginalRecoveryRestoreCrypto{origin:self.origin,encoded})
    }
}
impl OriginalRecoveryRestoreCrypto {
    pub(in crate::client::completion_recovery::owned) async fn drive(self)->Result<OriginalRecoveryRestoreDecoded>{
        self.origin.negative()?;
        let saved=match self.encoded.as_deref(){
            None=>None,
            Some(encoded)=>{let record=decode_record(encoded)?;let bytes=self.origin.crypto(self.origin.master.decrypt_bytes(&record.ciphertext)).await?;let mut map=decode_map_data(&bytes)?;map.remove(&self.origin.context.handoff.job().job_id)}
        };
        // Removal is from this transient decoded DATA map only, never storage.
        self.origin.negative()?;Ok(OriginalRecoveryRestoreDecoded{origin:self.origin,saved})
    }
}
impl OriginalRecoveryRestoreDecoded {
    pub(in crate::client::completion_recovery::owned) fn finish(self,client:&Client)->Result<Option<CompletionRecoveryCheckpoint>>{self.origin.check(client)?;self.origin.negative()?;Ok(self.saved)}
}
