//! `OpenMatesCore`: the Apple shell's handle on the shared Rust client. It owns
//! one multi-thread tokio runtime and the `openmates_sdk::Client` (identity
//! `Apple`) behind an async mutex (plan apple-client-core-migration D-1). Every
//! async method runs on that runtime; Swift only awaits the result. Credentials
//! follow the snapshot/acknowledge contract of `client-core.credentials.snapshot-boundary`
//! (pattern: `openmates-tui-native/src/session_runtime.rs`): the core emits a
//! revision, Swift stores the opaque payload in the Keychain and acknowledges.
use crate::CoreError;
use openmates_sdk::{Client, ClientIdentity, ClientOptions, CredentialEvent, Session};
use std::future::Future;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;
use tokio::runtime::{Handle, Runtime};
use tokio::sync::{Mutex, mpsc};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

/// Worker thread name; `probe` reports whether it ran on such a thread.
const RUNTIME_THREAD_NAME: &str = "openmates-core";
/// Small pool: the core is I/O bound and shares the device with the UI.
const RUNTIME_WORKERS: usize = 2;

/// Construction options. No environment, file or Keychain is read.
#[derive(Clone, Debug, uniffi::Record)]
pub struct CoreConfig {
    /// API origin, e.g. `https://api.openmates.org` (https, or http on loopback).
    pub api_url: String,
    /// Web app origin used as the auth `Origin` and pairing destination.
    pub app_url: Option<String>,
}

/// Opaque credential snapshot for the Keychain. `payload` is the serialized core
/// `Session` (JSON, includes the master key): Swift stores and returns it
/// unchanged and never parses, logs or shows it.
#[derive(uniffi::Record)]
pub struct CredentialSnapshotRecord {
    /// Revision to pass to `acknowledge_credentials` after a successful store.
    pub revision: u64,
    /// Serialized session; secret.
    pub payload: Vec<u8>,
}

/// Result of `probe`: proves async delivery and where the work ran.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct ProbeRecord {
    /// Same value as `core_version()`.
    pub core_version: String,
    /// True when the body ran on a core runtime worker, not the caller's thread.
    pub ran_on_core_runtime: bool,
}

/// Update listener implemented in Swift. Called on a core runtime thread, never
/// the main thread; implementations hop to `@MainActor` themselves and must not
/// block. Ordering: revisions arrive in the order the core produced them.
#[uniffi::export(foreign)]
pub trait CoreListener: Send + Sync {
    /// Credentials changed (new session, rotation or cleared) at `revision`.
    /// Read `credential_snapshot()`: `nil` means delete the stored credentials;
    /// otherwise store the payload, then call `acknowledge_credentials(revision)`.
    fn credentials_changed(&self, revision: u64);
}

/// Caller-owned cancellation for one cancellable core call. Create one per call
/// and cancel it from Swift's `withTaskCancellationHandler(onCancel:)`.
/// Cancelling is idempotent, thread-safe and never blocks.
#[derive(uniffi::Object)]
pub struct CoreCancellation {
    token: CancellationToken,
}

#[uniffi::export]
impl CoreCancellation {
    /// A fresh, not yet cancelled handle.
    #[uniffi::constructor]
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            token: CancellationToken::new(),
        })
    }

    /// Cancel the call this handle was passed to (before or while it runs).
    pub fn cancel(&self) {
        self.token.cancel();
    }

    /// Whether `cancel` was called.
    pub fn is_cancelled(&self) -> bool {
        self.token.is_cancelled()
    }
}

type ListenerSlot = Arc<StdMutex<Option<Arc<dyn CoreListener>>>>;

/// The core instance. Create one per account process; drop shuts the runtime
/// down without blocking the caller.
#[derive(uniffi::Object)]
pub struct OpenMatesCore {
    runtime: Option<Runtime>,
    handle: Handle,
    api_url: String,
    client: Arc<Mutex<Client>>,
    listener: ListenerSlot,
    shutdown: CancellationToken,
    active: Arc<AtomicU64>,
}

