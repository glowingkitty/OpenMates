//! `ViewModelCore`: the Apple shell's handle on the core view-model actor
//! (`openmates_sdk::view_model`). It wires the cache directory
//! (`FileByteStore`, `CacheEngine`, `FixedContext`, `NoScope`,
//! `OrderedBlocking`), the session runtime (`ShellSession`) and the actor
//! state (`ViewCore`) and serves `Start`, the boot sync, `RefreshChats`,
//! `SwitchTeam`, `Logout`, the chat window commands (`OpenChat`, `LoadOlder`,
//! `CloseChat`, `MarkRead`) and the fresh-session begin after a login. Send
//! lives in `view_send.rs`, the core-performed login in `view_login.rs`,
//! session state and auth loss in `view_session.rs`.
//! Swift supplies the Keychain (`CredentialStore`) and receives events
//! (`ViewListener`). Bindings only marshal; the hooks below are the minimal
//! Apple `ViewHost`. Plan `apple-client-core-migration` lane L8
//! (`a2-design.md`); spec `client-core` and `client-core.cache`.
use crate::core::{
    CoreCancellation, CoreConfig, CredentialSnapshotRecord, build_runtime, join_result,
};
use crate::{CoreError, view_records::ViewEventRecord};
use futures_util::future::BoxFuture;
use openmates_sdk::{
    Client, ClientIdentity, ClientOptions,
    client::{CredentialSnapshot, FreshChatInventory},
    error::{Error, Result},
    local_cache::{
        ByteStoreError, CacheEngine, CacheStore, FileByteStore, FixedContext, NoScope,
        OrderedBlocking,
    },
    session::Session,
    shell_session::{
        AcknowledgedCredentials, CredentialPersistence, CredentialVault, FreshSessionAdmission,
        ShellSession, session_cache_context,
    },
    view_model::{
        self, ListRecovery, RequestId, RevocationHandle, SendCancelHandle, SessionEvent,
        ViewCommand, ViewCore, ViewEvent, ViewHost, ViewSink,
    },
};
use std::future::Future;
use std::path::Path;
use std::sync::{Arc, Mutex as StdMutex, MutexGuard, PoisonError};
use std::time::Duration;
use tokio::runtime::{Handle, Runtime};
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

pub(crate) type Bytes = FileByteStore;

/// Keychain-backed credential store implemented in Swift. Holds one opaque
/// payload (the serialized core session, secret): Swift never parses, logs
/// or shows it. Called on core threads, never the main thread.
#[uniffi::export(foreign)]
pub trait CredentialStore: Send + Sync {
    /// The stored payload, or `nil` when none is stored. May block briefly
    /// (one Keychain read).
    ///
    /// # Errors
    /// `Locked` when the Keychain is unavailable (device locked), `Io` otherwise.
    fn load(&self) -> std::result::Result<Option<Vec<u8>>, CoreError>;

    /// Credentials changed. Store `snapshot.payload` (replacing the old one),
    /// then call `ViewModelCore.acknowledgeCredentials(revision:)` with
    /// `snapshot.revision`. Must not block; the core waits for the
    /// acknowledgement up to 10 seconds and then fails the save with `Locked`.
    fn credentials_changed(&self, snapshot: CredentialSnapshotRecord);

    /// Delete the stored payload; a missing payload is success. May block briefly.
    ///
    /// # Errors
    /// `Locked` when the Keychain refuses deletion, `Io` otherwise.
    fn delete(&self) -> std::result::Result<(), CoreError>;
}

/// Event listener implemented in Swift. Called on a core thread in event
/// order; it must not block and hops to `@MainActor` itself.
#[uniffi::export(foreign)]
pub trait ViewListener: Send + Sync {
    /// One core view-model event.
    fn on_event(&self, event: ViewEventRecord);
}

