//! Thin owning-Worker adapter for actual shared original recovery resources.
//! All protocol/crypto/storage/receipt policy remains in the shared Rust core.
use super::*;
use openmates_sdk::client::{self as core,OriginalBrowserRecoveryPort};
use crate::browser::BrowserOriginalRecoveryPort;

enum Phase {
    Apply(core::BrowserOriginalHintRecoveryApply),Io(core::BrowserOriginalHintRecoveryIo),
    Pending(core::BrowserOriginalHintRecoveryPendingPersistence),
    Prepared(core::BrowserOriginalHintRecoveryCheckpointPreparation),
    Ready(core::BrowserOriginalHintRecoveryCheckpointReadiness),
    Read(core::BrowserOriginalHintRecoveryCheckpointRead),
    ReadResult(core::BrowserOriginalHintRecoveryCheckpointReadResult),
    Crypto(core::BrowserOriginalHintRecoveryCheckpointCrypto),
    Write(core::BrowserOriginalHintRecoveryCheckpointWrite),
    NativeWrite(core::BrowserOriginalHintRecoveryCheckpointNativeWrite),
    NativeResult(core::BrowserOriginalHintRecoveryCheckpointNativeWriteResult),
    Readback(core::BrowserOriginalHintRecoveryCheckpointReadbackCrypto),
    Verified(core::BrowserOriginalHintRecoveryCheckpointVerified),
    Durable(core::BrowserOriginalHintRecoveryCheckpointDurable),
    Adopt(core::BrowserOriginalHintRecoveryAdoption),
    Progress(std::rc::Rc<core::BrowserOriginalHintRecoveryProgress>),
    Deferred(core::BrowserOriginalHintRecoveryDeferred),
    Failure(core::BrowserOriginalHintRecoveryPersistenceFailure),Refused,
}
/// Separate negative control remains callable while handle.drive owns a mutable
/// wasm-bindgen borrow across native IO. It can never release output or drain.
#[wasm_bindgen]
pub struct BrowserOriginalRecoveryControl {inner:core::BrowserOriginalHintRecoveryControl}
#[wasm_bindgen]
impl BrowserOriginalRecoveryControl {
    pub fn cancel(&self){self.inner.cancel();}
    pub async fn wait_cancelled(&self)->Result<(),JsValue>{worker_only()?;self.inner.wait_cancelled().await;Ok(())}
}
#[wasm_bindgen]
pub struct BrowserOriginalRecoveryHandle {
    binding:Binding,port:OriginalBrowserRecoveryPort,job_kind:core::CompletionRecoveryKind,
    driver:Option<core::BrowserOriginalHintRecoveryDriver>,
    control:core::BrowserOriginalHintRecoveryControl,phase:Option<Phase>,
}
#[wasm_bindgen]
impl BrowserCoreClient {
    /// Existing explicit foreground choice. Hints and ports never enable it.
    pub fn set_foreground_recovery(&mut self,handle:&str,generation:f64,owner:&str,enabled:bool)->Result<(),JsValue>{
        let binding=Binding{handle:handle.into(),generation,owner:owner.into(),
            #[cfg(feature="browser-metadata-prototype")]
            profile_store:self.initial_sync_store.clone(),
        };binding.check(self)?;
        self.client.set_foreground_completion_recovery(enabled).map_err(failure)?;binding.check(self)
    }
}
#[wasm_bindgen]
impl BrowserOwnedMetadataContinuationHandle {
    /// Consumes only the original committed metadata remainder and actual full
    /// notification offer. No caller job/stage/owner or recovered DTO is read.
    pub fn begin_next_recovery(&mut self,client:&mut BrowserCoreClient,port:&BrowserOriginalRecoveryPort)->Result<Option<BrowserOriginalRecoveryHandle>,JsValue>{
        self.binding.check(client)?;
        let value=self.continuation.as_ref().or_else(||self.recovery_root.as_deref()).ok_or_else(||JsValue::from_str("unavailable"))?;
        let Some(job)=value.next_recovery_offer(&client.client).map_err(failure)?else{return Ok(None)};
        let job_kind=job.kind;
        let original=port.original(client)?.clone();
        if self.recovery_root.is_none(){
            let value=self.continuation.take().ok_or_else(||JsValue::from_str("unavailable"))?;
            self.recovery_root=Some(std::sync::Arc::new(value));
        }
        let value=self.recovery_root.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
        let driver=value.begin_shared_recovery_with_checkpoint_port(&mut client.client,&job,&original).map_err(failure)?;
        let control=driver.control();self.binding.check(client)?;
        Ok(Some(BrowserOriginalRecoveryHandle{binding:self.binding.clone(),port:original,job_kind,driver:Some(driver),control,phase:None}))
    }
}
fn retained<T>(result:std::result::Result<T,core::BrowserOriginalHintRecoveryPersistenceFailure>,next:impl FnOnce(T)->Phase)->Phase{
    match result{Ok(value)=>next(value),Err(error)=>Phase::Failure(error)}
}
#[wasm_bindgen]
impl BrowserOriginalRecoveryHandle {
    #[wasm_bindgen(getter)]
    pub fn kind(&self)->String{match self.phase.as_ref(){
        None=>if self.driver.is_some(){"next"}else{"retired"},Some(Phase::Apply(_))=>"apply",Some(Phase::Io(_))=>"io",
        Some(Phase::Pending(_))=>"checkpoint_prepare",Some(Phase::Prepared(_))=>"checkpoint_ready",
        Some(Phase::Ready(_))=>"checkpoint_read_start",Some(Phase::Read(_))=>"checkpoint_read",
        Some(Phase::ReadResult(_))=>"checkpoint_read_apply",Some(Phase::Crypto(_))=>"checkpoint_crypto",
        Some(Phase::Write(_))=>"checkpoint_write_start",Some(Phase::NativeWrite(_))=>"checkpoint_write",
        Some(Phase::NativeResult(_))=>"checkpoint_write_apply",Some(Phase::Readback(_))=>"checkpoint_readback_crypto",
        Some(Phase::Verified(_))=>"checkpoint_verify",Some(Phase::Durable(_))=>"checkpoint_commit",
        Some(Phase::Adopt(_))=>"adopt",Some(Phase::Progress(_))=>"recovery_pending_local_persistence",
        Some(Phase::Deferred(_))=>"deferred",Some(Phase::Failure(_))=>"retained_failure",Some(Phase::Refused)=>"refused",
    }.into()}
    /// Selection DATA captured from the actual Core offer, never caller input.
    /// The selected Core operation independently validates original Progress.
    #[wasm_bindgen(getter)]
    pub fn job_kind(&self)->String{match self.job_kind{core::CompletionRecoveryKind::Main=>"main",core::CompletionRecoveryKind::Metadata=>"metadata"}.into()}
    pub fn failure_kind(&self)->Option<String>{match self.phase.as_ref(){Some(Phase::Failure(error))=>Some(error.error_kind().into()),Some(Phase::Refused)=>Some("unavailable".into()),_=>None}}
    /// Encrypted checkpoint identity DATA only; never a durability constructor.
    pub fn pending_checkpoint_digest(&self)->Result<Option<String>,JsValue>{worker_only()?;match self.phase.as_ref(){Some(Phase::Pending(value))=>value.checkpoint().and_then(|value|value.digest()).map(Some).map_err(failure),_=>Ok(None)}}
    pub fn control(&self)->Result<BrowserOriginalRecoveryControl,JsValue>{
        worker_only()?;
        let driver=self.driver.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
        Ok(BrowserOriginalRecoveryControl{inner:driver.control()})
    }
    /// Negative own-resource retirement only after actual canonical/shared-commit
    /// adoption or a genuine deferred terminal. Failure/unknown/start states
    /// retain their exact resources; this never acknowledges the whole hint.
    pub fn retire(&mut self)->Result<(),JsValue>{
        worker_only()?;
        if !matches!(self.phase.as_ref(),Some(Phase::Progress(_))|Some(Phase::Deferred(_))){return Err(JsValue::from_str("unavailable"))}
        self.control.cancel();self.phase.take();self.driver.take();Ok(())
    }
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{
        self.binding.check(client)?;
        match self.phase.as_ref(){Some(Phase::Pending(value))=>value.check_original(&client.client).map_err(failure),Some(Phase::Progress(value))=>value.ensure_current(&client.client).map_err(failure),Some(Phase::Failure(_))|Some(Phase::Refused)=>Err(JsValue::from_str("unavailable")),_=>Err(JsValue::from_str("unavailable"))}
    }
    /// Await only native driver/IO/crypto resources; no Client/auth lock exists.
    pub async fn drive(&mut self)->Result<(),JsValue>{
        worker_only()?;
        let phase=match self.phase.take(){
            None=>{
                let step=self.driver.as_mut().ok_or_else(||JsValue::from_str("unavailable"))?.next().await;
                match step{
                    Ok(core::BrowserOriginalHintRecoveryStep::Apply(value))=>Phase::Apply(value),
                    Ok(core::BrowserOriginalHintRecoveryStep::Io(value))=>Phase::Io(value),
                    Ok(core::BrowserOriginalHintRecoveryStep::PendingPersistence(value))=>Phase::Pending(value),
                    Ok(core::BrowserOriginalHintRecoveryStep::Adopt(value))=>Phase::Adopt(value),
                    Ok(core::BrowserOriginalHintRecoveryStep::Deferred(value))=>Phase::Deferred(value),
                    Err(_)=>{self.control.cancel();Phase::Refused},
                }
            },
            Some(Phase::Io(value))=>{match value.drive().await{Ok(resume)=>{if self.driver.as_mut().ok_or_else(||JsValue::from_str("unavailable"))?.resume(resume).is_err(){self.control.cancel();self.phase=Some(Phase::Refused);}return Ok(())},Err(_)=>{self.control.cancel();Phase::Refused}}},
            Some(Phase::Prepared(value))=>Phase::Ready(value.wait_ready(&self.port).await),
            Some(Phase::Read(value))=>Phase::ReadResult(value.drive().await),
            Some(Phase::Crypto(value))=>retained(value.drive().await,Phase::Write),
            Some(Phase::NativeWrite(value))=>Phase::NativeResult(value.drive().await),
            Some(Phase::Readback(value))=>retained(value.drive().await,Phase::Verified),
            Some(other)=>{self.phase=Some(other);return Err(JsValue::from_str("unavailable"))},
        };
        self.phase=Some(phase);Ok(())
    }
    /// Every original Client/native start/final publication phase is short and
    /// synchronous. Errors keep the exact persistence failure/resource in self.
    pub fn apply(&mut self,client:&mut BrowserCoreClient)->Result<(),JsValue>{
        self.binding.check(client)?;
        let phase=match self.phase.take().ok_or_else(||JsValue::from_str("unavailable"))?{
            Phase::Apply(value)=>{
                match value.apply(&mut client.client){Ok(resume)=>{if self.driver.as_mut().ok_or_else(||JsValue::from_str("unavailable"))?.resume(resume).is_err(){self.control.cancel();self.phase=Some(Phase::Refused);}return Ok(())},Err(_)=>{self.control.cancel();Phase::Refused}}
            },
            Phase::Pending(value)=>retained(value.prepare_checkpoint(&client.client),Phase::Prepared),
            Phase::Ready(value)=>retained(value.start(&client.client),Phase::Read),
            Phase::ReadResult(value)=>retained(value.into_crypto(&client.client),Phase::Crypto),
            Phase::Write(value)=>retained(value.start_native(&client.client,&self.port),Phase::NativeWrite),
            Phase::NativeResult(value)=>retained(value.readback(&client.client),Phase::Readback),
            Phase::Verified(value)=>retained(value.finish(&client.client),Phase::Durable),
            Phase::Durable(value)=>{
                match value.into_driver(&client.client){Ok(driver)=>{self.control=driver.control();self.driver=Some(driver);return Ok(())},Err(error)=>Phase::Failure(error)}
            },
            Phase::Adopt(value)=>match value.apply(&mut client.client){Ok(value)=>Phase::Progress(std::rc::Rc::new(value)),Err(_)=>{self.control.cancel();Phase::Refused}},
            other=>{self.phase=Some(other);return Err(JsValue::from_str("unavailable"))},
        };
        self.phase=Some(phase);Ok(())
    }
}
impl Drop for BrowserOriginalRecoveryHandle {fn drop(&mut self){self.control.cancel();}}
#[cfg(feature="browser-metadata-prototype")]
mod metadata_finalize {
 use super::*;
 #[wasm_bindgen]
 pub struct BrowserRecoveryMetadataFinalizeHandle {inner:core::BrowserMetadataRecoveryFinalize,binding:Binding}
 #[wasm_bindgen]
 pub struct BrowserRecoveryMetadataStoredHandle {inner:core::BrowserMetadataRecoveryLocalStored,binding:Binding}
 #[wasm_bindgen]
 pub struct BrowserRecoveryMetadataNativeTerminal {inner:core::BrowserMetadataRecoveryNativeTerminal}
 #[wasm_bindgen]
 impl BrowserRecoveryMetadataNativeTerminal {pub fn native_io_quiescent(&self)->bool{self.inner.native_io_quiescent()}}
 #[wasm_bindgen]
 impl BrowserOriginalRecoveryHandle {
  /// Only actual Personal metadata shared-commit Progress and the SAME restored
  /// Client's native store are admitted. No input rows, digest or success flag.
  pub fn begin_metadata_local_finalize(&self,client:&BrowserCoreClient)->Result<BrowserRecoveryMetadataFinalizeHandle,JsValue>{
   self.binding.check(client)?;
   let Some(Phase::Progress(progress))=self.phase.as_ref()else{return Err(JsValue::from_str("unavailable"))};
   let store=client.initial_sync_store.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
   let inner=store.begin_metadata_recovery_finalize(&client.client,progress.clone()).map_err(failure)?;
   self.binding.check(client)?;Ok(BrowserRecoveryMetadataFinalizeHandle{inner,binding:self.binding.clone()})
  }
 }
 #[wasm_bindgen]
 impl BrowserRecoveryMetadataFinalizeHandle {
  pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
  pub fn cancel(&self){self.inner.cancel();}
  pub async fn drive(&mut self)->Result<(),JsValue>{worker_only()?;self.inner.drive().await.map_err(failure)}
  pub fn terminal(&self)->Option<BrowserRecoveryMetadataNativeTerminal>{self.inner.terminal().map(|inner|BrowserRecoveryMetadataNativeTerminal{inner})}
  pub fn finish(&mut self,client:&BrowserCoreClient)->Result<BrowserRecoveryMetadataStoredHandle,JsValue>{
   self.binding.check(client)?;let inner=self.inner.finish(&client.client).map_err(failure)?;self.binding.check(client)?;
   Ok(BrowserRecoveryMetadataStoredHandle{inner,binding:self.binding.clone()})
  }
 }
 #[wasm_bindgen]
 impl BrowserRecoveryMetadataStoredHandle {
  pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
 }
}

