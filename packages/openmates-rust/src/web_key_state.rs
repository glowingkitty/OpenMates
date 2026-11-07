//! Worker-resident chat-key state (the shared Rust core Worker `crypto` unit, keys lane K2).
//!
//! spec: specifications/features/auth#auth.keys.client-wrapped
//! spec: specifications/features/auth#auth.keys.independent-unlock
//! spec: specifications/surfaces/sdk#sdk.encryption.local-only
//!
//! Mirrors the state held by `ChatKeyManager.ts` (`keys`, `states`, `provenances`,
//! `pendingOps` and their ordering rules): one slot per chat with the key bytes,
//! provenance and load state, a bounded FIFO of waiter tickets per chat, a
//! `persisted` flag for provisional (created, not yet stored) keys, and
//! termination (`remove`, `clear`) that hands back the tickets whose waiters
//! must be rejected. The admission rule is `web_keys::inject_decision`. Key bytes
//! are `Zeroizing` and never formatted; the page only sees handles (fingerprint,
//! source, timestamps), see `browser_keys.rs`.
use crate::web_keys::{inject_decision, key_fingerprint, InjectDecision, KeySource};
use std::collections::HashMap;
use zeroize::Zeroizing;

/// Maximum waiters per chat before new ones are refused (`MAX_QUEUE_SIZE` in TS).
pub const MAX_WAITERS_PER_CHAT: usize = 50;

/// Load state of a chat key (`ChatKeyState` in TS); the wire strings match.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KeyState {
    /// No key and no load attempt in flight.
    Unloaded,
    /// A load from storage is in flight.
    Loading,
    /// The key is in the store.
    Ready,
    /// The last load failed; callers must `reset` to retry.
    Failed,
}

impl KeyState {
    /// Stable wire string.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Unloaded => "unloaded",
            Self::Loading => "loading",
            Self::Ready => "ready",
            Self::Failed => "failed",
        }
    }

    /// Parses a wire string; `Ready` is not settable from outside (only an accepted key makes a slot ready).
    pub fn parse_settable(text: &str) -> Option<Self> {
        match text {
            "unloaded" => Some(Self::Unloaded),
            "loading" => Some(Self::Loading),
            "failed" => Some(Self::Failed),
            _ => None,
        }
    }
}

/// Non-secret description of a stored key: what the page may hold as a handle.
#[derive(Clone, Debug, PartialEq)]
pub struct KeyHandle {
    /// 16-hex-char debug fingerprint (`computeKeyFingerprint`).
    pub fingerprint: String,
    /// Where the key came from.
    pub source: KeySource,
    /// Wall-clock milliseconds when the provenance was recorded.
    pub timestamp_ms: f64,
    /// False while a locally created key is not yet stored wrapped (provisional).
    pub persisted: bool,
}

/// Result of offering a key to the store.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OfferOutcome {
    /// What the admission rule decided.
    pub decision: InjectDecision,
    /// True when the slot just became ready (fire key-ready listeners).
    pub notify_ready: bool,
    /// Waiter tickets to run now, in arrival order.
    pub flushed: Vec<u32>,
}

/// Result of registering a waiter.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Enqueue {
    /// The key is already available; run immediately.
    Ready,
    /// Parked under this ticket until a key arrives, `cancel`, `remove` or `clear`.
    Queued(u32),
    /// The per-chat bound is reached.
    Full,
}

struct Slot {
    key: Zeroizing<Vec<u8>>,
    handle: KeyHandle,
}

/// All chat-key state of one realm. Single-threaded by construction (one Worker).
#[derive(Default)]
pub struct KeyStore {
    slots: HashMap<String, Slot>,
    states: HashMap<String, KeyState>,
    waiters: HashMap<String, Vec<u32>>,
    next_ticket: u32,
}

impl KeyStore {
    /// An empty store.
    pub fn new() -> Self {
        Self::default()
    }

