//! Optional normal browser session check -> one-use SAME original restore.
//! Actual shared transport owns HTTP/header/body; response JSON is UI DATA only.
//! No imported status/response/metadata context can manufacture this receipt.
use super::*;
use zeroize::Zeroizing;
use crate::client::plaintext::Plain;
use crate::platform::time::Instant;
use std::sync::{Arc,atomic::{AtomicBool,Ordering}};
const MAX_RECEIPT_AGE:Duration=Duration::from_secs(5);

fn validate_normal_signals(signals:&Value)->Result<()>{
    if !signals.as_object().is_some_and(|object|object.len()<=64&&object.iter().all(|(k,v)|k.len()<=128&&(v.is_null()||v.as_str().is_some_and(|v|v.len()<=4096))))
        ||crate::client::monitor::cached_view::bounded_bytes(signals,16*1024).is_none(){return Err(Error::Protocol)}Ok(())
}
/// One private owner of the actual normal HTTP/header/body/status operation.
/// Both wrappers delegate here; no response/status/parser import or second auth.
struct NormalSessionIo {client:Client,session:Zeroizing<String>,signals:Plain<Value>,deadline:Instant}
struct NormalSessionResponse {value:Option<Result<Plain<Value>>>,status:Option<u16>}
impl NormalSessionIo {
    async fn read(mut self)->(Client,NormalSessionResponse){
        let body=Plain::new(json!({"session_id":self.session.as_str(),"deviceSignals":self.signals.into_inner()}));
        let mut status=None;
        // Never select-drop started IO: actual Cookie headers and bounded body
        // retain the maintained transport policy under the original deadline.
        let value=self.client.normal_browser_session_request_observed(body.into_inner(),&mut status,self.deadline).await.map(Plain::new);
        let value=if Instant::now()>=self.deadline{Err(Error::Offline)}else{value};
        (self.client,NormalSessionResponse{value:Some(value),status})
    }
}
impl NormalSessionResponse {
    fn json(&self)->Result<Zeroizing<String>>{
        let result=if self.status==Some(401){serde_json::to_string(&json!({"success":false,"message":"Session expired or revoked"}))?}
            else{let response=self.value.as_ref().ok_or(Error::Conflict)?;let value=response.as_ref().map_err(|error|*error)?;serde_json::to_string(&**value)?};
        Ok(Zeroizing::new(result))
    }
}

