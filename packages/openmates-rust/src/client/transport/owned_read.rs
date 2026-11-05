//! Fixed first-party readonly transport phases. Preparation uses the actual
//! Client; network futures own request/body IO without borrowing that Client.
//! These resources are not read, crypto, row/CAS, freshness or output grants.
use super::*;
use std::sync::Arc;
use zeroize::Zeroizing;

pub(in crate::client) enum OwnedReadRoute<'a> {
    CurrentTeam,
    AppsInventory,
    ProjectCatalogue(&'a str),
    CatalogueTeam(&'a str),
    SavedSendVersion(&'a str),
    AppTask(&'a str),
    ChatMetadata { chat_id: &'a str, include_read_details: bool },
    ChatMessages { chat_id: &'a str, options: &'a message_window::MessageWindowOptions },
    CanonicalChatMessages { chat_id: &'a str, before: Option<&'a Value> },
}
// Match the catalogue routes' canonical encodeURIComponent path policy.
// Query form encoding is separate: a path space is %20, never a literal +.
fn catalogue_segment(value: &str) -> String {
    let mut encoded = String::with_capacity(value.len());
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || b"-_.!~*'()".contains(&byte) {
            encoded.push(char::from(byte));
        } else {
            encoded.push('%');
            encoded.push(char::from(HEX[(byte >> 4) as usize]));
            encoded.push(char::from(HEX[(byte & 15) as usize]));
        }
    }
    encoded
}
struct ReadBinding {
    authority: Arc<project_task_watch::WatchAuthority>,
    parent: CancellationToken,
    generation: u64,
    credentials_owner: Zeroizing<String>,
    path: Zeroizing<String>,
    origin: Option<monitor::MonitorReadOrigin>,
    metadata_not_found: bool,
}
fn context(client:&Client)->Result<String> {
    let s=client.require_credentials()?;
    let encoded=Zeroizing::new(serde_json::to_string(&(
        s.api_url,s.session_id,s.hashed_email,s.active_team_id,
        &client.user["id"],&client.user["user_id"],&client.user["username"],
    ))?);
    Ok(sha256(&encoded))
}
impl ReadBinding {
    fn check_original_client(&self,client:&Client)->Result<()> {
        // Same canceled parent may retain a matched response's rotated cookie;
        // this admits no new request or plaintext and never replaces a child.
        // Full original operation/resource/policy checks remain the caller's.
        if self.generation!=client.generation
            || !Arc::ptr_eq(&self.authority,&client.task_watch_authority)
            || self.parent!=client.operation_parent
            || self.credentials_owner.as_str()!=context(client)? {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
}
/// Actual local cookie-header transition, minted ONLY after the validated
/// merge updates this Client. No Clone/Debug/serde or foreign receipt input.
/// Revision/binding pairs constrain same-root lineage; they grant no auth/read.
pub(in crate::client) struct ActualCookieTransition {
    before_revision:u64,after_revision:u64,
    before_binding:Zeroizing<[u8;32]>,after_binding:Zeroizing<[u8;32]>,
    authority:Arc<project_task_watch::WatchAuthority>,parent:CancellationToken,
    generation:u64,credentials_owner:Zeroizing<String>,master:credentials::MasterBinding,
}
struct BeforeCookieTransition {
    revision:u64,binding:Zeroizing<[u8;32]>,
    authority:Arc<project_task_watch::WatchAuthority>,parent:CancellationToken,
    generation:u64,credentials_owner:Zeroizing<String>,master:credentials::MasterBinding,
}
impl BeforeCookieTransition {
    fn capture(client:&Client)->Result<Self>{
        Ok(Self{revision:client.credential_revision,binding:Zeroizing::new(client.fresh_auth_binding()?),
            authority:client.task_watch_authority.clone(),parent:client.operation_parent.clone(),generation:client.generation,
            credentials_owner:Zeroizing::new(context(client)?),master:client.master_binding()?})
    }
    fn finish(self,client:&Client)->Result<ActualCookieTransition>{
        let transition=ActualCookieTransition{before_revision:self.revision,after_revision:client.credential_revision,
            before_binding:self.binding,after_binding:Zeroizing::new(client.fresh_auth_binding()?),authority:self.authority,
            parent:self.parent,generation:self.generation,credentials_owner:self.credentials_owner,master:self.master};
        transition.check_applied_state(client)?;Ok(transition)
    }
}
impl ActualCookieTransition {
    pub(in crate::client) fn revisions(&self)->(u64,u64){(self.before_revision,self.after_revision)}
    pub(in crate::client) fn binding_pair(&self)->(&[u8;32],&[u8;32]){(&self.before_binding,&self.after_binding)}
    pub(in crate::client) fn check_original_client(&self,client:&Client)->Result<()> {
        self.master.check(client)?;
        if self.generation!=client.generation||!Arc::ptr_eq(&self.authority,&client.task_watch_authority)
            ||self.parent!=client.operation_parent||self.credentials_owner.as_str()!=context(client)? {return Err(Error::Cancelled);}
        Ok(())
    }
    pub(in crate::client) fn check_applied_state(&self,client:&Client)->Result<()> {
        self.check_original_client(client)?;
        if self.after_revision!=client.credential_revision||*self.after_binding!=client.fresh_auth_binding()?
            ||self.after_revision<=self.before_revision {return Err(Error::Cancelled);}
        Ok(())
    }
}
/// Per-operation resource budget only: never auth, ownership or read authority.
/// Each observed wire byte is charged while its body OR parsed result remains
/// retained. Pending/error/drop paths release their actual owned lease.
#[derive(Clone)]
pub(in crate::client) struct OwnedReadByteBudget(Arc<ReadBytes>);
struct ReadBytes {used:std::sync::atomic::AtomicUsize,limit:usize}
pub(in crate::client) struct OwnedReadByteHold {budget:Arc<ReadBytes>,bytes:usize}
impl OwnedReadByteBudget {
    pub(in crate::client) fn new(limit:usize)->Self{Self(Arc::new(ReadBytes{used:0.into(),limit}))}
    fn hold(&self)->OwnedReadByteHold{OwnedReadByteHold{budget:self.0.clone(),bytes:0}}
}
impl OwnedReadByteHold {
    fn charge(&mut self,bytes:usize)->Result<()> {
        use std::sync::atomic::Ordering;
        self.budget.used.fetch_update(Ordering::AcqRel,Ordering::Acquire,|used|used.checked_add(bytes).filter(|n|*n<=self.budget.limit)).map_err(|_|Error::Protocol)?;
        self.bytes=self.bytes.checked_add(bytes).ok_or(Error::Protocol)?;Ok(())
    }
}
impl Drop for OwnedReadByteHold {fn drop(&mut self){self.budget.used.fetch_sub(self.bytes,std::sync::atomic::Ordering::AcqRel);}}
pub(in crate::client) struct PreparedOwnedRead {
    binding: ReadBinding,
    request: crate::platform::http::RequestBuilder,
}
pub(in crate::client) struct OwnedReadHeaders {
    binding: ReadBinding,
    response: crate::platform::http::Response,
}
pub(in crate::client) struct OwnedReadBody {
    binding: ReadBinding,
    response: crate::platform::http::Response,
    monitor_access_denied: bool,
    applied_credential_revision: u64,
    cookie_transition:Option<ActualCookieTransition>,
}
pub(in crate::client) struct CompletedOwnedRead {
    binding: ReadBinding,
    status: reqwest::StatusCode,
    bytes: Zeroizing<Vec<u8>>,
    byte_hold:Option<OwnedReadByteHold>,
    monitor_access_denied: bool,
    applied_credential_revision: u64,
    cookie_transition:Option<ActualCookieTransition>,
}
impl OwnedReadBody {
    pub(in crate::client) fn applied_credential_revision(&self)->u64 {self.applied_credential_revision}
    pub(in crate::client) fn take_cookie_transition(&mut self)->Option<ActualCookieTransition>{self.cookie_transition.take()}
}
impl CompletedOwnedRead {
    pub(in crate::client) fn take_byte_hold(&mut self)->Option<OwnedReadByteHold>{self.byte_hold.take()}
    pub(in crate::client) fn applied_credential_revision(&self)->u64 {self.applied_credential_revision}
    pub(in crate::client) fn take_cookie_transition(&mut self)->Option<ActualCookieTransition>{self.cookie_transition.take()}
}
impl Client {
    pub(in crate::client) fn prepare_owned_read(&mut self,route:OwnedReadRoute<'_>)->Result<PreparedOwnedRead> {
        self.require_canonical_read_profile()?;
        self.check_browser_credential_deadline()?;
        self.require_browser_owner_guards()?;
        if self.operation_cancel.is_cancelled(){return Err(Error::Cancelled);}
        let (method,path,body,metadata_not_found)=match route {
            OwnedReadRoute::CurrentTeam=>{
                let team=self.team()?.ok_or(Error::Forbidden)?;
                (Method::GET,format!("/v1/teams/{}",segment(team)),None,false)
            }
            OwnedReadRoute::ProjectCatalogue(id)=>(Method::GET,self.scoped(&format!("/v1/projects/{}",catalogue_segment(id)))?,None,false),
            OwnedReadRoute::CatalogueTeam(id)=>(Method::GET,format!("/v1/teams/{}",catalogue_segment(id)),None,false),
            OwnedReadRoute::SavedSendVersion(id)=>(Method::POST,self.scoped("/v1/chats/metadata/batch")?,Some(json!({"chat_ids":[id]})),false),
            OwnedReadRoute::AppsInventory=>(Method::GET,"/v1/apps/metadata?include_unavailable=true".into(),None,false),
            OwnedReadRoute::AppTask(id)=>{
                if id.is_empty()||id.len()>128||!id.bytes().all(|c|c.is_ascii_alphanumeric()||b"_-".contains(&c)){return Err(Error::Protocol);}
                (Method::GET,format!("/v1/tasks/{}",segment(id)),None,false)
            }
            OwnedReadRoute::ChatMetadata{chat_id,include_read_details}=>{
                if !uuid::Uuid::parse_str(chat_id).is_ok_and(|id|id.to_string()==chat_id){return Err(Error::Protocol);}
                let body=if include_read_details{json!({"chat_ids":[chat_id],"include_read_details":true})}else{json!({"chat_ids":[chat_id]})};
                (Method::POST,self.scoped("/v1/chats/metadata/batch")?,Some(body),true)
            }
            OwnedReadRoute::CanonicalChatMessages{chat_id,before}=>{
                // EXACT canonical API, not bounded MessageWindowOptions20.
                uuid::Uuid::parse_str(chat_id).map_err(|_|Error::Protocol)?;
                let mut url=self.url(&format!("/v1/chats/{}/messages/window",segment(chat_id)))?;
                {
                    let mut q=url.query_pairs_mut();
                    q.append_pair("direction",if before.is_some(){"before"}else{"latest"})
                        .append_pair("limit","100").append_pair("respect_compression_boundary","false");
                    if let Some(c)=before{q.append_pair("before_timestamp",&c["created_at"].to_string()).append_pair("before_message_id",required(c,"message_id")?);}
                }
                (Method::GET,self.scoped(&format!("{}?{}",self.request_route_path(&url)?,url.query().unwrap_or("")))?,None,false)
            }
            OwnedReadRoute::ChatMessages{chat_id,options}=>{
                if !uuid::Uuid::parse_str(chat_id).is_ok_and(|id|id.to_string()==chat_id){return Err(Error::Protocol);}
                options.validate(chat_id,&self.message_window_scope()?)?;
                let mut url=self.url(&format!("/v1/chats/{}/messages/window",segment(chat_id)))?;
                {
                    use message_window::MessageWindowDirection as D;
                    let direction=match options.direction{D::Latest=>"latest",D::Before=>"before",D::After=>"after",D::Around=>"around"};
                    let mut q=url.query_pairs_mut();q.append_pair("direction",direction).append_pair("limit",&options.limit.to_string()).append_pair("respect_compression_boundary",if options.respect_compression_boundary{"true"}else{"false"});
                    if let Some(c)=&options.cursor{let prefix=if options.direction==D::Before{"before"}else{"after"};q.append_pair(&format!("{prefix}_timestamp"),&c.created_at.to_string()).append_pair(&format!("{prefix}_message_id"),&c.message_id);}
                    if let Some(anchor)=&options.anchor_message_id{q.append_pair("anchor_message_id",anchor);}
                }
                (Method::GET,self.scoped(&format!("{}?{}",self.request_route_path(&url)?,url.query().unwrap_or("")))?,None,false)
            }
        };
        self.invalidate_chat_inventory_proofs();
        if method!=Method::GET {self.chat_list_freshness.invalidate();}
        let origin=self.monitor_read_origin(&method,&path,body.as_ref());
        let mut request=crate::platform::http::browser_credentials(self.http.request(method,self.url(&path)?).header("X-OpenMates-SDK",self.options.identity.header()).header("Origin",self.app_url()).header("Accept","application/json"),self.browser_cookies());
        if let Some(principal)=self.expected_request_principal()?{request=request.header("X-OpenMates-Expected-Principal",principal);}
        let cookies=Zeroizing::new(cookie_header(&self.cookies)?);
        if !cookies.is_empty(){request=request.header(COOKIE,cookies.as_str());}
        if let Some(body)=body{request=request.json(&body);}
        Ok(PreparedOwnedRead{binding:ReadBinding{authority:self.task_watch_authority.clone(),parent:self.operation_parent.clone(),generation:self.generation,credentials_owner:Zeroizing::new(context(self)?),path:Zeroizing::new(path),origin,metadata_not_found},request})
    }
    /// Apply only matched original response headers, before any body await.
    /// Full caller scope/row checks must surround the subsequent body/publication.
    pub(in crate::client) fn apply_owned_read_headers(&mut self,head:OwnedReadHeaders)->Result<OwnedReadBody> {
        head.binding.check_original_client(self)?;
        let status=head.response.status();
        let cache_namespace_unavailable=self.url(&head.binding.path).and_then(|url|self.request_route_path(&url)).is_ok_and(|path|cache_namespace_unavailable(status.as_u16(),&path));
        if status.as_u16()==403||cache_namespace_unavailable||status.is_redirection(){self.chat_list_freshness.invalidate();}
        if status.as_u16()==401{
            self.note_monitor_http_denial(401,head.binding.origin.clone())?;
            self.forget_session();return Err(Error::Expired);
        }
        let monitor_access_denied=status.as_u16()==403&&self.note_monitor_http_denial(403,head.binding.origin.clone())?;
        if status.is_redirection(){return Err(Error::Forbidden);}
        let cookie_transition=self.apply_owned_response_cookies(head.response.headers(),head.binding.generation)?;
        if status.as_u16()==403&&head.response.content_length().is_some_and(|n|n>4096){return Err(Error::Forbidden);}
        if head.response.content_length().is_some_and(|n|n>MAX_BODY as u64){return Err(Error::Protocol);}
        Ok(OwnedReadBody{binding:head.binding,response:head.response,monitor_access_denied,applied_credential_revision:self.credential_revision,cookie_transition})
    }
    pub(in crate::client) fn finish_owned_read(&mut self,completed:CompletedOwnedRead)->Result<Option<Value>> {
        completed.binding.check_original_client(self)?;
        let status=completed.status;
        if status.as_u16()==403&&super::super::browser::expected_principal_mismatch(&completed.bytes){self.forget_session();return Err(Error::Expired);}
        if completed.monitor_access_denied{return Err(Error::Forbidden);}
        if completed.binding.metadata_not_found&&status.as_u16()==404{return Ok(None);}
        if !status.is_success(){return Err(match status.as_u16(){401=>Error::Expired,403=>Error::Forbidden,409=>Error::Conflict,400|422=>Error::Invalid("The server rejected the requested operation."),404|410=>Error::Invalid("The requested item is unavailable."),429|500..=599=>Error::Offline,_=>Error::Protocol});}
        let value=super::super::plaintext::Plain::new(if completed.bytes.is_empty(){json!({})}else{serde_json::from_slice(&completed.bytes).map_err(|_|Error::Protocol)?});
        completed.binding.check_original_client(self)?;
        Ok(Some(value.into_inner()))
    }
    /// Shared ordinary/owned header application: merge response deltas into the
    /// CURRENT original cookie map, never a stale pre-dispatch cloned Session.
    pub(in crate::client) fn apply_owned_response_cookies(&mut self,headers:&reqwest::header::HeaderMap,generation:u64)->Result<Option<ActualCookieTransition>> {
        // Auth setup may have no admitted key/owner yet. Such a change has NO
        // owned-operation lineage receipt; strict observers remain restrictive.
        let mut next=super::super::plaintext::Plain::new(self.cookies.clone());
        for header in headers.get_all(SET_COOKIE){super::cookie_observation::apply(&mut next,header)?;}
        cookie_header(&next)?;
        if self.generation!=generation{return Err(Error::Cancelled);}
        let changed=self.cookies!=*next;
        // No scope/key copy or binding hash work on unchanged headers.
        let before=if changed{Some(BeforeCookieTransition::capture(self))}else{None};
        for cookie in self.cookies.values_mut(){zeroize::Zeroize::zeroize(cookie);}
        self.cookies=next.into_inner();
        if let Some(session)=self.session.as_mut(){for cookie in session.cookies.values_mut(){zeroize::Zeroize::zeroize(cookie);}session.cookies=self.cookies.clone();if changed{self.credentials_changed();}}
        else if changed {
            if let Some(browser)=self.browser_credentials.as_mut(){
                // Same already-admitted opaque browser credential resource;
                // preserve actual observed cookie rotation without a new key,
                // owner, session, policy grant or replacement Client.
                for cookie in browser.cookies.values_mut(){zeroize::Zeroize::zeroize(cookie);}
                browser.cookies=self.cookies.clone();
                self.credentials_changed();
            }
        }
        let transition=match before {
            Some(Ok(before)) if self.credential_revision>before.revision=>match before.finish(self) {
                Ok(transition)=>Some(transition),
                Err(error)=>{
                    // Keep the actual header merge durable. A failed binding
                    // observation must revoke live original observers before
                    // any caller can continue; never recapture or reset them.
                    self.refuse_unverifiable_owned_cookie_lineage()?;
                    return Err(error);
                }
            },
            Some(_)=>{
                // Capture unavailable OR no actual advanced-revision receipt.
                // Only the registry itself can attest a truly empty epoch.
                self.refuse_unverifiable_owned_cookie_lineage()?;None
            },
            None=>None, // unchanged headers have no transition to prove
        };
        if let Some(transition)=&transition {
            // Implemented by the same-root registry owner. Outside owned mode
            // this is a no-op; otherwise only this witnessed typed edge can
            // explain revision/binding drift. Ordinary guards are unchanged.
            self.record_actual_cookie_transition(transition)?;
        }
        Ok(transition)
    }
}
pub(in crate::client) async fn send_owned_read_headers<F>(prepared:PreparedOwnedRead,cancel:&CancellationToken,negative:F)->Result<OwnedReadHeaders>
where F:Fn()->Result<()> {
    negative()?;if cancel.is_cancelled(){return Err(Error::Cancelled);}
    let response=tokio::select!{biased;_=cancel.cancelled()=>return Err(Error::Cancelled),r=prepared.request.send()=>r.map_err(|_|Error::Offline)?};
    // Headers are returned immediately, not held behind a body/policy await.
    // The original Client applies actual rotation before future body checks.
    Ok(OwnedReadHeaders{binding:prepared.binding,response})
}
pub(in crate::client) async fn drive_owned_read_body<F>(body:OwnedReadBody,cancel:&CancellationToken,negative:F)->Result<CompletedOwnedRead>
where F:Fn()->Result<()> {
    drive_owned_read_body_with_budget(body,cancel,negative,None).await
}
pub(in crate::client) async fn drive_owned_read_body_with_budget<F>(mut body:OwnedReadBody,cancel:&CancellationToken,negative:F,budget:Option<&OwnedReadByteBudget>)->Result<CompletedOwnedRead>
where F:Fn()->Result<()> {
    let mut byte_hold=budget.map(OwnedReadByteBudget::hold);
    let mut bytes=Zeroizing::new(Vec::new());let status=body.response.status();
    loop {
        negative()?;
        let chunk=tokio::select!{biased;_=cancel.cancelled()=>return Err(Error::Cancelled),r=body.response.chunk()=>r.map_err(|_|Error::Offline)?};
        negative()?;
        let Some(chunk)=chunk else{break};
        if status.as_u16()==403&&bytes.len().saturating_add(chunk.len())>4096{return Err(Error::Forbidden);}
        if bytes.len().saturating_add(chunk.len())>MAX_BODY{return Err(Error::Protocol);}
        if let Some(hold)=byte_hold.as_mut(){hold.charge(chunk.len())?;}
        bytes.extend_from_slice(&chunk);
    }
    Ok(CompletedOwnedRead{binding:body.binding,status,bytes,byte_hold,monitor_access_denied:body.monitor_access_denied,applied_credential_revision:body.applied_credential_revision,cookie_transition:body.cookie_transition})
}

#[cfg(test)]
mod budget_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn concurrent_raw_and_retained_results_share_one_budget_and_drop_releases_it() {
        let budget=OwnedReadByteBudget::new(10);
        let mut retained_result=budget.hold();retained_result.charge(6).unwrap();
        let mut sibling_body=budget.hold();sibling_body.charge(4).unwrap();
        assert_eq!(sibling_body.charge(1),Err(Error::Protocol));
        // Moving a body lease to retained parsed output never resets charge.
        let parsed_result=sibling_body;let mut next_body=budget.hold();
        assert_eq!(next_body.charge(1),Err(Error::Protocol));drop(parsed_result);
        next_body.charge(4).unwrap();drop(retained_result);next_body.charge(6).unwrap();
        assert_eq!(next_body.charge(1),Err(Error::Protocol));drop(next_body);
        let mut after_drop=budget.hold();after_drop.charge(10).unwrap();
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
mod unverifiable_header_tests {
    use super::*;
    use crate::client::owned_operation::OwnedOperationScope;
    use tokio::io::{AsyncReadExt,AsyncWriteExt};
    fn fixture(base:&str)->Client {
        let mut client=Client::new(base,Some(Session{api_url:base.into(),session_id:"fixture".into(),
            cookies:BTreeMap::new(),ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),
            email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).expect("fixture");
        client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});client
    }
    // Real loopback response, not an injected registry edge or fake receipt.
    // The shared merge is also the ordinary transport header boundary. Fixed
    // owned routes correctly reject principal drift before reaching this merge.
    async fn headers<F:Fn()->Result<()>>(client:&mut Client,listener:tokio::net::TcpListener,negative:F)->(OwnedReadHeaders,tokio::task::JoinHandle<()>) {
        let server=tokio::spawn(async move{
            let(mut stream,_)=listener.accept().await.expect("original request");let mut request=Vec::new();
            loop{let mut bytes=[0u8;1024];let read=stream.read(&mut bytes).await.expect("request bytes");assert!(read>0);request.extend_from_slice(&bytes[..read]);if request.windows(4).any(|part|part==b"\r\n\r\n"){break;}assert!(request.len()<8192);}
            assert!(String::from_utf8_lossy(&request).starts_with("GET /v1/tasks/fixture-task "));
            stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nSet-Cookie: auth_refresh_token=rotated; Path=/\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{\"ok\":true}").await.expect("actual response");
        });
        let prepared=client.prepare_owned_read(OwnedReadRoute::AppTask("fixture-task")).expect("original fixed request");
        let cancel=CancellationToken::new();
        let received=send_owned_read_headers(prepared,&cancel,negative).await.expect("actual received response");
        (received,server)
    }
    async fn bound_fixture()->(Client,tokio::net::TcpListener) {
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.expect("fixture port");
        let client=fixture(&format!("http://{}",listener.local_addr().expect("fixture address")));
        (client,listener)
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn actual_changed_headers_with_unreadable_binding_revoke_both_original_observers_permanently() {
        let(mut client,listener)=bound_fixture().await;
        let a=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("A");
        let b=OwnedOperationScope::capture(&client,CancellationToken::new()).expect("B");
        let parent=client.operation_parent.clone();let generation=client.generation;
        let(received,server)=headers(&mut client,listener,||b.observer().check_release()).await;client.user=Value::Null;
        assert!(client.fresh_auth_binding().is_err(),"unreadable original owner binding");
        assert!(client.apply_owned_response_cookies(received.response.headers(),generation).is_err());
        assert_eq!(client.cookies.get("auth_refresh_token").map(String::as_str),Some("rotated"),"actual rotation must never roll back");
        assert!(a.observer().check_release().is_err());assert!(b.observer().check_release().is_err());
        client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});
        assert!(a.observer().check_release().is_err());assert!(b.observer().check_release().is_err());
        assert!(a.check(&client).is_err());assert!(b.check(&client).is_err());assert_eq!(client.operation_parent,parent);
        server.await.expect("fixture server");
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[tokio::test]
    async fn actual_changed_headers_with_unreadable_binding_and_truly_empty_registry_keep_ordinary_rotation() {
        let(mut client,listener)=bound_fixture().await;let generation=client.generation;
        let(received,server)=headers(&mut client,listener,||Ok(())).await;client.user=Value::Null;
        assert!(client.fresh_auth_binding().is_err());
        assert!(client.apply_owned_response_cookies(received.response.headers(),generation).expect("ordinary empty registry").is_none());
        assert_eq!(client.cookies.get("auth_refresh_token").map(String::as_str),Some("rotated"));
        assert_eq!(client.session.as_ref().expect("session").cookies.get("auth_refresh_token").map(String::as_str),Some("rotated"));
        assert!(client.fresh_auth_binding().is_err(),"a real cookie merge grants no missing owner/read authority");
        server.await.expect("fixture server");
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="browser_cookie_transition_tests.rs"]
mod browser_cookie_transition_tests;

#[cfg(all(test,not(target_arch="wasm32")))]
mod canonical_route_tests {
    use super::*;
    const CHAT:&str="AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA";
    fn client()->Client{
        let mut client=Client::new("https://api.example.com",Some(Session{api_url:"https://api.example.com".into(),session_id:"fixture".into(),cookies:BTreeMap::new(),ws_token:None,master_key:Zeroizing::new([7;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).unwrap();client.user=json!({"id":"11111111-1111-4111-8111-111111111111"});client
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
    #[test]
    fn actual_canonical_route_keeps_hundred_false_and_legacy_cursor_representation(){
        let mut client=client();let before=json!({"created_at":1234,"message_id":"composite:stored-row"});
        let request=client.prepare_owned_read(OwnedReadRoute::CanonicalChatMessages{chat_id:CHAT,before:Some(&before)}).unwrap().request.build().unwrap();
        let pairs=request.url().query_pairs().into_owned().collect::<BTreeMap<_,_>>();
        assert_eq!(pairs.get("direction").map(String::as_str),Some("before"));assert_eq!(pairs.get("limit").map(String::as_str),Some("100"));assert_eq!(pairs.get("respect_compression_boundary").map(String::as_str),Some("false"));
        assert_eq!(pairs.get("before_timestamp").map(String::as_str),Some("1234"));assert_eq!(pairs.get("before_message_id").map(String::as_str),Some("composite:stored-row"));
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
    #[test]
    fn canonical_latest_never_widens_the_existing_bounded_window_route(){
        let mut client=client();let request=client.prepare_owned_read(OwnedReadRoute::CanonicalChatMessages{chat_id:CHAT,before:None}).unwrap().request.build().unwrap();
        let pairs=request.url().query_pairs().into_owned().collect::<BTreeMap<_,_>>();assert_eq!(pairs.get("direction").map(String::as_str),Some("latest"));assert!(!pairs.contains_key("before_message_id"));
        let options=message_window::MessageWindowOptions{limit:100,..Default::default()};
        assert!(client.prepare_owned_read(OwnedReadRoute::ChatMessages{chat_id:"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",options:&options}).is_err());
    }
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="owned_catalogue_route_tests.rs"]
mod catalogue_route_tests;
