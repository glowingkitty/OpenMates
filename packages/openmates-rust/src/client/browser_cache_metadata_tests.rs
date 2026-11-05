//! Authored UNRUN opaque-port + owned IO regressions. No HTTP/browser/account.
// contract-test-file: tooling
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
fn client(local: bool) -> Client {
    let mut c = Client::new("http://127.0.0.1:9", None).unwrap();
    c.browser_transport = true;
    c.browser_local_read_only = local;
    c.browser_authority = Some(BrowserAuthority {
        principal: OWNER.into(),
        persistence: BrowserPersistence::MemoryOnly,
        owner_guards: !local,
    });
    c.user = json!({"id":OWNER});
    c.browser_credentials = Some(credentials::BrowserCredentials {
        api_url: "http://127.0.0.1:9".into(),
        session_id: OWNER.into(),
        cookies: BTreeMap::new(),
        ws_token: if local {
            None
        } else {
            Some("synthetic-token".into())
        },
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
fn wrapper(key: u8) -> String {
    use base64::Engine;
    let mut bytes = vec![3; 12];
    bytes.extend(crypto::encrypt_aead(&[key; 32], &[7; 32], &[3; 12], &[]).unwrap());
    base64::engine::general_purpose::STANDARD.encode(bytes)
}
fn row(title: &str, version: u64) -> Value {
    json!({"chat_id":CHAT,"user_id":OWNER,"encrypted_chat_key":wrapper(9),"encrypted_title":crypto::encrypt_combined(title,&[9;32]).unwrap(),"encrypted_chat_summary":crypto::encrypt_combined("Summary",&[9;32]).unwrap(),"encrypted_category":null,"title_v":version,"metadata_v":version,"messages_v":7,"created_at":1,"updated_at":2,"pinned":true,"cleared_draft_v":10,"encrypted_draft_md":"existing-private-draft-ciphertext","team_draft_pending_sync":"delete","message_window_has_more_before":true,"message_window_start_cursor":{"created_at":1,"message_id":"opaque_older"},"unowned_extension":{"private":"must survive, never projected"}})
}
fn source(c: &mut Client) {
    let mut value = row("New title", 2);
    value["id"] = json!(CHAT);
    value["messages_v"] = json!(99);
    value["unknown_plaintext_source"] = json!("must never persist");
    c.chats.insert(CHAT.into(), value);
}
fn host() -> BrowserMetadataCacheScope {
    serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":2})).unwrap()
}
struct Store {
    row: Value,
    plans: Vec<Value>,
    fault: &'static str,
    master: Option<MasterCapability>,
    private: Option<Arc<std::sync::atomic::AtomicBool>>,
    cancel: Option<CancellationToken>,
    watch: Option<Arc<crate::client::project_task_watch::WatchAuthority>>,
}
fn io(store: Rc<RefCell<Store>>) -> impl FnMut(String) -> Ready<Result<String>> {
    move |encoded| {
        let p: Value = serde_json::from_str(&encoded).unwrap();
        let mut s = store.borrow_mut();
        s.plans.push(p.clone());
        assert_eq!(p["database"], "chats_db");
        assert_eq!(p["store"], "chats");
        assert_eq!(p["owner"], OWNER);
        assert_eq!(p["chatId"], CHAT);
        let mut before = Value::Null;
        if p["kind"] == "compare_and_patch" {
            let projected = projection(&s.row, CHAT, OWNER, true).unwrap();
            assert_eq!(*projected, p["expected"]);
            for field in p["patch"].as_object().unwrap().keys() {
                assert!(CIPHERS.contains(&field.as_str()) || VERSIONS.contains(&field.as_str()));
            }
            assert!(!encoded.contains("must never persist"));
            assert!(!encoded.contains("must survive"));
            assert!(p["patch"].get("messages_v").is_none());
            assert!(p["patch"].get("encrypted_chat_key").is_none());
            before = s.row.clone();
            for (field, value) in p["patch"].as_object().unwrap() {
                s.row[field] = value.clone();
            }
            if s.fault == "unowned-loss" {
                s.row.as_object_mut().unwrap().remove("unowned_extension");
            }
            if s.fault == "key-revoked" {
                s.master.as_ref().unwrap().invalidate();
            }
            if s.fault == "private-denied" {
                s.private
                    .as_ref()
                    .unwrap()
                    .store(false, std::sync::atomic::Ordering::SeqCst);
            }
            if s.fault == "request-cancelled" {
                s.cancel.as_ref().unwrap().cancel();
            }
            if s.fault == "denied" {
                s.watch
                    .as_ref()
                    .unwrap()
                    .deny_cached_chat(Some(CHAT))
                    .unwrap();
            }
        }
        let mut frame = json!({"version":1,"kind":p["kind"],"operationId":p["operationId"],"databaseVersion":32,"transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,"record":s.row,"before":before});
        if s.fault == "early-success" {
            frame["transactionCommitted"] = json!(false);
        }
        if s.fault == "native-ack" {
            frame["credentialAcknowledged"] = json!(true);
        }
        if s.fault == "wrong-operation" {
            frame["operationId"] = json!(uuid::Uuid::new_v4().to_string());
        }
        if s.fault == "version-race" && p["kind"] != "capture" {
            frame["databaseVersion"] = json!(33);
        }
        ready(Ok(frame.to_string()))
    }
}
fn store(fault: &'static str) -> Rc<RefCell<Store>> {
    Rc::new(RefCell::new(Store {
        row: row("Old title", 1),
        plans: vec![],
        fault,
        master: None,
        private: None,
        cancel: None,
        watch: None,
    }))
}
#[tokio::test]
async fn opaque_metadata_patch_waits_owned_commit_readback_preserves_all_local_state_and_no_native_ack()
 {
    let mut c = client(false);
    source(&mut c);
    let old_snapshot = c.ciphertext_snapshot();
    let s = store("");
    let original = s.borrow().row.clone();
    let encoded = c
        .browser_metadata_cache_json(
            OWNER,
            CHAT,
            BrowserMetadataCacheMode::PersistCurrent,
            host(),
            true,
            io(s.clone()),
        )
        .await
        .unwrap();
    let out: Value = serde_json::from_str(&encoded).unwrap();
    assert_eq!(out["chat"]["title"], "New title");
    assert_eq!(out["metadataOnly"], true);
    assert_eq!(out["historyComplete"], false);
    assert_eq!(out["messagesPersisted"], false);
    assert_eq!(out["credentialAcknowledged"], false);
    assert_eq!(c.credential_ack, 0);
    assert!(c.session.is_none());
    assert_eq!(c.ciphertext_snapshot(), old_snapshot);
    let s = s.borrow();
    assert_eq!(
        s.plans
            .iter()
            .map(|p| p["kind"].as_str().unwrap())
            .collect::<Vec<_>>(),
        vec!["capture", "compare_and_patch", "readback"]
    );
    for (field, value) in original.as_object().unwrap() {
        if !CIPHERS.contains(&field.as_str()) && !VERSIONS.contains(&field.as_str()) {
            assert_eq!(&s.row[field], value, "preserve every unowned/local field");
        }
    }
    assert!(s.row.get("unknown_plaintext_source").is_none());
    assert_eq!(s.row["messages_v"], 7);
}
#[tokio::test]
async fn local_opaque_restore_reads_no_account_no_email_no_write_and_restores_only_closed_metadata()
{
    let mut c = client(true);
    let s = store("");
    let out = c
        .browser_metadata_cache_json(
            OWNER,
            CHAT,
            BrowserMetadataCacheMode::Restore,
            host(),
            true,
            io(s.clone()),
        )
        .await
        .unwrap();
    let out: Value = serde_json::from_str(&out).unwrap();
    assert_eq!(out["chat"]["title"], "Old title");
    assert_eq!(s.borrow().plans.len(), 1);
    assert_eq!(c.credential_ack, 0);
    assert!(c.history.is_empty());
    assert!(c.sync_message_windows.is_empty());
    assert!(c.selected_first_pages.is_empty());
    let restored = &c.chats[CHAT];
    assert!(restored.get("unowned_extension").is_none());
    assert!(restored.get("encrypted_draft_md").is_none());
    assert!(c.session.is_none());
    assert!(c.native_master_key().is_err());
}
#[tokio::test]
async fn wrong_transaction_receipts_and_unowned_field_loss_never_publish_or_restore() {
    for fault in [
        "early-success",
        "native-ack",
        "wrong-operation",
        "version-race",
        "unowned-loss",
    ] {
        let mut c = client(false);
        source(&mut c);
        let before = c.ciphertext_snapshot();
        let s = store(fault);
        assert!(
            c.browser_metadata_cache_json(
                OWNER,
                CHAT,
                BrowserMetadataCacheMode::PersistCurrent,
                host(),
                true,
                io(s)
            )
            .await
            .is_err()
        );
        assert_eq!(c.ciphertext_snapshot(), before);
        assert_eq!(c.credential_ack, 0);
    }
}
#[tokio::test]
async fn original_opaque_resource_revoked_after_store_commit_refuses_readback_and_output() {
    let mut c = client(false);
    source(&mut c);
    let s = store("key-revoked");
    s.borrow_mut().master = Some(c.master_capability().unwrap());
    assert!(
        c.browser_metadata_cache_json(
            OWNER,
            CHAT,
            BrowserMetadataCacheMode::PersistCurrent,
            host(),
            true,
            io(s.clone())
        )
        .await
        .is_err()
    );
    assert_eq!(s.borrow().plans.len(), 2);
    assert_eq!(c.credential_ack, 0);
}
#[tokio::test]
async fn consent_native_local_write_team_key_rotation_and_stale_metadata_refuse_without_new_policy()
{
    let mut c = client(false);
    source(&mut c);
    let s = store("");
    assert!(
        c.browser_metadata_cache_json(
            OWNER,
            CHAT,
            BrowserMetadataCacheMode::PersistCurrent,
            host(),
            false,
            io(s.clone())
        )
        .await
        .is_err()
    );
    assert!(s.borrow().plans.is_empty());
    let mut native = Client::new("http://127.0.0.1:9", None).unwrap();
    assert!(
        native
            .browser_metadata_cache_json(
                OWNER,
                CHAT,
                BrowserMetadataCacheMode::Restore,
                host(),
                true,
                io(s.clone())
            )
            .await
            .is_err()
    );
    let mut local = client(true);
    assert!(
        local
            .browser_metadata_cache_json(
                OWNER,
                CHAT,
                BrowserMetadataCacheMode::PersistCurrent,
                host(),
                true,
                io(s.clone())
            )
            .await
            .is_err()
    );
    assert!(s.borrow().plans.is_empty());
    for fault in ["team", "key", "version"] {
        let mut c = client(false);
        source(&mut c);
        match fault {
            "team" => c.chats.get_mut(CHAT).unwrap()["team_id"] = json!(OWNER),
            "key" => {
                let desired = c.chats.get_mut(CHAT).unwrap();
                desired["encrypted_chat_key"] = json!(wrapper(8));
                desired["encrypted_title"] =
                    json!(crypto::encrypt_combined("New title", &[8; 32]).unwrap());
                desired["encrypted_chat_summary"] =
                    json!(crypto::encrypt_combined("Summary", &[8; 32]).unwrap());
            }
            _ => {
                c.chats.get_mut(CHAT).unwrap()["metadata_v"] = json!(0);
                c.chats.get_mut(CHAT).unwrap()["title_v"] = json!(0);
            }
        }
        let s = store("");
        assert!(
            c.browser_metadata_cache_json(
                OWNER,
                CHAT,
                BrowserMetadataCacheMode::PersistCurrent,
                host(),
                true,
                io(s.clone())
            )
            .await
            .is_err()
        );
        assert_eq!(s.borrow().plans.len(), 1);
    }
}

#[tokio::test]
async fn request_cancel_or_known_denial_after_actual_store_commit_stops_original_readback() {
    for fault in ["request-cancelled", "denied"] {
        let mut c = client(false);
        source(&mut c);
        let s = store(fault);
        s.borrow_mut().cancel = Some(c.operation_cancel.clone());
        s.borrow_mut().watch = Some(c.task_watch_authority.clone());
        assert!(
            c.browser_metadata_cache_json(
                OWNER,
                CHAT,
                BrowserMetadataCacheMode::PersistCurrent,
                host(),
                true,
                io(s.clone())
            )
            .await
            .is_err()
        );
        assert_eq!(s.borrow().plans.len(), 2);
        assert_eq!(c.credential_ack, 0);
    }
}
#[test]
fn original_epoch_and_binding_are_retained_independently_of_revision_snapshot_and_request() {
    for change in ["identity", "interactive", "app-origin"] {
        let mut c = client(false);
        source(&mut c);
        let fence = Fence {
            parent: c.operation_parent.clone(),
            private_gate: c.options.private_operation_gate.clone(),
            scope: AsyncCryptoScope::begin(&c).unwrap(),
            epoch: c.fresh_auth.operation_epoch(),
            binding: Zeroizing::new(c.fresh_auth_binding().unwrap()),
            source_stamp: source_stamp(&c, CHAT).unwrap(),
            revision: c.credential_revision,
        };
        let request = c.operation_cancel.clone();
        let revision = c.credential_revision;
        let stamp = source_stamp(&c, CHAT).unwrap();
        match change {
            "identity" => c.set_identity(crate::client::ClientIdentity::Npm),
            "interactive" => c.set_interactive(true),
            _ => c
                .set_app_origin(Some("https://other.example.invalid".into()))
                .unwrap(),
        };
        assert_eq!(c.operation_cancel, request);
        assert_eq!(c.credential_revision, revision);
        assert_eq!(source_stamp(&c, CHAT).unwrap(), stamp);
        assert!(
            c.metadata_cache_check(
                &fence,
                OWNER,
                CHAT,
                BrowserMetadataCacheMode::PersistCurrent
            )
            .is_err()
        );
    }
}

#[tokio::test]
async fn original_private_gate_or_parent_cancel_after_durable_patch_refuses_plaintext() {
    for fault in ["private-denied", "parent-cancelled"] {
        let mut c = client(false);
        source(&mut c);
        let s = store(if fault == "parent-cancelled" {
            "request-cancelled"
        } else {
            fault
        });
        if fault == "parent-cancelled" {
            s.borrow_mut().cancel = Some(c.operation_parent.clone());
        } else {
            let gate = Arc::new(std::sync::atomic::AtomicBool::new(true));
            s.borrow_mut().private = Some(gate.clone());
            c.set_private_operation_gate(Some(Arc::new(move || {
                if gate.load(std::sync::atomic::Ordering::SeqCst) {
                    Ok(())
                } else {
                    Err(Error::Forbidden)
                }
            })));
        }
        assert!(
            c.browser_metadata_cache_json(
                OWNER,
                CHAT,
                BrowserMetadataCacheMode::PersistCurrent,
                host(),
                true,
                io(s.clone())
            )
            .await
            .is_err()
        );
        assert_eq!(s.borrow().plans.len(), 2);
        assert_eq!(c.credential_ack, 0);
    }
}

#[tokio::test]
async fn crossed_independent_version_rollbacks_refuse_before_patch_io_and_preserve_store() {
    for (old_title, old_metadata, next_title, next_metadata) in [
        (100, 10, 100, 9), // Original blocker: unchanged larger title hides metadata rollback.
        (100, 10, 101, 9), // Even a newly advanced title cannot authorize metadata rollback.
        (10, 100, 9, 100), // Symmetric larger metadata clock cannot hide title rollback.
        (10, 100, 9, 101), // Even advanced metadata cannot authorize title rollback.
    ] {
        let mut c = client(false);
        source(&mut c);
        c.chats.get_mut(CHAT).unwrap()["title_v"] = json!(next_title);
        c.chats.get_mut(CHAT).unwrap()["metadata_v"] = json!(next_metadata);
        let s = store("");
        s.borrow_mut().row["title_v"] = json!(old_title);
        s.borrow_mut().row["metadata_v"] = json!(old_metadata);
        let stored = s.borrow().row.clone();
        let cached = c.ciphertext_snapshot();
        let result = c
            .browser_metadata_cache_json(
                OWNER,
                CHAT,
                BrowserMetadataCacheMode::PersistCurrent,
                host(),
                true,
                io(s.clone()),
            )
            .await;
        assert!(
            matches!(result, Err(Error::Conflict)),
            "independent clocks must refuse without publication"
        );
        assert_eq!(
            s.borrow().plans.len(),
            1,
            "capture only: no compare_and_patch or readback may start"
        );
        assert_eq!(s.borrow().plans[0]["kind"], "capture");
        assert_eq!(s.borrow().row, stored, "existing storage unchanged");
        assert_eq!(c.ciphertext_snapshot(), cached, "in-memory state unchanged");
        assert_eq!(c.credential_ack, 0);
    }
}
