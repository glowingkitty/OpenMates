//! Bounded original-port ciphertext DATA prerequisite. Cursor EOF is not an
//! atomic profile inventory, deletion/freshness/durability or whole-hint ACK.
use super::*;
const KIND:&str="read_original_draft_inventory_page";
const REREAD_KIND:&str="reread_original_draft_inventory_row";
const PAGE_ROWS:usize=20;
const PAGE_BYTES:usize=2*1024*1024;
const KEY_BYTES:usize=4096;
pub(super) const FIELDS:&[&str]=&["chat_id","id","user_id","owner_id","hashed_user_id","team_id","hashed_team_id","chat_visibility","encrypted_chat_key","key_version","key_fingerprint","messages_v","draft_v","cleared_draft_v","encrypted_draft_md","encrypted_draft_preview","updated_at","last_edited_overall_timestamp","is_anonymous","is_shared","is_private"];
#[doc(hidden)]
pub struct OriginalHintDraftInventoryPrerequisite {batch:OriginalHintRefreshBatch,ticket:Arc<OriginalHintDraftInventoryTicket>}
#[doc(hidden)]
pub struct OriginalHintDraftInventoryTicket {
    context:Arc<Context>,operation:String,page:u64,after:Option<String>,row:Option<Plain<Value>>,database_version:Option<u64>,target:Option<String>,cancel:CancellationToken,claimed:AtomicBool,
}
#[doc(hidden)]
pub struct UntrustedDraftInventoryPageData {
    ticket:Arc<OriginalHintDraftInventoryTicket>,rows:Plain<Vec<Value>>,database_version:u64,last:Option<String>,exhausted:bool,
}
fn key(value:&Value)->Result<Option<String>>{match value{Value::Null=>Ok(None),Value::String(v) if v.len()<=KEY_BYTES=>Ok(Some(v.clone())),_=>Err(Error::Protocol)}}
impl OriginalHintRefreshBatch {
    pub fn begin_draft_inventory(self,client:&Client)->Result<OriginalHintDraftInventoryPrerequisite>{
        self.ensure_current(client)?;
        let ticket=Arc::new(OriginalHintDraftInventoryTicket{context:self.context.clone(),operation:uuid::Uuid::new_v4().to_string(),page:1,after:None,row:None,database_version:None,target:None,cancel:self.context.scope.child().child_token(),claimed:AtomicBool::new(false)});
        ticket.check_original(client)?;Ok(OriginalHintDraftInventoryPrerequisite{batch:self,ticket})
    }
}
impl OriginalHintDraftInventoryPrerequisite {
    pub fn first_ticket(&self,client:&Client)->Result<Arc<OriginalHintDraftInventoryTicket>>{self.batch.ensure_current(client)?;self.ticket.check_original(client)?;Ok(self.ticket.clone())}
    pub fn cancel(&self){self.ticket.cancel.cancel();}
    pub async fn wait_cancelled(&self){self.ticket.cancelled().await}
    // No finish/remainder/complete/import. NativePort's DISTINCT actual same-
    // port/ticket delivery consumer must drive continuation/hydration first.
}
impl OriginalHintDraftInventoryTicket {
    #[cfg(test)]
    pub(super) fn cancellation_for_test(&self)->CancellationToken{self.cancel.clone()}
    pub(crate) fn operation_id(&self)->&str{&self.operation}
    // Additional native-port negative after the genuine full original gate.
    // No callback/private output/current-Client/new scope or dispatch grant.
    pub(crate) fn check_original_negative(&self)->Result<()> {
        self.context.negative_without_gate()?;
        if self.cancel.is_cancelled(){return Err(Error::Cancelled)}
        self.context.negative_without_gate()?;
        if self.cancel.is_cancelled(){return Err(Error::Cancelled)}Ok(())
    }
    pub fn check_original(&self,client:&Client)->Result<()>{self.context.check(client)?;if let Some(target)=&self.target{self.context.scope.crypto.check_chat(client,target)?;}if let Some(row)=&self.row{self.context.scope.crypto.check_chat(client,required(row,"chat_id")?)?;}if self.cancel.is_cancelled(){return Err(Error::Cancelled)}self.context.negative()?;if self.cancel.is_cancelled(){return Err(Error::Cancelled)}Ok(())}
    pub fn effect_json(&self,client:&Client)->Result<Zeroizing<String>>{
        self.check_original(client)?;let effect=if let Some(target)=&self.target{json!({"version":1,"kind":REREAD_KIND,"operationId":self.operation,"page":self.page,"chatId":target})}else if let Some(row)=&self.row{json!({"version":1,"kind":REREAD_KIND,"operationId":self.operation,"page":self.page,"chatId":row["chat_id"]})}else{json!({"version":1,"kind":KIND,"operationId":self.operation,"page":self.page,"after":self.after,"maxRows":PAGE_ROWS,"maxBytes":PAGE_BYTES})};let out=Zeroizing::new(serde_json::to_string(&effect)?);self.check_original(client)?;Ok(out)
    }
    // Only the Core native-port owner may claim actual original dispatch. No
    // JS/JSON/status can call this or reopen a failed/abandoned claim.
    pub(crate) fn claim_dispatch(&self,client:&Client)->Result<()>{self.check_original(client)?;self.claimed.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;self.check_original(client)}
    // Native-port owner calls ONLY after consuming actual same-port/EXACT
    // ticket delivery. This makes another readonly DATA selector, never a
    // completeness/receipt or floor import. No public/raw cursor constructor.
    pub(crate) fn followup_from_native_data(self:&Arc<Self>,client:&Client,data:&UntrustedDraftInventoryPageData)->Result<Option<Arc<Self>>>{
        self.check_original(client)?;
        if self.target.is_some()||self.row.is_some()||!Arc::ptr_eq(self,&data.ticket){return Err(Error::Cancelled)}
        if !self.claimed.load(Ordering::Acquire){return Err(Error::Conflict)}
        if data.exhausted{return Ok(None)}
        let page=self.page.checked_add(1).filter(|page|*page<=MAX_SAFE).ok_or(Error::Protocol)?;
        let next=Arc::new(Self{context:self.context.clone(),operation:self.operation.clone(),page,after:data.last.clone(),row:None,database_version:None,target:None,cancel:self.cancel.clone(),claimed:AtomicBool::new(false)});
        next.check_original(client)?;Ok(Some(next))
    }
    pub(crate) async fn cancelled(&self){tokio::select!{_=self.cancel.cancelled()=>{},_=self.context.cancelled()=>{}}}
    // Exact row from original native page DATA, not a public caller selector.
    // Native owner must retain original actual Page observation and enforce it
    // across crypto before posting this DISTINCT readonly get ticket.
    pub(crate) fn reread_for_native_row(self:&Arc<Self>,client:&Client,data:&UntrustedDraftInventoryPageData,index:usize)->Result<Arc<Self>>{
        self.check_original(client)?;
        if self.target.is_some()||self.row.is_some()||!self.claimed.load(Ordering::Acquire)||!Arc::ptr_eq(self,&data.ticket){return Err(Error::Cancelled)}
        let row=data.rows.get(index).ok_or(Error::Protocol)?;let id=projection_data(row)?;
        if !uuid::Uuid::parse_str(id).is_ok_and(|uuid|uuid.to_string()==id){return Err(Error::Protocol)}
        self.context.scope.crypto.check_chat(client,id)?;
        let ticket=Arc::new(Self{context:self.context.clone(),operation:self.operation.clone(),page:self.page,after:None,row:Some(Plain::new(row.clone())),database_version:Some(data.database_version),target:None,cancel:self.cancel.clone(),claimed:AtomicBool::new(false)});
        ticket.check_original(client)?;Ok(ticket)
    }
    pub fn inspect_reread_data(self:&Arc<Self>,client:&Client,encoded:&str)->Result<UntrustedDraftInventoryRereadData>{
        self.check_original(client)?;let expected=self.row.as_ref().ok_or(Error::Protocol)?;
        if encoded.len()>PAGE_BYTES{return Err(Error::Protocol)}local_json::validate_original_draft_inventory(encoded)?;let frame=Plain::new(serde_json::from_str::<Value>(encoded)?);
        if !closed(&frame,&["version","kind","operationId","page","databaseVersion","row","transactionCommitted"])||frame["version"]!=1||frame["kind"]!=REREAD_KIND||frame["operationId"]!=self.operation||frame["page"].as_u64()!=Some(self.page)||frame["transactionCommitted"]!=true{return Err(Error::Protocol)}
        if Some(safe_number(&frame["databaseVersion"])?)!=self.database_version{return Err(Error::Conflict)}
        let row=if frame["row"].is_null(){None}else{if projection_data(&frame["row"])?!=projection_data(expected)?{return Err(Error::Protocol)}Some(Plain::new(frame["row"].clone()))};
        self.check_original(client)?;Ok(UntrustedDraftInventoryRereadData{ticket:self.clone(),row})
    }
    /// Parse untrusted ciphertext DATA only. transactionCommitted/EOF are never
    /// native event/port proof and cannot import floors or finish a hint.
    pub fn inspect_data(self:&Arc<Self>,client:&Client,encoded:&str)->Result<UntrustedDraftInventoryPageData>{
        self.check_original(client)?;if self.target.is_some()||self.row.is_some(){return Err(Error::Protocol)}if encoded.len()>PAGE_BYTES{return Err(Error::Protocol)}local_json::validate_original_draft_inventory(encoded)?;
        let frame=Plain::new(serde_json::from_str::<Value>(encoded)?);
        if !closed(&frame,&["version","kind","operationId","page","databaseVersion","rows","lastKey","cursorExhausted","transactionCommitted"])||frame["version"]!=1||frame["kind"]!=KIND||frame["operationId"]!=self.operation||frame["page"].as_u64()!=Some(self.page)||frame["transactionCommitted"]!=true{return Err(Error::Protocol)}
        let database_version=safe_number(&frame["databaseVersion"])?;if database_version==0{return Err(Error::Protocol)}
        let exhausted=frame["cursorExhausted"].as_bool().ok_or(Error::Protocol)?;let last=key(&frame["lastKey"])?;
        let rows=frame["rows"].as_array().filter(|rows|rows.len()<=PAGE_ROWS).ok_or(Error::Protocol)?;
        let mut previous=self.after.as_deref();
        for row in rows{
            let id=projection_data(row)?;
            if previous.is_some_and(|old|wire::idb_key_cmp(old,id)!=std::cmp::Ordering::Less){return Err(Error::Protocol)}
            previous=Some(id);
        }
        if last.as_deref()!=previous||(!exhausted&&rows.is_empty()){return Err(Error::Protocol)}
        let rows=Plain::new(rows.clone());self.check_original(client)?;
        Ok(UntrustedDraftInventoryPageData{ticket:self.clone(),rows,database_version,last,exhausted})
    }
}
impl UntrustedDraftInventoryPageData {
    pub fn rows_data<'a>(&'a self,client:&Client)->Result<&'a [Value]>{self.ticket.check_original(client)?;Ok(&self.rows)}
    pub fn cursor_data(&self,client:&Client)->Result<(Option<&str>,bool)>{self.ticket.check_original(client)?;Ok((self.last.as_deref(),self.exhausted))}
    pub fn database_version_data(&self,client:&Client)->Result<u64>{self.ticket.check_original(client)?;Ok(self.database_version)}
    // This type deliberately carries NO native-origin flag/receipt or positive
    // completeness. Future native delivery remains a distinct sealed domain.
}

