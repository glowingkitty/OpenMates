use super::*;
use serde_json::Value;

const FIXTURE: &str = include_str!("../../tests/crypto_fixtures/ts_hidden_chat_lifecycle.json");

fn fixture() -> Value {
    serde_json::from_str(FIXTURE).unwrap()
}
fn bytes(value: &Value) -> Vec<u8> {
    STANDARD.decode(value.as_str().unwrap()).unwrap()
}
fn key(value: &Value) -> [u8; 32] {
    bytes(value).try_into().unwrap()
}
fn text(value: &Value) -> &str {
    value.as_str().unwrap()
}
fn stored_keys(f: &Value) -> Vec<String> {
    f["stored_chats"]
        .as_array()
        .unwrap()
        .iter()
        .map(|c| text(&c["encrypted_chat_key"]).to_owned())
        .collect()
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[test]
fn ts_hide_wrappers_derive_and_rewrap_byte_for_byte() {
    let f = fixture();
    let master = key(&f["keys"]["master_b64"]);
    let salt = bytes(&f["keys"]["email_salt_b64"]);
    let chat_key = key(&f["keys"]["chat_key_b64"]);
    for case in f["codes"].as_array().unwrap() {
        let code = text(&case["code"]);
        assert!(valid_code(code), "{code}");
        let secret = derive_secret(&master, code, &salt).unwrap();
        assert_eq!(
            secret.as_slice(),
            key(&case["combined_secret_b64"]).as_slice(),
            "{}",
            case["label"]
        );
        let wrapped = text(&case["encrypted_chat_key"]);
        assert_eq!(
            unwrap_chat_key(wrapped, &secret).unwrap().as_slice(),
            chat_key.as_slice()
        );
        // Same IV => identical wrapper: the Rust writer is the deployed TS format.
        let iv: [u8; 12] = STANDARD.decode(wrapped).unwrap()[..12].try_into().unwrap();
        assert_eq!(wrap_with_iv(&chat_key, &secret, &iv).unwrap(), wrapped);
        // Random-IV wrappers open with the TS-derived secret too.
        let fresh = wrap_chat_key(&chat_key, &key(&case["combined_secret_b64"])).unwrap();
        assert_ne!(fresh, wrapped);
        assert_eq!(
            unwrap_chat_key(&fresh, &secret).unwrap().as_slice(),
            chat_key.as_slice()
        );
        // The PBKDF2 input the browser feeds WebCrypto is base64(master || utf8(code)).
        let mut raw = master.to_vec();
        raw.extend_from_slice(code.as_bytes());
        assert_eq!(
            combined_secret_input(&master, code).unwrap().as_str(),
            STANDARD.encode(raw)
        );
    }
    for code in f["invalid_codes"].as_array().unwrap() {
        let code = text(code);
        assert!(
            !valid_code(code)
                && derive_secret(&master, code, &salt).is_err()
                && combined_secret_input(&master, code).is_err()
        );
    }
    assert_eq!(hidden_salt(&salt).unwrap(), &salt[..16]);
    assert!(hidden_salt(&[]).is_err());
}

fn class_label(class: &ChatKeyClass) -> (&'static str, Option<String>) {
    match class {
        ChatKeyClass::Normal(k) => ("normal", Some(STANDARD.encode(k.as_slice()))),
        ChatKeyClass::Hidden(k) => ("hidden", Some(STANDARD.encode(k.as_slice()))),
        ChatKeyClass::LockedCandidate => ("locked_candidate", None),
    }
}

async fn assert_classes(
    vault: &HiddenChatVault,
    master: &MasterCapability,
    f: &Value,
    expected: &str,
) {
    let stored: Vec<&Value> = f["stored_chats"].as_array().unwrap().iter().collect();
    for want in f[expected].as_array().unwrap() {
        let row = stored
            .iter()
            .find(|c| c["chat_id"] == want["chat_id"])
            .unwrap();
        let got = vault
            .classify(master, text(&row["encrypted_chat_key"]))
            .await
            .unwrap();
        let (label, chat_key) = class_label(&got);
        assert_eq!(
            label,
            text(&want["class"]),
            "{expected} {}",
            want["chat_id"]
        );
        assert_eq!(chat_key.as_deref(), want["chat_key_b64"].as_str());
    }
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[tokio::test]
async fn ts_classification_unlock_counts_and_unhide_match_the_web_service() {
    let f = fixture();
    let raw = key(&f["keys"]["master_b64"]);
    let master = MasterCapability::from_browser_raw(Zeroizing::new(raw));
    let salt = bytes(&f["keys"]["email_salt_b64"]);
    let keys = stored_keys(&f);
    let mut vault = HiddenChatVault::new();
    assert_classes(&vault, &master, &f, "locked_classification").await;
    assert!(matches!(
        vault
            .plan_hide(&master, None, Some(&keys[0]))
            .await
            .unwrap(),
        HidePlan::NeedsUnlock
    ));
    assert_eq!(
        vault.unhide(&master, &keys[0]).await.err(),
        Some(Error::Locked)
    );

    let count = vault
        .unlock(&master, &raw, text(&f["unlock"]["code"]), &salt, &keys, 0)
        .await
        .unwrap();
    assert_eq!(
        count as u64,
        f["unlock"]["decrypted_count"].as_u64().unwrap()
    );
    assert_classes(&vault, &master, &f, "unlocked_classification").await;

    // Unhide: the TS master re-wrap opens in Rust and the Rust re-wrap is the
    // same Format C layout the TS reader opens (IV || AES-GCM(master, key)).
    let unhide = &f["unhide"];
    let source = text(&unhide["source_encrypted_chat_key"]);
    let chat_key = key(&f["keys"]["chat_key_b64"]);
    assert_eq!(
        master
            .decrypt_bytes(text(&unhide["encrypted_chat_key"]))
            .await
            .unwrap()
            .as_slice(),
        chat_key.as_slice()
    );
    let rewrapped = vault.unhide(&master, source).await.unwrap();
    assert_eq!(rewrapped.chat_key.as_slice(), chat_key.as_slice());
    let combined = STANDARD.decode(&rewrapped.encrypted_chat_key).unwrap();
    assert_eq!(combined.len(), 12 + 32 + 16, "Format C, never OM framed");
    let opened = crypto::decrypt_aead(&combined[12..], &raw, &combined[..12], &[]).unwrap();
    assert_eq!(opened.as_slice(), chat_key.as_slice());
    assert!(matches!(
        vault
            .classify(&master, &rewrapped.encrypted_chat_key)
            .await
            .unwrap(),
        ChatKeyClass::Normal(_)
    ));

    // Hide plans: cached key, normal stored key, already hidden, missing key.
    let normal = text(
        &f["stored_chats"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["chat_id"] == "normal")
            .unwrap()["encrypted_chat_key"],
    )
    .to_owned();
    let HidePlan::Hide {
        encrypted_chat_key,
        decrypted_chat_key,
    } = vault.plan_hide(&master, None, Some(&normal)).await.unwrap()
    else {
        panic!("normal chats hide");
    };
    let expected_normal = key(&f["keys"]["normal_chat_key_b64"]);
    assert_eq!(
        decrypted_chat_key.unwrap().as_slice(),
        expected_normal.as_slice()
    );
    assert_eq!(
        vault.unwrap(&encrypted_chat_key).unwrap().as_slice(),
        expected_normal.as_slice()
    );
    let HidePlan::Hide {
        decrypted_chat_key: None,
        ..
    } = vault
        .plan_hide(&master, Some(&chat_key), None)
        .await
        .unwrap()
    else {
        panic!("cached keys hide without decrypting");
    };
    assert!(matches!(
        vault.plan_hide(&master, None, Some(source)).await.unwrap(),
        HidePlan::AlreadyHidden
    ));
    assert!(matches!(
        vault
            .plan_hide(&master, None, Some(&keys[1]))
            .await
            .unwrap(),
        HidePlan::MissingKey
    ));
    assert!(matches!(
        vault.plan_hide(&master, None, Some("")).await.unwrap(),
        HidePlan::MissingKey
    ));

    vault.lock();
    assert!(!vault.is_unlocked() && vault.unwrap(source).is_none());
    let verified = &f["verified_unlock"];
    let count = vault
        .unlock(&master, &raw, text(&verified["code"]), &salt, &keys, 0)
        .await
        .unwrap();
    assert_eq!(count, 0);
    vault.lock();
    vault.admit_unlock(text(&verified["code"]), 0).unwrap();
    let secret = derive_secret(&raw, text(&verified["code"]), &salt).unwrap();
    let count = vault
        .complete_unlock(
            &master,
            secret,
            &keys,
            verified["verified_encrypted_chat_key"].as_str(),
            0,
        )
        .await
        .unwrap();
    assert_eq!(count as u64, verified["decrypted_count"].as_u64().unwrap());
    vault.lock();
    let zero = vault
        .unlock(
            &master,
            &raw,
            text(&f["zero_unlock"]["code"]),
            &salt,
            &keys,
            0,
        )
        .await
        .unwrap();
    assert!(
        zero == 0 && vault.is_unlocked(),
        "any well-formed code unlocks"
    );
}

// contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
#[tokio::test]
async fn ts_rate_limit_sequence_replays_exactly() {
    let f = fixture();
    let raw = key(&f["keys"]["master_b64"]);
    let master = MasterCapability::from_browser_raw(Zeroizing::new(raw));
    let salt = bytes(&f["keys"]["email_salt_b64"]);
    let keys = stored_keys(&f);
    let mut vault = HiddenChatVault::new();
    assert_eq!(
        f["rate_limit"]["max_failed_attempts"].as_u64(),
        Some(u64::from(MAX_FAILED_ATTEMPTS))
    );
    assert_eq!(f["rate_limit"]["lockout_ms"].as_u64(), Some(LOCKOUT_MS));
    for step in f["rate_limit"]["steps"].as_array().unwrap() {
        let now = step["now_ms"].as_u64().unwrap();
        let step_salt: &[u8] = if step["salt_missing"].as_bool().unwrap() {
            &[]
        } else {
            &salt
        };
        let outcome = match vault
            .unlock(&master, &raw, text(&step["code"]), step_salt, &keys, now)
            .await
        {
            Ok(_) => "unlocked",
            Err(Error::Locked) => "locked_out",
            Err(_) => "failed",
        };
        assert_eq!(outcome, text(&step["outcome"]), "{}", step["label"]);
        assert_eq!(
            vault.remaining_lockout_seconds(now),
            step["remaining_s"].as_u64().unwrap(),
            "{}",
            step["label"]
        );
        assert_eq!(
            vault.is_unlocked(),
            step["is_unlocked"].as_bool().unwrap(),
            "{}",
            step["label"]
        );
        vault.lock();
    }
}

#[test]
fn code_wraps_respect_lockout_without_counting_malformed_codes() {
    let raw = *crypto::random_key();
    let chat_key = crypto::random_key();
    let salt = [7u8; 16];
    let mut vault = HiddenChatVault::new();
    assert_eq!(
        vault
            .wrap_chat_key_with_code(&raw, "abc", &salt, &chat_key, 0)
            .unwrap_err(),
        INVALID_CODE
    );
    for _ in 0..2 {
        assert!(
            vault
                .wrap_chat_key_with_code(&raw, "abcd", &[], &chat_key, 0)
                .is_err()
        );
    }
    assert_eq!(
        vault.remaining_lockout_seconds(0),
        0,
        "two derivation failures stay below the bound"
    );
    vault.unlock_master_missing(1);
    assert_eq!(vault.remaining_lockout_seconds(1), 30);
    assert_eq!(
        vault
            .wrap_chat_key_with_code(&raw, "abcd", &salt, &chat_key, 2)
            .unwrap_err(),
        Error::Locked
    );
    let wrapped = vault
        .wrap_chat_key_with_code(&raw, "abcd", &salt, &chat_key, 30_001)
        .unwrap();
    let secret = derive_secret(&raw, "abcd", &salt).unwrap();
    assert_eq!(
        unwrap_chat_key(&wrapped, &secret).unwrap().as_slice(),
        chat_key.as_slice()
    );
    assert!(!vault.is_unlocked(), "wrapping with a code never unlocks");
    assert_eq!(vault.wrap(&chat_key).unwrap_err(), Error::Locked);
}

#[test]
fn key_update_frame_matches_the_web_sender() {
    let full = ChatKeyVersions {
        messages_v: Some(4),
        title_v: Some(2),
        last_edited_overall_timestamp: Some(1_700),
    };
    assert_eq!(
        chat_key_update_payload("c", "wrapped", full, 9_999).to_string(),
        r#"{"allow_chat_key_rotation":true,"chat_id":"c","chat_key_rotation_reason":"hidden_chat","encrypted_chat_key":"wrapped","versions":{"last_edited_overall_timestamp":1700,"messages_v":4,"title_v":2}}"#
    );
    let empty = ChatKeyVersions {
        messages_v: None,
        title_v: Some(0),
        last_edited_overall_timestamp: Some(0),
    };
    let payload = chat_key_update_payload("c", "wrapped", empty, 9_999);
    assert_eq!(
        payload["versions"],
        serde_json::json!({"messages_v":0,"title_v":0,"last_edited_overall_timestamp":9_999})
    );
    assert_eq!(CHAT_KEY_UPDATE_FRAME, "encrypted_chat_metadata");
}
