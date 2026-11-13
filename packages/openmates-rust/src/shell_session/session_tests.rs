//! `ShellSession` over a real cache directory and a recording credential
//! store: what is durable before what, receipt minting and logout ordering.
use super::*;
use crate::{
    client::CredentialSnapshot,
    local_cache::{
        ByteStore, CacheContext, CacheEngine, CacheStore, Durability, FileByteStore, FixedContext,
        NoScope, REVOCATION_FILE, RevocationFence, owner_hash,
    },
};
use futures_util::future::BoxFuture;
use serde_json::{Value, json};
use std::sync::{
    Arc, Mutex,
    atomic::{AtomicBool, Ordering},
};

const OWNER: &str = "synthetic-owner";
const A: &str = "11111111-1111-4111-8111-111111111111";
const EPOCH: &str = "c4f86cef-590c-4a5e-8120-eb6a27ded8a2";

fn synthetic_session() -> Session {
    Session {
        api_url: "https://never-contact.example.invalid".into(),
        session_id: "synthetic-session".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: Zeroizing::new([7; 32]),
        hashed_email: OWNER.into(),
        user_email_salt: String::new(),
        email_encryption_key: None,
        created_at: 1,
        paired_session_expires_at: None,
        active_team_id: None,
    }
}

fn content() -> Value {
    json!({
        "chats": {A: {"id": A, "encrypted_title": "ta"}},
        "wrappers": [],
        "history": {A: [{"message_id": "a1"}]},
        "embeds": {},
        "embed_keys": [],
        "team_wrapped_key": null,
    })
}

/// Records every call and what was durable at that moment.
struct Recorder {
    dir: std::path::PathBuf,
    stored: Mutex<Option<Session>>,
    superseded: Mutex<Option<Session>>,
    fail_store: AtomicBool,
    /// Advance this queue inside `store` (a logout racing the credential save).
    advance_in_store: Mutex<Option<OrderedBlocking>>,
    events: Mutex<Vec<String>>,
}

impl Recorder {
    fn new(dir: &tempfile::TempDir) -> Self {
        Self {
            dir: dir.path().to_path_buf(),
            stored: Mutex::new(None),
            superseded: Mutex::new(None),
            fail_store: AtomicBool::new(false),
            advance_in_store: Mutex::new(None),
            events: Mutex::new(Vec::new()),
        }
    }
    fn cache_files(&self) -> usize {
        std::fs::read_dir(&self.dir)
            .unwrap()
            .filter(|entry| {
                let name = entry.as_ref().unwrap().file_name();
                let name = name.to_string_lossy();
                name.starts_with("cache-") && name.ends_with(".json")
            })
            .count()
    }
    fn fence(&self) -> RevocationFence {
        RevocationFence::load(&FileByteStore::open(&self.dir).unwrap()).unwrap()
    }
    fn log(&self, event: String) {
        self.events.lock().unwrap().push(event);
    }
    fn events(&self) -> Vec<String> {
        self.events.lock().unwrap().clone()
    }
}

impl CredentialPersistence for Recorder {
    fn load(&self, _generation: u64) -> BoxFuture<'_, Result<Option<Session>>> {
        Box::pin(async move { Ok(self.stored.lock().unwrap().clone()) })
    }
    fn store(
        &self,
        snapshot: CredentialSnapshot,
        _generation: u64,
    ) -> BoxFuture<'_, Result<CredentialSave>> {
        Box::pin(async move {
            self.log(format!(
                "store rev={} cache_files={}",
                snapshot.revision,
                self.cache_files()
            ));
            if let Some(ops) = self.advance_in_store.lock().unwrap().take() {
                ops.advance();
            }
            if self.fail_store.load(Ordering::SeqCst) {
                return Err(Error::Locked);
            }
            if let Some(stored) = self.superseded.lock().unwrap().take() {
                return Ok(CredentialSave::Superseded(Box::new(stored)));
            }
            *self.stored.lock().unwrap() = Some(snapshot.session);
            Ok(CredentialSave::Saved)
        })
    }
    fn revoke(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            let bytes = FileByteStore::open(&self.dir)?;
            let mut fence = RevocationFence::load(&bytes)?;
            fence.revoked = true;
            fence.epoch = uuid::Uuid::new_v4().to_string();
            bytes.put(
                REVOCATION_FILE,
                &serde_json::to_vec(&fence)?,
                Durability::Now,
            )?;
            self.log("revoke".into());
            Ok(())
        })
    }
    fn clear(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            self.log(format!("clear revoked={}", self.fence().revoked));
            *self.stored.lock().unwrap() = None;
            Ok(())
        })
    }
}

