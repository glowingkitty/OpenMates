//! Actual native private-port delivery only. No callback/JSON/status constructor.
use super::*;
use crate::platform::browser_recovery_port::{OriginalBrowserRecoveryPort,NativeRecoveryPortPending,NativeRecoveryPortDelivery};
type PersistenceResult<T>=std::result::Result<T,OriginalRecoveryPersistenceFailure>;
pub(in crate::client) struct OriginalRecoveryNativeWrite {write:PreparedOriginalRecoveryCheckpointWrite,port:OriginalBrowserRecoveryPort,ticket:Arc<OriginalRecoveryCheckpointIoTicket>,native:NativeRecoveryPortPending}
pub(in crate::client) struct OriginalRecoveryNativeWriteResult {write:PreparedOriginalRecoveryCheckpointWrite,port:OriginalBrowserRecoveryPort,ticket:Arc<OriginalRecoveryCheckpointIoTicket>,actual:Result<NativeRecoveryPortDelivery>}
pub(in crate::client) struct OriginalRecoveryReadbackCrypto {write:PreparedOriginalRecoveryCheckpointWrite,proof:Arc<OriginalRecoveryStorageProof>,encoded:String}
pub(in crate::client) struct OriginalRecoveryVerifiedWrite {write:PreparedOriginalRecoveryCheckpointWrite,proof:Arc<OriginalRecoveryStorageProof>}
/// Only actual native terminal +full decrypted map/readback can mint this.
pub(in crate::client) struct OriginalHintRecoveryDurableReceipt {pending:OwnedRecoveryPendingPersistence,proof:Arc<OriginalRecoveryStorageProof>,digest:String}
impl PreparedOriginalRecoveryCheckpointWrite {
    /// Caller awaits actual port.ready OUTSIDE Client first. Full original
    /// checks/one claim/nativepost happen synchronously in this short phase.
    pub(in crate::client) fn start_native(self,client:&Client,port:&OriginalBrowserRecoveryPort)->PersistenceResult<OriginalRecoveryNativeWrite>{
        let ticket=match self.write_ticket(client){Ok(value)=>value,Err(error)=>return Err(OriginalRecoveryPersistenceFailure::from_write(self,error))};
        let native=match port.start(client,ticket.clone()){Ok(value)=>value,Err(error)=>return Err(OriginalRecoveryPersistenceFailure::from_write(self,error))};
        Ok(OriginalRecoveryNativeWrite{write:self,port:port.clone(),ticket,native})
    }
}
impl OriginalRecoveryNativeWrite {
    /// Always returns original Stage, including port loss/unknown terminal.
    pub(in crate::client) async fn drive(self)->OriginalRecoveryNativeWriteResult{
        let actual=self.native.drive().await;
        OriginalRecoveryNativeWriteResult{write:self.write,port:self.port,ticket:self.ticket,actual}
    }
}
impl OriginalRecoveryNativeWriteResult {
    pub(in crate::client) fn readback(self,client:&Client)->PersistenceResult<OriginalRecoveryReadbackCrypto>{
        let Self{write,port,ticket,actual}=self;
        let checked=(||{write.check_original(client)?;port.check_original(client)?;ticket.check_original(client)?;port.check_negative()})();
        if let Err(error)=checked{return Err(OriginalRecoveryPersistenceFailure::from_write(write,error))}
        // This value has no public constructor: only the genuine SAME native
        // private-port event path can supply it. DATA checks below add policy.
        let delivery=match actual{Ok(value)=>value,Err(error)=>return Err(OriginalRecoveryPersistenceFailure::from_write(write,error))};
        let encoded=match delivery.consume_for(&port,&ticket){Ok(Some(value))=>value,Ok(None)=>return Err(OriginalRecoveryPersistenceFailure::from_write(write,Error::Protocol)),Err(error)=>return Err(OriginalRecoveryPersistenceFailure::from_write(write,error))};
        let proof=Arc::new(OriginalRecoveryStorageProof{port,ticket,#[cfg(feature="browser-metadata-prototype")]checkpoint:write.prepared.checkpoint.clone()});
        Ok(OriginalRecoveryReadbackCrypto{write,proof,encoded})
    }
}
impl OriginalRecoveryReadbackCrypto {
    pub(in crate::client) async fn drive(self)->PersistenceResult<OriginalRecoveryVerifiedWrite>{
        let Self{write,proof,encoded}=self;
        let result=async{proof.check_negative()?;write.verify_readback_data(&encoded).await?;proof.check_negative()}.await;
        match result{Ok(())=>Ok(OriginalRecoveryVerifiedWrite{write,proof}),Err(error)=>Err(OriginalRecoveryPersistenceFailure::from_write(write,error))}
    }
}
impl OriginalRecoveryVerifiedWrite {
    pub(in crate::client) fn finish(self,client:&Client)->PersistenceResult<OriginalHintRecoveryDurableReceipt>{
        let Self{write,proof}=self;
        let result=(||{write.check_original(client)?;proof.check_original(client)?;proof.check_negative()})();
        if let Err(error)=result{return Err(OriginalRecoveryPersistenceFailure::from_write(write,error))}
        let digest=write.prepared.digest.clone();
        Ok(OriginalHintRecoveryDurableReceipt{pending:write.prepared.pending,proof,digest})
    }
}
impl OriginalHintRecoveryDurableReceipt {
    pub(in crate::client) fn into_driver(self,client:&Client)->PersistenceResult<OwnedRecoveryDriver>{
        let Self{mut pending,proof,digest}=self;
        let prepared=(||{pending.check_original(client)?;proof.check_original(client)?;
            if pending.checkpoint()?.digest()?!=digest{return Err(Error::Conflict)}proof.check_negative()?;
            super::super::phase::prepare_commit_driver(client,pending.context.clone(),pending.stage.as_ref().ok_or(Error::Cancelled)?,proof)
        })();
        let prepared=match prepared{Ok(value)=>value,Err(error)=>return Err(OriginalRecoveryPersistenceFailure::from_pending(pending,error))};
        let stage=match pending.stage.take(){Some(value)=>value,None=>return Err(OriginalRecoveryPersistenceFailure::from_pending(pending,Error::Cancelled))};
        match prepared.into_driver(stage,CompletionRecoveryDurableReceipt{checkpoint_sha256:digest}){
            Ok(driver)=>Ok(driver),Err((stage,error))=>{pending.stage=Some(stage);Err(OriginalRecoveryPersistenceFailure::from_pending(pending,error))}
        }
    }
}

#[path="completion_recovery_owned_checkpoint_restore.rs"]
mod restore;
pub(in crate::client::completion_recovery::owned) use restore::{prepare_restore,OriginalRecoveryRestorePreparation,OriginalRecoveryRestoreReadiness,OriginalRecoveryRestoreRead,OriginalRecoveryRestoreReadResult,OriginalRecoveryRestoreCrypto,OriginalRecoveryRestoreDecoded};
