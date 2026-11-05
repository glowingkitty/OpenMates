//! Synchronous successful caller callbacks must not publish retired authority.
use super::*;
use std::sync::{Arc, Mutex, atomic::{AtomicUsize, Ordering}};
const ID: &str = "22222222-2222-4222-8222-222222222222";
fn client() -> Client {
    let endpoint="http://127.0.0.1:9";
    let session=serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).unwrap();
    let mut c=Client::new(endpoint,Some(session)).unwrap();c.user=json!({"id":"synthetic-owner"});c
}
fn install(c:&mut Client, deny:bool)->(Arc<AtomicUsize>,Arc<AtomicUsize>) {
    let calls=Arc::new(AtomicUsize::new(0));let target=Arc::new(AtomicUsize::new(0));
    let (count,trigger)=(calls.clone(),target.clone());let token=c.operation_parent.clone();let authority=c.task_watch_authority.clone();
    c.set_private_operation_gate(Some(Arc::new(move || {
        let n=count.fetch_add(1,Ordering::SeqCst)+1;
        if n==trigger.load(Ordering::SeqCst) {
            if deny {authority.deny_cached_chat(Some(ID))?;} else {token.cancel();}
        }
        Ok(()) // The callback itself grants success, even when it retires A.
    })));
    (calls,target)
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[test]
fn final_successful_callback_cannot_cancel_or_deny_original_full_admission() {
    for restored in [false,true] {for deny in [false,true] {
        let mut c=client();let (calls,target)=install(&mut c,deny);
        let mut admission=c.full_chat_read_admission(ID).unwrap();
        if restored {admission.restore_team(&mut c,Some("33333333-3333-4333-8333-333333333333")).unwrap();}
        calls.store(0,Ordering::SeqCst);target.store(if restored {3}else{4},Ordering::SeqCst);
        assert!(admission.check(&c).is_err());
        assert_eq!(calls.load(Ordering::SeqCst),target.load(Ordering::SeqCst));
    }}
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[test]
fn full_callback_order_and_count_survive_current_gate_replacement() {
    for restored in [false,true] {
        let mut c=client();let log=Arc::new(Mutex::new(Vec::new()));let original=log.clone();
        c.set_private_operation_gate(Some(Arc::new(move || {original.lock().unwrap().push("original");Ok(())})));
        let mut admission=c.full_chat_read_admission(ID).unwrap();
        if restored {admission.restore_team(&mut c,Some("33333333-3333-4333-8333-333333333333")).unwrap();}
        let current=log.clone();c.set_private_operation_gate(Some(Arc::new(move || {current.lock().unwrap().push("current");Ok(())})));
        log.lock().unwrap().clear();admission.check(&c).unwrap();
        assert_eq!(*log.lock().unwrap(),if restored {vec!["original","original","current"]}else{vec!["original","current","original","current"]});
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[tokio::test]
async fn actual_full_projection_rechecks_after_last_successful_callback() {
    for deny in [false,true] {for retire in [false,true] {
        let mut c=client();let (calls,target)=install(&mut c,deny);
        // Draft-only projection is a real supported path with no slug decryption.
        c.chats.insert(ID.into(),json!({"id":ID,"encrypted_draft_md":"synthetic-encrypted-draft"}));
        let admission=c.full_chat_read_admission(ID).unwrap();let scope=AsyncCryptoScope::begin(&c).unwrap();
        let chat=Plain::new(serde_json::from_value::<Chat>(serde_json::from_str::<Value>(include_str!("../../tests/fixtures/full-chat-read-metadata.json")).unwrap()["chat"].clone()).unwrap());
        calls.store(0,Ordering::SeqCst);target.store(if retire {9}else{0},Ordering::SeqCst);
        let result=c.full_chat_read_projection(ID,chat,&scope,admission).await;
        assert_eq!(calls.load(Ordering::SeqCst),9);
        if retire {assert!(result.is_err());} else {let read=result.unwrap();assert_eq!(read.chat.id,ID);assert_eq!(read.slug,None);}
    }}
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[test]
fn final_successful_callback_cannot_revoke_original_master_after_team_restoration() {
    for restored in [false,true] {
        let mut c=client();
        let creds=credentials::BrowserCredentials::from_native_session(c.session.take().unwrap());
        let master=creds.master.clone();c.browser_credentials=Some(creds);
        c.browser_authority=Some(browser::BrowserAuthority {principal:"synthetic-owner".into(),persistence:browser::BrowserPersistence::MemoryOnly,owner_guards:true});
        c.browser_transport=true;
        let calls=Arc::new(AtomicUsize::new(0));let target=Arc::new(AtomicUsize::new(0));let (count,trigger)=(calls.clone(),target.clone());
        c.set_private_operation_gate(Some(Arc::new(move || {
            if count.fetch_add(1,Ordering::SeqCst)+1==trigger.load(Ordering::SeqCst) {master.invalidate();}
            Ok(())
        })));
        let mut admission=c.full_chat_read_admission(ID).unwrap();
        if restored {admission.restore_team(&mut c,Some("33333333-3333-4333-8333-333333333333")).unwrap();}
        calls.store(0,Ordering::SeqCst);target.store(if restored {3}else{4},Ordering::SeqCst);
        assert!(admission.check(&c).is_err());assert_eq!(calls.load(Ordering::SeqCst),target.load(Ordering::SeqCst));
    }
}
