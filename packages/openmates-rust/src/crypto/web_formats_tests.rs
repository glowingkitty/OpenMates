//! Rust readers against ciphertexts produced by the ACTUAL web TypeScript
//! encryption modules (tests/crypto_fixtures/ts_web_formats/generate.cjs).
//! Every positive case is paired with tamper/wrong-key/wrong-layout refusals so
//! no corrupted selected input silently downgrades to another format.
use super::*;
use serde_json::Value;

fn fx() -> Value {
    serde_json::from_str(include_str!("../../tests/crypto_fixtures/ts_web_formats.json")).unwrap()
}
fn s(v: &Value) -> &str {
    v.as_str().unwrap()
}
fn key(f: &Value, name: &str) -> Key {
    decode_key(s(&f["keys"][name])).unwrap()
}
fn raw(v: &Value) -> Vec<u8> {
    STANDARD.decode(s(v)).unwrap()
}
fn flip_last(ciphertext: &str) -> String {
    let mut bytes = STANDARD.decode(ciphertext).unwrap();
    *bytes.last_mut().unwrap() ^= 1;
    STANDARD.encode(bytes)
}
fn flip_url_last(ciphertext: &str) -> String {
    let mut bytes = master::decode_browser_base64(ciphertext).unwrap();
    *bytes.last_mut().unwrap() ^= 1;
    URL_SAFE_NO_PAD.encode(bytes)
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn ts_chat_content_om_and_legacy_layouts_decrypt_and_corruption_never_downgrades() {
    let f = fx();
    let (chat, other) = (key(&f, "chat_key_b64"), key(&f, "other_chat_key_b64"));
    let cases = f["chat_content"].as_array().unwrap();
    assert!(cases.iter().any(|c| c["layout"] == "om-fnv") && cases.iter().any(|c| c["layout"] == "legacy-iv"));
    for case in cases {
        let ct = s(&case["ciphertext"]);
        let wire = STANDARD.decode(ct).unwrap();
        if case["layout"] == "om-fnv" {
            assert!(wire.starts_with(b"OM") && wire[2..6] == key_fingerprint(&chat), "{}", case["label"]);
        }
        assert_eq!(decrypt_combined(ct, &chat).unwrap(), s(&case["plaintext"]), "{}", case["label"]);
        assert!(decrypt_bytes(ct, &other).is_err());
        assert!(decrypt_bytes(&flip_last(ct), &chat).is_err());
        // A flipped header/IV byte must not authenticate under any layout.
        let mut header = wire.clone();
        header[3] ^= 0x40;
        assert!(decrypt_bytes(&STANDARD.encode(&header), &chat).is_err());
        // Truncated tag never authenticates.
        assert!(decrypt_bytes(&STANDARD.encode(&wire[..wire.len() - 1]), &chat).is_err());
    }
    assert!(decrypt_bytes(s(&f["chat_content_other_key"]), &chat).is_err());
    assert_eq!(decrypt_combined(s(&f["chat_content_other_key"]), &other).unwrap(), "other key");
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn ts_format_d_master_text_and_format_c_chat_key_wrapper_decrypt() {
    let f = fx();
    let (master, chat) = (key(&f, "master_b64"), key(&f, "chat_key_b64"));
    for case in f["master_text"].as_array().unwrap() {
        let ct = s(&case["ciphertext"]);
        assert_eq!(server_fields::decrypt_text(ct, &master, &[]).unwrap(), s(&case["plaintext"]));
        assert!(decrypt_bytes(ct, &chat).is_err());
        assert!(decrypt_bytes(&flip_last(ct), &master).is_err());
    }
    let c = s(&f["wrappers"]["chat_key_master_format_c"]);
    assert_eq!(decrypt_bytes(c, &master).unwrap().as_slice(), chat.as_ref());
    assert!(decrypt_bytes(&flip_last(c), &master).is_err());
    assert!(decrypt_bytes(c, &chat).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn ts_embed_key_derivation_wrappers_child_keys_and_aad_content_decrypt() {
    let f = fx();
    let w = &f["wrappers"];
    let (master, chat, parent) = (key(&f, "master_b64"), key(&f, "chat_key_b64"), key(&f, "parent_embed_key_b64"));
    let derived = derive_embed_key(&chat, s(&w["embed_id"])).unwrap();
    assert_eq!(encode_key(&derived), s(&w["derived_embed_key_b64"]));
    assert_eq!(decrypt_bytes(s(&w["embed_key_master"]), &master).unwrap().as_slice(), derived.as_ref());
    assert_eq!(decrypt_bytes(s(&w["embed_key_chat"]), &chat).unwrap().as_slice(), derived.as_ref());
    assert!(decrypt_bytes(s(&w["embed_key_chat"]), &master).is_err());
    assert_eq!(decrypt_bytes(s(&w["child_embed_key_parent"]), &parent).unwrap().as_slice(), key(&f, "child_embed_key_b64").as_ref());
    assert!(decrypt_bytes(&flip_last(s(&w["child_embed_key_parent"])), &parent).is_err());
    let content = &w["embed_content"];
    assert_eq!(server_fields::decrypt_text(s(&content["ciphertext"]), &derived, &[]).unwrap(), s(&content["plaintext"]));
    let aad = &w["embed_content_aad"];
    let aad_bytes = s(&aad["aad"]).as_bytes();
    assert_eq!(server_fields::decrypt_text(s(&aad["ciphertext"]), &parent, aad_bytes).unwrap(), s(&aad["plaintext"]));
    assert!(server_fields::decrypt_bytes(s(&aad["ciphertext"]), &parent, &[]).is_err());
    assert!(server_fields::decrypt_bytes(s(&aad["ciphertext"]), &parent, b"task_activity_comment:task-1:entry-2:v1").is_err());
}

// contract-test: supporting surface=sdks.rust assertions=auth.password.versioned-protection,sdk.surface.semantic-parity
#[test]
fn ts_master_key_wrapping_by_password_recovery_key_passkey_and_password_v2() {
    let f = fx();
    let master = key(&f, "master_b64");
    let mut kinds = vec![];
    for case in f["master_wrapping"].as_array().unwrap() {
        let (ct, iv) = (s(&case["ciphertext"]), s(&case["iv"]));
        kinds.push(s(&case["kind"]).to_string());
        match s(&case["kind"]) {
            "pbkdf2" => {
                let secret = s(&case["secret"]);
                for version in [0, 1] {
                    let out = unwrap_password_master_key(secret, version, ct, s(&case["salt_b64"]), iv).unwrap();
                    assert_eq!(out.as_ref(), master.as_ref(), "{}", case["label"]);
                }
                assert!(unwrap_password_master_key(&format!("{secret}x"), 1, ct, s(&case["salt_b64"]), iv).is_err());
                assert!(unwrap_password_master_key(secret, 1, &flip_last(ct), s(&case["salt_b64"]), iv).is_err());
            }
            "prf" => {
                let (prf, salt) = (raw(&case["prf_b64"]), raw(&case["email_salt_b64"]));
                assert_eq!(encode_key(&web_formats::passkey_wrapping_key(&prf, &salt).unwrap()), s(&case["wrapping_key_b64"]));
                assert_eq!(web_formats::unwrap_passkey_master_key(&prf, &salt, ct, iv).unwrap().as_ref(), master.as_ref());
                let mut other_salt = salt.clone();
                other_salt[0] ^= 1;
                assert!(web_formats::unwrap_passkey_master_key(&prf, &other_salt, ct, iv).is_err());
                assert!(web_formats::unwrap_passkey_master_key(&prf, &salt, &flip_last(ct), iv).is_err());
                assert!(web_formats::passkey_wrapping_key(&prf[..15], &salt).is_err());
            }
            "argon2id-v2" => {
                let salt = raw(&case["salt_b64"]);
                let (auth, wrap) = derive_password_keys_v2(s(&case["secret"]), &salt).unwrap();
                assert_eq!(encode_key(&auth), s(&case["auth_key_b64"]));
                assert_eq!(encode_key(&wrap), s(&case["wrap_key_b64"]));
                assert_eq!(unwrap_master_key_with_wrapping_key(ct, iv, &wrap).unwrap().as_ref(), master.as_ref());
                assert!(unwrap_master_key_with_wrapping_key(ct, iv, &auth).is_err());
                // A v2 envelope never opens through the legacy PBKDF2 path.
                assert!(unwrap_password_master_key(s(&case["secret"]), 1, ct, s(&case["salt_b64"]), iv).is_err());
            }
            other => panic!("unexpected kind {other}"),
        }
    }
    assert_eq!(kinds.iter().filter(|k| *k == "pbkdf2").count(), 3);
    assert!(kinds.contains(&"prf".into()) && kinds.contains(&"argon2id-v2".into()));
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn ts_hidden_chat_key_wrapper_opens_only_with_the_code_secret() {
    let f = fx();
    let h = &f["hidden_chat"];
    let (master, chat) = (key(&f, "master_b64"), key(&f, "chat_key_b64"));
    let salt = raw(&h["email_salt_b64"]);
    let secret = web_formats::hidden_chat_secret(&master, s(&h["code"]), &salt).unwrap();
    assert_eq!(encode_key(&secret), s(&h["combined_secret_b64"]));
    let wrapped = s(&h["encrypted_chat_key"]);
    assert_eq!(web_formats::unwrap_hidden_chat_key(wrapped, &secret).unwrap().as_ref(), chat.as_ref());
    // A hidden wrapper is never readable as a normal Format C wrapper.
    assert!(decrypt_bytes(wrapped, &master).is_err());
    let wrong = web_formats::hidden_chat_secret(&master, "4821abce", &salt).unwrap();
    assert!(web_formats::unwrap_hidden_chat_key(wrapped, &wrong).is_err());
    assert!(web_formats::unwrap_hidden_chat_key(&flip_last(wrapped), &secret).is_err());
    // email salt beyond 16 bytes is ignored exactly like TS `slice(0, 16)`.
    let mut longer = salt.clone();
    longer.extend_from_slice(&[9; 8]);
    assert_eq!(web_formats::hidden_chat_secret(&master, s(&h["code"]), &longer).unwrap().as_ref(), secret.as_ref());
    assert!(web_formats::hidden_chat_secret(&master, "123", &salt).is_err());
    assert!(web_formats::hidden_chat_secret(&master, &"9".repeat(31), &salt).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn ts_chat_and_embed_share_blobs_and_short_url_decrypt_with_ts_refusal_order() {
    use web_formats::ShareKeyRefusal::*;
    let f = fx();
    let sh = &f["share"];
    let (chat_id, now) = (s(&sh["chat_id"]), sh["generated_at"].as_i64().unwrap());
    let chat_b64 = s(&f["keys"]["chat_key_b64"]);
    for case in sh["chat"].as_array().unwrap() {
        let blob = s(&case["blob"]);
        let password = case["password"].as_str();
        let opened = web_formats::decrypt_chat_share_key_blob(chat_id, blob, now + 10, password).unwrap().unwrap();
        assert_eq!(opened.as_str(), chat_b64);
        assert!(web_formats::decrypt_chat_share_key_blob("0d9f1a2b-3c4d-4e5f-8a9b-0c1d2e3f4a5c", blob, now, password).is_err());
        assert!(web_formats::decrypt_chat_share_key_blob(chat_id, &flip_url_last(blob), now, password).is_err());
        let duration = case["duration_seconds"].as_i64().unwrap();
        if duration > 0 {
            assert_eq!(web_formats::decrypt_chat_share_key_blob(chat_id, blob, now + duration + 1, password).unwrap().unwrap_err(), Expired);
            assert!(web_formats::decrypt_chat_share_key_blob(chat_id, blob, now + duration, password).unwrap().is_ok());
        }
        if password.is_some() {
            // TS checks the password requirement before expiry for chat shares.
            assert_eq!(web_formats::decrypt_chat_share_key_blob(chat_id, blob, now + duration + 1, None).unwrap().unwrap_err(), PasswordRequired);
            assert_eq!(web_formats::decrypt_chat_share_key_blob(chat_id, blob, now, Some("")).unwrap().unwrap_err(), PasswordRequired);
            assert_eq!(web_formats::decrypt_chat_share_key_blob(chat_id, blob, now, Some("wrong")).unwrap().unwrap_err(), InvalidPassword);
        }
    }
    let embed_id = s(&f["wrappers"]["embed_id"]);
    let embed_key = raw(&f["wrappers"]["derived_embed_key_b64"]);
    for case in sh["embed"].as_array().unwrap() {
        let blob = s(&case["blob"]);
        let password = case["password"].as_str();
        let opened = web_formats::decrypt_embed_share_key_blob(embed_id, blob, now + 10, password).unwrap().unwrap();
        assert_eq!(opened.as_slice(), embed_key.as_slice());
        assert!(web_formats::decrypt_embed_share_key_blob(embed_id, &flip_url_last(blob), now, password).is_err());
        if password.is_some() {
            let duration = case["duration_seconds"].as_i64().unwrap();
            // Embed shares check expiry first.
            assert_eq!(web_formats::decrypt_embed_share_key_blob(embed_id, blob, now + duration + 1, None).unwrap().unwrap_err(), Expired);
            assert_eq!(web_formats::decrypt_embed_share_key_blob(embed_id, blob, now, None).unwrap().unwrap_err(), PasswordRequired);
            assert_eq!(web_formats::decrypt_embed_share_key_blob(embed_id, blob, now, Some("wrong")).unwrap().unwrap_err(), InvalidPassword);
        }
    }
    let short = &sh["short_url"];
    assert_eq!(web_formats::decrypt_short_url(s(&short["encrypted"]), s(&short["token"]), s(&short["short_key"])).unwrap(), s(&short["url"]));
    assert!(web_formats::decrypt_short_url(s(&short["encrypted"]), s(&short["token"]), "MG56JGwigUoMz4RAbwfC0N").is_err());
    assert!(web_formats::decrypt_short_url(&flip_url_last(s(&short["encrypted"])), s(&short["token"]), s(&short["short_key"])).is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn ts_media_payload_layouts_decrypt_and_unknown_or_mismatched_layouts_fail_closed() {
    let f = fx();
    let m = &f["media"];
    let (key_b64, plain) = (s(&m["key_b64"]), raw(&m["plaintext_b64"]));
    let meta = |c: &Value| -> (Option<String>, Option<String>, Option<String>) {
        (c["encryption"].as_str().map(str::to_string), c["aes_nonce"].as_str().map(str::to_string), c["legacy_nonce"].as_str().map(str::to_string))
    };
    for case in m["cases"].as_array().unwrap() {
        let data = raw(&case["data_b64"]);
        let (encryption, aes_nonce, legacy_nonce) = meta(case);
        let info = web_formats::MediaEncryption { encryption: encryption.as_deref(), aes_nonce: aes_nonce.as_deref(), legacy_nonce: legacy_nonce.as_deref() };
        assert_eq!(web_formats::decrypt_media_payload(&data, key_b64, &info).unwrap().as_slice(), plain.as_slice(), "{}", case["label"]);
        let mut tampered = data.clone();
        *tampered.last_mut().unwrap() ^= 1;
        assert!(web_formats::decrypt_media_payload(&tampered, key_b64, &info).is_err());
        let unknown = web_formats::MediaEncryption { encryption: Some("future-v9"), ..info };
        assert!(web_formats::decrypt_media_payload(&data, key_b64, &unknown).is_err());
    }
    let prefixed = raw(&m["cases"][0]["data_b64"]);
    let sealed = raw(&m["cases"][1]["data_b64"]);
    let none = web_formats::MediaEncryption { encryption: None, aes_nonce: None, legacy_nonce: None };
    assert!(web_formats::decrypt_media_payload(&sealed, key_b64, &none).is_err());
    // Legacy external-nonce bytes never authenticate under the prefixed layout and vice versa.
    let v2 = web_formats::MediaEncryption { encryption: Some(web_formats::MEDIA_ENCRYPTION_V2), aes_nonce: None, legacy_nonce: None };
    assert!(web_formats::decrypt_media_payload(&sealed, key_b64, &v2).is_err());
    let external = web_formats::MediaEncryption { encryption: None, aes_nonce: m["cases"][1]["aes_nonce"].as_str(), legacy_nonce: None };
    assert!(web_formats::decrypt_media_payload(&prefixed, key_b64, &external).is_err());
    assert!(web_formats::decrypt_media_payload(&prefixed, &STANDARD.encode([1u8; 16]), &v2).is_err());
}

fn precedence() -> Value {
    serde_json::from_str(include_str!("../../tests/crypto_fixtures/legacy_chat_key_precedence.json")).unwrap()
}

// Crypto-level half of the legacy-precedence packet: both TS-produced Format C
// wrappers open, and a corrupted preferred wrapper never yields the legacy key.
// Selection order itself is owned by client::sync tests.
// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,sdk.surface.semantic-parity
#[test]
fn ts_format_c_legacy_and_preferred_wrappers_open_and_corruption_never_yields_another_key() {
    let p = precedence();
    let wrapping = decode_key(s(&p["wrapping_key_b64"])).unwrap();
    for name in ["legacy", "preferred"] {
        let ct = s(&p[name]["ciphertext"]);
        assert_eq!(encode_key(&exact(&decrypt_bytes(ct, &wrapping).unwrap())), s(&p[name]["key_b64"]));
        assert!(decrypt_bytes(&flip_last(ct), &wrapping).is_err());
    }
    for bad in ["", "not-base64", "AAAA"] {
        assert!(decrypt_bytes(bad, &wrapping).is_err());
    }
}
fn exact(raw: &[u8]) -> [u8; 32] {
    raw.try_into().unwrap()
}
