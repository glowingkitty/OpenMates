//! Genuine Personal metadata recovery result -> original native row -> journal.
//! No raw DTO constructor, main transcript write, UI output or whole-hint ACK.
use super::*;
use crate::client::{Client,BrowserOriginalHintRecoveryProgress,completion_recovery::OriginalMetadataRecoveryRetirement};
use crate::crypto::master::MasterCapability;
use std::{rc::Rc,cell::{Cell,RefCell},future::Future,pin::Pin};

struct Origin {
    store:BoundInitialSyncStore,progress:Rc<BrowserOriginalHintRecoveryProgress>,
    expected:Plain<Value>,source:Plain<Value>,ciphertext:Zeroizing<String>,master:MasterCapability,
    observations:RefCell<Vec<Rc<Plain<Value>>>>,
}
impl Origin {
    fn negative(&self)->Result<()>{self.store.original.check()?;self.progress.metadata_finalize_negative()?;self.master.ensure_current()}
    fn check(&self,client:&Client)->Result<()>{self.store.ensure_current(client)?;self.progress.ensure_current(client)?;if !self.master.same_instance(&client.master_capability()?){return Err(Error::Cancelled)}self.negative()}
}
/// Only this module's actual native full-row CAS/readback creates this value.
/// Its anchor is the SAME captured checkpoint retirement, never a job UUID grant.
pub(in crate::client) struct MetadataRecoveryPhysicalProof {origin:Rc<Origin>,anchor:Arc<()>,before:Rc<Plain<Value>>,after:Rc<Plain<Value>>}
impl MetadataRecoveryPhysicalProof {
    pub(in crate::client) fn check_retirement(&self,anchor:&Arc<()>)->Result<()>{
        if !Arc::ptr_eq(&self.anchor,anchor){return Err(Error::Cancelled)}
        self.origin.negative()?;
        if self.before["db_version"]!=self.after["db_version"]||self.after["record"].is_null(){return Err(Error::Conflict)}Ok(())
    }
}
pub struct BrowserMetadataRecoveryFinalize {
    origin:Rc<Origin>,retirement:Rc<RefCell<OriginalMetadataRecoveryRetirement>>,
    physical:Rc<RefCell<Option<MetadataRecoveryPhysicalProof>>>,
    pending:Option<Pin<Box<dyn Future<Output=Result<()>>>>>,completed:bool,taken:bool,terminal:Rc<Cell<bool>>,
}
pub struct BrowserMetadataRecoveryLocalStored {origin:Rc<Origin>,retirement:Rc<RefCell<OriginalMetadataRecoveryRetirement>>,physical:Rc<RefCell<Option<MetadataRecoveryPhysicalProof>>>}
pub struct BrowserMetadataRecoveryNativeTerminal {settled:Rc<Cell<bool>>}
impl BrowserMetadataRecoveryNativeTerminal {pub fn native_io_quiescent(&self)->bool{self.settled.get()}}
impl BrowserMetadataRecoveryLocalStored {
    pub fn ensure_current(&self,client:&Client)->Result<()>{
        self.origin.check(client)?;self.retirement.borrow().verified(client)?;
        self.physical.borrow().as_ref().ok_or(Error::Conflict)?.check_retirement(&self.retirement.borrow().anchor())?;
        self.origin.negative()
    }
}
impl BoundInitialSyncStore {
    pub fn begin_metadata_recovery_finalize(&self,client:&Client,progress:Rc<BrowserOriginalHintRecoveryProgress>)->Result<BrowserMetadataRecoveryFinalize>{
        self.ensure_current(client)?;
        let(expected,source,ciphertext,master,retirement)=progress.metadata_finalize_inputs(client)?;
        // Exact native principal/profile/store and original Master/Client are
        // checked BEFORE claim/IO. Unsupported main/canonical-no-journal stays
        // held on the original Progress and gains no synthetic journal proof.
        let origin=Rc::new(Origin{store:self.clone(),progress,expected,source,ciphertext,master,observations:RefCell::new(Vec::new())});origin.check(client)?;
        let retirement=Rc::new(RefCell::new(retirement));let physical=Rc::new(RefCell::new(None));let terminal=Rc::new(Cell::new(false));
        origin.progress.claim_metadata_finalize()?;
        let o=origin.clone();let r=retirement.clone();let p=physical.clone();let t=terminal.clone();
        let pending=Box::pin(async move{drive(o,r,p,t).await});
        Ok(BrowserMetadataRecoveryFinalize{origin,retirement,physical,pending:Some(pending),completed:false,taken:false,terminal})
    }
}
impl BrowserMetadataRecoveryFinalize {
    pub fn ensure_current(&self,client:&Client)->Result<()>{self.origin.check(client)}
    pub fn cancel(&self){self.origin.progress.cancel_local_finalize();}
    pub fn terminal(&self)->Option<BrowserMetadataRecoveryNativeTerminal>{self.terminal.get().then(||BrowserMetadataRecoveryNativeTerminal{settled:self.terminal.clone()})}
    pub async fn drive(&mut self)->Result<()>{
        let pending=self.pending.take().ok_or(Error::Conflict)?;
        // Every native await owns its exact request until the native terminal.
        // Unknown/error/drop retains original source/proofs; never retries.
        pending.await?;self.completed=true;Ok(())
    }
    pub fn finish(&mut self,client:&Client)->Result<BrowserMetadataRecoveryLocalStored>{
        self.origin.check(client)?;
        if !self.completed||self.taken||!self.terminal.get(){return Err(Error::Conflict)}
        self.retirement.borrow().verified(client)?;
        let stored=BrowserMetadataRecoveryLocalStored{origin:self.origin.clone(),retirement:self.retirement.clone(),physical:self.physical.clone()};
        stored.ensure_current(client)?;self.taken=true;Ok(stored)
    }
}
impl Drop for BrowserMetadataRecoveryFinalize {fn drop(&mut self){if !self.completed{self.origin.progress.cancel_local_finalize();}}}
async fn io(origin:&Rc<Origin>,change:Option<(&Value,&Value)>)->Result<Rc<Plain<Value>>>{
    origin.negative()?;
    let frame=super::native_row::io(&origin.store,&origin.progress,&origin.master,&origin.expected,&origin.source,&origin.observations,change).await?;
    origin.negative()?;Ok(frame)
}
async fn drive(origin:Rc<Origin>,retirement:Rc<RefCell<OriginalMetadataRecoveryRetirement>>,physical:Rc<RefCell<Option<MetadataRecoveryPhysicalProof>>>,terminal:Rc<Cell<bool>>)->Result<()>{
    origin.negative()?;
    // Read/validate the actual matching encrypted journal BEFORE any local
    // canonical mutation. Full-record compare_put later detects journal races.
    retirement.borrow_mut().read_matching().await?;origin.negative()?;
    let before=io(&origin,None).await?;let chat=origin.progress.metadata_finalize_chat();let owner=&origin.store.original.owner;
    let actual=super::super::projection(&before["record"],chat,owner,true)?;
    let expected=super::super::projection(&origin.expected,chat,owner,true)?;
    if *actual!=*expected{return Err(Error::Conflict)}
    // Compare actual unwrapped keys, preserving legitimate ciphertext rewraps.
    // Opaque native source and original Master remain owned across WebCrypto.
    let local=before["record"]["encrypted_chat_key"].as_str().filter(|v|!v.is_empty()).ok_or(Error::Crypto)?;
    let local_key=origin.master.decrypt_bytes(local).await?;origin.negative()?;
    let canonical_key=origin.master.decrypt_bytes(&origin.ciphertext).await?;origin.negative()?;
    let local_key=crate::client::key_from_bytes(&local_key)?;let canonical_key=crate::client::key_from_bytes(&canonical_key)?;
    if local_key.as_ref()!=canonical_key.as_ref(){return Err(Error::Crypto)}
    super::super::validate_metadata_cipher_fields(&origin.source,&canonical_key)?;origin.negative()?;
    let after=policy::merge_recovered_metadata(&origin.source,&before["record"],chat,owner)?;
    let written=io(&origin,Some((&before,&after))).await?;
    if written["db_version"]!=before["db_version"]||written["record"]!=*after{return Err(Error::Conflict)}
    let reread=io(&origin,None).await?;
    if reread["db_version"]!=written["db_version"]||reread["record"]!=written["record"]{return Err(Error::Conflict)}
    origin.store.original.context.recheck_profile_owner().await?;origin.negative()?;
    if !origin.store.original.context.native_operations_consumed(){return Err(Error::Conflict)}
    *physical.borrow_mut()=Some(MetadataRecoveryPhysicalProof{origin:origin.clone(),anchor:retirement.borrow().anchor(),before,after:reread});
    // The physical proof stays retained on every later journal/cancel failure.
    // Only the same original proof can authorize this exact candidate removal.
    {let proof=physical.borrow();retirement.borrow_mut().retire(proof.as_ref().ok_or(Error::Conflict)?).await?;}
    origin.negative()?;terminal.set(true);Ok(())
}
