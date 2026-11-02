//! One already-canonical Main-linked root code embed. Neither sealed-output
//! coverage nor journal/full-hint/ACK authority can be issued by this facet.
use super::*;
use crate::client::{required,sha256,Client,saved_embed::SavedEmbedRead,BrowserOriginalHintRecoveryProgress,completion_recovery::OriginalMainRecoveryJournalObservation};
use crate::crypto::master::MasterCapability;
use crate::client::main_code_embed_policy as policy;
use std::{rc::Rc,cell::{Cell,RefCell},future::Future,pin::Pin};
const PROOF:usize=8*crate::client::transport::MAX_BODY;
struct Origin {
 store:BoundInitialSyncStore,progress:Rc<BrowserOriginalHintRecoveryProgress>,read:Rc<SavedEmbedRead>,master:MasterCapability,
 metadata:Plain<Value>,message:Plain<Value>,ciphertext:Zeroizing<String>,journal:RefCell<OriginalMainRecoveryJournalObservation>,
 observations:RefCell<Vec<Rc<Plain<Value>>>>,
}
impl Origin {
 fn negative(&self)->Result<()>{self.store.original.check()?;self.progress.metadata_finalize_negative()?;self.read.main_native_negative()?;self.master.ensure_current()}
 fn check(&self,client:&Client)->Result<()>{
  self.store.ensure_current(client)?;self.progress.ensure_current(client)?;self.read.check_main_native(client,&self.store.original.owner,self.progress.metadata_finalize_chat(),self.progress.recovered_reply_message()?)?;
  if !self.master.same_instance(&client.master_capability()?){return Err(Error::Cancelled)}self.negative()
 }
 fn budget(&self,value:&impl serde::Serialize)->Result<()>{
  let retained=self.read.main_native_bytes()?;
  let maximum=PROOF.checked_sub(retained).ok_or(Error::Protocol)?;
  crate::client::monitor::cached_view::bounded_bytes(&(&*self.metadata,&*self.message,self.ciphertext.as_str(),value),maximum).ok_or(Error::Protocol).map(|_|())
 }
}
pub struct BrowserMainCodeEmbedStore {origin:Rc<Origin>,pending:Option<Pin<Box<dyn Future<Output=Result<()>>>>>,completed:bool,taken:bool,terminal:Rc<Cell<bool>>,proof:Rc<RefCell<Option<Rc<Plain<Value>>>> >}
pub struct BrowserMainCodeEmbedControl {origin:Rc<Origin>}
impl BrowserMainCodeEmbedControl {pub fn ensure_current(&self,client:&Client)->Result<()>{self.origin.check(client)}pub fn cancel(&self){self.origin.progress.cancel_local_finalize();}}
pub struct BrowserMainCodeEmbedNativeTerminal {settled:Rc<Cell<bool>>}
impl BrowserMainCodeEmbedNativeTerminal {pub fn native_io_quiescent(&self)->bool{self.settled.get()}}
pub struct BrowserMainCodeEmbedStored {origin:Rc<Origin>,proof:Rc<RefCell<Option<Rc<Plain<Value>>>> >}
impl BrowserMainCodeEmbedStored {pub fn ensure_current(&self,client:&Client)->Result<()>{self.origin.check(client)?;self.origin.journal.try_borrow().map_err(|_|Error::Conflict)?.ensure_current(client)?;if self.proof.borrow().is_none(){return Err(Error::Conflict)}self.origin.negative()}}
impl BoundInitialSyncStore {
 pub fn begin_main_code_embed_store(&self,client:&Client,progress:Rc<BrowserOriginalHintRecoveryProgress>,read:SavedEmbedRead)->Result<BrowserMainCodeEmbedStore>{
  self.ensure_current(client)?;
  let(metadata,message,ciphertext,master,journal)=progress.recovered_reply_store_inputs(client)?;
  read.check_main_native(client,&self.original.owner,progress.metadata_finalize_chat(),progress.recovered_reply_message()?)?;
  let origin=Rc::new(Origin{store:self.clone(),progress,read:Rc::new(read),master,metadata,message,ciphertext,journal:RefCell::new(journal),observations:RefCell::new(Vec::new())});origin.check(client)?;
  let proof=Rc::new(RefCell::new(None));let terminal=Rc::new(Cell::new(false));let(o,p,t)=(origin.clone(),proof.clone(),terminal.clone());
  Ok(BrowserMainCodeEmbedStore{origin,pending:Some(Box::pin(async move{drive(o,p,t).await})),completed:false,taken:false,terminal,proof})
 }
}
impl BrowserMainCodeEmbedStore {
 pub fn control(&self)->BrowserMainCodeEmbedControl{BrowserMainCodeEmbedControl{origin:self.origin.clone()}}
 pub fn ensure_current(&self,client:&Client)->Result<()>{self.origin.check(client)}
 pub fn cancel(&self){self.origin.progress.cancel_local_finalize();}
 pub async fn drive(&mut self)->Result<()>{self.pending.take().ok_or(Error::Conflict)?.await?;self.completed=true;Ok(())}
 pub fn terminal(&self)->Option<BrowserMainCodeEmbedNativeTerminal>{self.terminal.get().then(||BrowserMainCodeEmbedNativeTerminal{settled:self.terminal.clone()})}
 pub fn finish(&mut self,client:&Client)->Result<BrowserMainCodeEmbedStored>{
  self.origin.check(client)?;if !self.completed||self.taken||!self.terminal.get(){return Err(Error::Conflict)}
  let result=BrowserMainCodeEmbedStored{origin:self.origin.clone(),proof:self.proof.clone()};result.ensure_current(client)?;self.taken=true;Ok(result)
 }
}
impl Drop for BrowserMainCodeEmbedStore{fn drop(&mut self){if !self.completed{self.origin.progress.cancel_local_finalize();}}}
async fn io(origin:&Rc<Origin>,change:Option<(&Value,&Value)>)->Result<Rc<Plain<Value>>>{
 origin.negative()?;let original=&origin.store.original;let operation=uuid::Uuid::new_v4().to_string();let(id,_)=origin.read.main_native_identity()?;
 let hash=sha256(id);let chat=origin.progress.metadata_finalize_chat();
 let key_ids=[format!("{hash}:master:null"),format!("{hash}:chat:{}",sha256(chat))];
 let mut effect=Plain::new(json!({"kind":"openmates-main-code-embed-native-io-v1","op_id":operation,"owner_id":original.owner.as_str(),"chat_id":chat,"embed_id":id,"hashed_embed_id":hash,"key_ids":key_ids,"operation":if change.is_some(){"compare_store"}else{"read"}}));
 if let Some((before,after))=change{effect["expected_db_version"]=before["db_version"].clone();effect["before"]=before["observation"].clone();effect["after"]=after.clone();}
 {let frames=origin.observations.borrow();origin.budget(&(frames.iter().map(|v|&***v).collect::<Vec<_>>(),&*effect))?;}
 let ticket=Arc::new(MetadataNativeIoTicket{original:original.clone(),operation:Zeroizing::new(operation),effect,dispatched:AtomicBool::new(false),source:None,recovery_source:Some(origin.progress.clone()),embed_source:Some(origin.read.clone())});
 let actual=original.context.start(ticket.clone())?.drive().await?;let encoded=Zeroizing::new(actual.consume_for(&original.context,&ticket)?);origin.negative()?;
 let value=Plain::new(serde_json::from_str::<Value>(&encoded)?);
 if !value.as_object().is_some_and(|o|o.len()==7&&["kind","op_id","owner_id","chat_id","embed_id","db_version","observation"].iter().all(|k|o.contains_key(*k)))
  ||value["kind"]!="openmates-main-code-embed-native-result-v1"||value["op_id"].as_str()!=Some(ticket.operation_id())||value["owner_id"].as_str()!=Some(original.owner.as_str())
  ||value["chat_id"].as_str()!=Some(chat)||value["embed_id"].as_str()!=Some(id)||!value["db_version"].as_u64().is_some_and(|v|v>0&&v<=9_007_199_254_740_991)
  ||!value["observation"].as_object().is_some_and(|o|o.len()==4&&["metadata","record","keys","key_targets"].iter().all(|k|o.contains_key(*k)))
  ||!value["observation"]["metadata"].is_object()||!value["observation"]["keys"].is_array()||!value["observation"]["key_targets"].as_array().is_some_and(|v|v.len()==2){return Err(Error::Protocol)}
 let frame=Rc::new(value);origin.observations.borrow_mut().push(frame.clone());
 {let frames=origin.observations.borrow();origin.budget(&frames.iter().map(|v|&***v).collect::<Vec<_>>())?;}Ok(frame)
}
async fn drive(origin:Rc<Origin>,proof:Rc<RefCell<Option<Rc<Plain<Value>>>>>,terminal:Rc<Cell<bool>>)->Result<()>{
 origin.negative()?;origin.journal.try_borrow_mut().map_err(|_|Error::Conflict)?.read_matching().await?;origin.negative()?;
 let before=io(&origin,None).await?;let chat=origin.progress.metadata_finalize_chat();let message=origin.progress.recovered_reply_message()?;
 super::super::projection(&before["observation"]["metadata"],chat,&origin.store.original.owner,true)?;
 let wrapped=required(&before["observation"]["metadata"],"encrypted_chat_key")?;
 let local=origin.master.decrypt_bytes(wrapped).await?;origin.negative()?;
 let actual=origin.master.decrypt_bytes(&origin.ciphertext).await?;origin.negative()?;
 let key=crate::client::key_from_bytes(&actual)?;if local.as_slice()!=key.as_ref(){return Err(Error::Crypto)}
 let after=origin.read.plan_main_native(&origin.store.original.owner,chat,message,&key,&origin.master,&before).await?;origin.negative()?;
 // Reserve retained source, dispatch clones, and complete independent proof
 // envelopes before mutation. Existing content/window budgets remain separate.
 origin.budget(&([&**before;6],[&*after;10],[&before["observation"]["metadata"];4],4096usize))?;
 let written=io(&origin,Some((&before,&after))).await?;
 if written["db_version"]!=before["db_version"]||written["observation"]["metadata"]!=before["observation"]["metadata"]||written["observation"]["record"]!=after["record"]||written["observation"]["keys"]!=after["keys"]{return Err(Error::Conflict)}
 let reread=io(&origin,None).await?;
 policy::verify_physical(&before,&written,&reread,&after)?;
 origin.store.original.context.recheck_profile_owner().await?;origin.negative()?;
 if !origin.store.original.context.native_operations_consumed(){return Err(Error::Conflict)}
 *proof.borrow_mut()=Some(reread);terminal.set(true);Ok(())
}
