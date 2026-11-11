//! CLI/TUI session policy over the core session runtime
//! (`openmates_sdk::shell_session`): which cache a command restores, what
//! admission prefetches, the `whoami` output, and the native credential
//! adapter (keyring/vault/session envelope stay in this crate). Restore,
//! persist, admission and logout ordering live in the core.
use crate::{
    client::{ChatRefreshDurableReceipt, Client},
    error::Result,
    runtime_store::RuntimeStore,
    storage::{Session, SessionSave},
};
use futures_util::future::BoxFuture;
use openmates_sdk::{
    client::CredentialSnapshot,
    shell_session::{self, CredentialPersistence, CredentialSave, DurableCandidate},
};
use tokio_util::sync::CancellationToken;
use zeroize::Zeroizing;

/// Logical sync cache key of the session's scope (core-owned).
pub use openmates_sdk::shell_session::cache_key;
/// Which part of the protected sync cache a command restores before dispatch.
pub use openmates_sdk::shell_session::CacheLoad;

/// The vault passphrase of the running profile, shared between the TUI actor
/// (login, unlock and pairing set it) and the credential backend the core
/// view-model actor owns. Never `Debug`; the value is zeroized on drop.
#[derive(Clone, Default)]
pub struct SharedPassphrase(std::sync::Arc<std::sync::Mutex<Option<Zeroizing<String>>>>);
impl SharedPassphrase {
    pub fn new(passphrase: Option<Zeroizing<String>>) -> Self {
        Self(std::sync::Arc::new(std::sync::Mutex::new(passphrase)))
    }
    /// A copy of the current passphrase, if any.
    pub fn get(&self) -> Option<Zeroizing<String>> {
        self.0.lock().unwrap_or_else(std::sync::PoisonError::into_inner).clone()
    }
    pub fn set(&self, passphrase: Option<Zeroizing<String>>) {
        *self.0.lock().unwrap_or_else(std::sync::PoisonError::into_inner) = passphrase;
    }
    pub fn is_some(&self) -> bool {
        self.0.lock().unwrap_or_else(std::sync::PoisonError::into_inner).is_some()
    }
    pub fn is_none(&self) -> bool {
        !self.is_some()
    }
}

/// This profile's credential store: `RuntimeStore` operations on the shared
/// ordered queue, with the vault passphrase current at each call.
struct NativeCredentials {
    store: RuntimeStore,
    passphrase: SharedPassphrase,
}
impl CredentialPersistence for NativeCredentials {
    fn load(&self, generation: u64) -> BoxFuture<'_, Result<Option<Session>>> {
        Box::pin(self.store.load_at(generation, self.passphrase.get()))
    }
    fn store(&self, snapshot: CredentialSnapshot, generation: u64) -> BoxFuture<'_, Result<CredentialSave>> {
        Box::pin(async move {
            Ok(match self.store.save_unless_superseded_at(generation, snapshot.session, self.passphrase.get()).await? {
                SessionSave::Saved(_) => CredentialSave::Saved,
                SessionSave::Superseded(stored) => CredentialSave::Superseded(Box::new(stored)),
            })
        })
    }
    fn revoke(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(self.store.announce_revocation())
    }
    fn clear(&self) -> BoxFuture<'_, Result<()>> {
        Box::pin(self.store.cleanup())
    }
}
fn credentials(store: &RuntimeStore, passphrase: Option<Zeroizing<String>>) -> NativeCredentials {
    NativeCredentials { store: store.clone(), passphrase: SharedPassphrase::new(passphrase) }
}

/// The credential backend the core view-model actor owns for the terminal
/// session: reads the passphrase from `passphrase` at every call.
pub fn shared_credentials(store: &RuntimeStore, passphrase: SharedPassphrase) -> std::sync::Arc<dyn CredentialPersistence> {
    std::sync::Arc::new(NativeCredentials { store: store.clone(), passphrase })
}

/// Account/settings reads and writes that never use cached Chats or embeds.
const DEFERRED_ACCOUNT_COMMANDS: &[&str] = &[
    "credits",
    "account info",
    "account username set",
    "account timezone set",
    "account interests list",
    "account interests set",
    "account interests clear",
    "account chats stats",
    "account storage overview",
    "account storage files",
    "interface language set",
    "interface dark-mode set",
    "interface font set",
    "billing overview",
    "billing usage",
    "billing usage summaries",
    "billing usage daily",
    "billing usage export",
    "billing usage overview",
    "billing usage details",
    "billing usage chat-total",
    "billing gift-card list",
    "billing invoices list",
    "billing bank-transfer list",
    "gift-card list",
    "developers api-keys list",
    "developers devices",
    "security sessions",
    "memories list",
    "memories types",
    "memories create",
    "memories update",
    "memories delete",
    "reminders list",
];

