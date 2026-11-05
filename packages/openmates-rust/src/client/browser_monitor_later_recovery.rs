//! Separate immutable later invalidations on the SAME original monitor/scope.
//! Never extends the first hint, grants foreground, or acknowledges any facet.
use super::*;
use crate::client::CompletionRecoveryJob;
pub(in crate::client) const MAX_LATER_RECOVERY_HINTS:usize=4;
/// Exact received whole hint and its original negative owner. No constructor,
/// Clone/serde, status import or whole-hint-completion method is exported.
pub(in crate::client) struct OriginalLaterRecoveryHint {
    scope:Arc<crate::client::owned_operation::OwnedOperationScope>,
    monitor:Arc<ChatMonitor>,hint:Option<ChatInvalidation>,
}
impl OriginalLaterRecoveryHint {
    pub(in crate::client) fn check_original(&self,scope:&Arc<crate::client::owned_operation::OwnedOperationScope>)->Result<()> {
        if !Arc::ptr_eq(scope,&self.scope)||!self.monitor.is_valid(){return Err(Error::Cancelled)}
        self.scope.crypto.check_original_operation_negative()
    }
    fn manifest(&self)->Result<RecoveryHintManifest>{
        self.check_original(&self.scope)?;
        let result=self.hint.as_ref().ok_or(Error::Cancelled)?.recovery_manifest();
        self.check_original(&self.scope)?;Ok(result)
    }
    fn matches_full_offer(&self,job:&CompletionRecoveryJob)->Result<bool>{
        let manifest=self.manifest()?;
        // A keyless matching identity is never enough for a later handoff.
        for actual in manifest.offered_for_chat(&job.chat_id){
            if serde_json::to_value(actual)?==serde_json::to_value(job)?{return Ok(true)}
        }
        Ok(false)
    }
}
impl Drop for OriginalLaterRecoveryHint {
    fn drop(&mut self){if let Some(hint)=self.hint.take(){let _=self.monitor.requeue(hint);}}
}
impl BrowserOwnedMonitorReadContext {
    pub(in crate::client) fn capture_later_recovery_hint(&self,client:&Client)->Result<bool>{
        self.check(client)?;
        let mut held=self.later_recovery.lock().map_err(|_|Error::Protocol)?;
        if held.len()>=MAX_LATER_RECOVERY_HINTS{return Ok(false)}
        self.scope.crypto.check_original_operation_negative()?;
        if !self.monitor.is_valid(){return Err(Error::Cancelled)}
        let Some(hint)=self.monitor.take_pending()?else{return Ok(false)};
        let actual=Arc::new(OriginalLaterRecoveryHint{scope:self.scope.clone(),monitor:self.monitor.clone(),hint:Some(hint)});
        actual.check_original(&self.scope)?;
        held.push(actual);drop(held);
        self.check(client)?;Ok(true)
    }
    pub(in crate::client) fn later_recovery_origin(&self,job:&CompletionRecoveryJob)->Result<Option<Arc<OriginalLaterRecoveryHint>>>{
        self.negative_check()?;
        let held=self.later_recovery.lock().map_err(|_|Error::Protocol)?.clone();
        let kind=match job.kind{crate::client::CompletionRecoveryKind::Main=>RecoveryHintKind::Main,crate::client::CompletionRecoveryKind::Metadata=>RecoveryHintKind::Metadata};
        let mut later_identity=false;
        for actual in held{
            let manifest=actual.manifest()?;
            later_identity|=manifest.identities().any(|(actual_kind,id,_)|actual_kind==kind&&id==job.job_id);
            if actual.matches_full_offer(job)?{actual.check_original(&self.scope)?;self.negative_check()?;return Ok(Some(actual))}
        }
        self.negative_check()?;
        // A distinct received later identity shadows an older keyless hint.
        // Missing/tampered full data cannot fall back to that older identity.
        if later_identity{return Err(Error::Forbidden)}Ok(None)
    }
    pub(in crate::client) fn later_recovery_offer(&self,chat:&str,issued:&BTreeSet<(u8,String)>)->Result<Option<CompletionRecoveryJob>>{
        self.negative_check()?;
        let held=self.later_recovery.lock().map_err(|_|Error::Protocol)?.clone();
        for actual in held{
            let manifest=actual.manifest()?;
            for job in manifest.offered_for_chat(chat){
                let kind=match job.kind{crate::client::CompletionRecoveryKind::Main=>0,crate::client::CompletionRecoveryKind::Metadata=>1};
                if !issued.contains(&(kind,job.job_id.clone())){actual.check_original(&self.scope)?;self.negative_check()?;return Ok(Some(job.clone()))}
            }
        }
        self.negative_check()?;Ok(None)
    }
    pub(in crate::client) async fn wait_later_recovery_hint(&self)->Result<()> {
        self.negative_check()?;
        let bounded=self.later_recovery.lock().map_err(|_|Error::Protocol)?.len()>=MAX_LATER_RECOVERY_HINTS;
        if bounded{self.cancelled().await;return Err(Error::Cancelled)}
        // changed() is only keyless readiness on the existing socket actor. No
        // Client lock, new receive owner, job access or durable result crosses it.
        tokio::select!{biased;_=self.cancelled()=>Err(Error::Cancelled),result=self.monitor.changed()=>{result?;self.negative_check()}}
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_monitor_later_recovery_tests.rs"]
mod tests;

#[cfg(test)]
impl BrowserOwnedMonitorReadContext {
    /// Test supplier feeds exact full notification DATA through the actual
    /// coalescer/parser on this same monitor. No admission/result is forged.
    pub(in crate::client) fn queue_metadata_offer_for_test(&self,job:&CompletionRecoveryJob)->Result<()> {
        self.negative_check()?;
        record_change(&self.monitor.changes,"metadata_jobs_available",&json!({"jobs":[job]}))
    }
}
#[cfg(test)]
impl BrowserOwnedMonitorReadContext {
    pub(in crate::client) fn queue_metadata_identity_for_test(&self,job:&CompletionRecoveryJob)->Result<()> {
        self.negative_check()?;
        record_change(&self.monitor.changes,"metadata_jobs_available",&json!({"jobs":[{"job_id":job.job_id,"chat_id":job.chat_id}]}))
    }
}