/// Counts one in-flight runtime task until it finishes or is cancelled.
struct ActiveGuard(Arc<AtomicU64>);
impl ActiveGuard {
    fn new(counter: &Arc<AtomicU64>) -> Self {
        counter.fetch_add(1, Ordering::SeqCst);
        Self(counter.clone())
    }
}
impl Drop for ActiveGuard {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

fn join_result<T>(
    result: Result<Result<T, CoreError>, tokio::task::JoinError>,
) -> Result<T, CoreError> {
    match result {
        Ok(value) => value,
        Err(error) if error.is_cancelled() => Err(CoreError::internal("core runtime shut down")),
        Err(_) => Err(CoreError::internal("core task panicked")),
    }
}

fn lock_listener(slot: &ListenerSlot) -> Option<Arc<dyn CoreListener>> {
    // A poisoned slot only means a listener call panicked elsewhere; the stored
    // Arc itself is still valid, so recover it explicitly.
    match slot.lock() {
        Ok(guard) => guard.clone(),
        Err(poisoned) => poisoned.into_inner().clone(),
    }
}

impl OpenMatesCore {
    /// Run `work` on the core runtime to completion. Neither Swift task
    /// cancellation nor dropping the awaiting future stops it, so a started
    /// transaction is never cut in half; an unawaited result is discarded.
    async fn run<T, F>(&self, work: F) -> Result<T, CoreError>
    where
        T: Send + 'static,
        F: Future<Output = Result<T, CoreError>> + Send + 'static,
    {
        let guard = ActiveGuard::new(&self.active);
        join_result(
            self.handle
                .spawn(async move {
                    let _guard = guard;
                    work.await
                })
                .await,
        )
    }

    /// Run `work` on the core runtime with a token that fires when the caller's
    /// `CoreCancellation` is cancelled, the awaiting future is dropped, or the
    /// core shuts down; the work then ends with `CoreError::Cancelled`. Every
    /// cancellable call uses this one path.
    async fn run_cancellable<T, F, Fut>(
        &self,
        cancellation: &CoreCancellation,
        work: F,
    ) -> Result<T, CoreError>
    where
        T: Send + 'static,
        F: FnOnce(CancellationToken) -> Fut,
        Fut: Future<Output = Result<T, CoreError>> + Send + 'static,
    {
        let token = self.shutdown.child_token();
        let on_drop = token.clone().drop_guard();
        let caller = cancellation.token.clone();
        let guard = ActiveGuard::new(&self.active);
        let body = work(token.clone());
        let result = self
            .handle
            .spawn(async move {
                let _guard = guard;
                tokio::select! {
                    biased;
                    () = token.cancelled() => Err(CoreError::Cancelled),
                    () = caller.cancelled() => Err(CoreError::Cancelled),
                    value = body => value,
                }
            })
            .await;
        on_drop.disarm();
        join_result(result)
    }
}

#[uniffi::export]
impl OpenMatesCore {
    /// Create the core with its own runtime and an empty (signed-out) client.
    ///
    /// # Errors
    /// `Invalid` for a bad API or app URL; `Internal` if the runtime cannot start.
    #[uniffi::constructor]
    pub fn new(config: CoreConfig) -> Result<Arc<Self>, CoreError> {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(RUNTIME_WORKERS)
            .thread_name(RUNTIME_THREAD_NAME)
            .enable_all()
            .build()
            .map_err(|_| CoreError::internal("core runtime could not start"))?;
        let handle = runtime.handle().clone();
        // The HTTP client may register with the reactor; build inside the runtime.
        let entered = runtime.enter();
        let mut client = Client::with_options(
            &config.api_url,
            None,
            ClientOptions {
                identity: ClientIdentity::Apple,
                app_url: config.app_url,
                ..ClientOptions::default()
            },
        )?;
        let (updates, mut events) = mpsc::unbounded_channel::<CredentialEvent>();
        client.set_credential_updates(updates);
        drop(entered);
        let listener: ListenerSlot = Arc::new(StdMutex::new(None));
        let slot = listener.clone();
        handle.spawn(async move {
            while let Some(event) = events.recv().await {
                let revision = match &event {
                    CredentialEvent::Updated(snapshot) => snapshot.revision,
                    CredentialEvent::Cleared { revision } => *revision,
                };
                // Secrets never reach the listener; Swift pulls the snapshot.
                drop(event);
                if let Some(listener) = lock_listener(&slot) {
                    listener.credentials_changed(revision);
                }
            }
        });
        Ok(Arc::new(Self {
            runtime: Some(runtime),
            handle,
            api_url: config.api_url,
            client: Arc::new(Mutex::new(client)),
            listener,
            shutdown: CancellationToken::new(),
            active: Arc::new(AtomicU64::new(0)),
        }))
    }

    /// Register (or replace, or with `nil` remove) the update listener. Events
    /// produced before registration are not replayed; read `credential_snapshot()`
    /// once after registering.
    pub fn set_listener(&self, listener: Option<Arc<dyn CoreListener>>) {
        match self.listener.lock() {
            Ok(mut slot) => *slot = listener,
            Err(poisoned) => *poisoned.into_inner() = listener,
        }
    }

    /// Cheap async round trip with no network: runs on the core runtime and
    /// reports where it ran, so Swift can prove off-main delivery.
    ///
    /// # Errors
    /// `Internal` only if the runtime is gone.
    pub async fn probe(&self) -> Result<ProbeRecord, CoreError> {
        self.run(async {
            Ok(ProbeRecord {
                core_version: crate::core_version(),
                ran_on_core_runtime: std::thread::current().name() == Some(RUNTIME_THREAD_NAME),
            })
        })
        .await
    }

