//! Public synthetic raw-wire projection cases, authored UNRUN for Rust CI.
//! Existing AES-GCM fixture was generated independently with Python cryptography.
//! All data is artificial; no account, HTTP, credential discovery or browser IO.
//! These tests exercise closed projection, actual crypto and refusal cleanup.
//! They do not claim full allocator wiping or runtime/WASM/performance evidence.
// contract-test-file: tooling
use super::*;
use std::cell::Cell;
const CHAT:&str="22222222-2222-4222-8222-222222222222";
fn rows()->Vec<Value>{serde_json::from_str::<Value>(include_str!("../../tests/fixtures/browser-idb-local-window.json")).unwrap()["input"]["compression_checkpoints"].as_array().unwrap().clone()}
#[test]
fn latest_real_storage_ciphertext_projects_closed_stored_summary_without_raw_extensions(){
 let mut rows=rows();rows[1]["extension"]=json!({"plaintext":"NEVER_COPY_THIS_EXTENSION"});
 let out=project(&rows,CHAT,&[9;32],None,||Ok(())).unwrap();let encoded=serde_json::to_string(&out).unwrap();let value:Value=serde_json::from_str(&encoded).unwrap();
 let shared:Value=serde_json::from_str(include_str!("../../tests/fixtures/local-checkpoint-presentation.json")).unwrap();assert_eq!(value,shared["cases"][0]["expected"]);
 assert_eq!(value["coverage"],"retained_latest");assert_eq!(value["retainedCheckpointCount"],2);assert_eq!(value["piiRestoration"],"stored");
 assert_eq!(value["checkpoint"]["summary"],"Latest synthetic summary");assert_eq!(value["checkpoint"]["summaryState"],"loaded");assert!(!encoded.contains("encrypted_summary"));assert!(!encoded.contains("NEVER_COPY_THIS_EXTENSION"));
}
#[test]
fn stable_equal_created_tie_and_exact_selection_preserve_physical_checkpoint_identity(){
 let mut rows=rows();rows[0]["created_at"]=rows[1]["created_at"].clone();rows.reverse();
 let latest=project(&rows,CHAT,&[9;32],None,||Ok(())).unwrap();assert!(latest.checkpoint.as_ref().unwrap().id.ends_with("0001"));
 let selected=project(&rows,CHAT,&[9;32],Some(rows[0]["id"].as_str().unwrap()),||Ok(())).unwrap();assert_eq!(selected.coverage,"retained_selected");assert_eq!(selected.checkpoint.as_ref().unwrap().id,rows[0]["id"].as_str().unwrap());
 let missing=project(&rows,CHAT,&[9;32],Some("absent"),||Ok(())).unwrap();assert!(missing.checkpoint.is_none());assert_eq!(missing.coverage,"retained_selected");
}
#[test]
fn legacy_clear_summary_wins_and_pii_placeholders_remain_literal(){
 let mut rows=rows();rows[1]["summary"]=json!("Stored [PERSON_1] literal");rows[1]["encrypted_summary"]=json!("bad");
 let out=project(&rows,CHAT,&[9;32],None,||Ok(())).unwrap();assert_eq!(out.checkpoint.as_ref().unwrap().summary.as_deref(),Some("Stored [PERSON_1] literal"));
 rows[1]["summary"]=json!("");let out=project(&rows,CHAT,&[9;32],None,||Ok(())).unwrap();assert_eq!(out.checkpoint.as_ref().unwrap().summary_state,SummaryState::Unavailable);assert_eq!(out.checkpoint.as_ref().unwrap().summary_unavailable_reason,Some("corrupt"));
 rows[1]["encrypted_summary"]=Value::Null;let out=project(&rows,CHAT,&[9;32],None,||Ok(())).unwrap();assert_eq!(out.checkpoint.as_ref().unwrap().summary_state,SummaryState::Missing);
}
#[test]
fn corrupt_summary_never_swallows_original_scope_owner_key_cancel_or_denial_failure(){
 for error in [Error::Cancelled,Error::Forbidden,Error::Locked,Error::Expired,Error::Authentication]{
  let mut rows=rows();rows[1]["encrypted_summary"]=json!("bad");let calls=Cell::new(0);
  let result=project(&rows,CHAT,&[9;32],None,||{calls.set(calls.get()+1);if calls.get()==3{Err(error)}else{Ok(())}});assert!(matches!(result,Err(value) if value==error));
 }
 let mut wrong=rows();wrong[1]["chat_id"]=json!("wrong");assert!(matches!(project(&wrong,CHAT,&[9;32],None,||Ok(())),Err(Error::Forbidden)));
 let too_many=vec![rows()[0].clone();129];assert!(matches!(project(&too_many,CHAT,&[9;32],None,||Ok(())),Err(Error::Protocol)));
}
#[test]
fn omitted_or_exact_oversized_summaries_are_explicit_and_string_cleanup_is_directly_exercised(){
 let mut out=project(&rows(),CHAT,&[9;32],None,||Ok(())).unwrap();out.omit_summary();assert_eq!(out.checkpoint.as_ref().unwrap().summary_state,SummaryState::NotLoaded);assert!(out.checkpoint.as_ref().unwrap().summary.is_none());
 out.mark_oversized();assert_eq!(out.checkpoint.as_ref().unwrap().summary_unavailable_reason,Some("oversized"));
 let mut checkpoint=out.checkpoint.take().unwrap();checkpoint.summary=Some("CLEAR_SCRATCH".into());
 // Explicit zeroization semantics, not an assertion about freed allocator bytes.
 if let Some(value)=&mut checkpoint.summary{value.zeroize();assert!(value.is_empty());}
}

#[test]
fn equal_timestamp_checkpoint_uses_idb_utf16_primary_key_order(){
 let cp=|id:&str,n|json!({"id":id,"chat_id":CHAT,"created_at":2,"compressed_up_to_timestamp":n,"compressed_message_count":1});
 let out=project(&[cp("\u{e000}",20),cp("\u{10000}",10)],CHAT,&[9;32],None,||Ok(())).unwrap();
 let out=out.checkpoint.unwrap();assert_eq!(out.id,"\u{10000}");assert_eq!(out.compressed_up_to_timestamp,10);
}
