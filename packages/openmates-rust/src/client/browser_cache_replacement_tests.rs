//! Authored UNRUN original monitor/candidate/storage composition regressions.
// contract-test-file: tooling
use super::*;
use crate::crypto::master::{MasterCapability,MasterCrypto,MasterCryptoFuture};
use std::{cell::RefCell,rc::Rc,future::{ready,Ready},sync::Arc};
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const CHAT:&str="22222222-2222-4222-8222-222222222222";
struct Port;
impl MasterCrypto for Port {
 fn encrypt<'a>(&'a self,iv:&'a[u8;12],p:&'a[u8])->MasterCryptoFuture<'a>{Box::pin(async move{crypto::encrypt_aead(p,&[7;32],iv,&[]).map(Zeroizing::new)})}
 fn decrypt<'a>(&'a self,iv:&'a[u8;12],c:&'a[u8])->MasterCryptoFuture<'a>{Box::pin(async move{crypto::decrypt_aead(c,&[7;32],iv,&[])})}
}
fn header()->Value {json!({"id":CHAT,"chat_id":CHAT,"user_id":OWNER,"encrypted_chat_key":crypto::server_fields::encrypt_bytes(&[9;32],&[7;32],&[]).unwrap(),"encrypted_title":crypto::encrypt_combined("Title",&[9;32]).unwrap(),"messages_v":750,"title_v":1,"metadata_v":1,"local_draft":"must survive"})}
fn client()->Client {
 let mut c=Client::new("http://127.0.0.1:9",None).unwrap();c.browser_transport=true;c.user=json!({"id":OWNER});
 c.browser_authority=Some(crate::client::browser::BrowserAuthority{principal:OWNER.into(),persistence:crate::client::BrowserPersistence::MemoryOnly,owner_guards:true});
 c.browser_credentials=Some(crate::client::credentials::BrowserCredentials{api_url:"http://127.0.0.1:9".into(),session_id:OWNER.into(),cookies:BTreeMap::new(),ws_token:Some("synthetic".into()),master:MasterCapability::opaque_for_test(Arc::new(Port)),hashed_email:String::new(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None});c
}
fn row(id:&str,status:&str,cipher:&str)->Value{json!({"id":id,"message_id":id,"chat_id":CHAT,"role":"assistant","created_at":1,"status":status,"encrypted_content":cipher})}
fn fence(c:&Client)->Fence{Fence{parent:c.operation_parent.clone(),private_gate:c.options.private_operation_gate.clone(),scope:AsyncCryptoScope::begin(c).unwrap(),epoch:c.fresh_auth.operation_epoch(),binding:Zeroizing::new(c.fresh_auth_binding().unwrap()),source_stamp:source_stamp(c,CHAT).unwrap(),revision:c.credential_revision}}
fn host()->BrowserMetadataCacheScope{serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":0})).unwrap()}
fn state(c:&Client)->BrowserCandidateFailures{BrowserCandidateFailures{owner:OWNER.into(),chat:CHAT.into(),scope:AsyncCryptoScope::begin(c).unwrap(),epoch:c.fresh_auth.operation_epoch(),binding:Zeroizing::new(c.fresh_auth_binding().unwrap()),policy:candidate_policy::KeyFailures::new(&Zeroizing::new([9;32]))}}
fn page(metadata:Value,row:Value)->crate::client::message_window::BrowserIncomingMessagePage {crate::client::message_window::BrowserIncomingMessagePage{metadata:Plain::new(metadata),messages:Plain::new(vec![row]),key:Zeroizing::new([9;32])}}
struct Store{metadata:Value,rows:BTreeMap<String,Value>,plans:Vec<Value>,fault:&'static str,monitor:Option<Arc<crate::client::monitor::ChatMonitor>>}
fn frames(queries:&[Value],active:&[bool],rows:&BTreeMap<String,Value>)->Value{json!(queries.iter().zip(active).map(|(q,active)|{let mut set=if *active{rows.values().filter(|r|r["role"]=="assistant"&&r["message_id"]!=q["messageId"]&&r["encrypted_content"]==q["encryptedContent"]&&r["created_at"].as_u64().zip(q["createdAt"].as_u64()).is_some_and(|(a,b)|a.abs_diff(b)<60)).cloned().collect::<Vec<_>>()}else{vec![]};set.sort_by(|a,b|a["created_at"].as_u64().cmp(&b["created_at"].as_u64()).then_with(||wire::idb_key_cmp(text(a,"message_id"),text(b,"message_id"))));json!({"messageId":q["messageId"],"rows":set})}).collect::<Vec<_>>())}
fn io(s:Rc<RefCell<Store>>)->impl FnMut(String)->Ready<Result<String>>{move|encoded|{
 let p:Value=serde_json::from_str(&encoded).unwrap();let mut s=s.borrow_mut();s.plans.push(p.clone());
 let ids=p["messageIds"].as_array().unwrap();let mut rows=ids.iter().map(|id|s.rows.get(id.as_str().unwrap()).cloned().unwrap_or(Value::Null)).collect::<Vec<_>>();
 let regular=matches!(p["kind"].as_str(),Some("readback"|"readback_metadata_only"));
 if regular{return ready(Ok(json!({"version":1,"kind":p["kind"],"operationId":p["operationId"],"databaseVersion":32,"transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,"metadata":s.metadata,"rows":rows,"before":null}).to_string()))}
 let queries=p["candidateQueries"].as_array().unwrap();let active=queries.iter().map(|q|rows[ids.iter().position(|id|id==&q["messageId"]).unwrap()].is_null()).collect::<Vec<_>>();let initial=frames(queries,&active,&s.rows);let mut before=Value::Null;let mut before_candidates=Value::Null;let mut deleted=json!([]);
 if p["kind"]=="compare_and_replace_monitor_candidates" {
  before=json!(rows);before_candidates=initial.clone();
  if s.metadata.is_null(){assert_eq!(p["expectedMetadata"],Value::Null);s.metadata=p["metadataInsert"].clone();}
  for d in p["candidateDeletes"].as_array().unwrap(){s.rows.remove(d["messageId"].as_str().unwrap());}deleted=p["candidateDeletes"].clone();
  for(i,patch)in p["patches"].as_array().unwrap().iter().enumerate(){if let Some(value)=patch.get("insert"){s.rows.insert(ids[i].as_str().unwrap().into(),value.clone());rows[i]=value.clone();}else if patch.get("retainCandidateId").is_none(){let mut next=rows[i].clone();for(k,v)in patch["set"].as_object().unwrap(){next[k]=v.clone();}for k in patch["remove"].as_array().unwrap(){next.as_object_mut().unwrap().remove(k.as_str().unwrap());}s.rows.insert(ids[i].as_str().unwrap().into(),next.clone());rows[i]=next;}}
  if s.fault=="close-after-commit"{s.monitor.as_ref().unwrap().close();}
 }
 let after=if p["kind"]=="capture_monitor_candidates"{initial}else{frames(queries,&active,&s.rows)};
 ready(Ok(json!({"version":1,"kind":p["kind"],"operationId":p["operationId"],"databaseVersion":32,"transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,"metadata":s.metadata,"rows":rows,"before":before,"candidates":after,"beforeCandidates":before_candidates,"deleted":deleted}).to_string()))
}}
#[tokio::test]
async fn known_failure_then_corrected_cipher_replaces_only_supported_old_row_and_keeps_original_socket_proof(){
 let mut c=client();let monitor=Arc::new(c.retain_browser_monitor_for_test().unwrap());let ctx=c.browser_monitor_read_context(&monitor,OWNER,CHAT).unwrap();let f=fence(&c);let cipher=crypto::encrypt_combined("text",&[9;32]).unwrap();let old=row("old","delivered",&cipher);let new=row("new","synced",&cipher);let meta=header();let s=Rc::new(RefCell::new(Store{metadata:meta.clone(),rows:[("old".into(),old.clone())].into_iter().collect(),plans:vec![],fault:"",monitor:Some(monitor.clone())}));
 let mut failures=state(&c);failures.policy.project(&row("old","delivered","broken"),CHAT,candidate_policy::ReadMode::Connected).unwrap();
 let data=c.cache_monitor_candidates(&ctx,&f,&mut failures,OWNER,CHAT,host(),123,page(meta,new),&mut io(s.clone())).await.unwrap();
 assert!(!s.borrow().rows.contains_key("old"));assert!(s.borrow().rows.contains_key("new"));assert_eq!(s.borrow().metadata["local_draft"],"must survive");assert_eq!(data.dispositions[0]["disposition"],"replaced");assert_eq!(data.dispositions[0]["canonicalIncomingDurablyAcknowledged"],false);
 let token=BrowserRetainedMessageCache{fence:f,monitor_context:Some(ctx),owner:OWNER.into(),chat:CHAT.into(),data};assert!(token.ensure_current(&c).is_ok());monitor.close();assert!(token.ensure_current(&c).is_err());assert_eq!(c.credential_ack,0);
}
#[tokio::test]
async fn healthy_decrypted_candidate_is_not_duplicate_and_equal_status_failure_retains_actual_old_physical_row(){
 for known in [false,true]{let mut c=client();let monitor=c.retain_browser_monitor_for_test().unwrap();let ctx=c.browser_monitor_read_context(&monitor,OWNER,CHAT).unwrap();let f=fence(&c);let cipher=crypto::encrypt_combined("text",&[9;32]).unwrap();let old=row("old","delivered",&cipher);let new=row("new","delivered",&cipher);let meta=header();let s=Rc::new(RefCell::new(Store{metadata:meta.clone(),rows:[("old".into(),old)].into_iter().collect(),plans:vec![],fault:"",monitor:None}));let mut failures=state(&c);if known{failures.policy.project(&row("old","delivered","broken"),CHAT,candidate_policy::ReadMode::Connected).unwrap();}
 let data=c.cache_monitor_candidates(&ctx,&f,&mut failures,OWNER,CHAT,host(),123,page(meta,new),&mut io(s.clone())).await.unwrap();
 assert!(s.borrow().rows.contains_key("old"));assert_eq!(s.borrow().rows.contains_key("new"),!known);assert_eq!(data.readback["rows"][0]["message_id"],if known{"old"}else{"new"});assert_eq!(data.dispositions[0]["incomingPhysicalMessageId"],"new");assert_eq!(data.dispositions[0]["disposition"],if known{"retained"}else{"inserted"});}
}
#[tokio::test]
async fn protected_pending_call_unknown_or_unverified_duplicate_never_reaches_write_plan(){
 for field in ["pending_encrypted_turn_preflight_v1","call_persistence_v1","unknown_local","encrypted_model_name"]{let mut c=client();let monitor=c.retain_browser_monitor_for_test().unwrap();let ctx=c.browser_monitor_read_context(&monitor,OWNER,CHAT).unwrap();let f=fence(&c);let cipher=crypto::encrypt_combined("text",&[9;32]).unwrap();let mut old=row("old","delivered",&cipher);old[field]=if field=="call_persistence_v1"{json!({"entries":[]})}else{json!("must survive")};let new=row("new","synced",&cipher);let meta=header();let s=Rc::new(RefCell::new(Store{metadata:meta.clone(),rows:[("old".into(),old.clone())].into_iter().collect(),plans:vec![],fault:"",monitor:None}));let mut failures=state(&c);failures.policy.project(&row("old","delivered","broken"),CHAT,candidate_policy::ReadMode::Connected).unwrap();assert!(c.cache_monitor_candidates(&ctx,&f,&mut failures,OWNER,CHAT,host(),123,page(meta,new),&mut io(s.clone())).await.is_err());assert_eq!(s.borrow().plans.len(),1);assert_eq!(s.borrow().rows["old"],old);assert!(!s.borrow().rows.contains_key("new"));}
}
#[tokio::test]
async fn socket_close_after_legitimate_commit_cannot_publish_or_resume_readback(){let mut c=client();let monitor=Arc::new(c.retain_browser_monitor_for_test().unwrap());let ctx=c.browser_monitor_read_context(&monitor,OWNER,CHAT).unwrap();let f=fence(&c);let cipher=crypto::encrypt_combined("text",&[9;32]).unwrap();let meta=header();let s=Rc::new(RefCell::new(Store{metadata:meta.clone(),rows:BTreeMap::new(),plans:vec![],fault:"close-after-commit",monitor:Some(monitor)}));let mut failures=state(&c);assert!(c.cache_monitor_candidates(&ctx,&f,&mut failures,OWNER,CHAT,host(),123,page(meta,row("new","synced",&cipher)),&mut io(s.clone())).await.is_err());assert_eq!(s.borrow().plans.len(),2);}
#[test]
fn key_owner_epoch_or_resource_change_cannot_reuse_candidate_failure_state(){let mut c=client();let state=state(&c);let key=Zeroizing::new([9;32]);assert!(state.reusable(&c,OWNER,CHAT,&key));assert!(!state.reusable(&c,CHAT,CHAT,&key));assert!(!state.reusable(&c,OWNER,CHAT,&Zeroizing::new([8;32])));c.set_interactive(true);assert!(!state.reusable(&c,OWNER,CHAT,&key));}

#[tokio::test]
async fn public_monitor_cache_uses_one_metadata_and_one_page_then_owns_context_until_release(){
 use tokio::io::{AsyncReadExt,AsyncWriteExt};
 tokio::time::timeout(std::time::Duration::from_secs(10),async{
  let meta=header();let cipher=crypto::encrypt_combined("text",&[9;32]).unwrap();let incoming=row("new","synced",&cipher);let bytes=serde_json::to_vec(&incoming).unwrap().len();
  let window=json!({"chat_id":CHAT,"messages":[incoming],"has_more_before":false,"has_more_after":false,"start_cursor":{"created_at":1,"message_id":"new"},"end_cursor":{"created_at":1,"message_id":"new"},"anchor_found":true,"payload_bytes":bytes,"oversized_message":false,"oversized_message_cursor":null,"server_message_count":1,"messages_v":750});
  let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let endpoint=format!("http://{}",listener.local_addr().unwrap());
  let replies=vec![json!({"chats":[meta.clone()]}),window];
  let task=tokio::spawn(async move{for(index,reply)in replies.into_iter().enumerate(){let(mut socket,_)=listener.accept().await.unwrap();let mut bytes=Vec::new();loop{let mut one=[0u8;1];socket.read_exact(&mut one).await.unwrap();bytes.push(one[0]);assert!(bytes.len()<16384);if bytes.ends_with(b"\r\n\r\n"){break;}}let head=String::from_utf8(bytes).unwrap();let content_length=head.lines().find_map(|line|line.to_ascii_lowercase().strip_prefix("content-length:").map(|s|s.trim().parse::<usize>().unwrap())).unwrap_or(0);let mut body=vec![0;content_length];socket.read_exact(&mut body).await.unwrap();if index==0{assert!(head.starts_with("POST /v1/chats/metadata/batch "));}else{assert!(head.starts_with(&format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=1&respect_compression_boundary=true ")));}let body=reply.to_string();socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).as_bytes()).await.unwrap();}});
  struct Peer(Option<tokio::task::JoinHandle<()>>);impl Drop for Peer{fn drop(&mut self){if let Some(task)=&self.0{task.abort();}}}let mut peer=Peer(Some(task));
  let mut c=client();c.base=url::Url::parse(&endpoint).unwrap();c.browser_credentials.as_mut().unwrap().api_url=endpoint;c.set_app_origin(Some("https://app.example.invalid".into())).unwrap();
  let monitor=c.retain_browser_monitor_for_test().unwrap();let ctx=c.browser_monitor_read_context(&monitor,OWNER,CHAT).unwrap();let s=Rc::new(RefCell::new(Store{metadata:meta,rows:BTreeMap::new(),plans:vec![],fault:"",monitor:None}));let mut failures=None;
  let token=c.browser_prepare_retained_monitor_message_cache(ctx,&mut failures,OWNER,CHAT,crate::client::message_window::MessageWindowOptions{limit:1,..Default::default()},host(),123,true,io(s.clone())).await.unwrap();
  peer.0.take().unwrap().await.unwrap();assert_eq!(s.borrow().plans.len(),3);assert!(token.ensure_current(&c).is_ok());monitor.close();assert!(token.ensure_current(&c).is_err());assert_eq!(c.credential_ack,0);
 }).await.unwrap();
}
#[test]
fn local_terminal_candidate_is_never_deleted_by_a_higher_server_status(){let cipher=crypto::encrypt_combined("text",&[9;32]).unwrap();for status in ["failed","streaming","processing","queued","waiting_for_user"]{let old=row("old",status,&cipher);let before=old.clone();assert!(deletion_guard(&old,&row("new","synced",&cipher),CHAT,&Zeroizing::new([9;32])).is_err());assert_eq!(old,before);}}

#[tokio::test]
async fn sealed_monitored_publication_keeps_original_socket_context_after_prepare_until_take(){
 use tokio::io::{AsyncReadExt,AsyncWriteExt};
 tokio::time::timeout(std::time::Duration::from_secs(10),async{
  let meta=header();let cipher=crypto::encrypt_combined("text",&[9;32]).unwrap();let incoming=row("new","synced",&cipher);let bytes=serde_json::to_vec(&incoming).unwrap().len();
  let window=json!({"chat_id":CHAT,"messages":[incoming],"has_more_before":false,"has_more_after":false,"start_cursor":{"created_at":1,"message_id":"new"},"end_cursor":{"created_at":1,"message_id":"new"},"anchor_found":true,"payload_bytes":bytes,"oversized_message":false,"oversized_message_cursor":null,"server_message_count":1,"messages_v":750});
  let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let endpoint=format!("http://{}",listener.local_addr().unwrap());
  let replies=vec![json!({"chats":[meta.clone()]}),window];
  let task=tokio::spawn(async move{for(index,reply)in replies.into_iter().enumerate(){let(mut socket,_)=listener.accept().await.unwrap();let mut bytes=Vec::new();loop{let mut one=[0u8;1];socket.read_exact(&mut one).await.unwrap();bytes.push(one[0]);assert!(bytes.len()<16384);if bytes.ends_with(b"\r\n\r\n"){break;}}let head=String::from_utf8(bytes).unwrap();let content_length=head.lines().find_map(|line|line.to_ascii_lowercase().strip_prefix("content-length:").map(|s|s.trim().parse::<usize>().unwrap())).unwrap_or(0);let mut body=vec![0;content_length];socket.read_exact(&mut body).await.unwrap();if index==0{assert!(head.starts_with("POST /v1/chats/metadata/batch "));}else{assert!(head.starts_with(&format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=1&respect_compression_boundary=true ")));}let body=reply.to_string();socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body).as_bytes()).await.unwrap();}});
  struct Peer(Option<tokio::task::JoinHandle<()>>);impl Drop for Peer{fn drop(&mut self){if let Some(task)=&self.0{task.abort();}}}let mut peer=Peer(Some(task));
  let mut c=client();c.base=url::Url::parse(&endpoint).unwrap();c.browser_credentials.as_mut().unwrap().api_url=endpoint;c.set_app_origin(Some("https://app.example.invalid".into())).unwrap();
  let monitor=c.retain_browser_monitor_for_test().unwrap();let s=Rc::new(RefCell::new(Store{metadata:meta,rows:BTreeMap::new(),plans:vec![],fault:"",monitor:None}));let mut failures=None;
  let publication=c.prepare_browser_monitored_retained_saved_chat_with_io(&monitor,&mut failures,OWNER,CHAT,crate::client::message_window::MessageWindowOptions{limit:1,..Default::default()},host(),123,true,io(s.clone())).await.unwrap();
  peer.0.take().unwrap().await.unwrap();assert_eq!(s.borrow().plans.len(),4);monitor.close();assert!(c.browser_retained_cache_publication_json(publication,true).is_err());assert_eq!(c.credential_ack,0);
 }).await.unwrap();
}