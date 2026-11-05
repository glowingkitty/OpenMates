//! Authored UNRUN genuine browser/profile/hint/foreground Core phase fixtures.
//! Loopback HTTP/WS are real. The encrypted cache port is a maintained protocol
//! fixture backed by a map, NOT native IndexedDB/Host persistence acceptance.
use super::*;
use crate::client::completion_recovery::{OwnedRecoveryDriver,OwnedRecoveryStep,OwnedRecoveryPendingPersistence};
use crate::client::owned_operation::{ActiveOwnedClient,OwnedOperationScope};
use crate::client::transport::{self,OwnedReadRoute};
use futures_util::{SinkExt,StreamExt};
use zeroize::Zeroizing;
use std::{cell::RefCell,rc::Rc,pin::Pin,task::{Context,Poll},sync::{Arc,Mutex,atomic::{AtomicBool,AtomicUsize,Ordering}}};
use tokio::{io::{AsyncRead,AsyncReadExt,AsyncWrite,AsyncWriteExt,ReadBuf},sync::oneshot,time::{timeout,Duration}};
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const B:&str="22222222-2222-4222-8222-222222222222";
const PRIVATE:&str="Synthetic genuinely owned B metadata recovery";
fn fixture()->Value {
    // Reuse the maintained backend-generated encrypted recovery fixture DATA;
    // never deserialize an admission/result or make a second policy fixture.
    let source=include_str!("tests.rs");let raw=source.split_once("const BACKEND_FIXTURE: &str = r#\"").unwrap().1.split_once("\"#;").unwrap().0;
    serde_json::from_str(raw).unwrap()
}
fn job()->crate::client::CompletionRecoveryJob {
    let raw=fixture()["metadata"].clone();crate::client::CompletionRecoveryJob{kind:crate::client::CompletionRecoveryKind::Metadata,job_id:raw["job_id"].as_str().unwrap().into(),chat_id:B.into(),turn_id:None,assistant_message_id:None,task_id:Some(raw["task_id"].as_str().unwrap().into()),stage:Some("initial".into()),chat_key_version:1,created_at:None}
}
fn metadata()->Value {
    // Fixed wrapper IV means the exact same synthetic current wrapper is stable
    // across actual requests. Private text remains actual encrypted server data.
    let mut wrapped=vec![3;12];wrapped.extend(crypto::encrypt_aead(&[8;32],&[7;32],&[3;12],&[]).unwrap());
    use base64::Engine;
    json!({"id":B,"user_id":OWNER,"encrypted_chat_key":base64::engine::general_purpose::STANDARD.encode(wrapped),"encrypted_title":crypto::encrypt_combined(PRIVATE,&[8;32]).unwrap(),"messages_v":9,"title_v":1,"metadata_v":1})
}
fn message()->Value {json!({"id":"physical-owned-B","chat_id":B,"created_at":10,"role":"user","status":"delivered","encrypted_content":crypto::encrypt_combined(PRIVATE,&[8;32]).unwrap()})}
struct Replay {header:Vec<u8>,offset:usize,stream:tokio::net::TcpStream}
impl AsyncRead for Replay {fn poll_read(mut self:Pin<&mut Self>,cx:&mut Context<'_>,out:&mut ReadBuf<'_>)->Poll<std::io::Result<()>>{if self.offset<self.header.len(){let n=out.remaining().min(self.header.len()-self.offset);out.put_slice(&self.header[self.offset..self.offset+n]);self.offset+=n;Poll::Ready(Ok(()))}else{Pin::new(&mut self.stream).poll_read(cx,out)}}}
impl AsyncWrite for Replay {
    fn poll_write(mut self:Pin<&mut Self>,cx:&mut Context<'_>,value:&[u8])->Poll<std::io::Result<usize>>{Pin::new(&mut self.stream).poll_write(cx,value)}
    fn poll_flush(mut self:Pin<&mut Self>,cx:&mut Context<'_>)->Poll<std::io::Result<()>>{Pin::new(&mut self.stream).poll_flush(cx)}
    fn poll_shutdown(mut self:Pin<&mut Self>,cx:&mut Context<'_>)->Poll<std::io::Result<()>>{Pin::new(&mut self.stream).poll_shutdown(cx)}
}
pub(in crate::client) struct ServerHandle {
    break_recovery_socket:Arc<tokio::sync::Notify>,
    base:String,terminal:Arc<AtomicBool>,requests:Arc<AtomicUsize>,sockets:Arc<AtomicUsize>,persists:Arc<AtomicUsize>,
    wrapper_expires:Arc<std::sync::atomic::AtomicU64>,metadata_cookie:Arc<AtomicBool>,hold_auth:Arc<AtomicBool>,auth_release:Arc<tokio::sync::Notify>,a_started:Option<oneshot::Receiver<()>>,a_release:Arc<tokio::sync::Notify>,stop:CancellationToken,task:tokio::task::JoinHandle<()>,
}
impl Drop for ServerHandle {fn drop(&mut self){self.stop.cancel();self.task.abort();}}
impl ServerHandle {
    pub(in crate::client) fn break_recovery_socket_for_test(&self){self.break_recovery_socket.notify_one();}
    pub(in crate::client) fn request_count_for_test(&self)->usize{self.requests.load(Ordering::SeqCst)}
    pub(in crate::client) fn personal_wrapper_expiry_for_test(&self,seconds:u64){self.wrapper_expires.store(seconds,Ordering::Release);}
    pub(in crate::client) fn rotate_next_metadata_headers_for_test(&self){self.metadata_cookie.store(true,Ordering::Release);}
    pub(in crate::client) fn socket_count_for_test(&self)->usize{self.sockets.load(Ordering::SeqCst)}
    pub(in crate::client) fn hold_next_auth_for_test(&self){self.hold_auth.store(true,Ordering::Release);}
    pub(in crate::client) fn release_auth_for_test(&self){self.auth_release.notify_one();}
    async fn open(terminal:bool)->Self {
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
        let terminal=Arc::new(AtomicBool::new(terminal));let requests=Arc::new(AtomicUsize::new(0));let sockets=Arc::new(AtomicUsize::new(0));let persists=Arc::new(AtomicUsize::new(0));let stop=CancellationToken::new();let(starts,a_started)=oneshot::channel();let starts=Arc::new(Mutex::new(Some(starts)));let a_release=Arc::new(tokio::sync::Notify::new());let wrapper_expires=Arc::new(std::sync::atomic::AtomicU64::new(0));let metadata_cookie=Arc::new(AtomicBool::new(false));let hold_auth=Arc::new(AtomicBool::new(false));let auth_release=Arc::new(tokio::sync::Notify::new());
        let(end,counts,connections,writes,stopped,started,released,held_auth,auth_ready,rotated_metadata,expires)=(terminal.clone(),requests.clone(),sockets.clone(),persists.clone(),stop.clone(),starts.clone(),a_release.clone(),hold_auth.clone(),auth_release.clone(),metadata_cookie.clone(),wrapper_expires.clone());
        let break_recovery_socket=Arc::new(tokio::sync::Notify::new());let broken=break_recovery_socket.clone();
        let task=tokio::spawn(async move{loop{
            let(stream,_)=tokio::select!{_=stopped.cancelled()=>break,accepted=listener.accept()=>accepted.unwrap()};
            let(end,counts,connections,writes,started,released,stopped,held_auth,auth_ready,rotated_metadata,expires)=(end.clone(),counts.clone(),connections.clone(),writes.clone(),started.clone(),released.clone(),stopped.clone(),held_auth.clone(),auth_ready.clone(),rotated_metadata.clone(),expires.clone());
            let broken=broken.clone();
            tokio::spawn(async move{
                let mut stream=stream;let mut header=Vec::new();while !header.ends_with(b"\r\n\r\n"){let mut byte=[0];stream.read_exact(&mut byte).await.unwrap();header.push(byte[0]);assert!(header.len()<=65536);}
                let text=String::from_utf8(header.clone()).unwrap();let path=text.lines().next().unwrap().split_whitespace().nth(1).unwrap().to_owned();
                if text.to_ascii_lowercase().contains("upgrade: websocket") {
                    assert!(path.starts_with("/v1/ws?"));assert!(path.contains("chat_metadata_recovery"));connections.fetch_add(1,Ordering::SeqCst);
                    let mut ws=tokio_tungstenite::accept_async(Replay{header,offset:0,stream}).await.unwrap();
                    let frame=ws.next().await.unwrap().unwrap();let frame:Value=serde_json::from_str(frame.to_text().unwrap()).unwrap();assert_eq!(frame["type"],"native_client_lifecycle");assert_eq!(frame["payload"]["is_foreground"],true);
                    ws.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":"native_client_lifecycle_ack","payload":{"is_foreground":true}}).to_string().into())).await.unwrap();
                    let frame=ws.next().await.unwrap().unwrap();let frame:Value=serde_json::from_str(frame.to_text().unwrap()).unwrap();assert_eq!(frame["type"],"metadata_job_claim");assert_eq!(frame["payload"]["job_id"],job().job_id);assert_eq!(frame["payload"]["protocol_version"],1);
                    let mut reply=fixture()["metadata"].clone();reply["state"]=json!(if end.load(Ordering::Acquire){"TERMINAL"}else{"AVAILABLE"});reply["request_id"]=frame["payload"]["request_id"].clone();
                    ws.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":"metadata_job_claimed","payload":reply}).to_string().into())).await.unwrap();
                    loop{let frame=tokio::select!{biased;_=broken.notified()=>{ws.get_mut().stream.shutdown().await.unwrap();return;},frame=ws.next()=>frame};let Some(frame)=frame else{break};match frame{Ok(tokio_tungstenite::tungstenite::Message::Text(text))=>{let frame:Value=serde_json::from_str(&text).unwrap();if frame["type"]=="metadata_job_persist"{writes.fetch_add(1,Ordering::SeqCst);panic!("no public DTO or stage alone may dispatch owned persist");}},Ok(tokio_tungstenite::tungstenite::Message::Close(_))|Err(_)=>break,_=>{}}}
                    return;
                }
                counts.fetch_add(1,Ordering::SeqCst);
                let len=text.lines().filter_map(|line|line.split_once(':')).find(|(k,_)|k.eq_ignore_ascii_case("content-length")).map(|(_,v)|v.trim().parse::<usize>().unwrap()).unwrap_or(0);assert!(len<=65536);let mut body=vec![0;len];stream.read_exact(&mut body).await.unwrap();
                let hold_body=path=="/v1/auth/session"&&held_auth.swap(false,Ordering::AcqRel);
                let metadata_rotation=path.starts_with("/v1/chats/metadata/batch")&&rotated_metadata.swap(false,Ordering::AcqRel);
                let response=if path=="/v1/auth/session" {json!({"success":true,"ws_token":if hold_body{"synthetic-owned-recovery-rotated"}else{"synthetic-owned-recovery-token"},"user":{"id":OWNER},"client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]})}
                else {
                    assert!(text.to_ascii_lowercase().contains(&format!("x-openmates-expected-principal: {OWNER}")));
                    if path=="/v1/tasks/held-a"{if let Some(tx)=started.lock().unwrap().take(){tx.send(()).unwrap();}tokio::select!{_=released.notified()=>{},_=stopped.cancelled()=>return};json!({"status":"pending"})}
                    else if path.starts_with("/v1/chats/metadata/batch"){let body:Value=serde_json::from_slice(&body).unwrap();assert_eq!(body["chat_ids"],json!([B]));let mut row=metadata();let expiry=expires.load(Ordering::Acquire);if expiry!=0{row["chat_key_wrappers"]=json!([{"hashed_chat_id":sha256(B),"key_type":"master","wrapper_version":1,"encrypted_chat_key":row["encrypted_chat_key"],"expires_at":expiry}]);}json!({"chats":[row]})}
                    else {assert!(path.starts_with(&format!("/v1/chats/{B}/messages/window")));let row=message();let cursor=json!({"created_at":10,"message_id":"physical-owned-B"});let bytes=serde_json::to_vec(&row).unwrap().len();json!({"chat_id":B,"messages":[row],"messages_v":9,"server_message_count":1,"has_more_before":false,"has_more_after":false,"start_cursor":cursor,"end_cursor":cursor,"anchor_found":true,"payload_bytes":bytes,"oversized_message":false,"oversized_message_cursor":null})}
                };
                let raw=serde_json::to_vec(&response).unwrap();let cookie=if hold_body{"Set-Cookie: auth_refresh_token=synthetic-owned-recovery-rotation; Path=/\r\n"}else if metadata_rotation{"Set-Cookie: auth_refresh_token=synthetic-canonical-header-rotation; Path=/\r\n"}else{""};stream.write_all(format!("HTTP/1.1 200 OK\r\n{cookie}Content-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",raw.len()).as_bytes()).await.unwrap();stream.flush().await.unwrap();if hold_body{tokio::select!{_=auth_ready.notified()=>{},_=stopped.cancelled()=>return};}stream.write_all(&raw).await.unwrap();
            });
        }});Self{break_recovery_socket,base,terminal,requests,sockets,persists,wrapper_expires,metadata_cookie,hold_auth,auth_release,a_started:Some(a_started),a_release,stop,task}
    }
    async fn client(&self)->Client {
        let profile=BrowserProfileKey::from_existing_profile(OWNER,Zeroizing::new([7;32]),"synthetic-hash","synthetic-salt",BrowserPersistence::MemoryOnly).unwrap();
        let c=Client::restore_browser_credentials_inner(&self.base,"http://localhost:5173",OWNER,profile).await.unwrap();assert!(c.session.is_none());assert!(c.browser_credentials.is_some());c
    }
}
struct Store {header:Value,rows:BTreeMap<String,Value>}
fn store()->Rc<RefCell<Store>> {let mut header=metadata();header["chat_id"]=json!(B);header["messages_v"]=json!(7);header["encrypted_draft_md"]=json!("protected encrypted local draft");header["unknown_local"]=json!({"retain":true});Rc::new(RefCell::new(Store{header,rows:BTreeMap::new()}))}
fn assert_projection(actual:&Value,expected:&Value){for(k,v)in expected.as_object().unwrap(){assert_eq!(actual.get(k),Some(v),"actual encrypted physical field {k}");}}
fn port(store:Rc<RefCell<Store>>)->impl FnOnce(String)->std::future::Ready<Result<String>> {move|encoded|{
    assert!(!encoded.contains(PRIVATE));let plan:Value=serde_json::from_str(&encoded).unwrap();let mut s=store.borrow_mut();let mut before=Value::Null;
    if plan["store"]=="chats" {
        if plan["kind"]=="compare_and_patch"{assert_projection(&s.header,&plan["expected"]);before=s.header.clone();for(k,v)in plan["patch"].as_object().unwrap(){s.header[k]=v.clone();}}
        return std::future::ready(Ok(json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"databaseVersion":1,"transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,"record":s.header,"before":before}).to_string()));
    }
    let ids=plan["messageIds"].as_array().unwrap();let mut rows=ids.iter().map(|id|s.rows.get(id.as_str().unwrap()).cloned().unwrap_or(Value::Null)).collect::<Vec<_>>();
    if plan["kind"].as_str().unwrap().starts_with("compare_and_patch"){assert_projection(&s.header,&plan["expectedMetadata"]);before=json!(rows);for(i,patch)in plan["patches"].as_array().unwrap().iter().enumerate(){if let Some(insert)=patch.get("insert"){assert!(rows[i].is_null());rows[i]=insert.clone();}else{for(k,v)in patch["set"].as_object().unwrap(){rows[i][k]=v.clone();}for k in patch["remove"].as_array().unwrap(){rows[i].as_object_mut().unwrap().remove(k.as_str().unwrap());}}s.rows.insert(ids[i].as_str().unwrap().into(),rows[i].clone());}}
    std::future::ready(Ok(json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"databaseVersion":1,"transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,"metadata":s.header,"rows":rows,"before":before}).to_string()))
}}
async fn handoff(server:&ServerHandle)->(Client,Arc<crate::client::OriginalHintRecoveryHandoff>) {
    let(c,_remainder,handoff)=handoff_with_remainder(server).await;(c,handoff)
}
async fn handoff_with_remainder(server:&ServerHandle)->(Client,crate::client::OwnedBrowserMetadataContinuation,Arc<crate::client::OriginalHintRecoveryHandoff>) {handoff_with_job(server,job()).await}
async fn handoff_with_job(server:&ServerHandle,job:crate::client::CompletionRecoveryJob)->(Client,crate::client::OwnedBrowserMetadataContinuation,Arc<crate::client::OriginalHintRecoveryHandoff>) {handoff_with_job_and_gate(server,job,None).await}
async fn handoff_with_job_and_gate(server:&ServerHandle,job:crate::client::CompletionRecoveryJob,gate:Option<Arc<dyn Fn()->Result<()>+Send+Sync>>)->(Client,crate::client::OwnedBrowserMetadataContinuation,Arc<crate::client::OriginalHintRecoveryHandoff>) {
    let(c,remainder)=committed_remainder_with_job_and_gate(server,job.clone(),gate).await;
    let guard=remainder.recovery_handoff(&c,&job).unwrap();guard.check_before_io(&c).unwrap();(c,remainder,guard)
}
async fn committed_remainder_with_job_and_gate(server:&ServerHandle,job:crate::client::CompletionRecoveryJob,gate:Option<Arc<dyn Fn()->Result<()>+Send+Sync>>)->(Client,crate::client::OwnedBrowserMetadataContinuation) {
    let mut c=server.client().await;if let Some(gate)=gate{c.set_private_operation_gate(Some(gate));}let monitor=Arc::new(c.retain_browser_monitor_for_test().unwrap());c.browser_owned_job_hint_for_test(&monitor,job.kind==crate::client::CompletionRecoveryKind::Metadata,&job.job_id,B).unwrap();
    let host=serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":0})).unwrap();let physical=store();
    let mut selected=c.begin_owned_browser_original_hint_read(monitor,CancellationToken::new(),OWNER,B,Default::default(),host,20,true).unwrap();
    let mut publication=loop {match selected.next().await.unwrap(){OwnedBrowserReadStep::Apply(phase)=>phase.apply(&mut c).unwrap(),OwnedBrowserReadStep::IO(io)=>io.execute(port(physical.clone())).await.unwrap().apply(&mut c).unwrap(),OwnedBrowserReadStep::Selected(value)=>break value,_=>panic!("exact selected hint result")}};
    drop(selected);publication.take(&c,true).unwrap();let continuation=publication.into_metadata_continuation(&c).unwrap();let mut metadata=continuation.begin_metadata(&c).unwrap();
    let mut publication=loop{match metadata.next().await.unwrap(){OwnedBrowserReadStep::Apply(phase)=>phase.apply(&mut c).unwrap(),OwnedBrowserReadStep::IO(io)=>io.execute(port(physical.clone())).await.unwrap().apply(&mut c).unwrap(),OwnedBrowserReadStep::Metadata(value)=>break value,_=>panic!("exact original metadata continuation")}};
    drop(metadata);publication.take(&c,true).unwrap();let remainder=publication.into_remainder(&c).unwrap();(c,remainder)
}
/// Same actual selected+metadata phase supplier, before any handoff is minted.
pub(in crate::client) async fn genuine_unissued_metadata_remainder_for_test(terminal:bool)->(Client,crate::client::OwnedBrowserMetadataContinuation,crate::client::CompletionRecoveryJob,ServerHandle){
    let server=ServerHandle::open(terminal).await;
    let(c,remainder)=committed_remainder_with_job_and_gate(&server,job(),None).await;
    (c,remainder,job(),server)
}

async fn drive(driver:&mut OwnedRecoveryDriver,c:&mut Client)->Result<OwnedRecoveryStep>{for _ in 0..300{match driver.next().await?{OwnedRecoveryStep::Apply(phase)=>{let resume=phase.apply(c)?;driver.resume(resume)?;},OwnedRecoveryStep::Io(io)=>{let resume=io.drive().await?;driver.resume(resume)?;},terminal=>return Ok(terminal)}}Err(Error::Protocol)}
pub(in crate::client) async fn genuine_terminal_with_remainder_for_test()->(Client,Arc<crate::client::OwnedBrowserMetadataContinuation>,Arc<crate::client::OriginalHintRecoveryHandoff>,crate::client::completion_recovery::OriginalForegroundRecoveryResult,ServerHandle){
    let server=ServerHandle::open(true).await;let(mut c,remainder,handoff)=handoff_with_remainder(&server).await;c.set_foreground_completion_recovery(true).unwrap();
    let mut driver=c.prepare_original_owned_recovery(handoff.clone(),None).unwrap().into_driver().unwrap();
    let OwnedRecoveryStep::Canonical(result)=timeout(Duration::from_secs(10),drive(&mut driver,&mut c)).await.unwrap().unwrap()else{panic!("actual same original metadata terminal")};
    result.check_original(&c).unwrap();drop(driver);(c,Arc::new(remainder),handoff,result,server)
}
pub(in crate::client) async fn genuine_main_handoff_for_test()->(Client,Arc<crate::client::OriginalHintRecoveryHandoff>,ServerHandle){
    let server=ServerHandle::open(false).await;let raw=fixture()["main"].clone();
    let main=crate::client::CompletionRecoveryJob{kind:crate::client::CompletionRecoveryKind::Main,job_id:raw["job_id"].as_str().unwrap().into(),chat_id:B.into(),turn_id:Some(raw["turn_id"].as_str().unwrap().into()),assistant_message_id:Some(raw["assistant_message_id"].as_str().unwrap().into()),task_id:None,stage:None,chat_key_version:1,created_at:None};
    let(c,_remainder,handoff)=handoff_with_job(&server,main).await;(c,handoff,server)
}
pub(in crate::client) async fn genuine_metadata_handoff_for_test()->(Client,Arc<crate::client::OriginalHintRecoveryHandoff>,ServerHandle){let server=ServerHandle::open(false).await;let(c,handoff)=handoff(&server).await;(c,handoff,server)}
pub(in crate::client) async fn genuine_terminal_with_gate_for_test(gate:Arc<dyn Fn()->Result<()>+Send+Sync>)->(Client,Arc<crate::client::OriginalHintRecoveryHandoff>,crate::client::completion_recovery::OriginalForegroundRecoveryResult,ServerHandle){
    let server=ServerHandle::open(true).await;let(mut c,_remainder,handoff)=handoff_with_job_and_gate(&server,job(),Some(gate)).await;c.set_foreground_completion_recovery(true).unwrap();
    let mut driver=c.prepare_original_owned_recovery(handoff.clone(),None).unwrap().into_driver().unwrap();let OwnedRecoveryStep::Canonical(result)=timeout(Duration::from_secs(10),drive(&mut driver,&mut c)).await.unwrap().unwrap()else{panic!("actual original terminal")};result.check_original(&c).unwrap();(c,handoff,result,server)
}
pub(in crate::client) async fn genuine_pending_with_remainder_for_test()->(Client,OwnedRecoveryPendingPersistence,Arc<crate::client::OwnedBrowserMetadataContinuation>,Arc<crate::client::OriginalHintRecoveryHandoff>,ServerHandle){
    let server=ServerHandle::open(false).await;let(mut c,remainder,handoff)=handoff_with_remainder(&server).await;c.set_foreground_completion_recovery(true).unwrap();
    let mut driver=c.prepare_original_owned_recovery(handoff.clone(),None).unwrap().into_driver().unwrap();let OwnedRecoveryStep::PendingPersistence(pending)=timeout(Duration::from_secs(10),drive(&mut driver,&mut c)).await.unwrap().unwrap()else{panic!("actual original AVAILABLE pending")};drop(driver);(c,pending,Arc::new(remainder),handoff,server)
}
pub(in crate::client) async fn genuine_pending_for_test()->(Client,OwnedRecoveryPendingPersistence,ServerHandle){
    let server=ServerHandle::open(false).await;let(mut c,handoff)=handoff(&server).await;c.set_foreground_completion_recovery(true).unwrap();let mut driver=c.prepare_original_owned_recovery(handoff,None).unwrap().into_driver().unwrap();
    let OwnedRecoveryStep::PendingPersistence(pending)=timeout(Duration::from_secs(10),drive(&mut driver,&mut c)).await.unwrap().unwrap()else{panic!("actual AVAILABLE claim/shared crypto must yield Ready")};drop(driver);assert_eq!(server.persists.load(Ordering::SeqCst),0);(c,pending,server)
}
pub(in crate::client) async fn genuine_canonical_boundary_for_test()->(Client,OwnedRecoveryPendingPersistence,Arc<OwnedOperationScope>,Arc<crate::client::OriginalHintRecoveryHandoff>,Arc<crate::client::completion_recovery::OriginalRecoveryRowBoundary>,ServerHandle){
    let(c,pending,server)=genuine_pending_for_test().await;
    // Same actual short Apply constructor used by production CanonicalBegin;
    // requires the genuine original staged resource and actual expected row.
    let(scope,handoff,boundary)=pending.original_boundary_for_test(&c).unwrap();
    (c,pending,scope,handoff,boundary,server)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn actual_available_metadata_yields_same_original_pending_without_accepting_public_hash_as_storage(){
    let(c,pending,server)=genuine_pending_for_test().await;let checkpoint=pending.checkpoint().unwrap();assert_eq!(checkpoint.job().job_id,job().job_id);assert_eq!(server.sockets.load(Ordering::SeqCst),1);assert_eq!(server.persists.load(Ordering::SeqCst),0);assert!(c.session.is_none());
    // There is intentionally no public DTO/status/hash resume constructor here.
    let data=crate::client::CompletionRecoveryDurableReceipt{checkpoint_sha256:checkpoint.digest().unwrap()};assert_eq!(data.checkpoint_sha256.len(),64);drop(pending);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn passive_original_hint_cannot_grant_foreground_or_start_any_recovery_io(){
    let server=ServerHandle::open(true).await;let(mut c,handoff)=handoff(&server).await;let before=server.requests.load(Ordering::SeqCst);assert!(c.completion_recovery_mode.is_none());assert!(c.prepare_original_owned_recovery(handoff,None).is_err());assert_eq!(server.requests.load(Ordering::SeqCst),before);assert_eq!(server.sockets.load(Ordering::SeqCst),0);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn real_canonical_metadata_result_has_same_handoff_actual_before_after_witness_while_a_headers_remain_held(){
    let mut server=ServerHandle::open(true).await;let(mut c,handoff)=handoff(&server).await;c.set_foreground_completion_recovery(true).unwrap();
    let original_a=Arc::new(OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap());let prepared={let mut active=ActiveOwnedClient::enter(&mut c,&original_a).unwrap();active.prepare_owned_read(OwnedReadRoute::AppTask("held-a")).unwrap()};let request=original_a.request();let observer=original_a.observer();let mut held=Box::pin(transport::send_owned_read_headers(prepared,&request,||observer.check_release()));let started=server.a_started.take().unwrap();tokio::select!{value=started=>value.unwrap(),_=held.as_mut()=>panic!("real A must remain held")};
    let mut driver=c.prepare_original_owned_recovery(handoff.clone(),None).unwrap().into_driver().unwrap();let OwnedRecoveryStep::Canonical(result)=timeout(Duration::from_secs(10),drive(&mut driver,&mut c)).await.unwrap().unwrap()else{panic!("actual WS terminal required")};drop(driver);
    result.check_original(&c).unwrap();let(receipt,witness,artifacts)=result.into_witnessed_parts().unwrap();assert!(artifacts.is_none());witness.check_original(&c,&handoff).unwrap();assert_eq!(receipt.job_id,job().job_id);assert_eq!(receipt.state,"TERMINAL");assert_eq!(witness.before(),None);assert_eq!(witness.after(),c.chats.get(B));assert_eq!(server.sockets.load(Ordering::SeqCst),1);assert_eq!(server.persists.load(Ordering::SeqCst),0);
    original_a.check(&c).unwrap();assert!(futures_util::poll!(held.as_mut()).is_pending());assert!(!c.operation_parent.is_cancelled());server.a_release.notify_one();let _headers=held.await.unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn mode_cancel_after_actual_auth_headers_keeps_body_token_durable_and_denies_socket_continuation(){
    let server=ServerHandle::open(true).await;let(mut c,handoff)=handoff(&server).await;c.set_foreground_completion_recovery(true).unwrap();server.hold_auth.store(true,Ordering::Release);
    let mut driver=c.prepare_original_owned_recovery(handoff,None).unwrap().into_driver().unwrap();let mut cancelled=false;
    let result:Result<()>=timeout(Duration::from_secs(10),async{for _ in 0..100{match driver.next().await{
        Ok(OwnedRecoveryStep::Apply(phase))=>{let resume=phase.apply(&mut c)?;driver.resume(resume)?;},
        Ok(OwnedRecoveryStep::Io(io))=>{
            if io.stage_name_for_test()=="auth_body" {assert!(!cancelled);c.set_foreground_completion_recovery(false).unwrap();cancelled=true;server.auth_release.notify_one();}
            let resume=io.drive().await?;driver.resume(resume)?;
        }
        Ok(_)=>return Err(Error::Protocol),Err(error)=>return Err(error),
    }}Err(Error::Protocol)}).await.unwrap();
    assert!(cancelled);assert!(matches!(result,Err(Error::Cancelled)));assert_eq!(server.sockets.load(Ordering::SeqCst),0);assert_eq!(server.persists.load(Ordering::SeqCst),0);
    assert_eq!(c.browser_credentials.as_ref().unwrap().ws_token.as_deref(),Some("synthetic-owned-recovery-rotated"));
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn cloned_genuine_handoff_cannot_start_second_driver_and_original_attempt_still_succeeds(){
    let server=ServerHandle::open(true).await;let(mut c,handoff)=handoff(&server).await;c.set_foreground_completion_recovery(true).unwrap();
    let first=c.prepare_original_owned_recovery(handoff.clone(),None).unwrap();let requests=server.requests.load(Ordering::SeqCst);
    assert!(c.prepare_original_owned_recovery(handoff,None).is_err());assert_eq!(server.requests.load(Ordering::SeqCst),requests);assert_eq!(server.sockets.load(Ordering::SeqCst),0);
    let mut driver=first.into_driver().unwrap();let OwnedRecoveryStep::Canonical(result)=timeout(Duration::from_secs(10),drive(&mut driver,&mut c)).await.unwrap().unwrap()else{panic!("original real attempt must remain admitted")};result.check_original(&c).unwrap();assert_eq!(server.sockets.load(Ordering::SeqCst),1);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_foreign_client_cannot_apply_original_phase_and_genuine_peer_still_completes(){
    let a=ServerHandle::open(true).await;let(mut ca,ha)=handoff(&a).await;ca.set_foreground_completion_recovery(true).unwrap();
    let b=ServerHandle::open(true).await;let(mut cb,hb)=handoff(&b).await;cb.set_foreground_completion_recovery(true).unwrap();
    let mut da=ca.prepare_original_owned_recovery(ha,None).unwrap().into_driver().unwrap();let before=a.requests.load(Ordering::SeqCst);
    let OwnedRecoveryStep::Apply(phase)=da.next().await.unwrap()else{panic!("genuine first short phase")};
    // Returned Resume carries the original refusal; it cannot rebind to peer B.
    let refused=phase.apply(&mut cb).unwrap();da.resume(refused).unwrap();assert!(da.next().await.is_err());
    assert_eq!(a.requests.load(Ordering::SeqCst),before);assert_eq!(a.sockets.load(Ordering::SeqCst),0);drop(da);
    let mut db=cb.prepare_original_owned_recovery(hb,None).unwrap().into_driver().unwrap();let OwnedRecoveryStep::Canonical(result)=timeout(Duration::from_secs(10),drive(&mut db,&mut cb)).await.unwrap().unwrap()else{panic!("genuine peer must remain admitted")};result.check_original(&cb).unwrap();assert_eq!(b.sockets.load(Ordering::SeqCst),1);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn abandoning_actual_pending_retires_its_boundary_without_cancelling_original_scope_or_parent(){
    let(c,pending,scope,handoff,boundary,server)=genuine_canonical_boundary_for_test().await;let requests=server.requests.load(Ordering::SeqCst);
    boundary.check_before_io(&c,&scope,&handoff).unwrap();drop(pending);assert!(boundary.negative().is_err());scope.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());assert_eq!(server.requests.load(Ordering::SeqCst),requests);assert_eq!(server.persists.load(Ordering::SeqCst),0);
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_prepared_socket_io_cancel_before_drive_has_zero_connect_and_preserves_parent(){
    let server=ServerHandle::open(true).await;let(mut c,handoff)=handoff(&server).await;c.set_foreground_completion_recovery(true).unwrap();
    let mut driver=c.prepare_original_owned_recovery(handoff,None).unwrap().into_driver().unwrap();let control=driver.control();let mut cancelled=false;
    let result:Result<()>=timeout(Duration::from_secs(10),async{for _ in 0..100{match driver.next().await{
        Ok(OwnedRecoveryStep::Apply(phase))=>{let resume=phase.apply(&mut c)?;driver.resume(resume)?;},
        Ok(OwnedRecoveryStep::Io(io))=>{
            if io.stage_name_for_test()=="socket_connect"{assert!(!cancelled);control.cancel();cancelled=true;}
            let resume=io.drive().await?;driver.resume(resume)?;
        }
        Ok(_)=>return Err(Error::Protocol),Err(error)=>return Err(error),
    }}Err(Error::Protocol)}).await.unwrap();
    assert!(cancelled);assert!(matches!(result,Err(Error::Cancelled)));assert_eq!(server.sockets.load(Ordering::SeqCst),0);assert_eq!(server.persists.load(Ordering::SeqCst),0);assert!(!c.operation_parent.is_cancelled());
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn owned_current_handoff_resumes_legacy_checkpoint_without_enriching_durable_bytes() {
    let server=ServerHandle::open(false).await;
    let(mut old_client,old_handoff)=handoff(&server).await;old_client.set_foreground_completion_recovery(true).unwrap();
    let mut old_driver=old_client.prepare_original_owned_recovery(old_handoff,None).unwrap().into_driver().unwrap();
    let OwnedRecoveryStep::PendingPersistence(old_pending)=timeout(Duration::from_secs(10),drive(&mut old_driver,&mut old_client)).await.unwrap().unwrap()else{panic!("actual original legacy stage")};
    let saved=old_pending.checkpoint().unwrap();assert!(saved.job().created_at.is_none());
    let exact=serde_json::to_string(&saved).unwrap();let digest=saved.digest().unwrap();drop(old_driver);drop(old_pending);
    let mut current=job();current.created_at=Some(1_800_000_001);
    let(mut client,_remainder,current_handoff)=handoff_with_job(&server,current).await;client.set_foreground_completion_recovery(true).unwrap();
    let mut driver=client.prepare_original_owned_recovery(current_handoff,Some(saved)).unwrap().into_driver().unwrap();
    let OwnedRecoveryStep::PendingPersistence(pending)=timeout(Duration::from_secs(10),drive(&mut driver,&mut client)).await.unwrap().unwrap()else{panic!("same identity with optional current metadata")};
    let resumed=pending.checkpoint().unwrap();assert_eq!(serde_json::to_string(&resumed).unwrap(),exact);assert_eq!(resumed.digest().unwrap(),digest);
    assert_eq!(server.persists.load(Ordering::SeqCst),0);
}
