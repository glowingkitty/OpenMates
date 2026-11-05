//! Supporting policy/crypto fixtures only. No native/authentication proof.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sync.client.shared-rust-policy,auth.session.isolation
use super::*;
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const CHAT:&str="22222222-2222-4222-8222-222222222222";
const MESSAGE:&str="33333333-3333-4333-8333-333333333333";
const EMBED:&str="44444444-4444-4444-8444-444444444444";
fn raw()->Value{json!({"embed_id":EMBED,"user_id":OWNER,"chat_id":CHAT,"message_id":MESSAGE,"already_encrypted":true,"encryption_mode":"client","status":"finished","version_number":1,"parent_embed_id":null,"embed_ids":[],"embed_keys_has_more_after":false,"createdAt":100,"updatedAt":101,"content":crypto::encrypt_combined("language: rust\ncode: fn main() {}",&[8;32]).unwrap(),"type":crypto::encrypt_combined("code",&[8;32]).unwrap()})}
#[test]
fn code_embed_projection_keeps_ciphertext_and_merge_preserves_full_local_unknowns(){
 let wire=raw();let projected=source(&wire,OWNER,CHAT,MESSAGE).unwrap();
 assert_eq!(projected["type"],"code");assert_eq!(projected["encrypted_content"],wire["content"]);assert!(projected.get("content").is_none());
 assert_eq!(crypto::decrypt_combined(projected["encrypted_type"].as_str().unwrap(),&[8;32]).unwrap(),"code");
 let mut durable_wire=wire.clone();durable_wire["chat_id"]=json!(sha256(CHAT));durable_wire["message_id"]=json!(sha256(MESSAGE));
 assert_eq!(*source(&durable_wire,OWNER,CHAT,MESSAGE).unwrap(),*projected);
 let mut old=(*projected).clone();old["unknown_local"]=json!({"future":[true,null,"retained"]});old["draft_artifact"]=json!("opaque-local-draft");old["status"]=json!("processing");old["updatedAt"]=json!(100);
 let saved=old.clone();let merged=merge(&projected,&old,OWNER,CHAT,MESSAGE).unwrap();assert_eq!(merged["unknown_local"],old["unknown_local"]);assert_eq!(merged["draft_artifact"],old["draft_artifact"]);assert_eq!(merged["status"],"finished");assert_eq!(old,saved);
}
#[test]
fn source_and_existing_native_scope_version_and_legacy_conflicts_refuse(){
 for fault in ["owner","chat","message","parent","children","mode","status","version","privacy"]{
  let mut row=raw();match fault{"owner"=>row["user_id"]=json!(CHAT),"chat"=>row["chat_id"]=json!(OWNER),"message"=>row["message_id"]=json!(CHAT),"parent"=>row["parent_embed_id"]=json!(CHAT),"children"=>row["embed_ids"]=json!([CHAT]),"mode"=>row["encryption_mode"]=json!("vault"),"status"=>row["status"]=json!("processing"),"version"=>row["version_number"]=json!(2),_=>row["is_private"]=json!("true")};assert!(source(&row,OWNER,CHAT,MESSAGE).is_err(),"{fault}");
 }
 let projected=source(&raw(),OWNER,CHAT,MESSAGE).unwrap();
 for fault in ["owner","chat","message","version","newer","legacy","parent","mode"]{
  let mut row=(*projected).clone();match fault{"owner"=>row["hashed_user_id"]=json!(sha256(CHAT)),"chat"=>row["hashed_chat_id"]=json!(sha256(OWNER)),"message"=>row["hashed_message_id"]=json!(sha256(CHAT)),"version"=>row["version_number"]=json!(2),"newer"=>row["updatedAt"]=json!(102),"legacy"=>row["data"]=json!("legacy encrypted object"),"parent"=>row["parent_embed_id"]=json!(CHAT),_=>row["encryption_mode"]=json!("vault")};let before=row.clone();assert!(merge(&projected,&row,OWNER,CHAT,MESSAGE).is_err(),"{fault}");assert_eq!(row,before);
 }
}
#[test]
fn wrapper_identity_and_native_composite_storage_key_are_exact(){
 let mut row=json!({"hashed_embed_id":sha256(EMBED),"key_type":"master","hashed_chat_id":null,"hashed_user_id":sha256(OWNER),"encrypted_embed_key":"opaque-real-validation-is-required"});
 wrapper(&row,OWNER,CHAT,EMBED).unwrap();assert_eq!(key_id(&row).unwrap(),format!("{}:master:null",sha256(EMBED)));
 row["key_type"]=json!("chat");row["hashed_chat_id"]=json!(sha256(CHAT));wrapper(&row,OWNER,CHAT,EMBED).unwrap();
 assert_eq!(key_id(&row).unwrap(),format!("{}:chat:{}",sha256(EMBED),sha256(CHAT)));
 for field in ["hashed_user_id","hashed_chat_id","hashed_embed_id","hashed_team_id"]{let mut bad=row.clone();bad[field]=json!(sha256(MESSAGE));assert!(wrapper(&bad,OWNER,CHAT,EMBED).is_err(),"{field}");}
}
#[test]
fn native_reread_requires_all_keys_targets_record_unknowns_metadata_and_same_db(){
 let record=source(&raw(),OWNER,CHAT,MESSAGE).unwrap();let keys=json!([{"id":"chat-key","unknown":true},{"id":"master-key","unknown":null}]);
 let before=json!({"db_version":45,"observation":{"metadata":{"chat_id":CHAT,"unknown_draft":"retained"},"record":null,"keys":[],"key_targets":[null,null]}});
 let after=json!({"record":&*record,"keys":keys});let written=json!({"db_version":45,"observation":{"metadata":before["observation"]["metadata"],"record":&*record,"keys":keys,"key_targets":[keys[1],keys[0]]}});
 verify_physical(&before,&written,&written,&after).unwrap();
 for fault in ["version","metadata","record","keys","targets"]{let mut changed=written.clone();match fault{"version"=>changed["db_version"]=json!(46),"metadata"=>changed["observation"]["metadata"]["unknown_draft"]=json!("changed"),"record"=>changed["observation"]["record"]["unknown"]=json!(true),"keys"=>changed["observation"]["keys"][0]["unknown"]=json!(false),_=>changed["observation"]["key_targets"][0]=Value::Null};assert!(verify_physical(&before,&written,&changed,&after).is_err(),"{fault}");}
}
#[test]
fn complete_merged_unknowns_and_new_ciphertext_are_bounded_before_native_write(){
 let mut source_row=(*source(&raw(),OWNER,CHAT,MESSAGE).unwrap()).clone();source_row["encrypted_content"]=json!("c".repeat(7*1024*1024));
 let mut old=(*source(&raw(),OWNER,CHAT,MESSAGE).unwrap()).clone();old["unknown"]=json!("u".repeat(10*1024*1024));bound(&source_row).unwrap();bound(&old).unwrap();let saved=old.clone();
 assert!(merge(&source_row,&old,OWNER,CHAT,MESSAGE).is_err());assert_eq!(old,saved);
}
