//! Actual shared public callback methods with opaque synthetic AES master.
//! The parent harness executes maintained readonly plans against public raw rows.
//! These are authored UNRUN native Rust unit tests, never product/account IO.
//! Cancellation/key-denial cases hold the actual metadata callback future.
//! No success here substitutes for real WASM, browser or cross-SDK acceptance.
// contract-test-file: tooling
use super::*;
#[tokio::test]
async fn public_exact_checkpoint_read_uses_one_bounded_metadata_callback_and_real_crypto(){
 let client=client();let input=fixture();let id=input["compression_checkpoints"][0]["id"].as_str().unwrap();let calls=RefCell::new(0);
 let output=client.browser_local_checkpoint_summary_with_io_json(OWNER,CHAT,id,|plan|{*calls.borrow_mut()+=1;assert_eq!(serde_json::from_str::<Value>(&plan).unwrap()["kind"],"metadata");std::future::ready(Ok(reply(&plan,&input).to_string()))}).await.unwrap();
 let value:Value=serde_json::from_str(&output).unwrap();assert_eq!(value["checkpoint"]["summary"],"Older synthetic summary");assert_eq!(value["coverage"],"retained_selected");assert_eq!(*calls.borrow(),1);assert_eq!(client.credential_ack,0);assert!(client.history.is_empty());
}
#[tokio::test]
async fn public_local_saved_read_contains_latest_checkpoint_without_pii_or_history_upgrade(){
 let client=client();let input=fixture();let output=client.browser_local_saved_chat_read_with_io_json(OWNER,CHAT,SavedChatReadOptions{content_mode:SavedChatContentMode::PageLocal,..Default::default()},|plan|std::future::ready(Ok(reply(&plan,&input).to_string()))).await.unwrap();
 let value:Value=serde_json::from_str(&output).unwrap();assert_eq!(value["checkpointPresentation"]["checkpoint"]["summary"],"Latest synthetic summary");assert_eq!(value["checkpointPresentation"]["piiRestoration"],"stored");assert_eq!(value["historyComplete"],false);assert_eq!(value["pagesRead"],0);assert!(output.len()<=256*1024-8192);
}
#[tokio::test]
async fn held_exact_metadata_does_not_publish_after_cancel_key_retirement_or_known_denial(){
 for change in 0..3{let client=client();let input=fixture();let id=input["compression_checkpoints"][0]["id"].as_str().unwrap();let entered=Arc::new(Notify::new());let release=Arc::new(Notify::new());
 let mut future=Box::pin(client.browser_local_checkpoint_summary_with_io_json(OWNER,CHAT,id,|plan|{let result=reply(&plan,&input).to_string();let entered=entered.clone();let release=release.clone();async move{entered.notify_one();release.notified().await;Ok(result)}}));
 tokio::select!{biased;result=&mut future=>{let _=result;panic!("held metadata required");},_=entered.notified()=>{}}
 match change{0=>client.operation_cancel.cancel(),1=>client.master_capability().unwrap().invalidate(),_=>client.task_watch_authority.deny_cached_chat(Some(CHAT)).unwrap()};release.notify_one();assert!(future.await.is_err());assert_eq!(client.credential_ack,0);
 }
}
#[tokio::test]
async fn wrong_owner_and_oversized_or_duplicate_key_metadata_refuse_before_summary_publication(){
 let client=client();let input=fixture();let id=input["compression_checkpoints"][0]["id"].as_str().unwrap();
 let result=client.browser_local_checkpoint_summary_with_io_json(CHAT,CHAT,id,|_|{panic!("wrong principal cannot invoke IO");std::future::ready(Err(Error::Io))}).await;assert!(result.is_err());
 for extra in ["duplicate","overflow"]{let result=client.browser_local_checkpoint_summary_with_io_json(OWNER,CHAT,id,|plan|{let text=reply(&plan,&input).to_string();std::future::ready(Ok(if extra=="duplicate"{text.replacen("\"version\":1","\"version\":1,\"version\":1",1)}else{"x".repeat(256*1024+1)}))}).await;assert!(matches!(result,Err(Error::Protocol)));}
}

#[tokio::test]
async fn inline_budget_defers_summary_without_truncating_messages_and_exact_read_recovers_it(){
 let client=client();let mut input=fixture();input["compression_checkpoints"][1]["summary"]=json!("Q".repeat(30_000));
 let mapping=json!([{"placeholder":"[PERSON_1]","original":"P".repeat(1800)}]);
 input["messages"]=json!((0..4).map(|index|json!({"chat_id":CHAT,"message_id":format!("physical-{index}"),"created_at":120+index,"role":"user",
  "encrypted_content":crypto::encrypt_bytes("[PERSON_1]".repeat(32).as_bytes(),&[9;32]).unwrap(),
  "encrypted_pii_mappings":crypto::encrypt_bytes(mapping.to_string().as_bytes(),&[9;32]).unwrap()})).collect::<Vec<_>>());
 let output=client.browser_local_saved_chat_read_with_io_json(OWNER,CHAT,SavedChatReadOptions{content_mode:SavedChatContentMode::PageLocal,..Default::default()},|plan|std::future::ready(Ok(reply(&plan,&input).to_string()))).await.unwrap();
 let value:Value=serde_json::from_str(&output).unwrap();assert_eq!(value["checkpointPresentation"]["checkpoint"]["summaryState"],"not_loaded");assert!(value["checkpointPresentation"]["checkpoint"]["summary"].is_null());assert_eq!(value["chat"]["messages"].as_array().unwrap().len(),4);assert!(output.len()<=256*1024-8192);
 for message in value["chat"]["messages"].as_array().unwrap(){assert_eq!(message["content"].as_str().unwrap().len(),1800*32);}
 let id=input["compression_checkpoints"][1]["id"].as_str().unwrap();let output=client.browser_local_checkpoint_summary_with_io_json(OWNER,CHAT,id,|plan|std::future::ready(Ok(reply(&plan,&input).to_string()))).await.unwrap();
 let value:Value=serde_json::from_str(&output).unwrap();assert_eq!(value["checkpoint"]["summaryState"],"loaded");assert_eq!(value["checkpoint"]["summary"].as_str().unwrap().len(),30_000);
}
