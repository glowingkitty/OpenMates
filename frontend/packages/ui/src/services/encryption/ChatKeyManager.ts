// frontend/packages/ui/src/services/encryption/ChatKeyManager.ts
// Central key state machine for chat encryption keys.
// Architecture: See docs/architecture/encryption.md for design rationale.
//
// This class is the SINGLE source of truth for obtaining chat keys.
// It replaces the scattered getOrGenerateChatKey / getChatKeyOrNull / getOrCreateChatKeyForOriginator
// functions with a unified, state-tracked approach that NEVER silently generates wrong keys.
//
// Key design principles:
// 1. NEVER generate a key silently — getKey() returns null if unavailable
// 2. State machine per chat — tracks 'unloaded' | 'loading' | 'ready' | 'failed'
// 3. Queue-and-flush — operations that need a missing key are queued and auto-executed on key arrival
// 4. createKeyForNewChat() is the ONLY way to generate a new key (explicit, auditable)
// 5. All encryption operations receive the key as a parameter (enforced by TypeScript)
// 6. IMMUTABLE KEYS — once a key is set, it cannot be silently replaced (defense-in-depth)
// 7. KEY PROVENANCE — every key records its source for debugging decryption failures
//
// Tests: (to be added)

import {
  _generateChatKeyInternal,
  encryptChatKeyWithMasterKey,
  decryptChatKeyWithMasterKey,
  clearCryptoKeyCache,
} from "../cryptoService";
import { clearDecryptionFailureCache } from "../db/decryptionFailureCache";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Possible states for a chat key in the manager */
export type ChatKeyState = "unloaded" | "loading" | "ready" | "failed";

/** Where a key came from — critical for debugging decryption failures */
export type KeySource =
  | "created" // createKeyForNewChat() on originating device
  | "master_key" // Unwrapped from encrypted_chat_key via master key
  | "server_sync" // Received via WebSocket broadcast (encrypted, then unwrapped)
  | "share_link" // Extracted from a share link URL fragment
  | "shared_storage" // Loaded from openmates_shared_keys IndexedDB
  | "bulk_init" // Loaded during app init (loadChatKeysFromDatabase)
  | "hidden_chat" // Decrypted via hidden chat combined secret
  | "injected"; // Generic injection (legacy/migration path)

/** Provenance record for a key — tracks how and when it was loaded */
export interface KeyProvenance {
  source: KeySource;
  timestamp: number;
  /** First 8 hex chars of SHA-256 hash of the key bytes (for comparison, not security) */
  keyFingerprint: string;
}

/** A queued operation waiting for a chat key to become available */
interface QueuedOperation {
  /** Human-readable label for debugging (e.g. "encrypt post-processing metadata") */
  label: string;
  /** The async function to execute once the key is available */
  execute: (chatKey: Uint8Array) => Promise<void>;
  /** Reject callback so the caller can be notified if the key never arrives */
  reject: (reason: Error) => void;
}

/** Summary of key state for a single chat (used by debug tools) */
export interface ChatKeyInfo {
  chatId: string;
  state: ChatKeyState;
  keyLengthBytes: number | null;
  pendingOps: number;
  provenance: KeyProvenance | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maximum time (ms) a queued operation will wait before being rejected */
const QUEUE_TIMEOUT_MS = 30_000;

/** Maximum number of queued operations per chat before new ones are rejected */
const MAX_QUEUE_SIZE = 50;

/**
 * Compute a short fingerprint of a key for comparison/logging.
 * Uses first 8 hex chars of a simple hash (NOT cryptographic — just for debugging).
 * Fast and synchronous, no Web Crypto needed.
 *
 * Exported so other modules can use the same fingerprint algorithm without
 * duplicating the implementation (was duplicated in chatCrudOperations.ts).
 */
export function computeKeyFingerprint(key: Uint8Array): string {
  // Simple FNV-1a hash for speed (this is NOT for security, just comparison)
  let hash = 0x811c9dc5;
  for (let i = 0; i < key.length; i++) {
    hash ^= key[i];
    hash = Math.imul(hash, 0x01000193);
  }
  // Second pass with offset for more bits
  let hash2 = 0x1a47e90b;
  for (let i = key.length - 1; i >= 0; i--) {
    hash2 ^= key[i];
    hash2 = Math.imul(hash2, 0x01000193);
  }
  return (
    (hash >>> 0).toString(16).padStart(8, "0") +
    (hash2 >>> 0).toString(16).padStart(8, "0")
  );
}

/**
 * Compare two Uint8Array keys for byte-level equality.
 */
function keysAreEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// ChatKeyManager
// ---------------------------------------------------------------------------

/**
 * Centralized manager for chat encryption keys.
 *
 * Usage patterns:
 *
 * ```ts
 * // READ path (decryption) — returns null if key unavailable
 * const key = chatKeyManager.getKeySync(chatId);
 * if (!key) { // show placeholder or queue
 * }
 *
 * // READ path with auto-load from IDB — awaits loading if in progress
 * const key = await chatKeyManager.getKey(chatId);
 *
 * // WRITE path on originating device (new chat creation)
 * const key = chatKeyManager.createKeyForNewChat(chatId);
 *
 * // WRITE path that can wait for the key to arrive
 * await chatKeyManager.withKey(chatId, "encrypt summary", async (key) => {
 *   const encrypted = await encryptWithChatKey(summary, key);
 *   // ...
 * });
 *
 * // Receive key from server broadcast
 * await chatKeyManager.receiveKeyFromServer(chatId, encryptedChatKey);
 * ```
 */
// ---------------------------------------------------------------------------
// BroadcastChannel message types (cross-tab coordination)
// ---------------------------------------------------------------------------

type CrossTabMessage =
  /** A tab called clearAll() — all other tabs should also clear */
  | { type: "clearAll" }
  /** A tab loaded a new key — broadcast so other tabs can warm their cache */
  | { type: "keyLoaded"; chatId: string; encryptedChatKey: string };

export class ChatKeyManager {
  // ---- State ----

