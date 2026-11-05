//! Thin owning-Worker bootstrap adapter only. No persistence/receipt policy,
//! generic effect callback, record JSON finish or native port field is exposed.
use super::*;
use openmates_sdk::client::{CapturedBrowserRecoveryPort,OriginalBrowserRecoveryPort};

#[wasm_bindgen]
pub struct BrowserRecoveryBootstrap {captured:Option<CapturedBrowserRecoveryPort>}
#[wasm_bindgen]
pub struct BrowserOriginalRecoveryPort {port:OriginalBrowserRecoveryPort,handle:String,generation:f64}
fn unavailable()->JsValue{JsValue::from_str("unavailable")}
fn failure(_:openmates_sdk::Error)->JsValue{JsValue::from_str("session_expired")}

/// Called ONLY with held FIRST valid native bootstrap event before normal RPC
/// installation/Worker escape. Never return this private resource to the Page.
#[wasm_bindgen]
pub fn capture_original_recovery_bootstrap(event:JsValue)->Result<Option<BrowserRecoveryBootstrap>,JsValue>{
    worker_only()?;
    CapturedBrowserRecoveryPort::capture_first(&event).map(|captured|captured.map(|captured|BrowserRecoveryBootstrap{captured:Some(captured)})).map_err(failure)
}
#[wasm_bindgen]
impl BrowserRecoveryBootstrap {
    /// Consumes the original first-bootstrap resource and actual prepared
    /// profile. Root binding occurs INSIDE this Rust constructor before either
    /// the restored Client or its status can escape to the Worker dispatcher.
    pub async fn restore_original(self,api_url:&str,app_origin:&str,session_id:&str,prepared:PreparedBrowserProfile)->Result<BrowserRecoveryRestoredClient,JsValue>{
        worker_only()?;
        let client=BrowserCoreClient::restore(api_url,app_origin,session_id,prepared).await?;
        self.bind_original_client(client)
    }
}
impl BrowserRecoveryBootstrap {
    fn bind_original_client(mut self,client:BrowserCoreClient)->Result<BrowserRecoveryRestoredClient,JsValue>{
        worker_only()?;
        let status=client.admitted_status()?;
        let captured=self.captured.take().ok_or_else(unavailable)?;
        let port=captured.bind_original(&client.client).map_err(failure)?;
        client.status(&status.handle,status.generation)?;
        Ok(BrowserRecoveryRestoredClient{client:Some(client),port:Some(BrowserOriginalRecoveryPort{port,handle:status.handle,generation:status.generation})})
    }
}
// Actual restore constructor integrates both original resources before either
// Client/status escapes. The ordinary restore_original method remains intact.
#[cfg(feature="browser-metadata-prototype")]
#[wasm_bindgen]
impl BrowserRecoveryBootstrap {
    pub async fn restore_original_with_startup_store(self,api_url:&str,app_origin:&str,session_id:&str,prepared:PreparedBrowserProfile,
        startup:crate::browser::BrowserInitialSyncStoreBootstrap)->Result<BrowserRecoveryRestoredClient,JsValue>{
        worker_only()?;
        self.restore_original(api_url,app_origin,session_id,prepared).await?.bind_startup_store(startup).await
    }
    /// Same original normal session response, consumed before Client/Root escape.
    /// No repeat auth, imported UserDTO, metadata-only context or raw response.
    pub async fn restore_original_from_first_session(self,receipt:crate::browser::BrowserFirstSessionReceiptHandle,
        startup:crate::browser::BrowserInitialSyncStoreBootstrap)->Result<BrowserRecoveryRestoredClient,JsValue>{
        worker_only()?;
        let client=receipt.restore_client(&startup).await?;
        self.bind_original_client(client)?.bind_startup_store(startup).await
    }
}
#[cfg(feature="browser-metadata-prototype")]
impl BrowserRecoveryRestoredClient {
    async fn bind_startup_store(mut self,mut startup:crate::browser::BrowserInitialSyncStoreBootstrap)->Result<Self,JsValue>{
        let captured=startup.inner.take().ok_or_else(unavailable)?;
        let client=self.client.as_mut().ok_or_else(unavailable)?;
        let bound=captured.bind_original(&client.client).await.map_err(failure)?;
        let status=client.admitted_status()?;bound.ensure_current(&client.client).map_err(failure)?;
        client.initial_sync_store=Some(bound);client.status(&status.handle,status.generation)?;Ok(self)
    }
}
impl BrowserOriginalRecoveryPort {
    /// Only native Core browser recovery handle code uses this accessor. Core
    /// start additionally checks actual Root+Ticket against SAME actual Client.
    pub(in crate::browser) fn original<'a>(&'a self,client:&BrowserCoreClient)->Result<&'a OriginalBrowserRecoveryPort,JsValue>{
        worker_only()?;client.status(&self.handle,self.generation)?;Ok(&self.port)
    }
}
#[wasm_bindgen]
impl BrowserOriginalRecoveryPort {
    pub async fn ready(&self)->Result<(),JsValue>{worker_only()?;self.port.ready().await.map_err(failure)}
    pub fn revoke(&self){self.port.revoke();}
    /// Caller owns the actual resource through this await, outside Rust/auth
    /// leases; failure never attests storage/native driver quiescence.
    pub async fn close_and_drain(&self)->Result<(),JsValue>{worker_only()?;self.port.close_and_drain().await.map_err(failure)}
}
impl Drop for BrowserOriginalRecoveryPort {fn drop(&mut self){self.port.revoke();}}

/// One-use extraction from the already-root-bound Rust restore result. These
/// methods grant no new authority; Port/Client retain their original resources.
#[wasm_bindgen]
pub struct BrowserRecoveryRestoredClient{client:Option<BrowserCoreClient>,port:Option<BrowserOriginalRecoveryPort>}
#[wasm_bindgen]
impl BrowserRecoveryRestoredClient{
 pub fn take_port(&mut self)->Result<BrowserOriginalRecoveryPort,JsValue>{if self.client.is_none(){return Err(unavailable())}self.port.take().ok_or_else(unavailable)}
 pub fn take_client(&mut self)->Result<BrowserCoreClient,JsValue>{if self.port.is_some(){return Err(unavailable())}self.client.take().ok_or_else(unavailable)}
}
impl Drop for BrowserRecoveryRestoredClient{fn drop(&mut self){if let Some(port)=&self.port{port.revoke();}if let Some(client)=&mut self.client{client.invalidate();}}}
