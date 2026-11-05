//! Synthetic pure decode regressions; authored, product execution UNRUN.
// contract-test-file: tooling
// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
use super::*;
use crate::client::plaintext::Wipe;
use std::cell::Cell;
const ID: &str = "22222222-2222-4222-8222-222222222222";
const SCOPE: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const TOKEN: &str = "[OM_PII_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA]";
fn metadata() -> Value {
    json!({"id":ID,"messages_v":4,"encrypted_title":crypto::encrypt_combined("Synthetic title",&[9;32]).unwrap()})
}
fn item() -> Plain<Item> {
    Plain::new(Item {
        id: ID.into(),
        title: "Synthetic title".into(),
        category: "Synthetic category".into(),
        ..Item::default()
    })
}
fn row(id: &str, created_at: i64, role: &str, content: &str) -> Value {
    json!({"id":id,"chat_id":ID,"created_at":created_at,"role":role,"encrypted_content":crypto::encrypt_combined(content,&[9;32]).unwrap()})
}
fn page(rows: Vec<Value>) -> Value {
    let cursor = |row: &Value| json!({"created_at":row["created_at"],"message_id":row.get("client_message_id").unwrap_or(&row["id"])});
    let start = rows.first().map(cursor);
    let end = rows.last().map(cursor);
    let bytes: usize = rows
        .iter()
        .map(|row| serde_json::to_vec(row).unwrap().len())
        .sum();
    json!({"chat_id":ID,"messages":rows,"has_more_before":false,"has_more_after":false,"start_cursor":start,"end_cursor":end,"anchor_found":true,"payload_bytes":bytes,"oversized_message":false,"oversized_message_cursor":null,"server_message_count":4,"messages_v":4,"compression_boundary_timestamp":1})
}
fn decode(
    page: Value,
    options: &MessageWindowOptions,
    stored: bool,
    capture: bool,
) -> Result<MessagePageData> {
    decode_message_page_data(
        ID,
        &metadata(),
        zeroize::Zeroizing::new([9; 32]),
        item(),
        page,
        options,
        SCOPE,
        stored,
        capture,
        || Ok(()),
    )
}
#[test]
fn pure_empty_page_retains_noncomplete_paging_and_no_raw_capture() {
    let decoded =
        Plain::new(decode(page(vec![]), &MessageWindowOptions::default(), false, false).unwrap());
    assert!(decoded.window.chat.messages.is_empty());
    assert!(!decoded.window.history_complete);
    assert!(decoded.incoming.is_none());
    assert_eq!(decoded.window.pii_restoration, "page_local");
    assert!(decoded.window.start_cursor.is_none());
    assert_eq!(decoded.window.server_message_count, Some(4));
}
#[test]
fn pure_same_timestamp_opaque_order_and_exact_alias_cursor_remain_strict() {
    let first = row("opaque a", 1, "user", "A");
    let second = row("opaque b", 1, "assistant", "B");
    let good = page(vec![first.clone(), second.clone()]);
    let decoded = Plain::new(decode(good, &MessageWindowOptions::default(), false, false).unwrap());
    assert_eq!(decoded.window.chat.messages[0].id, "opaque a");
    assert_eq!(
        decoded.window.end_cursor.as_ref().unwrap().message_id,
        "opaque b"
    );
    for rows in [
        vec![second, first.clone()],
        vec![first.clone(), first.clone()],
    ] {
        assert!(matches!(
            decode(page(rows), &MessageWindowOptions::default(), false, false),
            Err(Error::Protocol)
        ));
    }
    let mut conflict = first;
    conflict["client_message_id"] = json!("logical a");
    conflict["message_id"] = json!("different");
    assert!(matches!(
        decode(
            page(vec![conflict]),
            &MessageWindowOptions::default(),
            false,
            false
        ),
        Err(Error::Protocol)
    ));
}
#[test]
fn pure_cross_chat_ciphertext_and_malformed_page_never_project() {
    let source = row("opaque a", 1, "user", "A");
    let mut bad_cipher = source.clone();
    bad_cipher["encrypted_content"] = json!("not-base64");
    assert!(decode(
        page(vec![bad_cipher]),
        &MessageWindowOptions::default(),
        false,
        false
    )
    .is_err());
    let mut wrong = source.clone();
    wrong["chat_id"] = json!("33333333-3333-4333-8333-333333333333");
    assert!(matches!(
        decode(
            page(vec![wrong]),
            &MessageWindowOptions::default(),
            false,
            false
        ),
        Err(Error::Forbidden)
    ));
    let valid = page(vec![source]);
    for field in [
        "messages",
        "has_more_before",
        "start_cursor",
        "payload_bytes",
    ] {
        let mut malformed = valid.clone();
        malformed[field] = json!("malformed");
        assert!(
            decode(malformed, &MessageWindowOptions::default(), false, false).is_err(),
            "{field}"
        );
    }
    let mut wrongpage = valid;
    wrongpage["chat_id"] = json!("33333333-3333-4333-8333-333333333333");
    assert!(matches!(
        decode(wrongpage, &MessageWindowOptions::default(), false, false),
        Err(Error::Forbidden)
    ));
}
#[test]
fn pure_cursor_payload_limit_and_oversize_guards_are_not_repaired() {
    let valid = page(vec![row("opaque a", 1, "user", "A")]);
    let options = MessageWindowOptions {
        direction: MessageWindowDirection::After,
        cursor: Some(MessageWindowCursor {
            chat_id: ID.into(),
            scope: SCOPE.into(),
            created_at: 1,
            message_id: "opaque a".into(),
        }),
        ..Default::default()
    };
    assert!(matches!(
        decode(valid.clone(), &options, false, false),
        Err(Error::Protocol)
    ));
    for (field, value) in [
        ("payload_bytes", json!(0)),
        ("oversized_message", json!(true)),
        (
            "end_cursor",
            json!({"created_at":2,"message_id":"opaque a"}),
        ),
    ] {
        let mut bad = valid.clone();
        bad[field] = value;
        assert!(
            matches!(
                decode(bad, &MessageWindowOptions::default(), false, false),
                Err(Error::Protocol)
            ),
            "{field}"
        );
    }
    let options = MessageWindowOptions {
        limit: 1,
        ..Default::default()
    };
    assert!(matches!(
        decode(
            page(vec![row("a", 1, "user", "A"), row("b", 2, "user", "B")]),
            &options,
            false,
            false
        ),
        Err(Error::Protocol)
    ));
    let mut huge = row("a", 1, "user", "A");
    huge["extra"] = json!("x".repeat(MAX_MESSAGE_BYTES));
    assert!(matches!(
        decode(
            page(vec![huge]),
            &MessageWindowOptions::default(),
            false,
            false
        ),
        Err(Error::Protocol)
    ));
}
#[test]
fn pure_compression_selector_does_not_filter_selected_page_or_lose_stamp_boundary() {
    let wire = page(vec![
        row("old", 1, "user", "A"),
        row("new", 2, "assistant", "B"),
    ]);
    let meta = metadata();
    let project = |wire, options: &MessageWindowOptions, stored| {
        decode_message_page_data(
            ID,
            &meta,
            zeroize::Zeroizing::new([9; 32]),
            item(),
            wire,
            options,
            SCOPE,
            stored,
            false,
            || Ok(()),
        )
    };
    let mut prior_stamp = None;
    for respect in [true, false] {
        let options = MessageWindowOptions {
            respect_compression_boundary: respect,
            ..Default::default()
        };
        let decoded = Plain::new(project(wire.clone(), &options, true).unwrap());
        assert_eq!(decoded.window.chat.messages.len(), 2);
        assert_eq!(decoded.window.chat.messages[0].id, "old");
        if let Some(prior) = prior_stamp {
            assert_eq!(decoded.metadata_stamp, prior);
        }
        prior_stamp = Some(decoded.metadata_stamp.clone());
    }
    let mut changed = wire.clone();
    changed["compression_boundary_timestamp"] = json!(2);
    for stored in [false, true] {
        let before =
            Plain::new(project(wire.clone(), &MessageWindowOptions::default(), stored).unwrap());
        let after =
            Plain::new(project(changed.clone(), &MessageWindowOptions::default(), stored).unwrap());
        assert_eq!(before.metadata_stamp != after.metadata_stamp, stored);
    }
}
#[test]
fn pure_page_local_and_stored_pii_paths_keep_original_role_policy() {
    let mut user = row("a", 1, "user", TOKEN);
    user["encrypted_pii_mappings"] = json!(crypto::encrypt_combined(
        &json!([{"placeholder":TOKEN,"original":"Synthetic Alice"}]).to_string(),
        &[9; 32]
    )
    .unwrap());
    let mut assistant = row("b", 2, "assistant", TOKEN);
    assistant["encrypted_pii_mappings"] = json!(crypto::encrypt_combined(
        &json!([{"placeholder":TOKEN,"original":"Must not restore assistant map"}]).to_string(),
        &[9; 32]
    )
    .unwrap());
    let wire = page(vec![user, assistant]);
    let local =
        Plain::new(decode(wire.clone(), &MessageWindowOptions::default(), false, false).unwrap());
    assert!(local.mappings.is_empty());
    assert!(local
        .window
        .chat
        .messages
        .iter()
        .all(|m| m.content == "Synthetic Alice"));
    let stored = Plain::new(decode(wire, &MessageWindowOptions::default(), true, false).unwrap());
    assert_eq!(stored.mappings.len(), 2);
    assert!(stored
        .window
        .chat
        .messages
        .iter()
        .all(|m| m.content == TOKEN));
    assert!(stored.chat_metadata.is_some());
    assert_eq!(stored.message_metadata.len(), 2);
}
#[test]
fn pure_capture_is_opt_in_exact_same_wire_and_wipe_covers_every_plaintext_field() {
    let raw = row("a", 1, "user", "Synthetic private text");
    let wire = page(vec![raw.clone()]);
    let meta = metadata();
    let mut decoded = decode_message_page_data(
        ID,
        &meta,
        zeroize::Zeroizing::new([9; 32]),
        item(),
        wire,
        &MessageWindowOptions::default(),
        SCOPE,
        true,
        true,
        || Ok(()),
    )
    .unwrap();
    assert_eq!(&*decoded.incoming.as_ref().unwrap().messages, &vec![raw]);
    assert_eq!(&*decoded.incoming.as_ref().unwrap().metadata, &meta);
    decoded.wipe();
    assert!(decoded.incoming.is_none());
    assert!(decoded.window.chat.title.is_empty());
    assert!(decoded
        .window
        .chat
        .messages
        .iter()
        .all(|m| m.id.is_empty() && m.content.is_empty() && m.role.is_empty()));
    assert!(decoded.mappings.is_empty());
    assert!(decoded.metadata_stamp.is_empty());
    assert!(decoded.chat_metadata.as_ref().unwrap().id.is_empty());
    assert!(decoded.message_metadata.iter().all(|m| m.id.is_empty()));
}
#[test]
fn pure_required_negative_observer_refuses_before_decode_and_after_owned_result_assembly() {
    let wire = page(vec![row("a", 1, "user", "Synthetic private text")]);
    for deny_at in [1, 2, 3] {
        let calls = Cell::new(0);
        let result = decode_message_page_data(
            ID,
            &metadata(),
            zeroize::Zeroizing::new([9; 32]),
            item(),
            wire.clone(),
            &MessageWindowOptions::default(),
            SCOPE,
            true,
            true,
            || {
                calls.set(calls.get() + 1);
                if calls.get() == deny_at {
                    Err(Error::Cancelled)
                } else {
                    Ok(())
                }
            },
        );
        assert!(matches!(result, Err(Error::Cancelled)));
        assert_eq!(calls.get(), deny_at);
    }
}


// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn owned_rows_and_reused_sender_match_reference_projection_exactly() {
    let key = [9; 32];
    let variants = [None, Some(Value::Null), Some(json!("")),
        Some(json!(crypto::encrypt_combined("", &key).unwrap())),
        Some(json!(crypto::encrypt_combined("Synthetic sender", &key).unwrap()))];
    for sender in variants {
        let mut raw = row("opaque sender", 1, "assistant", "Synthetic content");
        if let Some(value) = sender { raw["encrypted_sender_name"] = value; }
        raw["encrypted_thinking_content"] = json!(crypto::encrypt_combined("Synthetic thought", &key).unwrap());
        raw["encrypted_category"] = json!(crypto::encrypt_combined("Synthetic category", &key).unwrap());
        raw["unknown_extension"] = json!({"preserve":"exact ciphertext row"});
        for string_row in [false, true] {
            let wire = if string_row { json!(serde_json::to_string(&raw).unwrap()) } else { raw.clone() };
            let (_, expected_message) = crate::client::sync::decode_chat_message(
                &wire, ID, &key, &mut Default::default()).unwrap();
            let expected_message = Plain::new(expected_message);
            let expected_metadata = Plain::new(crate::client::saved_chat_read::metadata::message(
                &raw, &expected_message, ID, &key).unwrap());
            let mut input = page(vec![raw.clone()]);
            input["messages"][0] = wire;
            let decoded = Plain::new(decode(input, &MessageWindowOptions::default(), true, true).unwrap());
            assert_eq!(serde_json::to_value(&decoded.window.chat.messages[0]).unwrap(),
                serde_json::to_value(&*expected_message).unwrap());
            assert_eq!(serde_json::to_value(&decoded.message_metadata[0]).unwrap(),
                serde_json::to_value(&*expected_metadata).unwrap());
            assert_eq!(&*decoded.incoming.as_ref().unwrap().messages, &vec![raw.clone()]);
            assert!(!decoded.window.history_complete);
            assert_eq!(decoded.window.start_cursor.as_ref().unwrap().message_id, "opaque sender");
            assert_eq!(decoded.window.end_cursor.as_ref().unwrap().message_id, "opaque sender");
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sync.startup.bounded-phases
#[test]
fn owned_rows_retain_malformed_crypto_refusals_for_both_wire_forms() {
    for field in ["encrypted_content", "encrypted_sender_name", "encrypted_thinking_content",
        "encrypted_category", "encrypted_model_name", "encrypted_thinking_signature"] {
        for bad in [json!(false), json!({"invalid":"shape"}), json!("not-base64"),
            json!(crypto::encrypt_combined("wrong key", &[8;32]).unwrap())] {
            let mut raw = row("opaque malformed", 1, "assistant", "Synthetic");
            raw[field] = bad;
            for string_row in [false, true] {
                let mut input = page(vec![raw.clone()]);
                if string_row { input["messages"][0] = json!(serde_json::to_string(&raw).unwrap()); }
                assert!(decode(input, &MessageWindowOptions::default(), true, true).is_err(),
                    "{field}: string_row={string_row}");
            }
        }
    }
    // Sender's metadata bound still applies after canonical authentication.
    let mut raw = row("opaque oversized", 1, "assistant", "Synthetic");
    raw["encrypted_sender_name"] = json!(crypto::encrypt_combined(&"s".repeat(64*1024+1), &[9;32]).unwrap());
    assert!(decode(page(vec![raw]), &MessageWindowOptions::default(), true, false).is_err());
}

#[test]
fn owned_page_keeps_legacy_refusal_for_double_encoded_rows() {
    let raw = row("opaque nested", 1, "assistant", "Synthetic");
    let mut input = page(vec![raw.clone()]);
    input["messages"][0] = json!(serde_json::to_string(&json!(serde_json::to_string(&raw).unwrap())).unwrap());
    assert!(decode(input, &MessageWindowOptions::default(), true, true).is_err());
}
