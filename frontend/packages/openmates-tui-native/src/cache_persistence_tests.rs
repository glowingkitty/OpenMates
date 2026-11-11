//! Change-only, lazily loaded and sectioned sync-cache persistence through the
//! real RuntimeStore/session_runtime boundary. Each "process" is a fresh Store
//! over the same private directory, as a later CLI invocation would see it.
use super::*;
use crate::{
    client::Client,
    session_runtime::{self, CacheLoad},
    storage::{CredentialBackend, KeyringFailure},
};
use serde_json::json;
use std::sync::Mutex as BlockingMutex;

/// Synchronous section calls straight on the core engine, as a second
/// process over the same directory would make them.
trait SyncCalls {
    fn read_sync_cache(&self, owner: &str, key: &str, master: &[u8; 32], mode: crate::storage::SyncReadMode) -> Result<Option<crate::storage::SyncCacheRead>>;
    fn read_sync_chat(&self, owner: &str, key: &str, master: &[u8; 32], chat: &str) -> Result<Option<Value>>;
    fn prepare_sync_sections(&self, snapshot: Value, partial: Option<Vec<String>>) -> Result<crate::storage::PreparedSections>;
    fn write_sync_sections(&self, owner: &str, key: &str, master: &[u8; 32], prepared: crate::storage::PreparedSections) -> Result<bool>;
    fn revoke_sync_freshness(&self, owner: &str, key: &str) -> Result<()>;
}
impl SyncCalls for Store {
    fn read_sync_cache(&self, owner: &str, key: &str, master: &[u8; 32], mode: crate::storage::SyncReadMode) -> Result<Option<crate::storage::SyncCacheRead>> {
        self.cache_engine().read_sync_cache(self, owner, key, master, mode)
    }
    fn read_sync_chat(&self, owner: &str, key: &str, master: &[u8; 32], chat: &str) -> Result<Option<Value>> {
        self.cache_engine().read_sync_chat(self, owner, key, master, chat)
    }
    fn prepare_sync_sections(&self, snapshot: Value, partial: Option<Vec<String>>) -> Result<crate::storage::PreparedSections> {
        self.cache_engine().prepare_sync_sections(snapshot, partial)
    }
    fn write_sync_sections(&self, owner: &str, key: &str, master: &[u8; 32], prepared: crate::storage::PreparedSections) -> Result<bool> {
        self.cache_engine().write_sync_sections(self, owner, key, master, prepared)
    }
    fn revoke_sync_freshness(&self, owner: &str, key: &str) -> Result<()> {
        self.cache_engine().revoke_sync_freshness(self, owner, key)
    }
}

const A: &str = "11111111-1111-4111-8111-111111111111";
const B: &str = "22222222-2222-4222-8222-222222222222";