struct Fixture {
    _dir: tempfile::TempDir,
    shell: ShellSession<FileByteStore>,
    credentials: Recorder,
}

fn fixture() -> Fixture {
    use std::os::unix::fs::PermissionsExt;
    let mut builder = tempfile::Builder::new();
    builder.permissions(std::fs::Permissions::from_mode(0o700));
    let dir = builder.tempdir().unwrap();
    let bytes = FileByteStore::open(dir.path()).unwrap();
    let fence = format!(
        r#"{{"version":1,"epoch":"{EPOCH}","revoked":false,"context":null,"admitted":null,"cleanup":null,"retired_contexts":[]}}"#
    );
    bytes
        .put(REVOCATION_FILE, fence.as_bytes(), Durability::Now)
        .unwrap();
    let admission = FixedContext(CacheContext {
        owner_hash: owner_hash(OWNER),
        context: "synthetic-context".into(),
        expires_at: None,
    });
    let cache = CacheStore::new(
        Arc::new(CacheEngine::new(bytes)),
        Arc::new(admission),
        Arc::new(NoScope),
        OrderedBlocking::new(),
    );
    let credentials = Recorder::new(&dir);
    Fixture {
        shell: ShellSession::new(cache),
        credentials,
        _dir: dir,
    }
}

fn client() -> Client {
    let session = synthetic_session();
    let mut client = Client::new(&session.api_url.clone(), Some(session)).unwrap();
    client.restore_ciphertext_snapshot(&content()).unwrap();
    client
}

/// A candidate with a fixed digest, standing in for an SDK read.
struct Candidate {
    revision: u64,
    stale: bool,
}

impl DurableCandidate for Candidate {
    fn ciphertext_sha256(&self) -> Result<String> {
        if self.stale {
            return Err(Error::Cancelled);
        }
        Ok("synthetic-digest".into())
    }
    fn credential_revision(&self) -> u64 {
        self.revision
    }
}

#[tokio::test]
async fn persist_makes_credentials_durable_before_any_cache_section() {
    let f = fixture();
    let mut client = client();
    f.shell.persist(&mut client, &f.credentials).await.unwrap();
    let events = f.credentials.events();
    assert_eq!(events.len(), 1);
    assert!(events[0].ends_with("cache_files=0"), "{events:?}");
    assert!(f.credentials.cache_files() > 0);
}

#[tokio::test]
async fn failed_credential_save_publishes_no_cache_and_mints_no_receipt() {
    let f = fixture();
    let mut client = client();
    f.credentials.fail_store.store(true, Ordering::SeqCst);
    let revision = client.credential_snapshot().unwrap().revision;
    let candidate = Candidate {
        revision,
        stale: false,
    };
    let receipt = f
        .shell
        .persist_for(&mut client, &f.credentials, &candidate)
        .await;
    assert!(matches!(receipt, Err(Error::Locked)));
    assert_eq!(f.credentials.cache_files(), 0);
}

#[tokio::test]
async fn receipt_is_minted_only_after_a_committed_persist() {
    let f = fixture();
    let mut client = client();
    let revision = client.credential_snapshot().unwrap().revision;
    let receipt = f
        .shell
        .persist_for(
            &mut client,
            &f.credentials,
            &Candidate {
                revision,
                stale: false,
            },
        )
        .await
        .unwrap();
    assert_eq!(receipt.ciphertext_sha256, "synthetic-digest");
    assert_eq!(receipt.credential_revision, revision);
    assert!(f.credentials.cache_files() > 0);
}

#[tokio::test]
async fn stale_candidate_refuses_before_any_write() {
    let f = fixture();
    let mut client = client();
    let refused = f
        .shell
        .persist_for(
            &mut client,
            &f.credentials,
            &Candidate {
                revision: 0,
                stale: true,
            },
        )
        .await;
    assert!(matches!(refused, Err(Error::Cancelled)));
    assert!(f.credentials.events().is_empty());
    assert_eq!(f.credentials.cache_files(), 0);
}

#[tokio::test]
async fn superseded_credentials_are_adopted_and_vouch_for_nothing() {
    let f = fixture();
    let mut client = client();
    let mut rotated = synthetic_session();
    rotated
        .cookies
        .insert("auth_refresh_token".into(), "rotated-elsewhere".into());
    *f.credentials.superseded.lock().unwrap() = Some(rotated);
    let before = client.credential_snapshot().unwrap().revision;
    let refused = f
        .shell
        .persist_for(
            &mut client,
            &f.credentials,
            &Candidate {
                revision: before,
                stale: false,
            },
        )
        .await;
    assert!(matches!(refused, Err(Error::Cancelled)));
    assert_eq!(f.credentials.cache_files(), 0);
    let adopted = client.credential_snapshot().unwrap();
    assert_ne!(adopted.revision, before);
    assert_eq!(
        adopted.session.cookies["auth_refresh_token"],
        "rotated-elsewhere"
    );
}