/// Cache restoration policy per command. Only commands proven not to read
/// cached Chats/embeds defer; `chats list` needs only the index.
pub fn command_cache_load(invocation: &crate::cli::Invocation) -> CacheLoad {
    let path = invocation.command_path();
    let account = path.strip_prefix("settings ").unwrap_or(&path);
    if path == "whoami" {
        CacheLoad::Deferred { revoke_list_freshness: false }
    } else if crate::cli::is_direct_apps_command(invocation)
        || DEFERRED_ACCOUNT_COMMANDS.contains(&account)
    {
        CacheLoad::Deferred { revoke_list_freshness: true }
    } else if path == "chats list" {
        CacheLoad::Index
    } else if matches!(path.as_str(), "chats show" | "chats messages") {
        // Cache-first open: index + this chat's record only (see chat_details).
        match invocation.positionals.first() {
            Some(id) if uuid::Uuid::parse_str(id).is_ok_and(|u| u.hyphenated().to_string() == *id) => {
                CacheLoad::Chat(id.clone())
            }
            _ => CacheLoad::Full,
        }
    } else if let Some(id) = (matches!(path.as_str(), "chats show" | "chats messages"))
        .then(|| invocation.positionals.first())
        .flatten()
        .filter(|id| uuid::Uuid::parse_str(id).is_ok())
    {
        // Cache-first saved read: the index plus only this Chat's section;
        // other content still loads on demand through the index loader.
        CacheLoad::Chat(id.clone())
    } else {
        CacheLoad::Full
    }
}

/// Restore only the selected durable profile's protected ciphertext before its
/// first save (see `ShellSession::restore`, `CacheLoad::Full`).
pub async fn restore_protected_cache(
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    cancel: &CancellationToken,
) -> Result<()> {
    restore_command_cache(client, store, passphrase, cancel, CacheLoad::Full).await
}

/// `restore_protected_cache` restricted to what the command needs
/// (`ShellSession::restore`).
pub async fn restore_command_cache(
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    cancel: &CancellationToken,
    load: CacheLoad,
) -> Result<()> {
    store.shell().restore(client, &credentials(store, passphrase), cancel, load).await
}

/// Cache-first Chat open (`ShellSession::load_cached_chat`).
pub async fn load_cached_chat(client: &mut Client, store: &RuntimeStore, chat: &str) -> Result<bool> {
    store.shell().load_cached_chat(client, chat).await
}

/// Conservative native command admission. The immediately following initial
/// FreshSessionAdmission save durably publishes this removal before dispatch.
/// Whoami and eligible same-scope Personal lists are the preservation paths.
/// A list cache miss separately revokes durably before foreground recovery.
pub fn prepare_command_cache_admission(client: &mut Client, invocation: &crate::cli::Invocation) {
    let preserve =
        invocation.command_path() == "whoami" || same_personal_chat_list_scope(client, invocation);
    if !preserve {
        client.invalidate_chat_list_freshness();
    }
    // Overlap the warm list's (and `chats open`'s) feed page with the session
    // admission that follows.
    if same_personal_chat_list_scope(client, invocation)
        || (invocation.command_path() == "chats open" && !invocation.has("api-key"))
    {
        client.prefetch_chat_sync_feed();
    }
    // A selected read always opens its recovery socket after admission:
    // pre-establish only that connection's TCP/TLS (no request, no token), and
    // send a JSON show's first read round now (cached tail delta included).
    if let Some(id) = overlapped_saved_read_chat(invocation) {
        client.preconnect_socket();
        if crate::cli::is_full_json_show(invocation) {
            client.prefetch_chat_details(id, &crate::cli::full_chat_read_options(invocation));
        }
    }
}

/// Only an unscoped `chats show|messages <canonical id>` overlaps admission;
/// --personal/--team transitions keep the ordinary post-admission order.
fn overlapped_saved_read_chat(invocation: &crate::cli::Invocation) -> Option<&str> {
    (matches!(invocation.command_path().as_str(), "chats show" | "chats messages")
        && !invocation.has("personal")
        && !invocation.has("team")
        && !invocation.has("api-key"))
    .then(|| invocation.positionals.first())
    .flatten()
    .map(String::as_str)
    .filter(|id| uuid::Uuid::parse_str(id).is_ok_and(|u| u.hyphenated().to_string() == *id))
}

