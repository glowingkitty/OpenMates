//! Opaque dispatch guard for original captured recovery offers. It is not a
//! recovery admission/lease/physical store/full-hint completion. Genuine Core
//! foreground phases retain this SAME Arc and create actual result witnesses.
use super::*;
use std::sync::atomic::AtomicBool;
use crate::client::{CompletionRecoveryJob,CompletionRecoveryKind};
/// No constructor, Clone/serde/Debug or caller owner/status/hash authority.
#[doc(hidden)]
pub struct OriginalHintRecoveryHandoff {
    context:Arc<Context>,job:CompletionRecoveryJob,before:Plain<Option<Value>>,core_claimed:AtomicBool,later_origin:Option<Arc<crate::client::monitor::OriginalLaterRecoveryHint>>,
}
impl OriginalHintRecoveryHandoff {
    pub(super) fn capture(context:Arc<Context>,client:&Client,job:&CompletionRecoveryJob)->Result<Arc<Self>> {
        context.check(client)?;context.scope.crypto.check_chat(client,&job.chat_id)?;
        let Mode::Incoming(monitor)=&context.mode else{return Err(Error::Forbidden)};
        // Prefer a separately captured genuine later offer when the original
        // sealed hint was keyless. The original manifest never grows.
        let later_origin=monitor.later_recovery_origin(job)?;
        if later_origin.is_none()&&!monitor.recovery_manifest()?.contains(job){return Err(Error::Forbidden)}
        // Same existing per-row byte bound, no full Client snapshot or key copy.
        crate::client::browser::original_draft_bounds::source_stamp(client,&job.chat_id)?;
        let before=Plain::new(client.chats.get(&job.chat_id).cloned());
        let handoff=Arc::new(Self{context:context.clone(),job:job.clone(),before,core_claimed:AtomicBool::new(false),later_origin});
        handoff.check_before_io(client)?;
        let kind=match job.kind{CompletionRecoveryKind::Main=>0,CompletionRecoveryKind::Metadata=>1};
        {
            let mut issued=context.recovery_issued.lock().map_err(|_|Error::Protocol)?;
            if issued.len()>=crate::client::monitor::MAX_LATER_RECOVERY_HINTS
                ||!issued.insert((kind,job.job_id.clone())){return Err(Error::Conflict)}
        }
        // A failed/abandoned handoff never silently reopens this original job.
        // Retire/requeue through the actual original hint; checkpoint/lease
        // resume remains the genuine foreground protocol's responsibility.
        handoff.check_before_io(client)?;Ok(handoff)
    }
    /// Consume this SAME native handoff's single Core attempt before ANY IO.
    /// Arc clones do not mint another admission. A failed final check, abort or
    /// driver abandonment never reopens the attempt; actual hint/checkpoint
    /// retirement and genuine new admission remain explicit.
    pub(in crate::client) fn claim_core_driver(&self,client:&Client)->Result<crate::client::completion_recovery::OriginalRecoveryActivePermit> {
        self.check_before_io(client)?;
        // Atomic original Context occupancy and per-handoff one-use claim.
        // Reservation is still typed no-effect preparation, never IO settlement.
        let permit=self.context.recovery_active.claim(&self.core_claimed)?;
        self.check_before_io(client)?;self.negative()?;Ok(permit)
    }
    pub(in crate::client) fn job(&self)->&CompletionRecoveryJob{&self.job}
    pub(in crate::client) fn scope_arc(&self)->Arc<OwnedOperationScope>{self.context.scope.clone()}
    pub(in crate::client) fn before_row(&self)->&Option<Value>{&self.before}
    pub(in crate::client) fn selected_chat(&self)->&str{&self.context.chat}
    pub(in crate::client) fn check_before_io(&self,client:&Client)->Result<()> {
        self.context.check(client)?;if let Some(origin)=&self.later_origin{origin.check_original(&self.context.scope)?;}self.context.scope.crypto.check_chat(client,&self.job.chat_id)?;
        if client.chats.get(&self.job.chat_id)!=self.before.as_ref(){return Err(Error::Conflict)}
        self.context.check(client)
    }
    /// Original negative/key/owner/monitor/cursor lifetime ONLY after genuine
    /// driver-owned row mutation. Does not adopt that row or release UI output.
    pub(in crate::client) fn check_root(&self,client:&Client)->Result<()> {
        self.context.check_recovery_root(client)?;if let Some(origin)=&self.later_origin{origin.check_original(&self.context.scope)?;}
        self.context.scope.crypto.check_chat(client,&self.job.chat_id)?;
        self.context.negative()
    }
    /// Additional negative-only restriction AFTER the genuine outer original
    /// scope gate. Does not call application gates, admit IO or publish output.
    pub(in crate::client) fn check_original_negative(&self)->Result<()> {
        self.context.scope.crypto.check_original_operation_negative()?;
        let Mode::Incoming(monitor)=&self.context.mode else{return Err(Error::Forbidden)};
        monitor.check_original_negative()?;if let Some(origin)=&self.later_origin{origin.check_original(&self.context.scope)?;}
        self.context.scope.crypto.check_original_operation_negative()
    }
    pub(in crate::client) fn negative(&self)->Result<()>{self.context.negative()?;if let Some(origin)=&self.later_origin{origin.check_original(&self.context.scope)?;}self.context.negative()}
    pub(in crate::client) async fn cancelled(&self){self.context.cancelled().await}
}

#[cfg(test)]
impl OriginalHintRecoveryHandoff {pub(in crate::client) fn later_origin_for_test(&self)->bool{self.later_origin.is_some()}}
