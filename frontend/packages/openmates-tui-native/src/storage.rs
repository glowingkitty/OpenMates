//! Native credentials use an OS keyring, restricted local key file, or an
//! explicitly selected passphrase vault. Local-key mode has owner-only file
//! protection, not OS-keyring-equivalent protection.
//! State is separate from the TypeScript CLI. Private session/cache data is always
//! authenticated ciphertext on disk; keyring failures never migrate existing data.
use crate::{
    crypto::Key,
    error::{Error, Result},
};
use argon2::{Algorithm, Argon2, Block, Params, Version};
use base64::{Engine, engine::general_purpose::STANDARD};
use hmac::{Hmac, Mac};
use rand::{RngCore, rngs::OsRng};
use openmates_sdk::local_cache::{
    ByteStore, ByteStoreError, CacheAdmission, CacheContext, CacheEngine, Durability,
    FileByteStore, FileIdentity, LockGuard, OperationScope, RevocationFence,
};
// Record codec and naming live in the core; these are the names the TUI's
// session code uses. The rest are test-only helpers for assertions on files.
pub(crate) use openmates_sdk::local_cache::{
    open as decrypt, owner_hash as owner_id, seal as encrypt, sha256_hex as digest,
};
#[cfg(test)]
pub(crate) use openmates_sdk::local_cache::{
    MAX_LOCAL_RECORD_BYTES, cache_file_name as cache_name, cache_record_encoded_len,
    encode_bounded_json as encode_bounded_cache,
};
pub use openmates_sdk::local_cache::StorageMode;
use openmates_sdk::local_cache::PendingCleanup;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::File,
    io::Read,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};
use zeroize::{Zeroize, Zeroizing};

// Credential DTO belongs to the headless SDK; keyring/vault policy stays here.
pub use openmates_sdk::Session;

