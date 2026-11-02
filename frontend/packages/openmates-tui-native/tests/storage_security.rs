//! Isolated credential/cache tests. No OS keyring or installed CLI state is read.
use openmates::{
    error::Error,
    storage::{CredentialBackend, KeyringFailure, Session, StorageMode, Store},
};
use serde_json::json;
#[cfg(unix)]
use std::os::unix::{
    fs::MetadataExt,
    fs::{PermissionsExt, symlink},
};
use std::{
    collections::BTreeMap,
    fs,
    path::Path,
    sync::{
        Arc, Barrier, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
};
use zeroize::Zeroizing;

#[derive(Default)]
struct FakeKeyring {
    secret: Mutex<Option<Zeroizing<Vec<u8>>>>,
    fail: AtomicBool,
    reads: AtomicUsize,
    writes: AtomicUsize,
}
impl CredentialBackend for FakeKeyring {
    fn get(&self, _: &str) -> Result<Zeroizing<Vec<u8>>, KeyringFailure> {
        self.reads.fetch_add(1, Ordering::SeqCst);
        if self.fail.load(Ordering::SeqCst) {
            return Err(KeyringFailure::Unavailable);
        }
        self.secret
            .lock()
            .unwrap()
            .clone()
            .ok_or(KeyringFailure::Missing)
    }
    fn set(&self, _: &str, secret: &[u8]) -> Result<(), KeyringFailure> {
        self.writes.fetch_add(1, Ordering::SeqCst);
        if self.fail.load(Ordering::SeqCst) {
            return Err(KeyringFailure::Unavailable);
        }
        *self.secret.lock().unwrap() = Some(Zeroizing::new(secret.to_vec()));
        Ok(())
    }
    fn delete(&self, _: &str) -> Result<(), KeyringFailure> {
        if self.fail.load(Ordering::SeqCst) {
            return Err(KeyringFailure::Unavailable);
        }
        *self.secret.lock().unwrap() = None;
        Ok(())
    }
}
fn private_tempdir() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    #[cfg(unix)]
    builder.permissions(fs::Permissions::from_mode(0o700));
    builder.tempdir().unwrap()
}
fn session(owner: &str) -> Session {
    Session {
        api_url: "https://api.example.invalid".into(),
        session_id: "private-session-id".into(),
        cookies: BTreeMap::from([("session".into(), "private-cookie-value".into())]),
        ws_token: Some("private-websocket-token".into()),
        master_key: Zeroizing::new([37; 32]),
        hashed_email: owner.into(),
        user_email_salt: "private-email-salt".into(),
        email_encryption_key: Some("private-email-key".into()),
        created_at: 1234,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}
fn fake_store(path: &Path) -> (Store, Arc<FakeKeyring>) {
    let backend = Arc::new(FakeKeyring::default());
    (
        Store::with_backend(path.to_path_buf(), backend.clone()).unwrap(),
        backend,
    )
}
fn session_bytes(path: &Path) -> Vec<u8> {
    fs::read(path.join("session.json")).unwrap()
}
fn cache_file(path: &Path) -> std::path::PathBuf {
    fs::read_dir(path)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .find(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with("cache-")
                && path.extension().is_some_and(|e| e == "json")
        })
        .unwrap()
}

#[test]
fn keyring_is_preferred_and_every_private_field_is_ciphertext() {
    let temp = private_tempdir();
    let (store, backend) = fake_store(temp.path());
    let session = session("owner-a");
    store
        .save_session(&session, Some("ignored while keyring works"))
        .unwrap();
    assert_eq!(store.storage_mode().unwrap(), Some(StorageMode::OsKeyring));
    let on_disk = String::from_utf8(session_bytes(temp.path())).unwrap();
    for secret in [
        "private-session-id",
        "private-cookie-value",
        "private-websocket-token",
        "private-email-salt",
        "private-email-key",
        "owner-a",
        "api.example.invalid",
    ] {
        assert!(!on_disk.contains(secret));
    }
    let restored = store.load_session(None).unwrap().unwrap();
    assert_eq!(restored.cookies, session.cookies);
    assert_eq!(*restored.master_key, *session.master_key);
    assert_eq!(backend.writes.load(Ordering::SeqCst), 1);
    store
        .write_cache(
            "owner-a",
            "chats",
            &session.master_key,
            &json!({"title":"private-chat-title"}),
        )
        .unwrap();
    assert!(
        !String::from_utf8(fs::read(cache_file(temp.path())).unwrap())
            .unwrap()
            .contains("private-chat-title")
    );
    assert_eq!(
        store
            .read_cache("owner-a", "chats", &session.master_key)
            .unwrap(),
        Some(json!({"title":"private-chat-title"}))
    );
}

