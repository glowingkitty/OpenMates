//! Authored UNRUN: actual admitted Core/HTTP/socket/key operations, inert native
//! cursor port. Real IDB/profile/drain and timing acceptance remain browser CI.
use super::*;
struct LocalStore {physical:Rc<RefCell<Store>>,checkpoints:Vec<Value>,fault:&'static str,reads:usize}
fn local()->Rc<RefCell<LocalStore>>{
    let physical=store();let mut row=fresh_row();row["message_id"]=json!("physical-new-B");
    row["content"]=json!("UNTRUSTED clear extension must not publish");
    physical.borrow_mut().rows.insert("physical-new-B".into(),row);
    Rc::new(RefCell::new(LocalStore{physical,checkpoints:vec![],fault:"",reads:0}))
}
fn cursor_port(state:Rc<RefCell<LocalStore>>)->impl FnOnce(String)->std::future::Ready<Result<String>>{
    move|encoded|{
        let p:Value=serde_json::from_str(&encoded).unwrap();let mut s=state.borrow_mut();
        if !matches!(p["kind"].as_str(),Some("owned_metadata"|"messages")){
            if p["kind"]=="compare_and_patch_cold_incoming_insert"&&s.physical.borrow().header.is_null(){
                let mut physical=s.physical.borrow_mut();physical.plans.push(p.clone());assert!(p["expectedMetadata"].is_null());
                let ids=p["messageIds"].as_array().unwrap();let before=ids.iter().map(|id|physical.rows.get(id.as_str().unwrap()).cloned().unwrap_or(Value::Null)).collect::<Vec<_>>();
                physical.header=p["metadataInsert"].clone();
                for(i,patch)in p["patches"].as_array().unwrap().iter().enumerate(){assert!(before[i].is_null());physical.rows.insert(ids[i].as_str().unwrap().into(),patch["insert"].clone());}
                let rows=ids.iter().map(|id|physical.rows[id.as_str().unwrap()].clone()).collect::<Vec<_>>();
                return std::future::ready(Ok(json!({"version":1,"kind":p["kind"],"operationId":p["operationId"],"databaseVersion":1,"transactionCommitted":true,
                    "credentialAcknowledged":false,"crossDatabaseAssociationProven":false,"metadata":physical.header,"rows":rows,"before":before}).to_string()))
            }
            return port(s.physical.clone())(encoded)
        }
        assert!(!encoded.contains(TEXT));s.reads+=1;
        if s.fault=="io"{return std::future::ready(Err(Error::Offline))}
        let mut physical=s.physical.borrow_mut();physical.plans.push(p.clone());
        let mut result=json!({"version":1,"kind":p["kind"],"operationId":p["operationId"],"databaseVersion":1});
        if p["kind"]=="owned_metadata"{
            result["chat_metadata"]=physical.header.clone();result["messages"]=json!([]);
            result["wrappers"]=json!([]);result["boundary"]=Value::Null;result["compression_checkpoints"]=json!(s.checkpoints);
            if s.fault=="changed_metadata"&&s.reads>=3{result["chat_metadata"]["unknown_local"]=json!({"concurrent":true})}
        }else{
            let lower=p["lower"]["createdAt"].as_i64();let limit=p["maxPayloadRows"].as_u64().unwrap()as usize;
            let mut rows=physical.rows.values().filter(|r|lower.is_none_or(|at|r["created_at"].as_i64().unwrap()>at)).cloned().collect::<Vec<_>>();
            rows.sort_by(|a,b|wire::position_cmp(wire::position(b).unwrap(),wire::position(a).unwrap()));
            let next=rows.get(limit).map(|r|json!({"createdAt":r["created_at"],"messageId":wire::position(r).unwrap().1}));rows.truncate(limit);
            result["messages"]=json!(rows);result["nextKey"]=next.clone().unwrap_or(Value::Null);result["rangeExhausted"]=json!(next.is_none());
            if s.fault=="changed_rows"&&s.reads>=4{result["messages"][0]["unknown_local"]=json!("concurrent")}
            if s.fault=="database"{result["databaseVersion"]=json!(2)}
        }
        std::future::ready(Ok(result.to_string()))
    }
}
async fn finish_local(driver:&mut OwnedBrowserReadDriver,c:&mut Client,s:Rc<RefCell<LocalStore>>)->Result<OwnedBrowserReadPublication>{
    for _ in 0..40{match driver.next().await?{
        OwnedBrowserReadStep::Apply(phase)=>phase.apply(c)?,
        OwnedBrowserReadStep::IO(io)=>io.execute(cursor_port(s.clone())).await?.apply(c)?,
        OwnedBrowserReadStep::Selected(publication)=>return Ok(publication),
        _=>return Err(Error::Protocol),
    }}Err(Error::Protocol)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn warm_owned_b_publishes_without_http_while_actual_same_socket_startup_a_expansion_is_held(){
    let server=Server::open().await;let mut c=server.client().await;
    let(errors,_received)=mpsc::channel(4);let monitor=Arc::new(c.start_chat_monitor(CancellationToken::new(),errors).await.unwrap());
    let startup=c.prepare_initial_sync(monitor.clone(),CancellationToken::new()).unwrap();let a_control=startup.control();
    let mut waiting=Box::pin(startup.wait());assert!(futures_util::poll!(waiting.as_mut()).is_pending());
    server.monitor_started.notified().await;server.monitor_release.notify_one();
    tokio::select!{_=server.expanded_started.notified()=>{},_=waiting.as_mut()=>panic!("actual expanded response must remain held")};
    let s=local();let original_header=s.borrow().physical.borrow().header.clone();
    let mut b=c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut publication=tokio::time::timeout(Duration::from_secs(2),finish_local(&mut b,&mut c,s.clone())).await.unwrap().unwrap();
    assert!(publication.take(&c,false).is_err());assert!(publication.authenticated_source_stamp(&c).is_err());
    assert!(publication.authenticated_messages_version(&c).is_err());
    let output:Value=serde_json::from_str(&publication.take(&c,true).unwrap()).unwrap();
    assert_eq!(output["cacheReadKind"],"local");assert_eq!(output["chat"]["messages"][0]["content"],TEXT);
    for flag in ["fresh","historyComplete","nativeDurabilityAcknowledged","canonicalIncomingDurablyAcknowledged","credentialAcknowledged"]{assert_eq!(output[flag],false)}
    assert_eq!(s.borrow().reads,4);assert_eq!(s.borrow().physical.borrow().header,original_header);
    assert!(s.borrow().physical.borrow().plans.iter().all(|p|matches!(p["kind"].as_str(),Some("owned_metadata"|"messages"))));
    assert_eq!(server.selected_http.load(Ordering::Acquire),0);assert_eq!(server.monitor_sockets.load(Ordering::Acquire),1);
    assert!(futures_util::poll!(waiting.as_mut()).is_pending());a_control.ensure_current(&c).unwrap();
    publication.finish_cold(&c).unwrap();a_control.ensure_current(&c).unwrap();assert!(c.completion_recovery_mode.is_none());
    server.expanded_release.notify_one();let batch=waiting.await.unwrap().retain(&c).unwrap();assert_eq!(batch.received_metadata_count(&c).unwrap(),2);monitor.close();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,chats.persistence.client-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn local_read_errors_corruption_and_conflicts_never_turn_into_cold_http(){
    for fault in ["io","changed_metadata","changed_rows","database","owner","key","cipher","keyless_partial","large_payload","packet"]{
        let server=Server::open().await;let mut c=server.client().await;let s=local();s.borrow_mut().fault=fault;
        {let physical=s.borrow().physical.clone();let mut p=physical.borrow_mut();match fault{
            "owner"=>p.header["user_id"]=json!(A),"key"=>p.header["encrypted_chat_key"]=json!("bad"),
            "keyless_partial"=>{p.header["encrypted_chat_key"]=Value::Null;p.header["is_metadata_only"]=json!(true)},
            "cipher"=>p.rows.get_mut("physical-new-B").unwrap()["encrypted_content"]=json!("bad"),
            "large_payload"=>p.rows.get_mut("physical-new-B").unwrap()["large_payload"]=json!({"ref":"opaque"}),
            "packet"=>p.header["unknown_local"]=json!("x".repeat(256*1024)),
            _=>{},
        }}
        let mut driver=c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
        match finish_local(&mut driver,&mut c,s.clone()).await{Ok(mut publication)=>assert!(publication.take(&c,true).is_err(),"{fault}"),Err(_)=>{}}
        assert_eq!(server.selected_http.load(Ordering::Acquire),0,"{fault}");
        assert!(s.borrow().physical.borrow().plans.iter().all(|p|!p["kind"].as_str().unwrap().contains("patch")));
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn local_selected_cancel_and_stale_original_refuse_without_affecting_sibling_or_regranting(){
    for fault in ["cancel","profile","foreign"]{
        let server=Server::open().await;let mut c=server.client().await;let mut foreign=server.client().await;
        let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();let s=local();
        let mut driver=c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
        let io=actual_io_phase(&mut driver,&mut c).await;let phase=io.execute(cursor_port(s)).await.unwrap();
        match fault{"cancel"=>driver.cancel(),"profile"=>c.operation_parent.cancel(),"foreign"=>{},_=>unreachable!()}
        if fault=="foreign"{phase.apply(&mut foreign).unwrap()}else{phase.apply(&mut c).unwrap()}
        assert!(driver.next().await.is_err());assert_eq!(server.selected_http.load(Ordering::Acquire),0);
        if fault!="profile"{sibling.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled())}
    }
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn local_latest_compression_boundary_checkpoint_and_twenty_row_budget_use_maintained_policy(){
    let server=Server::open().await;let mut c=server.client().await;let s=local();
    {let mut state=s.borrow_mut();state.checkpoints.push(json!({"id":"checkpoint","chat_id":B,"created_at":9,"compressed_up_to_timestamp":8,"compressed_message_count":8,"summary":"Stored [PERSON_1]"}));
        let mut p=state.physical.borrow_mut();p.rows.clear();for i in 0..35{let id=format!("physical-{i:02}");let mut row=fresh_row();row["message_id"]=json!(id);row["id"]=json!(id);row["created_at"]=json!(i);p.rows.insert(id,row);}}
    let mut driver=c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),40,true).unwrap();
    let mut publication=finish_local(&mut driver,&mut c,s.clone()).await.unwrap();
    let output:Value=serde_json::from_str(&publication.take(&c,true).unwrap()).unwrap();
    assert_eq!(output["chat"]["messages"].as_array().unwrap().len(),20);assert_eq!(output["messageMetadata"][0]["createdAt"],15);
    assert_eq!(output["checkpointPresentation"]["checkpoint"]["summary"],"Stored [PERSON_1]");
    let state=s.borrow();let p=state.physical.borrow();for plan in p.plans.iter().filter(|p|p["kind"]=="messages"){
        assert_eq!(plan["maxPayloadRows"],20);assert_eq!(plan["lower"],json!({"createdAt":8,"messageId":null,"open":true}));assert!(plan["maxPacketBytes"].as_u64().unwrap()<256*1024);
    }assert_eq!(server.selected_http.load(Ordering::Acquire),0);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn explicit_local_first_does_not_change_cold_default_or_private_consent_and_selector_rules(){
    let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;
    assert!(c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,false).is_err());
    let mut bad=crate::client::message_window::MessageWindowOptions::default();bad.limit=21;
    assert!(c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,B,bad,host(),20,true).is_err());
    let s=local();let physical=s.borrow().physical.clone();physical.borrow_mut().rows.get_mut("physical-new-B").unwrap().as_object_mut().unwrap().remove("content");let mut cold=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut publication=finish(&mut cold,&mut c,physical).await.unwrap();let output:Value=serde_json::from_str(&publication.take(&c,true).unwrap()).unwrap();
    assert_eq!(output["cacheReadKind"],"cold");assert_eq!(server.selected_http.load(Ordering::Acquire),2);assert_eq!(s.borrow().reads,0);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn only_actual_absent_header_or_supported_empty_keyed_cache_enters_existing_cold_http(){
    for absent_header in [true,false]{
        let server=Server::open().await;*server.row.lock().unwrap()=Some(fresh_row());let mut c=server.client().await;let s=local();
        {let physical=s.borrow().physical.clone();let mut p=physical.borrow_mut();p.rows.clear();if absent_header{p.header=Value::Null}}
        let mut driver=c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
        let mut publication=finish_local(&mut driver,&mut c,s.clone()).await.unwrap();
        let output:Value=serde_json::from_str(&publication.take(&c,true).unwrap()).unwrap();assert_eq!(output["cacheReadKind"],"cold");
        assert_eq!(output["chat"]["messages"][0]["content"],TEXT);assert_eq!(server.selected_http.load(Ordering::Acquire),2);
        assert_eq!(s.borrow().reads,if absent_header{1}else{4});publication.finish_cold(&c).unwrap();
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn local_cancel_keeps_actual_started_native_io_owned_until_callback_terminal(){
    let server=Server::open().await;let mut c=server.client().await;let s=local();
    let sibling=OwnedOperationScope::capture(&c,CancellationToken::new()).unwrap();
    let mut driver=c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let observer=driver.terminal_observer();let io=actual_io_phase(&mut driver,&mut c).await;
    let(release,receive)=oneshot::channel::<()>();
    let mut executing=Box::pin(io.execute(move|encoded|async move{receive.await.map_err(|_|Error::Cancelled)?;cursor_port(s)(encoded).await}));
    assert!(futures_util::poll!(executing.as_mut()).is_pending());driver.cancel();
    assert!(observer.terminal().is_none());assert!(futures_util::poll!(executing.as_mut()).is_pending());sibling.check(&c).unwrap();
    release.send(()).unwrap();executing.await.unwrap().apply(&mut c).unwrap();
    assert!(driver.next().await.is_err());assert!(observer.terminal().unwrap().is_quiescent());
    assert_eq!(server.selected_http.load(Ordering::Acquire),0);sibling.check(&c).unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn valid_zero_message_full_local_header_does_not_force_any_http(){
    let server=Server::open().await;let mut c=server.client().await;let s=local();
    {let physical=s.borrow().physical.clone();let mut p=physical.borrow_mut();p.rows.clear();p.header["messages_v"]=json!(0);p.header["is_metadata_only"]=json!(false)}
    let mut driver=c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,B,Default::default(),host(),20,true).unwrap();
    let mut publication=finish_local(&mut driver,&mut c,s).await.unwrap();
    let output:Value=serde_json::from_str(&publication.take(&c,true).unwrap()).unwrap();assert_eq!(output["cacheReadKind"],"local");assert_eq!(output["chat"]["messages"],json!([]));
    assert_eq!(server.selected_http.load(Ordering::Acquire),0);assert!(publication.into_metadata_continuation(&c).is_err());
}
