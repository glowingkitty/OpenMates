//! Explicit API-key library; no Cookie/SessionBridge or CLI state discovery.
use super::{BindingError, embed_versions::wipe};
use openmates_sdk::{ApiKey, ClientIdentity, ClientOptions, Error, OpenMates, SdkCredentials, SdkOptions};
use openmates_sdk::privacy::PrivacyOptions;
use serde::Deserialize;
use serde_json::Value;
use std::{collections::BTreeMap, sync::{Arc, Mutex, atomic::{AtomicBool, Ordering}}};
use tokio_util::sync::CancellationToken;
use zeroize::{Zeroize, Zeroizing};
type Result<T> = std::result::Result<T, BindingError>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Options { api_url:String, #[serde(deserialize_with="deserialize_api_key")] api_key:Zeroizing<String>, device_id:String, app_url:Option<String>, enhanced_privacy:bool, allow_private_operations:bool }
fn deserialize_api_key<'de,D:serde::Deserializer<'de>>(deserializer:D)->std::result::Result<Zeroizing<String>,D::Error> {
    // Guard the decoded field itself before a later field/struct error can drop
    // it. A whole-Options Drop cannot own a partially deserialized Options.
    String::deserialize(deserializer).map(Zeroizing::new)
}
struct State { sdk:Mutex<Option<Arc<OpenMates>>>,root:CancellationToken, closed:AtomicBool, requests:Mutex<BTreeMap<String, Arc<Call>>>, privacy:PrivacyOptions, gate:Arc<dyn Fn()->openmates_sdk::Result<()>+Send+Sync>,
#[cfg(test)] input_string_wipes:Option<Arc<Mutex<Vec<bool>>>>,
#[cfg(test)] input_value_wipes:Option<Arc<Mutex<Vec<bool>>>>,
}
struct Call { id:String, cancel:CancellationToken }
impl State {
    fn check(&self, call:&Call)->Result<()> {
        self.privacy.verify().map_err(BindingError::from)?;
        (self.gate)().map_err(BindingError::from)?;
        // No callback after these original negative authorities.
        if self.closed.load(Ordering::Acquire) || self.root.is_cancelled() || call.cancel.is_cancelled() { return Err(Error::Cancelled.into()); }
        Ok(())
    }
    fn driver(&self,call:&Call)->Result<Arc<OpenMates>> {
        self.check(call)?;
        let sdk=self.sdk.lock().map_err(|_|BindingError::from(Error::Conflict))?.as_ref().cloned().ok_or_else(||BindingError::from(Error::Cancelled))?;
        self.check(call)?;
        Ok(sdk)
    }
    fn retire(&self, call:&Arc<Call>) {
        call.cancel.cancel();
        if let Ok(mut requests)=self.requests.try_lock() {
            if requests.get(&call.id).is_some_and(|found|Arc::ptr_eq(found,call)) { requests.remove(&call.id); }
        }
    }
}
/// The original immutable explicit credential is retained; cancel never imports a new identity.
pub struct ApiKeyBridge { state:Arc<State> }
impl ApiKeyBridge {
    pub fn new(options_json:&str)->Result<Self> { Self::with_identity(options_json,ClientIdentity::Rust) }
    pub(crate) fn with_identity(options_json:&str,identity:ClientIdentity)->Result<Self> {
        let encoded=Zeroizing::new(options_json.to_owned());
        if encoded.len()>16384 {return Err(Error::Invalid("Invalid API-key options.").into());}
        let options:Options=serde_json::from_str(&encoded).map_err(|_|BindingError::from(Error::Invalid("Invalid API-key options.")))?;
        let privacy=PrivacyOptions{enhanced:options.enhanced_privacy};
        privacy.verify().map_err(BindingError::from)?;
        let allow=options.allow_private_operations;
        let gate:Arc<dyn Fn()->openmates_sdk::Result<()>+Send+Sync>=Arc::new(move||if allow {Ok(())} else {Err(Error::Forbidden)});
        let mut sdk=OpenMates::new(SdkOptions{api_url:options.api_url.clone(),credentials:SdkCredentials::ApiKey(ApiKey::new(&options.api_key).map_err(BindingError::from)?),device_id:options.device_id.clone(),client_options:ClientOptions{identity,interactive:false,app_url:options.app_url.clone(),privacy:privacy.clone(),private_operation_gate:Some(gate.clone())}}).map_err(BindingError::from)?;
        let root=CancellationToken::new();
        sdk.set_operation_cancel(root.clone());
        Ok(Self{state:Arc::new(State{sdk:Mutex::new(Some(Arc::new(sdk))),root,closed:AtomicBool::new(false),requests:Mutex::new(BTreeMap::new()),privacy,gate,
#[cfg(test)] input_string_wipes:None,
#[cfg(test)] input_value_wipes:None,
})})
    }
    /// Synchronous original admission, before foreign scheduler/IO boundaries.
    pub fn request(&self)->Result<ApiKeyRequest> {
        let call=Arc::new(Call{id:uuid::Uuid::new_v4().to_string(),cancel:CancellationToken::new()});
        self.state.check(&call)?;
        let mut requests=self.state.requests.lock().map_err(|_|BindingError::from(Error::Conflict))?;
        self.state.check(&call)?;
        requests.retain(|_,call|!call.cancel.is_cancelled());
        requests.insert(call.id.clone(),call.clone());
        Ok(ApiKeyRequest{state:self.state.clone(),call,started:AtomicBool::new(false)})
    }
    /// Cancel current registered requests; future B still uses the same credential.
    pub fn cancel(&self)->Result<()> {
        let requests=self.state.requests.lock().map_err(|_|BindingError::from(Error::Conflict))?;
        for call in requests.values(){call.cancel.cancel();} Ok(())
    }
    pub fn close(&self)->Result<()> {
        self.state.closed.store(true,Ordering::Release);
        self.state.root.cancel();
        // Drop the bridge's owner reference now. Only actual in-flight drivers
        // retain the SAME Core until drain; opaque outputs never hold a Core Arc.
        if let Ok(mut sdk)=self.state.sdk.lock(){sdk.take();}
        self.cancel()
    }
}
impl Drop for ApiKeyBridge {fn drop(&mut self){let _=self.close();}}
/// Non-Clone one-use request; stale A cleanup only retires its original token.
pub struct ApiKeyRequest {state:Arc<State>,call:Arc<Call>,started:AtomicBool}
impl ApiKeyRequest {
    fn start(&self)->Result<()> {
        self.state.check(&self.call)?;
        if self.started.swap(true,Ordering::AcqRel){return Err(Error::Cancelled.into());} Ok(())
    }
    pub fn cancel(&self){self.state.retire(&self.call);}
    pub async fn account_info_prepare(&self)->Result<ApiKeyOutput>{
        self.start()?;
        let sdk=self.state.driver(&self.call)?;
        let result=sdk.account_info().await;
        drop(sdk);
        self.seal(result)
    }
    pub fn run_skill_prepare(&self,app:String,skill:String,input_json:String)->impl std::future::Future<Output=Result<ApiKeyOutput>>+Send+'_ {
        // Synchronous factory: even an UNPOLLED/dropped future owns a wiper.
        let encoded=Zeroizing::new(input_json);
        self.run_skill_prepare_guarded(app,skill,encoded)
    }
    pub(crate) fn run_skill_prepare_guarded(&self,app:String,skill:String,encoded:Zeroizing<String>)->impl std::future::Future<Output=Result<ApiKeyOutput>>+Send+'_ {
        let encoded=InputScratch{encoded,
            #[cfg(test)] probe:self.state.input_string_wipes.clone(),
        };
        async move {
            // Preserve original cancellation-before-validation priority.
            self.start()?;
            if encoded.encoded.len()>1024*1024{return Err(Error::Invalid("Invalid App skill input.").into());}
            let input:Value=serde_json::from_str(&encoded.encoded).map_err(|_|BindingError::from(Error::Invalid("Invalid App skill input.")))?;
            let input=WipingValue::input(input,&self.state);
            drop(encoded);
            // Parsed private input remains adapter-owned/wiping if this original
            // driver check refuses. Transfer it only into the actual Core call.
            let sdk=self.state.driver(&self.call)?;
            let result=sdk.run_app_skill(&app,&skill,input.into_inner(),self.call.cancel.clone()).await;
            drop(sdk);
            self.seal(result)
        }
    }
    pub fn list_project_sources_raw_prepare(&self, project: String, filters_json: String) -> impl std::future::Future<Output=Result<ApiKeyOutput>> + Send + '_ {
        // Synchronous factory owns encoded input even when never polled.
        self.list_project_sources_raw_prepare_guarded(project, Zeroizing::new(filters_json))
    }
    pub(crate) fn list_project_sources_raw_prepare_guarded(&self, project: String, encoded: Zeroizing<String>) -> impl std::future::Future<Output=Result<ApiKeyOutput>> + Send + '_ {
        async move {
            self.start()?;
            if encoded.len() > 65536 { return Err(Error::Invalid("Invalid Project filters.").into()); }
            let filters: openmates_sdk::work::ProjectFilters = serde_json::from_str(&encoded)
                .map_err(|_| BindingError::from(Error::Invalid("Invalid Project filters.")))?;
            drop(encoded);
            let sdk = self.state.driver(&self.call)?;
            let result = sdk.list_project_sources_raw(&project, filters).await.map(Value::Array);
            drop(sdk);
            self.seal(result)
        }
    }
    fn seal(&self,result:openmates_sdk::Result<Value>)->Result<ApiKeyOutput>{
        // Own/wipe successful data immediately, and apply original negatives
        // to both data and fixed safe errors after the actual driver await.
        let value=result.map(WipingValue::new);
        self.state.check(&self.call)?;
        let mut value=value.map_err(BindingError::from)?;
        let output=Zeroizing::new(serde_json::to_string(&value.value).map_err(|_|BindingError::from(Error::Protocol))?);
        wipe(&mut value.value);
        self.state.check(&self.call)?;
        Ok(ApiKeyOutput{state:self.state.clone(),call:self.call.clone(),output})
    }
}
impl Drop for ApiKeyRequest {fn drop(&mut self){self.cancel();}}
struct InputScratch {encoded:Zeroizing<String>,#[cfg(test)] probe:Option<Arc<Mutex<Vec<bool>>>>}
impl Drop for InputScratch {fn drop(&mut self){
    self.encoded.zeroize();
    #[cfg(test)] if let Some(probe)=&self.probe{probe.lock().expect("scratch probe").push(self.encoded.is_empty());}
}}
struct WipingValue {value:Value,#[cfg(test)] probe:Option<Arc<Mutex<Vec<bool>>>>}
impl WipingValue {
    fn new(value:Value)->Self{Self{value,#[cfg(test)] probe:None}}
    fn input(value:Value,_state:&State)->Self{Self{value,#[cfg(test)] probe:_state.input_value_wipes.clone()}}
    fn into_inner(mut self)->Value{
        #[cfg(test)] {self.probe=None;}
        std::mem::take(&mut self.value)
    }
}
impl Drop for WipingValue {fn drop(&mut self){
    // Erase the actual owned map's keys and nested allocations before release,
    // retaining its empty-object postcondition for the original wipe observer.
    match &mut self.value {
        Value::Object(object) => {
            for (mut key, mut value) in std::mem::take(object) {
                key.zeroize();
                wipe(&mut value);
            }
        }
        value => wipe(value),
    }
    #[cfg(test)] if let Some(probe)=&self.probe{probe.lock().expect("value probe").push(self.value.as_object().is_some_and(|v|v.is_empty()));}
}}
/// No plaintext getter, Clone, Debug or serialization; actual allocator must run here.
pub struct ApiKeyOutput {state:Arc<State>,call:Arc<Call>,output:Zeroizing<String>}
impl ApiKeyOutput {
    pub fn encode_with<T>(mut self,encode:impl FnOnce(&str)->Result<T>)->Result<T>{self.encode_checked(encode)}
    fn encode_checked<T>(&mut self,encode:impl FnOnce(&str)->Result<T>)->Result<T>{
        let result=(||{self.state.check(&self.call)?;let value=encode(&self.output)?;self.state.check(&self.call)?;Ok(value)})();
        self.output.zeroize();result
    }
}
impl Drop for ApiKeyOutput {fn drop(&mut self){self.state.retire(&self.call);}}
#[cfg(test)]
#[path="api_key_tests.rs"]
mod tests;
