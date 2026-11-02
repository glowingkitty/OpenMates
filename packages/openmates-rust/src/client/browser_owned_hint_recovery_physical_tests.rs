//! Authored UNRUN genuine profile/hint/AVAILABLE HTTP+WS pending resources.
//! Crypto plans remain DATA; these cases never manufacture native delivery,
//! IndexedDB durability, a shared-commit result or a successful drain.
use super::*;
use crate::client::browser::owned_recovery_phase_tests::{
    genuine_pending_with_remainder_for_test,genuine_metadata_handoff_for_test,
};

async fn pending()->(Client,BrowserOriginalHintRecoveryPendingPersistence,crate::client::browser::owned_recovery_phase_tests::ServerHandle){
    let(client,inner,remainder,handoff,server)=genuine_pending_with_remainder_for_test().await;
    (client,BrowserOriginalHintRecoveryPendingPersistence{inner,remainder,handoff},server)
}
fn assert_same_carry(pending:&BrowserOriginalHintRecoveryPendingPersistence,context:&Arc<Context>,handoff:&Arc<crate::client::OriginalHintRecoveryHandoff>,source:&str){
    assert!(Arc::ptr_eq(&pending.remainder.context,context));assert!(Arc::ptr_eq(&pending.handoff,handoff));assert_eq!(*context.source.lock().unwrap(),source);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn foreign_genuine_client_refusal_retains_original_pending_handoff_and_selected_anchor(){
    let(client,pending,server)=pending().await;let(peer,_peer_handoff,_peer_server)=genuine_metadata_handoff_for_test().await;
    let context=pending.remainder.context.clone();let handoff=pending.handoff.clone();let source=context.source.lock().unwrap().clone();
    let digest=pending.checkpoint().unwrap().digest().unwrap();let requests=server.request_count_for_test();let sockets=server.socket_count_for_test();
    let failure=match pending.prepare_checkpoint(&peer){Ok(_)=>panic!("foreign genuine Client must refuse"),Err(error)=>error};
    assert_eq!(format!("{failure:?}"),"BrowserOriginalHintRecoveryPersistenceFailure");
    let pending=failure.into_pending();assert_same_carry(&pending,&context,&handoff,&source);
    pending.check_original(&client).unwrap();assert_eq!(pending.checkpoint().unwrap().digest().unwrap(),digest);
    handoff.scope_arc().check(&client).unwrap();assert!(!client.operation_parent.is_cancelled());
    assert_eq!(server.request_count_for_test(),requests);assert_eq!(server.socket_count_for_test(),sockets);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn malformed_encrypted_record_failure_retains_actual_pending_and_preserves_original_carry(){
    let(client,pending,server)=pending().await;let context=pending.remainder.context.clone();let handoff=pending.handoff.clone();let source=context.source.lock().unwrap().clone();
    let digest=pending.checkpoint().unwrap().digest().unwrap();let requests=server.request_count_for_test();
    let BrowserOriginalHintRecoveryCheckpointPreparation{inner,carry,..}=pending.prepare_checkpoint(&client).unwrap();
    // Same Core DATA admission as native read forwarding; no native proof.
    let crypto=inner.with_read_data(&client,Some("malformed synthetic private record".into())).unwrap();
    let failure=match (BrowserOriginalHintRecoveryCheckpointCrypto{inner:crypto,carry}).drive().await{Ok(_)=>panic!("malformed encrypted record must refuse"),Err(error)=>error};
    assert_eq!(failure.error_kind(),"protocol");assert_eq!(format!("{failure:?}"),"BrowserOriginalHintRecoveryPersistenceFailure");
    let pending=failure.into_pending();assert_same_carry(&pending,&context,&handoff,&source);pending.check_original(&client).unwrap();
    assert_eq!(pending.checkpoint().unwrap().digest().unwrap(),digest);assert_eq!(server.request_count_for_test(),requests);assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[tokio::test]
async fn negative_crypto_and_write_transfers_keep_same_actual_pending_without_claiming_storage(){
    let(client,pending,server)=pending().await;let context=pending.remainder.context.clone();let handoff=pending.handoff.clone();let source=context.source.lock().unwrap().clone();
    let digest=pending.checkpoint().unwrap().digest().unwrap();let requests=server.request_count_for_test();let sockets=server.socket_count_for_test();
    let BrowserOriginalHintRecoveryCheckpointPreparation{inner,carry,..}=pending.prepare_checkpoint(&client).unwrap();
    let crypto=BrowserOriginalHintRecoveryCheckpointCrypto{inner:inner.with_read_data(&client,None).unwrap(),carry};
    let pending=crypto.into_pending();assert_same_carry(&pending,&context,&handoff,&source);pending.check_original(&client).unwrap();
    let BrowserOriginalHintRecoveryCheckpointPreparation{inner,carry,..}=pending.prepare_checkpoint(&client).unwrap();
    let crypto=BrowserOriginalHintRecoveryCheckpointCrypto{inner:inner.with_read_data(&client,None).unwrap(),carry};
    let write=crypto.drive().await.unwrap();let pending=write.into_pending();
    assert_same_carry(&pending,&context,&handoff,&source);pending.check_original(&client).unwrap();assert_eq!(pending.checkpoint().unwrap().digest().unwrap(),digest);
    assert_eq!(server.request_count_for_test(),requests);assert_eq!(server.socket_count_for_test(),sockets);assert!(!client.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn cancelled_original_mode_retains_wrapper_without_restoring_authority_or_cancelling_parent(){
    let(mut client,pending,server)=pending().await;let context=pending.remainder.context.clone();let handoff=pending.handoff.clone();let source=context.source.lock().unwrap().clone();
    let requests=server.request_count_for_test();client.set_foreground_completion_recovery(false).unwrap();
    let failure=match pending.prepare_checkpoint(&client){Ok(_)=>panic!("cancelled original mode must refuse"),Err(error)=>error};
    assert_eq!(failure.error_kind(),"cancelled");let pending=failure.into_pending();assert_same_carry(&pending,&context,&handoff,&source);
    assert!(pending.check_original(&client).is_err());assert!(pending.checkpoint().is_err());
    handoff.scope_arc().check(&client).unwrap();assert!(!client.operation_parent.is_cancelled());assert_eq!(server.request_count_for_test(),requests);
}
