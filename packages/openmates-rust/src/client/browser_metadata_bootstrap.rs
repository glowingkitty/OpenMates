//! Default-off prototype: first-party opaque storage, independent of Master.
//! No crypto restore, private publication, recovery ledger or ACK conversion.
use crate::error::{Error,Result};
use crate::client::plaintext::Plain;
use crate::platform::browser_metadata_native::{NativeMetadataContext,NativeMetadataProfileObservation};
use serde_json::{Value,json};
use std::sync::{Arc,atomic::{AtomicBool,Ordering}};
use zeroize::Zeroizing;
use super::metadata_bootstrap_policy as policy;
const MAX_PACKET:usize=4*1024*1024;
const MAX_HTTP:usize=256*1024;
struct Original {
    context:NativeMetadataContext,
    profile:NativeMetadataProfileObservation,
    owner:Zeroizing<String>,
    denied:AtomicBool,
    client_scope:Option<Arc<crate::client::owned_operation::OwnedOperationScope>>,
}
impl Original {
    fn check(&self)->Result<()> {
        self.context.check_negative()?;
        self.profile.check_for(&self.context)?;
        if self.denied.load(Ordering::Acquire){return Err(Error::Cancelled)}
        if let Some(scope)=&self.client_scope{scope.observer().check_release()?;}
        Ok(())
    }
}
/// Nonconstructible, nonserializable Core-issued immutable native effect.
/// Native delivery still must prove its actual original request/transactions.
pub struct MetadataNativeIoTicket {
    original:Arc<Original>,
    operation:Zeroizing<String>,
    effect:Plain<Value>,
    dispatched:AtomicBool,
    source:Option<crate::client::InitialSyncControl>,
    recovery_source:Option<std::rc::Rc<crate::client::BrowserOriginalHintRecoveryProgress>>,
    embed_source:Option<std::rc::Rc<crate::client::saved_embed::SavedEmbedRead>>,
}
impl MetadataNativeIoTicket {
    pub(crate) fn is_recovered_reply(&self)->bool{self.recovery_source.is_some()&&self.effect["kind"]=="openmates-recovery-reply-native-io-v1"}
    pub(crate) fn is_main_code_embed(&self)->bool{self.recovery_source.is_some()&&self.embed_source.is_some()&&self.effect["kind"]=="openmates-main-code-embed-native-io-v1"}
    pub(crate) fn packet_limit(&self)->usize{if self.is_recovered_reply()||self.is_main_code_embed(){4*crate::client::transport::MAX_BODY}else{MAX_PACKET}}
    pub(crate) fn check_original_negative(&self)->Result<()> {self.original.check()?;if let Some(source)=&self.source{source.check_original_negative()?;}if let Some(source)=&self.recovery_source{source.metadata_finalize_negative()?;}if let Some(source)=&self.embed_source{source.main_native_negative()?;}Ok(())}
    pub(crate) fn check_for_context(&self,context:&NativeMetadataContext)->Result<()> {
        self.check_original_negative()?;
        if !self.original.context.same_original(context){return Err(Error::Forbidden)}Ok(())
    }
    pub(crate) fn operation_id(&self)->&str {&self.operation}
    pub(crate) fn effect_json(&self)->Result<String> {
        self.check_original_negative()?;
        let encoded=serde_json::to_string(&*self.effect)?;
        if encoded.len()>self.packet_limit(){return Err(Error::Protocol)}Ok(encoded)
    }
    pub(crate) fn claim_dispatch(&self)->Result<()> {
        self.check_original_negative()?;
        self.dispatched.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;Ok(())
    }
}
/// Negative-only closure of this prototype's actual native IDB resources.
/// This MUST NOT be used as Core HTTP/global Worker settlement or a close ACK.
/// Unknown Fetch failure/drop remains held and cannot rearm the original owner.
pub async fn close_native_metadata_io_only()->Result<()> {
    NativeMetadataContext::close_captured().await
}
// Nonserializable source capability, born only after the matched actual fixed
// HTTP response under this SAME native/profile/auth resource. The parent UUID
// remains navigation DATA and cannot authorize any operation on that parent.
struct CapturedSubchatMetadata {
    original:Arc<Original>,chat:Zeroizing<String>,parent:Zeroizing<String>,source:Plain<Value>,
}
impl CapturedSubchatMetadata {
    fn check(&self,original:&Arc<Original>)->Result<()> {
        if !Arc::ptr_eq(&self.original,original){return Err(Error::Forbidden)}
        self.original.check()?;
        if policy::subchat_parent(&self.source,&self.chat,&self.original.owner)?!=self.parent.as_str(){return Err(Error::Conflict)}
        Ok(())
    }
}
/// One authentic selected metadata row. Parent and child paths are explicit;
/// no generic DTO/source constructor or parent access/key grant exists.
/// Consuming this resource prevents retry/rearm after partial or unknown work.
pub struct BrowserMetadataBootstrap {original:Arc<Original>}
/// Only exact opaque storage; contains no rows and cannot upgrade crypto roots.
pub struct MetadataOpaqueStored {original:Arc<Original>}
impl MetadataOpaqueStored {pub async fn check_current(&self)->Result<()> {self.original.check()?;self.original.context.recheck_profile_owner().await?;self.original.check()}}
// On cancellation/drop/error the entire original stays denied. This guard never
// declares native/HTTP drain; actual native pending owns its started resources.
struct Attempt {original:Arc<Original>,complete:bool}
impl Drop for Attempt {fn drop(&mut self){if !self.complete{self.original.denied.store(true,Ordering::Release);}}}
async fn fixed_post(context:&NativeMetadataContext,owner:&str,path:&str,body:Value)->Result<Plain<Value>> {
    context.check_negative()?;
    if !matches!(path,"/v1/auth/session"|"/v1/chats/metadata/batch"){return Err(Error::Forbidden)}
    let(api,app,_)=context.selectors();
    // The opaque context, not this URL/string, owns configured backend authority.
    // Match deployed getApiEndpoint exactly: `${getApiUrl()}${path}`. Do not
    // reuse the deliberately stricter native SDK URL policy here, strip a
    // configured prefix/trailing slash, or accept a frame-selected backend.
    let url=policy::configured_endpoint(api,path)?;
    let request=crate::platform::http::browser_credentials(crate::platform::http::client()?.post(url)
        .header("Accept","application/json").header("X-OpenMates-SDK","rust")
        .header("Origin",app).header("X-OpenMates-Expected-Principal",owner).json(&body),true).fetch_cache_no_store();
    // Await the actual response/body. Cancellation cannot synthesize a completed
    // response or a transport drain receipt. Browser manages Cookie rotation.
    let mut response=request.send().await?;
    let status=response.status().as_u16();
    context.check_negative()?;
    let mut bytes=Zeroizing::new(Vec::with_capacity(MAX_HTTP));
    if response.content_length().is_some_and(|n|n>MAX_HTTP as u64){return Err(Error::Protocol)}
    while let Some(chunk)=response.chunk().await? {
        let chunk=Zeroizing::new(chunk);
        context.check_negative()?;
        if bytes.len().checked_add(chunk.len()).is_none_or(|n|n>MAX_HTTP){return Err(Error::Protocol)}
        bytes.extend_from_slice(&chunk);
    }
    context.check_negative()?;
    match status {200=>{},401=>return Err(Error::Expired),403=>return Err(Error::Forbidden),404=>return Err(Error::Forbidden),_=>return Err(Error::Offline)}
    Ok(Plain::new(serde_json::from_slice(&bytes)?))
}
fn validate_auth(value:&Value,owner:&str)->Result<()> {
    if value["success"]!=true||value["user"]["id"].as_str()!=Some(owner){return Err(Error::Authentication)}
    let caps=value["client_security_capabilities"].as_array().ok_or(Error::Unavailable{code:"browser_owner_consistency_unsupported",reason:"BROWSER_OWNER_CONSISTENCY_REQUIRES_SERVER_CAPABILITIES"})?;
    if caps.len()>16||!caps.iter().all(|v|v.as_str().is_some_and(|v|v.len()<=64))||! ["expected-principal-v1","ws-dual-principal-v1"].iter().all(|cap|caps.iter().any(|v|v.as_str()==Some(*cap))){return Err(Error::Unavailable{code:"browser_owner_consistency_unsupported",reason:"BROWSER_OWNER_CONSISTENCY_REQUIRES_SERVER_CAPABILITIES"})}Ok(())
}
impl BrowserMetadataBootstrap {
    /// Must receive the actual first native owning Worker Event; a copied frame
    /// cannot construct the native context or its configured-backend resource.
    pub async fn capture_first(event:&wasm_bindgen::JsValue)->Result<Self> {
        let context=NativeMetadataContext::capture_first(event)?;
        let profile=context.profile_read().await?;
        profile.check_for(&context)?;
        let owner=Zeroizing::new(profile.owner_id().to_owned());
        if !uuid::Uuid::parse_str(&owner).is_ok_and(|id|id.to_string()==owner.as_str()){return Err(Error::Authentication)}
        let(_,_,session)=context.selectors();
        uuid::Uuid::parse_str(session).map_err(|_|Error::Authentication)?;
        let response=fixed_post(&context,&owner,"/v1/auth/session",json!({"session_id":session})).await?;
        profile.check_for(&context)?;
        validate_auth(&response,&owner)?;
        // Response may contain ws_token/private user fields: the wiping owner
        // drops them here. No token, Master or Client Session is constructed.
        Ok(Self{original:Arc::new(Original{context,profile,owner,denied:AtomicBool::new(false),client_scope:None})})
    }
    pub async fn store_selected(self,chat:&str)->Result<MetadataOpaqueStored> {
        self.original.check()?;
        if !uuid::Uuid::parse_str(chat).is_ok_and(|id|id.to_string()==chat){return Err(Error::Protocol)}
        let mut attempt=Attempt{original:self.original.clone(),complete:false};
        let response=fixed_post(&self.original.context,&self.original.owner,"/v1/chats/metadata/batch",json!({"chat_ids":[chat],"include_read_details":true})).await?;
        self.original.check()?;
        let rows=response["chats"].as_array().ok_or(Error::Protocol)?;
        if rows.len()!=1||rows[0]["id"].as_str()!=Some(chat){return Err(Error::Forbidden)}
        let source=policy::http_source(&rows[0])?;
        let read=self.io(chat,"read",None).await?;
        let after=policy::merge(&source,&read["record"],chat,&self.original.owner,crate::platform::unix_ms()/1000)?;
        let written=self.io(chat,"compare_store",Some((&read,&after))).await?;
        if written["db_version"]!=read["db_version"]||written["record"]!=*after{return Err(Error::Conflict)}
        self.original.check()?;
        attempt.complete=true;
        Ok(MetadataOpaqueStored{original:self.original.clone()})
    }
    /// One selected Personal child's opaque navigation header only. The sole
    /// caller selector is child ID. No parent fetch/prerequisite, message read,
    /// key/decrypt authority, recovery/ACK or root upgrade is introduced.
    pub async fn store_subchat(self,chat:&str)->Result<MetadataOpaqueStored> {
        self.original.check()?;
        if !uuid::Uuid::parse_str(chat).is_ok_and(|id|id.to_string()==chat){return Err(Error::Protocol)}
        let mut attempt=Attempt{original:self.original.clone(),complete:false};
        let captured=self.capture_subchat(chat).await?;captured.check(&self.original)?;
        let read=self.io(chat,"read",None).await?;captured.check(&self.original)?;
        let after=policy::merge_subchat(&captured.source,&read["record"],chat,&self.original.owner,crate::platform::unix_ms()/1000)?;
        captured.check(&self.original)?;
        let written=self.io(chat,"compare_store",Some((&read,&after))).await?;
        if written["db_version"]!=read["db_version"]||written["record"]!=*after{return Err(Error::Conflict)}
        captured.check(&self.original)?;
        attempt.complete=true;
        Ok(MetadataOpaqueStored{original:self.original.clone()})
    }
    async fn capture_subchat(&self,chat:&str)->Result<CapturedSubchatMetadata> {
        self.original.check()?;
        let response=fixed_post(&self.original.context,&self.original.owner,"/v1/chats/metadata/batch",json!({"chat_ids":[chat],"include_read_details":true})).await?;
        self.original.check()?;
        let rows=response["chats"].as_array().ok_or(Error::Protocol)?;
        if rows.len()!=1||rows[0]["id"].as_str()!=Some(chat){return Err(Error::Forbidden)}
        let source=policy::http_source(&rows[0])?;
        let parent=Zeroizing::new(policy::subchat_parent(&source,chat,&self.original.owner)?.to_owned());
        let captured=CapturedSubchatMetadata{original:self.original.clone(),chat:Zeroizing::new(chat.to_owned()),parent,source};
        captured.check(&self.original)?;Ok(captured)
    }
    async fn io(&self,chat:&str,operation:&str,change:Option<(&Value,&Value)>)->Result<Plain<Value>> {
        self.original.check()?;
        let op=uuid::Uuid::new_v4().to_string();
        let mut effect=Plain::new(json!({"kind":"openmates-metadata-native-io-v1","op_id":op,"owner_id":self.original.owner.as_str(),"chat_id":chat,"operation":operation}));
        if let Some((read,after))=change {effect["expected_db_version"]=read["db_version"].clone();effect["before"]=read["record"].clone();effect["after"]=after.clone();}
        let ticket=Arc::new(MetadataNativeIoTicket{original:self.original.clone(),operation:Zeroizing::new(op),effect,dispatched:AtomicBool::new(false),source:None,recovery_source:None,embed_source:None});
        let pending=self.original.context.start(ticket.clone())?;
        let delivered=pending.drive().await?;
        // Native consumes actual same-context/ticket delivery and terminals.
        let encoded=Zeroizing::new(delivered.consume_for(&self.original.context,&ticket)?);
        self.original.check()?;
        if encoded.len()>MAX_PACKET{return Err(Error::Protocol)}
        let value=Plain::new(serde_json::from_str::<Value>(&encoded)?);
        let object=value.as_object().ok_or(Error::Protocol)?;
        let keys=["kind","op_id","owner_id","chat_id","db_version","record"];
        if object.len()!=keys.len()||!keys.iter().all(|k|object.contains_key(*k))||value["kind"]!="openmates-metadata-native-result-v1"||value["op_id"].as_str()!=Some(ticket.operation_id())||value["owner_id"].as_str()!=Some(self.original.owner.as_str())||value["chat_id"].as_str()!=Some(chat)||!value["db_version"].as_u64().is_some_and(|v|v>0&&v<=9_007_199_254_740_991)||(!value["record"].is_null()&&!value["record"].is_object()){return Err(Error::Protocol)}
        Ok(value)
    }
}
#[cfg(test)]mod tests {
 use super::*;
 #[test]fn auth_requires_real_matching_first_party_capabilities(){let owner="11111111-1111-4111-8111-111111111111";let good=json!({"success":true,"user":{"id":owner},"client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]});assert!(validate_auth(&good,owner).is_ok());for field in ["success","user","client_security_capabilities"]{let mut bad=good.clone();bad.as_object_mut().unwrap().remove(field);assert!(validate_auth(&bad,owner).is_err());}assert!(validate_auth(&good,"foreign").is_err());}
}

