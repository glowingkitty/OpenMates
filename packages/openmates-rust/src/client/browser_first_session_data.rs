//! Closed original native normal-session DATA. No Master or restore operation.
use super::*;
use super::super::configured_native::OriginalNormalBrowser;
use std::rc::Rc;

#[doc(hidden)]
#[derive(Clone)]
pub struct BrowserFirstSessionDataControl {
    request:CancellationToken,abandoned:Arc<AtomicBool>,native:Rc<OriginalNormalBrowser>,
}
impl BrowserFirstSessionDataControl {
    pub fn cancel(&self){self.request.cancel();}
    pub fn ensure_current(&self)->Result<()>{
        if self.request.is_cancelled()||self.abandoned.load(Ordering::Acquire){return Err(Error::Cancelled)}
        self.native.negative()
    }
}
/// The Client remains entirely private and unadmitted. No getter, conversion,
/// metadata operation, key arrival upgrade, status grant or retry API exists.
#[doc(hidden)]
pub struct PreparedBrowserFirstSessionData {
    client:Option<Client>,session:Zeroizing<String>,signals:Option<Plain<Value>>,
    control:BrowserFirstSessionDataControl,deadline:Instant,returned:bool,
}
#[doc(hidden)]
pub struct BrowserFirstSessionData {
    _client:Client,response:NormalSessionResponse,control:BrowserFirstSessionDataControl,
    deadline:Instant,received:Instant,
}
pub(in crate::client) fn prepare_normal_data(native:Rc<OriginalNormalBrowser>,signals:Value,request:CancellationToken)->Result<PreparedBrowserFirstSessionData>{
    native.negative()?;validate_normal_signals(&signals)?;
    let session=Zeroizing::new(native.session().to_owned());
    let mut client=Client::from_validated_transport(native.base(),None,ClientOptions{app_url:Some(native.app().into()),..Default::default()})?;
    client.browser_transport=true;client.browser_normal_data_native=Some(native.clone());
    client.set_operation_cancel(request.clone());
    let control=BrowserFirstSessionDataControl{request,abandoned:Arc::new(AtomicBool::new(false)),native};control.ensure_current()?;
    let deadline=Instant::now().checked_add(transport::NORMAL_BROWSER_SESSION_TIMEOUT).ok_or(Error::Protocol)?;
    Ok(PreparedBrowserFirstSessionData{client:Some(client),session,signals:Some(Plain::new(signals)),control,deadline,returned:false})
}
impl PreparedBrowserFirstSessionData {
    pub fn control(&self)->BrowserFirstSessionDataControl{self.control.clone()}
    /// Negative-only restriction from the actual original Page deadline. Native
    /// pre/read/post share this absolute budget; none starts a fresh10s.
    pub fn restrict_remaining_budget(&mut self,remaining:Duration)->Result<()>{
        self.control.ensure_current()?;
        let candidate=Instant::now().checked_add(remaining.min(transport::NORMAL_BROWSER_SESSION_TIMEOUT)).ok_or(Error::Protocol)?;
        self.deadline=self.deadline.min(candidate);
        if self.deadline<=Instant::now(){self.control.cancel();return Err(Error::Offline)}Ok(())
    }
    pub async fn wait(mut self)->Result<BrowserFirstSessionData>{
        self.control.ensure_current()?;if self.deadline<=Instant::now(){return Err(Error::Offline)}
        self.control.native.observe_profile(&self.control.request,self.deadline).await?;
        self.control.ensure_current()?;if self.deadline<=Instant::now(){return Err(Error::Offline)}
        let io=NormalSessionIo{client:self.client.take().ok_or(Error::Conflict)?,session:Zeroizing::new(self.session.as_str().into()),signals:self.signals.take().ok_or(Error::Conflict)?,deadline:self.deadline};
        let(client,response)=io.read().await;
        // Retain actual HTTP/rotations while the actual same native owner read
        // completes. Neither server owner DATA nor a timeout supplies this proof.
        self.client=Some(client);
        self.control.native.recheck_profile(&self.control.request,self.deadline).await?;
        self.control.ensure_current()?;if self.deadline<=Instant::now(){return Err(Error::Offline)}
        self.returned=true;
        Ok(BrowserFirstSessionData{_client:self.client.take().ok_or(Error::Conflict)?,response,control:self.control.clone(),deadline:self.deadline,received:Instant::now()})
    }
}
impl Drop for PreparedBrowserFirstSessionData {
    fn drop(&mut self){if !self.returned{self.control.abandoned.store(true,Ordering::Release);self.control.cancel();}}
}
impl BrowserFirstSessionData {
    fn current(&self)->Result<()>{
        self.control.ensure_current()?;self.control.native.check()?;
        if Instant::now()>=self.deadline{return Err(Error::Offline)}
        if !Instant::now().checked_duration_since(self.received).is_some_and(|age|age<=MAX_RECEIPT_AGE){return Err(Error::Expired)}Ok(())
    }
    pub fn control(&self)->BrowserFirstSessionDataControl{self.control.clone()}
    pub fn observed_http_status(&self)->Option<u16>{self.response.status}
    /// Complete maintained normal UI response DATA only. It is not an auth
    /// receipt, private Root, metadata context, native terminal or full-hint ACK.
    pub fn response_json(&self)->Result<Zeroizing<String>>{
        self.current()?;let data=self.response.json()?;self.current()?;Ok(data)
    }
}