#[test]
fn existing_keyring_failure_never_falls_back_or_rewrites_credentials() {
    let temp = private_tempdir();
    let (store, backend) = fake_store(temp.path());
    let session = session("owner-a");
    store.save_session(&session, None).unwrap();
    let original = session_bytes(temp.path());
    backend.fail.store(true, Ordering::SeqCst);
    assert!(matches!(
        store.load_session(Some("fallback passphrase")),
        Err(Error::Locked)
    ));
    assert!(matches!(
        store.save_session(&session, Some("fallback passphrase")),
        Err(Error::Locked)
    ));
    assert_eq!(session_bytes(temp.path()), original);
    assert_eq!(backend.writes.load(Ordering::SeqCst), 1);
    // Explicit vault mode also cannot migrate an existing keyring record.
    let vault = Store::encrypted_vault(temp.path().to_path_buf()).unwrap();
    assert!(matches!(
        vault.load_session(Some("passphrase")),
        Err(Error::Locked)
    ));
}

#[test]
fn local_vault_requires_passphrase_authenticates_old_data_and_detects_tampering() {
    let temp = private_tempdir();
    let store = Store::encrypted_vault(temp.path().to_path_buf()).unwrap();
    let session = session("owner-a");
    assert!(matches!(
        store.save_session(&session, None),
        Err(Error::Locked)
    ));
    assert!(!temp.path().join("session.json").exists());
    store
        .save_session(&session, Some("a locally supplied passphrase"))
        .unwrap();
    assert_eq!(
        store.storage_mode().unwrap(),
        Some(StorageMode::EncryptedVault)
    );
    assert_eq!(
        *store
            .load_session(Some("a locally supplied passphrase"))
            .unwrap()
            .unwrap()
            .master_key,
        *session.master_key
    );
    let original = session_bytes(temp.path());
    assert!(matches!(
        store.load_session(Some("wrong passphrase")),
        Err(Error::Crypto)
    ));
    assert!(matches!(
        store.save_session(&session, Some("wrong passphrase")),
        Err(Error::Crypto)
    ));
    assert_eq!(session_bytes(temp.path()), original);
    let mut record: serde_json::Value = serde_json::from_slice(&original).unwrap();
    record["context"] = json!("0".repeat(64));
    fs::write(
        temp.path().join("session.json"),
        serde_json::to_vec(&record).unwrap(),
    )
    .unwrap();
    assert!(matches!(
        store.load_session(Some("a locally supplied passphrase")),
        Err(Error::Crypto)
    ));
}

#[test]
fn unavailable_initial_keyring_uses_visible_private_file_without_new_password() {
    let temp = private_tempdir();
    let (store, backend) = fake_store(temp.path());
    backend.fail.store(true, Ordering::SeqCst);
    store.save_session(&session("a"), None).unwrap();
    assert_eq!(
        store.storage_mode().unwrap(),
        Some(StorageMode::RestrictedLocalFile)
    );
    assert_eq!(
        *store.load_session(None).unwrap().unwrap().master_key,
        *session("a").master_key
    );
    assert_eq!(
        fs::metadata(temp.path().join("credential-key"))
            .unwrap()
            .mode()
            & 0o777,
        0o600
    );
    assert_eq!(
        fs::read(temp.path().join("credential-key")).unwrap().len(),
        32
    );
    let before = session_bytes(temp.path());
    backend.fail.store(false, Ordering::SeqCst);
    store.save_session(&session("a"), None).unwrap();
    assert_eq!(
        store.storage_mode().unwrap(),
        Some(StorageMode::RestrictedLocalFile)
    );
    assert_eq!(backend.writes.load(Ordering::SeqCst), 1);
    // Unavailable or altered local key material never triggers keyring fallback
    // or overwrites credentials with a newly generated key.
    fs::write(temp.path().join("credential-key"), [0u8; 32]).unwrap();
    assert!(matches!(store.load_session(None), Err(Error::Crypto)));
    let current = session_bytes(temp.path());
    assert!(matches!(
        store.save_session(&session("a"), None),
        Err(Error::Crypto)
    ));
    assert_eq!(session_bytes(temp.path()), current);
    assert_ne!(before, current);
    store.clear_session().unwrap();
    assert!(!temp.path().join("credential-key").exists());
    assert!(store.load_session(None).unwrap().is_none());
}

