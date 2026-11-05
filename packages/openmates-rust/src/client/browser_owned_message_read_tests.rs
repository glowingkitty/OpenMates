//! Authored UNRUN actual Core/HTTP/crypto phases. The storage port below is an
//! inert protocol fixture, not native IndexedDB or held-send acceptance proof.
use super::*;
use base64::Engine;
use futures_util::{SinkExt,StreamExt};
use std::{cell::RefCell,rc::Rc};
use tokio::io::{AsyncReadExt,AsyncWriteExt};
#[path="browser_owned_local_first_tests.rs"]
mod local_first_tests;
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const B:&str="22222222-2222-4222-8222-222222222222";
const A:&str="33333333-3333-4333-8333-333333333333";
const TEXT:&str="Synthetic NEW B plaintext after A headers are held";
fn metadata()->Value {
    let mut wrapped=vec![3;12];wrapped.extend(crypto::encrypt_aead(&[9;32],&[7;32],&[3;12],&[]).unwrap());
    json!({"id":B,"user_id":OWNER,"encrypted_chat_key":base64::engine::general_purpose::STANDARD.encode(wrapped),
        "encrypted_title":crypto::encrypt_combined("Synthetic B",&[9;32]).unwrap(),"messages_v":9,"title_v":1,"metadata_v":1})
}
fn fresh_row()->Value {json!({"id":"physical-new-B","chat_id":B,"created_at":10,"role":"user","status":"delivered","encrypted_content":crypto::encrypt_combined(TEXT,&[9;32]).unwrap()})}
struct Server {
    base:String,row:Arc<Mutex<Option<Value>>>,rotate:Arc<std::sync::atomic::AtomicBool>,
    a_started:Option<oneshot::Receiver<()>>,a_release:Arc<tokio::sync::Notify>,
    monitor_started:Arc<tokio::sync::Notify>,monitor_release:Arc<tokio::sync::Notify>,monitor_sockets:Arc<AtomicU64>,monitor_bad_sample:Arc<AtomicBool>,
    stopped:CancellationToken,task:tokio::task::JoinHandle<()>,
    selected_http:Arc<AtomicU64>,expanded_started:Arc<tokio::sync::Notify>,expanded_release:Arc<tokio::sync::Notify>,
}
impl Server {
    async fn open()->Self {
        let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
        let row=Arc::new(Mutex::new(None::<Value>));let(starts,a_started)=oneshot::channel();let starts=Arc::new(Mutex::new(Some(starts)));
        let a_release=Arc::new(tokio::sync::Notify::new());let stopped=CancellationToken::new();let rotate=Arc::new(std::sync::atomic::AtomicBool::new(false));let response_rotate=rotate.clone();
        let monitor_started=Arc::new(tokio::sync::Notify::new());let monitor_release=Arc::new(tokio::sync::Notify::new());let monitor_sockets=Arc::new(AtomicU64::new(0));
        let monitor_bad_sample=Arc::new(AtomicBool::new(false));let bad_sample=monitor_bad_sample.clone();
        let selected_http=Arc::new(AtomicU64::new(0));let selected_requests=selected_http.clone();
        let expanded_started=Arc::new(tokio::sync::Notify::new());let expanded_release=Arc::new(tokio::sync::Notify::new());
        let(expansion_started,expansion_release)=(expanded_started.clone(),expanded_release.clone());
        let phase_started=monitor_started.clone();let phase_release=monitor_release.clone();let sockets=monitor_sockets.clone();
        let(records,release,stop)=(row.clone(),a_release.clone(),stopped.clone());
        let task=tokio::spawn(async move {loop{
            let(stream,_)=tokio::select!{_=stop.cancelled()=>break,value=listener.accept()=>value.unwrap()};
            let(records,release,starts,stop,rotate)=(records.clone(),release.clone(),starts.clone(),stop.clone(),response_rotate.clone());
            let(phase_started,phase_release,sockets,bad_sample)=(phase_started.clone(),phase_release.clone(),sockets.clone(),bad_sample.clone());
            let(selected_requests,expansion_started,expansion_release)=(selected_requests.clone(),expansion_started.clone(),expansion_release.clone());
            tokio::spawn(async move{
                let mut stream=stream;let mut raw=Vec::new();
                loop{let mut bytes=[0;1024];let n=stream.read(&mut bytes).await.unwrap();assert!(n>0);raw.extend_from_slice(&bytes[..n]);
                    if raw.windows(4).any(|p|p==b"\r\n\r\n"){break}assert!(raw.len()<65536);}
                let request=String::from_utf8(raw).unwrap();let path=request.lines().next().unwrap().split_whitespace().nth(1).unwrap();
                if path.starts_with("/v1/ws?"){
                    assert!(!path.contains("chat_metadata_recovery"));sockets.fetch_add(1,Ordering::SeqCst);
                    let key=request.lines().find_map(|line|line.split_once(':').filter(|(key,_)|key.eq_ignore_ascii_case("sec-websocket-key")).map(|(_,v)|v.trim())).unwrap();
                    let accept=tokio_tungstenite::tungstenite::handshake::derive_accept_key(key.as_bytes());
                    stream.write_all(format!("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n").as_bytes()).await.unwrap();
                    let mut ws=tokio_tungstenite::WebSocketStream::from_raw_socket(stream,tokio_tungstenite::tungstenite::protocol::Role::Server,None).await;
                    let first=ws.next().await.unwrap().unwrap();let first:Value=serde_json::from_str(first.to_text().unwrap()).unwrap();assert_eq!(first["type"],"native_client_lifecycle");
                    ws.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":"recovery_outputs_discovery_complete","payload":{"status":"disabled"}}).to_string().into())).await.unwrap();
                    loop{let frame=tokio::select!{_=stop.cancelled()=>break,frame=ws.next()=>frame};let Some(Ok(frame))=frame else{break};if frame.is_close(){break}let Ok(text)=frame.to_text()else{continue};let event:Value=serde_json::from_str(text).unwrap();
                        if event["type"]=="native_client_lifecycle"{continue}
                        if event["type"]=="sync_metadata_chats"{
                            let epoch=event["payload"]["context_epoch"].as_u64().unwrap();expansion_started.notify_one();
                            tokio::select!{_=stop.cancelled()=>break,_=expansion_release.notified()=>{}};
                            ws.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":"sync_metadata_chats_response","payload":{"context_epoch":epoch,"team_id":null,"chats":[],"total_count":101}}).to_string().into())).await.unwrap();continue;
                        }
                        assert_eq!(event["type"],"phased_sync_request");assert_eq!(event["payload"]["phase"],"all");let epoch=event["payload"]["context_epoch"].as_u64().unwrap();assert!(epoch>0);
                        phase_started.notify_one();tokio::select!{_=stop.cancelled()=>break,_=phase_release.notified()=>{}};
                        let mut child=metadata();child["id"]=json!(A);child["parent_id"]=json!(B);child["is_sub_chat"]=json!(true);child["encrypted_chat_key"]=json!(crypto::server_fields::encrypt_bytes(&[8;32],&[7;32],&[]).unwrap());child["encrypted_title"]=json!(crypto::encrypt_combined("Synthetic child metadata",&[8;32]).unwrap());
                        let mut recent_message=fresh_row();if bad_sample.load(Ordering::Acquire){recent_message["encrypted_content"]=json!(crypto::encrypt_combined(TEXT,&[8;32]).unwrap());}
                        let content=json!({"context_epoch":epoch,"team_id":null,"chats":[{"chat_id":B,"messages":[recent_message],"server_message_count":1,"compression_checkpoints":[],"message_window":{"has_more_before":false,"start_cursor":{"created_at":10,"message_id":"physical-new-B"},"oversized_message":false,"oversized_message_cursor":null}}]});
                        for(kind,payload)in [("phase_1_last_chat_ready",json!({"context_epoch":epoch,"team_id":null,"chat_details":metadata()})),("phase_1b_chat_content_ready",content),("phase_2_last_20_chats_ready",json!({"context_epoch":epoch,"team_id":null,"total_chat_count":101,"chats":[{"chat_details":metadata()},{"chat_details":child}]})),("phased_sync_complete",json!({"context_epoch":epoch,"team_id":null}))]{
                            ws.send(tokio_tungstenite::tungstenite::Message::Text(json!({"type":kind,"payload":payload}).to_string().into())).await.unwrap();
                        }
                    }return;
                }
                let value=if path=="/v1/auth/session"{json!({"success":true,"ws_token":"fixture-token","user":{"id":OWNER},"client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]})}
                else{
                    assert!(request.to_lowercase().contains(&format!("x-openmates-expected-principal: {OWNER}")));
                    if path=="/v1/tasks/held-a"{
                        if let Some(sender)=starts.lock().unwrap().take(){sender.send(()).unwrap();}
                        tokio::select!{_=release.notified()=>{},_=stop.cancelled()=>return};json!({"status":"pending"})
                    }else if path.starts_with("/v1/chats/metadata/batch"){selected_requests.fetch_add(1,Ordering::AcqRel);json!({"chats":[metadata()]})}
                    else if path.starts_with(&format!("/v1/chats/{B}/messages/window")){
                        selected_requests.fetch_add(1,Ordering::AcqRel);
                        let row=records.lock().unwrap().as_ref().expect("independent NEW peer write after A started").clone();
                        let cursor=json!({"created_at":10,"message_id":"physical-new-B"});let bytes=serde_json::to_vec(&row).unwrap().len();
                        json!({"chat_id":B,"messages":[row],"messages_v":9,"server_message_count":1,"has_more_before":false,"has_more_after":false,
                            "start_cursor":cursor,"end_cursor":cursor,"anchor_found":true,"payload_bytes":bytes,"oversized_message":false,"oversized_message_cursor":null})
                    }else{panic!("unexpected fixed request route")}
                };
                let body=serde_json::to_vec(&value).unwrap();let cookie=if path.starts_with("/v1/chats/metadata/batch")&&rotate.load(Ordering::Acquire){"set-cookie: auth_refresh_token=synthetic-owned-B-rotation; Path=/\r\n"}else{""};let head=format!("HTTP/1.1 200 OK\r\n{cookie}content-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n",body.len());
                stream.write_all(head.as_bytes()).await.unwrap();stream.write_all(&body).await.unwrap();
            });
        }});
        Self{base,row,rotate,monitor_started,monitor_release,monitor_sockets,monitor_bad_sample,a_started:Some(a_started),a_release,stopped,task,selected_http,expanded_started,expanded_release}
    }
    async fn client(&self)->Client {
        let profile=crate::client::BrowserProfileKey::from_existing_profile(OWNER,Zeroizing::new([7;32]),"synthetic-hash","synthetic-salt",crate::client::BrowserPersistence::MemoryOnly).unwrap();
        let c=Client::restore_browser_credentials_inner(&self.base,"http://localhost:5173",OWNER,profile).await.unwrap();
        assert!(c.session.is_none());assert!(c.browser_credentials.is_some());assert!(!c.is_local_browser_profile());c
    }
}
impl Drop for Server {fn drop(&mut self){self.stopped.cancel();self.task.abort();}}
struct Store {header:Value,rows:BTreeMap<String,Value>,plans:Vec<Value>}
fn store()->Rc<RefCell<Store>> {
    let mut header=metadata();header["chat_id"]=json!(B);header["messages_v"]=json!(7);
    header["encrypted_draft_md"]=json!("protected encrypted local draft");header["unknown_local"]=json!({"retain":true});
    Rc::new(RefCell::new(Store{header,rows:BTreeMap::new(),plans:vec![]}))
}
fn port(store:Rc<RefCell<Store>>)->impl FnOnce(String)->std::future::Ready<Result<String>> {
    move|encoded|{
        assert!(!encoded.contains(TEXT));let plan:Value=serde_json::from_str(&encoded).unwrap();let mut s=store.borrow_mut();s.plans.push(plan.clone());
        let ids=plan["messageIds"].as_array().unwrap();let mut rows=ids.iter().map(|id|s.rows.get(id.as_str().unwrap()).cloned().unwrap_or(Value::Null)).collect::<Vec<_>>();
        let mut before=Value::Null;
        if plan["kind"].as_str().unwrap().starts_with("compare_and_patch"){
            assert_eq!(*projection(&s.header,B,OWNER,true).unwrap(),plan["expectedMetadata"]);before=json!(rows);
            for(i,p)in plan["patches"].as_array().unwrap().iter().enumerate(){
                if let Some(insert)=p.get("insert"){assert!(rows[i].is_null());rows[i]=insert.clone();}
                else{for(k,v)in p["set"].as_object().unwrap(){rows[i][k]=v.clone();}for k in p["remove"].as_array().unwrap(){rows[i].as_object_mut().unwrap().remove(k.as_str().unwrap());}}
                s.rows.insert(ids[i].as_str().unwrap().into(),rows[i].clone());
            }
        }
        std::future::ready(Ok(json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"databaseVersion":1,
            "transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,"metadata":s.header,"rows":rows,"before":before}).to_string()))
    }
}
fn host()->BrowserMetadataCacheScope{serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":0})).unwrap()}
async fn finish(driver:&mut OwnedBrowserReadDriver,c:&mut Client,s:Rc<RefCell<Store>>)->Result<OwnedBrowserReadPublication>{
    for _ in 0..40{match driver.next().await?{
        OwnedBrowserReadStep::Apply(phase)=>phase.apply(c)?,
        OwnedBrowserReadStep::IO(io)=>io.execute(port(s.clone())).await?.apply(c)?,
        OwnedBrowserReadStep::Selected(publication)=>return Ok(publication),
        OwnedBrowserReadStep::Metadata(_)|OwnedBrowserReadStep::Refresh(_)|OwnedBrowserReadStep::RowMetadata(_)=>return Err(Error::Protocol),
    }}Err(Error::Protocol)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,chats.persistence.client-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn new_b_fixed_http_decode_insert_and_full_readback_run_while_same_client_a_headers_remain_held(){
    let mut server=Server::open().await;let mut c=server.client().await;
    let a=Arc::new(OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap());
    let prepared={let mut active=ActiveOwnedClient::enter(&mut c,&a).unwrap();active.prepare_owned_read(OwnedReadRoute::AppTask("held-a")).unwrap()};
    let request=a.request();let a_observer=a.observer();let mut held=Box::pin(transport::send_owned_read_headers(prepared,&request,||a_observer.check_release()));
    let started=server.a_started.take().unwrap();tokio::select!{value=started=>value.unwrap(),_=held.as_mut()=>panic!("A must remain held")};
    // Independent test peer state becomes new only AFTER the actual A GET.
    let fresh=fresh_row();*server.row.lock().unwrap()=Some(fresh.clone());let s=store();
    let mut driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut publication=tokio::time::timeout(Duration::from_secs(10),finish(&mut driver,&mut c,s.clone())).await.unwrap().unwrap();
    let stamp=publication.authenticated_source_stamp(&c).unwrap();assert_eq!(stamp.len(),64);assert_eq!(publication.authenticated_messages_version(&c).unwrap(),Some(9));
    let mut encoded=publication.take(&c,true).unwrap();let value:Value=serde_json::from_str(&encoded).unwrap();assert_eq!(value["chat"]["messages"][0]["content"],TEXT);
    assert_eq!(s.borrow().rows["physical-new-B"]["encrypted_content"],fresh["encrypted_content"]);
    assert_eq!(s.borrow().header["messages_v"],7);assert_eq!(s.borrow().header["unknown_local"],json!({"retain":true}));
    assert_eq!(s.borrow().header["encrypted_draft_md"],"protected encrypted local draft");assert_eq!(value["canonicalIncomingDurablyAcknowledged"],false);assert_eq!(value["historyComplete"],false);
    assert!(s.borrow().plans.iter().filter(|p|p["kind"]=="readback").count()>=2);
    assert!(futures_util::poll!(held.as_mut()).is_pending());
    let pending=publication.into_metadata_continuation(&c).unwrap();assert_eq!(pending.kind(),"cold_metadata");pending.check_original(&c).unwrap();
    // Release is explicit and happens only after all B physical/source oracles.
    server.a_release.notify_one();let _headers=held.await.unwrap();encoded.clear();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn b_source_change_or_root_cancel_after_actual_io_refuses_publication_without_restoring_a(){
    for root in [false,true]{
        let server=Server::open().await;let mut c=server.client().await;*server.row.lock().unwrap()=Some(fresh_row());
        let s=store();
        let mut driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
        let mut changed=false;
        for _ in 0..40{match driver.next().await{
            Ok(OwnedBrowserReadStep::Apply(phase))=>phase.apply(&mut c).unwrap(),
            Ok(OwnedBrowserReadStep::IO(io))=>{
                let phase=io.execute(port(s.clone())).await.unwrap();
                c.insert_chat_row(A.into(),json!({"id":A,"metadata_v":88}));
                if root{c.operation_parent.cancel()}else{c.insert_chat_row(B.into(),metadata());}changed=true;phase.apply(&mut c).unwrap();
            },
            Ok(OwnedBrowserReadStep::Selected(_))=>panic!("stale B must not publish"),
            Ok(OwnedBrowserReadStep::Metadata(_))=>panic!("message read must not publish metadata"),
            Ok(OwnedBrowserReadStep::Refresh(_)|OwnedBrowserReadStep::RowMetadata(_))=>panic!("cold message read must not publish hint continuation steps"),
            Err(_)=>break,
        }}assert!(changed);assert_eq!(c.chats[A]["metadata_v"],88);
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,chats.persistence.client-encrypted
#[tokio::test]
async fn a_changes_during_b_io_do_not_hold_client_borrow_or_retire_b_and_selected_is_once_only(){
    let server=Server::open().await;let mut c=server.client().await;*server.row.lock().unwrap()=Some(fresh_row());
    let s=store();
    let mut driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut selected=None;
    for _ in 0..40{match driver.next().await.unwrap(){
        OwnedBrowserReadStep::Apply(phase)=>phase.apply(&mut c).unwrap(),
        OwnedBrowserReadStep::IO(io)=>{
            let (release,wait)=oneshot::channel();let storage=s.clone();let mut future=Box::pin(io.execute(move|plan|async move{wait.await.unwrap();port(storage)(plan).await}));
            // The actual IO future is started, then the SAME Client remains mutable.
            assert!(futures_util::poll!(future.as_mut()).is_pending());
            c.insert_chat_row(A.into(),json!({"id":A,"metadata_v":99}));release.send(()).unwrap();future.await.unwrap().apply(&mut c).unwrap();
        },
        OwnedBrowserReadStep::Selected(publication)=>{selected=Some(publication);break},
        OwnedBrowserReadStep::Metadata(_)=>panic!("message read must not publish metadata"),
        OwnedBrowserReadStep::Refresh(_)|OwnedBrowserReadStep::RowMetadata(_)=>panic!("cold message read must not publish hint continuation steps"),
    }}let mut selected=selected.unwrap();let _json=selected.take(&c,true).unwrap();assert!(selected.take(&c,true).is_err());
    assert_eq!(c.chats[A]["metadata_v"],99);selected.into_metadata_continuation(&c).unwrap().check_original(&c).unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn foreign_real_client_cannot_apply_original_phase_or_receive_its_selected_plaintext(){
    let server=Server::open().await;let mut original=server.client().await;let mut foreign=server.client().await;
    *server.row.lock().unwrap()=Some(fresh_row());
    let mut driver=original.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let OwnedBrowserReadStep::Apply(phase)=driver.next().await.unwrap()else{panic!("first actual Client phase")};
    phase.apply(&mut foreign).unwrap();assert!(driver.next().await.is_err());
    let foreign_scope=OwnedOperationScope::capture(&foreign,CancellationToken::new()).unwrap();foreign_scope.check(&foreign).unwrap();
    let s=store();
    let mut driver=original.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut selected=finish(&mut driver,&mut original,s).await.unwrap();assert!(selected.take(&foreign,true).is_err());
    foreign_scope.check(&foreign).unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn abandoned_original_phase_retires_its_exact_slot_without_canceling_same_parent_sibling(){
    let server=Server::open().await;let mut c=server.client().await;
    
    let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();
    let mut driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let OwnedBrowserReadStep::Apply(phase)=driver.next().await.unwrap()else{panic!("actual first phase")};
    drop(phase);assert_eq!(driver.context.outstanding.load(Ordering::Acquire),0);
    assert!(driver.next().await.is_err());sibling.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn independent_original_b_metadata_floors_refuse_stale_source_before_storage(){
    // Existing metadata_v takes precedence; only absent/zero metadata_v uses
    // title_v fallback. A message COUNT rewind is not this stale-clock case.
    for(metadata_v,title_v)in [(2,1),(0,2)]{
        let server=Server::open().await;let mut c=server.client().await;*server.row.lock().unwrap()=Some(fresh_row());
        let mut original=metadata();original["metadata_v"]=json!(metadata_v);original["title_v"]=json!(title_v);c.insert_chat_row(B.into(),original);
        let s=store();let mut driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
        assert!(matches!(finish(&mut driver,&mut c,s.clone()).await,Err(Error::Offline)));assert!(s.borrow().plans.is_empty());
        assert_eq!(c.chats[B]["metadata_v"],metadata_v);assert_eq!(c.chats[B]["title_v"],title_v);
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn selected_incoming_view_keeps_exact_unhandled_hint_owned_without_retry_spin_or_foreign_requeue(){
    const LATER:&str="44444444-4444-4444-8444-444444444444";
    let server=Server::open().await;let mut c=server.client().await;*server.row.lock().unwrap()=Some(fresh_row());
    let monitor=Arc::new(c.retain_browser_monitor_for_test().unwrap());c.browser_owned_hint_for_test(&monitor,&[A,B],&[]).unwrap();
    let s=store();let mut driver=c.begin_owned_browser_incoming_message_read(monitor.clone(),CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut selected=finish(&mut driver,&mut c,s).await.unwrap();drop(driver);
    let _json=selected.take(&c,true).unwrap();assert!(!c.browser_owned_pending_for_test(&monitor).unwrap().0);
    let pending=selected.into_metadata_continuation(&c).unwrap();assert_eq!(pending.kind(),"original_hint_metadata");
    assert!(!c.browser_owned_pending_for_test(&monitor).unwrap().0);
    // A later real queue update stays independent of the consumed original work.
    c.browser_owned_hint_for_test(&monitor,&[LATER],&[]).unwrap();
    let foreign=Arc::new(c.retain_browser_monitor_for_test().unwrap());
    pending.cancel();tokio::time::timeout(Duration::from_secs(10),pending.wait_cancelled()).await.unwrap();drop(pending);
    let(refresh,chats,recovery)=c.browser_owned_pending_for_test(&monitor).unwrap();assert!(refresh);assert!(recovery.is_empty());
    assert_eq!(chats,vec![B.to_string(),A.to_string(),LATER.to_string()]);
    assert!(!c.browser_owned_pending_for_test(&foreign).unwrap().0);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn incoming_requires_actual_pending_hint_and_never_treats_recovery_offer_as_cache_permission(){
    let server=Server::open().await;let mut c=server.client().await;let monitor=Arc::new(c.retain_browser_monitor_for_test().unwrap());
    assert!(c.begin_owned_browser_incoming_message_read(monitor.clone(),CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).is_err());
    c.browser_owned_hint_for_test(&monitor,&[B],&[A]).unwrap();
    assert!(c.begin_owned_browser_incoming_message_read(monitor.clone(),CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).is_err());
    let(refresh,chats,recovery)=c.browser_owned_pending_for_test(&monitor).unwrap();assert!(refresh);assert_eq!(chats,vec![B.to_string()]);assert_eq!(recovery,vec![A.to_string()]);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn cold_finishes_only_after_selected_take_without_monitor_or_metadata_ack(){
    let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;
    let original=store();let mut read=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut publication=finish(&mut read,&mut c,original.clone()).await.unwrap();
    assert_eq!(original.borrow().header["messages_v"],7);
    let encoded=publication.take(&c,true).unwrap();assert!(encoded.contains(TEXT));
    publication.finish_cold(&c).unwrap();assert!(c.monitor_cancel.is_none());
    assert_eq!(original.borrow().header["messages_v"],7);
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn original_hint_metadata_floor_refuses_stale_response_before_key_or_storage_and_requeues_exact_hint(){
    let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;
    let monitor=Arc::new(c.retain_browser_monitor_for_test().unwrap());
    c.browser_owned_hint_for_test(&monitor,&[B],&[]).unwrap();c.browser_owned_floor_for_test(&monitor,B,2,0).unwrap();
    let mut read=c.begin_owned_browser_incoming_message_read(monitor.clone(),CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let physical=store();assert!(matches!(finish(&mut read,&mut c,physical.clone()).await,Err(Error::Offline)));
    assert!(physical.borrow().plans.is_empty());drop(read);
    assert_eq!(c.browser_owned_pending_for_test(&monitor).unwrap().1,vec![B.to_string()]);
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn authenticated_message_count_rewind_and_maintained_metadata_fallback_keep_real_row_cas(){
    for(metadata_v,title_v,nested)in [(1,99,false),(0,1,false),(0,99,true)]{
        let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;
        let mut original=metadata();original["messages_v"]=json!(10);original["metadata_v"]=json!(metadata_v);original["title_v"]=json!(title_v);original["draft_v"]=json!(99);if nested{original["versions"]=json!({"metadata_v":1});}
        c.insert_chat_row(B.into(),original);let physical=store();let mut read=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
        let mut publication=finish(&mut read,&mut c,physical.clone()).await.unwrap();
        assert_eq!(publication.authenticated_messages_version(&c).unwrap(),Some(9));
        let encoded=publication.take(&c,true).unwrap();let output:Value=serde_json::from_str(&encoded).unwrap();
        assert_eq!(output["chat"]["messages"][0]["content"],TEXT);assert_eq!(output["messagesVersionAdvanced"],false);
        assert_eq!(physical.borrow().header["messages_v"],7);assert_eq!(c.chats[B]["messages_v"],10);
        assert!(physical.borrow().plans.iter().any(|p|p["kind"]=="compare_and_patch_cold_incoming_insert"));
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_received_headers_retain_matched_cookies_after_local_negative_before_enqueue_and_refuse_foreign_client(){
    for foreign in [false,true]{
        let server=Server::open().await;let mut original=server.client().await;let mut other=server.client().await;server.rotate.store(true,Ordering::Release);
        let driver=original.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
        let context=driver.context.clone();
        let prepared={let mut actual=ActiveOwnedClient::enter(&mut original,&context.scope).unwrap();
            actual.prepare_owned_read(OwnedReadRoute::ChatMetadata{chat_id:B,include_read_details:true}).unwrap()};
        let request=context.scope.request();
        let headers=transport::send_owned_read_headers(prepared,&request,||context.negative()).await.unwrap();
        // The response, including real SetCookie, is actually received first.
        // Negativity then occurs before the Channel can enqueue its apply.
        driver.cancel();assert!(context.negative().is_err());
        let(send,mut pending)=mpsc::unbounded_channel();let channel=Channel{context:context.clone(),drain:driver.drain.clone(),send};
        let applied=channel.apply(Work::Headers(headers));tokio::pin!(applied);
        assert!(futures_util::poll!(applied.as_mut()).is_pending());
        let phase=OwnedBrowserReadPhase{pending:pending.recv().await.unwrap()};
        if foreign{phase.apply(&mut other).unwrap();}else{phase.apply(&mut original).unwrap();}
        // Header merge cannot turn the revoked operation into body/key/IO/view
        // authority. A different genuine Client never receives these cookies.
        assert!(applied.await.is_err());assert!(!other.cookies.contains_key("auth_refresh_token"));
        if foreign{assert!(!original.cookies.contains_key("auth_refresh_token"));}
        else{assert_eq!(original.cookies.get("auth_refresh_token").map(String::as_str),Some("synthetic-owned-B-rotation"));}
        assert_eq!(context.outstanding.load(Ordering::Acquire),0);
    }
}

fn metadata_port(store:Rc<RefCell<Store>>)->impl FnOnce(String)->std::future::Ready<Result<String>> {
    move|encoded|{
        let plan:Value=serde_json::from_str(&encoded).unwrap();assert_eq!(plan["store"],"chats");assert!(!encoded.contains(TEXT));
        let mut s=store.borrow_mut();s.plans.push(plan.clone());let mut before=Value::Null;
        if plan["kind"]=="compare_and_patch"{
            assert_eq!(*super::super::super::projection(&s.header,B,OWNER,true).unwrap(),plan["expected"]);
            before=s.header.clone();for(field,value)in plan["patch"].as_object().unwrap(){s.header[field]=value.clone();}
        }
        let result=json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"databaseVersion":1,
            "transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,
            "record":s.header,"before":before});std::future::ready(Ok(result.to_string()))
    }
}
async fn finish_metadata(driver:&mut OwnedBrowserReadDriver,c:&mut Client,s:Rc<RefCell<Store>>)->Result<OwnedBrowserMetadataPublication>{
    for _ in 0..30{match driver.next().await?{
        OwnedBrowserReadStep::Apply(phase)=>phase.apply(c)?,
        OwnedBrowserReadStep::IO(io)=>io.execute(metadata_port(s.clone())).await?.apply(c)?,
        OwnedBrowserReadStep::Metadata(publication)=>return Ok(publication),
        OwnedBrowserReadStep::Selected(_)|OwnedBrowserReadStep::Refresh(_)|OwnedBrowserReadStep::RowMetadata(_)=>return Err(Error::Protocol),
    }}Err(Error::Protocol)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn exact_original_metadata_continuation_preserves_local_draft_extension_count_and_unhandled_hint(){
    let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;
    let monitor=Arc::new(c.retain_browser_monitor_for_test().unwrap());c.browser_owned_hint_for_test(&monitor,&[B,A],&[]).unwrap();
    let physical=store();let old_client_stamp=source_stamp(&c,B).unwrap();
    let mut selected=c.begin_owned_browser_incoming_message_read(monitor.clone(),CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut publication=finish(&mut selected,&mut c,physical.clone()).await.unwrap();drop(selected);
    let expected_title=publication.context.source_metadata.lock().unwrap().as_ref().unwrap()["encrypted_title"].clone();
    publication.take(&c,true).unwrap();let continuation=publication.into_metadata_continuation(&c).unwrap();
    let mut metadata=continuation.begin_metadata(&c).unwrap();
    let mut publication=finish_metadata(&mut metadata,&mut c,physical.clone()).await.unwrap();drop(metadata);
    let encoded=publication.take(&c,true).unwrap();let output:Value=serde_json::from_str(&encoded).unwrap();
    assert_eq!(output["pendingWork"],"original_hint_remainder");assert_eq!(output["metadataRowsPersisted"],1);
    for flag in ["draftsPersisted","inventoryComplete","messagesVersionAdvanced","nativeDurabilityAcknowledged","recoveryProof"]{assert_eq!(output[flag],false);}
    let remainder=publication.into_remainder(&c).unwrap();assert_eq!(remainder.kind(),"original_hint_remainder");
    assert_eq!(source_stamp(&c,B).unwrap(),old_client_stamp);assert_eq!(physical.borrow().header["messages_v"],7);
    assert_eq!(physical.borrow().header["encrypted_title"],expected_title);
    assert_eq!(physical.borrow().header["encrypted_draft_md"],"protected encrypted local draft");assert_eq!(physical.borrow().header["unknown_local"],json!({"retain":true}));
    assert_eq!(physical.borrow().plans.iter().filter(|p|p["kind"]=="compare_and_patch").count(),1);
    assert!(!c.browser_owned_pending_for_test(&monitor).unwrap().0);
    remainder.cancel();remainder.wait_cancelled().await;drop(remainder);
    let(refresh,chats,recovery)=c.browser_owned_pending_for_test(&monitor).unwrap();assert!(refresh);assert_eq!(chats,vec![B.to_string(),A.to_string()]);assert!(recovery.is_empty());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn metadata_continuation_refuses_concurrent_exact_row_change_before_commit_or_final_release(){
    for at_release in [false,true]{
        let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;
        let monitor=Arc::new(c.retain_browser_monitor_for_test().unwrap());c.browser_owned_hint_for_test(&monitor,&[B],&[]).unwrap();
        let physical=store();let mut selected=c.begin_owned_browser_incoming_message_read(monitor,CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
        let mut view=finish(&mut selected,&mut c,physical.clone()).await.unwrap();drop(selected);view.take(&c,true).unwrap();
        let continuation=view.into_metadata_continuation(&c).unwrap();let mut driver=continuation.begin_metadata(&c).unwrap();
        if !at_release{physical.borrow_mut().header["unknown_local"]=json!({"newer":true});
            assert!(matches!(finish_metadata(&mut driver,&mut c,physical.clone()).await,Err(Error::Conflict)));
            assert!(!physical.borrow().plans.iter().any(|p|p["kind"]=="compare_and_patch"));
        }else{let mut output=finish_metadata(&mut driver,&mut c,physical.clone()).await.unwrap();c.operation_parent.cancel();assert!(output.take(&c,true).is_err());}
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn original_dispatch_control_checks_exact_b_row_and_foreign_client_without_regranting_or_canceling_sibling(){
    let server=Server::open().await;let mut original=server.client().await;let foreign=server.client().await;
    let driver=original.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let control=driver.control();let sibling=OwnedOperationScope::capture(&original,CancellationToken::new()).unwrap();
    control.ensure_current(&original).unwrap();assert!(control.ensure_current(&foreign).is_err());
    original.insert_chat_row(A.into(),json!({"id":A,"user_id":OWNER}));control.ensure_current(&original).unwrap();
    control.cancel();assert!(control.ensure_current(&original).is_err());sibling.check(&original).unwrap();
    assert!(!original.operation_parent.is_cancelled());
    let later=original.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let original_b=later.control();original.insert_chat_row(B.into(),metadata());assert!(original_b.ensure_current(&original).is_err());
    sibling.check(&original).unwrap();
}

fn original_metadata_job()->crate::client::CompletionRecoveryJob{
    crate::client::CompletionRecoveryJob{kind:crate::client::CompletionRecoveryKind::Metadata,
        job_id:"55555555-5555-4555-8555-555555555555".into(),chat_id:B.into(),turn_id:None,assistant_message_id:None,
        task_id:Some("66666666-6666-4666-8666-666666666666".into()),stage:Some("initial".into()),chat_key_version:1,created_at:None}
}
async fn original_hint_remainder(server:&Server)->(Client,Arc<ChatMonitor>,OwnedBrowserMetadataContinuation){
    *server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;
    let monitor=Arc::new(c.retain_browser_monitor_for_test().unwrap());let job=original_metadata_job();
    c.browser_owned_job_hint_for_test(&monitor,true,&job.job_id,B).unwrap();
    // Existing selected-only API keeps its original recovery-pending refusal.
    assert!(c.begin_owned_browser_incoming_message_read(monitor.clone(),CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).is_err());
    let physical=store();let mut selected=c.begin_owned_browser_original_hint_read(monitor.clone(),CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut view=finish(&mut selected,&mut c,physical.clone()).await.unwrap();drop(selected);view.take(&c,true).unwrap();
    let mut metadata=view.into_metadata_continuation(&c).unwrap().begin_metadata(&c).unwrap();
    let mut result=finish_metadata(&mut metadata,&mut c,physical).await.unwrap();drop(metadata);result.take(&c,true).unwrap();
    let remainder=result.into_remainder(&c).unwrap();(c,monitor,remainder)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn whole_original_hint_retains_recovery_and_mints_handoff_only_for_exact_captured_job_without_foreground_grant(){
    let server=Server::open().await;let(c,monitor,remainder)=original_hint_remainder(&server).await;let job=original_metadata_job();
    assert!(c.completion_recovery_mode.is_none());let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();
    let handoff=remainder.recovery_handoff(&c,&job).unwrap();assert!(Arc::ptr_eq(&handoff.scope_arc(),&remainder.context.scope));handoff.check_before_io(&c).unwrap();
    assert_eq!(handoff.job().job_id,job.job_id);assert_eq!(handoff.selected_chat(),B);assert!(handoff.before_row().is_none());
    assert!(remainder.recovery_handoff(&c,&job).is_err());let mut wrong=job.clone();wrong.job_id="77777777-7777-4777-8777-777777777777".into();assert!(remainder.recovery_handoff(&c,&wrong).is_err());
    wrong=job;wrong.kind=crate::client::CompletionRecoveryKind::Main;assert!(remainder.recovery_handoff(&c,&wrong).is_err());
    assert!(c.completion_recovery_mode.is_none());assert!(!c.browser_owned_pending_for_test(&monitor).unwrap().0);
    handoff.scope_arc().observer().cancel();assert!(handoff.check_root(&c).is_err());sibling.check(&c).unwrap();drop(handoff);drop(remainder);
    assert_eq!(c.browser_owned_pending_for_test(&monitor).unwrap().2,vec![B.to_string()]);assert!(!c.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn handoff_root_check_cannot_replace_selected_row_guard_or_adopt_arbitrary_foreign_or_changed_state(){
    let server=Server::open().await;let(mut c,_monitor,remainder)=original_hint_remainder(&server).await;let handoff=remainder.recovery_handoff(&c,&original_metadata_job()).unwrap();
    let foreign=server.client().await;assert!(handoff.check_before_io(&foreign).is_err());assert!(handoff.check_root(&foreign).is_err());
    c.insert_chat_row(B.into(),metadata());assert!(handoff.check_before_io(&c).is_err());
    // Root-only checking is a restricted seam for the genuine driver-witnessed
    // mutation; it grants no selected output or source-anchor adoption.
    handoff.check_root(&c).unwrap();assert!(remainder.check_original(&c).is_err());
    c.operation_parent.cancel();assert!(handoff.negative().is_err());handoff.cancelled().await;
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn cloned_original_handoff_cannot_prepare_two_actual_core_attempts_or_reopen_after_abandonment(){
    let server=Server::open().await;let(c,_monitor,remainder)=original_hint_remainder(&server).await;
    let original=remainder.recovery_handoff(&c,&original_metadata_job()).unwrap();let cloned=original.clone();
    original.claim_core_driver(&c).unwrap();original.check_before_io(&c).unwrap();drop(original);
    // Still-live original root/scope demonstrates this is an actual one-use
    // admission refusal, not incidental parent cancellation or server lease.
    cloned.check_root(&c).unwrap();assert!(matches!(cloned.claim_core_driver(&c),Err(Error::Conflict)));
    assert!(remainder.recovery_handoff(&c,&original_metadata_job()).is_err());assert!(!c.operation_parent.is_cancelled());
}
async fn actual_io_phase(driver:&mut OwnedBrowserReadDriver,c:&mut Client)->OwnedBrowserReadIO{
    for _ in 0..40{match driver.next().await.unwrap(){
        OwnedBrowserReadStep::Apply(phase)=>phase.apply(c).unwrap(),
        OwnedBrowserReadStep::IO(io)=>return io,
        _=>panic!("actual first native IO phase required"),
    }}panic!("bounded native phase limit")
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn cancel_before_first_poll_is_not_terminal_until_original_future_actually_returns(){
    let server=Server::open().await;let mut c=server.client().await;
    let mut driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();let observer=driver.terminal_observer();
    assert!(observer.terminal().is_none());driver.cancel();assert!(observer.terminal().is_none());
    assert!(driver.next().await.is_err());let terminal=observer.terminal().expect("actual original future returned with no IO");assert!(terminal.is_quiescent());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn nonterminal_conflict_and_dropped_pending_phase_never_imply_actual_future_return(){
    let server=Server::open().await;let mut c=server.client().await;let mut driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let observer=driver.terminal_observer();let OwnedBrowserReadStep::Apply(phase)=driver.next().await.unwrap()else{panic!("actual pending apply")};
    assert!(matches!(driver.next().await,Err(Error::Conflict)));assert!(observer.terminal().is_none());
    drop(phase);assert!(observer.terminal().is_none());assert!(driver.next().await.is_err());assert!(observer.terminal().unwrap().is_quiescent());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn held_actual_io_callback_must_settle_then_original_apply_and_future_return_before_terminal(){
    let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;let mut driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let observer=driver.terminal_observer();let io=actual_io_phase(&mut driver,&mut c).await;let physical=store();let(release,receive)=oneshot::channel::<()>();
    let executing=io.execute(move|encoded|async move{receive.await.map_err(|_|Error::Cancelled)?;port(physical)(encoded).await});tokio::pin!(executing);
    assert!(futures_util::poll!(executing.as_mut()).is_pending());driver.cancel();assert!(observer.terminal().is_none());assert!(matches!(driver.next().await,Err(Error::Conflict)));assert!(observer.terminal().is_none());
    release.send(()).unwrap();let phase=executing.await.unwrap();assert!(observer.terminal().is_none());phase.apply(&mut c).unwrap();assert!(observer.terminal().is_none());
    assert!(driver.next().await.is_err());assert!(observer.terminal().unwrap().is_quiescent());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn dropping_started_io_await_cannot_forge_terminal_even_when_future_rejects_and_slots_are_empty(){
    let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;let mut driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let observer=driver.terminal_observer();let io=actual_io_phase(&mut driver,&mut c).await;let(_release,receive)=oneshot::channel::<()>();
    {let executing=io.execute(move|_encoded|async move{receive.await.map_err(|_|Error::Cancelled)?;Err(Error::Offline)});tokio::pin!(executing);assert!(futures_util::poll!(executing.as_mut()).is_pending());}
    assert!(driver.next().await.is_err());assert!(driver.finished);assert_eq!(driver.context.outstanding.load(Ordering::Acquire),0);
    assert!(observer.terminal().is_none());
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_original_monitor_refresh_waits_without_client_loan_and_dispatches_independent_exact_row_seeds(){
    let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;
    let(errors,_received)=mpsc::channel(4);let monitor=Arc::new(c.start_chat_monitor(CancellationToken::new(),errors).await.unwrap());
    let physical=store();let mut selected=c.begin_owned_browser_original_hint_read(monitor.clone(),CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut view=finish(&mut selected,&mut c,physical.clone()).await.unwrap();drop(selected);view.take(&c,true).unwrap();
    let mut metadata=view.into_metadata_continuation(&c).unwrap().begin_metadata(&c).unwrap();let mut result=finish_metadata(&mut metadata,&mut c,physical.clone()).await.unwrap();drop(metadata);result.take(&c,true).unwrap();
    let remainder=result.into_remainder(&c).unwrap();let OriginalHintRefreshAdmission::Driven(mut refresh)=remainder.begin_original_refresh(&c).unwrap()else{panic!("actual initial refresh required")};
    let OwnedBrowserReadStep::Apply(prepare)=refresh.next().await.unwrap()else{panic!("actual prepare phase")};prepare.apply(&mut c).unwrap();
    let next={let waiting=refresh.next();tokio::pin!(waiting);assert!(futures_util::poll!(waiting.as_mut()).is_pending());server.monitor_started.notified().await;
        // Only the native driver/ticket is borrowed across actual socket await.
        c.insert_chat_row(A.into(),json!({"id":A,"user_id":OWNER,"metadata_v":1}));server.monitor_release.notify_one();waiting.await.unwrap()};
    let OwnedBrowserReadStep::Apply(take)=next else{panic!("actual original receipt take")};take.apply(&mut c).unwrap();
    let OwnedBrowserReadStep::Refresh(mut batch)=refresh.next().await.unwrap()else{panic!("actual opaque received batch")};
    assert_eq!(server.monitor_sockets.load(Ordering::SeqCst),1);batch.ensure_current(&c).unwrap();
    let b=batch.next_row(&c).unwrap().unwrap();let a=batch.next_row(&c).unwrap().unwrap();assert_eq!(b.chat_id(),B);assert_eq!(a.chat_id(),A);assert!(!a.is_personal_draft_data());
    b.ensure_current(&c).unwrap();a.ensure_current(&c).unwrap();c.chats.get_mut(A).unwrap()["metadata_v"]=json!(2);
    assert!(a.ensure_current(&c).is_err());b.ensure_current(&c).unwrap();assert!(batch.next_row(&c).unwrap().is_none());
    // Empty metadata dispatch queue is not physical row/Phase1/draft/sidecar or
    // whole-hint completion; no API consumes the actual original hint here.
    assert_eq!(physical.borrow().header["messages_v"],7);batch.cancel();batch.wait_cancelled().await;monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn recovery_only_original_hint_does_not_invent_recent_refresh_or_release_its_owned_remainder(){
    let server=Server::open().await;let(c,monitor,remainder)=original_hint_remainder(&server).await;
    let OriginalHintRefreshAdmission::NotRequired(remainder)=remainder.begin_original_refresh(&c).unwrap()else{panic!("no original refresh bit")};
    remainder.check_original(&c).unwrap();assert_eq!(server.monitor_sockets.load(Ordering::SeqCst),0);
    let handoff=remainder.recovery_handoff(&c,&original_metadata_job()).unwrap();handoff.check_before_io(&c).unwrap();assert_eq!(remainder.kind(),"original_hint_remainder");monitor.close();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn recovery_additional_negative_observer_never_reinvokes_application_gate_and_still_refuses_original_monitor_or_parent(){
    for close_monitor in [false,true]{
        let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;
        let calls=Arc::new(AtomicU64::new(0));let count=calls.clone();let refusing=Arc::new(AtomicBool::new(false));let gate_refusing=refusing.clone();
        c.set_private_operation_gate(Some(Arc::new(move||{count.fetch_add(1,Ordering::SeqCst);if gate_refusing.load(Ordering::Acquire){Err(Error::Forbidden)}else{Ok(())}})));
        let monitor=Arc::new(c.retain_browser_monitor_for_test().unwrap());let job=original_metadata_job();c.browser_owned_job_hint_for_test(&monitor,true,&job.job_id,B).unwrap();
        let physical=store();let mut selected=c.begin_owned_browser_original_hint_read(monitor.clone(),CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
        let mut view=finish(&mut selected,&mut c,physical.clone()).await.unwrap();drop(selected);view.take(&c,true).unwrap();
        let mut metadata=view.into_metadata_continuation(&c).unwrap().begin_metadata(&c).unwrap();let mut result=finish_metadata(&mut metadata,&mut c,physical).await.unwrap();drop(metadata);result.take(&c,true).unwrap();
        let remainder=result.into_remainder(&c).unwrap();let handoff=remainder.recovery_handoff(&c,&job).unwrap();
        refusing.store(true,Ordering::Release);let before=calls.load(Ordering::SeqCst);
        handoff.check_original_negative().unwrap();assert_eq!(calls.load(Ordering::SeqCst),before);
        assert!(handoff.negative().is_err());assert!(calls.load(Ordering::SeqCst)>before);
        let before=calls.load(Ordering::SeqCst);if close_monitor{monitor.close()}else{c.operation_parent.cancel()}
        assert!(handoff.check_original_negative().is_err());assert_eq!(calls.load(Ordering::SeqCst),before);
    }
}

async fn actual_refresh_batch_for_windows(server:&Server)->(Client,Arc<ChatMonitor>,OriginalHintRefreshBatch){actual_refresh_batch_with_gate(server,None).await}
async fn actual_refresh_batch_with_gate(server:&Server,gate:Option<Arc<dyn Fn()->Result<()>+Send+Sync>>)->(Client,Arc<ChatMonitor>,OriginalHintRefreshBatch){
    *server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;c.set_private_operation_gate(gate);let(errors,_received)=mpsc::channel(4);
    let monitor=Arc::new(c.start_chat_monitor(CancellationToken::new(),errors).await.unwrap());let physical=store();
    let mut selected=c.begin_owned_browser_original_hint_read(monitor.clone(),CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut view=finish(&mut selected,&mut c,physical.clone()).await.unwrap();drop(selected);view.take(&c,true).unwrap();
    let mut metadata=view.into_metadata_continuation(&c).unwrap().begin_metadata(&c).unwrap();let mut result=finish_metadata(&mut metadata,&mut c,physical).await.unwrap();drop(metadata);result.take(&c,true).unwrap();
    let OriginalHintRefreshAdmission::Driven(mut refresh)=result.into_remainder(&c).unwrap().begin_original_refresh(&c).unwrap()else{panic!("actual original refresh")};
    let OwnedBrowserReadStep::Apply(prepare)=refresh.next().await.unwrap()else{panic!("actual original prepare")};prepare.apply(&mut c).unwrap();
    let next={let waiting=refresh.next();tokio::pin!(waiting);assert!(futures_util::poll!(waiting.as_mut()).is_pending());server.monitor_started.notified().await;server.monitor_release.notify_one();waiting.await.unwrap()};
    let OwnedBrowserReadStep::Apply(take)=next else{panic!("actual receipt")};take.apply(&mut c).unwrap();
    let OwnedBrowserReadStep::Refresh(batch)=refresh.next().await.unwrap()else{panic!("actual batch")};(c,monitor,batch)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn genuine_original_startup_windows_use_shared_crypto_budget_and_child_metadata_without_borrowing_client_or_claiming_store(){
    let server=Server::open().await;let(mut c,monitor,batch)=actual_refresh_batch_for_windows(&server).await;let before_history=c.history.clone();
    assert!(c.session.is_none());let prepared=batch.prepare_windows(&c).unwrap();
    // Preparation/drive own no Client lifetime; unrelated child's metadata can
    // change while platform crypto is held by a genuine browser implementation.
    c.insert_chat_row(A.into(),json!({"id":A,"metadata_v":1,"is_sub_chat":true,"parent_id":B}));
    let completed=prepared.drive().await.unwrap();let mut retained=completed.finish(&c).unwrap();
    retained.ensure_current(&c).unwrap();assert_eq!(retained.kind(),"original_hint_windows_pending_physical_store");
    let windows=serde_json::to_value(&retained.windows).unwrap();assert_eq!(windows.as_object().unwrap().len(),1);
    assert_eq!(windows[B]["messages"].as_array().unwrap().len(),1);assert_eq!(windows[B]["server_message_count"],1);assert_eq!(windows[B]["metadata_messages_v"],9);
    assert!(!windows.to_string().contains(TEXT));assert!(!windows[B].get("history_complete").is_some_and(|v|v==true));
    assert!(retained.windows.get(A).is_none());assert_eq!(c.history,before_history);assert!(c.sync_message_windows.is_empty());
    assert_eq!(retained.next_row(&c).unwrap().unwrap().chat_id(),B);assert_eq!(retained.next_row(&c).unwrap().unwrap().chat_id(),A);
    assert_eq!(server.monitor_sockets.load(Ordering::SeqCst),1);retained.cancel();monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn original_startup_window_crypto_cannot_accept_changed_target_row_or_revoked_parent_after_real_unwrap(){
    for revoke in [false,true]{let server=Server::open().await;let(mut c,monitor,batch)=actual_refresh_batch_for_windows(&server).await;
        let completed=batch.prepare_windows(&c).unwrap().drive().await.unwrap();
        if revoke{c.operation_parent.cancel()}else{c.insert_chat_row(B.into(),metadata());}
        assert!(completed.finish(&c).is_err());assert!(c.sync_message_windows.is_empty());monitor.close();
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_correlated_startup_bad_sample_defers_content_without_losing_metadata_or_inventing_history(){
    let server=Server::open().await;server.monitor_bad_sample.store(true,Ordering::Release);let(c,monitor,batch)=actual_refresh_batch_for_windows(&server).await;
    let mut retained=batch.prepare_windows(&c).unwrap().drive().await.unwrap().finish(&c).unwrap();
    assert!(retained.windows.is_empty());assert_eq!(retained.next_row(&c).unwrap().unwrap().chat_id(),B);assert_eq!(retained.next_row(&c).unwrap().unwrap().chat_id(),A);
    assert!(c.history.is_empty());assert!(c.sync_message_windows.is_empty());assert_eq!(retained.kind(),"original_hint_windows_pending_physical_store");monitor.close();
}

fn row_metadata_io(store:Rc<RefCell<Store>>)->impl FnOnce(String)->std::future::Ready<Result<String>> {
    move|encoded|{let plan:Value=serde_json::from_str(&encoded).unwrap();assert!(!encoded.contains(TEXT));let id=plan["chatId"].as_str().unwrap();let mut s=store.borrow_mut();s.plans.push(plan.clone());let mut before=Value::Null;
        if plan.get("store").is_some(){
            assert_eq!(plan["store"],"chats");
            if plan["kind"]=="compare_and_patch"{assert_eq!(*super::super::super::projection(&s.header,id,OWNER,true).unwrap(),plan["expected"]);before=s.header.clone();for(k,v)in plan["patch"].as_object().unwrap(){s.header[k]=v.clone();}}
            std::future::ready(Ok(json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"databaseVersion":1,"transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,"record":s.header,"before":before}).to_string()))
        }else{
            assert!(plan["messageIds"].as_array().unwrap().is_empty(),"metadata-only row cannot eager-fetch child history");
            if plan["kind"]=="compare_and_patch_cold_incoming_insert"{
                before=json!([]);if s.header.is_null(){assert!(plan["expectedMetadata"].is_null());s.header=plan["metadataInsert"].clone();}
                else{assert_eq!(*projection(&s.header,id,OWNER,true).unwrap(),plan["expectedMetadata"]);}
                assert!(plan["patches"].as_array().unwrap().is_empty());
            }
            std::future::ready(Ok(json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"databaseVersion":1,"transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,"metadata":s.header,"rows":[],"before":before}).to_string()))
        }
    }
}
async fn finish_row_metadata(driver:&mut OwnedBrowserReadDriver,c:&mut Client,physical:Rc<RefCell<Store>>)->Result<OriginalHintRowMetadataPublication>{
    for _ in 0..60{match driver.next().await?{
        OwnedBrowserReadStep::Apply(phase)=>phase.apply(c)?,OwnedBrowserReadStep::IO(io)=>io.execute(row_metadata_io(physical.clone())).await?.apply(c)?,
        OwnedBrowserReadStep::RowMetadata(row)=>return Ok(row),_=>return Err(Error::Protocol),
    }}Err(Error::Protocol)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_child_row_seed_bootstraps_absent_header_then_shared_metadata_cas_readback_without_eager_messages_or_hint_ack(){
    let server=Server::open().await;let(mut c,monitor,mut batch)=actual_refresh_batch_for_windows(&server).await;
    let _parent=batch.next_row(&c).unwrap().unwrap();let child=batch.next_row(&c).unwrap().unwrap();assert_eq!(child.chat_id(),A);
    let physical=store();physical.borrow_mut().header=Value::Null;
    let OriginalHintRowMetadataAdmission::Saved(mut row)=child.begin_metadata(&c,20).unwrap()else{panic!("actual saved child")};
    let publication=finish_row_metadata(&mut row,&mut c,physical.clone()).await.unwrap();publication.ensure_current(&c).unwrap();
    assert_eq!(publication.kind(),"original_hint_row_metadata_pending_client_apply");assert_eq!(publication.chat_id(),A);
    let s=physical.borrow();assert_eq!(s.header["chat_id"],A);assert_eq!(s.header["is_metadata_only"],true);assert!(s.rows.is_empty());
    assert!(s.plans.iter().any(|p|p["kind"]=="readback_metadata_only"));assert!(s.plans.iter().any(|p|p["kind"]=="readback"&&p["store"]=="chats"));
    assert_eq!(publication.physical_for_test()["record"],s.header);assert!(!c.chats.contains_key(A));assert!(c.history.is_empty());
    assert_eq!(s.plans.iter().filter(|p|p["kind"]=="compare_and_patch_cold_incoming_insert").count(),1);assert_eq!(server.monitor_sockets.load(Ordering::SeqCst),1);monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn same_existing_child_metadata_policy_preserves_local_draft_extensions_and_message_counter(){
    let server=Server::open().await;let(mut c,monitor,mut batch)=actual_refresh_batch_for_windows(&server).await;batch.next_row(&c).unwrap().unwrap();let child=batch.next_row(&c).unwrap().unwrap();
    let mut header=header::build(&child.row,None,20).unwrap().into_inner();header["messages_v"]=json!(7);header["title_v"]=json!(0);header["metadata_v"]=json!(0);header["encrypted_title"]=json!(crypto::encrypt_combined("Old valid child",&[8;32]).unwrap());
    header["encrypted_draft_md"]=json!("unchanged existing local encrypted draft");header["draft_v"]=json!(44);header["unknown_local"]=json!({"retain":true});
    let physical=store();physical.borrow_mut().header=header;
    let OriginalHintRowMetadataAdmission::Saved(mut row)=child.begin_metadata(&c,20).unwrap()else{panic!("actual saved child")};
    let publication=finish_row_metadata(&mut row,&mut c,physical.clone()).await.unwrap();publication.ensure_current(&c).unwrap();let s=physical.borrow();
    assert_eq!(s.header["title_v"],1);assert_eq!(s.header["metadata_v"],1);assert_eq!(s.header["messages_v"],7);assert_eq!(s.header["draft_v"],44);assert_eq!(s.header["encrypted_draft_md"],"unchanged existing local encrypted draft");assert_eq!(s.header["unknown_local"],json!({"retain":true}));assert!(!c.chats.contains_key(A));monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn original_b_and_child_target_guards_refuse_changed_rows_before_actual_metadata_io(){
    for change_b in [false,true]{let server=Server::open().await;let(mut c,monitor,mut batch)=actual_refresh_batch_for_windows(&server).await;batch.next_row(&c).unwrap().unwrap();let child=batch.next_row(&c).unwrap().unwrap();
        let OriginalHintRowMetadataAdmission::Saved(mut row)=child.begin_metadata(&c,20).unwrap()else{panic!("actual saved child")};let control=row.control();
        c.insert_chat_row(if change_b{B}else{A}.into(),metadata());assert!(control.ensure_current(&c).is_err());
        let physical=store();assert!(finish_row_metadata(&mut row,&mut c,physical.clone()).await.is_err());assert!(physical.borrow().plans.is_empty());monitor.close();
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_started_child_bootstrap_write_drains_before_target_conflict_and_never_rolls_back_or_acks(){
    let server=Server::open().await;let(mut c,monitor,mut batch)=actual_refresh_batch_for_windows(&server).await;batch.next_row(&c).unwrap().unwrap();let child=batch.next_row(&c).unwrap().unwrap();
    let OriginalHintRowMetadataAdmission::Saved(mut row)=child.begin_metadata(&c,20).unwrap()else{panic!("actual saved child")};let terminal=row.terminal_observer();let physical=store();physical.borrow_mut().header=Value::Null;
    let mut observed=false;
    for _ in 0..30{match row.next().await.unwrap(){
        OwnedBrowserReadStep::Apply(phase)=>phase.apply(&mut c).unwrap(),
        OwnedBrowserReadStep::IO(io)=>{
            let PendingWork::Io(plan)=&io.pending.work else{panic!("actual IO")};let encoded:Value=serde_json::from_str(&plan.encoded).unwrap();
            if encoded["kind"]=="compare_and_patch_cold_incoming_insert"{
                let(release,receive)=oneshot::channel::<()>();let port=row_metadata_io(physical.clone());
                let started=io.execute(move|encoded|async move{receive.await.map_err(|_|Error::Cancelled)?;port(encoded).await});tokio::pin!(started);
                assert!(futures_util::poll!(started.as_mut()).is_pending());assert!(terminal.terminal().is_none());
                c.insert_chat_row(A.into(),json!({"id":A,"metadata_v":44}));release.send(()).unwrap();let phase=started.await.unwrap();
                assert!(terminal.terminal().is_none());phase.apply(&mut c).unwrap();assert!(row.next().await.is_err());
                assert!(terminal.terminal().unwrap().is_quiescent());observed=true;break;
            }else{io.execute(row_metadata_io(physical.clone())).await.unwrap().apply(&mut c).unwrap();}
        },_=>panic!("no completion before actual held write"),
    }}
    assert!(observed);assert_eq!(physical.borrow().header["chat_id"],A);assert_eq!(c.chats[A]["metadata_v"],44);assert!(!c.chats.contains_key(B));monitor.close();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_native_metadata_row_apply_and_same_ledger_receipt_advance_only_owned_b_anchor_and_metadata_facet(){
    let server=Server::open().await;let(mut c,monitor,mut batch)=actual_refresh_batch_for_windows(&server).await;
    let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();
    let context=batch.context.clone();let previous=context.source.lock().unwrap().clone();let b=batch.next_row(&c).unwrap().unwrap();let expected=(*b.row).clone();
    let OriginalHintRowMetadataAdmission::Saved(mut driver)=b.begin_metadata(&c,20).unwrap()else{panic!("actual saved B")};let physical=store();
    let publication=finish_row_metadata(&mut driver,&mut c,physical.clone()).await.unwrap();let applied=publication.apply(&mut c).unwrap();
    for(field,value)in expected.as_object().unwrap(){assert_eq!(&c.chats[B][field],value,"server metadata field {field}");}assert_eq!(c.chats[B]["encrypted_draft_md"],physical.borrow().header["encrypted_draft_md"]);assert_eq!(c.chats[B]["draft_v"],physical.borrow().header["draft_v"]);assert_ne!(*context.source.lock().unwrap(),previous);assert_eq!(*context.source.lock().unwrap(),source_stamp(&c,B).unwrap());
    batch.ensure_current(&c).unwrap();assert!(!batch.ledger.metadata_for_test(B));batch.acknowledge_metadata(&c,applied).unwrap();assert!(batch.ledger.metadata_for_test(B));
    assert_eq!(batch.retained.readback["metadata"],physical.borrow().header);assert_eq!(physical.borrow().header["messages_v"],7);assert!(c.history.is_empty());
    // Other metadata still needs actual independent processing; neither this
    // facet receipt nor retained physical rows mean whole hint completion.
    let child=batch.next_row(&c).unwrap().unwrap();assert_eq!(child.chat_id(),A);assert!(!batch.ledger.metadata_for_test(A));sibling.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn same_original_resource_cannot_deliver_actual_metadata_receipt_to_a_different_dispatch_ledger(){
    let server=Server::open().await;let(mut c,monitor,mut batch)=actual_refresh_batch_for_windows(&server).await;let b=batch.next_row(&c).unwrap().unwrap();
    let OriginalHintRowMetadataAdmission::Saved(mut driver)=b.begin_metadata(&c,20).unwrap()else{panic!("actual saved B")};let publication=finish_row_metadata(&mut driver,&mut c,store()).await.unwrap();let applied=publication.apply(&mut c).unwrap();
    let original=batch.ledger.clone();batch.ledger=Arc::new(row_ledger::RowLedger::default());
    // Only dispatch identity differs; actual Client/profile/key/root remain
    // current, so a generic JSON count/status could not detect this misuse.
    batch.ensure_current(&c).unwrap();applied.check_for_test(&c).unwrap();assert!(batch.acknowledge_metadata(&c,applied).is_err());
    assert!(!original.metadata_for_test(B));assert!(!batch.ledger.metadata_for_test(B));monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn target_conflict_or_original_revoke_after_actual_physical_store_never_applies_or_marks_metadata_handled(){
    for revoke in [false,true]{let server=Server::open().await;let(mut c,monitor,mut batch)=actual_refresh_batch_for_windows(&server).await;batch.next_row(&c).unwrap().unwrap();let a=batch.next_row(&c).unwrap().unwrap();
        let OriginalHintRowMetadataAdmission::Saved(mut driver)=a.begin_metadata(&c,20).unwrap()else{panic!("actual saved child")};let physical=store();physical.borrow_mut().header=Value::Null;
        let publication=finish_row_metadata(&mut driver,&mut c,physical.clone()).await.unwrap();let physical_after=physical.borrow().header.clone();
        if revoke{c.operation_parent.cancel()}else{c.insert_chat_row(A.into(),json!({"id":A,"metadata_v":99}));}
        assert!(publication.apply(&mut c).is_err());assert!(!batch.ledger.metadata_for_test(A));assert_eq!(physical.borrow().header,physical_after);
        if !revoke{assert_eq!(c.chats[A]["metadata_v"],99);batch.ensure_current(&c).unwrap();}else{assert!(!c.chats.contains_key(A));}
        monitor.close();
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_physical_local_draft_ciphertext_and_floor_survive_omitted_server_fields_and_enter_shared_fallback_requests(){
    let server=Server::open().await;let(mut c,monitor,mut batch)=actual_refresh_batch_for_windows(&server).await;batch.next_row(&c).unwrap().unwrap();let child=batch.next_row(&c).unwrap().unwrap();
    let mut header=header::build(&child.row,None,20).unwrap().into_inner();let md=crypto::encrypt_combined("Synthetic retained local draft",&[7;32]).unwrap();let preview=crypto::encrypt_combined("Synthetic retained preview",&[7;32]).unwrap();
    header["encrypted_draft_md"]=json!(md);header["encrypted_draft_preview"]=json!(preview);header["draft_v"]=json!(44);let physical=store();physical.borrow_mut().header=header;
    let OriginalHintRowMetadataAdmission::Saved(mut row)=child.begin_metadata(&c,20).unwrap()else{panic!("actual saved child")};let publication=finish_row_metadata(&mut row,&mut c,physical.clone()).await.unwrap();
    let applied=publication.apply(&mut c).unwrap();batch.acknowledge_metadata(&c,applied).unwrap();
    assert_eq!(c.chats[A]["encrypted_draft_md"],md);assert_eq!(c.chats[A]["encrypted_draft_preview"],preview);assert_eq!(c.chats[A]["draft_v"],44);
    let shared=crate::client::draft_read::DraftFallbackPolicy::capture(&c,A).unwrap();assert!(shared.first_requested().contains(&(A.to_string(),44)));
    assert_eq!(physical.borrow().header["draft_v"],44);assert!(c.history.is_empty());monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn physical_cleared_draft_clock_is_retained_as_local_floor_without_resurrecting_ciphertext_or_granting_delete(){
    let server=Server::open().await;let(mut c,monitor,mut batch)=actual_refresh_batch_for_windows(&server).await;batch.next_row(&c).unwrap().unwrap();let child=batch.next_row(&c).unwrap().unwrap();
    let mut header=header::build(&child.row,None,20).unwrap().into_inner();header["draft_v"]=json!(0);header["cleared_draft_v"]=json!(51);let physical=store();physical.borrow_mut().header=header;
    let OriginalHintRowMetadataAdmission::Saved(mut row)=child.begin_metadata(&c,20).unwrap()else{panic!("actual saved child")};let publication=finish_row_metadata(&mut row,&mut c,physical.clone()).await.unwrap();let applied=publication.apply(&mut c).unwrap();batch.acknowledge_metadata(&c,applied).unwrap();
    assert!(c.chats[A]["encrypted_draft_md"].is_null());assert_eq!(c.chats[A]["draft_v"],51);assert_eq!(c.chats[A]["cleared_draft_v"],51);
    let shared=crate::client::draft_read::DraftFallbackPolicy::capture(&c,A).unwrap();assert!(shared.first_requested().contains(&(A.to_string(),51)));assert_eq!(physical.borrow().header["draft_v"],0);assert!(c.chats.contains_key(A));monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn physical_draft_cache_merge_reuses_strict_version_rule_and_refuses_older_or_same_clock_changed_local_cipher(){
    let server=Server::open().await;let c=server.client().await;let original=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();let server_row=metadata();
    let mut previous=server_row.clone();previous["draft_v"]=json!(55);previous["encrypted_draft_md"]=json!(crypto::encrypt_combined("Synthetic newer unpersisted editor draft",&[7;32]).unwrap());
    for version in [44,55]{let mut physical=header::build(&server_row,None,20).unwrap().into_inner();physical["draft_v"]=json!(version);physical["encrypted_draft_md"]=json!(crypto::encrypt_combined("Synthetic different physical draft",&[7;32]).unwrap());
        assert!(c.merge_original_physical_draft_cache(&original,B,&server_row,&physical,Some(&previous)).is_err());assert_eq!(previous["draft_v"],55);
    }
    original.observer().cancel();assert!(c.merge_original_physical_draft_cache(&original,B,&server_row,&server_row,None).is_err());
}

fn inventory_data(plan:&Value,rows:Vec<Value>,last:Option<&str>,exhausted:bool)->String{json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"page":plan["page"],"databaseVersion":1,"rows":rows,"lastKey":last,"cursorExhausted":exhausted,"transactionCommitted":true}).to_string()}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn genuine_original_inventory_prerequisite_mints_only_closed_read_data_ticket_and_refuses_foreign_or_repeated_dispatch(){
    let server=Server::open().await;let(c,monitor,batch)=actual_refresh_batch_for_windows(&server).await;let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();
    let prerequisite=batch.begin_draft_inventory(&c).unwrap();let ticket=prerequisite.first_ticket(&c).unwrap();let plan:Value=serde_json::from_str(&ticket.effect_json(&c).unwrap()).unwrap();
    assert_eq!(plan["kind"],"read_original_draft_inventory_page");assert_eq!(plan["maxRows"],20);assert_eq!(plan["maxBytes"],2*1024*1024);assert!(plan["after"].is_null());assert_eq!(plan["page"],1);assert!(!plan.to_string().contains("master"));
    ticket.claim_dispatch(&c).unwrap();assert!(matches!(ticket.claim_dispatch(&c),Err(Error::Conflict)));
    let foreign=server.client().await;assert!(ticket.check_original(&foreign).is_err());
    prerequisite.cancel();prerequisite.wait_cancelled().await;assert!(ticket.check_original(&c).is_err());sibling.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn inventory_ciphertext_page_parser_retains_data_only_and_refuses_plaintext_unknown_keys_bad_order_and_no_progress(){
    let server=Server::open().await;let(c,monitor,batch)=actual_refresh_batch_for_windows(&server).await;let prerequisite=batch.begin_draft_inventory(&c).unwrap();let ticket=prerequisite.first_ticket(&c).unwrap();let plan:Value=serde_json::from_str(&ticket.effect_json(&c).unwrap()).unwrap();
    let row=json!({"chat_id":A,"draft_v":44,"encrypted_draft_md":crypto::encrypt_combined("Synthetic local inventory draft",&[7;32]).unwrap()});
    let raw=inventory_data(&plan,vec![row.clone()],Some(A),true);let data=ticket.inspect_data(&c,&raw).unwrap();assert_eq!(data.rows_data(&c).unwrap(),&[row.clone()]);assert_eq!(data.cursor_data(&c).unwrap(),(Some(A),true));assert_eq!(data.database_version_data(&c).unwrap(),1);
    for fault in ["plaintext","descending","wrong_last","empty_progress","too_many","unsafe_version","oversized","extra_frame"]{
        let mut frame:Value=serde_json::from_str(&raw).unwrap();match fault{
            "plaintext"=>frame["rows"][0]["markdown"]=json!("MUST_NOT_PASS_AS_CIPHERTEXT_DATA"),
            "descending"=>frame["rows"]=json!([row.clone(),row.clone()]),
            "wrong_last"=>frame["lastKey"]=json!(B),
            "empty_progress"=>{frame["rows"]=json!([]);frame["lastKey"]=Value::Null;frame["cursorExhausted"]=json!(false);},
            "too_many"=>frame["rows"]=json!(vec![row.clone();21]),
            "unsafe_version"=>frame["rows"][0]["draft_v"]=json!(9007199254740992u64),
            "oversized"=>frame["rows"][0]["encrypted_draft_md"]=json!("x".repeat(2*1024*1024)),
            _=>frame["inventoryComplete"]=json!(true),
        }
        assert!(ticket.inspect_data(&c,&frame.to_string()).is_err(),"{fault}");
    }
    // No native delivery/receipt/import/whole-hint completion is minted by any
    // valid DATA shape or transactionCommitted/EOF boolean.
    assert!(!c.chats.contains_key(A));monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn already_parsed_inventory_data_cannot_release_after_original_root_revocation(){
    let server=Server::open().await;let(c,monitor,batch)=actual_refresh_batch_for_windows(&server).await;let prerequisite=batch.begin_draft_inventory(&c).unwrap();let ticket=prerequisite.first_ticket(&c).unwrap();let plan:Value=serde_json::from_str(&ticket.effect_json(&c).unwrap()).unwrap();
    let data=ticket.inspect_data(&c,&inventory_data(&plan,vec![],None,true)).unwrap();assert!(data.rows_data(&c).unwrap().is_empty());c.operation_parent.cancel();
    assert!(data.rows_data(&c).is_err());assert!(data.cursor_data(&c).is_err());assert!(ticket.effect_json(&c).is_err());monitor.close();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn caller_gate_returning_ok_cannot_hide_original_inventory_child_revocation_at_last_callback(){
    let server=Server::open().await;let armed=Arc::new(AtomicBool::new(false));let gate_armed=armed.clone();let child=Arc::new(Mutex::new(None::<CancellationToken>));let gate_child=child.clone();
    let gate=Arc::new(move||{if gate_armed.load(Ordering::Acquire){if let Some(child)=gate_child.lock().unwrap().as_ref(){child.cancel();}}Ok(())});
    let(c,monitor,batch)=actual_refresh_batch_with_gate(&server,Some(gate)).await;let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();
    let prerequisite=batch.begin_draft_inventory(&c).unwrap();let ticket=prerequisite.first_ticket(&c).unwrap();*child.lock().unwrap()=Some(ticket.cancellation_for_test());armed.store(true,Ordering::Release);
    assert!(ticket.effect_json(&c).is_err());assert!(ticket.claim_dispatch(&c).is_err());assert!(!c.operation_parent.is_cancelled());sibling.check(&c).unwrap();monitor.close();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn inventory_additional_negative_retains_original_resources_without_reinvoking_private_application_gate(){
    let server=Server::open().await;let calls=Arc::new(AtomicU64::new(0));let count=calls.clone();let deny=Arc::new(AtomicBool::new(false));let gate_deny=deny.clone();
    let gate=Arc::new(move||{count.fetch_add(1,Ordering::SeqCst);if gate_deny.load(Ordering::Acquire){Err(Error::Forbidden)}else{Ok(())}});
    let(c,monitor,batch)=actual_refresh_batch_with_gate(&server,Some(gate)).await;let prerequisite=batch.begin_draft_inventory(&c).unwrap();let ticket=prerequisite.first_ticket(&c).unwrap();let operation=ticket.operation_id().to_owned();
    deny.store(true,Ordering::Release);let before=calls.load(Ordering::SeqCst);ticket.check_original_negative().unwrap();assert_eq!(calls.load(Ordering::SeqCst),before);assert_eq!(ticket.operation_id(),operation);
    assert!(ticket.check_original(&c).is_err());assert!(calls.load(Ordering::SeqCst)>before);let before=calls.load(Ordering::SeqCst);
    prerequisite.cancel();assert!(ticket.check_original_negative().is_err());assert_eq!(calls.load(Ordering::SeqCst),before);assert!(!c.operation_parent.is_cancelled());monitor.close();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn inventory_reread_ticket_is_exact_original_page_row_and_data_match_never_delete_or_native_proof(){
    let server=Server::open().await;let(c,monitor,batch)=actual_refresh_batch_for_windows(&server).await;let prerequisite=batch.begin_draft_inventory(&c).unwrap();let page=prerequisite.first_ticket(&c).unwrap();page.claim_dispatch(&c).unwrap();let plan:Value=serde_json::from_str(&page.effect_json(&c).unwrap()).unwrap();
    let row=json!({"chat_id":A,"draft_v":44,"encrypted_draft_md":crypto::encrypt_combined("Synthetic original page draft",&[7;32]).unwrap()});let data=page.inspect_data(&c,&inventory_data(&plan,vec![row.clone()],Some(A),true)).unwrap();
    let reread=page.reread_for_native_row(&c,&data,0).unwrap();let effect:Value=serde_json::from_str(&reread.effect_json(&c).unwrap()).unwrap();assert_eq!(effect["kind"],"reread_original_draft_inventory_row");assert_eq!(effect["chatId"],A);assert!(effect.get("after").is_none());assert!(page.reread_for_native_row(&c,&data,1).is_err());
    let base=json!({"version":1,"kind":effect["kind"],"operationId":effect["operationId"],"page":effect["page"],"databaseVersion":1,"row":row,"transactionCommitted":true});
    let observed=reread.inspect_reread_data(&c,&base.to_string()).unwrap();assert_eq!(observed.require_original_projection(&c).unwrap(),&row);assert!(reread.inspect_data(&c,&inventory_data(&plan,vec![row.clone()],Some(A),true)).is_err());
    let mut absent=base.clone();absent["row"]=Value::Null;let absent=reread.inspect_reread_data(&c,&absent.to_string()).unwrap();assert!(absent.row_data(&c).unwrap().is_none());assert!(absent.require_original_projection(&c).is_err());assert!(!c.chats.contains_key(A));
    let mut changed=base;changed["row"]["draft_v"]=json!(45);let changed=reread.inspect_reread_data(&c,&changed.to_string()).unwrap();assert!(changed.require_original_projection(&c).is_err());monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn inventory_reread_original_ticket_child_and_profile_negatives_refuse_late_data_even_when_shape_matches(){
    let server=Server::open().await;let(c,monitor,batch)=actual_refresh_batch_for_windows(&server).await;let prerequisite=batch.begin_draft_inventory(&c).unwrap();let page=prerequisite.first_ticket(&c).unwrap();page.claim_dispatch(&c).unwrap();let plan:Value=serde_json::from_str(&page.effect_json(&c).unwrap()).unwrap();let row=json!({"chat_id":A,"draft_v":0,"cleared_draft_v":44});let data=page.inspect_data(&c,&inventory_data(&plan,vec![row.clone()],Some(A),true)).unwrap();
    let reread=page.reread_for_native_row(&c,&data,0).unwrap();let effect:Value=serde_json::from_str(&reread.effect_json(&c).unwrap()).unwrap();let encoded=json!({"version":1,"kind":effect["kind"],"operationId":effect["operationId"],"page":effect["page"],"databaseVersion":1,"row":row,"transactionCommitted":true}).to_string();let observed=reread.inspect_reread_data(&c,&encoded).unwrap();
    let foreign=server.client().await;assert!(reread.check_original(&foreign).is_err());prerequisite.cancel();assert!(observed.row_data(&c).is_err());assert!(observed.require_original_projection(&c).is_err());assert!(reread.effect_json(&c).is_err());assert!(!c.operation_parent.is_cancelled());monitor.close();
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn original_selected_row_ticket_is_distinct_get_origin_and_never_a_fabricated_page_or_import(){
    let server=Server::open().await;let mut c=server.client().await;
    let driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let ticket=draft_inventory::first_for_original_context(driver.context.clone(),&c,B).unwrap();ticket.claim_dispatch(&c).unwrap();
    let effect:Value=serde_json::from_str(&ticket.effect_json(&c).unwrap()).unwrap();assert_eq!(effect["kind"],"reread_original_draft_inventory_row");assert_eq!(effect["chatId"],B);assert!(effect.get("after").is_none());
    assert!(draft_inventory::first_for_original_context(driver.context.clone(),&c,A).is_err(),"caller row ID is not an original known selector");
    let row=json!({"chat_id":B,"draft_v":0,"cleared_draft_v":51});
    let frame=json!({"version":1,"kind":effect["kind"],"operationId":effect["operationId"],"page":effect["page"],"databaseVersion":1,"row":row,"transactionCommitted":true});
    let data=ticket.inspect_original_row(&c,&frame.to_string()).unwrap();assert_eq!(data.row(&c).unwrap(),Some(&row));
    assert!(ticket.inspect_data(&c,&inventory_data(&effect,vec![row.clone()],Some(B),true)).is_err());
    let reread=ticket.reread_original_row(&c,&data).unwrap();assert_eq!(reread.inspect_reread_data(&c,&frame.to_string()).unwrap().require_original_projection(&c).unwrap(),&row);
    let mut changed=frame;changed["row"]["cleared_draft_v"]=json!(52);assert!(reread.inspect_reread_data(&c,&changed.to_string()).unwrap().require_original_projection(&c).is_err());
    assert!(!c.chats.contains_key(B),"DATA parsers and reread selectors cannot hydrate or mint native observations");
}
// contract-test: supporting surface=sdks.rust assertions=auth.secrets.lifecycle,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn original_selected_row_parser_accepts_bounded_large_cipher_data_without_normal_budget_or_ownership_upgrade(){
    let server=Server::open().await;let mut c=server.client().await;
    let driver=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let ticket=draft_inventory::first_for_original_context(driver.context.clone(),&c,B).unwrap();ticket.claim_dispatch(&c).unwrap();let effect:Value=serde_json::from_str(&ticket.effect_json(&c).unwrap()).unwrap();
    let frame=json!({"version":1,"kind":effect["kind"],"operationId":effect["operationId"],"page":effect["page"],"databaseVersion":1,"row":{"chat_id":B,"draft_v":1,"encrypted_draft_md":"A".repeat(1_400_000)},"transactionCommitted":true}).to_string();
    assert!(local_json::validate(&frame).is_err());assert!(ticket.inspect_original_row(&c,&frame).is_ok());assert!(!c.chats.contains_key(B));assert!(c.original_physical_draft_bounds.is_empty(),"untrusted JSON cannot construct the native budget witness");
    c.operation_parent.cancel();assert!(ticket.inspect_original_row(&c,&frame).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[test]
fn secondary_inventory_lease_blocks_every_same_context_driver_terminal_and_drop_cannot_forge_drain(){
    let inventory=Arc::new(InventoryDrainState::default());
    let a=DriverDrainState{inventory:inventory.clone(),..DriverDrainState::default()};let b=DriverDrainState{inventory:inventory.clone(),..DriverDrainState::default()};
    a.returned.store(true,Ordering::Release);b.returned.store(true,Ordering::Release);assert!(a.quiescent());assert!(b.quiescent());
    let hold=InventoryLease::begin(inventory.clone()).unwrap();assert!(!a.quiescent());assert!(!b.quiescent());hold.settled();assert!(a.quiescent());assert!(b.quiescent());
    let abandoned=InventoryLease::begin(inventory).unwrap();drop(abandoned);assert!(!a.quiescent());assert!(!b.quiescent());
    let foreign=DriverDrainState::default();foreign.returned.store(true,Ordering::Release);assert!(foreign.quiescent(),"another original context cannot be retired by this abandoned lease");
}
// contract-test: supporting surface=sdks.rust assertions=drafts.persistence.local-first-encrypted,chats.persistence.client-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn original_physical_empty_cipher_and_null_id_clear_floor_preserve_strict_monotone_negative_semantics(){
    let server=Server::open().await;let c=server.client().await;let scope=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();
    let previous=json!({"id":B,"draft_v":3,"encrypted_draft_md":"previous encrypted draft"});
    let physical=json!({"chat_id":B,"id":null,"encrypted_draft_md":"","cleared_draft_v":5});
    let merged=c.merge_original_physical_draft_cache(&scope,B,&json!({"id":B}),&physical,Some(&previous)).unwrap();
    assert_eq!(merged["draft_v"],5);assert_eq!(merged["cleared_draft_v"],5);assert_eq!(merged["encrypted_draft_md"],"");assert!(merged.get("encrypted_chat_key").is_none());
    let mut foreign=physical.clone();foreign["id"]=json!(A);assert!(c.merge_original_physical_draft_cache(&scope,B,&json!({"id":B}),&foreign,Some(&previous)).is_err());
    let mut older=physical.clone();older["cleared_draft_v"]=json!(2);assert!(c.merge_original_physical_draft_cache(&scope,B,&json!({"id":B}),&older,Some(&previous)).is_err());
    let mut same=physical;same["cleared_draft_v"]=json!(3);assert!(c.merge_original_physical_draft_cache(&scope,B,&json!({"id":B}),&same,Some(&previous)).is_err(),"same-clock changed cipher remains a conflict");
}