    /// Sleep `milliseconds` on the core runtime through the cancellable path,
    /// so Swift can test task cancellation. UniFFI's generated Swift does not
    /// forward `Task.cancel()`; wrap the call in `withTaskCancellationHandler`
    /// and call `cancellation.cancel()` in `onCancel`. The Rust work then stops
    /// at once (see `active_operations`) and the call throws `CoreError.Cancelled`.
    ///
    /// # Errors
    /// `Cancelled` when `cancellation` fires or the core shuts down first.
    pub async fn sleep_cancellable(
        &self,
        milliseconds: u64,
        cancellation: Arc<CoreCancellation>,
    ) -> Result<(), CoreError> {
        self.run_cancellable(&cancellation, move |_token| async move {
            tokio::time::sleep(Duration::from_millis(milliseconds)).await;
            Ok(())
        })
        .await
    }

    /// Number of core runtime tasks started by this object that have not yet
    /// finished. Diagnostic for cancellation tests; not a progress indicator.
    pub fn active_operations(&self) -> u64 {
        self.active.load(Ordering::SeqCst)
    }

    /// Current credentials as an opaque payload, or `nil` when signed out.
    ///
    /// # Errors
    /// `Protocol` if the session cannot be serialized; `Internal` if the runtime is gone.
    pub async fn credential_snapshot(&self) -> Result<Option<CredentialSnapshotRecord>, CoreError> {
        let client = self.client.clone();
        self.run(async move {
            let Some(snapshot) = client.lock().await.credential_snapshot() else {
                return Ok(None);
            };
            let payload = serde_json::to_vec(&snapshot.session).map_err(|_| CoreError::Protocol)?;
            Ok(Some(CredentialSnapshotRecord {
                revision: snapshot.revision,
                payload,
            }))
        })
        .await
    }

    /// Confirm that the snapshot at `revision` is stored durably.
    ///
    /// # Errors
    /// `Cancelled` for a stale revision (a newer snapshot exists: store that
    /// one); `Authentication` when signed out.
    pub async fn acknowledge_credentials(&self, revision: u64) -> Result<(), CoreError> {
        let client = self.client.clone();
        self.run(async move { Ok(client.lock().await.acknowledge_credentials(revision)?) })
            .await
    }

    /// Load a payload previously returned by `credential_snapshot()` (app
    /// launch). Emits `credentials_changed` with a new revision; store and
    /// acknowledge it as usual. The payload buffer is zeroized after parsing.
    ///
    /// # Errors
    /// `Protocol` for an unreadable payload; `Forbidden` for a session of another
    /// API origin; `Expired` for an expired paired session.
    pub async fn restore_credentials(&self, payload: Vec<u8>) -> Result<(), CoreError> {
        let client = self.client.clone();
        let api_url = self.api_url.clone();
        self.run(async move {
            let payload = Zeroizing::new(payload);
            let session: Session =
                serde_json::from_slice(&payload).map_err(|_| CoreError::Protocol)?;
            client.lock().await.reset(&api_url, Some(session))?;
            Ok(())
        })
        .await
    }

    /// Drop the in-memory credentials (local sign-out). Emits
    /// `credentials_changed`; `credential_snapshot()` then returns `nil`.
    ///
    /// # Errors
    /// `Internal` only if the runtime is gone.
    pub async fn clear_credentials(&self) -> Result<(), CoreError> {
        let client = self.client.clone();
        let api_url = self.api_url.clone();
        self.run(async move { Ok(client.lock().await.reset(&api_url, None)?) })
            .await
    }
}

impl Drop for OpenMatesCore {
    fn drop(&mut self) {
        self.shutdown.cancel();
        if let Some(runtime) = self.runtime.take() {
            // Never blocks, so it is safe on any thread, including a runtime worker.
            runtime.shutdown_background();
        }
    }
}

/// Synthetic, never-valid credentials payload for Swift and Rust tests of the
/// snapshot round trip without a server: random master key, fixed fake ids, no
/// cookies. Pass it to `restore_credentials` on a core built with the same
/// `api_url`. It authorizes nothing on any server.
///
/// # Errors
/// `Protocol` if serialization fails.
#[uniffi::export]
pub fn test_support_synthetic_credentials_payload(api_url: String) -> Result<Vec<u8>, CoreError> {
    let session = Session {
        api_url,
        session_id: "synthetic-test-session".into(),
        cookies: Default::default(),
        ws_token: None,
        master_key: openmates_sdk::crypto::random_key(),
        hashed_email: "synthetic-test-hashed-email".into(),
        user_email_salt: "synthetic-test-salt".into(),
        email_encryption_key: None,
        created_at: 0,
        paired_session_expires_at: None,
        active_team_id: None,
    };
    serde_json::to_vec(&session).map_err(|_| CoreError::Protocol)
}
