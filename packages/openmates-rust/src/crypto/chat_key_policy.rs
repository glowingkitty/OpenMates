//! Web chat-key policy, sans IO: chat-content framing, key fingerprints, the
//! key-slot compare-and-swap, the chat-key write guard and the decryption
//! failure cache. Each item mirrors the deployed TypeScript owner named on it;
//! tests/crypto_fixtures/ts_web_policy.json is produced by those TS modules.
//! Adapters (native or the browser WebCrypto binding) execute the AEAD steps.
use super::*;
use std::collections::{HashMap, HashSet};

const MAGIC: &[u8; 2] = b"OM";
const HEADER: usize = 6;
const IV: usize = 12;
const TAG: usize = 16;
/// Historical Python writer marker accepted by `crypto::decrypt_bytes`.
const PYTHON_MARKER: [u8; 4] = [1, 0, 0, 0];

// ── Chat content (MessageEncryptor.encryptWithChatKey/decryptWithChatKey) ──

/// One AES-GCM attempt over byte ranges of the decoded ciphertext.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ChatAttempt {
    pub iv: (usize, usize),
    pub body: (usize, usize),
}

/// Ordered authenticated attempts for one chat-content ciphertext. Every
/// attempt needs a valid tag; nothing is returned on header trust alone.
#[derive(Debug, PartialEq, Eq)]
pub struct ChatContentPlan {
    pub attempts: Vec<ChatAttempt>,
    /// Stored OM fingerprint that differs from the key. TS answers this with
    /// candidate-key recovery, so callers report it when every attempt fails.
    pub fingerprint_mismatch: Option<[u8; 4]>,
}

/// Plans a chat-content read. It accepts everything the TS reader accepts
/// (OM header with matching fingerprint, legacy IV-prefixed) and, like
/// `crypto::decrypt_bytes`, also the Python marker and legacy buffers whose
/// random IV happens to begin with "OM" (the TS reader rejects those).
pub fn plan_chat_content(bytes: &[u8], key: &[u8; 32]) -> ChatContentPlan {
    let len = bytes.len();
    let legacy = (len >= IV + TAG).then_some(ChatAttempt {
        iv: (0, IV),
        body: (IV, len),
    });
    let framed = ChatAttempt {
        iv: (HEADER, HEADER + IV),
        body: (HEADER + IV, len),
    };
    // TS gate: length > header + IV and the "OM" magic.
    if len > HEADER + IV && bytes.starts_with(MAGIC) {
        let stored: [u8; 4] = bytes[2..HEADER].try_into().unwrap_or_default();
        if stored == key_fingerprint(key) || stored == PYTHON_MARKER {
            let attempts = if len >= HEADER + IV + TAG {
                vec![framed]
            } else {
                vec![]
            };
            return ChatContentPlan {
                attempts: attempts.into_iter().chain(legacy).collect(),
                fingerprint_mismatch: None,
            };
        }
        return ChatContentPlan {
            attempts: legacy.into_iter().collect(),
            fingerprint_mismatch: Some(stored),
        };
    }
    ChatContentPlan {
        attempts: legacy.into_iter().collect(),
        fingerprint_mismatch: None,
    }
}

/// Result of a chat-content read that callers must distinguish.
pub enum ChatContentOutcome {
    Plaintext(Zeroizing<Vec<u8>>),
    /// Every attempt failed and the OM header names another key.
    FingerprintMismatch([u8; 4]),
    Failed,
}

/// Browser `base64ToUint8Array` decode with a copy-free fast path for
/// canonical standard base64 (the deployed writer output).
pub fn decode_web_base64(value: &str) -> Result<Zeroizing<Vec<u8>>> {
    let canonical = !value.is_empty()
        && value.len() % 4 == 0
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'+' || b == b'/' || b == b'=');
    if canonical {
        let engine = base64::engine::GeneralPurpose::new(
            &base64::alphabet::STANDARD,
            base64::engine::GeneralPurposeConfig::new()
                .with_decode_allow_trailing_bits(true)
                .with_decode_padding_mode(base64::engine::DecodePaddingMode::Indifferent),
        );
        if let Ok(bytes) = engine.decode(value) {
            return Ok(Zeroizing::new(bytes));
        }
    }
    Ok(Zeroizing::new(master::decode_browser_base64(value)?))
}

