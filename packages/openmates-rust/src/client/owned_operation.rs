//! Core-issued sibling identity for owned work; never a credential/read grant.
//! Ordinary AsyncCryptoScope mode keeps its original current-child comparison.
use super::*;
use std::sync::{Arc,Weak,Mutex,atomic::{AtomicU64,AtomicBool,Ordering}};
const MAX_OWNED_OPERATIONS:usize=100;
const MAX_COOKIE_EDGES:usize=4096;
/// Closed known genuine origins only. Foreign JSON/status/raw revisions cannot
/// construct either receipt, and no open generic transition provider is accepted.
enum ActualOwnedCredentialTransition<'a> {
    Cookie(&'a transport::ActualCookieTransition),
    SessionValidation(&'a auth::ActualSessionValidationTransition),
}
impl ActualOwnedCredentialTransition<'_> {
    fn revisions(&self)->(u64,u64){match self{Self::Cookie(v)=>v.revisions(),Self::SessionValidation(v)=>v.revisions()}}
    fn binding_pair(&self)->(&[u8;32],&[u8;32]){match self{Self::Cookie(v)=>v.binding_pair(),Self::SessionValidation(v)=>v.binding_pair()}}
    fn check_original_client(&self,client:&Client)->Result<()>{match self{Self::Cookie(v)=>v.check_original_client(client),Self::SessionValidation(v)=>v.check_original_client(client)}}
    fn check_applied_state(&self,client:&Client)->Result<()>{match self{Self::Cookie(v)=>v.check_applied_state(client),Self::SessionValidation(v)=>v.check_applied_state(client)}}
}
struct CookieEdge {after_revision:u64,before:zeroize::Zeroizing<[u8;32]>,after:zeroize::Zeroizing<[u8;32]>}
fn follows_cookie_edges(edges:&BTreeMap<u64,CookieEdge>,mut revision:u64,mut binding:[u8;32],target:u64,expected:&[u8;32])->bool{
    if revision>target{return false}
    for _ in 0..=MAX_COOKIE_EDGES {
        if revision==target{return binding==*expected}
        let Some(edge)=edges.get(&revision) else{return false};
        if *edge.before!=binding||edge.after_revision<=revision||edge.after_revision>target{return false}
        revision=edge.after_revision;binding=*edge.after;
    }
    false
}
#[derive(Default)]
struct RegistryState {issued:bool,entries:BTreeMap<String,Weak<LeaseEntry>>,cookie_edges:BTreeMap<u64,CookieEdge>}
#[derive(Default)]
pub(super) struct OwnedOperationRegistry {
    state:Mutex<RegistryState>,revision:AtomicU64,exhausted:AtomicBool,wake:tokio::sync::Notify,
}
struct LeaseEntry {
    registry:Weak<OwnedOperationRegistry>,id:String,revision:u64,
    parent:CancellationToken,child:CancellationToken,request:CancellationToken,
    initial_credential_revision:u64,initial_credential_binding:zeroize::Zeroizing<[u8;32]>,
}
impl Drop for LeaseEntry {
    fn drop(&mut self){
        self.child.cancel();
        if let Some(registry)=self.registry.upgrade() {
            if let Ok(mut state)=registry.state.try_lock(){
                if registry.revision.load(Ordering::Acquire)==self.revision {state.entries.remove(&self.id);}
            }
        }
    }
}
/// Identity is issued only under an actual Client scope. Clone retains the same
/// original registration; it never issues a replacement child or refreshes it.
#[derive(Clone)]
pub(super) struct OwnedOperationLease {entry:Arc<LeaseEntry>}
impl OwnedOperationRegistry {
    pub(super) fn issue(self:&Arc<Self>,parent:&CancellationToken,request:CancellationToken,credential_revision:u64,credential_binding:[u8;32])->Result<OwnedOperationLease>{
        if parent.is_cancelled(){return Err(Error::Cancelled)}
        let mut state=self.state.lock().map_err(|_|Error::Cancelled)?;
        let current_revision=self.revision.load(Ordering::Acquire);
        state.entries.retain(|_,entry|entry.upgrade().is_some_and(|entry|entry.revision==current_revision));
        if self.exhausted.load(Ordering::Acquire){return Err(Error::Cancelled)}
        // A new sibling cannot silently start a fresh anchor over unexplained
        // drift while another original resource is still live.
        if state.entries.values().filter_map(Weak::upgrade).any(|entry|
            !follows_cookie_edges(&state.cookie_edges,entry.initial_credential_revision,*entry.initial_credential_binding,credential_revision,&credential_binding)) {
            drop(state);self.invalidate();return Err(Error::Cancelled)
        }
        let revision=self.revision.load(Ordering::Acquire);
        if state.entries.len()>=MAX_OWNED_OPERATIONS{return Err(Error::Conflict)}
        let id=uuid::Uuid::new_v4().to_string();
        if state.entries.contains_key(&id){return Err(Error::Conflict)}
        let entry=Arc::new(LeaseEntry{registry:Arc::downgrade(self),id:id.clone(),revision,
            parent:parent.clone(),child:parent.child_token(),request,initial_credential_revision:credential_revision,
            initial_credential_binding:zeroize::Zeroizing::new(credential_binding)});
        state.issued=true;
        state.entries.insert(id,Arc::downgrade(&entry));
        if self.revision.load(Ordering::Acquire)!=revision {entry.child.cancel();return Err(Error::Cancelled)}
        Ok(OwnedOperationLease{entry})
    }
    // A missing principal is compatible only with a genuinely empty original
    // epoch. Never relabel unreadable live owned authority as legacy import.
    pub(super) fn require_empty_import_compatibility(&self)->Result<()> {
        let mut state=self.state.lock().map_err(|_|Error::Cancelled)?;
        if self.exhausted.load(Ordering::Acquire){return Err(Error::Cancelled)}
        state.entries.retain(|_,entry|entry.upgrade().is_some());
        if state.issued||!state.entries.is_empty(){return Err(Error::Cancelled)}
        Ok(())
    }
    pub(super) fn checked_auth_binding(&self,client:&Client)->Result<[u8;32]>{
        match client.fresh_auth_binding(){
            Ok(binding)=>Ok(binding),
            Err(error)=>{self.invalidate();Err(error)}
        }
    }
    fn refuse_unverifiable_cookie_lineage(&self)->Result<()>{
        let live=match self.state.lock(){
            Ok(mut state)=>{
                let revision=self.revision.load(Ordering::Acquire);
                state.entries.retain(|_,entry|entry.upgrade().is_some_and(|entry|entry.revision==revision));
                !state.entries.is_empty()
            },
            Err(_)=>{self.invalidate();return Err(Error::Cancelled)},
        };
        if !live{return Ok(())}
        self.invalidate();Err(Error::Cancelled)
    }
    fn record_cookie_transition(&self,client:&Client,transition:&transport::ActualCookieTransition)->Result<()>{
        self.record_credential_transition(client,ActualOwnedCredentialTransition::Cookie(transition))
    }
    fn record_session_validation_transition(&self,client:&Client,transition:&auth::ActualSessionValidationTransition)->Result<()>{
        self.record_credential_transition(client,ActualOwnedCredentialTransition::SessionValidation(transition))
    }
    fn record_credential_transition(&self,client:&Client,transition:ActualOwnedCredentialTransition<'_>)->Result<()>{
        let mut state=self.state.lock().map_err(|_|Error::Cancelled)?;
        let current_revision=self.revision.load(Ordering::Acquire);
        state.entries.retain(|_,entry|entry.upgrade().is_some_and(|entry|entry.revision==current_revision));
        // Truly no issued live resource: preserve ordinary transport exactly.
        if state.entries.is_empty(){state.cookie_edges.clear();return Ok(())}
        drop(state);
        transition.check_original_client(client)?;transition.check_applied_state(client)?;
        let(before_revision,after_revision)=transition.revisions();let(before,after)=transition.binding_pair();
        let mut state=self.state.lock().map_err(|_|Error::Cancelled)?;
        let current_revision=self.revision.load(Ordering::Acquire);
        state.entries.retain(|_,entry|entry.upgrade().is_some_and(|entry|entry.revision==current_revision));
        if state.entries.is_empty(){state.cookie_edges.clear();return Ok(())}
        let revision=self.revision.load(Ordering::Acquire);
        if state.entries.values().filter_map(Weak::upgrade).any(|entry|entry.revision!=revision){return Err(Error::Cancelled)}
        // Every surviving original lease must reach this exact before binding
        // through witnessed edges; numbers alone cannot rebase its authority.
        for entry in state.entries.values().filter_map(Weak::upgrade){
            if !follows_cookie_edges(&state.cookie_edges,entry.initial_credential_revision,*entry.initial_credential_binding,before_revision,before){return Err(Error::Cancelled)}
        }
        if let Some(edge)=state.cookie_edges.get(&before_revision){
            if edge.after_revision==after_revision&&*edge.before==*before&&*edge.after==*after{return Ok(())}
            return Err(Error::Cancelled)
        }
        let min=state.entries.values().filter_map(Weak::upgrade).map(|entry|entry.initial_credential_revision).min().ok_or(Error::Cancelled)?;
        state.cookie_edges.retain(|_,edge|edge.after_revision>min);
        if state.cookie_edges.len()>=MAX_COOKIE_EDGES{return Err(Error::Conflict)}
        state.cookie_edges.insert(before_revision,CookieEdge{after_revision,before:zeroize::Zeroizing::new(*before),after:zeroize::Zeroizing::new(*after)});Ok(())
    }
    /// Synchronous negative revocation; never wait for IO or foreign allocation.
    pub(super) fn invalidate(&self){
        // Publish revocation before any lock/cleanup. In-flight original driver
        // waits observe this exact negative epoch and wake even on contention.
        if self.revision.fetch_update(Ordering::AcqRel,Ordering::Acquire,|revision|revision.checked_add(1)).is_err(){
            self.exhausted.store(true,Ordering::Release);
        }
        self.wake.notify_waiters();
        let entries=match self.state.try_lock(){
            Ok(mut state)=>{let entries=state.entries.values().filter_map(Weak::upgrade).collect::<Vec<_>>();state.entries.clear();state.cookie_edges.clear();entries},
            Err(_)=>return,
        };
        for entry in entries{entry.child.cancel();}
    }
}
impl OwnedOperationLease {
    pub(super) fn child(&self)->&CancellationToken{&self.entry.child}
    pub(super) fn request(&self)->&CancellationToken{&self.entry.request}
    pub(super) fn cancel(&self){self.entry.child.cancel();}
    /// Original child/request/parent/registration negatives only; no terminal
    /// exception or Client/read/effect authority is available to this caller.
    pub(super) fn check_original_negative(&self)->Result<()>{self.check_release(false)}
    pub(super) fn check_client(&self,client:&Client,terminal:bool)->Result<()>{
        let registry=self.entry.registry.upgrade().ok_or(Error::Cancelled)?;
        if !Arc::ptr_eq(&registry,&client.owned_operations)||self.entry.parent!=client.operation_parent{return Err(Error::Cancelled)}
        self.check_release(terminal)
    }
    pub(super) fn check_initial_credentials(&self,client:&Client,terminal:bool)->Result<()>{
        self.check_credentials(client,self.entry.initial_credential_revision,&self.entry.initial_credential_binding,terminal)
    }
    pub(super) fn check_credentials(&self,client:&Client,revision:u64,binding:&[u8;32],terminal:bool)->Result<()>{
        self.check_client(client,terminal)?;
        let registry=self.entry.registry.upgrade().ok_or(Error::Cancelled)?;
        let current=registry.checked_auth_binding(client)?;
        let state=registry.state.lock().map_err(|_|Error::Cancelled)?;
        let valid=follows_cookie_edges(&state.cookie_edges,revision,*binding,client.credential_revision,&current);
        drop(state);
        if !valid{registry.invalidate();return Err(Error::Cancelled)}
        Ok(())
    }
    pub(super) async fn cancelled(&self){
        loop {
            let Some(registry)=self.entry.registry.upgrade() else{return};
            let changed=registry.wake.notified();tokio::pin!(changed);changed.as_mut().enable();
            if self.check_release(false).is_err(){return}
            tokio::select!{biased;
                _=self.entry.parent.cancelled()=>return,
                _=self.entry.child.cancelled()=>return,
                _=self.entry.request.cancelled()=>return,
                _=&mut changed=>{},
            }
        }
    }
    /// Nonblocking original registration observation; no Client borrow or IO.
    /// terminal=true is private to the actual returned driver terminal path.
    fn check_release(&self,terminal:bool)->Result<()>{
        if self.entry.parent.is_cancelled()||(!terminal&&(self.entry.child.is_cancelled()||self.entry.request.is_cancelled())){return Err(Error::Cancelled)}
        let registry=self.entry.registry.upgrade().ok_or(Error::Cancelled)?;
        if registry.exhausted.load(Ordering::Acquire)||registry.revision.load(Ordering::Acquire)!=self.entry.revision{return Err(Error::Cancelled)}
        Ok(())
    }
}
/// Exclusive short Client phase for an already issued sibling. The guard owns
/// the mutable borrow and restores the previous phase on every drop/error.
/// It neither replaces/cancels the ordinary child nor changes the parent.
pub(super) struct ActiveOwnedClient<'a>{client:&'a mut Client,previous:Option<OwnedOperationLease>}
impl<'a> ActiveOwnedClient<'a>{
    pub(super) fn enter(client:&'a mut Client,scope:&OwnedOperationScope)->Result<Self>{
        scope.check(client)?;
        let previous=client.active_owned_operation.replace(scope.lease.clone());
        Ok(Self{client,previous})
    }
}
impl std::ops::Deref for ActiveOwnedClient<'_>{type Target=Client;fn deref(&self)->&Client{&*self.client}}
impl std::ops::DerefMut for ActiveOwnedClient<'_>{fn deref_mut(&mut self)->&mut Client{&mut *self.client}}
impl Drop for ActiveOwnedClient<'_>{fn drop(&mut self){self.client.active_owned_operation=self.previous.take();}}

