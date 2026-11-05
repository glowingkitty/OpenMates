//! TypeScript-generated vectors (tests/crypto_fixtures/ts_embed_writes/generate.cjs)
//! proving byte-identical embed writes and that every TS ciphertext decrypts.
use super::history::{self, RestoreRequest};
use super::keys::{self, NonceSource};
use super::payload::{self, ProcessingEmbedUpdate, StreamedEmbedData, WriteKeys};
use super::status::{self, EmbedStatus};
use super::*;
use crate::crypto::{Key, master::MasterCapability};
use crate::error::{Error, Result};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::collections::VecDeque;

fn fixture() -> Value {
    serde_json::from_str(include_str!("../../tests/crypto_fixtures/ts_embed_writes.json")).unwrap()
}
fn key(value: &Value) -> Key {
    keys::key_from(&STANDARD.decode(value.as_str().unwrap()).unwrap()).unwrap()
}
fn master(f: &Value) -> MasterCapability {
    MasterCapability::from_browser_raw(key(&f["keys"]["master_b64"]))
}
const NOW_SECONDS: i64 = 1_790_000_000;
const NOW_MS: i64 = NOW_SECONDS * 1000;

/// Replays the IVs the TypeScript writer drew, in write order.
struct Replay(VecDeque<[u8; 12]>);
impl Replay {
    fn new<'a>(ivs: impl IntoIterator<Item = &'a Value>) -> Self {
        Self(
            ivs.into_iter()
                .filter_map(Value::as_str)
                .map(|iv| STANDARD.decode(iv).unwrap().try_into().unwrap())
                .collect(),
        )
    }
    fn assert_drained(&self) {
        assert!(self.0.is_empty(), "unused replay nonces");
    }
}
impl NonceSource for Replay {
    fn next_nonce(&mut self) -> Result<[u8; 12]> {
        self.0.pop_front().ok_or(Error::Crypto)
    }
}

#[test]
fn hkdf_derivation_matches_typescript() {
    let f = fixture();
    for case in f["derivation"].as_array().unwrap() {
        let derived = keys::derive_embed_key(&key(&case["chat_key_b64"]), case["embed_id"].as_str().unwrap()).unwrap();
        assert_eq!(STANDARD.encode(*derived), case["embed_key_b64"].as_str().unwrap());
    }
}

#[test]
fn typescript_field_ciphertexts_decrypt_and_reencrypt_identically() {
    let f = fixture();
    for case in f["fields"].as_array().unwrap() {
        let k = key(&case["key_b64"]);
        let ct = case["ciphertext"].as_str().unwrap();
        let aad = case["aad"].as_str();
        let plain = case["plaintext"].as_str().unwrap();
        assert_eq!(keys::decrypt_text(ct, &k, aad).unwrap().as_str(), plain, "{}", case["label"]);
        let iv = &STANDARD.decode(ct).unwrap()[..12];
        let mut replay = Replay::new([&json!(STANDARD.encode(iv))]);
        assert_eq!(keys::encrypt_text(plain, &k, aad, &mut replay).unwrap(), ct);
        if aad.is_some() {
            assert!(keys::decrypt_text(ct, &k, None).is_err(), "AAD must bind");
        }
    }
}

#[tokio::test]
async fn typescript_key_wrappers_unwrap_and_rust_wrappers_round_trip() {
    let f = fixture();
    let w = &f["wrappers"];
    let embed_key = key(&w["embed_key_b64"]);
    let chat_key = key(&f["keys"]["chat_key_b64"]);
    let other = key(&f["keys"]["other_chat_key_b64"]);
    let master = master(&f);
    let ts_master = keys::unwrap_key_with_master(w["master"].as_str().unwrap(), &master).await.unwrap();
    assert_eq!(*ts_master, *embed_key);
    assert_eq!(*keys::unwrap_key(w["chat"].as_str().unwrap(), &chat_key).unwrap(), *embed_key);
    assert!(keys::unwrap_key(w["chat"].as_str().unwrap(), &other).is_err());
    assert_eq!(*keys::unwrap_key(w["child_by_parent"].as_str().unwrap(), &embed_key).unwrap(), *key(&w["child_key_b64"]));
    let chat_from_master = keys::unwrap_key_with_master(w["encrypted_chat_key"].as_str().unwrap(), &master).await.unwrap();
    assert_eq!(*chat_from_master, *chat_key);
    // Rust master wrapper uses the deployed IV||ct||tag layout the TS reader expects.
    let rust_wrap = keys::wrap_key_with_master(&embed_key, &master).await.unwrap();
    let raw = STANDARD.decode(&rust_wrap).unwrap();
    assert_eq!(raw.len(), 12 + 32 + 16);
    let master_key = key(&f["keys"]["master_b64"]);
    let opened = crate::crypto::decrypt_aead(&raw[12..], &master_key, &raw[..12], &[]).unwrap();
    assert_eq!(opened.as_slice(), embed_key.as_slice());
}

