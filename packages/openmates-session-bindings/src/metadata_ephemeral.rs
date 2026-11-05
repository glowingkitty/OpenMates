//! Direct explicit-credential metadata library boundary. No CLI/profile/key IO.
use crate::BindingError;
use openmates_sdk::{client::ephemeral_metadata::*,ClientIdentity,Error};
use serde::{Deserialize,Serialize};
use std::{collections::BTreeMap,sync::{Arc,Mutex}};
use tokio_util::sync::CancellationToken;
use zeroize::{Zeroize,Zeroizing};
type Result<T>=std::result::Result<T,BindingError>;
#[derive(Deserialize)]
#[serde(deny_unknown_fields,rename_all="camelCase")]
struct Input {api_url:String,app_url:String,session_id:String,cookies:BTreeMap<String,String>}
impl Drop for Input{fn drop(&mut self){self.session_id.zeroize();for value in self.cookies.values_mut(){value.zeroize();}}}
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
struct CredentialOutput<'a>{session_id:&'a str,cookies:&'a BTreeMap<String,String>}
fn credentials(value:MetadataCookieCredentials)->Result<String>{
    serde_json::to_string(&CredentialOutput{session_id:&value.session_id,cookies:&value.cookies}).map_err(|_|Error::Protocol.into())
}
#[derive(Clone)]
pub struct MetadataAuthenticationHandle {inner:Arc<PreparedMetadataAuthentication>,cancel:CancellationToken}
impl MetadataAuthenticationHandle {
    pub fn new(input_json:String,identity:ClientIdentity)->Result<Self>{
        let input_json=Zeroizing::new(input_json);
        if input_json.len()>1024*1024{return Err(Error::Invalid("Metadata credentials exceed the supported size.").into())}
        let mut input:Input=serde_json::from_str(&input_json).map_err(|_|Error::Invalid("Supply explicit metadata cookie credentials."))?;
        let inner=PreparedMetadataAuthentication::from_explicit_cookie(MetadataEndpointOptions{api_url:std::mem::take(&mut input.api_url),app_url:std::mem::take(&mut input.app_url),identity},
            MetadataCookieCredentials{session_id:Zeroizing::new(std::mem::take(&mut input.session_id)),cookies:std::mem::take(&mut input.cookies)})?;
        Ok(Self{inner:Arc::new(inner),cancel:CancellationToken::new()})
    }
    pub fn cancel(&self){self.cancel.cancel();}
    pub async fn cancel_and_drain(&self)->Result<()>{self.cancel();self.inner.wait_for_authentication_io().await.map_err(Into::into)}
    pub fn credential_snapshot_json(&self)->Result<String>{credentials(self.inner.credential_snapshot()?)}
    pub async fn authenticate(&self)->Result<MetadataClientHandle>{
        Ok(MetadataClientHandle{inner:Arc::new(self.inner.authenticate_existing(self.cancel.clone()).await?)})
    }
}
#[derive(Clone)]
pub struct MetadataClientHandle{inner:Arc<EphemeralMetadataClient>}
impl MetadataClientHandle {
    pub fn credential_snapshot_json(&self)->Result<String>{credentials(self.inner.credential_snapshot()?)}
    pub fn prepare_initial_sync(&self)->Result<MetadataStartupHandle>{
        let cancel=CancellationToken::new();let pending=self.inner.prepare_initial_sync(cancel.clone())?;
        Ok(MetadataStartupHandle{pending:Mutex::new(Some(pending)),control:MetadataStartupControl(Arc::new(CancelOnLastDrop(cancel)))})
    }
    pub async fn close(&self)->Result<()>{self.inner.close().await.map_err(Into::into)}
}
struct CancelOnLastDrop(CancellationToken);
impl Drop for CancelOnLastDrop{fn drop(&mut self){self.0.cancel();}}
#[derive(Clone)]
pub struct MetadataStartupControl(Arc<CancelOnLastDrop>);
impl MetadataStartupControl{pub fn cancel(&self){self.0.0.cancel();}}
pub struct MetadataStartupHandle{pending:Mutex<Option<PreparedEphemeralMetadataStartup>>,control:MetadataStartupControl}
impl MetadataStartupHandle {
    pub fn cancel(&self){self.control.cancel();}
    pub fn control(&self)->MetadataStartupControl{self.control.clone()}
    pub fn take(&self)->Result<PreparedEphemeralMetadataStartup>{self.pending.try_lock().map_err(|_|Error::Conflict)?.take().ok_or_else(||Error::Conflict.into())}
    pub async fn run(&self)->Result<MetadataSnapshotHandle>{
        let pending=self.take()?;let control=self.control();
        Ok(MetadataSnapshotHandle{inner:pending.run().await?,_control:control})
    }
}
pub struct MetadataSnapshotHandle{pub(crate) inner:EphemeralMetadataSnapshot,pub(crate) _control:MetadataStartupControl}
impl MetadataSnapshotHandle {
    pub fn cancel(&self){self.inner.cancel();}
    pub fn received_metadata_count(&self,client:&MetadataClientHandle)->Result<u32>{
        u32::try_from(self.inner.received_metadata_count(&client.inner)?).map_err(|_|Error::Protocol.into())
    }
}
