//! Personal Memory document records: web `ruleDocumentService.ts` plaintext
//! layout, carry-through of unrelated settings, refusals and the TS Format D
//! master-key fixture (`tests/crypto_fixtures/ts_web_formats.json`).
use super::*;

const DOC: &str = "---\ntitle: Career profile\nwhen_to_use: When writing applications.\nload_mode: ask_first\n---\n\nSenior Rust engineer in Berlin.\n";
const DOC2: &str = "---\ntitle: Career profile\nwhen_to_use: When writing applications.\n---\n\nStaff Rust engineer in Berlin.\n";

fn ids(documents: &[PersonalMemoryDocument]) -> Vec<&str> {
    documents.iter().map(|d| d.id.as_str()).collect()
}

#[test]
fn create_on_empty_settings_writes_the_web_record_layout() {
    let change = write_memory_plaintext(None, "personal:a", DOC, MemoryWriteMode::Create).unwrap();
    assert!(change.previous.is_none());
    let expected = format!(
        "{{\"memory_documents\":[{{\"id\":\"personal:a\",\"document\":{}}}]}}",
        serde_json::to_string(DOC).unwrap()
    );
    assert_eq!(change.plaintext.as_str(), expected);
    let back = decode_memory_documents(Some(&change.plaintext)).unwrap();
    assert_eq!(ids(&back), ["personal:a"]);
    assert_eq!(back[0].document.as_str(), DOC);
}

#[test]
fn update_keeps_unrelated_settings_and_merges_legacy_entries_like_the_web_client() {
    // A literal, not `json!`: serde_json sorts keys, and this test pins the stored order.
    let settings = format!(
        "{{\"theme\":\"dark\",\"rule_documents\":[{{\"id\":\"personal:old\",\"document\":{}}}],\"message_bookmarks\":{{\"version\":1,\"chats\":{{}}}}}}",
        serde_json::to_string(DOC).unwrap()
    );
    let change = write_memory_plaintext(
        Some(&settings),
        "personal:old",
        DOC2,
        MemoryWriteMode::Update,
    )
    .unwrap();
    assert_eq!(change.previous.as_deref().map(String::as_str), Some(DOC));
    // JSON.stringify order: existing keys untouched in place, the canonical key appended.
    let expected = format!(
        "{{\"theme\":\"dark\",\"rule_documents\":[{{\"id\":\"personal:old\",\"document\":{}}}],\"message_bookmarks\":{{\"version\":1,\"chats\":{{}}}},\"memory_documents\":[{{\"id\":\"personal:old\",\"document\":{}}}]}}",
        serde_json::to_string(DOC).unwrap(),
        serde_json::to_string(DOC2).unwrap()
    );
    assert_eq!(change.plaintext.as_str(), expected);
    let back = decode_memory_documents(Some(&change.plaintext)).unwrap();
    assert_eq!(back.len(), 1);
    assert_eq!(back[0].document.as_str(), DOC2);
}

#[test]
fn delete_removes_the_id_from_both_keys_and_returns_its_document() {
    let settings = json!({"rule_documents":[{"id":"personal:a","document":DOC}],
        "memory_documents":[{"id":"personal:a","document":DOC2},{"id":"personal:b","document":DOC}]})
    .to_string();
    let change = delete_memory_plaintext(Some(&settings), "personal:a").unwrap();
    assert_eq!(change.previous.as_deref().map(String::as_str), Some(DOC2));
    let value: Value = serde_json::from_str(&change.plaintext).unwrap();
    assert_eq!(value["rule_documents"], json!([]));
    assert_eq!(
        value["memory_documents"],
        json!([{"id":"personal:b","document":DOC}])
    );
    assert!(matches!(
        delete_memory_plaintext(Some(&change.plaintext), "personal:a"),
        Err(MemoryDocumentError::NotFound)
    ));
}

