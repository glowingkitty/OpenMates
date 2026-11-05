//! Owned B-only read/cache phases. Futures own network/key/IO resources, never
//! a Client borrow. Actual short Client application resumes each exact phase.
use super::*;
use crate::client::owned_operation::{ActiveOwnedClient, OwnedOperationScope};
use crate::client::monitor::{BrowserOwnedMonitorReadContext, BrowserOwnedMetadataFloor, ChatMonitor};
#[path="browser_owned_hint_recovery.rs"]
mod hint_recovery;
pub use hint_recovery::{BrowserOriginalHintRecoveryDriver,BrowserOriginalHintRecoveryStep,BrowserOriginalHintRecoveryApply,BrowserOriginalHintRecoveryIo,BrowserOriginalHintRecoveryResume,BrowserOriginalHintRecoveryControl,BrowserOriginalHintRecoveryAdoption,BrowserOriginalHintRecoveryProgress,BrowserOriginalHintRecoveryPendingPersistence,BrowserOriginalHintRecoveryDeferred,BrowserOriginalHintRecoveryCheckpointPreparation,BrowserOriginalHintRecoveryCheckpointCrypto,BrowserOriginalHintRecoveryCheckpointWrite,BrowserOriginalHintRecoveryPersistenceFailure};
#[path="browser_owned_hint_windows.rs"]
mod hint_windows;
pub use hint_windows::{OwnedOriginalHintWindowPreparation,OwnedOriginalHintWindowCompletion,OriginalHintWindowBatch};
#[path="browser_owned_hint_row.rs"]
mod hint_row;
pub use hint_row::{OriginalHintRowMetadataAdmission,OriginalHintRowMetadataPublication};
#[path="browser_owned_hint_row_ledger.rs"]
mod row_ledger;
pub use row_ledger::OriginalHintMetadataApplied;
#[path="browser_original_draft_inventory.rs"]
mod draft_inventory;
pub use draft_inventory::{OriginalHintDraftInventoryPrerequisite,OriginalHintDraftInventoryTicket,UntrustedDraftInventoryPageData,UntrustedDraftInventoryRereadData};
use crate::client::transport::{self, OwnedReadRoute, PreparedOwnedRead, OwnedReadHeaders, OwnedReadBody, CompletedOwnedRead};
use crate::crypto::master::MasterCapability;
use std::{collections::BTreeSet,pin::Pin, sync::{Mutex,atomic::{AtomicBool,AtomicU64,Ordering}}};
use tokio::sync::{mpsc,oneshot};
#[path="browser_owned_local_first.rs"]
mod local_first;
#[path="browser_profile_cache_readiness.rs"]
mod profile_cache;
pub use profile_cache::BrowserProfileCacheReadiness;
#[path="browser_profile_cache_absence.rs"]
mod profile_absence;
pub use profile_absence::OwnedBrowserProfileCacheAbsence;

#[path="browser_owned_hint_remainder.rs"]
mod hint_remainder;
pub use hint_remainder::OriginalHintRecoveryHandoff;
#[path="browser_owned_hint_refresh.rs"]
mod hint_refresh;
pub use hint_refresh::{OriginalHintRefreshAdmission,OriginalHintRefreshBatch,OriginalHintRowSeed};

