//! UNRUN actual original Pending supplier + journal reducer supporting cases.
//! These tests never mint a native delivery, physical proof or final receipt.
use super::*;
use crate::client::browser::owned_recovery_phase_tests::genuine_pending_for_test;

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,chats.persistence.client-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn exact_genuine_checkpoint_removal_preserves_other_job_team_and_encrypted_roundtrip(){
 let(c,pending,_server)=genuine_pending_for_test().await;let prepared=pending.prepare_checkpoint_persistence(&c).unwrap();
 let checkpoint=prepared.checkpoint.clone();let mut other=checkpoint.clone();other.job.job_id="33333333-3333-4333-8333-333333333333".into();other.team_id=Some("44444444-4444-4444-8444-444444444444".into());
 let old_other=serde_json::to_value(&other).unwrap();let mut map=BTreeMap::new();map.insert(checkpoint.job.job_id.clone(),checkpoint.clone());map.insert(other.job.job_id.clone(),other);
 matching_checkpoint(&map,&checkpoint).unwrap();remove_matching_checkpoint(&mut map,&checkpoint).unwrap();assert_eq!(map.len(),1);
 assert_eq!(serde_json::to_value(map.values().next().unwrap()).unwrap(),old_other);
 let bytes=encode_map(&map).unwrap();let encrypted=prepared.master.encrypt_server_bytes(&bytes).await.unwrap();let decrypted=prepared.master.decrypt_bytes(&encrypted).await.unwrap();
 let restored=decode_map_data(&decrypted).unwrap();assert!(!restored.contains_key(&checkpoint.job.job_id));assert_eq!(serde_json::to_value(restored.values().next().unwrap()).unwrap(),old_other);
 // Pure reduction/encryption never consumes the original pending Stage.
 prepared.check_original(&c).unwrap();assert!(prepared.pending.stage.is_some());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,chats.persistence.client-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn uncertain_changed_or_missing_candidate_is_not_removed_and_exact_map_survives(){
 let(c,pending,_server)=genuine_pending_for_test().await;let prepared=pending.prepare_checkpoint_persistence(&c).unwrap();let expected=prepared.checkpoint.clone();
 let mut changed=expected.clone();changed.encrypted_candidate["uncertain-ciphertext"]=json!("must-retain");let mut map=BTreeMap::new();map.insert(changed.job.job_id.clone(),changed);
 let before=serde_json::to_value(&map).unwrap();assert!(matches!(remove_matching_checkpoint(&mut map,&expected),Err(Error::Conflict)));assert_eq!(serde_json::to_value(&map).unwrap(),before);
 let mut missing=expected.clone();missing.job.job_id="55555555-5555-4555-8555-555555555555".into();assert!(matches!(remove_matching_checkpoint(&mut map,&missing),Err(Error::Conflict)));assert_eq!(serde_json::to_value(&map).unwrap(),before);
 prepared.check_original(&c).unwrap();assert!(prepared.pending.stage.is_some());assert!(!c.operation_parent.is_cancelled());
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,chats.persistence.client-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn retirement_exact_candidate_binds_endpoint_owner_team_key_and_canonical_state(){
 let(c,pending,_server)=genuine_pending_for_test().await;let prepared=pending.prepare_checkpoint_persistence(&c).unwrap();let expected=prepared.checkpoint.clone();
 let mut variants=Vec::new();
 let mut v=expected.clone();v.api_url.push_str("/foreign");variants.push(v);
 let mut v=expected.clone();v.owner_id="66666666-6666-4666-8666-666666666666".into();variants.push(v);
 let mut v=expected.clone();v.team_id=Some("77777777-7777-4777-8777-777777777777".into());variants.push(v);
 let mut v=expected.clone();v.wrapped_chat_key=Some("different-original-wrap".into());variants.push(v);
 let mut v=expected.clone();v.canonical_ciphertext=!v.canonical_ciphertext;variants.push(v);
 let mut other=expected.clone();other.job.job_id="88888888-8888-4888-8888-888888888888".into();
 for changed in variants {
  let mut map=BTreeMap::new();map.insert(expected.job.job_id.clone(),changed);map.insert(other.job.job_id.clone(),other.clone());
  let original=serde_json::to_value(&map).unwrap();
  assert!(matches!(matching_checkpoint(&map,&expected),Err(Error::Conflict)));
  assert!(matches!(remove_matching_checkpoint(&mut map,&expected),Err(Error::Conflict)));
  assert_eq!(serde_json::to_value(&map).unwrap(),original);
 }
 prepared.check_original(&c).unwrap();assert!(prepared.pending.stage.is_some());assert!(!c.operation_parent.is_cancelled());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.lifecycle,auth.session.isolation,chats.persistence.client-encrypted
#[tokio::test]
async fn cancelled_original_pending_cannot_issue_retirement_storage_work_or_clear_checkpoint(){
 let(c,pending,_server)=genuine_pending_for_test().await;let control=pending.context.cancel.clone();
 let prepared=pending.prepare_checkpoint_persistence(&c).unwrap();let expected=prepared.checkpoint.clone();
 let mut map=BTreeMap::new();map.insert(expected.job.job_id.clone(),expected);
 let original=serde_json::to_value(&map).unwrap();control.cancel();
 assert!(matches!(prepared.check_original(&c),Err(Error::Cancelled)));
 assert!(matches!(prepared.read_ticket(&c),Err(Error::Cancelled)));
 assert_eq!(serde_json::to_value(&map).unwrap(),original);
 assert!(prepared.pending.stage.is_some());assert!(!c.operation_parent.is_cancelled());
 // The pure reducer and a cancelled Stage never manufacture a native physical
 // proof, a journal retirement, success, or a parent/session cancellation.
}
