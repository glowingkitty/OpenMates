//! Authored UNRUN genuine Core + in-process HTTP/WebSocket cases. No native DB,
//! browser Fetch/IDB, compiler, product/runtime or performance acceptance.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation,sync.client.shared-rust-policy
use super::*;
use futures_util::{SinkExt,StreamExt};
use tokio::io::{AsyncReadExt,AsyncWriteExt};
// Drive the same original future while the fixture observes its held IO.
// A single poll cannot make later socket/HTTP progress while awaiting a notice.
async fn drive_until_held_notice<F: std::future::Future + ?Sized>(
    original: std::pin::Pin<&mut F>,
    notice: &tokio::sync::Notify,
) {
    tokio::time::timeout(Duration::from_secs(5), async {
        tokio::select! {
            _ = notice.notified() => {},
            _ = original => panic!("original held operation completed before fixture release"),
        }
    })
    .await
    .expect("fixture notice requires progress of the original bounded operation");
}
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const CHAT:&str="22222222-2222-4222-8222-222222222222";
const EMBED:&str="33333333-3333-4333-8333-333333333333";
const PARENT:&str="44444444-4444-4444-8444-444444444444";
const TEXT:&str="Exact synthetic code [EMAIL_1]";
fn payload(id:&str,mode:&str)->Value{
 let mut row=json!({"embed_id":id,"user_id":OWNER,"chat_id":CHAT,"message_id":PARENT,"already_encrypted":true,"encryption_mode":"client","status":"finished","version_number":1,"parent_embed_id":null,"embed_ids":[],"createdAt":10,"updatedAt":11,"embed_keys_has_more_after":false,
 "type":crypto::encrypt_combined("code",&[7;32]).unwrap(),"content":crypto::encrypt_combined(&json!({"text":TEXT,"language":"rust"}).to_string(),&[7;32]).unwrap(),
 "embed_keys":[{"hashed_embed_id":sha256(id),"hashed_user_id":sha256(OWNER),"key_type":"master","hashed_chat_id":null,"encrypted_embed_key":crypto::server_fields::encrypt_bytes(&[7;32],&[9;32],&[]).unwrap()}]});
 match mode {
  "wrong-id"=>row["embed_id"]=json!(PARENT),"owner"=>row["user_id"]=json!(PARENT),"incomplete"=>row["embed_keys_has_more_after"]=json!(true),"expired"=>row["embed_keys"][0]["expires_at"]=json!(0),
  "parent" if id==EMBED=>{row["parent_embed_id"]=json!(PARENT);row["embed_keys"]=json!([]);},
  "chat"=>{row["embed_keys"][0]["encrypted_embed_key"]=json!(crypto::server_fields::encrypt_bytes(&[7;32],&[3;32],&[]).unwrap());row["embed_keys"].as_array_mut().unwrap().push(json!({"hashed_embed_id":sha256(id),"hashed_user_id":sha256(OWNER),"hashed_chat_id":sha256(CHAT),"key_type":"chat","encrypted_embed_key":crypto::server_fields::encrypt_bytes(&[7;32],&[8;32],&[]).unwrap()}));},_=>{}
 }row
}
fn client(base:&str)->Client{
 let mut c=Client::new(base,Some(Session{api_url:base.into(),session_id:"owned-saved-fixture".into(),cookies:BTreeMap::from([("auth_refresh_token".into(),"initial".into())]),ws_token:Some("initial-token".into()),master_key:Zeroizing::new([9;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).unwrap();
 c.browser_credentials=Some(crate::client::credentials::BrowserCredentials::from_native_session(c.session.take().unwrap()));
 c.user=json!({"id":OWNER,"username":"fixture"});c.browser_transport=true;c.browser_authority=Some(crate::client::browser::BrowserAuthority{principal:OWNER.into(),persistence:crate::client::BrowserPersistence::MemoryOnly,owner_guards:true});
 c.chats.insert(CHAT.into(),json!({"id":CHAT,"chat_id":CHAT,"user_id":OWNER,"encrypted_chat_key":crypto::server_fields::encrypt_bytes(&[8;32],&[9;32],&[]).unwrap(),"encrypted_title":crypto::encrypt_combined("Local",&[8;32]).unwrap(),"messages_v":1,"title_v":1,"metadata_v":1}));c
}
struct Server {base:String,wire:Arc<tokio::sync::Notify>,release:Arc<tokio::sync::Notify>,hold_wire:Arc<AtomicBool>,auth:Arc<tokio::sync::Notify>,auth_release:Arc<tokio::sync::Notify>,hold_auth:Arc<AtomicBool>,requests:Arc<AtomicU64>,auth_count:Arc<AtomicU64>,sockets:Arc<AtomicU64>,closes:Arc<AtomicU64>,stop:CancellationToken,task:tokio::task::JoinHandle<()>}
impl Server {
 async fn open(mode:&'static str)->Self{
  let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
  let wire=Arc::new(tokio::sync::Notify::new());let release=Arc::new(tokio::sync::Notify::new());let hold_wire=Arc::new(AtomicBool::new(false));let auth=Arc::new(tokio::sync::Notify::new());let auth_release=Arc::new(tokio::sync::Notify::new());let hold_auth=Arc::new(AtomicBool::new(false));
  let requests=Arc::new(AtomicU64::new(0));let auth_count=Arc::new(AtomicU64::new(0));let sockets=Arc::new(AtomicU64::new(0));let closes=Arc::new(AtomicU64::new(0));let stop=CancellationToken::new();
  let(w,r,hw,a,ar,ha,n,ac,sc,cl,st)=(wire.clone(),release.clone(),hold_wire.clone(),auth.clone(),auth_release.clone(),hold_auth.clone(),requests.clone(),auth_count.clone(),sockets.clone(),closes.clone(),stop.clone());
  let task=tokio::spawn(async move{loop{
   let(stream,_)=tokio::select!{_=st.cancelled()=>break,value=listener.accept()=>value.unwrap()};
   let(w,r,hw,a,ar,ha,n,ac,sc,cl,st)=(w.clone(),r.clone(),hw.clone(),a.clone(),ar.clone(),ha.clone(),n.clone(),ac.clone(),sc.clone(),cl.clone(),st.clone());
   tokio::spawn(async move{
    let mut stream=stream;let mut raw=Vec::new();let header_end=loop{let mut bytes=[0u8;2048];let size=stream.read(&mut bytes).await.unwrap();if size==0{return}raw.extend_from_slice(&bytes[..size]);if let Some(end)=raw.windows(4).position(|v|v==b"\r\n\r\n"){break end+4}assert!(raw.len()<65536)};
    let head=String::from_utf8(raw[..header_end].to_vec()).unwrap();let path=head.lines().next().unwrap().split_whitespace().nth(1).unwrap();
    if path.starts_with("/v1/ws?"){
     sc.fetch_add(1,Ordering::AcqRel);assert!(!path.contains("chat_metadata_recovery"));assert!(!path.contains("task_update_jobs"));assert!(head.to_ascii_lowercase().contains("origin:"));
     if mode=="handshake-fail"{let _=stream.write_all(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await;return}
     if mode=="handshake"{w.notify_one();tokio::select!{_=st.cancelled()=>return,_=r.notified()=>{}};}
     let key=head.lines().find_map(|line|line.split_once(':').filter(|(k,_)|k.eq_ignore_ascii_case("sec-websocket-key")).map(|(_,v)|v.trim())).unwrap();let accept=tokio_tungstenite::tungstenite::handshake::derive_accept_key(key.as_bytes());
     if stream.write_all(format!("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").as_bytes()).await.is_err(){return}
     let mut ws=tokio_tungstenite::WebSocketStream::from_raw_socket(stream,tokio_tungstenite::tungstenite::protocol::Role::Server,None).await;let first=ws.next().await.unwrap().unwrap();
     if first.is_close(){cl.fetch_add(1,Ordering::AcqRel);let _=ws.close(None).await;return}let event:Value=serde_json::from_str(first.to_text().unwrap()).unwrap();assert_eq!(event["type"],"native_client_lifecycle");
     loop {let next=tokio::select!{_=st.cancelled()=>return,value=ws.next()=>value};let Some(Ok(frame))=next else{return};if frame.is_close(){cl.fetch_add(1,Ordering::AcqRel);let _=ws.close(None).await;return}
      let event:Value=serde_json::from_str(frame.to_text().unwrap()).unwrap();assert_eq!(event["type"],"request_embed");assert_eq!(event["payload"].as_object().unwrap().len(),1);let id=event["payload"]["embed_id"].as_str().unwrap();assert!([EMBED,PARENT].contains(&id));n.fetch_add(1,Ordering::AcqRel);w.notify_one();
      if hw.load(Ordering::Acquire){tokio::select!{_=st.cancelled()=>return,_=r.notified()=>{}};}
      let output=json!({"type":"send_embed_data","payload":payload(id,mode)});if ws.send(tokio_tungstenite::tungstenite::Message::Text(output.to_string().into())).await.is_err(){return}
     }
    }
    let(body,cookie)=if path=="/v1/auth/session"{
     let length=head.lines().find_map(|line|line.split_once(':').filter(|(k,_)|k.eq_ignore_ascii_case("content-length")).map(|(_,v)|v.trim().parse::<usize>().unwrap())).unwrap();while raw.len()-header_end<length{let mut bytes=[0;1024];let size=stream.read(&mut bytes).await.unwrap();assert!(size>0);raw.extend_from_slice(&bytes[..size]);}
     let data:Value=serde_json::from_slice(&raw[header_end..header_end+length]).unwrap();assert_eq!(data,json!({"session_id":"owned-saved-fixture"}));assert!(head.to_ascii_lowercase().contains("x-openmates-expected-principal:"));
     let count=ac.fetch_add(1,Ordering::AcqRel)+1;(json!({"success":true,"ws_token":format!("actual-token-{count}"),"user":{"id":OWNER,"username":"fixture"},"client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]}),format!("auth-{count}"))
    }else{assert_eq!(path,"/v1/tasks/rotation");(json!({"status":"pending"}),"actual-b-cookie".into())};
    let body=serde_json::to_vec(&body).unwrap();let declared=if mode=="oversize-auth"{transport::MAX_BODY+1}else{body.len()};let header=format!("HTTP/1.1 200 OK\r\ncontent-type: application/json\r\nset-cookie: auth_refresh_token={cookie}; Path=/\r\ncontent-length: {}\r\nconnection: close\r\n\r\n",declared);if stream.write_all(header.as_bytes()).await.is_err(){return}
    if path=="/v1/auth/session"&&ha.load(Ordering::Acquire){a.notify_one();tokio::select!{_=st.cancelled()=>return,_=ar.notified()=>{}};}
    let _=stream.write_all(&body).await;
   });
  }});Self{base,wire,release,hold_wire,auth,auth_release,hold_auth,requests,auth_count,sockets,closes,stop,task}
 }
}
impl Drop for Server{fn drop(&mut self){self.stop.cancel();self.task.abort();}}
async fn prepare_auth(driver:&mut PreparedOwnedSavedEmbedRead,c:&mut Client){for _ in 0..6{let OwnedSavedEmbedReadStep::Apply(phase)=driver.next().await.unwrap()else{panic!("both original auth/header/body sequences")};phase.apply(c).unwrap();}}
// Reach the actual wire request after applying the original socket and pre-wire check.
async fn prepare_wire_request(driver:&mut PreparedOwnedSavedEmbedRead,c:&mut Client){
 let OwnedSavedEmbedReadStep::Apply(connected)=driver.next().await.unwrap()else{panic!("actual connected phase")};
 assert!(matches!(connected.pending.work.as_ref(),Some(Work::Connected(_))));connected.apply(c).unwrap();
 let OwnedSavedEmbedReadStep::Apply(check)=driver.next().await.unwrap()else{panic!("actual pre-wire check phase")};
 assert!(matches!(check.pending.work.as_ref(),Some(Work::Check)));check.apply(c).unwrap();
}
async fn finish(driver:&mut PreparedOwnedSavedEmbedRead,c:&mut Client)->Result<OwnedSavedEmbedReadReady>{for _ in 0..80{match driver.next().await?{OwnedSavedEmbedReadStep::Apply(phase)=>phase.apply(c)?,OwnedSavedEmbedReadStep::Ready(value)=>return Ok(value)}}Err(Error::Protocol)}
async fn local_b(c:&mut Client){
 let host=serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":0})).unwrap();let metadata=c.chats[CHAT].clone();let row=json!({"message_id":"local-cache","chat_id":CHAT,"created_at":1,"role":"user","status":"delivered","encrypted_content":crypto::encrypt_combined(TEXT,&[8;32]).unwrap()});
 let mut read=c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,CHAT,Default::default(),host,20,true).unwrap();
 for _ in 0..32{match read.next().await.unwrap(){crate::client::OwnedBrowserReadStep::Apply(phase)=>phase.apply(c).unwrap(),crate::client::OwnedBrowserReadStep::IO(io)=>{let(metadata,row)=(metadata.clone(),row.clone());io.execute(move|encoded|async move{let plan:Value=serde_json::from_str(&encoded).unwrap();let mut data=json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"databaseVersion":1});if plan["kind"]=="owned_metadata"{data["chat_metadata"]=metadata;data["messages"]=json!([]);data["wrappers"]=json!([]);data["boundary"]=Value::Null;data["compression_checkpoints"]=json!([])}else{data["messages"]=json!([row]);data["nextKey"]=Value::Null;data["rangeExhausted"]=json!(true)}Ok(data.to_string())}).await.unwrap().apply(c).unwrap();},crate::client::OwnedBrowserReadStep::Selected(mut publication)=>{let data:Value=serde_json::from_str(&publication.take(c,true).unwrap()).unwrap();assert_eq!(data["cacheReadKind"],"local");assert_eq!(data["chat"]["messages"][0]["content"],TEXT);publication.finish_cold(c).unwrap();return},_=>panic!("local selected only")}}panic!("bounded local phase sequence")
}
#[tokio::test]
async fn real_held_embed_read_allows_owned_local_b_and_actual_cookie_rotation_without_monitor_replacement(){
 let s=Server::open("root").await;s.hold_wire.store(true,Ordering::Release);let mut c=client(&s.base);let marker=CancellationToken::new();c.monitor_cancel=Some(marker.clone());let parent=c.operation_parent.clone();let old_cancel=c.operation_cancel.clone();let sibling=Arc::new(OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap());
 let mut read=c.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();let control=read.control();prepare_auth(&mut read,&mut c).await;prepare_wire_request(&mut read,&mut c).await;
 let mut pending=Box::pin(read.next());assert!(futures_util::poll!(pending.as_mut()).is_pending());drive_until_held_notice(pending.as_mut(), &s.wire).await;local_b(&mut c).await;
 let request={let mut active=ActiveOwnedClient::enter(&mut c,&sibling).unwrap();active.prepare_owned_read(transport::OwnedReadRoute::AppTask("rotation")).unwrap()};let token=sibling.request();let headers=transport::send_owned_read_headers(request,&token,||sibling.observer().check_release()).await.unwrap();let body=c.apply_owned_read_headers(headers).unwrap();let body=transport::drive_owned_read_body(body,&token,||sibling.observer().check_release()).await.unwrap();c.finish_owned_read(body).unwrap();
 control.ensure_current(&c).unwrap();assert!(futures_util::poll!(pending.as_mut()).is_pending());s.release.notify_one();let OwnedSavedEmbedReadStep::Apply(phase)=pending.await.unwrap()else{panic!("actual same-socket row")};phase.apply(&mut c).unwrap();
 let mut ready=finish(&mut read,&mut c).await.unwrap();let selected=ready.retain(&c).unwrap();assert!(ready.retain(&c).is_err());let data:Value=serde_json::from_str(&selected.json(&c).unwrap()).unwrap();assert_eq!(data["content"]["text"],TEXT);assert_eq!(data["embed_id"],EMBED);assert!(data.get("embed_keys").is_none());assert!(c.embeds.is_empty());assert!(c.embed_keys.is_empty());
 assert_eq!(s.auth_count.load(Ordering::Acquire),2);assert_eq!(s.sockets.load(Ordering::Acquire),1);assert_eq!(s.requests.load(Ordering::Acquire),1);assert_eq!(c.cookies["auth_refresh_token"],"actual-b-cookie");assert_eq!(c.monitor_cancel,Some(marker.clone()));assert!(!marker.is_cancelled());assert_eq!(c.operation_parent,parent);assert_eq!(c.operation_cancel,old_cancel);sibling.check(&c).unwrap();assert!(control.terminal().unwrap().acquisition_io_quiescent());control.cancel();assert!(selected.json(&c).is_err());sibling.check(&c).unwrap();
}
#[tokio::test]
async fn normal_chat_wrapper_and_parent_key_paths_reuse_the_same_selection_engine(){
 for mode in ["chat","parent"]{let s=Server::open(mode).await;let mut c=client(&s.base);let mut read=c.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();let mut ready=finish(&mut read,&mut c).await.unwrap();let selected=ready.retain(&c).unwrap();let data:Value=serde_json::from_str(&selected.json(&c).unwrap()).unwrap();assert_eq!(data["content"]["text"],TEXT);assert_eq!(data["embed_id"],EMBED);assert_eq!(s.requests.load(Ordering::Acquire),if mode=="parent"{2}else{1});assert!(c.embeds.is_empty());}
}
#[tokio::test]
async fn real_foreign_id_owner_and_incomplete_wrappers_refuse_without_fallback_or_plaintext(){
 for mode in ["wrong-id","owner","incomplete","expired"]{let s=Server::open(mode).await;let mut c=client(&s.base);let mut read=c.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();assert!(finish(&mut read,&mut c).await.is_err());assert!(read.context.read.lock().unwrap().is_none());assert_eq!(s.requests.load(Ordering::Acquire),1);assert_eq!(s.auth_count.load(Ordering::Acquire),2);assert!(c.embeds.is_empty());}
}
#[tokio::test]
async fn cancelled_started_auth_retains_real_headers_body_rotation_and_only_stops_original_read(){
 let s=Server::open("root").await;s.hold_auth.store(true,Ordering::Release);let mut c=client(&s.base);let b=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();let mut read=c.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();let control=read.control();
 let OwnedSavedEmbedReadStep::Apply(phase)=read.next().await.unwrap()else{panic!("prepare")};phase.apply(&mut c).unwrap();let OwnedSavedEmbedReadStep::Apply(headers)=read.next().await.unwrap()else{panic!("actual headers")};headers.apply(&mut c).unwrap();assert_eq!(c.cookies["auth_refresh_token"],"auth-1");
 let mut body=Box::pin(read.next());assert!(futures_util::poll!(body.as_mut()).is_pending());s.auth.notified().await;control.cancel();assert!(control.terminal().is_none());assert!(futures_util::poll!(body.as_mut()).is_pending());s.auth_release.notify_one();let OwnedSavedEmbedReadStep::Apply(phase)=body.await.unwrap()else{panic!("actual body")};phase.apply(&mut c).unwrap();assert!(read.next().await.is_err());
 assert_eq!(c.require_credentials().unwrap().ws_token.as_deref(),Some("actual-token-1"));assert_eq!(s.sockets.load(Ordering::Acquire),0);assert_eq!(s.auth_count.load(Ordering::Acquire),1);b.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());assert!(control.terminal().unwrap().acquisition_io_quiescent());
}
#[tokio::test]
async fn changed_owner_during_actual_read_and_abandoned_apply_never_mint_a_ready_resource(){
 let s=Server::open("root").await;s.hold_wire.store(true,Ordering::Release);let mut c=client(&s.base);let mut read=c.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();prepare_auth(&mut read,&mut c).await;prepare_wire_request(&mut read,&mut c).await;let control=read.control();let mut pending=Box::pin(read.next());assert!(futures_util::poll!(pending.as_mut()).is_pending());drive_until_held_notice(pending.as_mut(), &s.wire).await;c.user=json!({"id":PARENT,"username":"other"});c.credentials_changed();s.release.notify_one();match pending.await{Err(_)=>{},Ok(OwnedSavedEmbedReadStep::Apply(phase))=>{phase.apply(&mut c).unwrap();assert!(read.next().await.is_err())},_=>panic!("no cross-owner ready")};assert!(control.ensure_current(&c).is_err());assert!(read.context.read.lock().unwrap().is_none());
 let mut c=client(&s.base);let b=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();let mut read=c.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();let control=read.control();let OwnedSavedEmbedReadStep::Apply(phase)=read.next().await.unwrap()else{panic!("prepare")};drop(phase);assert!(read.next().await.is_err());assert!(control.terminal().is_none());b.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());
}
#[test]
fn original_twenty_second_budget_is_never_restarted_after_queue_or_preparation(){
 let start=Instant::now();let deadline=start+Duration::from_secs(20);
 assert_eq!(PreparedOwnedSessionValidation::saved_embed_remaining(deadline,start+Duration::from_secs(19)).unwrap(),Duration::from_secs(1));assert_eq!(PreparedOwnedSessionValidation::saved_embed_remaining(deadline,start).unwrap(),Duration::from_secs(20));assert!(PreparedOwnedSessionValidation::saved_embed_remaining(deadline,deadline).is_err());assert!(PreparedOwnedSessionValidation::saved_embed_remaining(deadline,deadline+Duration::from_millis(1)).is_err());
}
struct HeldMaster {first:AtomicBool,entered:Arc<tokio::sync::Notify>,release:Arc<tokio::sync::Notify>}
impl crate::crypto::master::MasterCrypto for HeldMaster {
 fn encrypt<'a>(&'a self,iv:&'a [u8;12],bytes:&'a [u8])->crate::crypto::master::MasterCryptoFuture<'a>{Box::pin(async move{crypto::encrypt_aead(bytes,&[9;32],iv,&[]).map(Zeroizing::new)})}
 fn decrypt<'a>(&'a self,iv:&'a [u8;12],bytes:&'a [u8])->crate::crypto::master::MasterCryptoFuture<'a>{Box::pin(async move{if self.first.swap(false,Ordering::AcqRel){self.entered.notify_one();self.release.notified().await;}crypto::decrypt_aead(bytes,&[9;32],iv,&[])})}
}
#[tokio::test]
async fn opaque_master_wait_is_detached_and_cancellation_cannot_publish_before_actual_crypto_returns(){
 let s=Server::open("root").await;let mut c=client(&s.base);let entered=Arc::new(tokio::sync::Notify::new());let release=Arc::new(tokio::sync::Notify::new());
 let mut credentials=c.browser_credentials.take().unwrap();credentials.master=MasterCapability::opaque_for_test(Arc::new(HeldMaster{first:AtomicBool::new(true),entered:entered.clone(),release:release.clone()}));c.browser_credentials=Some(credentials);assert!(c.native_master_key().is_err());
 let mut read=c.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();let control=read.control();let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();
 for _ in 0..40{
  let mut next=Box::pin(read.next());let actual=tokio::select!{value=&mut next=>Some(value),_=entered.notified()=>None};
  match actual{Some(Ok(OwnedSavedEmbedReadStep::Apply(phase)))=>{drop(next);phase.apply(&mut c).unwrap();},None=>{
   local_b(&mut c).await;control.cancel();assert!(control.terminal().is_none());assert!(futures_util::poll!(next.as_mut()).is_pending());release.notify_one();assert!(next.await.is_err());assert!(read.context.read.lock().unwrap().is_none());sibling.check(&c).unwrap();assert!(c.native_master_key().is_err());assert!(control.terminal().unwrap().acquisition_io_quiescent());return
  },_=>panic!("no ready before real held opaque decrypt")}
 }panic!("bounded original phase sequence must reach actual crypto")
}
#[tokio::test]
async fn actual_held_dedicated_handshake_allows_local_b_and_failed_connect_has_no_terminal_claim(){
 let s=Server::open("handshake").await;let mut c=client(&s.base);let marker=CancellationToken::new();c.monitor_cancel=Some(marker.clone());let mut read=c.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();let control=read.control();prepare_auth(&mut read,&mut c).await;
 let mut next=Box::pin(read.next());assert!(futures_util::poll!(next.as_mut()).is_pending());drive_until_held_notice(next.as_mut(), &s.wire).await;local_b(&mut c).await;assert!(control.terminal().is_none());assert_eq!(c.monitor_cancel,Some(marker.clone()));assert!(!marker.is_cancelled());s.release.notify_one();let OwnedSavedEmbedReadStep::Apply(phase)=next.await.unwrap()else{panic!("actual connected phase")};phase.apply(&mut c).unwrap();let mut ready=finish(&mut read,&mut c).await.unwrap();ready.retain(&c).unwrap().check(&c).unwrap();assert!(control.terminal().unwrap().acquisition_io_quiescent());
 let s=Server::open("handshake-fail").await;let mut c=client(&s.base);let mut read=c.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();let control=read.control();assert!(finish(&mut read,&mut c).await.is_err());assert!(control.terminal().is_none());assert!(read.context.read.lock().unwrap().is_none());assert_eq!(s.requests.load(Ordering::Acquire),0);
}
#[tokio::test]
async fn held_original_auth_headers_refused_by_foreign_client_remain_unknown_after_driver_returns(){
 let s=Server::open("root").await;s.hold_auth.store(true,Ordering::Release);
 let mut original=client(&s.base);let mut foreign=client(&s.base);
 let sibling=OwnedOperationScope::capture(&original,CancellationToken::new()).unwrap();
 let parent=original.operation_parent.clone();let foreign_parent=foreign.operation_parent.clone();
 let mut read=original.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();let control=read.control();
 let OwnedSavedEmbedReadStep::Apply(prepare)=read.next().await.unwrap()else{panic!("actual original auth prepare")};prepare.apply(&mut original).unwrap();
 let OwnedSavedEmbedReadStep::Apply(headers)=read.next().await.unwrap()else{panic!("actual headers while body remains held")};s.auth.notified().await;
 assert!(control.terminal().is_none());headers.apply(&mut foreign).unwrap();
 assert!(matches!(read.next().await,Err(Error::Cancelled)));
 assert!(read.context.returned.load(Ordering::Acquire));assert_eq!(read.context.pending.load(Ordering::Acquire),0);
 assert!(read.context.abandoned.load(Ordering::Acquire));assert!(control.terminal().is_none(),"actual body was never consumed: Err/returned/pending=0 is not quiescence");
 assert!(read.context.read.lock().unwrap().is_none());assert_eq!(s.auth_count.load(Ordering::Acquire),1);assert_eq!(s.sockets.load(Ordering::Acquire),0);assert_eq!(s.requests.load(Ordering::Acquire),0);
 assert_eq!(original.cookies["auth_refresh_token"],"initial");assert_eq!(foreign.cookies["auth_refresh_token"],"initial");assert_eq!(original.require_credentials().unwrap().ws_token.as_deref(),Some("initial-token"));assert_eq!(foreign.require_credentials().unwrap().ws_token.as_deref(),Some("initial-token"));
 sibling.observer().check_release().unwrap();assert!(!parent.is_cancelled());assert!(!foreign_parent.is_cancelled());
 s.auth_release.notify_one();tokio::task::yield_now().await;
 assert!(control.terminal().is_none(),"server release cannot manufacture an unobserved original body/IO terminal");assert!(matches!(read.next().await,Err(Error::Conflict)));drop(read);assert!(control.terminal().is_none());
}
#[tokio::test]
async fn actual_oversized_declared_auth_body_is_unknown_despite_ok_header_body_phase_and_driver_return(){
 let s=Server::open("oversize-auth").await;s.hold_auth.store(true,Ordering::Release);let mut c=client(&s.base);
 let mut read=c.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();let control=read.control();
 let OwnedSavedEmbedReadStep::Apply(prepare)=read.next().await.unwrap()else{panic!("original auth prepare")};prepare.apply(&mut c).unwrap();
 let OwnedSavedEmbedReadStep::Apply(headers)=read.next().await.unwrap()else{panic!("actual oversized response header")};s.auth.notified().await;headers.apply(&mut c).unwrap();
 assert!(!read.context.abandoned.load(Ordering::Acquire),"outer header apply succeeded with a Body resource");assert_eq!(c.cookies["auth_refresh_token"],"auth-1");
 let OwnedSavedEmbedReadStep::Apply(finish)=read.next().await.unwrap()else{panic!("actual inner-body fast refusal")};
 let Some(Work::AuthFinish(completed,_))=finish.pending.work.as_ref()else{panic!("sealed actual completed phase")};
 assert!(completed.io_terminal_for(&c).is_none(),"declared-size refusal did not observe actual body EOF");finish.apply(&mut c).unwrap();assert!(read.next().await.is_err());
 assert!(read.context.returned.load(Ordering::Acquire));assert_eq!(read.context.pending.load(Ordering::Acquire),0);assert!(read.context.abandoned.load(Ordering::Acquire));assert!(control.terminal().is_none());assert!(read.context.read.lock().unwrap().is_none());
 assert_eq!(s.auth_count.load(Ordering::Acquire),1);assert_eq!(s.sockets.load(Ordering::Acquire),0);assert_eq!(s.requests.load(Ordering::Acquire),0);
 s.auth_release.notify_one();tokio::task::yield_now().await;assert!(control.terminal().is_none());drop(read);assert!(control.terminal().is_none());
}
#[tokio::test]
async fn actual_auth_body_eof_cannot_attest_foreign_original_target_or_drop_matched_bookkeeping_as_quiescent(){
 let s=Server::open("root").await;s.hold_auth.store(true,Ordering::Release);let mut original=client(&s.base);let mut foreign=client(&s.base);let foreign_parent=foreign.operation_parent.clone();
 let mut read=original.prepare_owned_saved_embed_read(EMBED,CancellationToken::new()).unwrap();let control=read.control();
 let OwnedSavedEmbedReadStep::Apply(prepare)=read.next().await.unwrap()else{panic!("original prepare")};prepare.apply(&mut original).unwrap();
 let OwnedSavedEmbedReadStep::Apply(headers)=read.next().await.unwrap()else{panic!("original headers")};headers.apply(&mut original).unwrap();
 let mut body=Box::pin(read.next());assert!(futures_util::poll!(body.as_mut()).is_pending());s.auth.notified().await;assert!(control.terminal().is_none());s.auth_release.notify_one();
 let OwnedSavedEmbedReadStep::Apply(finish)=body.await.unwrap()else{panic!("actual body EOF completion")};let Some(Work::AuthFinish(completed,_))=finish.pending.work.as_ref()else{panic!("actual completed phase")};
 assert!(completed.io_terminal_for(&original).is_some(),"actual EOF and SAME pre-finish original target");assert!(completed.io_terminal_for(&foreign).is_none(),"EOF cannot match another Client/epoch/key");
 finish.apply(&mut foreign).unwrap();assert!(matches!(read.next().await,Err(Error::Cancelled)));assert!(read.context.abandoned.load(Ordering::Acquire));assert!(control.terminal().is_none());assert!(read.context.read.lock().unwrap().is_none());
 assert_eq!(original.cookies["auth_refresh_token"],"auth-1");assert_eq!(foreign.cookies["auth_refresh_token"],"initial");assert_eq!(original.require_credentials().unwrap().ws_token.as_deref(),Some("initial-token"));assert_eq!(foreign.require_credentials().unwrap().ws_token.as_deref(),Some("initial-token"));assert!(!foreign_parent.is_cancelled());
 assert_eq!(s.auth_count.load(Ordering::Acquire),1);assert_eq!(s.sockets.load(Ordering::Acquire),0);assert_eq!(s.requests.load(Ordering::Acquire),0);drop(read);assert!(control.terminal().is_none());
}
