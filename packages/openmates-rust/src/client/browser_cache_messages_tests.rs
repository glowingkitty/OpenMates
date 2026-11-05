//! Authored UNRUN core/opaque/IO regressions; no real account or browser.
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
fn client() -> Client {
    let mut c = Client::new("http://127.0.0.1:9", None).unwrap();
    c.browser_transport = true;
    c.user = json!({"id":OWNER});
    c.browser_authority = Some(BrowserAuthority {
        principal: OWNER.into(),
        persistence: BrowserPersistence::MemoryOnly,
        owner_guards: true,
    });
    c.browser_credentials = Some(credentials::BrowserCredentials {
        api_url: "http://127.0.0.1:9".into(),
        session_id: OWNER.into(),
        cookies: BTreeMap::new(),
        ws_token: Some("synthetic".into()),
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
fn fence(c: &Client) -> Fence {
    Fence {
        parent: c.operation_parent.clone(),
        private_gate: c.options.private_operation_gate.clone(),
        scope: AsyncCryptoScope::begin(c).unwrap(),
        epoch: c.fresh_auth.operation_epoch(),
        binding: Zeroizing::new(c.fresh_auth_binding().unwrap()),
        source_stamp: source_stamp(c, CHAT).unwrap(),
        revision: c.credential_revision,
    }
}
fn host() -> BrowserMetadataCacheScope {
    serde_json::from_value(json!({"lifecycleGeneration":1,"workspaceEpoch":0})).unwrap()
}
fn metadata() -> Value {
    use base64::Engine;
    let mut wrapped = vec![3; 12];
    wrapped.extend(crypto::encrypt_aead(&[9; 32], &[7; 32], &[3; 12], &[]).unwrap());
    json!({"chat_id":CHAT,"user_id":OWNER,"encrypted_chat_key":base64::engine::general_purpose::STANDARD.encode(wrapped),"encrypted_title":crypto::encrypt_combined("Title",&[9;32]).unwrap(),"messages_v":7,"title_v":1,"metadata_v":1,"encrypted_draft_md":"protected draft","cleared_draft_v":12,"team_draft_pending_sync":"delete","unknown_header":{"private":"stay"}})
}
fn row(id: &str, logical: &str, index: u64, content: &str) -> Value {
    json!({"id":id,"message_id":id,"client_message_id":logical,"chat_id":CHAT,"created_at":index,"role":"user","status":"delivered","encrypted_content":crypto::encrypt_combined(content,&[9;32]).unwrap(),"encrypted_sender_name":crypto::encrypt_combined("Old sender",&[9;32]).unwrap(),"encrypted_model_name":crypto::encrypt_combined("Old model",&[9;32]).unwrap(),"pending_encrypted_embed_bundle_v1":"current embed journal","pending_encrypted_turn_preflight_v1":"current turn journal","pending_turn_preflight_v1":0,"unowned_extension":{"private":"must survive"}})
}
fn raw_page(rows: Vec<Value>) -> crate::client::message_window::BrowserIncomingMessagePage {
    let mut meta = metadata();
    meta.as_object_mut().unwrap().remove("chat_id");
    meta["id"] = json!(CHAT);
    crate::client::message_window::BrowserIncomingMessagePage {
        metadata: Plain::new(meta),
        messages: Plain::new(rows),
        key: Zeroizing::new([9; 32]),
    }
}
fn source_rows() -> Vec<Value> {
    [('a',1),('b',2)].into_iter().map(|(letter,index)|json!({"id":format!("physical_{letter}"),"client_message_id":format!("logical_{letter}"),"chat_id":CHAT,"created_at":index,"role":"user","encrypted_content":crypto::encrypt_combined(&format!("New {letter}"),&[9;32]).unwrap(),"encrypted_model_name":null,"unknown_source":"never persist"})).collect()
}
struct Store {
    metadata: Value,
    rows: BTreeMap<String, Value>,
    plans: Vec<Value>,
    fault: &'static str,
    master: Option<MasterCapability>,
    cancel: Option<CancellationToken>,
    gate: Option<Arc<std::sync::atomic::AtomicBool>>,
    watch: Option<Arc<crate::client::project_task_watch::WatchAuthority>>,
}
fn store(fault: &'static str) -> Rc<RefCell<Store>> {
    Rc::new(RefCell::new(Store {
        metadata: metadata(),
        rows: [
            (
                "physical_a".into(),
                row("physical_a", "logical_a", 1, "Old a"),
            ),
            (
                "physical_b".into(),
                row("physical_b", "logical_b", 2, "Old b"),
            ),
        ]
        .into_iter()
        .collect(),
        plans: vec![],
        fault,
        master: None,
        cancel: None,
        gate: None,
        watch: None,
    }))
}
fn io(s: Rc<RefCell<Store>>) -> impl FnMut(String) -> Ready<Result<String>> {
    move |encoded| {
        let p: Value = serde_json::from_str(&encoded).unwrap();
        let mut s = s.borrow_mut();
        s.plans.push(p.clone());
        assert_eq!(p["stores"], json!(["chats", "messages"]));
        if s.fault=="assistant-duplicate" && p.get("assistantDuplicateAbsence").is_some() {
            return ready(Err(unsupported("ASSISTANT_MATCHING_CANDIDATE_REPLACEMENT_REMAINS_REQUIRED")));
        }
        assert!(!encoded.contains("must survive"));
        assert!(!encoded.contains("never persist"));
        let ids = p["messageIds"].as_array().unwrap();
        let mut rows: Vec<Value> = ids
            .iter()
            .map(|id| {
                s.rows
                    .get(id.as_str().unwrap())
                    .cloned()
                    .unwrap_or(Value::Null)
            })
            .collect();
        let mut before = Value::Null;
        if p["kind"] == "compare_and_patch" || p["kind"] == "compare_and_patch_user_insert" || p["kind"] == "compare_and_patch_incoming_insert" || p["kind"] == "compare_and_patch_cold_incoming_insert" {
            if s.fault == "stale" {
                return ready(Err(Error::Conflict));
            }
            if s.metadata.is_null() {assert_eq!(p["expectedMetadata"],Value::Null);assert_eq!(p["kind"],"compare_and_patch_cold_incoming_insert");s.metadata=p["metadataInsert"].clone();}else {
            assert_eq!(
                *projection(&s.metadata, CHAT, OWNER, true).unwrap(),
                p["expectedMetadata"]
            );}
            before = json!(rows);
            for (index, old) in rows.iter_mut().enumerate() {
                if old.is_null() {
                    assert_eq!(p["expectedRows"][index],Value::Null);
                    assert!(p["kind"]=="compare_and_patch_user_insert"||p["kind"]=="compare_and_patch_incoming_insert"||p["kind"]=="compare_and_patch_cold_incoming_insert");
                    *old=p["patches"][index]["insert"].clone();
                    s.rows.insert(ids[index].as_str().unwrap().into(),old.clone());
                    continue;
                }
                assert_eq!(*row_predicate(old, CHAT).unwrap(), p["expectedRows"][index]);
                for (field, value) in p["patches"][index]["set"].as_object().unwrap() {
                    old[field] = value.clone();
                }
                for field in p["patches"][index]["remove"].as_array().unwrap() {
                    old.as_object_mut().unwrap().remove(field.as_str().unwrap());
                }
                s.rows
                    .insert(ids[index].as_str().unwrap().into(), old.clone());
            }
            if s.fault == "unowned-loss" {
                rows[0].as_object_mut().unwrap().remove("unowned_extension");
            }
            if s.fault == "key-revoke" {
                s.master.as_ref().unwrap().invalidate();
            }
            if s.fault == "private" {
                s.gate
                    .as_ref()
                    .unwrap()
                    .store(false, std::sync::atomic::Ordering::SeqCst);
            }
            if s.fault == "denial" {
                s.watch
                    .as_ref()
                    .unwrap()
                    .deny_cached_chat(Some(CHAT))
                    .unwrap();
            }
            if s.fault == "cancel" {
                s.cancel.as_ref().unwrap().cancel();
            }
        }
        let mut out = json!({"version":1,"kind":p["kind"],"operationId":p["operationId"],"databaseVersion":32,"transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,"metadata":s.metadata,"rows":rows,"before":before});
        if s.fault == "early-success" {
            out["transactionCommitted"] = json!(false);
        }
        if s.fault == "native-ack" {
            out["credentialAcknowledged"] = json!(true);
        }
        ready(Ok(out.to_string()))
    }
}
#[tokio::test]
async fn supported_incoming_patches_existing_rows_preserving_omissions_aliases_journals_and_header()
{
    let c = client();
    let f = fence(&c);
    let s = store("");
    let old = s.borrow().rows.clone();
    let meta = s.borrow().metadata.clone();
    let mut transport = io(s.clone());
    let output = c
        .cache_browser_incoming_page(
            OWNER,
            CHAT,
            host(),
            &f,
            raw_page(source_rows()),
            &mut transport,
        )
        .await
        .unwrap();
    let out: Value = serde_json::from_str(&output).unwrap();
    assert_eq!(out["rowsUpdated"], 2);
    assert_eq!(out["historyComplete"], false);
    assert_eq!(out["messagesVersionAdvanced"], false);
    assert_eq!(c.credential_ack, 0);
    assert_eq!(s.borrow().metadata, meta);
    for (id, row) in &s.borrow().rows {
        assert_eq!(row["message_id"], old[id]["message_id"]);
        assert_eq!(row["client_message_id"], old[id]["client_message_id"]);
        assert_eq!(row["id"], old[id]["id"]);
        assert_eq!(row["unowned_extension"], old[id]["unowned_extension"]);
        assert_eq!(
            row["pending_encrypted_embed_bundle_v1"],
            old[id]["pending_encrypted_embed_bundle_v1"]
        );
        assert_eq!(
            row["pending_encrypted_turn_preflight_v1"],
            old[id]["pending_encrypted_turn_preflight_v1"]
        );
        assert_eq!(row["pending_turn_preflight_v1"], 1);
        assert_eq!(
            row["encrypted_sender_name"], old[id]["encrypted_sender_name"],
            "wire omission preserves current cipher"
        );
        assert_eq!(
            row["encrypted_model_name"],
            Value::Null,
            "explicit wire null preserved"
        );
        assert!(row.get("unknown_source").is_none());
    }
    assert_eq!(
        s.borrow()
            .plans
            .iter()
            .map(|p| p["kind"].as_str().unwrap().to_owned())
            .collect::<Vec<_>>(),
        vec!["capture", "compare_and_patch", "readback"]
    );
}
#[tokio::test]
async fn call_outbox_and_newer_stored_revision_veto_even_status_or_decrypted_update() {
    for cause in ["call", "revision"] {
        let c = client();
        let f = fence(&c);
        let s = store("");
        let mut rows = source_rows();
        for row in &mut rows {
            row["queue_revision"] = json!(8);
            row["status"] = json!("synced");
        }
        for row in s.borrow_mut().rows.values_mut() {
            row["status"] = json!("queued");
            if cause == "call" {
                row["call_persistence_v1"] =
                    json!({"entries":[{"cipher":"pending call ciphertext"}]});
            } else {
                row["queue_revision"] = json!(9);
            }
        }
        let original = s.borrow().rows.clone();
        let mut transport = io(s.clone());
        let out: Value = serde_json::from_str(
            &c.cache_browser_incoming_page(OWNER, CHAT, host(), &f, raw_page(rows), &mut transport)
                .await
                .unwrap(),
        )
        .unwrap();
        assert_eq!(out["rowsUpdated"], 0);
        assert_eq!(out["rowsRetained"], 2);
        assert_eq!(s.borrow().rows, original);
        assert_eq!(c.credential_ack, 0);
    }
}
#[tokio::test]
async fn unsupported_local_terminal_insert_and_dispatch_modes_never_reach_write_transaction() {
    for cause in [
        "sending",
        "streaming",
        "waiting_for_user",
        "failed",
        "missing",
        "dispatch",
    ] {
        let c = client();
        let f = fence(&c);
        let s = store("");
        if cause == "missing" {
            s.borrow_mut().rows.remove("physical_a");
        } else if cause != "dispatch" {
            s.borrow_mut().rows.get_mut("physical_a").unwrap()["status"] = json!(cause);
        }
        let mut rows = source_rows();
        if cause == "dispatch" {
            rows[0]["queue_dispatch_status"] = json!("processing");
        }
        let original = s.borrow().rows.clone();
        let mut transport = io(s.clone());
        assert!(
            c.cache_browser_incoming_page(OWNER, CHAT, host(), &f, raw_page(rows), &mut transport)
                .await
                .is_err()
        );
        assert!(s.borrow().plans.iter().all(|p| p["kind"] == "capture"));
        assert_eq!(s.borrow().rows, original);
        assert_eq!(c.credential_ack, 0);
    }
}
#[tokio::test]
async fn stale_predicate_or_bad_receipt_never_publishes_or_acks() {
    for fault in ["stale", "early-success", "native-ack", "unowned-loss"] {
        let c = client();
        let f = fence(&c);
        let s = store(fault);
        let mut transport = io(s.clone());
        assert!(
            c.cache_browser_incoming_page(
                OWNER,
                CHAT,
                host(),
                &f,
                raw_page(source_rows()),
                &mut transport
            )
            .await
            .is_err()
        );
        assert_eq!(c.credential_ack, 0);
    }
}
#[tokio::test]
async fn original_request_or_opaque_resource_revocation_after_commit_stops_readback() {
    for fault in ["cancel", "key-revoke"] {
        let c = client();
        let f = fence(&c);
        let s = store(fault);
        s.borrow_mut().master = Some(c.master_capability().unwrap());
        s.borrow_mut().cancel = Some(c.operation_cancel.clone());
        let mut transport = io(s.clone());
        assert!(
            c.cache_browser_incoming_page(
                OWNER,
                CHAT,
                host(),
                &f,
                raw_page(source_rows()),
                &mut transport
            )
            .await
            .is_err()
        );
        assert_eq!(s.borrow().plans.len(), 2);
        assert_eq!(c.credential_ack, 0);
    }
}
#[tokio::test]
async fn complete_source_packet_overflow_refuses_without_any_capture_or_truncation() {
    let c = client();
    let f = fence(&c);
    let s = store("");
    let mut rows = source_rows();
    rows[0]["unknown_source"] = json!("x".repeat(256 * 1024));
    let original = s.borrow().rows.clone();
    let mut transport = io(s.clone());
    assert!(
        c.cache_browser_incoming_page(OWNER, CHAT, host(), &f, raw_page(rows), &mut transport)
            .await
            .is_err()
    );
    assert!(s.borrow().plans.is_empty());
    assert_eq!(s.borrow().rows, original);
}
#[tokio::test]
async fn physical_utf16_keys_keep_distinct_logical_client_aliases() {
    let c = client();
    let f = fence(&c);
    let s = store("");
    let mut rows = source_rows();
    rows[0]["id"] = json!("\u{10000}");
    rows[1]["id"] = json!("\u{e000}");
    let mut a = s.borrow_mut().rows.remove("physical_a").unwrap();
    let mut b = s.borrow_mut().rows.remove("physical_b").unwrap();
    a["id"] = json!("\u{10000}");
    a["message_id"] = json!("\u{10000}");
    b["id"] = json!("\u{e000}");
    b["message_id"] = json!("\u{e000}");
    s.borrow_mut().rows.insert("\u{10000}".into(), a);
    s.borrow_mut().rows.insert("\u{e000}".into(), b);
    let mut transport = io(s.clone());
    c.cache_browser_incoming_page(OWNER, CHAT, host(), &f, raw_page(rows), &mut transport)
        .await
        .unwrap();
    assert_eq!(
        s.borrow().plans[0]["messageIds"],
        json!(["\u{10000}", "\u{e000}"])
    );
    assert_eq!(
        s.borrow().rows["\u{10000}"]["client_message_id"],
        "logical_a"
    );
}
#[test]
fn actual_get_message_semantics_remove_successful_cipher_before_fill_missing_predicate() {
    let old = row("physical_a", "logical_a", 1, "Old a");
    let new = incoming(&source_rows()[0], CHAT).unwrap();
    let semantic = decrypted_existing(&old, &[9; 32]).unwrap();
    assert!(semantic.get("encrypted_content").is_none());
    assert_eq!(semantic["content"], "Old a");
    assert!(!message_policy::has_new_encrypted_fields(&old, &new).unwrap());
    assert!(message_policy::has_new_encrypted_fields(&semantic, &new).unwrap());
    assert!(!message_policy::should_update_message(&semantic, &new).unwrap());
}

#[tokio::test]
async fn parent_private_or_denial_revocation_after_commit_never_re_admits_original_read() {
    for fault in ["parent", "private", "denial"] {
        let mut c = client();
        let s = store(if fault == "parent" { "cancel" } else { fault });
        if fault == "parent" {
            s.borrow_mut().cancel = Some(c.operation_parent.clone());
        }
        if fault == "private" {
            let gate = Arc::new(std::sync::atomic::AtomicBool::new(true));
            s.borrow_mut().gate = Some(gate.clone());
            c.set_private_operation_gate(Some(Arc::new(move || {
                if gate.load(std::sync::atomic::Ordering::SeqCst) {
                    Ok(())
                } else {
                    Err(Error::Forbidden)
                }
            })));
        }
        if fault == "denial" {
            s.borrow_mut().watch = Some(c.task_watch_authority.clone());
        }
        let f = fence(&c);
        let mut transport = io(s.clone());
        assert!(
            c.cache_browser_incoming_page(
                OWNER,
                CHAT,
                host(),
                &f,
                raw_page(source_rows()),
                &mut transport
            )
            .await
            .is_err()
        );
        assert_eq!(s.borrow().plans.len(), 2);
        assert_eq!(c.credential_ack, 0);
    }
}
#[tokio::test]
async fn explicit_cache_entry_refuses_native_local_profile_and_missing_consent_before_any_io() {
    for mode in ["native", "local", "consent"] {
        let mut c = if mode == "native" {
            Client::new("http://127.0.0.1:9", None).unwrap()
        } else {
            client()
        };
        if mode == "local" {
            c.browser_local_read_only = true;
        }
        let s = store("");
        let result = c
            .browser_authoritative_message_cache_json(
                OWNER,
                CHAT,
                crate::client::message_window::MessageWindowOptions::default(),
                host(),
                mode != "consent",
                io(s.clone()),
            )
            .await;
        match mode {
            "native" => assert!(matches!(result, Err(Error::Forbidden))),
            "consent" => assert!(matches!(result, Err(Error::Invalid(_)))),
            _ => assert!(matches!(
                result,
                Err(Error::Unavailable {
                    code: "browser_offline_read_only",
                    ..
                })
            )),
        }
        assert!(s.borrow().plans.is_empty());
        assert_eq!(c.credential_ack, 0);
    }
}

#[tokio::test]
async fn retained_token_uses_actual_protected_rows_and_refuses_later_local_edits() {
    let c = client(); let f = fence(&c); let s = store("");
    s.borrow_mut().rows.get_mut("physical_a").unwrap()["call_persistence_v1"] = json!({"entries":[{"local":"owned"}]});
    let original = s.borrow().rows["physical_a"].clone();
    let data = c.cache_browser_incoming_page_retained(OWNER, CHAT, host(), &f,
        raw_page(source_rows()), false, false, None, &mut io(s.clone())).await.unwrap();
    let token = BrowserRetainedMessageCache { fence:f, monitor_context:None, owner:OWNER.into(), chat:CHAT.into(), data };
    let mut port=io(s.clone());
    let view=c.browser_revalidate_retained_message_cache(&token,&mut port).await.unwrap();
    let projected=view.with_rows(|_,rows,_,dispositions| {
        assert_eq!(rows[0],original);
        assert_eq!(dispositions[0]["disposition"],"retained");
        assert_eq!(dispositions[0]["canonicalIncomingDurablyAcknowledged"],false);
        Ok(Plain::new(json!({"cached":true,"historyComplete":false})))
    }).unwrap();
    assert_eq!(projected["cached"],true);
    s.borrow_mut().rows.get_mut("physical_a").unwrap()["unowned_extension"] = json!({"later":true});
    assert!(matches!(c.browser_revalidate_retained_message_cache(&token,&mut port).await,Err(Error::Conflict)));
}
#[tokio::test]
async fn retained_token_original_epoch_cancel_and_master_resource_never_readmit() {
    for mode in ["epoch","cancel","master"] {
        let mut c=client(); let f=fence(&c); let s=store("");
        let data=c.cache_browser_incoming_page_retained(OWNER,CHAT,host(),&f,
            raw_page(source_rows()),false,false,None,&mut io(s.clone())).await.unwrap();
        let token=BrowserRetainedMessageCache { fence:f,monitor_context:None,owner:OWNER.into(),chat:CHAT.into(),data };
        match mode {
            "epoch" => c.set_interactive(true),
            "cancel" => c.operation_parent.cancel(),
            _ => c.master_capability().unwrap().invalidate(),
        }
        let count=s.borrow().plans.len();
        assert!(c.browser_revalidate_retained_message_cache(&token,&mut io(s.clone())).await.is_err());
        assert_eq!(s.borrow().plans.len(),count);
    }
}

#[tokio::test]
async fn explicit_new_user_insertion_preserves_defaults_ids_and_existing_local_data() {
 let c=client();let f=fence(&c);let s=store("");s.borrow_mut().rows.remove("physical_b");
 let a=s.borrow().rows["physical_a"].clone();
 // Compare the exact stored ciphertext; metadata() encrypts with a fresh nonce.
 let original_metadata=s.borrow().metadata.clone();
 let data=c.cache_browser_incoming_page_retained(OWNER,CHAT,host(),&f,raw_page(source_rows()),true,false,None,&mut io(s.clone())).await.unwrap();
 assert_eq!(data.dispositions[1]["disposition"],"inserted");
 assert_eq!(data.readback["rows"][1]["message_id"],"physical_b");
 assert_eq!(data.readback["rows"][1]["client_message_id"],"logical_b");
 assert_eq!(data.readback["rows"][1]["status"],"delivered");
 assert!(data.readback["rows"][1].get("unknown_source").is_none());
 assert!(data.readback["rows"][1].get("pending_encrypted_turn_preflight_v1").is_none());
 assert_eq!(s.borrow().metadata,original_metadata);
 assert_eq!(s.borrow().rows["physical_a"]["unowned_extension"],a["unowned_extension"]);
 assert_eq!(serde_json::from_str::<Value>(&data.summary).unwrap()["rowsInserted"],1);
}
#[tokio::test]
async fn assistant_cross_id_insertion_refuses_before_write_transaction() {
 let c=client();let f=fence(&c);let s=store("");s.borrow_mut().rows.remove("physical_b");
 let baseline=s.borrow().rows.clone();let mut rows=source_rows();rows[1]["role"]=json!("assistant");
 assert!(c.cache_browser_incoming_page_retained(OWNER,CHAT,host(),&f,raw_page(rows),true,false,None,&mut io(s.clone())).await.is_err());
 assert_eq!(s.borrow().plans.len(),1);assert_eq!(s.borrow().rows,baseline);
}

#[tokio::test]
async fn assistant_insertion_plan_pins_source_cipher_timestamp_and_final_readback_drops_predicate() {
 let c=client();let f=fence(&c);let s=store("");s.borrow_mut().rows.remove("physical_b");
 let mut rows=source_rows();rows[1]["role"]=json!("assistant");let cipher=rows[1]["encrypted_content"].clone();
 let data=c.cache_browser_incoming_page_retained(OWNER,CHAT,host(),&f,raw_page(rows),true,true,None,&mut io(s.clone())).await.unwrap();
 assert_eq!(data.readback["rows"][1]["role"],"assistant");
 let s=s.borrow();assert_eq!(s.plans[0]["kind"],"capture_incoming_insert");
 for p in &s.plans[..2] {assert_eq!(p["assistantDuplicateAbsence"],json!([{"messageId":"physical_b","encryptedContent":cipher,"createdAt":2,"role":"assistant","timeThresholdExclusive":60}]));}
 assert!(s.plans[2].get("assistantDuplicateAbsence").is_none());
 assert_eq!(data.dispositions[1]["canonicalIncomingDurablyAcknowledged"],false);
}
#[tokio::test]
async fn assistant_candidate_refusal_never_becomes_fallback_or_synthetic_persistence() {
 let c=client();let f=fence(&c);let s=store("assistant-duplicate");s.borrow_mut().rows.remove("physical_b");let old=s.borrow().rows.clone();
 let mut rows=source_rows();rows[1]["role"]=json!("assistant");
 assert!(c.cache_browser_incoming_page_retained(OWNER,CHAT,host(),&f,raw_page(rows),true,true,None,&mut io(s.clone())).await.is_err());
 assert_eq!(s.borrow().plans.len(),1);assert_eq!(s.borrow().rows,old);
}

#[tokio::test]
async fn cold_header_creation_uses_source_defaults_and_inventory_never_completeness() {
 for empty in [false,true] {
 let c=client();let f=fence(&c);let s=store("");s.borrow_mut().metadata=Value::Null;s.borrow_mut().rows.clear();
 let mut source=raw_page(if empty {vec![]}else{source_rows()});source.metadata["messages_v"]=json!(750);
 let data=c.cache_browser_incoming_page_retained(OWNER,CHAT,host(),&f,source,true,true,Some(123),&mut io(s.clone())).await.unwrap();
 assert_eq!(data.readback["metadata"]["messages_v"],750);assert_eq!(data.readback["metadata"]["is_metadata_only"],true);
 assert_eq!(data.readback["metadata"]["created_at"],123);assert_eq!(data.readback["metadata"]["draft_v"],0);
 assert!(data.readback["metadata"].get("historyComplete").is_none());
 let summary:Value=serde_json::from_str(&data.summary).unwrap();assert_eq!(summary["contentCoverage"],"unknown");assert_eq!(summary["historyComplete"],false);assert_eq!(summary["messagesVersionMeaning"],"metadata_inventory_only");
 assert_eq!(data.readback["rows"].as_array().unwrap().len(),if empty {0}else{2});
 }
}
#[tokio::test]
async fn malformed_plaintext_or_anonymous_header_cannot_reach_io() {
 let c=client();let f=fence(&c);let s=store("");
 let mut source=raw_page(source_rows());source.metadata["is_private"]=json!("wrong-type");
 assert!(c.cache_browser_incoming_page_retained(OWNER,CHAT,host(),&f,source,true,true,Some(123),&mut io(s.clone())).await.is_err());assert!(s.borrow().plans.is_empty());
}

// V2: exercise the actual metadata capture/CAS/readback receipt and unchanged
// full physical message reread. These async Rust cases are authored UNRUN.
fn metadata_port(s:Rc<RefCell<Store>>, fault:&'static str)->impl FnMut(String)->Ready<Result<String>> {
 move|encoded| {
  let p:Value=serde_json::from_str(&encoded).unwrap();let mut s=s.borrow_mut();
  assert_eq!(p["store"],json!("chats"));
  let mut before=Value::Null;
  if p["kind"]=="compare_and_patch" {
   if fault=="before" {s.metadata["unknown_header"]=json!({"concurrent":true});}
   before=s.metadata.clone();
   for(field,value)in p["patch"].as_object().unwrap(){s.metadata[field]=value.clone();}
  }
  if p["kind"]=="readback"&&fault=="readback" {s.metadata["unknown_header"]=json!({"concurrent":true});}
  ready(Ok(json!({"version":1,"kind":p["kind"],"operationId":p["operationId"],"databaseVersion":32,
   "transactionCommitted":true,"credentialAcknowledged":false,"crossDatabaseAssociationProven":false,
   "record":s.metadata,"before":before}).to_string()))
 }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[tokio::test]
async fn owned_metadata_transition_admits_only_its_exact_original_physical_header() {
 for fault in ["","before","readback","row","cancel"] {
  let mut c=client();let s=store("");let mut desired=s.borrow().metadata.clone();
  desired["title_v"]=json!(2);desired["metadata_v"]=json!(2);
  desired["encrypted_title"]=json!(crypto::encrypt_combined("Updated",&[9;32]).unwrap());
  c.chats.insert(CHAT.into(),desired.clone());let f=fence(&c);
  let mut source=raw_page(source_rows());source.metadata=Plain::new(desired);source.metadata["id"]=json!(CHAT);
  let data=c.cache_browser_incoming_page_retained(OWNER,CHAT,host(),&f,source,false,false,None,&mut io(s.clone())).await.unwrap();
  let mut token=BrowserRetainedMessageCache{fence:f,monitor_context:None,owner:OWNER.into(),chat:CHAT.into(),data};
  // Original token deliberately rejects the operation's own metadata write until
  // it consumes the nonserializable receipt with its exact full preimage.
  let result=c.browser_metadata_cache_with_owned_transition(OWNER,CHAT,host(),true,metadata_port(s.clone(),fault)).await;
  if fault=="readback" {assert!(result.is_err());continue;}
  let (_,receipt)=result.unwrap();
  assert!(matches!(c.browser_revalidate_retained_message_cache(&token,&mut io(s.clone())).await,Err(Error::Conflict)));
  if fault=="cancel" {c.operation_parent.cancel();}
  let adopted=c.browser_apply_owned_metadata_transition(&mut token,receipt);
  if matches!(fault,"before"|"cancel") {assert!(adopted.is_err());continue;}
  adopted.unwrap();
  if fault=="row" {s.borrow_mut().rows.get_mut("physical_a").unwrap()["unowned_extension"]=json!({"concurrent":true});}
  let reread=c.browser_revalidate_retained_message_cache(&token,&mut io(s.clone())).await;
  if fault=="row" {assert!(matches!(reread,Err(Error::Conflict)));}
  else {let view=reread.unwrap();view.ensure_current().unwrap();assert_eq!(s.borrow().metadata["unknown_header"],json!({"private":"stay"}));assert_eq!(s.borrow().metadata["messages_v"],7);assert_eq!(s.borrow().metadata["encrypted_draft_md"],"protected draft");}
 }
}
