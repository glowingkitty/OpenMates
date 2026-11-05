// Frozen shared TypeScript/backend layouts through the actual client readers.
// Included inside sync::tests to reuse its existing synthetic Client constructor.
// contract-test-file: tooling
fn legacy_layouts() -> Value {
    serde_json::from_str(include_str!(
        "../../tests/crypto_fixtures/encryption_compatibility/legacy_layouts.json")).unwrap()
}
fn legacy_key(data: &Value, name: &str) -> crypto::Key {
    crypto::decode_key(data["keys"][name].as_str().unwrap()).unwrap()
}
fn legacy_tampered(cipher: &str) -> String {
    use base64::Engine as _;
    let mut bytes = base64::engine::general_purpose::STANDARD.decode(cipher).unwrap();
    *bytes.last_mut().unwrap() ^= 1;
    base64::engine::general_purpose::STANDARD.encode(bytes)
}
fn legacy_chat_row(data: &Value) -> Value {
    json!({"id":"legacy-chat", "chat_key_wrappers":[{
        "key_type":"master", "hashed_chat_id":sha256("legacy-chat"),
        "encrypted_chat_key":data["chat"]["format_c"]["blob_b64"]
    }]})
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn frozen_c_unwrap_then_a_b_canonical_history_preserves_original_keys_and_ciphertext() {
    let data = legacy_layouts();
    let original_master = legacy_key(&data, "wrapping_key_b64");
    let mut c = client(None);
    c.session.as_mut().unwrap().master_key = original_master.clone();
    let row = legacy_chat_row(&data);
    c.chats.insert("legacy-chat".into(), row.clone());
    let before = c.ciphertext_snapshot();
    let selected = c.chat_key_ciphertext(&row, true).unwrap();
    assert_eq!(selected.ciphertext, data["chat"]["format_c"]["blob_b64"].as_str().unwrap());
    assert!(!selected.ambiguous);
    let key = c.chat_key(&row, &original_master).unwrap();
    assert_eq!(crypto::encode_key(&key), data["chat"]["format_c"]["plaintext_key_b64"].as_str().unwrap());
    assert_eq!(*key, *legacy_key(&data, "content_key_b64"));
    let rows = ["format_a", "format_b"].into_iter().map(|format| {
        json!({"client_message_id":format,"chat_id":"legacy-chat","role":"assistant",
            "encrypted_content":data["chat"][format]["blob_b64"]})
    }).collect::<Vec<_>>();
    let mut history = canonical_history::CanonicalHistory::new("legacy-chat");
    let page = history.decode_page(json!({"messages":rows,"has_more_before":false}), &key).unwrap();
    assert_eq!(page.decoded()[0].content, data["chat"]["format_a"]["plaintext"].as_str().unwrap());
    assert_eq!(page.decoded()[1].content, data["chat"]["format_b"]["plaintext"].as_str().unwrap());
    assert!(history.append_page(page).unwrap());
    let (messages, encrypted, terminal) = history.into_parts().unwrap();
    assert!(terminal);
    assert_eq!(messages.len(), 2);
    assert_eq!(encrypted, rows);
    assert_eq!(c.ciphertext_snapshot(), before);
    assert_eq!(*c.require_session().unwrap().master_key, *original_master);
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation
#[test]
fn frozen_a_b_c_client_readers_refuse_wrong_keys_tamper_and_foreign_wrapper_scope() {
    let data = legacy_layouts();
    let content = legacy_key(&data, "content_key_b64");
    let wrapping = legacy_key(&data, "wrapping_key_b64");
    let c = client(None);
    let row = legacy_chat_row(&data);
    assert!(matches!(c.chat_key(&row, &[99;32]), Err(Error::Crypto)));
    let mut tampered = row.clone();
    tampered["chat_key_wrappers"][0]["encrypted_chat_key"] = json!(legacy_tampered(data["chat"]["format_c"]["blob_b64"].as_str().unwrap()));
    assert!(matches!(c.chat_key(&tampered, &wrapping), Err(Error::Crypto)));
    let mut foreign = row.clone();
    foreign["chat_key_wrappers"][0]["hashed_chat_id"] = json!(sha256("other-chat"));
    assert!(c.chat_key(&foreign, &wrapping).is_err());
    for format in ["format_a", "format_b"] {
        let cipher = data["chat"][format]["blob_b64"].as_str().unwrap();
        let row = json!({"id":format,"chat_id":"legacy-chat","role":"assistant","encrypted_content":cipher});
        for (key, input) in [(&[99;32], row.clone()), (&*content, {
            let mut corrupted = row.clone();
            corrupted["encrypted_content"] = json!(legacy_tampered(cipher));
            corrupted
        })] {
            let mut history = canonical_history::CanonicalHistory::new("legacy-chat");
            assert!(matches!(history.decode_page(json!({"messages":[input],"has_more_before":false}), key), Err(Error::Crypto)));
            assert!(history.into_parts().is_err());
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[tokio::test]
async fn frozen_d_master_metadata_readers_keep_existing_master_and_refuse_corruption() {
    use crate::crypto::master::MasterCapability;
    let data = legacy_layouts();
    let key = legacy_key(&data, "wrapping_key_b64");
    let cipher = data["chat"]["format_d"]["blob_b64"].as_str().unwrap();
    let expected = data["chat"]["format_d"]["plaintext"].as_str().unwrap();
    for master in [MasterCapability::from_native(key.clone()), MasterCapability::from_browser_raw(key.clone())] {
        assert_eq!(master.decrypt_text(cipher).await.unwrap(), expected);
        assert_eq!(**master.native_key().unwrap(), *key);
        assert!(matches!(master.decrypt_text(&legacy_tampered(cipher)).await, Err(Error::Crypto)));
    }
    assert!(matches!(MasterCapability::from_native(zeroize::Zeroizing::new([99;32])).decrypt_text(cipher).await, Err(Error::Crypto)));
    assert_eq!(crypto::server_fields::decrypt_text(cipher, &key, &[]).unwrap(), expected);
    assert!(matches!(crypto::server_fields::decrypt_text(cipher, &[99;32], &[]), Err(Error::Crypto)));
    assert!(matches!(crypto::server_fields::decrypt_text(&legacy_tampered(cipher), &key, &[]), Err(Error::Crypto)));
}
