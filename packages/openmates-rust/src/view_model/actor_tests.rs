//! The core view-model actor over a real cache directory, an in-memory
//! credential store, a recording host and a recording sink: cached chat list
//! before admission and network, logout ordering, command routing and
//! cancellation.
//! The fixtures are shared with `window_tests.rs`.
use super::*;
use crate::{
    client::{Client, CredentialSnapshot, FreshChatInventory},
    error::{Error, Result},
    local_cache::{
        ByteStore, CacheContext, CacheEngine, CacheStore, Durability, FileByteStore, FixedContext,
        NoScope, OrderedBlocking, REVOCATION_FILE, owner_hash,
    },
    model::Item,
    session::Session,
    shell_session::{CredentialPersistence, CredentialSave, ShellSession},
};
use futures_util::future::BoxFuture;
use serde_json::json;
use std::sync::{Arc, Mutex};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

pub(super) const OWNER: &str = "synthetic-owner";
pub(super) const CHAT: &str = "11111111-1111-4111-8111-111111111111";
const EPOCH: &str = "c4f86cef-590c-4a5e-8120-eb6a27ded8a2";
// Network access fails at once: the tests prove which steps need none.
pub(super) const API: &str = "https://never-contact.example.invalid";

pub(super) fn session() -> Session {
    Session {
        api_url: API.into(),
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

/// One chat whose key is wrapped with the session master key.
pub(super) fn snapshot() -> serde_json::Value {
    let row = json!({"id": CHAT, "messages_v": 1, "last_edited_overall_timestamp": 1,
        "encrypted_chat_key": crate::crypto::encrypt_bytes(&[9; 32], &[7; 32]).unwrap(),
        "encrypted_title": crate::crypto::encrypt_combined("Synthetic cached title", &[9; 32]).unwrap()});
    let message = json!({"id": "22222222-2222-4222-8222-222222222222", "chat_id": CHAT,
        "role": "user", "created_at": 1,
        "encrypted_content": crate::crypto::encrypt_combined("synthetic body", &[9; 32]).unwrap()});
    json!({"chats": {CHAT: row}, "wrappers": [], "history": {CHAT: [message]},
        "embeds": {}, "embed_keys": [], "team_wrapped_key": null})
}

#[derive(Default)]
pub(super) struct Memory {
    pub(super) stored: Mutex<Option<Session>>,
    pub(super) log: Mutex<Vec<&'static str>>,
}

impl CredentialPersistence for Memory {
    fn load(&self, _generation: u64) -> BoxFuture<'_, Result<Option<Session>>> {
        Box::pin(async move { Ok(self.stored.lock().unwrap().clone()) })
    }
    fn store(
        &self,
        snapshot: CredentialSnapshot,
        _generation: u64,
    ) -> BoxFuture<'_, Result<CredentialSave>> {
        Box::pin(async move {
            *self.stored.lock().unwrap() = Some(snapshot.session);
            Ok(CredentialSave::Saved)
        })
    }
    fn revoke(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            self.log.lock().unwrap().push("revoke");
            Ok(())
        })
    }
    fn clear(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            self.log.lock().unwrap().push("clear");
            *self.stored.lock().unwrap() = None;
            Ok(())
        })
    }
}

#[derive(Default)]
pub(super) struct Sink(Mutex<Vec<ViewEvent>>);

impl Sink {
    pub(super) fn events(&self) -> Vec<ViewEvent> {
        self.0.lock().unwrap().clone()
    }
}

impl ViewSink for Sink {
    fn emit(&self, event: ViewEvent) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            self.0.lock().unwrap().push(event);
            Ok(())
        })
    }
}

pub(super) struct Host {
    pub(super) core: ViewCore<FileByteStore>,
    /// Hook calls, with the number of events emitted when each ran.
    pub(super) calls: Vec<(String, usize)>,
    /// What `offline_cache_allowed` answers.
    pub(super) offline_allowed: bool,
}

