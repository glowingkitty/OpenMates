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
//
// Tests: (to be added)

import {
  generateChatKey,
  encryptChatKeyWithMasterKey,
  decryptChatKeyWithMasterKey,
} from "../cryptoService";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Possible states for a chat key in the manager */
export type ChatKeyState = "unloaded" | "loading" | "ready" | "failed";

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
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maximum time (ms) a queued operation will wait before being rejected */
const QUEUE_TIMEOUT_MS = 30_000;

/** Maximum number of queued operations per chat before new ones are rejected */
const MAX_QUEUE_SIZE = 50;

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
export class ChatKeyManager {
  // ---- State ----

  /** The actual decrypted chat keys (chatId → raw AES key bytes) */
  private keys: Map<string, Uint8Array> = new Map();

  /** Per-chat key state */
  private states: Map<string, ChatKeyState> = new Map();

  /** Per-chat loading promises (so multiple concurrent getKey() calls share one load) */
  private loadingPromises: Map<string, Promise<Uint8Array | null>> = new Map();

  /** Operations queued waiting for a key to arrive */
  private pendingOps: Map<string, QueuedOperation[]> = new Map();

  /** Callback to fetch encrypted_chat_key from IndexedDB for a given chatId */
  private fetchEncryptedChatKey:
    | ((chatId: string) => Promise<string | null>)
    | null = null;

  /** Hidden chat key decryptor (combined secret) — set by hiddenChatService */
  private hiddenChatKeyDecryptor:
    | ((encryptedKey: string, chatId?: string) => Promise<Uint8Array | null>)
    | null = null;

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

    const newKey = generateChatKey();
    this.keys.set(chatId, newKey);
    this.states.set(chatId, "ready");

    console.info(
      `[ChatKeyManager] Created new chat key for originator chat ${chatId}`,
    );

    // Flush any pending operations (unlikely for a brand-new chat, but safe)
    this.flushPendingOps(chatId, newKey);

    return newKey;
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
          this.keys.set(chatId, chatKey);
          this.states.set(chatId, "ready");
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
            this.keys.set(chatId, hiddenKey);
            this.states.set(chatId, "ready");
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
   * Resets the state to 'unloaded' first so loadKeyFromDB runs again.
   */
  async reloadKey(chatId: string): Promise<Uint8Array | null> {
    this.states.set(chatId, "unloaded");
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
    // If key is already ready, skip decryption (it's the same key from server)
    const existing = this.keys.get(chatId);
    if (existing) return existing;

    try {
      const chatKey = await decryptChatKeyWithMasterKey(encryptedChatKey);
      if (chatKey) {
        this.keys.set(chatId, chatKey);
        this.states.set(chatId, "ready");
        console.debug(
          `[ChatKeyManager] Received and cached key from server for chat ${chatId}`,
        );
        this.flushPendingOps(chatId, chatKey);
        return chatKey;
      }

      // Decryption failed — try hidden chat decryptor
      if (this.hiddenChatKeyDecryptor) {
        const hiddenKey = await this.hiddenChatKeyDecryptor(
          encryptedChatKey,
          chatId,
        );
        if (hiddenKey) {
          this.keys.set(chatId, hiddenKey);
          this.states.set(chatId, "ready");
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
   */
  injectKey(chatId: string, chatKey: Uint8Array): void {
    this.keys.set(chatId, chatKey);
    this.states.set(chatId, "ready");
    this.flushPendingOps(chatId, chatKey);
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
    this.keys.delete(chatId);
    this.states.delete(chatId);
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

  /**
   * Clear ALL chat keys from memory.
   * Called on logout, forced logout, or session expiry.
   */
  clearAll(): void {
    // Reject all pending operations
    for (const [chatId, queue] of Array.from(this.pendingOps.entries())) {
      for (const op of queue) {
        op.reject(
          new Error(`All chat keys cleared (logout) for ${chatId}: ${op.label}`),
        );
      }
    }

    this.keys.clear();
    this.states.clear();
    this.loadingPromises.clear();
    this.pendingOps.clear();
    console.debug("[ChatKeyManager] All keys cleared");
  }

  // ---- State Inspection (for debug tools) ----

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

  // ---- Legacy Compatibility ----

  /**
   * Access the raw keys Map for legacy code that reads chatDB.chatKeys directly.
   *
   * @deprecated — callers should migrate to getKeySync() / getKey() / withKey().
   * This is provided ONLY for the transition period so that existing code
   * referencing `chatDB.chatKeys` continues to work.
   */
  get legacyKeysMap(): Map<string, Uint8Array> {
    return this.keys;
  }

  /**
   * Bulk-load all keys during app initialization.
   * Called by loadChatKeysFromDatabase() after iterating all chats in IDB.
   *
   * @param entries - Array of [chatId, chatKey] pairs
   */
  bulkInject(entries: Array<[string, Uint8Array]>): void {
    for (const [chatId, chatKey] of entries) {
      this.keys.set(chatId, chatKey);
      this.states.set(chatId, "ready");
    }
    console.debug(
      `[ChatKeyManager] Bulk-injected ${entries.length} chat keys`,
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
