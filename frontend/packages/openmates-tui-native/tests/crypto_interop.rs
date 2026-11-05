//! Synthetic account vectors plus the shared browser/CLI/backend recovery vectors.
use base64::{
    Engine as _,
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
};
use openmates::crypto::*;
use serde_json::{Value, json};

fn fixture() -> Value {
    serde_json::from_str(include_str!("crypto_fixtures/account.json")).unwrap()
}
fn text<'a>(value: &'a Value, field: &str) -> &'a str {
    value[field].as_str().unwrap()
}

#[test]
fn shared_account_password_and_proof_vectors() {
    // contract-test: supporting surface=cli assertions=auth.password.versioned-protection,auth.signup.current-flow
    let f = fixture();
    assert_eq!(
        hash_email("user@example.com"),
        "tMmiiTI7IaAcPpQPFQ65uMVCWH8av9jw4cwf/F5HVRQ="
    );
    assert_eq!(
        hash_key("correct horse", &[1, 2, 3, 4]).unwrap(),
        "0hJvnJrn389Ik7M3OR+qOZl6NBsSet72zG2p4yy6GwE="
    );
    assert_eq!(
        derive_email_key(text(&f, "email"), text(&f, "email_salt")).unwrap(),
        text(&f, "email_key")
    );
    let salt = STANDARD.decode(text(&f, "password_v2_salt")).unwrap();
    let (auth, wrap) = derive_password_keys_v2(text(&f, "password_v2"), &salt).unwrap();
    assert_eq!(
        URL_SAFE_NO_PAD.encode(auth.as_ref()),
        text(&f, "auth_key_v2")
    );
    assert_eq!(
        URL_SAFE_NO_PAD.encode(wrap.as_ref()),
        text(&f, "wrap_key_v2")
    );
    assert_eq!(
        password_proof_v2(&auth, text(&f, "nonce_v2"), "login").unwrap(),
        text(&f, "login_proof_v2")
    );
    assert!(password_proof_v2(&auth, text(&f, "nonce_v2"), "LOGIN").is_err());
    assert!(password_proof_v2(&auth, &format!("{}=", text(&f, "nonce_v2")), "login").is_err());
    assert!(derive_password_keys_v2("password", &[0; 8]).is_err());
    let master = unwrap_password_master_key(
        text(&f, "legacy_password"),
        1,
        text(&f, "legacy_wrapped_master"),
        text(&f, "legacy_salt"),
        text(&f, "iv"),
    )
    .unwrap();
    assert_eq!(encode_key(&master), text(&f, "legacy_master"));
    let master_v2 = unwrap_password_master_key(
        text(&f, "password_v2"),
        2,
        text(&f, "password_v2_wrapped_master"),
        text(&f, "password_v2_salt"),
        text(&f, "iv"),
    )
    .unwrap();
    assert_eq!(encode_key(&master_v2), text(&f, "legacy_master"));
    assert!(
        unwrap_password_master_key(
            "wrong",
            1,
            text(&f, "legacy_wrapped_master"),
            text(&f, "legacy_salt"),
            text(&f, "iv")
        )
        .is_err()
    );
    assert!(
        unwrap_password_master_key(
            text(&f, "legacy_password"),
            3,
            text(&f, "legacy_wrapped_master"),
            text(&f, "legacy_salt"),
            text(&f, "iv")
        )
        .is_err()
    );
}

#[test]
fn independent_aes_combined_embed_and_slug_vectors() {
    let f = fixture();
    let key = decode_key(text(&f, "key")).unwrap();
    assert_eq!(
        decrypt_combined(text(&f, "combined"), &key).unwrap(),
        text(&f, "plaintext")
    );
    assert_eq!(
        decrypt_combined(text(&f, "om_combined"), &key).unwrap(),
        text(&f, "plaintext")
    );
    assert_eq!(
        encode_key(&derive_embed_key(&key, text(&f, "embed_id")).unwrap()),
        text(&f, "embed_key")
    );
    assert_eq!(
        object_slug_lookup_hash(text(&f, "slug"), &key).unwrap(),
        text(&f, "slug_lookup_hash")
    );
    assert_eq!(
        normalize_object_slug("  L'été — Déjà Vu  ").unwrap(),
        "lete-deja-vu"
    );
    assert!(normalize_object_slug("❄").is_err());
    assert!(decode_key("malformed").is_err());
    let raw = [0, 255, 128, 1, 0, 0];
    assert_eq!(
        decrypt_bytes(&encrypt_bytes(&raw, &key).unwrap(), &key)
            .unwrap()
            .as_slice(),
        raw
    );
    let encrypted = encrypt_combined(text(&f, "plaintext"), &key).unwrap();
    let second = encrypt_combined(text(&f, "plaintext"), &key).unwrap();
    assert_ne!(encrypted, second);
}

