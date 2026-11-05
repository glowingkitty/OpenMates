//! Native SDK-only opaque metadata. Memory is the actual store, never proof of
//! a browser Worker, native profile, durable commit, Master or full-hint ACK.
//! Existing Client/Session and browser capabilities are deliberately unrelated.
use super::*;
use super::plaintext::{Plain, Wipe};
use std::sync::{Arc, Mutex, atomic::{AtomicBool, AtomicU64, Ordering}};
use zeroize::Zeroizing;

/// Explicit transport inputs, not authenticated identity or storage authority.
/// The SDK adapter sets its own Rust/npm/PyPI identity; CLI is excluded.
pub struct MetadataEndpointOptions {
    pub api_url: String,
    pub app_url: String,
    pub identity: ClientIdentity,
}
/// Existing cookie-session transport only. No user DTO, key or API-key mode.
/// These inputs do not issue a context until the real auth response succeeds.
pub struct MetadataCookieCredentials {
    pub session_id: Zeroizing<String>,
    pub cookies: BTreeMap<String, String>,
}
impl Drop for MetadataCookieCredentials{fn drop(&mut self){self.cookies.wipe();}}
struct CredentialSource {
    session_id: Zeroizing<String>,
    cookies: Plain<BTreeMap<String,String>>,
}
pub(super) struct MetadataSource {
    pub(super) base: url::Url,
    pub(super) app: String,
    pub(super) identity: ClientIdentity,
    pub(super) http: crate::platform::http::Client,
    credentials: Mutex<CredentialSource>,
    // A received server Max-Age is negative expiry evidence only. Absence is
    // not an extension/grant; every new startup still reauthenticates remotely.
    deadline_ms:AtomicU64,
}
impl MetadataSource {
    pub(super) fn check_expiry(&self)->Result<()>{let deadline=self.deadline_ms.load(Ordering::SeqCst);if deadline!=0&&now_ms()>=deadline{Err(Error::Expired)}else{Ok(())}}
    pub(super) fn request_credentials(&self)->Result<MetadataCookieCredentials>{
        let source=self.credentials.lock().map_err(|_|Error::Cancelled)?;
        Ok(MetadataCookieCredentials{session_id:source.session_id.clone(),cookies:(*source.cookies).clone()})
    }
    /// Only the actual original HTTP driver's received headers call this.
    /// Merge into the CURRENT holder before body, denial or cancellation checks.
    pub(super) fn apply_headers(&self,headers:&reqwest::header::HeaderMap)->Result<()> {
        let mut source=self.credentials.lock().map_err(|_|Error::Cancelled)?;
        let mut refusal=None;
        for header in headers.get_all(reqwest::header::SET_COOKIE){
            let mut next=Plain::new((*source.cookies).clone());
            let observed=match super::transport::cookie_observation::apply(&mut next,header){
                Ok(observed)=>observed,
                Err(error)=>{if refusal.is_none(){refusal=Some(error)}continue},
            };
            // Publish each admissible original observation independently.
            // A later bad header cannot roll back an actual valid rotation;
            // an invalid owned cookie is never committed or sent onward.
            if let Err(error)=super::transport::cookie_header(&next){if refusal.is_none(){refusal=Some(error)}continue}
            source.cookies=next;
            if let Some(observed)=observed{
                if observed.name=="auth_refresh_token"{
                    for part in observed.raw.split(';').skip(1){if let Some((attribute,age))=part.trim().split_once('='){
                        if attribute.eq_ignore_ascii_case("max-age"){
                            // Invalid expiry is a negative retirement, while
                            // keeping the actual syntactically valid rotation.
                            let seconds=age.parse::<i64>().unwrap_or(0);
                            let deadline=if seconds<=0{1}else{now_ms().saturating_add((seconds as u64).saturating_mul(1000))};
                            self.deadline_ms.store(deadline,Ordering::SeqCst);
                        }
                    }}
                    if observed.value.is_empty(){self.deadline_ms.store(1,Ordering::SeqCst);}
                }
            }
        }
        // The batch is already received. A bad earlier observation cannot hide
        // a later admissible rotation; refusal remains negative after scanning.
        match refusal{Some(error)=>Err(error),None=>Ok(())}
    }
}
/// Pending credentials. This has no authenticated principal or memory store.
/// One actual attempt only; a failed/abandoned send is never rearmed as success.
pub struct PreparedMetadataAuthentication {source:Arc<MetadataSource>,used:AtomicBool,driver:Arc<tokio::sync::Mutex<()>>}
impl PreparedMetadataAuthentication {
    pub fn from_explicit_cookie(options:MetadataEndpointOptions,mut credentials:MetadataCookieCredentials)->Result<Self>{
        if matches!(options.identity,ClientIdentity::Cli){return Err(Error::Forbidden)}
        let base=super::transport::validate_base(&options.api_url)?;
        let app=super::transport::validate_app_origin(&options.app_url)?.to_string().trim_end_matches('/').to_owned();
        if credentials.session_id.is_empty() || credentials.cookies.is_empty(){return Err(Error::Authentication)}
        super::transport::cookie_header(&credentials.cookies)?;
        let source=Arc::new(MetadataSource{base,app,identity:options.identity,http:crate::platform::http::client()?,
            credentials:Mutex::new(CredentialSource{session_id:std::mem::take(&mut credentials.session_id),cookies:Plain::new(std::mem::take(&mut credentials.cookies))}),deadline_ms:AtomicU64::new(0)});
        Ok(Self{source,used:AtomicBool::new(false),driver:Arc::new(tokio::sync::Mutex::new(()))})
    }
    /// Actual headers survive negative completion in this original holder.
    pub fn credential_snapshot(&self)->Result<MetadataCookieCredentials>{self.source.request_credentials()}
    /// Negative-only barrier for this registered original authentication IO.
    /// Caller cancels its original request first. No scope, global/native store
    /// settlement, future operation readiness or protocol ACK is returned.
    pub async fn wait_for_authentication_io(&self)->Result<()>{
        let _original=tokio::time::timeout(Duration::from_secs(30),self.driver.lock()).await.map_err(|_|Error::Offline)?;Ok(())
    }
    pub async fn authenticate_existing(&self,cancel:CancellationToken)->Result<EphemeralMetadataClient>{
        if self.used.swap(true,Ordering::SeqCst){return Err(Error::Conflict)}
        if cancel.is_cancelled(){return Err(Error::Cancelled)}
        // Reserve before spawning: a drain cannot overtake dispatched work.
        let original_driver=self.driver.clone().try_lock_owned().map_err(|_|Error::Conflict)?;
        let source=self.source.clone();
        // Dropping a foreign future cannot discard a received rotation. The
        // bounded Rust task retains its original holder through HTTP completion.
        tokio::spawn(async move {
            let _original_driver=original_driver;
            let principal=super::transport::ephemeral_metadata::authenticate(&source,None,&cancel).await?;
            if cancel.is_cancelled(){return Err(Error::Cancelled)}
            Ok(EphemeralMetadataClient{inner:Arc::new(MetadataRuntime{
                source,principal:principal.principal,lifetime:cancel.child_token(),
                generation:AtomicU64::new(0),busy:AtomicBool::new(false),driver:Arc::new(tokio::sync::Mutex::new(())),
                // Allocation occurs ONLY after actual complete HTTP identity.
                store:Mutex::new(MemoryMetadataStore::default()),
            })})
        }).await.map_err(|_|Error::Cancelled)?
    }
}
#[derive(Default)]
struct MemoryMetadataStore {rows:PlainRows,order:Vec<String>}
#[derive(Default)]
struct PlainRows(BTreeMap<String,Value>);
impl Drop for PlainRows{fn drop(&mut self){self.0.wipe();}}
impl Drop for MemoryMetadataStore{fn drop(&mut self){self.order.wipe();}}
struct MetadataRuntime {
    source:Arc<MetadataSource>,principal:Zeroizing<String>,lifetime:CancellationToken,
    generation:AtomicU64,busy:AtomicBool,driver:Arc<tokio::sync::Mutex<()>>,store:Mutex<MemoryMetadataStore>,
}
impl MetadataRuntime {
    fn check(&self,generation:u64,cancel:&CancellationToken)->Result<()> {
        if let Err(error)=self.source.check_expiry(){self.lifetime.cancel();return Err(error)}
        if self.lifetime.is_cancelled()||cancel.is_cancelled()||self.generation.load(Ordering::SeqCst)!=generation{return Err(Error::Cancelled)}
        Ok(())
    }
    fn retire(&self){self.lifetime.cancel();if let Ok(mut store)=self.store.lock(){*store=MemoryMetadataStore::default();}}
}
/// Opaque authenticated principal + original credentials + actual Core memory
/// store identity/lifetime. No conversion to Client/Session/NativeMetadataContext.
pub struct EphemeralMetadataClient {inner:Arc<MetadataRuntime>}
impl Drop for EphemeralMetadataClient{fn drop(&mut self){self.inner.retire();}}
impl EphemeralMetadataClient {
    pub fn credential_snapshot(&self)->Result<MetadataCookieCredentials>{self.inner.source.request_credentials()}
    pub fn prepare_initial_sync(&self,cancel:CancellationToken)->Result<PreparedEphemeralMetadataStartup>{
        if self.inner.lifetime.is_cancelled()||cancel.is_cancelled(){return Err(Error::Cancelled)}
        if self.inner.busy.swap(true,Ordering::SeqCst){return Err(Error::Conflict)}
        let lease=StartupLease{runtime:self.inner.clone()};
        let generation=self.inner.generation.fetch_add(1,Ordering::SeqCst)+1;
        if generation>9_007_199_254_740_991{self.inner.retire();return Err(Error::Conflict)}
        *self.inner.store.lock().map_err(|_|Error::Cancelled)?=MemoryMetadataStore::default();
        self.inner.check(generation,&cancel)?;
        Ok(PreparedEphemeralMetadataStartup{lease:Some(lease),generation,cancel})
    }
    /// Negative retirement is immediate. Await the actual original driver lock,
    /// bounded by HTTP/socket deadlines; a timeout does not claim settlement.
    pub async fn close(&self)->Result<()> {
        self.inner.retire();
        let _drained=tokio::time::timeout(Duration::from_secs(35),self.inner.driver.lock()).await.map_err(|_|Error::Offline)?;
        Ok(())
    }
}
struct StartupLease{runtime:Arc<MetadataRuntime>}
impl Drop for StartupLease{fn drop(&mut self){self.runtime.busy.store(false,Ordering::SeqCst);}}
pub struct PreparedEphemeralMetadataStartup {lease:Option<StartupLease>,generation:u64,cancel:CancellationToken}
impl PreparedEphemeralMetadataStartup {
    pub fn cancel(&self){self.cancel.cancel();}
    pub fn cancellation(&self)->CancellationToken{self.cancel.clone()}
    pub async fn run(mut self)->Result<EphemeralMetadataSnapshot>{
        let lease=self.lease.take().ok_or(Error::Conflict)?;let generation=self.generation;let cancel=self.cancel.clone();
        tokio::spawn(async move {
            let runtime=lease.runtime.clone();
            let _driver=runtime.driver.clone().lock_owned().await;
            let result=async {
                runtime.check(generation,&cancel)?;
                // Revalidate the SAME original source and server principal.
                let auth=super::transport::ephemeral_metadata::authenticate(&runtime.source,Some(&runtime.principal),&cancel).await?;
                runtime.check(generation,&cancel)?;
                let mut data=super::transport::ephemeral_metadata::initial_sync(&runtime.source,&auth.token,generation,&runtime.lifetime,&cancel).await?;
                runtime.check(generation,&cancel)?;
                data.retained_navigation_bytes()?;
                {
                    let mut store=runtime.store.lock().map_err(|_|Error::Cancelled)?;
                    runtime.check(generation,&cancel)?;
                    store.rows=PlainRows(std::mem::take(&mut data.chats));
                    store.order=std::mem::take(&mut data.chat_arrival_order);
                }
                runtime.check(generation,&cancel)?;
                // Remaining windows/wrappers/embeds/keys are wiped by Plain.
                Ok(EphemeralMetadataSnapshot{runtime:runtime.clone(),generation,cancel})
            }.await;
            if result.is_err(){runtime.retire();}
            drop(lease);result
        }).await.map_err(|_|Error::Cancelled)?
    }
}
/// One actual original-store observation, not account-total/readiness/commit.
pub struct EphemeralMetadataSnapshot {runtime:Arc<MetadataRuntime>,generation:u64,cancel:CancellationToken}
impl EphemeralMetadataSnapshot {
    pub fn cancel(&self){self.cancel.cancel();self.runtime.retire();}
    pub fn received_metadata_count(&self,client:&EphemeralMetadataClient)->Result<usize>{
        if !Arc::ptr_eq(&self.runtime,&client.inner){return Err(Error::Forbidden)}
        self.runtime.check(self.generation,&self.cancel)?;
        let count=self.runtime.store.lock().map_err(|_|Error::Cancelled)?.rows.0.len();
        self.runtime.check(self.generation,&self.cancel)?;Ok(count)
    }
}

