//! `ViewModelCore`: the Apple shell's handle on the core view-model actor
//! (`openmates_sdk::view_model`). It wires the cache directory
//! (`FileByteStore`, `CacheEngine`, `FixedContext`, `NoScope`,
//! `OrderedBlocking`), the session runtime (`ShellSession`) and the actor
//! state (`ViewCore`) and serves `Start`, the boot sync, `RefreshChats`,
//! `SwitchTeam` and `Logout`. Swift supplies the Keychain (`CredentialStore`)
//! and receives events (`ViewListener`). Bindings only marshal; the hooks
//! below are the minimal Apple `ViewHost`. Plan `apple-client-core-migration`
//! lane L8 (`a2-design.md`); spec `client-core` and `client-core.cache`.
use crate::core::{
    CoreCancellation, CoreConfig, CredentialSnapshotRecord, build_runtime, join_result,
};
use crate::{CoreError, view_records::ViewEventRecord};
use futures_util::future::BoxFuture;
use openmates_sdk::{
    Client, ClientIdentity, ClientOptions,
    client::FreshChatInventory,
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
        self, ListRecovery, RevocationHandle, SessionEvent, ViewCommand, ViewCore, ViewEvent,
        ViewHost, ViewSink,
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

type Bytes = FileByteStore;

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
struct ListenerSink(Arc<dyn ViewListener>);

impl ViewSink for ListenerSink {
    fn emit(&self, event: ViewEvent) -> BoxFuture<'_, Result<()>> {
        self.0.on_event(event.into());
        Box::pin(async { Ok(()) })
    }
}

/// The Apple `ViewHost`: no profile settings, no trusted-account check,
/// admission by fresh server validation plus persistence, no completion
/// recovery yet (lane L5) and no bridged commands. Open, paging, mark read
/// and send are not exposed to Swift yet.
struct AppleHost {
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

    fn bridge<'a>(
        &'a mut self,
        _command: ViewCommand,
        _sink: &'a ListenerSink,
        _cancel: &'a CancellationToken,
    ) -> BoxFuture<'a, Result<()>> {
        Box::pin(async {
            Err(Error::Invalid(
                "This command is not served by the Apple core yet.",
            ))
        })
    }
}

fn lock<T>(mutex: &StdMutex<T>) -> MutexGuard<'_, T> {
    // A poisoned lock only means a panic elsewhere; the value stays valid.
    mutex.lock().unwrap_or_else(PoisonError::into_inner)
}

/// Everything a command task needs; shared by all calls of one core.
struct Shared {
    api_url: String,
    app_url: Option<String>,
    engine: Arc<CacheEngine<Bytes>>,
    ops: OrderedBlocking,
    credentials: Arc<AcknowledgedCredentials<Bytes>>,
    sink: ListenerSink,
    /// The actor state of the signed-in session; `None` while signed out.
    host: Mutex<Option<AppleHost>>,
    /// Revocation without waiting for a busy actor (logout priority lane).
    revocation: StdMutex<Option<RevocationHandle<Bytes>>>,
}

impl Shared {
    fn options(&self) -> ClientOptions {
        ClientOptions {
            identity: ClientIdentity::Apple,
            app_url: self.app_url.clone(),
            ..ClientOptions::default()
        }
    }

    async fn start(&self, cancel: CancellationToken) -> Result<()> {
        let mut host = self.host.lock().await;
        let Some(session) = self.credentials.load(self.ops.generation()).await? else {
            *host = None;
            *lock(&self.revocation) = None;
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
        let current = host.insert(AppleHost {
            core,
            api_url: self.api_url.clone(),
            credentials: self.credentials.clone(),
            cancel: cancel.clone(),
        });
        let start = ViewCommand::Start {
            credentials: Box::new(session),
        };
        view_model::handle(current, start, &self.sink, &cancel).await
    }

    async fn signed_in<F>(&self, cancel: CancellationToken, work: F) -> Result<()>
    where
        F: for<'a> FnOnce(
            &'a mut AppleHost,
            &'a ListenerSink,
            &'a CancellationToken,
        ) -> BoxFuture<'a, Result<()>>,
    {
        let mut host = self.host.lock().await;
        let host = host.as_mut().ok_or(Error::Authentication)?;
        host.cancel = cancel.clone();
        work(host, &self.sink, &cancel).await
    }

    async fn logout(&self) -> Result<()> {
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
    shared: Arc<Shared>,
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
            }),
            foreground: StdMutex::new(shutdown.child_token()),
            shutdown,
        }))
    }

    /// A fresh foreground token: replaces the previous one, fires on core
    /// shutdown, and when `cancellation` is cancelled. The core flows check
    /// it cooperatively, so a started persist is never cut in half.
    fn foreground(&self, cancellation: Option<Arc<CoreCancellation>>) -> CancellationToken {
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

    /// Run `work` to completion on the core runtime.
    async fn run<F>(&self, work: F) -> std::result::Result<(), CoreError>
    where
        F: Future<Output = Result<()>> + Send + 'static,
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

impl Drop for ViewModelCore {
    fn drop(&mut self) {
        self.shutdown.cancel();
        if let Some(runtime) = self.runtime.take() {
            // Never blocks, so it is safe on any thread, including a runtime worker.
            runtime.shutdown_background();
        }
    }
}
