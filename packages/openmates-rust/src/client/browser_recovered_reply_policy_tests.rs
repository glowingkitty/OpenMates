//! Pure storage policy regressions with real shared crypto. Not native/auth proof.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sync.client.shared-rust-policy,auth.session.isolation
use super::*;
const CHAT:&str="22222222-2222-4222-8222-222222222222";
const MESSAGE:&str="33333333-3333-4333-8333-333333333333";
const OTHER:&str="44444444-4444-4444-8444-444444444444";
fn raw(content:&str,status:&str)->Value{
 json!({"message_id":MESSAGE,"client_message_id":MESSAGE,"chat_id":CHAT,"role":"assistant","created_at":100,"status":status,
 "encrypted_content":crypto::server_fields::encrypt_text(content,&[8;32],&[]).unwrap(),"encrypted_model_name":crypto::server_fields::encrypt_text("synthetic-model",&[8;32],&[]).unwrap(),"key_version":1})
}
#[test]
fn recovered_reply_replaces_actual_streaming_ciphertext_and_preserves_unknowns_link_timestamp_and_journals(){
 let canonical=raw("canonical completed reply","delivered");let mut old=raw("partial stream","streaming");
 old["created_at"]=json!(88);old["unknown"] =json!({"nested":[false,null,"retained"]});old["user_message_id"]=json!(OTHER);
 old["pending_encrypted_embed_bundle_v1"]=json!("opaque-bundle");old["pending_encrypted_turn_preflight_v1"]=json!("opaque-preflight");
 let before=old.clone();let after=prepare(&canonical,&old,&[],CHAT,MESSAGE,&[8;32]).unwrap();
 for field in ["created_at","unknown","user_message_id","pending_encrypted_embed_bundle_v1","pending_encrypted_turn_preflight_v1"]{assert_eq!(after[field],old[field]);}
 assert_eq!(after["pending_turn_preflight_v1"],1);assert_eq!(after["status"],"synced");
 assert_eq!(open(&after,&[8;32]).unwrap()["content"],"canonical completed reply");assert_eq!(old,before);
 for field in CLEAR{assert!(after.get(*field).is_none());}
}
#[test]
fn actual_absence_accepts_empty_authenticated_reply_but_refuses_different_id_duplicate_and_foreign_candidate(){
 let canonical=raw("","delivered");let after=prepare(&canonical,&Value::Null,&[],CHAT,MESSAGE,&[8;32]).unwrap();
 assert_eq!(open(&after,&[8;32]).unwrap()["content"],"");assert_eq!(after["status"],"synced");
 let canonical=raw("same logical reply","delivered");let mut duplicate_row=raw("same logical reply","synced");duplicate_row["message_id"]=json!(OTHER);duplicate_row["client_message_id"]=json!(OTHER);duplicate_row["created_at"]=json!(159);
 assert!(prepare(&canonical,&Value::Null,&[duplicate_row.clone()],CHAT,MESSAGE,&[8;32]).is_err());
 duplicate_row["created_at"]=json!(160);assert!(prepare(&canonical,&Value::Null,&[duplicate_row.clone()],CHAT,MESSAGE,&[8;32]).is_ok());
 duplicate_row["chat_id"]=json!(OTHER);assert!(prepare(&canonical,&Value::Null,&[duplicate_row],CHAT,MESSAGE,&[8;32]).is_err());
}
#[test]
fn journals_revision_key_and_ciphertext_conflicts_refuse_without_mutating_any_source(){
 let canonical=raw("canonical","delivered");let original=canonical.clone();
 for cause in ["call","revision","missing-revision","key-version","tag","owner-chat","plaintext"]{
  let mut old=raw("old","synced");let mut new=canonical.clone();
  match cause{
   "call"=>old["call_persistence_v1"]=json!({"entries":[{"ciphertext":"original"}]}),
   "revision"=>{old["queue_revision"]=json!(5);new["queue_revision"]=json!(4);},
   "missing-revision"=>old["queue_revision"]=json!(5),
   "key-version"=>old["key_version"]=json!(2),
   "tag"=>new["encrypted_content"]=json!("synthetic-invalid-tag"),
   "owner-chat"=>old["chat_id"]=json!(OTHER),
   _=>old["content"]=json!("legacy plaintext requires actual migration"),
  }
  let before=old.clone();let source_before=new.clone();assert!(prepare(&new,&old,&[],CHAT,MESSAGE,&[8;32]).is_err(),"{cause}");assert_eq!(old,before);assert_eq!(new,source_before);
 }
 assert_eq!(canonical,original);
 assert!(prepare(&canonical,&Value::Null,&[],CHAT,MESSAGE,&[9;32]).is_err());
}
#[test]
fn full_native_observation_reread_detects_unknown_header_and_row_changes_or_db_switch(){
 let row=raw("canonical","synced");let metadata=json!({"chat_id":CHAT,"messages_v":7,"unknown":{"draft":"opaque"}});
 let before=json!({"db_version":45,"observation":{"metadata":metadata,"record":null,"candidates":[]}});
 let after=json!({"db_version":45,"observation":{"metadata":metadata,"record":row,"candidates":[]}});
 physical_matches(&before,&after,&after,&row).unwrap();
 for field in ["row","header","version","null"]{
  let mut changed=after.clone();match field{
   "row"=>changed["observation"]["record"]["unknown"]=json!("concurrent native write"),
   "header"=>changed["observation"]["metadata"]["unknown"]["draft"]=json!("new draft"),
   "version"=>changed["db_version"]=json!(46),
   _=>changed["observation"]["record"]=Value::Null,
  }
  assert!(physical_matches(&before,&after,&changed,&row).is_err(),"{field}");
 }
}
#[test]
fn selected_assistant_alias_and_role_are_not_repaired_from_dto(){
 let mut source_row=raw("canonical","delivered");source_row["client_message_id"]=json!(OTHER);assert!(source(&source_row,CHAT,MESSAGE).is_err());
 let mut source_row=raw("canonical","delivered");source_row["role"]=json!("user");assert!(source(&source_row,CHAT,MESSAGE).is_err());
 assert!(source(&raw("canonical","delivered"),CHAT,"short-id").is_err());
}
#[test]
fn shared_duplicate_predicate_retains_different_user_submissions_and_exact_assistant_time_boundary(){
 let a=json!({"message_id":MESSAGE,"chat_id":CHAT,"role":"user","created_at":1,"content":"repeat","status":"synced"});
 let mut b=a.clone();b["message_id"]=json!(OTHER);assert!(!message_policy::is_content_duplicate(&a,&b).unwrap());
 let mut a=a.clone();a["role"]=json!("assistant");b["role"]=json!("assistant");b["created_at"]=json!(60);
 assert!(message_policy::is_content_duplicate(&a,&b).unwrap());b["created_at"]=json!(61);assert!(!message_policy::is_content_duplicate(&a,&b).unwrap());
 let mut b=a.clone();b["message_id"]=json!(OTHER);a["content"]=json!("");b["content"]=json!("");assert!(!message_policy::is_content_duplicate(&a,&b).unwrap());
}
#[test]
fn individually_supported_old_unknowns_and_new_ciphertext_refuse_oversized_merged_row_before_any_effect(){
 let canonical=raw(&"c".repeat(5*1024*1024),"delivered");let mut old=raw("partial","streaming");
 old["unknown"]=json!({"retained":"u".repeat(10*1024*1024)});
 check_planned_row(&canonical).unwrap();check_planned_row(&old).unwrap();
 let mut hypothetical=old.clone();hypothetical["encrypted_content"]=canonical["encrypted_content"].clone();
 assert!(check_planned_row(&hypothetical).is_err());
 let old_before=old.clone();let canonical_before=canonical.clone();
 assert!(matches!(prepare(&canonical,&old,&[],CHAT,MESSAGE,&[8;32]),Err(Error::Protocol)));
 assert_eq!(old,old_before);assert_eq!(canonical,canonical_before);
 // The same authenticated source is supported when retained unknowns fit.
 old["unknown"]=json!({"retained":"u".repeat(2*1024*1024)});
 let after=prepare(&canonical,&old,&[],CHAT,MESSAGE,&[8;32]).unwrap();
 check_planned_row(&after).unwrap();assert_eq!(after["unknown"],old["unknown"]);
 assert!(body_matches(&after,&source(&canonical,CHAT,MESSAGE).unwrap(),&[8;32]).unwrap());
}
#[test]
fn planned_physical_row_limit_counts_complete_serialized_unknown_fields_at_exact_boundary(){
 let limit=crate::client::transport::MAX_BODY;
 let overhead=serde_json::to_vec(&json!({"unknown":""})).unwrap().len();
 let exact=json!({"unknown":"x".repeat(limit-overhead)});
 assert_eq!(serde_json::to_vec(&exact).unwrap().len(),limit);check_planned_row(&exact).unwrap();
 let mut beyond=exact.clone();beyond["additional_unknown"]=json!(null);
 assert!(check_planned_row(&beyond).is_err());assert!(check_planned_row(&exact).is_ok());
}
#[test]
fn actual_normalized_wire_database_alias_is_supported_without_rekeying_native_rows(){
 let mut wire=raw("actual canonical reply","delivered");wire["id"]=json!(OTHER);
 // This is the maintained endpoint shape after client_message_id normalization.
 let mut seen=std::collections::HashSet::new();let (validated,decoded)=sync::decode_chat_message(&wire,CHAT,&[8;32],&mut seen).unwrap();
 assert_eq!(decoded.id,MESSAGE);assert_eq!(validated["id"],OTHER);
 let inserted=prepare(&validated,&Value::Null,&[],CHAT,MESSAGE,&[8;32]).unwrap();
 assert_eq!(inserted["message_id"],MESSAGE);assert_eq!(inserted["client_message_id"],MESSAGE);assert_eq!(inserted["id"],OTHER);
 assert!(body_matches(&inserted,&source(&validated,CHAT,MESSAGE).unwrap(),&[8;32]).unwrap());
 let mut old=raw("prior partial","streaming");old["id"]=json!("55555555-5555-4555-8555-555555555555");old["unknown_local"]=json!({"journal":"preserve"});
 let before=old.clone();let updated=prepare(&validated,&old,&[],CHAT,MESSAGE,&[8;32]).unwrap();
 assert_eq!(updated["id"],old["id"]);assert_eq!(updated["unknown_local"],old["unknown_local"]);assert_eq!(old,before);
 assert_eq!(updated["message_id"],MESSAGE);assert_eq!(updated["client_message_id"],MESSAGE);
}
#[test]
fn canonical_logical_duplicate_foreign_chat_and_real_native_alias_collisions_remain_refused(){
 let mut wire=raw("canonical","delivered");wire["id"]=json!(OTHER);
 let mut seen=std::collections::HashSet::new();sync::decode_chat_message(&wire,CHAT,&[8;32],&mut seen).unwrap();
 let mut second=wire.clone();second["id"]=json!("55555555-5555-4555-8555-555555555555");
 assert!(sync::decode_chat_message(&second,CHAT,&[8;32],&mut seen).is_err());
 let mut foreign=wire.clone();foreign["chat_id"]=json!(OTHER);
 assert!(sync::decode_chat_message(&foreign,CHAT,&[8;32],&mut std::collections::HashSet::new()).is_err());assert!(source(&foreign,CHAT,MESSAGE).is_err());
 let mut contradictory=wire.clone();contradictory["message_id"]=json!(OTHER);assert!(source(&contradictory,CHAT,MESSAGE).is_err());
 let mut local=raw("prior","synced");local["message_id"]=json!(OTHER);let before=local.clone();
 assert!(prepare(&wire,&local,&[],CHAT,MESSAGE,&[8;32]).is_err());assert_eq!(local,before);
}
