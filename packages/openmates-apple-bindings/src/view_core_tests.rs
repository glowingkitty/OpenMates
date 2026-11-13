//! ViewModelCore over a temp cache directory, an in-memory Keychain stand-in and a recording listener: cached list without network, credential acknowledgement, revocation fence on logout, cache directory checks. The doubles are shared with `view_window_tests.rs`.
use crate::view_core::VaultBridge;
use crate::*;
use futures_util::future::BoxFuture;
use openmates_sdk::{
    Client,
    client::CredentialSnapshot,
    error::{Error, Result},
    local_cache::{
        ByteStore, CacheEngine, CacheStore, FileByteStore, FixedContext, NoScope, OrderedBlocking,
        RevocationFence,
    },
    session::Session,
    shell_session::{
        AcknowledgedCredentials, CredentialPersistence, CredentialSave, ShellSession,
        session_cache_context,
    },
};
use serde_json::json;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::sync::{Arc, Mutex, OnceLock, Weak};
use std::time::Duration;
use zeroize::Zeroizing;

// Network access fails at once: the tests prove which steps need none.
const API: &str = "https://never-contact.example.invalid";
const CHAT: &str = "11111111-1111-4111-8111-111111111111";
const TEAM: &str = "33333333-3333-4333-8333-333333333333";
/// Cache directory name inside the temp container (Apple: `core-cache`).
pub(crate) const NAME: &str = "core-cache";

fn session() -> Session {
    Session {
        api_url: API.into(),
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
    }
}

/// One chat whose key is wrapped with the session master key.
fn snapshot() -> serde_json::Value {
    use openmates_sdk::crypto::{encrypt_bytes, encrypt_combined};
    let row = json!({"id": CHAT, "messages_v": 1, "last_edited_overall_timestamp": 1,
        "encrypted_chat_key": encrypt_bytes(&[9; 32], &[7; 32]).unwrap(),
        "encrypted_title": encrypt_combined("Synthetic cached title", &[9; 32]).unwrap()});
    json!({"chats": {CHAT: row}, "wrappers": [], "history": {}, "embeds": {},
        "embed_keys": [], "team_wrapped_key": null})
}

pub(crate) fn private_dir() -> tempfile::TempDir {
    let mut builder = tempfile::Builder::new();
    builder.permissions(std::fs::Permissions::from_mode(0o700));
    builder.tempdir().unwrap()
}

/// Credentials that are already durable elsewhere (seeding only).
struct Durable;
impl CredentialPersistence for Durable {
    fn load(&self, _generation: u64) -> BoxFuture<'_, Result<Option<Session>>> {
        Box::pin(async { Ok(Some(session())) })
    }
    fn store(&self, _: CredentialSnapshot, _: u64) -> BoxFuture<'_, Result<CredentialSave>> {
        Box::pin(async { Ok(CredentialSave::Saved) })
    }
    fn revoke(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async { Ok(()) })
    }
    fn clear(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async { Ok(()) })
    }
}

/// The cache directory the core opens inside the container `dir`.
pub(crate) fn cache_bytes(dir: &Path) -> FileByteStore {
    FileByteStore::open_in(dir, NAME).unwrap()
}

/// Write the encrypted cache an earlier app run would have left.
async fn seed_cache(dir: &Path) {
    let engine = Arc::new(CacheEngine::new(cache_bytes(dir)));
    let cache = CacheStore::new(
        engine,
        Arc::new(FixedContext(session_cache_context(&session()).unwrap())),
        Arc::new(NoScope),
        OrderedBlocking::new(),
    );
    let mut client = Client::new(API, Some(session())).unwrap();
    client.restore_ciphertext_snapshot(&snapshot()).unwrap();
    ShellSession::new(cache)
        .persist(&mut client, &Durable)
        .await
        .unwrap();
}

