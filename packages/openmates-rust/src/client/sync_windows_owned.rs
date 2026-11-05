//! Actual original-sibling startup window key stage. No Client across opaque
//! platform crypto await; no physical store, freshness or recovery receipt.
use super::*;
use crate::client::{owned_operation::OwnedOperationScope,plaintext::Plain};
use crate::crypto::master::MasterCapability;
use std::sync::Arc;
enum KeyInput {Master{master:MasterCapability,ciphertext:Zeroizing<String>},Native(Key)}
pub(in crate::client) struct PreparedOwnedSyncWindows {
    scope:Arc<OwnedOperationScope>,batch:Plain<Phase1Windows>,chats:Plain<BTreeMap<String,Value>>,wrappers:Plain<Vec<Value>>,
    sources:BTreeMap<String,String>,inputs:Vec<(String,KeyInput)>,
}
pub(in crate::client) struct CompletedOwnedSyncWindows {
    scope:Arc<OwnedOperationScope>,batch:Plain<Phase1Windows>,chats:Plain<BTreeMap<String,Value>>,wrappers:Plain<Vec<Value>>,
    sources:BTreeMap<String,String>,keys:BTreeMap<String,Key>,
}
fn source(client:&Client,id:&str)->Result<String>{crate::client::browser::original_draft_bounds::source_stamp(client,id)}
fn original(scope:&OwnedOperationScope,client:&Client,sources:&BTreeMap<String,String>)->Result<()> {
    scope.check(client)?;for(id,stamp)in sources{scope.crypto.check_chat(client,id)?;if source(client,id)?!=*stamp{return Err(Error::Conflict)}}scope.check(client)
}
impl PreparedOwnedSyncWindows {
    // Internal only: the caller owns actual original actor batch/hint, validates
    // every raw row/floor before this prepares opaque platform key operations.
    pub(in crate::client) fn capture(client:&Client,scope:Arc<OwnedOperationScope>,batch:Phase1Windows,chats:Plain<BTreeMap<String,Value>>,wrappers:Plain<Vec<Value>>)->Result<Self>{
        scope.check(client)?;
        let wrapping=client.cached_wrapping_capability_for_owned(&scope)?;
        let mut sources=BTreeMap::new();let mut inputs=Vec::new();
        for id in &batch.order {let Some(row)=chats.get(id)else{continue};
            if !parent(row)||!client.task_watch_authority.cached_chat_allowed(id){continue}
            scope.crypto.check_chat(client,id)?;sources.insert(id.clone(),source(client,id)?);
            let prepared=if text(row,"chat_visibility")=="direct"{
                client.native_master_key().and_then(|_|client.direct_chat_key(row)).map(KeyInput::Native)
            }else{client.chat_key_ciphertext_from(row,false,&wrappers).map(|selected|KeyInput::Master{master:wrapping.clone(),ciphertext:Zeroizing::new(selected.ciphertext.into())})};
            // Same maintained phase semantics: unavailable chat keys defer that
            // viewport, but actual auth/cancel/expiry refuses the whole phase.
            match prepared{Ok(input)=>inputs.push((id.clone(),input)),Err(error@(Error::Expired|Error::Cancelled|Error::Authentication))=>return Err(error),Err(_)=>{}}
            scope.check(client)?;
        }
        original(&scope,client,&sources)?;Ok(Self{scope,batch:Plain::new(batch),chats,wrappers,sources,inputs})
    }
    pub(in crate::client) async fn drive<C>(self,mut check:C)->Result<CompletedOwnedSyncWindows> where C:FnMut()->Result<()>{
        let mut keys=BTreeMap::new();
        for(id,input)in self.inputs{
            self.scope.crypto.check_original_operation_negative()?;check()?;
            let key=match input {KeyInput::Native(key)=>Ok(key),KeyInput::Master{master,ciphertext}=>master.decrypt_bytes(&ciphertext).await.and_then(|bytes|key_from_bytes(&bytes))};
            self.scope.crypto.check_original_operation_negative()?;check()?;
            match key{Ok(key)=>{keys.insert(id,key);},Err(error@(Error::Expired|Error::Cancelled|Error::Authentication))=>return Err(error),Err(_)=>{}}
        }
        Ok(CompletedOwnedSyncWindows{scope:self.scope,batch:self.batch,chats:self.chats,wrappers:self.wrappers,sources:self.sources,keys})
    }
}
impl CompletedOwnedSyncWindows {
    pub(in crate::client) fn finish(self,client:&Client)->Result<BTreeMap<String,CiphertextMessageWindow>> {
        original(&self.scope,client,&self.sources)?;
        let result=client.finish_sync_windows_verified_keys(self.batch.into_inner(),&self.chats,&self.wrappers,&self.keys)?;
        original(&self.scope,client,&self.sources)?;Ok(result)
    }
}