impl ViewHost<FileByteStore> for Host {
    type Sink = Sink;
    fn core(&self) -> &ViewCore<FileByteStore> {
        &self.core
    }
    fn core_mut(&mut self) -> &mut ViewCore<FileByteStore> {
        &mut self.core
    }
    fn prepare_start(&mut self, credentials: &Session) -> Result<String> {
        self.calls.push(("prepare".into(), 0));
        Ok(credentials.api_url.clone())
    }
    fn verify_start(&mut self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async move {
            self.calls.push(("verify".into(), 0));
            Ok(())
        })
    }
    fn admit<'a>(&'a mut self, sink: &'a Sink) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            self.calls.push(("admit".into(), sink.events().len()));
            // Stand-in for actual authentication of the restored session.
            self.core.client_mut().adopt_test_principal(OWNER)
        })
    }
    fn recover_before_list<'a>(
        &'a mut self,
        sink: &'a Sink,
        recovery: ListRecovery,
    ) -> BoxFuture<'a, Result<Option<FreshChatInventory>>> {
        Box::pin(async move {
            self.calls
                .push((format!("recover {recovery:?}"), sink.events().len()));
            Ok(None)
        })
    }
    fn recovery_idle(&mut self) -> BoxFuture<'_, bool> {
        Box::pin(async move { true })
    }
    fn recover_before_open<'a>(
        &'a mut self,
        sink: &'a Sink,
        chat_id: &'a str,
    ) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            self.calls
                .push((format!("recover open {chat_id}"), sink.events().len()));
            Ok(())
        })
    }
    fn offline_cache_allowed(&self) -> bool {
        self.offline_allowed
    }
}

pub(super) struct Fixture {
    _dir: tempfile::TempDir,
    pub(super) host: Host,
    pub(super) credentials: Arc<Memory>,
}

pub(super) fn fixture() -> Fixture {
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
    let credentials = Arc::new(Memory::default());
    let client = Client::new(API, None).unwrap();
    let core = ViewCore::new(client, ShellSession::new(cache), credentials.clone());
    Fixture {
        host: Host {
            core,
            calls: Vec::new(),
            offline_allowed: true,
        },
        credentials,
        _dir: dir,
    }
}

/// Write the synthetic cache and credentials as an earlier run would have.
pub(super) async fn persisted(f: &mut Fixture) {
    let core = f.host.core_mut();
    core.client_mut().reset(API, Some(session())).unwrap();
    core.client_mut()
        .restore_ciphertext_snapshot(&snapshot())
        .unwrap();
    core.persist().await.unwrap();
    core.client_mut().reset(API, None).unwrap();
}

pub(super) fn names(calls: &[(String, usize)]) -> Vec<&str> {
    calls.iter().map(|(name, _)| name.as_str()).collect()
}

#[tokio::test]
async fn start_emits_cached_list_from_the_index_before_admission_and_network() {
    let mut f = fixture();
    persisted(&mut f).await;
    let sink = Sink::default();
    let start = ViewCommand::Start {
        credentials: Box::new(session()),
    };
    handle(&mut f.host, start, &sink, &CancellationToken::new())
        .await
        .unwrap();
    let events = sink.events();
    assert_eq!(
        events[0],
        ViewEvent::Session(SessionEvent::Restored { display_name: None })
    );
    let ViewEvent::ChatList { rows, completeness } = &events[1] else {
        panic!("cached chat list expected: {events:?}");
    };
    assert_eq!(*completeness, ListCompleteness::Cached);
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].id, CHAT);
    assert_eq!(rows[0].title, "Synthetic cached title");
    // Row facts come from the held row; ones it does not carry stay `None`.
    assert_eq!(rows[0].metadata.last_edited_at, Some(1));
    assert_eq!(rows[0].metadata.icon, None);
    assert_eq!(rows[0].metadata.budget_limit, None);
    assert_eq!(names(&f.host.calls), ["prepare", "verify", "admit"]);
    assert_eq!(f.host.calls[2].1, 2, "both cached events precede admission");
    // Eager mode loaded every chat's content before admission.
    assert!(f.host.core().client().partially_restored_chats().is_none());
    assert_eq!(
        f.host.core().client().ciphertext_snapshot()["history"][CHAT]
            .as_array()
            .map(Vec::len),
        Some(1)
    );
}

#[tokio::test]
async fn lazy_start_keeps_chat_content_on_disk_until_opened() {
    let mut f = fixture();
    persisted(&mut f).await;
    f.host.core_mut().set_eager_cached_content(false);
    let sink = Sink::default();
    start(&mut f.host, session(), &sink, &CancellationToken::new())
        .await
        .unwrap();
    assert_eq!(sink.events().len(), 2);
    assert_eq!(
        f.host.core().client().partially_restored_chats(),
        Some(Vec::new())
    );
}