fn finalized_case(f: &Value, case: &Value) -> payload::PreparedEmbedWrite {
    let input = case["input"].clone();
    let data = StreamedEmbedData::from_value(input).unwrap();
    let embed_key = key(&case["embed_key_b64"]);
    let chat_key = key(&f["keys"]["chat_key_b64"]);
    let expected = &case["expected"];
    let master_wrapper = expected["local_key_wrappers"]
        .as_array()
        .unwrap()
        .iter()
        .find(|row| row["key_type"] == "master")
        .map(|row| row["encrypted_embed_key"].as_str().unwrap().to_owned());
    let ivs = &case["ivs"];
    let mut replay = Replay::new([&ivs["content"], &ivs["type"], &ivs["text_preview"], &ivs["chat_wrapper"]]);
    let child = data.parent_embed_id().is_some();
    let prepared = payload::build_stream_completion(
        &data,
        WriteKeys { embed_key: &embed_key, chat_key: (!child).then_some(&*chat_key), master_wrapper },
        NOW_MS,
        &mut replay,
    )
    .unwrap();
    replay.assert_drained();
    prepared
}

#[test]
fn finalized_stream_writes_match_typescript_byte_for_byte() {
    let f = fixture();
    for case in f["finalized"].as_array().unwrap() {
        let label = case["label"].as_str().unwrap();
        let prepared = finalized_case(&f, case);
        let actual = serde_json::to_value(&prepared).unwrap();
        let expected = &case["expected"];
        for field in [
            "local_entry",
            "local_key_wrappers",
            "store_payload",
            "server_keys",
            "key_cache_embed_ids",
            "embed_ref_registration",
            "child_ref_embed_ids",
            "sealed_history",
        ] {
            assert_eq!(actual[field], expected[field], "{label}: {field}");
        }
        // Existing readers: every written ciphertext decrypts with the TS key.
        let k = key(&case["embed_key_b64"]);
        let content = keys::decrypt_text(actual["local_entry"]["encrypted_content"].as_str().unwrap(), &k, None).unwrap();
        assert_eq!(content.as_str(), case["input"]["content"].as_str().unwrap());
    }
}

