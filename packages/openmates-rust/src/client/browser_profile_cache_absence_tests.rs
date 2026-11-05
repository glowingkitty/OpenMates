//! Authored UNRUN actual admitted Client/auth HTTP plus inert native IO cases.
//! Native ledger/factory/Host/page retry mapping remains SourceNative/browser CI.
use super::*;
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn only_actual_supported_local_absence_after_return_and_io_quiescence_can_be_consumed_once(){
    for absence in [1,2]{
        let server=Server::open().await;let mut c=server.client().await;let readiness=c.prepare_browser_profile_cache_readiness().unwrap();
        server.hold_auth.store(true,Ordering::Release);let(errors,_received)=mpsc::channel(4);let mut a=c.prepare_owned_chat_monitor(CancellationToken::new(),errors).unwrap();
        let OwnedChatMonitorStartStep::Apply(prepare)=a.next().await.unwrap()else{panic!("actual auth prepare")};prepare.apply(&mut c).unwrap();
        let mut auth=Box::pin(a.next());assert!(futures_util::poll!(auth.as_mut()).is_pending());drive_until_held_notice(auth.as_mut(), &server.auth_held).await;
        let mut b=begin(&mut c,readiness.clone());assert!(b.take_profile_cache_absence(&c).is_err());
        assert!(matches!(local(&mut b,&mut c,absence).await,Err(Error::Offline)));
        assert!(b.terminal_observer().terminal().unwrap().is_quiescent());
        let mut observed=b.take_profile_cache_absence(&c).unwrap();assert!(b.take_profile_cache_absence(&c).is_err());observed.ensure_current(&c).unwrap();
        observed.consume(&c).unwrap();assert!(observed.consume(&c).is_err());assert!(observed.ensure_current(&c).is_err());
        // Consumed selection DATA still cannot grant cold HTTP under retired
        // general owner guards or manufacture a new monitor/private context.
        assert!(!c.browser_authority.as_ref().unwrap().owner_guards);
        assert!(c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,CHAT,Default::default(),host(),20,true).is_err());
        assert_eq!(server.selected_http.load(Ordering::Acquire),0);assert_eq!(server.sockets.load(Ordering::Acquire),0);
        server.auth_release.notify_one();let OwnedChatMonitorStartStep::Apply(headers)=auth.await.unwrap()else{panic!("actual headers")};headers.apply(&mut c).unwrap();
        let OwnedChatMonitorStartStep::Apply(body)=a.next().await.unwrap()else{panic!("actual body")};body.apply(&mut c).unwrap();
        // A fresh ordinary operation still performs its original real guards.
        let cold=c.begin_owned_browser_cold_message_read(CancellationToken::new(),OWNER,CHAT,Default::default(),host(),20,true).unwrap();cold.cancel();a.control().cancel();
        readiness.ensure_current(&c).unwrap();assert!(c.completion_recovery_mode.is_none());
    }
}
async fn failed_io(c:&mut Client,driver:&mut OwnedBrowserReadDriver,corrupt:bool)->Result<OwnedBrowserReadPublication>{
    for _ in 0..20{match driver.next().await?{
        OwnedBrowserReadStep::Apply(phase)=>phase.apply(c)?,
        OwnedBrowserReadStep::IO(io)=>io.execute(move|_|async move{if corrupt{Ok("{}".into())}else{Err(Error::Offline)}}).await?.apply(c)?,
        OwnedBrowserReadStep::Selected(publication)=>return Ok(publication),_=>return Err(Error::Protocol),
    }}Err(Error::Protocol)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn io_offline_corruption_and_success_are_not_an_absence_witness_even_if_core_io_settled(){
    for corrupt in [false,true]{
        let server=Server::open().await;let mut c=server.client().await;let readiness=c.prepare_browser_profile_cache_readiness().unwrap();let mut b=begin(&mut c,readiness);
        let result=failed_io(&mut c,&mut b,corrupt).await;
        if corrupt{assert!(matches!(result,Err(Error::Protocol)))}else{assert!(matches!(result,Err(Error::Offline)))}
        assert!(b.terminal_observer().terminal().unwrap().is_quiescent());assert!(b.take_profile_cache_absence(&c).is_err());assert_eq!(server.selected_http.load(Ordering::Acquire),0);
    }
    let server=Server::open().await;let mut c=server.client().await;let readiness=c.prepare_browser_profile_cache_readiness().unwrap();let mut b=begin(&mut c,readiness);
    let mut publication=local(&mut b,&mut c,0).await.unwrap();assert!(publication.take(&c,true).is_ok());assert!(b.take_profile_cache_absence(&c).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn original_request_profile_master_and_foreign_client_still_fence_held_absence_consumption(){
    for mutation in 0..4{
        let server=Server::open().await;let mut c=server.client().await;let readiness=c.prepare_browser_profile_cache_readiness().unwrap();let mut b=begin(&mut c,readiness.clone());
        assert!(matches!(local(&mut b,&mut c,1).await,Err(Error::Offline)));let mut observed=b.take_profile_cache_absence(&c).unwrap();
        match mutation{
            0=>b.cancel(),1=>c.user["id"]=json!(TEAM),2=>c.browser_credentials.as_ref().unwrap().master.invalidate(),
            _=>{let foreign=server.client().await;assert!(observed.consume(&foreign).is_err());observed.ensure_current(&c).unwrap();observed.consume(&c).unwrap();continue},
        }
        assert!(observed.ensure_current(&c).is_err());assert!(observed.consume(&c).is_err());
        if mutation==0{readiness.ensure_current(&c).unwrap();}
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn started_native_io_must_really_settle_and_abandoned_io_can_never_create_absence_or_terminal(){
    let server=Server::open().await;let mut c=server.client().await;let readiness=c.prepare_browser_profile_cache_readiness().unwrap();let mut b=begin(&mut c,readiness.clone());
    let io=loop{match b.next().await.unwrap(){OwnedBrowserReadStep::Apply(phase)=>phase.apply(&mut c).unwrap(),OwnedBrowserReadStep::IO(io)=>break io,_=>panic!("first actual native read")}};
    let started=Arc::new(AtomicBool::new(false));let mark=started.clone();let mut pending=Box::pin(io.execute(move|_|async move{mark.store(true,Ordering::Release);std::future::pending::<Result<String>>().await}));
    assert!(futures_util::poll!(pending.as_mut()).is_pending());assert!(started.load(Ordering::Acquire));
    assert!(b.take_profile_cache_absence(&c).is_err());assert!(b.terminal_observer().terminal().is_none());
    drop(pending);assert!(b.next().await.is_err());assert!(b.terminal_observer().terminal().is_none());assert!(b.take_profile_cache_absence(&c).is_err());
    readiness.ensure_current(&c).unwrap();assert!(!c.operation_parent.is_cancelled());assert_eq!(server.selected_http.load(Ordering::Acquire),0);
}
