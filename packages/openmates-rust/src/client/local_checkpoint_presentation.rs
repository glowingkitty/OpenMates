//! Closed retained-checkpoint presentation under the caller's existing read scope.
//! This contains no ciphertext, wrapping key, raw extensions or history authority.
//! Stored summaries keep their placeholders; message-local PII maps never apply.
//! Only authenticated-ciphertext corruption becomes unavailable summary metadata.
//! Owner/key/negative/cancellation errors from the current guard always propagate.
//! Output owns/wipes its strings on every error, rejected handoff and final Drop.
use super::*;
use super::super::plaintext::Plain;
use serde::Serialize;
use zeroize::Zeroize;
pub(in crate::client) const MAX_PRESENTATION_FRAME_BYTES:usize=super::super::message_window::MAX_MESSAGE_BYTES-8192;
#[derive(Clone,Copy,Debug,PartialEq,Eq,Serialize)]
#[serde(rename_all="snake_case")]
pub(in crate::client) enum SummaryState { Loaded, Missing, Unavailable, NotLoaded }
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
pub(in crate::client) struct Checkpoint {
    pub(in crate::client) id:String,pub(in crate::client) chat_id:String,pub(in crate::client) created_at:i64,
    pub(in crate::client) compressed_up_to_timestamp:i64,pub(in crate::client) compressed_message_count:u64,
    pub(in crate::client) summary_state:SummaryState,pub(in crate::client) summary:Option<String>,pub(in crate::client) summary_unavailable_reason:Option<&'static str>,
}
impl Drop for Checkpoint {fn drop(&mut self){self.id.zeroize();self.chat_id.zeroize();if let Some(value)=&mut self.summary{value.zeroize();}}}
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
pub(in crate::client) struct Presentation {
    pub(in crate::client) source:&'static str,pub(in crate::client) coverage:&'static str,pub(in crate::client) history_complete:bool,
    pub(in crate::client) pii_restoration:&'static str,pub(in crate::client) retained_checkpoint_count:usize,
    pub(in crate::client) checkpoint:Option<Checkpoint>,
}
impl Presentation {
    pub(in crate::client) fn omit_summary(&mut self){if let Some(row)=&mut self.checkpoint{if row.summary_state==SummaryState::Loaded{if let Some(mut value)=row.summary.take(){value.zeroize();}row.summary_state=SummaryState::NotLoaded;}}}
    pub(in crate::client) fn mark_oversized(&mut self){if let Some(row)=&mut self.checkpoint{if let Some(mut value)=row.summary.take(){value.zeroize();}row.summary_state=SummaryState::Unavailable;row.summary_unavailable_reason=Some("oversized");}}
}
fn summary(row:&Value,key:&[u8;32])->Result<(SummaryState,Option<Plain<String>>,Option<&'static str>)> {
    // Match deployed truthy clear-summary preference, without coercing types.
    if let Some(value)=row.get("summary").filter(|v|!v.is_null()) {
        let value=value.as_str().ok_or(Error::Protocol)?;
        if !value.is_empty(){return Ok((SummaryState::Loaded,Some(Plain::new(value.to_owned())),None));}
    }
    if row.get("encrypted_summary").is_none_or(|v|v.is_null()||v.as_str()==Some("")){return Ok((SummaryState::Missing,None,None));}
    match super::super::sync::decrypt_optional(row,"encrypted_summary",key) {
        Ok(value) if value.is_empty()=>Ok((SummaryState::Missing,None,None)),
        Ok(value)=>Ok((SummaryState::Loaded,Some(Plain::new(value)),None)),
        Err(Error::Crypto)=>Ok((SummaryState::Unavailable,None,Some("corrupt"))),
        Err(error)=>Err(error),
    }
}
pub(in crate::client) fn project(rows:&[Value],chat:&str,key:&[u8;32],selected:Option<&str>,mut current:impl FnMut()->Result<()>)->Result<Presentation>{
    current()?;wire::compression_timestamp(rows,chat)?;let explicit=selected.is_some();
    let selected=if let Some(id)=selected{wire::storage_id(id)?;rows.iter().find(|row|row["id"].as_str()==Some(id))}
        else{rows.iter().min_by(|a,b|b["created_at"].as_i64().cmp(&a["created_at"].as_i64()).then_with(||wire::idb_key_cmp(a["id"].as_str().unwrap(),b["id"].as_str().unwrap())))};
    let mut output=Presentation{source:"local_profile",coverage:if explicit{"retained_selected"}else{"retained_latest"},history_complete:false,pii_restoration:"stored",retained_checkpoint_count:rows.len(),checkpoint:None};
    if let Some(row)=selected {
        // Validate borrowed/scalar fields before allocating any owned plaintext.
        let id=required(row,"id")?;let created_at=row["created_at"].as_i64().ok_or(Error::Protocol)?;
        let compressed_up_to_timestamp=row["compressed_up_to_timestamp"].as_i64().ok_or(Error::Protocol)?;
        let compressed_message_count=row["compressed_message_count"].as_u64().ok_or(Error::Protocol)?;
        let mut checkpoint=Checkpoint{id:id.into(),chat_id:chat.into(),created_at,compressed_up_to_timestamp,compressed_message_count,
            summary_state:SummaryState::Missing,summary:None,summary_unavailable_reason:None};
        current()?;let (state,value,reason)=summary(row,key)?;checkpoint.summary_unavailable_reason=reason;checkpoint.summary_state=state;checkpoint.summary=value.map(Plain::into_inner);current()?;
        output.checkpoint=Some(checkpoint);
    }
    current()?;Ok(output)
}
#[cfg(test)]
#[path="local_checkpoint_presentation_tests.rs"]
mod tests;
