//! Explicit selected artifact only: genuine phased read -> SAME Main native store.
//! No plaintext/key/row export, artifact inventory, journal retirement or ACK.
use super::*;
use super::core::saved_embed::{PreparedOwnedSavedEmbedRead,OwnedSavedEmbedReadStep,
    OwnedSavedEmbedReadControl,OwnedSavedEmbedReadTerminal,SavedEmbedRead};
use std::rc::Rc;

struct Origin {binding:Binding,progress:Rc<core::BrowserOriginalHintRecoveryProgress>,store:core::BoundInitialSyncStore}
impl Origin {
    fn check(&self,client:&BrowserCoreClient)->Result<(),JsValue>{
        self.binding.check(client)?;self.store.ensure_current(&client.client).map_err(failure)?;
        self.progress.ensure_current(&client.client).map_err(failure)
    }
    // Actual auth bookkeeping must reach Core even after local cancellation or
    // a refused private continuation. This check cannot admit private output.
    fn target(&self,client:&BrowserCoreClient)->Result<(),JsValue>{
        worker_only()?;if client.handle!=self.binding.handle{return Err(JsValue::from_str("session_expired"))}Ok(())
    }
    fn matched(&self,recovery:&BrowserOriginalRecoveryHandle,client:&BrowserCoreClient,
        metadata:&main_metadata_store::BrowserRecoveryMainMetadataStoredHandle)->Result<(),JsValue>{
        self.check(client)?;recovery.binding.check(client)?;metadata.binding.check(client)?;
        metadata.inner.ensure_current(&client.client).map_err(failure)?;
        let Some(Phase::Progress(progress))=recovery.phase.as_ref()else{return Err(JsValue::from_str("unavailable"))};
        if !Rc::ptr_eq(progress,&self.progress)||!Rc::ptr_eq(progress,&metadata.progress){return Err(JsValue::from_str("unavailable"))}Ok(())
    }
}

#[wasm_bindgen]
pub struct BrowserRecoveryCodeEmbedReadHandle {driver:Option<PreparedOwnedSavedEmbedRead>,control:OwnedSavedEmbedReadControl,origin:Rc<Origin>}
#[wasm_bindgen]
pub struct BrowserRecoveryCodeEmbedReadControl {inner:OwnedSavedEmbedReadControl,origin:Rc<Origin>}
#[wasm_bindgen]
pub struct BrowserRecoveryCodeEmbedAcquisitionTerminal {inner:OwnedSavedEmbedReadTerminal}
#[wasm_bindgen]
pub struct BrowserRecoveryCodeEmbedReadStep {step:Option<OwnedSavedEmbedReadStep>,origin:Rc<Origin>,control:Rc<OwnedSavedEmbedReadControl>}
#[wasm_bindgen]
pub struct BrowserRecoverySelectedCodeEmbedRead {read:Option<SavedEmbedRead>,origin:Rc<Origin>,control:Rc<OwnedSavedEmbedReadControl>}

