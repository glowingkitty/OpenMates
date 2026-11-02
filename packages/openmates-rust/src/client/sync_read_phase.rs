//! Shared ordinary/owned-actor ciphertext phase parsing. DATA only: neither
//! a frame, completion marker nor this accumulator is auth/freshness/IO proof.
use super::*;
use std::collections::BTreeSet;
use crate::client::plaintext::{Plain,Wipe};
use crate::client::sync_windows::Phase1Windows;

#[allow(clippy::too_many_arguments)] // Exact existing internal parser fields.
pub(super) fn accept_sync_ciphertext_frame(
    k:&str,p:&Value,team:Option<&str>,phase1_windows:&mut Phase1Windows,
    chats:&mut BTreeMap<String,Value>,chat_arrival_order:&mut Vec<String>,
    wrappers:&mut Vec<Value>,embeds:&mut BTreeMap<String,Value>,embed_keys:&mut Vec<Value>,
    metadata_seen:&mut bool,sync_done:&mut bool,
)->Result<()> {
    accept_sync_ciphertext_frame_at_epoch(k,p,team,crate::client::sync_windows::REQUEST_CONTEXT_EPOCH,
        phase1_windows,chats,chat_arrival_order,wrappers,embeds,embed_keys,metadata_seen,sync_done)
}
#[allow(clippy::too_many_arguments)] // Same internal fields plus echoed request.
pub(super) fn accept_sync_ciphertext_frame_at_epoch(
    k:&str,p:&Value,team:Option<&str>,expected_epoch:u64,phase1_windows:&mut Phase1Windows,
    chats:&mut BTreeMap<String,Value>,chat_arrival_order:&mut Vec<String>,
    wrappers:&mut Vec<Value>,embeds:&mut BTreeMap<String,Value>,embed_keys:&mut Vec<Value>,
    metadata_seen:&mut bool,sync_done:&mut bool,
)->Result<()> {
                if matches!(k, "sync_metadata_chats_response" | "load_more_chats_response") {
                    // Return before generic sidecar capture: metadata pages can
                    // never smuggle message/embed/key work into startup content.
                    return phase1_windows.metadata_response_with_expected_epoch(k,p,team,expected_epoch,chats);
                }
                match k {
                    "phase_1_last_chat_ready" => phase1_windows.metadata_with_expected_epoch(&p, team,expected_epoch)?,
                    "phase_1b_chat_content_ready" => phase1_windows.content_with_expected_epoch(&p, team,expected_epoch)?,
                    _ => {},
                }
                if let Some(rows) = p["embeds"].as_array() {
                    for row in rows {
                        let id = row
                            .get("embed_id")
                            .or_else(|| row.get("id"))
                            .and_then(Value::as_str)
                            .ok_or(Error::Protocol)?;
                        embeds.insert(id.to_owned(), row.clone());
                    }
                }
                if let Some(rows) = p["embed_keys"].as_array() {
                    embed_keys.extend(rows.iter().cloned())
                }
                if let Some(rows) = p["chat_key_wrappers"].as_array() {
                    wrappers.extend(rows.iter().cloned())
                }
                if k == "phase_2_last_20_chats_ready" {
                    *metadata_seen = true;
                    for wrapper in p["chats"].as_array().ok_or(Error::Protocol)? {
                        let row = wrapper.get("chat_details").ok_or(Error::Protocol)?;
                        let id = required(row, "id")?;
                        if !chats.contains_key(id) { chat_arrival_order.push(id.to_owned()); }
                        chats.insert(id.to_owned(), row.clone());
                    }
                }
                if matches!(k,"phase_1_last_chat_ready"|"phase_2_last_20_chats_ready") { phase1_windows.validate_metadata_budget(chats)?; }
                if k == "phased_sync_complete" {
                    *sync_done = true
                }
    Ok(())
}
/// No constructor from a DTO receipt or public status. Even completed parser
/// data needs an actual original-monitor actor receipt and full owned scope
/// before any Client/IDB mutation or UI output.
#[derive(Default)]
pub(in crate::client) struct SyncPhaseReadData {
    pub(in crate::client) chats:BTreeMap<String,Value>,
    pub(in crate::client) chat_arrival_order:Vec<String>,
    pub(in crate::client) wrappers:Vec<Value>,
    pub(in crate::client) embeds:BTreeMap<String,Value>,
    pub(in crate::client) embed_keys:Vec<Value>,
    pub(in crate::client) phase1_windows:Phase1Windows,
    pub(in crate::client) expanded_only_chat_ids:BTreeSet<String>,
}
impl SyncPhaseReadData {
    pub(in crate::client) fn retained_navigation_bytes(&self)->Result<usize>{
        let limit=crate::client::transport::MAX_BODY;
        let direct=super::super::monitor::cached_view::bounded_bytes(&(&self.chats,&self.chat_arrival_order,&self.expanded_only_chat_ids),limit).ok_or(Error::Protocol)?;
        let phase=self.phase1_windows.retained_navigation_bytes(limit.saturating_sub(direct))?;
        direct.checked_add(phase).filter(|bytes|*bytes<=limit).ok_or(Error::Protocol)
    }
}
impl Wipe for SyncPhaseReadData {
    fn wipe(&mut self){self.chats.wipe();self.chat_arrival_order.wipe();self.wrappers.wipe();self.embeds.wipe();self.embed_keys.wipe();self.phase1_windows.wipe();for mut id in std::mem::take(&mut self.expanded_only_chat_ids){id.wipe();}}
}
pub(in crate::client) struct ReadOnlySyncPhase {
    expected_epoch:u64,data:Plain<SyncPhaseReadData>,metadata_seen:bool,sync_done:bool,recovery_marker:bool,
}
impl ReadOnlySyncPhase {
    pub(in crate::client) fn new(expected_epoch:u64)->Result<Self> {
        if expected_epoch>9_007_199_254_740_991{return Err(Error::Protocol)}
        Ok(Self{expected_epoch,data:Plain::new(SyncPhaseReadData::default()),metadata_seen:false,sync_done:false,recovery_marker:false})
    }
    pub(in crate::client) fn accept(&mut self,kind:&str,payload:&Value,team:Option<&str>)->Result<()> {
        if self.terminal_markers_received(){return Err(Error::Conflict)}
        // Correlation is DATA routing only; the original actor/socket/scope is
        // still mandatory. Zero preserves the ordinary legacy/default parser.
        if self.expected_epoch!=0&&(kind.starts_with("phase_")||kind=="phased_sync_complete"||matches!(kind,"sync_metadata_chats_response"|"load_more_chats_response")){
            if payload["context_epoch"].as_u64()!=Some(self.expected_epoch){return Ok(())}
            match payload.get("team_id"){
                Some(Value::Null) if team.is_none()=>{},
                Some(Value::String(id)) if team==Some(id.as_str())=>{},
                _=>return Err(Error::Forbidden),
            }
        }
        // Exactly the maintained MonitorReadOnly branch: validate discovery
        // terminal status, NEVER collect/decrypt/claim/replay offered outputs.
        if kind=="recovery_outputs_discovery_complete"{
            let mut ignored=BTreeMap::new();
            if let Some(done)=crate::client::recovery::capture(kind,payload,&mut ignored)?{self.recovery_marker=done;}
        }
        let data=&mut *self.data;
        accept_sync_ciphertext_frame_at_epoch(kind,payload,team,self.expected_epoch,&mut data.phase1_windows,
            &mut data.chats,&mut data.chat_arrival_order,&mut data.wrappers,
            &mut data.embeds,&mut data.embed_keys,&mut self.metadata_seen,&mut self.sync_done)
    }
    /// Fixed existing metadata response after the original startup boundary.
    /// Called only by the actual explicit actor request; this method grants no
    /// native commit/readback, full coverage, private publication or hint ACK.
    pub(in crate::client) fn accept_post_startup_expanded_metadata(&mut self,payload:&Value,team:Option<&str>)->Result<()> {
        if !self.terminal_markers_received() || !self.metadata_seen { return Err(Error::Conflict); }
        // A server error is not an empty completed metadata read. The owning
        // actor retires dispatched failures through its existing failure path.
        if payload.get("error").is_some_and(|value| !value.is_null()) { return Err(Error::Offline); }
        let data=&mut *self.data;
        data.phase1_windows.metadata_response_with_expected_epoch("sync_metadata_chats_response",payload,team,self.expected_epoch,&data.chats)
    }
    /// Data readiness only; NOT actual socket/owner, inventory, recovery or IO
    /// completion. The same original actor must separately attest its exchange.
    pub(in crate::client) fn terminal_markers_received(&self)->bool {self.sync_done&&self.recovery_marker}
    pub(in crate::client) fn finish(mut self)->Result<Plain<SyncPhaseReadData>> {
        if !self.terminal_markers_received()||!self.metadata_seen{return Err(Error::Protocol)}
        let data=&mut *self.data;
        data.expanded_only_chat_ids=data.phase1_windows.expanded_only_ids(&data.chats);
        data.phase1_windows.take_metadata_ordered(&mut data.chats,&mut data.chat_arrival_order)?;
        Ok(self.data)
    }
}
#[cfg(test)]
#[path="sync_read_phase_tests.rs"]
mod tests;