#[tokio::test]
async fn generation_moved_during_credential_save_refuses_the_cache_write() {
    let f = fixture();
    let mut client = client();
    *f.credentials.advance_in_store.lock().unwrap() = Some(f.shell.ops().clone());
    let refused = f.shell.persist(&mut client, &f.credentials).await;
    assert!(matches!(refused, Err(Error::Cancelled)));
    assert_eq!(f.credentials.cache_files(), 0);
}

#[tokio::test]
async fn cleared_client_revokes_durably_before_credential_cleanup() {
    let f = fixture();
    let mut client = client();
    f.shell.persist(&mut client, &f.credentials).await.unwrap();
    let generation = f.shell.ops().generation();
    client.take_session();
    f.shell.persist(&mut client, &f.credentials).await.unwrap();
    let events = f.credentials.events();
    assert_eq!(&events[1..], ["revoke", "clear revoked=true"]);
    assert!(f.shell.ops().generation() > generation);
    assert!(f.credentials.stored.lock().unwrap().is_none());
}

#[tokio::test]
async fn logout_revokes_before_cleanup_and_refuses_later_cache_writes() {
    let f = fixture();
    let mut client = client();
    f.shell.persist(&mut client, &f.credentials).await.unwrap();
    f.shell.logout(&mut client, &f.credentials).await.unwrap();
    assert_eq!(
        &f.credentials.events()[1..],
        ["revoke", "clear revoked=true"]
    );
    assert!(client.session().is_none());
    let mut late = self::client();
    assert!(f.shell.persist(&mut late, &f.credentials).await.is_err());
}

#[tokio::test]
async fn restore_refuses_credentials_other_than_the_clients() {
    let f = fixture();
    let mut writer = client();
    f.shell.persist(&mut writer, &f.credentials).await.unwrap();
    let mut other = synthetic_session();
    other.session_id = "another-admission".into();
    let mut client = Client::new(&other.api_url.clone(), Some(other)).unwrap();
    let refused = f
        .shell
        .restore(
            &mut client,
            &f.credentials,
            &CancellationToken::new(),
            CacheLoad::Full,
        )
        .await;
    assert!(matches!(refused, Err(Error::Cancelled)));
}

#[tokio::test]
async fn index_restore_then_cached_chat_loads_only_that_chat() {
    let f = fixture();
    let mut writer = client();
    f.shell.persist(&mut writer, &f.credentials).await.unwrap();
    let session = synthetic_session();
    let mut client = Client::new(&session.api_url.clone(), Some(session)).unwrap();
    f.shell
        .restore(
            &mut client,
            &f.credentials,
            &CancellationToken::new(),
            CacheLoad::Index,
        )
        .await
        .unwrap();
    assert_eq!(client.partially_restored_chats(), Some(vec![]));
    assert!(f.shell.load_cached_chat(&mut client, A).await.unwrap());
    assert_eq!(
        client.ciphertext_snapshot()["history"][A],
        content()["history"][A]
    );
}

#[tokio::test]
async fn deferred_restore_never_rewrites_the_cache() {
    let f = fixture();
    let mut writer = client();
    f.shell.persist(&mut writer, &f.credentials).await.unwrap();
    let files = f.credentials.cache_files();
    let session = synthetic_session();
    let mut client = Client::new(&session.api_url.clone(), Some(session)).unwrap();
    f.shell
        .restore(
            &mut client,
            &f.credentials,
            &CancellationToken::new(),
            CacheLoad::Deferred {
                revoke_list_freshness: false,
            },
        )
        .await
        .unwrap();
    assert_eq!(f.shell.sync_cache_deferred(), Some(false));
    f.shell.persist(&mut client, &f.credentials).await.unwrap();
    assert_eq!(f.credentials.cache_files(), files);
}

#[tokio::test]
async fn acknowledgement_timeout_is_a_typed_locked_error() {
    let never = std::future::pending::<Result<()>>();
    let timed_out =
        await_credential_acknowledgement(never, std::time::Duration::from_millis(10)).await;
    assert!(matches!(timed_out, Err(Error::Locked)));
}
