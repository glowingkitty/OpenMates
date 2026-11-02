//! Opt-in original-resource saved-send preparation. V2 public lifecycle and
//! compatibility wrappers remain available; no browser/default activation here.
use super::*;
use super::owned_operation::OwnedOperationScope;
use std::sync::Arc;
use super::plaintext::{Plain,Wipe};
use super::transport::Socket;
use super::send_observations::SendObservations;
#[path="owned_saved_send_phase.rs"]
mod phase;
#[doc(hidden)]
pub use phase::{OwnedClientPhase,OwnedSavedSendResume,OwnedSavedSendStep,OwnedSavedSendTerminal,OwnedSavedSendDriver,OwnedSavedSendControl,OwnedSavedSendDisposition,OwnedSavedSendReturnedRefusal,OwnedSavedSendRefusalReason};

struct OwnedSendContext {
    admission:OwnedSavedSendAdmission,
    observation:Arc<std::sync::Mutex<ScopedSendObservation>>,
    socket:std::sync::OnceLock<Socket>,
    generation:u64,
    terminal_consumed:std::sync::atomic::AtomicBool,
    apply_active:std::sync::atomic::AtomicUsize,
    apply_abandoned:std::sync::atomic::AtomicBool,
    socket_returned:std::sync::atomic::AtomicBool,
    transport_resources_tracked:std::sync::atomic::AtomicBool,
}
impl Drop for OwnedSendContext {
    fn drop(&mut self){
        self.admission.scope.child().cancel();
        if !self.terminal_consumed.load(std::sync::atomic::Ordering::Acquire){
            self.admission.publication.cancel();self.admission.gate.finish(&self.admission.id,false);
        }
    }
}
impl OwnedSendContext {
    fn resources_returned(&self)->bool{
        self.transport_resources_tracked.load(std::sync::atomic::Ordering::Acquire)
            &&self.socket_returned.load(std::sync::atomic::Ordering::Acquire)
            &&self.apply_active.load(std::sync::atomic::Ordering::Acquire)==0
            &&!self.apply_abandoned.load(std::sync::atomic::Ordering::Acquire)
    }
    fn guard(&self)->SavedSendPublicationGuard{
        let a=&self.admission;
        SavedSendPublicationGuard{id:a.id.clone(),child:a.scope.child(),parent:a.parent.clone(),publication:a.publication.clone(),
            resources:a.scope.crypto.negative_observer(),request:Some(a.request.clone()),owned_lease:Some(a.scope.publication_lease()),
            gate:a.gate.clone(),private_gate:a.private_gate.clone()}
    }
    fn root_fields(&self,client:&Client)->Result<()> {
        let a=&self.admission;
        if a.parent.is_cancelled()||a.parent!=client.operation_parent||self.generation!=client.generation
            ||a.epoch!=client.fresh_auth.operation_epoch()||!Arc::ptr_eq(&a.gate,&client.scoped_send_gate)
            ||!same_private_gate(&a.private_gate,&client.options.private_operation_gate){return Err(Error::Cancelled)}
        Ok(())
    }
    fn check_client(&self,client:&Client,terminated_original:bool)->Result<()> {
        self.root_fields(client)?;client.verify_private_operation()?;
        if terminated_original{self.admission.scope.crypto.check_terminated_child_context(client)?;}
        else{self.admission.scope.check(client)?;}
        self.root_fields(client)?;
        if let Some(chat)=self.admission.chat.as_deref(){
            if !client.task_watch_authority.cached_chat_allowed(chat){return Err(Error::Forbidden)}
        }
        Ok(())
    }
    fn check_active_phase(&self,client:&Client)->Result<()> {
        self.check_client(client,false)?;
        self.admission.gate.check_publication(&self.admission.id,&self.admission.publication)?;
        if !client.scoped_send_observation.as_ref().is_some_and(|v|Arc::ptr_eq(v,&self.observation)){return Err(Error::Cancelled)}
        Ok(())
    }
    fn check_socket(&self,socket:&Socket)->Result<()> {
        if !self.socket.get().is_some_and(|original|original.same_original_socket(socket)){return Err(Error::Cancelled)}Ok(())
    }
}

