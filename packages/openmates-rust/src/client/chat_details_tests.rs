//! Authored UNRUN shared pure projection/security cases. Actual authenticated IO
//! is separately covered by all three genuine direct conformance adapter source.
// contract-test-file: tooling
use super::*;
fn encrypted(value: &str) -> String {
    crypto::encrypt_combined(value, &[7; 32]).unwrap()
}
#[test]
fn options_default_bounded_stored_and_closed_variants_match_shared_api() {
    let options: ChatDetailsOptions = serde_json::from_str("{}").unwrap();
    assert!(matches!(
        options.history,
        ChatDetailsHistory::Latest { limit: 30 }
    ));
    assert!(options.content_mode == SavedChatContentMode::Stored);
    let full: ChatDetailsOptions =
        serde_json::from_str(r#"{"history":{"kind":"full"}}"#).unwrap();
    assert!(matches!(full.history, ChatDetailsHistory::Full));
    assert_eq!(serde_json::to_string(&full.history).unwrap(), r#"{"kind":"full"}"#);
    for value in [
        r#"{"unknown":true}"#,
        r#"{"history":{"kind":"full","limit":30}}"#,
        r#"{"history":{"kind":"latest"}}"#,
        r#"{"history":{"kind":"full","unknown":true}}"#,
        r#"{"history":{"kind":"latest","limit":30,"unknown":true}}"#,
        r#"{"content_mode":"restore_all"}"#,
    ] {
        assert!(serde_json::from_str::<ChatDetailsOptions>(value).is_err());
    }
}
#[test]
fn suggestions_filter_strip_prefix_and_optional_corruption_exactly_without_global_sync() {
    let source = json!({"encrypted_follow_up_request_suggestions":encrypted(r#"["[legacy]  First?  ","",4,null," [old] ","雪?","\uFEFF[old] Final?"]"#)});
    assert_eq!(
        suggestions(&source, &[7; 32]).unwrap(),
        vec!["First?", "雪?", "Final?"]
    );
    for source in [
        json!({}),
        json!({"encrypted_follow_up_request_suggestions":null}),
        json!({"encrypted_follow_up_request_suggestions":4}),
        json!({"encrypted_follow_up_request_suggestions":""}),
        json!({"encrypted_follow_up_request_suggestions":"corrupt"}),
        json!({"encrypted_follow_up_request_suggestions":encrypted("{}")}),
    ] {
        assert!(suggestions(&source, &[7; 32]).unwrap().is_empty());
    }
}
#[test]
fn stored_message_moves_decrypted_fields_and_preserves_pii_absence_empty_and_raw_rows() {
    let id = "22222222-2222-4222-8222-222222222222";
    let logical = "opaque-logical:雪";
    for mappings in [
        None,
        Some("[]"),
        Some("null"),
        Some("3"),
        Some(r#"[{"placeholder":"[EMAIL_1]","original":"synthetic@example.invalid"},null,3]"#),
    ] {
        let mut row = json!({"id":"storage-row","client_message_id":logical,"chat_id":id,"role":"assistant","created_at":0,"encrypted_content":encrypted("Stored [EMAIL_1]"),"encrypted_sender_name":encrypted(""),"encrypted_category":encrypted("science"),"encrypted_model_name":encrypted("automatic-source-model")});
        if let Some(mappings) = mappings {
            row["encrypted_pii_mappings"] = json!(encrypted(mappings));
        }
        let mut seen = std::collections::HashSet::new();
        let (raw, decoded) =
            sync::decode_chat_message_stored(&row, id, &[7; 32], &mut seen).unwrap();
        let mut message = project_message(&raw, decoded, &[7; 32]).unwrap();
        assert_eq!(message.id, "storage-row");
        assert_eq!(message.client_message_id, logical);
        assert_eq!(message.content, "Stored [EMAIL_1]");
        assert_eq!(message.created_at, serde_json::Number::from(0));
        assert_eq!(message.sender_name.as_deref(), Some(""));
        assert_eq!(message.category.as_deref(), Some("science"));
        assert_eq!(
            message.model_name.as_deref(),
            Some("automatic-source-model")
        );
        assert_eq!(message.pii_mappings.is_some(), mappings.is_some());
        if mappings == Some("[]") {
            assert!(
                message
                    .pii_mappings
                    .as_ref()
                    .unwrap()
                    .encoded_json()
                    .unwrap()
                    == "[]"
            );
        }
        message.wipe();
        assert!(message.content.is_empty());
        assert!(
            !serde_json::to_string(&message)
                .unwrap()
                .contains("synthetic@example.invalid")
        );
    }
}
#[test]
fn raw_utf16_preview_retains_exact_split_unit_and_only_serializes_a_quoted_json_leaf() {
    let input = format!("{}😀", "a".repeat(199));
    let preview = draft_preview(&input).unwrap().unwrap();
    let units = preview.utf16_units().unwrap();
    assert_eq!(units.len(), 200);
    assert_eq!(units[199], 0xd83d);
    let expected = format!("\"{}\\ud83d\"", "a".repeat(199));
    assert_eq!(preview.encoded_json().unwrap(), expected);
    let decoded: ChatDetailsText = serde_json::from_str(&expected).unwrap();
    assert_eq!(decoded.encoded_json().unwrap(), expected);
    for bad in ["null", "[]", "{}", "4"] {
        assert!(serde_json::from_str::<ChatDetailsText>(bad).is_err());
    }
    let injected = draft_preview("\"},\"unsafe\":true")
        .unwrap()
        .unwrap()
        .encoded_json()
        .unwrap();
    assert_eq!(
        serde_json::from_str::<String>(&injected).unwrap(),
        "\"},\"unsafe\":true"
    );
    assert_eq!(
        draft_preview("\u{feff} Saved\t synthetic\n draft \u{feff}")
            .unwrap()
            .unwrap()
            .encoded_json()
            .and_then(|v| serde_json::from_str::<String>(&v).map_err(|_| Error::Protocol))
            .unwrap(),
        "Saved synthetic draft"
    );
}
#[test]
fn deserialized_rich_projection_never_manufactures_original_admission() {
    let fixture: Value =
        serde_json::from_str(include_str!("../../tests/fixtures/chat-details-read.json")).unwrap();
    let encoded = serde_json::to_string(&fixture["vectors"][0]["expected_details"]).unwrap();
    let read: ChatDetailsRead = serde_json::from_str(&encoded).unwrap();
    let client = Client::new("http://127.0.0.1:9", None).unwrap();
    assert!(matches!(read.check(&client), Err(Error::Forbidden)));
}
#[test]
fn raw_pii_leaf_keeps_null_presence_any_json_and_escaped_utf16() {
    for raw in [
        "null",
        r#"{"synthetic":"object"}"#,
        "3",
        "[]",
        r#"[null,3,"\ud83d"]"#,
    ] {
        let mut message = ChatDetailsMessage {
            pii_mappings: Some(ChatDetailsJson::from_text(raw.into()).unwrap()),
            ..Default::default()
        };
        let encoded = serde_json::to_string(&message).unwrap();
        assert!(encoded.contains("\"piiMappings\":"));
        let decoded: ChatDetailsMessage = serde_json::from_str(&encoded).unwrap();
        assert!(
            decoded.pii_mappings.as_ref().unwrap().value()
                == ChatDetailsJson::from_text(raw.into()).unwrap().value()
        );
        message.wipe();
        assert!(message.pii_mappings.is_none());
    }
    let message = ChatDetailsMessage::default();
    assert!(
        !serde_json::to_string(&message)
            .unwrap()
            .contains("piiMappings")
    );
    assert!(ChatDetailsJson::from_text("null,\"unsafe\":true".into()).is_err());
}
#[test]
fn memory_request_coalescing_keeps_first_row_metadata_and_exact_ordered_content() {
    let content = r#"{"type":"app_settings_memories_request","user_message_id":"user","request_id":"request","requested_keys":["notes-private"],"categories":[{"appId":"notes","itemType":"private","entryCount":0}]}"#;
    let second = r#"{"type":"app_settings_memories_request","user_message_id":"user","request_id":"request","requested_keys":["notes-private","profile-personal"],"categories":[{"appId":"notes","itemType":"private","entryCount":3},{"appId":"profile","itemType":"personal","entryCount":null}],"count_semantics_version":1}"#;
    let mut messages = vec![
        ChatDetailsMessage {
            id: "first-storage".into(),
            client_message_id: "request".into(),
            role: "system".into(),
            content: content.into(),
            ..Default::default()
        },
        ChatDetailsMessage {
            id: "second-storage".into(),
            client_message_id: "request-2".into(),
            role: "system".into(),
            content: second.into(),
            ..Default::default()
        },
    ];
    memory::coalesce(&mut messages).unwrap();
    assert_eq!(messages.len(), 1);
    assert_eq!(messages[0].id, "first-storage");
    assert_eq!(
        messages[0].content,
        r#"{"type":"app_settings_memories_request","user_message_id":"user","request_id":"request","requested_keys":["notes-private","profile-personal"],"categories":[{"appId":"notes","itemType":"private","entryCount":3},{"appId":"profile","itemType":"personal","entryCount":null}],"count_semantics_version":1}"#
    );
}

#[test]
fn active_focus_matches_optional_nonempty_truthy_projection_and_is_wiped() {
    for raw in [
        json!({}),
        json!({"encrypted_active_focus_id":null}),
        json!({"encrypted_active_focus_id":4}),
        json!({"encrypted_active_focus_id":""}),
        json!({"encrypted_active_focus_id":"corrupt"}),
        json!({"encrypted_active_focus_id":encrypted("")}),
    ] {
        assert!(active_focus(&raw, &[7; 32]).unwrap().is_none());
    }
    for value in ["focus-synthetic-selected", " ", "focus-雪"] {
        assert_eq!(
            active_focus(
                &json!({"encrypted_active_focus_id":encrypted(value)}),
                &[7; 32]
            )
            .unwrap()
            .as_deref(),
            Some(value)
        );
    }
    let mut metadata = ChatDetailsMetadata {
        active_focus_id: Some("focus-synthetic-selected".into()),
        ..Default::default()
    };
    assert!(
        serde_json::to_string(&metadata)
            .unwrap()
            .contains("activeFocusId")
    );
    metadata.wipe();
    assert!(metadata.active_focus_id.as_ref().unwrap().is_empty());
    assert!(
        !serde_json::to_string(&ChatDetailsMetadata::default())
            .unwrap()
            .contains("activeFocusId")
    );
}

#[test]
fn js_pii_numbers_and_decoded_duplicate_keys_have_two_faithful_output_boundaries() {
    let source = r#"[9007199254740993,1e400,-0,{"k":"discarded","k":"kept"}]"#;
    let value = ChatDetailsJson::from_text(source.into()).unwrap();
    let ChatDetailsJsonValue::Array(values) = value.value() else {
        panic!("array")
    };
    assert!(matches!(values[0],ChatDetailsJsonValue::Number(n) if n==9007199254740992.0));
    assert!(matches!(values[1],ChatDetailsJsonValue::Number(n) if n==f64::INFINITY));
    assert!(matches!(values[2],ChatDetailsJsonValue::Number(n) if n==0.0&&n.is_sign_negative()));
    let cli: Value = serde_json::from_str(&value.encoded_json().unwrap()).unwrap();
    assert_eq!(cli, json!([9007199254740992u64,null,0,{"k":"kept"}]));
    let sdk = ChatDetailsJson::from_text(value.sdk_encoded_json().unwrap()).unwrap();
    assert!(sdk.value() == value.value());
    assert!(value.sdk_encoded_json().unwrap().contains("1e400,-0.0"));
    // Source semantics, not original token preservation. Last duplicate wins.
    let ChatDetailsJsonValue::Object(keys) = &values[3] else {
        panic!("object")
    };
    assert_eq!(keys.len(), 1);
    assert_eq!(keys[0].0.utf16_units(), &[107]);
}
#[test]
fn js_pii_decoded_utf16_keys_last_win_and_index_keys_enumerate_first() {
    let value = ChatDetailsJson::from_text(
        r#"{"a":1,"\u0061":2,"2":3,"1":4,"4294967295":5,"01":6}"#.into(),
    )
    .unwrap();
    let ChatDetailsJsonValue::Object(keys) = value.value() else {
        panic!("object")
    };
    let decoded = keys
        .iter()
        .map(|(k, _)| String::from_utf16(k.utf16_units()).unwrap())
        .collect::<Vec<_>>();
    assert_eq!(decoded, vec!["1", "2", "a", "4294967295", "01"]);
    assert!(matches!(keys[2].1,ChatDetailsJsonValue::Number(n) if n==2.0));
    let value=ChatDetailsJson::from_text(r#"{"\ud83d":"discarded","\uD83D":"\udc00","😀":"first","\ud83d\ude00":"kept","literal":"\ud83d"}"#.into()).unwrap();
    let ChatDetailsJsonValue::Object(keys) = value.value() else {
        panic!("object")
    };
    assert_eq!(keys.len(), 3);
    assert_eq!(keys[0].0.utf16_units(), &[0xd83d]);
    let ChatDetailsJsonValue::String(v) = &keys[0].1 else {
        panic!("string")
    };
    assert_eq!(v.utf16_units(), &[0xdc00]);
    assert_eq!(keys[1].0.utf16_units(), &[0xd83d, 0xde00]);
    let encoded = value.encoded_json().unwrap();
    let parsed = ChatDetailsJson::from_text(encoded).unwrap();
    assert!(parsed.value() == value.value());
}
#[test]
fn js_number_layout_keeps_observable_integer_values_and_sdk_underflow_sign() {
    let input = r#"[1e20,1e21,1e-6,1e-7,1000000000000000100,0.1,5e-324,-1e400,-1e-400]"#;
    let expected =
        r#"[100000000000000000000,1e+21,0.000001,1e-7,1000000000000000100,0.1,5e-324,null,0]"#;
    let value = ChatDetailsJson::from_text(input.into()).unwrap();
    let actual: Value = serde_json::from_str(&value.encoded_json().unwrap()).unwrap();
    let expected: Value = serde_json::from_str(expected).unwrap();
    assert_eq!(actual, expected);
    let sdk = ChatDetailsJson::from_text(value.sdk_encoded_json().unwrap()).unwrap();
    assert!(sdk.value() == value.value());
    let ChatDetailsJsonValue::Array(values) = sdk.value() else {
        panic!("array")
    };
    assert!(matches!(values[7],ChatDetailsJsonValue::Number(n) if n==f64::NEG_INFINITY));
    assert!(matches!(values[8],ChatDetailsJsonValue::Number(n) if n==0.0&&n.is_sign_negative()));
}
#[test]
fn normalized_pii_never_changes_absence_null_or_original_admission_and_wipes() {
    let mut read = ChatDetailsRead::default();
    read.messages.push(ChatDetailsMessage {
        pii_mappings: Some(ChatDetailsJson::from_text("[1e400,-0]".into()).unwrap()),
        ..Default::default()
    });
    let cli: Value = serde_json::from_str(&serde_json::to_string(&read).unwrap()).unwrap();
    assert_eq!(cli["messages"][0]["piiMappings"], json!([null, 0]));
    let sdk = read.sdk_json().unwrap();
    let parsed: ChatDetailsRead = serde_json::from_str(&sdk).unwrap();
    let ChatDetailsJsonValue::Array(values) =
        parsed.messages[0].pii_mappings.as_ref().unwrap().value()
    else {
        panic!("array")
    };
    assert!(matches!(values[0],ChatDetailsJsonValue::Number(n) if n==f64::INFINITY));
    let client = Client::new("http://127.0.0.1:9", None).unwrap();
    assert!(matches!(parsed.check(&client), Err(Error::Forbidden)));
    read.wipe();
    assert!(read.messages[0].pii_mappings.is_none());
    assert!(
        ChatDetailsJson::from_text(format!("[{}0{}]", "[".repeat(128), "]".repeat(128))).is_err()
    );
    assert!(ChatDetailsJson::from_text(format!("\"{}\"", "a".repeat(256 * 1024))).is_err());
    for invalid in [
        "01",
        "NaN",
        "Infinity",
        r#"{"x":1} trailing"#,
        r#""\uXX00""#,
    ] {
        assert!(ChatDetailsJson::from_text(invalid.into()).is_err());
    }
}

#[test]
fn sdk_finite_number_wire_preserves_binary64_for_python_integer_boundaries() {
    let value =
        ChatDetailsJson::from_text("[1000000000000000100,9007199254740993,3]".into()).unwrap();
    let sdk = value.sdk_encoded_json().unwrap();
    let raw: Vec<&serde_json::value::RawValue> = serde_json::from_str(&sdk).unwrap();
    assert!(raw[0].get().contains('.') || raw[0].get().contains('e'));
    assert!(raw[1].get().contains('.') || raw[1].get().contains('e'));
    assert_eq!(raw[2].get(), "3");
    let actual: Vec<f64> = serde_json::from_str(&sdk).unwrap();
    assert_eq!(actual[0] as i128, 1000000000000000128);
    assert_eq!(actual[1] as i128, 9007199254740992);
    let cli_text = value.encoded_json().unwrap();
    let cli: Vec<&serde_json::value::RawValue> = serde_json::from_str(&cli_text).unwrap();
    assert_eq!(cli[0].get(), "1000000000000000100");
}


#[test]
fn compact_utf16_strings_match_independent_escape_units_in_preview_pii_and_keys() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/fixtures/chat-details-string-escaping.json"
    ))
    .unwrap();
    for vector in fixture["vectors"].as_array().unwrap() {
        let units = vector["utf16_units"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| u16::try_from(v.as_u64().unwrap()).unwrap())
            .collect::<Vec<_>>();
        let expected = vector["expected_json"].as_str().unwrap();
        let mut encoded = Zeroizing::new(String::new());
        json::write_utf16_string(&units, &mut encoded).unwrap();
        assert_eq!(&*encoded, expected, "{}", vector["id"]);
        assert_eq!(encoded.len() as u64, vector["expected_utf8_bytes"].as_u64().unwrap());
        assert!(encoded.len() <= 2 + 6 * units.len());
        let preview = ChatDetailsText { repr: TextRepr::Units(units.clone()) };
        assert_eq!(preview.encoded_json().unwrap(), expected);
        assert_eq!(preview.utf16_units().unwrap(), units);
        let leaf = ChatDetailsJson::from_text(expected.into()).unwrap();
        let ChatDetailsJsonValue::String(value) = leaf.value() else {
            panic!("independent string vector");
        };
        assert_eq!(value.utf16_units(), units);
        assert_eq!(leaf.encoded_json().unwrap(), expected);
        assert_eq!(leaf.sdk_encoded_json().unwrap(), expected);
        let object_source = format!("{{{expected}:1}}");
        let object = ChatDetailsJson::from_text(object_source.clone()).unwrap();
        assert_eq!(object.encoded_json().unwrap(), object_source);
        assert_eq!(object.sdk_encoded_json().unwrap(), object_source);
        let ChatDetailsJsonValue::Object(entries) = object.value() else {
            panic!("independent key vector");
        };
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].0.utf16_units(), units);
        assert!(matches!(entries[0].1, ChatDetailsJsonValue::Number(n) if n == 1.0));
    }
}

#[test]
fn compact_string_writer_keeps_bounds_failure_wiping_and_nonstring_semantics() {
    let mut output = Zeroizing::new("x".repeat(256 * 1024 * 6 + 2));
    assert!(json::write_utf16_string(&[97], &mut output).is_err());
    assert_eq!(output.len(), 256 * 1024 * 6 + 2);
    let mut output = Zeroizing::new("x".repeat(256 * 1024 * 6));
    assert!(json::write_utf16_string(&[0xd800], &mut output).is_err());
    assert!(output.len() <= 256 * 1024 * 6 + 2);
    let mut preview = draft_preview("Saved synthetic draft").unwrap().unwrap();
    assert_eq!(preview.encoded_json().unwrap().len(), 23);
    preview.wipe();
    assert!(preview.utf16_units().unwrap().is_empty());
    let value = ChatDetailsJson::from_text(
        r#"[null,false,3,1e400,-0,{"a":1,"\u0061":2}]"#.into()
    ).unwrap();
    assert_eq!(value.encoded_json().unwrap(), r#"[null,false,3,null,0,{"a":2}]"#);
    assert_eq!(value.sdk_encoded_json().unwrap(), r#"[null,false,3,1e400,-0.0,{"a":2}]"#);
    let mut value = value;
    value.wipe();
    let ChatDetailsJsonValue::Array(values) = value.value() else { panic!("array") };
    assert_eq!(values.len(), 6);
    assert!(matches!(values[3], ChatDetailsJsonValue::Number(n) if n == 0.0));
    assert!(matches!(values[4], ChatDetailsJsonValue::Number(n) if n == 0.0 && !n.is_sign_negative()));
    let ChatDetailsJsonValue::Object(entries) = &values[5] else { panic!("object") };
    assert_eq!(entries.len(), 1);
    assert!(entries[0].0.utf16_units().is_empty());
    assert!(matches!(entries[0].1, ChatDetailsJsonValue::Number(n) if n == 0.0));
}
#[test]
fn memory_response_rows_expose_the_mappings_stored_in_their_content() {
    let id = "22222222-2222-4222-8222-222222222222";
    let content = r#"{"type":"app_settings_memories_response","action":"included","pii_mappings":[{"placeholder":"[EMAIL_1]","original":"ada@example.org"}]}"#;
    let row = json!({"id":"sys-row","client_message_id":"sys","chat_id":id,"role":"system","created_at":0,"encrypted_content":encrypted(content),"encrypted_sender_name":encrypted(""),"encrypted_category":encrypted(""),"encrypted_model_name":encrypted("")});
    let mut seen = std::collections::HashSet::new();
    let (raw, decoded) = sync::decode_chat_message_stored(&row, id, &[7; 32], &mut seen).unwrap();
    let message = project_message(&raw, decoded, &[7; 32]).unwrap();
    let mappings = message.pii_mappings.as_ref().expect("response mappings");
    assert!(
        mappings
            .encoded_json()
            .unwrap()
            .contains("ada@example.org")
    );
}
#[test]
fn page_local_restoration_uses_memory_response_mappings() {
    let id = "22222222-2222-4222-8222-222222222222";
    let content = r#"{"type":"app_settings_memories_response","action":"included","pii_mappings":[{"placeholder":"[EMAIL_1]","original":"ada@example.org"}]}"#;
    let row = json!({"id":"sys-row","client_message_id":"sys","chat_id":id,"role":"system","created_at":0,"encrypted_content":encrypted(content),"encrypted_sender_name":encrypted(""),"encrypted_category":encrypted(""),"encrypted_model_name":encrypted("")});
    let mut seen = std::collections::HashSet::new();
    let (raw, decoded) = sync::decode_chat_message_stored(&row, id, &[7; 32], &mut seen).unwrap();
    let system = project_message(&raw, decoded, &[7; 32]).unwrap();
    let answer = "Reach me at [EMAIL_1].";
    let mut assistant = ChatDetailsMessage::default();
    assistant.role = "assistant".into();
    assistant.content = answer.into();
    let parsed = page_restore_mappings(&[system, assistant]).unwrap();
    let mappings = parsed.iter().filter_map(Value::as_array).flatten().collect::<Vec<_>>();
    let restored = crate::privacy::restore_page_refs(answer, &mappings).unwrap();
    assert_eq!(restored, "Reach me at ada@example.org.");
}
