//! Fixed original native configuration, not a caller URL/authentication grant.
//! Pure route DATA below cannot construct the genuine original resource.
use super::*;

struct ConfiguredRouteData {api:String,app:String,base:url::Url}
impl ConfiguredRouteData {
    fn parse(api:&str,app:&str)->Result<Self>{
        let base=url::Url::parse(api).map_err(|_|Error::Protocol)?;
        let application=url::Url::parse(app).map_err(|_|Error::Protocol)?;
        // Match credentialed browser Fetch's supported HTTP(S) origins; retain
        // the module-owned configured API bytes/path rather than SDK rewriting.
        if !matches!(base.scheme(),"http"|"https")||base.host_str().is_none()||!base.username().is_empty()||base.password().is_some()
            ||!matches!(application.scheme(),"http"|"https")||application.host_str().is_none()
            ||application.origin().ascii_serialization()!=app{return Err(Error::Forbidden)}
        Ok(Self{api:api.into(),app:app.into(),base})
    }
    fn route(&self,path:&str)->Result<url::Url>{
        if !path.starts_with('/')||path.starts_with("//")||path.contains('\\')||path.contains('#'){return Err(Error::Protocol)}
        // Deployed getApiEndpoint is literal `${getApiUrl()}${path}`. Joining a
        // root-relative path would discard an existing self-host mount prefix.
        let url=url::Url::parse(&format!("{}{}",self.api,path)).map_err(|_|Error::Protocol)?;
        if url.origin()!=self.base.origin(){return Err(Error::Forbidden)}Ok(url)
    }
    /// Recover protocol route DATA from a same-origin effective URL produced by
    /// this configuration. Never send this unmounted path directly as an URL.
    fn logical_path(&self,url:&url::Url)->Result<String>{
        if url.origin()!=self.base.origin(){return Err(Error::Forbidden)}
        let root=self.route("/")?;let prefix=root.path().strip_suffix('/').ok_or(Error::Protocol)?;
        let path=url.path().strip_prefix(prefix).filter(|path|path.starts_with('/')).ok_or(Error::Protocol)?;
        Ok(path.into())
    }
}

