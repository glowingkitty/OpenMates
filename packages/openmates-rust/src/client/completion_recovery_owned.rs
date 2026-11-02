//! Original hint-bound owned recovery resources. No passive mode grant, copied
//! Client, checkpoint authority or caller-constructed row-transition receipt.
use super::*;
use super::super::owned_operation::OwnedOperationScope;
use super::super::OriginalHintRecoveryHandoff;
use std::sync::{Mutex,atomic::{AtomicBool,Ordering}};
#[path="completion_recovery_owned_active.rs"]
mod active;
pub(in crate::client) use active::{OriginalRecoveryActiveState,OriginalRecoveryActivePermit};
#[path="completion_recovery_owned_phase.rs"]
mod phase;
#[path="completion_recovery_owned_checkpoint.rs"]
mod checkpoint;
#[path="completion_recovery_owned_port_root.rs"]
mod port_root;
pub(crate) use port_root::BrowserRecoveryPortRoot;
pub(crate) use checkpoint::OriginalRecoveryCheckpointIoTicket;
pub(super) use checkpoint::OriginalRecoveryStorageProof;
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(in crate::client) use checkpoint::{OriginalMetadataRecoveryRetirement,OriginalMainRecoveryJournalObservation};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(crate) use checkpoint::OriginalRecoveryRetirementTicket;
#[cfg(target_arch="wasm32")]
pub(in crate::client) use checkpoint::{OriginalHintRecoveryDurableReceipt,OriginalRecoveryNativeWrite,OriginalRecoveryNativeWriteResult,OriginalRecoveryReadbackCrypto,OriginalRecoveryVerifiedWrite};
pub(in crate::client) use checkpoint::{PreparedOriginalRecoveryCheckpoint,OriginalRecoveryCheckpointCrypto,PreparedOriginalRecoveryCheckpointWrite,OriginalRecoveryPersistenceFailure};
pub(in crate::client) use phase::{OwnedRecoveryDriver,OwnedRecoveryApply,OwnedRecoveryIo,OwnedRecoveryResume,OwnedRecoveryStep,OwnedRecoveryControl};

