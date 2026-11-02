//! Narrow original-native-draft compatibility budget. The normal metadata JSON
//! and source budgets remain 256KiB. No field is removed from hashes or IO.
use super::*;
use crate::crypto::master::MasterCapability;
use crate::client::plaintext::Plain;
use zeroize::Zeroizing;
pub(in crate::client) const ROW_BYTES:usize=2*1024*1024;
pub(in crate::client) const PACKET_BYTES:usize=4*1024*1024;
const DRAFT_FIELDS:&[&str]=&["encrypted_draft_md","encrypted_draft_preview","draft_v","cleared_draft_v"];
fn projection(row:&Value)->Plain<Value>{
    let mut out=Plain::new(json!({}));for field in DRAFT_FIELDS {if let Some(value)=row.get(*field){out[*field]=value.clone();}}out
}
pub(in crate::client) fn validate_row(row:&Value)->Result<()> {
    if crate::client::monitor::cached_view::bounded_bytes(row,ROW_BYTES).is_none(){return Err(Error::Protocol)}
    let mut normal=Plain::new(row.clone());let fields=normal.as_object_mut().ok_or(Error::Protocol)?;
    // Size accounting only; the actual source hash and cache row stay complete.
    fields.remove("encrypted_draft_md");fields.remove("encrypted_draft_preview");
    if crate::client::monitor::cached_view::bounded_bytes(&*normal,256*1024).is_none(){return Err(Error::Protocol)}Ok(())
}
pub(in crate::client) fn stamp_row(row:&Option<&Value>)->Result<String>{
    if let Some(row)=row{validate_row(row)?;}let encoded=Zeroizing::new(serde_json::to_string(row)?);Ok(sha256(&encoded))
}
/// Issued only after both actual original native observations were consumed,
/// existing Master verification completed and exact reread remained equal.
/// Cannot be deserialized, cloned, exported or supplied by adapters.
pub(in crate::client) struct OriginalPhysicalDraftBounds {owner:String,generation:u64,master:Option<MasterCapability>,draft:Plain<Value>,physical:Plain<Value>}
impl OriginalPhysicalDraftBounds {
    #[cfg(target_arch="wasm32")]
    pub(in crate::client) fn capture(client:&Client,original:&crate::client::OriginalPhysicalDraftInventory)->Result<Self>{
        // Opaque actual consumer rechecks retained original native observations,
        // exact projections, actual Master verification and before-row CAS.
        // No row/owner/hash/cipher DTO can construct this budget witness.
        let(id,row,physical,master)=original.verified_draft_row(client)?;
        client.validate_original_physical_draft_scope(physical,id)?;validate_row(row)?;
        if physical["encrypted_draft_md"].as_str().is_some_and(|v|!v.is_empty())&&master.is_none(){return Err(Error::Forbidden)}
        if let Some(master)=master{master.ensure_current()?;if !master.same_instance(&client.master_capability()?){return Err(Error::Cancelled)}}
        Ok(Self{owner:client.browser_session_status().ok_or(Error::Authentication)?.principal().to_owned(),generation:client.generation,master:master.cloned(),draft:projection(row),physical:projection(physical)})
    }
    fn check(&self,client:&Client,row:&Value)->Result<()> {
        if client.generation!=self.generation||client.browser_session_status().ok_or(Error::Authentication)?.principal()!=self.owner||*projection(row)!=*self.draft{return Err(Error::Cancelled)}
        if let Some(master)=&self.master{master.ensure_current()?;if !master.same_instance(&client.master_capability()?){return Err(Error::Cancelled)}}
        validate_row(row)
    }
    pub(in crate::client) fn check_header(&self,client:&Client,row:&Value)->Result<()> {
        if client.generation!=self.generation||client.browser_session_status().ok_or(Error::Authentication)?.principal()!=self.owner||*projection(row)!=*self.physical{return Err(Error::Cancelled)}
        if let Some(master)=&self.master{master.ensure_current()?;if !master.same_instance(&client.master_capability()?){return Err(Error::Cancelled)}}validate_row(row)
    }
}
pub(in crate::client) fn source_stamp(client:&Client,id:&str)->Result<String>{
    let row=client.chats.get(id);
    if crate::client::monitor::cached_view::bounded_bytes(&row,256*1024).is_some(){
        return Ok(sha256(&Zeroizing::new(serde_json::to_string(&row)?)))
    }
    let value=row.ok_or(Error::Protocol)?;client.original_physical_draft_bounds.get(id).ok_or(Error::Protocol)?.check(client,value)?;
    stamp_row(&row)
}
pub(in crate::client) fn has_budget(client:&Client,id:&str)->Result<bool>{
    let Some(row)=client.chats.get(id)else{return Ok(false)};
    let Some(bounds)=client.original_physical_draft_bounds.get(id)else{return Ok(false)};bounds.check(client,row)?;Ok(true)
}

pub(in crate::client) fn validate_adopted_row(client:&Client,id:&str,row:&Value)->Result<()> {
    if crate::client::monitor::cached_view::bounded_bytes(row,256*1024).is_some(){return Ok(())}
    client.original_physical_draft_bounds.get(id).ok_or(Error::Protocol)?.check(client,row)
}