fn projection_data(row:&Value)->Result<&str>{
    let object=row.as_object().ok_or(Error::Protocol)?;
    if object.keys().any(|field|!FIELDS.contains(&field.as_str())){return Err(Error::Protocol)}
    let id=row["chat_id"].as_str().filter(|id|id.len()<=KEY_BYTES).ok_or(Error::Protocol)?;
    if row.get("id").is_some_and(|value|!value.is_null()&&value.as_str()!=Some(id)){return Err(Error::Protocol)}
    for(field,value)in object{
        if value.is_null(){continue}
        if matches!(field.as_str(),"key_version"|"messages_v"|"draft_v"|"cleared_draft_v"|"updated_at"|"last_edited_overall_timestamp"){safe_number(value)?;}
        else if matches!(field.as_str(),"is_anonymous"|"is_shared"|"is_private"){if !value.is_boolean(){return Err(Error::Protocol)}}
        else if !value.is_string(){return Err(Error::Protocol)}
    }
    Ok(id)
}
#[doc(hidden)]
pub struct UntrustedDraftInventoryRereadData {ticket:Arc<OriginalHintDraftInventoryTicket>,row:Option<Plain<Value>>}
impl UntrustedDraftInventoryRereadData {
    pub fn row_data<'a>(&'a self,client:&Client)->Result<Option<&'a Value>>{self.ticket.check_original(client)?;Ok(self.row.as_ref().map(|row|&**row))}
    pub(crate) fn require_original_projection(&self,client:&Client)->Result<&Value>{
        self.ticket.check_original(client)?;let expected=self.ticket.row.as_ref().ok_or(Error::Protocol)?;let row=self.row.as_ref().ok_or(Error::Conflict)?;
        if **row!=**expected{return Err(Error::Conflict)}self.ticket.check_original(client)?;Ok(row)
    }
    // DATA comparison, never native origin/permission/floor import/delete ACK.
}