#[cfg(test)]mod startup_provenance_tests {
 use super::*;
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.deletion.partial-window-not-authoritative
 #[test]fn expanded_only_classification_comes_from_actual_original_parser_sources_not_row_flags(){
  let a="11111111-1111-4111-8111-111111111111";let b="22222222-2222-4222-8222-222222222222";let c="33333333-3333-4333-8333-333333333333";
  let mut read=ReadOnlySyncPhase::new(0).unwrap();read.accept("phase_1_last_chat_ready",&json!({"context_epoch":0,"team_id":null,"chat_details":{"id":a}}),None).unwrap();
  read.accept("phase_2_last_20_chats_ready",&json!({"chats":[{"chat_details":{"id":b}}]}),None).unwrap();
  read.accept("sync_metadata_chats_response",&json!({"context_epoch":0,"team_id":null,"total_count":1234,"chats":[{"chat_details":{"id":a}},{"chat_details":{"id":b}},{"chat_details":{"id":c,"is_metadata_only":false}}]}),None).unwrap();
  read.accept("phased_sync_complete",&json!({}),None).unwrap();read.accept("recovery_outputs_discovery_complete",&json!({"status":"disabled"}),None).unwrap();let data=read.finish().unwrap();
  assert_eq!(data.expanded_only_chat_ids,BTreeSet::from([c.to_owned()]));assert_eq!(data.chats.len(),3);assert_eq!(data.chats[c]["is_metadata_only"],false);
 }
}

