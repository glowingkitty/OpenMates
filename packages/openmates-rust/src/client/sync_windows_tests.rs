//! Guard tests for the real server-shaped shared encrypted phase1b fixture.
//! No account, profile, provider or inference is contacted by these tests.
//! Policy fixtures model an already authenticated explicit SDK principal only.
//! Actual direct Rust/npm/Python wire admission is separately exercised by the
//! existing monitor conformance operation and its exact durable checkpoint.
//! Partial windows never become complete history, ACKs or canonical proof.
use super::*;
use crate::session::Session;
use zeroize::Zeroizing;
const CHAT: &str = "22222222-2222-4222-8222-222222222222";
fn shared() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/fixtures/phase1b-ciphertext-window.json"
    ))
    .unwrap()
}
fn fixture() -> (Client, Value, Value) {
    let vector = shared();
    let session = Session {
        api_url: "https://phase1b.example.invalid".into(),
        session_id: "synthetic-session".into(),
        cookies: BTreeMap::from([("auth_refresh_token".into(), "synthetic-cookie".into())]),
        ws_token: None,
        master_key: Zeroizing::new(std::array::from_fn(|n| n as u8)),
        hashed_email: "synthetic-owner-hash".into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    let mut client = Client::new(&session.api_url, Some(session.clone())).unwrap();
    client.user = json!({"id":"11111111-1111-4111-8111-111111111111"});
    client.credentials_changed();
    let metadata = vector["metadata"].clone();
    let mut payload = vector["payload"].clone();
    // Mutation guards use object rows; the shared wire fixture remains the
    // backend's actual serialized-JSON string form and is tested separately.
    for row in payload["chats"][0]["messages"].as_array_mut().unwrap() {
        if let Some(raw) = row.as_str() {
            *row = serde_json::from_str(raw).unwrap();
        }
    }
    (client, metadata, payload)
}
fn stage(
    client: &Client,
    metadata: Value,
    payload: &Value,
) -> Result<BTreeMap<String, CiphertextMessageWindow>> {
    let mut batch = Phase1Windows::default();
    batch.metadata(&json!({"team_id":null,"context_epoch":0,"chat_details":metadata,"recent_chat_metadata":[]}),None)?;
    batch.content(payload, None)?;
    let mut chats = BTreeMap::new();
    batch.merge_metadata(&mut chats);
    client.finish_sync_windows(batch, &chats, &[])
}
fn admitted() -> Client {
    let (mut client, metadata, payload) = fixture();
    let windows = stage(&client, metadata.clone(), &payload).unwrap();
    client.chats.insert(CHAT.into(), metadata);
    client.sync_message_windows = windows;
    client
}
// contract-test: supporting surface=sdks.rust assertions=sync.startup.bounded-phases,sync.access.first-party-authenticated,sync.client.shared-rust-policy
#[test]
fn server_shaped_window_is_ciphertext_only_and_complete_history_stays_separate() {
    let (mut client, metadata, mut payload) = fixture();
    payload["chats"][0]["messages"][0]["content"] = json!("MUST_NOT_PERSIST_CLEAR_EXTENSION");
    let before_history = client.history.clone();
    let revision = client.credential_revision;
    client.sync_message_windows = stage(&client, metadata.clone(), &payload).unwrap();
    client.chats.insert(CHAT.into(), metadata);
    let snapshot = client.ciphertext_snapshot();
    let window = &snapshot[SNAPSHOT_FIELD][CHAT];
    assert_eq!(window["messages"].as_array().unwrap().len(), 2);
    assert_eq!(window["server_message_count"], 5);
    assert_eq!(window["has_more_before"], true);
    assert!(
        !snapshot
            .to_string()
            .contains("MUST_NOT_PERSIST_CLEAR_EXTENSION")
    );
    assert!(window["messages"][0]["encrypted_content"].is_string());
    assert_eq!(client.history, before_history);
    assert!(!client.history.contains_key(CHAT));
    assert_eq!(client.credential_revision, revision);
    assert!(client.credential_ack < revision);
    assert!(snapshot.get("chat_list_freshness").is_none());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases
#[test]
fn cached_window_uses_existing_lazy_decoder_and_remains_read_only_partial() {
    let mut client = admitted();
    client
        .acknowledge_credentials(client.credential_revision)
        .unwrap();
    let before = client.ciphertext_snapshot();
    let views = client
        .stage_cached_chat_views(None, CancellationToken::new())
        .unwrap();
    let window = views
        .publish(CHAT, CancellationToken::new())
        .unwrap()
        .unwrap()
        .into_window()
        .unwrap();
    assert_eq!(window.chat.messages.len(), 2);
    assert!(!window.chat.messages[0].content.is_empty());
    assert!(window.cached && window.refreshing && !window.history_complete);
    assert_eq!(window.has_more_before, Some(true));
    assert_eq!(client.ciphertext_snapshot(), before);
    assert!(!client.history.contains_key(CHAT));
    assert!(
        client
            .try_cached_default_chat_list(false)
            .unwrap()
            .is_none()
    );
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases
#[test]
fn malformed_context_cursor_duplicate_order_and_bounds_refuse_atomically() {
    for change in [
        "epoch",
        "team",
        "chat",
        "cursor",
        "duplicate",
        "order",
        "rows",
        "parents",
    ] {
        let (client, metadata, mut payload) = fixture();
        let before = client.ciphertext_snapshot();
        match change {
            "epoch" => payload["context_epoch"] = json!(1),
            "team" => payload["team_id"] = json!("33333333-3333-4333-8333-333333333333"),
            "chat" => {
                payload["chats"][0]["messages"][0]["chat_id"] =
                    json!("33333333-3333-4333-8333-333333333333")
            }
            "cursor" => {
                payload["chats"][0]["message_window"]["start_cursor"]["message_id"] =
                    json!("10000000-0000-4000-8000-000000000004")
            }
            "duplicate" => {
                let row = payload["chats"][0]["messages"][0].clone();
                payload["chats"][0]["messages"][1] = row;
            }
            "order" => payload["chats"][0]["messages"]
                .as_array_mut()
                .unwrap()
                .reverse(),
            "rows" => {
                let row = payload["chats"][0]["messages"][0].clone();
                payload["chats"][0]["messages"] = json!(vec![row; MAX_ROWS + 1]);
            }
            "parents" => {
                let row = payload["chats"][0].clone();
                payload["chats"] = json!(vec![row; MAX_PARENTS + 1]);
            }
            _ => unreachable!(),
        }
        assert!(stage(&client, metadata, &payload).is_err(), "{change}");
        assert_eq!(client.ciphertext_snapshot(), before);
    }
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn identical_duplicate_phase_is_idempotent_but_conflicting_duplicate_is_closed() {
    let (client, metadata, payload) = fixture();
    let mut batch = Phase1Windows::default();
    batch.content(&payload, None).unwrap();
    batch.content(&payload, None).unwrap();
    let chats = BTreeMap::from([(CHAT.into(), metadata)]);
    assert_eq!(
        client
            .finish_sync_windows(batch, &chats, &[])
            .unwrap()
            .len(),
        1
    );
    let mut batch = Phase1Windows::default();
    batch.content(&payload, None).unwrap();
    let mut changed = payload;
    changed["chats"][0]["server_message_count"] = json!(6);
    assert!(batch.content(&changed, None).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sync.access.first-party-authenticated,sync.client.shared-rust-policy
#[test]
fn unavailable_wrong_key_and_new_metadata_never_rebind_a_cached_window() {
    for change in ["missing-key", "wrong-key", "subchat"] {
        let (client, mut metadata, payload) = fixture();
        match change {
            "missing-key" => {
                metadata
                    .as_object_mut()
                    .unwrap()
                    .remove("encrypted_chat_key");
            }
            "wrong-key" => {
                metadata["encrypted_chat_key"] = json!(
                    crypto::encrypt_bytes(&[9; 32], &std::array::from_fn::<u8, 32, _>(|n| n as u8))
                        .unwrap()
                )
            }
            "subchat" => metadata["is_sub_chat"] = json!(true),
            _ => unreachable!(),
        }
        assert!(
            stage(&client, metadata, &payload).unwrap().is_empty(),
            "{change}"
        );
    }
    let mut client = admitted();
    let row = client.chats[CHAT].clone();
    assert!(client.synced_window(&row).unwrap().is_some());
    client.chats.get_mut(CHAT).unwrap()["messages_v"] = json!(6);
    assert!(client.synced_window(&client.chats[CHAT]).unwrap().is_none());
}
// contract-test: supporting surface=sdks.rust assertions=sync.startup.bounded-phases,sync.client.shared-rust-policy
#[test]
fn count_lag_is_descriptive_and_never_invents_a_message_window_version() {
    let (mut client, metadata, mut payload) = fixture();
    payload["chats"][0]["server_message_count"] = json!(4);
    client.sync_message_windows = stage(&client, metadata.clone(), &payload).unwrap();
    client.chats.insert(CHAT.into(), metadata);
    let snapshot = client.ciphertext_snapshot();
    assert_eq!(snapshot[SNAPSHOT_FIELD][CHAT]["server_message_count"], 4);
    assert_eq!(snapshot[SNAPSHOT_FIELD][CHAT]["metadata_messages_v"], 5);
    assert_eq!(snapshot["chats"][CHAT]["messages_v"], 5);
    assert!(!client.history.contains_key(CHAT));
}
// contract-test: supporting surface=sdks.rust assertions=sync.access.first-party-authenticated,sync.client.shared-rust-policy
#[test]
fn snapshot_roundtrip_is_bounded_and_cannot_restore_auth_or_completion() {
    let client = admitted();
    let snapshot = client.ciphertext_snapshot();
    let session = client.clone_session().unwrap();
    let mut restored = Client::new(&session.api_url, Some(session.clone())).unwrap();
    restored.restore_ciphertext_snapshot(&snapshot).unwrap();
    assert_eq!(restored.ciphertext_snapshot(), snapshot);
    assert!(
        restored
            .stage_cached_chat_views(None, CancellationToken::new())
            .is_err()
    );
    assert!(!restored.history.contains_key(CHAT));
    for change in ["cleartext", "cursor", "complete"] {
        let mut forged = snapshot.clone();
        match change {
            "cleartext" => {
                forged[SNAPSHOT_FIELD][CHAT]["messages"][0]["content"] =
                    json!("unprotected clear extension")
            }
            "cursor" => forged[SNAPSHOT_FIELD][CHAT]["start_cursor"]["created_at"] = json!(-1),
            "complete" => forged[SNAPSHOT_FIELD][CHAT]["history_complete"] = json!(true),
            _ => unreachable!(),
        }
        assert!(
            restored.restore_ciphertext_snapshot(&forged).is_err(),
            "{change}"
        );
    }
}
// contract-test: supporting surface=sdks.rust assertions=sync.access.first-party-authenticated,sync.client.shared-rust-policy
#[test]
fn actual_owner_scope_cancel_and_partial_ciphertext_changes_invalidate_reuse() {
    let mut client = admitted();
    let row = client.chats[CHAT].clone();
    let proof = client
        .fresh_chat_inventory(&client.operation_parent.clone())
        .unwrap()
        .unwrap();
    client.sync_message_windows.get_mut(CHAT).unwrap().messages[0]["encrypted_content"] =
        json!("changed-ciphertext");
    assert!(
        !proof
            .consume_if_current(&client, &client.operation_parent.clone())
            .unwrap()
    );
    client.user = json!({"id":"99999999-9999-4999-8999-999999999999"});
    client.credentials_changed();
    assert!(client.synced_window(&row).unwrap().is_none());
    let mut client = admitted();
    client.operation_cancel.cancel();
    let (_, metadata, payload) = fixture();
    assert!(stage(&client, metadata, &payload).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sync.startup.bounded-phases,sync.client.shared-rust-policy
#[test]
fn all_twenty_server_sized_windows_survive_beyond_the_four_mib_write_memo_threshold() {
    let (client, metadata, payload) = fixture();
    let mut batch = Phase1Windows::default();
    let mut chats = BTreeMap::new();
    let mut rows = Vec::new();
    let large = crypto::encrypt_combined(
        &"x".repeat(190_000),
        &std::array::from_fn::<u8, 32, _>(|n| (n + 32) as u8),
    )
    .unwrap();
    for index in 0..MAX_PARENTS {
        let id = format!("30000000-0000-4000-8000-{index:012}");
        let message_id = format!("40000000-0000-4000-8000-{index:012}");
        let mut row = metadata.clone();
        row["id"] = json!(id);
        chats.insert(id.clone(), row);
        let mut candidate = payload["chats"][0].clone();
        candidate["chat_id"] = json!(id);
        candidate["messages"] = json!([{"id":message_id,"chat_id":id,"created_at":index,"role":"user","encrypted_content":large}]);
        candidate["message_window"]["start_cursor"] =
            json!({"created_at":index,"message_id":message_id});
        rows.push(candidate);
    }
    batch
        .content(
            &json!({"team_id":null,"context_epoch":0,"chats":rows}),
            None,
        )
        .unwrap();
    let windows = client.finish_sync_windows(batch, &chats, &[]).unwrap();
    assert_eq!(windows.len(), MAX_PARENTS);
    assert!(
        serde_json::to_vec(&windows).unwrap().len() > 4 * 1024 * 1024,
        "4MiB is a writer optimization, not a data-retention policy"
    );
    assert!(windows.values().all(|window| window.messages.len() == 1));
}
// contract-test: supporting surface=sdks.rust assertions=sync.surface.semantic-parity,sync.client.shared-rust-policy
#[test]
fn absent_optional_field_preserves_legacy_snapshot_bytes() {
    let legacy = json!({"chats":{},"wrappers":[],"history":{},"embeds":{},"embed_keys":[],"team_wrapped_key":null});
    // Compatibility concerns existing snapshots whose optional fields were
    // absent, rather than a fresh client's explicit never-synced marker.
    for authenticated in [false, true] {
        let (mut client, _, _) = fixture();
        if authenticated {
            client.restore_authenticated_ciphertext_snapshot(&legacy).unwrap();
        } else {
            client.restore_ciphertext_snapshot(&legacy).unwrap();
        }
        let snapshot = client.ciphertext_snapshot();
        assert!(snapshot.get(SNAPSHOT_FIELD).is_none());
        assert_eq!(snapshot, legacy);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sync.surface.semantic-parity,sync.client.shared-rust-policy
#[test]
fn actual_backend_json_string_rows_and_object_rows_have_identical_staged_ciphertext() {
    let (client, metadata, object_payload) = fixture();
    let wire = shared();
    assert!(wire["payload"]["chats"][0]["messages"][0].is_string());
    let object = stage(&client, metadata.clone(), &object_payload).unwrap();
    let string = stage(&client, metadata, &wire["payload"]).unwrap();
    assert_eq!(
        serde_json::to_value(object).unwrap(),
        serde_json::to_value(string).unwrap()
    );
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases
#[test]
fn reconnect_merges_owned_encrypted_rows_without_a_hidden_lifetime_twenty_chat_quota() {
    let mut client = admitted();
    let (_, metadata, mut payload) = fixture();
    let old_id = client.sync_message_windows[CHAT].messages[0]["message_id"]
        .as_str()
        .unwrap()
        .to_owned();
    payload["chats"][0]["messages"]
        .as_array_mut()
        .unwrap()
        .remove(0);
    payload["chats"][0]["message_window"]["start_cursor"] =
        json!({"created_at":1700000004_i64,"message_id":"10000000-0000-4000-8000-000000000004"});
    let next = stage(&client, metadata.clone(), &payload).unwrap();
    assert_eq!(next[CHAT].messages.len(), 1);
    assert!(next[CHAT].retained_rows.contains_key(&old_id));
    client.sync_message_windows = next;
    // Metadata-only delta and independent chat changes cannot erase prior rows.
    let mut chats = BTreeMap::new();
    let next = client
        .finish_sync_windows(Phase1Windows::default(), &chats, &[])
        .unwrap();
    assert!(next[CHAT].retained_rows.contains_key(&old_id));
    client.sync_message_windows = next;
    let mut changed = metadata;
    changed["messages_v"] = json!(6);
    chats.insert(CHAT.into(), changed.clone());
    let next = client
        .finish_sync_windows(Phase1Windows::default(), &chats, &[])
        .unwrap();
    assert!(next.contains_key(CHAT));
    client.sync_message_windows = next;
    client.chats = chats;
    assert!(
        client.synced_window(&changed).unwrap().is_none(),
        "retained ciphertext is not a current version proof"
    );
    let snapshot = client.ciphertext_snapshot();
    let session = client.clone_session().unwrap();
    let mut restored = Client::new(&session.api_url, Some(session.clone())).unwrap();
    restored.restore_ciphertext_snapshot(&snapshot).unwrap();
    assert_eq!(restored.ciphertext_snapshot(), snapshot);
    assert!(!restored.history.contains_key(CHAT));
}
// contract-test: supporting surface=sdks.rust assertions=sync.access.first-party-authenticated,sync.client.shared-rust-policy
#[test]
fn forged_or_stale_restored_descriptor_cannot_admit_a_current_cached_view() {
    let mut client = admitted();
    let mut snapshot = client.ciphertext_snapshot();
    snapshot[SNAPSHOT_FIELD][CHAT]["metadata_sha256"] = json!("0".repeat(64));
    client.restore_ciphertext_snapshot(&snapshot).unwrap();
    assert!(client.synced_window(&client.chats[CHAT]).unwrap().is_none());
    assert!(!client.history.contains_key(CHAT));
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases
#[test]
fn prior_windows_are_retained_across_more_than_twenty_distinct_phase_receipts() {
    let (mut client, base_metadata, base_payload) = fixture();
    for index in 0..=MAX_PARENTS {
        let id = format!("30000000-0000-4000-8000-{index:012}");
        let mut metadata = base_metadata.clone();
        metadata["id"] = json!(id);
        let mut payload = base_payload.clone();
        payload["chats"][0]["chat_id"] = json!(id);
        for (offset, row) in payload["chats"][0]["messages"]
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .enumerate()
        {
            let message = format!("50000000-0000-4000-8000-{:012}", index * 10 + offset);
            row["chat_id"] = json!(id);
            row["id"] = json!(message);
            row["client_message_id"] = json!(message);
            row["message_id"] = json!(message);
        }
        let first = payload["chats"][0]["messages"][0].clone();
        payload["chats"][0]["message_window"]["start_cursor"] =
            json!({"created_at":first["created_at"],"message_id":first["message_id"]});
        client.sync_message_windows = stage(&client, metadata.clone(), &payload).unwrap();
        client.chats.insert(id, metadata);
    }
    assert_eq!(client.sync_message_windows.len(), MAX_PARENTS + 1);
    let snapshot = client.ciphertext_snapshot();
    let session = client.clone_session().unwrap();
    let mut restored = Client::new(&session.api_url, Some(session.clone())).unwrap();
    restored.restore_ciphertext_snapshot(&snapshot).unwrap();
    assert_eq!(restored.ciphertext_snapshot(), snapshot);
    assert!(restored.history.is_empty());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases
#[test]
fn empty_compression_boundary_keeps_unknown_cursor_and_never_claims_complete_history() {
    let (mut client, metadata, mut payload) = fixture();
    payload["chats"][0]["messages"] = json!([]);
    payload["chats"][0]["message_window"]["start_cursor"] = Value::Null;
    client.sync_message_windows = stage(&client, metadata.clone(), &payload).unwrap();
    client.chats.insert(CHAT.into(), metadata);
    let snapshot = client.ciphertext_snapshot();
    assert_eq!(snapshot[SNAPSHOT_FIELD][CHAT]["has_more_before"], true);
    assert!(snapshot[SNAPSHOT_FIELD][CHAT]["start_cursor"].is_null());
    assert!(client.history.is_empty());
    let session = client.clone_session().unwrap();
    let mut restored = Client::new(&session.api_url, Some(session.clone())).unwrap();
    restored.restore_ciphertext_snapshot(&snapshot).unwrap();
    assert_eq!(restored.ciphertext_snapshot(), snapshot);
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.surface.semantic-parity
#[test]
fn initial_parent_window_order_precedes_unrelated_cached_history_without_new_metadata_fetch() {
    let mut client = admitted();
    let mut metadata = client.chats[CHAT].clone();
    for index in 0..20 {
        let id = format!("70000000-0000-4000-8000-{index:012}");
        metadata["id"] = json!(id);
        metadata["last_edited_overall_timestamp"] = json!(100 + index);
        client.chats.insert(id.clone(), metadata.clone());
        let row = client.sync_message_windows[CHAT].messages[0].clone();
        let mut row = row;
        row["chat_id"] = json!(id);
        client.history.insert(id, vec![row]);
    }
    client
        .acknowledge_credentials(client.credential_revision)
        .unwrap();
    let views = client
        .stage_cached_chat_views(None, CancellationToken::new())
        .unwrap();
    assert!(
        views
            .publish(CHAT, CancellationToken::new())
            .unwrap()
            .is_some(),
        "server-selected current parent must not be starved by unrelated recent complete caches"
    );
    assert_eq!(client.sync_message_windows.len(), 1);
}

// contract-test: supporting surface=sdks.rust assertions=sync.access.first-party-authenticated,sync.client.shared-rust-policy
#[test]
fn retained_row_projection_rejects_clear_extensions_and_latest_id_aliases() {
    let client = admitted();
    let original = client.ciphertext_snapshot();
    let latest = original[SNAPSHOT_FIELD][CHAT]["messages"][0].clone();
    let id = latest["message_id"].as_str().unwrap().to_owned();
    let mut duplicate = original.clone();
    duplicate[SNAPSHOT_FIELD][CHAT]["retained_rows"] =
        Value::Object(serde_json::Map::from_iter([(id, latest.clone())]));
    let session = client.clone_session().unwrap();
    let mut restored = Client::new(&session.api_url, Some(session.clone())).unwrap();
    assert!(restored.restore_ciphertext_snapshot(&duplicate).is_err());
    let mut clear = original;
    let mut row = latest;
    let other = "60000000-0000-4000-8000-000000000001";
    row["id"] = json!(other);
    row["client_message_id"] = json!(other);
    row["message_id"] = json!(other);
    row["content"] = json!("CLEAR_EXTENSION_REFUSED");
    clear[SNAPSHOT_FIELD][CHAT]["retained_rows"] =
        Value::Object(serde_json::Map::from_iter([(other.to_owned(), row)]));
    assert!(restored.restore_ciphertext_snapshot(&clear).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.surface.semantic-parity
#[test]
fn exact_payload_reference_and_other_received_rows_are_retained_without_fake_content() {
    let (mut client, metadata, mut payload) = fixture();
    let row = &mut payload["chats"][0]["messages"][1];
    row.as_object_mut().unwrap().remove("encrypted_content");
    row["large_payload"] = json!({"object_key":"synthetic/opaque-selector","checksum":"a".repeat(64),"size_bytes":300_000});
    client.sync_message_windows = stage(&client, metadata.clone(), &payload).unwrap();
    client.chats.insert(CHAT.into(), metadata);
    let snapshot = client.ciphertext_snapshot();
    assert_eq!(
        snapshot[SNAPSHOT_FIELD][CHAT]["messages"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
    assert_eq!(
        snapshot[SNAPSHOT_FIELD][CHAT]["messages"][1]["large_payload"]["size_bytes"],
        300_000
    );
    assert!(client.history.is_empty());
    client
        .acknowledge_credentials(client.credential_revision)
        .unwrap();
    let views = client
        .stage_cached_chat_views(None, CancellationToken::new())
        .unwrap();
    assert!(
        views
            .publish(CHAT, CancellationToken::new())
            .unwrap()
            .is_none(),
        "missing exact content cannot be a fabricated usable transcript"
    );
    let session = client.clone_session().unwrap();
    let mut restored = Client::new(&session.api_url, Some(session.clone())).unwrap();
    restored.restore_ciphertext_snapshot(&snapshot).unwrap();
    assert_eq!(restored.ciphertext_snapshot(), snapshot);
}

// contract-test: supporting surface=sdks.rust assertions=sync.surface.semantic-parity,sync.client.shared-rust-policy
#[test]
fn unsupported_legacy_content_keeps_the_original_reader_without_fabricating_windows() {
    let (client, metadata, mut payload) = fixture();
    payload["chats"][0]
        .as_object_mut()
        .unwrap()
        .remove("message_window");
    assert!(
        stage(&client, metadata.clone(), &payload)
            .unwrap()
            .is_empty()
    );
    let mut payload = shared()["payload"].clone();
    payload.as_object_mut().unwrap().remove("context_epoch");
    assert!(stage(&client, metadata, &payload).unwrap().is_empty());
    assert!(client.history.is_empty());
    assert!(client.ciphertext_snapshot().get(SNAPSHOT_FIELD).is_none());
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn deployed_composite_and_opaque_ids_survive_phase1_restore_and_native_cached_view() {
    let (mut client, metadata, mut payload) = fixture();
    let logical = [
        "2222222222-10000000-0000-4000-8000-000000000001",
        "legacy_msg_0002",
    ];
    let database = payload["chats"][0]["messages"][0]["id"].clone();
    for (index, row) in payload["chats"][0]["messages"].as_array_mut().unwrap().iter_mut().enumerate() {
        row["client_message_id"] = json!(logical[index]);
        row["message_id"] = json!(logical[index]);
    }
    payload["chats"][0]["message_window"]["start_cursor"]["message_id"] = json!(logical[0]);
    client.sync_message_windows = stage(&client, metadata.clone(), &payload).unwrap();
    client.chats.insert(CHAT.into(), metadata);
    let snapshot = client.ciphertext_snapshot();
    assert_eq!(snapshot[SNAPSHOT_FIELD][CHAT]["messages"][0]["id"], database);
    assert_eq!(snapshot[SNAPSHOT_FIELD][CHAT]["messages"][0]["message_id"], logical[0]);
    let restored = restore_windows(snapshot.get(SNAPSHOT_FIELD)).unwrap();
    assert_eq!(restored[CHAT].start_cursor.as_ref().unwrap().message_id, logical[0]);
    client.sync_message_windows = restored;
    client.acknowledge_credentials(client.credential_revision).unwrap();
    let before = client.ciphertext_snapshot();
    let view = client.stage_cached_chat_views(None, CancellationToken::new()).unwrap()
        .publish(CHAT, CancellationToken::new()).unwrap().unwrap().into_window().unwrap();
    assert_eq!(view.chat.messages.iter().map(|row| row.id.as_str()).collect::<Vec<_>>(), logical);
    assert!(view.cached && view.refreshing && !view.history_complete);
    assert_eq!(client.ciphertext_snapshot(), before);
    assert!(!client.history.contains_key(CHAT));
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn phase1_message_alias_conflicts_types_and_wrong_chat_still_refuse_atomically() {
    for change in ["logical_conflict", "nonstring_client", "nonstring_message", "empty_logical_conflict", "wrong_chat"] {
        let (client, metadata, mut payload) = fixture();
        let before = client.ciphertext_snapshot();
        let row = &mut payload["chats"][0]["messages"][0];
        row["message_id"] = row["client_message_id"].clone();
        match change {
            "logical_conflict" => row["message_id"] = json!("different-logical-id"),
            "nonstring_client" => row["client_message_id"] = json!(42),
            "nonstring_message" => row["message_id"] = json!(false),
            "empty_logical_conflict" => { row["client_message_id"]=json!(""); row["message_id"]=json!(false); },
            _ => row["chat_id"] = json!("33333333-3333-4333-8333-333333333333"),
        }
        assert!(stage(&client, metadata, &payload).is_err());
        assert_eq!(client.ciphertext_snapshot(), before);
        assert!(!client.history.contains_key(CHAT));
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn projected_opaque_id_budget_is_source_derived_and_json_escape_exact() {
    assert_eq!(PROJECTED_FIELD_FRAMING_BYTES, 65);
    assert_eq!(MAX_NORMALIZED_BYTES, 525588);
    assert_eq!(MAX_WINDOW_BYTES, 262144);
    assert_eq!(MAX_ROWS, 20);
    for ch in ['m', '"', '\\'] {
        let id = ch.to_string().repeat(256);
        let raw = json!({"client_message_id":id,"created_at":1,"role":"user"});
        let projected = encrypted_row(&raw, CHAT).unwrap();
        let delta = serde_json::to_vec(&projected).unwrap().len() - serde_json::to_vec(&raw).unwrap().len();
        assert!(delta <= serde_json::to_vec(&raw).unwrap().len() + PROJECTED_FIELD_FRAMING_BYTES);
        assert_eq!(delta, if ch == 'm' {321} else {577});
    }
    // The original reviewer counterexample must cross the former normalized cap.
    let rows: Vec<Value> = (0..20).map(|i| json!({"client_message_id":format!("{}{:02}","m".repeat(254),i),
        "id":format!("90000000-0000-4000-8000-{i:012}"),
        "created_at":i+1,"role":"user","encrypted_content":"c".repeat(12540)})).collect();
    let raw: usize = rows.iter().map(|row| serde_json::to_vec(row).unwrap().len()).sum();
    assert!(raw <= MAX_WINDOW_BYTES);
    let projected = message_rows(&rows,CHAT,MAX_WINDOW_BYTES).unwrap();
    assert!(normalized_rows_bytes(&projected).unwrap() > MAX_WINDOW_BYTES + MAX_ROWS * 128);
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn max_escaped_ids_valid_ciphertext_at_wire_cap_roundtrip_and_refuse_overbounds() {
    let (client, metadata, mut payload) = fixture();
    let session = client.require_session().unwrap();
    let key = crypto::decrypt_bytes(required(&metadata,"encrypted_chat_key").unwrap(), &session.master_key).unwrap();
    let key = key_from_bytes(&key).unwrap();
    for ch in ['m', '"', '\\'] {
        let logical: Vec<String> = (0..20).map(|i| {
            if ch == 'm' { return format!("{}{:02}",ch.to_string().repeat(254),i); }
            let prefix: String = (0..5).map(|bit| if i & (1 << bit) == 0 {'"'} else {'\\'}).collect();
            prefix + &ch.to_string().repeat(251)
        }).collect();
        let mut rows: Vec<Value> = logical.iter().enumerate().map(|(i,id)|json!({
            "client_message_id":id,"created_at":i as i64+1,"role":"user",
            "encrypted_content":crypto::encrypt_combined(&"x".repeat(8500),&key).unwrap()})).collect();
        let size = |rows:&[Value]| -> usize { rows.iter().map(|row|serde_json::to_vec(row).unwrap().len()).sum() };
        // Fill only real encrypted content. Base64 grows in four-byte quanta;
        // a <=3-byte role suffix consumes the remaining wire boundary exactly.
        let (mut low,mut high) = (8500,MAX_WINDOW_BYTES);
        while low < high {
            let mid = low + (high-low+1)/2;
            rows[19]["encrypted_content"] = json!(crypto::encrypt_combined(&"x".repeat(mid),&key).unwrap());
            if size(&rows) <= MAX_WINDOW_BYTES { low=mid; } else { high=mid-1; }
        }
        rows[19]["encrypted_content"] = json!(crypto::encrypt_combined(&"x".repeat(low),&key).unwrap());
        let remaining = MAX_WINDOW_BYTES-size(&rows);
        assert!(remaining < 4);
        rows[19]["role"] = json!(format!("user{}","x".repeat(remaining)));
        assert_eq!(size(&rows),MAX_WINDOW_BYTES);
        for row in &rows { assert!(!crypto::decrypt_combined(required(row,"encrypted_content").unwrap(),&key).unwrap().is_empty()); }
        payload["chats"][0]["messages"] = json!(rows);
        payload["chats"][0]["server_message_count"] = json!(20);
        payload["chats"][0]["message_window"]["start_cursor"] = json!({"created_at":1,"message_id":logical[0]});
        let windows = stage(&client,metadata.clone(),&payload).unwrap();
        assert_eq!(windows[CHAT].messages.len(),20);
        let value = serde_json::to_value(&windows).unwrap();
        let restored = restore_windows(Some(&value)).unwrap();
        assert_eq!(serde_json::to_value(&restored).unwrap(),value);
        // Record accounting equals actual serialization for the viewport and
        // ignores only separately bounded lifetime retained rows.
        let mut viewport = windows[CHAT].clone();
        viewport.start_cursor = Some(WindowCursor{created_at:i64::MAX,message_id:"\"".repeat(256)});
        viewport.oversized_message=true;
        viewport.oversized_message_cursor = Some(WindowCursor{created_at:i64::MAX,message_id:"\\".repeat(256)});
        viewport.source_rank=Some(19);
        viewport.has_more_before=false;
        viewport.server_message_count=u64::MAX;
        viewport.metadata_messages_v=u64::MAX;
        let record_bytes=viewport_record_bytes(&viewport).unwrap();
        assert_eq!(record_bytes,serde_json::to_vec(&viewport).unwrap().len());
        assert!(record_bytes-normalized_rows_bytes(&viewport.messages).unwrap() <= MAX_WINDOW_DESCRIPTOR_BYTES);
        viewport.retained_rows.insert("retained-old".into(),windows[CHAT].messages[0].clone());
        assert_eq!(viewport_record_bytes(&viewport).unwrap(),record_bytes);
        viewport.retained_rows.clear();
        assert_eq!(viewport_record_bytes(&viewport).unwrap(),serde_json::to_vec(&viewport).unwrap().len());
        let before=client.ciphertext_snapshot();
        let role=payload["chats"][0]["messages"][19]["role"].as_str().unwrap().to_owned();
        payload["chats"][0]["messages"][19]["role"]=json!(role+"x");
        assert!(stage(&client,metadata.clone(),&payload).is_err());
        assert_eq!(client.ciphertext_snapshot(),before);
        // An imported already-normalized latest window has the same strict cap.
        let mut imported=value.clone();
        let row=&mut imported[CHAT]["messages"][19];
        let extra=MAX_NORMALIZED_BYTES-normalized_rows_bytes(&windows[CHAT].messages).unwrap()+1;
        let cipher=required(row,"encrypted_content").unwrap().to_owned();
        row["encrypted_content"]=json!(cipher+&"x".repeat(extra));
        assert!(restore_windows(Some(&imported)).is_err());
    }
}


// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn long_control_unicode_ids_at_raw_cap_roundtrip_without_ciphertext_or_history_changes() {
    let (client,metadata,mut payload)=fixture();
    let key=crypto::decrypt_bytes(required(&metadata,"encrypted_chat_key").unwrap(),&client.require_session().unwrap().master_key).unwrap();
    let key=key_from_bytes(&key).unwrap();
    // Six-byte JSON escapes, not a byte/character ID cap. The ID is over 256
    // bytes and duplicates into normalized message_id plus the start cursor.
    let logical=["\u{1}".repeat(40000),"雪😀e\u{301} +%".repeat(300)];
    let mut rows:Vec<Value>=logical.iter().enumerate().map(|(i,id)|json!({"client_message_id":id,"created_at":i+1,"role":"user","encrypted_content":crypto::encrypt_combined("x",&key).unwrap()})).collect();
    let size=|rows:&[Value]| rows.iter().map(|r|serde_json::to_vec(r).unwrap().len()).sum::<usize>();
    let(mut low,mut high)=(1,MAX_WINDOW_BYTES);
    while low<high {let mid=low+(high-low+1)/2;rows[1]["encrypted_content"]=json!(crypto::encrypt_combined(&"x".repeat(mid),&key).unwrap());if size(&rows)<=MAX_WINDOW_BYTES{low=mid}else{high=mid-1}}
    rows[1]["encrypted_content"]=json!(crypto::encrypt_combined(&"x".repeat(low),&key).unwrap());
    let padding=MAX_WINDOW_BYTES-size(&rows);assert!(padding<4);rows[1]["role"]=json!(format!("user{}","x".repeat(padding)));
    assert_eq!(size(&rows),MAX_WINDOW_BYTES);
    let original_ciphers:Vec<Value>=rows.iter().map(|r|r["encrypted_content"].clone()).collect();
    payload["chats"][0]["messages"]=json!(rows);payload["chats"][0]["server_message_count"]=json!(2);
    payload["chats"][0]["message_window"]["start_cursor"]=json!({"created_at":1,"message_id":logical[0]});
    let before=client.ciphertext_snapshot();let windows=stage(&client,metadata.clone(),&payload).unwrap();
    assert!(normalized_rows_bytes(&windows[CHAT].messages).unwrap()>273684); // old V2 cap
    let snapshot=serde_json::to_value(&windows).unwrap();let restored=restore_windows(Some(&snapshot)).unwrap();
    assert_eq!(serde_json::to_value(&restored).unwrap(),snapshot);
    for(i,row)in restored[CHAT].messages.iter().enumerate(){assert_eq!(row["client_message_id"],logical[i]);assert_eq!(row["message_id"],logical[i]);assert_eq!(row["encrypted_content"],original_ciphers[i]);assert!(!crypto::decrypt_combined(required(row,"encrypted_content").unwrap(),&key).unwrap().is_empty());}
    assert_eq!(client.ciphertext_snapshot(),before);assert!(!client.history.contains_key(CHAT));
    let mut viewport=windows[CHAT].clone();viewport.oversized_message=true;
    viewport.oversized_message_cursor=Some(WindowCursor{created_at:i64::MAX,message_id:"\u{1}".repeat(30000)});
    let bytes=viewport_record_bytes(&viewport).unwrap();assert_eq!(bytes,serde_json::to_vec(&viewport).unwrap().len());
    assert!(bytes-normalized_rows_bytes(&viewport.messages).unwrap()>4096);
    let mut object=serde_json::to_value(BTreeMap::from([(CHAT,viewport.clone())])).unwrap();
    assert_eq!(serde_json::to_value(restore_windows(Some(&object)).unwrap()).unwrap(),object);
    let mut older=windows[CHAT].messages[0].clone();older["message_id"]=json!("older");older["client_message_id"]=json!("older");older["created_at"]=json!(0);
    viewport.retained_rows.insert("older".into(),older);assert_eq!(viewport_record_bytes(&viewport).unwrap(),bytes);
    let retained=serde_json::to_value(BTreeMap::from([(CHAT,viewport)])).unwrap();assert_eq!(serde_json::to_value(restore_windows(Some(&retained)).unwrap()).unwrap(),retained);
    object[CHAT]["oversized_message_cursor"]["message_id"]=json!("x".repeat(MAX_WINDOW_BYTES));assert!(restore_windows(Some(&object)).is_err());
    let role=required(&payload["chats"][0]["messages"][1],"role").unwrap().to_owned();payload["chats"][0]["messages"][1]["role"]=json!(role+"x");
    assert!(stage(&client,metadata,&payload).is_err());assert_eq!(client.ciphertext_snapshot(),before);
}
// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn complete_cursor_budget_is_exact_and_independent_of_opaque_id_grammar() {
    let mut cursor=WindowCursor{created_at:1,message_id:"x".into()};
    let overhead=serde_json::to_vec(&cursor).unwrap().len()-1;
    cursor.message_id="x".repeat(MAX_WINDOW_BYTES-overhead);
    assert_eq!(cursor_bytes(Some(&cursor)).unwrap(),MAX_WINDOW_BYTES);
    assert!(parse_cursor(Some(&serde_json::to_value(&cursor).unwrap())).is_ok());
    cursor.message_id.push('x');assert!(super::super::message_window::valid_message_id(&cursor.message_id));
    assert!(cursor_bytes(Some(&cursor)).is_err());assert!(parse_cursor(Some(&serde_json::to_value(&cursor).unwrap())).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.startup.bounded-phases
#[test]
fn phase_window_expected_epoch_is_request_bound_and_default_zero_stays_compatible() {
    let mut phase = Phase1Windows::default();
    let epoch = json!({"context_epoch":7,"team_id":null,"recent_chat_metadata":[]});
    assert_eq!(phase.metadata(&epoch,None),Err(Error::Forbidden));
    assert!(phase.metadata_with_expected_epoch(&epoch,None,7).is_ok());
    assert_eq!(phase.metadata_with_expected_epoch(&epoch,None,8),Err(Error::Forbidden));
    assert!(phase.metadata(&json!({"context_epoch":0,"team_id":null,"recent_chat_metadata":[]}),None).is_ok());
    assert_eq!(phase.content_with_expected_epoch(&json!({"context_epoch":6,"team_id":null,"chats":[]}),None,7),Err(Error::Forbidden));
    assert!(phase.content_with_expected_epoch(&json!({"context_epoch":7,"team_id":null,"chats":[]}),None,7).is_ok());
    assert_eq!(phase.metadata_with_expected_epoch(&json!({"context_epoch":7,"team_id":"22222222-2222-4222-8222-222222222222","recent_chat_metadata":[]}),None,7),Err(Error::Forbidden));
}

// contract-test: supporting surface=sdks.rust assertions=sync.startup.bounded-phases,sync.client.shared-rust-policy
#[test]
fn phase1_metadata_keeps_twenty_five_parents_and_child_with_only_twenty_content_windows() {
    let (client,base,payload)=fixture();let mut metadata=Vec::new();let mut content=Vec::new();
    for index in 0..25 {
        let id=format!("30000000-0000-4000-8000-{index:012}");let mut row=base.clone();row["id"]=json!(id);row["pinned"]=json!(index%2==0);metadata.push(row);
        if index<MAX_PARENTS {let mut candidate=payload["chats"][0].clone();candidate["chat_id"]=json!(id);for message in candidate["messages"].as_array_mut().unwrap(){message["chat_id"]=json!(id);}content.push(candidate);}
    }
    let child="60000000-0000-4000-8000-000000000000";let mut row=base.clone();row["id"]=json!(child);row["parent_id"]=metadata[0]["id"].clone();row["is_sub_chat"]=json!(true);metadata.push(row);
    let mut batch=Phase1Windows::default();let received=json!({"context_epoch":0,"team_id":null,"recent_chat_metadata":metadata});
    batch.metadata(&received,None).unwrap();batch.metadata(&received,None).unwrap();
    batch.content(&json!({"context_epoch":0,"team_id":null,"chats":content}),None).unwrap();
    let mut rows=BTreeMap::new();let mut order=Vec::new();batch.merge_metadata_ordered(&mut rows,&mut order);
    assert_eq!(rows.len(),26);assert_eq!(order.len(),26);assert_eq!(order,metadata.iter().map(|row|row["id"].as_str().unwrap().to_owned()).collect::<Vec<_>>());
    assert_eq!(rows[child]["parent_id"],metadata[0]["id"]);assert_eq!(rows[child]["is_sub_chat"],true);
    let windows=client.finish_sync_windows(batch,&rows,&[]).unwrap();assert_eq!(windows.len(),MAX_PARENTS);assert!(!windows.contains_key(child));
    for row in metadata.iter().take(MAX_PARENTS){assert!(windows.contains_key(row["id"].as_str().unwrap()));}
    for row in metadata.iter().skip(MAX_PARENTS){assert!(!windows.contains_key(row["id"].as_str().unwrap()));}
}
// contract-test: supporting surface=sdks.rust assertions=sync.startup.bounded-phases,sync.client.shared-rust-policy
#[test]
fn phase1_metadata_duplicate_scope_and_global_aggregate_bounds_are_atomic() {
    let (_,base,_)=fixture();let mut batch=Phase1Windows::default();let first=json!({"context_epoch":0,"team_id":null,"chat_details":base});batch.metadata(&first,None).unwrap();
    let before=batch.metadata.clone();let order=batch.metadata_order.clone();
    let mut changed=first.clone();changed["chat_details"]["messages_v"]=json!(99);assert!(batch.metadata(&changed,None).is_err());assert_eq!(batch.metadata,before);assert_eq!(batch.metadata_order,order);
    let mut foreign=first.clone();foreign["context_epoch"]=json!(1);assert_eq!(batch.metadata(&foreign,None),Err(Error::Forbidden));assert_eq!(batch.metadata,before);
    // Each row is individually below the existing16MiB transport limit; their
    // post-merge aggregate exceeds it. Refuse all new rows without truncation.
    let mut a=base.clone();a["id"]=json!("30000000-0000-4000-8000-000000000001");a["opaque_extension"]=json!("x".repeat(crate::client::transport::MAX_BODY/2));
    let mut b=a.clone();b["id"]=json!("30000000-0000-4000-8000-000000000002");
    assert!(batch.metadata(&json!({"context_epoch":0,"team_id":null,"recent_chat_metadata":[a,b]}),None).is_err());assert_eq!(batch.metadata,before);assert_eq!(batch.metadata_order,order);
}