#[test]
fn refuses_missing_existing_invalid_and_oversized_writes_with_web_codes() {
    let one = json!({"memory_documents":[{"id":"personal:a","document":DOC}]}).to_string();
    let update = write_memory_plaintext(Some(&one), "personal:x", DOC, MemoryWriteMode::Update);
    assert_eq!(update.err().map(|e| e.code()), Some("rule_not_found"));
    let create = write_memory_plaintext(Some(&one), "personal:a", DOC, MemoryWriteMode::Create);
    assert_eq!(create.err().map(|e| e.code()), Some("rule_exists"));
    for bad in [
        "no frontmatter",
        "---\nwhen_to_use: x\n---\nbody",
        "---\ntitle: x\nsecret: y\n---\nbody",
        "---\ntitle: x\n---\n  ",
    ] {
        let result = write_memory_plaintext(None, "personal:n", bad, MemoryWriteMode::Create);
        assert_eq!(
            result.err().map(|e| e.code()),
            Some("invalid_rule_document"),
            "{bad:?}"
        );
    }
    let full: Vec<Value> = (0..24)
        .map(|i| json!({"id": format!("personal:{i}"), "document": DOC}))
        .collect();
    let full = json!({ "memory_documents": full }).to_string();
    let result = write_memory_plaintext(Some(&full), "personal:new", DOC, MemoryWriteMode::Create);
    assert_eq!(result.err().map(|e| e.code()), Some("rule_catalog_limit"));
    let extra =
        json!({"memory_documents":[{"id":"personal:a","document":DOC,"source":"personal"}]})
            .to_string();
    assert_eq!(
        decode_memory_documents(Some(&extra))
            .err()
            .map(|e| e.code()),
        Some("invalid_rule_document")
    );
    assert_eq!(
        decode_memory_documents(Some("[]")).err().map(|e| e.code()),
        Some("rule_settings_unavailable")
    );
}

#[test]
fn server_canonical_documents_are_accepted() {
    // Shape of backend memory_document.build_memory_document (yaml.safe_dump).
    let document = "---\ntitle: 'Job search: profile'\nwhen_to_use: Use for CVs.\nload_mode: ask_first\nvalid_until: '2027-01-31'\n---\n\n- Rust\n- Berlin\n";
    validate_memory_document(document).unwrap();
    validate_memory_document(&format!("\u{FEFF}{document}")).unwrap();
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[tokio::test]
async fn ts_format_d_settings_round_trip_through_a_memory_write() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../tests/crypto_fixtures/ts_web_formats.json"
    ))
    .unwrap();
    let key = crate::crypto::decode_key(fixture["keys"]["master_b64"].as_str().unwrap()).unwrap();
    let case = fixture["master_text"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["plaintext"].as_str().unwrap().starts_with('{'))
        .unwrap();
    let master = MasterCapability::from_native(key.clone());
    let prepared = prepare_memory_write(
        &master,
        case["ciphertext"].as_str(),
        "personal:a",
        DOC,
        MemoryWriteMode::Create,
    )
    .await
    .unwrap();
    // Format D: base64(IV || ciphertext || tag), no native framing header.
    let raw = base64::Engine::decode(
        &base64::engine::general_purpose::STANDARD,
        &prepared.encrypted_settings,
    )
    .unwrap();
    let plaintext =
        crate::crypto::server_fields::decrypt_text(&prepared.encrypted_settings, &key, &[])
            .unwrap();
    assert_eq!(raw.len(), 12 + plaintext.len() + 16);
    let mut expected: Value = serde_json::from_str(case["plaintext"].as_str().unwrap()).unwrap();
    expected["memory_documents"] = json!([{"id":"personal:a","document":DOC}]);
    assert_eq!(serde_json::from_str::<Value>(&plaintext).unwrap(), expected);
    let listed = read_memory_documents(&master, Some(&prepared.encrypted_settings))
        .await
        .unwrap();
    assert_eq!(ids(&listed), ["personal:a"]);
    let wrong = MasterCapability::from_native(
        crate::crypto::decode_key(fixture["keys"]["chat_key_b64"].as_str().unwrap()).unwrap(),
    );
    assert!(matches!(
        read_memory_documents(&wrong, Some(&prepared.encrypted_settings)).await,
        Err(MemoryDocumentError::SettingsUnavailable)
    ));
}