struct OwnedSavedSendAdmission {
    id:String,chat:Option<String>,request:CancellationToken,parent:CancellationToken,
    publication:CancellationToken,scope:Arc<OwnedOperationScope>,epoch:u64,
    gate:Arc<ScopedSendGate>,private_gate:Option<Arc<dyn Fn()->Result<()>+Send+Sync>>,
}
/// Actual original prepared context, never a server/caller status or serialized
/// permission. Dropping an unstarted resource revokes only its own child/output.
#[doc(hidden)]
pub struct PreparedOwnedSavedSend {admission:Option<OwnedSavedSendAdmission>}
impl PreparedOwnedSavedSend {
    fn current(&self)->Result<&OwnedSavedSendAdmission>{self.admission.as_ref().ok_or(Error::Cancelled)}
    pub fn id(&self)->Result<&str>{Ok(&self.current()?.id)}
    pub fn cancellation_request(&self)->Result<CancellationToken>{Ok(self.current()?.request.clone())}
    pub fn publication_guard(&self)->Result<SavedSendPublicationGuard>{
        let original=self.current()?;
        Ok(SavedSendPublicationGuard{id:original.id.clone(),child:original.scope.child(),parent:original.parent.clone(),
            publication:original.publication.clone(),resources:original.scope.crypto.negative_observer(),
            request:Some(original.request.clone()),owned_lease:Some(original.scope.publication_lease()),
            gate:original.gate.clone(),private_gate:original.private_gate.clone()})
    }
}
impl Drop for PreparedOwnedSavedSend {
    fn drop(&mut self){if let Some(original)=&self.admission{original.scope.child().cancel();original.publication.cancel();}}
}
impl Client {
    fn promote_owned_saved_send(&self,prepared:PreparedSavedSend)->Result<PreparedOwnedSavedSend>{
        self.verify_private_operation()?;
        if prepared.parent.is_cancelled()||prepared.parent!=self.operation_parent
            ||prepared.epoch!=self.fresh_auth.operation_epoch()
            ||!Arc::ptr_eq(&prepared.gate,&self.scoped_send_gate)
            ||!same_private_gate(&prepared.private_gate,&self.options.private_operation_gate){return Err(Error::Cancelled)}
        let PreparedSavedSend{id,chat,request,child,publication,parent,scope,epoch,gate,private_gate}=prepared;
        let scope=Arc::new(OwnedOperationScope::promote_saved_send_preparation(self,scope,request.clone())?);
        // The provisional V2 child has never escaped or authorized any effect.
        // The returned resource/guard both refer to the SAME actual issued child.
        child.cancel();
        scope.check(self)?;
        Ok(PreparedOwnedSavedSend{admission:Some(OwnedSavedSendAdmission{id,chat,request,parent,
            publication,scope,epoch,gate,private_gate})})
    }
    #[doc(hidden)]
    pub fn prepare_owned_saved_send(&self,chat:Option<&str>,request:CancellationToken)->Result<PreparedOwnedSavedSend>{
        self.promote_owned_saved_send(self.prepare_scoped_saved_send(chat,request)?)
    }
    #[doc(hidden)]
    pub async fn prepare_validated_owned_saved_send(&mut self,chat:Option<&str>,request:CancellationToken)->Result<PreparedOwnedSavedSend>{
        // Same real native validation policy; no scope exists with an empty
        // owner and no empty-owner scope is relabeled after authentication.
        let prepared=self.prepare_validated_scoped_saved_send(chat,request).await?;
        self.promote_owned_saved_send(prepared)
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
mod preparation_tests {
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    use super::*;
    fn client()->Client {
        let api="https://example.invalid";let mut c=Client::new(api,Some(Session{api_url:api.into(),session_id:"owned-fixture".into(),
            cookies:Default::default(),ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"fixture".into(),
            user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).expect("explicit native fixture");
        c.user=json!({"id":"11111111-1111-4111-8111-111111111111"});c
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn actual_original_preparation_issues_one_sibling_and_drop_only_retires_it(){
        let c=client();let parent=c.operation_parent.clone();let ordinary=c.operation_cancel.clone();
        let prepared=c.prepare_owned_saved_send(None,CancellationToken::new()).expect("actual prepared scope");
        let admitted=prepared.current().expect("original");let child=admitted.scope.child();
        assert_ne!(child,ordinary);assert_eq!(admitted.parent,parent);
        let guard=prepared.publication_guard().expect("actual original resource");
        guard.owned_lease.as_ref().expect("original registration").check_original_negative().expect("live actual sibling");
        assert!(guard.check_release().is_err(),"preparation alone does not start/admit or publish");
        let peer=OwnedOperationScope::capture(&c,CancellationToken::new()).expect("genuine peer");
        drop(prepared);assert!(child.is_cancelled());assert!(!parent.is_cancelled());assert!(!ordinary.is_cancelled());
        assert!(guard.owned_lease.as_ref().expect("same registration").check_original_negative().is_err());
        peer.check(&c).expect("drop did not retire peer");
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn promotion_cannot_recapture_current_authority_after_original_denial_or_epoch_change(){
        let c=client();let original=c.prepare_scoped_saved_send(None,CancellationToken::new()).expect("original typed preparation");
        c.task_watch_authority.deny_cached_chat(None).expect("actual negative revision");
        assert!(c.promote_owned_saved_send(original).is_err(),"must retain old original denial revision");
        let mut c=client();let original=c.prepare_scoped_saved_send(None,CancellationToken::new()).expect("original typed preparation");
        c.set_private_operation_gate(None);assert!(c.promote_owned_saved_send(original).is_err(),"no fresh epoch/gate recapture");
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="owned_saved_send_tests.rs"]
mod ownership_tests;

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="owned_saved_send_refusal_tests.rs"]
mod refusal_tests;
