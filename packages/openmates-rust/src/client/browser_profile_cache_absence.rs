//! Actual closed local-only cache absence + returned original Core IO resource.
//! No Offline/error/Drop/DTO can mint this selection-data witness. It grants no
//! cold request, auth, native/global drain or publication authority.
use super::*;
pub(super) struct Observation {metadata:Plain<Value>,messages:Option<Plain<Value>>,host:BrowserMetadataCacheScope}
impl Observation {
    fn check(&self)->Result<()> {
        let metadata=&self.metadata;
        if metadata["kind"]!="owned_metadata"||metadata["compression_checkpoints"]!=json!([])
            ||self.host.lifecycle_generation==0||self.host.lifecycle_generation>MAX_SAFE||self.host.workspace_epoch>MAX_SAFE{return Err(Error::Protocol)}
        match &self.messages{
            None=>if !metadata["chat_metadata"].is_null(){return Err(Error::Protocol)},
            Some(messages)=>{
                if metadata["chat_metadata"].is_null()||text(&metadata["chat_metadata"],"encrypted_chat_key").is_empty()
                    ||!(metadata["chat_metadata"]["is_metadata_only"]==true||metadata["chat_metadata"]["messages_v"].as_u64().is_some_and(|v|v>0))
                    ||messages["kind"]!="messages"||messages["messages"]!=json!([])
                    ||messages["operationId"]!=metadata["operationId"]||messages["databaseVersion"]!=metadata["databaseVersion"]{return Err(Error::Protocol)}
            },
        }
        // Complete source envelopes, including unknown row fields, remain
        // bounded. These frames MOVE here, rather than cloning retained data.
        if crate::client::monitor::cached_view::bounded_bytes(&(&**metadata,self.messages.as_deref(),&self.host),256*1024).is_none(){return Err(Error::Protocol)}Ok(())
    }
}
pub(super) fn record(context:&Arc<Context>,metadata:Plain<Value>,messages:Option<Plain<Value>>,host:BrowserMetadataCacheScope)->Result<()> {
    context.negative()?;if context.profile_cache.is_none(){return Err(Error::Forbidden)}
    let observation=Observation{metadata,messages,host};observation.check()?;
    let mut slot=context.profile_absence.lock().map_err(|_|Error::Protocol)?;
    if slot.is_some(){return Err(Error::Conflict)}
    context.negative_without_gate()?;*slot=Some(observation);Ok(())
}
/// One-use actual supported absence at this ORIGINAL local read. Selection DATA
/// only; a fresh ordinary cold read separately requires all actual Client guards.
#[doc(hidden)]
pub struct OwnedBrowserProfileCacheAbsence {context:Arc<Context>,drain:Arc<DriverDrainState>,observation:Option<Observation>}
impl OwnedBrowserReadDriver {
    pub fn take_profile_cache_absence(&mut self,client:&Client)->Result<OwnedBrowserProfileCacheAbsence>{
        if !self.finished||!self.drain.quiescent()||self.context.profile_cache.is_none(){return Err(Error::Conflict)}
        self.context.check(client)?;
        let mut slot=self.context.profile_absence.lock().map_err(|_|Error::Protocol)?;
        slot.as_ref().ok_or(Error::Conflict)?.check()?;self.context.negative_without_gate()?;
        let observation=slot.take().ok_or(Error::Conflict)?;
        Ok(OwnedBrowserProfileCacheAbsence{context:self.context.clone(),drain:self.drain.clone(),observation:Some(observation)})
    }
}
impl OwnedBrowserProfileCacheAbsence {
    pub fn ensure_current(&self,client:&Client)->Result<()> {
        if !self.drain.quiescent(){return Err(Error::Conflict)}
        self.observation.as_ref().ok_or(Error::Conflict)?.check()?;self.context.check(client)
    }
    /// Host may use only the successful native call as negative selection data,
    /// after its separate actual native IO ledger also settles. No retry grant.
    pub fn consume(&mut self,client:&Client)->Result<()> {
        self.ensure_current(client)?;self.context.negative_without_gate()?;
        self.observation.take().ok_or(Error::Conflict)?;Ok(())
    }
}
