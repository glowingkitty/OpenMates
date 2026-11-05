//! Inactive worker-only cache bridges. No admission/key export/default switch.
use super::*;
#[path="browser_phased_monitor.rs"]
mod phased_monitor;
#[derive(Default)]
pub(super) struct BrowserCacheSession {
 owner:Option<(String,u64)>,
 monitor:Option<std::sync::Arc<openmates_sdk::client::ChatMonitor>>,
 monitor_id:Option<String>,
 errors:Option<tokio::sync::mpsc::Receiver<openmates_sdk::Error>>,
 failures:std::collections::BTreeMap<String,Option<openmates_sdk::client::BrowserCandidateFailures>>,
}
impl BrowserCacheSession {
 fn stop(&mut self){if let Some(monitor)=self.monitor.take(){monitor.close();}self.errors=None;self.monitor_id=None;}
 pub(super) fn clear(&mut self){self.stop();self.failures.clear();self.owner=None;}
}
/// Keyless actual-socket wait resource. No mutable Client or auth lock is held
/// while changed() waits. close/free affects only this original socket.
#[wasm_bindgen]
pub struct BrowserCacheMonitor {
 id:String,
 monitor:std::sync::Arc<openmates_sdk::client::ChatMonitor>,
 polling:std::sync::atomic::AtomicBool,
}
impl Drop for BrowserCacheMonitor {fn drop(&mut self){self.monitor.close();}}
struct CacheMonitorPolling<'a>(&'a std::sync::atomic::AtomicBool);
impl Drop for CacheMonitorPolling<'_>{fn drop(&mut self){self.0.store(false,std::sync::atomic::Ordering::Release);}}
#[wasm_bindgen]
impl BrowserCacheMonitor {
 #[wasm_bindgen(getter)]
 pub fn id(&self)->String{self.id.clone()}
 pub async fn changed(&self)->Result<bool,JsValue>{
  worker_only()?;
  if self.polling.swap(true,std::sync::atomic::Ordering::AcqRel){return Err(JsValue::from_str("unavailable"))}
  let _poll=CacheMonitorPolling(&self.polling);
  self.monitor.changed_or_idle().await.map_err(failure)
 }
 pub fn close(&self){self.monitor.close();}
}
#[wasm_bindgen]
pub struct BrowserIncomingPublication {id:String,publication:Option<openmates_sdk::client::BrowserIncomingCachePublication>,handle:String,generation:f64,owner:String}
#[wasm_bindgen]
impl BrowserIncomingPublication {
  #[wasm_bindgen(getter)]
  pub fn id(&self)->String{self.id.clone()}
 pub fn take(&mut self,client:&BrowserCoreClient)->Result<String,JsValue>{
  current(client,&self.handle,self.generation,&self.owner)?;
  let publication=self.publication.take().ok_or_else(||JsValue::from_str("session_expired"))?;
  let mut encoded=client.client.browser_incoming_cache_publication_json(publication,true).map_err(failure)?;
  current(client,&self.handle,self.generation,&self.owner)?;Ok(std::mem::take(&mut *encoded))
 }
}
#[wasm_bindgen]
pub struct BrowserCachedReadPublication {id:String,publication:Option<openmates_sdk::client::BrowserRetainedCachePublication>,handle:String,generation:f64,owner:String}
#[wasm_bindgen]
impl BrowserCachedReadPublication {
  #[wasm_bindgen(getter)]
  pub fn id(&self)->String{self.id.clone()}
 pub fn take(&mut self,client:&BrowserCoreClient)->Result<String,JsValue>{
  current(client,&self.handle,self.generation,&self.owner)?;
  let publication=self.publication.take().ok_or_else(||JsValue::from_str("session_expired"))?;
  let mut encoded=client.client.browser_retained_cache_publication_json(publication,true).map_err(failure)?;
  current(client,&self.handle,self.generation,&self.owner)?;Ok(std::mem::take(&mut *encoded))
 }
}

