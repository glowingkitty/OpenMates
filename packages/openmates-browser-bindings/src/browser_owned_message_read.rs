//! Thin owning-Worker bridge. Native step resources, not labels/JSON/status,
//! retain original Client/key/monitor authority through each short apply.
use super::*;
use openmates_sdk::client::{OwnedBrowserReadDriver,OwnedBrowserReadStep,OwnedBrowserMetadataContinuation,OwnedBrowserReadControl,OwnedBrowserReadTerminalObserver,OwnedBrowserReadTerminal};
use tokio_util::sync::CancellationToken;
use std::sync::Arc;

#[derive(Clone)]
struct Binding {handle:String,generation:f64,owner:String,
    #[cfg(feature="browser-metadata-prototype")]
    profile_store:Option<openmates_sdk::client::BoundInitialSyncStore>,
}
impl Binding {
    fn check(&self,client:&BrowserCoreClient)->Result<(),JsValue>{
        worker_only()?;let status=client.status(&self.handle,self.generation)?;
        if status.principal()!=self.owner{return Err(JsValue::from_str("session_expired"))}
        #[cfg(feature="browser-metadata-prototype")]
        if let Some(store)=&self.profile_store{store.ensure_profile_cache_current(&client.client).map_err(failure)?;}
        Ok(())
    }
}
fn failure(error:openmates_sdk::Error)->JsValue {JsValue::from_str(match error {
    openmates_sdk::Error::Cancelled|openmates_sdk::Error::Expired|openmates_sdk::Error::Authentication|openmates_sdk::Error::Forbidden=>"session_expired",
    _=>"chat_unavailable",
})}
fn worker_guard()->openmates_sdk::Result<()> {worker_only().map_err(|_|openmates_sdk::Error::Cancelled)}
#[wasm_bindgen]
pub struct BrowserOwnedMessageReadControl {control:OwnedBrowserReadControl,binding:Binding}
#[wasm_bindgen]
impl BrowserOwnedMessageReadControl {
    pub fn cancel(&self){self.control.cancel();}
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{
        self.binding.check(client)?;self.control.ensure_current(&client.client).map_err(failure)
    }
}

