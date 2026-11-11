//! Golden bytes captured from the pre-move TUI `storage.rs`, codec and size
//! bounds moved with the code, and fenced publication over a real file store.
use super::*;
use zeroize::Zeroizing;

const OWNER: &str = "90f9d7c2dc3a74b071652feddec532207e1aad02a37030875aa70b9266e8a4e8";
const CONTEXT: &str = "a482d440e75f0ab8f67ef8aa8fb26498f758cd2eb1a0a51af0defeff0e4237c8";
const GOLDEN_NAME: &str = "cache-90f9d7c2dc3a74b071652feddec532207e1aad02a37030875aa70b9266e8a4e8-916967d5a5542cba43534dbbe536315ff49d1f050e817331eba9b20d9f7f9fed.json";
// Written by the TUI `Store::write_ciphertext_cache` before the move.
const GOLDEN_RECORD: &str = r#"{"version":1,"ciphertext":"IKa+AmdKjhm3bKFObB8NsMNQ0lankUsYjqDwFbTiDm26BHkAmQRxWCZXinOCmrWljiSuV5+UQcolOl0+KyrVrHheQLVFGvuwWIKxxkC5LlUeMEOXqsyon2jhsFUurmHe+ic4M6fOvjWqpaw2gDlmKe8qZnHcR9GYQYXRqCWLZ4oqvpN3LlEyxd8XWJnS3CEFacXgthO+biNChd5tBHEAlZ1WVkXk"}"#;
const GOLDEN_SNAPSHOT: &str = r#"{"chats":{"synthetic":{"encrypted_title":"opaque","id":"synthetic"}},"embed_keys":[],"embeds":{},"history":{},"revision":1,"wrappers":[]}"#;
const GOLDEN_FENCE: &str = r#"{"version":1,"epoch":"c4f86cef-590c-4a5e-8120-eb6a27ded8a2","revoked":false,"context":"a482d440e75f0ab8f67ef8aa8fb26498f758cd2eb1a0a51af0defeff0e4237c8","admitted":null,"cleanup":{"mode":"restricted_local_file","owner":"90f9d7c2dc3a74b071652feddec532207e1aad02a37030875aa70b9266e8a4e8"},"retired_contexts":[]}"#;

#[test]
fn names_and_owner_hash_match_the_previous_layout() {
    assert_eq!(owner_hash("synthetic-owner"), OWNER);
    assert_eq!(
        cache_file_name("synthetic-owner", "sync-personal"),
        GOLDEN_NAME
    );
}

#[test]
fn record_written_by_the_previous_layout_decodes() {
    let aad = cache_aad(OWNER, CONTEXT, None, "sync-personal").unwrap();
    let value = decode_cache_record_value(GOLDEN_RECORD.as_bytes(), &[7; 32], &aad).unwrap();
    assert_eq!(
        value,
        serde_json::from_str::<serde_json::Value>(GOLDEN_SNAPSHOT).unwrap()
    );
    let other = cache_aad(OWNER, CONTEXT, None, "another-key").unwrap();
    assert!(decode_cache_record_value(GOLDEN_RECORD.as_bytes(), &[7; 32], &other).is_err());
    assert!(decode_cache_record_value(GOLDEN_RECORD.as_bytes(), &[8; 32], &aad).is_err());
}