/// Synchronous reader (native and tests). The browser binding runs the same
/// plan through WebCrypto (Worker) or [`ChatContentCipher`] (main thread).
pub fn decrypt_chat_content(ciphertext: &str, key: &[u8; 32]) -> ChatContentOutcome {
    ChatContentCipher::new(key).decrypt(ciphertext)
}

/// One chat key's AES-256-GCM state for repeated chat-content reads/writes
/// (a chat window decrypts many messages under one key). Key bytes and the
/// expanded key schedule are zeroized on drop.
pub struct ChatContentCipher {
    key: Zeroizing<[u8; 32]>,
    aead: Aes256Gcm,
}

impl ChatContentCipher {
    pub fn new(key: &[u8; 32]) -> Self {
        Self {
            key: Zeroizing::new(*key),
            aead: Aes256Gcm::new(key.into()),
        }
    }

    /// Constant-time check that this cipher was built from `key`.
    pub fn is_for(&self, key: &[u8; 32]) -> bool {
        chat_keys_equal(self.key.as_slice(), key)
    }

    /// Same outcome as [`decrypt_chat_content`] for this key.
    pub fn decrypt(&self, ciphertext: &str) -> ChatContentOutcome {
        let Ok(bytes) = decode_web_base64(ciphertext) else {
            return ChatContentOutcome::Failed;
        };
        let plan = plan_chat_content(&bytes, &self.key);
        for attempt in &plan.attempts {
            let nonce = Nonce::from_slice(&bytes[attempt.iv.0..attempt.iv.1]);
            let body = &bytes[attempt.body.0..attempt.body.1];
            if let Ok(plain) = self.aead.decrypt(
                nonce,
                Payload {
                    msg: body,
                    aad: &[],
                },
            ) {
                return ChatContentOutcome::Plaintext(Zeroizing::new(plain));
            }
        }
        match plan.fingerprint_mismatch {
            Some(stored) => ChatContentOutcome::FingerprintMismatch(stored),
            None => ChatContentOutcome::Failed,
        }
    }

    /// Same framing as [`encrypt_chat_content`] for this key, fresh random IV.
    pub fn encrypt(&self, plaintext: &[u8]) -> Result<String> {
        let iv = share::random_iv();
        let sealed = Zeroizing::new(
            self.aead
                .encrypt(
                    Nonce::from_slice(&iv),
                    Payload {
                        msg: plaintext,
                        aad: &[],
                    },
                )
                .map_err(|_| Error::Crypto)?,
        );
        Ok(frame_chat_content(&self.key, &iv, &sealed))
    }
}

/// Frames an already sealed body exactly like `encryptWithChatKey`:
/// base64("OM" || fnv32(key) || iv || ciphertext || tag).
pub fn frame_chat_content(key: &[u8; 32], iv: &[u8; 12], sealed: &[u8]) -> String {
    let mut combined = Vec::with_capacity(HEADER + IV + sealed.len());
    combined.extend_from_slice(MAGIC);
    combined.extend_from_slice(&key_fingerprint(key));
    combined.extend_from_slice(iv);
    combined.extend_from_slice(sealed);
    STANDARD.encode(combined)
}

/// Synchronous writer (native, tests and the browser main-thread chat-key
/// adapter): `encryptWithChatKey` framing with a fresh random 12-byte IV.
pub fn encrypt_chat_content(plaintext: &[u8], key: &[u8; 32]) -> Result<String> {
    ChatContentCipher::new(key).encrypt(plaintext)
}