// Compare ACTUAL Rust authority, never caller labels, before wiping a prior owner.
fn cache_current(client:&mut BrowserCoreClient,handle:&str,generation:f64,owner:&str)->Result<(),JsValue>{
 let Some(status)=client.client.browser_session_status()else{client.cache.clear();return Err(JsValue::from_str("session_expired"))};
 let actual=(status.principal().to_owned(),status.generation());
 if client.cache.owner.as_ref()!=Some(&actual){client.cache.clear();client.cache.owner=Some(actual);}
 client.cache.failures.retain(|_,state|state.as_ref().is_none_or(|value|value.is_current(&client.client)));
 current(client,handle,generation,owner)
}
fn failure(error:openmates_sdk::Error)->JsValue {JsValue::from_str(match error {
    openmates_sdk::Error::Cancelled|openmates_sdk::Error::Expired|openmates_sdk::Error::Authentication|openmates_sdk::Error::Forbidden=>"session_expired",
    _=>"chat_unavailable",
})}
fn current(client:&BrowserCoreClient,handle:&str,generation:f64,owner:&str)->Result<(),JsValue> {
    let status=client.status(handle,generation)?;
    if status.principal()!=owner{return Err(JsValue::from_str("session_expired"));}Ok(())
}
pub(super) fn owned_read_monitor(client:&mut BrowserCoreClient,handle:&str,generation:f64,owner:&str,monitor_id:&str)->Result<std::sync::Arc<openmates_sdk::client::ChatMonitor>,JsValue>{
    cache_current(client,handle,generation,owner)?;
    if client.cache.monitor_id.as_deref()!=Some(monitor_id){return Err(JsValue::from_str("unavailable"))}
    client.cache.monitor.as_ref().cloned().ok_or_else(||JsValue::from_str("unavailable"))
}
fn worker_guard()->openmates_sdk::Result<()> {worker_only().map_err(|_|openmates_sdk::Error::Cancelled)}
#[wasm_bindgen]
impl BrowserCoreClient {
    /// Actual admitted Client/key fences are enforced inside the shared core
    /// across every IO await. JS supplies only owned existing-store effects.
    pub async fn restore_cached_metadata(&mut self,handle:&str,generation:f64,owner:&str,
        ids_json:&str,scope_json:&str,host_effect:js_sys::Function)->Result<String,JsValue> {
        current(self,handle,generation,owner)?;
        if ids_json.len()>2048||scope_json.len()>256{return Err(JsValue::from_str("invalid_request"));}
        let ids:Vec<String>=serde_json::from_str(ids_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let scope=serde_json::from_str(scope_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let result=self.client.browser_restore_cached_metadata_json(owner,&ids,scope,true,
            |plan: String|host_local_packet(plan,&host_effect,&worker_guard)).await;
        current(self,handle,generation,owner)?;
        let mut encoded=result.map_err(failure)?;Ok(std::mem::take(&mut *encoded))
    }
    pub async fn read_cached_chat_items(&self,handle:&str,generation:f64,owner:&str,ids_json:&str)->Result<String,JsValue> {
        current(self,handle,generation,owner)?;
        if ids_json.len()>2048{return Err(JsValue::from_str("invalid_request"));}
        let ids:Vec<String>=serde_json::from_str(ids_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let result=self.client.browser_cached_chat_items_json(owner,&ids,true).await;
        current(self,handle,generation,owner)?;
        let mut encoded=result.map_err(failure)?;Ok(std::mem::take(&mut *encoded))
    }
    /// Distinct actual-retained-row view, never canonical saved-read/export.
    pub async fn read_retained_saved_chat(&mut self,handle:&str,generation:f64,owner:&str,id:&str,
        selector_json:&str,scope_json:&str,host_effect:js_sys::Function)->Result<String,JsValue> {
        current(self,handle,generation,owner)?;
        if selector_json.len()>2048||scope_json.len()>256{return Err(JsValue::from_str("invalid_request"));}
        let options:MessageWindowOptions=serde_json::from_str(selector_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let scope=serde_json::from_str(scope_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let result=self.client.browser_retained_saved_chat_with_io_json(owner,id,options,scope,true,
            |plan: String|host_local_packet(plan,&host_effect,&worker_guard)).await;
        current(self,handle,generation,owner)?;
        let mut encoded=result.map_err(failure)?;Ok(std::mem::take(&mut *encoded))
    }
    pub async fn start_cache_monitor(&mut self,handle:&str,generation:f64,owner:&str)->Result<BrowserCacheMonitor,JsValue>{
        cache_current(self,handle,generation,owner)?;if self.status(handle,generation)?.local_read_only(){return Err(JsValue::from_str("unavailable"));}
        self.cache.stop();let cancel=tokio_util::sync::CancellationToken::new();let(errors,receiver)=tokio::sync::mpsc::channel(1);
        let monitor=self.client.start_chat_monitor(cancel,errors).await.map_err(failure)?;
        self.client.validate_chat_monitor(&monitor).await.map_err(failure)?;current(self,handle,generation,owner)?;
        let monitor=std::sync::Arc::new(monitor);
        let id=uuid::Uuid::new_v4().to_string();
        self.cache.monitor=Some(monitor.clone());self.cache.monitor_id=Some(id.clone());self.cache.errors=Some(receiver);
        Ok(BrowserCacheMonitor{id,monitor,polling:std::sync::atomic::AtomicBool::new(false)})
    }
    pub fn stop_cache_monitor(&mut self,handle:&str,generation:f64,owner:&str,monitor_id:&str)->Result<(),JsValue>{cache_current(self,handle,generation,owner)?;if self.cache.monitor_id.as_deref()!=Some(monitor_id){return Err(JsValue::from_str("unavailable"))}self.cache.stop();Ok(())}
    pub async fn prepare_cache_monitor_update(&mut self,handle:&str,generation:f64,owner:&str,monitor_id:&str,id:&str,selector_json:&str,scope_json:&str,now_seconds:f64,host_effect:js_sys::Function)->Result<BrowserIncomingPublication,JsValue>{
        cache_current(self,handle,generation,owner)?;
        if selector_json.len()>2048||scope_json.len()>256||!now_seconds.is_finite()||now_seconds<0.0||now_seconds.fract()!=0.0||now_seconds>9_007_199_254_740_991.0{return Err(JsValue::from_str("invalid_request"));}
        let options=serde_json::from_str(selector_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let scope=serde_json::from_str(scope_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        if self.cache.monitor_id.as_deref()!=Some(monitor_id){return Err(JsValue::from_str("unavailable"))}
        let monitor=self.cache.monitor.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?.clone();
        let publication=self.client.prepare_browser_incoming_cache_update(monitor,&mut self.cache.failures,
            owner,id,options,scope,now_seconds as u64,true,|plan:String|host_local_packet(plan,&host_effect,&worker_guard)).await.map_err(failure)?;
        current(self,handle,generation,owner)?;
        Ok(BrowserIncomingPublication{id:uuid::Uuid::new_v4().to_string(),publication:Some(publication),handle:handle.into(),generation,owner:owner.into()})
    }
    pub async fn prepare_cold_retained_saved_chat(&mut self,handle:&str,generation:f64,owner:&str,id:&str,selector_json:&str,scope_json:&str,now_seconds:f64,host_effect:js_sys::Function)->Result<BrowserCachedReadPublication,JsValue>{
        cache_current(self,handle,generation,owner)?;if selector_json.len()>2048||scope_json.len()>256||!now_seconds.is_finite()||now_seconds<0.0||now_seconds.fract()!=0.0||now_seconds>9_007_199_254_740_991.0{return Err(JsValue::from_str("invalid_request"));}
        let options=serde_json::from_str(selector_json).map_err(|_|JsValue::from_str("invalid_request"))?;let scope=serde_json::from_str(scope_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let publication=self.client.prepare_browser_cold_retained_saved_chat_with_io(owner,id,options,scope,now_seconds as u64,true,|plan:String|host_local_packet(plan,&host_effect,&worker_guard)).await.map_err(failure)?;
        current(self,handle,generation,owner)?;Ok(BrowserCachedReadPublication{id:uuid::Uuid::new_v4().to_string(),publication:Some(publication),handle:handle.into(),generation,owner:owner.into()})
    }
    pub async fn prepare_monitored_retained_saved_chat(&mut self,handle:&str,generation:f64,owner:&str,id:&str,selector_json:&str,scope_json:&str,now_seconds:f64,host_effect:js_sys::Function)->Result<BrowserCachedReadPublication,JsValue>{
        cache_current(self,handle,generation,owner)?;if selector_json.len()>2048||scope_json.len()>256||!now_seconds.is_finite()||now_seconds<0.0||now_seconds.fract()!=0.0||now_seconds>9_007_199_254_740_991.0{return Err(JsValue::from_str("invalid_request"));}
        let options=serde_json::from_str(selector_json).map_err(|_|JsValue::from_str("invalid_request"))?;let scope=serde_json::from_str(scope_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let monitor=self.cache.monitor.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
        let state=self.cache.failures.entry(id.into()).or_insert(None);
        let result=self.client.prepare_browser_monitored_retained_saved_chat_with_io(monitor,state,owner,id,options,scope,now_seconds as u64,true,|plan:String|host_local_packet(plan,&host_effect,&worker_guard)).await;
        current(self,handle,generation,owner)?;let publication=result.map_err(failure)?;
        Ok(BrowserCachedReadPublication{id:uuid::Uuid::new_v4().to_string(),publication:Some(publication),handle:handle.into(),generation,owner:owner.into()})
    }

}