impl Client {
    /// Only a real shared HTTP header merge can supply this nonserializable
    /// receipt. Unexplained live lineage revokes all original owned scopes.
    /// Changed real headers were merged but no verifiable typed transition
    /// could be minted. Only the actual empty registry preserves ordinary auth
    /// setup; every still-live original sibling is synchronously revoked.
    pub(in crate::client) fn refuse_unverifiable_owned_cookie_lineage(&self)->Result<()>{
        self.owned_operations.refuse_unverifiable_cookie_lineage()
    }
    /// Real validated auth BODY observation only; the auth module alone mints
    /// this sealed proof after installing the actual token/user/revision. Same
    /// exact edge enforcement as real header rotation, never a numeric rebase.
    pub(in crate::client) fn record_actual_session_validation_transition(&self,transition:&auth::ActualSessionValidationTransition)->Result<()>{
        match self.owned_operations.record_session_validation_transition(self,transition){
            Ok(())=>Ok(()),Err(error)=>{self.owned_operations.invalidate();Err(error)}
        }
    }
    pub(in crate::client) fn refuse_unverifiable_owned_session_validation_lineage(&self)->Result<()>{
        self.owned_operations.refuse_unverifiable_cookie_lineage()
    }
    /// Preserve the actual original auth error after an unsuccessful real body
    /// left its binding unreadable. This only revokes live negative resources.
    pub(in crate::client) fn revoke_unreadable_owned_session_validation_lineage(&self){
        let _=self.owned_operations.refuse_unverifiable_cookie_lineage();
    }
    pub(in crate::client) fn record_actual_cookie_transition(&self,transition:&transport::ActualCookieTransition)->Result<()>{
        match self.owned_operations.record_cookie_transition(self,transition){
            Ok(())=>Ok(()),Err(error)=>{self.owned_operations.invalidate();Err(error)}
        }
    }
}