/// `ChatKeyManager.computeKeyFingerprint`: two FNV-1a passes, 16 hex chars.
pub fn chat_key_fingerprint_hex(key: &[u8]) -> String {
    let forward = key.iter().fold(0x811c9dc5u32, |h, b| {
        (h ^ u32::from(*b)).wrapping_mul(0x01000193)
    });
    let backward = key.iter().rev().fold(0x1a47e90bu32, |h, b| {
        (h ^ u32::from(*b)).wrapping_mul(0x01000193)
    });
    format!("{forward:08x}{backward:08x}")
}

/// `MessageEncryptor.computeKeyFingerprint4Bytes` as lowercase hex.
pub fn chat_key_fingerprint4_hex(key: &[u8]) -> String {
    let h = key.iter().fold(0x811c9dc5u32, |h, b| {
        (h ^ u32::from(*b)).wrapping_mul(0x01000193)
    });
    format!("{h:08x}")
}

/// Cache identity for imported keys: SHA-256 so no raw key is used as a map key.
pub fn key_cache_digest(key: &[u8]) -> [u8; 32] {
    Sha256::digest(key).into()
}

/// `chatKeyConsistency.chatKeysEqual`, constant time over equal lengths.
pub fn chat_keys_equal(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

// ── Master-key Formats C/D envelope (MetadataEncryptor, page WebCrypto adapter) ──
//
// For an adapter that runs the AES-GCM step itself with the page's
// non-extractable master CryptoKey (the browser main thread). Same envelope as
// `MasterCapability`'s opaque-port reader/writer.

/// Formats C/D read: `cryptoService.base64ToUint8Array` decode
/// ([`decode_web_base64`]); the first 12
/// bytes are always the IV (even when they start with "OM"); at least IV + tag.
/// Returns IV || ciphertext || tag for one authenticated AES-GCM attempt.
pub fn open_master_envelope(ciphertext: &str) -> Result<Zeroizing<Vec<u8>>> {
    let combined = decode_web_base64(ciphertext)?;
    if combined.len() < IV + TAG {
        return Err(Error::Crypto);
    }
    Ok(combined)
}

/// Formats C/D write: base64(IV || ciphertext || tag), after checking the
/// adapter's AES-GCM output is exactly the plaintext length plus the tag.
pub fn frame_master_envelope(iv: &[u8], sealed: &[u8], plaintext_len: usize) -> Result<String> {
    if iv.len() != IV || sealed.len() != plaintext_len.checked_add(TAG).ok_or(Error::Crypto)? {
        return Err(Error::Crypto);
    }
    let mut combined = Vec::with_capacity(IV + sealed.len());
    combined.extend_from_slice(iv);
    combined.extend_from_slice(sealed);
    Ok(STANDARD.encode(combined))
}

// ── Key slot compare-and-swap (ChatKeyManager.injectKey) ──

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeySource {
    DirectChat,
    MasterKey,
    ServerSync,
    Created,
    HiddenChat,
    BulkInit,
    AnonymousSession,
    SharedStorage,
    ShareLink,
    Injected,
}

impl KeySource {
    pub fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "direct_chat" => Self::DirectChat,
            "master_key" => Self::MasterKey,
            "server_sync" => Self::ServerSync,
            "created" => Self::Created,
            "hidden_chat" => Self::HiddenChat,
            "bulk_init" => Self::BulkInit,
            "anonymous_session" => Self::AnonymousSession,
            "shared_storage" => Self::SharedStorage,
            "share_link" => Self::ShareLink,
            "injected" => Self::Injected,
            _ => return None,
        })
    }
    fn priority(self) -> u8 {
        match self {
            Self::DirectChat | Self::MasterKey => 100,
            Self::ServerSync => 90,
            Self::Created => 80,
            Self::HiddenChat => 70,
            Self::BulkInit => 60,
            Self::AnonymousSession => 50,
            Self::SharedStorage => 30,
            Self::ShareLink => 20,
            Self::Injected => 10,
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum InjectDecision {
    /// No key loaded: store it.
    Insert,
    /// Same key; `update_provenance` when the new source outranks the old one.
    SameKey { update_provenance: bool },
    /// Different key without force: the slot keeps its key.
    Rejected,
    /// Different key with force: replace and log.
    ForceReplace,
}

/// Compare-and-swap for a chat's key slot. A loaded key is never silently
/// replaced by a different one.
pub fn decide_inject(
    existing: Option<(&[u8], Option<KeySource>)>,
    new_key: &[u8],
    source: KeySource,
    force: bool,
) -> InjectDecision {
    match existing {
        None => InjectDecision::Insert,
        Some((current, provenance)) if chat_keys_equal(current, new_key) => {
            InjectDecision::SameKey {
                update_provenance: provenance.is_none_or(|old| source.priority() > old.priority()),
            }
        }
        Some(_) if force => InjectDecision::ForceReplace,
        Some(_) => InjectDecision::Rejected,
    }
}

// ── Chat-key write guard (chatKeyWriteGuard.ensureChatKeySafeForWrite) ──

/// The chat row facts the TS guard reads before deciding.
#[derive(Debug, Default, Clone)]
pub struct ChatKeyWriteSnapshot {
    pub chat_exists: bool,
    pub candidate_key_count: usize,
    /// `chat.key_fingerprint` (16-hex) when truthy.
    pub key_fingerprint: Option<String>,
    pub is_anonymous: bool,
    pub team_scoped: bool,
    pub direct_visibility: bool,
    /// `chat.encrypted_chat_key ?? getEncryptedChatKey(chatId)` when truthy.
    pub encrypted_chat_key: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GuardReason {
    CandidateKeysPending,
    FingerprintMismatch,
    AnonymousKeyUnwrapFailed,
    AnonymousKeyMismatch,
    EncryptedKeyMissing,
    PersistedKeyUnwrapFailed,
    PersistedKeyMismatch,
}

impl GuardReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::CandidateKeysPending => "candidate_keys_pending",
            Self::FingerprintMismatch => "fingerprint_mismatch",
            Self::AnonymousKeyUnwrapFailed => "anonymous_key_unwrap_failed",
            Self::AnonymousKeyMismatch => "anonymous_key_mismatch",
            Self::EncryptedKeyMissing => "encrypted_key_missing",
            Self::PersistedKeyUnwrapFailed => "persisted_key_unwrap_failed",
            Self::PersistedKeyMismatch => "persisted_key_mismatch",
        }
    }
}