#[cfg(feature="browser-metadata-prototype")]
mod main_metadata_store {
 use super::*;
 #[wasm_bindgen]
 pub struct BrowserRecoveryMainMetadataStoreHandle {inner:core::BrowserMainMetadataStore,binding:Binding,progress:std::rc::Rc<core::BrowserOriginalHintRecoveryProgress>}
 #[wasm_bindgen]
 pub struct BrowserRecoveryMainMetadataStoredHandle {pub(super) inner:core::BrowserMainMetadataStored,pub(super) binding:Binding,pub(super) progress:std::rc::Rc<core::BrowserOriginalHintRecoveryProgress>}
 #[wasm_bindgen]
 pub struct BrowserRecoveryMainMetadataNativeTerminal {inner:core::BrowserMainMetadataNativeTerminal}
 #[wasm_bindgen]
 impl BrowserRecoveryMainMetadataNativeTerminal {pub fn native_io_quiescent(&self)->bool{self.inner.native_io_quiescent()}}
 #[wasm_bindgen]
 impl BrowserOriginalRecoveryHandle {
  /// Actual same original Main Progress/store only. This partial facet cannot
  /// retire the Main journal or attest native transcript/artifact durability.
  pub fn begin_main_metadata_local_store(&self,client:&BrowserCoreClient)->Result<BrowserRecoveryMainMetadataStoreHandle,JsValue>{
   self.binding.check(client)?;
   let Some(Phase::Progress(progress))=self.phase.as_ref()else{return Err(JsValue::from_str("unavailable"))};
   let store=client.initial_sync_store.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
   let inner=store.begin_main_metadata_store(&client.client,progress.clone()).map_err(failure)?;
   self.binding.check(client)?;Ok(BrowserRecoveryMainMetadataStoreHandle{inner,binding:self.binding.clone(),progress:progress.clone()})
  }
 }
 #[wasm_bindgen]
 impl BrowserRecoveryMainMetadataStoreHandle {
  pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
  pub fn cancel(&self){self.inner.cancel();}
  pub async fn drive(&mut self)->Result<(),JsValue>{worker_only()?;self.inner.drive().await.map_err(failure)}
  pub fn terminal(&self)->Option<BrowserRecoveryMainMetadataNativeTerminal>{self.inner.terminal().map(|inner|BrowserRecoveryMainMetadataNativeTerminal{inner})}
  pub fn finish(&mut self,client:&BrowserCoreClient)->Result<BrowserRecoveryMainMetadataStoredHandle,JsValue>{
   self.binding.check(client)?;let inner=self.inner.finish(&client.client).map_err(failure)?;self.binding.check(client)?;Ok(BrowserRecoveryMainMetadataStoredHandle{inner,binding:self.binding.clone(),progress:self.progress.clone()})
  }
 }
 #[wasm_bindgen]
 impl BrowserRecoveryMainMetadataStoredHandle {pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}}
}

