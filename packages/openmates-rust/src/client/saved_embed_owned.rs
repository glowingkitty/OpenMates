//! Prototype-only SAME original fresh selected read, detached IO and short
//! Client phases. No monitor slot/socket, caller proof or fallback authority.
use super::*;
use crate::client::{owned_operation::{OwnedOperationScope,ActiveOwnedClient},auth::{PreparedOwnedSessionValidation,OwnedSessionValidationHeaders,OwnedSessionValidationBody,CompletedOwnedSessionValidation},transport::{Socket,PreparedOwnedMonitorSocket,UnannouncedOwnedMonitorSocket},embed::selected_key::{self,Phases,PhaseFuture,Candidate}};
use crate::crypto::master::MasterCapability;
use crate::platform::time::Instant;
use std::{sync::{Arc,Mutex,atomic::{AtomicBool,AtomicU64,Ordering}},future::Future,pin::Pin};
use tokio::sync::{mpsc,oneshot};
struct Context {
 original:Arc<OwnedOperationScope>,deadline:Instant,slot:CancellationToken,socket:Arc<Mutex<Option<Socket>>>,
 read:Mutex<Option<SavedEmbedRead>>,pending:AtomicU64,returned:AtomicBool,abandoned:AtomicBool,taken:AtomicBool,
}
impl Context {
 fn negative(&self)->Result<()>{self.original.observer().check_release()?;if self.slot.is_cancelled(){return Err(Error::Cancelled)}if Instant::now()>=self.deadline{return Err(Error::Offline)}self.original.observer().check_original_negative()}
 fn check(&self,c:&Client)->Result<()>{personal(c)?;self.original.check(c)?;self.negative()}
 fn cancel(&self){self.slot.cancel();self.original.observer().cancel();}
 async fn close_socket(&self)->Result<()>{
  let actual=self.socket.lock().map_err(|_|Error::Protocol)?.as_ref().map(Socket::original_phase_handle);
  if let Some(mut socket)=actual{if socket.close(None).await.is_err(){self.abandoned.store(true,Ordering::Release);return Err(Error::Offline)}}
  *self.socket.lock().map_err(|_|Error::Protocol)?=None;Ok(())
 }
 fn terminal(&self)->bool{self.returned.load(Ordering::Acquire)&&self.pending.load(Ordering::Acquire)==0&&!self.abandoned.load(Ordering::Acquire)&&self.socket.try_lock().is_ok_and(|v|v.is_none())}
}
struct ChatPlan {id:String,row:Plain<Value>,selected:Option<Plain<Value>>,cipher:Option<Zeroizing<String>>,direct:Option<Key>}
enum Work {AuthPrepare(bool),AuthHeaders(OwnedSessionValidationHeaders),AuthFinish(CompletedOwnedSessionValidation,bool),Connected(UnannouncedOwnedMonitorSocket),Check,Master,
 Admit{wanted:String,response:Plain<Value>,source:Option<SourceChat>},ChatPrepare(Plain<Value>),ChatFinish(ChatPlan,Key),Publish(SavedEmbedRead)}
enum Resume {Auth(PreparedOwnedSessionValidation),Body(OwnedSessionValidationBody),Socket(PreparedOwnedMonitorSocket),Connected(UnannouncedOwnedMonitorSocket,Result<()>),Unit,Master(MasterCapability),
 Admitted(SourceChat,Plain<Value>,Plain<Vec<Value>>),Chat(Option<ChatPlan>),Key(Key)}