pub(in crate::client) struct OwnedRecoveryPendingPersistence {context:Arc<OwnedRecoveryContext>,stage:Option<CompletionRecoveryStage>}
impl OwnedRecoveryPendingPersistence {
    #[cfg(test)]
    pub(in crate::client) fn original_boundary_for_test(&self,client:&Client)->Result<(Arc<OwnedOperationScope>,Arc<OriginalHintRecoveryHandoff>,Arc<OriginalRecoveryRowBoundary>)>{
        let boundary=self.context.canonical_boundary(client,self.context.cancel.clone(),self.stage.as_ref().ok_or(Error::Cancelled)?.fence.lease_expires_at)?;
        Ok((self.context.original.clone(),self.context.handoff.clone(),boundary))
    }
    pub(in crate::client) fn negative(&self)->Result<()> {self.context.check_negative()?;self.stage.as_ref().ok_or(Error::Cancelled)?.fence.check()}
    pub(in crate::client) fn check_original(&self,client:&Client)->Result<()> {self.context.check_row(client)?;self.stage.as_ref().ok_or(Error::Cancelled)?.fence.check_client(client)?;self.negative()}
    pub(in crate::client) fn checkpoint(&self)->Result<CompletionRecoveryCheckpoint>{
        self.negative()?;let value=self.stage.as_ref().ok_or(Error::Cancelled)?.checkpoint()?;self.negative()?;Ok(value)
    }
}
impl Drop for OwnedRecoveryPendingPersistence {fn drop(&mut self){if self.stage.is_some(){self.context.cancel.cancel();}}}
/// Exact current-row boundary for a genuine nested canonical read. It derives
/// no owner/key/foreground grant and cannot be manufactured from a row DTO.
pub(in crate::client) struct OriginalRecoveryRowBoundary {
    context:Arc<OwnedRecoveryContext>,request:CancellationToken,before:Option<Value>,
    sequence:u64,claimed:AtomicBool,lease_expires_at:Option<u64>,
}
impl OriginalRecoveryRowBoundary {
    pub(in crate::client) fn check_root(&self,client:&Client,scope:&Arc<OwnedOperationScope>,handoff:&Arc<OriginalHintRecoveryHandoff>)->Result<()> {
        if !Arc::ptr_eq(scope,&self.context.original)||!Arc::ptr_eq(handoff,&self.context.handoff){return Err(Error::Cancelled)}
        self.context.check_root(client)?;self.negative()
    }
    pub(in crate::client) fn check_before_io(&self,client:&Client,scope:&Arc<OwnedOperationScope>,handoff:&Arc<OriginalHintRecoveryHandoff>)->Result<()> {
        self.check_root(client,scope,handoff)?;self.context.check_row(client)?;
        let state=self.context.row.lock().map_err(|_|Error::Cancelled)?;
        if state.mutations!=self.sequence||client.chats.get(&handoff.job().chat_id)!=self.before.as_ref(){return Err(Error::Conflict)}
        drop(state);self.negative()
    }
    pub(in crate::client) fn claim_canonical_driver(&self,client:&Client,scope:&Arc<OwnedOperationScope>,handoff:&Arc<OriginalHintRecoveryHandoff>)->Result<()> {
        self.check_before_io(client,scope,handoff)?;
        self.claimed.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
        self.check_before_io(client,scope,handoff)
    }
    pub(in crate::client) fn before_row(&self)->&Option<Value>{&self.before}
    pub(in crate::client) fn negative(&self)->Result<()> {self.context.check_negative()?;if self.request.is_cancelled(){return Err(Error::Cancelled)}if self.lease_expires_at.is_some_and(|at|at<=now_ms()){return Err(Error::Conflict)}Ok(())}
    pub(in crate::client) async fn cancelled(&self){
        let expiry=async {match self.lease_expires_at{Some(at)=>crate::platform::time::sleep(std::time::Duration::from_millis(at.saturating_sub(now_ms()))).await,None=>std::future::pending::<()>().await}};
        tokio::select!{_=self.context.cancel.cancelled()=>{},_=self.request.cancelled()=>{},_=self.context.fence.mode.cancelled()=>{},_=self.context.handoff.cancelled()=>{},_=expiry=>{}}
    }
}
/// Actual transcript evidence only. No child/embed/store/full-hint proof.
pub(in crate::client) struct OwnedRecoveryArtifacts {
    handoff:Arc<OriginalHintRecoveryHandoff>,scope:Arc<OwnedOperationScope>,
    boundary:Arc<OriginalRecoveryRowBoundary>,request:CancellationToken,
    actual:super::super::sync::canonical_owned::OriginalCanonicalChatArtifacts,
}
impl OwnedRecoveryArtifacts {
    pub(in crate::client) fn coverage(&self)->&'static str{"transcript_ciphertext_rows_only"}
    pub(in crate::client) fn check_original(&self,client:&Client,handoff:&Arc<OriginalHintRecoveryHandoff>)->Result<()> {
        if !Arc::ptr_eq(handoff,&self.handoff){return Err(Error::Cancelled)}
        self.boundary.check_root(client,&self.scope,&self.handoff)?;
        let _=self.actual.checked_ciphertext_rows(client,&self.scope,&self.handoff,&self.boundary)?;
        self.boundary.negative()?;if self.request.is_cancelled(){return Err(Error::Cancelled)}Ok(())
    }
    pub(super) fn check_client(&self,client:&Client)->Result<()>{self.check_original(client,&self.handoff)}
    pub(in crate::client) fn checked_ciphertext_rows<'a>(&'a self,client:&'a Client,handoff:&Arc<OriginalHintRecoveryHandoff>)->Result<&'a [Value]> {
        self.check_original(client,handoff)?;
        let rows=self.actual.checked_ciphertext_rows(client,&self.scope,&self.handoff,&self.boundary)?;
        self.boundary.negative()?;if self.request.is_cancelled(){return Err(Error::Cancelled)}Ok(rows)
    }
}
struct RowState { before:Option<Value>,expected:Option<Value>,mutations:u64 }
struct OwnedRecoveryContext {
    handoff:Arc<OriginalHintRecoveryHandoff>,
    active_permit:OriginalRecoveryActivePermit,
    original:Arc<OwnedOperationScope>,
    fence:RecoveryFence,
    cancel:CancellationToken,
    row:Mutex<RowState>,
    issued:AtomicBool,
}
impl Drop for OwnedRecoveryContext {fn drop(&mut self){self.cancel.cancel();}}
impl OwnedRecoveryContext {
    fn check_original_negative(&self)->Result<()>{
        self.handoff.check_original_negative()?;self.original.crypto.check_original_operation_negative()?;self.fence.check()?;
        if self.cancel.is_cancelled(){return Err(Error::Cancelled)}Ok(())
    }
    fn check_negative(&self)->Result<()> {
        self.handoff.negative()?;
        self.original.observer().check_release()?;
        self.fence.check()?;
        if self.cancel.is_cancelled(){return Err(Error::Cancelled)}
        // The final policy callback may revoke original resources synchronously.
        self.handoff.negative()?;
        self.fence.check()
    }
    fn check_root(&self,client:&Client)->Result<()> {
        self.handoff.check_root(client)?;
        self.original.check(client)?;
        self.fence.check_client(client)?;
        self.check_negative()
    }
    fn check_row(&self,client:&Client)->Result<()> {
        self.check_root(client)?;
        let row=self.row.lock().map_err(|_|Error::Cancelled)?;
        if client.chats.get(&self.handoff.job().chat_id)!=row.expected.as_ref(){return Err(Error::Conflict)}
        drop(row);
        self.check_negative()
    }
    fn cache_key_row(&self,client:&mut Client,id:String,row:Value,selected:Option<phase_key::SelectedRecoveryWrapper>)->Result<()> {
        if id!=self.handoff.job().chat_id{return Err(Error::Cancelled)}
        let row=if let Some(previous)=client.chats.get(&id){
            client.merge_original_physical_draft_cache(&self.original,&id,&row,previous,Some(previous))?
        }else{row};
        bound_row(&row)?;
        self.check_row(client)?;
        let mut state=self.row.lock().map_err(|_|Error::Cancelled)?;
        if client.chats.get(&id)!=state.expected.as_ref(){return Err(Error::Conflict)}
        if let Some(selected)=&selected{selected.check_publication(&id,&row,client.team()?)?;}
        // Exact original current-key cache publication. Other chat wrappers stay.
        client.wrappers.retain(|wrapper|text(wrapper,"hashed_chat_id")!=sha256(&id));
        client.wrappers.extend(row["chat_key_wrappers"].as_array().into_iter().flatten().cloned());
        client.insert_chat_row(id.clone(),row);
        state.expected=client.chats.get(&id).cloned();
        state.mutations=state.mutations.checked_add(1).ok_or(Error::Protocol)?;
        drop(state);
        self.check_row(client)
    }
    fn insert_metadata_row(&self,client:&mut Client,id:String,row:Value)->Result<()> {
        if id!=self.handoff.job().chat_id{return Err(Error::Cancelled)}
        let row=if let Some(previous)=client.chats.get(&id){
            client.merge_original_physical_draft_cache(&self.original,&id,&row,previous,Some(previous))?
        }else{row};
        bound_row(&row)?;self.check_row(client)?;
        let mut state=self.row.lock().map_err(|_|Error::Cancelled)?;
        if client.chats.get(&id)!=state.expected.as_ref(){return Err(Error::Conflict)}
        client.insert_chat_row(id.clone(),row);
        state.expected=client.chats.get(&id).cloned();
        state.mutations=state.mutations.checked_add(1).ok_or(Error::Protocol)?;
        drop(state);self.check_row(client)
    }
    fn canonical_boundary(self:&Arc<Self>,client:&Client,request:CancellationToken,lease_expires_at:Option<u64>)->Result<Arc<OriginalRecoveryRowBoundary>> {
        self.check_row(client)?;if request.is_cancelled(){return Err(Error::Cancelled)}
        let state=self.row.lock().map_err(|_|Error::Cancelled)?;
        let boundary=Arc::new(OriginalRecoveryRowBoundary{context:self.clone(),request,before:state.expected.clone(),sequence:state.mutations,claimed:AtomicBool::new(false),lease_expires_at});
        drop(state);boundary.check_before_io(client,&self.original,&self.handoff)?;Ok(boundary)
    }
    fn transition(self:&Arc<Self>,client:&Client,result:&OriginalForegroundRecoveryResult,request:CancellationToken,storage:Option<Arc<OriginalRecoveryStorageProof>>)->Result<OriginalRecoveryRowTransition> {
        // This nonserializable value only comes from the actual shared
        // canonical-terminal/commit path, never stage/DTO/ACK-only status.
        if request.is_cancelled(){return Err(Error::Cancelled)}
        result.check_original(client)?;
        if !same_checkpoint_job(result.job(),self.handoff.job())
            ||result.fence.operation!=self.cancel||result.fence.mode!=self.fence.mode
            ||!Arc::ptr_eq(&result.fence.authority,&self.fence.authority){return Err(Error::Cancelled)}
        self.check_row(client)?;
        if let Some(proof)=&storage{proof.check_original(client)?;}
        let state=self.row.lock().map_err(|_|Error::Cancelled)?;
        if state.mutations==0{return Err(Error::Protocol)}
        let after=client.chats.get(&self.handoff.job().chat_id).cloned();
        if after!=state.expected{return Err(Error::Conflict)}
        let witness=OriginalRecoveryRowTransition {context:self.clone(),request,job:self.handoff.job().clone(),before:state.before.clone(),after,mutations:state.mutations,storage};
        drop(state);self.check_negative()?;witness.check_original_negative()?;Ok(witness)
    }
}
fn bound_row(row:&Value)->Result<()> {
    let encoded=zeroize::Zeroizing::new(serde_json::to_vec(row)?);
    if encoded.len()>super::super::transport::MAX_BODY{return Err(Error::Protocol)}Ok(())
}
/// Minted only after the SAME recovery operation's actual row mutations and
/// canonical-terminal/commit result. No public constructor, Clone or serde.
pub(in crate::client) struct OriginalRecoveryRowTransition {
    context:Arc<OwnedRecoveryContext>,request:CancellationToken,job:CompletionRecoveryJob,
    before:Option<Value>,after:Option<Value>,mutations:u64,storage:Option<Arc<OriginalRecoveryStorageProof>>,
}
impl OriginalRecoveryRowTransition {
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn cancel_local_retirement(&self){self.context.cancel.cancel();}
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn prepare_metadata_retirement(&self,client:&Client)->Result<OriginalMetadataRecoveryRetirement>{
        self.check_client(client)?;
        OriginalMetadataRecoveryRetirement::capture(self.storage.clone().ok_or(Error::Unavailable{code:"recovery_checkpoint_origin_unavailable",reason:"ORIGINAL_DURABLE_CHECKPOINT_REQUIRED"})?,client)
    }
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn prepare_main_metadata_journal(&self,client:&Client)->Result<OriginalMainRecoveryJournalObservation>{
        self.check_client(client)?;
        OriginalMainRecoveryJournalObservation::capture(self.storage.clone().ok_or(Error::Unavailable{code:"recovery_checkpoint_origin_unavailable",reason:"ORIGINAL_DURABLE_CHECKPOINT_REQUIRED"})?,client)
    }
    pub(in crate::client) fn check_original_negative(&self)->Result<()>{
        self.context.check_original_negative()?;
        if self.request.is_cancelled(){return Err(Error::Cancelled)}
        if let Some(proof)=&self.storage{proof.check_negative()?;}
        Ok(())
    }
    pub(in crate::client) fn check_original(&self,client:&Client,handoff:&Arc<OriginalHintRecoveryHandoff>)->Result<()> {
        if !Arc::ptr_eq(&self.context.handoff,handoff)||self.context.cancel.is_cancelled()||self.request.is_cancelled()||self.mutations==0{return Err(Error::Cancelled)}
        self.context.check_root(client)?;
        if let Some(proof)=&self.storage{proof.check_original(client)?;}
        if client.chats.get(&self.job.chat_id)!=self.after.as_ref(){return Err(Error::Conflict)}
        self.context.check_negative()?;
        self.check_original_negative()
    }
    pub(super) fn check_client(&self,client:&Client)->Result<()>{self.check_original(client,&self.context.handoff)}
    pub(in crate::client) fn job(&self)->&CompletionRecoveryJob{&self.job}
    pub(in crate::client) fn before(&self)->Option<&Value>{self.before.as_ref()}
    pub(in crate::client) fn after(&self)->Option<&Value>{self.after.as_ref()}
}
/// Single original resource; must be consumed into the actual owned driver.
/// Preparation itself starts no HTTP/socket/storage and mints no completion.
pub(in crate::client) struct PreparedOwnedRecovery { context:Option<Arc<OwnedRecoveryContext>>,saved:Option<CompletionRecoveryCheckpoint>,
    #[cfg(target_arch="wasm32")] checkpoint_port:Option<crate::platform::browser_recovery_port::OriginalBrowserRecoveryPort>,
}
impl PreparedOwnedRecovery {
    #[cfg(target_arch="wasm32")]
    pub(in crate::client) fn with_checkpoint_port(mut self,client:&Client,port:crate::platform::browser_recovery_port::OriginalBrowserRecoveryPort)->Result<Self>{
        let context=self.context.as_ref().ok_or(Error::Cancelled)?;
        context.check_row(client)?;port.check_original(client)?;context.check_original_negative()?;port.check_negative()?;
        self.checkpoint_port=Some(port);Ok(self)
    }
}
impl Drop for PreparedOwnedRecovery {fn drop(&mut self){if let Some(context)=&self.context{context.cancel.cancel();}}}
impl Client {
    pub(in crate::client) fn prepare_original_owned_recovery(&mut self,handoff:Arc<OriginalHintRecoveryHandoff>,saved:Option<CompletionRecoveryCheckpoint>)->Result<PreparedOwnedRecovery>{
        handoff.check_before_io(self)?;
        validate_job(handoff.job())?;
        let original=handoff.scope_arc();
        original.check(self)?;
        // Derivation only narrows this operation. It cannot cancel the hint's
        // original sibling, its parent, or an unrelated active saved send A.
        let cancel=original.child().child_token();
        let fence=self.recovery_fence_with_operation(&cancel,cancel.clone())?;
        let active_permit=handoff.claim_core_driver(self)?;
        let before=self.chats.get(&handoff.job().chat_id).cloned();
        if let Some(row)=&before{bound_row(row)?;}
        handoff.check_before_io(self)?;original.check(self)?;fence.check_client(self)?;
        let context=Arc::new(OwnedRecoveryContext {handoff,active_permit,original,fence,cancel,row:Mutex::new(RowState{before:before.clone(),expected:before,mutations:0}),issued:AtomicBool::new(false)});
        context.check_row(self)?;
        Ok(PreparedOwnedRecovery{context:Some(context),saved,#[cfg(target_arch="wasm32")] checkpoint_port:None})
    }
}
