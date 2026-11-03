//! Hidden chats (`hiddenChatService.ts`). SECURITY CRITICAL: existing hidden
//! chats must keep opening with the deployed scheme, byte for byte.
//!
//! combined secret = PBKDF2-SHA256(base64(master_key || utf8(code)),
//!                    user_email_salt[0..16], 100 000 iterations, 32 bytes)
//! hidden wrapper  = base64(12-byte IV || AES-GCM(secret, chat_key) || tag)
//! unhide wrapper  = master-key Format C (base64(IV || AES-GCM(master, key)))
//!
//! The code is never stored; the combined secret lives only in this vault and
//! is zeroized on lock/drop. Three failed unlock attempts lock unlocking for
//! 30 s. Any well-formed code "unlocks" (zero chats may match), exactly like
//! the web client, so a code cannot be probed by success/failure.
use super::js::utf16_len;
use crate::crypto::{self, Key, master::MasterCapability, web_formats};
use crate::{Error, Result};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use rand::{RngCore, rngs::OsRng};
use zeroize::Zeroizing;

pub const MAX_FAILED_ATTEMPTS: u32 = 3;
pub const LOCKOUT_MS: u64 = 30_000;
pub const HIDDEN_CHAT_PBKDF2_ITERATIONS: u32 = 100_000;
const INVALID_CODE: Error = Error::Invalid("Hidden chat code must be 4 to 30 characters.");

/// `password.length` (UTF-16 units) within 4..=30.
pub fn valid_code(code: &str) -> bool {
    (4..=30).contains(&utf16_len(code))
}

/// `user_email_salt.slice(0, 16)`; a missing salt is refused.
pub fn hidden_salt(email_salt: &[u8]) -> Result<&[u8]> {
    if email_salt.is_empty() {
        return Err(Error::Crypto);
    }
    Ok(&email_salt[..email_salt.len().min(16)])
}

/// PBKDF2 password input: `uint8ArrayToBase64(master || TextEncoder(code))`.
/// Platform adapters feed it to their PBKDF2 primitive (WebCrypto in browsers).
pub fn combined_secret_input(master: &[u8; 32], code: &str) -> Result<Zeroizing<String>> {
    if !valid_code(code) {
        return Err(INVALID_CODE);
    }
    let mut combined = Zeroizing::new(Vec::with_capacity(32 + code.len()));
    combined.extend_from_slice(master);
    combined.extend_from_slice(code.as_bytes());
    Ok(Zeroizing::new(STANDARD.encode(combined.as_slice())))
}

/// Native derivation (the browser uses WebCrypto PBKDF2 over the same input).
pub fn derive_secret(master: &[u8; 32], code: &str, email_salt: &[u8]) -> Result<Key> {
    if !valid_code(code) {
        return Err(INVALID_CODE);
    }
    web_formats::hidden_chat_secret(master, code, email_salt)
}

pub(crate) fn wrap_with_iv(
    chat_key: &[u8; 32],
    secret: &[u8; 32],
    iv: &[u8; 12],
) -> Result<String> {
    let mut combined = iv.to_vec();
    combined.extend(crypto::encrypt_aead(chat_key, secret, iv, &[])?);
    Ok(STANDARD.encode(combined))
}

/// `encryptChatKeyWithSecret`: fresh random IV per wrapper.
pub fn wrap_chat_key(chat_key: &[u8; 32], secret: &[u8; 32]) -> Result<String> {
    let mut iv = [0u8; 12];
    OsRng.fill_bytes(&mut iv);
    wrap_with_iv(chat_key, secret, &iv)
}

pub fn unwrap_chat_key(encrypted_chat_key: &str, secret: &[u8; 32]) -> Result<Key> {
    web_formats::unwrap_hidden_chat_key(encrypted_chat_key, secret)
}

/// `tryDecryptChatKey` result.
pub enum ChatKeyClass {
    /// Opens with the master key: an ordinary chat.
    Normal(Key),
    /// Opens with the unlocked combined secret: a hidden chat.
    Hidden(Key),
    /// Opens with neither: a locked hidden chat (or corrupt data). The web
    /// list treats it as hidden for filtering.
    LockedCandidate,
}

/// `hideChat` decision for one chat.
pub enum HidePlan {
    /// Hidden chats are locked: the UI must ask for the code first.
    NeedsUnlock,
    AlreadyHidden,
    MissingKey,
    /// Persist `encrypted_chat_key` and send it as a hidden-chat key rotation.
    /// `decrypted_chat_key` is set when the key was not cached and had to be
    /// opened from the stored wrapper (the adapter caches it).
    Hide {
        encrypted_chat_key: String,
        decrypted_chat_key: Option<Key>,
    },
}

pub struct UnhiddenChatKey {
    pub chat_key: Key,
    /// Master-key Format C wrapper to persist and sync.
    pub encrypted_chat_key: String,
}

fn exact_key(bytes: &[u8]) -> Result<Key> {
    let raw: [u8; 32] = bytes.try_into().map_err(|_| Error::Crypto)?;
    Ok(Zeroizing::new(raw))
}