/// Classification of a Swift store failure for the core. The Keychain can
/// only report "locked" or a store failure; anything else is a store failure.
fn store_error(error: CoreError) -> Error {
    match error {
        CoreError::Locked => Error::Locked,
        CoreError::Cancelled => Error::Cancelled,
        _ => Error::Io,
    }
}

/// Classification of a cache directory open failure: configuration mistakes
/// (relative or non-normalized container, a name that is not one plain
/// component) are `Invalid`; file-system failures keep the core mapping (`Io`).
fn store_open_error(error: ByteStoreError) -> CoreError {
    let message = match error {
        ByteStoreError::RelativePath => "The cache container must be an absolute path.",
        ByteStoreError::NonNormalizedPath => "The cache container must be a normalized path.",
        ByteStoreError::InvalidName => "The cache directory name must be one plain path component.",
        other => return Error::from(other).into(),
    };
    CoreError::Invalid {
        message: message.to_owned(),
    }
}

/// The Swift `CredentialStore` as the core's `CredentialVault`.
pub(crate) struct VaultBridge(pub(crate) Arc<dyn CredentialStore>);

impl CredentialVault for VaultBridge {
    fn load(&self) -> Result<Option<Zeroizing<Vec<u8>>>> {
        Ok(self.0.load().map_err(store_error)?.map(Zeroizing::new))
    }

    fn credentials_changed(&self, revision: u64, payload: &[u8]) {
        self.0.credentials_changed(CredentialSnapshotRecord {
            revision,
            payload: payload.to_vec(),
        });
    }

    fn delete(&self) -> Result<()> {
        self.0.delete().map_err(store_error)
    }
}

/// Delivers core events to the Swift listener, mapped 1:1.
pub(crate) struct ListenerSink(Arc<dyn ViewListener>);

impl ViewSink for ListenerSink {
    fn emit(&self, event: ViewEvent) -> BoxFuture<'_, Result<()>> {
        self.0.on_event(event.into());
        Box::pin(async { Ok(()) })
    }

    fn emit_detached(&self, events: Vec<ViewEvent>) {
        // `on_event` never blocks, so the queued stream updates of a dropped
        // send (among them the `Submitted` fence) are delivered right here.
        for event in events {
            self.0.on_event(event.into());
        }
    }
}

/// The Apple `ViewHost`: no profile settings, no trusted-account check,
/// admission by fresh server validation plus persistence, no completion
/// recovery yet (lane L5, so `recover_before_open` does nothing), no live
/// monitor yet (so no known denial: `offline_cache_allowed` is true); send
/// and cancel run in the core (`view_send.rs`).
pub(crate) struct AppleHost {
    core: ViewCore<Bytes>,
    api_url: String,
    credentials: Arc<AcknowledgedCredentials<Bytes>>,
    cancel: CancellationToken,
}

impl ViewHost<Bytes> for AppleHost {
    type Sink = ListenerSink;

    fn core(&self) -> &ViewCore<Bytes> {
        &self.core
    }

    fn core_mut(&mut self) -> &mut ViewCore<Bytes> {
        &mut self.core
    }

    fn prepare_start(&mut self, _credentials: &Session) -> Result<String> {
        // The configured origin; a session of another origin is refused by
        // `Client::reset` with `Forbidden`.
        Ok(self.api_url.clone())
    }