#[wasm_bindgen]
pub struct BrowserOwnedMessageReadHandle {driver:Option<OwnedBrowserReadDriver>,binding:Binding,request:CancellationToken,terminal:OwnedBrowserReadTerminalObserver}
#[wasm_bindgen]
impl BrowserOwnedMessageReadHandle {
    /// Actual returned Core failure + sealed absence, never an error-label test.
    pub fn take_profile_cache_absence(&mut self,client:&BrowserCoreClient)->Result<BrowserProfileCacheAbsenceHandle,JsValue>{
        self.binding.check(client)?;
        let inner=self.driver.as_mut().ok_or_else(||JsValue::from_str("unavailable"))?.take_profile_cache_absence(&client.client).map_err(failure)?;
        Ok(BrowserProfileCacheAbsenceHandle{inner,binding:self.binding.clone()})
    }
    /// Negative-only original driver fact. No Client recapture, auth/storage
    /// grant or private output; transferred work and actual Host IO drain apart.
    pub fn terminal(&self)->Option<BrowserOwnedReadTerminalHandle>{self.terminal.terminal().map(|terminal|BrowserOwnedReadTerminalHandle{terminal})}
    pub fn control(&self)->Result<BrowserOwnedMessageReadControl,JsValue>{
        worker_only()?;let driver=self.driver.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
        Ok(BrowserOwnedMessageReadControl{control:driver.control(),binding:self.binding.clone()})
    }
    /// Only this native driver is borrowed; no BrowserCoreClient/auth lock is
    /// held while network, opaque key operations or native IO are pending.
    pub async fn next(&mut self)->Result<BrowserOwnedMessageReadStepHandle,JsValue>{
        worker_only()?;
        let step=self.driver.as_mut().ok_or_else(||JsValue::from_str("unavailable"))?.next().await.map_err(failure)?;
        if matches!(&step,OwnedBrowserReadStep::Selected(_)|OwnedBrowserReadStep::Metadata(_)){self.driver.take();}
        Ok(BrowserOwnedMessageReadStepHandle{id:uuid::Uuid::new_v4().to_string(),step:Some(step),binding:self.binding.clone(),request:self.request.clone()})
    }
}
#[wasm_bindgen]
pub struct BrowserProfileCacheAbsenceHandle {inner:openmates_sdk::client::OwnedBrowserProfileCacheAbsence,binding:Binding}
#[wasm_bindgen]
impl BrowserProfileCacheAbsenceHandle {
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
    pub fn consume(&mut self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.consume(&client.client).map_err(failure)}
}
#[wasm_bindgen]
pub struct BrowserOwnedReadTerminalHandle {terminal:OwnedBrowserReadTerminal}
#[wasm_bindgen]
impl BrowserOwnedReadTerminalHandle {pub fn is_quiescent(&self)->bool{self.terminal.is_quiescent()}}
#[wasm_bindgen]
pub struct BrowserOwnedMessageReadStepHandle {id:String,step:Option<OwnedBrowserReadStep>,binding:Binding,request:CancellationToken}
#[wasm_bindgen]
impl BrowserOwnedMessageReadStepHandle {
    #[wasm_bindgen(getter)]pub fn id(&self)->String{self.id.clone()}
    #[wasm_bindgen(getter)]pub fn kind(&self)->String{match self.step.as_ref(){
        Some(OwnedBrowserReadStep::Apply(_))=>"apply",Some(OwnedBrowserReadStep::IO(_))=>"io",
        Some(OwnedBrowserReadStep::Selected(_))=>"selected_pending_metadata",Some(OwnedBrowserReadStep::Metadata(_))=>"metadata_pending_remainder",Some(OwnedBrowserReadStep::Refresh(_))=>"original_hint_refresh_pending",Some(OwnedBrowserReadStep::RowMetadata(_))=>"original_hint_row_metadata_pending",None=>"consumed",
    }.into()}
    pub fn apply(&mut self,client:&mut BrowserCoreClient)->Result<(),JsValue>{
        self.binding.check(client)?;
        if !matches!(self.step.as_ref(),Some(OwnedBrowserReadStep::Apply(_))){return Err(JsValue::from_str("unavailable"))}
        let Some(OwnedBrowserReadStep::Apply(phase))=self.step.take()else{return Err(JsValue::from_str("unavailable"))};
        phase.apply(&mut client.client).map_err(failure)?;self.binding.check(client)
    }
    pub fn uses_original_physical_draft_budget(&self)->bool {matches!(self.step.as_ref(),Some(OwnedBrowserReadStep::IO(io)) if io.uses_original_physical_draft_budget())}
    pub async fn execute(mut self,host_effect:js_sys::Function)->Result<BrowserOwnedMessageReadStepHandle,JsValue>{
        worker_only()?;
        let Some(OwnedBrowserReadStep::IO(io))=self.step.take()else{return Err(JsValue::from_str("unavailable"))};
        let draft_budget=io.uses_original_physical_draft_budget();
        let phase=io.execute(move|plan:String|async move{if draft_budget{host_original_physical_draft_packet(plan,&host_effect,&worker_guard).await}else{host_local_packet(plan,&host_effect,&worker_guard).await}}).await.map_err(failure)?;
        Ok(BrowserOwnedMessageReadStepHandle{id:self.id,step:Some(OwnedBrowserReadStep::Apply(phase)),binding:self.binding,request:self.request})
    }
    /// Called only after the existing native Host's original prepared-id IO
    /// drain acknowledgement. No caller drained/complete boolean is accepted.
    pub fn take(&mut self,client:&BrowserCoreClient)->Result<String,JsValue>{
        self.binding.check(client)?;
        let mut encoded=match self.step.as_mut(){
            Some(OwnedBrowserReadStep::Selected(publication))=>publication.take(&client.client,true),
            Some(OwnedBrowserReadStep::Metadata(publication))=>publication.take(&client.client,true),
            _=>return Err(JsValue::from_str("unavailable")),
        }.map_err(failure)?;
        self.binding.check(client)?;Ok(std::mem::take(&mut *encoded))
    }
    /// Sealed cold-only completion of the already-taken selected view. This
    /// cannot discard an incoming hint or acknowledge remote metadata work.
    pub fn finish_cold(&mut self,client:&BrowserCoreClient)->Result<(),JsValue>{
        self.binding.check(client)?;
        let Some(OwnedBrowserReadStep::Selected(publication))=self.step.take()else{return Err(JsValue::from_str("unavailable"))};
        publication.finish_cold(&client.client).map_err(failure)?;self.binding.check(client)
    }
    /// Explicit typed incomplete work. Retain this exact native resource; do not
    /// immediately retry the same hint or label selected publication complete.
    pub fn pending_metadata(&mut self,client:&BrowserCoreClient)->Result<BrowserOwnedMetadataContinuationHandle,JsValue>{
        self.binding.check(client)?;
        let Some(OwnedBrowserReadStep::Selected(publication))=self.step.take()else{return Err(JsValue::from_str("unavailable"))};
        let continuation=publication.into_metadata_continuation(&client.client).map_err(failure)?;
        self.binding.check(client)?;
        Ok(BrowserOwnedMetadataContinuationHandle{id:self.id.clone(),continuation:Some(continuation),recovery_root:None,binding:self.binding.clone(),request:self.request.clone()})
    }
    /// Actual per-B metadata persistence is not whole-hint completion.
    pub fn pending_remainder(&mut self,client:&BrowserCoreClient)->Result<BrowserOwnedMetadataContinuationHandle,JsValue>{
        self.binding.check(client)?;
        let Some(OwnedBrowserReadStep::Metadata(publication))=self.step.take()else{return Err(JsValue::from_str("unavailable"))};
        let continuation=publication.into_remainder(&client.client).map_err(failure)?;
        self.binding.check(client)?;
        Ok(BrowserOwnedMetadataContinuationHandle{id:self.id.clone(),continuation:Some(continuation),recovery_root:None,binding:self.binding.clone(),request:self.request.clone()})
    }
    pub fn authenticated_source_stamp(&self,client:&BrowserCoreClient)->Result<String,JsValue>{
        self.binding.check(client)?;
        let Some(OwnedBrowserReadStep::Selected(publication))=self.step.as_ref()else{return Err(JsValue::from_str("unavailable"))};
        publication.authenticated_source_stamp(&client.client).map_err(failure)
    }
    pub fn authenticated_messages_version(&self,client:&BrowserCoreClient)->Result<Option<f64>,JsValue>{
        self.binding.check(client)?;
        let Some(OwnedBrowserReadStep::Selected(publication))=self.step.as_ref()else{return Err(JsValue::from_str("unavailable"))};
        publication.authenticated_messages_version(&client.client).map(|value|value.map(|n|n as f64)).map_err(failure)
    }
}
#[wasm_bindgen]
pub struct BrowserOwnedMetadataContinuationHandle {id:String,continuation:Option<OwnedBrowserMetadataContinuation>,recovery_root:Option<Arc<OwnedBrowserMetadataContinuation>>,binding:Binding,request:CancellationToken}
#[wasm_bindgen]
impl BrowserOwnedMetadataContinuationHandle {
    #[wasm_bindgen(getter)]pub fn id(&self)->String{self.id.clone()}
    #[wasm_bindgen(getter)]pub fn kind(&self)->String{self.continuation.as_ref().or_else(||self.recovery_root.as_deref()).map(|value|value.kind()).unwrap_or("consumed").into()}
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{
        self.binding.check(client)?;
        self.continuation.as_ref().or_else(||self.recovery_root.as_deref()).ok_or_else(||JsValue::from_str("unavailable"))?.check_original(&client.client).map_err(failure)
    }
    /// Start the next exact native metadata phase after the selected Host IO
    /// drain/publication. No new Client, scope, hint or positive receipt exists.
    pub fn begin_metadata(&mut self,client:&BrowserCoreClient)->Result<BrowserOwnedMessageReadHandle,JsValue>{
        self.binding.check(client)?;
        let value=self.continuation.take().ok_or_else(||JsValue::from_str("unavailable"))?;
        let driver=value.begin_metadata(&client.client).map_err(failure)?;self.binding.check(client)?;
        let terminal=driver.terminal_observer();
        Ok(BrowserOwnedMessageReadHandle{driver:Some(driver),binding:self.binding.clone(),request:self.request.clone(),terminal})
    }
    pub fn cancel(&self){if let Some(value)=self.continuation.as_ref().or_else(||self.recovery_root.as_deref()){value.cancel();}}
    pub async fn wait_cancelled(&self)->Result<(),JsValue>{
        worker_only()?;
        self.continuation.as_ref().or_else(||self.recovery_root.as_deref()).ok_or_else(||JsValue::from_str("unavailable"))?.wait_cancelled().await;Ok(())
    }
    pub async fn wait_recovery_work(&self)->Result<(),JsValue>{
        worker_only()?;
        self.continuation.as_ref().or_else(||self.recovery_root.as_deref()).ok_or_else(||JsValue::from_str("unavailable"))?.wait_recovery_work().await.map_err(failure)
    }
    pub fn close(&mut self){if let Some(value)=self.continuation.take(){value.cancel();drop(value);}if let Some(value)=self.recovery_root.take(){value.cancel();drop(value);}}
}
enum StartMode<'a>{Cold,LocalFirst,Incoming(&'a str),
    #[cfg(feature="browser-metadata-prototype")]
    ProfileCache(&'a BrowserProfileCacheReadinessHandle),
}
impl BrowserCoreClient {
    fn start_owned_message_read(&mut self,handle:&str,generation:f64,owner:&str,mode:StartMode<'_>,id:&str,
        selector_json:&str,scope_json:&str,now_seconds:f64)->Result<BrowserOwnedMessageReadHandle,JsValue>{
        worker_only()?;
        #[cfg(feature="browser-metadata-prototype")]
        let profile_store=match &mode{StartMode::ProfileCache(profile)=>{profile.ensure_current(self)?;Some(profile.store.clone())},_=>None};
        let binding=Binding{handle:handle.into(),generation,owner:owner.into(),
            #[cfg(feature="browser-metadata-prototype")]profile_store,
        };binding.check(self)?;
        if selector_json.len()>2048||scope_json.len()>256||!now_seconds.is_finite()||now_seconds<0.0||now_seconds.fract()!=0.0||now_seconds>9_007_199_254_740_991.0{return Err(JsValue::from_str("invalid_request"))}
        let options=serde_json::from_str(selector_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let scope=serde_json::from_str(scope_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let request=CancellationToken::new();
        let driver=match mode {
            StartMode::Cold=>self.client.begin_owned_browser_cold_message_read(request.clone(),owner,id,options,scope,now_seconds as u64,true),
            StartMode::LocalFirst=>self.client.begin_owned_browser_local_first_message_read(request.clone(),owner,id,options,scope,now_seconds as u64,true),
            #[cfg(feature="browser-metadata-prototype")]
            StartMode::ProfileCache(profile)=>self.client.begin_owned_browser_profile_cache_read(profile.inner.clone(),request.clone(),owner,id,options,scope,now_seconds as u64,true),
            StartMode::Incoming(monitor_id)=>{
                let monitor=cache_operations::owned_read_monitor(self,handle,generation,owner,monitor_id)?;
                self.client.begin_owned_browser_incoming_message_read(monitor,request.clone(),owner,id,options,scope,now_seconds as u64,true)
            },
        }.map_err(failure)?;
        binding.check(self)?;let terminal=driver.terminal_observer();
        Ok(BrowserOwnedMessageReadHandle{driver:Some(driver),binding,request,terminal})
    }
}

/// Same original authenticated Client and native bootstrap/profile/store only.
/// This is not a substitute restore/status, generic key or network admission.
#[cfg(feature="browser-metadata-prototype")]
#[wasm_bindgen]
pub struct BrowserProfileCacheReadinessHandle {
    inner:Arc<openmates_sdk::client::BrowserProfileCacheReadiness>,binding:Binding,
    store:openmates_sdk::client::BoundInitialSyncStore,
}
#[cfg(feature="browser-metadata-prototype")]
#[wasm_bindgen]
impl BrowserProfileCacheReadinessHandle {
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{
        self.binding.check(client)?;self.store.ensure_profile_cache_current(&client.client).map_err(failure)?;
        self.inner.ensure_current(&client.client).map_err(failure)
    }
    pub fn cancel(&self){self.inner.cancel();}
    pub async fn wait_invalidated(&self)->Result<(),JsValue>{
        worker_only()?;
        tokio::select!{_ = self.inner.wait_invalidated()=>{},_ = self.store.wait_native_invalidated()=>{}}
        // Waking is negative only; neither branch reports IO drain or release.
        self.inner.cancel();Ok(())
    }
}
#[cfg(feature="browser-metadata-prototype")]
#[wasm_bindgen]
impl BrowserCoreClient {
    /// Must run immediately after genuine original restore and before refresh.
    pub fn prepare_profile_cache_readiness(&self,handle:&str,generation:f64,owner:&str)->Result<BrowserProfileCacheReadinessHandle,JsValue>{
        worker_only()?;let store=self.initial_sync_store.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
        store.ensure_current(&self.client).map_err(failure)?;
        let binding=Binding{handle:handle.into(),generation,owner:owner.into(),profile_store:Some(store.clone())};binding.check(self)?;
        let inner=self.client.prepare_browser_profile_cache_readiness().map_err(failure)?;
        let result=BrowserProfileCacheReadinessHandle{inner,binding,store:store.clone()};result.ensure_current(self)?;Ok(result)
    }
    pub fn begin_owned_profile_cache_read(&mut self,readiness:&BrowserProfileCacheReadinessHandle,handle:&str,generation:f64,owner:&str,id:&str,selector_json:&str,scope_json:&str,now_seconds:f64)->Result<BrowserOwnedMessageReadHandle,JsValue>{
        self.start_owned_message_read(handle,generation,owner,StartMode::ProfileCache(readiness),id,selector_json,scope_json,now_seconds)
    }
}
#[wasm_bindgen]
impl BrowserCoreClient {
    pub fn begin_owned_cache_cold_read(&mut self,handle:&str,generation:f64,owner:&str,id:&str,selector_json:&str,scope_json:&str,now_seconds:f64)->Result<BrowserOwnedMessageReadHandle,JsValue>{self.start_owned_message_read(handle,generation,owner,StartMode::Cold,id,selector_json,scope_json,now_seconds)}
    pub fn begin_owned_cache_local_first_read(&mut self,handle:&str,generation:f64,owner:&str,id:&str,selector_json:&str,scope_json:&str,now_seconds:f64)->Result<BrowserOwnedMessageReadHandle,JsValue>{self.start_owned_message_read(handle,generation,owner,StartMode::LocalFirst,id,selector_json,scope_json,now_seconds)}
    pub fn begin_owned_cache_incoming_read(&mut self,handle:&str,generation:f64,owner:&str,monitor_id:&str,id:&str,selector_json:&str,scope_json:&str,now_seconds:f64)->Result<BrowserOwnedMessageReadHandle,JsValue>{self.start_owned_message_read(handle,generation,owner,StartMode::Incoming(monitor_id),id,selector_json,scope_json,now_seconds)}
}

#[path="browser_owned_recovery.rs"]
mod original_recovery;

#[wasm_bindgen]
pub struct BrowserOriginalPhysicalDraftInventory {inner:openmates_sdk::client::OriginalPhysicalDraftInventory,binding:Binding}
#[wasm_bindgen]
impl BrowserOwnedMessageReadHandle {
    pub fn begin_physical_draft_inventory(&self,client:&BrowserCoreClient,port:&crate::browser::BrowserOriginalRecoveryPort)->Result<BrowserOriginalPhysicalDraftInventory,JsValue>{
        self.binding.check(client)?;
        let original=port.original(client)?;
        let inner=self.driver.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?.begin_physical_draft_inventory(&client.client,original).map_err(failure)?;
        self.binding.check(client)?;Ok(BrowserOriginalPhysicalDraftInventory{inner,binding:self.binding.clone()})
    }
}
#[wasm_bindgen]
impl BrowserOriginalPhysicalDraftInventory {
    #[wasm_bindgen(getter)]pub fn kind(&self)->String{self.inner.kind().into()}
    pub async fn drive(&mut self)->Result<(),JsValue>{worker_only()?;self.inner.drive().await.map_err(failure)}
    pub fn apply(&mut self,client:&mut BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.apply(&mut client.client).map_err(failure)?;self.binding.check(client)}
}
// Distinct typed IO-only compatibility bound, called only by a genuine Core IO
// whose original native inventory witness has enabled this exact draft path.
async fn host_original_physical_draft_packet(request:String,effect:&js_sys::Function,guard:&impl Fn()->openmates_sdk::Result<()>)->openmates_sdk::Result<String>{
    guard()?;let invoked=effect.call1(&JsValue::UNDEFINED,&JsValue::from_str(&request)).map_err(|_|openmates_sdk::Error::Io)?;
    let result=wasm_bindgen_futures::JsFuture::from(js_sys::Promise::resolve(&invoked)).await;
    let value=result.map_err(|_|openmates_sdk::Error::Io).and_then(|value|value.as_string().map(Zeroizing::new).ok_or(openmates_sdk::Error::Protocol));
    guard()?;let mut value=value?;if value.len()>4*1024*1024{return Err(openmates_sdk::Error::Protocol)}Ok(std::mem::take(&mut *value))
}

#[wasm_bindgen]
impl BrowserOwnedMetadataContinuationHandle {
    pub fn begin_next_physical_draft_inventory(&self,client:&BrowserCoreClient,port:&crate::browser::BrowserOriginalRecoveryPort)->Result<Option<BrowserOriginalPhysicalDraftInventory>,JsValue>{
        self.binding.check(client)?;
        let original=port.original(client)?;
        let inner=self.continuation.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?.begin_next_physical_draft_inventory(&client.client,original).map_err(failure)?;
        self.binding.check(client)?;Ok(inner.map(|inner|BrowserOriginalPhysicalDraftInventory{inner,binding:self.binding.clone()}))
    }
}
