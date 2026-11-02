//! Thin typed original monitor acquisition. No Client/auth lock across next().
use super::*;
use openmates_sdk::client::{PreparedOwnedChatMonitor,OwnedChatMonitorStartStep,OwnedChatMonitorStartControl,OwnedChatMonitorStartTerminal};
#[derive(Clone)]
struct Binding {handle:String,generation:f64,owner:String}
impl Binding {
    fn current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{worker_only()?;current(client,&self.handle,self.generation,&self.owner)}
    // Matched auth headers/body must reach the actual Core original-client
    // checks even after local cancellation/TTL. This is bookkeeping only.
    fn target(&self,client:&BrowserCoreClient)->Result<(),JsValue>{worker_only()?;if client.handle!=self.handle{return Err(JsValue::from_str("session_expired"))}Ok(())}
}
#[wasm_bindgen]
pub struct BrowserPreparedCacheMonitor {driver:Option<PreparedOwnedChatMonitor>,control:OwnedChatMonitorStartControl,binding:Binding,errors:Option<tokio::sync::mpsc::Receiver<openmates_sdk::Error>>}
#[wasm_bindgen]
impl BrowserPreparedCacheMonitor {
    pub fn control(&self)->Result<BrowserCacheMonitorStartControl,JsValue>{worker_only()?;Ok(BrowserCacheMonitorStartControl{control:self.driver.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?.control(),binding:self.binding.clone()})}
    pub fn terminal(&self)->Option<BrowserCacheMonitorStartTerminal>{self.control.terminal().map(|terminal|BrowserCacheMonitorStartTerminal{terminal})}
    pub async fn next(&mut self)->Result<BrowserCacheMonitorStartStep,JsValue>{
        worker_only()?;let step=self.driver.as_mut().ok_or_else(||JsValue::from_str("unavailable"))?.next().await.map_err(failure)?;
        let errors=if matches!(&step,OwnedChatMonitorStartStep::Ready(_)){self.driver.take();self.errors.take()}else{None};
        Ok(BrowserCacheMonitorStartStep{step:Some(step),binding:self.binding.clone(),errors})
    }
}
#[wasm_bindgen]
pub struct BrowserCacheMonitorStartControl {control:OwnedChatMonitorStartControl,binding:Binding}
#[wasm_bindgen]
impl BrowserCacheMonitorStartControl {
    pub fn cancel(&self){self.control.cancel()}
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.current(client)?;self.control.ensure_current(&client.client).map_err(failure)}
    pub async fn retire(&self)->Result<(),JsValue>{worker_only()?;self.control.retire().await.map_err(failure)}
    pub fn terminal(&self)->Option<BrowserCacheMonitorStartTerminal>{self.control.terminal().map(|terminal|BrowserCacheMonitorStartTerminal{terminal})}
}
#[wasm_bindgen]
pub struct BrowserCacheMonitorStartTerminal {terminal:OwnedChatMonitorStartTerminal}
#[wasm_bindgen]
impl BrowserCacheMonitorStartTerminal {pub fn acquisition_io_quiescent(&self)->bool{self.terminal.acquisition_io_quiescent()}}
#[wasm_bindgen]
pub struct BrowserCacheMonitorStartStep {step:Option<OwnedChatMonitorStartStep>,binding:Binding,errors:Option<tokio::sync::mpsc::Receiver<openmates_sdk::Error>>}
#[wasm_bindgen]
impl BrowserCacheMonitorStartStep {
    #[wasm_bindgen(getter)]pub fn kind(&self)->String{match self.step.as_ref(){Some(OwnedChatMonitorStartStep::Apply(_))=>"apply",Some(OwnedChatMonitorStartStep::Ready(_))=>"ready",None=>"consumed"}.into()}
    pub fn apply(&mut self,client:&mut BrowserCoreClient)->Result<(),JsValue>{
        self.binding.target(client)?;
        if !matches!(self.step.as_ref(),Some(OwnedChatMonitorStartStep::Apply(_))){return Err(JsValue::from_str("unavailable"))}
        let Some(OwnedChatMonitorStartStep::Apply(phase))=self.step.take()else{return Err(JsValue::from_str("unavailable"))};
        phase.apply(&mut client.client).map_err(failure)
    }
    pub fn retain(&mut self,client:&mut BrowserCoreClient)->Result<BrowserCacheMonitor,JsValue>{
        self.binding.current(client)?;
        if self.errors.is_none(){return Err(JsValue::from_str("unavailable"))}
        let Some(OwnedChatMonitorStartStep::Ready(ready))=self.step.as_mut()else{return Err(JsValue::from_str("unavailable"))};
        let monitor=ready.retain(&client.client).map_err(failure)?;
        let id=uuid::Uuid::new_v4().to_string();client.cache.monitor=Some(monitor.clone());client.cache.monitor_id=Some(id.clone());client.cache.errors=self.errors.take();
        self.step.take();Ok(BrowserCacheMonitor{id,monitor,polling:std::sync::atomic::AtomicBool::new(false)})
    }
}
#[wasm_bindgen]
impl BrowserCoreClient {
    pub fn prepare_cache_monitor(&mut self,handle:&str,generation:f64,owner:&str)->Result<BrowserPreparedCacheMonitor,JsValue>{
        worker_only()?;cache_current(self,handle,generation,owner)?;
        if self.status(handle,generation)?.local_read_only(){return Err(JsValue::from_str("unavailable"))}
        self.cache.stop();let(errors,receiver)=tokio::sync::mpsc::channel(1);
        let driver=self.client.prepare_owned_chat_monitor(tokio_util::sync::CancellationToken::new(),errors).map_err(failure)?;
        let control=driver.control();Ok(BrowserPreparedCacheMonitor{driver:Some(driver),control,binding:Binding{handle:handle.into(),generation,owner:owner.into()},errors:Some(receiver)})
    }
}