    /// Offers `key` for `chat_id` (`injectKey`, `receiveKeyFromServer`, loads, rotation with `force`).
    ///
    /// `Set` and `Replace` store the key, mark it ready and release the chat's
    /// waiters; `UpgradeSource` only relabels provenance; `Keep` and `Reject` change nothing.
    /// A `Created` key starts unpersisted until `mark_persisted`.
    pub fn offer(
        &mut self,
        chat_id: &str,
        key: &[u8],
        source: KeySource,
        force: bool,
        now_ms: f64,
    ) -> OfferOutcome {
        let existing = self.slots.get(chat_id);
        let decision = inject_decision(
            existing.map(|slot| slot.key.as_slice()),
            existing.map(|slot| slot.handle.source),
            key,
            source,
            force,
        );
        let mut notify_ready = false;
        let mut flushed = Vec::new();
        match decision {
            InjectDecision::Set | InjectDecision::Replace => {
                notify_ready = self.states.get(chat_id) != Some(&KeyState::Ready);
                self.slots.insert(
                    chat_id.to_owned(),
                    Slot {
                        key: Zeroizing::new(key.to_vec()),
                        handle: KeyHandle {
                            fingerprint: key_fingerprint(key),
                            source,
                            timestamp_ms: now_ms,
                            persisted: source != KeySource::Created,
                        },
                    },
                );
                self.states.insert(chat_id.to_owned(), KeyState::Ready);
                flushed = self.waiters.remove(chat_id).unwrap_or_default();
            }
            InjectDecision::UpgradeSource => {
                if let Some(slot) = self.slots.get_mut(chat_id) {
                    slot.handle.source = source;
                    slot.handle.timestamp_ms = now_ms;
                    slot.handle.fingerprint = key_fingerprint(key);
                }
            }
            InjectDecision::Keep | InjectDecision::Reject => {}
        }
        OfferOutcome {
            decision,
            notify_ready,
            flushed,
        }
    }

    /// Marks a provisional key as stored; false when the chat has no key.
    pub fn mark_persisted(&mut self, chat_id: &str) -> bool {
        self.slots
            .get_mut(chat_id)
            .map(|slot| slot.handle.persisted = true)
            .is_some()
    }

    /// The key bytes for same-realm use (Worker-side crypto); never sent to the page.
    pub fn key(&self, chat_id: &str) -> Option<Zeroizing<Vec<u8>>> {
        self.slots.get(chat_id).map(|slot| slot.key.clone())
    }

    /// The page-safe handle of a stored key.
    pub fn handle(&self, chat_id: &str) -> Option<&KeyHandle> {
        self.slots.get(chat_id).map(|slot| &slot.handle)
    }

    /// Load state of a chat (`unloaded` when unknown).
    pub fn state(&self, chat_id: &str) -> KeyState {
        self.states
            .get(chat_id)
            .copied()
            .unwrap_or(KeyState::Unloaded)
    }

    /// Records a load transition; a ready slot keeps `Ready`.
    pub fn set_state(&mut self, chat_id: &str, state: KeyState) {
        if !self.slots.contains_key(chat_id) {
            self.states.insert(chat_id.to_owned(), state);
        }
    }

    /// Registers a waiter for the chat's key (`queueOperation`), FIFO, bounded.
    pub fn enqueue(&mut self, chat_id: &str) -> Enqueue {
        if self.slots.contains_key(chat_id) {
            return Enqueue::Ready;
        }
        let queue = self.waiters.entry(chat_id.to_owned()).or_default();
        if queue.len() >= MAX_WAITERS_PER_CHAT {
            return Enqueue::Full;
        }
        self.next_ticket = self.next_ticket.wrapping_add(1);
        queue.push(self.next_ticket);
        Enqueue::Queued(self.next_ticket)
    }

    /// Drops a waiter after its timeout; true when it was still parked.
    pub fn cancel(&mut self, chat_id: &str, ticket: u32) -> bool {
        let Some(queue) = self.waiters.get_mut(chat_id) else {
            return false;
        };
        let Some(index) = queue.iter().position(|t| *t == ticket) else {
            return false;
        };
        queue.remove(index);
        if queue.is_empty() {
            self.waiters.remove(chat_id);
        }
        true
    }

    /// Number of parked waiters for a chat.
    pub fn pending(&self, chat_id: &str) -> usize {
        self.waiters.get(chat_id).map_or(0, Vec::len)
    }

    /// Forgets the key and state for a retry load (`reloadKey`); waiters stay parked.
    pub fn reset(&mut self, chat_id: &str) {
        self.slots.remove(chat_id);
        self.states.insert(chat_id.to_owned(), KeyState::Unloaded);
    }

    /// Removes one chat (`removeKey`); returns the tickets to reject.
    pub fn remove(&mut self, chat_id: &str) -> Vec<u32> {
        self.slots.remove(chat_id);
        self.states.remove(chat_id);
        self.waiters.remove(chat_id).unwrap_or_default()
    }

    /// Terminates all key state (logout, account switch, cross-tab clear); returns the tickets to reject.
    pub fn clear(&mut self) -> Vec<u32> {
        self.slots.clear();
        self.states.clear();
        let mut tickets: Vec<u32> = self.waiters.drain().flat_map(|(_, queue)| queue).collect();
        tickets.sort_unstable();
        tickets
    }

    /// Number of stored keys.
    pub fn size(&self) -> usize {
        self.slots.len()
    }

    /// Chats whose key is stored but not yet persisted wrapped.
    pub fn unpersisted(&self) -> usize {
        self.slots
            .values()
            .filter(|slot| !slot.handle.persisted)
            .count()
    }
}