    fn verify_start(&mut self) -> BoxFuture<'_, Result<()>> {
        Box::pin(async { Ok(()) })
    }

    fn admit<'a>(&'a mut self, sink: &'a ListenerSink) -> BoxFuture<'a, Result<()>> {
        Box::pin(async move {
            let shell = self.core.shell().clone();
            let credentials = self.credentials.clone();
            let cancel = self.cancel.clone();
            let admission = FreshSessionAdmission::admit(
                self.core.client_mut(),
                &shell,
                &*credentials,
                &cancel,
            )
            .await?;
            // Same name choice as the terminal's admitted greeting.
            let user = admission.user()?;
            let username = ["username", "display_name"]
                .into_iter()
                .filter_map(|key| user[key].as_str())
                .find(|name| !name.is_empty())
                .unwrap_or("OpenMates")
                .to_owned();
            drop(admission);
            let expires_at = self
                .core
                .client()
                .session()
                .ok_or(Error::Authentication)?
                .paired_session_expires_at;
            sink.emit(ViewEvent::Session(SessionEvent::Admitted {
                username,
                expires_at,
            }))
            .await
        })
    }

    fn recover_before_list<'a>(
        &'a mut self,
        _sink: &'a ListenerSink,
        _recovery: ListRecovery,
    ) -> BoxFuture<'a, Result<Option<FreshChatInventory>>> {
        Box::pin(async { Ok(None) })
    }

    fn recovery_idle(&mut self) -> BoxFuture<'_, bool> {
        Box::pin(async { true })
    }

    fn recover_before_open<'a>(
        &'a mut self,
        _sink: &'a ListenerSink,
        _chat_id: &'a str,
    ) -> BoxFuture<'a, Result<()>> {
        Box::pin(async { Ok(()) })
    }

    fn offline_cache_allowed(&self) -> bool {
        // No live monitor yet, so no known denial: offline cache may show.
        true
    }
}

pub(crate) fn lock<T>(mutex: &StdMutex<T>) -> MutexGuard<'_, T> {
    // A poisoned lock only means a panic elsewhere; the value stays valid.
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

/// Everything a command task needs; shared by all calls of one core.
pub(crate) struct Shared {
    pub(crate) api_url: String,
    app_url: Option<String>,
    engine: Arc<CacheEngine<Bytes>>,
    pub(crate) ops: OrderedBlocking,
    pub(crate) credentials: Arc<AcknowledgedCredentials<Bytes>>,
    pub(crate) sink: ListenerSink,
    /// The actor state of the signed-in session; `None` while signed out.
    pub(crate) host: Mutex<Option<AppleHost>>,
    /// Revocation without waiting for a busy actor (logout priority lane).
    pub(crate) revocation: StdMutex<Option<RevocationHandle<Bytes>>>,
    /// Cancels the running send without waiting for the actor.
    pub(crate) send_cancel: StdMutex<Option<SendCancelHandle>>,
    /// The client of a running pair login (signed out only); see `view_login.rs`.
    pub(crate) pairing: Mutex<Option<crate::view_login::PendingPair>>,
}

impl Shared {
    /// Client options of every client this core builds.
    pub(crate) fn options(&self) -> ClientOptions {
        ClientOptions {
            identity: ClientIdentity::Apple,
            app_url: self.app_url.clone(),
            ..ClientOptions::default()
        }
    }

    async fn start(&self, cancel: CancellationToken) -> Result<()> {
        let mut host = self.host.lock().await;
        self.start_locked(&mut host, cancel).await
    }

    /// `start` with the actor lock already held (login hand-over).
    pub(crate) async fn start_locked(
        &self,
        host: &mut Option<AppleHost>,
        cancel: CancellationToken,
    ) -> Result<()> {
        let Some(session) = self.credentials.load(self.ops.generation()).await? else {
            *host = None;
            *lock(&self.revocation) = None;
            *lock(&self.send_cancel) = None;
            return self
                .sink
                .emit(ViewEvent::Session(SessionEvent::SignedOut))
                .await;
        };
        let cache = CacheStore::new(
            self.engine.clone(),
            Arc::new(FixedContext(session_cache_context(&session)?)),
            Arc::new(NoScope),
            self.ops.clone(),
        );
        let client = Client::with_options(&self.api_url, None, self.options())?;
        let persistence: Arc<dyn CredentialPersistence> = self.credentials.clone();
        let mut core = ViewCore::new(client, ShellSession::new(cache), persistence);
        // Chat content loads per chat on open (a2-design: index-only start).
        core.set_eager_cached_content(false);
        *lock(&self.revocation) = Some(core.revocation_handle());
        *lock(&self.send_cancel) = Some(core.send_cancel_handle());
        let current = host.insert(AppleHost {
            core,
            api_url: self.api_url.clone(),
            credentials: self.credentials.clone(),
            cancel: cancel.clone(),
        });
        let start = ViewCommand::Start {
            credentials: Box::new(session),
        };
        let started = view_model::handle(current, start, &self.sink, &cancel).await;
        self.settle_auth(host, started).await
    }