/// User notice the TS guard raises when failure reporting is on.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GuardNotice {
    None,
    ConflictingKeys,
    KeyNotValidated,
}

#[derive(Debug, PartialEq, Eq)]
pub enum GuardStep {
    Allow,
    /// Allowed although the persisted wrapper did not open (hidden-chat owner).
    AllowUnverified,
    Refuse {
        reason: GuardReason,
        add_candidate: bool,
        notice: GuardNotice,
    },
    /// Caller unwraps `anonymous_encrypted_chat_key`, then calls `guard_after_anonymous`.
    UnwrapAnonymous,
    /// Caller unwraps the persisted key (Team envelope when `team`, else master
    /// key), then calls `guard_after_persisted`.
    UnwrapPersisted {
        team: bool,
    },
}

fn refuse(reason: GuardReason, add_candidate: bool, notice: GuardNotice) -> GuardStep {
    GuardStep::Refuse {
        reason,
        add_candidate,
        notice,
    }
}

pub fn guard_begin(
    snapshot: &ChatKeyWriteSnapshot,
    raw_key: &[u8],
    allow_missing_encrypted_chat_key: bool,
) -> GuardStep {
    if snapshot.candidate_key_count > 0 {
        return refuse(
            GuardReason::CandidateKeysPending,
            false,
            GuardNotice::ConflictingKeys,
        );
    }
    if let Some(stored) = snapshot
        .key_fingerprint
        .as_deref()
        .filter(|v| !v.is_empty())
        && stored != chat_key_fingerprint_hex(raw_key)
    {
        return refuse(
            GuardReason::FingerprintMismatch,
            snapshot.encrypted_chat_key.is_some(),
            GuardNotice::ConflictingKeys,
        );
    }
    if snapshot.is_anonymous && snapshot.encrypted_chat_key.is_none() {
        return GuardStep::UnwrapAnonymous;
    }
    let Some(wrapped) = snapshot.encrypted_chat_key.as_deref() else {
        if allow_missing_encrypted_chat_key && !snapshot.direct_visibility {
            return GuardStep::Allow;
        }
        return refuse(GuardReason::EncryptedKeyMissing, false, GuardNotice::None);
    };
    if !snapshot.team_scoped && (snapshot.direct_visibility || wrapped.starts_with("OMDM1.")) {
        // TS: "Private chat has no Team context" thrown inside the unwrap.
        return refuse(
            GuardReason::PersistedKeyUnwrapFailed,
            false,
            GuardNotice::KeyNotValidated,
        );
    }
    GuardStep::UnwrapPersisted {
        team: snapshot.team_scoped,
    }
}

