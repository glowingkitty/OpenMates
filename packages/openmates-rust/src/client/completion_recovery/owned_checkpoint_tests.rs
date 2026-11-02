//! Genuine original Pending/profile/crypto fixture. Ciphertext IO plans and
//! readback DATA checks below are NOT trusted native IDB/port completion proof.
use super::*;
use crate::client::browser::owned_recovery_phase_tests::genuine_pending_for_test;
fn record(next:&str)->Record{serde_json::from_str(next).unwrap()}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,chats.persistence.client-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn genuine_pending_uses_actual_master_and_whole_encrypted_record_without_minting_storage_receipt(){
    let(c,pending,_server)=genuine_pending_for_test().await;
    let prepared=pending.prepare_checkpoint_persistence(&c).unwrap();
    let read:Value=serde_json::from_str(&prepared.read_effect(&c).unwrap()).unwrap();assert_eq!(read["operation"],"read");assert_eq!(read["owner"],prepared.checkpoint.owner_id());
    let write=prepared.with_read_data(&c,None).unwrap().drive().await.unwrap();
    let effect:Value=serde_json::from_str(&write.write_effect(&c).unwrap()).unwrap();assert_eq!(effect["operation"],"compare_and_put");assert!(effect["expected"].is_null());assert_eq!(write.namespace(),"openmates_rust_pending_recovery_v1");
    let next=effect["next"].as_str().unwrap();assert!(next.len()<=MAX_RECORD_BYTES);let record=record(next);assert_eq!(record.version,1);
    let bytes=write.prepared.master.decrypt_bytes(&record.ciphertext).await.unwrap();let map=pending_map(Some(serde_json::from_slice(&bytes).unwrap())).unwrap();assert_eq!(map.len(),1);assert_eq!(map.values().next().unwrap().digest().unwrap(),write.prepared.digest);
    write.verify_readback_data(next).await.unwrap();
    // Unit DATA verification returns (), never a native durable/commit resource.
    assert!(write.prepared.pending.stage.is_some());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,chats.persistence.client-encrypted
#[tokio::test]
async fn whole_readback_mismatch_is_refused_even_if_target_checkpoint_digest_is_unchanged(){
    let(c,pending,_server)=genuine_pending_for_test().await;let write=pending.prepare_checkpoint_persistence(&c).unwrap().with_read_data(&c,None).unwrap().drive().await.unwrap();
    let changed=format!(" {}",write.next);assert!(matches!(write.verify_readback_data(&changed).await,Err(Error::Conflict)));
    let mut outer:Value=serde_json::from_str(&write.next).unwrap();outer["extra"]=json!("synthetic hostile extra");assert!(decode_record(&outer.to_string()).is_err());assert!(write.prepared.pending.stage.is_some());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,chats.persistence.client-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn actual_encrypted_map_preserves_other_team_and_uncertain_same_job_candidate(){
    let(c,pending,_server)=genuine_pending_for_test().await;let prepared=pending.prepare_checkpoint_persistence(&c).unwrap();
    let mut other=prepared.checkpoint.clone();other.job.job_id="33333333-3333-4333-8333-333333333333".into();other.team_id=Some("44444444-4444-4444-8444-444444444444".into());let original_digest=other.digest().unwrap();
    let mut map=BTreeMap::new();map.insert(other.job.job_id.clone(),other);let bytes=encode_map(&map).unwrap();let ciphertext=prepared.master.encrypt_server_bytes(&bytes).await.unwrap();let expected=serde_json::to_string(&Record{version:1,ciphertext}).unwrap();
    let write=prepared.with_read_data(&c,Some(expected.clone())).unwrap().drive().await.unwrap();assert_eq!(write.expected.as_deref(),Some(expected.as_str()));
    let bytes=write.prepared.master.decrypt_bytes(&record(&write.next).ciphertext).await.unwrap();let map=pending_map(Some(serde_json::from_slice(&bytes).unwrap())).unwrap();assert_eq!(map.len(),2);assert_eq!(map["33333333-3333-4333-8333-333333333333"].digest().unwrap(),original_digest);
    let mut uncertain=map;let mut changed=write.prepared.checkpoint.clone();changed.encrypted_candidate["synthetic_unknown_ciphertext"]=json!("retained uncertain candidate");let before=uncertain.clone();assert!(matches!(merge_checkpoint(&mut uncertain,&changed,&changed.digest().unwrap()),Err(Error::Conflict)));assert_eq!(serde_json::to_value(uncertain).unwrap(),serde_json::to_value(before).unwrap());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn original_pending_cancel_denies_crypto_without_cancelling_scope_or_parent(){
    let(c,pending,_server)=genuine_pending_for_test().await;let prepared=pending.prepare_checkpoint_persistence(&c).unwrap();let scope=prepared.pending.context.original.clone();let cancel=prepared.pending.context.cancel.clone();
    let crypto=prepared.with_read_data(&c,None).unwrap();cancel.cancel();let failure=match crypto.drive().await{Err(failure)=>failure,Ok(_)=>panic!("cancelled original crypto must refuse")};assert!(matches!(failure.error(),Error::Cancelled));let pending=failure.into_pending();assert!(pending.stage.is_some());scope.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn native_pending_map_identity_and_count_policy_applies_to_genuine_checkpoint_data(){
    let(c,pending,_server)=genuine_pending_for_test().await;let prepared=pending.prepare_checkpoint_persistence(&c).unwrap();let mut alias=BTreeMap::new();alias.insert("foreign-alias",prepared.checkpoint.clone());assert!(pending_map(Some(serde_json::to_value(alias).unwrap())).is_err());
    let mut full=BTreeMap::new();for n in 0..100{let mut item=prepared.checkpoint.clone();item.job.job_id=format!("{n:08x}-3333-4333-8333-333333333333");full.insert(item.job.job_id.clone(),item);}assert_eq!(full.len(),100);assert!(matches!(merge_checkpoint(&mut full,&prepared.checkpoint,&prepared.digest),Err(Error::Protocol)));assert_eq!(full.len(),100);
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn native_io_ticket_is_issued_once_from_real_pending_and_never_rearmed_on_cancel(){
    let(c,pending,_server)=genuine_pending_for_test().await;let prepared=pending.prepare_checkpoint_persistence(&c).unwrap();let ticket=prepared.read_ticket(&c).unwrap();ticket.check_original(&c).unwrap();assert_eq!(ticket.effect(),prepared.read_effect(&c).unwrap());assert!(prepared.read_ticket(&c).is_err());ticket.claim_dispatch().unwrap();assert!(ticket.claim_dispatch().is_err());
    let original=prepared.pending.context.original.clone();drop(prepared);assert!(ticket.check_original_negative().is_err());original.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn cancelled_actual_pending_admission_failure_returns_same_stage_and_never_recaptures_peer(){
    let(c,pending,_server)=genuine_pending_for_test().await;let context=pending.context.clone();let original=context.original.clone();context.cancel.cancel();
    let failure=match pending.prepare_checkpoint_persistence(&c){Err(value)=>value,Ok(_)=>panic!("cancelled original admission")};assert_eq!(format!("{failure:?}"),"OriginalRecoveryPersistenceFailure");assert!(matches!(failure.error(),Error::Cancelled));
    let pending=failure.into_pending();assert!(Arc::ptr_eq(&pending.context,&context));assert!(pending.stage.is_some());original.check(&c).unwrap();assert!(!c.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,chats.persistence.client-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn malformed_encrypted_record_crypto_failure_retains_exact_original_checkpoint_and_stage(){
    let(c,pending,_server)=genuine_pending_for_test().await;let context=pending.context.clone();let digest=pending.checkpoint().unwrap().digest().unwrap();
    let crypto=pending.prepare_checkpoint_persistence(&c).unwrap().with_read_data(&c,Some("{".into())).unwrap();let failure=match crypto.drive().await{Err(value)=>value,Ok(_)=>panic!("malformed encrypted record")};
    assert!(matches!(failure.error(),Error::Protocol));let pending=failure.into_pending();assert!(Arc::ptr_eq(&pending.context,&context));assert!(pending.stage.is_some());assert_eq!(pending.checkpoint().unwrap().digest().unwrap(),digest);pending.check_original(&c).unwrap();assert!(!c.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,chats.persistence.client-encrypted
#[tokio::test]
async fn foreign_actual_client_read_admission_error_returns_same_prepared_pending(){
    let(c,pending,_server)=genuine_pending_for_test().await;let(peer,_peer_pending,_peer_server)=genuine_pending_for_test().await;let context=pending.context.clone();let prepared=pending.prepare_checkpoint_persistence(&c).unwrap();
    let failure=match prepared.with_read_data(&peer,None){Err(value)=>value,Ok(_)=>panic!("original prepared must not adopt genuine peer")};let pending=failure.into_pending();assert!(Arc::ptr_eq(&pending.context,&context));assert!(pending.stage.is_some());pending.check_original(&c).unwrap();assert!(!c.operation_parent.is_cancelled());assert!(!peer.operation_parent.is_cancelled());
}
