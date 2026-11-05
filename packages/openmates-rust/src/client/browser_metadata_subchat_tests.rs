//! Pure data-policy controls only. Actual native/auth/browser execution UNRUN.
use super::*;
fn fixture()->Value {serde_json::from_str(include_str!("../../tests/fixtures/browser-subchat-metadata-bootstrap.json")).unwrap()}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted,auth.session.isolation
#[test]
fn actual_child_navigation_shape_preserves_draft_floors_and_unknown_fields() {
 let f=fixture();let owner=f["owner"].as_str().unwrap();let child=f["child"].as_str().unwrap();
 for case in f["cases"].as_array().unwrap(){let result=merge_subchat(&case["source"],&case["before"],child,owner,f["now"].as_u64().unwrap());
  if case["refused"]==true {assert!(result.is_err(),"{}",case["id"]);continue}
  let after=result.unwrap();assert_eq!(after["parent_id"],case["expected_parent"]);assert_eq!(after["is_sub_chat"],true);assert_eq!(after["chat_id"],child);assert_eq!(after["title"],Value::Null);assert!(after.get("messages").is_none());assert_eq!(after["encrypted_chat_key"],case["source"]["encrypted_chat_key"]);
  for field in case["preserve"].as_array().into_iter().flatten(){let field=field.as_str().unwrap();assert_eq!(after.get(field),case["before"].get(field),"{}:{field}",case["id"]);}
  for field in case["absent"].as_array().into_iter().flatten(){assert!(after.get(field.as_str().unwrap()).is_none());}
  if let Some(fields)=case["fields"].as_object(){for(field,value)in fields {assert_eq!(after.get(field),Some(value));}}
 }
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[test]
fn caller_parent_labels_cannot_select_source_link_and_parent_path_stays_strict() {
 let f=fixture();let child=f["child"].as_str().unwrap();let owner=f["owner"].as_str().unwrap();let source=f["cases"][0]["source"].clone();
 let mut before=json!({"chat_id":child,"caller_parent_id":"55555555-5555-4555-8555-555555555555"});
 let after=merge_subchat(&source,&before,child,owner,3).unwrap();assert_eq!(after["parent_id"],source["parent_id"]);assert_eq!(after["caller_parent_id"],before["caller_parent_id"]);
 assert!(merge(&source,&Value::Null,child,owner,3).is_err());
 before["is_sub_chat"]=json!(true);before["parent_id"]=source["parent_id"].clone();let mut parent=source.clone();parent.as_object_mut().unwrap().remove("parent_id");parent["is_sub_chat"]=json!(false);
 assert!(merge(&parent,&before,child,owner,3).is_err());
 assert!(merge(&parent,&Value::Null,child,owner,3).is_ok());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
#[test]
fn same_second_revision_advance_and_canonical_rewrap_keep_child_edge() {
 let f=fixture();let child=f["child"].as_str().unwrap();let owner=f["owner"].as_str().unwrap();let mut source=f["cases"][0]["source"].clone();let before=json!({"chat_id":child,"parent_id":f["parent"],"is_sub_chat":true,"encrypted_title":"old","title_v":1,"metadata_v":1,"updated_at":2});
 assert_eq!(merge_subchat(&source,&before,child,owner,3).unwrap()["title_v"],2);
 source["title_v"]=json!(1);source["metadata_v"]=json!(1);assert_eq!(merge_subchat(&source,&before,child,owner,3).unwrap()["encrypted_title"],source["encrypted_title"]);
 source["metadata_v"]=json!(0);assert!(merge_subchat(&source,&before,child,owner,3).is_err());
}