#[test]
fn aad_is_the_exact_previous_json_tuple() {
    let aad = cache_aad("o", "c", Some(5), "k").unwrap();
    assert_eq!(aad, br#"["openmates-rust-cache-v1","o","c",5,"k"]"#);
}

#[test]
fn unknown_record_version_is_refused() {
    let bytes = br#"{"version":2,"ciphertext":""}"#;
    assert!(matches!(
        decode_cache_record(bytes, &[7; 32], b"a"),
        Err(crate::error::Error::Protocol)
    ));
}

#[test]
fn encoded_record_roundtrips_and_has_the_predicted_length() {
    let plain = Zeroizing::new(b"{\"a\":1}".to_vec());
    let bytes = encode_cache_record(&[3; 32], &plain, b"aad").unwrap();
    assert_eq!(bytes.len(), cache_record_encoded_len(plain.len()).unwrap());
    let opened = decode_cache_record(&bytes, &[3; 32], b"aad").unwrap();
    assert_eq!(opened.as_slice(), plain.as_slice());
}

#[test]
fn prospective_length_matches_actual_aes_base64_json_encoder_without_kdf() {
    for bytes in [0, 1, 2, 3, 31, 255, 4096] {
        let plain = Zeroizing::new(vec![0; bytes]);
        let record = CacheRecord {
            version: 1,
            ciphertext: seal(&[7; 32], &plain, b"synthetic").unwrap(),
        };
        assert_eq!(
            cache_record_encoded_len(bytes).unwrap(),
            serde_json::to_vec(&record).unwrap().len()
        );
    }
    assert!(cache_record_encoded_len(usize::MAX).is_err());
}

#[test]
fn actual_encoded_record_boundary_preserves_existing_thirty_two_mib_read_ceiling() {
    let (mut low, mut high) = (0usize, MAX_LOCAL_RECORD_BYTES);
    while low < high {
        let middle = low + (high - low + 1) / 2;
        if cache_record_encoded_len(middle).unwrap() <= MAX_LOCAL_RECORD_BYTES {
            low = middle
        } else {
            high = middle - 1
        }
    }
    for bytes in [low, low + 1] {
        let plain = Zeroizing::new(vec![0; bytes]);
        let record = CacheRecord {
            version: 1,
            ciphertext: seal(&[7; 32], &plain, b"synthetic").unwrap(),
        };
        let actual = serde_json::to_vec(&record).unwrap().len();
        assert_eq!(actual, cache_record_encoded_len(bytes).unwrap());
        assert_eq!(actual <= MAX_LOCAL_RECORD_BYTES, bytes == low);
    }
}

#[test]
fn streaming_capacity_counts_the_actual_json_escapes_without_encryption() {
    for value in [
        serde_json::json!({"opaque":"\u{1}\n雪😀\"\\"}),
        serde_json::json!([1, true, null]),
    ] {
        encode_bounded_json(&value).unwrap();
        assert!(
            cache_record_encoded_len(serde_json::to_vec(&value).unwrap().len()).unwrap()
                <= MAX_LOCAL_RECORD_BYTES
        );
    }
    let too_big = serde_json::Value::String("\u{1}".repeat(MAX_LOCAL_RECORD_BYTES / 6));
    assert!(matches!(
        encode_bounded_json(&too_big),
        Err(crate::error::Error::Invalid(_))
    ));
}

#[cfg(unix)]
mod fenced {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn store() -> (tempfile::TempDir, FileByteStore) {
        let directory = tempfile::tempdir().unwrap();
        std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let store = FileByteStore::open(directory.path()).unwrap();
        (directory, store)
    }

    #[test]
    fn missing_fence_is_default_and_golden_fence_parses() {
        let (_directory, store) = store();
        let fence = RevocationFence::load(&store).unwrap();
        assert!(fence.epoch.is_empty() && !fence.revoked);
        store
            .put(REVOCATION_FILE, GOLDEN_FENCE.as_bytes(), Durability::Now)
            .unwrap();
        let fence = RevocationFence::load(&store).unwrap();
        assert_eq!(
            fence.active_epoch().unwrap(),
            "c4f86cef-590c-4a5e-8120-eb6a27ded8a2"
        );
        assert_eq!(
            fence.cleanup.as_ref().unwrap().mode,
            StorageMode::RestrictedLocalFile
        );
        assert_eq!(serde_json::to_string(&fence).unwrap(), GOLDEN_FENCE);
    }

    #[test]
    fn malformed_fences_are_refused() {
        let (_directory, store) = store();
        for bad in [
            r#"{"version":2,"epoch":"c4f86cef-590c-4a5e-8120-eb6a27ded8a2","revoked":false,"context":null,"admitted":null,"cleanup":null,"retired_contexts":[]}"#,
            r#"{"version":1,"epoch":"nope","revoked":false,"context":null,"admitted":null,"cleanup":null,"retired_contexts":[]}"#,
            r#"{"version":1,"epoch":"c4f86cef-590c-4a5e-8120-eb6a27ded8a2","revoked":false,"context":null,"admitted":null,"cleanup":null,"retired_contexts":["a","b","c"]}"#,
        ] {
            store
                .put(REVOCATION_FILE, bad.as_bytes(), Durability::Now)
                .unwrap();
            assert!(matches!(
                RevocationFence::load(&store),
                Err(crate::error::Error::Protocol)
            ));
        }
    }

    #[test]
    fn publish_refuses_after_revocation_or_epoch_change_and_writes_otherwise() {
        let (_directory, store) = store();
        store
            .put(REVOCATION_FILE, GOLDEN_FENCE.as_bytes(), Durability::Now)
            .unwrap();
        let epoch = "c4f86cef-590c-4a5e-8120-eb6a27ded8a2";
        let put = |name: &str, bytes: &[u8]| -> crate::error::Result<()> {
            Ok(store.put(name, bytes, Durability::Now)?)
        };
        publish_record(&store, "cache-x.json", epoch, b"one", put).unwrap();
        assert_eq!(store.get("cache-x.json").unwrap().unwrap(), b"one");
        let other = "d4f86cef-590c-4a5e-8120-eb6a27ded8a2";
        assert!(matches!(
            publish_record(&store, "cache-x.json", other, b"two", put),
            Err(crate::error::Error::Cancelled)
        ));
        let revoked = GOLDEN_FENCE.replace("\"revoked\":false", "\"revoked\":true");
        store
            .put(REVOCATION_FILE, revoked.as_bytes(), Durability::Now)
            .unwrap();
        assert!(matches!(
            publish_record(&store, "cache-x.json", epoch, b"two", put),
            Err(crate::error::Error::Cancelled)
        ));
        assert_eq!(store.get("cache-x.json").unwrap().unwrap(), b"one");
        assert!(matches!(
            RevocationFence::load(&store).unwrap().active_epoch(),
            Err(crate::error::Error::Authentication)
        ));
    }

    #[test]
    fn read_record_roundtrips_a_written_record_and_reports_missing() {
        let (_directory, store) = store();
        let aad = cache_aad(OWNER, CONTEXT, None, "k").unwrap();
        assert!(
            read_record(&store, "cache-y.json", &[1; 32], &aad)
                .unwrap()
                .is_none()
        );
        let plain = encode_bounded_json(&serde_json::json!({"a":[1,2]})).unwrap();
        let bytes = encode_cache_record(&[1; 32], &plain, &aad).unwrap();
        store.put("cache-y.json", &bytes, Durability::Now).unwrap();
        assert_eq!(
            read_record(&store, "cache-y.json", &[1; 32], &aad)
                .unwrap()
                .unwrap(),
            serde_json::json!({"a":[1,2]})
        );
    }
}
