//! Fixed actual session validation phases. These opaque resources carry only
//! their original request/response and original lifetime; no caller DTO is proof.
use super::*;
use crate::client::{owned_operation::{OwnedOperationRegistry, OwnedOperationScope, DispatchedAuthNegativeCohort}, plaintext::Plain};
use reqwest::header::COOKIE;
use std::sync::Arc;
use zeroize::Zeroizing;

struct Epoch {
    registry: Arc<OwnedOperationRegistry>,
    authority: Arc<project_task_watch::WatchAuthority>,
    parent: CancellationToken,
    generation: u64,
}
impl Epoch {
    fn capture(client: &Client) -> Self {
        Self { registry:client.owned_operations.clone(), authority:client.task_watch_authority.clone(),
            parent:client.operation_parent.clone(), generation:client.generation }
    }
    fn check(&self, client:&Client)->Result<()> {
        if !Arc::ptr_eq(&self.registry,&client.owned_operations)
            || !Arc::ptr_eq(&self.authority,&client.task_watch_authority)
            || self.parent!=client.operation_parent || self.generation!=client.generation {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
fn owner_context(client:&Client)->Result<Zeroizing<String>> {
    encode_owner_context(client,client.require_credentials()?)
}
// Authentication already dispatched before TTL expiry is credential bookkeeping,
// not a fresh credential admission. Read only the STILL PRESENT exact metadata;
// this helper never exports/adopts a session or admits IO/private continuation.
fn stored_owner_context(client:&Client)->Result<Zeroizing<String>> {
    let scope=match (&client.session,&client.browser_credentials) {
        (Some(native),None)=>credentials::CredentialScope::from(native),
        (None,Some(browser))=>credentials::CredentialScope::from(browser),
        (None,None)=>return Err(Error::Cancelled),
        _=>return Err(Error::Protocol),
    };
    encode_owner_context(client,scope)
}
fn encode_owner_context(client:&Client,c:credentials::CredentialScope<'_>)->Result<Zeroizing<String>> {
    Ok(Zeroizing::new(sha256(&Zeroizing::new(serde_json::to_string(&(
        (c.api_url,c.session_id,c.hashed_email,c.user_email_salt,c.email_encryption_key,
            c.created_at,c.paired_session_expires_at,c.active_team_id),
        (&client.user["id"],&client.user["user_id"],&client.user["username"],client.base.as_str(),
            client.app_url(),client.options.identity.header(),client.options.interactive,
            client.browser_transport,client.browser_password_transport,
            client.browser_password_stay_logged_in,client.browser_local_read_only),
    ))?))))
}
struct OriginalClient {
    epoch:Epoch,
    owner:Zeroizing<String>,
    master:credentials::MasterBinding,
}
impl OriginalClient {
    fn capture(client:&Client)->Result<Self> {
        Ok(Self {epoch:Epoch::capture(client),owner:owner_context(client)?,master:client.master_binding()?})
    }
    fn check(&self,client:&Client)->Result<()> {
        self.epoch.check(client)?;
        // Same original key/resource identity only. The normal MasterBinding
        // check calls require_session and rejects TTL before an already-started
        // auth response can publish its real token. Keep strict expiry at prepare,
        // sealed transition/lineage validation and final original continuation.
        match (&self.master,&client.session,&client.browser_credentials) {
            (credentials::MasterBinding::Native(key),Some(native),None)
                if native.master_key.as_ref()==key.as_ref()=>{},
            (credentials::MasterBinding::Browser(master),None,Some(browser))
                if master.same_instance(&browser.master)=>{master.ensure_current()?;},
            _=>return Err(Error::Cancelled),
        }
        if self.owner.as_str()!=stored_owner_context(client)?.as_str(){return Err(Error::Cancelled);}
        Ok(())
    }
}
// Negative identity stamp for an actual post-header failure/empty state.
// It authorizes only same-target error bookkeeping, never auth/private work.
fn error_target_binding(client:&Client)->Result<Zeroizing<String>> {
    let stored=Zeroizing::new(match (&client.session,&client.browser_credentials) {
        (Some(native),None)=>serde_json::to_string(native)?,
        (None,Some(browser))=>serde_json::to_string(&(credentials::CredentialScope::from(browser),browser.master.instance_binding()))?,
        (None,None)=>"absent".to_owned(),
        _=>return Err(Error::Protocol),
    });
    Ok(Zeroizing::new(sha256(&Zeroizing::new(serde_json::to_string(&(
        stored.as_str(),&client.user["id"],&client.user["user_id"],&client.user["username"],
        client.base.as_str(),client.app_url(),client.options.identity.header(),client.options.interactive,
        client.browser_transport,client.browser_password_transport,client.browser_password_stay_logged_in,
        client.browser_local_read_only,
    ))?))))
}
// Restricting original operation adapter only; ordinary validation retains its
// existing current-child semantics. Owned validation never resets/re-admits it.
pub(super) enum ValidationOperation {
    Ordinary(CancellationToken),
    Owned(Arc<OwnedOperationScope>),
}
impl ValidationOperation {
    pub(super) fn check(&self,client:&Client)->Result<()> {
        match self {
            Self::Ordinary(token)=>client.browser_operation_current(token),
            Self::Owned(original)=>{
                client.check_browser_credential_deadline()?;
                original.check(client)
            },
        }
    }
    // Credential control-plane observation only after actual dispatch. The
    // original child/request stop cannot roll back real body/token bookkeeping.
    // Foreign/root/key/authority/TTL/denial constraints still apply; full owned
    // private continuation is checked again before any receipt can be issued.
    pub(super) fn check_dispatched(&self,client:&Client)->Result<()> {
        match self {
            Self::Ordinary(token)=>client.browser_operation_current(token),
            Self::Owned(original)=>{
                client.check_browser_credential_deadline()?;
                original.crypto.check_dispatched_credential_observation(client)
            },
        }
    }
}
// Sealed local transport history only. No caller DTO/status can claim Started.
enum ValidationDispatch { Unsent, Started }
pub(super) struct ValidationContext {
    pub(super) browser:bool,
    pub(super) was_local:bool,
    pub(super) operation:Option<ValidationOperation>,
    pub(super) observed_status:Option<u16>,
    registry:Arc<OwnedOperationRegistry>,
    original:Option<OriginalClient>,
    applied_epoch:Option<Epoch>,
    applied_error_target:Option<Zeroizing<String>>,
    original_cohort:Option<DispatchedAuthNegativeCohort>,
    owned:Option<Arc<OwnedOperationScope>>,
    monitor_origin:Option<monitor::MonitorReadOrigin>,
    dispatch:ValidationDispatch,
}
impl ValidationContext {
    pub(super) fn new(client:&Client,browser:bool,was_local:bool,operation:Option<ValidationOperation>)->Self {
        Self{browser,was_local,operation,observed_status:None,registry:client.owned_operations.clone(),
            original:None,applied_epoch:None,applied_error_target:None,original_cohort:None,owned:None,monitor_origin:None,dispatch:ValidationDispatch::Unsent}
    }
    fn check_target(&self,client:&Client)->Result<()> {
        if !Arc::ptr_eq(&self.registry,&client.owned_operations){return Err(Error::Cancelled);}
        Ok(())
    }
}
pub(in crate::client) struct PreparedOwnedSessionValidation {
    context:ValidationContext,
    request:Result<crate::platform::http::RequestBuilder>,
    #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
    saved_embed_deadline:Option<crate::platform::time::Instant>,
}
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
impl PreparedOwnedSessionValidation {
    /// Negative-only transport ceiling for the already prepared original read.
    /// Started headers/body still return through actual matched auth apply.
    pub(in crate::client) fn restrict_saved_embed_deadline(mut self,deadline:crate::platform::time::Instant)->Self{
        self.saved_embed_deadline=Some(self.saved_embed_deadline.map_or(deadline,|old|old.min(deadline)));self
    }
    pub(in crate::client) fn saved_embed_remaining(deadline:crate::platform::time::Instant,now:crate::platform::time::Instant)->Result<Duration>{
        deadline.checked_duration_since(now).filter(|d|!d.is_zero()).map(|d|d.min(Duration::from_secs(20))).ok_or(Error::Offline)
    }
}
pub(in crate::client) struct OwnedSessionValidationHeaders {
    context:ValidationContext,
    response:Result<crate::platform::http::Response>,
}
pub(in crate::client) struct OwnedSessionValidationBody {
    context:ValidationContext,
    response:Result<crate::platform::http::Response>,
    validation_before:Result<BeforeSessionValidation>,
    monitor_access_denied:bool,
}
pub(in crate::client) struct CompletedOwnedSessionValidation {
    context:ValidationContext,
    bytes:Result<Zeroizing<Vec<u8>>>,
    validation_before:Result<BeforeSessionValidation>,
    monitor_access_denied:bool,
    #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
    io:ValidationIoDisposition,
}
/// Produced only by the actual transport/body phase, never a Result projection.
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
enum ValidationIoDisposition {NeverDispatched,BodyConsumed,Unknown}
/// Nonconstructible borrowed fact about this SAME original completed phase.
/// No authentication/read/native-store/Root/global/ACK authority is exposed.
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
pub(in crate::client) struct OwnedSessionValidationIoTerminal<'a>{_original:&'a CompletedOwnedSessionValidation}
impl CompletedOwnedSessionValidation {
    // One maintained matcher for normal auth finish and narrow IO evidence.
    // It deliberately preserves actual dispatched bookkeeping after local stop.
    fn check_matched_target(&self,client:&Client)->Result<()> {
        self.context.check_target(client)?;
        self.context.applied_epoch.as_ref().ok_or(Error::Cancelled)?.check(client)?;
        if let Some(expected)=&self.context.applied_error_target {
            if expected.as_str()!=error_target_binding(client)?.as_str(){return Err(Error::Cancelled);}
        }else{
            self.context.original.as_ref().ok_or(Error::Cancelled)?.check(client)?;
        }
        Ok(())
    }
    #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
    pub(in crate::client) fn io_terminal_for(&self,client:&Client)->Option<OwnedSessionValidationIoTerminal<'_>>{
        if matches!(self.io,ValidationIoDisposition::Unknown)||self.check_matched_target(client).is_err(){return None}
        Some(OwnedSessionValidationIoTerminal{_original:self})
    }
}
/// Only a successful actual detached body installation and recorded sealed
/// transition can mint this one-use socket preparation evidence.
pub(in crate::client) struct OwnedSessionValidationReceipt {
    original:Arc<OwnedOperationScope>,
    transition:ActualSessionValidationTransition,
}
impl OwnedSessionValidationReceipt {
    pub(in crate::client) fn check_original(&self,client:&Client,original:&Arc<OwnedOperationScope>)->Result<()> {
        if !Arc::ptr_eq(&self.original,original){return Err(Error::Cancelled);}
        self.original.check(client)?;
        // No raw revision waiver: this receipt is conservatively exact here.
        self.transition.check_applied_state(client)?;
        self.original.check(client)
    }
}
impl Client {
    pub(in crate::client) fn prepare_owned_session_validation(&mut self,original:Arc<OwnedOperationScope>)->Result<PreparedOwnedSessionValidation> {
        self.prepare_session_validation(Some(original))
    }
    pub(super) fn prepare_session_validation(&mut self,original:Option<Arc<OwnedOperationScope>>)->Result<PreparedOwnedSessionValidation> {
        if let Some(original)=&original{original.check(self)?;}
        let mut context=self.begin_session_validation(original.as_ref())?;
        context.original_cohort=original.as_ref().map(|scope|scope.capture_dispatched_auth_negative_cohort(self)).transpose()?;
        context.owned=original;
        // Keep the original order: refresh retires prepared URLs/owner guards
        // before requiring credentials or constructing the fixed request.
        if self.browser_cookies(){
            self.retire_browser_prepared_transports();
            if let Some(authority)=self.browser_authority.as_mut(){authority.owner_guards=false;}
        }
        let request=(|| {
            let id=self.require_credentials()?.session_id.clone();
            self.check_browser_credential_deadline()?;
            self.invalidate_chat_inventory_proofs();
            match &context.owned {
                Some(original)=>original.observer().check_release()?,
                None=>{if self.operation_cancel.is_cancelled(){return Err(Error::Cancelled);}},
            }
            let body=json!({"session_id":id});
            context.monitor_origin=self.monitor_read_origin(&Method::POST,"/v1/auth/session",Some(&body));
            context.original=Some(OriginalClient::capture(self)?);
            let mut request=crate::platform::http::browser_credentials(
                self.http.request(Method::POST,self.url("/v1/auth/session")?)
                    .header("X-OpenMates-SDK",self.options.identity.header())
                    .header("Origin",self.app_url()).header("Accept","application/json"),self.browser_cookies());
            if let Some(expected)=self.expected_request_principal()?{request=request.header("X-OpenMates-Expected-Principal",expected);}
            let cookies=Zeroizing::new(transport::cookie_header(&self.cookies)?);
            if !cookies.is_empty(){request=request.header(COOKIE,cookies.as_str());}
            Ok(request.json(&body))
        })();
        Ok(PreparedOwnedSessionValidation{context,request,#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]saved_embed_deadline:None})
    }
    pub(in crate::client) fn apply_owned_session_validation_headers(&mut self,headers:OwnedSessionValidationHeaders)->Result<OwnedSessionValidationBody> {
        let OwnedSessionValidationHeaders{mut context,response}=headers;
        context.check_target(self)?;
        if let Some(original)=&context.original{original.check(self)?;}
        // Matched received headers are settled before local child/request denial.
        // Auth's existing 401/redirection order intentionally precedes cookies.
        let mut monitor_access_denied=false;
        let response=response.and_then(|response| {
            let status=response.status();context.observed_status=Some(status.as_u16());
            if status.as_u16()==403||status.is_redirection(){self.chat_list_freshness.invalidate();}
            if status.as_u16()==401 {
                self.note_monitor_http_denial(401,context.monitor_origin.clone())?;
                self.forget_session();return Err(Error::Expired);
            }
            monitor_access_denied=status.as_u16()==403&&self.note_monitor_http_denial(403,context.monitor_origin.clone())?;
            if status.is_redirection(){return Err(Error::Forbidden);}
            self.apply_owned_response_cookies(response.headers(),context.original.as_ref().ok_or(Error::Cancelled)?.epoch.generation)?;
            if status.as_u16()==403&&response.content_length().is_some_and(|n|n>4096){return Err(Error::Forbidden);}
            if response.content_length().is_some_and(|n|n>transport::MAX_BODY as u64){return Err(Error::Protocol);}
            Ok(response)
        });
        // This is the actual post-header boundary; never capture after body IO
        // or after installing server ws_token/user. Capture errors stay deferred.
        let validation_before=BeforeSessionValidation::capture(self);
        context.applied_epoch=Some(Epoch::capture(self));
        if context.original.is_none() || self.session.is_none()&&self.browser_credentials.is_none(){
            context.applied_error_target=Some(error_target_binding(self)?);
        }
        Ok(OwnedSessionValidationBody{context,response,validation_before,monitor_access_denied})
    }
    fn complete_session_validation_transport(&mut self,completed:&CompletedOwnedSessionValidation,bytes:Result<Zeroizing<Vec<u8>>>)->Result<Plain<Value>> {
        let bytes=bytes?;
        let status=completed.context.observed_status.ok_or(Error::Protocol)?;
        if status==403&&browser::expected_principal_mismatch(&bytes){self.forget_session();return Err(Error::Expired);}
        if completed.monitor_access_denied{return Err(Error::Forbidden);}
        if !(200..300).contains(&status){return Err(match status {
            401=>Error::Expired,403=>Error::Forbidden,409=>Error::Conflict,
            400|422=>Error::Invalid("The server rejected the requested operation."),
            404|410=>Error::Invalid("The requested item is unavailable."),
            429|500..=599=>Error::Offline,_=>Error::Protocol,
        });}
        Ok(Plain::new(if bytes.is_empty(){json!({})}else{serde_json::from_slice(&bytes).map_err(|_|Error::Protocol)?}))
    }
    pub(in crate::client) fn finish_owned_session_validation(&mut self,completed:CompletedOwnedSessionValidation)->Result<OwnedSessionValidationReceipt> {
        self.finish_session_validation(completed)?.ok_or(Error::Cancelled)
    }
    pub(super) fn finish_session_validation(&mut self,mut completed:CompletedOwnedSessionValidation)->Result<Option<OwnedSessionValidationReceipt>> {
        // A stale A response must never run current B denial/wrapper cleanup.
        // Revoke only the pre-IO captured OLD negative resources, never current
        // registry entries, parent, credentials or a later B operation.
        let matched=completed.check_matched_target(self);
        if let Err(error)=matched {
            if let Some(cohort)=&completed.context.original_cohort{cohort.revoke();}
            return Err(error);
        }
        // No auth attempt started: this owned negative is not an authenticated
        // root denial and must not run browser cleanup against healthy siblings.
        // Preparation's conservative URL/guard retirement is NOT rearmed here.
        if completed.context.owned.is_some()
            && matches!(completed.context.dispatch,ValidationDispatch::Unsent)
            && matches!(&completed.bytes,Err(Error::Cancelled)) {
            return Err(Error::Cancelled);
        }
        let bytes=std::mem::replace(&mut completed.bytes,Err(Error::Cancelled));
        let mut received=self.complete_session_validation_transport(&completed,bytes);
        let mut before=std::mem::replace(&mut completed.validation_before,Err(Error::Cancelled));
        // Advance only this actual captured token across an exact witnessed
        // original lineage. No scope capture, caller epoch or raw status enters.
        if received.is_ok() {
            let advancement=if let (Some(original),Ok(before_value))=(&completed.context.owned,&mut before){
                match before_value.endpoint_matches(self) {
                    Ok(true)=>Ok(()),
                    Ok(false)=>before_value.advance_over_original_owned_lineage(self,original),
                    Err(error)=>Err(error),
                }
            }else{Ok(())};
            // Failed lineage observation must not roll back/discard actual
            // credential-control-plane output. Existing auth installs it, then
            // refuses/revokes unverifiable original observers without a receipt.
            if let Err(error)=advancement{before=Err(error);}
        }
        let mut transition=None;
        let result=self.apply_session_validation_body(received,&mut completed.context.observed_status,
            completed.context.operation.as_ref(),before,&mut transition);
        self.finish_session_validation_wrapper(&completed.context,result)?;
        match completed.context.owned {
            Some(original)=>{
                original.check(self)?;
                let transition=transition.ok_or(Error::Cancelled)?;
                transition.check_applied_state(self)?;
                Ok(Some(OwnedSessionValidationReceipt{original,transition}))
            },None=>Ok(None),
        }
    }
}
pub(in crate::client) async fn send_owned_session_validation_headers(prepared:PreparedOwnedSessionValidation)->OwnedSessionValidationHeaders {
    send_owned_session_validation_headers_with_negative(prepared,||Ok(())).await
}
pub(in crate::client) async fn send_owned_session_validation_headers_with_negative<F>(mut prepared:PreparedOwnedSessionValidation,negative:F)->OwnedSessionValidationHeaders
where F:Fn()->Result<()> {
    // Original callbacks can revoke narrower recovery mode/request resources.
    // Its negative-only hook runs LAST, before any request is dispatched.
    let before_dispatch=prepared.context.owned.as_ref().map_or(Ok(()),|original|original.observer().check_release())
        .and_then(|_|negative())
        .and_then(|_|prepared.context.owned.as_ref().map_or(Ok(()),|original|original.observer().check_original_negative()));
    // Match ordinary auth once dispatched: no cancellation race may discard
    // actual matched headers or its credential-control-plane body bookkeeping.
    let response=match before_dispatch {
        Err(error)=>Err(error),
        Ok(())=>match prepared.request {
            Ok(request)=>{
                #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
                let request=match prepared.saved_embed_deadline{None=>Ok(request),Some(deadline)=>PreparedOwnedSessionValidation::saved_embed_remaining(deadline,crate::platform::time::Instant::now()).map(|remaining|request.timeout(remaining))};
                #[cfg(not(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test))))]
                let request=Ok(request);
                match request{Err(error)=>Err(error),Ok(request)=>{prepared.context.dispatch=ValidationDispatch::Started;request.send().await.map_err(|_|Error::Offline)}}
            },
            Err(error)=>Err(error),
        },
    };
    OwnedSessionValidationHeaders{context:prepared.context,response}
}
pub(in crate::client) async fn drive_owned_session_validation_body(body:OwnedSessionValidationBody)->CompletedOwnedSessionValidation {
    #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
    let mut body_consumed=false;
    let bytes=async {
        let mut response=body.response?;
        let status=response.status();let mut bytes=Zeroizing::new(Vec::new());
        while let Some(chunk)=response.chunk().await.map_err(|_|Error::Offline)? {
            if status.as_u16()==403&&bytes.len()+chunk.len()>4096{return Err(Error::Forbidden);}
            if bytes.len()+chunk.len()>transport::MAX_BODY{return Err(Error::Protocol);}
            bytes.extend_from_slice(&chunk);
        }
        // Only actual chunk EOF, never successful outer/inner Result or status.
        #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
        {body_consumed=true;}
        Ok(bytes)
    }.await;
    #[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
    let io=if matches!(body.context.dispatch,ValidationDispatch::Unsent){ValidationIoDisposition::NeverDispatched}else if body_consumed{ValidationIoDisposition::BodyConsumed}else{ValidationIoDisposition::Unknown};
    CompletedOwnedSessionValidation{context:body.context,bytes,validation_before:body.validation_before,monitor_access_denied:body.monitor_access_denied,#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]io}
}
