//! Explicit default-off metadata-only prototype. No Client/key/crypto Root RPC.
use super::*;
use openmates_sdk::client::{BrowserMetadataBootstrap as CoreBootstrap,MetadataOpaqueStored as CoreStored};
#[wasm_bindgen]
pub struct BrowserMetadataBootstrap {inner:Option<CoreBootstrap>}
#[wasm_bindgen]
pub struct BrowserMetadataOpaqueStored {inner:CoreStored}
#[wasm_bindgen]
pub async fn capture_native_metadata_bootstrap(event:JsValue)->Result<BrowserMetadataBootstrap,JsValue>{
 worker_only()?;let inner=CoreBootstrap::capture_first(&event).await.map_err(|_|JsValue::from_str("unavailable"))?;
 Ok(BrowserMetadataBootstrap{inner:Some(inner)})
}
#[wasm_bindgen]
impl BrowserMetadataBootstrap {
 pub async fn store_selected(&mut self,chat:&str)->Result<BrowserMetadataOpaqueStored,JsValue>{
  worker_only()?;let original=self.inner.take().ok_or_else(||JsValue::from_str("unavailable"))?;
  let inner=original.store_selected(chat).await.map_err(|_|JsValue::from_str("unavailable"))?;Ok(BrowserMetadataOpaqueStored{inner})
 }
 pub async fn store_subchat(&mut self,chat:&str)->Result<BrowserMetadataOpaqueStored,JsValue>{
  worker_only()?;let original=self.inner.take().ok_or_else(||JsValue::from_str("unavailable"))?;
  let inner=original.store_subchat(chat).await.map_err(|_|JsValue::from_str("unavailable"))?;Ok(BrowserMetadataOpaqueStored{inner})
 }
}
#[wasm_bindgen]
impl BrowserMetadataOpaqueStored {pub async fn check_current(&self)->Result<(),JsValue>{worker_only()?;self.inner.check_current().await.map_err(|_|JsValue::from_str("unavailable"))}}
/// Native IndexedDB only. NEVER global Worker/Core HTTP settlement or a retry.
#[wasm_bindgen]
pub async fn close_native_metadata_io_only()->Result<(),JsValue>{worker_only()?;openmates_sdk::client::close_native_metadata_io_only().await.map_err(|_|JsValue::from_str("unavailable"))}
