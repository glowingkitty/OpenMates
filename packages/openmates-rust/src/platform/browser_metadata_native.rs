//! Default-off original Worker/native IDB resource; no Master or crypto Root.
//! Native receipts are opaque objects, never caller record JSON/terminal flags.
use crate::{Error,Result};
use crate::client::MetadataNativeIoTicket;
use std::{cell::{Cell,RefCell},collections::BTreeMap,rc::Rc,sync::Arc};
use wasm_bindgen::{JsValue,JsCast,closure::Closure};
use js_sys::{Array,Promise};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;
#[wasm_bindgen::prelude::wasm_bindgen(module="/src/platform/browser_metadata_native.js")]
extern "C" {
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataCapture)]fn capture(event:&JsValue)->std::result::Result<JsValue,JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataCaptureStartup)]fn capture_startup(event:&JsValue)->std::result::Result<JsValue,JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataSelectors)]fn selectors(context:&JsValue)->std::result::Result<JsValue,JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataListenNegative)]fn listen(context:&JsValue,notify:&JsValue)->std::result::Result<(),JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(js_name=metadataUnlistenNegative)]fn unlisten(context:&JsValue,notify:&JsValue);
 #[wasm_bindgen::prelude::wasm_bindgen(js_name=metadataDeferDrop)]fn defer(callback:JsValue);
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataCheck)]fn check(context:&JsValue)->std::result::Result<(),JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataCheckProfile)]fn check_profile(context:&JsValue,owner:&str,version:f64)->std::result::Result<(),JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(js_name=metadataRevoke)]fn revoke(context:&JsValue);
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataProfile)]fn profile(context:&JsValue,recheck:bool)->std::result::Result<JsValue,JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataStart)]fn start(context:&JsValue,operation:&str,effect:&str)->std::result::Result<JsValue,JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataReplyStart)]fn start_reply(context:&JsValue,operation:&str,effect:&str)->std::result::Result<JsValue,JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataMainCodeEmbedStart)]fn start_main_code_embed(context:&JsValue,operation:&str,effect:&str)->std::result::Result<JsValue,JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataDrive)]fn drive(operation:&JsValue)->std::result::Result<Promise,JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataConsume)]fn consume(context:&JsValue,operation:&JsValue,receipt:&JsValue,kind:&str)->std::result::Result<JsValue,JsValue>;
 #[wasm_bindgen::prelude::wasm_bindgen(catch,js_name=metadataCloseCaptured)]fn close_captured()->std::result::Result<Promise,JsValue>;
}
fn unavailable()->Error{Error::Unavailable{code:"native_metadata_unavailable",reason:"ORIGINAL_NATIVE_METADATA_RESOURCE_REQUIRED"}}
struct Slot {operation:JsValue,ticket:Option<Arc<MetadataNativeIoTicket>>,_keepalive:Rc<Inner>}
struct Inner {native:JsValue,api:String,app:String,session:String,cancel:CancellationToken,held:Cell<bool>,profiled:Cell<bool>,next:Cell<u64>,slots:RefCell<BTreeMap<u64,Slot>>,listener:RefCell<Option<Closure<dyn FnMut()>>>,negative_revoke:RefCell<Option<Rc<dyn Fn()>>>}
impl Inner {fn deny(&self){self.cancel.cancel();if let Some(revoke)=self.negative_revoke.borrow().as_ref(){revoke();}}}
impl Drop for Inner {fn drop(&mut self){if let Some(callback)=self.listener.get_mut().take(){unlisten(&self.native,callback.as_ref());}revoke(&self.native);}}
/// Cloning retains the SAME original native resource, never a new admission.
#[derive(Clone)]
#[doc(hidden)]
pub struct NativeMetadataContext {inner:Rc<Inner>}
impl NativeMetadataContext {
 pub fn capture_first(event:&JsValue)->Result<Self>{Self::from_native(capture(event).map_err(|_|unavailable())?)}
 pub fn capture_startup_first(event:&JsValue)->Result<Self>{Self::from_native(capture_startup(event).map_err(|_|unavailable())?)}
 fn from_native(native:JsValue)->Result<Self>{
  let values:Array=selectors(&native).map_err(|_|unavailable())?.dyn_into().map_err(|_|unavailable())?;
  if values.length()!=3{return Err(unavailable())}
  let api=values.get(0).as_string().ok_or_else(unavailable)?;let app=values.get(1).as_string().ok_or_else(unavailable)?;let session=values.get(2).as_string().ok_or_else(unavailable)?;
  let inner=Rc::new(Inner{native,api,app,session,cancel:CancellationToken::new(),held:Cell::new(false),profiled:Cell::new(false),next:Cell::new(0),slots:RefCell::new(BTreeMap::new()),listener:RefCell::new(None),negative_revoke:RefCell::new(None)});
  let weak=Rc::downgrade(&inner);let callback=Closure::wrap(Box::new(move||{if let Some(inner)=weak.upgrade(){let later=inner.clone();defer(Closure::once_into_js(move||drop(later)));inner.deny();}})as Box<dyn FnMut()>);
  listen(&inner.native,callback.as_ref()).map_err(|_|unavailable())?;inner.listener.replace(Some(callback));let context=Self{inner};context.check_negative()?;Ok(context)
 }
 pub fn revoke_original(&self){self.inner.deny();revoke(&self.inner.native);}
 /// One negative-only observer on this original lifetime. It supplies no key,
 /// owner, auth or metadata admission and cannot reset native cancellation.
 pub(crate) fn register_negative_revoke(&self,negative:Rc<dyn Fn()>)->Result<()>{
  self.check_negative()?;if self.inner.negative_revoke.borrow().is_some(){return Err(Error::Conflict)}
  self.inner.negative_revoke.replace(Some(negative));self.check_negative()
 }
 pub(crate) fn native_operations_consumed(&self)->bool{!self.inner.held.get()&&self.inner.slots.borrow().is_empty()}
 pub fn selectors(&self)->(&str,&str,&str){(&self.inner.api,&self.inner.app,&self.inner.session)}
 pub fn same_original(&self,other:&Self)->bool{Rc::ptr_eq(&self.inner,&other.inner)}
 pub fn check_negative(&self)->Result<()>{if self.inner.held.get()||self.inner.cancel.is_cancelled(){self.inner.deny();return Err(Error::Cancelled)}check(&self.inner.native).map_err(|_|{self.inner.deny();Error::Cancelled})}
 pub async fn cancelled(&self){self.inner.cancel.cancelled().await}
 fn reserve_sequence(&self)->Result<u64>{
  self.check_negative()?;if !self.inner.slots.borrow().is_empty(){return Err(Error::Conflict)}
  let next=self.inner.next.get().checked_add(1).filter(|n|*n<=9_007_199_254_740_991).ok_or(Error::Protocol)?;self.inner.next.set(next);Ok(next)
 }
 fn retain(&self,sequence:u64,operation:JsValue,ticket:Option<Arc<MetadataNativeIoTicket>>)->Result<()>{
  self.check_negative()?;if !self.inner.slots.borrow().is_empty(){self.held();return Err(Error::Conflict)}
  self.inner.slots.borrow_mut().insert(sequence,Slot{operation,ticket,_keepalive:self.inner.clone()});Ok(())
 }
 fn held(&self){self.inner.held.set(true);self.inner.deny();revoke(&self.inner.native);}
 async fn actual(&self,sequence:u64)->Result<JsValue>{
  let operation=self.inner.slots.borrow().get(&sequence).ok_or(Error::Conflict)?.operation.clone();
  let promise=drive(&operation).map_err(|_|unavailable())?;let future=wasm_bindgen_futures::JsFuture::from(promise);tokio::pin!(future);
  let actual=tokio::select!{result=&mut future=>result,_=self.cancelled()=>{revoke(&self.inner.native);future.await}};
  actual.map_err(|_|{self.held();unavailable()})
 }
 async fn profile_operation(&self,recheck:bool)->Result<JsValue>{
  self.check_negative()?;
  if self.inner.profiled.get()!=recheck{return Err(Error::Conflict)}
  if !self.inner.slots.borrow().is_empty(){return Err(Error::Conflict)}
  let sequence=self.reserve_sequence()?;let operation=profile(&self.inner.native,recheck).map_err(|_|unavailable())?;self.retain(sequence,operation.clone(),None)?;
  let actual=self.actual(sequence).await?;self.check_negative()?;
  let result=consume(&self.inner.native,&operation,&actual,if recheck{"recheck"}else{"profile"}).map_err(|_|{self.held();unavailable()})?;
  self.check_negative()?;self.inner.slots.borrow_mut().remove(&sequence);Ok(result)
 }
 pub async fn profile_read(&self)->Result<NativeMetadataProfileObservation>{
  let value:Array=self.profile_operation(false).await?.dyn_into().map_err(|_|unavailable())?;
  if value.length()!=2{return Err(unavailable())}let owner=value.get(0).as_string().ok_or_else(unavailable)?;let version=value.get(1).as_f64().ok_or_else(unavailable)?;
  if !uuid::Uuid::parse_str(&owner).is_ok_and(|id|id.to_string()==owner)||!version.is_finite()||version<1.0||version.fract()!=0.0||version>9_007_199_254_740_991.0{return Err(Error::Protocol)}
  self.inner.profiled.set(true);let observed=NativeMetadataProfileObservation{context:self.clone(),owner:Zeroizing::new(owner),version};observed.check_for(self)?;Ok(observed)
 }
 pub async fn recheck_profile_owner(&self)->Result<()>{self.profile_operation(true).await?;self.check_negative()}
 pub fn start(&self,ticket:Arc<MetadataNativeIoTicket>)->Result<NativeMetadataPending>{
  self.check_negative()?;if !self.inner.profiled.get()||!self.inner.slots.borrow().is_empty(){return Err(Error::Conflict)}
  ticket.check_for_context(self)?;let effect=Zeroizing::new(ticket.effect_json()?);let sequence=self.reserve_sequence()?;ticket.claim_dispatch()?;
  let operation=(if ticket.is_main_code_embed(){start_main_code_embed(&self.inner.native,ticket.operation_id(),&effect)}else if ticket.is_recovered_reply(){start_reply(&self.inner.native,ticket.operation_id(),&effect)}else{start(&self.inner.native,ticket.operation_id(),&effect)}).map_err(|_|{self.held();unavailable()})?;self.retain(sequence,operation,Some(ticket.clone()))?;
  Ok(NativeMetadataPending{context:self.clone(),ticket,sequence,finished:false})
 }
 /// Native IndexedDB ONLY. This never proves HTTP/Core/Worker settlement.
 pub async fn close_captured()->Result<()>{let promise=close_captured().map_err(|_|unavailable())?;wasm_bindgen_futures::JsFuture::from(promise).await.map_err(|_|unavailable())?;Ok(())}
}
#[doc(hidden)]
#[derive(Clone)]
pub struct NativeMetadataProfileObservation {context:NativeMetadataContext,owner:Zeroizing<String>,version:f64}
impl NativeMetadataProfileObservation {
 pub fn owner_id(&self)->&str{&self.owner}
 pub fn check_for(&self,context:&NativeMetadataContext)->Result<()>{if !self.context.same_original(context){return Err(Error::Forbidden)}context.check_negative()?;check_profile(&context.inner.native,&self.owner,self.version).map_err(|_|Error::Cancelled)}
}
#[doc(hidden)]
pub struct NativeMetadataPending {context:NativeMetadataContext,ticket:Arc<MetadataNativeIoTicket>,sequence:u64,finished:bool}
impl NativeMetadataPending {pub async fn drive(mut self)->Result<NativeMetadataDelivery>{let receipt=self.context.actual(self.sequence).await?;self.finished=true;Ok(NativeMetadataDelivery{context:self.context.clone(),ticket:self.ticket.clone(),sequence:self.sequence,receipt})}}
impl Drop for NativeMetadataPending {fn drop(&mut self){if !self.finished{self.context.held();}}}
#[doc(hidden)]
pub struct NativeMetadataDelivery {context:NativeMetadataContext,ticket:Arc<MetadataNativeIoTicket>,sequence:u64,receipt:JsValue}
impl NativeMetadataDelivery {
 pub fn consume_for(self,context:&NativeMetadataContext,ticket:&Arc<MetadataNativeIoTicket>)->Result<String>{
  if !self.context.same_original(context)||!Arc::ptr_eq(&self.ticket,ticket){return Err(Error::Forbidden)}ticket.check_for_context(context)?;
  let operation={let slots=context.inner.slots.borrow();let slot=slots.get(&self.sequence).ok_or(Error::Conflict)?;if !slot.ticket.as_ref().is_some_and(|actual|Arc::ptr_eq(actual,ticket)){return Err(Error::Forbidden)}slot.operation.clone()};
  let value=consume(&context.inner.native,&operation,&self.receipt,"ticket").map_err(|_|{context.held();unavailable()})?;
  let data=value.as_string().ok_or_else(unavailable)?;if data.len()>ticket.packet_limit(){context.held();return Err(Error::Protocol)}ticket.check_original_negative()?;context.check_negative()?;
  context.inner.slots.borrow_mut().remove(&self.sequence);Ok(data)
 }
}