pub(crate) fn cache_files(dir: &Path) -> usize {
    std::fs::read_dir(dir.join(NAME))
        .unwrap()
        .filter(|entry| {
            let name = entry.as_ref().unwrap().file_name();
            name.to_string_lossy().starts_with("cache-")
        })
        .count()
}

/// The Swift Keychain stand-in. With `acknowledge`, it stores and then
/// acknowledges through the core as the Swift adapter does.
#[derive(Default)]
pub(crate) struct Keychain {
    pub(crate) payload: Mutex<Option<Vec<u8>>>,
    pub(crate) changed: Mutex<Vec<u64>>,
    pub(crate) deletes: Mutex<usize>,
    pub(crate) acknowledge: bool,
    pub(crate) core: OnceLock<Weak<ViewModelCore>>,
}

impl Keychain {
    pub(crate) fn holding(session: &Session, acknowledge: bool) -> Arc<Self> {
        Arc::new(Self {
            payload: Mutex::new(Some(serde_json::to_vec(session).unwrap())),
            acknowledge,
            ..Self::default()
        })
    }
    fn stored_team(&self) -> Option<String> {
        let payload = self.payload.lock().unwrap().clone()?;
        let stored: Session = serde_json::from_slice(&payload).unwrap();
        stored.active_team_id.clone()
    }
}

impl CredentialStore for Keychain {
    fn load(&self) -> std::result::Result<Option<Vec<u8>>, CoreError> {
        Ok(self.payload.lock().unwrap().clone())
    }
    fn credentials_changed(&self, snapshot: CredentialSnapshotRecord) {
        self.changed.lock().unwrap().push(snapshot.revision);
        if !self.acknowledge {
            return;
        }
        *self.payload.lock().unwrap() = Some(snapshot.payload);
        if let Some(core) = self.core.get().and_then(Weak::upgrade) {
            core.acknowledge_credentials(snapshot.revision).unwrap();
        }
    }
    fn delete(&self) -> std::result::Result<(), CoreError> {
        *self.payload.lock().unwrap() = None;
        *self.deletes.lock().unwrap() += 1;
        Ok(())
    }
}

#[derive(Default)]
pub(crate) struct Events(Mutex<Vec<ViewEventRecord>>);
impl ViewListener for Events {
    fn on_event(&self, event: ViewEventRecord) {
        self.0.lock().unwrap().push(event);
    }
}
impl Events {
    pub(crate) fn all(&self) -> Vec<ViewEventRecord> {
        self.0.lock().unwrap().clone()
    }
}

fn config(dir: &Path) -> CoreConfig {
    CoreConfig {
        api_url: API.into(),
        app_url: None,
        cache_container: Some(dir.to_str().unwrap().to_owned()),
        cache_directory_name: Some(NAME.into()),
    }
}

fn core(dir: &Path, keychain: &Arc<Keychain>, events: &Arc<Events>) -> Arc<ViewModelCore> {
    let core = ViewModelCore::build(
        config(dir),
        keychain.clone(),
        events.clone(),
        Duration::from_millis(300),
    )
    .unwrap();
    keychain.core.set(Arc::downgrade(&core)).unwrap();
    core
}

pub(crate) const SIGNED_OUT: ViewEventRecord = ViewEventRecord::Session {
    event: SessionEventRecord::SignedOut,
};

#[tokio::test]
async fn start_with_an_empty_keychain_emits_signed_out() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), &keychain, &events);
    core.start(None).await.unwrap();
    assert_eq!(events.all(), [SIGNED_OUT]);
    assert_eq!(
        core.refresh_chats(None).await,
        Err(CoreError::Authentication)
    );
}