async fn open_with_master(
    master: &MasterCapability,
    encrypted_chat_key: &str,
) -> Result<Option<Key>> {
    match master.decrypt_bytes(encrypted_chat_key).await {
        Ok(bytes) => exact_key(&bytes).map(Some),
        Err(Error::Crypto) => Ok(None),
        Err(other) => Err(other),
    }
}

#[derive(Default)]
pub struct HiddenChatVault {
    secret: Option<Key>,
    failed_attempts: u32,
    lockout_until_ms: Option<u64>,
}

impl HiddenChatVault {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn is_unlocked(&self) -> bool {
        self.secret.is_some()
    }

    /// `isLockedOut`: an expired lockout also resets the failure count.
    fn locked_out(&mut self, now_ms: u64) -> bool {
        match self.lockout_until_ms {
            None => false,
            Some(until) if now_ms >= until => {
                self.lockout_until_ms = None;
                self.failed_attempts = 0;
                false
            }
            Some(_) => true,
        }
    }

    pub fn remaining_lockout_seconds(&mut self, now_ms: u64) -> u64 {
        if !self.locked_out(now_ms) {
            return 0;
        }
        self.lockout_until_ms
            .map_or(0, |until| (until - now_ms).div_ceil(1000))
    }

    fn record_failed_attempt(&mut self, now_ms: u64) {
        self.failed_attempts += 1;
        if self.failed_attempts >= MAX_FAILED_ATTEMPTS {
            self.lockout_until_ms = Some(now_ms + LOCKOUT_MS);
        }
    }

    /// Gate before deriving for an unlock: refuses during lockout, and counts
    /// a malformed code as one failed attempt.
    pub fn admit_unlock(&mut self, code: &str, now_ms: u64) -> Result<()> {
        if self.locked_out(now_ms) {
            return Err(Error::Locked);
        }
        if !valid_code(code) {
            self.record_failed_attempt(now_ms);
            return Err(INVALID_CODE);
        }
        Ok(())
    }

    /// Unlock derivation threw (missing email salt, PBKDF2 failure). The web
    /// client counts it twice: in `deriveCombinedSecret` and in unlock.
    pub fn unlock_derivation_failed(&mut self, now_ms: u64) {
        self.record_failed_attempt(now_ms);
        self.record_failed_attempt(now_ms);
    }

    /// Unlock without master key material counts once.
    pub fn unlock_master_missing(&mut self, now_ms: u64) {
        self.record_failed_attempt(now_ms);
    }

    /// Gate before deriving for `encryptChatKeyWithCode`: lockout refuses, a
    /// malformed code is refused without counting.
    pub fn admit_code_wrap(&mut self, code: &str, now_ms: u64) -> Result<()> {
        if self.locked_out(now_ms) {
            return Err(Error::Locked);
        }
        if !valid_code(code) {
            return Err(INVALID_CODE);
        }
        Ok(())
    }

    /// `encryptChatKeyWithCode` derivation threw: counts once.
    pub fn code_wrap_derivation_failed(&mut self, now_ms: u64) {
        self.record_failed_attempt(now_ms);
    }

    /// Finish an unlock with a derived secret. Counts the stored wrappers that
    /// open with it (master-key wrappers are skipped), plus an optional freshly
    /// created wrapper. Succeeds for any count, storing the secret.
    pub async fn complete_unlock(
        &mut self,
        master: &MasterCapability,
        secret: Key,
        encrypted_chat_keys: &[String],
        verified_encrypted_chat_key: Option<&str>,
        now_ms: u64,
    ) -> Result<usize> {
        let verified = verified_encrypted_chat_key
            .is_some_and(|wrapped| unwrap_chat_key(wrapped, &secret).is_ok());
        let mut decrypted = 0usize;
        for wrapped in encrypted_chat_keys
            .iter()
            .filter(|wrapped| !wrapped.is_empty())
        {
            match open_with_master(master, wrapped).await {
                Ok(Some(_)) => continue,
                Ok(None) => decrypted += usize::from(unwrap_chat_key(wrapped, &secret).is_ok()),
                Err(error) => {
                    self.record_failed_attempt(now_ms);
                    return Err(error);
                }
            }
        }
        self.secret = Some(secret);
        self.failed_attempts = 0;
        self.lockout_until_ms = None;
        Ok(decrypted.max(usize::from(verified)))
    }

    /// Native convenience: admit, derive and complete in one step.
    pub async fn unlock(
        &mut self,
        master: &MasterCapability,
        raw_master: &[u8; 32],
        code: &str,
        email_salt: &[u8],
        encrypted_chat_keys: &[String],
        now_ms: u64,
    ) -> Result<usize> {
        self.admit_unlock(code, now_ms)?;
        let secret = match derive_secret(raw_master, code, email_salt) {
            Ok(secret) => secret,
            Err(error) => {
                self.unlock_derivation_failed(now_ms);
                return Err(error);
            }
        };
        self.complete_unlock(master, secret, encrypted_chat_keys, None, now_ms)
            .await
    }

