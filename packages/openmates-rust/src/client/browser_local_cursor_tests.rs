//! Actual shared callback coordinator regressions, authored UNRUN for CI.
//! Public synthetic maintained-IDB fixture; no native credentials or product IO.
//! Callback fixtures execute plans as readonly stores; only Rust owns selection.
//! Opaque master AES uses existing legacy wire and remains non-exporting.
//! Output/cancel tests do not claim real browser, allocator or performance proof.
// contract-test-file: tooling
use super::*;
use crate::client::saved_chat_read::SavedChatContentMode;
use crate::crypto::master::{MasterCapability, MasterCrypto, MasterCryptoFuture};
use std::{cell::RefCell, sync::Arc};
use tokio::sync::Notify;
const OWNER: &str = "11111111-1111-4111-8111-111111111111";
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
struct Aes;
impl MasterCrypto for Aes {
    fn encrypt<'a>(&'a self, iv: &'a [u8; 12], plain: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move {
            crypto::encrypt_aead(plain, &[7; 32], iv, &[]).map(zeroize::Zeroizing::new)
        })
    }
    fn decrypt<'a>(&'a self, iv: &'a [u8; 12], cipher: &'a [u8]) -> MasterCryptoFuture<'a> {
        Box::pin(async move { crypto::decrypt_aead(cipher, &[7; 32], iv, &[]) })
    }
}
fn client() -> Client {
    let mut client = Client::new("http://127.0.0.1:9", None).unwrap();
    client.browser_transport = true;
    client.browser_local_read_only = true;
    client.user = json!({"id":OWNER});
    client.browser_authority = Some(BrowserAuthority {
        principal: OWNER.into(),
        persistence: BrowserPersistence::MemoryOnly,
        owner_guards: false,
    });
    client.browser_credentials = Some(credentials::BrowserCredentials {
        api_url: "http://127.0.0.1:9".into(),
        session_id: OWNER.into(),
        cookies: BTreeMap::new(),
        ws_token: None,
        master: MasterCapability::opaque_for_test(Arc::new(Aes)),
        hashed_email: String::new(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    });
    client
}
fn fixture() -> Value {
    serde_json::from_str::<Value>(include_str!(
        "../../tests/fixtures/browser-idb-local-window.json"
    ))
    .unwrap()["input"]
        .take()
}
fn reply(encoded: &str, input: &Value) -> Value {
    let plan: Value = serde_json::from_str(encoded).unwrap();
    assert_eq!(plan["owner"], OWNER);
    assert_eq!(plan["chatId"], CHAT);
    let mut output = json!({"version":1,"kind":plan["kind"],"operationId":plan["operationId"],"databaseVersion":31});
    if plan["kind"] == "metadata" {
        output["chat_metadata"] = input["chat_metadata"].clone();
        output["messages"] = json!([]);
        output["wrappers"] = input["wrappers"].clone();
        output["boundary"] = Value::Null;
        output["compression_checkpoints"] = input["compression_checkpoints"].clone();
    } else if plan["kind"] == "anchor" {
        assert_eq!(plan["maxPayloadRows"], 1);
        output["messages"] = json!(
            input["messages"]
                .as_array()
                .unwrap()
                .iter()
                .filter(
                    |r| wire::position(r).unwrap().1 == plan["anchorMessageId"].as_str().unwrap()
                )
                .cloned()
                .collect::<Vec<_>>()
        );
    } else {
        let lower: Option<Bound> = if plan["lower"].is_null() {
            None
        } else {
            Some(Bound {
                created_at: plan["lower"]["createdAt"].as_i64().unwrap(),
                message_id: plan["lower"]["messageId"].as_str().map(str::to_owned),
                open: plan["lower"]["open"].as_bool().unwrap(),
            })
        };
        let upper: Option<Bound> = if plan["upper"].is_null() {
            None
        } else {
            Some(Bound {
                created_at: plan["upper"]["createdAt"].as_i64().unwrap(),
                message_id: plan["upper"]["messageId"].as_str().map(str::to_owned),
                open: plan["upper"]["open"].as_bool().unwrap(),
            })
        };
        let mut rows = input["messages"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|r| in_range(wire::position(r).unwrap(), lower.as_ref(), upper.as_ref()))
            .cloned()
            .collect::<Vec<_>>();
        if plan["direction"] == "prev" {
            rows.reverse();
        }
        let limit = plan["maxPayloadRows"].as_u64().unwrap() as usize;
        assert!(limit <= 20);
        let next = rows.get(limit).map(|row| {
            let (time, id) = wire::position(row).unwrap();
            json!({"createdAt":time,"messageId":id})
        });
        rows.truncate(limit);
        output["messages"] = json!(rows);
        output["nextKey"] = next.clone().unwrap_or(Value::Null);
        output["rangeExhausted"] = json!(next.is_none());
    }
    output
}
#[tokio::test]
async fn public_cursor_read_requests_only_twenty_payloads_and_preserves_incomplete_aliases() {
    let client = client();
    let mut input = fixture();
    input["compression_checkpoints"] = json!([]);
    let calls = RefCell::new(vec![]);
    let snapshot = client.ciphertext_snapshot();
    let output = client
        .browser_local_saved_chat_read_with_io_json(
            OWNER,
            CHAT,
            SavedChatReadOptions::default(),
            |plan| {
                calls
                    .borrow_mut()
                    .push(serde_json::from_str::<Value>(&plan).unwrap());
                std::future::ready(Ok(reply(&plan, &input).to_string()))
            },
        )
        .await
        .unwrap();
    let output: Value = serde_json::from_str(&output).unwrap();
    assert_eq!(calls.borrow().len(), 2);
    assert_eq!(calls.borrow()[1]["maxPayloadRows"], 20);
    let protocol: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/browser-local-read-plan.json"
    ))
    .unwrap();
    let mut metadata_plan = calls.borrow()[0].clone();
    metadata_plan["operationId"] = protocol["metadataPlan"]["operationId"].clone();
    assert_eq!(metadata_plan, protocol["metadataPlan"]);
    let mut latest_plan = calls.borrow()[1].clone();
    latest_plan["operationId"] = protocol["latestPlan"]["operationId"].clone();
    latest_plan["maxPacketBytes"] = protocol["latestPlan"]["maxPacketBytes"].clone();
    assert_eq!(latest_plan, protocol["latestPlan"]);
    assert!(calls.borrow()[1]["maxPacketBytes"].as_u64().unwrap() < 256 * 1024);
    assert_eq!(output["chat"]["messages"].as_array().unwrap().len(), 20);
    assert_eq!(
        output["chat"]["messages"][0]["id"],
        input["messages"][12]["client_message_id"]
    );
    assert_eq!(
        output["startCursor"]["messageId"],
        input["messages"][12]["message_id"]
    );
    assert_eq!(
        output["messageMetadata"][0]["sourceMessageId"],
        input["messages"][12]["message_id"]
    );
    assert_eq!(output["hasMoreBefore"], true);
    assert_eq!(output["fresh"], false);
    assert_eq!(output["historyComplete"], false);
    assert_eq!(output["pagesRead"], 0);
    assert_eq!(client.ciphertext_snapshot(), snapshot);
    assert_eq!(client.credential_ack, 0);
}
#[tokio::test]
async fn rust_checkpoint_cutoff_is_issued_as_exclusive_timestamp_and_restores_page_local_pii() {
    let client = client();
    let input = fixture();
    let options = SavedChatReadOptions {
        content_mode: SavedChatContentMode::PageLocal,
        ..Default::default()
    };
    let output = client
        .browser_local_saved_chat_read_with_io_json(OWNER, CHAT, options, |plan| {
            let value: Value = serde_json::from_str(&plan).unwrap();
            if value["kind"] == "messages" {
                assert_eq!(
                    value["lower"],
                    json!({"createdAt":110,"messageId":null,"open":true})
                );
            }
            std::future::ready(Ok(reply(&plan, &input).to_string()))
        })
        .await
        .unwrap();
    let value: Value = serde_json::from_str(&output).unwrap();
    assert_eq!(value["chat"]["messages"].as_array().unwrap().len(), 10);
    assert_eq!(value["hasMoreBefore"], false);
    assert_eq!(
        value["chat"]["messages"][0]["content"],
        "Synthetic local row 23 Synthetic Person"
    );
    assert_eq!(value["piiRestoration"], "page_local");
}
#[tokio::test]
async fn physical_before_cursor_returns_older_tied_rows_and_wrong_scope_never_calls_io() {
    let client = client();
    let mut input = fixture();
    input["compression_checkpoints"] = json!([]);
    let first = client
        .browser_local_saved_chat_read_with_io_json(
            OWNER,
            CHAT,
            SavedChatReadOptions::default(),
            |p| std::future::ready(Ok(reply(&p, &input).to_string())),
        )
        .await
        .unwrap();
    let value: Value = serde_json::from_str(&first).unwrap();
    let cursor: crate::client::message_window::MessageWindowCursor =
        serde_json::from_value(value["startCursor"].clone()).unwrap();
    let options = SavedChatReadOptions {
        before: Some(cursor.clone()),
        ..Default::default()
    };
    let older = client
        .browser_local_saved_chat_read_with_io_json(OWNER, CHAT, options, |p| {
            std::future::ready(Ok(reply(&p, &input).to_string()))
        })
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&older).unwrap()["chat"]["messages"]
            .as_array()
            .unwrap()
            .len(),
        12
    );
    let mut cursor = cursor;
    cursor.scope = "0".repeat(64);
    let refused = client
        .browser_local_saved_chat_read_with_io_json(
            OWNER,
            CHAT,
            SavedChatReadOptions {
                before: Some(cursor),
                ..Default::default()
            },
            |_| {
                panic!("wrong scope must not issue IO");
                std::future::ready(Ok(String::new()))
            },
        )
        .await;
    assert!(matches!(refused, Err(Error::Conflict)));
}
#[tokio::test]
async fn malformed_correlations_versions_extra_payload_and_sentinel_refuse_without_ack() {
    for change in 0..5 {
        let client = client();
        let input = fixture();
        let result = client
            .browser_local_saved_chat_read_with_io_json(
                OWNER,
                CHAT,
                SavedChatReadOptions::default(),
                |plan| {
                    let mut out = reply(&plan, &input);
                    if out["kind"] == "messages" {
                        match change {
                            0 => out["operationId"] = json!(CHAT),
                            1 => out["databaseVersion"] = json!(32),
                            2 => out["messages"].as_array_mut().unwrap().reverse(),
                            3 => {
                                out["nextKey"] = json!({"createdAt":0,"messageId":"outside-range"});
                                out["rangeExhausted"] = json!(false);
                            }
                            _ => out["messages"] = json!(vec![input["messages"][31].clone(); 21]),
                        }
                    }
                    std::future::ready(Ok(out.to_string()))
                },
            )
            .await;
        assert!(result.is_err());
        assert_eq!(client.credential_ack, 0);
        assert!(client.history.is_empty());
    }
}
#[tokio::test]
async fn cancel_key_revocation_and_denial_during_platform_await_block_late_publication() {
    for change in 0..3 {
        let client = client();
        let input = fixture();
        let entered = Arc::new(Notify::new());
        let release = Arc::new(Notify::new());
        let mut future = Box::pin(client.browser_local_saved_chat_read_with_io_json(
            OWNER,
            CHAT,
            SavedChatReadOptions::default(),
            |plan| {
                let result = reply(&plan, &input).to_string();
                let entered = entered.clone();
                let release = release.clone();
                async move {
                    entered.notify_one();
                    release.notified().await;
                    Ok(result)
                }
            },
        ));
        tokio::select! {biased; result=&mut future=>{let _=result;panic!("must await owned IO");},_=entered.notified()=>{}}
        match change {
            0 => client.operation_cancel.cancel(),
            1 => client.master_capability().unwrap().invalidate(),
            _ => client
                .task_watch_authority
                .deny_cached_chat(Some(CHAT))
                .unwrap(),
        }
        release.notify_one();
        assert!(future.await.is_err());
        assert!(client.history.is_empty());
        assert_eq!(client.credential_ack, 0);
    }
}
#[tokio::test]
async fn dropped_platform_future_cannot_publish_or_ack() {
    let client = client();
    let input = fixture();
    let entered = Notify::new();
    let release = Notify::new();
    let snapshot = client.ciphertext_snapshot();
    let mut future = Box::pin(client.browser_local_saved_chat_read_with_io_json(
        OWNER,
        CHAT,
        SavedChatReadOptions::default(),
        |plan| {
            let result = reply(&plan, &input).to_string();
            let entered = &entered;
            let release = &release;
            async move {
                entered.notify_one();
                release.notified().await;
                Ok(result)
            }
        },
    ));
    tokio::select! {biased; result=&mut future=>{let _=result;panic!("must await IO");},_=entered.notified()=>{}}
    drop(future);
    release.notify_one();
    assert_eq!(client.ciphertext_snapshot(), snapshot);
    assert_eq!(client.credential_ack, 0);
}

