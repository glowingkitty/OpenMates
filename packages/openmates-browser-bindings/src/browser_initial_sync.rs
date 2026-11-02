//! Thin explicit initial-sync adapter for an actual owning-Worker cache monitor.
//! No selected-read/default path selects this operation; no legacy-hint boolean.
use super::*;
use openmates_sdk::client::{PreparedInitialSync,InitialSyncRead,InitialSyncMetadataBatch,InitialSyncControl};
#[derive(Clone)]
struct Binding {handle:String,generation:f64,owner:String}
impl Binding {
    fn check(&self,client:&BrowserCoreClient)->Result<(),JsValue>{
        worker_only()?;let status=client.status(&self.handle,self.generation)?;
        if status.principal()!=self.owner{return Err(JsValue::from_str("session_expired"))}Ok(())
    }
}
fn failure(error:openmates_sdk::Error)->JsValue{JsValue::from_str(match error{
    openmates_sdk::Error::Cancelled|openmates_sdk::Error::Expired|openmates_sdk::Error::Authentication|openmates_sdk::Error::Forbidden=>"session_expired",
    _=>"chat_unavailable",
})}
#[wasm_bindgen]
pub struct BrowserInitialSyncControl {inner:InitialSyncControl,binding:Binding}
#[wasm_bindgen]
impl BrowserInitialSyncControl {
    pub fn cancel(&self){self.inner.cancel();}
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
}
/// Actual initial-sync IO handle. drive borrows no mutable Client/auth lane.
#[wasm_bindgen]
pub struct BrowserInitialSyncHandle {
    pending:Option<PreparedInitialSync>,read:Option<InitialSyncRead>,control:InitialSyncControl,binding:Binding,
}
#[wasm_bindgen]
impl BrowserInitialSyncHandle {
    pub fn control(&self)->Result<BrowserInitialSyncControl,JsValue>{worker_only()?;Ok(BrowserInitialSyncControl{inner:self.control.clone(),binding:self.binding.clone()})}
    pub async fn drive(&mut self)->Result<(),JsValue>{
        worker_only()?;
        let pending=self.pending.take().ok_or_else(||JsValue::from_str("unavailable"))?;
        // Await actual original actor IO; Err/Drop does not assert drain/ACK.
        self.read=Some(pending.wait().await.map_err(failure)?);Ok(())
    }
    pub fn retain(&mut self,client:&BrowserCoreClient)->Result<BrowserInitialSyncMetadata,JsValue>{
        self.binding.check(client)?;
        let read=self.read.take().ok_or_else(||JsValue::from_str("unavailable"))?;
        let inner=read.retain(&client.client).map_err(failure)?;self.binding.check(client)?;
        Ok(BrowserInitialSyncMetadata{inner,binding:self.binding.clone()})
    }
}
/// Opaque original-source DATA only. No native-store, key or public-row getter.
/// Native per-row persistence and whole-hint completion remain separate work.
#[wasm_bindgen]
pub struct BrowserInitialSyncMetadata {inner:InitialSyncMetadataBatch,binding:Binding}
#[wasm_bindgen]
impl BrowserInitialSyncMetadata {
    pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
    pub fn received_metadata_count(&self,client:&BrowserCoreClient)->Result<u32,JsValue>{
        self.ensure_current(client)?;u32::try_from(self.inner.received_metadata_count(&client.client).map_err(failure)?).map_err(|_|JsValue::from_str("unavailable"))
    }
    pub fn cancel(&self){self.inner.cancel();}
}
#[wasm_bindgen]
impl BrowserCoreClient {
    /// UI selects the initial-sync operation. Authentication/owner/backend and
    /// connection admission come only from actual Rust Client/monitor resources.
    pub fn begin_initial_sync(&mut self,handle:&str,generation:f64,owner:&str,monitor_id:&str)->Result<BrowserInitialSyncHandle,JsValue>{
        worker_only()?;
        let monitor=cache_operations::owned_read_monitor(self,handle,generation,owner,monitor_id)?;
        let binding=Binding{handle:handle.into(),generation,owner:owner.into()};binding.check(self)?;
        let pending=self.client.prepare_initial_sync(monitor,tokio_util::sync::CancellationToken::new()).map_err(failure)?;
        let control=pending.control();binding.check(self)?;
        Ok(BrowserInitialSyncHandle{pending:Some(pending),read:None,control,binding})
    }
}

