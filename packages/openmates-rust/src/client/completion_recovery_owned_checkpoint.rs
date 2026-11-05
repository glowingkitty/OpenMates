//! Fixed existing-KV encrypted checkpoint preparation. Ciphertext/read plans
//! remain DATA. No raw readback/status/hash path can mint a durable receipt.
use super::*;
use serde::{Deserialize,Serialize};
#[cfg(target_arch="wasm32")]
#[path="completion_recovery_owned_checkpoint_native.rs"]
mod native;
#[cfg(target_arch="wasm32")]
pub(super) use native::{prepare_restore,OriginalRecoveryRestorePreparation,OriginalRecoveryRestoreReadiness,OriginalRecoveryRestoreRead,OriginalRecoveryRestoreReadResult,OriginalRecoveryRestoreCrypto,OriginalRecoveryRestoreDecoded};
#[cfg(target_arch="wasm32")]
pub(in crate::client) use native::{OriginalHintRecoveryDurableReceipt,OriginalRecoveryNativeWrite,OriginalRecoveryNativeWriteResult,OriginalRecoveryReadbackCrypto,OriginalRecoveryVerifiedWrite};
/// Retained actual native storage provenance; never constructible from DATA.
pub(in crate::client) struct OriginalRecoveryStorageProof {
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))] checkpoint:CompletionRecoveryCheckpoint,
    #[cfg(target_arch="wasm32")] port:crate::platform::browser_recovery_port::OriginalBrowserRecoveryPort,
    #[cfg(target_arch="wasm32")] ticket:Arc<OriginalRecoveryCheckpointIoTicket>,
    #[cfg(not(target_arch="wasm32"))] _unavailable:(),
}
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
#[path="completion_recovery_owned_retirement.rs"]
mod retirement;
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(in crate::client) use retirement::{OriginalMetadataRecoveryRetirement,OriginalMainRecoveryJournalObservation};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(crate) use retirement::OriginalRecoveryRetirementTicket;
impl OriginalRecoveryStorageProof {
    pub(super) fn check_negative(&self)->Result<()>{
        #[cfg(target_arch="wasm32")] {self.port.check_negative()?;self.ticket.check_original_negative()?;self.port.check_negative()}
        #[cfg(not(target_arch="wasm32"))] {Err(Error::Cancelled)}
    }
    pub(super) fn check_original(&self,client:&Client)->Result<()>{
        #[cfg(target_arch="wasm32")] {self.port.check_original(client)?;self.ticket.check_original(client)?;self.check_negative()}
        #[cfg(not(target_arch="wasm32"))] {let _=client;Err(Error::Cancelled)}
    }
}
const MAX_RECORD_BYTES:usize=32*1024*1024;
const STORE_KEY:&str="openmates_rust_pending_recovery_v1";
#[derive(Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
struct Record {version:u8,ciphertext:String}
#[derive(Serialize)]
#[serde(tag="operation",rename_all="snake_case")]
enum Effect<'a>{
    Read{version:u8,#[serde(rename="operationId")]operation_id:&'a str,owner:&'a str},
    CompareAndPut{version:u8,#[serde(rename="operationId")]operation_id:&'a str,owner:&'a str,expected:Option<&'a str>,next:&'a str},
}
/// Every consuming preparation/IO refusal retains the SAME original Stage.
/// Error/Drop carries no settlement, retry, rearm or quiescence authority.
pub(in crate::client) struct OriginalRecoveryPersistenceFailure {pending:OwnedRecoveryPendingPersistence,error:Error}
impl std::fmt::Debug for OriginalRecoveryPersistenceFailure {fn fmt(&self,f:&mut std::fmt::Formatter<'_>)->std::fmt::Result{f.write_str("OriginalRecoveryPersistenceFailure")}}
impl OriginalRecoveryPersistenceFailure {
    fn from_pending(pending:OwnedRecoveryPendingPersistence,error:Error)->Self{Self{pending,error}}
    fn from_prepared(prepared:PreparedOriginalRecoveryCheckpoint,error:Error)->Self{Self::from_pending(prepared.pending,error)}
    fn from_write(write:PreparedOriginalRecoveryCheckpointWrite,error:Error)->Self{Self::from_prepared(write.prepared,error)}
    pub(in crate::client) fn error(&self)->&Error{&self.error}
    pub(in crate::client) fn into_pending(self)->OwnedRecoveryPendingPersistence{self.pending}
}
/// Original stage/master capture. Never a persistence/foreground grant.
pub(in crate::client) struct PreparedOriginalRecoveryCheckpoint {
    pending:OwnedRecoveryPendingPersistence,master:MasterCapability,
    checkpoint:CompletionRecoveryCheckpoint,digest:String,operation_id:String,read_issued:AtomicBool,
}
/// Detached crypto owns only original resources and ciphertext DATA.
pub(in crate::client) struct OriginalRecoveryCheckpointCrypto {
    prepared:PreparedOriginalRecoveryCheckpoint,expected:Option<String>,
}
/// Immutable full-record compare-and-put plan; still no durable receipt.
pub(in crate::client) struct PreparedOriginalRecoveryCheckpointWrite {
    prepared:PreparedOriginalRecoveryCheckpoint,expected:Option<String>,next:String,operation_id:String,write_issued:AtomicBool,
}
/// Actual native IO admission, issued by an original prepared resource.
/// Native platform port accepts this opaque resource, never arbitrary effects.
pub(crate) struct OriginalRecoveryCheckpointIoTicket {
    context:Arc<OwnedRecoveryContext>,fence:RecoveryFence,master:MasterCapability,
    operation_id:String,effect:String,dispatched:AtomicBool,
}
impl OriginalRecoveryCheckpointIoTicket {
    fn capture(prepared:&PreparedOriginalRecoveryCheckpoint,client:&Client,operation_id:&str,effect:String)->Result<Arc<Self>>{
        prepared.check_original(client)?;
        Self::capture_original(prepared.pending.context.clone(),prepared.pending.stage.as_ref().ok_or(Error::Cancelled)?.fence.clone(),prepared.master.clone(),client,operation_id,effect)
    }
    fn capture_original(context:Arc<OwnedRecoveryContext>,fence:RecoveryFence,master:MasterCapability,client:&Client,operation_id:&str,effect:String)->Result<Arc<Self>>{
        context.check_row(client)?;fence.check_client(client)?;
        let ticket=Arc::new(Self{context,fence,master,operation_id:operation_id.into(),effect,dispatched:AtomicBool::new(false)});
        ticket.check_original(client)?;Ok(ticket)
    }
    pub(crate) fn effect(&self)->&str{&self.effect}
    pub(crate) fn operation_id(&self)->&str{&self.operation_id}
    pub(crate) fn check_original_negative(&self)->Result<()>{
        self.context.handoff.check_original_negative()?;self.master.ensure_current()?;self.fence.check()?;
        if self.context.cancel.is_cancelled(){return Err(Error::Cancelled)}Ok(())
    }
    pub(crate) fn check_original(&self,client:&Client)->Result<()>{
        self.context.check_row(client)?;self.fence.check_client(client)?;
        if !self.master.same_instance(&client.master_capability()?){return Err(Error::Cancelled)}
        self.check_original_negative()
    }
    pub(crate) fn claim_dispatch(&self)->Result<()>{
        self.check_original_negative()?;
        self.dispatched.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
        self.check_original_negative()
    }
    pub(crate) async fn cancelled(&self){
        let expiry=async{match self.fence.lease_expires_at{Some(at)=>crate::platform::time::sleep(std::time::Duration::from_millis(at.saturating_sub(now_ms()))).await,None=>std::future::pending::<()>().await}};
        tokio::select!{_=self.context.cancel.cancelled()=>{},_=self.context.handoff.cancelled()=>{},_=self.fence.mode.cancelled()=>{},_=self.master.cancelled()=>{},_=expiry=>{}}
    }
}
impl OwnedRecoveryPendingPersistence {
    pub(in crate::client) fn prepare_checkpoint_persistence(self,client:&Client)->std::result::Result<PreparedOriginalRecoveryCheckpoint,OriginalRecoveryPersistenceFailure>{
        let checked=(||{self.check_original(client)?;let checkpoint=self.checkpoint()?;
            if checkpoint.owner_id()!=owner(client)?||checkpoint.api_url()!=client.base.as_str().trim_end_matches('/')||checkpoint.team_id()!=client.team()?{return Err(Error::Forbidden)}
            let master=client.master_capability()?;self.check_original(client)?;let digest=checkpoint.digest()?;Ok((checkpoint,master,digest))})();
        match checked{Ok((checkpoint,master,digest))=>Ok(PreparedOriginalRecoveryCheckpoint{pending:self,master,checkpoint,digest,operation_id:uuid::Uuid::new_v4().to_string(),read_issued:AtomicBool::new(false)}),Err(error)=>Err(OriginalRecoveryPersistenceFailure::from_pending(self,error))}
    }
}
impl PreparedOriginalRecoveryCheckpoint {
    pub(in crate::client) fn into_pending(self)->OwnedRecoveryPendingPersistence{self.pending}
    pub(in crate::client) fn read_ticket(&self,client:&Client)->Result<Arc<OriginalRecoveryCheckpointIoTicket>>{
        let effect=self.read_effect(client)?;
        self.read_issued.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
        OriginalRecoveryCheckpointIoTicket::capture(self,client,&self.operation_id,effect)
    }
    fn negative(&self)->Result<()>{self.master.ensure_current()?;self.pending.negative()}
    async fn crypto<T>(&self,future:impl std::future::Future<Output=Result<T>>)->Result<T>{
        self.negative()?;
        let stage=self.pending.stage.as_ref().ok_or(Error::Cancelled)?;
        let expiry=async{match stage.fence.lease_expires_at{Some(at)=>crate::platform::time::sleep(std::time::Duration::from_millis(at.saturating_sub(now_ms()))).await,None=>std::future::pending::<()>().await}};
        let result=tokio::select!{biased;
            _=self.pending.context.cancel.cancelled()=>Err(Error::Cancelled),
            _=self.pending.context.handoff.cancelled()=>Err(Error::Cancelled),
            _=stage.fence.mode.cancelled()=>Err(Error::Cancelled),
            _=expiry=>Err(Error::Conflict),result=future=>result,
        };
        self.negative()?;result
    }
    fn check_original(&self,client:&Client)->Result<()>{
        self.pending.check_original(client)?;
        if !self.master.same_instance(&client.master_capability()?){return Err(Error::Cancelled)}
        self.negative()
    }
    /// Plan serialization conveys ciphertext IO intent only, never IO success.
    pub(in crate::client) fn read_effect(&self,client:&Client)->Result<String>{
        self.check_original(client)?;
        let value=serde_json::to_string(&Effect::Read{version:1,operation_id:&self.operation_id,owner:self.checkpoint.owner_id()})?;
        self.check_original(client)?;Ok(value)
    }
    /// Received record is untrusted DATA. Native CAS must still compare these
    /// exact full bytes to the actual current row before any durable receipt.
    pub(in crate::client) fn with_read_data(self,client:&Client,expected:Option<String>)->std::result::Result<OriginalRecoveryCheckpointCrypto,OriginalRecoveryPersistenceFailure>{
        let checked=(||{self.check_original(client)?;if let Some(value)=&expected{bound_record(value)?;}Ok(())})();
        match checked{Ok(())=>Ok(OriginalRecoveryCheckpointCrypto{prepared:self,expected}),Err(error)=>Err(OriginalRecoveryPersistenceFailure::from_prepared(self,error))}
    }
}
impl OriginalRecoveryCheckpointCrypto {
    pub(in crate::client) fn into_pending(self)->OwnedRecoveryPendingPersistence{self.prepared.pending}
    pub(in crate::client) async fn drive(self)->std::result::Result<PreparedOriginalRecoveryCheckpointWrite,OriginalRecoveryPersistenceFailure>{
        let Self{prepared,expected}=self;
        let encoded:Result<String>=async{
            prepared.negative()?;
            let mut map=match expected.as_deref(){None=>BTreeMap::new(),Some(encoded)=>{let record=decode_record(encoded)?;let bytes=prepared.crypto(prepared.master.decrypt_bytes(&record.ciphertext)).await?;prepared.negative()?;decode_map_data(&bytes)?}};
            merge_checkpoint(&mut map,&prepared.checkpoint,&prepared.digest)?;
            let bytes=encode_map(&map)?;prepared.negative()?;
            let ciphertext=prepared.crypto(prepared.master.encrypt_server_bytes(&bytes)).await?;prepared.negative()?;
            let next=serde_json::to_string(&Record{version:1,ciphertext})?;bound_record(&next)?;Ok(next)
        }.await;
        match encoded{Ok(next)=>Ok(PreparedOriginalRecoveryCheckpointWrite{prepared,expected,next,operation_id:uuid::Uuid::new_v4().to_string(),write_issued:AtomicBool::new(false)}),Err(error)=>Err(OriginalRecoveryPersistenceFailure::from_prepared(prepared,error))}
    }
}
impl PreparedOriginalRecoveryCheckpointWrite {
    pub(in crate::client) fn into_pending(self)->OwnedRecoveryPendingPersistence{self.prepared.pending}
    pub(in crate::client) fn write_ticket(&self,client:&Client)->Result<Arc<OriginalRecoveryCheckpointIoTicket>>{
        let effect=self.write_effect(client)?;
        self.write_issued.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
        OriginalRecoveryCheckpointIoTicket::capture(&self.prepared,client,&self.operation_id,effect)
    }
    pub(in crate::client) fn check_original(&self,client:&Client)->Result<()>{self.prepared.check_original(client)}
    pub(in crate::client) fn write_effect(&self,client:&Client)->Result<String>{
        self.check_original(client)?;
        let value=serde_json::to_string(&Effect::CompareAndPut{version:1,operation_id:&self.operation_id,owner:self.prepared.checkpoint.owner_id(),expected:self.expected.as_deref(),next:&self.next})?;
        self.check_original(client)?;Ok(value)
    }
    pub(in crate::client) fn namespace(&self)->&'static str{STORE_KEY}
    /// DATA validation only. Deliberately returns no durable/native receipt.
    /// The trusted native port completion supplier must consume the actual
    /// plan and one-use native completion before any positive continuation.
    pub(in crate::client) async fn verify_readback_data(&self,encoded:&str)->Result<()>{
        self.prepared.negative()?;bound_record(encoded)?;
        if encoded!=self.next{return Err(Error::Conflict)}
        let record=decode_record(encoded)?;
        let bytes=self.prepared.crypto(self.prepared.master.decrypt_bytes(&record.ciphertext)).await?;
        self.prepared.negative()?;
        let map=decode_map_data(&bytes)?;
        let checkpoint=map.get(&self.prepared.checkpoint.job.job_id).ok_or(Error::Protocol)?;
        if checkpoint.digest()?!=self.prepared.digest{return Err(Error::Conflict)}
        self.prepared.negative()
    }
}
fn bound_record(value:&str)->Result<()>{if value.len()>MAX_RECORD_BYTES{return Err(Error::Protocol)}Ok(())}
fn decode_record(value:&str)->Result<Record>{bound_record(value)?;let record:Record=serde_json::from_str(value).map_err(|_|Error::Protocol)?;if record.version!=1{return Err(Error::Protocol)}Ok(record)}
/// Same native uncertain-candidate policy: no eviction/replacement on mismatch.
fn merge_checkpoint(map:&mut BTreeMap<String,CompletionRecoveryCheckpoint>,checkpoint:&CompletionRecoveryCheckpoint,digest:&str)->Result<()>{
    let id=&checkpoint.job.job_id;
    if map.len()>=100&&!map.contains_key(id){return Err(Error::Protocol)}
    if checkpoint.digest()?!=digest{return Err(Error::Protocol)}
    if let Some(old)=map.get(id){if old.digest()?!=digest{return Err(Error::Conflict)}}
    map.insert(id.clone(),checkpoint.clone());Ok(())
}
fn decode_map_data(bytes:&[u8])->Result<BTreeMap<String,CompletionRecoveryCheckpoint>>{let value=serde_json::from_slice(bytes).map_err(|_|Error::Protocol)?;pending_map(Some(value))}
// Pure journal selection only; the private native retirement child also needs
// genuine commit, metadata physical proof and original full-record CAS.
#[cfg(any(test,all(target_arch="wasm32",feature="browser-metadata-prototype")))]
fn matching_checkpoint(map:&BTreeMap<String,CompletionRecoveryCheckpoint>,expected:&CompletionRecoveryCheckpoint)->Result<()>{
    let actual=map.get(&expected.job.job_id).ok_or(Error::Conflict)?;
    if actual.digest()?!=expected.digest()?{return Err(Error::Conflict)}Ok(())
}
#[cfg(any(test,all(target_arch="wasm32",feature="browser-metadata-prototype")))]
fn remove_matching_checkpoint(map:&mut BTreeMap<String,CompletionRecoveryCheckpoint>,expected:&CompletionRecoveryCheckpoint)->Result<()>{
    matching_checkpoint(map,expected)?;map.remove(&expected.job.job_id).ok_or(Error::Conflict)?;Ok(())
}
/// Exact native pending_map admission. Rehydration never grants completion.
fn pending_map(value:Option<Value>)->Result<BTreeMap<String,CompletionRecoveryCheckpoint>>{
    let pending=match value{
        None|Some(Value::Null)=>BTreeMap::new(),
        Some(value)=>{
            let object=value.as_object().ok_or(Error::Protocol)?;
            if object.len()>100||object.values().any(|checkpoint|checkpoint["protocol_version"]!=1||!checkpoint["encrypted_candidate"].is_object()){return Err(Error::Protocol)}
            serde_json::from_value::<BTreeMap<String,CompletionRecoveryCheckpoint>>(value).map_err(|_|Error::Protocol)?
        }
    };
    if pending.iter().any(|(id,checkpoint)|id!=&checkpoint.job.job_id){return Err(Error::Protocol)}
    for checkpoint in pending.values(){checkpoint.digest()?;}
    Ok(pending)
}
fn encode_map(map:&BTreeMap<String,CompletionRecoveryCheckpoint>)->Result<zeroize::Zeroizing<Vec<u8>>>{
    use std::io::Write;
    let framing=serde_json::to_vec(&Record{version:1,ciphertext:String::new()})?.len();
    let limit=MAX_RECORD_BYTES.checked_sub(framing).and_then(|n|(n/4).checked_mul(3)).and_then(|n|n.checked_sub(28)).ok_or(Error::Protocol)?;
    struct Encoder{bytes:zeroize::Zeroizing<Vec<u8>>,limit:usize,exceeded:bool}
    impl Write for Encoder{
        fn write(&mut self,bytes:&[u8])->std::io::Result<usize>{if self.bytes.len().checked_add(bytes.len()).is_none_or(|n|n>self.limit){self.exceeded=true;return Err(std::io::Error::other("local cache capacity"))}self.bytes.extend_from_slice(bytes);Ok(bytes.len())}
        fn flush(&mut self)->std::io::Result<()>{Ok(())}
    }
    let mut encoder=Encoder{bytes:zeroize::Zeroizing::new(Vec::new()),limit,exceeded:false};
    let result=serde_json::to_writer(&mut encoder,map);if encoder.exceeded{return Err(Error::Protocol)}result?;Ok(encoder.bytes)
}
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="completion_recovery/owned_checkpoint_tests.rs"]
mod tests;
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="completion_recovery/owned_retirement_tests.rs"]
mod retirement_tests;
