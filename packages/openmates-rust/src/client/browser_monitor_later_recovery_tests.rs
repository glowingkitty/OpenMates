//! Authored UNRUN actual coalescer/scope/resource tests with an explicit inert
//! browser profile. No socket/auth/foreground/physical durability is simulated.
use super::*;
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const CHAT:&str="22222222-2222-4222-8222-222222222222";
fn id(n:u32)->String{format!("{n:08x}-3333-4333-8333-333333333333")}
fn setup()->(Client,Arc<ChatMonitor>,Arc<BrowserOwnedMonitorReadContext>){
    let mut client=super::super::tests::client();
    let monitor=Arc::new(client.retain_browser_monitor_for_test().unwrap());
    monitor.changes.pending.lock().unwrap().refresh=true;
    let scope=Arc::new(crate::client::owned_operation::OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    let context=client.browser_owned_monitor_original_hint_context(scope,monitor.clone(),OWNER,CHAT).unwrap();
    (client,monitor,context)
}
fn offer(monitor:&ChatMonitor,n:u32,full:bool){
    let mut row=json!({"job_id":id(n),"chat_id":CHAT});
    if full{row["chat_key_version"]=json!(1);row["task_id"]=json!(id(n+100));row["stage"]=json!("initial");}
    record_change(&monitor.changes,"metadata_jobs_available",&json!({"jobs":[row]})).unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[tokio::test]
async fn later_actual_offer_wakes_without_growing_or_acknowledging_first_sealed_hint(){
    let(client,monitor,context)=setup();
    assert_eq!(context.recovery_manifest().unwrap().len(),0);
    let waiting=context.wait_later_recovery_hint();tokio::pin!(waiting);
    assert!(matches!(futures_util::poll!(&mut waiting),std::task::Poll::Pending));
    offer(&monitor,1,true); // Deliberately AFTER the first original hint/wait.
    tokio::time::timeout(Duration::from_secs(1),&mut waiting).await.unwrap().unwrap();
    assert!(context.capture_later_recovery_hint(&client).unwrap());
    assert_eq!(context.recovery_manifest().unwrap().len(),0);
    let job=context.later_recovery_offer(CHAT,&BTreeSet::new()).unwrap().unwrap();
    assert_eq!(job.task_id.as_deref(),Some(id(101).as_str()));
    assert_eq!(job.stage.as_deref(),Some("initial"));
    let origin=context.later_recovery_origin(&job).unwrap().unwrap();
    assert!(Arc::ptr_eq(&origin.scope,&context.scope));assert!(Arc::ptr_eq(&origin.monitor,&monitor));
    assert!(monitor.take_pending().unwrap().is_none());
    origin.check_original(&context.scope).unwrap();
    context.scope.observer().cancel();
    assert!(origin.check_original(&context.scope).is_err());
    assert!(monitor.is_valid());assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation,auth.session.authoritative-enforcement
#[tokio::test]
async fn later_keyless_identity_or_changed_job_cannot_become_a_full_offer_or_foreign_scope(){
    let(client,monitor,context)=setup();offer(&monitor,1,false);
    assert!(context.capture_later_recovery_hint(&client).unwrap());
    assert!(context.later_recovery_offer(CHAT,&BTreeSet::new()).unwrap().is_none());
    offer(&monitor,1,true);assert!(context.capture_later_recovery_hint(&client).unwrap());
    let job=context.later_recovery_offer(CHAT,&BTreeSet::new()).unwrap().unwrap();
    let mut wrong=job.clone();wrong.task_id=Some(id(999));assert!(matches!(context.later_recovery_origin(&wrong),Err(Error::Forbidden)));
    let origin=context.later_recovery_origin(&job).unwrap().unwrap();
    let foreign=Arc::new(crate::client::owned_operation::OwnedOperationScope::capture(&client,CancellationToken::new()).unwrap());
    assert!(origin.check_original(&foreign).is_err());origin.check_original(&context.scope).unwrap();
    assert_eq!(context.recovery_manifest().unwrap().len(),0);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[tokio::test]
async fn bounded_later_hint_queue_retains_fifth_actual_pending_and_waits_only_original_cancel(){
    let(client,monitor,context)=setup();
    for n in 1..=MAX_LATER_RECOVERY_HINTS as u32{offer(&monitor,n,true);assert!(context.capture_later_recovery_hint(&client).unwrap());}
    assert_eq!(context.later_recovery.lock().unwrap().len(),MAX_LATER_RECOVERY_HINTS);
    offer(&monitor,99,true);assert!(!context.capture_later_recovery_hint(&client).unwrap());
    assert!(monitor.changes.pending.lock().unwrap().recovery_jobs.snapshot(&BTreeSet::new()).offered_for_chat(CHAT).any(|job|job.job_id==id(99)));
    let waiting=context.wait_later_recovery_hint();tokio::pin!(waiting);
    assert!(matches!(futures_util::poll!(&mut waiting),std::task::Poll::Pending));
    context.scope.observer().cancel();assert!(matches!(waiting.await,Err(Error::Cancelled)));
    assert!(!client.operation_parent.is_cancelled());assert!(monitor.is_valid());
    assert_eq!(context.recovery_manifest().err(),Some(Error::Cancelled));
}
