//! Opaque original-hint foreground coupling. The private native result never
//! crosses Core. Canonical row adoption is NOT local persistence/full-hint ACK.
use super::*;
use crate::client::completion_recovery::{self as recovery,CompletionRecoveryJob,CompletionRecoveryCheckpoint};
#[path="browser_owned_hint_recovery_physical.rs"]
mod physical;
pub use physical::{BrowserOriginalHintRecoveryCheckpointPreparation,BrowserOriginalHintRecoveryCheckpointCrypto,BrowserOriginalHintRecoveryCheckpointWrite,BrowserOriginalHintRecoveryPersistenceFailure};
#[cfg(target_arch="wasm32")]
pub use physical::{BrowserOriginalHintRecoveryCheckpointReadiness,BrowserOriginalHintRecoveryCheckpointRead,BrowserOriginalHintRecoveryCheckpointReadResult,BrowserOriginalHintRecoveryCheckpointNativeWrite,BrowserOriginalHintRecoveryCheckpointNativeWriteResult,BrowserOriginalHintRecoveryCheckpointReadbackCrypto,BrowserOriginalHintRecoveryCheckpointVerified,BrowserOriginalHintRecoveryCheckpointDurable};
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryDriver {
    inner:recovery::OwnedRecoveryDriver,remainder:Option<Arc<OwnedBrowserMetadataContinuation>>,handoff:Arc<crate::client::OriginalHintRecoveryHandoff>,
    #[cfg(target_arch="wasm32")] port_hold:Option<crate::platform::browser_recovery_port::OriginalBrowserRecoveryPort>,
}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryControl {inner:recovery::OwnedRecoveryControl}
impl BrowserOriginalHintRecoveryControl {pub fn cancel(&self){self.inner.cancel();}pub async fn wait_cancelled(&self){self.inner.wait_cancelled().await}}
#[doc(hidden)]
pub enum BrowserOriginalHintRecoveryStep {
    Apply(BrowserOriginalHintRecoveryApply),Io(BrowserOriginalHintRecoveryIo),
    Adopt(BrowserOriginalHintRecoveryAdoption),PendingPersistence(BrowserOriginalHintRecoveryPendingPersistence),Deferred(BrowserOriginalHintRecoveryDeferred),
}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryApply {inner:recovery::OwnedRecoveryApply}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryIo {inner:recovery::OwnedRecoveryIo}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryResume {inner:recovery::OwnedRecoveryResume}
impl BrowserOriginalHintRecoveryApply {
    pub fn apply(self,client:&mut Client)->Result<BrowserOriginalHintRecoveryResume>{Ok(BrowserOriginalHintRecoveryResume{inner:self.inner.apply(client)?})}
}
impl BrowserOriginalHintRecoveryIo {
    pub async fn drive(self)->Result<BrowserOriginalHintRecoveryResume>{Ok(BrowserOriginalHintRecoveryResume{inner:self.inner.drive().await?})}
}
impl OwnedBrowserMetadataContinuation {
    pub fn begin_recovery(self,client:&mut Client,job:&CompletionRecoveryJob,saved:Option<CompletionRecoveryCheckpoint>)->Result<BrowserOriginalHintRecoveryDriver>{
        self.check_original(client)?;if !self.metadata_committed{return Err(Error::Conflict)}
        let handoff=self.recovery_handoff(client,job)?;
        let inner=client.prepare_original_owned_recovery(handoff.clone(),saved)?.into_driver()?;
        Ok(BrowserOriginalHintRecoveryDriver{inner,remainder:Some(Arc::new(self)),handoff,#[cfg(target_arch="wasm32")]port_hold:None})
    }
}
impl BrowserOriginalHintRecoveryDriver {
    pub fn control(&self)->BrowserOriginalHintRecoveryControl{BrowserOriginalHintRecoveryControl{inner:self.inner.control()}}
    pub fn resume(&mut self,resume:BrowserOriginalHintRecoveryResume)->Result<()>{self.inner.resume(resume.inner)}
    pub async fn next(&mut self)->Result<BrowserOriginalHintRecoveryStep>{
        Ok(match self.inner.next().await? {
            recovery::OwnedRecoveryStep::Apply(inner)=>BrowserOriginalHintRecoveryStep::Apply(BrowserOriginalHintRecoveryApply{inner}),
            recovery::OwnedRecoveryStep::Io(inner)=>BrowserOriginalHintRecoveryStep::Io(BrowserOriginalHintRecoveryIo{inner}),
            recovery::OwnedRecoveryStep::Canonical(result)=>BrowserOriginalHintRecoveryStep::Adopt(BrowserOriginalHintRecoveryAdoption{result,remainder:self.remainder.take().ok_or(Error::Cancelled)?,handoff:self.handoff.clone(),#[cfg(target_arch="wasm32")]port_hold:self.port_hold.take()}),
            recovery::OwnedRecoveryStep::PendingPersistence(inner)=>BrowserOriginalHintRecoveryStep::PendingPersistence(BrowserOriginalHintRecoveryPendingPersistence{inner,remainder:self.remainder.take().ok_or(Error::Cancelled)?,handoff:self.handoff.clone(),#[cfg(target_arch="wasm32")]port_hold:self.port_hold.take()}),
            recovery::OwnedRecoveryStep::Deferred=>BrowserOriginalHintRecoveryStep::Deferred(BrowserOriginalHintRecoveryDeferred{remainder:self.remainder.take().ok_or(Error::Cancelled)?,handoff:self.handoff.clone(),#[cfg(target_arch="wasm32")]port_hold:self.port_hold.take()}),
        })
    }
}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryAdoption {
    result:recovery::OriginalForegroundRecoveryResult,remainder:Arc<OwnedBrowserMetadataContinuation>,handoff:Arc<crate::client::OriginalHintRecoveryHandoff>,
    #[cfg(target_arch="wasm32")] port_hold:Option<crate::platform::browser_recovery_port::OriginalBrowserRecoveryPort>,
}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryProgress {
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))] reply_store_issued:AtomicBool,
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))] finalize_issued:AtomicBool,
    remainder:Arc<OwnedBrowserMetadataContinuation>,handoff:Arc<crate::client::OriginalHintRecoveryHandoff>,
    receipt:recovery::CompletionRecoveryReceipt,witness:recovery::OriginalRecoveryRowTransition,artifacts:Option<recovery::OwnedRecoveryArtifacts>,
    #[cfg(target_arch="wasm32")] port_hold:Option<crate::platform::browser_recovery_port::OriginalBrowserRecoveryPort>,
}
fn same_job(a:&CompletionRecoveryJob,b:&CompletionRecoveryJob)->bool {
    a.kind==b.kind&&a.job_id==b.job_id&&a.chat_id==b.chat_id&&a.turn_id==b.turn_id&&a.assistant_message_id==b.assistant_message_id&&a.task_id==b.task_id&&a.stage==b.stage&&a.chat_key_version==b.chat_key_version
}
impl BrowserOriginalHintRecoveryAdoption {
    pub fn apply(self,client:&mut Client)->Result<BrowserOriginalHintRecoveryProgress>{
        self.result.check_original(client)?;self.handoff.check_root(client)?;
        #[cfg(target_arch="wasm32")] if let Some(port)=&self.port_hold{port.check_original(client)?;}
        if !Arc::ptr_eq(&self.handoff.scope_arc(),&self.remainder.context.scope)||!same_job(self.result.job(),self.handoff.job()){return Err(Error::Cancelled)}
        let(receipt,witness,artifacts)=self.result.into_witnessed_parts()?;
        witness.check_original(client,&self.handoff)?;
        if !same_job(witness.job(),self.handoff.job())||witness.before()!=self.handoff.before_row().as_ref(){return Err(Error::Conflict)}
        if let Some(artifacts)=&artifacts{artifacts.check_original(client,&self.handoff)?;}
        let ctx=&self.remainder.context;
        if witness.job().chat_id==ctx.chat {
            // Advance ONLY this SAME context's original selected-row anchor,
            // from actual original-before to actual witnessed current-after.
            // No caller hash/status/source re-capture can enter this branch.
            let before=Zeroizing::new(serde_json::to_string(self.handoff.before_row())?);
            self.handoff.check_root(client)?;witness.check_original(client,&self.handoff)?;
            let after=crate::client::browser::original_draft_bounds::source_stamp(client,&ctx.chat)?;
            // Never hold the anchor lock across caller gates. Last resource
            // check while locked is callback-free and only removes authority.
            let mut anchor=ctx.source.lock().map_err(|_|Error::Protocol)?;
            if *anchor!=sha256(&before)||client.chats.get(&ctx.chat)!=witness.after(){return Err(Error::Conflict)}
            self.handoff.check_original_negative()?;witness.check_original_negative()?;
            #[cfg(target_arch="wasm32")] if let Some(port)=&self.port_hold{port.check_negative()?;}
            *anchor=after;
        }else{
            // Job A cannot rebase B; unrelated B mutation still refuses.
            ctx.check(client)?;
        }
        let progress=BrowserOriginalHintRecoveryProgress{#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]reply_store_issued:AtomicBool::new(false),#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]finalize_issued:AtomicBool::new(false),remainder:self.remainder,handoff:self.handoff,receipt,witness,artifacts,#[cfg(target_arch="wasm32")]port_hold:self.port_hold};
        progress.ensure_current(client)?;Ok(progress)
    }
}
impl BrowserOriginalHintRecoveryProgress {
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn recovered_reply_store_inputs(&self,client:&Client)->Result<(Plain<Value>,Plain<Value>,Zeroizing<String>,MasterCapability,recovery::OriginalMainRecoveryJournalObservation)>{
        let(_expected,source,ciphertext,master,journal)=self.main_metadata_store_inputs(client)?;
        let job=self.handoff.job();let message=job.assistant_message_id.as_deref().ok_or(Error::Protocol)?;let rows=self.artifacts.as_ref().ok_or(Error::Protocol)?.checked_ciphertext_rows(client,&self.handoff)?;
        let mut selected=None;
        for row in rows{if crate::client::message_window::server_message_id(row)?==message{
            if selected.is_some()||row["role"]!="assistant"{return Err(Error::Protocol)}selected=Some(row);
        }}
        let selected=selected.ok_or(Error::Protocol)?;
        if crate::client::monitor::cached_view::bounded_bytes(selected,crate::client::transport::MAX_BODY).is_none(){return Err(Error::Protocol)}
        let selected=Plain::new(selected.clone());self.ensure_current(client)?;
        Ok((source,selected,ciphertext,master,journal))
    }
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn recovered_reply_message(&self)->Result<&str>{self.handoff.job().assistant_message_id.as_deref().ok_or(Error::Protocol)}
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn claim_recovered_reply_store(&self)->Result<()>{
        self.metadata_finalize_negative()?;self.reply_store_issued.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;self.metadata_finalize_negative()
    }
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn metadata_finalize_inputs(&self,client:&Client)->Result<(Plain<Value>,Plain<Value>,Zeroizing<String>,MasterCapability,recovery::OriginalMetadataRecoveryRetirement)>{
        self.ensure_current(client)?;
        let job=self.handoff.job();
        if job.kind!=recovery::CompletionRecoveryKind::Metadata||client.team()?.is_some()||job.chat_id!=self.remainder.context.chat||self.artifacts.is_some(){return Err(Error::Unavailable{code:"recovery_local_finalize_unsupported",reason:"MAIN_TRANSCRIPT_NATIVE_FINALIZATION_REMAINS_REQUIRED"})}
        let source=self.witness.after().ok_or(Error::Protocol)?;
        client.browser_message_cache_metadata_guard(source,&job.chat_id)?;
        let selected=client.chat_key_ciphertext_from(source,false,&client.wrappers)?;
        let expected=Plain::new(self.remainder.data.readback["metadata"].clone());
        let retirement=self.witness.prepare_metadata_retirement(client)?;
        self.ensure_current(client)?;
        Ok((expected,Plain::new(source.clone()),Zeroizing::new(selected.ciphertext.to_owned()),client.master_capability()?,retirement))
    }
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn main_metadata_store_inputs(&self,client:&Client)->Result<(Plain<Value>,Plain<Value>,Zeroizing<String>,MasterCapability,recovery::OriginalMainRecoveryJournalObservation)>{
        self.ensure_current(client)?;let job=self.handoff.job();
        if job.kind!=recovery::CompletionRecoveryKind::Main||client.team()?.is_some()||job.chat_id!=self.remainder.context.chat||self.receipt.state!="TERMINAL"{
            return Err(Error::Unavailable{code:"main_metadata_local_store_unsupported",reason:"ORIGINAL_PERSONAL_MAIN_RESULT_REQUIRED"})
        }
        self.artifacts.as_ref().ok_or(Error::Protocol)?.checked_ciphertext_rows(client,&self.handoff)?;
        let source=self.witness.after().ok_or(Error::Protocol)?;client.browser_message_cache_metadata_guard(source,&job.chat_id)?;
        let selected=client.chat_key_ciphertext_from(source,false,&client.wrappers)?;
        let expected=Plain::new(self.remainder.data.readback["metadata"].clone());
        let journal=self.witness.prepare_main_metadata_journal(client)?;self.ensure_current(client)?;
        Ok((expected,Plain::new(source.clone()),Zeroizing::new(selected.ciphertext.to_owned()),client.master_capability()?,journal))
    }
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn claim_metadata_finalize(&self)->Result<()>{self.metadata_finalize_negative()?;self.finalize_issued.compare_exchange(false,true,Ordering::AcqRel,Ordering::Acquire).map_err(|_|Error::Conflict)?;self.metadata_finalize_negative()}
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn metadata_finalize_negative(&self)->Result<()>{
        self.remainder.context.negative()?;self.witness.check_original_negative()?;
        self.port_hold.as_ref().ok_or(Error::Forbidden)?.check_negative()
    }
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn metadata_finalize_chat(&self)->&str{&self.handoff.job().chat_id}
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn cancel_local_finalize(&self){self.witness.cancel_local_retirement();}
    pub fn ensure_current(&self,client:&Client)->Result<()> {
        #[cfg(target_arch="wasm32")] if let Some(port)=&self.port_hold{port.check_original(client)?;}
        self.remainder.context.check(client)?;self.witness.check_original(client,&self.handoff)?;
        if let Some(artifacts)=&self.artifacts{artifacts.check_original(client,&self.handoff)?;}
        self.handoff.negative()?;self.witness.check_original_negative()?;
        #[cfg(target_arch="wasm32")] if let Some(port)=&self.port_hold{port.check_negative()?;}
        Ok(())
    }
    pub fn kind(&self)->&'static str{"recovery_pending_local_persistence"}
    // No receipt/row/artifact/plaintext/remainder/finish export. Actual local
    // store/readback/drain must consume these SAME native resources first.
}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryPendingPersistence {
    inner:recovery::OwnedRecoveryPendingPersistence,remainder:Arc<OwnedBrowserMetadataContinuation>,handoff:Arc<crate::client::OriginalHintRecoveryHandoff>,
    #[cfg(target_arch="wasm32")] port_hold:Option<crate::platform::browser_recovery_port::OriginalBrowserRecoveryPort>,
}
impl BrowserOriginalHintRecoveryPendingPersistence {
    pub fn check_original(&self,client:&Client)->Result<()> {
        #[cfg(target_arch="wasm32")] if let Some(port)=&self.port_hold{port.check_original(client)?;}
        self.inner.check_original(client)?;self.handoff.check_root(client)?;
        #[cfg(target_arch="wasm32")] if let Some(port)=&self.port_hold{port.check_negative()?;}Ok(())
    }
    /// Existing encrypted checkpoint DATA, not a commit/durability receipt.
    pub fn checkpoint(&self)->Result<CompletionRecoveryCheckpoint>{
        #[cfg(target_arch="wasm32")] if let Some(port)=&self.port_hold{port.check_negative()?;}
        let checkpoint=self.inner.checkpoint()?;
        #[cfg(target_arch="wasm32")] if let Some(port)=&self.port_hold{port.check_negative()?;}Ok(checkpoint)
    }
    // No generic commit/finish factory. Physical original-resource successor
    // must preserve inner Stage and opaque actual local-store receipt.
}
#[doc(hidden)]
pub struct BrowserOriginalHintRecoveryDeferred {remainder:Arc<OwnedBrowserMetadataContinuation>,handoff:Arc<crate::client::OriginalHintRecoveryHandoff>,#[cfg(target_arch="wasm32")]port_hold:Option<crate::platform::browser_recovery_port::OriginalBrowserRecoveryPort>}
impl BrowserOriginalHintRecoveryDeferred {
    pub fn kind(&self)->&'static str{"original_recovery_deferred"}
    // Holds original hint/remainder. Deferred is not success, retry, or ACK.
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_owned_hint_recovery_tests.rs"]
mod tests;

impl OwnedBrowserMetadataContinuation {
    /// Actual full notification DATA only; the same original handoff still
    /// owns foreground mode, lease, crypto, physical checkpoint and commit.
    pub fn next_recovery_offer(&self,client:&Client)->Result<Option<CompletionRecoveryJob>>{
        self.check_original(client)?;if !self.metadata_committed{return Err(Error::Conflict)}
        let Mode::Incoming(monitor)=&self.context.mode else{return Err(Error::Forbidden)};
        let issued=self.context.recovery_issued.lock().map_err(|_|Error::Protocol)?.clone();
        if issued.len()>=crate::client::monitor::MAX_LATER_RECOVERY_HINTS{return Ok(None)}
        let unseen=|job:&&CompletionRecoveryJob|!issued.contains(&(match job.kind{crate::client::CompletionRecoveryKind::Main=>0,crate::client::CompletionRecoveryKind::Metadata=>1},job.job_id.clone()));
        let original=monitor.recovery_manifest()?;
        let mut job=original.offered_for_chat(&self.context.chat).find(unseen).cloned();
        if job.is_none(){job=monitor.later_recovery_offer(&self.context.chat,&issued)?;}
        if job.is_none(){
            // This actual pending invalidation is a DISTINCT immutable origin.
            // Capturing it neither extends nor completes the original hint.
            monitor.capture_later_recovery_hint(client)?;
            job=monitor.later_recovery_offer(&self.context.chat,&issued)?;
        }
        self.check_original(client)?;Ok(job)
    }
    /// Detached keyless wake only. The subsequent short Client phase captures
    /// actual pending work; wake/idle/capacity never grants a job or completion.
    pub async fn wait_recovery_work(&self)->Result<()>{
        self.context.negative()?;
        let Mode::Incoming(monitor)=&self.context.mode else{return Err(Error::Forbidden)};
        let bounded=self.context.recovery_issued.lock().map_err(|_|Error::Protocol)?.len()>=crate::client::monitor::MAX_LATER_RECOVERY_HINTS;
        if bounded{self.context.cancelled().await;return Err(Error::Cancelled)}
        monitor.wait_later_recovery_hint().await
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_owned_recovery_scheduler_tests.rs"]
mod scheduler_tests;