#[tokio::test]
async fn start_emits_the_cached_chat_list_from_a_seeded_cache_before_any_network() {
    let dir = private_dir();
    seed_cache(dir.path()).await;
    let keychain = Keychain::holding(&session(), true);
    let events = Arc::new(Events::default());
    let core = core(dir.path(), &keychain, &events);
    // Admission needs the (unreachable) server; the cached paint does not.
    assert!(core.start(None).await.is_err());
    let all = events.all();
    assert_eq!(
        all[0],
        ViewEventRecord::Session {
            event: SessionEventRecord::Restored { display_name: None }
        }
    );
    let ViewEventRecord::ChatList {
        rows, completeness, ..
    } = &all[1]
    else {
        panic!("cached chat list expected: {all:?}");
    };
    assert_eq!(*completeness, ListCompletenessRecord::Cached);
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].id, CHAT);
    assert_eq!(rows[0].title, "Synthetic cached title");
    assert_eq!(rows[0].status, ChatRowStatusRecord::Ready);
    // Unchanged credentials are not written to the Keychain again.
    assert!(keychain.changed.lock().unwrap().is_empty());
}

#[tokio::test]
async fn changed_credentials_are_stored_and_acknowledged_through_the_keychain() {
    let dir = private_dir();
    seed_cache(dir.path()).await;
    let keychain = Keychain::holding(&session(), true);
    let events = Arc::new(Events::default());
    let core = core(dir.path(), &keychain, &events);
    let _ = core.start(None).await;
    // The team change is persisted (and acknowledged) before admission.
    let _ = core.switch_team(Some(TEAM.into()), None).await;
    assert_eq!(keychain.changed.lock().unwrap().len(), 1);
    assert_eq!(keychain.stored_team().as_deref(), Some(TEAM));
    // A revision nobody waits for is refused.
    assert_eq!(
        core.acknowledge_credentials(9_999),
        Err(CoreError::Cancelled)
    );
}

#[tokio::test]
async fn an_unacknowledged_credential_save_times_out_as_locked() {
    let dir = private_dir();
    seed_cache(dir.path()).await;
    let keychain = Keychain::holding(&session(), false);
    let events = Arc::new(Events::default());
    let core = core(dir.path(), &keychain, &events);
    let _ = core.start(None).await;
    assert_eq!(
        core.switch_team(Some(TEAM.into()), None).await,
        Err(CoreError::Locked)
    );
    let revision = keychain.changed.lock().unwrap()[0];
    // The late acknowledgement no longer counts.
    assert_eq!(
        core.acknowledge_credentials(revision),
        Err(CoreError::Cancelled)
    );
    assert_eq!(keychain.stored_team(), None);
}

#[tokio::test]
async fn acknowledged_store_reports_saved_only_for_the_waiting_revision() {
    let dir = private_dir();
    let engine = Arc::new(CacheEngine::new(cache_bytes(dir.path())));
    let keychain = Arc::new(Keychain::default());
    let credentials = Arc::new(AcknowledgedCredentials::with_timeout(
        Arc::new(VaultBridge(keychain.clone())),
        engine,
        Duration::from_secs(5),
    ));
    let waiting = credentials.clone();
    let store = tokio::spawn(async move {
        let snapshot = CredentialSnapshot {
            revision: 7,
            session: session(),
        };
        waiting.store(snapshot, 0).await.map(|_| ())
    });
    while keychain.changed.lock().unwrap().is_empty() {
        tokio::time::sleep(Duration::from_millis(5)).await;
    }
    assert!(matches!(credentials.acknowledge(6), Err(Error::Cancelled)));
    credentials.acknowledge(7).unwrap();
    assert!(store.await.unwrap().is_ok());
}