#[tokio::test]
async fn around_uses_physical_anchor_fixed_split_no_refill_and_global_budget() {
    let protocol: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/browser-local-around-plan.json"
    ))
    .unwrap();
    for case in protocol["cases"].as_array().unwrap() {
        let index = case["index"].as_u64().unwrap() as usize;
        let limit = case["limit"].as_u64().unwrap() as usize;
        let client = client();
        let mut input = fixture();
        input["compression_checkpoints"] = json!([]);
        let anchor = input["messages"][index]["message_id"]
            .as_str()
            .unwrap()
            .to_owned();
        let calls = RefCell::new(vec![]);
        let options = SavedChatReadOptions {
            limit,
            anchor_message_id: Some(anchor.clone()),
            ..Default::default()
        };
        let direct = client
            .browser_local_saved_chat_read_json(OWNER, CHAT, options.clone(), &input.to_string())
            .await
            .unwrap();
        let direct: Value = serde_json::from_str(&direct).unwrap();
        let out = client
            .browser_local_saved_chat_read_with_io_json(OWNER, CHAT, options, |plan| {
                let value: Value = serde_json::from_str(&plan).unwrap();
                calls.borrow_mut().push(value);
                std::future::ready(Ok(reply(&plan, &input).to_string()))
            })
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(out["chat"], direct["chat"]);
        assert_eq!(out["messageMetadata"], direct["messageMetadata"]);
        assert_eq!(
            out["piiMappingsByMessageId"],
            direct["piiMappingsByMessageId"]
        );
        let before = (limit - 1) / 2;
        let after = limit - 1 - before;
        assert_eq!(before, case["before"].as_u64().unwrap() as usize);
        assert_eq!(after, case["after"].as_u64().unwrap() as usize);
        let expected = case["expectedIndices"]
            .as_array()
            .unwrap()
            .iter()
            .map(|i| input["messages"][i.as_u64().unwrap() as usize]["message_id"].clone())
            .collect::<Vec<_>>();
        let metadata = out["messageMetadata"].as_array().unwrap();
        assert_eq!(
            metadata
                .iter()
                .map(|row| row["sourceMessageId"].clone())
                .collect::<Vec<_>>(),
            expected
        );
        assert_eq!(out["anchorFound"], true);
        assert_eq!(calls.borrow()[1]["kind"], "anchor");
        assert_eq!(calls.borrow()[1]["anchorMessageId"], anchor);
        if index == 16 && limit == 20 {
            let mut plan = calls.borrow()[1].clone();
            plan["operationId"] = protocol["anchorPlan"]["operationId"].clone();
            plan["maxPacketBytes"] = protocol["anchorPlan"]["maxPacketBytes"].clone();
            assert_eq!(plan, protocol["anchorPlan"]);
        }
        let payload_plans = calls.borrow();
        let mut retained_rows = 0;
        for pair in payload_plans[1..].windows(2) {
            let prior_reply = reply(&pair[0].to_string(), &input);
            let rows = prior_reply["messages"].as_array().unwrap();
            // An empty older leg consumes no bytes. Every nonempty append pays
            // its exact serialized row bytes plus the existing-array comma.
            let consumed = serde_json::to_vec(rows).unwrap().len() - 2
                + usize::from(retained_rows > 0 && !rows.is_empty());
            assert_eq!(
                pair[1]["maxPacketBytes"].as_u64().unwrap(),
                pair[0]["maxPacketBytes"].as_u64().unwrap() - consumed as u64,
                "each next plan retains exactly the unconsumed global budget"
            );
            if rows.is_empty() { assert_eq!(consumed, 0); }
            else { assert!(consumed > 0); }
            retained_rows += rows.len();
        }
        drop(payload_plans);
        assert_eq!(
            calls
                .borrow()
                .iter()
                .map(|p| p["maxPayloadRows"].as_u64().unwrap())
                .sum::<u64>(),
            limit as u64
        );
        if limit == 1 {
            assert_eq!(calls.borrow().len(), 2);
            assert!(out["hasMoreBefore"].is_null());
            assert!(out["hasMoreAfter"].is_null());
        } else {
            assert_eq!(calls.borrow().len(), 4);
            assert_eq!(calls.borrow()[2]["maxPayloadRows"], before);
            assert_eq!(calls.borrow()[3]["maxPayloadRows"], after);
        }
        assert_eq!(client.credential_ack, 0);
        assert!(client.history.is_empty());
    }
}
#[tokio::test]
async fn explicit_old_anchor_survives_checkpoint_but_older_leg_remains_cutoff() {
    let client = client();
    let input = fixture();
    let protocol: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/browser-local-around-plan.json"
    ))
    .unwrap();
    let case = &protocol["belowCutoffCase"];
    let index = case["index"].as_u64().unwrap() as usize;
    let anchor = input["messages"][index]["message_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let calls = RefCell::new(vec![]);
    let out = client
        .browser_local_saved_chat_read_with_io_json(
            OWNER,
            CHAT,
            SavedChatReadOptions {
                limit: 11,
                anchor_message_id: Some(anchor.clone()),
                ..Default::default()
            },
            |plan| {
                calls
                    .borrow_mut()
                    .push(serde_json::from_str::<Value>(&plan).unwrap());
                std::future::ready(Ok(reply(&plan, &input).to_string()))
            },
        )
        .await
        .unwrap();
    let out: Value = serde_json::from_str(&out).unwrap();
    assert_eq!(calls.borrow().len(), 3);
    assert_eq!(out["anchorFound"], true);
    assert_eq!(out["hasMoreBefore"], false);
    assert_eq!(out["historyComplete"], false);
    assert_eq!(out["coverage"], "retained_only");

    assert_eq!(out["messageMetadata"].as_array().unwrap().len(), 6);
    assert_eq!(out["messageMetadata"][0]["sourceMessageId"], anchor);
    let expected = case["expectedIndices"]
        .as_array()
        .unwrap()
        .iter()
        .map(|i| input["messages"][i.as_u64().unwrap() as usize]["message_id"].clone())
        .collect::<Vec<_>>();
    assert_eq!(
        out["messageMetadata"]
            .as_array()
            .unwrap()
            .iter()
            .map(|r| r["sourceMessageId"].clone())
            .collect::<Vec<_>>(),
        expected
    );
    assert_eq!(out["hasMoreAfter"], case["hasMoreAfter"]);
    assert_eq!(
        calls.borrow()[2]["lower"],
        json!({"createdAt":101,"messageId":null,"open":true})
    );
    let direct = client
        .browser_local_saved_chat_read_json(
            OWNER,
            CHAT,
            SavedChatReadOptions {
                limit: 11,
                anchor_message_id: Some(anchor),
                ..Default::default()
            },
            &input.to_string(),
        )
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&direct).unwrap()["chat"],
        out["chat"]
    );
}
#[tokio::test]
async fn around_missing_or_logical_only_anchor_does_not_scan_and_cannot_claim_completeness() {
    for anchor in [
        "missing-physical".to_owned(),
        fixture()["messages"][16]["client_message_id"]
            .as_str()
            .unwrap()
            .to_owned(),
    ] {
        let client = client();
        let input = fixture();
        let calls = RefCell::new(0);
        let out = client
            .browser_local_saved_chat_read_with_io_json(
                OWNER,
                CHAT,
                SavedChatReadOptions {
                    anchor_message_id: Some(anchor),
                    ..Default::default()
                },
                |plan| {
                    *calls.borrow_mut() += 1;
                    std::future::ready(Ok(reply(&plan, &input).to_string()))
                },
            )
            .await
            .unwrap();
        let out: Value = serde_json::from_str(&out).unwrap();
        assert_eq!(*calls.borrow(), 2);
        assert_eq!(out["anchorFound"], false);
        assert!(out["chat"]["messages"].as_array().unwrap().is_empty());
        assert!(out["hasMoreBefore"].is_null());
        assert!(out["hasMoreAfter"].is_null());
        assert_eq!(out["historyComplete"], false);
    }
}
#[tokio::test]
async fn around_rejects_wrong_anchor_chat_identity_version_and_leg_scope() {
    for change in 0..6 {
        let client = client();
        let mut input = fixture();
        input["compression_checkpoints"] = json!([]);
        let anchor = input["messages"][16]["message_id"]
            .as_str()
            .unwrap()
            .to_owned();
        let out = client
            .browser_local_saved_chat_read_with_io_json(
                OWNER,
                CHAT,
                SavedChatReadOptions {
                    anchor_message_id: Some(anchor),
                    ..Default::default()
                },
                |plan| {
                    let mut out = reply(&plan, &input);
                    if out["kind"] == "anchor" {
                        match change {
                            0 => out["messages"][0]["chat_id"] = json!(OWNER),
                            1 => out["messages"][0]["message_id"] = json!("different-physical"),
                            2 => out["databaseVersion"] = json!(32),
                            3 => out["extra"] = json!(true),
                            _ => {}
                        }
                    }
                    if out["kind"] == "messages" {
                        match change {
                            4 => out["messages"][0] = input["messages"][16].clone(),
                            5 => out["operationId"] = json!(CHAT),
                            _ => {}
                        }
                    }
                    std::future::ready(Ok(out.to_string()))
                },
            )
            .await;
        assert!(out.is_err());
        assert_eq!(client.credential_ack, 0);
        assert!(client.history.is_empty());
    }
}
#[tokio::test]
async fn around_cancellation_key_revocation_denial_at_every_io_phase_blocks_output() {
    for phase in 1..=3 {
        for change in 0..3 {
            let client = client();
            let mut input = fixture();
            input["compression_checkpoints"] = json!([]);
            let anchor = input["messages"][16]["message_id"]
                .as_str()
                .unwrap()
                .to_owned();
            let entered = Arc::new(Notify::new());
            let release = Arc::new(Notify::new());
            let calls = RefCell::new(0);
            let mut future = Box::pin(client.browser_local_saved_chat_read_with_io_json(
                OWNER,
                CHAT,
                SavedChatReadOptions {
                    anchor_message_id: Some(anchor),
                    ..Default::default()
                },
                |plan| {
                    let result = reply(&plan, &input).to_string();
                    let current = *calls.borrow();
                    *calls.borrow_mut() += 1;
                    let entered = entered.clone();
                    let release = release.clone();
                    async move {
                        if current == phase {
                            entered.notify_one();
                            release.notified().await;
                        }
                        Ok(result)
                    }
                },
            ));
            tokio::select! {biased;result=&mut future=>{let _=result;panic!("must await selected around phase");},_=entered.notified()=>{}}
            match change {
                0 => client.operation_cancel.cancel(),
                1 => client.master_capability().unwrap().invalidate(),
                _ => client
                    .task_watch_authority
                    .deny_cached_chat(Some(CHAT))
                    .unwrap(),
            }
            release.notify_one();
            assert!(future.await.is_err());
            assert_eq!(client.credential_ack, 0);
            assert!(client.history.is_empty());
        }
    }
}

