//! Authored pure registry/cancellation regressions. No network or credentials.
use super::*;
const SELECTED:&str="22222222-2222-4222-8222-222222222222";
const OTHER:&str="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
fn bridge()->SessionBridge { SessionBridge::new(&json!({"api_url":"http://127.0.0.1:1","enhanced_privacy":false,"allow_private_operations":true}).to_string()).unwrap_or_else(|_|panic!("selected bridge fixture")) }
fn job(chat:&str,guard:Arc<EssentialGuard>)->Job {
    Job{value:CompletionRecoveryJob{kind:openmates_sdk::client::CompletionRecoveryKind::Main,job_id:uuid::Uuid::new_v4().to_string(),chat_id:chat.into(),turn_id:None,assistant_message_id:None,task_id:None,stage:None,chat_key_version:1,created_at:None},guard}
}
#[test]
fn selected_registry_quota_refusal_is_atomic_and_preserves_other_owner() {
    let bridge=bridge();let owner=EssentialGuard::new(&bridge,true).unwrap_or_else(|_|panic!("selected guard fixture"));
    let mut jobs=BTreeMap::from([("old-selected".into(),job(SELECTED,owner.clone())),("unrelated".into(),job(OTHER,owner.clone()))]);
    assert_eq!(replace_discovered_selection(&mut jobs,Some(SELECTED),CAP).unwrap_err().code,"protocol");
    assert_eq!(jobs.len(),2);assert!(jobs.contains_key("old-selected"));assert!(jobs.contains_key("unrelated"));
    assert!(owner.check().is_ok());
    replace_discovered_selection(&mut jobs,Some(SELECTED),1).unwrap_or_else(|_|panic!("selected replacement fixture"));
    assert_eq!(jobs.len(),1);assert!(jobs.contains_key("unrelated"));assert!(owner.check().is_ok());
}
#[test]
fn abandoned_selected_delivery_closes_only_owned_handles_and_cannot_remove_other_selection() {
    let bridge=bridge();let old=EssentialGuard::new(&bridge,true).unwrap_or_else(|_|panic!("selected guard fixture"));let fresh=EssentialGuard::new(&bridge,true).unwrap_or_else(|_|panic!("selected guard fixture"));
    {let mut jobs=bridge.state.essential.jobs.lock().unwrap();jobs.insert("unrelated".into(),job(OTHER,old.clone()));jobs.insert("selected".into(),job(SELECTED,fresh.clone()));}
    drop(Delivery::new(&bridge.state,fresh.clone(),DeliveryKind::Recovery));
    let jobs=bridge.state.essential.jobs.lock().unwrap();assert!(jobs.contains_key("unrelated"));assert!(!jobs.contains_key("selected"));
    assert!(old.check().is_ok());assert_eq!(fresh.check().unwrap_err().code,"cancelled");
}
