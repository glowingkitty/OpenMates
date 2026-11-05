//! One genuine Main recovered assistant reply -> original native messages row.
//! Transcript/sidecar coverage, chat version and journal retirement remain separate.
use super::*;
use crate::client::{required,Client,BrowserOriginalHintRecoveryProgress,completion_recovery::OriginalMainRecoveryJournalObservation};
use crate::crypto::master::MasterCapability;
use crate::client::browser::cache_metadata::recovered_reply_policy as reply;
use std::{rc::Rc,cell::{Cell,RefCell},future::Future,pin::Pin};
const PROOF_BYTES:usize=8*crate::client::transport::MAX_BODY;
struct Origin {
 store:BoundInitialSyncStore,progress:Rc<BrowserOriginalHintRecoveryProgress>,master:MasterCapability,
 metadata:Plain<Value>,message:Plain<Value>,ciphertext:Zeroizing<String>,journal:RefCell<OriginalMainRecoveryJournalObservation>,
 observations:RefCell<Vec<Rc<Plain<Value>>>>,
}
impl Origin {
 fn negative(&self)->Result<()>{self.store.original.check()?;self.progress.metadata_finalize_negative()?;self.master.ensure_current()}
 fn check(&self,client:&Client)->Result<()>{self.store.ensure_current(client)?;self.progress.ensure_current(client)?;if !self.master.same_instance(&client.master_capability()?){return Err(Error::Cancelled)}self.negative()}
}
struct Physical {before:Rc<Plain<Value>>,written:Rc<Plain<Value>>,reread:Rc<Plain<Value>>}
impl Physical {
 fn check(&self)->Result<()>{
  reply::physical_matches(&self.before,&self.written,&self.reread,&self.written["observation"]["record"])
 }
}
pub struct BrowserRecoveredReplyStore {origin:Rc<Origin>,physical:Rc<RefCell<Option<Physical>>>,pending:Option<Pin<Box<dyn Future<Output=Result<()>>>>>,completed:bool,taken:bool,terminal:Rc<Cell<bool>>}
pub struct BrowserRecoveredReplyControl {origin:Rc<Origin>}
impl BrowserRecoveredReplyControl {
 pub fn ensure_current(&self,client:&Client)->Result<()>{self.origin.check(client)}
 pub fn cancel(&self){self.origin.progress.cancel_local_finalize();}
}
/// Only the selected Main assistant row. No general transcript or artifact ACK.
pub struct BrowserRecoveredReplyStored {origin:Rc<Origin>,physical:Rc<RefCell<Option<Physical>>>}
pub struct BrowserRecoveredReplyNativeTerminal {settled:Rc<Cell<bool>>}
impl BrowserRecoveredReplyNativeTerminal {pub fn native_io_quiescent(&self)->bool{self.settled.get()}}
impl BrowserRecoveredReplyStored {
 pub fn ensure_current(&self,client:&Client)->Result<()>{self.origin.check(client)?;self.origin.journal.try_borrow().map_err(|_|Error::Conflict)?.ensure_current(client)?;self.physical.borrow().as_ref().ok_or(Error::Conflict)?.check()?;self.origin.negative()}
}
impl BoundInitialSyncStore {
 pub fn begin_recovered_reply_store(&self,client:&Client,progress:Rc<BrowserOriginalHintRecoveryProgress>)->Result<BrowserRecoveredReplyStore>{
  self.ensure_current(client)?;
  let(metadata,message,ciphertext,master,journal)=progress.recovered_reply_store_inputs(client)?;
  reply::source(&message,progress.metadata_finalize_chat(),progress.recovered_reply_message()?)?;
  let origin=Rc::new(Origin{store:self.clone(),progress,master,metadata,message,ciphertext,journal:RefCell::new(journal),observations:RefCell::new(Vec::new())});origin.check(client)?;
  origin.progress.claim_recovered_reply_store()?;
  let physical=Rc::new(RefCell::new(None));let terminal=Rc::new(Cell::new(false));
  let(o,p,t)=(origin.clone(),physical.clone(),terminal.clone());
  Ok(BrowserRecoveredReplyStore{origin,physical,pending:Some(Box::pin(async move{drive(o,p,t).await})),completed:false,taken:false,terminal})
 }
}
impl BrowserRecoveredReplyStore {
 pub fn control(&self)->BrowserRecoveredReplyControl{BrowserRecoveredReplyControl{origin:self.origin.clone()}}
 pub fn ensure_current(&self,client:&Client)->Result<()>{self.origin.check(client)}
 pub fn cancel(&self){self.origin.progress.cancel_local_finalize();}
 pub fn terminal(&self)->Option<BrowserRecoveredReplyNativeTerminal>{self.terminal.get().then(||BrowserRecoveredReplyNativeTerminal{settled:self.terminal.clone()})}
 pub async fn drive(&mut self)->Result<()>{let future=self.pending.take().ok_or(Error::Conflict)?;future.await?;self.completed=true;Ok(())}
 pub fn finish(&mut self,client:&Client)->Result<BrowserRecoveredReplyStored>{
  self.origin.check(client)?;if !self.completed||self.taken||!self.terminal.get(){return Err(Error::Conflict)}
  let stored=BrowserRecoveredReplyStored{origin:self.origin.clone(),physical:self.physical.clone()};stored.ensure_current(client)?;self.taken=true;Ok(stored)
 }
}
impl Drop for BrowserRecoveredReplyStore {fn drop(&mut self){if !self.completed{self.origin.progress.cancel_local_finalize();}}}
fn bounded(value:&impl serde::Serialize)->Result<()>{crate::client::monitor::cached_view::bounded_bytes(value,PROOF_BYTES).ok_or(Error::Protocol).map(|_|())}
async fn io(origin:&Rc<Origin>,change:Option<(&Value,&Value)>)->Result<Rc<Plain<Value>>>{
 origin.negative()?;let original=&origin.store.original;let operation=uuid::Uuid::new_v4().to_string();
 let chat=origin.progress.metadata_finalize_chat();let message=origin.progress.recovered_reply_message()?;
 let mut effect=Plain::new(json!({"kind":"openmates-recovery-reply-native-io-v1","op_id":operation,"owner_id":original.owner.as_str(),"chat_id":chat,"message_id":message,"created_at":origin.message["created_at"],"operation":if change.is_some(){"compare_store"}else{"read"}}));
 if let Some((before,after))=change{effect["expected_db_version"]=before["db_version"].clone();effect["before"]=before["observation"].clone();effect["after"]=after.clone();}
 {let observations=origin.observations.borrow();let previous=observations.iter().map(|v|&***v).collect::<Vec<_>>();bounded(&(&*origin.metadata,&*origin.message,previous,&*effect))?;}
 let ticket=Arc::new(MetadataNativeIoTicket{original:original.clone(),operation:Zeroizing::new(operation),effect,dispatched:AtomicBool::new(false),source:None,recovery_source:Some(origin.progress.clone()),embed_source:None});
 let actual=original.context.start(ticket.clone())?.drive().await?;
 let encoded=Zeroizing::new(actual.consume_for(&original.context,&ticket)?);origin.negative()?;
 let frame=Plain::new(serde_json::from_str::<Value>(&encoded)?);
 let keys=["kind","op_id","owner_id","chat_id","message_id","db_version","observation"];
 if !frame.as_object().is_some_and(|o|o.len()==keys.len()&&keys.iter().all(|k|o.contains_key(*k)))
  ||frame["kind"]!="openmates-recovery-reply-native-result-v1"||frame["op_id"].as_str()!=Some(ticket.operation_id())
  ||frame["owner_id"].as_str()!=Some(original.owner.as_str())||frame["chat_id"].as_str()!=Some(chat)||frame["message_id"].as_str()!=Some(message)
  ||!frame["db_version"].as_u64().is_some_and(|v|v>0&&v<=9_007_199_254_740_991)
  ||!frame["observation"].as_object().is_some_and(|o|o.len()==3&&["metadata","record","candidates"].iter().all(|k|o.contains_key(*k)))
  ||!frame["observation"]["metadata"].is_object()||!frame["observation"]["candidates"].is_array(){return Err(Error::Protocol)}
 let frame=Rc::new(frame);
 // Completed original observations remain retained even if their budget causes
 // refusal. No later error loses source/proof or turns a failed CAS into success.
 origin.observations.borrow_mut().push(frame.clone());
 {let observations=origin.observations.borrow();let previous=observations.iter().map(|v|&***v).collect::<Vec<_>>();bounded(&(&*origin.metadata,&*origin.message,previous))?;}
 Ok(frame)
}
async fn drive(origin:Rc<Origin>,physical:Rc<RefCell<Option<Physical>>>,terminal:Rc<Cell<bool>>)->Result<()>{
 origin.negative()?;origin.journal.try_borrow_mut().map_err(|_|Error::Conflict)?.read_matching().await?;origin.negative()?;
 let before=io(&origin,None).await?;let observation=&before["observation"];
 let chat=origin.progress.metadata_finalize_chat();let message=origin.progress.recovered_reply_message()?;
 super::super::projection(&observation["metadata"],chat,&origin.store.original.owner,true)?;
 let local=required(&observation["metadata"],"encrypted_chat_key")?;
 let local=origin.master.decrypt_bytes(local).await?;origin.negative()?;
 let canonical=origin.master.decrypt_bytes(&origin.ciphertext).await?;origin.negative()?;
 let local=crate::client::key_from_bytes(&local)?;let key=crate::client::key_from_bytes(&canonical)?;
 if local.as_ref()!=key.as_ref(){return Err(Error::Crypto)}
 let candidates=observation["candidates"].as_array().ok_or(Error::Protocol)?;
 let after=reply::prepare(&origin.message,&observation["record"],candidates,chat,message,&key)?;reply::check_planned_row(&after)?;origin.negative()?;
 // Reserve complete write + independent-readback evidence BEFORE mutation.
 // The native CAS exact-compares all metadata/row/candidate unknown fields.
 // Include the retained sources, full unknown before/candidates, the dispatch
 // effect copies, both completed envelopes and final normalized body check.
 // Borrow each repeated value for accounting; do not allocate proof replicas.
 bounded(&(&*origin.metadata,&*origin.message,&**before,&**before,&*after,&*after,&*after,&*after,&observation["metadata"],&observation["metadata"],4096usize))?;
 let written=io(&origin,Some((&before,&after))).await?;
 if written["db_version"]!=before["db_version"]||written["observation"]["metadata"]!=observation["metadata"]
  ||written["observation"]["record"]!=*after||written["observation"]["candidates"]!=json!([]){return Err(Error::Conflict)}
 let reread=io(&origin,None).await?;
 if reread["db_version"]!=written["db_version"]||reread["observation"]!=written["observation"]{return Err(Error::Conflict)}
 let normalized=reply::source(&origin.message,chat,message)?;
 if !reply::body_matches(&reread["observation"]["record"],&normalized,&key)?{return Err(Error::Conflict)}
 origin.store.original.context.recheck_profile_owner().await?;origin.negative()?;
 if !origin.store.original.context.native_operations_consumed(){return Err(Error::Conflict)}
 let proof=Physical{before,written,reread};proof.check()?;*physical.borrow_mut()=Some(proof);terminal.set(true);Ok(())
}
