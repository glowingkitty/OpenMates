//! Authored UNRUN direct Core boundary regressions. Uses the existing genuine
//! local HTTP/WS profile/selected/metadata supplier; no adapter sequencing proof.
use super::*;
use crate::client::browser::owned_recovery_phase_tests::genuine_unissued_metadata_remainder_for_test;
use std::time::Duration;
fn other(job:&CompletionRecoveryJob,n:u32)->CompletionRecoveryJob {
    let mut value=job.clone();value.job_id=format!("{n:08x}-7777-4777-8777-777777777777");value
}
fn queue(remainder:&OwnedBrowserMetadataContinuation,client:&Client,job:&CompletionRecoveryJob){
    let Mode::Incoming(monitor)=&remainder.context.mode else{panic!("same actual original monitor")};
    monitor.queue_metadata_offer_for_test(job).unwrap();
    assert!(monitor.capture_later_recovery_hint(client).unwrap());
}
async fn drive(driver:&mut recovery::OwnedRecoveryDriver,client:&mut Client)->Result<recovery::OwnedRecoveryStep>{
    for _ in 0..300 {match driver.next().await? {
        recovery::OwnedRecoveryStep::Apply(value)=>driver.resume(value.apply(client)?)?,
        recovery::OwnedRecoveryStep::Io(value)=>driver.resume(value.drive().await?)?,
        value=>return Ok(value),
    }}Err(Error::Protocol)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn tampered_later_full_offer_cannot_fall_back_to_first_keyless_handoff(){
    let(client,remainder,job,server)=genuine_unissued_metadata_remainder_for_test(true).await;
    let Mode::Incoming(monitor)=&remainder.context.mode else{panic!("incoming")};
    assert!(monitor.recovery_manifest().unwrap().contains(&job));
    assert!(monitor.recovery_manifest().unwrap().offered_for_chat(&job.chat_id).next().is_none());
    // Actual later notification arrives after the first immutable keyless hint.
    queue(&remainder,&client,&job);
    let before=server.request_count_for_test();let sockets=server.socket_count_for_test();
    let mut tampered=job.clone();tampered.task_id=Some("99999999-9999-4999-8999-999999999999".into());
    assert!(matches!(remainder.recovery_handoff(&client,&tampered),Err(Error::Forbidden)));
    assert!(remainder.context.recovery_issued.lock().unwrap().is_empty());
    let genuine=remainder.recovery_handoff(&client,&job).unwrap();assert!(genuine.later_origin_for_test());
    assert_eq!(server.request_count_for_test(),before);assert_eq!(server.socket_count_for_test(),sockets);
    assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn fifth_direct_core_handoff_refuses_atomically_without_adapter_offer_selection(){
    let(client,remainder,job,server)=genuine_unissued_metadata_remainder_for_test(true).await;
    let mut jobs=Vec::new();for n in 1..=5{let value=other(&job,n);jobs.push(value);}
    let Mode::Incoming(monitor)=&remainder.context.mode else{panic!("incoming")};
    // One genuinely captured whole later origin contains all five full offers.
    for value in &jobs{monitor.queue_metadata_offer_for_test(value).unwrap();}
    assert!(monitor.capture_later_recovery_hint(&client).unwrap());
    let before=server.request_count_for_test();
    let first_four=jobs[..4].iter().map(|job|remainder.recovery_handoff(&client,job).unwrap()).collect::<Vec<_>>();
    assert_eq!(remainder.context.recovery_issued.lock().unwrap().len(),4);
    assert!(matches!(remainder.recovery_handoff(&client,&jobs[4]),Err(Error::Conflict)));
    assert_eq!(remainder.context.recovery_issued.lock().unwrap().len(),4);
    drop(first_four);assert!(matches!(remainder.recovery_handoff(&client,&jobs[4]),Err(Error::Conflict)),"drop never resets issuance");
    assert_eq!(server.request_count_for_test(),before);assert!(!remainder.context.recovery_active.held_for_test());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn exact_unstarted_preparation_drop_releases_only_its_slot_and_preserves_one_use_handoff(){
    let(mut client,remainder,job,server)=genuine_unissued_metadata_remainder_for_test(true).await;
    client.set_foreground_completion_recovery(true).unwrap();
    let first=remainder.recovery_handoff(&client,&job).unwrap();let second_job=other(&job,2);queue(&remainder,&client,&second_job);
    let second=remainder.recovery_handoff(&client,&second_job).unwrap();let before=server.request_count_for_test();
    let prepared=client.prepare_original_owned_recovery(first.clone(),None).unwrap();assert!(remainder.context.recovery_active.held_for_test());
    assert!(matches!(client.prepare_original_owned_recovery(second.clone(),None),Err(Error::Conflict)));
    drop(prepared);assert!(!remainder.context.recovery_active.held_for_test(),"typed preparation never activated a future or IO");
    assert!(matches!(client.prepare_original_owned_recovery(first,None),Err(Error::Conflict)),"first handoff stays one use");
    let next=client.prepare_original_owned_recovery(second,None).unwrap();assert!(remainder.context.recovery_active.held_for_test());drop(next);
    assert!(!remainder.context.recovery_active.held_for_test());assert_eq!(server.request_count_for_test(),before);assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn active_original_driver_refuses_second_until_real_canonical_apply_resume_and_typed_transfer(){
    let(mut client,remainder,job,server)=genuine_unissued_metadata_remainder_for_test(true).await;let remainder=Arc::new(remainder);
    client.set_foreground_completion_recovery(true).unwrap();
    let first=remainder.recovery_handoff(&client,&job).unwrap();let second_job=other(&job,2);queue(&remainder,&client,&second_job);let second=remainder.recovery_handoff(&client,&second_job).unwrap();
    let mut driver=client.prepare_original_owned_recovery(first.clone(),None).unwrap().into_driver().unwrap();
    assert!(remainder.context.recovery_active.held_for_test());assert!(matches!(client.prepare_original_owned_recovery(second,None),Err(Error::Conflict)));
    let terminal=tokio::time::timeout(Duration::from_secs(10),drive(&mut driver,&mut client)).await.unwrap().unwrap();
    let recovery::OwnedRecoveryStep::Canonical(result)=terminal else{panic!("actual canonical result transfer")};
    assert!(!remainder.context.recovery_active.held_for_test());drop(driver);
    // Only actual witnessed adoption advances this SAME original source anchor.
    let progress=BrowserOriginalHintRecoveryAdoption{result,remainder:remainder.clone(),handoff:first}.apply(&mut client).unwrap();progress.ensure_current(&client).unwrap();
    let third_job=other(&job,3);queue(&remainder,&client,&third_job);let third=remainder.recovery_handoff(&client,&third_job).unwrap();
    let before=server.request_count_for_test();let next=client.prepare_original_owned_recovery(third,None).unwrap();assert!(remainder.context.recovery_active.held_for_test());drop(next);
    assert!(!remainder.context.recovery_active.held_for_test());assert_eq!(server.request_count_for_test(),before);assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn held_actual_auth_body_cancel_error_and_abandonment_never_release_original_active_permit(){
    let(mut client,remainder,job,server)=genuine_unissued_metadata_remainder_for_test(true).await;
    client.set_foreground_completion_recovery(true).unwrap();
    let first=remainder.recovery_handoff(&client,&job).unwrap();let second_job=other(&job,2);queue(&remainder,&client,&second_job);let second=remainder.recovery_handoff(&client,&second_job).unwrap();
    server.hold_next_auth_for_test();let mut driver=client.prepare_original_owned_recovery(first,None).unwrap().into_driver().unwrap();let control=driver.control();
    let held=loop{match driver.next().await.unwrap(){
        recovery::OwnedRecoveryStep::Apply(value)=>driver.resume(value.apply(&mut client).unwrap()).unwrap(),
        recovery::OwnedRecoveryStep::Io(io)=>{if io.stage_name_for_test()=="auth_body"{break io;}driver.resume(io.drive().await.unwrap()).unwrap();},
        _=>panic!("held actual auth body precedes terminal"),
    }};
    let pending=held.drive();tokio::pin!(pending);assert!(futures_util::poll!(pending.as_mut()).is_pending());
    assert!(client.prepare_original_owned_recovery(second.clone(),None).is_err());
    control.cancel();assert!(futures_util::poll!(pending.as_mut()).is_pending(),"actual received auth body must drain after cancel");
    assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second.clone(),None).is_err());
    server.release_auth_for_test();let resume=tokio::time::timeout(Duration::from_secs(10),pending).await.unwrap().unwrap();driver.resume(resume).unwrap();
    let recovery::OwnedRecoveryStep::Apply(actual)=driver.next().await.unwrap()else{panic!("same received auth body owns mandatory Apply after cancel")};
    assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second.clone(),None).is_err());
    driver.resume(actual.apply(&mut client).unwrap()).unwrap();
    assert!(tokio::time::timeout(Duration::from_secs(10),drive(&mut driver,&mut client)).await.unwrap().is_err());
    assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second.clone(),None).is_err());drop(driver);
    assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second,None).is_err());assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn actual_pending_checkpoint_and_dropped_checkpoint_preparation_keep_same_active_permit(){
    let(mut client,remainder,job,_server)=genuine_unissued_metadata_remainder_for_test(false).await;let remainder=Arc::new(remainder);
    client.set_foreground_completion_recovery(true).unwrap();let first=remainder.recovery_handoff(&client,&job).unwrap();
    let second_job=other(&job,2);queue(&remainder,&client,&second_job);let second=remainder.recovery_handoff(&client,&second_job).unwrap();
    let mut driver=client.prepare_original_owned_recovery(first.clone(),None).unwrap().into_driver().unwrap();
    let recovery::OwnedRecoveryStep::PendingPersistence(inner)=tokio::time::timeout(Duration::from_secs(10),drive(&mut driver,&mut client)).await.unwrap().unwrap()else{panic!("actual AVAILABLE checkpoint boundary")};
    assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second.clone(),None).is_err());
    drop(driver);assert!(remainder.context.recovery_active.held_for_test());
    let pending=BrowserOriginalHintRecoveryPendingPersistence{inner,remainder:remainder.clone(),handoff:first};let prepared=pending.prepare_checkpoint(&client).unwrap();
    assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second.clone(),None).is_err());
    drop(prepared);assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second,None).is_err());assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_finite_presocket_deferred_transfer_releases_permit_without_claim_or_parent_reset(){
    let(mut client,remainder,mut job,server)=genuine_unissued_metadata_remainder_for_test(true).await;
    client.set_foreground_completion_recovery(true).unwrap();job.chat_key_version=2;queue(&remainder,&client,&job);
    let first=remainder.recovery_handoff(&client,&job).unwrap();let mut driver=client.prepare_original_owned_recovery(first,None).unwrap().into_driver().unwrap();
    assert!(remainder.context.recovery_active.held_for_test());
    assert!(matches!(tokio::time::timeout(Duration::from_secs(10),drive(&mut driver,&mut client)).await.unwrap().unwrap(),recovery::OwnedRecoveryStep::Deferred));
    assert!(!remainder.context.recovery_active.held_for_test());assert_eq!(server.socket_count_for_test(),0,"typed version deferral is before any claim socket");drop(driver);
    let mut next_job=other(&job,2);next_job.chat_key_version=1;queue(&remainder,&client,&next_job);let next=remainder.recovery_handoff(&client,&next_job).unwrap();
    let prepared=client.prepare_original_owned_recovery(next,None).unwrap();assert!(remainder.context.recovery_active.held_for_test());drop(prepared);
    assert!(!remainder.context.recovery_active.held_for_test());assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn dropping_started_actual_auth_body_future_keeps_context_permit_even_after_late_peer_completion(){
    let(mut client,remainder,job,server)=genuine_unissued_metadata_remainder_for_test(true).await;
    client.set_foreground_completion_recovery(true).unwrap();let first=remainder.recovery_handoff(&client,&job).unwrap();
    let second_job=other(&job,2);queue(&remainder,&client,&second_job);let second=remainder.recovery_handoff(&client,&second_job).unwrap();
    server.hold_next_auth_for_test();let mut driver=client.prepare_original_owned_recovery(first,None).unwrap().into_driver().unwrap();
    let held=loop{match driver.next().await.unwrap(){
        recovery::OwnedRecoveryStep::Apply(value)=>driver.resume(value.apply(&mut client).unwrap()).unwrap(),
        recovery::OwnedRecoveryStep::Io(io)=>{if io.stage_name_for_test()=="auth_body"{break io;}driver.resume(io.drive().await.unwrap()).unwrap();},
        _=>panic!("actual auth body before terminal"),
    }};
    {let pending=held.drive();tokio::pin!(pending);assert!(futures_util::poll!(pending.as_mut()).is_pending());}
    assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second.clone(),None).is_err());
    drop(driver);server.release_auth_for_test();tokio::task::yield_now().await;
    assert!(remainder.context.recovery_active.held_for_test(),"late response or last runtime Drop is not a typed settled transfer");
    assert!(client.prepare_original_owned_recovery(second,None).is_err());assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn missing_later_full_offer_refuses_direct_handoff_until_a_distinct_genuine_full_origin_arrives(){
    let(client,remainder,job,server)=genuine_unissued_metadata_remainder_for_test(true).await;
    let Mode::Incoming(monitor)=&remainder.context.mode else{panic!("incoming")};
    monitor.queue_metadata_identity_for_test(&job).unwrap();assert!(monitor.capture_later_recovery_hint(&client).unwrap());
    let before=server.request_count_for_test();
    assert!(matches!(remainder.recovery_handoff(&client,&job),Err(Error::Forbidden)));
    assert!(remainder.context.recovery_issued.lock().unwrap().is_empty());
    // Capture a distinct real full notification, without growing the keyless
    // first/later original manifests or accepting supplied DTO authority.
    queue(&remainder,&client,&job);let genuine=remainder.recovery_handoff(&client,&job).unwrap();
    assert!(genuine.later_origin_for_test());assert_eq!(remainder.context.recovery_issued.lock().unwrap().len(),1);
    assert_eq!(server.request_count_for_test(),before);assert!(!client.operation_parent.is_cancelled());
}

