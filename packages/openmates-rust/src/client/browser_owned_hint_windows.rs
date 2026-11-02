//! Actual original actor batch to shared startup20 crypto validation. Opaque
//! completion retains all remainder DATA; no local-store/full-hint ACK exists.
use super::*;
use super::hint_refresh::OriginalHintRefreshBatch;
use crate::client::sync_windows::{PreparedOwnedSyncWindows,CompletedOwnedSyncWindows,CiphertextMessageWindow};
#[doc(hidden)]
pub struct OwnedOriginalHintWindowPreparation {batch:OriginalHintRefreshBatch,prepared:PreparedOwnedSyncWindows}
#[doc(hidden)]
pub struct OwnedOriginalHintWindowCompletion {batch:OriginalHintRefreshBatch,completed:CompletedOwnedSyncWindows}
#[doc(hidden)]
pub struct OriginalHintWindowBatch {batch:OriginalHintRefreshBatch,pub(super) windows:BTreeMap<String,CiphertextMessageWindow>}
impl OriginalHintRefreshBatch {
    pub fn prepare_windows(mut self,client:&Client)->Result<OwnedOriginalHintWindowPreparation>{
        self.ensure_current(client)?;
        // Validate actual raw actor row floors before any platform unwrap.
        // Metadata-only children remain in batch but never get eager content.
        let Mode::Incoming(monitor)=&self.context.mode else{return Err(Error::Forbidden)};
        for(id,row)in &self.read.chats{
            self.context.scope.crypto.check_chat(client,id)?;monitor.check_chat_metadata_floor(id,row)?;
            BrowserOwnedMetadataFloor::capture(client,id)?.check(row)?;
        }
        let phase=std::mem::take(&mut self.read.phase1_windows);
        let prepared=PreparedOwnedSyncWindows::capture(client,self.context.scope.clone(),phase,Plain::new(self.read.chats.clone()),Plain::new(self.read.wrappers.clone()))?;
        self.ensure_current(client)?;Ok(OwnedOriginalHintWindowPreparation{batch:self,prepared})
    }
}
impl OwnedOriginalHintWindowPreparation {
    pub async fn drive(self)->Result<OwnedOriginalHintWindowCompletion>{
        let context=self.batch.context.clone();context.negative()?;let completed=self.prepared.drive(move||context.negative()).await?;self.batch.context.negative()?;
        Ok(OwnedOriginalHintWindowCompletion{batch:self.batch,completed})
    }
}
impl OwnedOriginalHintWindowCompletion {
    pub fn finish(self,client:&Client)->Result<OriginalHintWindowBatch>{
        self.batch.ensure_current(client)?;let windows=self.completed.finish(client)?;self.batch.ensure_current(client)?;
        Ok(OriginalHintWindowBatch{batch:self.batch,windows})
    }
}
impl OriginalHintWindowBatch {
    pub fn ensure_current(&self,client:&Client)->Result<()>{self.batch.ensure_current(client)}
    pub fn kind(&self)->&'static str{"original_hint_windows_pending_physical_store"}
    pub fn next_row(&mut self,client:&Client)->Result<Option<OriginalHintRowSeed>>{self.batch.next_row(client)}
    pub fn cancel(&self){self.batch.cancel();}
    pub async fn wait_cancelled(&self){self.batch.wait_cancelled().await}
    // Ciphertext windows remain native resources, not count/DTO completion.
}