#[derive(Default)]
struct MemoryKeyring(BlockingMutex<Option<Zeroizing<Vec<u8>>>>);
impl CredentialBackend for MemoryKeyring {
    fn get(&self, _: &str) -> std::result::Result<Zeroizing<Vec<u8>>, KeyringFailure> {
        self.0.lock().unwrap().clone().ok_or(KeyringFailure::Missing)
    }
    fn set(&self, _: &str, secret: &[u8]) -> std::result::Result<(), KeyringFailure> {
        *self.0.lock().unwrap() = Some(Zeroizing::new(secret.to_vec()));
        Ok(())
    }
    fn delete(&self, _: &str) -> std::result::Result<(), KeyringFailure> {
        *self.0.lock().unwrap() = None;
        Ok(())
    }
}
struct Profile {
    directory: tempfile::TempDir,
    keyring: Arc<MemoryKeyring>,
    session: Session,
}
impl Profile {
    fn new() -> Self {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        Self {
            directory: builder.tempdir().unwrap(),
            keyring: Arc::default(),
            session: Session {
                api_url: "https://never-contact.example.invalid".into(),
                session_id: "synthetic-session".into(),
                cookies: Default::default(),
                ws_token: None,
                master_key: Zeroizing::new([7; 32]),
                hashed_email: "synthetic-owner".into(),
                user_email_salt: String::new(),
                email_encryption_key: None,
                created_at: 1,
                paired_session_expires_at: None,
                active_team_id: None,
            },
        }
    }
    /// A fresh "process": new Store, empty in-memory evidence.
    fn process(&self) -> RuntimeStore {
        RuntimeStore::from_store(Arc::new(Store::with_backend(self.directory.path().to_path_buf(), self.keyring.clone()).unwrap()))
    }
    fn client(&self) -> Client {
        Client::new(&self.session.api_url, Some(self.session.clone())).unwrap()
    }
    fn cache_files(&self) -> Vec<String> {
        let mut names: Vec<String> = std::fs::read_dir(self.directory.path())
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .filter(|name| name.starts_with("cache-") && name.ends_with(".json"))
            .collect();
        names.sort();
        names
    }
}
fn hashed(id: &str) -> String {
    use sha2::Digest;
    sha2::Sha256::digest(id.as_bytes()).iter().map(|byte| format!("{byte:02x}")).collect()
}
fn content() -> Value {
    json!({
        "chats": {A: {"id": A, "encrypted_title": "ta"}, B: {"id": B, "encrypted_title": "tb"}},
        "wrappers": [],
        "history": {A: [{"message_id": "a1"}], B: [{"message_id": "b1"}]},
        "embeds": {
            "e-a": {"embed_id": "e-a", "hashed_chat_id": hashed(A)},
            "e-b": {"embed_id": "e-b", "hashed_chat_id": hashed(B)},
            "e-free": {"embed_id": "e-free", "hashed_chat_id": null},
        },
        "embed_keys": [{"id": "k-master", "hashed_chat_id": null}],
        "team_wrapped_key": null,
    })
}
/// Persist a profile whose cache holds `content()` in the sectioned layout.
async fn seeded() -> (Profile, Value) {
    let profile = Profile::new();
    let runtime = profile.process();
    let mut client = profile.client();
    client.restore_ciphertext_snapshot(&content()).unwrap();
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    let expected = client.ciphertext_snapshot();
    (profile, expected)
}
async fn command(profile: &Profile, load: CacheLoad) -> (RuntimeStore, Client) {
    let runtime = profile.process();
    let mut client = profile.client();
    session_runtime::restore_command_cache(&mut client, &runtime, None, &CancellationToken::new(), load)
        .await
        .unwrap();
    (runtime, client)
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
#[tokio::test]
async fn whoami_never_reads_or_writes_the_cache_or_rewrites_unchanged_credentials() {
    let (profile, _) = seeded().await;
    let files = profile.cache_files();
    let bytes: Vec<Vec<u8>> = files.iter().map(|name| std::fs::read(profile.directory.path().join(name)).unwrap()).collect();
    let (runtime, mut client) =
        command(&profile, CacheLoad::Deferred { revoke_list_freshness: false }).await;
    // Admission save, then the final output save: both are change-only.
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    assert_eq!(runtime.store.io_counts_for_test(), (0, 0, 0, 0));
    assert_eq!(profile.cache_files(), files);
    for (name, bytes) in files.iter().zip(bytes) {
        assert_eq!(std::fs::read(profile.directory.path().join(name)).unwrap(), bytes);
    }
    // A rotated credential is still published exactly once.
    client.take_session();
    let mut rotated = profile.session.clone();
    rotated.cookies.insert("auth_refresh_token".into(), "rotated".into());
    let api = rotated.api_url.clone();
    let mut client = Client::new(&api, Some(rotated)).unwrap();
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    let (reads, writes, sessions, _) = runtime.store.io_counts_for_test();
    assert_eq!((reads, writes, sessions), (0, 0, 1));
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
#[tokio::test]
async fn deferred_commands_revoke_list_freshness_with_one_marker_and_no_cache_io() {
    let (profile, _) = seeded().await;
    let files = profile.cache_files();
    let (runtime, mut client) =
        command(&profile, CacheLoad::Deferred { revoke_list_freshness: true }).await;
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    let (reads, writes, sessions, revocations) = runtime.store.io_counts_for_test();
    assert_eq!((reads, writes, sessions, revocations), (0, 1, 0, 0), "only the revocation marker");
    assert_eq!(profile.cache_files().len(), files.len() + 1);
    // The next real cache publication removes the marker again.
    let (runtime, mut client) = command(&profile, CacheLoad::Index).await;
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    assert_eq!(profile.cache_files(), files);
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
#[tokio::test]
async fn chats_list_reads_only_the_index_and_never_rewrites_an_unchanged_cache() {
    let (profile, expected) = seeded().await;
    let (runtime, mut client) = command(&profile, CacheLoad::Index).await;
    assert_eq!(runtime.store.io_counts_for_test().0, 1, "index record only");
    assert_eq!(client.partially_restored_chats(), Some(vec![]));
    assert!(client.ciphertext_snapshot()["history"].as_object().unwrap().is_empty());
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    let (reads, writes, sessions, revocations) = runtime.store.io_counts_for_test();
    assert_eq!((reads, writes, sessions, revocations), (1, 0, 0, 0));
    // Unloaded content was retained, not replaced by the index-only client.
    let (_, client) = command(&profile, CacheLoad::Full).await;
    assert_eq!(client.ciphertext_snapshot(), expected);
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
#[tokio::test]
async fn cached_chat_open_decrypts_one_chat_and_rewrites_only_what_changed() {
    let (profile, expected) = seeded().await;
    let (runtime, mut client) = command(&profile, CacheLoad::Chat(A.into())).await;
    assert_eq!(runtime.store.io_counts_for_test().0, 2, "index + one Chat record");
    let snapshot = client.ciphertext_snapshot();
    assert_eq!(snapshot["history"][A], expected["history"][A]);
    assert!(snapshot["history"].get(B).is_none() && snapshot["embeds"].get("e-b").is_none());
    assert!(snapshot["embeds"]["e-a"].is_object());
    // Change only Chat A's content: exactly its record plus the index commit.
    let mut changed = snapshot.clone();
    changed["history"][A] = json!([{"message_id": "a1"}, {"message_id": "a2"}]);
    let loader = runtime.sync_content_loader(
        profile.session.hashed_email.clone(),
        session_runtime::cache_key(&profile.session),
        profile.session.master_key.clone(),
    );
    let mut sections = openmates_sdk::client::snapshot_sections::split(changed).unwrap();
    let a = Value::Object(sections.chats.remove(A).unwrap());
    client.restore_authenticated_ciphertext_index(&Value::Object(sections.index), loader).unwrap();
    client.restore_cached_chat_content(A, Some(&a)).unwrap();
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    let (_, writes, sessions, _) = runtime.store.io_counts_for_test();
    assert_eq!((writes, sessions), (2, 0));
    let (_, client) = command(&profile, CacheLoad::Full).await;
    let mut want = expected.clone();
    want["history"][A] = json!([{"message_id": "a1"}, {"message_id": "a2"}]);
    assert_eq!(client.ciphertext_snapshot(), want);
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
#[tokio::test]
async fn legacy_single_file_cache_restores_and_upgrades_to_sections_once() {
    let profile = Profile::new();
    let runtime = profile.process();
    let mut client = profile.client();
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    let key = session_runtime::cache_key(&profile.session);
    // Exactly the pre-sections on-disk format: one record holding everything.
    for name in profile.cache_files() {
        std::fs::remove_file(profile.directory.path().join(name)).unwrap();
    }
    runtime
        .store
        .write_cache(&profile.session.hashed_email, &key, &profile.session.master_key, &content())
        .unwrap();
    assert_eq!(profile.cache_files().len(), 1);
    let legacy = profile.cache_files();
    // An index-only command on a legacy cache restores it completely...
    let (runtime, mut client) = command(&profile, CacheLoad::Index).await;
    assert_eq!(client.partially_restored_chats(), None);
    let mut reference = profile.client();
    reference.restore_ciphertext_snapshot(&content()).unwrap();
    let expected = reference.ciphertext_snapshot();
    assert_eq!(client.ciphertext_snapshot(), expected);
    // ...and its first save migrates to sections and retires the old file.
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    let files = profile.cache_files();
    assert!(!files.contains(&legacy[0]));
    assert_eq!(files.len(), 4, "index + shared + two Chat records");
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    assert_eq!(profile.cache_files(), files);
    let (_, client) = command(&profile, CacheLoad::Full).await;
    assert_eq!(client.ciphertext_snapshot(), expected);
    // The compatibility reader assembles the same snapshot for older callers.
    let assembled = profile
        .process()
        .read_cache(profile.session.hashed_email.clone(), key, profile.session.master_key.clone())
        .await
        .unwrap()
        .unwrap();
    let mut restored = profile.client();
    restored.restore_ciphertext_snapshot(&assembled).unwrap();
    assert_eq!(restored.ciphertext_snapshot(), expected);
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
#[tokio::test]
async fn uncommitted_chat_record_reads_as_absent_and_revoked_freshness_is_dropped() {
    let (profile, expected) = seeded().await;
    let key = session_runtime::cache_key(&profile.session);
    let runtime = profile.process();
    let store = &runtime.store;
    let owner = profile.session.hashed_email.as_str();
    let master = &profile.session.master_key;
    // Simulate a crash after a new Chat record but before its index commit.
    let Some(crate::storage::SyncCacheRead::Index(_)) =
        store.read_sync_cache(owner, &key, master, crate::storage::SyncReadMode::Index).unwrap()
    else {
        panic!("sectioned index expected")
    };
    let mut changed = expected.clone();
    changed["history"][A] = json!([{"message_id": "uncommitted"}]);
    let other = profile.process();
    other.store.read_sync_cache(owner, &key, master, crate::storage::SyncReadMode::Complete).unwrap();
    let prepared = other.store.prepare_sync_sections(changed, None).unwrap();
    other.store.write_sync_sections(owner, &key, master, prepared).unwrap();
    // `store` still holds the old manifest: the rewritten record's set differs.
    assert_eq!(store.read_sync_chat(owner, &key, master, A).unwrap(), None);
    assert!(store.read_sync_chat(owner, &key, master, B).unwrap().is_some());
    // A durable revocation removes only the list-freshness receipt on restore.
    let mut with_receipt = expected.clone();
    with_receipt[openmates_sdk::client::snapshot_sections::CHAT_LIST_FRESHNESS_FIELD] = json!({"synthetic": true});
    let prepared = other.store.prepare_sync_sections(with_receipt, None).unwrap();
    other.store.write_sync_sections(owner, &key, master, prepared).unwrap();
    other.store.revoke_sync_freshness(owner, &key).unwrap();
    let read = |store: &Store| match store.read_sync_cache(owner, &key, master, crate::storage::SyncReadMode::Index).unwrap() {
        Some(crate::storage::SyncCacheRead::Index(index)) => index,
        _ => panic!("sectioned index expected"),
    };
    let field = openmates_sdk::client::snapshot_sections::CHAT_LIST_FRESHNESS_FIELD;
    assert!(read(&profile.process().store).get(field).is_none());
}

// contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
#[tokio::test]
async fn crash_between_chat_records_and_index_commit_never_mixes_generations() {
    let (profile, expected) = seeded().await;
    let key = session_runtime::cache_key(&profile.session);
    let index_name = profile
        .cache_files()
        .into_iter()
        .find(|name| {
            use sha2::Digest;
            let digest: String = sha2::Sha256::digest(format!("{key}#index").as_bytes())
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect();
            name.ends_with(&format!("-{digest}.json"))
        })
        .unwrap();
    let committed_index = std::fs::read(profile.directory.path().join(&index_name)).unwrap();
    // A later command rewrites Chat A's record and commits a new index...
    let (runtime, mut client) = command(&profile, CacheLoad::Full).await;
    let mut changed = client.ciphertext_snapshot();
    changed["history"][A] = json!([{"message_id": "a1"}, {"message_id": "a-new"}]);
    changed["embeds"]["e-a"]["version_number"] = json!(2);
    client.restore_authenticated_ciphertext_snapshot(&changed).unwrap();
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    // ...but the machine crashed before the index rename became durable: the
    // new Chat A record is on disk while the old index is still committed.
    std::fs::write(profile.directory.path().join(&index_name), &committed_index).unwrap();
    let (runtime, mut client) = command(&profile, CacheLoad::Full).await;
    let restored = client.ciphertext_snapshot();
    assert!(restored["history"].get(A).is_none(), "uncommitted record is absent content");
    assert!(restored["embeds"].get("e-a").is_none(), "no mixed-generation embed");
    assert_eq!(restored["history"][B], expected["history"][B]);
    assert_eq!(restored["embeds"]["e-b"], expected["embeds"]["e-b"]);
    assert_eq!(restored["chats"], expected["chats"]);
    // The same, lazily: index + Chat A reads as an uncached Chat.
    let (_, lazy) = command(&profile, CacheLoad::Chat(A.into())).await;
    assert!(lazy.ciphertext_snapshot()["history"].get(A).is_none());
    // The next save converges disk and manifest again.
    session_runtime::persist(&mut client, &runtime, None).await.unwrap();
    let (_, client) = command(&profile, CacheLoad::Full).await;
    assert_eq!(client.ciphertext_snapshot(), restored);
}
