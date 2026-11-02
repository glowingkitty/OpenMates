//! Worker-only adapter for actual shared draft resources. No JS policy/key IO.
use super::*;
use openmates_sdk::client::{BrowserDraftControl, BrowserDraftPublication, BrowserDraftWrite};
#[wasm_bindgen]
pub struct BrowserDraftWriteHandle {
    resource: BrowserDraftWrite,
    handle: String,
    generation: f64,
    owner: String,
}
#[wasm_bindgen]
pub struct BrowserDraftPublicationHandle {
    resource: BrowserDraftPublication,
    handle: String,
    generation: f64,
    owner: String,
}
#[wasm_bindgen]
impl BrowserDraftPublicationHandle {
    pub fn take(self, client: &BrowserCoreClient) -> Result<String, JsValue> {
        let status = client.status(&self.handle, self.generation)?;
        if status.principal() != self.owner {
            return Err(JsValue::from_str("session_expired"));
        }
        self.resource
            .take(&client.client)
            .map(|s| s.to_string())
            .map_err(|_| JsValue::from_str("session_expired"))
    }
}
#[wasm_bindgen]
pub struct BrowserDraftControlHandle {
    resource: BrowserDraftControl,
}
#[wasm_bindgen]
impl BrowserDraftControlHandle {
    pub fn cancel(&self) {
        self.resource.cancel();
    }
}
#[wasm_bindgen]
impl BrowserDraftWriteHandle {
    pub fn local_result(&self, client: &BrowserCoreClient) -> Result<String, JsValue> {
        let status = client.status(&self.handle, self.generation)?;
        if status.principal() != self.owner {
            return Err(JsValue::from_str("session_expired"));
        }
        self.resource
            .local_result(&client.client)
            .map(|s| s.to_string())
            .map_err(|_| JsValue::from_str("unavailable"))
    }
    pub fn control(&self) -> BrowserDraftControlHandle {
        BrowserDraftControlHandle {
            resource: self.resource.control(),
        }
    }
    pub async fn synchronize(
        self,
        client: &mut BrowserCoreClient,
        effect: js_sys::Function,
    ) -> Result<BrowserDraftPublicationHandle, JsValue> {
        let status = client.status(&self.handle, self.generation)?;
        if status.principal() != self.owner {
            return Err(JsValue::from_str("session_expired"));
        }
        // The core resource holds original root/key/owner/child authority. JS callback
        // labels and status copies cannot create a local or server draft permission.
        let output = self
            .resource
            .synchronize(&mut client.client, |plan| {
                let effect = effect.clone();
                async move {
                    let value = effect
                        .call1(&JsValue::NULL, &JsValue::from_str(&plan))
                        .map_err(|_| openmates_sdk::Error::Offline)?;
                    let reply =
                        wasm_bindgen_futures::JsFuture::from(js_sys::Promise::resolve(&value))
                            .await
                            .map_err(|_| openmates_sdk::Error::Offline)?;
                    reply
                        .as_string()
                        .filter(|s| s.len() <= 2 * 1024 * 1024)
                        .ok_or(openmates_sdk::Error::Protocol)
                }
            })
            .await
            .map_err(|_| JsValue::from_str("unavailable"))?;
        let status = client.status(&self.handle, self.generation)?;
        if status.principal() != self.owner {
            return Err(JsValue::from_str("session_expired"));
        }
        Ok(BrowserDraftPublicationHandle {
            resource: output,
            handle: self.handle,
            generation: self.generation,
            owner: self.owner,
        })
    }
}
#[wasm_bindgen]
impl BrowserCoreClient {
    pub async fn prepare_local_draft(
        &mut self,
        handle: &str,
        generation: f64,
        owner: &str,
        chat_id: &str,
        markdown: String,
        scope: &str,
        now: f64,
        effect: js_sys::Function,
    ) -> Result<BrowserDraftWriteHandle, JsValue> {
        let markdown = Zeroizing::new(markdown);
        let status = self.status(handle, generation)?;
        if status.principal() != owner
            || !now.is_finite()
            || now.fract() != 0.0
            || now < 0.0
            || now > 9_007_199_254_740_991.0
        {
            return Err(JsValue::from_str("invalid_request"));
        }
        let resource = self
            .client
            .prepare_browser_draft_with_io_json(
                owner,
                chat_id,
                &markdown,
                scope,
                now as u64,
                |plan| {
                    let effect = effect.clone();
                    async move {
                        let value = effect
                            .call1(&JsValue::NULL, &JsValue::from_str(&plan))
                            .map_err(|_| openmates_sdk::Error::Offline)?;
                        let reply =
                            wasm_bindgen_futures::JsFuture::from(js_sys::Promise::resolve(&value))
                                .await
                                .map_err(|_| openmates_sdk::Error::Offline)?;
                        reply
                            .as_string()
                            .filter(|s| s.len() <= 2 * 1024 * 1024)
                            .ok_or(openmates_sdk::Error::Protocol)
                    }
                },
            )
            .await
            .map_err(|_| JsValue::from_str("unavailable"))?;
        let status = self.status(handle, generation)?;
        if status.principal() != owner {
            return Err(JsValue::from_str("session_expired"));
        }
        Ok(BrowserDraftWriteHandle {
            resource,
            handle: handle.into(),
            generation,
            owner: owner.into(),
        })
    }
    pub async fn restore_local_draft(
        &mut self,
        handle: &str,
        generation: f64,
        owner: &str,
        chat_id: &str,
        scope: &str,
        effect: js_sys::Function,
    ) -> Result<BrowserDraftPublicationHandle, JsValue> {
        let status = self.status(handle, generation)?;
        if status.principal() != owner {
            return Err(JsValue::from_str("session_expired"));
        }
        let output = self
            .client
            .restore_browser_draft_with_io_json(owner, chat_id, scope, |plan| {
                let effect = effect.clone();
                async move {
                    let value = effect
                        .call1(&JsValue::NULL, &JsValue::from_str(&plan))
                        .map_err(|_| openmates_sdk::Error::Offline)?;
                    let reply =
                        wasm_bindgen_futures::JsFuture::from(js_sys::Promise::resolve(&value))
                            .await
                            .map_err(|_| openmates_sdk::Error::Offline)?;
                    reply
                        .as_string()
                        .filter(|s| s.len() <= 2 * 1024 * 1024)
                        .ok_or(openmates_sdk::Error::Protocol)
                }
            })
            .await
            .map_err(|_| JsValue::from_str("unavailable"))?;
        let status = self.status(handle, generation)?;
        if status.principal() != owner {
            return Err(JsValue::from_str("session_expired"));
        }
        Ok(BrowserDraftPublicationHandle {
            resource: output,
            handle: handle.into(),
            generation,
            owner: owner.into(),
        })
    }
}