    /// Begin `session` (fresh from a core login) on this profile, then start
    /// from it. Holds the actor lock, so no other command interleaves.
    async fn begin_session(&self, session: Session, cancel: CancellationToken) -> Result<()> {
        let mut host = self.host.lock().await;
        if host.is_some() {
            return Err(Error::Invalid("Sign out before beginning another session."));
        }
        // The client's credential snapshot carries the revision the Keychain
        // acknowledges; the client itself is discarded (start builds its own).
        let client = Client::with_options(&self.api_url, Some(session), self.options())?;
        let snapshot: CredentialSnapshot =
            client.credential_snapshot().ok_or(Error::Authentication)?;
        drop(client);
        self.credentials.begin_session(snapshot, &cancel).await?;
        self.start_locked(&mut host, cancel).await
    }

    /// Run `work` on the signed-in actor state.
    ///
    /// # Errors
    /// `Authentication` while signed out; otherwise what `work` returns.
    pub(crate) async fn signed_in<T, F>(&self, cancel: CancellationToken, work: F) -> Result<T>
    where
        F: for<'a> FnOnce(
            &'a mut AppleHost,
            &'a ListenerSink,
            &'a CancellationToken,
        ) -> BoxFuture<'a, Result<T>>,
    {
        let mut guard = self.host.lock().await;
        let host = guard.as_mut().ok_or(Error::Authentication)?;
        host.cancel = cancel.clone();
        let result = work(host, &self.sink, &cancel).await;
        // A rejected session signs out here (`view_session.rs`).
        self.settle_auth(&mut guard, result).await
    }

    /// Sign out (see `ViewModelCore::logout`).
    pub(crate) async fn logout(&self) -> Result<()> {
        // Durable revocation first, without waiting for a running command.
        let revocation = lock(&self.revocation).clone();
        if let Some(revocation) = &revocation {
            revocation.revoke().await?;
        }
        let mut host = self.host.lock().await;
        if let Some(current) = host.as_mut() {
            // The core logout emits `Session(SignedOut)` itself.
            let cancel = CancellationToken::new();
            let result =
                view_model::handle(current, ViewCommand::Logout, &self.sink, &cancel).await;
            *host = None;
            *lock(&self.revocation) = None;
            *lock(&self.send_cancel) = None;
            return result;
        }
        // Signed out already: still make revocation durable and wipe stored
        // credentials and cache, in `ShellSession::clear_credentials` order.
        self.ops.advance();
        let result = match self.credentials.revoke().await {
            Ok(()) => self.credentials.clear().await,
            Err(error) => Err(error),
        };
        self.sink
            .emit(ViewEvent::Session(SessionEvent::SignedOut))
            .await?;
        result
    }
}

/// The core view-model actor for the Apple app. Create one per process
/// (main app only); dropping it shuts its runtime down without blocking.
/// All async methods run on the core runtime; dropping the awaiting Swift
/// task does not stop them (pass a `CoreCancellation` instead).
#[derive(uniffi::Object)]
pub struct ViewModelCore {
    runtime: Option<Runtime>,
    handle: Handle,
    pub(crate) shared: Arc<Shared>,
    foreground: StdMutex<CancellationToken>,
    shutdown: CancellationToken,
}