#[test]
fn authenticated_ciphertext_rejects_tamper_wrong_keys_and_headers() {
    let f = fixture();
    let key = decode_key(text(&f, "key")).unwrap();
    let mut bytes = STANDARD.decode(text(&f, "om_combined")).unwrap();
    bytes[2] ^= 1; // Header tampering must fail even though AES ciphertext is valid.
    assert!(decrypt_bytes(&STANDARD.encode(&bytes), &key).is_err());
    let mut bytes = STANDARD.decode(text(&f, "om_combined")).unwrap();
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    assert!(decrypt_bytes(&STANDARD.encode(&bytes), &key).is_err());
    assert!(decrypt_bytes(text(&f, "combined"), &[42; 32]).is_err());
    assert!(decrypt_bytes(text(&f, "om_combined"), &[42; 32]).is_err());
    for len in 0..34 {
        assert!(decrypt_bytes(&STANDARD.encode(vec![0u8; len]), &key).is_err());
    }
}

#[test]
fn shared_browser_cli_backend_recovery_vectors_and_identity_binding() {
    // contract-test: supporting surface=cli assertions=chats.completion.recovery-takeover
    let fixture: Value = serde_json::from_str(include_str!(
        "crypto_fixtures/chat_completion_recovery_vectors.json"
    ))
    .unwrap();
    for f in fixture["vectors"].as_array().unwrap() {
        let key = decode_key(text(f, "chat_key")).unwrap();
        let version = f["key_version"].as_u64().unwrap() as u32;
        let keys = recovery_keypair(&key, text(f, "chat_id"), version).unwrap();
        assert_eq!(
            URL_SAFE_NO_PAD.encode(keys.private_key.as_ref()),
            text(f, "recovery_private_key")
        );
        assert_eq!(keys.public_key, text(f, "recovery_public_key"));
        let mut identity = RecoveryIdentity {
            owner_id: text(f, "owner_id").into(),
            chat_id: text(f, "chat_id").into(),
            turn_id: text(f, "turn_id").into(),
            job_id: text(f, "job_id").into(),
            assistant_message_id: text(f, "assistant_message_id").into(),
            key_version: version,
        };
        assert_eq!(
            URL_SAFE_NO_PAD.encode(recovery_associated_data(&identity).unwrap()),
            text(f, "associated_data")
        );
        assert_eq!(
            open_recovery_envelope(&f["envelope"], &keys.private_key, &identity)
                .unwrap()
                .as_slice(),
            text(f, "plaintext").as_bytes()
        );
        identity.key_version += 1;
        assert!(open_recovery_envelope(&f["envelope"], &keys.private_key, &identity).is_err());
        identity.key_version -= 1;
        for name in ["epk", "nonce", "ciphertext"] {
            let mut envelope = f["envelope"].clone();
            let mut raw = URL_SAFE_NO_PAD.decode(text(&envelope, name)).unwrap();
            raw[0] ^= 1;
            envelope[name] = json!(URL_SAFE_NO_PAD.encode(raw));
            assert!(open_recovery_envelope(&envelope, &keys.private_key, &identity).is_err());
        }
        let mut extra = f["envelope"].clone();
        extra["extra"] = json!(true);
        assert!(open_recovery_envelope(&extra, &keys.private_key, &identity).is_err());
        let mut low_order = f["envelope"].clone();
        low_order["epk"] = json!(URL_SAFE_NO_PAD.encode([0u8; 32]));
        assert!(open_recovery_envelope(&low_order, &keys.private_key, &identity).is_err());
    }
}
