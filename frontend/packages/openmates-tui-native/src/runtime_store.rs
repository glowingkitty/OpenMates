//! Async boundary for the blocking filesystem, password KDF, and native keyring.
//! Started operations retain their ordering permit and the profile lock even if
//! the caller cancels its future. Logout announces a durable revocation before
//! queued cleanup; a stalled native keyring cannot resurrect the old profile.
//! The queue, generation guard and cache operations are the core's
//! `CacheStore`/`OrderedBlocking`; this file adds the credential operations.
use crate::{
    crypto::Key,
    error::{Error, Result},
    storage::{CacheBytes, Session, SessionSave, StorageMode, Store},
};
use openmates_sdk::{local_cache::{CacheStore, OrderedBlocking}, shell_session::ShellSession};
use serde_json::Value;
use std::{
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

/// Read-only local publication guard. It retains neither Store nor credentials.
pub use openmates_sdk::local_cache::GenerationGuard as RuntimeStoreGeneration;
#[derive(Clone)]
pub struct RuntimeStore {
    store: Arc<Store>,
    /// Async cache façade over the core engine; shares `ops` with credentials.
    cache: CacheStore<CacheBytes>,
    ops: OrderedBlocking,
    /// The core session runtime (restore, persist, logout) over `cache`.
    session: ShellSession<CacheBytes>,
}
impl RuntimeStore {
    pub async fn new(path: Option<PathBuf>, force_vault: bool) -> Result<Self> {
        tokio::task::spawn_blocking(move || {
            let path = match path {
                Some(path) => path,
                None => Store::default_path()?,
            };
            let store = if force_vault {
                Store::encrypted_vault(path)?
            } else {
                Store::new(path)?
            };
            Ok(Self::from_store(Arc::new(store)))
        })
        .await
        .map_err(|_| Error::Io)?
    }
    /// Wrap an opened `Store`: the cache façade uses the store as its
    /// admission hook and operation scope and shares one ordered queue.
    fn from_store(store: Arc<Store>) -> Self {
        let ops = OrderedBlocking::new();
        let cache = CacheStore::new(store.cache_engine().clone(), store.clone(), store.clone(), ops.clone());
        let session = ShellSession::new(cache.clone());
        Self { store, cache, ops, session }
    }
    /// The core session runtime of this profile (see `session_runtime`).
    pub fn shell(&self) -> &ShellSession<CacheBytes> {
        &self.session
    }
    /// Release the lifetime runtime lock; each later store operation takes it
    /// only while it runs (see `Store::scope_runtime_lock_to_operations`).
    pub fn scope_runtime_lock_to_operations(&self) -> Result<()> {
        self.store.scope_runtime_lock_to_operations()
    }
    /// Credential operation on the shared queue under the runtime lock. With
    /// `generation` it refuses once a revocation advanced the generation.
    async fn blocking_at<T: Send + 'static>(
        &self,
        generation: Option<u64>,
        operation: impl FnOnce(Arc<Store>) -> Result<T> + Send + 'static,
    ) -> Result<T> {
        let store = self.store.clone();
        self.ops
            .run(generation, move || {
                let held = store.clone();
                held.with_runtime_lock(move || operation(store))
            })
            .await
    }
    async fn blocking<T: Send + 'static>(
        &self,
        operation: impl FnOnce(Arc<Store>) -> Result<T> + Send + 'static,
    ) -> Result<T> {
        self.blocking_at(None, operation).await
    }
    /// Like `blocking`, refusing when the generation moved after this call.
    async fn blocking_current<T: Send + 'static>(
        &self,
        operation: impl FnOnce(Arc<Store>) -> Result<T> + Send + 'static,
    ) -> Result<T> {
        self.blocking_at(Some(self.ops.generation()), operation).await
    }
    pub async fn load(&self, passphrase: Option<Zeroizing<String>>) -> Result<Option<Session>> {
        self.load_at(self.ops.generation(), passphrase).await
    }
    /// `load` refusing once the queue moved past `generation`.
    pub(crate) async fn load_at(
        &self,
        generation: u64,
        passphrase: Option<Zeroizing<String>>,
    ) -> Result<Option<Session>> {
        self.blocking_at(Some(generation), move |store| {
            store.load_session(passphrase.as_ref().map(|secret| secret.as_str()))
        })
        .await
    }
    pub async fn save(
        &self,
        session: Session,
        passphrase: Option<Zeroizing<String>>,
    ) -> Result<()> {
        self.blocking_current(move |store| {
            store.save_session(&session, passphrase.as_ref().map(|secret| secret.as_str()))
        })
        .await
    }
    /// Await durable local revocation without waiting for queued OS cleanup.
    /// Callers may bound cleanup separately, but must not claim remote logout.
    pub async fn revoke(&self) -> Result<()> {
        self.ops.advance();
        self.announce_revocation().await
    }
    /// The durable revocation write alone; the caller advanced the generation.
    pub(crate) async fn announce_revocation(&self) -> Result<()> {
        // A dedicated, short filesystem worker cannot sit behind saturated
        // spawn_blocking keyring jobs. It retains the descriptor even if the
        // awaiting logout future is cancelled while fsync is in progress.
        let store = self.store.clone();
        let (done, ready) = tokio::sync::oneshot::channel();
        std::thread::Builder::new()
            .name("native-revoke".into())
            .spawn(move || {
                let _ = done.send(store.with_runtime_lock(|| store.revoke_session()));
            })
            .map_err(|_| Error::Io)?;
        ready.await.map_err(|_| Error::Io)?
    }
    pub async fn clear(&self) -> Result<()> {
        self.revoke().await?;
        self.cleanup().await
    }
    /// Credential and owner-cache cleanup after a durable revocation; never
    /// refused by the generation (logout cleanup must run).
    pub(crate) async fn cleanup(&self) -> Result<()> {
        self.blocking(move |store| store.clear_session()).await
    }
    /// Explicit application admission, never called by boot or ordinary
    /// refresh/persistence. The supplied fresh session binds subsequent saves.
    pub async fn begin_session(&self, session: Session) -> Result<()> {
        self.begin_session_cancellable(session, CancellationToken::new())
            .await
    }
    /// Interactive admission must carry its original request token. Check it
    /// while holding the durable fence lock, so completed logout cannot be
    /// undone by admission that starts after its last application-side check.
    pub async fn begin_session_cancellable(
        &self,
        session: Session,
        request_cancel: CancellationToken,
    ) -> Result<()> {
        struct CancelAdmission(Arc<AtomicBool>);
        impl Drop for CancelAdmission {
            fn drop(&mut self) {
                self.0.store(true, Ordering::SeqCst);
            }
        }
        let cancelled = Arc::new(AtomicBool::new(false));
        let _cancel = CancelAdmission(cancelled.clone());
        let generation = self.generation();
        let ops = self.ops.clone();
        self.blocking(move |store| {
            store.begin_session_if(&session, || {
                if request_cancel.is_cancelled()
                    || cancelled.load(Ordering::SeqCst)
                    || !ops.is_current(generation)
                {
                    return Err(Error::Cancelled);
                }
                Ok(())
            })
        })
        .await
    }
    pub fn generation(&self) -> u64 {
        self.ops.generation()
    }
    pub fn generation_guard(&self) -> RuntimeStoreGeneration {
        self.ops.guard()
    }
    /// The shared ordered queue (test seam: hold it to stall later operations).
    #[cfg(test)]
    pub(crate) fn ops(&self) -> &OrderedBlocking {
        &self.ops
    }
    pub async fn read_cache(
        &self,
        owner: String,
        key: String,
        master: Key,
    ) -> Result<Option<Value>> {
        self.cache.read_cache(owner, key, master).await
    }
    /// Capacity only, no write/ACK/auth admission. The caller retains its
    /// original owner/generation/private fences around this optional decision.
    pub fn admits_ciphertext_checkpoint(&self, checkpoint_json_bytes: usize) -> Result<bool> {
        self.cache.admits_checkpoint(checkpoint_json_bytes)
    }
    pub async fn write_cache(
        &self,
        owner: String,
        key: String,
        master: Key,
        value: Value,
    ) -> Result<()> {
        self.cache.write_cache(owner, key, master, value).await
    }
    /// Change-only credential publication (see Store::save_session_if_changed).
    pub async fn save_if_changed(
        &self,
        session: Session,
        passphrase: Option<Zeroizing<String>>,
    ) -> Result<bool> {
        self.blocking_current(move |store| {
            store.save_session_if_changed(&session, passphrase.as_ref().map(|secret| secret.as_str()))
        })
        .await
    }
    /// `save_if_changed` for long-running hosts: when another process rotated
    /// the stored session, adopt it instead of overwriting it. The comparison
    /// and write run in one runtime-lock critical section. One-shot (lifetime
    /// locked) stores always report `Saved`.
    pub async fn save_unless_superseded(
        &self,
        session: Session,
        passphrase: Option<Zeroizing<String>>,
    ) -> Result<SessionSave> {
        self.save_unless_superseded_at(self.ops.generation(), session, passphrase).await
    }
    /// `save_unless_superseded` refusing once the queue moved past `generation`.
    pub(crate) async fn save_unless_superseded_at(
        &self,
        generation: u64,
        session: Session,
        passphrase: Option<Zeroizing<String>>,
    ) -> Result<SessionSave> {
        self.blocking_at(Some(generation), move |store| {
            store.save_session_unless_superseded(
                &session,
                passphrase.as_ref().map(|secret| secret.as_str()),
            )
        })
        .await
    }
    /// The session another process rotated and stored since this one last
    /// loaded or saved, if any (hosts only). Read under the runtime lock.
    pub async fn load_superseded(
        &self,
        passphrase: Option<Zeroizing<String>>,
    ) -> Result<Option<Session>> {
        self.blocking_current(move |store| {
            store.superseded_session(passphrase.as_ref().map(|secret| secret.as_str()))
        })
        .await
    }
    /// Loader for the SDK's partial restore (see `CacheStore::content_loader`).
    pub fn sync_content_loader(
        &self,
        owner: String,
        key: String,
        master: Key,
    ) -> openmates_sdk::client::CachedContentLoader {
        self.cache.content_loader(owner, key, master)
    }
    pub(crate) async fn prepare_sync_sections(
        &self,
        value: Value,
        partial: Option<Vec<String>>,
    ) -> Result<crate::storage::PreparedSections> {
        self.cache.prepare_sections(value, partial).await
    }
    pub(crate) async fn write_sync_sections(
        &self,
        owner: String,
        key: String,
        master: Key,
        prepared: crate::storage::PreparedSections,
    ) -> Result<bool> {
        self.cache.write_sections(owner, key, master, prepared).await
    }
    pub async fn storage_mode(&self) -> Result<Option<StorageMode>> {
        self.blocking(move |store| store.storage_mode()).await
    }
    pub async fn device_identity(&self) -> Result<String> {
        self.blocking(move |store| store.device_identity()).await
    }
    pub async fn anonymous_identity(&self) -> Result<String> {
        self.blocking(move |store| store.anonymous_identity()).await
    }
    pub async fn update_private_record<T: Send + 'static>(
        &self,
        owner: String,
        context: String,
        name: String,
        key: Key,
        generation: u64,
        update: impl FnOnce(Option<Value>) -> Result<(Option<Value>, T)> + Send + 'static,
    ) -> Result<T> {
        let ops = self.ops.clone();
        self.blocking_at(Some(generation), move |store| {
            store.update_private_record(&owner, &context, &name, &key, move |previous| {
                let next = update(previous)?;
                if !ops.is_current(generation) {
                    return Err(Error::Cancelled);
                }
                Ok(next)
            })
        })
        .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::{CredentialBackend, KeyringFailure};
    use std::sync::{Mutex as BlockingMutex, atomic::{AtomicU64, AtomicU8}};

    struct StalledBackend {
        secret: BlockingMutex<Option<Zeroizing<Vec<u8>>>>,
        stage: AtomicU8,
        entered: BlockingMutex<Option<tokio::sync::oneshot::Sender<()>>>,
        released: BlockingMutex<std::sync::mpsc::Receiver<()>>,
        reads: AtomicU64,
        delete_fails: AtomicBool,
    }
    impl StalledBackend {
        fn pause(&self, stage: u8) {
            if self
                .stage
                .compare_exchange(stage, 0, Ordering::SeqCst, Ordering::SeqCst)
                .is_ok()
            {
                self.entered
                    .lock()
                    .unwrap()
                    .take()
                    .unwrap()
                    .send(())
                    .unwrap();
                self.released.lock().unwrap().recv().unwrap();
            }
        }
        fn arm(&self, stage: u8) -> tokio::sync::oneshot::Receiver<()> {
            let (started, entered) = tokio::sync::oneshot::channel();
            *self.entered.lock().unwrap() = Some(started);
            self.stage.store(stage, Ordering::SeqCst);
            entered
        }
    }
    impl CredentialBackend for StalledBackend {
        fn get(&self, _: &str) -> std::result::Result<Zeroizing<Vec<u8>>, KeyringFailure> {
            self.reads.fetch_add(1, Ordering::SeqCst);
            self.pause(1);
            self.secret
                .lock()
                .unwrap()
                .clone()
                .ok_or(KeyringFailure::Missing)
        }
        fn set(&self, _: &str, secret: &[u8]) -> std::result::Result<(), KeyringFailure> {
            self.pause(2);
            *self.secret.lock().unwrap() = Some(Zeroizing::new(secret.to_vec()));
            Ok(())
        }
        fn delete(&self, _: &str) -> std::result::Result<(), KeyringFailure> {
            self.pause(3);
            if self.delete_fails.load(Ordering::SeqCst) {
                return Err(KeyringFailure::Unavailable);
            }
            *self.secret.lock().unwrap() = None;
            Ok(())
        }
    }
    fn isolated() -> (
        tempfile::TempDir,
        RuntimeStore,
        Arc<StalledBackend>,
        std::sync::mpsc::Sender<()>,
        Session,
    ) {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().unwrap();
        let (release, released) = std::sync::mpsc::channel();
        let backend = Arc::new(StalledBackend {
            secret: BlockingMutex::new(None),
            stage: AtomicU8::new(0),
            entered: BlockingMutex::new(None),
            released: BlockingMutex::new(released),
            reads: AtomicU64::new(0),
            delete_fails: AtomicBool::new(false),
        });
        // Injection deliberately models restart readers without relaxing the
        // production Store::new lifetime lock (covered by storage_security).
        let store =
            Arc::new(Store::with_backend(directory.path().to_path_buf(), backend.clone()).unwrap());
        let runtime = RuntimeStore::from_store(store);
        let session = Session {
            api_url: "https://never-contact.example.invalid".into(),
            session_id: "old-admission".into(),
            cookies: Default::default(),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        (directory, runtime, backend, release, session)
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[tokio::test]
    async fn oversized_full_persist_refuses_before_credentials_and_preserves_cached_rows() {
        let (directory, runtime, _backend, _release, session) = isolated();
        let mut prior = crate::client::Client::new(&session.api_url, Some(session.clone())).unwrap();
        crate::session_runtime::persist(&mut prior, &runtime, None).await.unwrap();
        let cache_key = crate::session_runtime::cache_key(&session);
        let old_cache = runtime.read_cache(session.hashed_email.clone(), cache_key.clone(), session.master_key.clone()).await.unwrap();
        let credentials = std::fs::read(directory.path().join("session.json")).unwrap();
        let revocation = std::fs::read(directory.path().join("revocation.json")).unwrap();
        let mut changed = session.clone(); changed.session_id = "unpublished-new-admission".into();
        let mut client = crate::client::Client::new(&changed.api_url, Some(changed.clone())).unwrap();
        let mut snapshot = client.ciphertext_snapshot();
        snapshot["chats"]["synthetic-large"] = serde_json::json!({"id":"synthetic-large","encrypted_title":"x".repeat(crate::storage::MAX_LOCAL_RECORD_BYTES)});
        client.restore_ciphertext_snapshot(&snapshot).unwrap();
        drop(snapshot);
        let generation = runtime.generation();
        let serializations = runtime.store.cache_serializations_for_test();
        assert!(matches!(crate::session_runtime::persist(&mut client, &runtime, None).await, Err(Error::Invalid(_))));
        assert_eq!(std::fs::read(directory.path().join("session.json")).unwrap(), credentials);
        assert_eq!(std::fs::read(directory.path().join("revocation.json")).unwrap(), revocation);
        assert_eq!(runtime.read_cache(session.hashed_email.clone(), cache_key, session.master_key.clone()).await.unwrap(), old_cache);
        assert_eq!(runtime.load(None).await.unwrap().unwrap().session_id, session.session_id);
        assert_eq!(runtime.generation(), generation);
        assert_eq!(runtime.store.cache_serializations_for_test(), serializations);
        assert_eq!(client.ciphertext_snapshot()["chats"]["synthetic-large"]["encrypted_title"].as_str().unwrap().len(), crate::storage::MAX_LOCAL_RECORD_BYTES);
        assert_eq!(client.credential_snapshot().unwrap().session.session_id, changed.session_id);
        // persist returns at the capacity guard, before its only ACK call.
        // The SDK has no public ACK getter; do not invent one for this test.
    }
    #[tokio::test]
    async fn unchanged_client_full_persist_rewrites_neither_session_nor_cache_but_acks() {
        let (directory, runtime, _backend, _release, session) = isolated();
        let mut client =
            crate::client::Client::new(&session.api_url.clone(), Some(session)).unwrap();
        let generation = runtime.generation();
        let initial = client.credential_snapshot().unwrap();
        let ciphertext = client.ciphertext_snapshot();

        // Execute the real application boundary, including RuntimeStore::save,
        // RuntimeStore::write_cache and Client::acknowledge_credentials.
        crate::session_runtime::persist(&mut client, &runtime, None)
            .await
            .unwrap();
        assert_eq!(runtime.store.cache_serializations_for_test(), 1);
        let first_io = runtime.store.io_counts_for_test();
        let first_session = std::fs::read(directory.path().join("session.json")).unwrap();
        let first_fence: Value = serde_json::from_slice(
            &std::fs::read(directory.path().join("revocation.json")).unwrap(),
        )
        .unwrap();
        assert!(!first_fence["epoch"].as_str().unwrap().is_empty());
        let cache_path = std::fs::read_dir(directory.path())
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .find(|path| {
                let name = path.file_name().unwrap().to_str().unwrap();
                name.starts_with("cache-") && name.ends_with(".json")
            })
            .unwrap();
        let first_cache = std::fs::read(&cache_path).unwrap();

        // Acknowledgement preserves the same credential snapshot and ciphertext;
        // it must not force a fresh epoch or clear the Store-local cache proof.
        assert_eq!(
            client.credential_snapshot().unwrap().revision,
            initial.revision
        );
        assert_eq!(client.ciphertext_snapshot(), ciphertext);
        crate::session_runtime::persist(&mut client, &runtime, None)
            .await
            .unwrap();
        assert_eq!(
            std::fs::read(directory.path().join("session.json")).unwrap(),
            first_session,
            "an unchanged session is not re-encrypted or republished"
        );
        let second_fence: Value = serde_json::from_slice(
            &std::fs::read(directory.path().join("revocation.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(second_fence["epoch"], first_fence["epoch"]);
        assert_eq!(runtime.generation(), generation);
        assert_eq!(
            client.credential_snapshot().unwrap().revision,
            initial.revision
        );
        assert_eq!(client.ciphertext_snapshot(), ciphertext);
        // Change detection encodes the bounded sections once per persist.
        assert_eq!(runtime.store.cache_serializations_for_test(), 2);
        assert_eq!(std::fs::read(&cache_path).unwrap(), first_cache);
        assert_eq!(runtime.store.io_counts_for_test(), first_io, "second persist read and wrote nothing");
        assert!(runtime.load(None).await.unwrap().is_some());

        // The same real persistence boundary must still refuse after revocation;
        // an eligible retained Value does not grant authority or acknowledge IO.
        runtime.revoke().await.unwrap();
        assert_eq!(runtime.store.cache_serializations_for_test(), 2);
        let revoked_session = std::fs::read(directory.path().join("session.json")).unwrap();
        let revoked_fence = std::fs::read(directory.path().join("revocation.json")).unwrap();
        assert!(
            crate::session_runtime::persist(&mut client, &runtime, None)
                .await
                .is_err()
        );
        // Revocation erased all durable evidence. Pure bounded preparation runs
        // before credential save; its one encoding grants no disk/ACK right.
        assert_eq!(runtime.store.cache_serializations_for_test(), 3);
        assert_eq!(std::fs::read(directory.path().join("session.json")).unwrap(), revoked_session);
        assert_eq!(std::fs::read(directory.path().join("revocation.json")).unwrap(), revoked_fence);
        assert_eq!(std::fs::read(&cache_path).unwrap(), first_cache);
        assert!(runtime.load(None).await.unwrap().is_none());
    }


    // Real peer, SDK authentication, encrypted history and RuntimeStore persist.
    // The queue is held only by this module's test: no product test-hook exists.
    #[tokio::test]
    async fn canonical_publication_cannot_cross_cancel_owner_denial_or_key_epoch_during_real_save()
    {
        use crate::client::{ChatRefreshDurableReceipt, ChatViewRead};
        use futures_util::{SinkExt, StreamExt};
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        const CHAT: &str = "22222222-2222-4222-8222-222222222222";
        tokio::time::timeout(std::time::Duration::from_secs(15), async {
            for change in ["cancel", "monitor-owner-denial", "store-key-epoch"] {
                let (_directory, runtime, _backend, _release, mut session) = isolated();
                let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
                session.api_url = format!("http://{}",listener.local_addr().unwrap());
                let (trigger, triggered) = tokio::sync::oneshot::channel::<()>();
                let server = tokio::spawn(async move {
                    let mut monitor_task = None;
                    let mut trigger = Some(triggered);
                    for index in 0..4 {
                        let (mut socket, _) = listener.accept().await.unwrap();
                        if index == 1 {
                            let mut ws = tokio_tungstenite::accept_async(socket).await.unwrap();
                            let lifecycle: Value = serde_json::from_str(ws.next().await.unwrap().unwrap().to_text().unwrap()).unwrap();
                            assert_eq!(lifecycle["type"],"native_client_lifecycle");
                            let trigger = trigger.take().unwrap();
                            monitor_task = Some(tokio::spawn(async move {
                                if trigger.await.is_ok() {
                                    ws.send(tokio_tungstenite::tungstenite::Message::Text(serde_json::json!({"type":"force_logout","payload":{}}).to_string().into())).await.unwrap();
                                }
                                while let Some(frame) = ws.next().await {
                                    if frame.unwrap().is_close() { break; }
                                }
                            }));
                            continue;
                        }
                        let mut bytes=Vec::new();
                        loop {
                            let mut byte=[0;1];socket.read_exact(&mut byte).await.unwrap();bytes.push(byte[0]);
                            assert!(bytes.len()<16384);if bytes.ends_with(b"\r\n\r\n"){break;}
                        }
                        let head=String::from_utf8(bytes).unwrap();
                        let length=head.lines().find_map(|line|line.to_ascii_lowercase().strip_prefix("content-length:").map(|value|value.trim().parse::<usize>().unwrap())).unwrap_or(0);
                        let mut body=vec![0;length];socket.read_exact(&mut body).await.unwrap();
                        let response=match index {
                            0 => {assert!(head.starts_with("POST /v1/auth/session HTTP/1.1\r\n"));serde_json::json!({"success":true,"ws_token":"synthetic-token","user":{"id":"synthetic-owner"}})},
                            2 => {assert!(head.starts_with("POST /v1/chats/metadata/batch HTTP/1.1\r\n"));assert_eq!(serde_json::from_slice::<Value>(&body).unwrap(),serde_json::json!({"chat_ids":[CHAT]}));
                                serde_json::json!({"chats":[{"id":CHAT,"messages_v":1,"encrypted_chat_key":crate::crypto::encrypt_bytes(&[9;32],&[7;32]).unwrap(),"encrypted_title":crate::crypto::encrypt_combined("Owned saved title",&[9;32]).unwrap()}]})},
                            3 => {assert!(head.starts_with(&format!("GET /v1/chats/{CHAT}/messages/window?direction=latest&limit=100&respect_compression_boundary=false HTTP/1.1\r\n")));
                                serde_json::json!({"messages":[{"id":"10000000-0000-4000-8000-000000000001","chat_id":CHAT,"role":"user","created_at":1,"encrypted_content":crate::crypto::encrypt_combined("Owned saved text",&[9;32]).unwrap()}],"has_more_before":false})},
                            _=>unreachable!(),
                        }.to_string();
                        socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response}",response.len()).as_bytes()).await.unwrap();
                    }
                    monitor_task.unwrap().await.unwrap();
                });
                let mut client=crate::client::Client::new(&session.api_url.clone(),Some(session)).unwrap();
                let (errors,mut observed)=tokio::sync::mpsc::channel(4);
                let monitor=client.start_chat_monitor(CancellationToken::new(),errors).await.unwrap();
                let request=CancellationToken::new();client.set_operation_cancel(request.clone());
                let ChatViewRead::Canonical(candidate)=client.read_chat_view(Some(&monitor),CHAT,request.clone()).await.unwrap() else {panic!("wire success must be canonical")};
                client.validate_chat_view(&candidate).unwrap();
                let receipt=ChatRefreshDurableReceipt{ciphertext_sha256:candidate.ciphertext_sha256().unwrap(),credential_revision:candidate.credential_revision()};
                let generation=runtime.generation_guard();
                let queue=runtime.ops().hold().await;
                let saved_result = {
                let saved=crate::session_runtime::persist(&mut client,&runtime,None);
                tokio::pin!(saved);
                std::future::poll_fn(|cx| {
                    assert!(std::future::Future::poll(saved.as_mut(),cx).is_pending(),"real final save must actually be held");
                    std::task::Poll::Ready(())
                }).await;
                match change {
                    "cancel"=>{request.cancel();drop(trigger);},
                    "monitor-owner-denial"=>{trigger.send(()).unwrap();assert_eq!(observed.recv().await,Some(Error::Expired));},
                    "store-key-epoch"=>{runtime.revoke().await.unwrap();drop(trigger);},
                    _=>unreachable!(),
                }
                drop(queue);
                saved.await
                };
                // The lexical save scope releases the mutable Client borrow.
                if change=="store-key-epoch" {assert!(saved_result.is_err());assert!(!generation.is_current());}
                else {assert!(saved_result.is_ok());}
                drop(monitor);
                server.await.unwrap();
                // Candidate is retained through the real save; no plain Chat was
                // available to the UI while independently observed state changed.
                // Evaluate the SDK fence only after that real persistence ends.
                assert!(client.commit_chat_view(candidate,receipt).is_err(),"{change}");
            }
        }).await.unwrap();
    }
    async fn fence_published(path: &std::path::Path) {
        tokio::time::timeout(std::time::Duration::from_secs(2), async {
            loop {
                if std::fs::read(path.join("revocation.json"))
                    .ok()
                    .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
                    .is_some_and(|fence| fence["revoked"] == true)
                {
                    return;
                }
                tokio::time::sleep(std::time::Duration::from_millis(5)).await;
            }
        })
        .await
        .unwrap();
    }

    #[test]
    fn logout_fence_bypasses_saturated_blocking_pool_and_survives_cancelled_cleanup() {
        // One keyring call consumes every Tokio blocking slot. Revocation must
        // still become durable without waiting for that pool, queue or lock.
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .max_blocking_threads(1)
            .build()
            .unwrap()
            .block_on(async {
                let (directory, runtime, backend, release, session) = isolated();
                runtime.save(session.clone(), None).await.unwrap();
                runtime
                    .write_cache(
                        session.hashed_email.clone(),
                        "chats".into(),
                        session.master_key.clone(),
                        serde_json::json!(["private fixture"]),
                    )
                    .await
                    .unwrap();
                let entered = backend.arm(1);
                let worker = runtime.clone();
                let old = session.clone();
                let saved = tokio::spawn(async move { worker.save(old, None).await });
                entered.await.unwrap();
                saved.abort();
                assert!(saved.await.unwrap_err().is_cancelled());
                tokio::time::timeout(std::time::Duration::from_secs(2), runtime.revoke())
                    .await
                    .unwrap()
                    .unwrap();
                let worker = runtime.clone();
                let cleared = tokio::spawn(async move { worker.clear().await });
                fence_published(directory.path()).await;
                cleared.abort();
                assert!(cleared.await.unwrap_err().is_cancelled());
                // Before releasing the stalled keyring, a fresh descriptor must
                // reject restoration and private reads without another key call.
                let restarted =
                    Store::with_backend(directory.path().to_path_buf(), backend.clone()).unwrap();
                let reads = backend.reads.load(Ordering::SeqCst);
                assert!(restarted.load_session(None).unwrap().is_none());
                assert!(matches!(
                    restarted.read_cache(&session.hashed_email, "chats", &session.master_key),
                    Err(Error::Authentication)
                ));
                assert!(matches!(
                    restarted.update_private_record(
                        &session.hashed_email,
                        "fixture",
                        "journal",
                        &session.master_key,
                        |_| Ok((None, ()))
                    ),
                    Err(Error::Authentication)
                ));
                assert_eq!(backend.reads.load(Ordering::SeqCst), reads);
                release.send(()).unwrap();
                // Drain the original ordering permit: the late save must not
                // overwrite the tombstone or publish the old session again.
                runtime.blocking(|_| Ok(())).await.unwrap();
                assert!(runtime.load(None).await.unwrap().is_none());
                assert!(matches!(
                    runtime.begin_session(session.clone()).await,
                    Err(Error::Authentication)
                ));
                let mut fresh = session.clone();
                fresh.session_id = "fresh-admission".into();
                runtime.begin_session(fresh.clone()).await.unwrap();
                runtime.save(fresh.clone(), None).await.unwrap();
                assert_eq!(
                    runtime.load(None).await.unwrap().unwrap().session_id,
                    fresh.session_id
                );
                assert!(matches!(
                    runtime.save(session, None).await,
                    Err(Error::Authentication)
                ));
                assert!(
                    runtime
                        .read_cache(
                            fresh.hashed_email.clone(),
                            "chats".into(),
                            fresh.master_key.clone()
                        )
                        .await
                        .unwrap()
                        .is_none()
                );
            });
    }

    #[tokio::test]
    async fn first_keyring_set_cannot_publish_after_logout_and_orphan_cleanup_precedes_new_admission()
     {
        let (directory, runtime, backend, release, session) = isolated();
        let entered = backend.arm(2);
        let worker = runtime.clone();
        let old = session.clone();
        let saved = tokio::spawn(async move { worker.save(old, None).await });
        entered.await.unwrap();
        let worker = runtime.clone();
        let cleared = tokio::spawn(async move { worker.clear().await });
        fence_published(directory.path()).await;
        cleared.abort();
        let _ = cleared.await;
        release.send(()).unwrap();
        assert!(matches!(saved.await.unwrap(), Err(Error::Cancelled)));
        assert!(!directory.path().join("session.json").exists());
        assert!(backend.secret.lock().unwrap().is_some());
        let mut fresh = session;
        fresh.session_id = "fresh-admission".into();
        runtime.begin_session(fresh.clone()).await.unwrap();
        assert!(
            backend.secret.lock().unwrap().is_none(),
            "orphan key must be deleted before epoch reset"
        );
        runtime.save(fresh, None).await.unwrap();
        assert_eq!(
            runtime.storage_mode().await.unwrap(),
            Some(StorageMode::OsKeyring)
        );
    }

    #[tokio::test]
    async fn cancelled_request_cannot_reset_logout_completed_before_admission_starts() {
        let (directory, runtime, backend, _release, session) = isolated();
        runtime.save(session.clone(), None).await.unwrap();
        let cancel = CancellationToken::new();
        // The application observed a live request, then another task processed
        // Logout before admission captured the RuntimeStore generation.
        assert!(!cancel.is_cancelled());
        cancel.cancel();
        runtime.revoke().await.unwrap();
        let before: Value = serde_json::from_slice(
            &std::fs::read(directory.path().join("revocation.json")).unwrap(),
        )
        .unwrap();
        let mut fresh = session.clone();
        fresh.session_id = "cancelled-fresh-admission".into();
        assert_eq!(
            runtime
                .begin_session_cancellable(fresh.clone(), cancel)
                .await,
            Err(Error::Cancelled)
        );
        let after: Value = serde_json::from_slice(
            &std::fs::read(directory.path().join("revocation.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(after["epoch"], before["epoch"]);
        assert_eq!(after["revoked"], true);
        assert!(runtime.load(None).await.unwrap().is_none());
        assert!(runtime.save(session, None).await.is_err());
        assert!(runtime.save(fresh, None).await.is_err());
        let restarted = Store::with_backend(directory.path().to_path_buf(), backend).unwrap();
        assert!(restarted.load_session(None).unwrap().is_none());
    }
    #[tokio::test]
    async fn request_cancel_during_admission_cleanup_is_checked_before_fence_reset() {
        let (directory, runtime, backend, release, mut session) = isolated();
        runtime.save(session.clone(), None).await.unwrap();
        runtime.revoke().await.unwrap();
        let before: Value = serde_json::from_slice(
            &std::fs::read(directory.path().join("revocation.json")).unwrap(),
        )
        .unwrap();
        let entered = backend.arm(3);
        let cancel = CancellationToken::new();
        let request_cancel = cancel.clone();
        let worker = runtime.clone();
        session.session_id = "cancel-during-cleanup".into();
        let admission = tokio::spawn(async move {
            worker
                .begin_session_cancellable(session, request_cancel)
                .await
        });
        entered.await.unwrap();
        cancel.cancel();
        release.send(()).unwrap();
        assert_eq!(admission.await.unwrap(), Err(Error::Cancelled));
        let after: Value = serde_json::from_slice(
            &std::fs::read(directory.path().join("revocation.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(after["epoch"], before["epoch"]);
        assert_eq!(after["revoked"], true);
        assert!(runtime.load(None).await.unwrap().is_none());
    }
    #[tokio::test]
    async fn completed_cancellable_admission_cannot_prevent_subsequent_logout() {
        let (directory, runtime, backend, _release, session) = isolated();
        let cancel = CancellationToken::new();
        runtime
            .begin_session_cancellable(session.clone(), cancel.clone())
            .await
            .unwrap();
        runtime.save(session.clone(), None).await.unwrap();
        cancel.cancel();
        runtime.revoke().await.unwrap();
        let fence: Value = serde_json::from_slice(
            &std::fs::read(directory.path().join("revocation.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(fence["revoked"], true);
        assert!(runtime.save(session, None).await.is_err());
        assert!(runtime.load(None).await.unwrap().is_none());
        let restarted = Store::with_backend(directory.path().to_path_buf(), backend).unwrap();
        assert!(restarted.load_session(None).unwrap().is_none());
    }
    #[tokio::test]
    async fn completed_logout_does_not_require_an_os_backend_to_delete_the_key_twice() {
        let (_directory, runtime, backend, _release, mut session) = isolated();
        runtime.save(session.clone(), None).await.unwrap();
        runtime.clear().await.unwrap();
        backend.delete_fails.store(true, Ordering::SeqCst);
        session.session_id = "fresh-admission".into();
        runtime.begin_session(session.clone()).await.unwrap();
        runtime.save(session, None).await.unwrap();
    }

    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[tokio::test]
    async fn prepared_and_preparing_cache_cannot_cross_logout_generation() {
        let (directory, runtime, _backend, _release, session) = isolated();
        runtime.save(session.clone(), None).await.unwrap();
        let prepared = runtime.prepare_sync_sections(serde_json::json!({"chats":{}}), None).await.unwrap();
        let held = runtime.ops().hold().await;
        let mut preparing = Box::pin(runtime.prepare_sync_sections(serde_json::json!({"chats":{}}), None));
        let mut publishing = Box::pin(runtime.write_sync_sections(session.hashed_email.clone(), "sync-personal".into(), session.master_key.clone(), prepared));
        assert!(futures_util::poll!(preparing.as_mut()).is_pending());
        assert!(futures_util::poll!(publishing.as_mut()).is_pending());
        let worker = runtime.clone();
        let cleared = tokio::spawn(async move { worker.clear().await });
        fence_published(directory.path()).await;
        drop(held);
        assert!(matches!(preparing.await, Err(Error::Cancelled)));
        assert!(matches!(publishing.await, Err(Error::Cancelled)));
        cleared.await.unwrap().unwrap();
        assert!(runtime.load(None).await.unwrap().is_none());
    }
    #[tokio::test]
    async fn queued_session_reads_and_writes_cannot_cross_logout_generation() {
        let (directory, runtime, backend, _release, session) = isolated();
        runtime.save(session.clone(), None).await.unwrap();
        let held = runtime.ops().hold().await;
        let mut read = Box::pin(runtime.load(None));
        let mut write = Box::pin(runtime.save(session, None));
        assert!(futures_util::poll!(read.as_mut()).is_pending());
        assert!(futures_util::poll!(write.as_mut()).is_pending());
        let worker = runtime.clone();
        let cleared = tokio::spawn(async move { worker.clear().await });
        fence_published(directory.path()).await;
        let reads = backend.reads.load(Ordering::SeqCst);
        drop(held);
        assert!(matches!(read.await, Err(Error::Cancelled)));
        assert!(matches!(write.await, Err(Error::Cancelled)));
        cleared.await.unwrap().unwrap();
        assert_eq!(backend.reads.load(Ordering::SeqCst), reads);
        assert!(runtime.load(None).await.unwrap().is_none());
    }

    #[tokio::test]
    async fn backend_failure_and_cancelled_fresh_admission_keep_revocation_durable() {
        let (directory, runtime, backend, release, session) = isolated();
        runtime.save(session.clone(), None).await.unwrap();
        backend.delete_fails.store(true, Ordering::SeqCst);
        assert!(matches!(runtime.clear().await, Err(Error::Locked)));
        let mut fresh = session;
        fresh.session_id = "fresh-admission".into();
        assert!(matches!(
            runtime.begin_session(fresh.clone()).await,
            Err(Error::Locked)
        ));
        assert!(runtime.load(None).await.unwrap().is_none());
        backend.delete_fails.store(false, Ordering::SeqCst);
        let entered = backend.arm(3);
        let worker = runtime.clone();
        let admitted = fresh.clone();
        let admission = tokio::spawn(async move { worker.begin_session(admitted).await });
        entered.await.unwrap();
        admission.abort();
        assert!(admission.await.unwrap_err().is_cancelled());
        release.send(()).unwrap();
        runtime.blocking(|_| Ok(())).await.unwrap();
        fence_published(directory.path()).await;
        assert!(runtime.load(None).await.unwrap().is_none());
        runtime.begin_session(fresh.clone()).await.unwrap();
        runtime.save(fresh, None).await.unwrap();
    }

    #[tokio::test]
    async fn cancellation_keeps_later_logout_behind_started_blocking_work() {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().unwrap();
        let runtime = RuntimeStore::new(Some(directory.path().to_path_buf()), true)
            .await
            .unwrap();
        let (started, ready) = tokio::sync::oneshot::channel();
        let (release, blocked) = std::sync::mpsc::channel();
        let worker = runtime.clone();
        let operation = tokio::spawn(async move {
            worker
                .blocking(move |_| {
                    let _ = started.send(());
                    blocked.recv().map_err(|_| Error::Io)?;
                    Ok(())
                })
                .await
        });
        ready.await.unwrap();
        operation.abort();
        assert!(operation.await.unwrap_err().is_cancelled());
        let worker = runtime.clone();
        let mut logout = tokio::spawn(async move { worker.clear().await });
        let waiting = tokio::time::timeout(std::time::Duration::from_millis(40), &mut logout).await;
        // Release even if the assertion fails, so a regression cannot hang the
        // Tokio runtime waiting for its unfinished blocking thread on shutdown.
        release.send(()).unwrap();
        assert!(waiting.is_err(), "logout overtook cancelled blocking work");
        logout.await.unwrap().unwrap();
    }
}

#[cfg(test)]
#[path = "cache_persistence_tests.rs"]
mod cache_persistence_tests;