/// Poll only the original owned driver until its real terminal socket is
/// registered. Dropping this borrowed next() wrapper leaves the SAME policy
/// future owned inside driver; no IO task, socket or completion is substituted.
async fn reach_held_close(driver:&mut recovery::OwnedRecoveryDriver,client:&mut Client,entered:&mut tokio::sync::oneshot::Receiver<()>){
    for _ in 0..300 {
        let step={
            let next=driver.next();tokio::pin!(next);
            tokio::select!{biased;value=&mut *entered=>{value.unwrap();return;},value=&mut next=>value.unwrap()}
        };
        match step {
            recovery::OwnedRecoveryStep::Apply(value)=>driver.resume(value.apply(client).unwrap()).unwrap(),
            recovery::OwnedRecoveryStep::Io(value)=>driver.resume(value.drive().await.unwrap()).unwrap(),
            _=>panic!("typed terminal cannot precede held actual socket close"),
        }
    }
    panic!("bounded actual close registration required")
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn held_registered_original_socket_refuses_successor_until_real_close_and_typed_terminal_transfer(){
    let(mut client,remainder,job,server)=genuine_unissued_metadata_remainder_for_test(true).await;let remainder=Arc::new(remainder);
    client.set_foreground_completion_recovery(true).unwrap();let first=remainder.recovery_handoff(&client,&job).unwrap();
    let second_job=other(&job,2);queue(&remainder,&client,&second_job);let second=remainder.recovery_handoff(&client,&second_job).unwrap();
    let mut driver=client.prepare_original_owned_recovery(first.clone(),None).unwrap().into_driver().unwrap();let control=driver.control();let(mut entered,release)=control.hold_outcome_close_for_test();
    tokio::time::timeout(Duration::from_secs(10),reach_held_close(&mut driver,&mut client,&mut entered)).await.unwrap();
    assert_eq!(server.socket_count_for_test(),1);assert!(control.outcome_socket_retained_for_test().await);assert!(remainder.context.recovery_active.held_for_test());
    assert!(client.prepare_original_owned_recovery(second,None).is_err());
    {let pending=driver.next();tokio::pin!(pending);assert!(futures_util::poll!(pending.as_mut()).is_pending());}
    // This releases only a test scheduler hold. The SAME registered production
    // socket must still execute its actual close and original typed Apply/Resume.
    release.send(()).unwrap();let recovery::OwnedRecoveryStep::Canonical(result)=tokio::time::timeout(Duration::from_secs(10),drive(&mut driver,&mut client)).await.unwrap().unwrap()else{panic!("actual canonical typed transfer")};
    assert!(!control.outcome_socket_retained_for_test().await);assert!(!remainder.context.recovery_active.held_for_test());
    let progress=BrowserOriginalHintRecoveryAdoption{result,remainder:remainder.clone(),handoff:first}.apply(&mut client).unwrap();progress.ensure_current(&client).unwrap();
    let third_job=other(&job,3);queue(&remainder,&client,&third_job);let third=remainder.recovery_handoff(&client,&third_job).unwrap();
    let next=client.prepare_original_owned_recovery(third,None).unwrap();assert!(remainder.context.recovery_active.held_for_test());drop(next);
    assert!(!remainder.context.recovery_active.held_for_test());assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn cancel_during_registered_real_socket_close_cannot_select_drop_it_or_release_the_context_permit(){
    let(mut client,remainder,job,_server)=genuine_unissued_metadata_remainder_for_test(true).await;
    client.set_foreground_completion_recovery(true).unwrap();let first=remainder.recovery_handoff(&client,&job).unwrap();
    let second_job=other(&job,2);queue(&remainder,&client,&second_job);let second=remainder.recovery_handoff(&client,&second_job).unwrap();
    let mut driver=client.prepare_original_owned_recovery(first,None).unwrap().into_driver().unwrap();let control=driver.control();let(mut entered,release)=control.hold_outcome_close_for_test();
    tokio::time::timeout(Duration::from_secs(10),reach_held_close(&mut driver,&mut client,&mut entered)).await.unwrap();
    control.cancel();assert!(control.outcome_socket_retained_for_test().await);assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second.clone(),None).is_err());
    {let pending=driver.next();tokio::pin!(pending);assert!(futures_util::poll!(pending.as_mut()).is_pending(),"cancel cannot bypass the same actual close await");}
    release.send(()).unwrap();assert!(tokio::time::timeout(Duration::from_secs(10),drive(&mut driver,&mut client)).await.unwrap().is_err());
    assert!(!control.outcome_socket_retained_for_test().await,"actual close drained even after negative cancellation");
    assert!(remainder.context.recovery_active.held_for_test(),"physical close without original typed terminal transfer is not settlement");
    drop(driver);assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second,None).is_err());assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn genuine_broken_peer_close_error_retains_original_socket_and_context_permit_without_rearm(){
    let(mut client,remainder,job,server)=genuine_unissued_metadata_remainder_for_test(true).await;
    client.set_foreground_completion_recovery(true).unwrap();let first=remainder.recovery_handoff(&client,&job).unwrap();
    let second_job=other(&job,2);queue(&remainder,&client,&second_job);let second=remainder.recovery_handoff(&client,&second_job).unwrap();
    let mut driver=client.prepare_original_owned_recovery(first,None).unwrap().into_driver().unwrap();let control=driver.control();let(mut entered,release)=control.hold_outcome_close_for_test();
    tokio::time::timeout(Duration::from_secs(10),reach_held_close(&mut driver,&mut client,&mut entered)).await.unwrap();
    assert!(control.outcome_socket_retained_for_test().await);server.break_recovery_socket_for_test();
    // Consume the SAME real socket's EOF/protocol failure after the actual peer
    // closes TCP without a WebSocket close. No fabricated close result/event.
    tokio::time::timeout(Duration::from_secs(10),control.observe_outcome_transport_error_for_test()).await.unwrap().unwrap();
    assert!(remainder.context.recovery_active.held_for_test());release.send(()).unwrap();
    assert!(matches!(tokio::time::timeout(Duration::from_secs(10),drive(&mut driver,&mut client)).await.unwrap(),Err(Error::Offline)));
    assert!(control.outcome_socket_retained_for_test().await,"actual failed close remains an owned resource");assert!(remainder.context.recovery_active.held_for_test());
    assert!(client.prepare_original_owned_recovery(second.clone(),None).is_err());drop(driver);
    assert!(control.outcome_socket_retained_for_test().await);assert!(remainder.context.recovery_active.held_for_test());assert!(client.prepare_original_owned_recovery(second,None).is_err());assert!(!client.operation_parent.is_cancelled());
}
