//! Direct NAPI byte/public-wire adapters; Core alone owns ephemeral/key state.
use crate::{BindingError, remote_crypto::{RemoteHandshakeHandle,RemoteSessionHandle}};
use napi::bindgen_prelude::Uint8Array;
use napi_derive::napi;
fn error(value:BindingError)->napi::Error { napi::Error::new(napi::Status::GenericFailure,value.json()) }
#[napi(js_name="NativeRemoteHandshake")]
pub struct NodeRemoteHandshake { handle:RemoteHandshakeHandle }
#[napi]
impl NodeRemoteHandshake {
    #[napi(constructor)]
    pub fn new(key:Uint8Array,identity_json:String,role:String)->napi::Result<Self> {
        RemoteHandshakeHandle::new(key.as_ref(),identity_json.as_bytes(),&role).map(|handle|Self{handle}).map_err(error)
    }
    #[napi]
    pub fn handshake_json(&self)->napi::Result<String> {self.handle.handshake_json().map_err(error)}
    #[napi]
    pub fn finish(&self,remote_json:String)->napi::Result<NodeRemoteSession> {self.handle.finish(remote_json.as_bytes()).map(|handle|NodeRemoteSession{handle}).map_err(error)}
    #[napi]
    pub fn close(&self)->napi::Result<()> {self.handle.close().map_err(error)}
}
#[napi(js_name="NativeRemoteSession")]
pub struct NodeRemoteSession { handle:RemoteSessionHandle }
#[napi]
impl NodeRemoteSession {
    #[napi]
    pub fn seal(&self,request_id:String,plaintext:Uint8Array)->napi::Result<String> {self.handle.seal(&request_id,plaintext.as_ref()).map_err(error)}
    #[napi]
    pub fn open(&self,request_id:String,envelope_json:String)->napi::Result<Uint8Array> {
        let plaintext=self.handle.open(&request_id,envelope_json.as_bytes()).map_err(error)?;
        // This one copy is the caller-authorized byte output. The Core temporary
        // remains zeroizing through foreign-output construction; no key is copied.
        Ok(Uint8Array::new(plaintext.to_vec()))
    }
    #[napi]
    pub fn open_json_text(&self,request_id:String,envelope_json:String)->napi::Result<String> {self.handle.open_json_text(&request_id,envelope_json.as_bytes()).map_err(error)}
    #[napi]
    pub fn close(&self)->napi::Result<()> {self.handle.close().map_err(error)}
}
