//! Actual ordinary-policy scope cases, authored UNRUN for isolated Rust CI.
//! Explicit synthetic already-admitted fresh context, no native discovery/HTTP.
//! This does not claim real password auth, WASM import or browser storage proof.
//! Existing restore is never promoted into a mutating retention operation.
//! Ordinary preference remains separate from Worker lifetime and stronger ACK.
// contract-test-file: tooling
use super::*;
const OWNER:&str="11111111-1111-4111-8111-111111111111";
fn session()->Session{Session{api_url:"http://127.0.0.1:9".into(),session_id:OWNER.into(),cookies:BTreeMap::new(),ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),hashed_email:String::new(),user_email_salt:String::new(),email_encryption_key:None,created_at:now_ms(),paired_session_expires_at:None,active_team_id:None}}
fn client()->Client{
 let mut client=Client::new("http://127.0.0.1:9",None).unwrap();client.user=json!({"id":OWNER});client.generation=1;client.browser_transport=true;client.browser_password_transport=true;client.browser_password_stay_logged_in=Some(true);
 client.browser_authority=Some(BrowserAuthority{principal:OWNER.into(),persistence:BrowserPersistence::MemoryOnly,owner_guards:false});
 client.browser_credentials=Some(credentials::BrowserCredentials::from_native_session(session()));client
}
#[test]
fn fresh_preference_requests_ordinary_put_or_memory_delete_without_absence_gate(){
 for stay in [false,true]{let mut client=client();client.browser_password_stay_logged_in=Some(stay);let operation=begin(&client,stay,1).unwrap();let mut effect:Value=serde_json::from_str(&operation.effect_json(&client).unwrap()).unwrap();
 let shared:Value=serde_json::from_str(include_str!("../../tests/fixtures/browser-ordinary-retention.json")).unwrap();effect["operationId"]=shared["cases"][usize::from(stay)]["effect"]["operationId"].clone();assert_eq!(effect,shared["cases"][usize::from(stay)]["effect"]);
 assert_eq!(effect["action"],if stay{"save_persisted"}else{"save_memory"});assert_eq!(effect["credentialAcknowledged"],false);assert_eq!(effect["crossDatabaseAssociationProven"],false);
 assert_eq!(client.browser_authority.as_ref().unwrap().persistence,BrowserPersistence::MemoryOnly);assert_eq!(client.credential_ack,0);assert!(!client.browser_authority.as_ref().unwrap().owner_guards);}
}
#[test]
fn existing_restore_or_local_or_native_context_cannot_become_mutating_fresh_login(){
 for change in 0..5{let mut client=client();match change{0=>client.browser_password_transport=false,1=>client.browser_local_read_only=true,2=>client.browser_transport=false,3=>client.generation=0,_=>client.session=Some(session())};assert!(matches!(begin(&client,true,1),Err(Error::Forbidden)));}
}
#[test]
fn effect_has_no_secret_channel_or_stronger_proof_and_requires_safe_lifecycle(){
 let client=client();let operation=begin(&client,true,1).unwrap();let encoded=operation.effect_json(&client).unwrap();let value:Value=serde_json::from_str(&encoded).unwrap();
 assert_eq!(value.as_object().unwrap().len(),8);assert!(!encoded.contains("masterKey"));assert!(!encoded.contains("ws_token"));assert!(!encoded.contains("encrypted_email"));assert!(!encoded.contains("transactionCommitted"));
 for value in [0,MAX_SAFE+1]{assert!(begin(&client,true,value).is_err());}
}
#[test]
fn scope_rejects_owner_endpoint_session_key_generation_denial_or_cancel_before_handoff(){
 for change in 0..7{let mut client=client();let operation=begin(&client,true,1).unwrap();match change{
 0=>client.user["id"]=json!("22222222-2222-4222-8222-222222222222"),1=>client.browser_credentials.as_mut().unwrap().api_url="http://127.0.0.1:10".into(),
 2=>client.browser_credentials.as_mut().unwrap().session_id="changed".into(),3=>client.master_capability().unwrap().invalidate(),4=>client.generation+=1,
 5=>client.task_watch_authority.deny_cached_chat(None).unwrap(),_=>client.operation_cancel.cancel()};assert!(operation.effect_json(&client).is_err());assert_eq!(client.credential_ack,0);}
}

#[test]
fn local_retention_preference_must_match_the_actual_fresh_login_options(){let client=client();assert!(begin(&client,false,1).is_err());let mut client=client;let operation=begin(&client,true,1).unwrap();client.browser_password_stay_logged_in=Some(false);assert!(operation.effect_json(&client).is_err());}