// DISTINCT original-known-row origin; no fabricated Page or caller DTO. The
// existing fixed readonly native row-get adapter already supports this effect.
pub(super) fn first_for_original_context(context:Arc<Context>,client:&Client,target:&str)->Result<Arc<OriginalHintDraftInventoryTicket>>{
    context.check(client)?;
    if target!=context.chat {
        let Mode::Incoming(monitor)=&context.mode else{return Err(Error::Forbidden)};
        if !monitor.original_draft_working_set()?.iter().any(|id|id==target){return Err(Error::Forbidden)}
    }
    context.scope.crypto.check_chat(client,target)?;
    let ticket=Arc::new(OriginalHintDraftInventoryTicket{context:context.clone(),operation:uuid::Uuid::new_v4().to_string(),page:1,after:None,row:None,database_version:None,target:Some(target.into()),cancel:context.scope.child().child_token(),claimed:AtomicBool::new(false)});
    ticket.check_original(client)?;Ok(ticket)
}
/// Untrusted row DATA only. Native original observation is a separate required
/// resource retained through Master, exact reread and final Client mutation.
pub(super) struct UntrustedOriginalDraftRowData {ticket:Arc<OriginalHintDraftInventoryTicket>,row:Option<Plain<Value>>,database_version:u64}
impl UntrustedOriginalDraftRowData {
    pub(super) fn row<'a>(&'a self,client:&Client)->Result<Option<&'a Value>>{self.ticket.check_original(client)?;Ok(self.row.as_ref().map(|row|&**row))}
}
impl OriginalHintDraftInventoryTicket {
    pub(super) fn inspect_original_row(self:&Arc<Self>,client:&Client,encoded:&str)->Result<UntrustedOriginalDraftRowData>{
        self.check_original(client)?;let target=self.target.as_ref().ok_or(Error::Protocol)?;
        local_json::validate_original_draft_inventory(encoded)?;let frame=Plain::new(serde_json::from_str::<Value>(encoded)?);
        if !closed(&frame,&["version","kind","operationId","page","databaseVersion","row","transactionCommitted"])||frame["version"]!=1||frame["kind"]!=REREAD_KIND||frame["operationId"]!=self.operation||frame["page"].as_u64()!=Some(self.page)||frame["transactionCommitted"]!=true{return Err(Error::Protocol)}
        let database_version=safe_number(&frame["databaseVersion"])?;if database_version==0{return Err(Error::Protocol)}
        let row=if frame["row"].is_null(){None}else{if projection_data(&frame["row"])?!=target{return Err(Error::Forbidden)}Some(Plain::new(frame["row"].clone()))};
        self.check_original(client)?;Ok(UntrustedOriginalDraftRowData{ticket:self.clone(),row,database_version})
    }
    pub(super) fn reread_original_row(self:&Arc<Self>,client:&Client,data:&UntrustedOriginalDraftRowData)->Result<Arc<Self>>{
        self.check_original(client)?;
        if self.target.is_none()||!self.claimed.load(Ordering::Acquire)||!Arc::ptr_eq(self,&data.ticket){return Err(Error::Cancelled)}
        let row=data.row.as_ref().ok_or(Error::Conflict)?;self.context.scope.crypto.check_chat(client,projection_data(row)?)?;
        let ticket=Arc::new(Self{context:self.context.clone(),operation:self.operation.clone(),page:self.page,after:None,row:Some(Plain::new((**row).clone())),database_version:Some(data.database_version),target:None,cancel:self.cancel.clone(),claimed:AtomicBool::new(false)});
        ticket.check_original(client)?;Ok(ticket)
    }
}
