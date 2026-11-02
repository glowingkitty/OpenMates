//! Exact original journal candidate retirement after actual metadata CAS/readback.
//! No server commit, generic receipt import, main-artifact or whole-hint ACK.
use super::*;
use crate::platform::browser_recovery_port::{OriginalBrowserRecoveryPort,NativeRecoveryPortDelivery};
use zeroize::Zeroizing;

pub(in crate::client) struct OriginalMetadataRecoveryRetirement {
    proof:Arc<OriginalRecoveryStorageProof>,anchor:Arc<()>,read_issued:AtomicBool,write_issued:AtomicBool,
    expected:Option<Zeroizing<String>>,next:Option<Zeroizing<String>>,readback:Option<Zeroizing<String>>,verified:bool,
}
/// This resource is born only from the original Client-captured commit proof.
/// The port's detached start cannot accept a JSON effect or ordinary IO ticket.
pub(crate) struct OriginalRecoveryRetirementTicket {proof:Arc<OriginalRecoveryStorageProof>,ticket:Arc<OriginalRecoveryCheckpointIoTicket>}
impl OriginalRecoveryRetirementTicket {
    pub(crate) fn check_negative(&self)->Result<()>{self.proof.check_negative()?;self.ticket.check_original_negative()}
    pub(crate) fn check_port(&self,port:&OriginalBrowserRecoveryPort)->Result<()>{if !self.proof.port.same_original(port){return Err(Error::Cancelled)}self.check_negative()}
    pub(crate) fn original_ticket(&self)->&Arc<OriginalRecoveryCheckpointIoTicket>{&self.ticket}
}
impl OriginalMetadataRecoveryRetirement {
    pub(in crate::client) fn capture(proof:Arc<OriginalRecoveryStorageProof>,client:&Client)->Result<Self>{
        Self::capture_kind(proof,client,CompletionRecoveryKind::Metadata)
    }
    fn capture_kind(proof:Arc<OriginalRecoveryStorageProof>,client:&Client,kind:CompletionRecoveryKind)->Result<Self>{
        proof.check_original(client)?;
        if proof.checkpoint.job.kind!=kind||proof.checkpoint.team_id().is_some(){return Err(Error::Forbidden)}
        if proof.checkpoint.owner_id()!=owner(client)?||proof.checkpoint.api_url()!=client.base.as_str().trim_end_matches('/'){return Err(Error::Forbidden)}
        Ok(Self{proof,anchor:Arc::new(()),read_issued:AtomicBool::new(false),write_issued:AtomicBool::new(false),expected:None,next:None,readback:None,verified:false})
    }
    pub(in crate::client) fn anchor(&self)->Arc<()>{self.anchor.clone()}
    pub(in crate::client) fn check(&self,client:&Client)->Result<()>{self.proof.check_original(client)}
    pub(in crate::client) fn negative(&self)->Result<()>{self.proof.check_negative()}
    fn ticket(&self,effect:Effect<'_>,operation:&str)->Result<OriginalRecoveryRetirementTicket>{
        self.negative()?;
        let old=&self.proof.ticket;
        let ticket=Arc::new(OriginalRecoveryCheckpointIoTicket{context:old.context.clone(),fence:old.fence.clone(),master:old.master.clone(),operation_id:operation.into(),effect:serde_json::to_string(&effect)?,dispatched:AtomicBool::new(false)});
        let value=OriginalRecoveryRetirementTicket{proof:self.proof.clone(),ticket};value.check_negative()?;Ok(value)
    }
    async fn receive(&self,ticket:&OriginalRecoveryRetirementTicket)->Result<NativeRecoveryPortDelivery>{
        self.negative()?;let port=&self.proof.port;
        // Native pending keeps the actual started port operation until its own
        // terminal even after cancellation. No select-drop/drain invention.
        let actual=port.start_metadata_retirement(ticket)?.drive().await?;
        self.negative()?;Ok(actual)
    }
    pub(in crate::client) async fn read_matching(&mut self)->Result<()>{
        self.negative()?;self.read_issued.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
        let operation=uuid::Uuid::new_v4().to_string();let owner=self.proof.checkpoint.owner_id();
        let ticket=self.ticket(Effect::Read{version:1,operation_id:&operation,owner},&operation)?;
        let delivery=self.receive(&ticket).await?;
        self.expected=Some(Zeroizing::new(delivery.consume_for(&self.proof.port,&ticket.ticket)?.ok_or(Error::Conflict)?));
        let record=decode_record(self.expected.as_ref().ok_or(Error::Conflict)?)?;
        let bytes=self.proof.ticket.master.decrypt_bytes(&record.ciphertext).await?;self.negative()?;
        let map=decode_map_data(&bytes)?;
        matching_checkpoint(&map,&self.proof.checkpoint)?;
        Ok(())
    }
    pub(in crate::client) async fn retire(&mut self,physical:&crate::client::browser::MetadataRecoveryPhysicalProof)->Result<()>{
        self.negative()?;physical.check_retirement(&self.anchor)?;
        self.write_issued.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
        let expected=self.expected.as_ref().ok_or(Error::Conflict)?;
        let record=decode_record(expected)?;
        let bytes=self.proof.ticket.master.decrypt_bytes(&record.ciphertext).await?;
        self.negative()?;physical.check_retirement(&self.anchor)?;
        let mut map=decode_map_data(&bytes)?;
        remove_matching_checkpoint(&mut map,&self.proof.checkpoint)?;
        let bytes=encode_map(&map)?;
        let ciphertext=self.proof.ticket.master.encrypt_server_bytes(&bytes).await?;
        self.negative()?;physical.check_retirement(&self.anchor)?;
        let next=Zeroizing::new(serde_json::to_string(&Record{version:1,ciphertext})?);bound_record(&next)?;
        self.next=Some(next);
        let next=self.next.as_ref().ok_or(Error::Conflict)?;
        let operation=uuid::Uuid::new_v4().to_string();
        let ticket=self.ticket(Effect::CompareAndPut{version:1,operation_id:&operation,owner:self.proof.checkpoint.owner_id(),expected:Some(expected),next},&operation)?;
        let delivery=self.receive(&ticket).await?;
        self.readback=Some(Zeroizing::new(delivery.consume_for(&self.proof.port,&ticket.ticket)?.ok_or(Error::Protocol)?));
        let actual=self.readback.as_ref().ok_or(Error::Conflict)?;
        if actual.as_str()!=next.as_str(){return Err(Error::Conflict)}
        let actual_record=decode_record(&actual)?;
        let actual_bytes=self.proof.ticket.master.decrypt_bytes(&actual_record.ciphertext).await?;
        self.negative()?;physical.check_retirement(&self.anchor)?;
        drop(decode_map_data(&actual_bytes)?);
        if actual_bytes.as_slice()!=bytes.as_slice(){return Err(Error::Conflict)}
        self.verified=true;Ok(())
    }
    pub(in crate::client) fn verified(&self,client:&Client)->Result<()>{self.check(client)?;if !self.verified{return Err(Error::Conflict)}self.negative()}
}

/// Actual original Main checkpoint read only. Metadata storage cannot retire
/// Main while transcript/artifact native durability remains unproved.
pub(in crate::client) struct OriginalMainRecoveryJournalObservation {
    inner:OriginalMetadataRecoveryRetirement,matched:bool,
}
impl OriginalMainRecoveryJournalObservation {
    pub(in crate::client) fn capture(proof:Arc<OriginalRecoveryStorageProof>,client:&Client)->Result<Self>{
        Ok(Self{inner:OriginalMetadataRecoveryRetirement::capture_kind(proof,client,CompletionRecoveryKind::Main)?,matched:false})
    }
    pub(in crate::client) fn negative(&self)->Result<()>{self.inner.negative()}
    pub(in crate::client) async fn read_matching(&mut self)->Result<()>{
        self.inner.read_matching().await?;self.inner.negative()?;self.matched=true;Ok(())
    }
    pub(in crate::client) fn ensure_current(&self,client:&Client)->Result<()>{
        self.inner.check(client)?;if !self.matched{return Err(Error::Conflict)}self.inner.negative()
    }
    // No write/retire/receipt/record accessor or public constructor.
}
