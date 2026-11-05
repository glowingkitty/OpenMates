//! Opaque per-row metadata facet receipt. No count/DTO/Clone/serde can mark a
//! hint handled; this ledger has NO whole-hint completion/ACK operation.
use super::*;
#[derive(Default)]
pub(super) struct RowLedger {next:AtomicU64,entries:Mutex<BTreeMap<String,Entry>>}
struct Entry {ticket:u64,row:String,source:String,draft:bool,metadata_applied:bool}
impl RowLedger {
    #[cfg(test)]
    pub(super) fn metadata_for_test(&self,id:&str)->bool{self.entries.lock().unwrap().get(id).is_some_and(|entry|entry.metadata_applied)}
    pub(super) fn issue(&self,id:&str,row:&Value,source:&str,draft:bool)->Result<u64>{
        let ticket=self.next.fetch_update(Ordering::AcqRel,Ordering::Acquire,|n|n.checked_add(1).filter(|n|*n<=MAX_SAFE)).map_err(|_|Error::Protocol)?+1;
        let mut entries=self.entries.lock().map_err(|_|Error::Protocol)?;
        if entries.contains_key(id){return Err(Error::Conflict)}
        entries.insert(id.into(),Entry{ticket,row:sha256(&serde_json::to_string(row)?),source:source.into(),draft,metadata_applied:false});Ok(ticket)
    }
    fn pending(&self,seed:&OriginalHintRowSeed)->Result<()> {
        let entries=self.entries.lock().map_err(|_|Error::Protocol)?;let entry=entries.get(&seed.id).ok_or(Error::Cancelled)?;
        if entry.ticket!=seed.ticket||entry.row!=sha256(&serde_json::to_string(&*seed.row)?)||entry.source!=seed.source||entry.draft||entry.metadata_applied{return Err(Error::Conflict)}Ok(())
    }
}
#[doc(hidden)]
pub struct OriginalHintMetadataApplied {
    context:Arc<Context>,root:Arc<Context>,ledger:Arc<RowLedger>,ticket:u64,id:String,
    after:Plain<Value>,physical:Plain<Value>,
}
impl OriginalHintMetadataApplied {
    #[cfg(test)]
    pub(super) fn check_for_test(&self,client:&Client)->Result<()>{self.check(client)}
    fn check(&self,client:&Client)->Result<()> {
        self.root.check(client)?;self.context.check(client)?;
        if client.chats.get(&self.id)!=Some(&*self.after){return Err(Error::Conflict)}self.context.negative()
    }
}
impl OriginalHintRowMetadataPublication {
    pub fn apply(self,client:&mut Client)->Result<OriginalHintMetadataApplied>{
        self.ensure_current(client)?;let seed=&self.data.seed;seed.ledger.pending(seed)?;
        let root=seed.context.clone();let before=client.chats.get(&seed.id).cloned();
        if before.as_ref()!=seed.before.as_ref(){return Err(Error::Conflict)}
        let physical=Plain::new(self.data.metadata.physical["record"].clone());
        // The full actual metadata readback came through shared native policy;
        // it must still be the exact retained physical metadata projection.
        if *physical!=self.data.metadata.retained.readback["metadata"]{return Err(Error::Conflict)}
        root.check(client)?;self.context.check(client)?;
        let after=Plain::new(client.merge_original_physical_draft_cache(&self.context.scope,&seed.id,&seed.row,&physical,before.as_ref())?);
        crate::client::browser::original_draft_bounds::validate_adopted_row(client,&seed.id,&after)?;
        // No caller gates while holding source locks. Revocation cannot turn
        // an already authorized own mutation into a rollback/global restore.
        let mut target_anchor=self.context.source.lock().map_err(|_|Error::Protocol)?;
        if *target_anchor!=seed.source{return Err(Error::Conflict)}
        let mut selected_anchor=if seed.id==root.chat{Some(root.source.lock().map_err(|_|Error::Protocol)?)}else{None};
        if selected_anchor.as_ref().is_some_and(|anchor|anchor.as_str()!=seed.source.as_str()){return Err(Error::Conflict)}
        self.context.negative_without_gate()?;
        client.chat_list_freshness.invalidate();client.invalidate_chat_inventory_proofs();
        if let Some(old)=client.insert_chat_row(seed.id.clone(),(*after).clone()){drop(Plain::new(old));}
        let stamp=crate::client::browser::original_draft_bounds::source_stamp(client,&seed.id)?;*target_anchor=stamp.clone();if let Some(anchor)=&mut selected_anchor{**anchor=stamp;}
        drop(selected_anchor);drop(target_anchor);
        if let Err(error)=self.context.check(client){self.context.scope.observer().cancel();return Err(error)}
        let applied=OriginalHintMetadataApplied{context:self.context.clone(),root,ledger:seed.ledger.clone(),ticket:seed.ticket,id:seed.id.clone(),after,physical};
        applied.check(client)?;Ok(applied)
    }
}
impl OriginalHintRefreshBatch {
    pub fn acknowledge_metadata(&mut self,client:&Client,applied:OriginalHintMetadataApplied)->Result<()> {
        self.ensure_current(client)?;applied.check(client)?;
        if !Arc::ptr_eq(&self.context,&applied.root)||!Arc::ptr_eq(&self.ledger,&applied.ledger){return Err(Error::Cancelled)}
        let mut entries=self.ledger.entries.lock().map_err(|_|Error::Protocol)?;
        let entry=entries.get_mut(&applied.id).ok_or(Error::Cancelled)?;
        if entry.ticket!=applied.ticket||entry.draft||entry.metadata_applied{return Err(Error::Conflict)}
        self.context.negative_without_gate()?;
        if applied.id==self.context.chat{self.retained.readback["metadata"]=(*applied.physical).clone();}
        entry.metadata_applied=true;Ok(())
    }
    // No all-done/finish/ACK: metadata facet alone cannot certify startup
    // windows, drafts, sidecars, omitted hints, rescan or recovery/local commit.
}