    /// `lockHiddenChats`: the secret is zeroized; adapters also drop every
    /// cached chat key so hidden content leaves memory.
    pub fn lock(&mut self) {
        self.secret = None;
    }

    pub fn wrap(&self, chat_key: &[u8; 32]) -> Result<String> {
        wrap_chat_key(chat_key, self.secret.as_ref().ok_or(Error::Locked)?)
    }

    /// `None` when locked or when the wrapper does not open with the secret.
    pub fn unwrap(&self, encrypted_chat_key: &str) -> Option<Key> {
        unwrap_chat_key(encrypted_chat_key, self.secret.as_ref()?).ok()
    }

    pub async fn classify(
        &self,
        master: &MasterCapability,
        encrypted_chat_key: &str,
    ) -> Result<ChatKeyClass> {
        if let Some(key) = open_with_master(master, encrypted_chat_key).await? {
            return Ok(ChatKeyClass::Normal(key));
        }
        Ok(self
            .unwrap(encrypted_chat_key)
            .map_or(ChatKeyClass::LockedCandidate, ChatKeyClass::Hidden))
    }

    pub async fn plan_hide(
        &self,
        master: &MasterCapability,
        cached_chat_key: Option<&[u8; 32]>,
        encrypted_chat_key: Option<&str>,
    ) -> Result<HidePlan> {
        if !self.is_unlocked() {
            return Ok(HidePlan::NeedsUnlock);
        }
        if let Some(key) = cached_chat_key {
            return Ok(HidePlan::Hide {
                encrypted_chat_key: self.wrap(key)?,
                decrypted_chat_key: None,
            });
        }
        let Some(wrapped) = encrypted_chat_key.filter(|wrapped| !wrapped.is_empty()) else {
            return Ok(HidePlan::MissingKey);
        };
        match self.classify(master, wrapped).await? {
            ChatKeyClass::Hidden(_) => Ok(HidePlan::AlreadyHidden),
            ChatKeyClass::LockedCandidate => Ok(HidePlan::MissingKey),
            ChatKeyClass::Normal(key) => Ok(HidePlan::Hide {
                encrypted_chat_key: self.wrap(&key)?,
                decrypted_chat_key: Some(key),
            }),
        }
    }

    /// `unhideChat`: open with the secret, re-wrap with the master key.
    pub async fn unhide(
        &self,
        master: &MasterCapability,
        encrypted_chat_key: &str,
    ) -> Result<UnhiddenChatKey> {
        if !self.is_unlocked() {
            return Err(Error::Locked);
        }
        let chat_key = self.unwrap(encrypted_chat_key).ok_or(Error::Crypto)?;
        let encrypted_chat_key = master.encrypt_server_bytes(chat_key.as_slice()).await?;
        Ok(UnhiddenChatKey {
            chat_key,
            encrypted_chat_key,
        })
    }
}

impl HiddenChatVault {
    /// Native `encryptChatKeyWithCode` (hide while locked): derive and wrap
    /// without unlocking; the caller unlocks next with the same code.
    pub fn wrap_chat_key_with_code(
        &mut self,
        raw_master: &[u8; 32],
        code: &str,
        email_salt: &[u8],
        chat_key: &[u8; 32],
        now_ms: u64,
    ) -> Result<String> {
        self.admit_code_wrap(code, now_ms)?;
        let secret = match derive_secret(raw_master, code, email_salt) {
            Ok(secret) => secret,
            Err(error) => {
                self.code_wrap_derivation_failed(now_ms);
                return Err(error);
            }
        };
        wrap_chat_key(chat_key, &secret)
    }
}

/// Stored chat versions used by `sendUpdateChatKeyImpl`.
#[derive(Clone, Copy, Debug, Default)]
pub struct ChatKeyVersions {
    pub messages_v: Option<u64>,
    pub title_v: Option<u64>,
    pub last_edited_overall_timestamp: Option<u64>,
}

/// `encrypted_chat_metadata` frame for hide/unhide key rotation. Falsy
/// versions become 0 and a falsy edit timestamp becomes `now_seconds`, like
/// the web `||` defaults.
pub fn chat_key_update_payload(
    chat_id: &str,
    encrypted_chat_key: &str,
    versions: ChatKeyVersions,
    now_seconds: u64,
) -> serde_json::Value {
    let edited = versions
        .last_edited_overall_timestamp
        .filter(|t| *t != 0)
        .unwrap_or(now_seconds);
    serde_json::json!({
        "chat_id": chat_id,
        "encrypted_chat_key": encrypted_chat_key,
        "allow_chat_key_rotation": true,
        "chat_key_rotation_reason": "hidden_chat",
        "versions": {
            "messages_v": versions.messages_v.unwrap_or(0),
            "title_v": versions.title_v.unwrap_or(0),
            "last_edited_overall_timestamp": edited,
        },
    })
}

pub const CHAT_KEY_UPDATE_FRAME: &str = "encrypted_chat_metadata";

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "hidden_tests.rs"]
mod tests;
