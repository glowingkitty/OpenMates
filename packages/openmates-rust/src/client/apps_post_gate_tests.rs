//! Direct caller gates retain their exact order and count before final negatives.
use super::*;
use std::sync::{Arc, Mutex, atomic::{AtomicUsize, Ordering}};
fn client()->Client {
    let endpoint="http://127.0.0.1:9";
    let session=serde_json::from_value(json!({"api_url":endpoint,"session_id":"synthetic","cookies":{},"ws_token":null,"master_key":"BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=","hashed_email":"synthetic","user_email_salt":"synthetic","email_encryption_key":null,"created_at":1,"paired_session_expires_at":null,"active_team_id":null})).unwrap();
    let mut c=Client::new(endpoint,Some(session)).unwrap();c.user=json!({"id":"synthetic-owner"});c
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[test]
fn final_successful_original_callback_cannot_cancel_or_mark_denial() {
    for deny in [false,true] {
        let mut c=client();let count=Arc::new(AtomicUsize::new(0));let target=Arc::new(AtomicUsize::new(0));
        let (calls,trigger)=(count.clone(),target.clone());let token=c.operation_parent.clone();let authority=c.task_watch_authority.clone();
        c.set_private_operation_gate(Some(Arc::new(move || {
            if calls.fetch_add(1,Ordering::SeqCst)+1==trigger.load(Ordering::SeqCst) {
                if deny {authority.deny_cached_chat(None)?;} else {token.cancel();}
            }
            Ok(())
        })));
        let admission=c.direct_app_skill_admission().unwrap();
        count.store(0,Ordering::SeqCst);admission.check(&c).unwrap();assert_eq!(count.load(Ordering::SeqCst),4);
        count.store(0,Ordering::SeqCst);target.store(4,Ordering::SeqCst);
        assert!(admission.check(&c).is_err());assert_eq!(count.load(Ordering::SeqCst),4);
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[test]
fn direct_callback_order_survives_current_gate_replacement() {
    let mut c=client();let log=Arc::new(Mutex::new(Vec::new()));let original=log.clone();
    c.set_private_operation_gate(Some(Arc::new(move || {original.lock().unwrap().push("original");Ok(())})));
    let admission=c.direct_app_skill_admission().unwrap();let current=log.clone();
    c.set_private_operation_gate(Some(Arc::new(move || {current.lock().unwrap().push("current");Ok(())})));
    log.lock().unwrap().clear();admission.check(&c).unwrap();
    assert_eq!(*log.lock().unwrap(),vec!["original","current","current","original"]);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[test]
fn final_successful_callback_cannot_revoke_original_master_resource() {
    let mut c=client();let creds=credentials::BrowserCredentials::from_native_session(c.session.take().unwrap());
    let master=creds.master.clone();c.browser_credentials=Some(creds);
    c.browser_authority=Some(browser::BrowserAuthority {principal:"synthetic-owner".into(),persistence:browser::BrowserPersistence::MemoryOnly,owner_guards:true});c.browser_transport=true;
    let calls=Arc::new(AtomicUsize::new(0));let target=Arc::new(AtomicUsize::new(0));let (count,trigger)=(calls.clone(),target.clone());
    c.set_private_operation_gate(Some(Arc::new(move || {
        if count.fetch_add(1,Ordering::SeqCst)+1==trigger.load(Ordering::SeqCst) {master.invalidate();}
        Ok(())
    })));
    let admission=c.direct_app_skill_admission().unwrap();calls.store(0,Ordering::SeqCst);target.store(4,Ordering::SeqCst);
    assert!(admission.check(&c).is_err());assert_eq!(calls.load(Ordering::SeqCst),4);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[test]
fn restrictive_app_final_recheck_refuses_successful_callback_denial_without_more_callbacks() {
    let mut c=client();
    let calls=Arc::new(AtomicUsize::new(0));let trigger=Arc::new(AtomicUsize::new(0));
    let (count,target)=(calls.clone(),trigger.clone());let authority=c.task_watch_authority.clone();
    c.set_private_operation_gate(Some(Arc::new(move || {
        if count.fetch_add(1,Ordering::SeqCst)+1==target.load(Ordering::SeqCst) {authority.deny_cached_chat(None)?;}
        Ok(())
    })));
    let admission=c.direct_app_skill_admission().unwrap();
    calls.store(0,Ordering::SeqCst);
    admission.check_after_private_gate(&c).unwrap();
    assert_eq!(calls.load(Ordering::SeqCst),0);
    trigger.store(1,Ordering::SeqCst);
    c.verify_private_operation().unwrap(); // Final caller callback itself succeeded.
    assert_eq!(calls.load(Ordering::SeqCst),1);
    assert!(admission.check_after_private_gate(&c).is_err());
    assert_eq!(calls.load(Ordering::SeqCst),1);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[test]
fn restrictive_app_final_recheck_refuses_successful_callback_master_revocation_without_more_callbacks() {
    let mut c=client();let creds=credentials::BrowserCredentials::from_native_session(c.session.take().unwrap());
    let master=creds.master.clone();c.browser_credentials=Some(creds);
    c.browser_authority=Some(browser::BrowserAuthority {principal:"synthetic-owner".into(),persistence:browser::BrowserPersistence::MemoryOnly,owner_guards:true});c.browser_transport=true;
    let calls=Arc::new(AtomicUsize::new(0));let trigger=Arc::new(AtomicUsize::new(0));
    let (count,target)=(calls.clone(),trigger.clone());
    c.set_private_operation_gate(Some(Arc::new(move || {
        if count.fetch_add(1,Ordering::SeqCst)+1==target.load(Ordering::SeqCst) {master.invalidate();}
        Ok(())
    })));
    let admission=c.direct_app_skill_admission().unwrap();
    calls.store(0,Ordering::SeqCst);
    admission.check_after_private_gate(&c).unwrap();
    assert_eq!(calls.load(Ordering::SeqCst),0);
    trigger.store(1,Ordering::SeqCst);
    c.verify_private_operation().unwrap(); // Policy success cannot override key revocation.
    assert_eq!(calls.load(Ordering::SeqCst),1);
    assert!(admission.check_after_private_gate(&c).is_err());
    assert_eq!(calls.load(Ordering::SeqCst),1);
}