impl ViewModelCore {
    /// Construction with an explicit acknowledgement timeout (tests).
    pub(crate) fn build(
        config: CoreConfig,
        credentials: Arc<dyn CredentialStore>,
        listener: Arc<dyn ViewListener>,
        acknowledgement_timeout: Duration,
    ) -> std::result::Result<Arc<Self>, CoreError> {
        let (container, name) = match (config.cache_container, config.cache_directory_name) {
            (Some(container), Some(name)) => (container, name),
            _ => {
                return Err(CoreError::Invalid {
                    message: "A cache container and cache directory name are required.".to_owned(),
                });
            }
        };
        let runtime = build_runtime()?;
        let handle = runtime.handle().clone();
        let options = ClientOptions {
            identity: ClientIdentity::Apple,
            app_url: config.app_url.clone(),
            ..ClientOptions::default()
        };
        {
            // Validate the origins now; the HTTP client needs the reactor.
            let _entered = runtime.enter();
            Client::with_options(&config.api_url, None, options)?;
        }
        // The container is opened as the OS hands it out; the cache directory
        // inside it is O_NOFOLLOW, 0700 and owned by this user (`open_in`).
        let bytes =
            FileByteStore::open_in(Path::new(&container), &name).map_err(store_open_error)?;
        let engine = Arc::new(CacheEngine::new(bytes));
        let credentials = Arc::new(AcknowledgedCredentials::with_timeout(
            Arc::new(VaultBridge(credentials)),
            engine.clone(),
            acknowledgement_timeout,
        ));
        let shutdown = CancellationToken::new();
        Ok(Arc::new(Self {
            runtime: Some(runtime),
            handle,
            shared: Arc::new(Shared {
                api_url: config.api_url,
                app_url: config.app_url,
                engine,
                ops: OrderedBlocking::new(),
                credentials,
                sink: ListenerSink(listener),
                host: Mutex::new(None),
                revocation: StdMutex::new(None),
                send_cancel: StdMutex::new(None),
                pairing: Mutex::new(None),
            }),
            foreground: StdMutex::new(shutdown.child_token()),
            shutdown,
        }))
    }