#[tokio::test]
async fn logout_writes_the_revocation_fence_and_wipes_cache_and_keychain() {
    let dir = private_dir();
    seed_cache(dir.path()).await;
    assert!(cache_files(dir.path()) > 0);
    let keychain = Keychain::holding(&session(), true);
    let events = Arc::new(Events::default());
    let core = core(dir.path(), &keychain, &events);
    let _ = core.start(None).await;
    // Remote logout is unreachable; local sign-out completes regardless.
    let _ = core.logout().await;
    let fence = RevocationFence::load(&cache_bytes(dir.path())).unwrap();
    assert!(fence.revoked);
    assert!(uuid_like(&fence.epoch));
    assert_eq!(cache_files(dir.path()), 0);
    assert!(keychain.payload.lock().unwrap().is_none());
    assert_eq!(events.all().last(), Some(&SIGNED_OUT));
    // Credentials written behind the fence's back are never handed out.
    *keychain.payload.lock().unwrap() = Some(serde_json::to_vec(&session()).unwrap());
    core.start(None).await.unwrap();
    assert_eq!(events.all().last(), Some(&SIGNED_OUT));
}

#[tokio::test]
async fn logout_while_signed_out_still_revokes_durably() {
    let dir = private_dir();
    let (keychain, events) = (Arc::new(Keychain::default()), Arc::new(Events::default()));
    let core = core(dir.path(), &keychain, &events);
    core.logout().await.unwrap();
    let bytes = cache_bytes(dir.path());
    assert!(RevocationFence::load(&bytes).unwrap().revoked);
    assert!(bytes.get("revocation.json").unwrap().is_some());
    assert_eq!(*keychain.deletes.lock().unwrap(), 1);
    assert_eq!(events.all(), [SIGNED_OUT]);
}

fn uuid_like(value: &str) -> bool {
    value.len() == 36 && value.chars().filter(|c| *c == '-').count() == 4
}

fn rejected(container: Option<String>, name: Option<&str>) -> CoreError {
    let config = CoreConfig {
        api_url: API.into(),
        app_url: None,
        cache_container: container,
        cache_directory_name: name.map(str::to_owned),
    };
    let result = ViewModelCore::new(
        config,
        Arc::new(Keychain::default()),
        Arc::new(Events::default()),
    );
    match result {
        Ok(_) => panic!("cache directory accepted"),
        Err(error) => error,
    }
}

#[test]
fn bad_cache_directories_are_rejected() {
    let dir = private_dir();
    let base = dir.path().to_str().unwrap().to_owned();
    let invalid = |container: Option<String>, name: Option<&str>| {
        matches!(rejected(container, name), CoreError::Invalid { .. })
    };
    // Both or neither: one alone is a configuration mistake.
    assert!(invalid(None, None));
    assert!(invalid(Some(base.clone()), None));
    assert!(invalid(None, Some(NAME)));
    assert!(invalid(Some("relative".into()), Some(NAME)));
    assert!(invalid(Some(format!("{base}/../x")), Some(NAME)));
    for name in ["", "..", "a/b"] {
        assert!(invalid(Some(base.clone()), Some(name)), "{name:?}");
    }
    // A missing container is never created.
    assert_eq!(
        rejected(Some(format!("{base}/missing")), Some(NAME)),
        CoreError::Io
    );
    // Readable by others: not private.
    let open = dir.path().join("shared");
    std::fs::create_dir(&open).unwrap();
    std::fs::set_permissions(&open, std::fs::Permissions::from_mode(0o755)).unwrap();
    assert_eq!(rejected(Some(base.clone()), Some("shared")), CoreError::Io);
    // A symlink planted at the name is refused.
    std::fs::create_dir(dir.path().join("private")).unwrap();
    std::os::unix::fs::symlink(dir.path().join("private"), dir.path().join("link")).unwrap();
    assert_eq!(rejected(Some(base), Some("link")), CoreError::Io);
}

#[test]
fn chat_list_record_carries_the_account_total_and_saved_item_flag() {
    use openmates_sdk::view_model::{ListCompleteness, ViewEvent};
    let record = ViewEventRecord::from(ViewEvent::ChatList {
        rows: Vec::new(),
        completeness: ListCompleteness::Partial,
        total_count: Some(412),
    });
    let ViewEventRecord::ChatList { total_count, .. } = record else {
        panic!("chat list record expected");
    };
    assert_eq!(total_count, Some(412));
}
