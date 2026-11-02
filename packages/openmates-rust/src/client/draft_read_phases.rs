//! Shared strict Personal draft fallback decision phases. These are DATA and
//! original Client cache-policy operations, not socket/auth/IDB completion.
//! Native old API and original-monitor actor reuse these same exact decisions.
use super::*;
use crate::client::plaintext::{Plain,Wipe};
#[derive(Clone,Copy,PartialEq,Eq)]
enum Stage {First,Metadata,Final,Consumed}
pub(in crate::client) struct PreparedDraftFallback {
    pub(in crate::client) updates:Plain<BTreeMap<String,Value>>,
    pub(in crate::client) row:Option<Plain<Value>>,
}
pub(in crate::client) struct DraftFallbackPolicy {
    id:String,requested:Vec<(String,u64)>,first:BTreeMap<String,u64>,
    floors:BTreeMap<String,u64>,rows:Plain<BTreeMap<String,Value>>,
    final_requested:Vec<(String,u64)>,stage:Stage,
}
impl DraftFallbackPolicy {
    pub(in crate::client) fn capture(client:&Client,id:&str)->Result<Self>{
        Ok(Self{id:id.into(),requested:client.requested_draft_versions(&[id])?,
            first:BTreeMap::new(),floors:BTreeMap::new(),rows:Plain::new(BTreeMap::new()),
            final_requested:Vec::new(),stage:Stage::First})
    }
    pub(in crate::client) fn first_requested(&self)->&[(String,u64)]{&self.requested}
    pub(in crate::client) fn accept_first(&mut self,client:&Client,
        first:BTreeMap<String,u64>,first_tomb:BTreeMap<String,u64>,
    )->Result<Option<PreparedDraftFallback>> {
        if self.stage!=Stage::First{return Err(Error::Conflict)}self.stage=Stage::Consumed;
        // These maps must come from the SAME actual version-response parser,
        // never a host status/receipt. Caller retains original actor/fence.
        if first.get(&self.id)==Some(&0){
            let updates=client.prepare_draft_versions(&self.requested,&first,&first_tomb)?;
            self.stage=Stage::Consumed;return Ok(Some(PreparedDraftFallback{updates:Plain::new(updates),row:None}));
        }
        self.floors=observed_draft_floors(&self.requested,&first,&first_tomb);
        self.first=first;self.stage=Stage::Metadata;Ok(None)
    }
    pub(in crate::client) fn accept_metadata(&mut self,client:&Client,rows:BTreeMap<String,Value>)->Result<()> {
        if self.stage!=Stage::Metadata{return Err(Error::Conflict)}self.stage=Stage::Consumed;
        // Own even rejected server extensions before any policy check.
        let rows=Plain::new(rows);
        drop(Plain::new(client.prepare_draft_metadata_at(&rows,&self.floors,&self.first)?));
        self.final_requested=self.requested.iter().map(|(id,old)|
            (id.clone(),self.floors.get(id).copied().unwrap_or(*old))).collect();
        self.rows=rows;self.stage=Stage::Final;Ok(())
    }
    pub(in crate::client) fn final_requested(&self)->Result<&[(String,u64)]>{
        if self.stage!=Stage::Final{return Err(Error::Conflict)}Ok(&self.final_requested)
    }
    pub(in crate::client) fn accept_final(mut self,client:&Client,
        final_versions:BTreeMap<String,u64>,final_tomb:BTreeMap<String,u64>,
    )->Result<PreparedDraftFallback>{
        if self.stage!=Stage::Final{return Err(Error::Conflict)}self.stage=Stage::Consumed;
        if final_versions.get(&self.id)==Some(&0){
            let updates=client.prepare_draft_versions_at(&self.requested,&final_versions,&final_tomb,&self.floors)?;
            return Ok(PreparedDraftFallback{updates:Plain::new(updates),row:None});
        }
        let row=self.rows.get(&self.id).filter(|row|row["encrypted_draft_md"].is_string()).ok_or(Error::Offline)?;
        let version=draft_version(row)?;
        if final_versions.get(&self.id)!=Some(&version){return Err(Error::Conflict)}
        client.check_draft_regression(client.chats.get(&self.id),row)?;
        let mut updates=client.prepare_draft_versions_at(&self.requested,&final_versions,&final_tomb,&self.floors)?;
        updates.insert(self.id.clone(),merge_draft_fields(client.chats.get(&self.id),row)?);
        Ok(PreparedDraftFallback{updates:Plain::new(updates),row:Some(Plain::new(row.clone()))})
    }
}
// Actual version parser is reused by both the native wire loop and the owned
// actor. Data alone does not authorize apply/publication or clear a whole chat.
pub(in crate::client) struct DraftVersionsRead {
    requested:Vec<(String,u64)>,next:usize,failed:bool,versions:BTreeMap<String,u64>,tombstones:BTreeMap<String,u64>,
}
impl DraftVersionsRead {
    pub(in crate::client) fn new(requested:&[(String,u64)])->Self{Self{requested:requested.to_vec(),next:0,failed:false,versions:BTreeMap::new(),tombstones:BTreeMap::new()}}
    pub(in crate::client) fn next_chunk(&self)->Option<&[(String,u64)]>{if self.next>=self.requested.len(){None}else{Some(&self.requested[self.next..self.requested.len().min(self.next+200)])}}
    pub(in crate::client) fn accept(&mut self,response:&Value)->Result<()> {
        let end=self.requested.len().min(self.next+200);if self.failed||self.next>=end{return Err(Error::Conflict)}self.failed=true;
        parse_versions(response,&self.requested[self.next..end],&mut self.versions,&mut self.tombstones)?;self.next=end;self.failed=false;Ok(())
    }
    pub(in crate::client) fn finish(self)->Result<(BTreeMap<String,u64>,BTreeMap<String,u64>)>{
        if self.failed||self.next!=self.requested.len(){return Err(Error::Protocol)}Ok((self.versions,self.tombstones))
    }
}
#[cfg(test)]
#[path="draft_read_phases_tests.rs"]
mod tests;