    /// A fresh foreground token: replaces the previous one, fires on core
    /// shutdown, and when `cancellation` is cancelled. The core flows check
    /// it cooperatively, so a started persist is never cut in half.
    pub(crate) fn foreground(
        &self,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> CancellationToken {
        let token = self.shutdown.child_token();
        *lock(&self.foreground) = token.clone();
        if let Some(cancellation) = cancellation {
            let (caller, forward) = (cancellation.token.clone(), token.clone());
            self.handle.spawn(async move {
                tokio::select! {
                    () = caller.cancelled() => forward.cancel(),
                    () = forward.cancelled() => {}
                }
            });
        }
        token
    }

    /// A token that fires on core shutdown and when `cancellation` is
    /// cancelled, without replacing the foreground token (concurrent calls
    /// such as `httpRequest` must not make a running open uncancellable).
    pub(crate) fn detached(
        &self,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> CancellationToken {
        let token = self.shutdown.child_token();
        if let Some(cancellation) = cancellation {
            let (caller, forward) = (cancellation.token.clone(), token.clone());
            self.handle.spawn(async move {
                tokio::select! {
                    () = caller.cancelled() => forward.cancel(),
                    () = forward.cancelled() => {}
                }
            });
        }
        token
    }

    /// Run `work` to completion on the core runtime.
    pub(crate) async fn run<T, F>(&self, work: F) -> std::result::Result<T, CoreError>
    where
        T: Send + 'static,
        F: Future<Output = Result<T>> + Send + 'static,
    {
        join_result(
            self.handle
                .spawn(async move { work.await.map_err(CoreError::from) })
                .await,
        )
    }
}

#[uniffi::export]
impl ViewModelCore {
    /// Create the actor over the cache directory `config.cache_directory_name`
    /// inside `config.cache_container`, with Swift's credential
    /// store and event listener. Signed out until `start`.
    ///
    /// # Errors
    /// `Invalid` when the container or name is missing, the container path is
    /// relative or non-normalized, the name is not one plain component, or an
    /// API/app URL is bad; `Io` when the container is missing or not owned by
    /// this user, or the directory cannot be created, is a symlink, is not
    /// `0700` or not owned by this user;
    /// `Internal` if the runtime cannot start.
    #[uniffi::constructor]
    pub fn new(
        config: CoreConfig,
        credentials: Arc<dyn CredentialStore>,
        listener: Arc<dyn ViewListener>,
    ) -> std::result::Result<Arc<Self>, CoreError> {
        Self::build(
            config,
            credentials,
            listener,
            openmates_sdk::shell_session::CREDENTIAL_ACKNOWLEDGEMENT_TIMEOUT,
        )
    }

    /// Start from the stored credentials: no stored session emits
    /// `Session(SignedOut)`; otherwise the cached index emits
    /// `Session(Restored)` and `ChatList(Cached)` before any network request,
    /// then the session is admitted (`Session(Admitted)`). Run `boot_sync`
    /// afterwards for the network chat list.
    ///
    /// # Errors
    /// `Expired` for a lapsed stored pairing, `Locked` for an unavailable
    /// Keychain or acknowledgement timeout, `Offline`/`Authentication` from
    /// admission (the cached list was already emitted), cache errors,
    /// `Cancelled` when `cancellation` fired.
    pub async fn start(
        &self,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move { shared.start(token).await }).await
    }

    /// The background half of start: the chat list read from the network,
    /// persisted, then emitted as `ChatList(Partial)`. Safe to repeat.
    ///
    /// # Errors
    /// `Authentication` when signed out, sync and persistence errors,
    /// `Cancelled` when superseded.
    pub async fn boot_sync(
        &self,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            shared
                .signed_in(token, |host, sink, cancel| {
                    view_model::boot_sync(host, sink, cancel)
                })
                .await
        })
        .await
    }

    /// Re-read the chat list (feed catch-up when possible) and emit it.
    ///
    /// # Errors
    /// `Authentication` when signed out, sync and persistence errors.
    pub async fn refresh_chats(
        &self,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            shared
                .signed_in(token, |host, sink, cancel| {
                    view_model::handle(host, ViewCommand::RefreshChats, sink, cancel)
                })
                .await
        })
        .await
    }

    /// Switch to team `team_id` (`nil`: personal), admit the session there and
    /// emit its chat list.
    ///
    /// # Errors
    /// `Authentication` when signed out, scope, admission and sync errors.
    pub async fn switch_team(
        &self,
        team_id: Option<String>,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, cancel| {
                    view_model::handle(host, ViewCommand::SwitchTeam { team_id }, sink, cancel)
                })
                .await
        })
        .await
    }

    /// Open chat `chat_id` as the window of Swift's `request` id, replacing
    /// any other open window. Events, all carrying `request`: the cached
    /// window (`ChatWindow` with source `Cached`) before any network request
    /// when the chat is cached and the session admitted; a cold chat's
    /// `FirstPage`; then the strict window (`Canonical`, `CacheSettled`, or
    /// read-only `CachedOffline` when the server is unreachable).
    ///
    /// # Errors
    /// `Authentication` when signed out or not admitted; `Invalid` for a
    /// malformed chat id; `Forbidden`, `Offline` and persistence errors from
    /// the strict read (a window already shown stays open); `Cancelled` when
    /// `cancellation` fired or a newer open superseded `request`.
    pub async fn open_chat(
        &self,
        request: u64,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, cancel| {
                    let request = RequestId(request);
                    view_model::handle(
                        host,
                        ViewCommand::OpenChat { request, chat_id },
                        sink,
                        cancel,
                    )
                })
                .await
        })
        .await
    }

    /// Merge the next older page into the open window of `chat_id` and emit
    /// it as `ChatWindow` for `request`. A complete window is emitted
    /// unchanged without any network request.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` when `chat_id` is not the
    /// open chat or has no page yet; page read and persistence errors;
    /// `Cancelled` when `cancellation` fired.
    pub async fn load_older(
        &self,
        request: u64,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, cancel| {
                    let request = RequestId(request);
                    view_model::handle(
                        host,
                        ViewCommand::LoadOlder { request, chat_id },
                        sink,
                        cancel,
                    )
                })
                .await
        })
        .await
    }

    /// Close the window of `chat_id`; later live data for it changes only the
    /// chat list. Closing a chat that is not open does nothing. Waits for a
    /// running command; cancel a running open's `CoreCancellation` first to
    /// close at once. Emits nothing.
    ///
    /// # Errors
    /// `Authentication` when signed out.
    pub async fn close_chat(&self, chat_id: String) -> std::result::Result<(), CoreError> {
        // Not a foreground command: it must not replace the token logout
        // cancels, or a running open would stop being cancellable.
        let (shared, token) = (self.shared.clone(), self.shutdown.child_token());
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, cancel| {
                    view_model::handle(host, ViewCommand::CloseChat { chat_id }, sink, cancel)
                })
                .await
        })
        .await
    }

    /// Mark `chat_id` read on every device, then persist the patched cached
    /// row (the next `ChatList` shows it read). Emits nothing itself.
    ///
    /// # Errors
    /// `Authentication` when signed out; `Invalid` for a malformed id;
    /// network and persistence errors; `Cancelled` when `cancellation` fired.
    pub async fn mark_read(
        &self,
        chat_id: String,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move {
            shared
                .signed_in(token, move |host, sink, cancel| {
                    view_model::handle(host, ViewCommand::MarkRead { chat_id }, sink, cancel)
                })
                .await
        })
        .await
    }

    /// Sign out: cancels the running command, makes revocation durable in the
    /// cache directory, wipes the cache records and the Keychain payload
    /// (`CredentialStore.delete`) together with the remote logout, then emits
    /// `Session(SignedOut)` even when a step failed.
    ///
    /// # Errors
    /// The local error first, else the remote one (`Offline` when the
    /// server is unreachable; local sign-out still completed).
    pub async fn logout(&self) -> std::result::Result<(), CoreError> {
        lock(&self.foreground).cancel();
        let shared = self.shared.clone();
        self.run(async move { shared.logout().await }).await
    }

    /// Swift stored the payload of `revision` (see
    /// `CredentialStore.credentialsChanged`). Callable from any thread.
    ///
    /// # Errors
    /// `Cancelled` when no save waits for `revision` (stale or timed out).
    pub fn acknowledge_credentials(&self, revision: u64) -> std::result::Result<(), CoreError> {
        Ok(self.shared.credentials.acknowledge(revision)?)
    }
}

