//! Authored UNRUN genuine native profile/hint/foreground HTTP/WS supplier.
//! Its map cache protocol fixture is NOT native IDB/store/drain acceptance.
use super::*;
use crate::client::browser::owned_recovery_phase_tests::genuine_terminal_with_remainder_for_test;
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_same_original_foreground_result_alone_can_advance_selected_anchor_but_cannot_complete_local_persistence_or_hint(){
    let(mut c,remainder,handoff,result,_server)=genuine_terminal_with_remainder_for_test().await;
    let physical_before=remainder.data.readback["metadata"].clone();let context=remainder.context.clone();let before=context.source.lock().unwrap().clone();
    assert!(remainder.check_original(&c).is_err(),"actual recovery mutated the original B row");
    assert_ne!(source_stamp(&c,&context.chat).unwrap(),before);
    let progress=BrowserOriginalHintRecoveryAdoption{result,remainder,handoff}.apply(&mut c).unwrap();
    assert!(Arc::ptr_eq(&context,&progress.remainder.context));progress.ensure_current(&c).unwrap();
    assert_eq!(*context.source.lock().unwrap(),source_stamp(&c,&context.chat).unwrap());
    assert_eq!(progress.kind(),"recovery_pending_local_persistence");
    // Source adoption cannot silently call physical persistence complete. The
    // exact previous selected store image remains retained for real next CAS.
    assert_eq!(progress.remainder.data.readback["metadata"],physical_before);
    assert_ne!(progress.remainder.data.readback["metadata"],*c.chats.get(&context.chat).unwrap());
    assert_eq!(progress.receipt.job_id,progress.handoff.job().job_id);assert!(progress.artifacts.is_none(),"metadata is not a transcript artifact");
    c.operation_parent.cancel();assert!(progress.ensure_current(&c).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_result_cannot_adopt_under_another_genuine_clients_handoff_or_change_original_anchor(){
    let(mut c,remainder,_original,result,_server)=genuine_terminal_with_remainder_for_test().await;
    let(_peer,_peer_remainder,foreign,_peer_result,_peer_server)=genuine_terminal_with_remainder_for_test().await;
    let context=remainder.context.clone();let before=context.source.lock().unwrap().clone();
    assert!(BrowserOriginalHintRecoveryAdoption{result,remainder,handoff:foreign}.apply(&mut c).is_err());
    assert_eq!(*context.source.lock().unwrap(),before);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn unrelated_actual_row_mutation_after_real_terminal_cannot_be_adopted_as_owned_transition(){
    let(mut c,remainder,handoff,result,_server)=genuine_terminal_with_remainder_for_test().await;
    let context=remainder.context.clone();let before=context.source.lock().unwrap().clone();
    let id=handoff.job().chat_id.clone();c.chats.get_mut(&id).unwrap()["metadata_v"]=json!(999);
    assert!(BrowserOriginalHintRecoveryAdoption{result,remainder,handoff}.apply(&mut c).is_err());
    assert_eq!(*context.source.lock().unwrap(),before);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn original_parent_revocation_after_real_terminal_refuses_anchor_adoption_without_restoring_authority(){
    let(mut c,remainder,handoff,result,_server)=genuine_terminal_with_remainder_for_test().await;
    let context=remainder.context.clone();let before=context.source.lock().unwrap().clone();c.operation_parent.cancel();
    assert!(BrowserOriginalHintRecoveryAdoption{result,remainder,handoff}.apply(&mut c).is_err());
    assert_eq!(*context.source.lock().unwrap(),before);
}