#[tokio::test]
async fn session_plans_finalized_writes_with_the_typescript_key_policy() {
    let f = fixture();
    let master = master(&f);
    let mut session = EmbedWriteSession::new(master.clone());
    let chat_id = f["ids"]["chat_id"].as_str().unwrap();
    let adoption = session.chat_key_adoption(chat_id, f["wrappers"]["encrypted_chat_key"].as_str().unwrap()).unwrap();
    let child_case = &f["finalized"][2];
    let child = StreamedEmbedData::from_value(child_case["input"].clone()).unwrap();
    assert!(matches!(session.plan_stream_completion(child), Err(Error::Unavailable { code: "embed_parent_key_pending", .. })));
    let parent_case = &f["finalized"][0];
    let parent = StreamedEmbedData::from_value(parent_case["input"].clone()).unwrap();
    assert!(matches!(session.plan_stream_completion(parent), Err(Error::Unavailable { code: "embed_chat_key_unavailable", .. })));
    session.install(adoption.resolve().await.unwrap());

    let parent = StreamedEmbedData::from_value(parent_case["input"].clone()).unwrap();
    let ivs = &parent_case["ivs"];
    let mut replay = Replay::new([&ivs["content"], &ivs["type"], &ivs["text_preview"], &ivs["chat_wrapper"]]);
    let prepared = session.plan_stream_completion(parent).unwrap().finish_with(NOW_MS, &mut replay).await.unwrap();
    let expected = &parent_case["expected"];
    assert_eq!(prepared.local_entry, expected["local_entry"]);
    assert_eq!(prepared.local_key_wrappers[1], expected["local_key_wrappers"][1]);
    let rust_master = prepared.local_key_wrappers[0]["encrypted_embed_key"].as_str().unwrap();
    let unwrapped = keys::unwrap_key_with_master(rust_master, &master).await.unwrap();
    assert_eq!(*unwrapped, *key(&parent_case["embed_key_b64"]));
    for id in expected["key_cache_embed_ids"].as_array().unwrap() {
        assert!(session.has_embed_key(id.as_str().unwrap()));
    }
    // The child now inherits the parent key without any raw-key exchange.
    let child = StreamedEmbedData::from_value(child_case["input"].clone()).unwrap();
    let civs = &child_case["ivs"];
    let mut replay = Replay::new([&civs["content"], &civs["type"]]);
    let child_prepared = session.plan_stream_completion(child).unwrap().finish_with(NOW_MS, &mut replay).await.unwrap();
    assert_eq!(child_prepared.local_entry, child_case["expected"]["local_entry"]);
    assert!(child_prepared.server_keys.is_none());

    // Wrapper rows re-adopt keys in a fresh session (reload path).
    let mut reloaded = EmbedWriteSession::new(master.clone());
    let embed_id = parent_case["input"]["embed_id"].as_str().unwrap();
    let row = &prepared.local_key_wrappers[0];
    let adopted = reloaded.embed_wrapper_adoption(embed_id, chat_id, row).unwrap().resolve().await.unwrap();
    reloaded.install(adopted);
    assert!(reloaded.has_embed_key(embed_id));
    assert!(reloaded.embed_wrapper_adoption("other-embed", chat_id, row).is_err());
    reloaded.forget_chat(chat_id);
    assert!(!reloaded.has_embed_key(embed_id));
}

#[test]
fn processing_update_matches_typescript() {
    let f = fixture();
    let case = &f["processing_update"];
    let input = &case["input"];
    let update = ProcessingEmbedUpdate {
        existing: input["existing"].as_object().unwrap().clone(),
        chat_id: input["chat_id"].as_str().unwrap().to_owned(),
        user_id: input["user_id"].as_str().map(str::to_owned),
        message_id: input["message_id"].as_str().map(str::to_owned),
        normalized_type: input["existing"]["type"].as_str().unwrap().to_owned(),
    };
    let expected = &case["expected"];
    let embed_key = key(&case["embed_key_b64"]);
    let chat_key = key(&f["keys"]["chat_key_b64"]);
    let ivs = &case["ivs"];
    let mut replay = Replay::new([&ivs["content"], &ivs["type"], &ivs["chat_wrapper"]]);
    let master_wrapper = Some(expected["local_key_wrappers"][0]["encrypted_embed_key"].as_str().unwrap().to_owned());
    let prepared = payload::build_processing_update(
        &update,
        WriteKeys { embed_key: &embed_key, chat_key: Some(&chat_key), master_wrapper },
        NOW_MS,
        &mut replay,
    )
    .unwrap();
    replay.assert_drained();
    let actual = serde_json::to_value(&prepared).unwrap();
    for field in ["local_entry", "local_key_wrappers", "store_payload", "server_keys", "key_cache_embed_ids"] {
        assert_eq!(actual[field], expected[field], "{field}");
    }
}

#[test]
fn processing_update_refuses_a_child_without_its_inherited_key() {
    let f = fixture();
    let mut session = EmbedWriteSession::new(master(&f));
    let mut existing = f["processing_update"]["input"]["existing"].as_object().unwrap().clone();
    existing.insert("parent_embed_id".into(), json!("parent"));
    let update = ProcessingEmbedUpdate {
        existing,
        chat_id: "chat".into(),
        user_id: None,
        message_id: None,
        normalized_type: "sheet".into(),
    };
    assert!(matches!(session.plan_processing_update(update), Err(Error::Unavailable { code: "embed_parent_key_pending", .. })));
}