#[wasm_bindgen]
impl BrowserOriginalRecoveryHandle {
    /// ID is selection DATA. Only the fresh authenticated source and Core
    /// native policy can bind it to this actual Main assistant message.
    pub fn prepare_selected_code_embed_read(&self,client:&mut BrowserCoreClient,
        metadata:&main_metadata_store::BrowserRecoveryMainMetadataStoredHandle,embed_id:&str)->Result<BrowserRecoveryCodeEmbedReadHandle,JsValue>{
        self.binding.check(client)?;metadata.binding.check(client)?;metadata.inner.ensure_current(&client.client).map_err(failure)?;
        let Some(Phase::Progress(progress))=self.phase.as_ref()else{return Err(JsValue::from_str("unavailable"))};
        if !Rc::ptr_eq(progress,&metadata.progress){return Err(JsValue::from_str("unavailable"))}
        let store=client.initial_sync_store.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?.clone();
        let origin=Rc::new(Origin{binding:self.binding.clone(),progress:progress.clone(),store});origin.matched(self,client,metadata)?;
        let driver=client.client.prepare_owned_saved_embed_read(embed_id,tokio_util::sync::CancellationToken::new()).map_err(failure)?;
        let control=driver.control();Ok(BrowserRecoveryCodeEmbedReadHandle{driver:Some(driver),control,origin})
    }
    /// Consumes the genuine read once only after all original opaque resources
    /// match. Core remains the sole crypto/native CAS/readback policy owner.
    pub fn begin_selected_code_embed_local_store(&self,client:&BrowserCoreClient,
        metadata:&main_metadata_store::BrowserRecoveryMainMetadataStoredHandle,read:&mut BrowserRecoverySelectedCodeEmbedRead)->Result<BrowserRecoveryCodeEmbedStoreHandle,JsValue>{
        read.origin.matched(self,client,metadata)?;read.control.ensure_current(&client.client).map_err(failure)?;
        let actual=read.read.take().ok_or_else(||JsValue::from_str("unavailable"))?;
        let inner=read.origin.store.begin_main_code_embed_store(&client.client,read.origin.progress.clone(),actual).map_err(failure)?;
        Ok(BrowserRecoveryCodeEmbedStoreHandle{inner,origin:read.origin.clone()})
    }
}
#[wasm_bindgen]
impl BrowserRecoveryCodeEmbedReadHandle {
    pub fn control(&self)->Result<BrowserRecoveryCodeEmbedReadControl,JsValue>{worker_only()?;Ok(BrowserRecoveryCodeEmbedReadControl{inner:self.driver.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?.control(),origin:self.origin.clone()})}
    pub fn terminal(&self)->Option<BrowserRecoveryCodeEmbedAcquisitionTerminal>{self.control.terminal().map(|inner|BrowserRecoveryCodeEmbedAcquisitionTerminal{inner})}
    /// No Client borrow or auth lock is held while this actual driver waits.
    pub async fn next(&mut self)->Result<BrowserRecoveryCodeEmbedReadStep,JsValue>{
        worker_only()?;let driver=self.driver.as_mut().ok_or_else(||JsValue::from_str("unavailable"))?;
        let step=driver.next().await.map_err(failure)?;let control=driver.control();
        if matches!(&step,OwnedSavedEmbedReadStep::Ready(_)){self.driver.take();}
        Ok(BrowserRecoveryCodeEmbedReadStep{step:Some(step),origin:self.origin.clone(),control:Rc::new(control)})
    }
}
#[wasm_bindgen]
impl BrowserRecoveryCodeEmbedReadControl {
    pub fn cancel(&self){self.inner.cancel();}
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.origin.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
    pub fn terminal(&self)->Option<BrowserRecoveryCodeEmbedAcquisitionTerminal>{self.inner.terminal().map(|inner|BrowserRecoveryCodeEmbedAcquisitionTerminal{inner})}
}
#[wasm_bindgen]
impl BrowserRecoveryCodeEmbedAcquisitionTerminal {pub fn acquisition_io_quiescent(&self)->bool{self.inner.acquisition_io_quiescent()}}
#[wasm_bindgen]
impl BrowserRecoveryCodeEmbedReadStep {
    #[wasm_bindgen(getter)]pub fn kind(&self)->String{match self.step.as_ref(){Some(OwnedSavedEmbedReadStep::Apply(_))=>"apply",Some(OwnedSavedEmbedReadStep::Ready(_))=>"ready",None=>"consumed"}.into()}
    pub fn apply(&mut self,client:&mut BrowserCoreClient)->Result<(),JsValue>{
        // Refuse foreign binding BEFORE consuming the original pending phase.
        self.origin.target(client)?;
        if !matches!(self.step.as_ref(),Some(OwnedSavedEmbedReadStep::Apply(_))){return Err(JsValue::from_str("unavailable"))}
        let Some(OwnedSavedEmbedReadStep::Apply(actual))=self.step.take()else{return Err(JsValue::from_str("unavailable"))};
        actual.apply(&mut client.client).map_err(failure)
    }
    pub fn retain(&mut self,client:&BrowserCoreClient)->Result<BrowserRecoverySelectedCodeEmbedRead,JsValue>{
        self.origin.check(client)?;
        let Some(OwnedSavedEmbedReadStep::Ready(ready))=self.step.as_mut()else{return Err(JsValue::from_str("unavailable"))};
        let read=ready.retain(&client.client).map_err(failure)?;self.step.take();
        // A separate original control survives the one-use transfer.
        Ok(BrowserRecoverySelectedCodeEmbedRead{read:Some(read),origin:self.origin.clone(),control:self.control.clone()})
    }
}
#[wasm_bindgen]
impl BrowserRecoverySelectedCodeEmbedRead {
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.origin.check(client)?;if self.read.is_none(){return Err(JsValue::from_str("unavailable"))}self.control.ensure_current(&client.client).map_err(failure)}
    pub fn cancel(&self){self.control.cancel();}
}

#[wasm_bindgen]
pub struct BrowserRecoveryCodeEmbedStoreHandle {inner:core::BrowserMainCodeEmbedStore,origin:Rc<Origin>}
#[wasm_bindgen]
pub struct BrowserRecoveryCodeEmbedStoreControl {inner:core::BrowserMainCodeEmbedControl,origin:Rc<Origin>}
#[wasm_bindgen]
pub struct BrowserRecoveryCodeEmbedStoredHandle {inner:core::BrowserMainCodeEmbedStored,origin:Rc<Origin>}
#[wasm_bindgen]
pub struct BrowserRecoveryCodeEmbedNativeTerminal {inner:core::BrowserMainCodeEmbedNativeTerminal}
#[wasm_bindgen]
impl BrowserRecoveryCodeEmbedNativeTerminal {pub fn native_io_quiescent(&self)->bool{self.inner.native_io_quiescent()}}
#[wasm_bindgen]
impl BrowserRecoveryCodeEmbedStoreControl {
    pub fn cancel(&self){self.inner.cancel();}
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.origin.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
}
#[wasm_bindgen]
impl BrowserRecoveryCodeEmbedStoreHandle {
    pub fn control(&self)->Result<BrowserRecoveryCodeEmbedStoreControl,JsValue>{worker_only()?;Ok(BrowserRecoveryCodeEmbedStoreControl{inner:self.inner.control(),origin:self.origin.clone()})}
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.origin.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
    pub async fn drive(&mut self)->Result<(),JsValue>{worker_only()?;self.inner.drive().await.map_err(failure)}
    pub fn terminal(&self)->Option<BrowserRecoveryCodeEmbedNativeTerminal>{self.inner.terminal().map(|inner|BrowserRecoveryCodeEmbedNativeTerminal{inner})}
    pub fn finish(&mut self,client:&BrowserCoreClient)->Result<BrowserRecoveryCodeEmbedStoredHandle,JsValue>{self.origin.check(client)?;let inner=self.inner.finish(&client.client).map_err(failure)?;Ok(BrowserRecoveryCodeEmbedStoredHandle{inner,origin:self.origin.clone()})}
}
#[wasm_bindgen]
impl BrowserRecoveryCodeEmbedStoredHandle {pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.origin.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}}
