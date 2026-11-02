//! SAME original saved-send Version read; only actual IO/unwrap leaves Client.
use super::*;
use super::super::super::sync_capability::{PreparedChatKey,CompletedChatKey};
/// Exact local row/wrapper conflict observation, never read/auth/version proof.
pub(super) struct VersionStamp {row:Option<String>,wrappers:String}
pub(super) struct PreparedVersionKey {stamp:VersionStamp,row:Plain<Value>,team:TeamCacheStamp,key:PreparedChatKey}
pub(super) struct CompletedVersionKey {stamp:VersionStamp,row:Plain<Value>,team:TeamCacheStamp,key:CompletedChatKey}
fn wrappers_stamp(client:&Client,chat:&str)->Result<String>{
    let hash=sha256(chat);
    let rows:Vec<&Value>=client.wrappers.iter().filter(|row|text(row,"hashed_chat_id")==hash).collect();
    bound(&rows)?;let encoded=zeroize::Zeroizing::new(serde_json::to_string(&rows)?);Ok(sha256(&encoded))
}
pub(super) fn stamp(client:&Client,chat:&str)->Result<VersionStamp>{
    Ok(VersionStamp{row:focus_row_stamp(client,chat)?,wrappers:wrappers_stamp(client,chat)?})
}
impl VersionStamp {
    fn check(&self,client:&Client,chat:&str)->Result<()>{
        if self.row!=focus_row_stamp(client,chat)?||self.wrappers!=wrappers_stamp(client,chat)?{return Err(Error::Conflict)}Ok(())
    }
}
pub(super) fn prepare_key(client:&Client,chat:&str,stamp:VersionStamp,detail:Plain<Value>,wrapping:&MasterCapability)->Result<PreparedVersionKey>{
    stamp.check(client,chat)?;
    let row=detail;
    if text(&row,"id")!=chat{return Err(Error::Forbidden)}
    bound(&*row)?;
    let key=client.prepare_chat_key_with_capability_from(&row,wrapping,&client.wrappers)?;
    Ok(PreparedVersionKey{stamp,row,team:catalogue::cache_stamp(client),key})
}
impl PreparedVersionKey {
    async fn drive(self)->CompletedVersionKey {CompletedVersionKey{stamp:self.stamp,row:self.row,team:self.team,key:self.key.drive().await}}
}
pub(super) fn commit(client:&mut Client,chat:&str,key:&[u8;32],minimum:u64,completed:CompletedVersionKey)->Result<u64>{
    completed.stamp.check(client,chat)?;
    if !completed.team.matches(client){return Err(Error::Conflict)}
    if completed.key.finish(client)?.as_ref()!=key{return Err(Error::Crypto)}
    let latest=completed.row["messages_v"].as_u64().ok_or(Error::Protocol)?;
    if latest<minimum{return Err(Error::Protocol)}
    client.insert_chat_row(chat.into(),completed.row.into_inner());Ok(latest)
}
impl OwnedTurnPhases {
    pub(super) async fn owned_current_messages_version(&self,chat:&str,key:&[u8;32],minimum:u64)->Result<u64>{
        let stamp=match self.exchange(Call::VersionBegin(chat.into())).await?{Reply::VersionStamp(value)=>value,_=>return Err(Error::Protocol)};
        let detail=self.catalogue_read(CatalogueRoute::Version(chat.into())).await?;
        // Preserve missing/malformed-row refusal BEFORE lazy Team HTTP/key work.
        let row=detail["chats"].as_array().ok_or(Error::Protocol)?.iter().find(|row|text(row,"id")==chat).ok_or(Error::Forbidden)?.clone();
        let detail=Plain::new(row);
        let wrapping=self.owned_wrapping_capability().await?;
        let prepared=match self.exchange(Call::VersionKey{chat:chat.into(),stamp,detail,wrapping}).await?{Reply::VersionKey(value)=>value,_=>return Err(Error::Protocol)};
        self.catalogue_negative()?;
        // Do not select/drop opaque crypto on cancellation. The SAME original
        // driver retains it until actual return, then refuses retired A.
        let completed=prepared.drive().await;
        self.catalogue_negative()?;
        match self.exchange(Call::VersionCommit{chat:chat.into(),key:zeroize::Zeroizing::new(*key),minimum,completed}).await?{Reply::Version(value)=>Ok(value),_=>Err(Error::Protocol)}
    }
}
#[cfg(all(test,not(target_arch="wasm32")))]
#[path="owned_saved_send_version_tests.rs"]
mod tests;