#[derive(Clone,Copy)]
enum ReadKind { Metadata,Messages }
#[derive(Clone,Copy)]
enum KeyKind { Server,Local }
struct SourceEvidence { packet:String,metadata:String,messages_version:Option<u64> }
enum Mode {Cold,Incoming(Arc<BrowserOwnedMonitorReadContext>)}
enum BeginMode {Cold,LocalFirst,ProfileCache(Arc<BrowserProfileCacheReadiness>),Incoming(Arc<ChatMonitor>),OriginalHint(Arc<ChatMonitor>)}
struct Context {
    profile_cache:Option<Arc<BrowserProfileCacheReadiness>>,
    profile_absence:Mutex<Option<profile_absence::Observation>>,
    scope:Arc<OwnedOperationScope>,mode:Mode,original:Option<Arc<Context>>,server_wrappers:Option<Plain<Vec<Value>>>,
    owner:String,chat:String,cursor_scope:String,source:Mutex<String>,floors:Mutex<BrowserOwnedMetadataFloor>,
    options:crate::client::message_window::MessageWindowOptions,
    recovery_issued:Arc<Mutex<BTreeSet<(u8,String)>>>,recovery_active:Arc<crate::client::completion_recovery::OriginalRecoveryActiveState>,refresh_issued:AtomicBool,inventory_issued:AtomicBool,inventory_drain:Arc<InventoryDrainState>,inventory_working_issued:Mutex<BTreeSet<String>>,inventory_finished:AtomicBool,original_draft_budget:AtomicBool,
    next:AtomicU64,outstanding:AtomicU64,evidence:Mutex<Option<SourceEvidence>>,source_metadata:Mutex<Option<Plain<Value>>>,
}
impl Context {
    // Additional resource-negative only; never caller gate/row/IO authority.
    fn negative_without_gate(&self)->Result<()> {
        if let Some(profile)=&self.profile_cache{profile.scope.observer().check_original_negative()?;}
        if let Some(original)=&self.original{original.negative_without_gate()?;}
        self.scope.crypto.check_original_operation_negative()?;
        if let Mode::Incoming(monitor)=&self.mode{monitor.check_original_negative()?;}
        self.scope.crypto.check_original_operation_negative()
    }
    fn io_budget(&self)->CacheIoBudget{if self.original_draft_budget.load(Ordering::Acquire){CacheIoBudget::OriginalPhysicalDraft}else{CacheIoBudget::Metadata}}
    fn validate_original_draft_packet(&self,client:&Client,encoded:&str)->Result<()> {
        if !self.original_draft_budget.load(Ordering::Acquire){return local_json::validate(encoded)}
        local_json::validate_original_physical_draft(encoded)?;
        let mut frame=Plain::new(serde_json::from_str::<Value>(encoded)?);
        let permit=client.original_physical_draft_bounds.get(&self.chat).ok_or(Error::Cancelled)?;
        for field in ["metadata","record","before"] {
            let Some(header)=frame.get_mut(field)else{continue};
            if !header.is_object(){continue}
            if header["chat_id"].as_str()!=Some(self.chat.as_str()){return Err(Error::Forbidden)}
            permit.check_header(client,header)?;
            if let Some(object)=header.as_object_mut(){object.remove("encrypted_draft_md");object.remove("encrypted_draft_preview");}
        }
        // Size accounting only. Return the original unmodified full IO bytes.
        let accounted=Zeroizing::new(serde_json::to_string(&*frame)?);local_json::validate(&accounted)
    }
    fn negative(&self)->Result<()> {
        if let Some(profile)=&self.profile_cache{profile.scope.observer().check_release()?;}
        if let Some(original)=&self.original{original.negative()?;}
        self.scope.observer().check_release()?;
        if let Mode::Incoming(monitor)=&self.mode{monitor.negative_check()?;}
        self.scope.observer().check_release()
    }
    async fn cancelled(&self){match &self.mode{Mode::Cold=>self.scope.cancelled().await,Mode::Incoming(monitor)=>monitor.cancelled().await}}
    fn metadata_kind(&self)->&'static str{match &self.mode{Mode::Cold=>"cold_metadata",Mode::Incoming(_)=>"original_hint_metadata"}}
    fn check_lifetime(&self,c:&Client)->Result<()> {
        if let Some(original)=&self.original{original.check(c)?;}
        if let Mode::Incoming(monitor)=&self.mode{monitor.check(c)?;}
        self.scope.check(c)?;self.scope.crypto.check_chat(c,&self.chat)?;
        if let Some(profile)=&self.profile_cache{
            profile.ensure_current(c)?;
            c.metadata_cache_scope(&self.owner,&self.chat,BrowserMetadataCacheMode::Restore)?;
        }else{c.metadata_cache_scope(&self.owner,&self.chat,BrowserMetadataCacheMode::PersistCurrent)?;}
        Ok(())
    }
    fn check(&self,c:&Client)->Result<()> {
        self.check_lifetime(c)?;
        if crate::client::browser::original_draft_bounds::source_stamp(c,&self.chat)?!=*self.source.lock().map_err(|_|Error::Protocol)?||c.message_window_scope()?!=self.cursor_scope{return Err(Error::Cancelled)}
        self.negative()
    }
    // ONLY the genuine recovery driver may use this after its own witnessed
    // row apply. It cannot release selected output or adopt a new source stamp.
    fn check_recovery_root(&self,c:&Client)->Result<()> {
        self.check_lifetime(c)?;
        if c.message_window_scope()?!=self.cursor_scope{return Err(Error::Cancelled)}
        self.negative()
    }
    fn metadata_floor(&self,metadata:&Value)->Result<()> {
        if let Mode::Incoming(monitor)=&self.mode{monitor.check_chat_metadata_floor(&self.chat,metadata)?;}
        self.floors.lock().map_err(|_|Error::Protocol)?.check(metadata)
    }
    fn issue(&self)->Result<u64> {self.negative()?;self.issue_sequence()}
    // Only already-received opaque real headers use this path. Matched original
    // cookie adoption must precede local cancellation refusal; no body/key/IO
    // permission or caller receipt is accepted here.
    fn issue_received_headers(&self)->Result<u64> {self.issue_sequence()}
    fn issue_sequence(&self)->Result<u64> {
        let seq=self.next.fetch_update(Ordering::AcqRel,Ordering::Acquire,|n|n.checked_add(1).filter(|n|*n<=MAX_SAFE)).map_err(|_|Error::Protocol)?;
        self.outstanding.compare_exchange(0,seq,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;Ok(seq)
    }
    fn pending(&self,seq:u64)->Result<()> {
        if seq==0||self.outstanding.load(Ordering::Acquire)!=seq{return Err(Error::Conflict)}Ok(())
    }
    fn finish(&self,seq:u64)->Result<()> {
        self.outstanding.compare_exchange(seq,0,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;Ok(())
    }
}
struct PreparedKey { master:MasterCapability,ciphertext:Zeroizing<String> }
struct PreparedIo { encoded:Zeroizing<String>,budget:CacheIoBudget }
enum Work {
    Prepare(ReadKind),Headers(OwnedReadHeaders),Body(CompletedOwnedRead),
    Key(Plain<Value>,KeyKind),AcceptKey(Key),
    Decode {metadata:Plain<Value>,key:Key,page:Plain<Value>},
    AuthorizeIo(Zeroizing<String>),FinishIo(Result<Zeroizing<String>>),
    MetadataItem {metadata:Plain<Value>,key:Key},
    PrepareMonitorRefresh,TakeMonitorRead(crate::client::monitor::MonitorReadReceipt),
}
enum Resume {
    Prepared(PreparedOwnedRead),Body(OwnedReadBody),Value(Plain<Value>),KeyInput(PreparedKey),Key(Key),
    Incoming(crate::client::message_window::BrowserIncomingMessagePage),Io(PreparedIo),Encoded(Zeroizing<String>),
    MetadataItem(Plain<Item>),
    MonitorPrepared(crate::client::monitor::PreparedMonitorRead),MonitorData(crate::client::monitor::MonitorReadData),
}
// Per ACTUAL driver bookkeeping. Negative-only quiescence, never Client/auth,
// cache/IO authority or a full transferred-resource/Host transaction receipt.
#[derive(Default)]
struct InventoryDrainState {active:AtomicU64,unsettled:AtomicBool}
impl InventoryDrainState {
    fn quiescent(&self)->bool{self.active.load(Ordering::Acquire)==0&&!self.unsettled.load(Ordering::Acquire)}
}
struct InventoryLease {state:Arc<InventoryDrainState>,settled:bool}
impl InventoryLease {
    fn begin(state:Arc<InventoryDrainState>)->Result<Self>{
        state.active.fetch_update(Ordering::AcqRel,Ordering::Acquire,|n|n.checked_add(1)).map_err(|_|Error::Protocol)?;
        Ok(Self{state,settled:false})
    }
    fn settled(mut self){self.settled=true;}
}
impl Drop for InventoryLease {
    fn drop(&mut self){
        if !self.settled{self.state.unsettled.store(true,Ordering::Release);}
        if self.state.active.fetch_update(Ordering::AcqRel,Ordering::Acquire,|n|n.checked_sub(1)).is_err(){self.state.unsettled.store(true,Ordering::Release);}
    }
}
#[derive(Default)]
struct DriverDrainState {returned:AtomicBool,steps:AtomicU64,io:AtomicU64,unsettled:AtomicBool,inventory:Arc<InventoryDrainState>}
impl DriverDrainState {
    fn for_context(context:&Context)->Self{Self{inventory:context.inventory_drain.clone(),..Self::default()}}
    fn add(&self,count:&AtomicU64){if count.fetch_update(Ordering::AcqRel,Ordering::Acquire,|n|n.checked_add(1)).is_err(){self.unsettled.store(true,Ordering::Release);}}
    fn remove(&self,count:&AtomicU64){if count.fetch_update(Ordering::AcqRel,Ordering::Acquire,|n|n.checked_sub(1)).is_err(){self.unsettled.store(true,Ordering::Release);}}
    fn quiescent(&self)->bool{self.returned.load(Ordering::Acquire)&&self.steps.load(Ordering::Acquire)==0&&self.io.load(Ordering::Acquire)==0&&!self.unsettled.load(Ordering::Acquire)&&self.inventory.quiescent()}
}
#[doc(hidden)]
pub struct OwnedBrowserReadTerminalObserver {state:Arc<DriverDrainState>}
impl OwnedBrowserReadTerminalObserver {
    pub fn terminal(&self)->Option<OwnedBrowserReadTerminal>{self.state.quiescent().then(||OwnedBrowserReadTerminal{state:self.state.clone()})}
}
/// Minted only after this driver's actual future returned and exact steps/IO
/// settled. No serialization/constructor/private output, NOT auth/durability.
#[doc(hidden)]
pub struct OwnedBrowserReadTerminal {state:Arc<DriverDrainState>}
impl OwnedBrowserReadTerminal {pub fn is_quiescent(&self)->bool{self.state.quiescent()}}
struct ActualIoLease {state:Arc<DriverDrainState>,settled:bool}
impl ActualIoLease {
    fn begin(state:Arc<DriverDrainState>)->Self{state.add(&state.io);Self{state,settled:false}}
    fn settled(mut self){self.settled=true;}
}
impl Drop for ActualIoLease {
    fn drop(&mut self){if !self.settled{self.state.unsettled.store(true,Ordering::Release);}self.state.remove(&self.state.io);}
}
struct ReplySlot {context:Arc<Context>,drain:Arc<DriverDrainState>,seq:u64,sender:Option<oneshot::Sender<Result<Resume>>>}
impl ReplySlot {
    fn finish(mut self,result:Result<Resume>)->Result<()> {
        self.context.finish(self.seq)?;
        let sender=self.sender.take().ok_or(Error::Conflict)?;self.drain.remove(&self.drain.steps);
        sender.send(result).map_err(|_|Error::Cancelled)
    }
}
impl Drop for ReplySlot {
    fn drop(&mut self){
        if let Some(sender)=self.sender.take(){
            // Abandonment retires only this exact original operation/sequence.
            // A stale cleanup cannot clear a later phase or any sibling's slot.
            self.context.scope.observer().cancel();
            let _=self.context.outstanding.compare_exchange(self.seq,0,Ordering::AcqRel,Ordering::Acquire);
            self.drain.remove(&self.drain.steps);let _=sender.send(Err(Error::Cancelled));
        }
    }
}
struct Pending { context:Arc<Context>,seq:u64,work:PendingWork,reply:ReplySlot }
enum PendingWork { Apply(Work),Io(PreparedIo) }
#[derive(Clone)]
struct Channel {context:Arc<Context>,drain:Arc<DriverDrainState>,send:mpsc::UnboundedSender<Pending>}
impl Channel {
    async fn call(&self,work:PendingWork)->Result<Resume> {
        let seq=match &work {
            PendingWork::Apply(Work::Headers(_))=>self.context.issue_received_headers()?,
            _=>self.context.issue()?,
        };let(reply,receive)=oneshot::channel();
        self.drain.add(&self.drain.steps);
        let reply=ReplySlot{context:self.context.clone(),drain:self.drain.clone(),seq,sender:Some(reply)};
        self.send.send(Pending{context:self.context.clone(),seq,work,reply}).map_err(|_|Error::Cancelled)?;
        receive.await.map_err(|_|Error::Cancelled)?
    }
    async fn apply(&self,work:Work)->Result<Resume>{self.call(PendingWork::Apply(work)).await}
    async fn unwrap(&self,row:Plain<Value>,kind:KeyKind)->Result<Key> {
        let Resume::KeyInput(input)=self.apply(Work::Key(row,kind)).await? else{return Err(Error::Protocol)};
        self.context.negative()?;
        // WebCrypto cannot be cancelled: retain and actually drain the exact
        // original opaque operation, then refuse its result if revoked.
        let bytes=input.master.decrypt_bytes(&input.ciphertext).await?;
        self.context.negative()?;let key=key_from_bytes(&bytes)?;
        let Resume::Key(key)=self.apply(Work::AcceptKey(key)).await? else{return Err(Error::Protocol)};Ok(key)
    }
    async fn validate_metadata(&self,row:Plain<Value>)->Result<Key> {
        let key=self.unwrap(Plain::new((*row).clone()),KeyKind::Local).await?;
        self.context.negative()?;super::super::validate_metadata_cipher_fields(&row,&key)?;
        self.context.negative()?;Ok(key)
    }
    async fn read(&self,kind:ReadKind)->Result<Plain<Value>> {
        let Resume::Prepared(prepared)=self.apply(Work::Prepare(kind)).await? else{return Err(Error::Protocol)};
        let request=self.context.scope.request();
        let headers=tokio::select!{biased;_=self.context.cancelled()=>return Err(Error::Cancelled),
            value=transport::send_owned_read_headers(prepared,&request,||self.context.negative())=>value?};
        // Matched actual header merge happens before any body/policy await.
        let Resume::Body(body)=self.apply(Work::Headers(headers)).await? else{return Err(Error::Protocol)};
        let completed=tokio::select!{biased;_=self.context.cancelled()=>return Err(Error::Cancelled),
            value=transport::drive_owned_read_body(body,&request,||self.context.negative())=>value?};
        let Resume::Value(value)=self.apply(Work::Body(completed)).await? else{return Err(Error::Protocol)};Ok(value)
    }
    async fn io(&self,encoded:String)->Result<String> {
        let Resume::Io(prepared)=self.apply(Work::AuthorizeIo(Zeroizing::new(encoded))).await? else{return Err(Error::Protocol)};
        let Resume::Encoded(encoded)=self.call(PendingWork::Io(prepared)).await? else{return Err(Error::Protocol)};Ok(encoded.to_string())
    }
}
/// One actual Client phase. No Clone/serde/constructor or public raw resume.
#[doc(hidden)]
pub struct OwnedBrowserReadPhase {pending:Pending}
impl OwnedBrowserReadPhase {
    /// Errors are delivered to the original driver; this only acknowledges that
    /// the exact phase was applied. No callback/JSON can mint a new resume.
    pub fn apply(self,client:&mut Client)->Result<()> {
        let Pending{context,seq,work,reply}=self.pending;context.pending(seq)?;
        let PendingWork::Apply(work)=work else{return Err(Error::Protocol)};
        let result=match work {
            Work::Headers(headers)=>{
                // Retain an original matched response's real rotated cookies
                // even if local request cancellation became ready meanwhile.
                let result=client.apply_owned_read_headers(headers);
                result.and_then(|body|{context.check(client)?;Ok(Resume::Body(body))})
            },
            work=>(||{
                context.check(client)?;
                let mut actual=ActiveOwnedClient::enter(client,&context.scope)?;
                let result=apply_work(&context,&mut actual,work)?;drop(actual);
                context.check(client)?;Ok(result)
            })(),
        };
        reply.finish(result)
    }
}
fn apply_work(ctx:&Context,c:&mut Client,work:Work)->Result<Resume> {
    if ctx.profile_cache.is_some(){
        match &work {
            Work::Key(_,KeyKind::Local)|Work::AcceptKey(_)|Work::FinishIo(_)=>{},
            Work::AuthorizeIo(encoded)=>{
                let plan:Value=serde_json::from_str(encoded)?;
                if !matches!(plan["kind"].as_str(),Some("owned_metadata"|"messages"))
                    ||plan["owner"].as_str()!=Some(ctx.owner.as_str())||plan["chatId"].as_str()!=Some(ctx.chat.as_str()){return Err(Error::Forbidden)}
            },
            _=>return Err(Error::Forbidden),
        }
    }
    match work {
        Work::Prepare(ReadKind::Metadata)=>Ok(Resume::Prepared(c.prepare_owned_read(OwnedReadRoute::ChatMetadata{chat_id:&ctx.chat,include_read_details:true})?)),
        Work::Prepare(ReadKind::Messages)=>Ok(Resume::Prepared(c.prepare_owned_read(OwnedReadRoute::ChatMessages{chat_id:&ctx.chat,options:&ctx.options})?)),
        Work::Headers(_)=>Err(Error::Protocol),
        Work::Body(body)=>Ok(Resume::Value(Plain::new(c.finish_owned_read(body)?.ok_or(Error::Forbidden)?))),
        Work::Key(row,kind)=>{
            if matches!(kind,KeyKind::Server){c.browser_message_cache_metadata_guard(&row,&ctx.chat)?;ctx.metadata_floor(&row)?;}
            if c.team()?.is_some()||text(&row,"chat_visibility")=="direct"{return Err(unsupported("TEAM_DIRECT_BROWSER_MONITOR_POLICY_REMAINS_REQUIRED"))}
            let wrappers=if matches!(kind,KeyKind::Server){ctx.server_wrappers.as_ref().map(|rows|rows.as_slice()).unwrap_or(c.wrappers.as_slice())}else{&[]};
            let selected=c.chat_key_ciphertext_from(&row,false,wrappers)?;
            let ciphertext=Zeroizing::new(selected.ciphertext.to_owned());
            Ok(Resume::KeyInput(PreparedKey{master:c.master_capability()?,ciphertext}))
        },
        Work::AcceptKey(key)=>Ok(Resume::Key(key)),
        Work::Decode{metadata,key,page}=>{
            ctx.metadata_floor(&metadata)?;
            let item=Plain::new(c.chat_item(&metadata,&key)?);
            let mut decoded=Plain::new(crate::client::message_window::decode_message_page_data(
                &ctx.chat,&metadata,key,item,page.into_inner(),&ctx.options,&ctx.cursor_scope,false,true,||ctx.negative())?);
            let raw=decoded.incoming.take().ok_or(Error::Protocol)?;
            let evidence=SourceEvidence{packet:packet_source_stamp(&raw.metadata,&raw.messages)?,
                metadata:decoded.metadata_stamp.clone(),messages_version:raw.metadata["messages_v"].as_u64()};
            *ctx.evidence.lock().map_err(|_|Error::Protocol)?=Some(evidence);
            *ctx.source_metadata.lock().map_err(|_|Error::Protocol)?=Some(normalized(&raw.metadata,&ctx.chat,&ctx.owner,false)?);
            Ok(Resume::Incoming(raw))
        },
        Work::AuthorizeIo(encoded)=>{local_json::validate(&encoded)?;Ok(Resume::Io(PreparedIo{encoded,budget:ctx.io_budget()}))},
        Work::FinishIo(result)=>{let encoded=result?;ctx.validate_original_draft_packet(c,&encoded)?;Ok(Resume::Encoded(encoded))},
        Work::PrepareMonitorRefresh=>{
            let Mode::Incoming(monitor)=&ctx.mode else{return Err(Error::Forbidden)};
            Ok(Resume::MonitorPrepared(monitor.prepare_original_read(c,crate::client::monitor::MonitorReadRequest::RecentSync)?))
        },
        Work::TakeMonitorRead(receipt)=>{
            let Mode::Incoming(monitor)=&ctx.mode else{return Err(Error::Forbidden)};
            Ok(Resume::MonitorData(monitor.take_original_read(c,receipt)?))
        },
        Work::MetadataItem{metadata,key}=>{
            // Original raw authenticated source already passed exact cached and
            // original-hint floors before unwrap/decode. This is its physical
            // closed CAS projection; normalization omits nested counters/drafts
            // and must never be mistaken for a new authoritative envelope.
            Ok(Resume::MetadataItem(Plain::new(c.chat_item(&metadata,&key)?)))
        },
    }
}
/// Closed existing IDB plan and its exact original resource. This is not native
/// transaction authority; the real host handler independently drains trusted IO.
#[doc(hidden)]
pub struct OwnedBrowserReadIO {pending:Pending}
impl OwnedBrowserReadIO {
    pub fn uses_original_physical_draft_budget(&self)->bool {matches!(&self.pending.work,PendingWork::Io(PreparedIo{budget:CacheIoBudget::OriginalPhysicalDraft,..}))}
    pub async fn execute<F,Fut>(self,io:F)->Result<OwnedBrowserReadPhase>
    where F:FnOnce(String)->Fut,Fut:Future<Output=Result<String>> {
        let Pending{context,seq,work,reply}=self.pending;context.pending(seq)?;
        let PendingWork::Io(input)=work else{return Err(Error::Protocol)};
        let result=match context.negative(){
            Ok(())=>{
                let active=ActualIoLease::begin(reply.drain.clone());
                let result=io(input.encoded.to_string()).await;
                // Only actual callback settlement (including Err) disarms the
                // abandoned-IO marker. Dropping this await cannot mint drain.
                active.settled();result
            },
            Err(error)=>Err(error),
        };
        // Do not select-drop an already started IDB callback on cancellation:
        // the actual complete/abort and owned host drain must really finish.
        let result=result.map(Zeroizing::new);
        let result=context.negative().and_then(|_|result);
        Ok(OwnedBrowserReadPhase{pending:Pending{context,seq,work:PendingWork::Apply(Work::FinishIo(result)),reply}})
    }
}
#[doc(hidden)]
pub enum OwnedBrowserReadStep {Apply(OwnedBrowserReadPhase),IO(OwnedBrowserReadIO),Selected(OwnedBrowserReadPublication),Metadata(OwnedBrowserMetadataPublication),Refresh(OriginalHintRefreshBatch),RowMetadata(OriginalHintRowMetadataPublication)}
enum Outcome {Selected(RetainedData),LocalSelected(local_first::LocalSelected),Metadata(MetadataData),Refresh(hint_refresh::RefreshData),RowMetadata(hint_row::RowMetadataData)}
/// Opaque original resource observation, never caller status or a new grant.
#[doc(hidden)]
pub struct OwnedBrowserReadControl {context:Arc<Context>}
impl OwnedBrowserReadControl {
    pub fn ensure_current(&self,client:&Client)->Result<()>{self.context.check(client)}
    pub fn cancel(&self){self.context.scope.observer().cancel();}
}
#[doc(hidden)]
pub struct OwnedBrowserReadDriver {
    context:Arc<Context>,future:Pin<Box<dyn Future<Output=Result<Outcome>>>>,
    pending:mpsc::UnboundedReceiver<Pending>,finished:bool,drain:Arc<DriverDrainState>,
}
impl OwnedBrowserReadDriver {
    pub fn terminal_observer(&self)->OwnedBrowserReadTerminalObserver{OwnedBrowserReadTerminalObserver{state:self.drain.clone()}}
    pub fn control(&self)->OwnedBrowserReadControl{OwnedBrowserReadControl{context:self.context.clone()}}
    pub async fn next(&mut self)->Result<OwnedBrowserReadStep> {
        if self.finished||self.context.outstanding.load(Ordering::Acquire)!=0||self.context.inventory_issued.load(Ordering::Acquire)&&!self.context.inventory_finished.load(Ordering::Acquire){return Err(Error::Conflict)}
        tokio::select!{biased;
            result=&mut self.future=>{
                self.finished=true;self.drain.returned.store(true,Ordering::Release);let data=result?;self.context.negative()?;
                Ok(match data{
                    Outcome::Selected(data)=>OwnedBrowserReadStep::Selected(OwnedBrowserReadPublication{context:self.context.clone(),data,local:None,selected_taken:false}),
                    Outcome::LocalSelected(data)=>OwnedBrowserReadStep::Selected(OwnedBrowserReadPublication{context:self.context.clone(),data:data.retained,local:Some(data.checkpoints),selected_taken:false}),
                    Outcome::Metadata(data)=>OwnedBrowserReadStep::Metadata(OwnedBrowserMetadataPublication{context:self.context.clone(),data,taken:false}),
                    Outcome::Refresh(data)=>OwnedBrowserReadStep::Refresh(OriginalHintRefreshBatch::from_actual_read(self.context.clone(),data)),
                    Outcome::RowMetadata(data)=>OwnedBrowserReadStep::RowMetadata(OriginalHintRowMetadataPublication::from_actual(self.context.clone(),data)),
                })
            },
            pending=self.pending.recv()=>{
                let pending=pending.ok_or(Error::Cancelled)?;
                if !Arc::ptr_eq(&pending.context,&self.context){return Err(Error::Conflict)}
                if matches!(&pending.work,PendingWork::Apply(_)){Ok(OwnedBrowserReadStep::Apply(OwnedBrowserReadPhase{pending}))}
                else{Ok(OwnedBrowserReadStep::IO(OwnedBrowserReadIO{pending}))}
            },
        }
    }
    pub fn cancel(&self){self.context.scope.observer().cancel();}
}
impl Drop for OwnedBrowserReadDriver {
    fn drop(&mut self){if !self.finished{self.drain.unsettled.store(true,Ordering::Release);self.context.scope.observer().cancel();}}
}
/// Actual physical retained rows and original response evidence, not canonical
/// history, inventory completion, recovery or native transaction acknowledgement.
#[doc(hidden)]
pub struct OwnedBrowserReadPublication {context:Arc<Context>,data:RetainedData,local:Option<Plain<Vec<Value>>>,selected_taken:bool}
impl OwnedBrowserReadPublication {
    pub fn authenticated_source_stamp(&self,client:&Client)->Result<String>{
        self.context.check(client)?;let evidence=self.context.evidence.lock().map_err(|_|Error::Protocol)?;
        let stamp=evidence.as_ref().ok_or(Error::Protocol)?.packet.clone();drop(evidence);self.context.check(client)?;Ok(stamp)
    }
    pub fn authenticated_metadata_stamp(&self,client:&Client)->Result<String>{
        self.context.check(client)?;let evidence=self.context.evidence.lock().map_err(|_|Error::Protocol)?;
        let stamp=evidence.as_ref().ok_or(Error::Protocol)?.metadata.clone();drop(evidence);self.context.check(client)?;Ok(stamp)
    }
    pub fn authenticated_messages_version(&self,client:&Client)->Result<Option<u64>>{
        self.context.check(client)?;let evidence=self.context.evidence.lock().map_err(|_|Error::Protocol)?;
        let version=evidence.as_ref().ok_or(Error::Protocol)?.messages_version;drop(evidence);self.context.check(client)?;Ok(version)
    }
    pub fn take(&mut self,client:&Client,include_private_output:bool)->Result<Zeroizing<String>> {
        if !include_private_output{return Err(Error::Invalid("Explicit private output consent is required."))}
        if self.selected_taken{return Err(Error::Conflict)}
        self.context.check(client)?;
        let rows=self.data.readback["rows"].as_array().ok_or(Error::Protocol)?;
        let mut output=super::super::retained_view::retained_projection(client,&self.context.owner,&self.context.chat,
            &self.data.readback["metadata"],rows,&self.data.key,&self.data.dispositions,
            Some(if self.local.is_some(){"local"}else{match &self.context.mode{Mode::Cold=>"cold",Mode::Incoming(_)=>"monitor"}}),None)?;
        if let Some(checkpoints)=&self.local {local_first::add_checkpoint(&self.context,&mut output,checkpoints,&self.data.key)?;}
        let encoded=Zeroizing::new(serde_json::to_string(&*output)?);local_json::validate(&encoded)?;
        self.context.check(client)?;self.selected_taken=true;Ok(encoded)
    }
    /// Finish only the bounded cold selected-view contract. There was no
    /// original monitor hint to consume; this grants no metadata/recovery ACK.
    pub fn finish_cold(self,client:&Client)->Result<()> {
        self.context.check(client)?;
        if !self.selected_taken||!matches!(&self.context.mode,Mode::Cold){return Err(Error::Conflict)}
        self.context.check(client)
    }
    /// The selected-message view is not completion of metadata/refresh work.
    /// Move the same sealed original resource into the next Rust phase instead
    /// of dropping/acknowledging the original hint or immediately retrying it.
    pub fn into_metadata_continuation(self,client:&Client)->Result<OwnedBrowserMetadataContinuation>{
        self.context.check(client)?;
        if !self.selected_taken||self.local.is_some(){return Err(Error::Conflict)}
        Ok(OwnedBrowserMetadataContinuation{context:self.context,data:self.data,metadata_committed:false})
    }
}
/// Incomplete work, not a completion boolean or caller-reconstructed receipt.
/// Exact authenticated metadata, B physical readback/key and original hint stay
/// owned for the subsequent typed metadata CAS. Drop requeues only that hint.
#[doc(hidden)]
pub struct OwnedBrowserMetadataContinuation {context:Arc<Context>,data:RetainedData,metadata_committed:bool}
impl OwnedBrowserMetadataContinuation {
    pub fn check_original(&self,client:&Client)->Result<()> {
        self.context.check(client)?;
        if self.context.source_metadata.lock().map_err(|_|Error::Protocol)?.is_none()
            ||self.data.readback["metadata"].is_null(){return Err(Error::Protocol)}
        self.context.check(client)
    }
    pub fn cancel(&self){self.context.scope.observer().cancel();}
    pub async fn wait_cancelled(&self){self.context.cancelled().await}
    pub fn kind(&self)->&'static str{if self.metadata_committed{"original_hint_remainder"}else{self.context.metadata_kind()}}
    /// Consume only the same sealed resource. Already-committed work cannot be
    /// replayed as a fresh metadata source or acknowledged as full hint work.
    /// Opaque handoff only; no mode/capability/lease or completion is granted.
    /// Rust decides from the actual original hint, never a caller refresh flag.
    pub fn begin_original_refresh(self,client:&Client)->Result<OriginalHintRefreshAdmission>{
        hint_refresh::begin(self,client)
    }
    pub fn recovery_handoff(&self,client:&Client,job:&crate::client::CompletionRecoveryJob)->Result<Arc<OriginalHintRecoveryHandoff>> {
        if !self.metadata_committed{return Err(Error::Conflict)}
        OriginalHintRecoveryHandoff::capture(self.context.clone(),client,job)
    }
    pub fn begin_metadata(self,client:&Client)->Result<OwnedBrowserReadDriver> {
        self.check_original(client)?;
        if self.metadata_committed||!matches!(&self.context.mode,Mode::Incoming(_)){return Err(Error::Conflict)}
        let(send,pending)=mpsc::unbounded_channel();
        let context=self.context;
        let drain=Arc::new(DriverDrainState::for_context(&context));
        let channel=Channel{context:context.clone(),drain:drain.clone(),send};
        let future=Box::pin(async move{drive_metadata(channel,self.data).await.map(Outcome::Metadata)});
        Ok(OwnedBrowserReadDriver{context,future,pending,finished:false,drain})
    }
}
struct MetadataData {retained:RetainedData,output:Zeroizing<String>,physical:Plain<Value>}
/// Selected B metadata CAS is complete; refresh, other-chat, draft and recovery
/// work remain on the original hint. There is no full-hint completion accessor.
#[doc(hidden)]
pub struct OwnedBrowserMetadataPublication {context:Arc<Context>,data:MetadataData,taken:bool}
impl OwnedBrowserMetadataPublication {
    pub fn take(&mut self,client:&Client,consent:bool)->Result<Zeroizing<String>> {
        if !consent||self.taken{return Err(Error::Conflict)}
        self.context.check(client)?;
        if self.data.physical["record"].is_null(){return Err(Error::Protocol)}
        let result=Zeroizing::new(self.data.output.to_string());self.context.check(client)?;
        self.taken=true;Ok(result)
    }
    pub fn into_remainder(self,client:&Client)->Result<OwnedBrowserMetadataContinuation> {
        self.context.check(client)?;if !self.taken{return Err(Error::Conflict)}
        Ok(OwnedBrowserMetadataContinuation{context:self.context,data:self.data.retained,metadata_committed:true})
    }
}
async fn drive_metadata(channel:Channel,mut retained:RetainedData)->Result<MetadataData> {
    let ctx=channel.context.clone();ctx.negative()?;
    let desired=Plain::new((**ctx.source_metadata.lock().map_err(|_|Error::Protocol)?.as_ref().ok_or(Error::Protocol)?).clone());
    let host:BrowserMetadataCacheScope=serde_json::from_value(retained.plan["scope"].clone())?;
    let operation=uuid::Uuid::new_v4().to_string();
    let mut plan=Plain::new(json!({"version":1,"kind":"capture","operationId":operation,"scope":host,"owner":ctx.owner,"chatId":ctx.chat,"database":"chats_db","store":"chats","databaseVersion":null,"compareFields":super::super::PREDICATES,"expected":null,"patch":null}));
    let mut check=||ctx.negative();let io_channel=channel.clone();
    let mut io=move|encoded:String|{let channel=io_channel.clone();async move{channel.io(encoded).await}};
    let captured=super::super::execute_metadata_cache_io_budget(&plan,&mut check,&mut io,ctx.io_budget()).await?;
    if !captured["before"].is_null(){return Err(Error::Protocol)}
    let old=super::super::projection(&captured["record"],&ctx.chat,&ctx.owner,true)?;
    let normal=super::super::normalized(&old,&ctx.chat,&ctx.owner,false)?;
    let old_key=channel.validate_metadata(normal).await?;
    // The preceding actual selected physical readback must still be the exact
    // metadata row. Never apply a late source over a concurrent local edit.
    if captured["record"]!=retained.readback["metadata"]{return Err(Error::Conflict)}
    let keys=channel.clone();let validate=move|row:Plain<Value>|{let channel=keys.clone();async move{channel.validate_metadata(row).await}};
    let persisted=super::super::drive_metadata_persist_policy_budget(&ctx.owner,&ctx.chat,&desired,&old_key,
        &captured,&old,&mut plan,true,&mut check,validate,&mut io,ctx.io_budget()).await?;
    channel.validate_metadata(Plain::new((*persisted.effective).clone())).await?;
    let Resume::MetadataItem(item)=channel.apply(Work::MetadataItem{metadata:persisted.effective,key:old_key}).await?else{return Err(Error::Protocol)};
    let output=Plain::new(json!({"source":"browser_owned_selected_metadata_cache","metadataOnly":true,"cached":true,"fresh":false,"readOnly":true,
        "chat":&*item,"selectedChatId":ctx.chat,"metadataRowsPersisted":1,"pendingWork":"original_hint_remainder",
        "draftsPersisted":false,"inventoryComplete":false,"historyComplete":false,"messagesVersionAdvanced":false,
        "canonicalIncomingWindow":false,"credentialAcknowledged":false,"nativeDurabilityAcknowledged":false,
        "crossDatabaseAssociationProven":false,"recoveryProof":false}));
    let output=Zeroizing::new(serde_json::to_string(&*output)?);local_json::validate(&output)?;
    retained.readback["metadata"]=persisted.readback["record"].clone();ctx.negative()?;
    Ok(MetadataData{retained,output,physical:persisted.readback})
}
async fn drive(channel:Channel,host:BrowserMetadataCacheScope,now_seconds:u64)->Result<RetainedData> {
    let response=channel.read(ReadKind::Metadata).await?;
    let rows=response["chats"].as_array().ok_or(Error::Protocol)?;
    if rows.len()!=1||text(&rows[0],"id")!=channel.context.chat{return Err(Error::Forbidden)}
    let metadata=Plain::new(rows[0].clone());drop(response);
    let key=channel.unwrap(Plain::new((*metadata).clone()),KeyKind::Server).await?;
    let page=channel.read(ReadKind::Messages).await?;
    let Resume::Incoming(raw)=channel.apply(Work::Decode{metadata,key,page}).await? else{return Err(Error::Protocol)};
    let ctx=channel.context.clone();let mut check=||ctx.negative();
    let key_channel=channel.clone();let unwrap_key=move|metadata:Plain<Value>|{
        let channel=key_channel.clone();async move{channel.unwrap(metadata,KeyKind::Local).await}
    };
    let io_channel=channel.clone();let mut io=move|encoded:String|{
        let channel=io_channel.clone();async move{channel.io(encoded).await}
    };
    // Same actual bounded capture/CAS/readback policy as the ordinary wrapper.
    // Matching assistant cross-ID candidates explicitly refuse this subset;
    // no duplicate deletion/recovery/failure-cache permission is manufactured.
    let data=drive_incoming_cache_policy_budget(&ctx.owner,&ctx.chat,host,raw,true,true,
        Some(now_seconds),&mut check,unwrap_key,&mut io,ctx.io_budget()).await?;
    // A final full physical read, not just predicates, retains every local
    // journal, alias, extension and ciphertext through the last publication.
    let actual=execute_message_cache_io_budget(&data.plan,&mut check,&mut io,ctx.io_budget()).await?;
    if !actual["before"].is_null()||actual["metadata"]!=data.readback["metadata"]
        ||actual["rows"]!=data.readback["rows"]{return Err(Error::Conflict)}
    ctx.negative()?;Ok(data)
}
impl Client {
    fn begin_owned_browser_message_read(&mut self,mode:BeginMode,request:CancellationToken,
        owner:&str,chat:&str,options:crate::client::message_window::MessageWindowOptions,
        host:BrowserMetadataCacheScope,now_seconds:u64,include_private_output:bool,
    )->Result<OwnedBrowserReadDriver> {
        if !include_private_output{return Err(Error::Invalid("Explicit private output consent is required."))}
        if now_seconds>MAX_SAFE||host.lifecycle_generation==0||host.lifecycle_generation>MAX_SAFE||host.workspace_epoch>MAX_SAFE{return Err(Error::Protocol)}
        // Capture original principal/key/parent/request BEFORE the first await.
        let scope=Arc::new(OwnedOperationScope::capture(self,request)?);
        scope.crypto.check_chat(self,chat)?;
        let cursor_scope=self.message_window_scope()?;options.validate(chat,&cursor_scope)?;
        let profile_cache=match &mode{BeginMode::ProfileCache(profile)=>{profile.ensure_current(self)?;Some(profile.clone())},_=>None};
        self.metadata_cache_scope(owner,chat,if profile_cache.is_some(){BrowserMetadataCacheMode::Restore}else{BrowserMetadataCacheMode::PersistCurrent})?;
        let source=crate::client::browser::original_draft_bounds::source_stamp(self,chat)?;let floors=BrowserOwnedMetadataFloor::capture(self,chat)?;
        let local_first=matches!(&mode,BeginMode::LocalFirst|BeginMode::ProfileCache(_));
        if local_first&&(options.direction!=crate::client::message_window::MessageWindowDirection::Latest||options.cursor.is_some()||options.anchor_message_id.is_some()) {return Err(Error::Invalid("Owned local-first selected read requires the latest selector."))}
        let mode=match mode{
            BeginMode::Cold|BeginMode::LocalFirst|BeginMode::ProfileCache(_)=>Mode::Cold,
            BeginMode::Incoming(monitor)=>Mode::Incoming(self.browser_owned_monitor_read_context(scope.clone(),monitor,owner,chat)?),
            BeginMode::OriginalHint(monitor)=>Mode::Incoming(self.browser_owned_monitor_original_hint_context(scope.clone(),monitor,owner,chat)?),
        };
        let context=Arc::new(Context{profile_absence:Mutex::new(None),profile_cache,scope,mode,original:None,server_wrappers:None,owner:owner.into(),chat:chat.into(),cursor_scope,
            source:Mutex::new(source),floors:Mutex::new(floors),options,recovery_issued:Arc::new(Mutex::new(BTreeSet::new())),recovery_active:Arc::new(crate::client::completion_recovery::OriginalRecoveryActiveState::default()),refresh_issued:AtomicBool::new(false),inventory_issued:AtomicBool::new(false),inventory_drain:Arc::new(InventoryDrainState::default()),inventory_working_issued:Mutex::new(BTreeSet::new()),inventory_finished:AtomicBool::new(false),original_draft_budget:AtomicBool::new(crate::client::browser::original_draft_bounds::has_budget(self,chat)?),next:AtomicU64::new(1),outstanding:AtomicU64::new(0),evidence:Mutex::new(None),source_metadata:Mutex::new(None)});
        context.check(self)?;
        let(send,pending)=mpsc::unbounded_channel();let drain=Arc::new(DriverDrainState::for_context(&context));
        let channel=Channel{context:context.clone(),drain:drain.clone(),send};
        let future=Box::pin(async move{if local_first{local_first::drive(channel,host,now_seconds).await}else{drive(channel,host,now_seconds).await.map(Outcome::Selected)}});
        Ok(OwnedBrowserReadDriver{context,future,pending,finished:false,drain})
    }
    /// Explicit inactive cold retained page under the original admitted scope; no monitor or replacement socket is required.
    #[doc(hidden)]
    pub fn begin_owned_browser_cold_message_read(&mut self,request:CancellationToken,
        owner:&str,chat:&str,options:crate::client::message_window::MessageWindowOptions,
        host:BrowserMetadataCacheScope,now_seconds:u64,include_private_output:bool,
    )->Result<OwnedBrowserReadDriver>{self.begin_owned_browser_message_read(BeginMode::Cold,request,owner,chat,options,host,now_seconds,include_private_output)}
    /// Explicit browser selected latest-page policy. Native cache absence alone
    /// permits the unchanged cold read; IO/corruption/cancellation errors stay errors.
    #[doc(hidden)]
    pub fn begin_owned_browser_local_first_message_read(&mut self,request:CancellationToken,
        owner:&str,chat:&str,options:crate::client::message_window::MessageWindowOptions,
        host:BrowserMetadataCacheScope,now_seconds:u64,include_private_output:bool,
    )->Result<OwnedBrowserReadDriver>{self.begin_owned_browser_message_read(BeginMode::LocalFirst,request,owner,chat,options,host,now_seconds,include_private_output)}
    /// Inactive whole-original-hint entry. Recovery offers remain owned work;
    /// canonical selected publication cannot complete them or grant foreground.
    #[doc(hidden)]
    pub fn begin_owned_browser_original_hint_read(&mut self,monitor:Arc<ChatMonitor>,request:CancellationToken,
        owner:&str,chat:&str,options:crate::client::message_window::MessageWindowOptions,
        host:BrowserMetadataCacheScope,now_seconds:u64,include_private_output:bool,
    )->Result<OwnedBrowserReadDriver>{self.begin_owned_browser_message_read(BeginMode::OriginalHint(monitor),request,owner,chat,options,host,now_seconds,include_private_output)}
    /// Incoming work consumes only an actual original pending invalidation;
    /// dropped/failed work requeues that exact hint on that original monitor.
    #[doc(hidden)]
    pub fn begin_owned_browser_incoming_message_read(&mut self,monitor:Arc<ChatMonitor>,request:CancellationToken,
        owner:&str,chat:&str,options:crate::client::message_window::MessageWindowOptions,
        host:BrowserMetadataCacheScope,now_seconds:u64,include_private_output:bool,
    )->Result<OwnedBrowserReadDriver>{self.begin_owned_browser_message_read(BeginMode::Incoming(monitor),request,owner,chat,options,host,now_seconds,include_private_output)}
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_owned_message_read_tests.rs"]
mod tests;

#[cfg(target_arch="wasm32")]
#[doc(hidden)]
pub use hint_recovery::{BrowserOriginalHintRecoveryCheckpointReadiness,BrowserOriginalHintRecoveryCheckpointRead,BrowserOriginalHintRecoveryCheckpointReadResult,BrowserOriginalHintRecoveryCheckpointNativeWrite,BrowserOriginalHintRecoveryCheckpointNativeWriteResult,BrowserOriginalHintRecoveryCheckpointReadbackCrypto,BrowserOriginalHintRecoveryCheckpointVerified,BrowserOriginalHintRecoveryCheckpointDurable};

#[cfg(target_arch="wasm32")]
#[path="browser_original_draft_consumer.rs"]
mod native_draft_consumer;
#[cfg(target_arch="wasm32")]
#[doc(hidden)]
pub use native_draft_consumer::OriginalPhysicalDraftInventory;