#[cfg(feature="browser-metadata-prototype")]
mod recovered_reply_store {
 use super::*;
 #[wasm_bindgen]
 pub struct BrowserRecoveryReplyStoreHandle {inner:core::BrowserRecoveredReplyStore,binding:Binding}
 #[wasm_bindgen]
 pub struct BrowserRecoveryReplyControl {inner:core::BrowserRecoveredReplyControl,binding:Binding}
 #[wasm_bindgen]
 pub struct BrowserRecoveryReplyStoredHandle {inner:core::BrowserRecoveredReplyStored,binding:Binding}
 #[wasm_bindgen]
 pub struct BrowserRecoveryReplyNativeTerminal {inner:core::BrowserRecoveredReplyNativeTerminal}
 #[wasm_bindgen]
 impl BrowserRecoveryReplyNativeTerminal {pub fn native_io_quiescent(&self)->bool{self.inner.native_io_quiescent()}}
 #[wasm_bindgen]
 impl BrowserOriginalRecoveryHandle {
  /// SAME opaque actual Main metadata proof and Progress, never row/receipt DATA.
  pub fn begin_recovered_reply_local_store(&self,client:&BrowserCoreClient,metadata:&main_metadata_store::BrowserRecoveryMainMetadataStoredHandle)->Result<BrowserRecoveryReplyStoreHandle,JsValue>{
   self.binding.check(client)?;metadata.binding.check(client)?;metadata.inner.ensure_current(&client.client).map_err(failure)?;
   let Some(Phase::Progress(progress))=self.phase.as_ref()else{return Err(JsValue::from_str("unavailable"))};
   if !std::rc::Rc::ptr_eq(progress,&metadata.progress){return Err(JsValue::from_str("unavailable"))}
   let store=client.initial_sync_store.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
   let inner=store.begin_recovered_reply_store(&client.client,progress.clone()).map_err(failure)?;
   self.binding.check(client)?;metadata.inner.ensure_current(&client.client).map_err(failure)?;
   Ok(BrowserRecoveryReplyStoreHandle{inner,binding:self.binding.clone()})
  }
 }
 #[wasm_bindgen]
 impl BrowserRecoveryReplyControl {
  pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
  pub fn cancel(&self){self.inner.cancel();}
 }
 #[wasm_bindgen]
 impl BrowserRecoveryReplyStoreHandle {
  pub fn control(&self)->Result<BrowserRecoveryReplyControl,JsValue>{worker_only()?;Ok(BrowserRecoveryReplyControl{inner:self.inner.control(),binding:self.binding.clone()})}
  pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
  pub async fn drive(&mut self)->Result<(),JsValue>{worker_only()?;self.inner.drive().await.map_err(failure)}
  pub fn terminal(&self)->Option<BrowserRecoveryReplyNativeTerminal>{self.inner.terminal().map(|inner|BrowserRecoveryReplyNativeTerminal{inner})}
  pub fn finish(&mut self,client:&BrowserCoreClient)->Result<BrowserRecoveryReplyStoredHandle,JsValue>{self.binding.check(client)?;let inner=self.inner.finish(&client.client).map_err(failure)?;self.binding.check(client)?;Ok(BrowserRecoveryReplyStoredHandle{inner,binding:self.binding.clone()})}
 }
 #[wasm_bindgen]
 impl BrowserRecoveryReplyStoredHandle {pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}}
}

#[cfg(feature="browser-metadata-prototype")]
#[path="browser_recovery_code_embed.rs"]
mod selected_code_embed;
