//! Actual browser restore/profile/hint fixture and actual owned send future.
//! Negative observation corruption is fault injection, NOT valid admission or
//! remote attempt proof. No running/phase/socket/terminal flags are fabricated.
use super::*;
use crate::client::browser::owned_recovery_phase_tests::genuine_metadata_handoff_for_test;
fn poison(observation:&Arc<std::sync::Mutex<ScopedSendObservation>>){
    let _=std::panic::catch_unwind(std::panic::AssertUnwindSafe(||{let _held=observation.lock().unwrap();panic!("synthetic observation lock failure");}));
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_pre_effect_return_with_poisoned_observation_yields_one_correlated_negative_refusal_and_keeps_peer(){
    let(mut client,peer,_server)=genuine_metadata_handoff_for_test().await;let request=CancellationToken::new();let prepared=client.prepare_owned_saved_send(None,request.clone()).unwrap();request.cancel();let(updates,_)=mpsc::channel(4);let mut driver=client.start_owned_saved_send(prepared,"synthetic private A",updates).unwrap();let control=driver.control();
    poison(client.scoped_send_observation.as_ref().unwrap());assert!(driver.take_returned_refusal().is_none());assert!(matches!(driver.drive_next().await,Err(Error::Cancelled)));
    let refusal=driver.take_returned_refusal().expect("actual future returned and no original socket/started phase");assert_eq!(refusal.consume_for(&control).unwrap(),OwnedSavedSendRefusalReason::ObservationUnavailable);assert!(driver.take_returned_refusal().is_none());assert!(matches!(driver.drive_next().await,Err(Error::Cancelled)));
    peer.scope_arc().check(&client).unwrap();assert!(!client.operation_parent.is_cancelled());assert!(!client.operation_cancel.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity,sync.client.shared-rust-policy
#[tokio::test]
async fn corrupted_unverifiable_admission_is_finite_refusal_not_a_terminal_disposition_or_remote_attempt_proof(){
    let(mut client,peer,_server)=genuine_metadata_handoff_for_test().await;let request=CancellationToken::new();let prepared=client.prepare_owned_saved_send(None,request.clone()).unwrap();request.cancel();let(updates,_)=mpsc::channel(4);let mut driver=client.start_owned_saved_send(prepared,"synthetic private A",updates).unwrap();let control=driver.control();
    // Deliberately corrupt the actual observation into an impossible negative
    // state. This does NOT represent a real wire attempt/admission.
    {let mut actual=client.scoped_send_observation.as_ref().unwrap().lock().unwrap();actual.attempted=true;assert!(actual.admission.is_none());}
    assert!(matches!(driver.drive_next().await,Err(Error::Protocol)));let refusal=driver.take_returned_refusal().unwrap();assert_eq!(refusal.consume_for(&control).unwrap(),OwnedSavedSendRefusalReason::AdmissionUnverifiable);assert!(driver.take_returned_refusal().is_none());peer.scope_arc().check(&client).unwrap();assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
#[tokio::test]
async fn actual_refusal_cannot_be_consumed_for_an_equal_owner_genuine_peer_control(){
    let(mut a,_ha,_sa)=genuine_metadata_handoff_for_test().await;let(mut b,_hb,_sb)=genuine_metadata_handoff_for_test().await;
    let ra=CancellationToken::new();let pa=a.prepare_owned_saved_send(None,ra.clone()).unwrap();ra.cancel();let(ua,_)=mpsc::channel(4);let mut da=a.start_owned_saved_send(pa,"A",ua).unwrap();poison(a.scoped_send_observation.as_ref().unwrap());assert!(da.drive_next().await.is_err());let refusal=da.take_returned_refusal().unwrap();
    let rb=CancellationToken::new();let pb=b.prepare_owned_saved_send(None,rb.clone()).unwrap();rb.cancel();let(ub,_)=mpsc::channel(4);let mut db=b.start_owned_saved_send(pb,"B",ub).unwrap();let cb=db.control();assert!(matches!(refusal.consume_for(&cb),Err(Error::Cancelled)));
    let OwnedSavedSendStep::Terminal(terminal)=db.drive_next().await.unwrap()else{panic!("ordinary actual peer terminal unchanged")};b.finish_owned_saved_send(terminal).unwrap();assert!(!b.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,auth.session.authoritative-enforcement,sync.client.shared-rust-policy
#[tokio::test]
async fn outstanding_and_abandoned_started_apply_never_become_terminal_or_returned_refusal_proof(){
    for corrupt in [false,true] {
        let(mut client,peer,server)=genuine_metadata_handoff_for_test().await;let prepared=client.prepare_owned_saved_send(None,CancellationToken::new()).unwrap();let(updates,_)=mpsc::channel(8);let mut driver=client.start_owned_saved_send(prepared,"synthetic private A",updates).unwrap();let control=driver.control();
        let OwnedSavedSendStep::Apply(phase)=driver.drive_next().await.unwrap()else{panic!("actual original Prepare")};assert!(matches!(driver.drive_next().await,Err(Error::Conflict)));assert!(driver.take_returned_refusal().is_none());
        let observation=client.scoped_send_observation.as_ref().unwrap().clone();let before=server.request_count_for_test();server.hold_next_auth_for_test();
        let mut applied=Box::pin(client.apply_owned_saved_send_step(phase));
        tokio::time::timeout(std::time::Duration::from_secs(5),async{loop{tokio::select!{value=applied.as_mut()=>{let _=value;panic!("actual held auth body must remain pending")},_=tokio::task::yield_now()=>{if server.request_count_for_test()>before{break}}}}}).await.unwrap();
        // Abandon a genuinely STARTED Client/HTTP future. Its Drop is not
        // completion, with OR without an independently poisoned observation.
        drop(applied);control.cancel();if corrupt{poison(&observation);}
        assert!(matches!(driver.drive_next().await,Err(Error::Cancelled)));assert!(driver.take_returned_refusal().is_none());
        assert!(client.prepare_owned_saved_send(None,CancellationToken::new()).is_err());peer.scope_arc().check(&client).unwrap();assert!(!client.operation_parent.is_cancelled());server.release_auth_for_test();
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_return_from_untracked_transport_preparation_is_held_even_without_observation_corruption(){
    for corrupt in [false,true] {
        let(mut client,peer,server)=genuine_metadata_handoff_for_test().await;let prepared=client.prepare_owned_saved_send(None,CancellationToken::new()).unwrap();let(updates,_)=mpsc::channel(8);let mut driver=client.start_owned_saved_send(prepared,"synthetic private A",updates).unwrap();let control=driver.control();
        let OwnedSavedSendStep::Apply(phase)=driver.drive_next().await.unwrap()else{panic!("actual original Prepare")};let before=server.request_count_for_test();server.hold_next_auth_for_test();
        let mut applied=Box::pin(client.apply_owned_saved_send_step(phase));
        tokio::time::timeout(std::time::Duration::from_secs(5),async{loop{tokio::select!{value=applied.as_mut()=>{let _=value;panic!("actual auth body must remain pending")},_=tokio::task::yield_now()=>{if server.request_count_for_test()>before{break}}}}}).await.unwrap();
        control.cancel();server.release_auth_for_test();let resumed=applied.await.unwrap();driver.resume(resumed).unwrap();
        if corrupt{poison(client.scoped_send_observation.as_ref().unwrap());}
        // The original helper actually returned, but its generic Err cannot
        // establish whether an unregistered socket was created/closed inside.
        assert!(matches!(driver.drive_next().await,Err(Error::Cancelled)));assert!(driver.take_returned_refusal().is_none());
        assert!(client.prepare_owned_saved_send(None,CancellationToken::new()).is_err());peer.scope_arc().check(&client).unwrap();assert!(!client.operation_parent.is_cancelled());
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity,sync.client.shared-rust-policy
#[tokio::test]
async fn unstarted_phase_drop_only_yields_refusal_after_the_actual_original_future_returned(){
    let(mut client,peer,_server)=genuine_metadata_handoff_for_test().await;let prepared=client.prepare_owned_saved_send(None,CancellationToken::new()).unwrap();let(updates,_)=mpsc::channel(8);let mut driver=client.start_owned_saved_send(prepared,"synthetic private A",updates).unwrap();let control=driver.control();
    let OwnedSavedSendStep::Apply(phase)=driver.drive_next().await.unwrap()else{panic!("actual original Prepare")};drop(phase);poison(client.scoped_send_observation.as_ref().unwrap());
    assert!(driver.take_returned_refusal().is_none(),"Drop alone is never proof");assert!(matches!(driver.drive_next().await,Err(Error::Cancelled)));
    assert_eq!(driver.take_returned_refusal().unwrap().consume_for(&control).unwrap(),OwnedSavedSendRefusalReason::ObservationUnavailable);
    assert!(driver.take_returned_refusal().is_none());assert!(client.prepare_owned_saved_send(None,CancellationToken::new()).is_err());peer.scope_arc().check(&client).unwrap();
}
