//! Authored UNRUN inert browser metadata monitor cases. No network/browser/CI.
// contract-test-file: tooling
use super::*;
use crate::crypto::master::{MasterCapability,MasterCrypto,MasterCryptoFuture};
use std::{cell::RefCell,future::{ready,Ready},rc::Rc};
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const CHAT:&str="22222222-2222-4222-8222-222222222222";
struct Port;
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self,iv:&'a [u8;12],plain:&'a [u8])->MasterCryptoFuture<'a> {
        Box::pin(async move{crypto::encrypt_aead(plain,&[7;32],iv,&[]).map(Zeroizing::new)})
    }
    fn decrypt<'a>(&'a self,iv:&'a [u8;12],cipher:&'a [u8])->MasterCryptoFuture<'a> {
        Box::pin(async move{crypto::decrypt_aead(cipher,&[7;32],iv,&[])})
    }
}
pub(super) fn client()->Client {
    let mut c=Client::new("http://127.0.0.1:9",None).unwrap();c.browser_transport=true;
    c.browser_authority=Some(crate::client::browser::BrowserAuthority {principal:OWNER.into(),
        persistence:crate::client::BrowserPersistence::MemoryOnly,owner_guards:true});
    c.user=json!({"id":OWNER});
    c.browser_credentials=Some(crate::client::credentials::BrowserCredentials {
        api_url:"http://127.0.0.1:9".into(),session_id:OWNER.into(),cookies:BTreeMap::new(),ws_token:Some("synthetic".into()),
        master:MasterCapability::opaque_for_test(Arc::new(Port)),hashed_email:String::new(),user_email_salt:String::new(),
        email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None});c
}
fn row(title:&str,version:u64)->Value {
    use base64::Engine;
    let mut wrapped=vec![3;12];wrapped.extend(crypto::encrypt_aead(&[9;32],&[7;32],&[3;12],&[]).unwrap());
    json!({"id":CHAT,"chat_id":CHAT,"user_id":OWNER,"encrypted_chat_key":base64::engine::general_purpose::STANDARD.encode(wrapped),
        "encrypted_title":crypto::encrypt_combined(title,&[9;32]).unwrap(),"title_v":version,"metadata_v":version,
        "messages_v":7,"created_at":1,"last_edited_overall_timestamp":2,"encrypted_draft_md":"preserve"})
}
fn monitor(c:&Client)->ChatMonitor {
    ChatMonitor {changes:Arc::new(Changes::default()),fence:Arc::new(MonitorFence {
        owner:c.task_watch_authority.clone(),generation:c.generation,team:None,expires_at:None,
        cancel:c.operation_cancel.child_token(),alive:AtomicBool::new(true),denial:Mutex::new(None)})}
}
fn candidate(c:&Client,m:&ChatMonitor)->BrowserMetadataMonitorRefresh {
    BrowserMetadataMonitorRefresh {fence:BrowserMonitorFence::capture(c,m,OWNER,Some(CHAT)).unwrap(),stamp:snapshot_stamp(c).unwrap(),
        changed:vec![CHAT.into()],items:Plain::new(vec![c.chat_item(&c.chats[CHAT],&[9;32]).unwrap()]),selected_invalidated:Some(CHAT.into())}
}
fn scope()->crate::client::BrowserMetadataCacheScope {serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":2})).unwrap()}
struct Store {row:Value,plans:Vec<Value>,fault:&'static str,master:MasterCapability,cancel:CancellationToken}
fn store(c:&Client,fault:&'static str)->Rc<RefCell<Store>> {
    Rc::new(RefCell::new(Store {row:row("Old",1),plans:vec![],fault,master:c.master_capability().unwrap(),cancel:c.operation_parent.clone()}))
}
fn io(store:Rc<RefCell<Store>>)->impl FnMut(String)->Ready<Result<String>> {
    move|encoded| {
        let p:Value=serde_json::from_str(&encoded).unwrap();let mut s=store.borrow_mut();s.plans.push(p.clone());
        let mut before=Value::Null;
        if p["kind"]=="compare_and_patch" {
            before=s.row.clone();for (key,value) in p["patch"].as_object().unwrap(){s.row[key]=value.clone();}
        }
        let mut frame=json!({"version":1,"kind":p["kind"],"operationId":p["operationId"],"databaseVersion":32,
            "transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,
            "record":s.row,"before":before});
        if p["kind"]=="readback" {
            match s.fault {"early"=>frame["transactionCommitted"]=json!(false),"ack"=>frame["credentialAcknowledged"]=json!(true),
                "cross-db"=>frame["crossDatabaseAssociationProven"]=json!(true),"key"=>s.master.invalidate(),
                "cancel"=>s.cancel.cancel(),"wrong-row"=>frame["record"]["metadata_v"]=json!(999),_=>{}}
        }
        ready(Ok(frame.to_string()))
    }
}
fn seeded()->Client {let mut c=client();let mut desired=row("New",2);desired["messages_v"]=json!(99);c.chats.insert(CHAT.into(),desired);c}
#[tokio::test]
async fn actual_metadata_readback_is_projected_without_native_ack_or_canonical_message_counter() {
    let mut c=seeded();let m=monitor(&c);let r=candidate(&c,&m);let s=store(&c,"");
    let publication=c.commit_browser_chat_monitor_metadata(r,scope(),true,io(s.clone())).await.unwrap();
    let output=c.browser_chat_monitor_metadata_json(publication,true).unwrap();let v:Value=serde_json::from_str(&output).unwrap();
    assert_eq!(v["items"][0]["title"],"New");assert_eq!(v["items"][0]["fields"]["messages_v"],7);
    assert_eq!(v["metadataRowsPersisted"],1);assert_eq!(v["selectedChatInvalidated"],CHAT);
    for field in ["inventoryComplete","historyComplete","messagesVersionAdvanced","canonicalIncomingWindow","selectedWindowPublished",
        "credentialAcknowledged","nativeDurabilityAcknowledged","crossDatabaseAssociationProven","recoveryProof"] {assert_eq!(v[field],false);}
    assert_eq!(s.borrow().row["encrypted_draft_md"],"preserve");assert_eq!(s.borrow().plans.len(),3);
    assert!(c.session.is_none());assert_eq!(c.credential_ack,0);
}
#[tokio::test]
async fn uncommitted_mismatched_ack_claiming_or_revoked_readback_refuses_publication() {
    for fault in ["early","ack","cross-db","key","cancel","wrong-row"] {
        let mut c=seeded();let m=monitor(&c);let r=candidate(&c,&m);let s=store(&c,fault);
        assert!(c.commit_browser_chat_monitor_metadata(r,scope(),true,io(s)).await.is_err(),"{fault}");assert_eq!(c.credential_ack,0);
    }
}
#[tokio::test]
async fn original_epoch_key_private_gate_owner_and_source_fences_are_retained() {
    for fault in ["identity","interactive","gate","owner","source","denial"] {
        let mut c=seeded();let m=monitor(&c);let r=candidate(&c,&m);let s=store(&c,"");
        match fault {"identity"=>c.set_identity(crate::client::ClientIdentity::Npm),"interactive"=>c.set_interactive(true),
            "gate"=>c.set_private_operation_gate(Some(Arc::new(||Ok(())))),"owner"=>c.user["id"]=json!(CHAT),
            "source"=>c.chats.get_mut(CHAT).unwrap()["metadata_v"]=json!(9),
            _=>c.task_watch_authority.deny_cached_chat(Some(CHAT)).unwrap()}
        assert!(c.commit_browser_chat_monitor_metadata(r,scope(),true,io(s.clone())).await.is_err(),"{fault}");
        assert!(s.borrow().plans.is_empty());
    }
}
#[tokio::test]
async fn delayed_publication_requires_original_client_and_live_resource() {
    for fault in ["foreign","revoked","changed","closed"] {
        let mut c=seeded();let m=monitor(&c);let r=candidate(&c,&m);let s=store(&c,"");
        let publication=c.commit_browser_chat_monitor_metadata(r,scope(),true,io(s)).await.unwrap();
        match fault {"foreign"=>assert!(seeded().browser_chat_monitor_metadata_json(publication,true).is_err()),
            "revoked"=>{c.master_capability().unwrap().invalidate();assert!(c.browser_chat_monitor_metadata_json(publication,true).is_err());},
            "changed"=>{c.chats.get_mut(CHAT).unwrap()["messages_v"]=json!(1);assert!(c.browser_chat_monitor_metadata_json(publication,true).is_err());},
            _=>{m.close();assert!(c.browser_chat_monitor_metadata_json(publication,true).is_err());}}
    }
}
#[tokio::test]
async fn explicit_consent_and_offline_browser_mode_are_not_bypassed_by_monitor_commit() {
    let mut c=seeded();let m=monitor(&c);let r=candidate(&c,&m);let s=store(&c,"");
    assert!(c.commit_browser_chat_monitor_metadata(r,scope(),false,io(s.clone())).await.is_err());assert!(s.borrow().plans.is_empty());
    c.browser_local_read_only=true;assert!(BrowserMonitorFence::capture(&c,&m,OWNER,Some(CHAT)).is_err());
}
#[test]
fn reconnect_wrapper_merge_preserves_older_resources_and_prefers_current_exact_selector() {
    let old=json!({"hashed_chat_id":"chat","key_type":"master","encrypted_chat_key":"old"});
    let new=json!({"hashed_chat_id":"chat","key_type":"master","encrypted_chat_key":"new"});
    let other=json!({"hashed_chat_id":"pinned-older","key_type":"master","encrypted_chat_key":"keep"});
    let mut current=vec![new.clone()];retain_missing_wrappers(&mut current,&[old,other.clone()],"hashed_chat_id");
    assert_eq!(current,vec![new,other]);
}

#[test]
fn actual_monitor_context_refuses_socket_failure_reconnect_owner_or_resource_rebinding() {
    for fault in ["socket-error","closed","owner","chat","epoch","key","foreign"] {
        let mut c=seeded();let monitor=monitor(&c);let context=c.browser_monitor_read_context(&monitor,OWNER,CHAT).unwrap();
        assert!(context.ensure_current(&c,OWNER,CHAT).is_ok());
        match fault {
            "socket-error"=>monitor.fence.alive.store(false,Ordering::Release),
            "closed"=>monitor.close(),
            "owner"=>assert!(context.ensure_current(&c,CHAT,CHAT).is_err()),
            "chat"=>assert!(context.ensure_current(&c,OWNER,OWNER).is_err()),
            "epoch"=>c.set_interactive(true),
            "key"=>c.master_capability().unwrap().invalidate(),
            _=>assert!(context.ensure_current(&seeded(),OWNER,CHAT).is_err()),
        }
        if !matches!(fault,"owner"|"chat"|"foreign") {assert!(context.ensure_current(&c,OWNER,CHAT).is_err(),"{fault}");}
    }
}
#[test]
fn reconnect_cannot_reanimate_an_old_closed_socket_context() {
    let c=seeded();let first=monitor(&c);let context=c.browser_monitor_read_context(&first,OWNER,CHAT).unwrap();first.close();
    let second=monitor(&c);assert!(c.browser_monitor_read_context(&second,OWNER,CHAT).is_ok());assert!(context.ensure_current(&c,OWNER,CHAT).is_err());
}