struct Pending {context:Arc<Context>,work:Option<Work>,reply:Option<oneshot::Sender<Result<Resume>>>}
impl Drop for Pending {fn drop(&mut self){if let Some(reply)=self.reply.take(){self.context.abandoned.store(true,Ordering::Release);self.context.cancel();self.context.pending.store(0,Ordering::Release);let _=reply.send(Err(Error::Cancelled));}}}
struct Channel {context:Arc<Context>,send:mpsc::UnboundedSender<Pending>}
impl Channel {
 async fn call(&self,work:Work)->Result<Resume>{
  self.context.pending.compare_exchange(0,1,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
  let(reply,receive)=oneshot::channel();self.send.send(Pending{context:self.context.clone(),work:Some(work),reply:Some(reply)}).map_err(|_|Error::Cancelled)?;
  receive.await.map_err(|_|Error::Cancelled)?
 }
 async fn check(&self)->Result<()>{self.context.negative()?;let Resume::Unit=self.call(Work::Check).await?else{return Err(Error::Protocol)};Ok(())}
 async fn auth(&self,open:bool)->Result<Option<PreparedOwnedMonitorSocket>>{
  let Resume::Auth(prepared)=self.call(Work::AuthPrepare(open)).await?else{return Err(Error::Protocol)};
  let headers=crate::client::auth::send_owned_session_validation_headers_with_negative(prepared,||self.context.negative()).await;
  let Resume::Body(body)=self.call(Work::AuthHeaders(headers)).await?else{return Err(Error::Protocol)};
  let completed=crate::client::auth::drive_owned_session_validation_body(body).await;
  match self.call(Work::AuthFinish(completed,open)).await?{Resume::Socket(value)if open=>Ok(Some(value)),Resume::Unit if !open=>Ok(None),_=>Err(Error::Protocol)}
 }
}
pub struct OwnedSavedEmbedReadApply {pending:Pending}
impl OwnedSavedEmbedReadApply {
 pub fn apply(mut self,c:&mut Client)->Result<()>{
  let ctx=self.pending.context.clone();let work=self.pending.work.take().ok_or(Error::Conflict)?;
  let result=match work{
   // Actual received auth bookkeeping is applied before local cancellation.
   Work::AuthHeaders(headers)=>{
    let actual=c.apply_owned_session_validation_headers(headers);
    // A refused original-target apply may have dropped a started response
    // before its body was consumed. Returned Err is NOT an IO terminal.
    // Keep this acquisition conservatively unknown; never rearm/ACK it.
    if actual.is_err(){ctx.abandoned.store(true,Ordering::Release);}
    actual.map(Resume::Body)
   },
   Work::AuthFinish(completed,open)=>(||{
    // This actual phase alone proves EOF/never-dispatched plus same original
    // target. An Ok Body containing a dropped response is still Unknown.
    if completed.io_terminal_for(c).is_none(){ctx.abandoned.store(true,Ordering::Release);}
    let receipt=c.finish_owned_session_validation(completed)?;ctx.check(c)?;
    if open{let mut active=ActiveOwnedClient::enter(c,&ctx.original)?;Ok(Resume::Socket(transport::prepare_owned_saved_embed_socket(&mut active,ctx.original.clone(),receipt,ctx.slot.clone(),ctx.socket.clone(),ctx.deadline)?))}else{Ok(Resume::Unit)}
   })(),
   Work::Connected(value)=>{let checked=ctx.check(c).and_then(|_|value.check(c));Ok(Resume::Connected(value,checked))},
   work=>(||{ctx.check(c)?;let mut active=ActiveOwnedClient::enter(c,&ctx.original)?;
    let resume=match work{
     Work::AuthPrepare(open)=>{if open{active.invalidate_chat_inventory_proofs();active.chat_list_freshness.invalidate();}Resume::Auth(active.prepare_owned_session_validation(ctx.original.clone())?.restrict_saved_embed_deadline(ctx.deadline))},
     Work::Check=>Resume::Unit,Work::Master=>Resume::Master(active.master_capability()?),
     Work::Admit{wanted,response,source}=>{let(next,row,keys)=admit_row(&active,&*ctx.original,&response,&wanted,source.as_ref())?;Resume::Admitted(source.unwrap_or(next),Plain::new(row),Plain::new(keys))},
     Work::ChatPrepare(wrapper)=>Resume::Chat(prepare_chat(&active,&ctx.original,&wrapper)?),
     Work::ChatFinish(plan,key)=>{check_chat_plan(&active,&ctx.original,&plan)?;Resume::Key(key)},
     Work::Publish(read)=>{read.check(&active)?;let mut slot=ctx.read.lock().map_err(|_|Error::Protocol)?;if slot.is_some(){return Err(Error::Conflict)}*slot=Some(read);Resume::Unit},
     _=>return Err(Error::Protocol),
    };drop(active);ctx.check(c)?;Ok(resume)
   })(),
  };
  let reply=self.pending.reply.take().ok_or(Error::Conflict)?;ctx.pending.store(0,Ordering::Release);reply.send(result).map_err(|_|Error::Cancelled)
 }
}
fn selected_chat_wrapper(c:&Client,row:&Value)->Option<Plain<Value>>{let id=required(row,"id").ok()?;c.wrappers.iter().chain(row["chat_key_wrappers"].as_array().into_iter().flatten()).find(|w|text(w,"hashed_chat_id")==sha256(id)&&text(w,"key_type")=="master").cloned().map(Plain::new)}
fn prepare_chat(c:&Client,scope:&OwnedOperationScope,wrapper:&Value)->Result<Option<ChatPlan>>{
 let hash=required(wrapper,"hashed_chat_id")?;let Some((id,row))=c.chats.iter().find(|(id,_)|sha256(id)==hash)else{return Ok(None)};
 scope.check(c)?;scope.crypto.check_chat(c,id)?;
 let(selected,cipher,direct)=if text(row,"chat_visibility")=="direct"{c.native_master_key()?;(None,None,Some(c.direct_chat_key(row)?))}else{
  let selected=selected_chat_wrapper(c,row);let cipher=c.chat_key_ciphertext_from(row,false,&c.wrappers)?.ciphertext;
  (selected,Some(Zeroizing::new(cipher.to_owned())),None)
 };
 scope.crypto.check_chat(c,id)?;Ok(Some(ChatPlan{id:id.clone(),row:Plain::new(row.clone()),selected,cipher,direct}))
}
fn check_chat_plan(c:&Client,scope:&OwnedOperationScope,plan:&ChatPlan)->Result<()>{
 scope.check(c)?;scope.crypto.check_chat(c,&plan.id)?;let row=c.chats.get(&plan.id).ok_or(Error::Cancelled)?;
 if row!=&*plan.row{return Err(Error::Cancelled)}
 if let Some(cipher)=&plan.cipher{if c.chat_key_ciphertext_from(row,false,&c.wrappers)?.ciphertext!=cipher.as_str()||selected_chat_wrapper(c,row).as_deref()!=plan.selected.as_deref(){return Err(Error::Cancelled)}}
 scope.crypto.check_chat(c,&plan.id)
}
struct KeyPhases<'a>{channel:&'a Channel,scope:&'a VersionReadScope}
impl Phases for KeyPhases<'_>{
 fn check(&self)->PhaseFuture<'_,()>{Box::pin(async move{self.channel.check().await?;self.scope.check_original_negative()})}
 fn master(&self)->PhaseFuture<'_,MasterCapability>{Box::pin(async move{let Resume::Master(master)=self.channel.call(Work::Master).await?else{return Err(Error::Protocol)};self.scope.check_original_negative()?;Ok(master)})}
 fn candidate<'a>(&'a self,wanted:&str,staged:&'a BTreeMap<String,Value>,keys:&'a [Value],cached:bool)->Result<Candidate<'a>>{if cached{return Err(Error::Protocol)}self.scope.check_original_negative()?;selected_key::candidate(None,wanted,staged,keys,false)}
 fn wrapper<'a>(&'a self,row:&'a Value)->PhaseFuture<'a,()>{Box::pin(async move{self.scope.check_original_negative()?;self.scope.wrapper(row)})}
 fn decrypt<'a>(&'a self,master:&'a MasterCapability,cipher:&'a str)->PhaseFuture<'a,Zeroizing<Vec<u8>>>{Box::pin(async move{
  self.channel.check().await?;self.scope.check_original_negative()?;let actual=master.decrypt_bytes(cipher).await;
  self.scope.check_original_negative()?;self.channel.check().await?;actual
 })}
 fn chat<'a>(&'a self,wrapper:&'a Value,master:&'a MasterCapability)->PhaseFuture<'a,Option<Key>>{Box::pin(async move{
  let Resume::Chat(plan)=self.channel.call(Work::ChatPrepare(Plain::new(wrapper.clone()))).await?else{return Err(Error::Protocol)};let Some(mut plan)=plan else{return Ok(None)};
  if let Some(selected)=&plan.selected{self.scope.wrapper(selected)?;}self.scope.check_original_negative()?;
  let key=if let Some(key)=plan.direct.take(){key}else{let bytes=self.decrypt(master,plan.cipher.as_deref().ok_or(Error::Protocol)?).await?;key_from_bytes(&bytes)?};
  let Resume::Key(key)=self.channel.call(Work::ChatFinish(plan,key)).await?else{return Err(Error::Protocol)};
  self.scope.check_original_negative()?;self.scope.wrapper(wrapper)?;
  let bytes=crypto::server_fields::decrypt_bytes(required(wrapper,"encrypted_embed_key")?,&key,&[])?;
  self.channel.check().await?;self.scope.check_original_negative()?;key_from_bytes(&bytes).map(Some)
 })}
}
async fn wire(channel:&Channel,scope:&VersionReadScope,wanted:&str,bytes:&mut usize)->Result<Plain<Value>>{
 channel.check().await?;scope.check_original_negative()?;
 // Only this operation consumes this dedicated actual socket. The guard keeps
 // it in original ownership even if the outer drive future is abandoned.
 let mut socket=channel.context.socket.lock().map_err(|_|Error::Protocol)?.as_ref().ok_or(Error::Conflict)?.original_phase_handle();let ws=&mut socket;
 let result=async{
  scope.run_io(transport::send(ws,"request_embed",json!({"embed_id":wanted}))).await?;
  for _ in 0..MAX_UNRELATED_FRAMES{
   channel.context.negative()?;let(event,value)=scope.run_io(async{let(event,value)=transport::receive_ephemeral(ws).await?;let value=Plain::new(value);if event=="error"{return Err(match value["status"].as_u64(){Some(401)=>Error::Expired,Some(403|404)=>Error::Forbidden,_=>Error::Protocol})}Ok((event,value))}).await?;
   *bytes=bytes.checked_add(Zeroizing::new(serde_json::to_vec(&*value)?).len()).ok_or(Error::Protocol)?;if *bytes>MAX_BYTES{return Err(Error::Protocol)}
   if event=="send_embed_data"{if value["embed_id"].as_str()!=Some(wanted){return Err(Error::Forbidden)}return Ok(value)}
  }Err(Error::Protocol)
 }.await;
 drop(socket);if matches!(&result,Err(Error::Expired|Error::Forbidden)){return result}channel.context.negative()?;scope.check_original_negative()?;result
}
async fn drive(channel:Channel,scope:VersionReadScope,id:String)->Result<()>{
 let result=async{
  channel.auth(false).await?;let prepared=channel.auth(true).await?.ok_or(Error::Protocol)?;
  let connected=match transport::connect_owned_passive_monitor_socket(prepared).await{Ok(value)=>value,Err(error)=>{channel.context.abandoned.store(true,Ordering::Release);return Err(error)}};
  let Resume::Connected(connected,checked)=channel.call(Work::Connected(connected)).await?else{return Err(Error::Protocol)};
  if let Err(error)=checked{if connected.retire().await.is_err(){channel.context.abandoned.store(true,Ordering::Release)}return Err(error)}
  let socket=transport::announce_owned_passive_monitor_socket(connected).await?;*channel.context.socket.lock().map_err(|_|Error::Protocol)?=Some(socket);
  let mut staged=Plain::new(BTreeMap::new());let mut keys=Plain::new(Vec::new());let mut source=None;let mut visited=HashSet::new();let mut wanted=id.clone();let mut bytes=0;
  #[cfg(target_arch="wasm32")]let mut native_source=Plain::new(Value::Null);
  loop{
   if visited.len()>=MAX_CHAIN||!visited.insert(wanted.clone()){return Err(Error::Crypto)}
   let response=wire(&channel,&scope,&wanted,&mut bytes).await?;
   #[cfg(target_arch="wasm32")]if wanted==id{*native_source=response.clone();}
   let Resume::Admitted(next,row,wrappers)=channel.call(Work::Admit{wanted:wanted.clone(),response,source}).await?else{return Err(Error::Protocol)};source=Some(next);
   let parent=row["parent_embed_id"].as_str().map(str::to_owned);staged.insert(wanted.clone(),row.into_inner());keys.extend(wrappers.into_inner());if keys.len()>MAX_WRAPPERS{return Err(Error::Protocol)}
   let key=selected_key::select(&KeyPhases{channel:&channel,scope:&scope},&id,&staged,&keys,false).await;
   match key{
    Ok(key)=>{channel.check().await?;scope.check_original_negative()?;let value=decode(staged.get(&id).ok_or(Error::Protocol)?,&id,&key)?;
     channel.context.close_socket().await?;channel.check().await?;scope.check_original_negative()?;
     let read=SavedEmbedRead{scope,value,_key:key,source:source.ok_or(Error::Protocol)?,#[cfg(target_arch="wasm32")]native_source};
     let Resume::Unit=channel.call(Work::Publish(read)).await?else{return Err(Error::Protocol)};return Ok(())
    },Err(Error::Forbidden|Error::Crypto)if parent.is_some()=>{},Err(error)=>return Err(error),
   }wanted=parent.ok_or(Error::Forbidden)?;
  }
 }.await;
 if matches!(&result,Err(Error::Offline|Error::Unavailable{..})){channel.context.abandoned.store(true,Ordering::Release)}
 if result.is_err()&&channel.context.close_socket().await.is_err(){channel.context.abandoned.store(true,Ordering::Release)}result
}
pub enum OwnedSavedEmbedReadStep {Apply(OwnedSavedEmbedReadApply),Ready(OwnedSavedEmbedReadReady)}
pub struct OwnedSavedEmbedReadControl {context:Arc<Context>}
impl OwnedSavedEmbedReadControl {
 pub fn ensure_current(&self,c:&Client)->Result<()>{self.context.check(c)?;if let Some(read)=&*self.context.read.lock().map_err(|_|Error::Protocol)?{read.check(c)?;}self.context.negative()}
 pub fn cancel(&self){self.context.cancel()}
 pub fn terminal(&self)->Option<OwnedSavedEmbedReadTerminal>{self.context.terminal().then(||OwnedSavedEmbedReadTerminal{context:self.context.clone()})}
}
/// This exact acquisition returned and its dedicated socket closed. No native
/// store/monitor/Root/global recovery durability or ACK is implied.
pub struct OwnedSavedEmbedReadTerminal {context:Arc<Context>}
impl OwnedSavedEmbedReadTerminal {pub fn acquisition_io_quiescent(&self)->bool{self.context.terminal()}}
pub struct PreparedOwnedSavedEmbedRead {context:Arc<Context>,future:Pin<Box<dyn Future<Output=Result<()>>>>,pending:mpsc::UnboundedReceiver<Pending>,finished:bool}
impl PreparedOwnedSavedEmbedRead {
 pub fn control(&self)->OwnedSavedEmbedReadControl{OwnedSavedEmbedReadControl{context:self.context.clone()}}
 pub async fn next(&mut self)->Result<OwnedSavedEmbedReadStep>{
  if self.finished||self.context.pending.load(Ordering::Acquire)!=0{return Err(Error::Conflict)}
  tokio::select!{biased;result=&mut self.future=>{self.finished=true;self.context.returned.store(true,Ordering::Release);result?;self.context.negative()?;Ok(OwnedSavedEmbedReadStep::Ready(OwnedSavedEmbedReadReady{context:self.context.clone()}))},pending=self.pending.recv()=>Ok(OwnedSavedEmbedReadStep::Apply(OwnedSavedEmbedReadApply{pending:pending.ok_or(Error::Cancelled)?}))}
 }
}
impl Drop for PreparedOwnedSavedEmbedRead {fn drop(&mut self){if !self.finished{self.context.abandoned.store(true,Ordering::Release);self.context.cancel();}}}
pub struct OwnedSavedEmbedReadReady {context:Arc<Context>}
impl OwnedSavedEmbedReadReady {
 pub fn retain(&mut self,c:&Client)->Result<SavedEmbedRead>{
  self.context.check(c)?;if !self.context.terminal()||self.context.taken.load(Ordering::Acquire){return Err(Error::Conflict)}
  let mut slot=self.context.read.lock().map_err(|_|Error::Protocol)?;slot.as_ref().ok_or(Error::Conflict)?.check(c)?;
  self.context.taken.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;slot.take().ok_or(Error::Conflict)
 }
}
impl Drop for OwnedSavedEmbedReadReady {fn drop(&mut self){if !self.context.taken.load(Ordering::Acquire){self.context.cancel();}}}
impl Client {
 /// Explicit prototype web operation only. The same genuine saved resource is
 /// retained after detached next()/short matched Apply phases. No native SDK
 /// default, monitor replacement, global child/reset or auth discovery occurs.
 pub fn prepare_owned_saved_embed_read(&mut self,id:&str,request:CancellationToken)->Result<PreparedOwnedSavedEmbedRead>{
  if !canonical(id){return Err(Error::Invalid("A canonical full embed ID is required."))}personal(self)?;self.require_browser_owner_guards()?;
  let original=Arc::new(OwnedOperationScope::capture(self,request)?);
  let scope={let active=ActiveOwnedClient::enter(self,&original)?;VersionReadScope::begin_owned(&active)?};
  let deadline=scope.original_deadline();let slot=original.request().child_token();
  let context=Arc::new(Context{original,deadline,slot,socket:Arc::new(Mutex::new(None)),read:Mutex::new(None),pending:AtomicU64::new(0),returned:AtomicBool::new(false),abandoned:AtomicBool::new(false),taken:AtomicBool::new(false)});context.check(self)?;
  let(send,pending)=mpsc::unbounded_channel();let channel=Channel{context:context.clone(),send};
  Ok(PreparedOwnedSavedEmbedRead{context,future:Box::pin(drive(channel,scope,id.to_owned())),pending,finished:false})
 }
}
#[cfg(all(test,not(target_arch="wasm32")))]#[path="saved_embed_owned_tests.rs"]mod tests;