#[test]
fn unavailable_initial_keyring_preserves_an_explicitly_supplied_vault_password() {
    let temp = private_tempdir();
    let (store, backend) = fake_store(temp.path());
    backend.fail.store(true, Ordering::SeqCst);
    store
        .save_session(&session("a"), Some("explicit vault password"))
        .unwrap();
    assert_eq!(
        store.storage_mode().unwrap(),
        Some(StorageMode::EncryptedVault)
    );
    assert!(matches!(store.load_session(None), Err(Error::Locked)));
    assert!(!temp.path().join("credential-key").exists());
    assert_eq!(
        *store
            .load_session(Some("explicit vault password"))
            .unwrap()
            .unwrap()
            .master_key,
        *session("a").master_key
    );
}

#[test]
fn caches_reject_different_owners_keys_contexts_and_modified_ciphertext() {
    let temp = private_tempdir();
    let (store, _) = fake_store(temp.path());
    let mut session = session("owner-a");
    store.save_session(&session, None).unwrap();
    store
        .write_cache("owner-a", "chats", &session.master_key, &json!(["secret"]))
        .unwrap();
    assert!(matches!(
        store.read_cache("owner-b", "chats", &session.master_key),
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        store.read_cache("owner-a", "chats", &[1; 32]),
        Err(Error::Crypto)
    ));
    let cache = cache_file(temp.path());
    let original_cache = fs::read(&cache).unwrap();
    let mut record: serde_json::Value = serde_json::from_slice(&original_cache).unwrap();
    record["ciphertext"] = json!("AAAA");
    fs::write(&cache, serde_json::to_vec(&record).unwrap()).unwrap();
    assert!(matches!(
        store.read_cache("owner-a", "chats", &session.master_key),
        Err(Error::Crypto)
    ));
    fs::write(&cache, original_cache).unwrap();
    session.session_id = "a different signed in session".into();
    store.save_session(&session, None).unwrap();
    assert!(matches!(
        store.read_cache("owner-a", "chats", &session.master_key),
        Err(Error::Crypto)
    ));
}

#[test]
fn copied_ciphertext_cannot_cross_account_boundaries_even_with_the_same_key() {
    let first = private_tempdir();
    let second = private_tempdir();
    let (store_a, _) = fake_store(first.path());
    let (store_b, _) = fake_store(second.path());
    store_a.save_session(&session("owner-a"), None).unwrap();
    store_b.save_session(&session("owner-b"), None).unwrap();
    store_a
        .write_cache("owner-a", "chats", &[37; 32], &json!(["account-a-private"]))
        .unwrap();
    store_b
        .write_cache("owner-b", "chats", &[37; 32], &json!(["account-b-private"]))
        .unwrap();
    fs::copy(cache_file(first.path()), cache_file(second.path())).unwrap();
    assert!(matches!(
        store_b.read_cache("owner-b", "chats", &[37; 32]),
        Err(Error::Crypto)
    ));
}

#[test]
fn expired_session_does_not_retrieve_keys_or_expose_cache() {
    let temp = private_tempdir();
    let (store, backend) = fake_store(temp.path());
    let session = session("owner-a");
    store.save_session(&session, None).unwrap();
    store
        .write_cache("owner-a", "chats", &session.master_key, &json!(["secret"]))
        .unwrap();
    let mut record: serde_json::Value =
        serde_json::from_slice(&session_bytes(temp.path())).unwrap();
    record["expires_at"] = json!(1);
    fs::write(
        temp.path().join("session.json"),
        serde_json::to_vec(&record).unwrap(),
    )
    .unwrap();
    let reads = backend.reads.load(Ordering::SeqCst);
    assert!(matches!(store.load_session(None), Err(Error::Expired)));
    assert!(matches!(
        store.read_cache("owner-a", "chats", &session.master_key),
        Err(Error::Expired)
    ));
    assert_eq!(backend.reads.load(Ordering::SeqCst), reads);
}