#[cfg(feature="browser-metadata-prototype")]
mod native_store {
    use super::*;
    use openmates_sdk::client::{CapturedInitialSyncStore,StartupMetadataStoreDriver,StartupMetadataStored,StartupMetadataNativeTerminal};
    #[wasm_bindgen]
    pub struct BrowserInitialSyncStoreBootstrap {pub(in crate::browser) inner:Option<CapturedInitialSyncStore>}
    #[wasm_bindgen]
    pub fn capture_initial_sync_store(event:JsValue)->Result<BrowserInitialSyncStoreBootstrap,JsValue>{
        worker_only()?;let inner=CapturedInitialSyncStore::capture_first(&event).map_err(failure)?;
        Ok(BrowserInitialSyncStoreBootstrap{inner:Some(inner)})
    }
    #[wasm_bindgen]
    pub struct BrowserInitialSyncStoreDriver {inner:StartupMetadataStoreDriver,binding:Binding}
    #[wasm_bindgen]
    pub struct BrowserInitialSyncNativeTerminal {inner:StartupMetadataNativeTerminal}
    #[wasm_bindgen]
    impl BrowserInitialSyncNativeTerminal {pub fn native_io_quiescent(&self)->bool{self.inner.native_io_quiescent()}}
    #[wasm_bindgen]
    impl BrowserInitialSyncStoreDriver {
        pub fn control(&self)->Result<BrowserInitialSyncControl,JsValue>{worker_only()?;Ok(BrowserInitialSyncControl{inner:self.inner.control(),binding:self.binding.clone()})}
        pub fn terminal(&self)->Option<BrowserInitialSyncNativeTerminal>{self.inner.terminal().map(|inner|BrowserInitialSyncNativeTerminal{inner})}
        pub async fn drive(&mut self)->Result<(),JsValue>{worker_only()?;self.inner.drive().await.map_err(failure)}
        pub fn finish(&mut self,client:&BrowserCoreClient)->Result<BrowserInitialSyncStored,JsValue>{
            self.binding.check(client)?;let inner=self.inner.finish(&client.client).map_err(failure)?;self.binding.check(client)?;
            Ok(BrowserInitialSyncStored{inner,binding:self.binding.clone()})
        }
    }
    #[wasm_bindgen]
    pub struct BrowserInitialSyncStored {inner:StartupMetadataStored,binding:Binding}
    #[wasm_bindgen]
    impl BrowserInitialSyncStored {
        pub fn ensure_current(&self,client:&BrowserCoreClient)->Result<(),JsValue>{self.binding.check(client)?;self.inner.ensure_current(&client.client).map_err(failure)}
        pub fn stored_metadata_count(&self,client:&BrowserCoreClient)->Result<u32,JsValue>{self.ensure_current(client)?;u32::try_from(self.inner.stored_metadata_count(&client.client).map_err(failure)?).map_err(|_|JsValue::from_str("unavailable"))}
    }
    #[wasm_bindgen]
    impl BrowserInitialSyncMetadata {
        pub fn begin_store(self,client:&BrowserCoreClient)->Result<BrowserInitialSyncStoreDriver,JsValue>{
            self.binding.check(client)?;
            let store=client.initial_sync_store.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
            let inner=store.begin(&client.client,self.inner).map_err(failure)?;self.binding.check(client)?;
            Ok(BrowserInitialSyncStoreDriver{inner,binding:self.binding})
        }
    }
}
#[cfg(feature="browser-metadata-prototype")]
pub use native_store::{BrowserInitialSyncStoreBootstrap,BrowserInitialSyncStoreDriver,BrowserInitialSyncNativeTerminal,BrowserInitialSyncStored,capture_initial_sync_store};
