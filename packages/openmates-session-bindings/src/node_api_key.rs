//! Separate direct API-key ABI; no Cookie session or CLI fallback.
use crate::{ApiKeyBridge, ApiKeyRequest, ApiKeyOutput, BindingError};
use napi_derive::napi;
use std::sync::{Arc,Mutex};
use zeroize::Zeroizing;
fn error(e:BindingError)->napi::Error{napi::Error::new(napi::Status::GenericFailure,e.json())}
#[napi(js_name="NativeApiKeyClient")]
pub struct NodeApiKeyClient { bridge:ApiKeyBridge }
#[napi]
impl NodeApiKeyClient {
    #[napi(constructor)]
    pub fn new(options_json:String)->napi::Result<Self>{
        let encoded=Zeroizing::new(options_json);
        Ok(Self{bridge:ApiKeyBridge::with_identity(&encoded,openmates_sdk::ClientIdentity::Npm).map_err(error)?})
    }
    #[napi]
    pub fn request(&self)->napi::Result<NodeApiKeyRequest>{Ok(NodeApiKeyRequest{request:Arc::new(self.bridge.request().map_err(error)?)})}
    #[napi]
    pub fn cancel(&self)->napi::Result<()>{self.bridge.cancel().map_err(error)}
    #[napi]
    pub fn close(&self)->napi::Result<()>{self.bridge.close().map_err(error)}
}
#[napi(js_name="NativeApiKeyRequest")]
pub struct NodeApiKeyRequest {request:Arc<ApiKeyRequest>}
#[napi]
impl NodeApiKeyRequest {
    #[napi]
    pub async fn account_info_prepare(&self)->napi::Result<NodeApiKeyOutput>{
        Ok(NodeApiKeyOutput{output:Mutex::new(Some(self.request.account_info_prepare().await.map_err(error)?))})
    }
    #[napi(ts_return_type="Promise<NativeApiKeyOutput>")]
    pub fn run_skill_prepare<'env>(&self,env:&'env napi::Env,app:String,skill:String,input_json:String)->napi::Result<napi::bindgen_prelude::PromiseRaw<'env,NodeApiKeyOutput>>{
        let encoded=Zeroizing::new(input_json);
        let request=self.request.clone();
        env.spawn_future(async move{
            Ok(NodeApiKeyOutput{output:Mutex::new(Some(request.run_skill_prepare_guarded(app,skill,encoded).await.map_err(error)?))})
        })
    }
    #[napi(ts_return_type="Promise<NativeApiKeyOutput>")]
    pub fn list_project_sources_raw_prepare<'env>(&self, env: &'env napi::Env, project: String, filters_json: String) -> napi::Result<napi::bindgen_prelude::PromiseRaw<'env, NodeApiKeyOutput>> {
        let encoded = Zeroizing::new(filters_json);
        let request = self.request.clone();
        env.spawn_future(async move {
            Ok(NodeApiKeyOutput { output: Mutex::new(Some(request.list_project_sources_raw_prepare_guarded(project, encoded).await.map_err(error)?)) })
        })
    }
    #[napi]
    pub fn cancel(&self){self.request.cancel();}
}
impl Drop for NodeApiKeyRequest{fn drop(&mut self){self.request.cancel();}}
#[napi(js_name="NativeApiKeyOutput")]
pub struct NodeApiKeyOutput{output:Mutex<Option<ApiKeyOutput>>}
#[napi]
impl NodeApiKeyOutput {
    #[napi]
    pub fn release_json<'env>(&self,env:&'env napi::Env)->napi::Result<napi::JsString<'env>>{
        let output=self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take().ok_or_else(||error(openmates_sdk::Error::Cancelled.into()))?;
        output.encode_with(|text|env.create_string(text).map_err(|_|openmates_sdk::Error::Protocol.into())).map_err(error)
    }
    #[napi]
    pub fn discard(&self)->napi::Result<()>{self.output.try_lock().map_err(|_|error(openmates_sdk::Error::Conflict.into()))?.take();Ok(())}
}