#[test]
fn logout_reports_keyring_cleanup_failure_and_can_retry() {
    let temp = private_tempdir();
    let (store, backend) = fake_store(temp.path());
    let session = session("owner-a");
    store.save_session(&session, None).unwrap();
    store
        .write_cache("owner-a", "chats", &session.master_key, &json!(["secret"]))
        .unwrap();
    backend.fail.store(true, Ordering::SeqCst);
    assert!(matches!(store.clear_session(), Err(Error::Locked)));
    assert!(!temp.path().join("session.json").exists());
    assert!(temp.path().join("pending-cleanup.json").exists());
    assert!(store.load_session(None).unwrap().is_none());
    assert!(matches!(
        store.save_session(&session, Some("fallback")),
        Err(Error::Locked)
    ));
    assert!(matches!(
        store.read_cache("owner-a", "chats", &session.master_key),
        Err(Error::Authentication)
    ));
    assert!(fs::read_dir(temp.path()).unwrap().all(|entry| {
        let name = entry.unwrap().file_name();
        let name = name.to_string_lossy();
        !(name.starts_with("cache-") && name.ends_with(".json"))
    }));
    backend.fail.store(false, Ordering::SeqCst);
    store.clear_session().unwrap();
    assert!(backend.secret.lock().unwrap().is_none());
    assert!(store.load_session(None).unwrap().is_none());
    let remaining_json: Vec<_> = fs::read_dir(temp.path())
        .unwrap()
        .map(|entry| entry.unwrap().file_name())
        .filter(|name| name.to_string_lossy().ends_with(".json"))
        .collect();
    assert_eq!(remaining_json, ["revocation.json"]);
    let fence_bytes = fs::read(temp.path().join("revocation.json")).unwrap();
    let fence: serde_json::Value = serde_json::from_slice(&fence_bytes).unwrap();
    assert_eq!(fence["version"], 1);
    assert_eq!(fence["revoked"], true);
    assert!(fence["cleanup"].is_null());
    let text = String::from_utf8(fence_bytes).unwrap();
    assert!(!text.contains(&session.session_id));
    assert!(!text.contains("secret"));
    assert!(matches!(
        store.save_session(&session, None),
        Err(Error::Locked)
    ));
}

#[cfg(unix)]
#[test]
fn strict_permissions_symlinks_and_hardlinks_are_rejected() {
    let temp = private_tempdir();
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o755)).unwrap();
    assert!(matches!(
        Store::encrypted_vault(temp.path().to_path_buf()),
        Err(Error::Io)
    ));
    fs::set_permissions(temp.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let (store, _) = fake_store(temp.path());
    store.save_session(&session("a"), None).unwrap();
    assert_eq!(
        fs::metadata(temp.path().join("session.json"))
            .unwrap()
            .mode()
            & 0o777,
        0o600
    );
    fs::set_permissions(
        temp.path().join("session.json"),
        fs::Permissions::from_mode(0o644),
    )
    .unwrap();
    assert!(matches!(store.load_session(None), Err(Error::Io)));
    fs::set_permissions(
        temp.path().join("session.json"),
        fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    fs::hard_link(
        temp.path().join("session.json"),
        temp.path().join("linked.json"),
    )
    .unwrap();
    assert!(matches!(store.load_session(None), Err(Error::Io)));
    fs::remove_file(temp.path().join("linked.json")).unwrap();
    let other = private_tempdir();
    let marker = other.path().join("marker");
    fs::write(&marker, b"preserve").unwrap();
    fs::remove_file(temp.path().join("session.json")).unwrap();
    symlink(&marker, temp.path().join("session.json")).unwrap();
    assert!(matches!(
        store.save_session(&session("a"), None),
        Err(Error::Io)
    ));
    assert_eq!(fs::read(&marker).unwrap(), b"preserve");
    let link = other.path().join("state-link");
    symlink(temp.path(), &link).unwrap();
    assert!(matches!(Store::encrypted_vault(link), Err(Error::Io)));
}

#[test]
fn independent_handles_serialize_concurrent_atomic_cache_writes() {
    let temp = private_tempdir();
    let (store, backend) = fake_store(temp.path());
    let session = session("owner-a");
    store.save_session(&session, None).unwrap();
    let barrier = Arc::new(Barrier::new(8));
    std::thread::scope(|scope| {
        for value in 0..8 {
            let backend = backend.clone();
            let barrier = barrier.clone();
            let path = temp.path().to_path_buf();
            scope.spawn(move || {
                let store = Store::with_backend(path, backend).unwrap();
                barrier.wait();
                for _ in 0..5 {
                    store
                        .write_cache(
                            "owner-a",
                            "chats",
                            &[37; 32],
                            &json!({"writer":value,"payload":"x".repeat(8192)}),
                        )
                        .unwrap();
                }
            });
        }
    });
    let value = store
        .read_cache("owner-a", "chats", &session.master_key)
        .unwrap()
        .unwrap();
    assert!(value["writer"].as_u64().unwrap() < 8);
    assert_eq!(value["payload"].as_str().unwrap().len(), 8192);
    assert!(fs::read_dir(temp.path()).unwrap().all(|entry| {
        !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".tmp-")
    }));
}

