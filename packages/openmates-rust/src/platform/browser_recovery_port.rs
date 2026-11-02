//! Original owning-Worker MessagePort. This resource proves native transport
//! provenance only; the client physical child alone validates/mints durability.
//! No generic Worker message, JSON, callback, owner label or success bit can
//! construct a delivery. Caller retains this resource through actual drain.
use crate::{Client,Error,Result};
use crate::client::{BrowserRecoveryPortRoot,OriginalRecoveryCheckpointIoTicket};
use std::{cell::{Cell,RefCell},collections::BTreeMap,rc::Rc,sync::Arc};
use futures_channel::oneshot;
use tokio::sync::Notify;
use wasm_bindgen::{JsCast,JsValue,closure::Closure};
use js_sys::Array;
#[path="browser_recovery_port/inventory.rs"]
mod inventory;
pub(crate) use inventory::{NativeDraftInventoryPortPending,NativeDraftInventoryPortDelivery,NativeDraftInventoryObservation};
const MAX_PENDING:usize=100; // Existing owning-request bound; no user quota.
const MAX_SEQUENCE:u64=9_007_199_254_740_991;
const MAX_RECORD:usize=32*1024*1024;
thread_local!{static CAPTURED:Cell<bool>=const{Cell::new(false)};}

// Intrinsics and private original port values stay inside this compiled module.
// No eval, global callback, caller-supplied function or public finish(JSONObject).
#[wasm_bindgen::prelude::wasm_bindgen(inline_js = "
const et=Object.getOwnPropertyDescriptor(Event.prototype,'target').get;
const ey=Object.getOwnPropertyDescriptor(Event.prototype,'type').get;
const md=Object.getOwnPropertyDescriptor(MessageEvent.prototype,'data').get;
const mp=Object.getOwnPropertyDescriptor(MessageEvent.prototype,'ports').get;
const post=MessagePort.prototype.postMessage, start=MessagePort.prototype.start, close=MessagePort.prototype.close;
const add=EventTarget.prototype.addEventListener, remove=EventTarget.prototype.removeEventListener;
const defer=globalThis.queueMicrotask.bind(globalThis);
const own=(v,ks)=>v!==null&&typeof v==='object'&&Object.getPrototypeOf(v)===Object.prototype&&Reflect.ownKeys(v).length===ks.length&&ks.every(k=>Object.hasOwn(v,k))&&Object.values(Object.getOwnPropertyDescriptors(v)).every(p=>'value'in p);
export function recoveryCapture(e){
 if(!(globalThis instanceof DedicatedWorkerGlobalScope)||ey.call(e)!=='message'||et.call(e)!==globalThis||e.isTrusted!==true)throw Error('unavailable');
 const d=md.call(e),ps=mp.call(e);
 if(!own(d,['version','operation','artifact','apiUrl','appOrigin','sessionId','expectedPrincipal'])||d.version!==1||d.operation!=='bootstrap_existing_key'||typeof d.artifact!=='string'||!/^[a-f0-9]{64}$/.test(d.artifact)||d.appOrigin!==globalThis.location.origin||![d.apiUrl,d.sessionId,d.expectedPrincipal].every(v=>typeof v==='string')||ps.length>1)throw Error('unavailable');
 return [ps.length===1?ps[0]:null,d.apiUrl,d.sessionId,d.expectedPrincipal];
}
export function recoveryListen(p,f){add.call(p,'message',f);add.call(p,'messageerror',f);start.call(p);}
export function recoveryUnlisten(p,f){remove.call(p,'message',f);remove.call(p,'messageerror',f);}
export function recoveryClose(p){close.call(p);}
export function recoveryDefer(f){defer(f);}
export function recoveryRequest(p,c,s,o,e){post.call(p,{version:1,contextId:c,sequence:s,operationId:o,effect:JSON.parse(e)});}
export function recoveryInventoryRequest(p,c,s,o,e){post.call(p,{version:1,domain:'draft_inventory',contextId:c,sequence:s,operationId:o,effect:JSON.parse(e)});}
export function recoveryCancel(p,c,s,o){post.call(p,{version:1,contextId:c,sequence:s,operationId:o,cancel:true});}
export function recoveryStop(p,c){post.call(p,{version:1,contextId:c,close:true});}
export function recoveryRead(p,e){
 const type=ey.call(e);if(et.call(e)!==p||e.isTrusted!==true)return ['untrusted'];
 if(type==='messageerror')return ['lost'];if(type!=='message')return ['untrusted'];
 const d=md.call(e);if(!d||typeof d!=='object'||d.version!==1)return ['invalid'];
 if(own(d,['version','admitted'])&&own(d.admitted,['contextId'])&&typeof d.admitted.contextId==='string')return ['admitted',d.admitted.contextId];
 if(own(d,['version','contextId','revoked'])&&d.revoked===true&&typeof d.contextId==='string')return ['revoked',d.contextId];
 if(own(d,['version','contextId','closed'])&&d.closed===true&&typeof d.contextId==='string')return ['closed',d.contextId];
 if(own(d,['version','contextId','domain','ready'])&&d.domain==='draft_inventory'&&d.ready===true&&typeof d.contextId==='string')return ['inventory_ready',d.contextId];
 if(own(d,['version','domain','contextId','sequence','operationId','result'])&&d.domain==='draft_inventory'&&typeof d.contextId==='string'&&Number.isSafeInteger(d.sequence)&&d.sequence>=1&&typeof d.operationId==='string'){
  const r=d.result;if(own(r,['ok','packet'])&&r.ok===true&&typeof r.packet==='string'&&r.packet.length<=2097152)return ['inventory_reply',d.contextId,d.sequence,d.operationId,true,r.packet];
  if(own(r,['ok','error'])&&r.ok===false&&['unavailable','cancelled','conflict'].includes(r.error))return ['inventory_reply',d.contextId,d.sequence,d.operationId,false,r.error];return ['invalid'];
 }
 if(!own(d,['version','contextId','sequence','operationId','result'])||typeof d.contextId!=='string'||!Number.isSafeInteger(d.sequence)||d.sequence<1||typeof d.operationId!=='string')return ['invalid'];
 const r=d.result;
 if(own(r,['ok','record'])&&r.ok===true&&(r.record===null||typeof r.record==='string'))return ['reply',d.contextId,d.sequence,d.operationId,true,r.record];
 if(own(r,['ok','error'])&&r.ok===false&&['unavailable','cancelled','conflict'].includes(r.error))return ['reply',d.contextId,d.sequence,d.operationId,false,r.error];
 return ['invalid'];
}
")]
extern "C"{
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=recoveryCapture)]fn capture(event:&JsValue)->std::result::Result<JsValue,JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=recoveryListen)]fn listen(port:&JsValue,callback:&JsValue)->std::result::Result<(),JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(js_name=recoveryUnlisten)]fn unlisten(port:&JsValue,callback:&JsValue);
 #[wasm_bindgen::prelude::wasm_bindgen(js_name=recoveryClose)]fn close(port:&JsValue);
 #[wasm_bindgen::prelude::wasm_bindgen(js_name=recoveryDefer)]fn defer(callback:JsValue);
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=recoveryRequest)]fn request(port:&JsValue,context:&str,sequence:f64,operation:&str,effect:&str)->std::result::Result<(),JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=recoveryInventoryRequest)]fn inventory_request(port:&JsValue,context:&str,sequence:f64,operation:&str,effect:&str)->std::result::Result<(),JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=recoveryCancel)]fn cancel(port:&JsValue,context:&str,sequence:f64,operation:&str)->std::result::Result<(),JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=recoveryStop)]fn stop(port:&JsValue,context:&str)->std::result::Result<(),JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=recoveryRead)]fn read(port:&JsValue,event:&JsValue)->std::result::Result<JsValue,JsValue>;
}
fn unavailable()->Error{Error::Unavailable{code:"recovery_checkpoint_port_unavailable",reason:"ORIGINAL_NATIVE_STORAGE_TERMINAL_REQUIRED"}}
fn uuid(value:&str)->bool{uuid::Uuid::parse_str(value).is_ok_and(|id|id.to_string()==value)}