#[tokio::test]
async fn start_without_a_cache_emits_nothing_before_admission() {
    let mut f = fixture();
    *f.credentials.stored.lock().unwrap() = Some(session());
    let sink = Sink::default();
    start(&mut f.host, session(), &sink, &CancellationToken::new())
        .await
        .unwrap();
    assert!(sink.events().is_empty());
    assert_eq!(names(&f.host.calls), ["prepare", "verify", "admit"]);
}

#[tokio::test]
async fn cancelled_start_restores_nothing_and_never_admits() {
    let mut f = fixture();
    persisted(&mut f).await;
    let cancel = CancellationToken::new();
    cancel.cancel();
    let sink = Sink::default();
    let result = start(&mut f.host, session(), &sink, &cancel).await;
    assert_eq!(result, Err(Error::Cancelled));
    assert!(sink.events().is_empty());
    assert_eq!(names(&f.host.calls), ["prepare", "verify"]);
}

#[tokio::test]
async fn superseded_boot_sync_publishes_nothing() {
    let mut f = fixture();
    persisted(&mut f).await;
    let sink = Sink::default();
    start(&mut f.host, session(), &sink, &CancellationToken::new())
        .await
        .unwrap();
    let before = sink.events().len();
    let cancel = CancellationToken::new();
    cancel.cancel();
    let result = boot_sync(&mut f.host, &sink, &cancel).await;
    assert_eq!(result, Err(Error::Cancelled));
    assert_eq!(sink.events().len(), before);
    assert_eq!(names(&f.host.calls).last(), Some(&"recover BootSync"));
}

#[tokio::test]
async fn boot_sync_without_a_session_does_nothing() {
    let mut f = fixture();
    let sink = Sink::default();
    boot_sync(&mut f.host, &sink, &CancellationToken::new())
        .await
        .unwrap();
    assert!(sink.events().is_empty());
    assert!(f.host.calls.is_empty());
}

#[tokio::test]
async fn logout_revokes_before_cleanup_and_always_reports_signed_out() {
    let mut f = fixture();
    persisted(&mut f).await;
    let sink = Sink::default();
    start(&mut f.host, session(), &sink, &CancellationToken::new())
        .await
        .unwrap();
    let generation = f.host.core().shell().ops().guard();
    // Remote logout cannot reach the synthetic origin; local cleanup still runs.
    let _remote = handle(
        &mut f.host,
        ViewCommand::Logout,
        &sink,
        &CancellationToken::new(),
    )
    .await;
    assert_eq!(
        sink.events().last(),
        Some(&ViewEvent::Session(SessionEvent::SignedOut))
    );
    assert_eq!(*f.credentials.log.lock().unwrap(), ["revoke", "clear"]);
    assert!(f.credentials.stored.lock().unwrap().is_none());
    assert!(!generation.is_current());
    assert!(f.host.core().client().session().is_none());
}

#[tokio::test]
async fn revocation_handle_fences_the_queue_without_the_actor() {
    let f = fixture();
    let generation = f.host.core().shell().ops().guard();
    f.host.core().revocation_handle().revoke().await.unwrap();
    assert!(!generation.is_current());
    assert_eq!(*f.credentials.log.lock().unwrap(), ["revoke"]);
}

#[tokio::test]
async fn window_commands_and_a_queued_cancel_run_in_the_core_without_host_hooks() {
    let mut f = fixture();
    let sink = Sink::default();
    let cancel = CancellationToken::new();
    handle(&mut f.host, ViewCommand::Cancel, &sink, &cancel)
        .await
        .unwrap();
    // A malformed id never reaches the host, and closing a chat that is not
    // open does nothing.
    let open = ViewCommand::OpenChat {
        request: RequestId(7),
        chat_id: "not-a-chat-id".into(),
    };
    assert!(matches!(
        handle(&mut f.host, open, &sink, &cancel).await,
        Err(Error::Invalid(_))
    ));
    let close = ViewCommand::CloseChat {
        chat_id: CHAT.into(),
    };
    handle(&mut f.host, close, &sink, &cancel).await.unwrap();
    assert!(f.host.calls.is_empty());
    assert!(sink.events().is_empty());
}

#[test]
fn chat_list_event_refuses_a_malformed_row_instead_of_defaulting_it() {
    let f = fixture();
    let malformed = Item {
        id: CHAT.into(),
        status: "unknown".into(),
        fields: json!({}),
        ..Item::default()
    };
    assert_eq!(
        f.host
            .core()
            .chat_list_event(vec![malformed], ListCompleteness::Partial),
        Err(Error::Protocol)
    );
}
