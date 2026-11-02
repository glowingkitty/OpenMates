//! Authored UNRUN actual HTTP/auth Core cases; native cursors are inert.
//! No native profile, browser clear-view or latency acceptance is inferred.
use super::*;
use crate::client::{BrowserProfileCacheReadiness,OwnedBrowserReadDriver,OwnedBrowserReadStep,OwnedBrowserReadPublication};
#[path="browser_profile_cache_absence_tests.rs"]
mod absence;
fn host()->crate::client::BrowserMetadataCacheScope{serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":0})).unwrap()}
fn begin(c:&mut Client,readiness:Arc<BrowserProfileCacheReadiness>)->OwnedBrowserReadDriver{
    c.begin_owned_browser_profile_cache_read(readiness,CancellationToken::new(),OWNER,CHAT,Default::default(),host(),20,true).unwrap()
}
async fn local(driver:&mut OwnedBrowserReadDriver,c:&mut Client,absence:u8)->Result<OwnedBrowserReadPublication>{
    let metadata=if absence==1{Value::Null}else{header()};
    let row=json!({"message_id":"cached-local","chat_id":CHAT,"created_at":1,"role":"user","status":"delivered","encrypted_content":crypto::encrypt_combined(TEXT,&[9;32]).unwrap()});
    for _ in 0..30{match driver.next().await?{
        OwnedBrowserReadStep::Apply(phase)=>phase.apply(c)?,
        OwnedBrowserReadStep::IO(io)=>{
            let(metadata,row)=(metadata.clone(),row.clone());io.execute(move|encoded|async move{
                let plan:Value=serde_json::from_str(&encoded)?;
                assert!(matches!(plan["kind"].as_str(),Some("owned_metadata"|"messages")));
                let mut response=json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"databaseVersion":1});
                if plan["kind"]=="owned_metadata"{response["chat_metadata"]=metadata;response["messages"]=json!([]);response["wrappers"]=json!([]);response["boundary"]=Value::Null;response["compression_checkpoints"]=json!([])}
                else{response["messages"]=if absence==2{json!([])}else{json!([row])};response["nextKey"]=Value::Null;response["rangeExhausted"]=json!(true)}
                Ok(response.to_string())
            }).await?.apply(c)?;
        },
        OwnedBrowserReadStep::Selected(publication)=>return Ok(publication),
        _=>return Err(Error::Protocol),
    }}Err(Error::Protocol)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn genuine_prior_profile_cache_publishes_during_real_held_auth_without_rearming_general_guards(){
    let server=Server::open().await;let mut c=server.client().await;
    let readiness=c.prepare_browser_profile_cache_readiness().unwrap();server.hold_auth.store(true,Ordering::Release);
    let(errors,_received)=mpsc::channel(4);let mut a=c.prepare_owned_chat_monitor(CancellationToken::new(),errors).unwrap();
    let OwnedChatMonitorStartStep::Apply(prepare)=a.next().await.unwrap()else{panic!("original auth prepare")};prepare.apply(&mut c).unwrap();
    assert!(!c.browser_authority.as_ref().unwrap().owner_guards);
    let mut pending=Box::pin(a.next());assert!(futures_util::poll!(pending.as_mut()).is_pending());drive_until_held_notice(pending.as_mut(), &server.auth_held).await;
    assert!(c.prepare_browser_profile_cache_readiness().is_err());
    assert!(c.begin_owned_browser_local_first_message_read(CancellationToken::new(),OWNER,CHAT,Default::default(),host(),20,true).is_err());
    let mut b=begin(&mut c,readiness.clone());let control=b.control();
    let mut publication=tokio::time::timeout(Duration::from_secs(2),local(&mut b,&mut c,0)).await.unwrap().unwrap();
    control.ensure_current(&c).unwrap();assert!(publication.take(&c,false).is_err());assert!(publication.authenticated_source_stamp(&c).is_err());
    let value:Value=serde_json::from_str(&publication.take(&c,true).unwrap()).unwrap();
    assert_eq!(value["chat"]["messages"][0]["content"],TEXT);assert_eq!(value["cacheReadKind"],"local");
    for name in ["fresh","historyComplete","nativeDurabilityAcknowledged","canonicalIncomingDurablyAcknowledged","credentialAcknowledged"]{assert_eq!(value[name],false)}
    publication.finish_cold(&c).unwrap();assert!(futures_util::poll!(pending.as_mut()).is_pending());
    assert!(!c.browser_authority.as_ref().unwrap().owner_guards);assert_eq!(server.sockets.load(Ordering::Acquire),0);assert_eq!(server.selected_http.load(Ordering::Acquire),0);
    server.auth_release.notify_one();let OwnedChatMonitorStartStep::Apply(headers)=pending.await.unwrap()else{panic!("headers")};headers.apply(&mut c).unwrap();
    let OwnedChatMonitorStartStep::Apply(body)=a.next().await.unwrap()else{panic!("body")};body.apply(&mut c).unwrap();
    // Only the ACTUAL successful auth body re-admits general owner guards.
    assert!(c.browser_authority.as_ref().unwrap().owner_guards);readiness.ensure_current(&c).unwrap();
    assert!(c.cookies.values().any(|v|v=="actual-auth-rotation"));a.control().cancel();
    readiness.ensure_current(&c).unwrap();assert_eq!(server.auth_count.load(Ordering::Acquire),2);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,chats.persistence.client-encrypted
#[tokio::test]
async fn actual_received_auth_denial_revokes_prior_local_publication_and_readiness(){
    let server=Server::open().await;let mut c=server.client().await;let readiness=c.prepare_browser_profile_cache_readiness().unwrap();
    let mut b=begin(&mut c,readiness.clone());let control=b.control();let mut publication=local(&mut b,&mut c,0).await.unwrap();
    server.deny_auth.store(true,Ordering::Release);server.hold_auth.store(true,Ordering::Release);
    let(errors,_received)=mpsc::channel(4);let mut a=c.prepare_owned_chat_monitor(CancellationToken::new(),errors).unwrap();
    let OwnedChatMonitorStartStep::Apply(prepare)=a.next().await.unwrap()else{panic!("prepare")};prepare.apply(&mut c).unwrap();
    let mut pending=Box::pin(a.next());assert!(futures_util::poll!(pending.as_mut()).is_pending());drive_until_held_notice(pending.as_mut(), &server.auth_held).await;
    let mut invalidated=Box::pin(readiness.wait_invalidated());assert!(futures_util::poll!(invalidated.as_mut()).is_pending());
    control.ensure_current(&c).unwrap();server.auth_release.notify_one();
    let OwnedChatMonitorStartStep::Apply(headers)=pending.await.unwrap()else{panic!("headers")};headers.apply(&mut c).unwrap();
    tokio::time::timeout(Duration::from_secs(2),invalidated).await.unwrap();
    assert!(readiness.ensure_current(&c).is_err());assert!(control.ensure_current(&c).is_err());assert!(publication.take(&c,true).is_err());
    assert!(c.browser_credentials.is_none());assert!(c.prepare_browser_profile_cache_readiness().is_err());assert_eq!(server.selected_http.load(Ordering::Acquire),0);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn local_only_absence_never_fetches_and_request_stop_does_not_destroy_readiness(){
    for absence in [1,2]{
        let server=Server::open().await;let mut c=server.client().await;let readiness=c.prepare_browser_profile_cache_readiness().unwrap();
        let mut b=begin(&mut c,readiness.clone());assert!(matches!(local(&mut b,&mut c,absence).await,Err(Error::Offline)));
        b.cancel();readiness.ensure_current(&c).unwrap();let mut next=begin(&mut c,readiness.clone());let mut output=local(&mut next,&mut c,0).await.unwrap();
        assert!(output.take(&c,true).is_ok());assert_eq!(server.selected_http.load(Ordering::Acquire),0);
        readiness.cancel();assert!(output.finish_cold(&c).is_err());assert!(readiness.ensure_current(&c).is_err());
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn profile_credential_key_and_foreign_client_changes_cannot_reuse_local_readiness(){
    for mutation in 0..5{
        let server=Server::open().await;let mut c=server.client().await;let readiness=c.prepare_browser_profile_cache_readiness().unwrap();
        let mut b=begin(&mut c,readiness.clone());let mut publication=local(&mut b,&mut c,0).await.unwrap();
        match mutation{
            0=>c.user["id"]=json!(TEAM),1=>c.browser_credentials.as_mut().unwrap().session_id="changed-original-session".into(),
            2=>c.browser_credentials.as_ref().unwrap().master.invalidate(),3=>c.operation_parent.cancel(),
            _=>{let foreign=server.client().await;assert!(readiness.ensure_current(&foreign).is_err());assert!(publication.take(&foreign,true).is_err());continue},
        }
        assert!(readiness.ensure_current(&c).is_err());assert!(publication.take(&c,true).is_err());
    }
}
