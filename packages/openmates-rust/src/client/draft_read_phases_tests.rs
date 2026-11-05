//! Actual shared decision/parser modules only. UNRUN. These fixtures have NO
//! Session or auth grant; policy data cannot enter the public draft read API.
use super::*;
const ID:&str="11111111-1111-4111-8111-111111111111";
const OWNER:&str="22222222-2222-4222-8222-222222222222";
fn client()->Client{let mut c=Client::new("http://127.0.0.1:9",None).unwrap();c.user=json!({"id":OWNER});c.insert_chat_row(ID.into(),json!({"id":ID,"user_id":OWNER,"draft_v":3,"encrypted_draft_md":"opaque-old","encrypted_draft_preview":null,"encrypted_title":"preserve-title","encrypted_chat_key":"preserve-wrap","messages_v":7,"unknown_local":{"retain":true}}));assert!(c.draft_read_admission().is_err());c}
fn versions(n:u64)->BTreeMap<String,u64>{BTreeMap::from([(ID.into(),n)])}
fn metadata(version:u64)->BTreeMap<String,Value>{BTreeMap::from([(ID.into(),json!({"id":ID,"user_id":OWNER,"draft_v":version,"encrypted_draft_md":"opaque-new","encrypted_draft_preview":null}))])}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn first_version_zero_prepares_only_draft_clear_without_chat_delete_or_auth_grant(){
    let c=client();let mut policy=DraftFallbackPolicy::capture(&c,ID).unwrap();let prepared=policy.accept_first(&c,versions(0),versions(4)).unwrap().unwrap();assert!(prepared.row.is_none());
    let row=&prepared.updates[ID];assert!(!row["encrypted_draft_md"].is_string());assert_eq!(row["draft_v"],4);
    for field in ["encrypted_title","encrypted_chat_key","messages_v","unknown_local"]{assert_eq!(row[field],c.chats[ID][field]);}
    assert_eq!(c.chats[ID]["encrypted_draft_md"],"opaque-old");assert!(policy.accept_first(&c,versions(0),versions(4)).is_err());assert!(c.draft_read_admission().is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[test]
fn matching_first_metadata_final_versions_use_same_strict_merge_and_preserve_saved_chat(){
    let c=client();let mut policy=DraftFallbackPolicy::capture(&c,ID).unwrap();assert!(policy.accept_first(&c,versions(4),BTreeMap::new()).unwrap().is_none());
    policy.accept_metadata(&c,metadata(4)).unwrap();assert_eq!(policy.final_requested().unwrap(),&[(ID.into(),4)]);
    let prepared=policy.accept_final(&c,versions(4),BTreeMap::new()).unwrap();assert_eq!(prepared.row.as_ref().unwrap()["draft_v"],4);
    assert_eq!(prepared.updates[ID]["encrypted_draft_md"],"opaque-new");assert_eq!(prepared.updates[ID]["encrypted_title"],"preserve-title");assert_eq!(prepared.updates[ID]["messages_v"],7);assert_eq!(prepared.updates[ID]["unknown_local"],json!({"retain":true}));
    assert_eq!(c.chats[ID]["draft_v"],3);assert!(c.draft_read_admission().is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[test]
fn final_version_race_or_original_cached_version_change_refuses_prepared_commit(){
    for cache_changed in [false,true]{let mut c=client();let mut policy=DraftFallbackPolicy::capture(&c,ID).unwrap();policy.accept_first(&c,versions(4),BTreeMap::new()).unwrap();policy.accept_metadata(&c,metadata(4)).unwrap();if cache_changed{c.chats.get_mut(ID).unwrap()["draft_v"]=json!(5);}
        assert!(matches!(policy.accept_final(&c,versions(if cache_changed{4}else{5}),BTreeMap::new()),Err(Error::Conflict)));}
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn foreign_draft_scope_and_equal_version_different_ciphertext_refuse_before_preparation(){
    for field in ["user_id","team_id","chat_visibility","same_version"]{let c=client();let mut policy=DraftFallbackPolicy::capture(&c,ID).unwrap();policy.accept_first(&c,versions(4),BTreeMap::new()).unwrap();let mut rows=metadata(4);let row=rows.get_mut(ID).unwrap();match field{"same_version"=>row["draft_v"]=json!(3),"chat_visibility"=>row[field]=json!("direct"),_=>row[field]=json!("33333333-3333-4333-8333-333333333333")};assert!(policy.accept_metadata(&c,rows).is_err());assert!(policy.final_requested().is_err());}
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn version_chunk_parser_keeps200_bound_exact_ids_duplicate_and_tombstone_floor_checks(){
    let requested=(1..=201).map(|n|(format!("{n:08x}-1111-4111-8111-111111111111"),3)).collect::<Vec<_>>();let mut read=DraftVersionsRead::new(&requested);assert_eq!(read.next_chunk().unwrap().len(),200);
    let rows=requested[..200].iter().map(|(id,_)|(id.clone(),json!(4))).collect::<serde_json::Map<_,_>>();read.accept(&json!({"versions":rows})).unwrap();assert_eq!(read.next_chunk().unwrap().len(),1);
    let mut refused=DraftVersionsRead::new(&requested[200..]);assert!(refused.accept(&json!({"versions":{(requested[0].0.clone()):4}})).is_err());assert!(refused.accept(&json!({"versions":{(requested[200].0.clone()):4}})).is_err());
    read.accept(&json!({"versions":{(requested[200].0.clone()):4}})).unwrap();assert!(read.next_chunk().is_none());let(done,tomb)=read.finish().unwrap();assert_eq!(done.len(),201);assert!(tomb.is_empty());
    let mut read=DraftVersionsRead::new(&[(ID.into(),3)]);assert!(read.accept(&json!({"versions":{ID:0},"tombstone_versions":{ID:3}})).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn shared_targeted_metadata_parser_ignores_foreign_epoch_and_refuses_content_or_partial_completion(){
    let mut read=DraftMetadataRead::new(42);read.accept("phase_2_last_20_chats_ready",&json!({"context_epoch":41,"team_id":null,"phase":"phase2","chats":[]})).unwrap();assert!(!read.terminal());assert!(read.finish().is_err());
    let mut read=DraftMetadataRead::new(42);assert!(read.accept("phase_2_last_20_chats_ready",&json!({"context_epoch":42,"team_id":null,"phase":"phase2","chats":[],"messages":[{}]})).is_err());
    let mut read=DraftMetadataRead::new(42);read.accept("phase_2_last_20_chats_ready",&json!({"context_epoch":42,"team_id":null,"phase":"phase2","chats":[]})).unwrap();read.accept("phased_sync_complete",&json!({"context_epoch":42,"team_id":null,"phase":"phase2"})).unwrap();assert!(read.terminal());assert!(read.finish().unwrap().is_empty());
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn actual_phase1b_content_tag_is_refused_by_the_shared_metadata_only_parser(){
    for kind in ["phase_1b_chat_content_ready","phase_1b_last_chat_messages_ready"]{
        let mut read=DraftMetadataRead::new(42);
        let payload=json!({"context_epoch":42,"team_id":null,"chats":[{"chat_id":ID,"messages":[{"encrypted_content":"opaque-content"}]}]});
        assert!(matches!(read.accept(kind,&payload),Err(Error::Protocol)));assert!(read.finish().is_err());
    }
}
