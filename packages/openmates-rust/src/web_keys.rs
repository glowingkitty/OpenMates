//! Web chat-key admission policy (the shared Rust core Worker `crypto` unit, keys lane K1).
//!
//! spec: specifications/features/auth#auth.keys.client-wrapped
//! spec: specifications/features/auth#auth.keys.independent-unlock
//! spec: specifications/surfaces/sdk#sdk.encryption.local-only
//!
//! Mirrors the pure decisions of `ChatKeyManager.ts`: the debug key fingerprint
//! (`computeKeyFingerprint`), byte equality (`keysAreEqual`), the `KeySource`
//! priority table and the `injectKey` admission rule (immutable keys: a different
//! key never replaces a loaded one without `force`). Key bytes are only compared
//! and hashed here, never stored or logged. Byte-for-byte parity with the TS
//! functions is proven by `web_keys_ts_vectors.json`, which
//! `chatKeyAdmissionVectors.test.ts` checks against the real `ChatKeyManager`.

/// Where a chat key came from; the wire strings match the TS `KeySource` union.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeySource {
    /// `createKeyForNewChat()` on the originating device.
    Created,
    /// Unwrapped from `encrypted_chat_key` with the master key.
    MasterKey,
    /// Received over the WebSocket and unwrapped.
    ServerSync,
    /// Extracted from a share-link URL fragment.
    ShareLink,
    /// Loaded from the shared-keys IndexedDB store.
    SharedStorage,
    /// Loaded during app initialisation.
    BulkInit,
    /// Decrypted via the hidden-chat combined secret.
    HiddenChat,
    /// Unwrapped locally for logged-out anonymous chats.
    AnonymousSession,
    /// Opened from a recipient-bound Team direct-chat envelope.
    DirectChat,
    /// Generic injection (legacy/migration path).
    Injected,
}

impl KeySource {
    /// Parses the wire string; `None` for anything outside the ten known sources.
    pub fn parse(text: &str) -> Option<Self> {
        Some(match text {
            "created" => Self::Created,
            "master_key" => Self::MasterKey,
            "server_sync" => Self::ServerSync,
            "share_link" => Self::ShareLink,
            "shared_storage" => Self::SharedStorage,
            "bulk_init" => Self::BulkInit,
            "hidden_chat" => Self::HiddenChat,
            "anonymous_session" => Self::AnonymousSession,
            "direct_chat" => Self::DirectChat,
            "injected" => Self::Injected,
            _ => return None,
        })
    }

    /// Authority of the source: a higher value may relabel the provenance of an identical key.
    pub fn priority(self) -> u8 {
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

/// Outcome of offering a key to a chat slot (`ChatKeyManager.injectKey`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InjectDecision {
    /// Slot was empty: store the key, mark it ready, notify key-ready listeners, flush pending operations.
    Set,
    /// A different key was loaded and `force` was set: replace it (no key-ready notification).
    Replace,
    /// Identical key, more authoritative source: keep the key, relabel its provenance.
    UpgradeSource,
    /// Identical key, no more authoritative: nothing to do (still accepted).
    Keep,
    /// A different key is loaded and `force` is false: refuse the replacement.
    Reject,
}

impl InjectDecision {
    /// Stable wire string used across the worker boundary and in the vectors.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Set => "set",
            Self::Replace => "replace",
            Self::UpgradeSource => "upgrade_source",
            Self::Keep => "keep",
            Self::Reject => "reject",
        }
    }

    /// Whether the caller's `injectKey` returns true (the key is, or becomes, the chat key).
    pub fn accepted(self) -> bool {
        self != Self::Reject
    }
}

/// Non-cryptographic 16-hex-char key fingerprint (two FNV-1a passes, forward and
/// backward). Only for comparing and logging keys; it must stay identical to
/// `computeKeyFingerprint` because stored provenance and logs use it.
pub fn key_fingerprint(key: &[u8]) -> String {
    const PRIME: u32 = 0x0100_0193;
    let forward = key
        .iter()
        .fold(0x811c_9dc5_u32, |hash, byte| (hash ^ u32::from(*byte)).wrapping_mul(PRIME));
    let backward = key
        .iter()
        .rev()
        .fold(0x1a47_e90b_u32, |hash, byte| (hash ^ u32::from(*byte)).wrapping_mul(PRIME));
    format!("{forward:08x}{backward:08x}")
}

/// Byte equality of two keys without an early exit on the first differing byte.
pub fn keys_equal(a: &[u8], b: &[u8]) -> bool {
    a.len() == b.len() && a.iter().zip(b).fold(0u8, |diff, (x, y)| diff | (x ^ y)) == 0
}

/// Decides what `injectKey` does when `key` from `source` is offered to a chat slot.
///
/// `existing` is the loaded key (if any) and `current_source` its recorded
/// provenance source (it can be absent for a loaded key, which counts as
/// upgradable). Invariant: a different key never replaces a loaded one unless `force`.
pub fn inject_decision(
    existing: Option<&[u8]>,
    current_source: Option<KeySource>,
    key: &[u8],
    source: KeySource,
    force: bool,
) -> InjectDecision {
    match existing {
        None => InjectDecision::Set,
        Some(loaded) if keys_equal(loaded, key) => match current_source {
            Some(current) if source.priority() <= current.priority() => InjectDecision::Keep,
            _ => InjectDecision::UpgradeSource,
        },
        Some(_) if force => InjectDecision::Replace,
        Some(_) => InjectDecision::Reject,
    }
}