#[cfg(test)]mod header_retention_tests{
 use super::*;
 fn pending()->PreparedMetadataAuthentication{PreparedMetadataAuthentication::from_explicit_cookie(MetadataEndpointOptions{api_url:"http://127.0.0.1:1".into(),app_url:"https://app.example.invalid".into(),identity:ClientIdentity::Rust},MetadataCookieCredentials{session_id:Zeroizing::new("synthetic".into()),cookies:BTreeMap::from([("auth_refresh_token".into(),"old".into())])}).unwrap()}
 // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
 #[test]fn observed_auth_rotation_survives_later_invalid_preference_without_committing_it(){
  let p=pending();let mut h=reqwest::header::HeaderMap::new();h.append(reqwest::header::SET_COOKIE,"auth_refresh_token=rotated; Max-Age=3600".parse().unwrap());h.append(reqwest::header::SET_COOKIE,"preference.v1=1".parse().unwrap());
  assert!(matches!(p.source.apply_headers(&h),Err(Error::Protocol)));let c=p.credential_snapshot().unwrap();assert_eq!(c.cookies,BTreeMap::from([("auth_refresh_token".into(),"rotated".into())]));
 }
 // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
 #[test]fn observed_auth_rotation_survives_later_undecodable_header(){
  let p=pending();let mut h=reqwest::header::HeaderMap::new();h.append(reqwest::header::SET_COOKIE,"auth_refresh_token=rotated".parse().unwrap());h.append(reqwest::header::SET_COOKIE,reqwest::header::HeaderValue::from_bytes(b"preference=\xff").unwrap());
  assert!(matches!(p.source.apply_headers(&h),Err(Error::Protocol)));assert_eq!(p.credential_snapshot().unwrap().cookies["auth_refresh_token"],"rotated");
 }
 // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
 #[test]fn invalid_preference_before_valid_auth_rotation_still_retains_only_admissible_original_cookie(){
  let p=pending();let mut h=reqwest::header::HeaderMap::new();h.append(reqwest::header::SET_COOKIE,"preference.v1=1".parse().unwrap());h.append(reqwest::header::SET_COOKIE,"auth_refresh_token=rotated; Max-Age=3600".parse().unwrap());
  assert!(matches!(p.source.apply_headers(&h),Err(Error::Protocol)));assert_eq!(p.credential_snapshot().unwrap().cookies,BTreeMap::from([("auth_refresh_token".into(),"rotated".into())]));
 }
 // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
 #[test]fn undecodable_header_before_valid_auth_rotation_does_not_hide_received_rotation(){
  let p=pending();let mut h=reqwest::header::HeaderMap::new();h.append(reqwest::header::SET_COOKIE,reqwest::header::HeaderValue::from_bytes(b"preference=\xff").unwrap());h.append(reqwest::header::SET_COOKIE,"auth_refresh_token=rotated".parse().unwrap());
  assert!(matches!(p.source.apply_headers(&h),Err(Error::Protocol)));assert_eq!(p.credential_snapshot().unwrap().cookies,BTreeMap::from([("auth_refresh_token".into(),"rotated".into())]));
 }
}
