//! WebAssembly adapter for encrypted Task jobs in the shared browser Worker.
//! The core owns the job transaction and validation (feature.task-inline-embeds).
//! The callback relays requests over the existing page socket.
use super::*;
use openmates_sdk::Error;
use serde_json::Value;
use wasm_bindgen_futures::JsFuture;

#[wasm_bindgen]
impl BrowserCoreClient {
    /// Forward a server offer to the shared Rust job writer. The host callback
    /// returns the correlated socket frame and never receives any key material.
    pub async fn persist_task_jobs(
        &mut self,
        handle: &str,
        generation: f64,
        offer: &str,
        host_exchange: js_sys::Function,
    ) -> Result<String, JsValue> {
        if self.status(handle, generation)?.local_read_only {
            return Err(JsValue::from_str("local_session"));
        }
        if offer.len() > 256 * 1024 {
            return Err(JsValue::from_str("invalid_request"));
        }
        let offer =
            serde_json::from_str(offer).map_err(|_| JsValue::from_str("invalid_request"))?;
        let committed = self.client
            .run_browser_task_jobs(&offer, |request| {
                let host = &host_exchange;
                async move {
                    let request = serde_json::to_string(&request)?;
                    let invoked = host
                        .call1(&JsValue::UNDEFINED, &JsValue::from_str(&request))
                        .map_err(|_| Error::Offline)?;
                    let result = JsFuture::from(js_sys::Promise::resolve(&invoked))
                        .await
                        .map_err(|_| Error::Offline)?;
                    let frame = Zeroizing::new(result.as_string().ok_or(Error::Protocol)?);
                    if frame.len() > 1024 * 1024 {
                        return Err(Error::Protocol);
                    }
                    Ok(serde_json::from_str::<Value>(&frame)?)
                }
            })
            .await
            .map_err(|error| {
                JsValue::from_str(match error {
                    Error::Conflict => "conflict",
                    Error::Forbidden => "forbidden",
                    Error::Crypto => "crypto",
                    Error::Protocol => "protocol",
                    Error::Offline => "offline",
                    Error::Cancelled | Error::Authentication | Error::Expired => "session_expired",
                    _ => "task_job_unavailable",
                })
            })?;
        self.status(handle, generation)?;
        serde_json::to_string(&committed).map_err(|_| JsValue::from_str("protocol"))
    }
}
