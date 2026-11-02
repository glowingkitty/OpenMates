//! Original startup socket source -> actual same-native-store row CAS/readback.
//! No generic effect callback, row DTO grant, key operation or full-hint ACK.
use super::*;
use crate::client::{Client,InitialSyncControl,InitialSyncMetadataBatch};
use crate::client::owned_operation::OwnedOperationScope;
use std::{cell::{Cell,RefCell},rc::Rc,future::Future,pin::Pin};

/// Captured from the actual saved Worker's first native bootstrap event only.
/// Contains no key material, caller rows or authentication/upgrading method.
pub struct CapturedInitialSyncStore {context:NativeMetadataContext,first_session_issued:Cell<bool>}
impl CapturedInitialSyncStore {
    pub fn capture_first(event:&wasm_bindgen::JsValue)->Result<Self>{Ok(Self{context:NativeMetadataContext::capture_startup_first(event)?,first_session_issued:Cell::new(false)})}
    /// Borrow the same first native bootstrap/store/config before auth HTTP.
    /// Only this original object can issue one normal-session preparation.
    pub fn prepare_first_session_original(&self,profile:crate::client::BrowserProfileKey,signals:Value,request:tokio_util::sync::CancellationToken)->Result<crate::client::PreparedBrowserFirstSession>{
        self.context.check_negative()?;
        if self.first_session_issued.replace(true){return Err(Error::Conflict)}
        let native=crate::client::browser::configured_native::OriginalConfiguredBrowser::capture(&self.context,&profile)?;
        Client::prepare_browser_first_session_configured(native,profile,signals,request)
    }
    /// Distinct normal response DATA purpose. No key/profile argument and no
    /// restoration, metadata, storage or private-content conversion exists.
    pub fn prepare_first_session_data_original(&self,signals:Value,request:tokio_util::sync::CancellationToken)->Result<crate::client::PreparedBrowserFirstSessionData>{
        self.context.check_negative()?;
        if self.first_session_issued.replace(true){return Err(Error::Conflict)}
        let native=crate::client::browser::configured_native::OriginalNormalBrowser::capture(&self.context)?;
        crate::client::browser::prepare_normal_data(native,signals,request)
    }
    pub(in crate::client) async fn recheck_first_session_original(&self,original:&Rc<crate::client::browser::configured_native::OriginalConfiguredBrowser>,request:&tokio_util::sync::CancellationToken,deadline:crate::platform::time::Instant)->Result<()>{
        // A foreign bootstrap refuses BEFORE native IO. The actual original
        // profile owner is read again after HTTP and before crypto Client escape.
        original.recheck_profile_for(&self.context,request,deadline).await
    }
    /// Thin restore constructor consumes this before Client/status escape.
    pub async fn bind_original(self,client:&Client)->Result<BoundInitialSyncStore>{
        let profile=match &client.browser_configured_native{
            Some(original)=>original.profile_for(&self.context)?,
            None=>self.context.profile_read().await?,
        };let owner=Zeroizing::new(profile.owner_id().to_owned());
        check_native_client(&self.context,&owner,client)?;profile.check_for(&self.context)?;
        let scope=Arc::new(OwnedOperationScope::capture(client,tokio_util::sync::CancellationToken::new())?);scope.check(client)?;
        let original=Arc::new(Original{context:self.context,profile,owner,denied:AtomicBool::new(false),client_scope:Some(scope)});
        let bound=BoundInitialSyncStore{original};bound.ensure_current(client)?;Ok(bound)
    }
}
fn check_native_client(context:&NativeMetadataContext,owner:&str,client:&Client)->Result<()> {
    context.check_negative()?;client.require_canonical_read_profile()?;client.require_browser_owner_guards()?;
    let(api,app,session)=context.selectors();let credentials=client.require_credentials()?;
    if client.browser_credentials.is_none()||client.user["id"].as_str()!=Some(owner)
        ||!client.browser_authority.as_ref().is_some_and(|a|a.principal==owner)
        ||url::Url::parse(api).map_err(|_|Error::Protocol)?!=client.base
        ||credentials.session_id!=session||client.options.app_url.as_deref()!=Some(app){return Err(Error::Forbidden)}
    Ok(())
}
/// Cloning retains only the SAME actual original profile/store/Client context.
#[derive(Clone)]
pub struct BoundInitialSyncStore {pub(super) original:Arc<Original>}
impl BoundInitialSyncStore {
    /// SAME retained native context negative only. Not IO settlement or ACK.
    #[doc(hidden)]
    pub async fn wait_native_invalidated(&self){self.original.context.cancelled().await;}

