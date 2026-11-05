//! Original native selected/known-hint draft hydration. No all-cache scan.
//! Untrusted DATA has no deletion,
//! inventory freshness, canonical history or whole-hint completion meaning.
use super::*;
use crate::platform::browser_recovery_port::{OriginalBrowserRecoveryPort,NativeDraftInventoryObservation,NativeDraftInventoryPortPending,NativeDraftInventoryPortDelivery};
use crate::sdk_drafts::EncryptedDraftRecord;
use zeroize::Zeroize;

enum Phase {Ready,Start,OriginPending(NativeDraftInventoryPortPending),OriginDelivered(NativeDraftInventoryPortDelivery),Prepare,Decrypt,Decrypted,RowPending(NativeDraftInventoryPortPending),RowDelivered(NativeDraftInventoryPortDelivery),Hydrate,Finished,Refused}
struct Row {
    id:String,before:Plain<Option<Value>>,after:Plain<Value>,physical:Plain<Value>,
    ticket:Arc<OriginalHintDraftInventoryTicket>,master:Option<MasterCapability>,encrypted:Option<EncryptedDraftRecord>,crypto_verified:bool,
}
/// One opaque original consumer; errors retain its observations and exact
/// resources. There is deliberately no retry/reset/rearm or JSON completion.
#[doc(hidden)]
pub struct OriginalPhysicalDraftInventory {
    context:Arc<Context>,port:OriginalBrowserRecoveryPort,ticket:Arc<OriginalHintDraftInventoryTicket>,
    origin:Option<NativeDraftInventoryObservation>,data:Option<draft_inventory::UntrustedOriginalDraftRowData>,
    row:Option<Row>,reread:Option<NativeDraftInventoryObservation>,primary:bool,phase:Phase,
    held:Option<InventoryLease>,
}
impl OwnedBrowserReadDriver {
    /// Same original driver, profile, scope and native Root. Run before polling
    /// its first read; no replacement Client/actor batch or caller row is used.
    pub fn begin_physical_draft_inventory(&self,client:&Client,port:&OriginalBrowserRecoveryPort)->Result<OriginalPhysicalDraftInventory>{
        // This separate local-only facet cannot fall back, hydrate/write or
        // advance draft floors; it reads the original physical row twice.
        if self.context.profile_cache.is_some(){return Err(Error::Forbidden)}
        if self.finished||self.context.original.is_some()||self.context.next.load(Ordering::Acquire)!=1||self.context.outstanding.load(Ordering::Acquire)!=0{return Err(Error::Conflict)}
        self.context.check(client)?;port.check_original(client)?;
        self.context.inventory_issued.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;
        let ticket=draft_inventory::first_for_original_context(self.context.clone(),client,&self.context.chat)?;
        port.check_negative()?;ticket.check_original_negative()?;
        let held=Some(InventoryLease::begin(self.context.inventory_drain.clone())?);
        Ok(OriginalPhysicalDraftInventory{context:self.context.clone(),port:port.clone(),ticket,origin:None,data:None,row:None,reread:None,primary:true,phase:Phase::Ready,held})
    }
}
impl OriginalPhysicalDraftInventory {
    pub fn kind(&self)->&'static str {match self.phase {
        Phase::Start|Phase::OriginDelivered(_)|Phase::Prepare|Phase::Decrypted|Phase::RowDelivered(_)|Phase::Hydrate=>"apply",
        Phase::Ready|Phase::OriginPending(_)|Phase::RowPending(_)|Phase::Decrypt=>"drive",
        Phase::Finished=>"original_physical_draft_rows_hydrated",Phase::Refused=>"retained_failure",
    }}
    pub fn cancel(&self){self.context.scope.observer().cancel();}
    pub async fn wait_cancelled(&self){self.context.cancelled().await;}
    fn negative(&self)->Result<()> {
        self.port.check_negative()?;self.ticket.check_original_negative()?;
        if let Some(origin)=&self.origin{origin.check_original_negative()?;}
        if let Some(row)=&self.reread{row.check_original_negative()?;}
        self.context.negative_without_gate()
    }
    fn current(&self,client:&Client)->Result<()> {
        self.context.check(client)?;self.port.check_original(client)?;self.ticket.check_original(client)?;
        if let Some(origin)=&self.origin{origin.check_original(client)?;}
        if let Some(row)=&self.reread{row.check_original(client)?;}
        self.negative()
    }
    /// Only actual native IO or the captured Master is awaited; no Client is
    /// held, and WebCrypto/native pending work is never select-dropped.
    pub async fn drive(&mut self)->Result<()> {
        let phase=std::mem::replace(&mut self.phase,Phase::Refused);
        let result=match phase {
            Phase::Ready=>tokio::select!{biased;_=self.context.cancelled()=>Err(Error::Cancelled),result=self.port.inventory_ready()=>result.and_then(|_|self.negative()).map(|_|Phase::Start)},
            Phase::OriginPending(pending)=>pending.drive().await.map(Phase::OriginDelivered),
            Phase::RowPending(pending)=>pending.drive().await.map(Phase::RowDelivered),
            Phase::Decrypt=>self.decrypt().await.map(|_|Phase::Decrypted),
            other=>{self.phase=other;return Err(Error::Conflict)},
        };
        match result {Ok(phase)=>{self.phase=phase;Ok(())},Err(error)=>Err(error)}
    }
    async fn decrypt(&mut self)->Result<()> {
        self.negative()?;
        let row=self.row.as_mut().ok_or(Error::Protocol)?;
        let encrypted=row.encrypted.take().ok_or(Error::Protocol)?;
        let master=row.master.as_ref().ok_or(Error::Protocol)?;
        // Exact existing Master draft envelope/preview contract; no chat key,
        // username enrollment or new wrapper prerequisite is introduced.
        let mut plaintext=encrypted.decrypt_with_master_capability(master).await?;
        // No plaintext escapes or is retained in Client, bindings, observations
        // or diagnostics, including cancellation after the actual crypto await.
        plaintext.markdown.zeroize();plaintext.preview.zeroize();
        self.row.as_mut().ok_or(Error::Protocol)?.crypto_verified=true;
        self.negative()
    }
    pub fn apply(&mut self,client:&mut Client)->Result<()> {
        self.current(client)?;
        let phase=std::mem::replace(&mut self.phase,Phase::Refused);
        let result=match phase {
            Phase::Start=>self.port.start_draft_inventory(client,self.ticket.clone()).map(Phase::OriginPending),
            Phase::OriginDelivered(delivery)=>(||{
                let origin=delivery.consume_for(&self.port,&self.ticket)?;origin.check_original(client)?;
                self.origin=Some(origin);
                let data=self.ticket.inspect_original_row(client,self.origin.as_ref().ok_or(Error::Protocol)?.data(client)?)?;
                self.data=Some(data);Ok(Phase::Prepare)
            })(),
            Phase::Prepare=>self.prepare_row(client),
            Phase::Decrypted=>self.start_reread(client),
            Phase::RowDelivered(delivery)=>(||{
                let row=self.row.as_ref().ok_or(Error::Protocol)?;
                let observed=delivery.consume_for(&self.port,&row.ticket)?;
                self.origin.as_ref().ok_or(Error::Protocol)?.check_original(client)?;
                observed.check_original(client)?;self.reread=Some(observed);
                let data=row.ticket.inspect_reread_data(client,self.reread.as_ref().ok_or(Error::Protocol)?.data(client)?)?;
                data.require_original_projection(client)?;Ok(Phase::Hydrate)
            })(),
            Phase::Hydrate=>self.hydrate(client),
            other=>{self.phase=other;return Err(Error::Conflict)},
        };
        match result {Ok(phase)=>{self.phase=phase;Ok(())},Err(error)=>Err(error)}
    }
    fn finish(&mut self)->Phase {
        if let Some(held)=self.held.take(){held.settled();}
        if self.primary{self.context.inventory_finished.store(true,Ordering::Release);}
        Phase::Finished
    }
    fn prepare_row(&mut self,client:&Client)->Result<Phase> {
        self.current(client)?;
        let data=self.data.as_ref().ok_or(Error::Protocol)?;
        let physical=data.row(client)?;self.negative()?;
        let Some(physical)=physical else{return Ok(self.finish())};
        let id=required(physical,"chat_id")?.to_owned();
        client.validate_original_physical_draft_scope(physical,&id)?;self.context.scope.crypto.check_chat(client,&id)?;
        let draft=physical.get("draft_v").filter(|v|!v.is_null()).map(safe_number).transpose()?.unwrap_or(0);
        let clear=physical.get("cleared_draft_v").filter(|v|!v.is_null()).map(safe_number).transpose()?.unwrap_or(0);
        let cipher=match physical.get("encrypted_draft_md"){None|Some(Value::Null)=>None,Some(Value::String(value))=>if value.is_empty(){None}else{Some(value.as_str())},_=>return Err(Error::Protocol)};
        // Empty/no-draft rows and EOF make no absence/deletion claim.
        if cipher.is_none()&&clear==0{self.negative()?;return Ok(self.finish())}
        let before=Plain::new(client.chats.get(&id).cloned());
        let server=before.as_ref().cloned().unwrap_or_else(||json!({"id":id}));
        let after=Plain::new(client.merge_original_physical_draft_cache(&self.context.scope,&id,&server,physical,before.as_ref())?);
        crate::client::browser::original_draft_bounds::validate_row(&after)?;
        let ticket=self.ticket.reread_original_row(client,data)?;
        let (master,encrypted)=if let Some(cipher)=cipher{
            if draft==0{return Err(Error::Protocol)}
            let preview=physical.get("encrypted_draft_preview").filter(|v|!v.is_null()).map(|v|v.as_str().map(str::to_owned).ok_or(Error::Protocol)).transpose()?;
            (Some(client.master_capability()?),Some(EncryptedDraftRecord{chat_id:id.clone(),encrypted_draft_md:cipher.into(),encrypted_draft_preview:preview,draft_v:draft}))
        }else{(None,None)};
        // Cleared-only negative floor needs no ciphertext/wrapped chat key.
        self.row=Some(Row{id,before,after,physical:Plain::new(physical.clone()),ticket,master,crypto_verified:encrypted.is_none(),encrypted});
        self.current(client)?;
        if self.row.as_ref().is_some_and(|r|r.encrypted.is_some()){Ok(Phase::Decrypt)}else{self.start_reread(client)}
    }
    fn start_reread(&self,client:&Client)->Result<Phase>{
        self.current(client)?;let row=self.row.as_ref().ok_or(Error::Protocol)?;
        if client.chats.get(&row.id)!=row.before.as_ref(){return Err(Error::Conflict)}
        self.port.start_draft_inventory(client,row.ticket.clone()).map(Phase::RowPending)
    }
    pub(crate) fn verified_draft_row<'a>(&'a self,client:&Client)->Result<(&'a str,&'a Value,&'a Value,Option<&'a MasterCapability>)>{
        self.current(client)?;let row=self.row.as_ref().ok_or(Error::Protocol)?;
        if !row.crypto_verified||client.chats.get(&row.id)!=row.before.as_ref(){return Err(Error::Conflict)}
        let origin=self.origin.as_ref().ok_or(Error::Protocol)?;
        let first=self.ticket.inspect_original_row(client,origin.data(client)?)?;
        if first.row(client)?!=Some(&*row.physical){return Err(Error::Conflict)}
        let reread=self.reread.as_ref().ok_or(Error::Protocol)?;
        let data=row.ticket.inspect_reread_data(client,reread.data(client)?)?;
        if data.require_original_projection(client)?!=&*row.physical{return Err(Error::Conflict)}
        self.negative()?;Ok((&row.id,&row.after,&row.physical,row.master.as_ref()))
    }
    fn hydrate(&mut self,client:&mut Client)->Result<Phase>{
        self.current(client)?;
        let row=self.row.as_ref().ok_or(Error::Protocol)?;
        if client.chats.get(&row.id)!=row.before.as_ref(){return Err(Error::Conflict)}
        // Retain BOTH actual original selected-row and exact Row observations through the final
        // synchronous same-Client encrypted-row CAS. DATA alone cannot enter.
        self.origin.as_ref().ok_or(Error::Protocol)?.check_original(client)?;
        self.reread.as_ref().ok_or(Error::Protocol)?.check_original(client)?;
        let permit=crate::client::browser::original_draft_bounds::OriginalPhysicalDraftBounds::capture(client,self)?;
        let stamp=crate::client::browser::original_draft_bounds::stamp_row(&Some(&*row.after))?;
        let mut anchor=if row.id==self.context.chat{Some(self.context.source.lock().map_err(|_|Error::Protocol)?)}else{None};
        self.negative()?;
        client.chat_list_freshness.invalidate();client.invalidate_chat_inventory_proofs();
        if let Some(old)=client.insert_chat_row(row.id.clone(),(*row.after).clone()){drop(Plain::new(old));}
        client.original_physical_draft_bounds.insert(row.id.clone(),permit);
        if let Some(anchor)=&mut anchor{**anchor=stamp;}
        drop(anchor);
        if row.id==self.context.chat{self.context.original_draft_budget.store(true,Ordering::Release);*self.context.floors.lock().map_err(|_|Error::Protocol)?=BrowserOwnedMetadataFloor::capture(client,&row.id)?;}
        self.current(client)?;
        self.row.take();self.reread.take();Ok(self.finish())
    }
}
impl Drop for OriginalPhysicalDraftInventory {fn drop(&mut self){if !matches!(self.phase,Phase::Finished){self.context.scope.observer().cancel();}}}