#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
mod original {
 use super::*;
 use crate::platform::browser_metadata_native::{NativeMetadataContext,NativeMetadataProfileObservation};
 use crate::crypto::master::MasterCapability;
 use std::{rc::Rc,cell::RefCell};
 /// Purpose-bound original configuration/profile only. It contains no Master,
 /// authentication receipt, Client, row data or conversion into private scope.
 pub(in crate::client) struct OriginalNormalBrowser {
  context:NativeMetadataContext,routes:ConfiguredRouteData,
  profile:RefCell<Option<NativeMetadataProfileObservation>>,
 }
 impl OriginalNormalBrowser {
  pub(in crate::client) fn capture(context:&NativeMetadataContext)->Result<Rc<Self>>{
   context.check_negative()?;let(api,app,session)=context.selectors();
   uuid::Uuid::parse_str(session).map_err(|_|Error::Authentication)?;
   Ok(Rc::new(Self{context:context.clone(),routes:ConfiguredRouteData::parse(api,app)?,profile:RefCell::new(None)}))
  }
  pub(in crate::client) fn negative(&self)->Result<()>{
   self.context.check_negative()?;
   if let Some(profile)=self.profile.borrow().as_ref(){if let Err(error)=profile.check_for(&self.context){self.context.revoke_original();return Err(error)}}self.context.check_negative()
  }
  pub(in crate::client) fn check(&self)->Result<()>{self.negative()?;if self.profile.borrow().is_none(){return Err(Error::Forbidden)}Ok(())}
  pub(in crate::client) fn check_client(&self,client:&Client)->Result<()>{
   self.check()?;if client.base!=self.routes.base||client.options.app_url.as_deref()!=Some(self.routes.app.as_str()){return Err(Error::Cancelled)}self.negative()
  }
  pub(in crate::client) fn base(&self)->url::Url{self.routes.base.clone()}
  pub(in crate::client) fn app(&self)->&str{&self.routes.app}
  pub(in crate::client) fn session(&self)->&str{self.context.selectors().2}
  pub(in crate::client) fn route(&self,path:&str)->Result<url::Url>{self.check()?;self.routes.route(path)}
  pub(in crate::client) fn logical_path(&self,url:&url::Url)->Result<String>{self.check()?;self.routes.logical_path(url)}
  pub(in crate::client) fn profile_for(&self,context:&NativeMetadataContext)->Result<NativeMetadataProfileObservation>{
   if !self.context.same_original(context){return Err(Error::Forbidden)}self.check()?;
   self.profile.borrow().as_ref().cloned().ok_or(Error::Conflict)
  }
  pub(in crate::client) async fn observe_profile(&self,request:&CancellationToken,deadline:crate::platform::time::Instant)->Result<()>{
   self.negative()?;if self.profile.borrow().is_some(){return Err(Error::Conflict)}
   let actual=self.context.profile_read();tokio::pin!(actual);
   let budget=deadline.checked_duration_since(crate::platform::time::Instant::now()).unwrap_or_default();
   let observed=tokio::select!{biased;
    value=&mut actual=>value,
    _=request.cancelled()=>{self.context.revoke_original();actual.await},
    _=crate::platform::time::sleep(budget)=>{self.context.revoke_original();actual.await},
   }?;
   self.negative()?;if request.is_cancelled(){return Err(Error::Cancelled)}
   observed.check_for(&self.context)?;self.profile.replace(Some(observed));self.check()
  }
  pub(in crate::client) async fn recheck_profile(&self,request:&CancellationToken,deadline:crate::platform::time::Instant)->Result<()>{
   let observed=self.profile_for(&self.context)?;self.check()?;
   let actual=self.context.recheck_profile_owner();tokio::pin!(actual);
   let budget=deadline.checked_duration_since(crate::platform::time::Instant::now()).unwrap_or_default();
   tokio::select!{biased;
    value=&mut actual=>value,
    _=request.cancelled()=>{self.context.revoke_original();actual.await},
    _=crate::platform::time::sleep(budget)=>{self.context.revoke_original();actual.await},
   }?;
   observed.check_for(&self.context)?;self.check()?;
   if request.is_cancelled(){return Err(Error::Cancelled)}
   if crate::platform::time::Instant::now()>=deadline{return Err(Error::Offline)}Ok(())
  }
 }
 /// Nonserializable original bootstrap/config/factory/profile/key restriction.
 /// Only CapturedInitialSyncStore can supply the actual context to capture.
 pub(in crate::client) struct OriginalConfiguredBrowser {
  normal:Rc<OriginalNormalBrowser>,principal:String,master:MasterCapability,
 }
 impl Drop for OriginalConfiguredBrowser {fn drop(&mut self){self.master.invalidate();}}
 impl OriginalConfiguredBrowser {
  pub(in crate::client) fn capture(context:&NativeMetadataContext,profile:&BrowserProfileKey)->Result<Rc<Self>>{
   context.check_negative()?;profile.current()?;
   let original=Rc::new(Self{normal:OriginalNormalBrowser::capture(context)?,principal:profile.principal.clone(),master:profile.master.clone()});
   original.negative()?;
   // Actual native profile/config/connection revocation invalidates this SAME
   // original Master and every already-derived publication guard. No bool or
   // DTO supplies that negative. Dropping the last original owner also retires
   // this same opaque Master, so delayed publications cannot outlive it.
   let master=profile.master.clone();context.register_negative_revoke(Rc::new(move||master.invalidate()))?;
   Ok(original)
  }
  pub(in crate::client) fn negative(&self)->Result<()>{
   self.normal.negative()?;self.master.ensure_current()
  }
  pub(in crate::client) fn check(&self)->Result<()>{self.negative()?;self.normal.check()}
  pub(in crate::client) fn check_client(&self,client:&Client)->Result<()>{
   self.check()?;self.normal.check_client(client)?;self.negative()
  }
  pub(in crate::client) fn base(&self)->url::Url{self.normal.base()}
  pub(in crate::client) fn app(&self)->&str{self.normal.app()}
  pub(in crate::client) fn api(&self)->&str{&self.normal.routes.api}
  pub(in crate::client) fn session(&self)->&str{self.normal.session()}
  pub(in crate::client) fn route(&self,path:&str)->Result<url::Url>{self.check()?;self.normal.route(path)}
  pub(in crate::client) fn logical_path(&self,url:&url::Url)->Result<String>{self.check()?;self.normal.logical_path(url)}
  pub(in crate::client) fn profile_for(&self,context:&NativeMetadataContext)->Result<NativeMetadataProfileObservation>{
   self.check()?;self.normal.profile_for(context)
  }
  pub(in crate::client) async fn recheck_profile_for(&self,context:&NativeMetadataContext,request:&CancellationToken,deadline:crate::platform::time::Instant)->Result<()>{
   self.profile_for(context)?;self.normal.recheck_profile(request,deadline).await?;self.check()
  }
  pub(in crate::client) async fn observe_profile(&self,request:&CancellationToken,deadline:crate::platform::time::Instant)->Result<()>{
   self.negative()?;self.normal.observe_profile(request,deadline).await?;
   if self.normal.profile_for(&self.normal.context)?.owner_id()!=self.principal{return Err(Error::Forbidden)}self.check()
  }
 }
}
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
pub(in crate::client) use original::{OriginalConfiguredBrowser,OriginalNormalBrowser};

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_configured_native_tests.rs"]
mod tests;