  /** The actual decrypted chat keys (chatId → raw AES key bytes) */
  private keys: Map<string, Uint8Array> = new Map();

  /** Per-chat key state */
  private states: Map<string, ChatKeyState> = new Map();

  /** Per-chat key provenance — tracks where each key came from */
  private provenances: Map<string, KeyProvenance> = new Map();

  /** Per-chat loading promises (so multiple concurrent getKey() calls share one load) */
  private loadingPromises: Map<string, Promise<Uint8Array | null>> = new Map();

  /** Operations queued waiting for a key to arrive */
  private pendingOps: Map<string, QueuedOperation[]> = new Map();

  /**
   * Operation lock counter. When > 0, clearAll() is deferred.
   * This prevents multi-tab auth disruptions from wiping the key cache
   * while sendEncryptedStoragePackage() or other critical crypto operations
   * are mid-flight — the root cause of K1→K2 key corruption.
   */
  private criticalOpCount = 0;

  /** If clearAll() was requested while locked, it runs when the lock drops to 0 */
  private deferredClearAll = false;

  /** Flag to prevent broadcast loops: set true while processing a cross-tab keyLoaded message */
  private _receivingFromBroadcast = false;

  /** Callback to fetch encrypted_chat_key from IndexedDB for a given chatId */
  private fetchEncryptedChatKey:
    | ((chatId: string) => Promise<string | null>)
    | null = null;

  /** Hidden chat key decryptor (combined secret) — set by hiddenChatService */
  private hiddenChatKeyDecryptor:
    | ((encryptedKey: string, chatId?: string) => Promise<Uint8Array | null>)
    | null = null;

  /**
   * Callback to persist encrypted_chat_key to IndexedDB for a given chatId.
   * Set during ChatDatabase init via setEncryptedChatKeyPersister().
   * Used by createAndPersistKey() to atomically create + persist keys.
   */
  private persistEncryptedChatKeyFn:
    | ((chatId: string, encryptedChatKey: string) => Promise<void>)
    | null = null;

  /**
   * BroadcastChannel for cross-tab coordination.
   * When this tab clears all keys (logout), other tabs are notified so they
   * also clear — preventing stale decrypted keys from lingering in other tabs.
   * Each tab's own critical-op lock is still respected on the receiving side.
   */
  private broadcastChannel: BroadcastChannel | null = null;

  // ---- Constructor ----

  constructor() {
    // Initialise BroadcastChannel if available (not available in SSR/Node)
    if (typeof BroadcastChannel !== "undefined") {
      this.broadcastChannel = new BroadcastChannel("openmates_crypto_v1");
      this.broadcastChannel.onmessage = (event: MessageEvent) => {
        this.handleCrossTabMessage(event.data as CrossTabMessage);
      };
    }
  }

  // ---- Cross-tab messaging ----

  private handleCrossTabMessage(msg: CrossTabMessage): void {
    if (msg.type === "clearAll") {
      console.debug(
        "[ChatKeyManager] Received cross-tab clearAll — clearing keys",
      );
      // clearAll() respects the critical-op lock: if THIS tab has a critical
      // op running, the clear will be deferred until the op finishes.
      this.clearAll({ broadcast: false });
    }
    if (msg.type === "keyLoaded") {
      // Cross-tab key notification: warm our cache only if this chat has
      // pending operations waiting for a key. If no pending work exists,
      // skip the async decrypt — the lazy-load path (getKey/loadKeyFromDB)
      // will handle it when needed. This prevents Pitfall 4: unnecessary
      // async work for every keyLoaded broadcast.
      if (this.keys.has(msg.chatId)) {
        // Already have this key in memory — no action needed
        return;
      }
      const pending = this.pendingOps.get(msg.chatId);
      if (!pending || pending.length === 0) {
        // No pending operations — lazy-load when needed
        return;
      }
      // Pending ops exist — warm the cache by processing the encrypted key
      this._receivingFromBroadcast = true;
      this.receiveKeyFromServer(msg.chatId, msg.encryptedChatKey)
        .catch((err) => {
          console.warn(
            `[ChatKeyManager] Failed to process cross-tab keyLoaded for ${msg.chatId}:`,
            err,
          );
        })
        .finally(() => {
          this._receivingFromBroadcast = false;
        });
    }
  }