/// Rust-only entry points (not exported to Swift).
impl ViewModelCore {
    /// Begin `session`, freshly produced by a core login or pairing, on this
    /// profile (`AcknowledgedCredentials::begin_session`: new fence epoch,
    /// the signed-out session's cache and Keychain payload wiped, then the
    /// Keychain store with acknowledgement), then `start` from it. This is
    /// the hand-over point for a session produced in Rust. It is not
    /// exported: Swift signs in through the core login (`view_login.rs`),
    /// and importing Swift-held sessions is a separate decision (plan
    /// `apple-client-core-migration`, A2 notes).
    ///
    /// # Errors
    /// `Invalid` while signed in; `Authentication` for an expired, ownerless
    /// or revoked session; `Locked` for an acknowledgement timeout;
    /// otherwise as `start`.
    pub async fn begin_session(
        &self,
        session: Session,
        cancellation: Option<Arc<CoreCancellation>>,
    ) -> std::result::Result<(), CoreError> {
        let (shared, token) = (self.shared.clone(), self.foreground(cancellation));
        self.run(async move { shared.begin_session(session, token).await })
            .await
    }
}

impl Drop for ViewModelCore {
    fn drop(&mut self) {
        self.shutdown.cancel();
        if let Some(runtime) = self.runtime.take() {
            // Never blocks, so it is safe on any thread, including a runtime worker.
            runtime.shutdown_background();
        }
    }
}
