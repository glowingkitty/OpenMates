// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
use super::*;
use crate::Client;
use crate::account::imports_chat::parse_chat_import_payload;
use crate::account::imports_parse::*;
use crate::account::test_support::{mock, session};

fn body(request: &str) -> Value {
    serde_json::from_str(request.split("\r\n\r\n").nth(1).unwrap()).unwrap()
}

fn claude_export() -> String {
    json!({"conversations": [{
        "uuid": "conv-1", "name": "Trip", "created_at": "2024-01-01T00:00:00.000Z",
        "chat_messages": [
            {"uuid": "m1", "sender": "human", "content": [{"type": "text", "text": "Hi \"there\"\nä"}],
             "attachments": [{"file_name": "a.pdf", "file_size": 12, "file_type": "application/pdf"}]},
            {"uuid": "m2", "sender": "assistant", "content": [{"type": "tool_use"}], "text": "Hello"}
        ]
    }]})
    .to_string()
}

#[test]
fn claude_parser_matches_legacy_fingerprint_identity_and_uploads() {
    let parsed = parse_claude_import(&claude_export(), "claude.zip", ImportSource::Claude).unwrap();
    assert_eq!(parsed.source, ImportSource::Claude);
    let chat = &parsed.chats[0];
    // sha256 of JSON.stringify({provider, source_chat_id, messages[{role, source_message_id, content}]}).
    assert_eq!(
        chat.source_fingerprint,
        "d8dc213d62dd276958850209aff17c01fe86ab0a0459d9fb199cec8d5c8b3b07"
    );
    assert_eq!(chat.messages[0].role, "user");
    assert_eq!(chat.messages[0].imported_assistant_identity, None);
    assert_eq!(chat.messages[1].content, "Hello");
    assert_eq!(
        chat.messages[1].provider_metadata,
        json!({"content_block_types": ["tool_use"]})
    );
    assert_eq!(
        chat.messages[1]
            .imported_assistant_identity
            .as_ref()
            .unwrap()
            .sender_name,
        "Claude"
    );
    assert_eq!(chat.uploads[0].file_name, "a.pdf");
    assert_eq!(chat.uploads[0].source_upload_id, "a.pdf");
    assert_eq!(
        chat.uploads[0].mime_type.as_deref(),
        Some("application/pdf")
    );
    assert_eq!(chat.uploads[0].bytes, Some(json!(12)));
    assert_eq!(
        chat.source_metadata,
        json!({"source_name": "claude.zip", "message_count": 2})
    );
    // A user-selected source relabels assistants but keeps the parser fingerprint.
    let other = parse_claude_import(&claude_export(), "x", ImportSource::Other).unwrap();
    assert_eq!(other.chats[0].provider, "other");
    assert_eq!(other.chats[0].parser_format, "claude");
    assert_eq!(
        other.chats[0].messages[1]
            .imported_assistant_identity
            .as_ref()
            .unwrap()
            .avatar_key,
        "ai-star"
    );
    assert!(
        parse_claude_import("[{\"name\":\"x\"}]", "x", ImportSource::Claude)
            .unwrap_err()
            .contains("missing uuid")
    );
    assert!(
        parse_claude_import("{bad", "x", ImportSource::Claude)
            .unwrap_err()
            .starts_with("Claude export could not be parsed: ")
    );
    assert_eq!(
        parse_claude_import("{}", "x", ImportSource::Claude).unwrap_err(),
        "Claude export conversations must be an array"
    );
}