/// Explicit --personal is scope-equivalent only while the admitted profile is
/// already Personal and contains no Direct rows. Eligibility grants no auth,
/// freshness, recovery clearance or output publication; those guards stay in
/// the existing warm read. Real Team transitions keep the foreground path and
/// SDK set_team retains its unconditional invalidation semantics.
pub(crate) fn same_personal_chat_list_scope(
    client: &Client,
    invocation: &crate::cli::Invocation,
) -> bool {
    invocation.command_path() == "chats list"
        && !invocation.has("team")
        && (!invocation.has("personal") || invocation.boolean("personal"))
        && client.supports_cached_default_chat_list()
}

/// A durable pre-dispatch fence for recovery, TUI and other uncertain effects
/// (`ShellSession::revoke_list_freshness_before_dispatch`).
pub async fn revoke_chat_cache_before_dispatch(
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    cancel: &CancellationToken,
) -> Result<()> {
    store.shell().revoke_list_freshness_before_dispatch(client, &credentials(store, passphrase), cancel).await
}

/// Single-use evidence of fresh server admission and durable initial save
/// (core `shell_session::FreshSessionAdmission`) plus the CLI `whoami` output.
///
/// A separately authenticated Client cannot be supplied to the formatter:
/// ```compile_fail
/// use openmates::{client::Client, cli::Invocation,
///     runtime_store::RuntimeStore, session_runtime::FreshSessionAdmission};
/// use tokio_util::sync::CancellationToken;
/// async fn replace(client: &mut Client, other: &Client, store: &RuntimeStore,
///     invocation: &Invocation, cancel: &CancellationToken) {
///     let admission = FreshSessionAdmission::admit(client, store, None, cancel).await.unwrap();
///     let _ = admission.whoami_output(invocation, other);
/// }
/// ```
/// The admitted Client cannot change account or Team while its guard exists:
/// ```compile_fail
/// use openmates::{client::Client, cli::Invocation,
///     runtime_store::RuntimeStore, session_runtime::FreshSessionAdmission};
/// use tokio_util::sync::CancellationToken;
/// async fn mutate(client: &mut Client, store: &RuntimeStore,
///     invocation: &Invocation, cancel: &CancellationToken) {
///     let admission = FreshSessionAdmission::admit(client, store, None, cancel).await.unwrap();
///     client.set_team(None).unwrap();
///     let _ = admission.whoami_output(invocation);
/// }
/// ```
pub struct FreshSessionAdmission<'a>(shell_session::FreshSessionAdmission<'a>);
impl<'a> FreshSessionAdmission<'a> {
    pub async fn admit(
        client: &'a mut Client,
        store: &RuntimeStore,
        passphrase: Option<Zeroizing<String>>,
        cancel: &CancellationToken,
    ) -> Result<Self> {
        let credentials = credentials(store, passphrase);
        shell_session::FreshSessionAdmission::admit(client, store.shell(), &credentials, cancel).await.map(Self)
    }
    /// Consume fresh server admission after its durable initial save.
    pub fn prepare_recovery(self) -> Result<()> {
        self.0.prepare_recovery()
    }
    pub fn user(&self) -> Result<&serde_json::Value> {
        self.0.user()
    }
    /// Consume the original admitted Client lane after the trusted-account
    /// check. The application retains its final PendingOutput persistence fence.
    pub fn whoami_output(
        self,
        invocation: &crate::cli::Invocation,
    ) -> std::result::Result<crate::cli::CliOutput, crate::cli::CliError> {
        crate::cli::admitted_whoami_output(invocation, self.0.into_user()?)
    }
}

/// Persist credentials and the protected cache, then acknowledge the saved
/// revision (`ShellSession::persist`).
pub async fn persist(
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
) -> Result<()> {
    store.shell().persist(client, &credentials(store, passphrase)).await
}

/// `persist` for a candidate that commits against a durable receipt; the core
/// mints the receipt only after the committed save (`ShellSession::persist_for`).
pub async fn persist_for<C: DurableCandidate + Sync>(
    client: &mut Client,
    store: &RuntimeStore,
    passphrase: Option<Zeroizing<String>>,
    candidate: &C,
) -> Result<ChatRefreshDurableReceipt> {
    store.shell().persist_for(client, &credentials(store, passphrase), candidate).await
}

/// Local revocation runs even if remote logout is unavailable
/// (`ShellSession::logout`).
pub async fn logout(client: &mut Client, store: &RuntimeStore) -> Result<()> {
    store.shell().logout(client, &credentials(store, None)).await
}

#[cfg(test)]
#[path = "session_runtime_tests.rs"]
mod tests;
