//! Authored UNRUN shared-core draft regressions. Explicit inert local IO and
//! native opaque AES test port only; not real CryptoKey/Worker/IDB proof.
use super::*;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use std::{
    cell::RefCell,
    future::{Ready, ready},
    rc::Rc,
    sync::Arc,
};
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
struct Port;
impl MasterCrypto for Port {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::encrypt_aead(plain, &[7; 32], iv, &[]).map(Zeroizing::new) })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::decrypt_aead(cipher, &[7; 32], iv, &[]) })
    }
}
fn client() -> Client {
    let mut c = Client::new("http://127.0.0.1:9", None).unwrap();
    c.browser_transport = true;
    c.browser_local_read_only = true;
    c.browser_authority = Some(super::super::browser::BrowserAuthority {
        principal: OWNER.into(),
        persistence: BrowserPersistence::MemoryOnly,
        owner_guards: false,
    });
    c.user = json!({"id":OWNER});
    c.browser_credentials = Some(credentials::BrowserCredentials {
        api_url: "http://127.0.0.1:9".into(),
        session_id: OWNER.into(),
        cookies: BTreeMap::new(),
        ws_token: None,
        master: MasterCapability::opaque_for_test(Arc::new(Port)),
        hashed_email: String::new(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    });
    c
}
fn row() -> Value {
    json!({"chat_id":CHAT,"user_id":OWNER,"messages_v":7,"encrypted_chat_key":"original-wrapper","draft_v":3,"cleared_draft_v":9,"updated_at":10,"pinned":true,"extension":{"keep":true}})
}
struct Store {
    row: Value,
    change: Value,
    maximum: u64,
    plans: Vec<String>,
    mutate_on_final_capture: bool,
}
fn io(state: Rc<RefCell<Store>>) -> impl Fn(String) -> Ready<Result<String>> {
    move |encoded| {
        let p: Value = serde_json::from_str(&encoded).unwrap();
        let mut s = state.borrow_mut();
        let kind = p["kind"].as_str().unwrap().to_owned();
        s.plans.push(kind.clone());
        let result = (|| -> Result<String> {
            if kind == "store_draft" {
                if projection(&s.row)? != p["expected"] {
                    return Err(Error::Conflict);
                }
                for (k, v) in p["patch"].as_object().unwrap() {
                    s.row[k] = v.clone();
                }
                s.change = p["change"].clone();
            } else if kind == "ack_draft" {
                if projection(&s.row)? != p["expected"] || s.change != p["change"] {
                    return Err(Error::Conflict);
                }
                s.change = Value::Null;
            }
            if kind == "capture_draft" && s.mutate_on_final_capture && s.plans.len() > 1 {
                s.row["cleared_draft_v"] = json!(100);
            }
            Ok(serde_json::to_string(
                &json!({"version":1,"kind":kind,"operationId":p["operationId"],"chatId":CHAT,"row":projection(&s.row)?,"queueMaximum":s.maximum,"change":if kind=="capture_draft"{Value::Null}else{s.change.clone()},"transactionCommitted":true}),
            )?)
        })();
        ready(result)
    }
}
fn store() -> Rc<RefCell<Store>> {
    Rc::new(RefCell::new(Store {
        row: row(),
        change: Value::Null,
        maximum: 0,
        plans: vec![],
        mutate_on_final_capture: false,
    }))
}
const SCOPE: &str = r#"{"lifecycleGeneration":1,"workspaceEpoch":2}"#;
// contract-test: supporting surface=sdks.rust assertions=drafts.persistence.local-first-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn offline_local_draft_uses_opaque_master_existing_format_and_durable_encrypted_intent() {
    let mut c = client();
    let s = store();
    let prepared = c
        .prepare_browser_draft_with_io_json(
            OWNER,
            CHAT,
            "Synthetic browser draft 界",
            SCOPE,
            20,
            io(s.clone()),
        )
        .await
        .unwrap();
    assert!(c.session.is_none());
    assert_eq!(
        s.borrow().plans,
        ["capture_draft", "store_draft", "readback_draft"]
    );
    let receipt: Value = serde_json::from_str(&prepared.local_result(&c).unwrap()).unwrap();
    assert_eq!(receipt["version"], 10);
    assert_eq!(receipt["remoteSynced"], false);
    let encrypted = s.borrow().row["encrypted_draft_md"]
        .as_str()
        .unwrap()
        .to_owned();
    assert_eq!(
        &*c.master_capability()
            .unwrap()
            .decrypt_bytes(&encrypted)
            .await
            .unwrap(),
        "Synthetic browser draft 界".as_bytes()
    );
    assert!(!encrypted.contains("Synthetic"));
    assert_eq!(s.borrow().change["value"], encrypted);
    assert!(s.borrow().change.get("markdown").is_none());
    assert_eq!(s.borrow().row["extension"], json!({"keep":true}));
    assert_eq!(s.borrow().row["messages_v"], 7);
    let before = s.borrow().plans.len();
    let pending = prepared.synchronize(&mut c, io(s.clone())).await.unwrap();
    let pending: Value = serde_json::from_str(&pending.take(&c).unwrap()).unwrap();
    assert_eq!(pending["pending"], true);
    assert_eq!(s.borrow().plans.len(), before);
    assert!(!s.borrow().change.is_null());
}
// contract-test: supporting surface=sdks.rust assertions=drafts.access.first-party-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn restore_authenticates_opaque_cipher_and_brackets_decrypt_with_original_row_readback() {
    let mut c = client();
    let s = store();
    let prepared = c
        .prepare_browser_draft_with_io_json(
            OWNER,
            CHAT,
            "Synthetic restored draft",
            SCOPE,
            20,
            io(s.clone()),
        )
        .await
        .unwrap();
    drop(prepared);
    s.borrow_mut().plans.clear();
    let output = c
        .restore_browser_draft_with_io_json(OWNER, CHAT, SCOPE, io(s.clone()))
        .await
        .unwrap();
    assert_eq!(s.borrow().plans, ["capture_draft", "capture_draft"]);
    let output: Value = serde_json::from_str(&output.take(&c).unwrap()).unwrap();
    assert_eq!(output["markdown"], "Synthetic restored draft");
    assert_eq!(output["present"], true);
    assert_eq!(output["localOnly"], true);
}
// contract-test: supporting surface=sdks.rust assertions=drafts.sync.version-authoritative,sync.client.shared-rust-policy
#[tokio::test]
async fn final_row_tombstone_race_or_root_change_refuses_already_decrypted_publication() {
    let mut c = client();
    let s = store();
    let prepared = c
        .prepare_browser_draft_with_io_json(
            OWNER,
            CHAT,
            "Private original",
            SCOPE,
            20,
            io(s.clone()),
        )
        .await
        .unwrap();
    drop(prepared);
    s.borrow_mut().plans.clear();
    s.borrow_mut().mutate_on_final_capture = true;
    assert!(matches!(
        c.restore_browser_draft_with_io_json(OWNER, CHAT, SCOPE, io(s.clone()))
            .await,
        Err(Error::Conflict)
    ));
    s.borrow_mut().mutate_on_final_capture = false;
    s.borrow_mut().row["cleared_draft_v"] = json!(9);
    s.borrow_mut().plans.clear();
    let output = c
        .restore_browser_draft_with_io_json(OWNER, CHAT, SCOPE, io(s.clone()))
        .await
        .unwrap();
    c.user["id"] = json!(CHAT);
    assert!(output.take(&c).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=drafts.access.first-party-encrypted,sync.phase2.drafts.authoritative-encrypted
#[tokio::test]
async fn foreign_owner_team_and_draft_only_rows_refuse_before_any_write() {
    for (field, value) in [
        ("user_id", json!(CHAT)),
        ("team_id", json!(CHAT)),
        ("messages_v", json!(0)),
    ] {
        let mut c = client();
        let s = store();
        s.borrow_mut().row[field] = value;
        assert!(
            c.prepare_browser_draft_with_io_json(
                OWNER,
                CHAT,
                "Retain editor input",
                SCOPE,
                20,
                io(s.clone())
            )
            .await
            .is_err()
        );
        assert_eq!(s.borrow().plans, ["capture_draft"]);
        assert!(s.borrow().change.is_null());
    }
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[tokio::test]
async fn cancelled_child_cannot_cancel_another_original_local_draft_resource() {
    let mut c = client();
    let s = store();
    let a = c
        .prepare_browser_draft_with_io_json(
            OWNER,
            CHAT,
            "A remains encrypted",
            SCOPE,
            20,
            io(s.clone()),
        )
        .await
        .unwrap();
    s.borrow_mut().maximum = 1;
    let b = c
        .prepare_browser_draft_with_io_json(
            OWNER,
            CHAT,
            "B remains available",
            SCOPE,
            21,
            io(s.clone()),
        )
        .await
        .unwrap();
    a.cancel();
    assert!(a.local_result(&c).is_err());
    assert!(b.local_result(&c).is_ok());
    c.operation_parent.cancel();
    assert!(b.local_result(&c).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=drafts.persistence.local-first-encrypted,auth.session.isolation,sync.client.shared-rust-policy
#[test]
fn sealed_local_draft_scope_keeps_independent_child_and_actual_request_cancellation(){
    let c=client();let admission=c.prepare_browser_draft_admission(OWNER,CHAT).unwrap();
    assert!(OwnedOperationScope::capture(&c,CancellationToken::new()).is_err(),"generic canonical capture remains forbidden for local profile");
    let a=OwnedOperationScope::capture_local_draft(&c,&admission).unwrap();
    let b=OwnedOperationScope::capture_local_draft(&c,&admission).unwrap();
    a.check(&c).unwrap();b.check(&c).unwrap();assert!(c.session.is_none());
    assert!(c.require_canonical_read_profile().is_err(),"local draft admission does not upgrade server authority");
    a.observer().cancel();assert!(a.check(&c).is_err());b.check(&c).unwrap();
    c.current_operation_child().cancel();assert!(b.check(&c).is_err(),"actual captured request cancellation must retire the original local draft");
}
// contract-test: supporting surface=sdks.rust assertions=drafts.persistence.local-first-encrypted,auth.session.authoritative-enforcement,auth.secrets.lifecycle
#[test]
fn local_draft_scope_refuses_stale_admission_owner_generation_and_actual_master(){
    for mutation in ["owner","generation","master"]{
        let mut c=client();let admission=c.prepare_browser_draft_admission(OWNER,CHAT).unwrap();
        match mutation {
            "owner"=>c.user["id"]=json!("33333333-3333-4333-8333-333333333333"),
            "generation"=>c.generation+=1,
            "master"=>c.browser_credentials.as_ref().unwrap().master.invalidate(),
            _=>unreachable!(),
        }
        assert!(OwnedOperationScope::capture_local_draft(&c,&admission).is_err(),"stale actual local draft admission must refuse: {mutation}");
    }
}
// contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn local_profile_write_has_no_platform_payload_or_transport_ack() {
    let mut c = client();
    let s = store();
    let prepared = c
        .prepare_browser_draft_with_preview_io_json(
            OWNER,
            CHAT,
            "Body",
            Some("Body"),
            SCOPE,
            20,
            io(s.clone()),
        )
        .await
        .unwrap();
    // A local-only profile has no server authority: no payload, no transport ack.
    assert!(matches!(prepared.remote_payload(&c), Err(Error::Forbidden)));
    assert!(matches!(
        prepared.acknowledge_transport(&mut c, io(s.clone())).await,
        Err(Error::Forbidden)
    ));
    assert!(!s.borrow().change.is_null());
}
// contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted,sync.client.shared-rust-policy
#[tokio::test]
async fn display_preview_is_encrypted_and_platform_transport_ack_removes_only_this_intent() {
    let mut c = client();
    // Server-checked browser session (the web history admission), not a local profile.
    c.browser_local_read_only = false;
    let s = store();
    let prepared = c
        .prepare_browser_draft_with_preview_io_json(
            OWNER,
            CHAT,
            "Hello [@Claude](mate:claude) body",
            Some("Hello @Claude body"),
            SCOPE,
            20,
            io(s.clone()),
        )
        .await
        .unwrap();
    let preview = s.borrow().row["encrypted_draft_preview"]
        .as_str()
        .unwrap()
        .to_owned();
    assert_eq!(
        &*c.master_capability()
            .unwrap()
            .decrypt_bytes(&preview)
            .await
            .unwrap(),
        "Hello @Claude body".as_bytes()
    );
    let payload: Value = serde_json::from_str(&prepared.remote_payload(&c).unwrap()).unwrap();
    assert_eq!(payload["chat_id"], CHAT);
    assert_eq!(payload["draft_v"], 10);
    assert_eq!(payload["encrypted_draft_preview"], preview);
    assert_eq!(
        payload["encrypted_draft_md"],
        s.borrow().row["encrypted_draft_md"]
    );
    assert!(!payload.to_string().contains("Hello"));
    assert!(!s.borrow().change.is_null());
    let synced = prepared
        .acknowledge_transport(&mut c, io(s.clone()))
        .await
        .unwrap();
    let synced: Value = serde_json::from_str(&synced.take(&c).unwrap()).unwrap();
    assert_eq!(synced["remoteSynced"], true);
    assert_eq!(synced["pending"], false);
    assert!(s.borrow().change.is_null());
    assert_eq!(s.borrow().plans.last().unwrap(), "ack_draft");
}
// contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
#[tokio::test]
async fn empty_or_oversized_display_preview_refuses_before_any_io() {
    for preview in ["   ".to_owned(), "x".repeat(4 * 1024 + 1)] {
        let mut c = client();
        let s = store();
        assert!(matches!(
            c.prepare_browser_draft_with_preview_io_json(
                OWNER,
                CHAT,
                "Body",
                Some(&preview),
                SCOPE,
                20,
                io(s.clone())
            )
            .await,
            Err(Error::Invalid(_))
        ));
        assert!(s.borrow().plans.is_empty());
    }
}