  /**
   * Broadcast a keyLoaded message to other tabs so they can warm their cache
   * if they have pending operations for this chat.
   * No-op when BroadcastChannel is unavailable (SSR) or when the key was
   * received via cross-tab broadcast (prevents infinite loops).
   */
  private broadcastKeyLoaded(chatId: string, encryptedChatKey: string): void {
    if (!this.broadcastChannel) return;
    if (this._receivingFromBroadcast) return;
    this.broadcastChannel.postMessage({
      type: "keyLoaded",
      chatId,
      encryptedChatKey,
    } satisfies CrossTabMessage);
  }

  // ---- Initialization ----

  /**
   * Register the function that fetches encrypted_chat_key from IndexedDB.
   * Called once during ChatDatabase initialization.
   */
  setEncryptedChatKeyFetcher(
    fetcher: (chatId: string) => Promise<string | null>,
  ): void {
    this.fetchEncryptedChatKey = fetcher;
  }

  /**
   * Register the hidden chat key decryptor (combined secret).
   * Called by hiddenChatService when the combined secret is available.
   */
  setHiddenChatKeyDecryptor(
    decryptor:
      | ((encryptedKey: string, chatId?: string) => Promise<Uint8Array | null>)
      | null,
  ): void {
    this.hiddenChatKeyDecryptor = decryptor;
  }

  /**
   * Register the function that persists encrypted_chat_key to IndexedDB.
   * Called once during ChatDatabase initialization.
   * Used by createAndPersistKey() to atomically create + persist keys.
   */
  setEncryptedChatKeyPersister(
    persister: (chatId: string, encryptedChatKey: string) => Promise<void>,
  ): void {
    this.persistEncryptedChatKeyFn = persister;
  }

  // ---- Core Key Access ----

  /**
   * Get a chat key synchronously from the in-memory cache.
   *
   * Returns null if the key is not loaded yet. This is the SAFE replacement
   * for the old getOrGenerateChatKey() — it NEVER generates a random key.
   *
   * Use this for:
   * - Decryption in render paths (show placeholder if null)
   * - Quick checks before async operations
   */
  getKeySync(chatId: string): Uint8Array | null {
    return this.keys.get(chatId) ?? null;
  }

  /**
   * Get a chat key, loading it from IndexedDB if necessary.
   *
   * Flow:
   * 1. If key is in memory → return immediately
   * 2. If key is currently loading → await the existing load
   * 3. If key is unloaded → trigger load from IDB, await, return
   * 4. If key load failed → return null
   *
   * NEVER generates a new key. Returns null if the key cannot be obtained.
   */
  async getKey(chatId: string): Promise<Uint8Array | null> {
    // Fast path: key already in memory
    const cached = this.keys.get(chatId);
    if (cached) return cached;

    const state = this.states.get(chatId) ?? "unloaded";

    // If already loading, await the existing promise
    if (state === "loading") {
      const existing = this.loadingPromises.get(chatId);
      if (existing) return existing;
    }

    // If failed previously, don't retry automatically
    // (caller can call reloadKey() to retry)
    if (state === "failed") return null;

    // Trigger load from IDB
    return this.loadKeyFromDB(chatId);
  }

  /**
   * Create a NEW chat key for a chat being created on THIS device.
   *
   * This is the ONLY way to generate a new key in the entire codebase.
   * It asserts that no key already exists for this chat — calling this
   * for an existing chat is a programming error.
   *
   * @throws Error if a key already exists for this chatId
   */
  createKeyForNewChat(chatId: string): Uint8Array {
    const existing = this.keys.get(chatId);
    if (existing) {
      // Key already exists — this is fine if it was created by us in this session
      // (e.g. sendHandlers called twice due to React re-render)
      console.warn(
        `[ChatKeyManager] createKeyForNewChat called but key already exists for ${chatId} — returning existing key`,
      );
      return existing;
    }

    const newKey = _generateChatKeyInternal();
    this.setKeyWithProvenance(chatId, newKey, "created");

    console.info(
      `[ChatKeyManager] Created new chat key for originator chat ${chatId}`,
    );

    // Flush any pending operations (unlikely for a brand-new chat, but safe)
    this.flushPendingOps(chatId, newKey);

    return newKey;
  }