#[test]
fn streamed_history_rows_match_typescript_and_reconstruct() {
    let f = fixture();
    let h = &f["history"];
    let k = key(&h["embed_key_b64"]);
    let hashed_user = h["hashed_user_id"].as_str().unwrap();
    let mut local_rows = Vec::new();
    for (input, expected) in h["input"].as_array().unwrap().iter().zip(h["rows"].as_array().unwrap()) {
        let mut replay = Replay::new([&expected["iv"]]);
        let row = history::encrypt_streamed_row(input, &k, NOW_SECONDS, &mut replay).unwrap();
        match row {
            None => assert!(expected.is_null()),
            Some(row) => {
                replay.assert_drained();
                assert_eq!(serde_json::to_value(&row).unwrap(), expected["local_row"]);
                assert_eq!(row.server_payload(hashed_user), expected["server_payload"]);
                local_rows.push(expected["local_row"].clone());
            }
        }
    }
    assert_eq!(history::reconstruct(&local_rows[..2], &k).unwrap().as_str(), h["reconstructed_v2"].as_str().unwrap());
    assert_eq!(history::reconstruct(&local_rows, &k).unwrap().as_str(), h["reconstructed_v3"].as_str().unwrap());
}

#[test]
fn sealed_history_reuses_matching_rows_and_rejects_divergence() {
    let f = fixture();
    let h = &f["history"];
    let k = key(&h["embed_key_b64"]);
    let inputs = h["input"].as_array().unwrap();
    let embed_id = inputs[0]["embed_id"].as_str().unwrap();
    history::validate_sealed_rows(&inputs[..3], embed_id, 3.0).unwrap();
    assert!(history::validate_sealed_rows(&inputs[..3], embed_id, 2.0).is_err());
    assert!(history::validate_sealed_rows(&[inputs[0].clone(), inputs[0].clone()], embed_id, 3.0).is_err());
    let existing: history::EncryptedDiffRow = serde_json::from_value(h["rows"][0]["local_row"].clone()).unwrap();
    let mut none = Replay::new([]);
    let reused = history::reconcile_sealed_row(&inputs[0], Some(&existing), &k, NOW_SECONDS, &mut none).unwrap().unwrap();
    assert_eq!(reused.encrypted_snapshot, existing.encrypted_snapshot);
    let mut diverged = inputs[0].clone();
    diverged["snapshot"] = json!("changed");
    assert!(matches!(history::reconcile_sealed_row(&diverged, Some(&existing), &k, NOW_SECONDS, &mut none), Err(Error::Conflict)));
}

#[test]
fn canonical_rows_are_adopted_only_when_plaintext_matches() {
    let f = fixture();
    let h = &f["history"];
    let k = key(&h["embed_key_b64"]);
    let input = &h["input"][1];
    let canonical = &h["rows"][1]["local_row"];
    let embed_id = input["embed_id"].as_str().unwrap();
    let page = json!({ "embed_id": embed_id, "version_number": 2, "rows": [h["rows"][0]["local_row"], canonical] });
    let adopted = history::adopt_canonical_row(&page, input, &k, NOW_SECONDS).unwrap();
    assert_eq!(serde_json::to_value(&adopted).unwrap(), *canonical);
    let wrong = json!({ "embed_id": embed_id, "version_number": 2, "rows": [h["rows"][0]["local_row"]] });
    assert!(matches!(history::adopt_canonical_row(&wrong, input, &k, NOW_SECONDS), Err(Error::Conflict)));
    assert_eq!(history::classify_canonical_read(404, None, 2).unwrap(), CanonicalRead::Absent);
    assert_eq!(
        history::classify_canonical_read(409, Some(&json!({"detail": "snapshot_required"})), 1).unwrap(),
        CanonicalRead::Absent
    );
    assert!(history::classify_canonical_read(409, Some(&json!({"detail": "snapshot_required"})), 2).is_err());
    let rows: Vec<Value> = h["input"].as_array().unwrap()[..3].to_vec();
    let head_rows: Vec<Value> = h["rows"].as_array().unwrap()[..3].iter().map(|r| r["local_row"].clone()).collect();
    let head = json!({ "embed_id": embed_id, "version_number": 3, "rows": head_rows });
    assert_eq!(history::verify_canonical_head(&head, &rows, embed_id, &k, NOW_SECONDS).unwrap().len(), 3);
}