    /// Negative/currentness observation of the ORIGINAL native profile/store
    /// only. This does not permit startup writes, auth or general private work.
    #[doc(hidden)]
    pub fn ensure_profile_cache_current(&self,client:&Client)->Result<()> {
        self.original.check()?;client.require_canonical_read_profile()?;
        let(api,app,session)=self.original.context.selectors();let credentials=client.require_credentials()?;
        if client.browser_credentials.is_none()||client.user["id"].as_str()!=Some(self.original.owner.as_str())
            ||!client.browser_authority.as_ref().is_some_and(|a|a.principal==*self.original.owner)
            ||url::Url::parse(api).map_err(|_|Error::Protocol)?!=client.base
            ||credentials.session_id!=session||client.options.app_url.as_deref()!=Some(app){return Err(Error::Forbidden)}
        self.original.client_scope.as_ref().ok_or(Error::Forbidden)?.check(client)?;self.original.check()
    }
    pub fn ensure_current(&self,client:&Client)->Result<()> {
        self.original.check()?;check_native_client(&self.original.context,&self.original.owner,client)?;
        self.original.client_scope.as_ref().ok_or(Error::Forbidden)?.check(client)?;self.original.check()
    }
    pub fn begin(&self,client:&Client,batch:InitialSyncMetadataBatch)->Result<StartupMetadataStoreDriver>{
        self.ensure_current(client)?;batch.ensure_current(client)?;
        let control=batch.original_control();control.ensure_current(client)?;
        let original=self.original.clone();let terminal=Rc::new(Cell::new(false));let settled=terminal.clone();
        // Driver retains the SAME original source and every completed physical
        // pre/post even on Err, unknown native IO or a dropped driving future.
        let retained_batch=Rc::new(batch);let retained_rows=Rc::new(RefCell::new(Vec::new()));
        let batch=retained_batch.clone();let rows=retained_rows.clone();let source=control.clone();
        let future=Box::pin(async move{drive(original,batch,source,settled,rows).await});
        Ok(StartupMetadataStoreDriver{pending:Some(future),completed:None,control,terminal,_retained_batch:retained_batch,_retained_rows:retained_rows})
    }
}
/// Native operations of this exact driver only; never socket/HTTP/Worker/global
/// settlement, readiness, native row authority or original/full/later-hint ACK.
pub struct StartupMetadataNativeTerminal {settled:Rc<Cell<bool>>}
impl StartupMetadataNativeTerminal {pub fn native_io_quiescent(&self)->bool{self.settled.get()}}
pub struct StartupMetadataStoreDriver {
    pending:Option<Pin<Box<dyn Future<Output=Result<StartupMetadataStored>>>>>,completed:Option<StartupMetadataStored>,control:InitialSyncControl,terminal:Rc<Cell<bool>>,_retained_batch:Rc<InitialSyncMetadataBatch>,_retained_rows:Rc<RefCell<Vec<StoredRow>>>,
}
impl StartupMetadataStoreDriver {
    pub fn control(&self)->InitialSyncControl{self.control.clone()}
    pub fn terminal(&self)->Option<StartupMetadataNativeTerminal>{self.terminal.get().then(||StartupMetadataNativeTerminal{settled:self.terminal.clone()})}
    pub async fn drive(&mut self)->Result<()> {
        let pending=self.pending.take().ok_or(Error::Conflict)?;
        // Actual IO owns cancellation/terminals. Err/Drop never fabricates a
        // settled terminal; failed or unknown original contexts remain held.
        self.completed=Some(pending.await?);Ok(())
    }
    pub fn finish(&mut self,client:&Client)->Result<StartupMetadataStored>{
        let result=self.completed.as_ref().ok_or(Error::Conflict)?;result.ensure_current(client)?;
        self.completed.take().ok_or(Error::Conflict)
    }
}
/// Opaque physical per-row readback handoff. All source facets stay retained;
/// metadata persistence alone is not startup/full-hint completion or private UI.
#[allow(dead_code)] // Intentionally sealed full physical evidence, never public row DTOs.
struct StoredRow {chat:String,before:Plain<Value>,after:Plain<Value>}
impl Drop for StoredRow{fn drop(&mut self){zeroize::Zeroize::zeroize(&mut self.chat);}}
pub struct StartupMetadataStored {original:Arc<Original>,batch:Rc<InitialSyncMetadataBatch>,rows:Rc<RefCell<Vec<StoredRow>>>}
impl StartupMetadataStored {
    pub fn ensure_current(&self,client:&Client)->Result<()> {
        self.original.check()?;self.batch.ensure_current(client)?;
        self.original.client_scope.as_ref().ok_or(Error::Forbidden)?.check(client)?;
        check_native_client(&self.original.context,&self.original.owner,client)?;self.original.profile.check_for(&self.original.context)
    }
    pub fn stored_metadata_count(&self,client:&Client)->Result<usize>{self.ensure_current(client)?;Ok(self.rows.borrow().len())}
}
struct Attempt {original:Arc<Original>,complete:bool}
impl Drop for Attempt{fn drop(&mut self){if !self.complete{self.original.denied.store(true,Ordering::Release);self.original.context.revoke_original();}}}
fn source_check(original:&Original,source:&InitialSyncControl)->Result<()>{original.check()?;source.check_original_negative()?;original.check()}
async fn cancelled(original:&Original,source:&InitialSyncControl){
    let owner=async{if let Some(scope)=&original.client_scope{scope.cancelled().await}else{std::future::pending::<()>().await}};
    tokio::select!{biased;_=source.cancelled()=>{},_=owner=>{},_=original.context.cancelled()=>{}}
}
async fn io(original:&Arc<Original>,source:&InitialSyncControl,chat:&str,change:Option<(&Value,&Value)>)->Result<Plain<Value>> {
    source_check(original,source)?;let op=uuid::Uuid::new_v4().to_string();
    let mut effect=Plain::new(json!({"kind":"openmates-metadata-native-io-v1","op_id":op,"owner_id":original.owner.as_str(),"chat_id":chat,"operation":if change.is_some(){"compare_store"}else{"read"}}));
    if let Some((before,after))=change{effect["expected_db_version"]=before["db_version"].clone();effect["before"]=before["record"].clone();effect["after"]=after.clone();}
    let ticket=Arc::new(MetadataNativeIoTicket{original:original.clone(),operation:Zeroizing::new(op),effect,dispatched:AtomicBool::new(false),source:Some(source.clone()),recovery_source:None,embed_source:None});
    let pending=original.context.start(ticket.clone())?;let actual=pending.drive();tokio::pin!(actual);
    let delivery=tokio::select!{result=&mut actual=>result,_=cancelled(original,source)=>{original.context.revoke_original();actual.await}}?;
    let encoded=Zeroizing::new(delivery.consume_for(&original.context,&ticket)?);source_check(original,source)?;
    if encoded.len()>MAX_PACKET{return Err(Error::Protocol)}let value=Plain::new(serde_json::from_str::<Value>(&encoded)?);
    let keys=["kind","op_id","owner_id","chat_id","db_version","record"];let object=value.as_object().ok_or(Error::Protocol)?;
    if object.len()!=keys.len()||!keys.iter().all(|k|object.contains_key(*k))||value["kind"]!="openmates-metadata-native-result-v1"||value["op_id"].as_str()!=Some(ticket.operation_id())||value["owner_id"].as_str()!=Some(original.owner.as_str())||value["chat_id"].as_str()!=Some(chat)||!value["db_version"].as_u64().is_some_and(|n|n>0&&n<=9_007_199_254_740_991)||(!value["record"].is_null()&&!value["record"].is_object()){return Err(Error::Protocol)}
    Ok(value)
}
async fn drive(original:Arc<Original>,batch:Rc<InitialSyncMetadataBatch>,source:InitialSyncControl,terminal:Rc<Cell<bool>>,retained:Rc<RefCell<Vec<StoredRow>>>)->Result<StartupMetadataStored>{
    let mut attempt=Attempt{original:original.clone(),complete:false};source_check(&original,&source)?;
    let(rows,order,expanded)=batch.original_rows();let mut used=batch.retained_navigation_bytes()?;
    for chat in order {
        source_check(&original,&source)?;let row=rows.get(chat).ok_or(Error::Protocol)?;
        let before=io(&original,&source,chat,None).await?;
        let after=policy::merge_startup(row,&before["record"],chat,&original.owner,batch.original_team(),expanded.contains(chat),crate::platform::unix_ms()/1000)?;
        // Retain complete physical pre/post evidence for later opaque handoff.
        // Refuse before this row's write when the existing16MiB aggregate would
        // be exceeded; never truncate fields, drafts or earlier proof records.
        let next=policy::reserve_startup_metadata_evidence(used,&before,&after)?;
        // Even a full expanded row intentionally kept unchanged gets an actual
        // same-store readback; no successful page or count stands in for IO.
        let actual=if *after==before["record"]{io(&original,&source,chat,None).await?}else{io(&original,&source,chat,Some((&before,&after))).await?};
        if actual["db_version"]!=before["db_version"]||actual["record"]!=*after{return Err(Error::Conflict)}
        source_check(&original,&source)?;used=next;retained.borrow_mut().push(StoredRow{chat:chat.clone(),before,after:actual});
    }
    {
        let profile=original.context.recheck_profile_owner();tokio::pin!(profile);
        tokio::select!{result=&mut profile=>result,_=cancelled(&original,&source)=>{original.context.revoke_original();profile.await}}?;
    }
    source_check(&original,&source)?;
    if !original.context.native_operations_consumed(){return Err(Error::Conflict)}
    attempt.complete=true;terminal.set(true);Ok(StartupMetadataStored{original,batch,rows:retained})
}
