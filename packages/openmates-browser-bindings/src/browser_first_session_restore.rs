//! Feature-only same owning Worker normal session read and opaque restore.
//! UI response JSON is data; only the retained native Rust receipt can restore.
use super::*;
use openmates_sdk::client::{PreparedBrowserFirstSession,BrowserFirstSessionControl,BrowserFirstSessionReceipt};
fn first_failure(error:openmates_sdk::Error)->JsValue{JsValue::from_str(match error{
    openmates_sdk::Error::Cancelled=>"cancelled",openmates_sdk::Error::Expired|openmates_sdk::Error::Authentication=>"session_expired",
    openmates_sdk::Error::Offline=>"offline",openmates_sdk::Error::Protocol=>"invalid_request",_=>"unavailable",
})}
#[wasm_bindgen]
pub struct BrowserPreparedFirstSession {inner:Option<PreparedBrowserFirstSession>,control:BrowserFirstSessionControl}
#[wasm_bindgen]
pub struct BrowserFirstSessionControlHandle {inner:BrowserFirstSessionControl}
#[wasm_bindgen]
impl BrowserFirstSessionControlHandle {
    pub fn cancel(&self){self.inner.cancel();}
    pub fn ensure_current(&self)->Result<(),JsValue>{worker_only()?;self.inner.ensure_current().map_err(first_failure)}
}
#[wasm_bindgen]
impl BrowserPreparedFirstSession {
    pub fn control(&self)->BrowserFirstSessionControlHandle{BrowserFirstSessionControlHandle{inner:self.control.clone()}}
    pub fn restrict_remaining_budget_ms(&mut self,remaining:f64)->Result<(),JsValue>{
        worker_only()?;
        if !remaining.is_finite()||remaining<0.0||remaining>10000.0||remaining.fract()!=0.0{return Err(JsValue::from_str("invalid_request"))}
        self.inner.as_mut().ok_or_else(||JsValue::from_str("unavailable"))?.restrict_remaining_budget(std::time::Duration::from_millis(remaining as u64)).map_err(first_failure)
    }
    pub async fn wait(mut self)->Result<BrowserFirstSessionReceiptHandle,JsValue>{
        worker_only()?;let pending=self.inner.take().ok_or_else(||JsValue::from_str("unavailable"))?;
        Ok(BrowserFirstSessionReceiptHandle{inner:Some(pending.wait().await.map_err(first_failure)?)})
    }
}
#[wasm_bindgen]
pub struct BrowserFirstSessionReceiptHandle {inner:Option<BrowserFirstSessionReceipt>}
#[wasm_bindgen]
impl BrowserFirstSessionReceiptHandle {
    pub fn observed_http_status(&self)->Result<Option<u16>,JsValue>{
        worker_only()?;Ok(self.inner.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?.observed_http_status())
    }
    pub fn response_json(&self)->Result<String,JsValue>{
        worker_only()?;let mut data=self.inner.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?.response_json().map_err(first_failure)?;
        Ok(std::mem::take(&mut *data))
    }
    pub fn control(&self)->Result<BrowserFirstSessionControlHandle,JsValue>{
        worker_only()?;Ok(BrowserFirstSessionControlHandle{inner:self.inner.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?.control()})
    }
}
impl BrowserFirstSessionReceiptHandle {
    /// Internal typed consumer only; original Root/store bind precedes escape.
    pub(in crate::browser) async fn restore_client(mut self,store:&BrowserInitialSyncStoreBootstrap)->Result<BrowserCoreClient,JsValue>{
        worker_only()?;let original=store.inner.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
        let client=self.inner.take().ok_or_else(||JsValue::from_str("unavailable"))?.restore_with_original_store(original).await.map_err(first_failure)?;
        Ok(BrowserCoreClient{client,handle:uuid::Uuid::new_v4().to_string(),cache:Default::default(),initial_sync_store:None})
    }
}
#[wasm_bindgen]
impl BrowserCoreClient {
    /// Genuine original native configuration/profile, separate DATA-only type.
    /// No CryptoKey argument and no restore/admission conversion is exported.
    pub fn prepare_first_session_data_original(device_signals_json:&str,store:&BrowserInitialSyncStoreBootstrap)->Result<BrowserPreparedFirstSessionData,JsValue>{
        worker_only()?;if device_signals_json.len()>16*1024{return Err(JsValue::from_str("invalid_request"))}
        let signals=serde_json::from_str(device_signals_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let original=store.inner.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
        let inner=original.prepare_first_session_data_original(signals,tokio_util::sync::CancellationToken::new()).map_err(first_failure)?;
        let control=inner.control();Ok(BrowserPreparedFirstSessionData{inner:Some(inner),control})
    }
    /// Original configured Worker/native store is the sole endpoint producer.
    /// Borrow before HTTP; restore later consumes this SAME bootstrap/receipt.
    pub fn prepare_first_session_original(prepared:PreparedBrowserProfile,device_signals_json:&str,store:&BrowserInitialSyncStoreBootstrap)->Result<BrowserPreparedFirstSession,JsValue>{
        worker_only()?;if device_signals_json.len()>16*1024{return Err(JsValue::from_str("invalid_request"))}
        let signals=serde_json::from_str(device_signals_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let original=store.inner.as_ref().ok_or_else(||JsValue::from_str("unavailable"))?;
        let inner=original.prepare_first_session_original(prepared.profile,signals,tokio_util::sync::CancellationToken::new()).map_err(first_failure)?;
        let control=inner.control();Ok(BrowserPreparedFirstSession{inner:Some(inner),control})
    }
    /// Called for the actual NORMAL session read, under its existing auth lock.
    /// There is no accepted response/status/validated flag argument.
    pub fn prepare_first_session(api_url:&str,app_origin:&str,session_id:&str,prepared:PreparedBrowserProfile,device_signals_json:&str)->Result<BrowserPreparedFirstSession,JsValue>{
        worker_only()?;if device_signals_json.len()>16*1024{return Err(JsValue::from_str("invalid_request"))}
        let signals=serde_json::from_str(device_signals_json).map_err(|_|JsValue::from_str("invalid_request"))?;
        let inner=Client::prepare_browser_first_session(api_url,app_origin,session_id,prepared.profile,signals,tokio_util::sync::CancellationToken::new()).map_err(first_failure)?;
        let control=inner.control();Ok(BrowserPreparedFirstSession{inner:Some(inner),control})
    }
}

#[wasm_bindgen]
pub struct BrowserPreparedFirstSessionData {inner:Option<openmates_sdk::client::PreparedBrowserFirstSessionData>,control:openmates_sdk::client::BrowserFirstSessionDataControl}
#[wasm_bindgen]
pub struct BrowserFirstSessionDataControlHandle {inner:openmates_sdk::client::BrowserFirstSessionDataControl}
#[wasm_bindgen]
impl BrowserFirstSessionDataControlHandle {
    pub fn cancel(&self){self.inner.cancel();}
    pub fn ensure_current(&self)->Result<(),JsValue>{worker_only()?;self.inner.ensure_current().map_err(first_failure)}
}
#[wasm_bindgen]
impl BrowserPreparedFirstSessionData {
    pub fn control(&self)->BrowserFirstSessionDataControlHandle{BrowserFirstSessionDataControlHandle{inner:self.control.clone()}}
    pub fn restrict_remaining_budget_ms(&mut self,remaining:f64)->Result<(),JsValue>{
        worker_only()?;if !remaining.is_finite()||remaining<0.0||remaining>10000.0||remaining.fract()!=0.0{return Err(JsValue::from_str("invalid_request"))}
        self.inner.as_mut().ok_or_else(||JsValue::from_str("unavailable"))?.restrict_remaining_budget(std::time::Duration::from_millis(remaining as u64)).map_err(first_failure)
    }
    pub async fn wait(mut self)->Result<BrowserFirstSessionDataHandle,JsValue>{
        worker_only()?;let pending=self.inner.take().ok_or_else(||JsValue::from_str("unavailable"))?;
        Ok(BrowserFirstSessionDataHandle{inner:pending.wait().await.map_err(first_failure)?})
    }
}
#[wasm_bindgen]
pub struct BrowserFirstSessionDataHandle {inner:openmates_sdk::client::BrowserFirstSessionData}
#[wasm_bindgen]
impl BrowserFirstSessionDataHandle {
    pub fn control(&self)->Result<BrowserFirstSessionDataControlHandle,JsValue>{worker_only()?;Ok(BrowserFirstSessionDataControlHandle{inner:self.inner.control()})}
    pub fn observed_http_status(&self)->Result<Option<u16>,JsValue>{worker_only()?;Ok(self.inner.observed_http_status())}
    pub fn response_json(&self)->Result<String,JsValue>{
        worker_only()?;let mut data=self.inner.response_json().map_err(first_failure)?;Ok(std::mem::take(&mut *data))
    }
}
