//! Actual personal master-wrapper selection/AES and original queued cache Apply.
//! Real expiry clock/server DATA; no fake clock, admission or publication proof.
use super::*;
use crate::client::browser::owned_recovery_phase_tests::genuine_metadata_handoff_for_test;
use tokio::time::{timeout,Duration};
async fn held_cache(driver:&mut OwnedRecoveryDriver,client:&mut Client)->Result<OwnedRecoveryApply>{
    for _ in 0..200{match driver.next().await?{
        OwnedRecoveryStep::Apply(phase) if phase.is_cache_key_for_test()=>return Ok(phase),
        OwnedRecoveryStep::Apply(phase)=>driver.resume(phase.apply(client)?)?,
        OwnedRecoveryStep::Io(io)=>driver.resume(io.drive().await?)?,
        _=>return Err(Error::Protocol),
    }}Err(Error::Protocol)
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn actual_personal_wrapper_expiring_while_cache_apply_is_queued_cannot_publish_row_or_wrappers(){
    let(mut client,handoff,server)=genuine_metadata_handoff_for_test().await;client.set_foreground_completion_recovery(true).unwrap();let scope=handoff.scope_arc();let expiry=now_ms()/1000+10;server.personal_wrapper_expiry_for_test(expiry);
    let mut driver=client.prepare_original_owned_recovery(handoff,None).unwrap().into_driver().unwrap();let held=timeout(Duration::from_secs(8),held_cache(&mut driver,&mut client)).await.unwrap().unwrap();
    let before=client.chats.get("22222222-2222-4222-8222-222222222222").cloned();let wrappers=client.wrappers.clone();
    crate::platform::time::sleep(Duration::from_millis(expiry.saturating_mul(1000).saturating_sub(now_ms()).saturating_add(1))).await;
    driver.resume(held.apply(&mut client).unwrap()).unwrap();assert!(matches!(driver.next().await.unwrap(),OwnedRecoveryStep::Deferred));
    assert_eq!(client.chats.get("22222222-2222-4222-8222-222222222222"),before.as_ref());assert_eq!(client.wrappers,wrappers);assert_eq!(server.socket_count_for_test(),0);assert!(!client.operation_parent.is_cancelled());scope.check(&client).unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn actual_still_valid_personal_selected_wrapper_publishes_and_reaches_real_pending(){
    let(mut client,handoff,server)=genuine_metadata_handoff_for_test().await;client.set_foreground_completion_recovery(true).unwrap();server.personal_wrapper_expiry_for_test(now_ms()/1000+60);
    let mut driver=client.prepare_original_owned_recovery(handoff,None).unwrap().into_driver().unwrap();let held=held_cache(&mut driver,&mut client).await.unwrap();driver.resume(held.apply(&mut client).unwrap()).unwrap();
    let pending=timeout(Duration::from_secs(10),async{for _ in 0..200{match driver.next().await.unwrap(){OwnedRecoveryStep::Apply(phase)=>driver.resume(phase.apply(&mut client).unwrap()).unwrap(),OwnedRecoveryStep::Io(io)=>driver.resume(io.drive().await.unwrap()).unwrap(),OwnedRecoveryStep::PendingPersistence(pending)=>return pending,_=>panic!("real valid selected wrapper must reach pending")}}panic!("bounded phases")}).await.unwrap();
    pending.check_original(&client).unwrap();assert_eq!(client.wrappers.len(),1);assert_eq!(client.wrappers[0]["key_type"],"master");assert_eq!(server.socket_count_for_test(),1);assert!(!client.operation_parent.is_cancelled());
}
