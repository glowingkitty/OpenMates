//! Authored UNRUN Rust tests. Synthetic opaque crypto and owned IO only;
//! these cases establish no actual browser, IndexedDB, WASM or product evidence.
// contract-test-file: tooling
use super::*;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use std::{cell::RefCell, future::{ready, Ready}, rc::Rc, sync::Arc};
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const A: &str = "22222222-2222-4222-8222-222222222222";
const B: &str = "33333333-3333-4333-8333-333333333333";
struct Port;
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::encrypt_aead(plain, &[7;32], iv, &[]).map(Zeroizing::new) })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::decrypt_aead(cipher, &[7;32], iv, &[]) })
    }
}
fn client(local: bool) -> Client {
    let mut c = Client::new("http://127.0.0.1:9", None).unwrap();
    c.browser_transport = true; c.browser_local_read_only = local;
    c.browser_authority = Some(BrowserAuthority {principal:OWNER.into(), persistence:BrowserPersistence::MemoryOnly, owner_guards:!local});
    c.user = json!({"id":OWNER});
    c.browser_credentials = Some(credentials::BrowserCredentials {
        api_url:"http://127.0.0.1:9".into(),session_id:OWNER.into(),cookies:BTreeMap::new(),
        ws_token:if local {None} else {Some("synthetic-token".into())},
        master:MasterCapability::opaque_for_test(Arc::new(Port)),hashed_email:String::new(),
        user_email_salt:String::new(),email_encryption_key:None,created_at:1,
        paired_session_expires_at:None,active_team_id:None,
    }); c
}
fn row(id: &str, title: &str, edited: u64) -> Value {
    use base64::Engine;
    let mut wrapped = vec![3;12];
    wrapped.extend(crypto::encrypt_aead(&[9;32], &[7;32], &[3;12], &[]).unwrap());
    json!({"chat_id":id,"user_id":OWNER,"encrypted_chat_key":base64::engine::general_purpose::STANDARD.encode(wrapped),
        "encrypted_title":crypto::encrypt_combined(title,&[9;32]).unwrap(),"metadata_v":1,"title_v":1,
        "messages_v":7,"created_at":1,"last_edited_overall_timestamp":edited,
        "encrypted_draft_md":"existing-ciphertext-preserved","local_flag":{"must":"survive"}})
}
fn host() -> BrowserMetadataCacheScope { serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":2})).unwrap() }
struct Store {
    rows:BTreeMap<String, Value>, plans:Vec<Value>, fault:&'static str,
    cancel:Option<CancellationToken>, master:Option<MasterCapability>,
    watch:Option<Arc<crate::client::project_task_watch::WatchAuthority>>,
    private:Option<Arc<std::sync::atomic::AtomicBool>>,
}
fn store(fault: &'static str) -> Rc<RefCell<Store>> {
    Rc::new(RefCell::new(Store {rows:BTreeMap::from([(A.into(),row(A,"Older",1)),(B.into(),row(B,"Newer",2))]),
        plans:vec![],fault,cancel:None,master:None,watch:None,private:None}))
}
fn io(s: Rc<RefCell<Store>>) -> impl FnMut(String) -> Ready<Result<String>> {
    move |encoded| {
        let p:Value = serde_json::from_str(&encoded).unwrap(); let mut s=s.borrow_mut();
        assert!(matches!(p["kind"].as_str(),Some("capture"|"readback")));
        assert_eq!(p["database"],"chats_db");assert_eq!(p["store"],"chats");assert_eq!(p["owner"],OWNER);
        assert!(p["patch"].is_null());s.plans.push(p.clone());
        let id=p["chatId"].as_str().unwrap();
        let mut f=json!({"version":1,"kind":p["kind"],"operationId":p["operationId"],"databaseVersion":32,
            "transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,
            "before":null,"record":s.rows[id]});
        if p["kind"]=="readback" {
            match s.fault {
                "incomplete"=>f["transactionCommitted"]=json!(false),
                "ack"=>f["credentialAcknowledged"]=json!(true),
                "association"=>f["crossDatabaseAssociationProven"]=json!(true),
                "operation"=>f["operationId"]=json!(uuid::Uuid::new_v4().to_string()),
                "database-version"=>f["databaseVersion"]=json!(33),
                "record-change"=>f["record"]["metadata_v"]=json!(2),
                "extension-change"=>f["record"]["local_flag"]=json!(false),
                "owner"=>f["record"]["user_id"]=json!(B),
                "before"=>f["before"]=f["record"].clone(),
                "cancel"=>s.cancel.as_ref().unwrap().cancel(),
                "key"=>s.master.as_ref().unwrap().invalidate(),
                "deny"=>s.watch.as_ref().unwrap().deny_cached_chat(Some(A)).unwrap(),
                "private"=>s.private.as_ref().unwrap().store(false,std::sync::atomic::Ordering::SeqCst),
                "second-row" if id==B=>f["transactionCommitted"]=json!(false),
                _=>{},
            }
        }
        ready(Ok(f.to_string()))
    }
}
#[tokio::test]
async fn opaque_restore_local_and_online_is_tagged_ordered_and_preserves_store_without_native_session_or_ack() {
    for local in [true,false] {
        let mut c=client(local);let s=store("");let original=s.borrow().rows.clone();
        c.history.insert(A.into(),vec![json!({"untouched":"history"})]);
        let before=c.ciphertext_snapshot();
        let encoded=c.browser_restore_cached_metadata_json(OWNER,&[A.into(),B.into()],host(),true,io(s.clone())).await.unwrap();
        let out:Value=serde_json::from_str(&encoded).unwrap();
        assert_eq!(out["items"][0]["id"],B);assert_eq!(out["items"][1]["title"],"Older");
        assert_eq!(out["metadataRestored"],true);assert_eq!(out["readOnly"],true);
        for field in ["fresh","inventoryComplete","historyComplete","messagesPersisted","credentialAcknowledged","nativeDurabilityAcknowledged","recoveryProof"] {assert_eq!(out[field],false);}
        assert_eq!(s.borrow().rows,original);assert_eq!(s.borrow().plans.len(),4);
        assert!(c.session.is_none());assert!(c.clone_session().is_none());assert_eq!(c.credential_ack,0);
        assert_eq!(c.ciphertext_snapshot()["history"],before["history"]);
        assert!(c.chats[A].get("local_flag").is_none());assert!(c.chats[A].get("encrypted_draft_md").is_none());
        let cached=c.browser_cached_chat_items_json(OWNER,&[A.into(),B.into()],true).await.unwrap();
        let cached:Value=serde_json::from_str(&cached).unwrap();assert_eq!(cached["items"],out["items"]);
        assert_eq!(cached["metadataRestored"],false);
    }
}
#[tokio::test]
async fn incomplete_forged_or_raced_readback_never_restores_any_row() {
    for fault in ["incomplete","ack","association","operation","database-version","record-change","extension-change","owner","before","second-row"] {
        let mut c=client(false);let s=store(fault);let before=c.ciphertext_snapshot();
        assert!(c.browser_restore_cached_metadata_json(OWNER,&[A.into(),B.into()],host(),true,io(s.clone())).await.is_err(),"{fault}");
        assert_eq!(c.ciphertext_snapshot(),before,"{fault}");assert_eq!(c.credential_ack,0);
    }
}
#[tokio::test]
async fn original_request_parent_private_denial_and_master_resource_fences_survive_readback() {
    for fault in ["cancel","parent","private","deny","key"] {
        let mut c=client(false);let s=store(if fault=="parent" {"cancel"} else {fault});
        s.borrow_mut().cancel=Some(if fault=="parent" {c.operation_parent.clone()} else {c.operation_cancel.clone()});
        s.borrow_mut().master=Some(c.master_capability().unwrap());s.borrow_mut().watch=Some(c.task_watch_authority.clone());
        let private=Arc::new(std::sync::atomic::AtomicBool::new(true));s.borrow_mut().private=Some(private.clone());
        c.set_private_operation_gate(Some(Arc::new(move || if private.load(std::sync::atomic::Ordering::SeqCst) {Ok(())} else {Err(Error::Forbidden)})));
        assert!(c.browser_restore_cached_metadata_json(OWNER,&[A.into(),B.into()],host(),true,io(s.clone())).await.is_err(),"{fault}");
        assert!(c.chats.is_empty());assert_eq!(c.credential_ack,0);
    }
}
#[tokio::test]
async fn conflicting_existing_memory_row_refuses_without_overwrite_or_partial_insert() {
    let mut c=client(false);let s=store("");let mut current=row(B,"Current conflicting title",3);current["id"]=json!(B);
    c.chats.insert(B.into(),current);let before=c.ciphertext_snapshot();
    assert!(matches!(c.browser_restore_cached_metadata_json(OWNER,&[A.into(),B.into()],host(),true,io(s)).await,Err(Error::Conflict)));
    assert_eq!(c.ciphertext_snapshot(),before);
}
#[tokio::test]
async fn bounded_selectors_explicit_consent_owner_scope_and_known_denial_refuse_before_io() {
    for ids in [vec![],vec![A.into(),A.into()],vec!["invalid".into()],vec![A.into();21]] {
        let mut c=client(false);let s=store("");assert!(c.browser_restore_cached_metadata_json(OWNER,&ids,host(),true,io(s.clone())).await.is_err());assert!(s.borrow().plans.is_empty());
    }
    for fault in ["consent","owner","deny","team"] {
        let mut c=client(false);let s=store("");
        if fault=="deny" {c.task_watch_authority.deny_cached_chat(Some(A)).unwrap();}
        if fault=="team" {c.browser_credentials.as_mut().unwrap().active_team_id=Some(B.into());}
        assert!(c.browser_restore_cached_metadata_json(if fault=="owner" {B} else {OWNER},&[A.into()],host(),fault!="consent",io(s.clone())).await.is_err());
        assert!(s.borrow().plans.is_empty());
    }
}
#[test]
fn original_epoch_identity_and_gate_replacement_are_not_recaptured_after_suspend() {
    for fault in ["identity","origin","interactive","gate"] {
        let mut c=client(false);let f=restore_fence(&c,OWNER,A).unwrap();
        match fault {"identity"=>c.set_identity(crate::client::ClientIdentity::Npm),
            "origin"=>c.set_app_origin(Some("https://other.example.invalid".into())).unwrap(),
            "interactive"=>c.set_interactive(true),_=>c.set_private_operation_gate(Some(Arc::new(||Ok(()))))}
        assert!(c.metadata_cache_check(&f,OWNER,A,BrowserMetadataCacheMode::Restore).is_err(),"{fault}");
    }
}
#[tokio::test]
async fn cached_projection_does_not_reauthorize_a_denied_row_or_export_a_resource() {
    let mut c=client(true);let mut r=row(A,"Secret",1);r["id"]=json!(A);c.chats.insert(A.into(),r);
    let before=c.ciphertext_snapshot();
    c.task_watch_authority.deny_cached_chat(Some(A)).unwrap();
    assert!(c.browser_cached_chat_items_json(OWNER,&[A.into()],true).await.is_err());
    assert_eq!(c.ciphertext_snapshot(),before);assert!(c.session.is_none());assert_eq!(c.credential_ack,0);
}

#[tokio::test]
async fn wrong_key_draft_team_direct_and_foreign_owner_rows_refuse_without_mutation() {
    for fault in ["key","draft","team","direct","owner"] {
        let mut c=client(false);let s=store("");
        { let mut store=s.borrow_mut();let row=store.rows.get_mut(A).unwrap();
            match fault {"key"=>row["encrypted_title"]=json!(crypto::encrypt_combined("wrong key",&[8;32]).unwrap()),
                "draft"=>{row["encrypted_chat_key"]=Value::Null;row["encrypted_draft_md"]=json!("private draft cipher");},
                "team"=>row["team_id"]=json!(B),"direct"=>row["chat_visibility"]=json!("direct"),_=>row["user_id"]=json!(B)}
        }
        let before=c.ciphertext_snapshot();
        assert!(c.browser_restore_cached_metadata_json(OWNER,&[A.into()],host(),true,io(s.clone())).await.is_err(),"{fault}");
        assert_eq!(c.ciphertext_snapshot(),before);assert_eq!(s.borrow().plans.len(),1);
    }
}
struct PendingPort;
impl MasterCrypto for PendingPort {
    fn encrypt<'a>(&'a self,_iv:&'a [u8;12],_plain:&'a [u8])->MasterCryptoFuture<'a> {Box::pin(std::future::pending())}
    fn decrypt<'a>(&'a self,_iv:&'a [u8;12],_cipher:&'a [u8])->MasterCryptoFuture<'a> {Box::pin(std::future::pending())}
}
#[test]
fn dropped_restore_future_before_async_crypto_completion_cannot_publish_or_insert() {
    let mut c=client(true);let s=store("");
    c.browser_credentials.as_mut().unwrap().master=MasterCapability::opaque_for_test(Arc::new(PendingPort));
    let before=c.ciphertext_snapshot();let ids=[A.into()];
    let mut future=Box::pin(c.browser_restore_cached_metadata_json(OWNER,&ids,host(),true,io(s.clone())));
    let waker=std::task::Waker::noop();let mut context=std::task::Context::from_waker(waker);
    assert!(std::future::Future::poll(std::pin::Pin::as_mut(&mut future),&mut context).is_pending());
    drop(future);assert_eq!(c.ciphertext_snapshot(),before);
    assert_eq!(s.borrow().plans.len(),1);assert_eq!(c.credential_ack,0);
}