/// Original crypto/owner/policy scope plus its genuine sibling identity. The
/// registry alone is insufficient to decrypt, read, write or publish anything.
pub(super) struct OwnedOperationScope {
    pub(super) crypto:sync_capability::AsyncCryptoScope,
    lease:OwnedOperationLease,
    private_gate:Option<Arc<dyn Fn()->Result<()>+Send+Sync>>,
}
/// Only pre-dispatch original negative children. No lease/key/credential data,
/// lookup of the current Client, registry reset or replacement authority.
pub(super) struct DispatchedAuthNegativeCohort {children:Vec<CancellationToken>}
impl DispatchedAuthNegativeCohort {
    pub(super) fn revoke(&self){for child in &self.children{child.cancel();}}
}
impl OwnedOperationScope {
    /// Local draft purpose only, derived from the actual sealed admission.
    /// Generic capture remains canonical-only; this does not admit a server
    /// read/send, replace profile material or manufacture a native Session.
    pub(super) fn capture_local_draft(client:&Client,admission:&super::BrowserDraftAdmission)->Result<Self>{
        admission.check(client)?;
        let original=sync_capability::AsyncCryptoScope::begin(client)?;
        admission.check(client)?;
        // Preserve the actual original request cancellation, plus an independent
        // registry child for this draft. No detached replacement token is used.
        let request=client.current_operation_child();
        let lease=client.owned_operations.issue(&client.operation_parent,request,
            client.credential_revision,client.owned_operations.checked_auth_binding(client)?)?;
        let crypto=original.into_owned(client,lease.clone())?;
        let scope=Self{crypto,lease,private_gate:client.options.private_operation_gate.clone()};
        scope.check(client)?;admission.check(client)?;
        // The final admission callback may revoke an original resource. Observe
        // its negatives without calling another application gate or recapture.
        scope.crypto.check_original_operation_negative()?;
        Ok(scope)
    }
    pub(super) fn capture(client:&Client,request:CancellationToken)->Result<Self>{
        client.verify_private_operation()?;client.require_canonical_read_profile()?;
        let original=sync_capability::AsyncCryptoScope::begin(client)?;
        let lease=client.owned_operations.issue(&client.operation_parent,request,client.credential_revision,client.owned_operations.checked_auth_binding(client)?)?;
        let crypto=original.into_owned(client,lease.clone())?;
        Ok(Self{crypto,lease,private_gate:client.options.private_operation_gate.clone()})
    }
    /// Promote the actual original saved-send preparation synchronously, before
    /// any guard/driver escapes or IO can suspend. Preserve its captured crypto
    /// identity instead of taking a fresh current scope after an await.
    pub(super) fn promote_saved_send_preparation(client:&Client,original:sync_capability::AsyncCryptoScope,
        request:CancellationToken)->Result<Self>{
        client.verify_private_operation()?;client.require_canonical_read_profile()?;
        original.check(client)?;
        let lease=client.owned_operations.issue(&client.operation_parent,request,
            client.credential_revision,client.owned_operations.checked_auth_binding(client)?)?;
        let crypto=original.into_owned(client,lease.clone())?;
        let scope=Self{crypto,lease,private_gate:client.options.private_operation_gate.clone()};
        scope.check(client)?;Ok(scope)
    }
    pub(super) fn publication_lease(&self)->OwnedOperationLease{self.lease.clone()}
    pub(super) fn check(&self,client:&Client)->Result<()>{
        client.verify_private_operation()?;
        if !same_private_gate(&self.private_gate,&client.options.private_operation_gate){return Err(Error::Cancelled)}
        self.crypto.check(client)
    }
    /// Continue ONLY the same sealed auth pre-body observation through actual
    /// recorded credential edges. No raw revision/current-snapshot waiver or
    /// new operation/parent/resource admission is available to this caller.
    pub(super) fn check_original_session_validation_lineage(&self,client:&Client,before:&auth::BeforeSessionValidation)->Result<()>{
        self.check(client)?;
        before.check_original_client(client)?;
        self.lease.check_credentials(client,before.revision(),before.binding(),false)?;
        // Full check above can invoke the captured original private gate. All
        // remaining checks are callback-free original negative observations.
        self.lease.check_original_negative()?;
        self.crypto.check_original_operation_negative()
    }
    /// Matched dispatched credential observation ONLY. A stopped request/child
    /// may retain its rotated auth body; no private work or output is granted.
    pub(super) fn check_dispatched_session_validation_lineage(&self,client:&Client,before:&auth::BeforeSessionValidation)->Result<()>{
        self.crypto.check_dispatched_credential_observation(client)?;
        before.check_original_client(client)?;
        self.lease.check_credentials(client,before.revision(),before.binding(),true)?;
        self.crypto.check_dispatched_credential_observation(client)
    }
    pub(super) fn capture_dispatched_auth_negative_cohort(&self,client:&Client)->Result<DispatchedAuthNegativeCohort>{
        self.check(client)?;
        let registry=self.lease.entry.registry.upgrade().ok_or(Error::Cancelled)?;
        if !Arc::ptr_eq(&registry,&client.owned_operations){return Err(Error::Cancelled)}
        let state=registry.state.lock().map_err(|_|Error::Cancelled)?;
        let revision=registry.revision.load(Ordering::Acquire);
        if registry.exhausted.load(Ordering::Acquire)||revision!=self.lease.entry.revision
            ||self.lease.entry.parent!=client.operation_parent
            ||!state.entries.get(&self.lease.entry.id).and_then(Weak::upgrade)
                .is_some_and(|entry|Arc::ptr_eq(&entry,&self.lease.entry)){return Err(Error::Cancelled)}
        let mut children=Vec::with_capacity(state.entries.len().min(MAX_OWNED_OPERATIONS));
        for entry in state.entries.values().filter_map(Weak::upgrade){
            if entry.revision!=revision{continue}
            if entry.parent!=self.lease.entry.parent{return Err(Error::Cancelled)}
            children.push(entry.child.clone());
            if children.len()>MAX_OWNED_OPERATIONS{return Err(Error::Conflict)}
        }
        drop(state);
        self.crypto.check_original_operation_negative()?;
        Ok(DispatchedAuthNegativeCohort{children})
    }
    pub(super) fn observer(&self)->OwnedOperationObserver{
        OwnedOperationObserver{crypto:self.crypto.negative_observer(),lease:self.lease.clone(),private_gate:self.private_gate.clone()}
    }
    pub(super) async fn cancelled(&self){self.crypto.original_operation_cancelled().await}
    pub(super) fn child(&self)->CancellationToken{self.lease.child().clone()}
    pub(super) fn request(&self)->CancellationToken{self.lease.request().clone()}
}
#[derive(Clone)]
pub(super) struct OwnedOperationObserver {
    crypto:sync_capability::NegativeCryptoScope,lease:OwnedOperationLease,
    private_gate:Option<Arc<dyn Fn()->Result<()>+Send+Sync>>,
}
impl OwnedOperationObserver {
    pub(super) fn check_release(&self)->Result<()>{
        self.check_original_negative()?;
        if let Some(gate)=&self.private_gate{gate()?;}
        // Caller code can synchronously revoke the ORIGINAL request/parent or
        // denial resource while returning Ok. Recheck after its final callback.
        self.check_original_negative()
    }
    /// Final original negatives without invoking another caller gate.
    pub(super) fn check_original_negative(&self)->Result<()>{
        self.lease.check_release(false)?;self.crypto.check_release()
    }
    pub(super) fn cancel(&self){self.lease.cancel();}
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[cfg(all(test,not(target_arch="wasm32")))]
mod tests {
    use super::*;
    fn client()->Client {
        let mut client=Client::new("https://example.invalid",Some(Session{api_url:"https://example.invalid".into(),session_id:"fixture".into(),
            cookies:BTreeMap::new(),ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),
            email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).expect("fixture");
        client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});client
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn genuine_siblings_keep_same_parent_and_child_cancel_does_not_retire_peer(){
        let client=client();let a=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("A");
        let b=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("B");
        assert_ne!(a.child(),b.child());assert_eq!(a.lease.entry.parent,b.lease.entry.parent);
        a.observer().cancel();assert!(a.observer().check_release().is_err());assert!(b.observer().check_release().is_ok());
        b.check(&client).expect("B current");client.operation_parent.cancel();assert!(b.observer().check_release().is_err());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn exact_registration_cannot_survive_parent_policy_denial_or_reset(){
        let mut client=client();let a=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("A");
        client.set_operation_cancel(CancellationToken::new());assert!(a.observer().check_release().is_err());
        let b=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("B");
        client.set_private_operation_gate(None);assert!(b.observer().check_release().is_err());
        let c=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("C");
        client.task_watch_authority.deny_cached_chat(None).expect("denial");assert!(c.observer().check_release().is_err());
        client.forget_session();assert!(c.check(&client).is_err());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn ordinary_global_child_fence_remains_exact_and_owned_final_check_is_nonblocking(){
        let mut client=client();let ordinary=sync_capability::AsyncCryptoScope::begin(&client).expect("ordinary");
        let a=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("A");
        let parent=client.operation_parent.clone();client.set_operation_cancel(parent);
        assert!(ordinary.check(&client).is_err());a.check(&client).expect("actual sibling survives same-parent ordinary child replacement");
        let held=client.owned_operations.state.lock().expect("fixture hold");
        assert!(a.observer().check_release().is_ok(),"negative resource check never blocks on mutation bookkeeping");drop(held);
        client.owned_operations.invalidate();assert!(a.observer().check_release().is_err());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn missing_or_forged_cookie_edge_never_rebases_a_live_original_scope(){
        let mut client=client();let a=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("A");
        let b=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("B");
        client.cookies.insert("auth_refresh_token".into(),"unwitnessed".into());
        assert!(OwnedOperationScope::capture(&client,CancellationToken::new()).is_err(),"new sibling cannot recapture over unknown live lineage");
        assert!(a.check(&client).is_err());assert!(b.observer().check_release().is_err());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn cookie_path_requires_exact_every_before_after_binding_and_monotone_revision(){
        let mut edges=BTreeMap::new();
        edges.insert(0,CookieEdge{after_revision:1,before:zeroize::Zeroizing::new([1;32]),after:zeroize::Zeroizing::new([2;32])});
        edges.insert(1,CookieEdge{after_revision:2,before:zeroize::Zeroizing::new([2;32]),after:zeroize::Zeroizing::new([3;32])});
        assert!(follows_cookie_edges(&edges,0,[1;32],2,&[3;32]));
        assert!(!follows_cookie_edges(&edges,0,[9;32],2,&[3;32]));
        assert!(!follows_cookie_edges(&edges,0,[1;32],2,&[9;32]));
        edges.remove(&1);assert!(!follows_cookie_edges(&edges,0,[1;32],2,&[3;32]));
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn callback_free_original_operation_negatives_keep_actual_token_and_denial_identity(){
        let mut c=client();let ordinary=sync_capability::AsyncCryptoScope::begin(&c).expect("actual ordinary scope");
        ordinary.check_original_operation_negative().expect("original live scope");
        let parent=c.operation_parent.clone();c.set_operation_cancel(parent.clone());
        assert!(!parent.is_cancelled());assert!(ordinary.check_original_operation_negative().is_err(),"old actual child stays retired");
        let request=CancellationToken::new();let a=OwnedOperationScope::capture(&c,request.clone()).expect("A");
        let b=OwnedOperationScope::capture(&c,CancellationToken::new()).expect("B");
        request.cancel();assert!(a.crypto.check_original_operation_negative().is_err());
        b.crypto.check_original_operation_negative().expect("same-parent B unaffected by A request");
        c.task_watch_authority.deny_cached_chat(None).expect("actual denial");
        assert!(b.crypto.check_original_operation_negative().is_err());
        let c=client();let scope=sync_capability::AsyncCryptoScope::begin(&c).expect("captured original parent");
        c.operation_parent.cancel();assert!(scope.check_original_operation_negative().is_err());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn gate_returning_ok_cannot_hide_synchronous_original_negative_revocation(){
        use std::sync::atomic::{AtomicBool,Ordering};
        for kind in 0..3 {
            let mut client=client();let request=CancellationToken::new();
            let armed=Arc::new(AtomicBool::new(false));let gate_armed=armed.clone();
            let original_request=request.clone();let original_parent=client.operation_parent.clone();
            let original_authority=client.task_watch_authority.clone();
            client.set_private_operation_gate(Some(Arc::new(move||{
                if gate_armed.load(Ordering::Acquire){
                    match kind {0=>original_request.cancel(),1=>original_parent.cancel(),_=>original_authority.deny_cached_chat(None)?}
                }
                Ok(())
            })));
            let a=OwnedOperationScope::capture(&client,request).expect("actual original sibling");
            armed.store(true,Ordering::Release);
            assert!(a.observer().check_release().is_err(),"post-gate original negative must refuse");
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn unreadable_original_binding_revokes_check_and_issuance_observers(){
        for issue in [false,true] {
            let mut client=client();let a=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("A");
            let b=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("B");
            client.user=Value::Null;
            assert_eq!(client.fresh_auth_binding().err(),Some(Error::Protocol));
            if issue {assert!(OwnedOperationScope::capture(&client,CancellationToken::new()).is_err());}
            else {assert!(a.check(&client).is_err());}
            assert!(a.observer().check_release().is_err());assert!(b.observer().check_release().is_err());
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn unverifiable_header_hook_uses_actual_live_registry_and_preserves_empty_auth_setup(){
        let empty=client();empty.refuse_unverifiable_owned_cookie_lineage().expect("no owned operation exists");
        let client=client();let a=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("A");
        let b=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("B");
        assert_eq!(client.refuse_unverifiable_owned_cookie_lineage(),Err(Error::Cancelled));
        assert!(a.observer().check_release().is_err());assert!(b.observer().check_release().is_err());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn actual_http_cookie_header_keeps_siblings_and_unknown_revision_revokes_them(){
        use tokio::io::{AsyncReadExt,AsyncWriteExt};
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.expect("fixture listener");
        let address=listener.local_addr().expect("fixture address");
        let server=tokio::spawn(async move{
            let(mut stream,_)=listener.accept().await.expect("request");let mut request=Vec::new();
            loop{let mut bytes=[0u8;1024];let read=stream.read(&mut bytes).await.expect("request bytes");assert!(read>0);request.extend_from_slice(&bytes[..read]);if request.windows(4).any(|part|part==b"\r\n\r\n"){break;}assert!(request.len()<8192);}
            assert!(String::from_utf8_lossy(&request).starts_with("GET /v1/tasks/fixture-task "));
            stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=rotated; Path=/\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{\"ok\":true}").await.expect("actual headers/body");
        });
        let mut client=client();let base=format!("http://{address}");
        // Explicit fresh fixture credentials; no CLI/environment discovery.
        let mut session=client.session.take().expect("fixture session");session.api_url=base.clone();
        client.reset(&base,Some(session)).expect("fixture reset");client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});
        let a=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("A");
        let b=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("B");let original_parent=client.operation_parent.clone();
        let prepared=client.prepare_owned_read(transport::OwnedReadRoute::AppTask("fixture-task")).expect("fixed readonly request");
        let cancel=CancellationToken::new();let headers=transport::send_owned_read_headers(prepared,&cancel,||b.observer().check_release()).await.expect("actual received headers");
        let body=client.apply_owned_read_headers(headers).expect("typed actual header apply + lineage");
        assert_eq!(client.session.as_ref().expect("session").cookies.get("auth_refresh_token").map(String::as_str),Some("rotated"));
        a.check(&client).expect("A accepts witnessed same-root cookie transition");b.check(&client).expect("B accepts transition");
        let completed=transport::drive_owned_read_body(body,&cancel,||b.observer().check_release()).await.expect("owned body");
        assert_eq!(client.finish_owned_read(completed).expect("matched original body"),Some(json!({"ok":true})));
        assert_eq!(client.operation_parent,original_parent);assert!(!original_parent.is_cancelled());
        client.credentials_changed();assert!(a.check(&client).is_err());assert!(b.observer().check_release().is_err());
        server.await.expect("fixture server");
    }

}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
#[cfg(all(test,not(target_arch="wasm32")))]
mod original_negative_wait_tests {
    use super::*;
    fn client()->Client {
        let api="https://example.invalid";let mut c=Client::new(api,Some(Session{api_url:api.into(),session_id:"negative-wait-fixture".into(),cookies:BTreeMap::new(),ws_token:None,
            master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).expect("explicit native fixture");
        c.user=json!({"id":"11111111-1111-4111-8111-111111111111"});c
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
    #[tokio::test]
    async fn exact_original_request_wakes_only_its_sibling(){
        let c=client();let request=CancellationToken::new();let a=OwnedOperationScope::capture(&c,request.clone()).expect("actual A");
        let b=OwnedOperationScope::capture(&c,CancellationToken::new()).expect("actual B");
        let waiting=a.cancelled();tokio::pin!(waiting);assert!(futures_util::poll!(waiting.as_mut()).is_pending());
        request.cancel();tokio::time::timeout(Duration::from_secs(1),waiting).await.expect("watchdog only");
        assert!(a.observer().check_release().is_err());b.observer().check_release().expect("actual B still live");
        let waiting=b.cancelled();tokio::pin!(waiting);assert!(futures_util::poll!(waiting.as_mut()).is_pending());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
    #[tokio::test]
    async fn actual_registry_and_parent_retirement_wake_original_negative_wait(){
        for parent in [false,true]{
            let c=client();let scope=OwnedOperationScope::capture(&c,CancellationToken::new()).expect("actual resource");
            let waiting=scope.cancelled();tokio::pin!(waiting);assert!(futures_util::poll!(waiting.as_mut()).is_pending());
            if parent{c.operation_parent.cancel();}else{c.owned_operations.invalidate();}
            tokio::time::timeout(Duration::from_secs(1),waiting).await.expect("watchdog only");assert!(scope.observer().check_release().is_err());
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
    #[tokio::test]
    async fn actual_denial_revision_wakes_both_same_parent_siblings_without_token_reset(){
        let c=client();let ordinary=c.operation_cancel.clone();
        let a=OwnedOperationScope::capture(&c,CancellationToken::new()).expect("actual A");let b=OwnedOperationScope::capture(&c,CancellationToken::new()).expect("actual B");
        let wa=a.cancelled();let wb=b.cancelled();tokio::pin!(wa);tokio::pin!(wb);
        assert!(futures_util::poll!(wa.as_mut()).is_pending());assert!(futures_util::poll!(wb.as_mut()).is_pending());
        c.task_watch_authority.deny_cached_chat(Some("actual-denied-row")).expect("actual negative ledger");
        tokio::time::timeout(Duration::from_secs(1),async{wa.await;wb.await}).await.expect("watchdog only");
        assert!(a.observer().check_release().is_err());assert!(b.observer().check_release().is_err());assert!(!ordinary.is_cancelled());assert_eq!(c.operation_cancel,ordinary);
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
    #[test]
    fn old_dispatched_cohort_cannot_retire_later_same_parent_sibling(){
        let c=client();let a=OwnedOperationScope::capture(&c,CancellationToken::new()).expect("original A");
        let cohort=a.capture_dispatched_auth_negative_cohort(&c).expect("preIO exact old cohort");
        let b=OwnedOperationScope::capture(&c,CancellationToken::new()).expect("later B");
        cohort.revoke();cohort.revoke();
        assert!(a.observer().check_release().is_err());b.check(&c).expect("later B never captured");
        assert!(!c.operation_parent.is_cancelled());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,auth.session.authoritative-enforcement
    #[test]
    fn stale_cohort_after_supported_parent_replacement_cannot_reset_new_registry_work(){
        let mut c=client();let a=OwnedOperationScope::capture(&c,CancellationToken::new()).expect("original A");
        let cohort=a.capture_dispatched_auth_negative_cohort(&c).expect("captured before IO");
        c.set_operation_cancel(CancellationToken::new());
        let b=OwnedOperationScope::capture(&c,CancellationToken::new()).expect("new epoch B");
        cohort.revoke();b.check(&c).expect("new original B survives stale auth bookkeeping");
        assert!(!c.operation_parent.is_cancelled());assert!(a.observer().check_release().is_err());
    }

}