/// Original operation negative only. It cannot read/restore or attest HTTP drain.
#[doc(hidden)]
#[derive(Clone)]
pub struct BrowserFirstSessionControl {request:CancellationToken,abandoned:Arc<AtomicBool>,
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    native:Option<std::rc::Rc<super::configured_native::OriginalConfiguredBrowser>>,
}
impl BrowserFirstSessionControl {
    pub fn cancel(&self){self.request.cancel();}
    pub fn ensure_current(&self)->Result<()> {
        if self.request.is_cancelled()||self.abandoned.load(Ordering::Acquire){return Err(Error::Cancelled)}
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if let Some(native)=&self.native{native.negative()?;}
        Ok(())
    }
}
/// Owns the original configured pending Client and actual prepared key/profile.
/// No Client/status/credential/key accessor exists before the actual auth read.
#[doc(hidden)]
pub struct PreparedBrowserFirstSession {
    client:Option<Client>,profile:Option<BrowserProfileKey>,session:Zeroizing<String>,
    signals:Option<Plain<Value>>,control:BrowserFirstSessionControl,returned:bool,
    deadline:Instant,
}
/// Real response evidence plus original profile/key/operation, consumed once.
/// No Clone/Debug/serde, caller response import, or response replacement API.
#[doc(hidden)]
pub struct BrowserFirstSessionReceipt {
    client:Option<Client>,profile:Option<BrowserProfileKey>,session:Zeroizing<String>,
    response:NormalSessionResponse,control:BrowserFirstSessionControl,
    received:Instant,
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))] deadline:Instant,
}
impl Client {
    #[cfg(target_arch="wasm32")]
    #[doc(hidden)]
    pub fn prepare_browser_first_session(api_url:&str,app_origin:&str,session_id:&str,profile:BrowserProfileKey,
        device_signals:Value,request:CancellationToken)->Result<PreparedBrowserFirstSession>{
        use wasm_bindgen::JsCast;
        let worker=js_sys::global().dyn_into::<web_sys::DedicatedWorkerGlobalScope>().map_err(|_|Error::Forbidden)?;
        if transport::validate_app_origin(&worker.location().origin())?!=transport::validate_app_origin(app_origin)?{return Err(Error::Forbidden)}
        Self::prepare_browser_first_session_inner(api_url,app_origin,session_id,profile,device_signals,request)
    }
    fn prepare_browser_first_session_inner(api_url:&str,app_origin:&str,session_id:&str,profile:BrowserProfileKey,
        signals:Value,request:CancellationToken)->Result<PreparedBrowserFirstSession>{
        validate_normal_signals(&signals)?;
        let control=BrowserFirstSessionControl{request:request.clone(),abandoned:Arc::new(AtomicBool::new(false)),#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]native:None};control.ensure_current()?;
        let mut client=Self::prepare_browser_restore_client(api_url,app_origin,session_id,&profile)?;
        // The NORMAL UI check must observe the actual ambient Cookie owner,
        // including an account switch. The retained profile is a restriction
        // at crypto restoration, never an assertion in this earlier request.
        client.browser_authority=None;
        // There is no admitted Root/peer to reset: this is the original pending
        // constructor's actual lifetime, installed before its first HTTP.
        client.set_operation_cancel(request);
        let deadline=Instant::now().checked_add(transport::NORMAL_BROWSER_SESSION_TIMEOUT).ok_or(Error::Protocol)?;
        Ok(PreparedBrowserFirstSession{client:Some(client),profile:Some(profile),session:Zeroizing::new(session_id.into()),signals:Some(Plain::new(signals)),control,returned:false,deadline})
    }
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub(in crate::client) fn prepare_browser_first_session_configured(native:std::rc::Rc<super::configured_native::OriginalConfiguredBrowser>,profile:BrowserProfileKey,signals:Value,request:CancellationToken)->Result<PreparedBrowserFirstSession>{
        native.negative()?;profile.current()?;
        validate_normal_signals(&signals)?;
        let session=Zeroizing::new(native.session().to_owned());
        let options=ClientOptions{app_url:Some(native.app().into()),..Default::default()};
        // Allocation is shared; only the genuine captured native resource may
        // select this configuration. No placeholder/second effective endpoint.
        let mut client=Self::from_validated_transport(native.base(),None,options)?;
        client.browser_configured_native=Some(native.clone());client.browser_transport=true;
        client.set_operation_cancel(request.clone());
        let control=BrowserFirstSessionControl{request,abandoned:Arc::new(AtomicBool::new(false)),native:Some(native)};control.ensure_current()?;
        let deadline=Instant::now().checked_add(transport::NORMAL_BROWSER_SESSION_TIMEOUT).ok_or(Error::Protocol)?;
        Ok(PreparedBrowserFirstSession{client:Some(client),profile:Some(profile),session,signals:Some(Plain::new(signals)),control,returned:false,deadline})
    }
}
impl PreparedBrowserFirstSession {
    pub fn control(&self)->BrowserFirstSessionControl{self.control.clone()}
    /// Restrict this original request to the ACTUAL outer normal-auth time left
    /// after queue/lock/Worker setup. It can only shorten, never renew a grant.
    pub fn restrict_remaining_budget(&mut self,remaining:Duration)->Result<()> {
        self.control.ensure_current()?;
        let candidate=Instant::now().checked_add(remaining.min(transport::NORMAL_BROWSER_SESSION_TIMEOUT)).ok_or(Error::Protocol)?;
        self.deadline=self.deadline.min(candidate);
        if self.deadline<=Instant::now(){self.control.cancel();return Err(Error::Offline)}Ok(())
    }
    pub async fn wait(mut self)->Result<BrowserFirstSessionReceipt>{
        self.control.ensure_current()?;self.profile.as_ref().ok_or(Error::Conflict)?.current()?;
        if self.deadline<=Instant::now(){return Err(Error::Offline)}
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        {
            let original=self.client.as_ref().and_then(|client|client.browser_configured_native.clone());
            if let Some(original)=original{original.observe_profile(&self.control.request,self.deadline).await?;}
            self.control.ensure_current()?;
            if self.deadline<=Instant::now(){return Err(Error::Offline)}
        }
        let io=NormalSessionIo{client:self.client.take().ok_or(Error::Conflict)?,session:Zeroizing::new(self.session.as_str().into()),signals:self.signals.take().ok_or(Error::Conflict)?,deadline:self.deadline};
        let(client,response)=io.read().await;
        self.returned=true;
        let receipt=BrowserFirstSessionReceipt{client:Some(client),profile:self.profile.take(),session:Zeroizing::new(std::mem::take(&mut *self.session)),response,control:self.control.clone(),received:Instant::now(),#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]deadline:self.deadline};
        // Keep actual remote evidence in the opaque resource, including errors.
        // Positive/public use independently checks the original request/profile.
        Ok(receipt)
    }
}
impl Drop for PreparedBrowserFirstSession {
    fn drop(&mut self){if !self.returned{self.control.abandoned.store(true,Ordering::Release);self.control.cancel();}}
}
impl BrowserFirstSessionReceipt {
    fn current(&self)->Result<()> {
        self.control.ensure_current()?;self.profile.as_ref().ok_or(Error::Conflict)?.current()?;
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if self.control.native.is_some()&&Instant::now()>=self.deadline{return Err(Error::Offline)}
        if !Instant::now().checked_duration_since(self.received).is_some_and(|age|age<=MAX_RECEIPT_AGE){return Err(Error::Expired)}Ok(())
    }
    pub fn control(&self)->BrowserFirstSessionControl{self.control.clone()}
    /// Actual received HTTP status DATA for the existing401/403 UI policy.
    /// It cannot be imported back, restore a Client or acknowledge settlement.
    pub fn observed_http_status(&self)->Option<u16>{self.response.status}
    /// Exact maintained normal session response DATA, including device challenge
    /// and profile extras. It is never accepted back as authority. Actual401 has
    /// the same legacy definitive-expiry UI representation, not an auth receipt.
    pub fn response_json(&self)->Result<Zeroizing<String>> {
        self.current()?;
        let result=self.response.json()?;self.current()?;Ok(result)
    }
    /// Consume actual transport response and SAME prepared profile. The common
    /// old restore finisher retains exact principal/token/local-only/error policy;
    /// no second request, status DTO, new profile, enrollment or key proof occurs.
    pub fn restore(self)->Result<Client>{
        #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
        if self.client.as_ref().is_some_and(|client|client.browser_configured_native.is_some()){return Err(Error::Forbidden)}
        self.restore_inner()
    }
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    pub async fn restore_with_original_store(self,store:&crate::client::CapturedInitialSyncStore)->Result<Client>{
        self.current()?;
        let original=self.client.as_ref().and_then(|client|client.browser_configured_native.clone());
        if let Some(original)=original{store.recheck_first_session_original(&original,&self.control.request,self.deadline).await?;}
        self.current()?;self.restore_inner()
    }
    fn restore_inner(mut self)->Result<Client>{
        self.current()?;
        let client=self.client.take().ok_or(Error::Conflict)?;let profile=self.profile.take().ok_or(Error::Conflict)?;
        let response=self.response.value.take().ok_or(Error::Conflict)?.map(Plain::into_inner);
        // Only after the actual normal response was retained may the SAME
        // finisher establish this original profile's restricted restore context.
        let mut client=client;
        client.browser_authority=Some(BrowserAuthority{principal:profile.principal.clone(),persistence:profile.persistence,owner_guards:false});
        Client::finish_browser_restore_client(client,&self.session,profile,response,self.response.status)
    }
}

#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
#[path="browser_first_session_data.rs"]
mod normal_data;
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub use normal_data::{PreparedBrowserFirstSessionData,BrowserFirstSessionDataControl,BrowserFirstSessionData};
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(in crate::client) use normal_data::prepare_normal_data;

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_first_session_restore_tests.rs"]
mod tests;