#[test]
fn unified_diffs_and_restores_match_typescript() {
    let f = fixture();
    for case in f["unified_diffs"].as_array().unwrap() {
        let patch = build_unified_diff(
            case["current"].as_str().unwrap(),
            case["restored"].as_str().unwrap(),
            case["current_version"].as_i64().unwrap(),
            case["new_version"].as_i64().unwrap(),
        );
        assert_eq!(patch, case["patch"].as_str().unwrap(), "{}", case["label"]);
    }
    let k = key(&f["history"]["embed_key_b64"]);
    for case in f["restore"].as_array().unwrap() {
        let mut replay = Replay::new([&case["ivs"]["patch"], &case["ivs"]["snapshot"]]);
        let current_version = case["current_version"].as_i64().unwrap();
        let request = RestoreRequest {
            embed_id: case["embed_id"].as_str().unwrap(),
            selected_version: 1,
            current_version,
            current_content: case["current_content"].as_str().unwrap(),
            restored_content: case["restored_content"].as_str().unwrap(),
        };
        let plan = history::prepare_restore(&request, &k, NOW_SECONDS, &mut replay).unwrap();
        replay.assert_drained();
        assert_eq!(serde_json::to_value(&plan).unwrap(), case["expected"], "{}", case["label"]);
    }
    let same = RestoreRequest { embed_id: "e", selected_version: 2, current_version: 2, current_content: "", restored_content: "" };
    assert!(history::prepare_restore(&same, &k, NOW_SECONDS, &mut keys::OsNonces).is_err());
    assert!(history::should_publish_client_snapshot(33, Some(false)));
    assert!(!history::should_publish_client_snapshot(32, Some(false)));
    assert!(!history::should_publish_client_snapshot(33, None));
}

#[test]
fn status_machine_matches_typescript() {
    let f = fixture();
    for case in f["status"]["transitions"].as_array().unwrap() {
        let (from, to) = (case[0].as_str().unwrap(), case[1].as_str().unwrap());
        assert_eq!(status::transition_allowed(from, to), case[2].as_bool().unwrap(), "{from}->{to}");
    }
    for case in f["status"]["normalize"].as_array().unwrap() {
        assert_eq!(EmbedStatus::normalize(&case[0]).as_str(), case[1].as_str().unwrap(), "{}", case[0]);
    }
    for case in f["status"]["terminal"].as_array().unwrap() {
        assert_eq!(status::is_terminal(case[0].as_str().unwrap()), case[1].as_bool().unwrap());
    }
}

#[test]
fn embed_ref_index_matches_typescript() {
    let f = fixture();
    let mut index = EmbedRefIndex::new();
    for op in f["ref_index"].as_array().unwrap() {
        match op["op"].as_str().unwrap() {
            "register" => {
                let entry: EmbedRefIndexEntry = serde_json::from_value(op["entry"].clone()).unwrap();
                assert_eq!(index.register(op["ref"].as_str().unwrap(), entry), op["changed"].as_bool().unwrap(), "{op}");
            }
            "resolve" => {
                let resolved = index.resolve(op["ref"].as_str().unwrap());
                assert_eq!(serde_json::to_value(resolved).unwrap(), op["result"], "{op}");
            }
            _ => index.clear(),
        }
    }
}

#[tokio::test]
async fn coordinator_serializes_writers_and_tracks_acknowledgements() {
    let coordinator = std::sync::Arc::new(EmbedWriteCoordinator::new());
    let lease = coordinator.lease("e1").await.unwrap();
    let waiter = {
        let coordinator = coordinator.clone();
        tokio::spawn(async move { coordinator.lease("e1").await.map(|lease| lease.embed_id().to_owned()) })
    };
    tokio::task::yield_now().await;
    assert!(!waiter.is_finished());
    coordinator.mark_acknowledged(&lease, "chat", 3).unwrap();
    coordinator.mark_acknowledged(&lease, "chat", 2).unwrap();
    assert!(coordinator.has_acknowledged(&lease, "chat", 3).unwrap());
    assert!(!coordinator.has_acknowledged(&lease, "chat", 4).unwrap());
    assert!(!coordinator.has_acknowledged(&lease, "other", 1).unwrap());
    drop(lease);
    assert_eq!(waiter.await.unwrap().unwrap(), "e1");
    assert!(coordinator.lease("").await.is_err());
}

#[test]
fn unix_seconds_normalization_matches_typescript() {
    assert_eq!(normalize_to_unix_seconds(Some(&json!(1_789_999_000_123i64)), 7), 1_789_999_000);
    assert_eq!(normalize_to_unix_seconds(Some(&json!(1_789_000_000.9)), 7), 1_789_000_000);
    assert_eq!(normalize_to_unix_seconds(Some(&json!(0)), 7), 7);
    assert_eq!(normalize_to_unix_seconds(Some(&json!("1789000000")), 7), 7);
    assert_eq!(normalize_to_unix_seconds(None, 7), 7);
}