fn known_arrival_client()->Client {
    const C:&str="44444444-4444-4444-8444-444444444444";
    let mut c=client(false);let mut existing=row(C,"Existing",3);existing["id"]=json!(C);
    c.chats.insert(C.into(),existing);c.chat_arrival_order=Some(vec![C.into()]);c
}
#[tokio::test]
async fn cached_map_batch_with_two_unseen_rows_marks_arrival_unavailable_without_losing_old_data(){
    let mut c=known_arrival_client();let original=c.chats.clone();let s=store("");
    let encoded=c.browser_restore_cached_metadata_json(OWNER,&[B.into(),A.into()],host(),true,io(s.clone())).await.unwrap();
    assert!(serde_json::from_str::<Value>(&encoded).unwrap()["metadataRestored"].as_bool().unwrap());
    assert!(c.chat_arrival_order.is_none());assert_eq!(c.chats.len(),3);
    for(id,row)in original{assert_eq!(c.chats[&id],row);}
    assert!(c.ciphertext_snapshot().get(crate::client::chat_arrival_order::SNAPSHOT_FIELD).is_none());
}
#[tokio::test]
async fn cached_map_batch_final_lifetime_refusal_restores_original_known_order_and_rows(){
    use std::sync::atomic::{AtomicUsize,Ordering};
    let mut baseline=known_arrival_client();let calls=Arc::new(AtomicUsize::new(0));let counter=calls.clone();
    baseline.set_private_operation_gate(Some(Arc::new(move||{counter.fetch_add(1,Ordering::SeqCst);Ok(())})));
    baseline.browser_restore_cached_metadata_json(OWNER,&[B.into(),A.into()],host(),true,io(store(""))).await.unwrap();
    let last=calls.load(Ordering::SeqCst);assert!(last>0);
    let mut c=known_arrival_client();let original=c.ciphertext_snapshot();let attempts=Arc::new(AtomicUsize::new(0));let counter=attempts.clone();
    c.set_private_operation_gate(Some(Arc::new(move||if counter.fetch_add(1,Ordering::SeqCst)+1>=last{Err(Error::Forbidden)}else{Ok(())})));
    assert!(c.browser_restore_cached_metadata_json(OWNER,&[B.into(),A.into()],host(),true,io(store(""))).await.is_err());
    assert_eq!(attempts.load(Ordering::SeqCst),last);assert_eq!(c.ciphertext_snapshot(),original);
}