#[path="browser_initial_sync_store.rs"]
mod startup_store;
pub use startup_store::{CapturedInitialSyncStore,BoundInitialSyncStore,StartupMetadataStoreDriver,StartupMetadataStored,StartupMetadataNativeTerminal};
#[path="browser_recovery_metadata_finalize.rs"]
mod recovery_finalize;
pub use recovery_finalize::{BrowserMetadataRecoveryFinalize,BrowserMetadataRecoveryLocalStored,BrowserMetadataRecoveryNativeTerminal};
pub(in crate::client) use recovery_finalize::MetadataRecoveryPhysicalProof;

#[path="browser_recovery_native_row.rs"]
mod native_row;
#[path="browser_main_metadata_store.rs"]
mod main_metadata;
pub use main_metadata::{BrowserMainMetadataStore,BrowserMainMetadataStored,BrowserMainMetadataNativeTerminal};
#[path="browser_recovered_reply_store.rs"]
mod recovered_reply;
pub use recovered_reply::{BrowserRecoveredReplyStore,BrowserRecoveredReplyControl,BrowserRecoveredReplyStored,BrowserRecoveredReplyNativeTerminal};
#[path="browser_main_code_embed_store.rs"]
mod main_code_embed;
pub use main_code_embed::{BrowserMainCodeEmbedStore,BrowserMainCodeEmbedControl,BrowserMainCodeEmbedStored,BrowserMainCodeEmbedNativeTerminal};