#[cfg(test)]mod navigation_footprint_tests {
 use super::*;
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
 #[test]fn final_source_footprint_counts_canonical_rows_orders_provenance_and_all_remaining_older_metadata(){
  let a="11111111-1111-4111-8111-111111111111";let b="22222222-2222-4222-8222-222222222222";let mut read=ReadOnlySyncPhase::new(0).unwrap();
  read.accept("phase_1_last_chat_ready",&json!({"context_epoch":0,"team_id":null,"chat_details":{"id":a,"opaque":{"unknown":"retained"}}}),None).unwrap();
  read.accept("sync_metadata_chats_response",&json!({"context_epoch":0,"team_id":null,"total_count":1234,"chats":[{"chat_details":{"id":b}}]}),None).unwrap();
  let older=json!({"context_epoch":0,"team_id":null,"total_count":1234,"offset":1000,"has_more":false,"chats":[],"unknownEnvelope":"z".repeat(4096)});read.accept("load_more_chats_response",&older,None).unwrap();
  read.accept("phase_2_last_20_chats_ready",&json!({"chats":[]}),None).unwrap();read.accept("phased_sync_complete",&json!({}),None).unwrap();read.accept("recovery_outputs_discovery_complete",&json!({"status":"disabled"}),None).unwrap();let data=read.finish().unwrap();
  let expected=serde_json::to_vec(&(&data.chats,&data.chat_arrival_order,&data.expanded_only_chat_ids)).unwrap().len()+serde_json::to_vec(&(BTreeMap::<String,Value>::new(),Vec::<String>::new(),BTreeMap::<String,Value>::new(),Vec::<String>::new(),data.phase1_windows.older_metadata_pages())).unwrap().len();
  assert_eq!(data.retained_navigation_bytes().unwrap(),expected);assert!(expected>4096);assert_eq!(data.chats.len(),2);
 }
}
