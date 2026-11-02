use crate::{BindingError,metadata_ephemeral::*};
use napi_derive::napi;
fn error(value:BindingError)->napi::Error{napi::Error::new(napi::Status::GenericFailure,value.json())}
#[napi(js_name="NativeMetadataAuthentication")]
pub struct NodeMetadataAuthentication{handle:MetadataAuthenticationHandle}
#[napi]
impl NodeMetadataAuthentication {
    #[napi(constructor)]
    pub fn new(input_json:String)->napi::Result<Self>{MetadataAuthenticationHandle::new(input_json,openmates_sdk::ClientIdentity::Npm).map(|handle|Self{handle}).map_err(error)}
    #[napi]
    pub async fn authenticate(&self)->napi::Result<NodeMetadataClient>{self.handle.authenticate().await.map(|handle|NodeMetadataClient{handle}).map_err(error)}
    #[napi]
    pub fn credential_snapshot_json(&self)->napi::Result<String>{self.handle.credential_snapshot_json().map_err(error)}
    #[napi]
    pub fn cancel(&self){self.handle.cancel();}
    #[napi]
    pub async fn cancel_and_drain(&self)->napi::Result<()>{self.handle.cancel_and_drain().await.map_err(error)}
}
#[napi(js_name="NativeEphemeralMetadataClient")]
pub struct NodeMetadataClient{handle:MetadataClientHandle}
#[napi]
impl NodeMetadataClient {
    #[napi]
    pub fn prepare_initial_sync(&self)->napi::Result<NodeMetadataStartup>{self.handle.prepare_initial_sync().map(|handle|NodeMetadataStartup{handle}).map_err(error)}
    #[napi]
    pub fn credential_snapshot_json(&self)->napi::Result<String>{self.handle.credential_snapshot_json().map_err(error)}
    #[napi]
    pub async fn close(&self)->napi::Result<()>{self.handle.close().await.map_err(error)}
}
#[napi(js_name="NativeEphemeralMetadataStartup")]
pub struct NodeMetadataStartup{handle:MetadataStartupHandle}
#[napi]
impl NodeMetadataStartup {
    #[napi]
    pub async fn run(&self)->napi::Result<NodeMetadataSnapshot>{
        let pending=self.handle.take().map_err(error)?;let control=self.handle.control();
        pending.run().await.map(|inner|NodeMetadataSnapshot{handle:MetadataSnapshotHandle{inner,_control:control}}).map_err(|e|error(e.into()))
    }
    #[napi]
    pub fn cancel(&self){self.handle.cancel();}
}
#[napi(js_name="NativeEphemeralMetadataSnapshot")]
pub struct NodeMetadataSnapshot{handle:MetadataSnapshotHandle}
#[napi]
impl NodeMetadataSnapshot {
    #[napi]
    pub fn received_metadata_count(&self,client:&NodeMetadataClient)->napi::Result<u32>{self.handle.received_metadata_count(&client.handle).map_err(error)}
    #[napi]
    pub fn cancel(&self){self.handle.cancel();}
}
