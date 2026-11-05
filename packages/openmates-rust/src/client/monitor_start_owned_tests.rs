//! Authored UNRUN actual Core/HTTP/socket/key cases. Cursor IO is inert; native
//! browser DB/provenance/lock/latency acceptance remains isolated CI.
use super::*;
use futures_util::{SinkExt,StreamExt};
use tokio::io::{AsyncReadExt,AsyncWriteExt};
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const CHAT:&str="22222222-2222-4222-8222-222222222222";
const TEAM:&str="33333333-3333-4333-8333-333333333333";
const TEXT:&str="Synthetic cached content while original handshake remains held";
struct Server {
    deny_auth:Arc<AtomicBool>,
    base:String,handshake:Arc<tokio::sync::Notify>,release:Arc<tokio::sync::Notify>,auth_held:Arc<tokio::sync::Notify>,auth_release:Arc<tokio::sync::Notify>,hold_auth:Arc<AtomicBool>,
    auth_count:Arc<AtomicU64>,sockets:Arc<AtomicU64>,selected_http:Arc<AtomicU64>,stop:CancellationToken,task:tokio::task::JoinHandle<()>,
    team_count:Arc<AtomicU64>,deny_second_team:Arc<AtomicBool>,
}
impl Server {
    async fn open()->Self{
        let deny_auth=Arc::new(AtomicBool::new(false));let da=deny_auth.clone();
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
        let handshake=Arc::new(tokio::sync::Notify::new());let release=Arc::new(tokio::sync::Notify::new());
        let auth_held=Arc::new(tokio::sync::Notify::new());let auth_release=Arc::new(tokio::sync::Notify::new());let hold_auth=Arc::new(AtomicBool::new(false));
        let auth_count=Arc::new(AtomicU64::new(0));let sockets=Arc::new(AtomicU64::new(0));let selected_http=Arc::new(AtomicU64::new(0));let stop=CancellationToken::new();
        let team_count=Arc::new(AtomicU64::new(0));let deny_second_team=Arc::new(AtomicBool::new(false));let(tc,dt)=(team_count.clone(),deny_second_team.clone());
        let(h,r,a,ar,ha,ac,sc,selected,st)=(handshake.clone(),release.clone(),auth_held.clone(),auth_release.clone(),hold_auth.clone(),auth_count.clone(),sockets.clone(),selected_http.clone(),stop.clone());
        let task=tokio::spawn(async move{loop{
            let(stream,_)=tokio::select!{_=st.cancelled()=>break,value=listener.accept()=>value.unwrap()};
            let(h,r,a,ar,ha,ac,sc,selected,st)=(h.clone(),r.clone(),a.clone(),ar.clone(),ha.clone(),ac.clone(),sc.clone(),selected.clone(),st.clone());
            let(tc,dt)=(tc.clone(),dt.clone());
            let da=da.clone();
            tokio::spawn(async move{
                let mut stream=stream;let mut raw=Vec::new();loop{let mut bytes=[0;1024];let n=stream.read(&mut bytes).await.unwrap();if n==0{return}raw.extend_from_slice(&bytes[..n]);if raw.windows(4).any(|p|p==b"\r\n\r\n"){break}assert!(raw.len()<65536)}
                let request=String::from_utf8(raw).unwrap();let path=request.lines().next().unwrap().split_whitespace().nth(1).unwrap();
                if path.starts_with("/v1/ws?"){
                    assert!(!path.contains("chat_metadata_recovery"));assert!(!path.contains("task_update_jobs"));sc.fetch_add(1,Ordering::AcqRel);h.notify_one();
                    tokio::select!{_=st.cancelled()=>return,_=r.notified()=>{}};
                    let key=request.lines().find_map(|line|line.split_once(':').filter(|(key,_)|key.eq_ignore_ascii_case("sec-websocket-key")).map(|(_,v)|v.trim())).unwrap();
                    let accept=tokio_tungstenite::tungstenite::handshake::derive_accept_key(key.as_bytes());
                    if stream.write_all(format!("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").as_bytes()).await.is_err(){return}
                    let mut ws=tokio_tungstenite::WebSocketStream::from_raw_socket(stream,tokio_tungstenite::tungstenite::protocol::Role::Server,None).await;
                    let first=tokio::select!{_=st.cancelled()=>return,value=ws.next()=>value};
                    if let Some(Ok(first))=first{if first.is_close(){let _=ws.close(None).await;return}let event:Value=serde_json::from_str(first.to_text().unwrap()).unwrap();assert_eq!(event["type"],"native_client_lifecycle");
                        ws.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"disabled"}}).to_string().into())).await.unwrap();}
                    loop{let next=tokio::select!{_=st.cancelled()=>return,value=ws.next()=>value};match next{Some(Ok(value))if value.is_close()=>{let _=ws.close(None).await;return},None|Some(Err(_))=>return,_=>{}}}
                }
                let mut status="200 OK";let(body,cookie)=if path=="/v1/auth/session"{
                    let count=ac.fetch_add(1,Ordering::AcqRel)+1;
                    if count==2&&ha.load(Ordering::Acquire){a.notify_one();tokio::select!{_=st.cancelled()=>return,_=ar.notified()=>{}};}
                    if count==2&&da.load(Ordering::Acquire){status="401 Unauthorized";}
                    (json!({"success":true,"ws_token":"synthetic-token","user":{"id":OWNER},"client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]}),if count==2{"set-cookie: auth_refresh_token=actual-auth-rotation; Path=/\r\n"}else{""})
                }else if path==format!("/v1/teams/{TEAM}"){
                    let count=tc.fetch_add(1,Ordering::AcqRel)+1;if count==2&&dt.load(Ordering::Acquire){status="403 Forbidden";}
                    (json!({"team":{"team_id":TEAM}}),"")
                }else if path=="/v1/tasks/rotation"{(json!({"status":"pending"}),"set-cookie: auth_refresh_token=actual-b-header-rotation; Path=/\r\n")}
                else{selected.fetch_add(1,Ordering::AcqRel);(json!({}),"")};
                let body=serde_json::to_vec(&body).unwrap();let head=format!("HTTP/1.1 {status}\r\n{cookie}content-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n",body.len());let _=stream.write_all(head.as_bytes()).await;let _=stream.write_all(&body).await;
            });
        }});
        Self{deny_auth,base,handshake,release,auth_held,auth_release,hold_auth,auth_count,sockets,selected_http,stop,task,team_count,deny_second_team}
    }
    async fn client(&self)->Client{
        let profile=crate::client::BrowserProfileKey::from_existing_profile(OWNER,zeroize::Zeroizing::new([7;32]),"fixture-hash","fixture-salt",crate::client::BrowserPersistence::MemoryOnly).unwrap();
        crate::client::browser::restore_monitor_test_profile(&self.base,"http://localhost:5173",OWNER,profile).await.unwrap()
    }
}
impl Drop for Server{fn drop(&mut self){self.stop.cancel();self.task.abort();}}
#[path="browser_profile_cache_readiness_tests.rs"]
mod profile_cache_readiness;
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
async fn first_auth(driver:&mut PreparedOwnedChatMonitor,c:&mut Client){
    for _ in 0..3{let OwnedChatMonitorStartStep::Apply(phase)=driver.next().await.unwrap()else{panic!("actual auth preparation/header/body phase required")};phase.apply(c).unwrap();}
}
async fn ready(driver:&mut PreparedOwnedChatMonitor,c:&mut Client)->Result<OwnedChatMonitorReady>{
    for _ in 0..20{match driver.next().await?{OwnedChatMonitorStartStep::Apply(phase)=>phase.apply(c)?,OwnedChatMonitorStartStep::Ready(ready)=>return Ok(ready)}}Err(Error::Protocol)
}
fn header()->Value{json!({"id":CHAT,"chat_id":CHAT,"user_id":OWNER,"encrypted_chat_key":crypto::server_fields::encrypt_bytes(&[9;32],&[7;32],&[]).unwrap(),"encrypted_title":crypto::encrypt_combined("Local",&[9;32]).unwrap(),"messages_v":1,"title_v":1,"metadata_v":1})}
async fn local_b(c:&mut Client){
    let host=serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":0})).unwrap();
    let metadata=header();let row=json!({"message_id":"cached-local","chat_id":CHAT,"created_at":1,"role":"user","status":"delivered","encrypted_content":crypto::encrypt_combined(TEXT,&[9;32]).unwrap(),"content":"ignored clear extension"});
    let mut driver=c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,CHAT,Default::default(),host,20,true).unwrap();
    for _ in 0..30{match driver.next().await.unwrap(){
        crate::client::OwnedBrowserReadStep::Apply(phase)=>phase.apply(c).unwrap(),
        crate::client::OwnedBrowserReadStep::IO(io)=>{
            let(metadata,row)=(metadata.clone(),row.clone());io.execute(move|encoded|async move{
                let plan:Value=serde_json::from_str(&encoded).unwrap();let mut response=json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"databaseVersion":1});
                if plan["kind"]=="owned_metadata"{response["chat_metadata"]=metadata;response["messages"]=json!([]);response["wrappers"]=json!([]);response["boundary"]=Value::Null;response["compression_checkpoints"]=json!([])}
                else{assert_eq!(plan["kind"],"messages");response["messages"]=json!([row]);response["nextKey"]=Value::Null;response["rangeExhausted"]=json!(true)}Ok(response.to_string())
            }).await.unwrap().apply(c).unwrap();
        },
        crate::client::OwnedBrowserReadStep::Selected(mut publication)=>{
            let value:Value=serde_json::from_str(&publication.take(c,true).unwrap()).unwrap();assert_eq!(value["cacheReadKind"],"local");assert_eq!(value["chat"]["messages"][0]["content"],TEXT);publication.finish_cold(c).unwrap();return
        },_=>panic!("selected local B required"),
    }}panic!("bounded local B phases")
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn actual_held_original_handshake_does_not_borrow_client_or_block_owned_local_b_and_witnessed_cookie_rotation(){
    let server=Server::open().await;let mut c=server.client().await;let(errors,_receiver)=mpsc::channel(4);
    let mut acquisition=c.prepare_owned_chat_monitor(CancellationToken::new(),errors).unwrap();let control=acquisition.control();
    first_auth(&mut acquisition,&mut c).await;
    let mut connecting=Box::pin(acquisition.next());assert!(futures_util::poll!(connecting.as_mut()).is_pending());drive_until_held_notice(connecting.as_mut(), &server.handshake).await;
    tokio::time::timeout(Duration::from_secs(2),local_b(&mut c)).await.unwrap();assert_eq!(server.selected_http.load(Ordering::Acquire),0);
    let sibling=Arc::new(OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap());
    let request={let mut active=ActiveOwnedClient::enter(&mut c,&sibling).unwrap();active.prepare_owned_read(OwnedReadRoute::AppTask("rotation")).unwrap()};
    let token=sibling.request();let headers=transport::send_owned_read_headers(request,&token,||sibling.observer().check_release()).await.unwrap();
    let body=c.apply_owned_read_headers(headers).unwrap();let body=transport::drive_owned_read_body(body,&token,||sibling.observer().check_release()).await.unwrap();c.finish_owned_read(body).unwrap();
    control.ensure_current(&c).unwrap();assert!(futures_util::poll!(connecting.as_mut()).is_pending());assert_eq!(server.sockets.load(Ordering::Acquire),1);
    server.release.notify_one();let OwnedChatMonitorStartStep::Apply(phase)=connecting.await.unwrap()else{panic!("actual connected Client phase")};phase.apply(&mut c).unwrap();
    let mut original=ready(&mut acquisition,&mut c).await.unwrap();let monitor=original.retain(&c).unwrap();assert!(original.retain(&c).is_err());
    assert_eq!(server.auth_count.load(Ordering::Acquire),3);assert_eq!(server.sockets.load(Ordering::Acquire),1);c.check_chat_monitor_fence(&monitor.fence).unwrap();
    assert!(control.terminal().unwrap().acquisition_io_quiescent());assert!(c.completion_recovery_mode.is_none());control.cancel();sibling.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn cancelled_or_superseded_held_handshake_retires_only_original_acquisition_after_real_connect_returns(){
    for supersede in [false,true]{
        let server=Server::open().await;let mut c=server.client().await;let(errors,_receiver)=mpsc::channel(4);
        let mut acquisition=c.prepare_owned_chat_monitor(CancellationToken::new(),errors).unwrap();let control=acquisition.control();first_auth(&mut acquisition,&mut c).await;
        let mut connecting=Box::pin(acquisition.next());assert!(futures_util::poll!(connecting.as_mut()).is_pending());drive_until_held_notice(connecting.as_mut(), &server.handshake).await;
        let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();
        let later=if supersede{let(errors,_receiver)=mpsc::channel(4);Some(c.prepare_owned_chat_monitor(CancellationToken::new(),errors).unwrap())}else{control.cancel();None};
        assert!(control.terminal().is_none());assert!(futures_util::poll!(connecting.as_mut()).is_pending());sibling.check(&c).unwrap();
        server.release.notify_one();assert!(connecting.await.is_err());assert!(control.terminal().unwrap().acquisition_io_quiescent());sibling.check(&c).unwrap();
        if let Some(later)=later{later.control().ensure_current(&c).unwrap();assert_eq!(server.sockets.load(Ordering::Acquire),1)}
        assert!(!c.operation_parent.is_cancelled());
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn changed_profile_or_foreign_actual_client_cannot_retain_original_connected_monitor(){
    for changed_profile in [false,true]{
        let server=Server::open().await;let mut c=server.client().await;let mut foreign=server.client().await;let(errors,_receiver)=mpsc::channel(4);
        let mut acquisition=c.prepare_owned_chat_monitor(CancellationToken::new(),errors).unwrap();first_auth(&mut acquisition,&mut c).await;
        let mut connecting=Box::pin(acquisition.next());assert!(futures_util::poll!(connecting.as_mut()).is_pending());drive_until_held_notice(connecting.as_mut(), &server.handshake).await;
        if changed_profile{c.forget_session();c=server.client().await;}
        let healthy=OwnedOperationScope::capture(if changed_profile{&c}else{&foreign},CancellationToken::new()).unwrap();server.release.notify_one();
        match connecting.await{Ok(OwnedChatMonitorStartStep::Apply(phase))=>{phase.apply(&mut foreign).unwrap();assert!(acquisition.next().await.is_err())},Err(_)=>{},_=>panic!("foreign monitor must never become ready")}
        healthy.check(if changed_profile{&c}else{&foreign}).unwrap();
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn cancelled_actual_auth_still_applies_matched_cookie_and_body_before_refusing_monitor_without_new_socket(){
    let server=Server::open().await;let mut c=server.client().await;server.hold_auth.store(true,Ordering::Release);
    let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();let(errors,_receiver)=mpsc::channel(4);
    let mut acquisition=c.prepare_owned_chat_monitor(CancellationToken::new(),errors).unwrap();let control=acquisition.control();
    let OwnedChatMonitorStartStep::Apply(prepare)=acquisition.next().await.unwrap()else{panic!("prepare actual auth")};prepare.apply(&mut c).unwrap();
    assert!(c.require_browser_owner_guards().is_err(),"auth-held private cache readiness is explicitly NOT granted by this split");
    let mut headers=Box::pin(acquisition.next());assert!(futures_util::poll!(headers.as_mut()).is_pending());drive_until_held_notice(headers.as_mut(), &server.auth_held).await;control.cancel();
    assert!(control.terminal().is_none());assert!(futures_util::poll!(headers.as_mut()).is_pending());server.auth_release.notify_one();
    let OwnedChatMonitorStartStep::Apply(apply)=headers.await.unwrap()else{panic!("actual matched headers retained")};apply.apply(&mut c).unwrap();
    let OwnedChatMonitorStartStep::Apply(body)=acquisition.next().await.unwrap()else{panic!("actual matched auth body retained")};body.apply(&mut c).unwrap();
    assert!(acquisition.next().await.is_err());assert_eq!(c.cookies.get("auth_refresh_token").map(String::as_str),Some("actual-auth-rotation"));
    assert_eq!(server.sockets.load(Ordering::Acquire),0);sibling.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());assert!(control.terminal().unwrap().acquisition_io_quiescent());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn abandoned_actual_apply_is_never_a_terminal_receipt_or_a_parent_cancel(){
    let server=Server::open().await;let mut c=server.client().await;let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();let(errors,_receiver)=mpsc::channel(4);
    let mut acquisition=c.prepare_owned_chat_monitor(CancellationToken::new(),errors).unwrap();let control=acquisition.control();
    let OwnedChatMonitorStartStep::Apply(phase)=acquisition.next().await.unwrap()else{panic!("actual typed apply required")};drop(phase);
    assert!(acquisition.next().await.is_err());assert!(control.terminal().is_none());sibling.check(&c).unwrap();assert_eq!(server.auth_count.load(Ordering::Acquire),1);assert_eq!(server.sockets.load(Ordering::Acquire),0);assert!(!c.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_current_team_is_checked_twice_and_second_denial_retires_real_monitor_without_a_ready_grant(){
    for denied in [false,true]{
        let server=Server::open().await;let mut c=server.client().await;
        // Explicit fixture workspace selection before any original operation.
        c.browser_credentials.as_mut().unwrap().active_team_id=Some(TEAM.into());server.deny_second_team.store(denied,Ordering::Release);
        let(errors,_receiver)=mpsc::channel(4);let mut acquisition=c.prepare_owned_chat_monitor(CancellationToken::new(),errors).unwrap();let control=acquisition.control();
        first_auth(&mut acquisition,&mut c).await;server.release.notify_one();
        let result=ready(&mut acquisition,&mut c).await;
        if denied{assert!(result.is_err());assert!(control.ensure_current(&c).is_err())}
        else{let monitor=result.unwrap().retain(&c).unwrap();assert_eq!(monitor.fence.team.as_deref(),Some(TEAM));control.cancel();}
        assert_eq!(server.team_count.load(Ordering::Acquire),2);assert_eq!(server.auth_count.load(Ordering::Acquire),3);assert_eq!(server.sockets.load(Ordering::Acquire),1);assert_eq!(server.selected_http.load(Ordering::Acquire),0);
    }
}
