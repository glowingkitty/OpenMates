//! Main's opaque metadata facet only. Transcript/artifacts/journal/full ACK stay pending.
use super::*;
use crate::client::{Client,BrowserOriginalHintRecoveryProgress,completion_recovery::OriginalMainRecoveryJournalObservation};
use crate::crypto::master::MasterCapability;
use std::{rc::Rc,cell::{Cell,RefCell},future::Future,pin::Pin};
struct Origin {
 store:BoundInitialSyncStore,progress:Rc<BrowserOriginalHintRecoveryProgress>,master:MasterCapability,
 expected:Plain<Value>,source:Plain<Value>,ciphertext:Zeroizing<String>,journal:RefCell<OriginalMainRecoveryJournalObservation>,
 observations:RefCell<Vec<Rc<Plain<Value>>>>,
}
impl Origin {
 fn negative(&self)->Result<()>{self.store.original.check()?;self.progress.metadata_finalize_negative()?;self.journal.borrow().negative()?;self.master.ensure_current()}
 fn check(&self,client:&Client)->Result<()>{self.store.ensure_current(client)?;self.progress.ensure_current(client)?;if !self.master.same_instance(&client.master_capability()?){return Err(Error::Cancelled)}self.negative()}
}
/// Kept private: no ordinary row/status can create this actual CAS+reread evidence.
struct Physical {before:Rc<Plain<Value>>,written:Rc<Plain<Value>>,reread:Rc<Plain<Value>>}
impl Physical {
 fn check(&self)->Result<()>{
  if self.before["db_version"]!=self.written["db_version"]||self.written["db_version"]!=self.reread["db_version"]||self.reread["record"]!=self.written["record"]{return Err(Error::Conflict)}Ok(())
 }
}
pub struct BrowserMainMetadataStore {
 origin:Rc<Origin>,physical:Rc<RefCell<Option<Physical>>>,pending:Option<Pin<Box<dyn Future<Output=Result<()>>>>>,
 completed:bool,taken:bool,terminal:Rc<Cell<bool>>,
}
/// Opaque partial facet, never accepted by metadata retirement or a full-hint ACK.
pub struct BrowserMainMetadataStored {origin:Rc<Origin>,physical:Rc<RefCell<Option<Physical>>>}
pub struct BrowserMainMetadataNativeTerminal {settled:Rc<Cell<bool>>}
impl BrowserMainMetadataNativeTerminal {pub fn native_io_quiescent(&self)->bool{self.settled.get()}}
impl BrowserMainMetadataStored {
 pub fn ensure_current(&self,client:&Client)->Result<()>{
  self.origin.check(client)?;self.origin.journal.borrow().ensure_current(client)?;
  self.physical.borrow().as_ref().ok_or(Error::Conflict)?.check()?;self.origin.negative()
 }
}
impl BoundInitialSyncStore {
 pub fn begin_main_metadata_store(&self,client:&Client,progress:Rc<BrowserOriginalHintRecoveryProgress>)->Result<BrowserMainMetadataStore>{
  self.ensure_current(client)?;
  let(expected,source,ciphertext,master,journal)=progress.main_metadata_store_inputs(client)?;
  let origin=Rc::new(Origin{store:self.clone(),progress,master,expected,source,ciphertext,journal:RefCell::new(journal),observations:RefCell::new(Vec::new())});origin.check(client)?;
  origin.progress.claim_metadata_finalize()?;
  let physical=Rc::new(RefCell::new(None));let terminal=Rc::new(Cell::new(false));
  let(o,p,t)=(origin.clone(),physical.clone(),terminal.clone());let pending=Box::pin(async move{drive(o,p,t).await});
  Ok(BrowserMainMetadataStore{origin,physical,pending:Some(pending),completed:false,taken:false,terminal})
 }
}
impl BrowserMainMetadataStore {
 pub fn ensure_current(&self,client:&Client)->Result<()>{self.origin.check(client)}
 pub fn cancel(&self){self.origin.progress.cancel_local_finalize();}
 pub fn terminal(&self)->Option<BrowserMainMetadataNativeTerminal>{self.terminal.get().then(||BrowserMainMetadataNativeTerminal{settled:self.terminal.clone()})}
 pub async fn drive(&mut self)->Result<()>{let future=self.pending.take().ok_or(Error::Conflict)?;future.await?;self.completed=true;Ok(())}
 pub fn finish(&mut self,client:&Client)->Result<BrowserMainMetadataStored>{
  self.origin.check(client)?;if !self.completed||self.taken||!self.terminal.get(){return Err(Error::Conflict)}
  let stored=BrowserMainMetadataStored{origin:self.origin.clone(),physical:self.physical.clone()};stored.ensure_current(client)?;self.taken=true;Ok(stored)
 }
}
impl Drop for BrowserMainMetadataStore {fn drop(&mut self){if !self.completed{self.origin.progress.cancel_local_finalize();}}}
async fn io(origin:&Rc<Origin>,change:Option<(&Value,&Value)>)->Result<Rc<Plain<Value>>>{
 origin.negative()?;
 let frame=super::native_row::io(&origin.store,&origin.progress,&origin.master,&origin.expected,&origin.source,&origin.observations,change).await?;
 origin.negative()?;Ok(frame)
}
async fn drive(origin:Rc<Origin>,physical:Rc<RefCell<Option<Physical>>>,terminal:Rc<Cell<bool>>)->Result<()>{
 origin.negative()?;
 // This exact encrypted original Main journal must still be present before
 // canonical native mutation. This read-only resource has NO retire method.
 origin.journal.borrow_mut().read_matching().await?;origin.negative()?;
 let before=io(&origin,None).await?;let chat=origin.progress.metadata_finalize_chat();let owner=&origin.store.original.owner;
 let actual=super::super::projection(&before["record"],chat,owner,true)?;
 let expected=super::super::projection(&origin.expected,chat,owner,true)?;
 if *actual!=*expected{return Err(Error::Conflict)}
 let local=before["record"]["encrypted_chat_key"].as_str().filter(|v|!v.is_empty()).ok_or(Error::Crypto)?;
 let local_key=origin.master.decrypt_bytes(local).await?;origin.negative()?;
 let canonical_key=origin.master.decrypt_bytes(&origin.ciphertext).await?;origin.negative()?;
 let local_key=crate::client::key_from_bytes(&local_key)?;let canonical_key=crate::client::key_from_bytes(&canonical_key)?;
 if local_key.as_ref()!=canonical_key.as_ref(){return Err(Error::Crypto)}
 super::super::validate_metadata_cipher_fields(&origin.source,&canonical_key)?;origin.negative()?;
 // Metadata never advances native messages_v/timestamps or marks a transcript
 // durable: deployed TS does that only AFTER actual recovered message storage.
 let after=policy::merge_main_recovered_metadata(&origin.source,&before["record"],chat,owner)?;
 let written=io(&origin,Some((&before,&after))).await?;
 if written["db_version"]!=before["db_version"]||written["record"]!=*after{return Err(Error::Conflict)}
 let reread=io(&origin,None).await?;
 if reread["db_version"]!=written["db_version"]||reread["record"]!=written["record"]{return Err(Error::Conflict)}
 origin.store.original.context.recheck_profile_owner().await?;origin.negative()?;
 if !origin.store.original.context.native_operations_consumed(){return Err(Error::Conflict)}
 let proof=Physical{before,written,reread};proof.check()?;*physical.borrow_mut()=Some(proof);
 // Main journal intentionally remains. Native transcript/artifacts and exact
 // original journal retirement require their own genuine durable proofs.
 terminal.set(true);Ok(())
}