  /**
   * Atomically create a new chat key AND persist the encrypted form to IndexedDB.
   * This is the preferred way to create keys for new chats — it guarantees the key
   * is persisted before any data is encrypted with it.
   *
   * Returns both the raw key (for immediate encryption) and the encrypted form
   * (for inclusion in the chat record sent to server).
   *
   * @throws Error if master key is unavailable or persistence callback not registered
   */
  async createAndPersistKey(chatId: string): Promise<{
    chatKey: Uint8Array;
    encryptedChatKey: string;
  }> {
    // Step 1: Create the key (idempotent — returns existing if already created)
    const chatKey = this.createKeyForNewChat(chatId);

    // Step 2: Encrypt with master key for server/IDB storage
    const encryptedChatKey = await encryptChatKeyWithMasterKey(chatKey);
    if (!encryptedChatKey) {
      throw new Error(
        `[ChatKeyManager] Failed to encrypt chat key for ${chatId} — master key unavailable`,
      );
    }

    // Step 3: Persist to IndexedDB (if persister is registered)
    if (this.persistEncryptedChatKeyFn) {
      await this.persistEncryptedChatKeyFn(chatId, encryptedChatKey);
      console.info(
        `[ChatKeyManager] ✅ Created and persisted key for chat ${chatId}`,
      );
    } else {
      console.warn(
        `[ChatKeyManager] Key created for ${chatId} but no persister registered — encrypted_chat_key not saved to IDB`,
      );
    }

    // Broadcast to other tabs so they can warm cache if needed
    this.broadcastKeyLoaded(chatId, encryptedChatKey);

    return { chatKey, encryptedChatKey };
  }