#[tokio::test]
async fn around_refuses_oversized_anchor_packet_before_publication() {
    let client = client();
    let input = fixture();
    let anchor = input["messages"][16]["message_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let out = client
        .browser_local_saved_chat_read_with_io_json(
            OWNER,
            CHAT,
            SavedChatReadOptions {
                anchor_message_id: Some(anchor),
                ..Default::default()
            },
            |plan| {
                let request: Value = serde_json::from_str(&plan).unwrap();
                let mut out = reply(&plan, &input);
                if request["kind"] == "anchor" {
                    out["messages"][0]["rich_extension"] =
                        json!("x".repeat(request["maxPacketBytes"].as_u64().unwrap() as usize));
                }
                std::future::ready(Ok(out.to_string()))
            },
        )
        .await;
    assert!(matches!(out, Err(Error::Protocol)));
    assert_eq!(client.credential_ack, 0);
    assert!(client.history.is_empty());
}

#[path="browser_local_checkpoint_tests.rs"]
mod checkpoint_tests;


#[test]
fn actual_local_range_and_sentinel_comparison_use_idb_utf16_not_server_c_order() {
    let low=Bound{created_at:1,message_id:Some("\u{10000}".into()),open:true};
    let high=Bound{created_at:1,message_id:Some("\u{e000}".into()),open:false};
    assert!(in_range((1,"\u{e000}"),Some(&low),Some(&high)));
    assert!(!in_range((1,"\u{10000}"),Some(&low),Some(&high)));
    assert!(!in_range((1,"\u{10000}"),Some(&Bound{created_at:1,message_id:Some("\u{e000}".into()),open:true}),None));
}
#[tokio::test]
async fn actual_callback_coordinator_keeps_unicode_physical_aliases_and_paging_order() {
    let client=client();let mut input=fixture();input["compression_checkpoints"]=json!([]);
    let source=input["messages"][0].clone();
    input["messages"]=json!(["\u{10000}","\u{e000}"].iter().map(|id|{let mut r=source.clone();r["message_id"]=json!(id);r["client_message_id"]=json!(format!("logical {id}\n"));r["created_at"]=json!(1);r}).collect::<Vec<_>>());
    let selector=MessageWindowOptions{direction:MessageWindowDirection::After,cursor:Some(crate::client::message_window::MessageWindowCursor{chat_id:CHAT.into(),scope:client.local_cached_scope().unwrap(),created_at:1,message_id:"\u{10000}".into()}),respect_compression_boundary:false,..Default::default()};
    let encoded=client.browser_local_saved_chat_read_with_io_json(OWNER,CHAT,SavedChatReadOptions{after:selector.cursor,respect_compression_boundary:false,..Default::default()},|plan|{let result=reply(&plan,&input);async move{Ok(result.to_string())}}).await.unwrap();
    let output:Value=serde_json::from_str(&encoded).unwrap();assert_eq!(output["chat"]["messages"].as_array().unwrap().len(),1);
    assert_eq!(output["startCursor"]["messageId"],"\u{e000}");assert_eq!(output["messageMetadata"][0]["storageId"],source["id"]);
    assert_eq!(output["chat"]["messages"][0]["id"],"logical \u{e000}\n");assert_eq!(output["historyComplete"],false);
}


fn budget_fixture()->Value {
    serde_json::from_str(include_str!("../../tests/fixtures/browser-local-plan-budget.json")).unwrap()
}
fn budget_plan(id:&str)->Plan<'_> {
    Plan{version:1,kind:"anchor",operation_id:OWNER,owner:OWNER,chat_id:CHAT,
        max_packet_bytes:MAX_PACKET_BYTES,max_checkpoint_rows:0,max_payload_rows:1,
        lower:None,upper:None,direction:"next",anchor_message_id:Some(id)}
}
fn sized_plan_id(target:usize)->String {
    let mut id=budget_fixture()["prefix"].as_str().unwrap().to_owned();
    let base=serde_json::to_vec(&budget_plan(&id)).unwrap().len();
    let space=target.checked_sub(base).unwrap();id.push_str(&"\u{1}".repeat(space/6));id.push_str(&"x".repeat(space%6));
    assert_eq!(serde_json::to_vec(&budget_plan(&id)).unwrap().len(),target);id
}
#[test]
fn local_plan_budget_derives_from_the_unchanged_complete_callback_envelope() {
    let fixture=budget_fixture();assert_eq!(MAX_PACKET_BYTES,fixture["maxEnvelopeBytes"].as_u64().unwrap()as usize);
    assert_eq!(LOCAL_JSON_FRAME_RESERVE_BYTES,fixture["existingJsonFrameReserveBytes"].as_u64().unwrap()as usize);
    let frame=json!({"version":1,"id":9_007_199_254_740_991_u64,"effectId":4,"localReadEffect":null});
    assert_eq!(serde_json::to_vec(&frame).unwrap().len()-4,MAX_EFFECT_ENVELOPE_FRAMING_BYTES);
    assert_eq!(MAX_PLAN_BYTES,fixture["maxPlanBytes"].as_u64().unwrap()as usize);
    let mut id=sized_plan_id(MAX_PLAN_BYTES);assert_eq!(local_plan_bytes(&budget_plan(&id)).unwrap(),MAX_PLAN_BYTES);
    assert_eq!(MAX_PLAN_BYTES+MAX_EFFECT_ENVELOPE_FRAMING_BYTES+LOCAL_JSON_FRAME_RESERVE_BYTES,MAX_PACKET_BYTES);
    id.push('x');assert!(matches!(local_plan_bytes(&budget_plan(&id)),Err(Error::Protocol)));
}
#[test]
fn local_plan_control_unicode_and_quote_escapes_count_actual_serialized_bytes() {
    for value in budget_fixture()["escapingCases"].as_array().unwrap() {
        let id=value.as_str().unwrap();let plan=budget_plan(id);let encoded=serde_json::to_string(&plan).unwrap();
        assert!(encoded.len()>4096);assert_eq!(local_plan_bytes(&plan).unwrap(),encoded.len());
        let parsed:Value=serde_json::from_str(&encoded).unwrap();assert_eq!(parsed["anchorMessageId"],id);
    }
}
#[tokio::test]
async fn actual_rust_producer_refuses_plus1_before_platform_io_and_admits_exact_budget() {
    use std::cell::Cell;
    let client = client();
    let scope = client.browser_local_read_scope(OWNER, CHAT).unwrap();
    let before = client.ciphertext_snapshot();
    for over in [false, true] {
        let mut id = sized_plan_id(MAX_PLAN_BYTES);
        if over {
            id.push('x');
        }
        let calls = Cell::new(0);
        let mut io = |encoded: String| {
            calls.set(calls.get() + 1);
            assert_eq!(encoded.len(), MAX_PLAN_BYTES);
            std::future::ready(Err::<String, _>(Error::Offline))
        };
        let result = client
            .local_cursor_io(
                OWNER,
                CHAT,
                &scope,
                crate::client::local_cached_read::CachedViewMode::LocalProfile,
                &budget_plan(&id),
                &mut io,
            )
            .await;
        if over {
            assert!(matches!(result, Err(Error::Protocol)));
            assert_eq!(calls.get(), 0);
        } else {
            assert!(matches!(result, Err(Error::Offline)));
            assert_eq!(calls.get(), 1);
        }
        assert_eq!(client.ciphertext_snapshot(), before);
        assert_eq!(client.credential_ack, 0);
        assert!(client.history.is_empty());
    }
}
async fn cached_view_read(
    client: &Client,
    input: &Value,
    online: bool,
) -> Result<zeroize::Zeroizing<String>> {
    let io = |plan: String| std::future::ready(Ok(reply(&plan, input).to_string()));
    if online {
        client
            .browser_online_cached_saved_chat_read_with_io_json(
                OWNER,
                CHAT,
                SavedChatReadOptions::default(),
                io,
            )
            .await
    } else {
        client
            .browser_local_saved_chat_read_with_io_json(
                OWNER,
                CHAT,
                SavedChatReadOptions::default(),
                io,
            )
            .await
    }
}
#[tokio::test]
async fn online_cached_view_reads_retained_rows_only_in_its_own_admitted_mode() {
    let input = fixture();
    let mut online = client();
    online.browser_local_read_only = false;
    let snapshot = online.ciphertext_snapshot();
    let offline_view = cached_view_read(&client(), &input, false).await.unwrap();
    let online_view = cached_view_read(&online, &input, true).await.unwrap();
    let offline_view: Value = serde_json::from_str(&offline_view).unwrap();
    let online_view: Value = serde_json::from_str(&online_view).unwrap();
    // Same retained rows and decryption; provenance stays local/incomplete/not fresh.
    assert_eq!(online_view["chat"], offline_view["chat"]);
    assert_eq!(
        online_view["messageMetadata"],
        offline_view["messageMetadata"]
    );
    assert_eq!(online_view["source"], "local_profile");
    assert_eq!(online_view["fresh"], false);
    assert_eq!(online_view["historyComplete"], false);
    assert_eq!(online.ciphertext_snapshot(), snapshot);
    assert_eq!(online.credential_ack, 0);
    // Each entry refuses the other admitted mode.
    assert!(cached_view_read(&online, &input, false).await.is_err());
    assert!(cached_view_read(&client(), &input, true).await.is_err());
    let mut no_transport = client();
    no_transport.browser_local_read_only = false;
    no_transport.browser_transport = false;
    assert!(cached_view_read(&no_transport, &input, true).await.is_err());
}
#[test]
fn online_cached_view_scope_rejects_mode_owner_and_generation_replacement() {
    for change in 0..4 {
        let mut client = client();
        client.browser_local_read_only = false;
        let view = crate::client::local_cached_read::CachedViewMode::OnlineCache;
        let scope = client.browser_cached_view_scope(OWNER, CHAT, view).unwrap();
        let cached = client.local_cached_scope_for(view).unwrap();
        match change {
            0 => client.browser_local_read_only = true,
            1 => client.user = json!({"id":CHAT}),
            2 => client.generation += 1,
            _ => client.browser_authority.as_mut().unwrap().principal = CHAT.into(),
        }
        assert!(
            scope.check_chat(&client, CHAT).is_err()
                || client.browser_cached_view_scope(OWNER, CHAT, view).is_err()
                || client.local_cached_scope_for(view).ok() != Some(cached.clone())
        );
    }
}
