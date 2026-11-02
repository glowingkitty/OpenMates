//! Fresh-password ordinary retention policy and one-use opaque resource handoff.
//! Only the actual browser password factory context may prepare this operation.
//! Worker-local import sees canonical unwrap bytes internally, never a raw getter.
//! Existing restore is nonmutating; ordinary completion is not a durability ACK.
//! Original owner/session/key/denial/generation/cancel scope spans every await.
//! Retire the fresh Worker after handoff; then ordinary IO precedes new admission.
use super::*;
use serde::Serialize;
const MAX_SAFE:u64=9_007_199_254_740_991;
#[derive(Clone,Copy,Debug,PartialEq,Eq,Serialize)]
#[serde(rename_all="snake_case")]
enum BrowserOrdinaryRetentionAction{SaveMemory,SavePersisted}
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
struct Effect{version:u8,operation_id:String,owner:String,generation:u64,lifecycle_generation:u64,action:BrowserOrdinaryRetentionAction,credential_acknowledged:bool,cross_database_association_proven:bool}
pub struct BrowserOrdinaryKeyRetention{
 scope:sync_capability::AsyncCryptoScope,effect:Effect,
 #[cfg(target_arch="wasm32")] key:Option<wasm_bindgen::JsValue>,
}
fn begin(client:&Client,stay:bool,lifecycle_generation:u64)->Result<BrowserOrdinaryKeyRetention>{
 let authority=client.browser_authority.as_ref().ok_or(Error::Forbidden)?;
 if !client.browser_password_transport||!client.browser_transport||client.browser_local_read_only||client.session.is_some()
  ||client.browser_credentials.is_none()||client.browser_password_stay_logged_in!=Some(stay)||client.user["id"].as_str()!=Some(authority.principal.as_str())
  ||client.generation==0||client.generation>MAX_SAFE||lifecycle_generation==0||lifecycle_generation>MAX_SAFE{return Err(Error::Forbidden);}
 let scope=sync_capability::AsyncCryptoScope::begin(client)?;
 Ok(BrowserOrdinaryKeyRetention{scope,effect:Effect{version:1,operation_id:uuid::Uuid::new_v4().to_string(),owner:authority.principal.clone(),generation:client.generation,
  lifecycle_generation,action:if stay{BrowserOrdinaryRetentionAction::SavePersisted}else{BrowserOrdinaryRetentionAction::SaveMemory},credential_acknowledged:false,cross_database_association_proven:false},
  #[cfg(target_arch="wasm32")]key:None})
}
impl BrowserOrdinaryKeyRetention{
 fn current(&self,client:&Client)->Result<()>{self.scope.check(client)?;if client.browser_password_stay_logged_in!=Some(self.effect.action==BrowserOrdinaryRetentionAction::SavePersisted){return Err(Error::Cancelled);}Ok(())}
 pub fn effect_json(&self,client:&Client)->Result<String>{self.current(client)?;Ok(serde_json::to_string(&self.effect)?)}
 #[cfg(target_arch="wasm32")]
 pub fn take_key(mut self,client:&Client)->Result<wasm_bindgen::JsValue>{self.current(client)?;self.key.take().ok_or(Error::Cancelled)}
}
#[cfg(target_arch="wasm32")]
struct ImportBytes(js_sys::Uint8Array);
#[cfg(target_arch="wasm32")]
impl Drop for ImportBytes{fn drop(&mut self){self.0.fill(0,0,self.0.length());}}
#[cfg(target_arch="wasm32")]
impl Client{
 /// Fresh canonical unwrap -> actual Worker CryptoKey, preserving deployed fresh
 /// extractability. No existing key is exported or reimported by this operation.
 pub async fn prepare_browser_ordinary_key_retention(&self,stay:bool,lifecycle_generation:u64)->Result<BrowserOrdinaryKeyRetention>{
  use wasm_bindgen::{JsCast,JsValue};use js_sys::{Reflect,Function,Promise,Array,Object};
  let mut operation=begin(self,stay,lifecycle_generation)?;
  js_sys::global().dyn_into::<web_sys::DedicatedWorkerGlobalScope>().map_err(|_|Error::Forbidden)?;
  let crypto=Reflect::get(&js_sys::global(),&JsValue::from_str("crypto")).map_err(|_|Error::Crypto)?;
  let subtle=Reflect::get(&crypto,&JsValue::from_str("subtle")).map_err(|_|Error::Crypto)?;
  let import=Reflect::get(&subtle,&JsValue::from_str("importKey")).map_err(|_|Error::Crypto)?.dyn_into::<Function>().map_err(|_|Error::Crypto)?;
  let master=self.master_capability()?;operation.current(self)?;
  let bytes=ImportBytes(js_sys::Uint8Array::from(&master.native_key()?[..]));
  let algorithm=Object::new();Reflect::set(&algorithm,&JsValue::from_str("name"),&JsValue::from_str("AES-GCM")).map_err(|_|Error::Crypto)?;
  let usages=Array::new();usages.push(&JsValue::from_str("encrypt"));usages.push(&JsValue::from_str("decrypt"));
  let args=Array::new();args.push(&JsValue::from_str("raw"));args.push(&bytes.0);args.push(&algorithm);args.push(&JsValue::TRUE);args.push(&usages);
  let invoked=import.apply(&subtle,&args).map_err(|_|Error::Crypto)?.dyn_into::<Promise>().map_err(|_|Error::Crypto)?;
  let key=wasm_bindgen_futures::JsFuture::from(invoked).await;drop(bytes);
  operation.current(self)?;let key=key.map_err(|_|Error::Crypto)?;
  // The binding validates the actual CryptoKey brand/usages before handoff.
  operation.key=Some(key);operation.current(self)?;Ok(operation)
 }
}
#[cfg(test)]
#[path="browser_ordinary_retention_tests.rs"]
mod tests;