/// First native valid-bootstrap capture only. The thin binding keeps this
/// unbound object PRIVATE until actual restore constructs the owning Client.
#[doc(hidden)]
pub struct CapturedBrowserRecoveryPort {port:Option<JsValue>,api:String,session:String,principal:String}
impl CapturedBrowserRecoveryPort {
 /// Must be called only in the actual already-valid FIRST production bootstrap
 /// branch before normal RPC/Worker escape. Zero ports is feature-off exact.
 pub fn capture_first(event:&JsValue)->Result<Option<Self>>{
  let values:Array=capture(event).map_err(|_|unavailable())?.dyn_into().map_err(|_|unavailable())?;
  if values.length()!=4{return Err(unavailable())}
  if CAPTURED.with(|once|once.replace(true)){return Err(unavailable())}
  let port=values.get(0);if port.is_null(){return Ok(None)}
  let api=values.get(1).as_string().ok_or_else(unavailable)?;
  let session=values.get(2).as_string().ok_or_else(unavailable)?;
  let principal=values.get(3).as_string().ok_or_else(unavailable)?;
  Ok(Some(Self{port:Some(port),api,session,principal}))
 }
 /// Consume INSIDE the actual restore constructor before publishing Client or
 /// status; never accept a later arbitrary Client/owner through generic RPC.
 pub fn bind_original(mut self,client:&Client)->Result<OriginalBrowserRecoveryPort>{
  let root=client.capture_browser_recovery_port_root()?;
  root.check_bootstrap(&self.api,&self.session,&self.principal)?;
  let inner=Rc::new(Inner{port:self.port.take().ok_or_else(unavailable)?,root:Rc::new(root),context:RefCell::new(None),next:Cell::new(0),pending:RefCell::new(BTreeMap::new()),inventory:RefCell::new(BTreeMap::new()),inventory_ready:Cell::new(false),
   revoked:Cell::new(false),failed:Cell::new(false),close_sent:Cell::new(false),closed_ack:Cell::new(false),changed:Notify::new(),listener:RefCell::new(None)});
  let weak=Rc::downgrade(&inner);
  let callback=Closure::wrap(Box::new(move|event:JsValue|{if let Some(inner)=weak.upgrade(){
   // Last resource drops cannot destroy this callback while it is executing.
   let later=inner.clone();defer(Closure::once_into_js(move||drop(later)));
   Inner::receive(&inner,&event);
  }})as Box<dyn FnMut(JsValue)>);
  listen(&inner.port,callback.as_ref()).map_err(|_|unavailable())?;
  inner.listener.replace(Some(callback));
  inner.root.check_original(client)?;
  Ok(OriginalBrowserRecoveryPort{inner})
 }
}
impl Drop for CapturedBrowserRecoveryPort {fn drop(&mut self){if let Some(port)=self.port.take(){close(&port);}}}
struct Slot {
 ticket:Arc<OriginalRecoveryCheckpointIoTicket>,sender:oneshot::Sender<NativeRecoveryPortDelivery>,
 actual_terminal:Rc<Cell<bool>>,cancel_sent:bool,_keepalive:Rc<Inner>,
}
struct Inner {
 port:JsValue,root:Rc<BrowserRecoveryPortRoot>,context:RefCell<Option<String>>,next:Cell<u64>,pending:RefCell<BTreeMap<u64,Slot>>,
 revoked:Cell<bool>,failed:Cell<bool>,close_sent:Cell<bool>,closed_ack:Cell<bool>,changed:Notify,
 inventory:RefCell<BTreeMap<u64,inventory::Slot>>,inventory_ready:Cell<bool>,
 listener:RefCell<Option<Closure<dyn FnMut(JsValue)>>>,
}
impl Drop for Inner {fn drop(&mut self){if let Some(callback)=self.listener.get_mut().take(){unlisten(&self.port,callback.as_ref());}close(&self.port);}}
impl Inner {
 fn check(&self)->Result<()>{
  if self.revoked.get()||self.failed.get(){return Err(Error::Cancelled)}
  self.root.check_release()?;
  if self.revoked.get()||self.failed.get(){return Err(Error::Cancelled)}
  self.root.check_negative()
 }
 fn cancel_slot(&self,sequence:u64){
  if !self.pending.borrow().contains_key(&sequence){inventory::cancel_slot(self,sequence);return;}
  let value={let mut slots=self.pending.borrow_mut();slots.get_mut(&sequence).and_then(|slot|{if slot.cancel_sent{return None}slot.cancel_sent=true;Some(slot.ticket.operation_id().to_owned())})};
  if let(Some(operation),Some(context))=(value,self.context.borrow().clone()){
   if cancel(&self.port,&context,sequence as f64,&operation).is_err(){self.failed.set(true);self.changed.notify_waiters();}
  }
 }
 fn revoke(&self){
  self.revoked.set(true);
  let sequences:Vec<_>=self.pending.borrow().keys().chain(self.inventory.borrow().keys()).copied().collect();for sequence in sequences{self.cancel_slot(sequence);}
  if !self.close_sent.replace(true){if let Some(context)=self.context.borrow().as_ref(){if stop(&self.port,context).is_err(){self.failed.set(true)}}else if self.pending.borrow().is_empty()&&self.inventory.borrow().is_empty(){self.closed_ack.set(true)}}
  self.changed.notify_waiters();
 }
 fn fail(&self){self.failed.set(true);self.revoke();}
 fn receive(inner:&Rc<Self>,event:&JsValue){
  let frame=match read(&inner.port,event).and_then(|v|v.dyn_into::<Array>().map_err(|v|v)){Ok(v)=>v,Err(_)=>return};
  let kind=frame.get(0).as_string().unwrap_or_default();
  if kind=="untrusted"{return}
  if kind=="admitted"{
   let Some(context)=frame.get(1).as_string().filter(|v|uuid(v))else{inner.fail();return};
   if inner.context.borrow().is_some(){inner.fail();return}inner.context.replace(Some(context));inner.changed.notify_waiters();
   if inner.revoked.get(){inner.close_sent.set(false);inner.revoke();}return;
  }
  if matches!(kind.as_str(),"invalid"|"lost"){inner.fail();return}
  let context=frame.get(1).as_string();if context.as_deref()!=inner.context.borrow().as_deref(){inner.fail();return}
  if kind=="revoked"{inner.revoke();return}
  if kind=="closed"{if !inner.pending.borrow().is_empty()||!inner.inventory.borrow().is_empty(){inner.fail();return}inner.closed_ack.set(true);inner.changed.notify_waiters();return}
  if kind=="inventory_ready"{if inner.inventory_ready.replace(true){inner.fail();return}inner.changed.notify_waiters();return;}
  if kind=="inventory_reply"{inventory::receive(inner,&frame);return;}
  if kind!="reply"{inner.fail();return}
  let Some(sequence)=frame.get(2).as_f64().filter(|v|v.is_finite()&&v.fract()==0.0&&*v>=1.0&&*v<=MAX_SEQUENCE as f64).map(|v|v as u64)else{inner.fail();return};
  let Some(operation)=frame.get(3).as_string()else{inner.fail();return};
  // Late/copy replies never target a different current pending resource.
  let matches=inner.pending.borrow().get(&sequence).is_some_and(|slot|slot.ticket.operation_id()==operation);
  if !matches{return}
  let Some(slot)=inner.pending.borrow_mut().remove(&sequence)else{return};
  slot.actual_terminal.set(true); // ONLY the matched native private-port reply.
  let result=if frame.get(4).as_bool()==Some(true){
   let value=frame.get(5);if value.is_null(){Ok(None)}else{value.as_string().filter(|v|v.len()<=MAX_RECORD).map(Some).ok_or(Error::Protocol)}
  }else{Err(match frame.get(5).as_string().as_deref(){Some("conflict")=>Error::Conflict,Some("cancelled")=>Error::Cancelled,_=>unavailable()})};
  let result=inner.check().and_then(|_|slot.ticket.check_original_negative()).and(result);
  let delivery=NativeRecoveryPortDelivery{inner:inner.clone(),ticket:slot.ticket,sequence,result};
  let _=slot.sender.send(delivery);inner.changed.notify_waiters();
 }
}
/// Real private port/root resource only, not an auth/read/storage-success grant.
#[doc(hidden)]
#[derive(Clone)]
pub struct OriginalBrowserRecoveryPort {inner:Rc<Inner>}
impl OriginalBrowserRecoveryPort {
 #[cfg(feature="browser-metadata-prototype")]
 pub(crate) fn same_original(&self,other:&Self)->bool{Rc::ptr_eq(&self.inner,&other.inner)}
 /// Restrictive actual-root final check. Always combine with SAME Ticket/Stage
 /// and run callback-free port negatives after any later caller callback.
 pub(crate) fn check_original(&self,client:&Client)->Result<()>{
  self.inner.check()?;self.inner.root.check_original(client)?;self.check_negative()
 }
 /// Captured port/root negatives ONLY, without a caller gate or ready await.
 pub(crate) fn check_negative(&self)->Result<()>{
  if self.inner.revoked.get()||self.inner.failed.get(){return Err(Error::Cancelled)}
  self.inner.root.check_negative()?;
  if self.inner.revoked.get()||self.inner.failed.get(){return Err(Error::Cancelled)}Ok(())
 }
 pub async fn ready(&self)->Result<()>{loop{
  let wait=self.inner.changed.notified();tokio::pin!(wait);wait.as_mut().enable();
  self.inner.check()?;if self.inner.context.borrow().is_some(){return Ok(())}
  tokio::select!{_=self.inner.root.cancelled()=>return Err(Error::Cancelled),_=&mut wait=>{}}
 }}
 /// Full checks + actual post in ONE synchronous original-Client phase.
 pub(crate) fn start(&self,client:&Client,ticket:Arc<OriginalRecoveryCheckpointIoTicket>)->Result<NativeRecoveryPortPending>{
  self.inner.check()?;self.inner.root.check_original(client)?;ticket.check_original(client)?;
  self.post_checkpoint(ticket)
 }
 #[cfg(feature="browser-metadata-prototype")]
 pub(crate) fn start_metadata_retirement(&self,prepared:&crate::client::OriginalRecoveryRetirementTicket)->Result<NativeRecoveryPortPending>{
  prepared.check_port(self)?;self.inner.check()?;
  self.post_checkpoint(prepared.original_ticket().clone())
 }
 fn post_checkpoint(&self,ticket:Arc<OriginalRecoveryCheckpointIoTicket>)->Result<NativeRecoveryPortPending>{
  let context=self.inner.context.borrow().clone().ok_or_else(unavailable)?;
  if self.inner.pending.borrow().len()+self.inner.inventory.borrow().len()>=MAX_PENDING{return Err(Error::Conflict)}
  let sequence=self.inner.next.get().checked_add(1).filter(|v|*v<=MAX_SEQUENCE).ok_or_else(unavailable)?;
  ticket.claim_dispatch()?;
  self.inner.root.check_negative()?;ticket.check_original_negative()?;
  if self.inner.revoked.get()||self.inner.failed.get(){return Err(Error::Cancelled)}
  let(sender,receiver)=oneshot::channel();let actual_terminal=Rc::new(Cell::new(false));
  self.inner.next.set(sequence);
  self.inner.pending.borrow_mut().insert(sequence,Slot{ticket:ticket.clone(),sender,actual_terminal:actual_terminal.clone(),cancel_sent:false,_keepalive:self.inner.clone()});
  if request(&self.inner.port,&context,sequence as f64,ticket.operation_id(),ticket.effect()).is_err(){
   self.inner.pending.borrow_mut().remove(&sequence);self.inner.changed.notify_waiters();return Err(unavailable())
  }
  Ok(NativeRecoveryPortPending{inner:self.inner.clone(),ticket,sequence,receiver:Some(receiver),actual_terminal,finished:false})
 }
 pub fn revoke(&self){self.inner.revoke();}
 pub async fn close_and_drain(&self)->Result<()>{
  self.revoke();loop{
   let wait=self.inner.changed.notified();tokio::pin!(wait);wait.as_mut().enable();
   if self.inner.failed.get(){return Err(unavailable())} // NO quiescence claim.
   if self.inner.pending.borrow().is_empty()&&self.inner.inventory.borrow().is_empty()&&self.inner.closed_ack.get(){close(&self.inner.port);return Ok(())}
   wait.await;
  }
 }
}
/// Awaiting/abandoning this object alone does not prove native IO termination.
#[doc(hidden)]
pub struct NativeRecoveryPortPending {
 inner:Rc<Inner>,ticket:Arc<OriginalRecoveryCheckpointIoTicket>,sequence:u64,
 receiver:Option<oneshot::Receiver<NativeRecoveryPortDelivery>>,actual_terminal:Rc<Cell<bool>>,finished:bool,
}
impl NativeRecoveryPortPending {
 pub async fn drive(mut self)->Result<NativeRecoveryPortDelivery>{
  let mut receiver=self.receiver.take().ok_or_else(unavailable)?;
  let delivery=tokio::select!{biased;
   result=&mut receiver=>result.map_err(|_|unavailable())?,
   _=self.ticket.cancelled()=>{self.inner.cancel_slot(self.sequence);receiver.await.map_err(|_|unavailable())?},
  };
  self.finished=true;Ok(delivery)
 }
 /// Restrictive fact only. Port loss/bare cancellation never sets this bit.
 pub fn actual_terminal_observed(&self)->bool{self.actual_terminal.get()}
}
impl Drop for NativeRecoveryPortPending {fn drop(&mut self){if !self.finished{self.inner.cancel_slot(self.sequence);}}}
/// Only actual private native message reception can construct this one-use DATA.
#[doc(hidden)]
pub struct NativeRecoveryPortDelivery {inner:Rc<Inner>,ticket:Arc<OriginalRecoveryCheckpointIoTicket>,sequence:u64,result:Result<Option<String>>}
impl NativeRecoveryPortDelivery {
 pub(crate) fn consume_for(self,port:&OriginalBrowserRecoveryPort,ticket:&Arc<OriginalRecoveryCheckpointIoTicket>)->Result<Option<String>>{
  if !Rc::ptr_eq(&self.inner,&port.inner)||!Arc::ptr_eq(&self.ticket,ticket)||self.sequence==0{return Err(Error::Cancelled)}
  self.inner.check()?;ticket.check_original_negative()?;self.result
 }
}