pub(crate) use openmates_sdk::local_cache::{PreparedSections, SyncCacheRead, SyncReadMode};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeyringFailure {
    Missing,
    Unavailable,
}
/// Injection point for isolated tests. Implementations must never log secrets.
pub trait CredentialBackend: Send + Sync {
    fn get(&self, account: &str) -> std::result::Result<Zeroizing<Vec<u8>>, KeyringFailure>;
    fn set(&self, account: &str, secret: &[u8]) -> std::result::Result<(), KeyringFailure>;
    fn delete(&self, account: &str) -> std::result::Result<(), KeyringFailure>;
}
struct NativeKeyring;
impl CredentialBackend for NativeKeyring {
    fn get(&self, account: &str) -> std::result::Result<Zeroizing<Vec<u8>>, KeyringFailure> {
        keyring::Entry::new("OpenMates Rust TUI", account)
            .map_err(keyring_failure)?
            .get_secret()
            .map(Zeroizing::new)
            .map_err(keyring_failure)
    }
    fn set(&self, account: &str, secret: &[u8]) -> std::result::Result<(), KeyringFailure> {
        keyring::Entry::new("OpenMates Rust TUI", account)
            .map_err(keyring_failure)?
            .set_secret(secret)
            .map_err(keyring_failure)
    }
    fn delete(&self, account: &str) -> std::result::Result<(), KeyringFailure> {
        match keyring::Entry::new("OpenMates Rust TUI", account)
            .map_err(keyring_failure)?
            .delete_credential()
        {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(error) => Err(keyring_failure(error)),
        }
    }
}
fn keyring_failure(error: keyring::Error) -> KeyringFailure {
    match error {
        keyring::Error::NoEntry => KeyringFailure::Missing,
        _ => KeyringFailure::Unavailable,
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    version: u8,
    mode: StorageMode,
    owner: String,
    context: String,
    expires_at: Option<u64>,
    salt: Option<String>,
    ciphertext: String,
}
impl Envelope {
    fn aad(&self) -> Result<Vec<u8>> {
        Ok(serde_json::to_vec(&(
            self.version,
            self.mode,
            &self.owner,
            &self.context,
            self.expires_at,
            &self.salt,
        ))?)
    }
    fn validate(&self) -> Result<()> {
        if self.version != 1 || self.owner.len() != 64 || self.context.len() != 64 {
            return Err(Error::Protocol);
        }
        if expired(self.expires_at) {
            return Err(Error::Expired);
        }
        Ok(())
    }
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PrivateRecord {
    version: u8,
    owner: String,
    context: String,
    ciphertext: String,
}
// Only authenticated vaults enter this cache. No passphrase or deterministic
// password verifier is retained: a fresh random HMAC key verifies warm calls.
struct UnlockedVault {
    key: Key,
    verifier_key: Key,
    verifier: Zeroizing<[u8; 32]>,
    binding: String,
    #[cfg(test)]
    erased: Option<Arc<std::sync::atomic::AtomicBool>>,
}
impl Drop for UnlockedVault {
    fn drop(&mut self) {
        self.key.zeroize();
        self.verifier_key.zeroize();
        self.verifier.zeroize();
        self.binding.zeroize();
        #[cfg(test)]
        if let Some(erased) = &self.erased {
            erased.store(
                self.key
                    .iter()
                    .chain(self.verifier_key.iter())
                    .chain(self.verifier.iter())
                    .all(|byte| *byte == 0),
                std::sync::atomic::Ordering::SeqCst,
            );
        }
    }
}

/// Outcome of a save that must not clobber a session another process rotated.
pub enum SessionSave {
    /// Whether the session was written (false: already the durable one).
    Saved(bool),
    /// The stored session is newer than the caller's; it was not overwritten.
    Superseded(Session),
}
/// In-process evidence of the exact durable session publication. The Store's
/// lifetime runtime lock excludes other writers; every skip still rechecks the
/// fence epoch, cleanup state and current session.json bytes. Never serialized.
#[derive(Clone)]
struct DurableSession {
    epoch: String,
    session_digest: [u8; 32],
    envelope_digest: [u8; 32],
    synced: bool,
}
// A first intent is reusable only while the exact durable inode remains current.
// Bytes alone cannot prove that a later replacement was durably published.
struct DurableRevocationIntent {
    file: File,
    identity: FileIdentity,
    bytes: Vec<u8>,
}
#[cfg(test)]
#[derive(Default)]
struct SessionIntentTestState {
    revocation_writes: usize,
    session_writes: usize,
    fail_revocation_at: Option<usize>,
    fail_after_revocation_rename_at: Option<usize>,
    fail_session: bool,
    before_final: Option<Box<dyn FnOnce(&Store) + Send>>,
}
/// A descriptor anchored at a private, owner-controlled directory.
pub struct Store {
    bytes: Arc<FileByteStore>,
    /// The encrypted cache engine (core-owned) over this directory's records.
    cache: Arc<CacheEngine<CacheBytes>>,
    path: PathBuf,
    account: String,
    backend: Arc<dyn CredentialBackend>,
    force_vault: bool,
    runtime_guard: Mutex<Option<LockGuard>>,
    /// Set by long-running hosts: the runtime lock is then taken per operation.
    per_operation_lock: std::sync::atomic::AtomicBool,
    vault_cache: Mutex<Option<UnlockedVault>>,
    #[cfg(test)]
    session_intent_test: Mutex<SessionIntentTestState>,
    durable_session: Mutex<Option<DurableSession>>,
    #[cfg(test)]
    vault_derivations: std::sync::atomic::AtomicUsize,
    #[cfg(test)]
    io_counts: Arc<IoCounts>,
}
/// Test-only counters of private session/cache record reads and publications.
#[cfg(test)]
#[derive(Default)]
pub(crate) struct IoCounts {
    pub(crate) cache_reads: std::sync::atomic::AtomicUsize,
    pub(crate) cache_writes: std::sync::atomic::AtomicUsize,
    pub(crate) session_writes: std::sync::atomic::AtomicUsize,
    pub(crate) revocation_writes: std::sync::atomic::AtomicUsize,
}
impl Store {
    pub fn default_path() -> Result<PathBuf> {
        directories::BaseDirs::new()
            .map(|dirs| dirs.home_dir().join(".openmates-rust"))
            .ok_or(Error::Io)
    }
    pub fn new(path: PathBuf) -> Result<Self> {
        let store = Self::with_backend(path, Arc::new(NativeKeyring))?;
        let guard = store.bytes.try_lock("runtime.lock").map_err(|error| match error {
            ByteStoreError::WouldBlock => {
                Error::Invalid("This state directory is already in use by another native client.")
            }
            _ => Error::Io,
        })?;
        *store.runtime_guard.lock().map_err(|_| Error::Io)? = Some(guard);
        Ok(store)
    }
    /// Long-running hosts (`remote-access`) must not exclude every other
    /// `openmates` command on the same state directory for their lifetime.
    /// After this call the runtime lock is released and `with_runtime_lock`
    /// takes it only around each store operation, so one-shot commands run
    /// between operations while the cookie-refresh and cache-write exclusion
    /// still holds for every individual operation.
    pub fn scope_runtime_lock_to_operations(&self) -> Result<()> {
        self.per_operation_lock
            .store(true, std::sync::atomic::Ordering::SeqCst);
        self.runtime_guard.lock().map_err(|_| Error::Io)?.take();
        Ok(())
    }
    /// Run one store operation under the runtime lock when it is per-operation
    /// (a no-op for lifetime-locked stores). Waits a bounded time for a
    /// concurrent one-shot command to finish rather than blocking forever.
    pub fn with_runtime_lock<T>(&self, operation: impl FnOnce() -> Result<T>) -> Result<T> {
        if !self.per_operation_lock.load(std::sync::atomic::Ordering::SeqCst) {
            return operation();
        }
        let _guard = self
            .bytes
            .lock_timeout("runtime.lock", std::time::Duration::from_secs(60))?;
        operation()
    }
    /// Injectable backend for isolated storage tests; production constructors
    /// additionally hold a lifetime runtime lock against cookie-refresh races.
    pub fn with_backend(path: PathBuf, backend: Arc<dyn CredentialBackend>) -> Result<Self> {
        // Equivalent spellings must address the same keyring namespace.
        let path: PathBuf = path.components().collect();
        let bytes = Arc::new(FileByteStore::open(&path)?);
        #[cfg(test)]
        let io_counts = Arc::new(IoCounts::default());
        let cache = Arc::new(CacheEngine::new(CacheBytes {
            inner: bytes.clone(),
            #[cfg(test)]
            io: io_counts.clone(),
        }));
        let account = digest(path.as_os_str().as_encoded_bytes());
        Ok(Self {
            bytes,
            cache,
            path,
            account,
            backend,
            force_vault: false,
            runtime_guard: Mutex::new(None),
            per_operation_lock: std::sync::atomic::AtomicBool::new(false),
            vault_cache: Mutex::new(None),
            #[cfg(test)]
            session_intent_test: Mutex::new(SessionIntentTestState::default()),
            durable_session: Mutex::new(None),
            #[cfg(test)]
            vault_derivations: std::sync::atomic::AtomicUsize::new(0),
            #[cfg(test)]
            io_counts,
        })
    }
    /// Explicit local vault mode, useful on hosts without a native credential store.
    /// Existing OS-keyring sessions cannot be opened or downgraded through this mode.
    pub fn encrypted_vault(path: PathBuf) -> Result<Self> {
        let mut store = Self::new(path)?;
        store.force_vault = true;
        Ok(store)
    }
    pub fn state_dir(&self) -> &Path {
        &self.path
    }
    pub fn storage_mode(&self) -> Result<Option<StorageMode>> {
        if self.fence()?.revoked {
            return Ok(None);
        }
        let _guard = self.lock("session.lock")?;
        Ok(self.envelope()?.map(|record| record.mode))
    }
    pub fn load_session(&self, passphrase: Option<&str>) -> Result<Option<Session>> {
        let fence = self.fence()?;
        if fence.revoked {
            self.clear_vault_cache()?;
            return Ok(None);
        }
        let _guard = self.lock("session.lock")?;
        self.require_epoch(&fence.epoch)?;
        if self.pending_cleanup()?.is_some() {
            return Ok(None);
        }
        let Some((envelope, envelope_digest)) = self.envelope_with_digest()? else {
            return Ok(None);
        };
        envelope.validate()?;
        let key = self.unwrap_key(&envelope, passphrase)?;
        let plaintext = match decrypt(&key, &envelope.ciphertext, &envelope.aad()?) {
            Ok(plaintext) => plaintext,
            Err(error) => {
                self.clear_vault_cache()?;
                return Err(error);
            }
        };
        let session: Session = serde_json::from_slice(&plaintext)?;
        if session.is_expired() {
            return Err(Error::Expired);
        }
        if owner_id(&session.hashed_email) != envelope.owner
            || session_context(&session)? != envelope.context
            || session.paired_session_expires_at != envelope.expires_at
        {
            return Err(Error::Crypto);
        }
        let _fence = self.lock("revocation.lock")?;
        self.require_epoch(&fence.epoch)?;
        self.remember_vault_key(&envelope, passphrase, &key)?;
        // Loaded bytes are evidence only: an unsynced earlier publication is
        // fsynced once before a later save may be skipped (see below).
        self.remember_durable_session(DurableSession {
            epoch: fence.epoch,
            session_digest: session_digest(&session)?,
            envelope_digest,
            synced: false,
        });
        Ok(Some(session))
    }
    fn remember_durable_session(&self, evidence: DurableSession) {
        *self
            .durable_session
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(evidence);
    }
    fn forget_durable_evidence(&self) {
        self.durable_session
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take();
        self.cache.forget_evidence();
    }
    /// Change-only persistence: skip the credential publication when the exact
    /// session is already the durable one for the current epoch. Otherwise (or
    /// on any doubt) this is precisely `save_session`. Returns whether it wrote.
    pub fn save_session_if_changed(
        &self,
        session: &Session,
        passphrase: Option<&str>,
    ) -> Result<bool> {
        if !session.is_expired() && self.durable_session_current(session, passphrase)? {
            return Ok(false);
        }
        self.save_session(session, passphrase).map(|()| true)
    }
    /// Per-operation (host) stores only: the stored session when another
    /// process rotated and saved it since this process last loaded or saved
    /// it (the stored record's digest no longer matches the remembered one).
    /// Lifetime-locked stores and stores with no remembered record never
    /// report one, so one-shot commands behave exactly as before. The caller
    /// must already hold the runtime lock (`RuntimeStore` operations do), so
    /// the comparison and any following write form one critical section; this
    /// never takes the runtime lock itself, which would deadlock under it.
    pub fn superseded_session(&self, passphrase: Option<&str>) -> Result<Option<Session>> {
        if !self.per_operation_lock.load(std::sync::atomic::Ordering::SeqCst) {
            return Ok(None);
        }
        let Some(remembered) = self
            .durable_session
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
        else {
            return Ok(None);
        };
        let stored_digest = {
            let _guard = self.lock("session.lock")?;
            self.envelope_with_digest()?.map(|(_, digest)| digest)
        };
        match stored_digest {
            Some(digest) if digest != remembered.envelope_digest => self.load_session(passphrase),
            _ => Ok(None),
        }
    }
    /// `save_session_if_changed`, except that a host whose stored session was
    /// rotated by another process adopts that one instead of overwriting it
    /// with its older in-memory credentials. Same lock contract as
    /// `superseded_session`.
    pub fn save_session_unless_superseded(
        &self,
        session: &Session,
        passphrase: Option<&str>,
    ) -> Result<SessionSave> {
        if let Some(stored) = self.superseded_session(passphrase)? {
            return Ok(SessionSave::Superseded(stored));
        }
        self.save_session_if_changed(session, passphrase).map(SessionSave::Saved)
    }
    fn durable_session_current(&self, session: &Session, passphrase: Option<&str>) -> Result<bool> {
        let digest = session_digest(session)?;
        let Some(remembered) = self
            .durable_session
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
            .filter(|remembered| remembered.session_digest == digest)
        else {
            return Ok(false);
        };
        let _guard = self.lock("session.lock")?;
        let fence = self.fence()?;
        if fence.revoked || fence.epoch != remembered.epoch || self.pending_cleanup()?.is_some() {
            return Ok(false);
        }
        let Some((envelope, envelope_digest)) = self.envelope_with_digest()? else {
            return Ok(false);
        };
        let context = session_context(session)?;
        let unchanged = envelope_digest == remembered.envelope_digest
            && envelope.validate().is_ok()
            && envelope.owner == owner_id(&session.hashed_email)
            && envelope.context == context
            && envelope.expires_at == session.paired_session_expires_at
            && fence.context.as_ref() == Some(&context)
            && fence.admitted.as_ref().is_none_or(|admitted| admitted == &context)
            && fence.cleanup.as_ref().is_some_and(|cleanup| {
                cleanup.mode == envelope.mode && cleanup.owner == envelope.owner
            });
        // A vault passphrase must still verify exactly as an ordinary save would.
        if !unchanged
            || (envelope.mode == StorageMode::EncryptedVault
                && self.unwrap_key(&envelope, passphrase).is_err())
        {
            return Ok(false);
        }
        let _fence = self.lock("revocation.lock")?;
        self.require_epoch(&remembered.epoch)?;
        if !remembered.synced {
            for name in ["session.json", "revocation.json"] {
                self.bytes.sync(name)?;
            }
            self.bytes.barrier()?;
            self.remember_durable_session(DurableSession { synced: true, ..remembered });
        }
        Ok(true)
    }
    pub fn save_session(&self, session: &Session, passphrase: Option<&str>) -> Result<()> {
        if session.is_expired() {
            self.clear_vault_cache()?;
            return Err(Error::Expired);
        }
        if session.hashed_email.is_empty() || session.session_id.is_empty() {
            return Err(Error::Invalid("A session owner is required."));
        }
        let _guard = self.lock("session.lock")?;
        self.durable_session
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take();
        let mut fence = self.fence()?;
        if fence.revoked {
            return Err(Error::Locked);
        }
        if self.pending_cleanup()?.is_some() {
            return Err(Error::Locked);
        }
        let existing = self.envelope()?;
        let owner = owner_id(&session.hashed_email);
        if existing
            .as_ref()
            .is_some_and(|record| record.owner != owner)
        {
            return Err(Error::Invalid(
                "Sign out before changing the stored account.",
            ));
        }
        let context = session_context(session)?;
        if fence
            .admitted
            .as_ref()
            .is_some_and(|admitted| admitted != &context)
        {
            return Err(Error::Authentication);
        }
        // Publish the intent before an OS backend can stall, including the first
        // save before session.json exists. Logout can then clean an orphan key.
        let published_intent = {
            let _fence = self.lock("revocation.lock")?;
            self.require_epoch(&fence.epoch)?;
            if fence.epoch.is_empty() {
                fence.version = 1;
                fence.epoch = uuid::Uuid::new_v4().to_string();
            }
            fence.context = Some(context.clone());
            fence.cleanup = Some(PendingCleanup {
                mode: existing
                    .as_ref()
                    .map(|record| record.mode)
                    .unwrap_or(if self.force_vault {
                        StorageMode::EncryptedVault
                    } else {
                        StorageMode::OsKeyring
                    }),
                owner: owner.clone(),
            });
            let bytes = serde_json::to_vec(&fence)?;
            let file = self.atomic_write_file("revocation.json", &bytes)?;
            // Optional evidence: unsupported/failed identity capture takes the
            // original second-write path, never grants authority or fails save.
            FileByteStore::identity(&file).ok().map(|identity| {
                DurableRevocationIntent { file, identity, bytes }
            })
        };
        let (mode, salt, key) = match existing.as_ref() {
            Some(record) => {
                record.validate()?;
                let key = self.unwrap_key(record, passphrase)?;
                // Authenticate the old vault before replacing it. A mistyped
                // passphrase must never silently re-encrypt an existing session.
                let plaintext = decrypt(&key, &record.ciphertext, &record.aad()?)?;
                let saved: Session = serde_json::from_slice(&plaintext)?;
                if owner_id(&saved.hashed_email) != record.owner
                    || session_context(&saved)? != record.context
                    || saved.paired_session_expires_at != record.expires_at
                {
                    return Err(Error::Crypto);
                }
                (record.mode, record.salt.clone(), key)
            }
            None if !self.force_vault => {
                let key = random_key();
                match self.backend.set(&self.account, key.as_ref()) {
                    Ok(()) => (StorageMode::OsKeyring, None, key),
                    // A password already supplied for native password login or
                    // the explicit pairing vault field retains its protection.
                    // Browser pairing without one never adds a password prompt.
                    Err(_) if passphrase.is_some_and(|value| !value.is_empty()) => {
                        self.new_vault_key(passphrase)?
                    }
                    Err(_) => {
                        // Preserve existing CLI login behavior without another
                        // password. A random local wrapping key has the same
                        // owner-only filesystem boundary as the legacy file
                        // fallback; it is never called keyring protection.
                        let _fence = self.lock("revocation.lock")?;
                        self.require_epoch(&fence.epoch)?;
                        self.atomic_write("credential-key", key.as_ref())?;
                        (StorageMode::RestrictedLocalFile, None, key)
                    }
                }
            }
            None => self.new_vault_key(passphrase)?,
        };
        let mut envelope = Envelope {
            version: 1,
            mode,
            owner,
            context,
            expires_at: session.paired_session_expires_at,
            salt,
            ciphertext: String::new(),
        };
        let plaintext = Zeroizing::new(serde_json::to_vec(session)?);
        envelope.ciphertext = encrypt(&key, &plaintext, &envelope.aad()?)?;
        #[cfg(test)]
        {
            let action = self.session_intent_test.lock().unwrap().before_final.take();
            if let Some(action) = action { action(self); }
        }
        // Only disk/crypto work is allowed while holding this independent fence.
        // A late keyring result must never publish across durable logout.
        let publication = self.lock("revocation.lock")?;
        self.require_epoch(&fence.epoch)?;
        fence.cleanup = Some(PendingCleanup {
            mode,
            owner: envelope.owner.clone(),
        });
        let final_intent = serde_json::to_vec(&fence)?;
        // The original final lock and epoch check remain above. Other Store
        // processes may have replaced the first intent while keyring work ran;
        // only its still-current exact durable descriptor can avoid this write.
        let already_durable = published_intent.as_ref().is_some_and(|intent| {
            self.reuses_revocation_intent(intent, &final_intent).unwrap_or(false)
        });
        if !already_durable {
            self.atomic_write("revocation.json", &final_intent)?;
        }
        let envelope_bytes = serde_json::to_vec(&envelope)?;
        let result = self.atomic_write("session.json", &envelope_bytes);
        drop(publication);
        if result.is_err() && existing.is_none() && mode == StorageMode::OsKeyring {
            // Do not leave an untracked wrapping key behind after a failed save.
            self.backend
                .delete(&self.account)
                .map_err(|_| Error::Locked)?;
        }
        if result.is_err() && existing.is_none() && mode == StorageMode::RestrictedLocalFile {
            self.remove("credential-key")?;
            self.bytes.barrier()?;
        }
        if result.is_ok() {
            // Even a newly created cache entry follows a verified AEAD record.
            let _authenticated = decrypt(&key, &envelope.ciphertext, &envelope.aad()?)?;
            let _fence = self.lock("revocation.lock")?;
            self.require_epoch(&fence.epoch)?;
            self.remember_vault_key(&envelope, passphrase, &key)?;
            self.remember_durable_session(DurableSession {
                epoch: fence.epoch.clone(),
                session_digest: session_digest(session)?,
                envelope_digest: Sha256::digest(&envelope_bytes).into(),
                synced: true,
            });
        }
        result
    }
    /// Application-owned stable identity contains no key or account material.
    /// The headless SDK receives this explicitly and never discovers this file.
    pub fn device_identity(&self) -> Result<String> {
        let _guard = self.lock("device.lock")?;
        if let Some(bytes) = self.read("sdk-device-id")? {
            let value = std::str::from_utf8(&bytes).map_err(|_| Error::Protocol)?;
            if value.len() > 128
                || !value.starts_with("cli:")
                || !value
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || matches!(b, b':' | b'-'))
            {
                return Err(Error::Protocol);
            }
            return Ok(value.to_owned());
        }
        let value = format!("cli:{}", uuid::Uuid::new_v4());
        self.atomic_write("sdk-device-id", value.as_bytes())?;
        Ok(value)
    }
    /// Public free-usage identity, isolated from account/device approval IDs.
    /// The application must use its per-origin anonymous state directory. This
    /// record contains no transcript, credentials or key material and survives
    /// session logout; the SDK receives its value explicitly.
    pub fn anonymous_identity(&self) -> Result<String> {
        let _guard = self.lock("anonymous.lock")?;
        if let Some(bytes) = self.read("anonymous-id")? {
            let value = std::str::from_utf8(&bytes).map_err(|_| Error::Protocol)?;
            let id = uuid::Uuid::parse_str(value).map_err(|_| Error::Protocol)?;
            if id.get_version_num() != 4 || id.to_string() != value {
                return Err(Error::Protocol);
            }
            return Ok(value.to_owned());
        }
        let value = uuid::Uuid::new_v4().to_string();
        self.atomic_write("anonymous-id", value.as_bytes())?;
        Ok(value)
    }
    /// Explicit-key application journals also support API-key callers without
    /// manufacturing or discovering a cookie session. The profile descriptor,
    /// owner and context all participate in authenticated encryption.
    pub fn update_private_record<T>(
        &self,
        owner: &str,
        context: &str,
        name: &str,
        key: &Key,
        update: impl FnOnce(Option<serde_json::Value>) -> Result<(Option<serde_json::Value>, T)>,
    ) -> Result<T> {
        let epoch = self.active_epoch()?;
        let owner = owner_id(owner);
        let context = digest(context.as_bytes());
        let name = digest(name.as_bytes());
        let file = format!("private-{owner}-{context}-{name}.json");
        let _guard = self.lock(&format!("{file}.lock"))?;
        let aad = serde_json::to_vec(&(
            "openmates-private-journal-v1",
            &self.account,
            &owner,
            &context,
            &name,
        ))?;
        let previous = match self.read(&file)? {
            None => None,
            Some(raw) => {
                let record: PrivateRecord = serde_json::from_slice(&raw)?;
                if record.version != 1 || record.owner != owner || record.context != context {
                    return Err(Error::Crypto);
                }
                Some(serde_json::from_slice(&decrypt(
                    key,
                    &record.ciphertext,
                    &aad,
                )?)?)
            }
        };
        let (next, result) = update(previous)?;
        let Some(next) = next else {
            let _fence = self.lock("revocation.lock")?;
            self.require_epoch(&epoch)?;
            return Ok(result);
        };
        let plaintext = Zeroizing::new(serde_json::to_vec(&next)?);
        if plaintext.len() > 16 * 1024 * 1024 {
            return Err(Error::Invalid(
                "The local journal is full; no pending delivery was removed.",
            ));
        }
        let record = PrivateRecord {
            version: 1,
            owner,
            context,
            ciphertext: encrypt(key, &plaintext, &aad)?,
        };
        let _fence = self.lock("revocation.lock")?;
        self.require_epoch(&epoch)?;
        self.atomic_write(&file, &serde_json::to_vec(&record)?)?;
        Ok(result)
    }
    /// Durable, descriptor-anchored announcement never waits for session/keyring
    /// work. Repeated announcements preserve the context and cleanup intent.
    pub fn revoke_session(&self) -> Result<()> {
        let _fence = self.lock("revocation.lock")?;
        self.forget_durable_evidence();
        let mut fence = self.fence()?;
        if !fence.revoked {
            let existing = self.read("session.json").and_then(|bytes| {
                bytes
                    .map(|bytes| serde_json::from_slice::<Envelope>(&bytes).map_err(Error::from))
                    .transpose()
            });
            fence.retired_contexts = fence.context.iter().cloned().collect();
            if let Ok(Some(record)) = &existing {
                if !fence.retired_contexts.contains(&record.context) {
                    fence.retired_contexts.push(record.context.clone());
                }
                fence.cleanup = Some(PendingCleanup {
                    mode: record.mode,
                    owner: record.owner.clone(),
                });
            }
            fence.version = 1;
            fence.epoch = uuid::Uuid::new_v4().to_string();
            fence.revoked = true;
            self.atomic_write("revocation.json", &serde_json::to_vec(&fence)?)?;
            self.clear_vault_cache()?;
            // Damaged ciphertext may prevent physical cleanup, but cannot stop
            // the logout fence from becoming durable first.
            let _ = existing?;
        }
        self.clear_vault_cache()?;
        Ok(())
    }
    /// Called only following fresh authenticated admission. Cleanup remains
    /// fenced through any backend failure; an old snapshot cannot reopen it.
    pub fn begin_session(&self, session: &Session) -> Result<()> {
        self.begin_session_if(session, || Ok(()))
    }
    pub(crate) fn begin_session_if(
        &self,
        session: &Session,
        admitted: impl FnOnce() -> Result<()>,
    ) -> Result<()> {
        if session.is_expired() || session.hashed_email.is_empty() || session.session_id.is_empty()
        {
            return Err(Error::Authentication);
        }
        let _guard = self.lock("session.lock")?;
        let before = self.fence()?;
        let context = session_context(session)?;
        if before.revoked && before.retired_contexts.contains(&context) {
            return Err(Error::Authentication);
        }
        let existing = self.envelope()?;
        if before.revoked
            && existing
                .as_ref()
                .is_some_and(|record| record.context == context)
        {
            return Err(Error::Authentication);
        }
        if !before.revoked && before.admitted.as_ref() == Some(&context) {
            if existing.as_ref().is_some_and(|record| {
                record.context != context || record.owner != owner_id(&session.hashed_email)
            }) {
                return Err(Error::Authentication);
            }
            // Pairing can retry the same admission after a vault-unlock prompt.
            // This path changes neither the epoch nor prior cleanup metadata.
            let _fence = self.lock("revocation.lock")?;
            self.require_epoch(&before.epoch)?;
            admitted()?;
            return Ok(());
        }
        if !before.revoked && (existing.is_some() || before.cleanup.is_some()) {
            return Err(Error::Invalid(
                "Sign out before admitting another stored session.",
            ));
        }
        if before.revoked || self.pending_cleanup()?.is_some() {
            self.clear_session_locked()?;
        }
        let _fence = self.lock("revocation.lock")?;
        if self.fence()?.epoch != before.epoch {
            return Err(Error::Cancelled);
        }
        admitted()?;
        let fence = RevocationFence {
            version: 1,
            epoch: uuid::Uuid::new_v4().to_string(),
            admitted: Some(context.clone()),
            context: Some(context),
            ..Default::default()
        };
        self.atomic_write("revocation.json", &serde_json::to_vec(&fence)?)
    }
    pub fn clear_session(&self) -> Result<()> {
        self.revoke_session()?;
        let _guard = self.lock("session.lock")?;
        self.clear_session_locked()
    }
    fn clear_session_locked(&self) -> Result<()> {
        self.clear_vault_cache()?;
        self.forget_durable_evidence();
        let pending = match self.pending_cleanup()? {
            Some(pending) => pending,
            None => {
                let pending = match self.envelope()? {
                    Some(record) => PendingCleanup {
                        mode: record.mode,
                        owner: record.owner,
                    },
                    None => match self.fence()?.cleanup {
                        Some(pending) => pending,
                        None => return Ok(()),
                    },
                };
                // A durable, non-secret marker blocks login/cache access even if
                // deletion fails or the process exits during logout.
                self.atomic_write("pending-cleanup.json", &serde_json::to_vec(&pending)?)?;
                pending
            }
        };
        self.remove("session.json")?;
        self.bytes.barrier()?;
        self.clear_owned_cache(&pending.owner)?;
        if pending.mode == StorageMode::OsKeyring {
            self.backend
                .delete(&self.account)
                .map_err(|_| Error::Locked)?;
        }
        if pending.mode == StorageMode::RestrictedLocalFile {
            self.remove("credential-key")?;
        }
        self.remove("pending-cleanup.json")?;
        self.bytes.barrier()?;
        let _fence = self.lock("revocation.lock")?;
        let mut fence = self.fence()?;
        if !fence.revoked {
            return Err(Error::Cancelled);
        }
        // Keep the revocation and retired identity, but do not require another
        // OS deletion after its successful durable cleanup was acknowledged.
        fence.cleanup = None;
        self.atomic_write("revocation.json", &serde_json::to_vec(&fence)?)?;
        Ok(())
    }
    /// Authenticated read of one logical cache value (sectioned layout
    /// assembled); the work lives in the core cache engine.
    pub fn read_cache(
        &self,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
    ) -> Result<Option<serde_json::Value>> {
        self.cache.read_cache(self, owner, cache_key, key)
    }
    /// Publish one logical value as a single encrypted record.
    pub fn write_cache(
        &self,
        owner: &str,
        cache_key: &str,
        key: &[u8; 32],
        value: &serde_json::Value,
    ) -> Result<()> {
        self.cache.write_cache(self, owner, cache_key, key, value)
    }
    /// The core cache engine over this directory (shared with `RuntimeStore`).
    pub(crate) fn cache_engine(&self) -> &Arc<CacheEngine<CacheBytes>> {
        &self.cache
    }
    fn require_current_cache_file(
        &self,
        name: &str,
        held: &File,
        expected: &FileIdentity,
    ) -> Result<()> {
        self.bytes.check_directory()?;
        let current = self.bytes.open_current(name)?;
        if FileByteStore::identity(held)? != *expected
            || FileByteStore::identity(&current)? != *expected
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    #[cfg(test)]
    pub(crate) fn cache_serializations_for_test(&self) -> usize {
        self.cache.encode_count()
    }
    /// (cache record reads, cache record writes, session.json writes, revocation.json writes)
    #[cfg(test)]
    pub(crate) fn io_counts_for_test(&self) -> (usize, usize, usize, usize) {
        let load = |counter: &std::sync::atomic::AtomicUsize| counter.load(std::sync::atomic::Ordering::SeqCst);
        (
            load(&self.io_counts.cache_reads),
            load(&self.io_counts.cache_writes),
            load(&self.io_counts.session_writes),
            load(&self.io_counts.revocation_writes),
        )
    }
    fn fence(&self) -> Result<RevocationFence> {
        RevocationFence::load(&*self.bytes)
    }
    fn active_epoch(&self) -> Result<String> {
        self.fence()?.active_epoch()
    }
    fn require_epoch(&self, expected: &str) -> Result<()> {
        self.fence()?.require_epoch(expected)
    }
    fn pending_cleanup(&self) -> Result<Option<PendingCleanup>> {
        let bytes = self.read("pending-cleanup.json")?;
        if bytes.is_some() {
            self.clear_vault_cache()?;
        }
        bytes
            .map(|bytes| serde_json::from_slice(&bytes).map_err(Error::from))
            .transpose()
    }
    fn envelope(&self) -> Result<Option<Envelope>> {
        Ok(self.envelope_with_digest()?.map(|(record, _)| record))
    }
    /// The parsed envelope plus the SHA-256 of its exact current file bytes.
    fn envelope_with_digest(&self) -> Result<Option<(Envelope, [u8; 32])>> {
        let record = self.read("session.json").and_then(|bytes| {
            bytes
                .map(|bytes| {
                    serde_json::from_slice::<Envelope>(&bytes)
                        .map(|record| (record, Sha256::digest(&bytes).into()))
                        .map_err(Error::from)
                })
                .transpose()
        });
        match record {
            Ok(record) => {
                let binding = record
                    .as_ref()
                    .map(|(record, _)| record)
                    .filter(|record| {
                        record.version == 1
                            && record.mode == StorageMode::EncryptedVault
                            && !expired(record.expires_at)
                    })
                    .map(|record| self.vault_binding(record))
                    .transpose()?;
                let mut cached = self.vault_cache.lock().map_err(|_| Error::Io)?;
                if cached
                    .as_ref()
                    .is_some_and(|cached| Some(cached.binding.as_str()) != binding.as_deref())
                {
                    *cached = None;
                }
                Ok(record)
            }
            Err(error) => {
                self.clear_vault_cache()?;
                Err(error)
            }
        }
    }
    fn unwrap_key(&self, record: &Envelope, passphrase: Option<&str>) -> Result<Key> {
        match record.mode {
            StorageMode::RestrictedLocalFile => {
                if self.force_vault {
                    return Err(Error::Locked);
                }
                let bytes = Zeroizing::new(self.read("credential-key")?.ok_or(Error::Locked)?);
                if bytes.len() != 32 {
                    return Err(Error::Locked);
                }
                let mut key = Zeroizing::new([0; 32]);
                key.copy_from_slice(&bytes);
                Ok(key)
            }
            StorageMode::OsKeyring => {
                if self.force_vault {
                    return Err(Error::Locked);
                }
                let bytes = self.backend.get(&self.account).map_err(|_| Error::Locked)?;
                if bytes.len() != 32 {
                    return Err(Error::Locked);
                }
                let mut key = Zeroizing::new([0; 32]);
                key.copy_from_slice(&bytes);
                Ok(key)
            }
            StorageMode::EncryptedVault => {
                let passphrase = passphrase
                    .filter(|value| !value.is_empty())
                    .ok_or(Error::Locked)?;
                let binding = self.vault_binding(record)?;
                {
                    let cached = self.vault_cache.lock().map_err(|_| Error::Io)?;
                    if let Some(cached) = cached.as_ref().filter(|cached| cached.binding == binding)
                    {
                        passphrase_mac(&cached.verifier_key, &binding, passphrase)?
                            .verify_slice(cached.verifier.as_ref())
                            .map_err(|_| Error::Crypto)?;
                        return Ok(cached.key.clone());
                    }
                }
                let salt = STANDARD
                    .decode(record.salt.as_ref().ok_or(Error::Crypto)?)
                    .map_err(|_| Error::Crypto)?;
                self.derive_vault_key(Some(passphrase), &salt)
            }
        }
    }
    fn clear_vault_cache(&self) -> Result<()> {
        *self.vault_cache.lock().map_err(|_| Error::Io)? = None;
        Ok(())
    }
    fn vault_binding(&self, record: &Envelope) -> Result<String> {
        Ok(digest(&serde_json::to_vec(&(
            "argon2id-v19-m65536-t3-p1-aes256gcm",
            &self.account,
            record.version,
            record.mode,
            &record.salt,
            &record.owner,
            &record.context,
            record.expires_at,
        ))?))
    }
    fn remember_vault_key(
        &self,
        record: &Envelope,
        passphrase: Option<&str>,
        key: &Key,
    ) -> Result<()> {
        if record.mode != StorageMode::EncryptedVault {
            return self.clear_vault_cache();
        }
        if let Err(error) = record.validate() {
            self.clear_vault_cache()?;
            return Err(error);
        }
        let passphrase = passphrase
            .filter(|value| !value.is_empty())
            .ok_or(Error::Locked)?;
        let binding = self.vault_binding(record)?;
        let mut cached = self.vault_cache.lock().map_err(|_| Error::Io)?;
        if let Some(existing) = cached.as_ref().filter(|cached| cached.binding == binding) {
            passphrase_mac(&existing.verifier_key, &binding, passphrase)?
                .verify_slice(existing.verifier.as_ref())
                .map_err(|_| Error::Crypto)?;
            return Ok(());
        }
        let verifier_key = random_key();
        let mut bytes = passphrase_mac(&verifier_key, &binding, passphrase)?
            .finalize()
            .into_bytes();
        let mut verifier = Zeroizing::new([0; 32]);
        verifier.copy_from_slice(&bytes);
        bytes.as_mut_slice().zeroize();
        *cached = Some(UnlockedVault {
            key: key.clone(),
            verifier_key,
            verifier,
            binding,
            #[cfg(test)]
            erased: None,
        });
        Ok(())
    }
    fn derive_vault_key(&self, passphrase: Option<&str>, salt: &[u8]) -> Result<Key> {
        #[cfg(test)]
        self.vault_derivations
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        derive_vault_key(passphrase, salt)
    }
    fn new_vault_key(
        &self,
        passphrase: Option<&str>,
    ) -> Result<(StorageMode, Option<String>, Key)> {
        let mut salt = [0; 16];
        OsRng.fill_bytes(&mut salt);
        let key = self.derive_vault_key(passphrase, &salt)?;
        Ok((
            StorageMode::EncryptedVault,
            Some(STANDARD.encode(salt)),
            key,
        ))
    }
    fn read(&self, name: &str) -> Result<Option<Vec<u8>>> {
        let read = self.bytes.get(name)?;
        #[cfg(test)]
        if read.is_some() && name.starts_with("cache-") {
            self.io_counts.cache_reads.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        }
        Ok(read)
    }
    fn lock(&self, name: &str) -> Result<LockGuard> {
        Ok(self.bytes.lock(name)?)
    }
    // Caller holds revocation.lock across this check and the session publish.
    // Retain the first fsynced inode, check both descriptor identities and the
    // anchored current pathname, and read the exact bounded bytes. Optional
    // evidence failure falls back to the original durable second write.
    fn reuses_revocation_intent(
        &self,
        intent: &DurableRevocationIntent,
        bytes: &[u8],
    ) -> Result<bool> {
        if bytes != intent.bytes.as_slice() {
            return Ok(false);
        }
        self.require_current_cache_file("revocation.json", &intent.file, &intent.identity)?;
        let mut current = self.bytes.open_current("revocation.json")?;
        if FileByteStore::identity(&current)? != intent.identity {
            return Ok(false);
        }
        let mut actual = Vec::new();
        (&mut current).take(bytes.len() as u64 + 1).read_to_end(&mut actual)?;
        if actual != bytes || FileByteStore::identity(&current)? != intent.identity {
            return Ok(false);
        }
        self.require_current_cache_file("revocation.json", &intent.file, &intent.identity)?;
        Ok(true)
    }
    fn atomic_write(&self, name: &str, bytes: &[u8]) -> Result<()> {
        self.atomic_write_file(name, bytes).map(|_| ())
    }
    /// Return the actual fsynced/renamed descriptor, never a later reopened file.
    /// Ordinary writers discard it immediately; session intent retains evidence.
    fn atomic_write_file(&self, name: &str, bytes: &[u8]) -> Result<File> {
        self.atomic_write_file_with(name, bytes, true)
    }
    /// `sync_directory: false` is only for records a later, synced commit names.
    fn atomic_write_file_with(&self, name: &str, bytes: &[u8], sync_directory: bool) -> Result<File> {
        #[cfg(test)]
        if name.starts_with("cache-") {
            self.io_counts.cache_writes.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        } else if name == "revocation.json" {
            self.io_counts.revocation_writes.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        } else if name == "session.json" {
            self.io_counts.session_writes.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        }
        #[cfg(test)]
        {
            let mut state = self.session_intent_test.lock().unwrap();
            if name == "revocation.json" {
                state.revocation_writes += 1;
                if state.fail_revocation_at == Some(state.revocation_writes) {
                    return Err(Error::Io);
                }
            } else if name == "session.json" {
                state.session_writes += 1;
                if state.fail_session { return Err(Error::Io); }
            }
        }
        Ok(self.bytes.put_file_hooked(name, bytes, sync_directory, || {
            #[cfg(test)]
            {
                let state = self.session_intent_test.lock().unwrap();
                if name == "revocation.json"
                    && state.fail_after_revocation_rename_at == Some(state.revocation_writes)
                {
                    return Err(ByteStoreError::Io);
                }
            }
            Ok(())
        })?)
    }
    fn remove(&self, name: &str) -> Result<()> {
        Ok(self.bytes.delete(name)?)
    }
    fn clear_owned_cache(&self, owner: &str) -> Result<()> {
        for prefix in [format!("cache-{owner}-"), format!("private-{owner}-")] {
            for name in self.bytes.list(&prefix)? {
                if name.ends_with(".json") || name.ends_with(".json.lock") {
                    self.remove(&name)?;
                }
            }
        }
        self.bytes.barrier()?;
        Ok(())
    }
}
/// The session record decides who may use the cache: no pending logout
/// cleanup, a valid unexpired envelope and the matching owner. Called by the
/// core engine while it holds `session.lock`.
impl CacheAdmission for Store {
    fn admit(&self, owner: &str) -> Result<CacheContext> {
        if self.pending_cleanup()?.is_some() {
            return Err(Error::Authentication);
        }
        let envelope = self.envelope()?.ok_or(Error::Authentication)?;
        envelope.validate()?;
        if envelope.owner != owner_id(owner) {
            return Err(Error::Forbidden);
        }
        Ok(CacheContext {
            owner_hash: envelope.owner,
            context: envelope.context,
            expires_at: envelope.expires_at,
        })
    }
}
/// Per-operation hosts hold the runtime lock around every cache operation.
impl OperationScope for Store {
    fn enter(&self) -> Result<Option<LockGuard>> {
        if !self.per_operation_lock.load(std::sync::atomic::Ordering::SeqCst) {
            return Ok(None);
        }
        Ok(Some(self.bytes.lock_timeout("runtime.lock", std::time::Duration::from_secs(60))?))
    }
}
/// The byte store the core cache engine uses: this directory's records, with
/// test-only counters of cache record reads and publications.
pub struct CacheBytes {
    inner: Arc<FileByteStore>,
    #[cfg(test)]
    io: Arc<IoCounts>,
}
impl ByteStore for CacheBytes {
    type Version = FileIdentity;
    fn get(&self, name: &str) -> std::result::Result<Option<Vec<u8>>, ByteStoreError> {
        let read = self.inner.get(name)?;
        #[cfg(test)]
        if read.is_some() && name.starts_with("cache-") {
            self.io.cache_reads.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        }
        Ok(read)
    }
    fn version(&self, name: &str) -> std::result::Result<Option<FileIdentity>, ByteStoreError> {
        self.inner.version(name)
    }
    fn put(&self, name: &str, bytes: &[u8], durability: Durability) -> std::result::Result<(), ByteStoreError> {
        #[cfg(test)]
        if name.starts_with("cache-") {
            self.io.cache_writes.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        }
        self.inner.put(name, bytes, durability)
    }
    fn delete(&self, name: &str) -> std::result::Result<(), ByteStoreError> {
        self.inner.delete(name)
    }
    fn list(&self, prefix: &str) -> std::result::Result<Vec<String>, ByteStoreError> {
        self.inner.list(prefix)
    }
    fn barrier(&self) -> std::result::Result<(), ByteStoreError> {
        self.inner.barrier()
    }
    fn sync(&self, name: &str) -> std::result::Result<(), ByteStoreError> {
        self.inner.sync(name)
    }
    fn lock(&self, scope: &str) -> std::result::Result<LockGuard, ByteStoreError> {
        self.inner.lock(scope)
    }
}
fn session_context(session: &Session) -> Result<String> {
    let identity = Zeroizing::new(serde_json::to_vec(&(
        &session.api_url,
        &session.session_id,
        &session.hashed_email,
        session.created_at,
    ))?);
    Ok(digest(&identity))
}
fn session_digest(session: &Session) -> Result<[u8; 32]> {
    let encoded = Zeroizing::new(serde_json::to_vec(session)?);
    Ok(Sha256::digest(encoded.as_slice()).into())
}
fn expired(deadline: Option<u64>) -> bool {
    deadline.is_some_and(|deadline| {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(true, |now| now.as_millis() >= u128::from(deadline))
    })
}
fn random_key() -> Key {
    let mut key = Zeroizing::new([0; 32]);
    OsRng.fill_bytes(key.as_mut());
    key
}
fn passphrase_mac(key: &[u8; 32], binding: &str, passphrase: &str) -> Result<Hmac<Sha256>> {
    let mut mac = <Hmac<Sha256> as Mac>::new_from_slice(key).map_err(|_| Error::Crypto)?;
    mac.update(b"openmates-rust-vault-cache-v1\0");
    mac.update(binding.as_bytes());
    mac.update(passphrase.as_bytes());
    Ok(mac)
}
fn derive_vault_key(passphrase: Option<&str>, salt: &[u8]) -> Result<Key> {
    let passphrase = passphrase
        .filter(|value| !value.is_empty())
        .ok_or(Error::Locked)?;
    if salt.len() != 16 {
        return Err(Error::Crypto);
    }
    let params = Params::new(64 * 1024, 3, 1, Some(32)).map_err(|_| Error::Crypto)?;
    let mut key = Zeroizing::new([0; 32]);
    let mut memory = Zeroizing::new(vec![Block::default(); params.block_count()]);
    Argon2::new(Algorithm::Argon2id, Version::V0x13, params)
        .hash_password_into_with_memory(passphrase.as_bytes(), salt, key.as_mut(), &mut memory[..])
        .map_err(|_| Error::Crypto)?;
    Ok(key)
}
#[cfg(test)]
mod vault_cache_tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::sync::atomic::{AtomicBool, Ordering};

    #[test]
    fn per_operation_runtime_lock_lets_a_second_client_open_between_operations() {
        let (directory, host, _) = fixture();
        let path = directory.path().to_path_buf();
        assert!(Store::new(path.clone()).is_err(), "lifetime lock excludes a second client");
        host.scope_runtime_lock_to_operations().unwrap();
        let other = Store::new(path.clone()).expect("a one-shot client opens beside the scoped host");
        drop(other);
        let mut ran = false;
        host.with_runtime_lock(|| {
            ran = true;
            assert!(Store::new(path.clone()).is_err(), "the lock is held during the operation");
            Ok(())
        })
        .unwrap();
        assert!(ran);
        Store::new(path).expect("the lock is released after the operation");
    }

    const HOST_PASSPHRASE: &str = "fixture vault passphrase";
    fn with_cookie(session: &Session, cookie: &str) -> Session {
        let mut next = session.clone();
        next.cookies.insert("session".into(), cookie.into());
        next
    }

    #[test]
    fn host_adopts_a_session_rotated_by_another_process_instead_of_overwriting_it() {
        let (directory, host, session) = fixture();
        host.save_session(&session, Some(HOST_PASSPHRASE)).unwrap();
        host.scope_runtime_lock_to_operations().unwrap();
        // A one-shot command rotates the cookie and stores it beside the host.
        let rotated = with_cookie(&session, "rotated-cookie");
        {
            let other = Store::encrypted_vault(directory.path().to_path_buf()).unwrap();
            other.save_session(&rotated, Some(HOST_PASSPHRASE)).unwrap();
        }
        assert!(
            host.superseded_session(Some(HOST_PASSPHRASE)).unwrap().is_some(),
            "the host sees the newer stored session",
        );
        // Re-arm: the lookup above adopted it, so do it again with a fresh rotation.
        let newest = with_cookie(&session, "newest-cookie");
        {
            let other = Store::encrypted_vault(directory.path().to_path_buf()).unwrap();
            other.save_session(&newest, Some(HOST_PASSPHRASE)).unwrap();
        }
        let stale = with_cookie(&session, "stale-host-cookie");
        match host.save_session_unless_superseded(&stale, Some(HOST_PASSPHRASE)).unwrap() {
            SessionSave::Superseded(stored) => {
                assert_eq!(stored.cookies["session"], "newest-cookie");
            }
            SessionSave::Saved(_) => panic!("the host overwrote a newer stored session"),
        }
        let on_disk = host.load_session(Some(HOST_PASSPHRASE)).unwrap().unwrap();
        assert_eq!(on_disk.cookies["session"], "newest-cookie");
        assert!(
            host.superseded_session(Some(HOST_PASSPHRASE)).unwrap().is_none(),
            "after adopting, nothing is superseded any more",
        );
    }

    #[test]
    fn host_refresh_saves_when_the_stored_session_is_its_own() {
        let (_directory, host, session) = fixture();
        host.save_session(&session, Some(HOST_PASSPHRASE)).unwrap();
        host.scope_runtime_lock_to_operations().unwrap();
        // Not holding the runtime lock: must neither deadlock nor report a newer session.
        assert!(host.superseded_session(Some(HOST_PASSPHRASE)).unwrap().is_none());
        let refreshed = with_cookie(&session, "host-refreshed");
        let saved = host
            .with_runtime_lock(|| host.save_session_unless_superseded(&refreshed, Some(HOST_PASSPHRASE)))
            .unwrap();
        assert!(matches!(saved, SessionSave::Saved(true)));
        let on_disk = host.load_session(Some(HOST_PASSPHRASE)).unwrap().unwrap();
        assert_eq!(on_disk.cookies["session"], "host-refreshed");
        // And again directly, outside the lock, with a second refresh.
        let again = with_cookie(&session, "host-refreshed-twice");
        let saved = host.save_session_unless_superseded(&again, Some(HOST_PASSPHRASE)).unwrap();
        assert!(matches!(saved, SessionSave::Saved(true)));
    }

    #[test]
    fn lifetime_locked_store_never_reports_a_superseded_session() {
        let (_directory, store, session) = fixture();
        store.save_session(&session, Some(HOST_PASSPHRASE)).unwrap();
        assert!(store.superseded_session(Some(HOST_PASSPHRASE)).unwrap().is_none());
        let next = with_cookie(&session, "one-shot-refresh");
        let saved = store.save_session_unless_superseded(&next, Some(HOST_PASSPHRASE)).unwrap();
        assert!(matches!(saved, SessionSave::Saved(true)));
    }

    fn fixture() -> (tempfile::TempDir, Store, Session) {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().unwrap();
        let store = Store::encrypted_vault(directory.path().to_path_buf()).unwrap();
        let session = Session {
            api_url: "https://api.example.invalid".into(),
            session_id: "synthetic-session".into(),
            cookies: BTreeMap::from([("session".into(), "synthetic-cookie".into())]),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        (directory, store, session)
    }
    fn observe_erasure(store: &Store) -> Arc<AtomicBool> {
        let erased = Arc::new(AtomicBool::new(false));
        store.vault_cache.lock().unwrap().as_mut().unwrap().erased = Some(erased.clone());
        erased
    }
    #[test]
    fn damaged_session_cannot_prevent_durable_logout_or_cached_key_erasure() {
        let (_directory, store, session) = fixture();
        store
            .save_session(&session, Some("fixture vault passphrase"))
            .unwrap();
        let erased = observe_erasure(&store);
        store.atomic_write("session.json", b"{damaged").unwrap();
        assert!(store.revoke_session().is_err());
        assert!(store.fence().unwrap().revoked);
        assert!(erased.load(Ordering::SeqCst));
        assert!(store.load_session(None).unwrap().is_none());
        assert!(store.active_epoch().is_err());
    }
    #[test]
    fn fresh_pair_admission_is_idempotent_through_unlock_and_cookie_team_changes() {
        let (_directory, store, mut session) = fixture();
        store.begin_session(&session).unwrap();
        let admitted = store.read("revocation.json").unwrap().unwrap();
        store.begin_session(&session).unwrap();
        assert_eq!(store.read("revocation.json").unwrap().unwrap(), admitted);
        assert!(matches!(
            store.save_session(&session, None),
            Err(Error::Locked)
        ));
        let pending = store.read("revocation.json").unwrap().unwrap();
        store.begin_session(&session).unwrap();
        assert_eq!(store.read("revocation.json").unwrap().unwrap(), pending);
        store
            .save_session(&session, Some("fixture vault passphrase"))
            .unwrap();
        let context = session_context(&session).unwrap();
        session
            .cookies
            .insert("session".into(), "rotated fixture cookie".into());
        session.active_team_id = Some("fixture-team".into());
        assert_eq!(session_context(&session).unwrap(), context);
        store
            .save_session(&session, Some("fixture vault passphrase"))
            .unwrap();
        store.begin_session(&session).unwrap();
        let loaded = store
            .load_session(Some("fixture vault passphrase"))
            .unwrap()
            .unwrap();
        assert_eq!(loaded.active_team_id, session.active_team_id);
        assert_eq!(loaded.cookies, session.cookies);
        store.clear_session().unwrap();
        assert!(matches!(
            store.begin_session(&session),
            Err(Error::Authentication)
        ));
        session.session_id = "newly-authenticated-pair".into();
        store.begin_session(&session).unwrap();
        store
            .save_session(&session, Some("fixture vault passphrase"))
            .unwrap();
    }
    #[test]
    fn revocation_fence_is_private_and_malformed_or_symlinked_fences_fail_closed() {
        let (directory, store, session) = fixture();
        store
            .save_session(&session, Some("fixture vault passphrase"))
            .unwrap();
        let ciphertext = store.read("session.json").unwrap().unwrap();
        store.revoke_session().unwrap();
        assert!(store.load_session(None).unwrap().is_none());
        assert!(store.storage_mode().unwrap().is_none());
        assert_eq!(store.read("session.json").unwrap().unwrap(), ciphertext);
        #[cfg(unix)]
        {
            use std::os::unix::fs::{PermissionsExt, symlink};
            let marker = directory.path().join("revocation.json");
            assert_eq!(
                std::fs::metadata(&marker).unwrap().permissions().mode() & 0o777,
                0o600
            );
            std::fs::remove_file(&marker).unwrap();
            symlink(directory.path().join("session.json"), &marker).unwrap();
            assert!(store.load_session(None).is_err());
            std::fs::remove_file(&marker).unwrap();
        }
        store.atomic_write("revocation.json", b"{}").unwrap();
        assert!(store.load_session(None).is_err());
        assert!(store.begin_session(&session).is_err());
    }
    #[test]
    fn warm_vault_reuses_verified_key_but_rejects_a_different_passphrase() {
        let (_directory, store, mut session) = fixture();
        store
            .save_session(&session, Some("local passphrase"))
            .unwrap();
        assert_eq!(store.vault_derivations.load(Ordering::SeqCst), 1);
        store
            .load_session(Some("local passphrase"))
            .unwrap()
            .unwrap();
        session
            .cookies
            .insert("session".into(), "rotated-cookie".into());
        store
            .save_session(&session, Some("local passphrase"))
            .unwrap();
        assert_eq!(
            store
                .load_session(Some("local passphrase"))
                .unwrap()
                .unwrap()
                .cookies["session"],
            "rotated-cookie"
        );
        let original = store.read("session.json").unwrap().unwrap();
        assert!(matches!(
            store.load_session(Some("different passphrase")),
            Err(Error::Crypto)
        ));
        assert!(matches!(
            store.save_session(&session, Some("different passphrase")),
            Err(Error::Crypto)
        ));
        assert_eq!(store.read("session.json").unwrap().unwrap(), original);
        // Includes refresh writes with different ciphertext; no repeated Argon2.
        assert_eq!(store.vault_derivations.load(Ordering::SeqCst), 1);
        let erased = observe_erasure(&store);
        session.paired_session_expires_at = Some(1);
        assert!(matches!(
            store.save_session(&session, Some("local passphrase")),
            Err(Error::Expired)
        ));
        assert!(erased.load(Ordering::SeqCst));
        assert!(store.vault_cache.lock().unwrap().is_none());
    }
    #[test]
    fn altered_wrapping_metadata_invalidates_and_failed_auth_never_caches() {
        let (_directory, store, session) = fixture();
        store
            .save_session(&session, Some("local passphrase"))
            .unwrap();
        let original = store.read("session.json").unwrap().unwrap();
        let erased = observe_erasure(&store);
        let mut record: serde_json::Value = serde_json::from_slice(&original).unwrap();
        record["salt"] = serde_json::json!(STANDARD.encode([99; 16]));
        store
            .atomic_write("session.json", &serde_json::to_vec(&record).unwrap())
            .unwrap();
        assert!(matches!(
            store.load_session(Some("local passphrase")),
            Err(Error::Crypto)
        ));
        assert!(erased.load(Ordering::SeqCst));
        assert!(store.vault_cache.lock().unwrap().is_none());
        assert_eq!(store.vault_derivations.load(Ordering::SeqCst), 2);
        store.atomic_write("session.json", &original).unwrap();
        store
            .load_session(Some("local passphrase"))
            .unwrap()
            .unwrap();
        let erased = observe_erasure(&store);
        let mut record: serde_json::Value = serde_json::from_slice(&original).unwrap();
        record["mode"] = serde_json::json!("os_keyring");
        record["salt"] = serde_json::Value::Null;
        store
            .atomic_write("session.json", &serde_json::to_vec(&record).unwrap())
            .unwrap();
        assert!(matches!(
            store.load_session(Some("local passphrase")),
            Err(Error::Locked)
        ));
        assert!(erased.load(Ordering::SeqCst));
        assert!(store.vault_cache.lock().unwrap().is_none());
        assert_eq!(store.vault_derivations.load(Ordering::SeqCst), 3);
    }
    #[test]
    fn tombstone_logout_and_store_drop_erase_cached_credential_material() {
        let (_directory, store, mut session) = fixture();
        store
            .save_session(&session, Some("local passphrase"))
            .unwrap();
        let erased = observe_erasure(&store);
        let pending = PendingCleanup {
            mode: StorageMode::EncryptedVault,
            owner: owner_id(&session.hashed_email),
        };
        store
            .atomic_write(
                "pending-cleanup.json",
                &serde_json::to_vec(&pending).unwrap(),
            )
            .unwrap();
        assert!(
            store
                .load_session(Some("local passphrase"))
                .unwrap()
                .is_none()
        );
        assert!(erased.load(Ordering::SeqCst));
        assert!(store.vault_cache.lock().unwrap().is_none());
        store.clear_session().unwrap();
        assert!(matches!(
            store.begin_session(&session),
            Err(Error::Authentication)
        ));
        session.session_id = "fresh-session-two".into();
        store.begin_session(&session).unwrap();
        store
            .save_session(&session, Some("local passphrase"))
            .unwrap();
        let erased = observe_erasure(&store);
        store.clear_session().unwrap();
        assert!(erased.load(Ordering::SeqCst));
        session.session_id = "fresh-session-three".into();
        store.begin_session(&session).unwrap();
        store
            .save_session(&session, Some("local passphrase"))
            .unwrap();
        let erased = observe_erasure(&store);
        drop(store);
        assert!(erased.load(Ordering::SeqCst));
    }
}

#[cfg(test)]
mod cache_record_tests {
    use super::*;
    use serde_json::json;
    use std::collections::BTreeMap;

    struct NoKeyring;
    impl CredentialBackend for NoKeyring {
        fn get(&self, _: &str) -> std::result::Result<Zeroizing<Vec<u8>>, KeyringFailure> {
            Err(KeyringFailure::Missing)
        }
        fn set(&self, _: &str, _: &[u8]) -> std::result::Result<(), KeyringFailure> {
            Err(KeyringFailure::Unavailable)
        }
        fn delete(&self, _: &str) -> std::result::Result<(), KeyringFailure> {
            Ok(())
        }
    }
    pub(super) fn fixture() -> (tempfile::TempDir, Store, Session) {
        let mut builder = tempfile::Builder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            builder.permissions(std::fs::Permissions::from_mode(0o700));
        }
        let directory = builder.tempdir().unwrap();
        let store =
            Store::with_backend(directory.path().to_path_buf(), Arc::new(NoKeyring)).unwrap();
        let session = Session {
            api_url: "https://api.example.invalid".into(),
            session_id: "synthetic-session".into(),
            cookies: BTreeMap::new(),
            ws_token: None,
            master_key: Zeroizing::new([7; 32]),
            hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(),
            email_encryption_key: None,
            created_at: 1,
            paired_session_expires_at: None,
            active_team_id: None,
        };
        store.save_session(&session, None).unwrap();
        (directory, store, session)
    }
    fn snapshot(revision: u64) -> serde_json::Value {
        json!({"chats":{"synthetic":{"id":"synthetic","encrypted_title":"opaque"}},
               "wrappers":[],"history":{},"embeds":{},"embed_keys":[],"revision":revision})
    }
    fn write(store: &Store, session: &Session, value: serde_json::Value) {
        store
            .write_cache(&session.hashed_email, "sync-personal", &session.master_key, &value)
            .unwrap();
    }
    fn serializations(store: &Store) -> usize {
        store.cache_serializations_for_test()
    }

    // Without the write-skip memo every write encrypts afresh: equal values
    // give new ciphertext (new nonce) that still opens to the same value.
    #[test]
    fn identical_snapshot_is_rewritten_and_still_reads_back() {
        let (_dir, store, session) = fixture();
        write(&store, &session, snapshot(1));
        let name = cache_name(&session.hashed_email, "sync-personal");
        let original = store.read(&name).unwrap().unwrap();
        write(&store, &session, snapshot(1));
        assert_ne!(store.read(&name).unwrap().unwrap(), original);
        assert_eq!(serializations(&store), 2);
        assert_eq!(
            store
                .read_cache(&session.hashed_email, "sync-personal", &session.master_key)
                .unwrap(),
            Some(snapshot(1))
        );
    }
    #[test]
    fn owner_context_and_expiry_are_enforced_on_write() {
        let (_dir, store, mut session) = fixture();
        write(&store, &session, snapshot(1));
        assert!(matches!(
            store.write_cache("another-owner", "sync-personal", &session.master_key, &snapshot(1)),
            Err(Error::Forbidden)
        ));
        session.session_id = "fresh-authenticated-context".into();
        store.save_session(&session, None).unwrap();
        assert!(matches!(
            store.read_cache(&session.hashed_email, "sync-personal", &session.master_key),
            Err(Error::Crypto)
        ), "a record written for the previous context no longer opens");
        write(&store, &session, snapshot(1));
        let mut expired = store.envelope().unwrap().unwrap();
        expired.expires_at = Some(1);
        store
            .atomic_write("session.json", &serde_json::to_vec(&expired).unwrap())
            .unwrap();
        assert!(matches!(
            store.write_cache(&session.hashed_email, "sync-personal", &session.master_key, &snapshot(1)),
            Err(Error::Expired)
        ));
    }
    #[test]
    fn logout_refuses_stale_publication() {
        let (_dir, store, session) = fixture();
        write(&store, &session, snapshot(1));
        store.revoke_session().unwrap();
        assert!(matches!(
            store.write_cache(&session.hashed_email, "sync-personal", &session.master_key, &snapshot(1)),
            Err(Error::Authentication) | Err(Error::Cancelled)
        ));
        assert_eq!(serializations(&store), 1);
    }
    #[test]
    fn authenticated_read_never_changes_ciphertext_or_freshness_metadata() {
        let (directory, writer, session) = fixture();
        let mut value = snapshot(1);
        value["chat_list_freshness"] = json!({"opaque":"expired-or-untrusted-source-metadata"});
        write(&writer, &session, value.clone());
        let reader = Store::with_backend(directory.path().to_path_buf(), Arc::new(NoKeyring)).unwrap();
        let name = cache_name(&session.hashed_email, "sync-personal");
        let bytes = reader.read(&name).unwrap().unwrap();
        let returned = reader.read_cache(&session.hashed_email, "sync-personal", &session.master_key).unwrap().unwrap();
        assert_eq!(returned, value);
        assert_eq!(reader.read(&name).unwrap().unwrap(), bytes);
    }
}

#[cfg(test)]
mod ordinary_cache_roundtrip_capacity_tests {
    use super::*;
    fn largest_plaintext() -> usize {
        let (mut low, mut high) = (0, MAX_LOCAL_RECORD_BYTES);
        while low < high {
            let middle = low + (high - low + 1) / 2;
            if cache_record_encoded_len(middle).unwrap() <= MAX_LOCAL_RECORD_BYTES { low = middle; }
            else { high = middle - 1; }
        }
        low
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn ordinary_writer_largest_record_roundtrips_through_actual_reader() {
        let (_directory, store, session) = super::cache_record_tests::fixture();
        let mut restored = crate::client::Client::new(&session.api_url, Some(session.clone())).unwrap();
        // Ordinary restore deliberately drops the initial unsynced selector hint;
        // it cannot import the live read authority used by the owned cache path.
        // Seed the capacity case from that actual ordinary-restore state so the
        // full equality below still proves every cached data row survives.
        let initial = restored.ciphertext_snapshot();
        restored.restore_ciphertext_snapshot(&initial).unwrap();
        let mut value = restored.ciphertext_snapshot();
        value["chats"]["synthetic-large"] = serde_json::json!({"id":"synthetic-large","encrypted_title":""});
        let base = serde_json::to_vec(&value).unwrap().len();
        value["chats"]["synthetic-large"]["encrypted_title"] = serde_json::json!("x".repeat(largest_plaintext() - base));
        store.write_cache(&session.hashed_email, "sync-personal", &session.master_key, &value).unwrap();
        let record = store.read(&cache_name(&session.hashed_email, "sync-personal")).unwrap().unwrap();
        assert_eq!(record.len(), cache_record_encoded_len(largest_plaintext()).unwrap());
        assert!(record.len() <= MAX_LOCAL_RECORD_BYTES);
        let loaded = store.read_cache(&session.hashed_email, "sync-personal", &session.master_key).unwrap().unwrap();
        assert_eq!(loaded, value);
        restored.restore_ciphertext_snapshot(&loaded).unwrap();
        assert_eq!(restored.ciphertext_snapshot(), value, "actual Client restore retains every cached row");
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn oversized_ordinary_and_owned_writes_preserve_session_file_and_cache() {
        let (directory, store, session) = super::cache_record_tests::fixture();
        let old = serde_json::json!({"chats":{},"history":{},"wrappers":[],"embeds":{},"embed_keys":[]});
        store.write_cache(&session.hashed_email, "sync-personal", &session.master_key, &old).unwrap();
        let name = cache_name(&session.hashed_email, "sync-personal");
        let cache = store.read(&name).unwrap().unwrap();
        let credentials = std::fs::read(directory.path().join("session.json")).unwrap();
        let serializations = store.cache_serializations_for_test();
        let over = serde_json::Value::String("x".repeat(largest_plaintext() - 1));
        assert!(matches!(encode_bounded_cache(&over), Err(Error::Invalid(_))));
        assert!(store.write_cache(&session.hashed_email, "sync-personal", &session.master_key, &over).is_err());
        assert!(store.write_cache(&session.hashed_email, "sync-personal", &session.master_key, &over).is_err());
        assert_eq!(store.cache_serializations_for_test(), serializations, "refuse before encryption/publication without a completed serialization");
        assert_eq!(store.read(&name).unwrap().unwrap(), cache);
        assert_eq!(std::fs::read(directory.path().join("session.json")).unwrap(), credentials);
        assert_eq!(store.read_cache(&session.hashed_email, "sync-personal", &session.master_key).unwrap(), Some(old));
        assert!(!std::fs::read_dir(directory.path()).unwrap().any(|entry| entry.unwrap().file_name().to_string_lossy().starts_with(".tmp-")));
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn streaming_capacity_counts_the_actual_json_escapes_without_encryption() {
        for value in [serde_json::json!({"opaque":"\u{1}\n雪😀\"\\"}), serde_json::json!([1, true, null])] {
            encode_bounded_cache(&value).unwrap();
            assert!(cache_record_encoded_len(serde_json::to_vec(&value).unwrap().len()).unwrap() <= MAX_LOCAL_RECORD_BYTES);
        }
        assert!(encode_bounded_cache(&serde_json::Value::String("\u{1}".repeat(MAX_LOCAL_RECORD_BYTES / 6))).is_err());
    }
}

#[cfg(all(test, unix))]
mod session_intent_once_tests {
    use super::*;
    use std::{collections::BTreeMap, os::unix::fs::PermissionsExt,
        sync::atomic::{AtomicBool, AtomicUsize, Ordering}};

    #[derive(Default)]
    struct Keyring {
        key: Mutex<Option<Zeroizing<Vec<u8>>>>,
        unavailable: AtomicBool,
        gets: AtomicUsize,
        sets: AtomicUsize,
        get_action: Mutex<Option<Box<dyn FnOnce() + Send>>>,
    }
    impl CredentialBackend for Keyring {
        fn get(&self, _: &str) -> std::result::Result<Zeroizing<Vec<u8>>, KeyringFailure> {
            self.gets.fetch_add(1, Ordering::SeqCst);
            let action = self.get_action.lock().unwrap().take();
            if let Some(action) = action { action(); }
            if self.unavailable.load(Ordering::SeqCst) { return Err(KeyringFailure::Unavailable); }
            self.key.lock().unwrap().clone().ok_or(KeyringFailure::Missing)
        }
        fn set(&self, _: &str, key: &[u8]) -> std::result::Result<(), KeyringFailure> {
            self.sets.fetch_add(1, Ordering::SeqCst);
            if self.unavailable.load(Ordering::SeqCst) { return Err(KeyringFailure::Unavailable); }
            *self.key.lock().unwrap() = Some(Zeroizing::new(key.to_vec()));
            Ok(())
        }
        fn delete(&self, _: &str) -> std::result::Result<(), KeyringFailure> {
            *self.key.lock().unwrap() = None;
            Ok(())
        }
    }
    fn fixture() -> (tempfile::TempDir, Store, Arc<Keyring>, Session) {
        let directory = tempfile::Builder::new().permissions(std::fs::Permissions::from_mode(0o700)).tempdir().unwrap();
        let backend = Arc::new(Keyring::default());
        let store = Store::with_backend(directory.path().to_path_buf(), backend.clone()).unwrap();
        let session = Session {
            api_url: "https://api.example.invalid".into(), session_id: "synthetic-session".into(),
            cookies: BTreeMap::from([("session".into(), "synthetic-cookie".into())]), ws_token: None,
            master_key: Zeroizing::new([7; 32]), hashed_email: "synthetic-owner".into(),
            user_email_salt: String::new(), email_encryption_key: None, created_at: 1,
            paired_session_expires_at: None, active_team_id: None,
        };
        (directory, store, backend, session)
    }
    fn reset(store: &Store) {
        *store.session_intent_test.lock().unwrap() = SessionIntentTestState::default();
    }
    fn counts(store: &Store) -> (usize, usize) {
        let state = store.session_intent_test.lock().unwrap();
        (state.revocation_writes, state.session_writes)
    }
    fn before_final(store: &Store, action: impl FnOnce(&Store) + Send + 'static) {
        store.session_intent_test.lock().unwrap().before_final = Some(Box::new(action));
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn existing_session_saves_one_intent_but_always_fresh_envelope_and_keyring_read() {
        let (_directory, store, backend, mut session) = fixture();
        store.save_session(&session, None).unwrap();
        assert_eq!(counts(&store), (1, 1));
        let previous = store.read("session.json").unwrap().unwrap();
        let intent = store.read("revocation.json").unwrap().unwrap();
        reset(&store);
        session.cookies.insert("session".into(), "synthetic-rotated".into());
        store.save_session(&session, None).unwrap();
        assert_eq!(counts(&store), (1, 1));
        assert_eq!(backend.gets.load(Ordering::SeqCst), 1);
        assert_ne!(store.read("session.json").unwrap().unwrap(), previous);
        assert_eq!(store.read("revocation.json").unwrap().unwrap(), intent);
        assert_eq!(store.load_session(None).unwrap().unwrap().cookies, session.cookies);
        let rotated = store.read("session.json").unwrap().unwrap();
        reset(&store);
        store.save_session(&session, None).unwrap();
        assert_eq!(counts(&store), (1, 1));
        assert_ne!(store.read("session.json").unwrap().unwrap(), rotated, "unchanged credentials still require a new envelope");
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn first_intent_failure_prevents_any_keyring_or_session_publication() {
        let (_directory, store, backend, session) = fixture();
        store.session_intent_test.lock().unwrap().fail_revocation_at = Some(1);
        assert!(matches!(store.save_session(&session, None), Err(Error::Io)));
        assert_eq!(counts(&store), (1, 0));
        assert_eq!(backend.sets.load(Ordering::SeqCst), 0);
        assert_eq!(backend.gets.load(Ordering::SeqCst), 0);
        assert!(store.read("session.json").unwrap().is_none());
        assert!(store.read("revocation.json").unwrap().is_none());
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn first_intent_rename_without_successful_directory_sync_grants_no_receipt() {
        let (_directory, store, backend, session) = fixture();
        store.session_intent_test.lock().unwrap().fail_after_revocation_rename_at = Some(1);
        assert!(matches!(store.save_session(&session, None), Err(Error::Io)));
        assert_eq!(counts(&store), (1, 0));
        assert_eq!(backend.sets.load(Ordering::SeqCst), 0);
        assert_eq!(backend.gets.load(Ordering::SeqCst), 0);
        assert!(store.read("session.json").unwrap().is_none());
        assert!(store.read("revocation.json").unwrap().is_some(), "renamed bytes are not a successful durable-write ACK");
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn failed_first_intent_on_existing_save_preserves_session_and_skips_keyring() {
        let (_directory, store, backend, session) = fixture();
        store.save_session(&session, None).unwrap();
        let previous = store.read("session.json").unwrap().unwrap();
        let intent = store.read("revocation.json").unwrap().unwrap();
        reset(&store);
        store.session_intent_test.lock().unwrap().fail_revocation_at = Some(1);
        assert!(matches!(store.save_session(&session, None), Err(Error::Io)));
        assert_eq!(counts(&store), (1, 0));
        assert_eq!(backend.gets.load(Ordering::SeqCst), 0);
        assert_eq!(store.read("session.json").unwrap().unwrap(), previous);
        assert_eq!(store.read("revocation.json").unwrap().unwrap(), intent);
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn changed_fallback_mode_requires_second_intent_and_cannot_publish_if_it_fails() {
        for fail_second in [false, true] {
            let (_directory, store, backend, session) = fixture();
            backend.unavailable.store(true, Ordering::SeqCst);
            if fail_second { store.session_intent_test.lock().unwrap().fail_revocation_at = Some(2); }
            let saved = store.save_session(&session, None);
            assert_eq!(counts(&store), (2, usize::from(!fail_second)));
            assert_eq!(backend.sets.load(Ordering::SeqCst), 1);
            if fail_second {
                assert!(matches!(saved, Err(Error::Io)));
                assert!(store.read("session.json").unwrap().is_none());
            } else {
                saved.unwrap();
                assert_eq!(store.fence().unwrap().cleanup.unwrap().mode, StorageMode::RestrictedLocalFile);
                assert_eq!(store.storage_mode().unwrap(), Some(StorageMode::RestrictedLocalFile));
                assert_eq!(store.load_session(None).unwrap().unwrap().session_id, session.session_id);
            }
        }
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn vault_fallback_changes_intent_and_repeated_save_keeps_kdf_and_wrong_password_policy() {
        let (_directory, store, backend, session) = fixture();
        backend.unavailable.store(true, Ordering::SeqCst);
        store.save_session(&session, Some("synthetic-vault-passphrase")).unwrap();
        assert_eq!(counts(&store), (2, 1));
        assert_eq!(store.fence().unwrap().cleanup.unwrap().mode, StorageMode::EncryptedVault);
        let derivations = store.vault_derivations.load(Ordering::SeqCst);
        let previous = store.read("session.json").unwrap().unwrap();
        reset(&store);
        store.save_session(&session, Some("synthetic-vault-passphrase")).unwrap();
        assert_eq!(counts(&store), (1, 1));
        assert_eq!(store.vault_derivations.load(Ordering::SeqCst), derivations);
        assert_ne!(store.read("session.json").unwrap().unwrap(), previous);
        let current = store.read("session.json").unwrap().unwrap();
        reset(&store);
        assert!(matches!(store.save_session(&session, Some("wrong-synthetic-passphrase")), Err(Error::Crypto)));
        assert_eq!(counts(&store), (1, 0));
        assert_eq!(store.read("session.json").unwrap().unwrap(), current);
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn independently_replaced_same_bytes_are_not_a_durable_descriptor_receipt() {
        let (directory, store, backend, session) = fixture();
        store.save_session(&session, None).unwrap();
        reset(&store);
        let peer = Store::with_backend(directory.path().to_path_buf(), backend).unwrap();
        before_final(&store, move |_| {
            let _lock = peer.lock("revocation.lock").unwrap();
            let bytes = peer.read("revocation.json").unwrap().unwrap();
            peer.atomic_write("revocation.json", &bytes).unwrap();
        });
        store.save_session(&session, None).unwrap();
        assert_eq!(counts(&store), (2, 1), "equal bytes on a replacement inode must fall back");
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn independently_changed_same_epoch_intent_requires_original_final_write() {
        let (directory, store, backend, session) = fixture();
        store.save_session(&session, None).unwrap();
        reset(&store);
        let expected = store.read("revocation.json").unwrap().unwrap();
        let peer = Store::with_backend(directory.path().to_path_buf(), backend).unwrap();
        before_final(&store, move |_| {
            let _lock = peer.lock("revocation.lock").unwrap();
            let mut fence = peer.fence().unwrap();
            fence.cleanup.as_mut().unwrap().owner = "synthetic-different-intent".into();
            peer.atomic_write("revocation.json", &serde_json::to_vec(&fence).unwrap()).unwrap();
        });
        store.save_session(&session, None).unwrap();
        assert_eq!(counts(&store), (2, 1));
        assert_eq!(store.read("revocation.json").unwrap().unwrap(), expected);
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn in_place_same_epoch_intent_tamper_cannot_reuse_a_first_write_receipt() {
        let (directory, store, _backend, session) = fixture();
        store.save_session(&session, None).unwrap();
        reset(&store);
        let expected = store.read("revocation.json").unwrap().unwrap();
        let path = directory.path().join("revocation.json");
        before_final(&store, move |_| {
            let bytes = std::fs::read(&path).unwrap();
            let mut fence: RevocationFence = serde_json::from_slice(&bytes).unwrap();
            fence.cleanup.as_mut().unwrap().owner = "synthetic-in-place".into();
            std::fs::write(&path, serde_json::to_vec(&fence).unwrap()).unwrap();
        });
        store.save_session(&session, None).unwrap();
        assert_eq!(counts(&store), (2, 1));
        assert_eq!(store.read("revocation.json").unwrap().unwrap(), expected);
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn independent_logout_after_first_intent_prevents_session_resurrection() {
        let (directory, store, backend, session) = fixture();
        store.save_session(&session, None).unwrap();
        let previous = store.read("session.json").unwrap().unwrap();
        reset(&store);
        let peer = Store::with_backend(directory.path().to_path_buf(), backend).unwrap();
        before_final(&store, move |_| { peer.revoke_session().unwrap(); });
        assert!(matches!(store.save_session(&session, None), Err(Error::Cancelled)));
        assert_eq!(counts(&store), (1, 0));
        assert_eq!(store.read("session.json").unwrap().unwrap(), previous);
        assert!(store.fence().unwrap().revoked);
        assert!(store.load_session(None).unwrap().is_none());
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn peer_logout_during_actual_keyring_get_cannot_reuse_or_publish_initial_intent() {
        let (directory, store, backend, session) = fixture();
        store.save_session(&session, None).unwrap();
        let previous = store.read("session.json").unwrap().unwrap();
        reset(&store);
        let peer = Store::with_backend(directory.path().to_path_buf(), backend.clone()).unwrap();
        let (started, observed) = std::sync::mpsc::sync_channel(1);
        let (release, released) = std::sync::mpsc::sync_channel(1);
        *backend.get_action.lock().unwrap() = Some(Box::new(move || {
            started.send(()).unwrap();
            released.recv_timeout(std::time::Duration::from_secs(5)).unwrap();
        }));
        let store = Arc::new(store);
        let writer = store.clone();
        let saving = std::thread::spawn(move || writer.save_session(&session, None));
        observed.recv_timeout(std::time::Duration::from_secs(5)).unwrap();
        peer.revoke_session().unwrap();
        assert!(peer.fence().unwrap().revoked, "revoke cannot wait on the stalled keyring/session lock");
        release.send(()).unwrap();
        assert!(matches!(saving.join().unwrap(), Err(Error::Cancelled)));
        assert_eq!(counts(&store), (1, 0));
        assert_eq!(store.read("session.json").unwrap().unwrap(), previous);
        assert!(store.load_session(None).unwrap().is_none());
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn final_session_failure_stays_an_error_and_preserves_previous_envelope() {
        let (_directory, store, _backend, mut session) = fixture();
        store.save_session(&session, None).unwrap();
        let previous = store.read("session.json").unwrap().unwrap();
        let previous_cookies = session.cookies.clone();
        reset(&store);
        store.session_intent_test.lock().unwrap().fail_session = true;
        session.cookies.insert("session".into(), "synthetic-unpublished".into());
        assert!(matches!(store.save_session(&session, None), Err(Error::Io)));
        assert_eq!(counts(&store), (1, 1));
        assert_eq!(store.read("session.json").unwrap().unwrap(), previous);
        assert_eq!(store.load_session(None).unwrap().unwrap().cookies, previous_cookies);
    }
    // contract-test: supporting surface=cli assertions=cli.runtime.native-rust,cli.migration.complete-compatible
    #[test]
    fn damaged_old_envelope_is_still_authenticated_before_any_session_replacement() {
        let (_directory, store, backend, session) = fixture();
        store.save_session(&session, None).unwrap();
        let mut envelope = store.envelope().unwrap().unwrap();
        envelope.ciphertext = "AAAA".into();
        store.atomic_write("session.json", &serde_json::to_vec(&envelope).unwrap()).unwrap();
        let damaged = store.read("session.json").unwrap().unwrap();
        reset(&store);
        assert!(matches!(store.save_session(&session, None), Err(Error::Crypto)));
        assert_eq!(counts(&store), (1, 0));
        assert_eq!(backend.gets.load(Ordering::SeqCst), 1);
        assert_eq!(store.read("session.json").unwrap().unwrap(), damaged);
    }
}