#[test]
fn production_store_excludes_another_client_until_exit_without_reading_keyring() {
    let temp = private_tempdir();
    let first = Store::new(temp.path().to_path_buf()).unwrap();
    assert!(matches!(
        Store::new(temp.path().to_path_buf()),
        Err(Error::Invalid(_))
    ));
    drop(first);
    assert!(Store::new(temp.path().to_path_buf()).is_ok());
}

#[test]
fn anonymous_identity_is_stable_private_and_independent_of_login_and_device() {
    let temp = private_tempdir();
    let (store, backend) = fake_store(temp.path());
    let id = store.anonymous_identity().unwrap();
    assert_eq!(uuid::Uuid::parse_str(&id).unwrap().get_version_num(), 4);
    assert_ne!(id, store.device_identity().unwrap());
    assert_eq!(id, store.anonymous_identity().unwrap());
    assert_eq!(backend.reads.load(Ordering::SeqCst), 0);
    assert_eq!(backend.writes.load(Ordering::SeqCst), 0);
    #[cfg(unix)]
    assert_eq!(
        fs::metadata(temp.path().join("anonymous-id"))
            .unwrap()
            .mode()
            & 0o777,
        0o600
    );
    store.clear_session().unwrap();
    drop(store);
    let (reopened, _) = fake_store(temp.path());
    assert_eq!(id, reopened.anonymous_identity().unwrap());
    assert!(reopened.load_session(None).unwrap().is_none());
    assert!(!temp.path().join("session.json").exists());
}

#[test]
fn anonymous_identity_rejects_corruption_without_replacing_it() {
    let temp = private_tempdir();
    let (store, _) = fake_store(temp.path());
    store.anonymous_identity().unwrap();
    for bytes in [
        b"not-a-uuid".as_slice(),
        b"00000000-0000-0000-0000-000000000000".as_slice(),
    ] {
        fs::write(temp.path().join("anonymous-id"), bytes).unwrap();
        assert!(store.anonymous_identity().is_err());
        assert_eq!(fs::read(temp.path().join("anonymous-id")).unwrap(), bytes);
    }
}

#[cfg(unix)]
#[test]
fn anonymous_identity_rejects_links_and_leaves_the_target_untouched() {
    let temp = private_tempdir();
    let (store, _) = fake_store(temp.path());
    let target = temp.path().join("target");
    fs::write(&target, b"sentinel").unwrap();
    fs::set_permissions(&target, fs::Permissions::from_mode(0o600)).unwrap();
    let record = temp.path().join("anonymous-id");
    symlink(&target, &record).unwrap();
    assert!(store.anonymous_identity().is_err());
    fs::remove_file(&record).unwrap();
    fs::hard_link(&target, &record).unwrap();
    assert!(store.anonymous_identity().is_err());
    assert_eq!(fs::read(&target).unwrap(), b"sentinel");
}