pub fn guard_after_anonymous(raw_key: &[u8], unwrapped: Option<&[u8]>) -> GuardStep {
    match unwrapped {
        None => refuse(
            GuardReason::AnonymousKeyUnwrapFailed,
            false,
            GuardNotice::None,
        ),
        Some(key) if chat_keys_equal(raw_key, key) => GuardStep::Allow,
        Some(_) => refuse(
            GuardReason::AnonymousKeyMismatch,
            false,
            GuardNotice::ConflictingKeys,
        ),
    }
}

/// `unwrapped`: `Err` when the unwrap threw, `Ok(None)` when it returned null.
pub fn guard_after_persisted(
    raw_key: &[u8],
    unwrapped: std::result::Result<Option<&[u8]>, ()>,
) -> GuardStep {
    match unwrapped {
        Err(()) => refuse(
            GuardReason::PersistedKeyUnwrapFailed,
            false,
            GuardNotice::KeyNotValidated,
        ),
        Ok(None) => GuardStep::AllowUnverified,
        Ok(Some(key)) if chat_keys_equal(raw_key, key) => GuardStep::Allow,
        Ok(Some(_)) => refuse(
            GuardReason::PersistedKeyMismatch,
            true,
            GuardNotice::ConflictingKeys,
        ),
    }
}

// ── Decryption failure cache (db/decryptionFailureCache.ts) ──

/// Permanent per-field decryption failures, keyed by chat. Entries carry the
/// key fingerprint so a failure with one key never blocks a retry with another.
#[derive(Default)]
pub struct DecryptionFailureCache {
    chats: HashMap<String, HashSet<String>>,
}

impl DecryptionFailureCache {
    pub fn clear(&mut self, chat_id: Option<&str>) {
        match chat_id {
            Some(chat_id) => {
                self.chats.remove(chat_id);
            }
            None => self.chats.clear(),
        }
    }

    pub fn is_known(
        &self,
        chat_id: &str,
        message_id: &str,
        field: &str,
        fingerprint: Option<&str>,
    ) -> bool {
        let Some(entries) = self.chats.get(chat_id) else {
            return false;
        };
        match fingerprint.filter(|v| !v.is_empty()) {
            Some(fp) => entries.contains(&format!("{message_id}:{field}:{fp}")),
            None => {
                let prefix = format!("{message_id}:{field}");
                let scoped = format!("{prefix}:");
                entries
                    .iter()
                    .any(|entry| *entry == prefix || entry.starts_with(&scoped))
            }
        }
    }

    pub fn record(
        &mut self,
        chat_id: &str,
        message_id: &str,
        field: &str,
        fingerprint: Option<&str>,
    ) {
        let entry = match fingerprint.filter(|v| !v.is_empty()) {
            Some(fp) => format!("{message_id}:{field}:{fp}"),
            None => format!("{message_id}:{field}"),
        };
        self.chats
            .entry(chat_id.to_owned())
            .or_default()
            .insert(entry);
    }
}