#[test]
fn chatgpt_parser_follows_the_active_branch_and_iso_timestamps() {
    let export = json!([{
        "id": "c1", "title": "T", "create_time": 1_700_000_000.5, "current_node": "n3",
        "mapping": {
            "n1": {"parent": null, "message": {"id": "a", "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["Hi"]}, "create_time": 1_700_000_000.123_4}},
            "n2": {"parent": "n1", "message": {"id": "b", "author": {"role": "assistant"}, "content": {"parts": ["discarded"]}}},
            "n3": {"parent": "n1", "message": {"id": "c", "author": {"role": "assistant"}, "content": {"content_type": "multimodal_text", "parts": ["Yo", {"asset_pointer": "x"}, "  "]}}},
            "n4": {"parent": "n3", "message": {"id": "d", "author": {"role": "tool"}, "content": {"parts": ["skip"]}}}
        }
    }]);
    let parsed =
        parse_chatgpt_import(&export.to_string(), "c.json", ImportSource::ChatGpt).unwrap();
    let chat = &parsed.chats[0];
    assert_eq!(chat.created_at.as_deref(), Some("2023-11-14T22:13:20.500Z"));
    assert_eq!(chat.updated_at, None);
    let texts: Vec<_> = chat.messages.iter().map(|m| m.content.as_str()).collect();
    assert_eq!(texts, ["Hi", "Yo"]);
    assert_eq!(
        chat.messages[0].created_at.as_deref(),
        Some("2023-11-14T22:13:20.123Z")
    );
    assert_eq!(
        chat.messages[1].provider_metadata,
        json!({"content_type": "multimodal_text", "asset_count": 1})
    );
    assert_eq!(iso_from_ms(0.0).unwrap(), "1970-01-01T00:00:00.000Z");
    assert!(
        parse_chatgpt_import("[{\"id\":\"x\"}]", "x", ImportSource::ChatGpt)
            .unwrap_err()
            .contains("missing mapping")
    );
}

#[test]
fn opencode_generic_and_openmates_parsers_keep_legacy_validation() {
    let opencode = json!({"info": {"id": "s1", "title": "Sess", "time": {"created": 1_700_000_000_000u64}},
    "messages": [
        {"info": {"id": "u", "role": "user", "time": {"created": 1_700_000_000_000u64}}, "parts": [{"type": "text", "text": "Fix it"}, {"type": "file"}]},
        {"info": {"id": "x", "role": "assistant"}, "parts": [{"type": "text", "text": "hidden", "ignored": true}]},
        {"info": {"role": "tool"}, "parts": [{"type": "text", "text": "no"}]}
    ]});
    let parsed =
        parse_opencode_import(&opencode.to_string(), "o.json", ImportSource::OpenCode).unwrap();
    assert_eq!(parsed.chats[0].messages.len(), 1);
    assert_eq!(
        parsed.chats[0].messages[0].provider_metadata,
        json!({"part_types": ["text", "file"], "text_part_count": 1})
    );
    assert_eq!(
        parsed.chats[0].created_at.as_deref(),
        Some("2023-11-14T22:13:20.000Z")
    );
    assert!(
        parse_opencode_import("{}", "o", ImportSource::OpenCode)
            .unwrap_err()
            .contains("missing info.id")
    );

    let generic = parse_generic_import(
        r#"{"messages":[{"role":"user","content":"One"}]}"#,
        "g",
        ImportSource::Gemini,
    )
    .unwrap();
    assert_eq!(generic.chats[0].source_chat_id, "generic-chat-1");
    assert_eq!(
        generic.chats[0].source_fingerprint,
        "2d1104ddab4141d6a9a7aea71735481c8ba2045ea45dce0e11d96599c7282d04"
    );
    assert_eq!(generic.chats[0].provider_labels, ["gemini", "generic"]);
    for (input, message) in [
        (
            r#"{"messages":[{"role":"user","content":"x","extra":1}]}"#,
            "Generic role/content message 1 contains unknown fields: extra",
        ),
        (
            r#"{"messages":[{"role":"tool","content":"x"}]}"#,
            "Generic role/content message 1 has unsupported role",
        ),
        (
            r#"{"messages":[{"role":"user","content":" "}]}"#,
            "Generic role/content message 1 requires non-empty string content",
        ),
        (
            r#"{"messages":[]}"#,
            "Generic role/content transcript messages must not be empty",
        ),
        (
            r#"{"messages":[{"role":"user","content":"x"}],"x":1}"#,
            "Generic role/content transcript contains unknown chat fields: x",
        ),
        (
            "[]",
            "Generic role/content transcript must be a chat object or array of chat objects with messages arrays",
        ),
    ] {
        assert_eq!(
            parse_generic_import(input, "g", ImportSource::Other).unwrap_err(),
            message
        );
    }
    assert!(
        parse_generic_import(r#"{"messages":[]}"#, "g", ImportSource::Claude)
            .unwrap_err()
            .contains("--source gemini")
    );

    let manifest = "format: openmates-account-export\nversion: 1\ndomains:\n  chats:\n    count: 1\n  usage:\n  settings:\nother: x\n";
    let names = vec![
        "manifest.yml".to_owned(),
        "chats/".to_owned(),
        "chats/abc.yml".to_owned(),
    ];
    let parsed =
        parse_openmates_import(Some(manifest), &names, "e.zip", ImportSource::OpenMates).unwrap();
    assert_eq!(parsed.skipped_domains, ["settings", "usage"]);
    assert_eq!(parsed.chats[0].source_chat_id, "abc");
    assert!(parsed.chats[0].messages.is_empty());
    assert!(
        parse_openmates_import(None, &names, "e", ImportSource::OpenMates)
            .unwrap_err()
            .contains("missing manifest.yml")
    );
    assert!(
        parse_openmates_import(Some("format: x\n"), &names, "e", ImportSource::OpenMates)
            .unwrap_err()
            .contains("format or version")
    );
    assert!(
        parse_openmates_import(Some(manifest), &names[..2], "e", ImportSource::OpenMates)
            .unwrap_err()
            .contains("no chat YAML")
    );
}

#[test]
fn batches_split_at_the_legacy_size_and_summaries_append() {
    let mut chat = parse_generic_import(
        r#"{"messages":[{"role":"user","content":"One"}]}"#,
        "g",
        ImportSource::Other,
    )
    .unwrap()
    .chats
    .remove(0);
    chat.messages = (0..251).map(|_| chat.messages[0].clone()).collect();
    let batches =
        build_account_import_message_batches(&[chat.clone()], ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE)
            .unwrap();
    assert_eq!(batches.len(), 2);
    assert_eq!(
        batches[1].batch_id,
        format!("scan-{}-1", &chat.source_fingerprint[..16])
    );
    assert_eq!(batches[1].chat.messages.len(), 1);
    append_compression_summary(&mut chat, Some("  "));
    assert_eq!(chat.messages.len(), 251);
    append_compression_summary(&mut chat, Some("Summary"));
    assert_eq!(
        chat.messages[251].provider_metadata,
        json!({"import_type": "compression_summary"})
    );
}

#[test]
fn import_chat_payload_parses_cli_yaml_and_json_shapes() {
    let yaml = "chat:\n  title: \"My chat\"\n  draft: null\nmessages:\n  -\n    role: user\n    content: |\n      line one\n      line two\n    completed_at: 12\n  -\n    role: assistant\n    content: Hi\n";
    let payload = parse_chat_import_payload(yaml).unwrap();
    let chat = &payload["chats"][0];
    assert_eq!(chat["title"], "My chat");
    assert_eq!(chat["messages"][0]["content"], "line one\nline two");
    assert_eq!(chat["messages"][0]["completed_at"], 12);
    assert_eq!(chat["messages"][1]["thinking"], Value::Null);
    let json_chat = parse_chat_import_payload(
        r#"{"chat":{"title":"T"},"messages":[{"role":"user","content":"x","timestamp":"t"}]}"#,
    )
    .unwrap();
    assert_eq!(json_chat["chats"][0]["messages"][0]["completed_at"], "t");
    assert_eq!(
        parse_chat_import_payload("[{\"a\":1}]").unwrap(),
        json!({"chats":[{"a":1}]})
    );
    assert_eq!(
        parse_chat_import_payload("  ").unwrap_err(),
        "Import file is empty."
    );
    assert_eq!(
        parse_chat_import_payload("{\"x\":1}").unwrap_err(),
        "JSON import must contain a chats array, a chat object, or messages."
    );
    assert_eq!(
        parse_chat_import_payload("chat:\n  title: x\n").unwrap_err(),
        "Import YAML did not contain any messages."
    );
}

#[tokio::test]
async fn import_runs_cursor_checked_batches_and_encrypts_personal_chats() {
    let parsed = parse_claude_import(&claude_export(), "c", ImportSource::Claude).unwrap();
    let fp = parsed.chats[0].source_fingerprint.clone();
    let batch = format!("scan-{}-0", &fp[..16]);
    let sanitized = json!({"messages": [
        {"role": "user", "content": "Hi [redacted]", "provider_metadata": {}},
        {"role": "assistant", "content": "Hello", "imported_assistant_identity": ImportSource::Claude.identity()}
    ]});
    let (api, server) = mock(vec![
        (200, json!({"import_id": "imp-1", "default_selection_count": 5, "max_batch_count": 1, "can_import": true})),
        (200, json!({"status": "confirmed"})),
        (200, json!({"last_scan_sequence": -1, "last_compression_sequence": -1})),
        (200, json!({"status": "acknowledged", "sequence": 0, "batch_id": batch, "chats": [sanitized]})),
        (200, json!({"last_scan_sequence": 0})),
        (200, json!({"status": "acknowledged", "sequence": 0, "summary": "Earlier context"})),
        (200, json!({"last_compression_sequence": 0})),
        (200, json!({"imported_chat_ids": ["new-chat"], "encrypted_record_counts": {"chats": 1, "messages": 3}})),
        (200, json!({"status": "complete", "imported_count": 1})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, None))).unwrap();
    let plan = client
        .account()
        .preview_account_import(&parsed, false)
        .await
        .unwrap();
    assert_eq!(plan.selected_count, 1);
    assert_eq!(plan.result["parsed"]["source_fingerprints"], json!([fp]));
    let result = client
        .account()
        .run_account_import(&parsed, &plan)
        .await
        .unwrap();
    assert_eq!(result["import_id"], "imp-1");
    assert_eq!(result["complete"]["status"], "complete");
    let requests = server.await.unwrap();
    assert!(requests[0].starts_with("POST /v1/account-imports/preview "));
    assert_eq!(body(&requests[0])["estimated_tokens_by_chat"], json!([5]));
    assert!(requests[3].starts_with("POST /v1/account-imports/imp-1/scan "));
    assert_eq!(body(&requests[3])["final_batch"], true);
    assert!(requests[5].starts_with("POST /v1/account-imports/imp-1/compress "));
    assert_eq!(
        body(&requests[5])["sanitized_messages"][0]["content"],
        "Hi [redacted]"
    );
    assert!(requests[7].starts_with("POST /v1/account-imports/imp-1/persist-encrypted "));
    let persisted = body(&requests[7]);
    let encrypted = &persisted["chats"][0];
    assert!(!requests[7].contains("Hi [redacted]") && !requests[7].contains("Earlier context"));
    let key =
        crypto::decrypt_bytes(encrypted["encrypted_chat_key"].as_str().unwrap(), &[7; 32]).unwrap();
    let key: [u8; 32] = key.as_slice().try_into().unwrap();
    let open = |v: &Value| crypto::decrypt_combined(v.as_str().unwrap(), &key).unwrap();
    assert_eq!(open(&encrypted["encrypted_title"]), "Trip");
    let rows = encrypted["messages"].as_array().unwrap();
    assert_eq!(open(&rows[0]["encrypted_content"]), "Hi [redacted]");
    assert_eq!(open(&rows[1]["encrypted_model_name"]), "Claude");
    assert_eq!(rows[1]["user_message_id"], rows[0]["message_id"]);
    assert_eq!(open(&rows[2]["encrypted_category"]), "compression_summary");
    assert_eq!(open(&rows[2]["encrypted_content"]), "Earlier context");
    assert_eq!(encrypted["created_at"], 1_704_067_200);
    let complete = body(&requests[8]);
    assert_eq!(complete["imported_chat_ids"], json!(["new-chat"]));
    assert_eq!(complete["client_failures"], json!([]));
}

#[tokio::test]
async fn import_stops_on_resume_state_and_unacknowledged_scans() {
    let parsed = parse_generic_import(
        r#"{"messages":[{"role":"user","content":"One"}]}"#,
        "g",
        ImportSource::Other,
    )
    .unwrap();
    let (api, server) = mock(vec![
        (
            200,
            json!({"import_id": "imp-2", "default_selection_count": 1, "can_import": true}),
        ),
        (200, json!({})),
        (200, json!({"last_scan_sequence": 0})),
    ])
    .await;
    let mut client = Client::new(&api, Some(session(&api, None))).unwrap();
    let plan = client
        .account()
        .preview_account_import(&parsed, true)
        .await
        .unwrap();
    assert_eq!(plan.selected_count, 1);
    let error = client
        .account()
        .run_account_import(&parsed, &plan)
        .await
        .unwrap_err();
    assert_eq!(
        error,
        Error::Invalid("Resuming this import requires the client-held sanitized batch state.")
    );
    assert_eq!(server.await.unwrap().len(), 3);
    let blocked = AccountImportPlan {
        result: json!({"preview": {"can_import": false, "reason": "limit"}}),
        selected_count: 1,
    };
    assert!(!blocked.can_import());
    assert_eq!(blocked.blocked_reason(), "limit");
}