  /**
   * Create and persist a chat key with Web Locks mutex for cross-tab safety.
   *
   * Wraps createAndPersistKey() with an exclusive Web Lock per chatId so that
   * only one tab can generate a key for a given chat at a time. This prevents
   * the #1 bug pattern: two tabs generating different keys for the same chat
   * (KEYS-01/KEYS-02).
   *
   * Inside the lock callback:
   * 1. Re-checks in-memory cache (another tab may have created while we waited)
   * 2. Re-checks IDB (another tab may have persisted)
   * 3. Checks deferredClearAll (user logging out — abort key generation)
   * 4. Only then generates a new key
   *
   * Fallback: If navigator.locks is unavailable (SSR/old browser) or times out
   * (10s), falls back to the unlocked createAndPersistKey() which still has
   * the immutability guard as a safety net.
   *
   * Lock naming: `om-chatkey-{chatId}` (exclusive mode, one holder at a time)
   *
   * @param chatId - Chat identifier to create/get key for
   * @returns The raw key and its encrypted form for server storage
   * @throws Error if deferredClearAll is true (logout in progress)
   */
  async createAndPersistKeyLocked(chatId: string): Promise<{
    chatKey: Uint8Array;
    encryptedChatKey: string;
  }> {
    // Guard: browser without Web Locks (SSR, older browsers)
    if (typeof navigator === "undefined" || !navigator.locks) {
      return this.createAndPersistKey(chatId);
    }

    const WEB_LOCK_TIMEOUT_MS = 10_000;
    const LOCK_NAME = `om-chatkey-${chatId}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), WEB_LOCK_TIMEOUT_MS);

    try {
      return await navigator.locks.request(
        LOCK_NAME,
        { signal: controller.signal },
        async () => {
          // Re-check: another tab may have created the key while we waited
          const existing = this.keys.get(chatId);
          if (existing) {
            const encryptedChatKey = await encryptChatKeyWithMasterKey(existing);
            return {
              chatKey: existing,
              encryptedChatKey: encryptedChatKey!,
            };
          }

          // Also check IDB in case another tab persisted but we haven't loaded
          const loaded = await this.getKey(chatId);
          if (loaded) {
            const encryptedChatKey = await encryptChatKeyWithMasterKey(loaded);
            return {
              chatKey: loaded,
              encryptedChatKey: encryptedChatKey!,
            };
          }

          // Check deferredClearAll — if user is logging out, abort key generation
          // (Pitfall 5: don't create keys into a cache about to be cleared)
          if (this.deferredClearAll) {
            throw new Error(
              `[ChatKeyManager] Key generation aborted: clearAll pending for ${chatId}`,
            );
          }

          // No key exists anywhere — safe to generate
          return this.createAndPersistKey(chatId);
        },
      );
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        console.error(
          `[ChatKeyManager] Web Lock timeout for key creation: ${chatId} — falling back to unlocked path`,
        );
        // Fallback: attempt without lock (immutability guard is the safety net)
        return this.createAndPersistKey(chatId);
      }
      throw err;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  // ---- Key Loading ----

  /**
   * Load a key from IndexedDB's encrypted_chat_key field.
   * Sets state to 'loading' during the operation.
   */
  private async loadKeyFromDB(chatId: string): Promise<Uint8Array | null> {
    if (!this.fetchEncryptedChatKey) {
      console.warn(
        `[ChatKeyManager] No encrypted chat key fetcher registered, cannot load key for ${chatId}`,
      );
      return null;
    }

    this.states.set(chatId, "loading");

    const loadPromise = (async (): Promise<Uint8Array | null> => {
      try {
        const encryptedKey = await this.fetchEncryptedChatKey!(chatId);
        if (!encryptedKey) {
          // No encrypted_chat_key in DB — this chat might be brand new or not synced yet
          this.states.set(chatId, "unloaded");
          return null;
        }

        // Try master key decryption first
        const chatKey = await decryptChatKeyWithMasterKey(encryptedKey);
        if (chatKey) {
          this.setKeyWithProvenance(chatId, chatKey, "master_key");
          this.flushPendingOps(chatId, chatKey);
          return chatKey;
        }

        // Master key failed — try hidden chat decryptor if available
        if (this.hiddenChatKeyDecryptor) {
          const hiddenKey = await this.hiddenChatKeyDecryptor(
            encryptedKey,
            chatId,
          );
          if (hiddenKey) {
            this.setKeyWithProvenance(chatId, hiddenKey, "hidden_chat");
            this.flushPendingOps(chatId, hiddenKey);
            return hiddenKey;
          }
        }

        // Both failed
        console.warn(
          `[ChatKeyManager] Failed to decrypt chat key for ${chatId} — ` +
            `master key and hidden chat decryptors both returned null`,
        );
        this.states.set(chatId, "failed");
        return null;
      } catch (error) {
        console.error(
          `[ChatKeyManager] Error loading key for ${chatId}:`,
          error,
        );
        this.states.set(chatId, "failed");
        return null;
      } finally {
        this.loadingPromises.delete(chatId);
      }
    })();

    this.loadingPromises.set(chatId, loadPromise);
    return loadPromise;
  }

  /**
   * Force-reload a key from IndexedDB (e.g., after hidden chat unlock).
   *
   * Formal state machine transition: failed -> loading -> ready|failed
   * Also supports: ready -> loading -> ready|failed (for key refresh)
   *
   * Re-entrancy safe: if called while a load is already in flight for this
   * chat, the existing loading promise is discarded and a fresh load starts.
   * This prevents deadlock when reloadKey is called from a retry path while
   * a previous load is still pending.
   *
   * @param chatId - Chat identifier to reload the key for
   * @returns The raw key if successfully loaded, null otherwise
   */
  async reloadKey(chatId: string): Promise<Uint8Array | null> {
    this.states.set(chatId, "unloaded");
    this.keys.delete(chatId);
    this.provenances.delete(chatId);
    this.loadingPromises.delete(chatId);
    return this.loadKeyFromDB(chatId);
  }

  // ---- Key Injection (from server broadcasts) ----

  /**
   * Receive an encrypted chat key from a server broadcast and decrypt it.
   *
   * Called when:
   * - ai_typing_started arrives with encrypted_chat_key
   * - new_chat_message arrives with encrypted_chat_key
   * - phased sync delivers chat metadata
   *
   * If the key is already loaded and matches, this is a no-op.
   * If the key is new, it's decrypted and cached, and pending ops are flushed.
   */
  async receiveKeyFromServer(
    chatId: string,
    encryptedChatKey: string,
  ): Promise<Uint8Array | null> {
    const existing = this.keys.get(chatId);
    if (existing) {
      // Key already loaded — verify it matches the server key instead of
      // silently skipping. A mismatch here means the server has a different key
      // than what we have locally, which is the root cause of decryption failures.
      try {
        const serverKey = await decryptChatKeyWithMasterKey(encryptedChatKey);
        if (serverKey && !keysAreEqual(existing, serverKey)) {
          const existingFp = computeKeyFingerprint(existing);
          const serverFp = computeKeyFingerprint(serverKey);
          console.error(
            `[ChatKeyManager] ⚠️ KEY CONFLICT in receiveKeyFromServer for chat ${chatId}! ` +
              `Local key fp=${existingFp} differs from server key fp=${serverFp}. ` +
              `Server key wins as source of truth — locally encrypted data may need re-encryption.`,
          );
          // Server is the source of truth — accept the server key
          this.setKeyWithProvenance(chatId, serverKey, "server_sync");
          return serverKey;
        }
      } catch {
        // Decryption of server key failed — keep existing
      }
      return existing;
    }

    try {
      const chatKey = await decryptChatKeyWithMasterKey(encryptedChatKey);
      if (chatKey) {
        this.setKeyWithProvenance(chatId, chatKey, "server_sync");
        console.debug(
          `[ChatKeyManager] Received and cached key from server for chat ${chatId}`,
        );
        this.flushPendingOps(chatId, chatKey);
        // Broadcast to other tabs (loop-guarded by _receivingFromBroadcast)
        this.broadcastKeyLoaded(chatId, encryptedChatKey);
        return chatKey;
      }

      // Decryption failed — try hidden chat decryptor
      if (this.hiddenChatKeyDecryptor) {
        const hiddenKey = await this.hiddenChatKeyDecryptor(
          encryptedChatKey,
          chatId,
        );
        if (hiddenKey) {
          this.setKeyWithProvenance(chatId, hiddenKey, "hidden_chat");
          this.flushPendingOps(chatId, hiddenKey);
          return hiddenKey;
        }
      }

      console.warn(
        `[ChatKeyManager] Failed to decrypt server-provided key for chat ${chatId}`,
      );
      return null;
    } catch (error) {
      console.error(
        `[ChatKeyManager] Error decrypting server key for ${chatId}:`,
        error,
      );
      return null;
    }
  }

  /**
   * Directly inject a raw chat key (already decrypted).
   *
   * Used for:
   * - Share link keys (decrypted from URL fragment)
   * - Keys loaded from sharedChatKeyStorage (unauthenticated users)
   * - Bulk load during app initialization
   *
   * @param chatId - Chat identifier
   * @param chatKey - Raw AES key bytes
   * @param source - Where this key came from (for provenance tracking)
   * @param force - If true, allow overwriting an existing key (use with caution)
   * @returns true if the key was accepted, false if rejected (existing key differs)
   */
  injectKey(
    chatId: string,
    chatKey: Uint8Array,
    source: KeySource = "injected",
    force = false,
  ): boolean {
    const existing = this.keys.get(chatId);

    if (existing) {
      if (keysAreEqual(existing, chatKey)) {
        // Same key — update provenance if the new source is more authoritative
        // Priority: master_key > server_sync > created > hidden_chat > shared_storage > share_link > injected
        const currentProv = this.provenances.get(chatId);
        const SOURCE_PRIORITY: Record<KeySource, number> = {
          master_key: 100,
          server_sync: 90,
          created: 80,
          hidden_chat: 70,
          bulk_init: 60,
          shared_storage: 30,
          share_link: 20,
          injected: 10,
        };
        if (
          !currentProv ||
          SOURCE_PRIORITY[source] > SOURCE_PRIORITY[currentProv.source]
        ) {
          this.provenances.set(chatId, {
            source,
            timestamp: Date.now(),
            keyFingerprint: computeKeyFingerprint(chatKey),
          });
        }
        return true; // Same key, no-op
      }

      // DIFFERENT key — this is the dangerous case
      if (!force) {
        const existingProv = this.provenances.get(chatId);
        const existingFp = computeKeyFingerprint(existing);
        const newFp = computeKeyFingerprint(chatKey);
        console.error(
          `[ChatKeyManager] BLOCKED key replacement for chat ${chatId}! ` +
            `Existing key (fp=${existingFp}, source=${existingProv?.source ?? "unknown"}) ` +
            `would be replaced by different key (fp=${newFp}, source=${source}). ` +
            `This prevents silent key corruption. Use force=true to override.`,
        );
        return false; // Reject the replacement
      }

      // Force override — log prominently
      const existingFp = computeKeyFingerprint(existing);
      const newFp = computeKeyFingerprint(chatKey);
      console.warn(
        `[ChatKeyManager] FORCE replacing key for chat ${chatId}: ` +
          `old fp=${existingFp}, new fp=${newFp}, source=${source}`,
      );
    }

    this.setKeyWithProvenance(chatId, chatKey, source);
    this.flushPendingOps(chatId, chatKey);
    return true;
  }

  // ---- Internal Key Setting ----

  /**
   * Internal: set a key with provenance tracking.
   * Bypasses the immutability guard — callers must validate first.
   */
  private setKeyWithProvenance(
    chatId: string,
    chatKey: Uint8Array,
    source: KeySource,
  ): void {
    this.keys.set(chatId, chatKey);
    this.states.set(chatId, "ready");
    this.provenances.set(chatId, {
      source,
      timestamp: Date.now(),
      keyFingerprint: computeKeyFingerprint(chatKey),
    });
    // Clear decryption failure cache for this chat — new key may succeed
    // where the old one failed (key rotation, re-encryption, etc.)
    clearDecryptionFailureCache(chatId);
  }

  // ---- Queue-and-Flush ----

  /**
   * Queue an operation that needs a chat key which isn't available yet.
   *
   * The operation will be executed automatically when the key arrives
   * (via receiveKeyFromServer, loadKeyFromDB, or injectKey).
   *
   * If the key doesn't arrive within QUEUE_TIMEOUT_MS, the operation's
   * reject callback is called with a timeout error.
   *
   * Returns a Promise that resolves when the operation completes.
   */
  queueOperation(
    chatId: string,
    label: string,
    execute: (chatKey: Uint8Array) => Promise<void>,
  ): Promise<void> {
    // If key is already available, execute immediately
    const existingKey = this.keys.get(chatId);
    if (existingKey) {
      return execute(existingKey);
    }

    const queue = this.pendingOps.get(chatId) ?? [];

    if (queue.length >= MAX_QUEUE_SIZE) {
      console.error(
        `[ChatKeyManager] Queue full for chat ${chatId} (${MAX_QUEUE_SIZE} ops). ` +
          `Rejecting new operation: ${label}`,
      );
      return Promise.reject(
        new Error(`Chat key queue full for ${chatId}: ${label}`),
      );
    }

    return new Promise<void>((resolve, reject) => {
      const op: QueuedOperation = {
        label,
        execute: async (key: Uint8Array) => {
          try {
            await execute(key);
            resolve();
          } catch (error) {
            reject(error);
          }
        },
        reject,
      };

      queue.push(op);
      this.pendingOps.set(chatId, queue);

      console.debug(
        `[ChatKeyManager] Queued operation "${label}" for chat ${chatId} ` +
          `(${queue.length} ops pending)`,
      );

      // Set timeout to reject if key never arrives
      setTimeout(() => {
        const currentQueue = this.pendingOps.get(chatId);
        if (currentQueue) {
          const idx = currentQueue.indexOf(op);
          if (idx !== -1) {
            currentQueue.splice(idx, 1);
            if (currentQueue.length === 0) this.pendingOps.delete(chatId);
            console.warn(
              `[ChatKeyManager] Operation "${label}" for chat ${chatId} timed out after ${QUEUE_TIMEOUT_MS}ms`,
            );
            reject(
              new Error(
                `Chat key not available for ${chatId} within ${QUEUE_TIMEOUT_MS}ms: ${label}`,
              ),
            );
          }
        }
      }, QUEUE_TIMEOUT_MS);
    });
  }

  /**
   * Execute an async callback with the chat key, or queue it if the key isn't ready.
   *
   * This is the primary API for write paths that need a key:
   *
   * ```ts
   * await chatKeyManager.withKey(chatId, "encrypt follow-ups", async (key) => {
   *   const encrypted = await encryptWithChatKey(data, key);
   *   // send to server...
   * });
   * ```
   *
   * If the key is available synchronously, the callback runs immediately.
   * If not, a load from IDB is attempted, and if that fails, the operation is queued.
   */
  async withKey(
    chatId: string,
    label: string,
    callback: (chatKey: Uint8Array) => Promise<void>,
  ): Promise<void> {
    // Fast path: key in memory
    const cached = this.keys.get(chatId);
    if (cached) {
      return callback(cached);
    }

    // Try loading from IDB
    const loaded = await this.getKey(chatId);
    if (loaded) {
      return callback(loaded);
    }

    // Key not available — queue the operation
    return this.queueOperation(chatId, label, callback);
  }

  /**
   * Flush all queued operations for a chat once its key becomes available.
   */
  private flushPendingOps(chatId: string, chatKey: Uint8Array): void {
    const queue = this.pendingOps.get(chatId);
    if (!queue || queue.length === 0) return;

    console.info(
      `[ChatKeyManager] Flushing ${queue.length} pending operations for chat ${chatId}`,
    );

    // Take and clear the queue before executing (prevents re-entrancy issues)
    this.pendingOps.delete(chatId);

    for (const op of queue) {
      op.execute(chatKey).catch((error) => {
        console.error(
          `[ChatKeyManager] Queued operation "${op.label}" failed for chat ${chatId}:`,
          error,
        );
      });
    }
  }

  // ---- Encrypted Chat Key Generation ----

  /**
   * Get the encrypted_chat_key (wrapped with master key) for server storage.
   * If no encrypted form exists yet, creates one from the in-memory key.
   *
   * Returns null if no key is available for this chat.
   */
  async getEncryptedChatKey(chatId: string): Promise<string | null> {
    const key = this.keys.get(chatId);
    if (!key) return null;

    try {
      return await encryptChatKeyWithMasterKey(key);
    } catch (error) {
      console.error(
        `[ChatKeyManager] Failed to encrypt chat key for server storage (chat ${chatId}):`,
        error,
      );
      return null;
    }
  }

  // ---- Cleanup ----

  /**
   * Remove a single chat key from memory.
   * Used when locking hidden chats or removing a chat.
   */
  removeKey(chatId: string): void {
    // Clear cached CryptoKey for this chat key's fingerprint
    const key = this.keys.get(chatId);
    if (key) {
      clearCryptoKeyCache(computeKeyFingerprint(key));
    }
    this.keys.delete(chatId);
    this.states.delete(chatId);
    this.provenances.delete(chatId);
    this.loadingPromises.delete(chatId);
    // Reject any pending operations
    const queue = this.pendingOps.get(chatId);
    if (queue) {
      for (const op of queue) {
        op.reject(new Error(`Chat key removed for ${chatId}: ${op.label}`));
      }
      this.pendingOps.delete(chatId);
    }
  }

  // ---- Critical Operation Lock ----

  /**
   * Acquire a lock that prevents clearAll() from running.
   * Call this before starting a critical crypto operation (e.g. sendEncryptedStoragePackage).
   * MUST be paired with releaseCriticalOp().
   */
  acquireCriticalOp(): void {
    this.criticalOpCount++;
    if (this.criticalOpCount === 1) {
      console.debug("[ChatKeyManager] Critical crypto operation lock acquired");
    }
  }

  /**
   * Release the critical operation lock.
   * If clearAll() was deferred, it runs now (when count drops to 0).
   */
  releaseCriticalOp(): void {
    this.criticalOpCount = Math.max(0, this.criticalOpCount - 1);
    if (this.criticalOpCount === 0 && this.deferredClearAll) {
      console.warn(
        "[ChatKeyManager] Executing deferred clearAll() after critical op completed",
      );
      this.deferredClearAll = false;
      // broadcast=false: already sent when clearAll() was first called
      this.clearAll({ broadcast: false });
    }
  }

  /**
   * Clear ALL chat keys from memory.
   * Called on logout, forced logout, or session expiry.
   *
   * If a critical crypto operation is in progress (acquireCriticalOp),
   * the clear is DEFERRED until the operation completes. This prevents
   * the multi-tab auth disruption from wiping keys mid-flight, which
   * causes sendEncryptedStoragePackage to generate a new key (K2) and
   * corrupt messages already encrypted with the original key (K1).
   *
   * By default also broadcasts to other tabs via BroadcastChannel so they
   * also clear their in-memory keys (cross-tab logout safety).
   */
  clearAll({ broadcast = true }: { broadcast?: boolean } = {}): void {
    if (this.criticalOpCount > 0) {
      console.warn(
        `[ChatKeyManager] clearAll() DEFERRED — ${this.criticalOpCount} critical crypto op(s) in progress. ` +
          `Keys will be cleared when all operations complete.`,
      );
      this.deferredClearAll = true;
      // Still broadcast immediately so other tabs begin their own deferred clear
      if (broadcast) {
        this.broadcastChannel?.postMessage({ type: "clearAll" } satisfies CrossTabMessage);
      }
      return;
    }

    // Broadcast BEFORE clearing so other tabs receive the message while this
    // tab is still alive (prevents timing issues on tab close)
    if (broadcast) {
      this.broadcastChannel?.postMessage({ type: "clearAll" } satisfies CrossTabMessage);
    }

    // Reject all pending operations
    for (const [chatId, queue] of Array.from(this.pendingOps.entries())) {
      for (const op of queue) {
        op.reject(
          new Error(
            `All chat keys cleared (logout) for ${chatId}: ${op.label}`,
          ),
        );
      }
    }

    this.keys.clear();
    this.states.clear();
    this.provenances.clear();
    this.loadingPromises.clear();
    this.pendingOps.clear();
    this.deferredClearAll = false;
    // Clear all cached CryptoKey objects since all raw keys are gone
    clearCryptoKeyCache();
    // Clear decryption failure cache — all keys gone, fresh start on re-login
    clearDecryptionFailureCache();
    console.debug("[ChatKeyManager] All keys cleared");
  }

  // ---- State Inspection (for debug tools) ----

  /**
   * Total number of keys currently held in memory.
   */
  size(): number {
    return this.keys.size;
  }

  /**
   * Get the current state of a chat key.
   */
  getState(chatId: string): ChatKeyState {
    return this.states.get(chatId) ?? "unloaded";
  }

  /**
   * Check if a key is loaded and ready.
   */
  hasKey(chatId: string): boolean {
    return this.keys.has(chatId);
  }

  /**
   * Get the number of pending operations for a chat.
   */
  getPendingOpCount(chatId: string): number {
    return this.pendingOps.get(chatId)?.length ?? 0;
  }

  /**
   * Get summary info for all loaded keys (for debug dashboard).
   */
  getDebugInfo(): {
    totalKeys: number;
    totalPendingOps: number;
    keys: ChatKeyInfo[];
  } {
    const keys: ChatKeyInfo[] = [];
    const allChatIds = new Set([
      ...Array.from(this.keys.keys()),
      ...Array.from(this.states.keys()),
      ...Array.from(this.pendingOps.keys()),
    ]);

    for (const chatId of Array.from(allChatIds)) {
      keys.push({
        chatId,
        state: this.states.get(chatId) ?? "unloaded",
        keyLengthBytes: this.keys.get(chatId)?.length ?? null,
        pendingOps: this.pendingOps.get(chatId)?.length ?? 0,
        provenance: this.provenances.get(chatId) ?? null,
      });
    }

    return {
      totalKeys: this.keys.size,
      totalPendingOps: Array.from(this.pendingOps.values()).reduce(
        (sum, q) => sum + q.length,
        0,
      ),
      keys,
    };
  }

  /**
   * Get provenance info for a specific chat key.
   */
  getProvenance(chatId: string): KeyProvenance | null {
    return this.provenances.get(chatId) ?? null;
  }

  /**
   * Bulk-load all keys during app initialization.
   * Called by loadChatKeysFromDatabase() after iterating all chats in IDB.
   *
   * @param entries - Array of [chatId, chatKey] pairs
   */
  bulkInject(
    entries: Array<[string, Uint8Array]>,
    source: KeySource = "bulk_init",
  ): void {
    let injected = 0;
    let skipped = 0;
    for (const [chatId, chatKey] of entries) {
      // Use injectKey so the immutability guard applies — a key already loaded
      // from a higher-priority source (master_key, server_sync) will not be
      // silently overwritten by a bulk load.
      const accepted = this.injectKey(chatId, chatKey, source);
      if (accepted) injected++;
      else skipped++;
    }
    console.debug(
      `[ChatKeyManager] Bulk-injected ${injected} chat keys (source=${source})` +
        (skipped > 0 ? `, skipped ${skipped} (already loaded from higher-priority source)` : ""),
    );
  }
}

// ---------------------------------------------------------------------------
// Singleton
// ---------------------------------------------------------------------------

/**
 * The global ChatKeyManager instance.
 * Import this from anywhere in the app to access chat keys.
 */
export const chatKeyManager = new ChatKeyManager();