impl OwnedBrowserMetadataContinuation {
    /// After selected publication only. Actual original hint selectors, at most
    ///20 rows; no global local-cache enumeration, actor DTO or full-hint ACK.
    pub fn begin_next_physical_draft_inventory(&self,client:&Client,port:&OriginalBrowserRecoveryPort)->Result<Option<OriginalPhysicalDraftInventory>>{
        self.check_original(client)?;port.check_original(client)?;
        let Mode::Incoming(monitor)=&self.context.mode else{return Ok(None)};
        let rows=monitor.original_draft_working_set()?;
        let mut issued=self.context.inventory_working_issued.lock().map_err(|_|Error::Protocol)?;
        let Some(target)=rows.into_iter().find(|id|!issued.contains(id))else{drop(issued);port.check_negative()?;self.context.negative_without_gate()?;return Ok(None)};
        // Issuing cannot be silently rearmed by failure, drop or lost delivery.
        issued.insert(target.clone());drop(issued);
        let ticket=draft_inventory::first_for_original_context(self.context.clone(),client,&target)?;
        port.check_negative()?;ticket.check_original_negative()?;
        Ok(Some(OriginalPhysicalDraftInventory{context:self.context.clone(),port:port.clone(),ticket,origin:None,data:None,row:None,reread:None,primary:false,phase:Phase::Ready,held:Some(InventoryLease::begin(self.context.inventory_drain.clone())?)}))
    }
}
