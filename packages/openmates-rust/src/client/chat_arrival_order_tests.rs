//! Actual shared renderer/snapshot/freshness units; authored UNRUN for parent CI.
use super::*;
use zeroize::Zeroizing;
fn client()->Client{
 let mut session=crate::client::sdk_boundary_tests::session();session.master_key=Zeroizing::new([7;32]);
 let mut c=Client::new("https://api.example.org",Some(session)).unwrap();c.user=json!({"id":"synthetic-owner"});c
}
fn id(n:usize)->String{format!("00000000-0000-4000-8000-{n:012x}")}
fn row(n:usize,score:i64)->Value{json!({"id":id(n),"last_edited_overall_timestamp":score,
 "encrypted_chat_key":crypto::encrypt_bytes(&[8;32],&[7;32]).unwrap(),
 "encrypted_title":crypto::encrypt_combined("Synthetic title",&[8;32]).unwrap()})}
fn ordered()->Client{
 let mut c=client();c.chat_arrival_order=Some(vec![]);
 for n in (0..21).rev(){c.insert_chat_row(id(n),row(n,10));}c
}
#[test]
fn equal_score_cutoff_uses_original_arrival_without_changing_timestamp_priority(){
 let mut c=ordered();c.insert_chat_row(id(3),row(3,20));
 let got=c.render_chat_inventory().unwrap().into_iter().map(|v|v.id).collect::<Vec<_>>();
 let mut expected=vec![id(3)];expected.extend((0..21).rev().filter(|n|*n!=3).map(id));
 assert_eq!(got,expected);assert_eq!(got[..20],expected[..20]);assert_eq!(got[20],id(0));
 let order=c.chat_arrival_order.clone();c.insert_chat_row(id(3),row(3,10));assert_eq!(c.chat_arrival_order,order);
 c.remove_chat_row(&id(7));assert!(!c.chat_arrival_order.as_ref().unwrap().contains(&id(7)));
}
#[test]
fn exact_snapshot_restart_and_old_missing_order_compatibility(){
 let c=ordered();let snapshot=c.ciphertext_snapshot();assert_eq!(snapshot[SNAPSHOT_FIELD]["version"],1);
 let mut restored=client();restored.restore_ciphertext_snapshot(&snapshot).unwrap();
 assert_eq!(restored.chat_arrival_order,c.chat_arrival_order);assert_eq!(restored.ciphertext_snapshot(),snapshot);
 let mut old=snapshot.clone();old.as_object_mut().unwrap().remove(SNAPSHOT_FIELD);
 restored.restore_ciphertext_snapshot(&old).unwrap();assert!(restored.chat_arrival_order.is_none());
 assert!(restored.ciphertext_snapshot().get(SNAPSHOT_FIELD).is_none());
 assert_eq!(restored.render_chat_inventory().unwrap()[0].id,id(0));
}
#[test]
fn malformed_order_refuses_before_replacing_existing_rows_or_order(){
 let mut c=ordered();let before=c.ciphertext_snapshot();let before_rows=c.chats.clone();
 for ids in [json!([id(0)]),json!(vec![id(0);21]),json!((0..21).map(|n|if n==20{id(99)}else{id(n)}).collect::<Vec<_>>())]{
  let mut bad=before.clone();bad[SNAPSHOT_FIELD]["ids"]=ids;
  assert!(c.restore_ciphertext_snapshot(&bad).is_err());assert_eq!(c.chats,before_rows);
  assert_eq!(c.chat_arrival_order.as_ref().unwrap()[0],id(20));
 }
}
#[test]
fn order_mutation_invalidates_original_full_inventory_proof(){
 let mut c=ordered();let cancel=CancellationToken::new();let proof=c.fresh_chat_inventory(&cancel).unwrap().unwrap();
 assert!(c.chat_inventory_is_current(&proof).unwrap());c.chat_arrival_order.as_mut().unwrap().reverse();
 assert!(!c.chat_inventory_is_current(&proof).unwrap());
}
#[test]
fn reset_and_unknown_map_only_batch_never_invent_historical_order(){
 let mut c=ordered();let order=c.chat_arrival_order.clone();c.extend_chat_rows_without_arrival(BTreeMap::from([(id(1),row(1,10))]));
 assert_eq!(c.chat_arrival_order,order);c.extend_chat_rows_without_arrival(BTreeMap::from([(id(50),row(50,10))]));
 assert!(c.chat_arrival_order.is_none());assert_eq!(c.render_chat_inventory().unwrap().len(),22);
 c.clear_chat_rows();assert!(c.chats.is_empty());assert!(c.chat_arrival_order.is_none());
 c.insert_chat_row(id(0),row(0,10));assert!(c.chat_arrival_order.is_none());
 c.set_team(Some("11111111-1111-4111-8111-111111111111")).unwrap();assert!(c.chat_arrival_order.is_none());assert!(c.chats.is_empty());
}
#[test]
fn phase1_metadata_order_appends_only_missing_rows_after_phase2_precedence(){
 let mut phase=super::super::sync_windows::Phase1Windows::default();
 phase.metadata(&json!({"team_id":null,"context_epoch":0,"chat_details":row(3,10),"recent_chat_metadata":[row(2,10),row(1,10)]}),None).unwrap();
 let mut chats=BTreeMap::from([(id(2),row(2,20))]);let mut order=vec![id(2)];
 phase.merge_metadata_ordered(&mut chats,&mut order);assert_eq!(order,vec![id(2),id(3),id(1)]);
 assert_eq!(chats[&id(2)]["last_edited_overall_timestamp"],20);
}

#[test]
fn freshness_receipt_binds_exact_order_and_read_does_not_renew_it(){
 fn clock(t:u64)->CacheClockEvidence{CacheClockEvidence::from_platform("synthetic-arrival-boot".into(),t,t).unwrap()}
 let mut c=ordered();c.set_chat_cache_clock_provider(Some(std::sync::Arc::new(||Some(clock(1100)))));
 c.record_complete_chat_list_at(Some(&clock(1000)));let original=c.ciphertext_snapshot();
 assert!(c.try_cached_default_chat_list(false).unwrap().is_some());assert_eq!(c.ciphertext_snapshot(),original);
 let mut reordered=original.clone();reordered[SNAPSHOT_FIELD]["ids"].as_array_mut().unwrap().reverse();
 let mut restored=client();restored.set_chat_cache_clock_provider(Some(std::sync::Arc::new(||Some(clock(1100)))));
 restored.restore_authenticated_ciphertext_snapshot(&reordered).unwrap();
 assert!(restored.try_cached_default_chat_list(false).unwrap().is_none());
 assert_eq!(restored.render_chat_inventory().unwrap().len(),21);
}
