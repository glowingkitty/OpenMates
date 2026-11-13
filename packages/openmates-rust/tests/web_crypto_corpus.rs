//! Web crypto vector corpus: every vector was produced by the deployed web
//! TypeScript modules (ts_web_formats/generate.cjs, ts_web_policy/generate.cjs)
//! plus the shared legacy layouts. The browser WASM binding runs the same
//! files in frontend/packages/ui/src/services/rustCore/crypto/__tests__.
use base64::{Engine as _, engine::general_purpose::STANDARD};
use openmates_sdk::crypto::{
    chat_key_policy::{
        self as policy, ChatContentOutcome, ChatKeyWriteSnapshot, GuardStep, InjectDecision,
        KeySource,
    },
    media::{self, MediaEncryption, MediaStage},
    share::{self, ShareKind},
    web_formats,
};
use serde_json::Value;

fn formats() -> Value {
    serde_json::from_str(include_str!("crypto_fixtures/ts_web_formats.json")).unwrap()
}
fn policy_vectors() -> Value {
    serde_json::from_str(include_str!("crypto_fixtures/ts_web_policy.json")).unwrap()
}
fn key32(b64: &str) -> [u8; 32] {
    STANDARD.decode(b64).unwrap().try_into().unwrap()
}
fn s(value: &Value) -> &str {
    value.as_str().unwrap()
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sdk.encryption.local-only
#[test]
fn ts_chat_content_current_and_legacy_layouts_decrypt() {
    let f = formats();
    let key = key32(s(&f["keys"]["chat_key_b64"]));
    let other = key32(s(&f["keys"]["other_chat_key_b64"]));
    for case in f["chat_content"].as_array().unwrap() {
        match policy::decrypt_chat_content(s(&case["ciphertext"]), &key) {
            ChatContentOutcome::Plaintext(plain) => assert_eq!(
                String::from_utf8_lossy(&plain),
                s(&case["plaintext"]),
                "{case}"
            ),
            _ => panic!("undecryptable {case}"),
        }
        let wrong = policy::decrypt_chat_content(s(&case["ciphertext"]), &other);
        match (s(&case["layout"]), wrong) {
            ("om-fnv", ChatContentOutcome::FingerprintMismatch(fp)) => {
                assert_eq!(fp, openmates_sdk::crypto::key_fingerprint(&key))
            }
            ("legacy-iv", ChatContentOutcome::Failed) => {}
            _ => panic!("wrong key must not decrypt {case}"),
        }
    }
    // Shared legacy layouts (formats A/B with the content key).
    let legacy: Value = serde_json::from_str(include_str!(
        "crypto_fixtures/encryption_compatibility/legacy_layouts.json"
    ))
    .unwrap();
    let content_key = key32(s(&legacy["keys"]["content_key_b64"]));
    for name in ["format_a", "format_b"] {
        let entry = &legacy["chat"][name];
        match policy::decrypt_chat_content(s(&entry["blob_b64"]), &content_key) {
            ChatContentOutcome::Plaintext(plain) => {
                assert_eq!(String::from_utf8_lossy(&plain), s(&entry["plaintext"]))
            }
            _ => panic!("{name}"),
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sdk.encryption.local-only
#[test]
fn ts_chat_content_outcomes_match_or_extend_typescript() {
    let p = policy_vectors();
    let k1 = key32(s(&p["keys"]["k1_b64"]));
    for case in p["chat_content"].as_array().unwrap() {
        let label = s(&case["label"]);
        let outcome = policy::decrypt_chat_content(s(&case["ciphertext"]), &k1);
        match (&case["ts_plaintext"], outcome) {
            (Value::String(expected), ChatContentOutcome::Plaintext(plain)) => {
                assert_eq!(String::from_utf8_lossy(&plain), *expected, "{label}")
            }
            // Documented superset: TS rejects these authenticated layouts.
            (Value::Null, ChatContentOutcome::Plaintext(_)) => assert!(
                matches!(label, "legacy-iv-starts-om" | "python-marker"),
                "{label}"
            ),
            (Value::Null, ChatContentOutcome::FingerprintMismatch(fp)) => {
                assert_eq!(
                    case["ts_candidate_lookup"].as_str(),
                    Some(hex(&fp).as_str()),
                    "{label}"
                )
            }
            (Value::Null, ChatContentOutcome::Failed) => {
                assert!(case["ts_candidate_lookup"].is_null(), "{label}")
            }
            (expected, _) => panic!("{label}: TS {expected}"),
        }
    }
    // Rust writes OM frames that the same plan reads.
    let sealed = policy::frame_chat_content(&k1, &[7; 12], &aes(&k1, &[7; 12], b"rust writer"));
    assert!(
        matches!(policy::decrypt_chat_content(&sealed, &k1), ChatContentOutcome::Plaintext(p) if p.as_slice() == b"rust writer")
    );
    // The synchronous writer (browser main-thread adapter) frames like
    // encryptWithChatKey: OM || fnv32(key) || fresh IV || ciphertext || tag.
    let first = policy::encrypt_chat_content(b"main thread writer", &k1).unwrap();
    let second = policy::encrypt_chat_content(b"main thread writer", &k1).unwrap();
    assert_ne!(first, second, "fresh IV per write");
    let framed = STANDARD.decode(&first).unwrap();
    assert_eq!(&framed[..2], b"OM");
    assert_eq!(hex(&framed[2..6]), policy::chat_key_fingerprint4_hex(&k1));
    assert_eq!(framed.len(), 6 + 12 + b"main thread writer".len() + 16);
    assert!(
        matches!(policy::decrypt_chat_content(&first, &k1), ChatContentOutcome::Plaintext(p) if p.as_slice() == b"main thread writer")
    );
}

fn aes(key: &[u8; 32], iv: &[u8; 12], plain: &[u8]) -> Vec<u8> {
    use aes_gcm::{Aes256Gcm, KeyInit, Nonce, aead::Aead};
    Aes256Gcm::new_from_slice(key)
        .unwrap()
        .encrypt(Nonce::from_slice(iv), plain)
        .unwrap()
}
fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn ts_master_envelope_opens_and_rust_frames_read_back() {
    use aes_gcm::{Aes256Gcm, KeyInit, Nonce, aead::Aead};
    let f = formats();
    let master = key32(s(&f["keys"]["master_b64"]));
    let cipher = Aes256Gcm::new_from_slice(&master).unwrap();
    let open = |ciphertext: &str| {
        let combined = policy::open_master_envelope(ciphertext).unwrap();
        cipher
            .decrypt(Nonce::from_slice(&combined[..12]), &combined[12..])
            .unwrap()
    };
    // TS MetadataEncryptor Formats C/D (text fields and a wrapped chat key).
    for case in f["master_text"].as_array().unwrap() {
        assert_eq!(
            open(s(&case["ciphertext"])),
            s(&case["plaintext"]).as_bytes()
        );
    }
    let chat_key = key32(s(&f["keys"]["chat_key_b64"]));
    assert_eq!(
        open(s(&f["wrappers"]["chat_key_master_format_c"])),
        chat_key
    );
    // Rust-framed envelope reads back; wrong tag length and malformed input fail.
    let iv = [7u8; 12];
    let sealed = aes(&master, &iv, b"rust framed");
    let framed = policy::frame_master_envelope(&iv, &sealed, 11).unwrap();
    assert_eq!(open(&framed), b"rust framed");
    assert!(policy::frame_master_envelope(&iv, &sealed, 12).is_err());
    assert!(policy::frame_master_envelope(&iv[..11], &sealed, 11).is_err());
    for bad in ["", "AAAA", "not base64!", &STANDARD.encode([0u8; 27])] {
        assert!(policy::open_master_envelope(bad).is_err(), "{bad:?}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn ts_fingerprints_match() {
    for case in policy_vectors()["fingerprints"].as_array().unwrap() {
        let key = STANDARD.decode(s(&case["key_b64"])).unwrap();
        assert_eq!(policy::chat_key_fingerprint_hex(&key), s(&case["fp16"]));
        assert_eq!(policy::chat_key_fingerprint4_hex(&key), s(&case["fp4"]));
    }
}

// contract-test: supporting surface=sdks.rust assertions=chat-share-settings.shared-link-open,sdk.encryption.local-only
#[test]
fn ts_share_links_read_and_rust_writes_read_back() {
    let f = formats();
    let share_fx = &f["share"];
    let chat_id = s(&share_fx["chat_id"]);
    let now = share_fx["generated_at"].as_i64().unwrap();
    for case in share_fx["chat"].as_array().unwrap() {
        let password = case["password"].as_str();
        let key =
            web_formats::decrypt_chat_share_key_blob(chat_id, s(&case["blob"]), now + 10, password)
                .unwrap()
                .unwrap();
        assert_eq!(key.as_str(), s(&f["keys"]["chat_key_b64"]));
    }
    let embed_id = s(&f["wrappers"]["embed_id"]);
    for case in share_fx["embed"].as_array().unwrap() {
        let key = web_formats::decrypt_embed_share_key_blob(
            embed_id,
            s(&case["blob"]),
            now + 10,
            case["password"].as_str(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(
            STANDARD.encode(key.as_slice()),
            s(&f["wrappers"]["derived_embed_key_b64"])
        );
    }
    let short = &share_fx["short_url"];
    assert_eq!(
        web_formats::decrypt_short_url(
            s(&short["encrypted"]),
            s(&short["token"]),
            s(&short["short_key"])
        )
        .unwrap(),
        s(&short["url"])
    );

    // Rust writers, read back by the reader (the WASM vitest reads them with TS).
    let chat_key = s(&f["keys"]["chat_key_b64"]);
    let blob = share::generate_share_key_blob(
        ShareKind::Chat,
        chat_id,
        chat_key,
        86400,
        Some("pw ü"),
        now,
    )
    .unwrap();
    use web_formats::ShareKeyRefusal::*;
    assert_eq!(
        web_formats::decrypt_chat_share_key_blob(chat_id, &blob, now, None)
            .unwrap()
            .unwrap_err(),
        PasswordRequired
    );
    assert_eq!(
        web_formats::decrypt_chat_share_key_blob(chat_id, &blob, now, Some("bad"))
            .unwrap()
            .unwrap_err(),
        InvalidPassword
    );
    assert_eq!(
        web_formats::decrypt_chat_share_key_blob(chat_id, &blob, now + 86401, Some("pw ü"))
            .unwrap()
            .unwrap_err(),
        Expired
    );
    assert_eq!(
        web_formats::decrypt_chat_share_key_blob(chat_id, &blob, now + 5, Some("pw ü"))
            .unwrap()
            .unwrap()
            .as_str(),
        chat_key
    );
    let embed_key = STANDARD
        .decode(s(&f["wrappers"]["derived_embed_key_b64"]))
        .unwrap();
    let value = share::share_key_value(ShareKind::Embed, &embed_key);
    let blob =
        share::generate_share_key_blob(ShareKind::Embed, embed_id, &value, 0, None, now).unwrap();
    assert_eq!(
        web_formats::decrypt_embed_share_key_blob(embed_id, &blob, now + 9_999_999, None)
            .unwrap()
            .unwrap()
            .as_slice(),
        embed_key.as_slice()
    );
    let (token, short_key) = share::generate_short_url_parts();
    assert_eq!((token.len(), short_key.len()), (8, 22));
    assert!(
        token
            .bytes()
            .chain(short_key.bytes())
            .all(|b| b.is_ascii_alphanumeric())
    );
    let url = "https://openmates.org/share/chat/x#key=abc-_123";
    let encrypted = share::encrypt_short_url(url, &token, &short_key).unwrap();
    assert_eq!(
        web_formats::decrypt_short_url(&encrypted, &token, &short_key).unwrap(),
        url
    );
    // Exact URLSearchParams serialization.
    assert_eq!(
        share::serialize_share_blob(ShareKind::Chat, "a+b/c=", 5, 0, false).as_str(),
        "chat_encryption_key=a%2Bb%2Fc%3D&generated_at=5&duration_seconds=0&pwd=0"
    );
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sdk.encryption.local-only
#[test]
fn ts_media_layouts_decrypt_and_unknown_fail_closed() {
    let f = formats();
    let m = &f["media"];
    let plain = STANDARD.decode(s(&m["plaintext_b64"])).unwrap();
    let key_b64 = s(&m["key_b64"]);
    for case in m["cases"].as_array().unwrap() {
        let data = STANDARD.decode(s(&case["data_b64"])).unwrap();
        let meta = MediaEncryption {
            encryption: case["encryption"].as_str(),
            aes_nonce: case["aes_nonce"].as_str(),
            legacy_nonce: case["legacy_nonce"].as_str(),
        };
        assert_eq!(
            media::decrypt_media(&data, key_b64, &meta)
                .unwrap()
                .as_slice(),
            plain.as_slice(),
            "{case}"
        );
    }
    let data = STANDARD.decode(s(&m["cases"][0]["data_b64"])).unwrap();
    let unknown = MediaEncryption {
        encryption: Some("future-v9"),
        aes_nonce: None,
        legacy_nonce: None,
    };
    assert_eq!(
        media::decrypt_media(&data, key_b64, &unknown).unwrap_err(),
        MediaStage::Metadata
    );
    let none = MediaEncryption {
        encryption: None,
        aes_nonce: None,
        legacy_nonce: None,
    };
    assert_eq!(
        media::decrypt_media(&data, key_b64, &none).unwrap_err(),
        MediaStage::Metadata
    );
    let key = key32(key_b64);
    let v2 = media::encrypt_media_v2(&plain, &key).unwrap();
    let marker = MediaEncryption {
        encryption: Some(media::MEDIA_ENCRYPTION_V2),
        aes_nonce: None,
        legacy_nonce: None,
    };
    assert_eq!(
        media::decrypt_media(&v2, key_b64, &marker)
            .unwrap()
            .as_slice(),
        plain.as_slice()
    );
}

fn named<'a>(value: &Value, k1: &'a [u8], k2: &'a [u8]) -> Option<&'a [u8]> {
    match value.as_str() {
        Some("k1") => Some(k1),
        Some("k2") => Some(k2),
        _ => None,
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sdk.encryption.local-only
#[test]
fn ts_write_guard_scenarios_match() {
    let p = policy_vectors();
    let k1 = STANDARD.decode(s(&p["keys"]["k1_b64"])).unwrap();
    let k2 = STANDARD.decode(s(&p["keys"]["k2_b64"])).unwrap();
    for case in p["write_guard"].as_array().unwrap() {
        let chat = &case["chat"];
        let truthy = |v: &Value| v.as_str().filter(|v| !v.is_empty()).map(str::to_owned);
        let snapshot = ChatKeyWriteSnapshot {
            chat_exists: !chat.is_null(),
            candidate_key_count: chat["candidate_encrypted_keys"]
                .as_array()
                .map_or(0, Vec::len),
            key_fingerprint: truthy(&chat["key_fingerprint"]),
            is_anonymous: chat["is_anonymous"].as_bool().unwrap_or(false),
            team_scoped: truthy(&chat["team_id"]).is_some(),
            direct_visibility: chat["chat_visibility"].as_str() == Some("direct"),
            encrypted_chat_key: truthy(&chat["encrypted_chat_key"])
                .or_else(|| truthy(&case["fallback_encrypted_key"])),
        };
        let allow_missing = case["options"]["allowMissingEncryptedChatKey"]
            .as_bool()
            .unwrap_or(false);
        let unwraps = &case["unwraps"];
        let mut step = policy::guard_begin(&snapshot, &k1, allow_missing);
        step = match step {
            GuardStep::UnwrapAnonymous => {
                policy::guard_after_anonymous(&k1, named(&unwraps["anonymous"], &k1, &k2))
            }
            GuardStep::UnwrapPersisted { team } => {
                let value = if team {
                    &unwraps["team"]
                } else {
                    &unwraps["master"]
                };
                let result = if value.as_str() == Some("throw") {
                    Err(())
                } else {
                    Ok(named(value, &k1, &k2))
                };
                policy::guard_after_persisted(&k1, result)
            }
            other => other,
        };
        let report = case["options"]["reportFailure"].as_bool() != Some(false);
        let label = s(&case["label"]);
        match step {
            GuardStep::Allow | GuardStep::AllowUnverified => {
                assert_eq!(case["ts_allowed"], true, "{label}");
            }
            GuardStep::Refuse {
                reason,
                add_candidate,
                notice,
            } => {
                assert_eq!(case["ts_allowed"], false, "{label}");
                assert_eq!(case["ts_reason"].as_str(), Some(reason.as_str()), "{label}");
                assert_eq!(
                    case["ts_added_candidate"].as_bool(),
                    Some(add_candidate),
                    "{label}"
                );
                let notices = if report && notice != policy::GuardNotice::None {
                    1
                } else {
                    0
                };
                assert_eq!(case["ts_notices"].as_u64(), Some(notices), "{label}");
            }
            other => panic!("{label}: unfinished {other:?}"),
        }
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn ts_key_slot_compare_and_swap_matches() {
    let p = policy_vectors();
    let k1 = STANDARD.decode(s(&p["keys"]["k1_b64"])).unwrap();
    let k2 = STANDARD.decode(s(&p["keys"]["k2_b64"])).unwrap();
    for case in p["inject"].as_array().unwrap() {
        let label = s(&case["label"]);
        let existing = case["existing"]
            .as_array()
            .map(|e| (named(&e[0], &k1, &k2).unwrap(), KeySource::parse(s(&e[1]))));
        let inject = case["inject"].as_array().unwrap();
        let source = KeySource::parse(s(&inject[1])).unwrap();
        let decision = policy::decide_inject(
            existing,
            named(&inject[0], &k1, &k2).unwrap(),
            source,
            inject[2].as_bool().unwrap(),
        );
        let (accepted, source_after, key_after) = match decision {
            InjectDecision::Insert | InjectDecision::ForceReplace => {
                (true, Some(inject[1].clone()), inject[0].clone())
            }
            InjectDecision::SameKey { update_provenance } => (
                true,
                Some(if update_provenance {
                    inject[1].clone()
                } else {
                    case["ts_source_before"].clone()
                }),
                inject[0].clone(),
            ),
            InjectDecision::Rejected => (
                false,
                Some(case["ts_source_before"].clone()),
                case["existing"][0].clone(),
            ),
        };
        assert_eq!(case["ts_accepted"].as_bool(), Some(accepted), "{label}");
        assert_eq!(
            Some(case["ts_source_after"].clone()),
            source_after,
            "{label}"
        );
        assert_eq!(case["ts_key_after"], key_after, "{label}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only
#[test]
fn ts_decryption_failure_cache_matches() {
    let mut cache = policy::DecryptionFailureCache::default();
    for op in policy_vectors()["failure_cache"].as_array().unwrap() {
        let chat = op["chat"].as_str();
        match s(&op["op"]) {
            "record" => cache.record(
                chat.unwrap(),
                s(&op["message"]),
                s(&op["field"]),
                op["fp"].as_str(),
            ),
            "clear" => cache.clear(chat),
            _ => assert_eq!(
                cache.is_known(
                    chat.unwrap(),
                    s(&op["message"]),
                    s(&op["field"]),
                    op["fp"].as_str()
                ),
                op["ts_known"].as_bool().unwrap(),
                "{op}"
            ),
        }
    }
}

fn outcome_label(outcome: &ChatContentOutcome) -> String {
    match outcome {
        ChatContentOutcome::Plaintext(plain) => format!("plain:{}", hex(plain)),
        ChatContentOutcome::FingerprintMismatch(fp) => format!("mismatch:{}", hex(fp)),
        ChatContentOutcome::Failed => "failed".to_owned(),
    }
}

// contract-test: supporting surface=sdks.rust assertions=chats.persistence.client-encrypted,sdk.encryption.local-only
#[tokio::test]
async fn aead_provider_runs_the_same_policy_as_the_synchronous_reader() {
    use openmates_sdk::crypto::aead::{self, AeadProvider, NativeAead};
    let (f, p) = (formats(), policy_vectors());
    let k1 = key32(s(&p["keys"]["k1_b64"]));
    let chat_key = key32(s(&f["keys"]["chat_key_b64"]));
    for (raw, cases) in [(k1, &p["chat_content"]), (chat_key, &f["chat_content"])] {
        let items: Vec<&str> = cases
            .as_array()
            .unwrap()
            .iter()
            .map(|case| s(&case["ciphertext"]))
            .collect();
        let key = NativeAead.import_key(&raw).await.unwrap();
        let batch = aead::open_chat_batch(key.as_ref(), &raw, &items)
            .await
            .unwrap();
        assert_eq!(batch.len(), items.len());
        for (item, outcome) in items.iter().zip(&batch) {
            let expected = policy::decrypt_chat_content(item, &raw);
            assert_eq!(outcome_label(outcome), outcome_label(&expected), "{item}");
            let single = aead::open_chat_content(key.as_ref(), &raw, item)
                .await
                .unwrap();
            assert_eq!(outcome_label(&single), outcome_label(&expected), "{item}");
        }
    }
    // Provider writes OM frames (fresh IV per item) that the synchronous reader opens.
    let key = NativeAead.import_key(&k1).await.unwrap();
    let sealed = aead::seal_chat_batch(key.as_ref(), &k1, &["first", "second"])
        .await
        .unwrap();
    assert_ne!(sealed[0], sealed[1]);
    for (frame, plain) in sealed.iter().zip(["first", "second"]) {
        assert!(
            matches!(policy::decrypt_chat_content(frame, &k1), ChatContentOutcome::Plaintext(p) if p.as_slice() == plain.as_bytes())
        );
    }
    // Formats C/D under the master key: TS envelopes open, malformed items fail alone.
    let master = key32(s(&f["keys"]["master_b64"]));
    let key = NativeAead.import_key(&master).await.unwrap();
    let cases = f["master_text"].as_array().unwrap();
    let mut items: Vec<&str> = cases.iter().map(|case| s(&case["ciphertext"])).collect();
    items.push("AAAA");
    items.push(s(&f["wrappers"]["chat_key_master_format_c"]));
    let opened = aead::open_master_batch(key.as_ref(), &items).await;
    for (case, result) in cases.iter().zip(&opened) {
        assert_eq!(
            result.as_ref().unwrap().as_slice(),
            s(&case["plaintext"]).as_bytes()
        );
    }
    assert!(opened[cases.len()].is_err());
    assert_eq!(
        opened[cases.len() + 1].as_ref().unwrap().as_slice(),
        chat_key.as_slice()
    );
    // Wrong key: authentication failure, never plaintext.
    let other = NativeAead.import_key(&k1).await.unwrap();
    assert!(matches!(
        aead::open_master_envelope(other.as_ref(), items[0]).await,
        Err(openmates_sdk::Error::Crypto)
    ));
}
