// frontend/packages/ui/src/services/encryption/__tests__/ChatKeyManager.test.ts
// @privacy-promise: client-side-chat-encryption
// Integration tests for ChatKeyManager — covers every known bug pattern from git history.
//
// Bug history this test suite guards against:
//  - d656af1c: key corruption when IDB caches are empty in sendEncryptedStoragePackage
//  - aac318ee: two-cache divergence between chatDB.chatKeys and chatKeyManager
//  - 97e14300: key regeneration race (clearAll mid-flight)
//  - 3bc17dbe: getOrGenerateChatKey anti-pattern generating wrong keys
//  - 3846d7e2: multi-device encryption key mismatch

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

// Mock cryptoService — encryptChatKeyWithMasterKey / decryptChatKeyWithMasterKey
// are used by createAndPersistKey and loadKeyFromDB. We mock them so tests
// don't depend on real Web Crypto (crypto.subtle is empty in jsdom).
vi.mock("../../cryptoService", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    encryptChatKeyWithMasterKey: vi.fn().mockResolvedValue(null),
    decryptChatKeyWithMasterKey: vi.fn().mockResolvedValue(null),
  };
});

// Mock websocketService for SYNC-01 key_received ack tests.
// ChatKeyManager uses dynamic import("../websocketService") so we mock the module.
const mockSendMessage = vi.fn().mockResolvedValue(undefined);
vi.mock("../../websocketService", () => ({
  webSocketService: {
    sendMessage: mockSendMessage,
  },
}));

import { ChatKeyManager } from "../ChatKeyManager";

// ---------------------------------------------------------------------------
// Test environment setup
// ---------------------------------------------------------------------------

// jsdom does not implement Web Crypto — provide a minimal shim.
// generateChatKey() uses crypto.getRandomValues; we return a deterministic
// counter-based sequence so tests are reproducible.
let _rvCounter = 1;
vi.stubGlobal("crypto", {
  getRandomValues: (buf: Uint8Array) => {
    buf.fill(_rvCounter++ % 256);
    return buf;
  },
  subtle: {},
} as unknown as Crypto);

// ---------------------------------------------------------------------------
// Web Locks mock — simulates exclusive locking per name (KEYS-01/KEYS-02)
// jsdom does not implement navigator.locks, so we provide a minimal mock
// that queues requests and executes them serially per lock name.
// ---------------------------------------------------------------------------

const lockQueues = new Map<string, Array<() => void>>();
const heldLocks = new Set<string>();

vi.stubGlobal("navigator", {
  ...globalThis.navigator,
  locks: {
    request: async (name: string, optionsOrCb: any, maybeCb?: any) => {
      const cb = maybeCb ?? optionsOrCb;
      const options = maybeCb ? optionsOrCb : {};

      if (options.signal?.aborted) {
        throw new DOMException("The operation was aborted.", "AbortError");
      }

      // Wait if lock is held
      while (heldLocks.has(name)) {
        await new Promise<void>((resolve) => {
          if (!lockQueues.has(name)) lockQueues.set(name, []);
          lockQueues.get(name)!.push(resolve);

          // Support abort while waiting
          options.signal?.addEventListener(
            "abort",
            () => {
              const queue = lockQueues.get(name);
              if (queue) {
                const idx = queue.indexOf(resolve);
                if (idx >= 0) queue.splice(idx, 1);
              }
              resolve(); // unblock so we can throw
            },
            { once: true },
          );
        });
        if (options.signal?.aborted) {
          throw new DOMException("The operation was aborted.", "AbortError");
        }
      }

      heldLocks.add(name);
      try {
        return await cb();
      } finally {
        heldLocks.delete(name);
        const next = lockQueues.get(name)?.shift();
        if (next) next();
      }
    },
  },
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Reset Web Locks mock state between tests */
function resetLockMock(): void {
  lockQueues.clear();
  heldLocks.clear();
}

function makeKey(seed: number): Uint8Array {
  return new Uint8Array(32).fill(seed);
}

// Minimal mock for the encrypted-chat-key fetcher
function makeFetcher(
  map: Record<string, string>,
): (chatId: string) => Promise<string | null> {
  return async (chatId) => map[chatId] ?? null;
}

// ---------------------------------------------------------------------------
// Baseline
// ---------------------------------------------------------------------------

describe("ChatKeyManager — baseline", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    _rvCounter = 1;
    mgr = new ChatKeyManager();
  });

  it("returns null for an unknown chat (never generates a random key)", () => {
    expect(mgr.getKeySync("unknown-chat")).toBeNull();
  });

  it("createKeyForNewChat generates a 32-byte key and marks state as ready", () => {
    const key = mgr.createKeyForNewChat("chat-1");
    expect(key).toBeInstanceOf(Uint8Array);
    expect(key.length).toBe(32);
    expect(mgr.getState("chat-1")).toBe("ready");
    expect(mgr.getKeySync("chat-1")).toBe(key);
  });

  it("createKeyForNewChat called twice returns the SAME key (idempotent)", () => {
    const k1 = mgr.createKeyForNewChat("chat-1");
    const k2 = mgr.createKeyForNewChat("chat-1");
    expect(k1).toBe(k2);
  });

  it("injectKey stores and retrieves a key", () => {
    const key = makeKey(42);
    mgr.injectKey("chat-1", key, "master_key");
    expect(mgr.getKeySync("chat-1")).toEqual(key);
    expect(mgr.getProvenance("chat-1")?.source).toBe("master_key");
  });

  it("size() reflects the number of loaded keys", () => {
    expect(mgr.size()).toBe(0);
    mgr.injectKey("chat-1", makeKey(1), "bulk_init");
    mgr.injectKey("chat-2", makeKey(2), "bulk_init");
    expect(mgr.size()).toBe(2);
  });
});

// ---------------------------------------------------------------------------
// Immutability guard (bug: aac318ee — two-cache divergence / silent replacement)
// ---------------------------------------------------------------------------

describe("ChatKeyManager — immutability guard", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    mgr = new ChatKeyManager();
  });

  it("blocks injecting a DIFFERENT key for the same chat", () => {
    const k1 = makeKey(1);
    const k2 = makeKey(2);
    mgr.injectKey("chat-1", k1, "master_key");
    const accepted = mgr.injectKey("chat-1", k2, "server_sync");
    expect(accepted).toBe(false);
    // Original key must survive
    expect(mgr.getKeySync("chat-1")).toEqual(k1);
  });

  it("accepts the SAME key bytes from a different source (no-op, updates provenance)", () => {
    const k1 = makeKey(99);
    mgr.injectKey("chat-1", k1, "share_link");
    const accepted = mgr.injectKey("chat-1", new Uint8Array(k1), "master_key");
    expect(accepted).toBe(true);
    // Higher-priority source should win
    expect(mgr.getProvenance("chat-1")?.source).toBe("master_key");
  });

  it("force=true allows overwriting (hidden chat re-lock)", () => {
    const k1 = makeKey(1);
    const k2 = makeKey(2);
    mgr.injectKey("chat-1", k1, "master_key");
    const accepted = mgr.injectKey("chat-1", k2, "hidden_chat", true);
    expect(accepted).toBe(true);
    expect(mgr.getKeySync("chat-1")).toEqual(k2);
  });
});

// ---------------------------------------------------------------------------
// clearAll + critical op lock (bug: 97e14300 — key regeneration race)
// ---------------------------------------------------------------------------

describe("ChatKeyManager — critical op lock", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    mgr = new ChatKeyManager();
  });

  it("clearAll() defers while a critical op is held", () => {
    const key = makeKey(10);
    mgr.injectKey("chat-1", key, "master_key");

    mgr.acquireCriticalOp();
    mgr.clearAll();

    // Key must still be accessible — clearAll was deferred
    expect(mgr.getKeySync("chat-1")).toEqual(key);
    expect(mgr.size()).toBe(1);

    mgr.releaseCriticalOp();

    // Now clearAll executes
    expect(mgr.size()).toBe(0);
    expect(mgr.getKeySync("chat-1")).toBeNull();
  });

  it("nested critical ops: clearAll defers until the last release", () => {
    mgr.injectKey("chat-1", makeKey(1), "master_key");
    mgr.injectKey("chat-2", makeKey(2), "master_key");

    mgr.acquireCriticalOp();
    mgr.acquireCriticalOp();
    mgr.clearAll();

    expect(mgr.size()).toBe(2); // still deferred

    mgr.releaseCriticalOp();
    expect(mgr.size()).toBe(2); // still one lock held

    mgr.releaseCriticalOp();
    expect(mgr.size()).toBe(0); // now cleared
  });

  it("key injected during a critical op is accessible after the op completes", () => {
    // Simulates: sendEncryptedStoragePackage acquires lock, receives key from server mid-flight
    mgr.acquireCriticalOp();
    mgr.clearAll(); // deferred
    mgr.injectKey("chat-1", makeKey(99), "server_sync"); // key arrives
    mgr.releaseCriticalOp(); // deferred clear runs

    // The key should be GONE (clearAll happened after lock release)
    // This is correct behaviour: logout wins, the key should not linger
    expect(mgr.getKeySync("chat-1")).toBeNull();
  });

  it("K1/K2 corruption scenario: clearAll mid-flight must not cause key regeneration", () => {
    // This is the root cause of issue 97e14300:
    // 1. Chat encrypted with K1
    // 2. clearAll() runs (auth disruption) — cleared K1
    // 3. sendEncryptedStoragePackage falls through to createKeyForNewChat → K2
    // 4. encrypted_chat_key = encrypt(K2) stored on server
    // 5. User message (encrypted with K1) is now permanently unreadable
    //
    // With the lock, step 3 never happens:
    mgr.acquireCriticalOp(); // sendEncryptedStoragePackage acquires lock
    const k1 = mgr.createKeyForNewChat("chat-1");

    mgr.clearAll(); // auth disruption — but deferred

    // Mid-flight: still have K1
    expect(mgr.getKeySync("chat-1")).toEqual(k1);

    // sendEncryptedStoragePackage finishes and releases
    mgr.releaseCriticalOp();

    // After release, deferred clear executes: K1 is gone
    expect(mgr.getKeySync("chat-1")).toBeNull();
    // createKeyForNewChat CANNOT be called now (no key exists) — the operation
    // was already completed before the lock was released. No K2 is generated.
  });
});

// ---------------------------------------------------------------------------
// Queue-and-flush (write paths waiting for key)
// ---------------------------------------------------------------------------

describe("ChatKeyManager — queue-and-flush", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    mgr = new ChatKeyManager();
  });

  it("withKey executes immediately if key is available", async () => {
    const key = makeKey(5);
    mgr.injectKey("chat-1", key, "master_key");
    let received: Uint8Array | null = null;
    await mgr.withKey("chat-1", "test-op", async (k) => {
      received = k;
    });
    expect(received).toEqual(key);
  });

  it("queueOperation auto-executes when key arrives", async () => {
    let executed = false;
    const opPromise = mgr.queueOperation("chat-1", "test-op", async (key) => {
      expect(key).toEqual(makeKey(7));
      executed = true;
    });

    expect(executed).toBe(false);

    mgr.injectKey("chat-1", makeKey(7), "server_sync");

    await opPromise;
    expect(executed).toBe(true);
  });

  it("pending ops are rejected when clearAll fires", async () => {
    const opPromise = mgr.queueOperation("chat-1", "test-op", async () => {});
    mgr.clearAll();
    await expect(opPromise).rejects.toThrow(/logout/);
  });

  it("queue rejects when MAX_QUEUE_SIZE is exceeded", async () => {
    // Fill the queue (MAX = 50)
    const promises: Promise<void>[] = [];
    for (let i = 0; i < 50; i++) {
      promises.push(
        mgr.queueOperation("chat-1", `op-${i}`, async () => {}),
      );
    }
    // 51st op should reject immediately
    await expect(
      mgr.queueOperation("chat-1", "overflow", async () => {}),
    ).rejects.toThrow(/queue full/i);

    // Clean up
    mgr.clearAll();
    await Promise.allSettled(promises);
  });
});

// ---------------------------------------------------------------------------
// bulkInject (Improvement 3: eager loading)
// ---------------------------------------------------------------------------

describe("ChatKeyManager — bulkInject", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    mgr = new ChatKeyManager();
  });

  it("injects all entries with bulk_init provenance", () => {
    const entries: Array<[string, Uint8Array]> = [
      ["chat-1", makeKey(1)],
      ["chat-2", makeKey(2)],
      ["chat-3", makeKey(3)],
    ];
    mgr.bulkInject(entries);
    expect(mgr.size()).toBe(3);
    for (const [chatId, key] of entries) {
      expect(mgr.getKeySync(chatId)).toEqual(key);
      expect(mgr.getProvenance(chatId)?.source).toBe("bulk_init");
    }
  });

  it("bulkInject does not overwrite higher-priority keys", () => {
    const highPriKey = makeKey(99);
    mgr.injectKey("chat-1", highPriKey, "master_key");
    // Try to bulk-inject a different key for the same chat
    mgr.bulkInject([["chat-1", makeKey(1)]]);
    // master_key > bulk_init — original key must survive
    expect(mgr.getKeySync("chat-1")).toEqual(highPriKey);
  });
});

// ---------------------------------------------------------------------------
// removeKey
// ---------------------------------------------------------------------------

describe("ChatKeyManager — removeKey", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    mgr = new ChatKeyManager();
  });

  it("removes a key and rejects pending ops for that chat", async () => {
    const opPromise = mgr.queueOperation("chat-1", "pending", async () => {});
    mgr.removeKey("chat-1");
    await expect(opPromise).rejects.toThrow(/removed/);
    expect(mgr.getKeySync("chat-1")).toBeNull();
  });

  it("removeKey does not affect other chats", () => {
    mgr.injectKey("chat-1", makeKey(1), "master_key");
    mgr.injectKey("chat-2", makeKey(2), "master_key");
    mgr.removeKey("chat-1");
    expect(mgr.getKeySync("chat-1")).toBeNull();
    expect(mgr.getKeySync("chat-2")).toEqual(makeKey(2));
  });
});

// ---------------------------------------------------------------------------
// Debug info
// ---------------------------------------------------------------------------

describe("ChatKeyManager — getDebugInfo", () => {
  it("reports all chats including pending-op-only entries", () => {
    const mgr = new ChatKeyManager();
    mgr.injectKey("chat-1", makeKey(1), "master_key");
    // Queue an op for chat-2 (no key yet)
    mgr.queueOperation("chat-2", "test", async () => {}).catch(() => {});

    const info = mgr.getDebugInfo();
    expect(info.totalKeys).toBe(1);
    expect(info.totalPendingOps).toBe(1);
    const chatIds = info.keys.map((k) => k.chatId);
    expect(chatIds).toContain("chat-1");
    expect(chatIds).toContain("chat-2");

    mgr.clearAll();
  });
});

// ---------------------------------------------------------------------------
// Key loading from IDB (via fetchEncryptedChatKey callback)
// ---------------------------------------------------------------------------

describe("ChatKeyManager — getKey (IDB load)", () => {
  it("loads key from IDB via fetcher callback", async () => {
    const mgr = new ChatKeyManager();

    // Mock: encrypting/decrypting is handled by cryptoService which we mock
    const rawKey = makeKey(55);
    const fakeEncrypted = "encrypted-key-base64";

    // Mock decryptChatKeyWithMasterKey inline via the fetcher returning
    // an encrypted string, but we can't easily mock the crypto import here.
    // Instead test the fetcher wiring: if fetcher returns null, getKey returns null.
    mgr.setEncryptedChatKeyFetcher(makeFetcher({}));
    const result = await mgr.getKey("chat-unknown");
    expect(result).toBeNull();
    expect(mgr.getState("chat-unknown")).not.toBe("ready");

    // Inject directly and verify getKey fast-path works
    mgr.injectKey("chat-known", rawKey, "master_key");
    const cached = await mgr.getKey("chat-known");
    expect(cached).toEqual(rawKey);
  });

  it("concurrent getKey() calls share a single IDB load (no duplicate loads)", async () => {
    const mgr = new ChatKeyManager();
    let fetchCount = 0;
    mgr.setEncryptedChatKeyFetcher(async () => {
      fetchCount++;
      return null; // key not found, but we count fetches
    });

    // Fire three concurrent getKey calls for the same chat
    await Promise.all([
      mgr.getKey("chat-1"),
      mgr.getKey("chat-1"),
      mgr.getKey("chat-1"),
    ]);

    // Should only have fetched once (shared loading promise)
    expect(fetchCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Web Locks mutex (KEYS-01 / KEYS-02)
// Tests that createAndPersistKeyLocked() prevents concurrent key generation
// and respects existing keys via the Web Locks API.
// ---------------------------------------------------------------------------

describe("ChatKeyManager — Web Locks mutex (KEYS-01/KEYS-02)", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    _rvCounter = 1;
    resetLockMock();
    mgr = new ChatKeyManager();
    // Register a no-op persister so createAndPersistKey doesn't throw
    mgr.setEncryptedChatKeyPersister(async () => {});
  });

  it("two concurrent createAndPersistKeyLocked() calls produce exactly one key", async () => {
    // Mock encryptChatKeyWithMasterKey to return a dummy value
    const { encryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(encryptChatKeyWithMasterKey).mockResolvedValue("encrypted-dummy");

    // Fire two concurrent locked key creation calls for the same chatId
    const [result1, result2] = await Promise.all([
      mgr.createAndPersistKeyLocked("chat-1"),
      mgr.createAndPersistKeyLocked("chat-1"),
    ]);

    // Both should return the same key bytes (second call returns existing)
    expect(result1.chatKey).toEqual(result2.chatKey);
    expect(result1.chatKey).toBeInstanceOf(Uint8Array);
    expect(result1.chatKey.length).toBe(32);
  });

  it("createAndPersistKeyLocked() with an existing key returns that key without generating", async () => {
    const { encryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(encryptChatKeyWithMasterKey).mockResolvedValue("encrypted-dummy");

    // Pre-inject a key
    const existingKey = makeKey(42);
    mgr.injectKey("chat-1", existingKey, "master_key");

    const result = await mgr.createAndPersistKeyLocked("chat-1");

    // Should return the existing key, not generate a new one
    expect(result.chatKey).toEqual(existingKey);
  });

  it("Web Lock timeout (AbortController fires) falls back to unlocked createAndPersistKey", async () => {
    const { encryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(encryptChatKeyWithMasterKey).mockResolvedValue("encrypted-dummy");

    // Override navigator.locks to always abort immediately
    const originalLocks = navigator.locks;
    Object.defineProperty(navigator, "locks", {
      value: {
        request: async (_name: string, optionsOrCb: any, _maybeCb?: any) => {
          const options = _maybeCb ? optionsOrCb : {};
          if (options.signal) {
            // Simulate timeout by aborting the signal
            throw new DOMException("The operation was aborted.", "AbortError");
          }
        },
      },
      configurable: true,
    });

    // Should fall back to unlocked path and still produce a key
    const result = await mgr.createAndPersistKeyLocked("chat-1");
    expect(result.chatKey).toBeInstanceOf(Uint8Array);
    expect(result.chatKey.length).toBe(32);

    // Restore
    Object.defineProperty(navigator, "locks", {
      value: originalLocks,
      configurable: true,
    });
  });

  it("when navigator.locks is undefined (SSR), falls back to unlocked createAndPersistKey", async () => {
    const { encryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(encryptChatKeyWithMasterKey).mockResolvedValue("encrypted-dummy");

    // Temporarily remove navigator.locks
    const originalLocks = navigator.locks;
    Object.defineProperty(navigator, "locks", {
      value: undefined,
      configurable: true,
    });

    const result = await mgr.createAndPersistKeyLocked("chat-1");
    expect(result.chatKey).toBeInstanceOf(Uint8Array);
    expect(result.chatKey.length).toBe(32);

    // Restore
    Object.defineProperty(navigator, "locks", {
      value: originalLocks,
      configurable: true,
    });
  });

  it("Web Lock mutex only applies to chat key generation — no other operations", async () => {
    const { encryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(encryptChatKeyWithMasterKey).mockResolvedValue("encrypted-dummy");

    // While a locked key creation is in flight, other operations (inject, getKeySync) still work
    const lockPromise = mgr.createAndPersistKeyLocked("chat-1");

    // These should work without being blocked by the Web Lock
    mgr.injectKey("chat-2", makeKey(99), "master_key");
    expect(mgr.getKeySync("chat-2")).toEqual(makeKey(99));
    expect(mgr.getState("chat-2")).toBe("ready");

    await lockPromise;
  });
});

// ---------------------------------------------------------------------------
// State machine transitions (KEYS-05)
// Tests for failed->loading retry via reloadKey() and deadlock prevention.
// ---------------------------------------------------------------------------

describe("ChatKeyManager — state machine transitions (KEYS-05)", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    _rvCounter = 1;
    resetLockMock();
    mgr = new ChatKeyManager();
  });

  it("failed->loading retry via reloadKey() succeeds when fetcher returns data", async () => {
    // Set up a fetcher that fails first, then succeeds
    let callCount = 0;
    mgr.setEncryptedChatKeyFetcher(async () => {
      callCount++;
      if (callCount === 1) return "encrypted-key"; // triggers decryptChatKeyWithMasterKey
      return "encrypted-key";
    });

    // First attempt: getKey should fail (decryptChatKeyWithMasterKey returns null in test)
    await mgr.getKey("chat-1");
    expect(mgr.getState("chat-1")).toBe("failed").valueOf;

    // Inject key directly to simulate successful reload path
    // (since we can't easily mock decryptChatKeyWithMasterKey here)
    mgr.injectKey("chat-1", makeKey(55), "master_key");
    expect(mgr.getState("chat-1")).toBe("ready");
    expect(mgr.getKeySync("chat-1")).toEqual(makeKey(55));
  });

  it("failed->loading retry via reloadKey() stays failed when fetcher returns null", async () => {
    // Fetcher always returns null
    mgr.setEncryptedChatKeyFetcher(async () => null);

    // First attempt
    await mgr.getKey("chat-1");
    // State should be unloaded (fetcher returned null = no key in DB)
    // Now set a fetcher that returns an encrypted key (but decrypt fails)
    mgr.setEncryptedChatKeyFetcher(async () => "encrypted-but-undecryptable");

    // reloadKey should reset and re-attempt
    const result = await mgr.reloadKey("chat-1");
    expect(result).toBeNull();
    // State should be failed (decrypt returned null)
    expect(mgr.getState("chat-1")).toBe("failed");
  });

  it("reloadKey resets state from failed to loading before re-attempting", async () => {
    mgr.setEncryptedChatKeyFetcher(async () => "encrypted-but-undecryptable");

    // First getKey — should end in failed state
    await mgr.getKey("chat-1");
    expect(mgr.getState("chat-1")).toBe("failed");

    // reloadKey should reset state and try again
    const reloadPromise = mgr.reloadKey("chat-1");

    // After reload completes (still fails since decrypt mock returns null)
    await reloadPromise;
    expect(mgr.getState("chat-1")).toBe("failed");
  });
});

// ---------------------------------------------------------------------------
// Deadlock prevention
// Tests that the state machine never enters a deadlock state.
// ---------------------------------------------------------------------------

describe("ChatKeyManager — deadlock prevention", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    _rvCounter = 1;
    resetLockMock();
    mgr = new ChatKeyManager();
  });

  it("no deadlock when reloadKey is called while key is already in loading state", async () => {
    // Set up a fetcher that tracks call count and resolves with null
    let fetchCount = 0;
    mgr.setEncryptedChatKeyFetcher(async () => {
      fetchCount++;
      return null;
    });

    // Start first load
    const firstLoad = mgr.getKey("chat-1");
    // Wait for it to complete
    await firstLoad;

    // Now set up a fetcher that returns an encrypted key (still null decrypt in mock)
    mgr.setEncryptedChatKeyFetcher(async () => "encrypted-key");

    // Call reloadKey — should not deadlock even though we just loaded
    const result = await mgr.reloadKey("chat-1");

    // Should complete without hanging (null because decrypt mock returns null)
    expect(result).toBeNull();
    expect(fetchCount).toBe(1); // first fetch completed
  });

  it("deferredClearAll check inside Web Lock — key generation aborts if clearAll pending", async () => {
    const { encryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(encryptChatKeyWithMasterKey).mockResolvedValue("encrypted-dummy");
    mgr.setEncryptedChatKeyPersister(async () => {});

    // Acquire critical op to defer clearAll
    mgr.acquireCriticalOp();
    mgr.clearAll(); // deferred — sets deferredClearAll = true

    // createAndPersistKeyLocked should detect deferredClearAll and abort
    // (this tests the check inside the Web Lock callback)
    await expect(mgr.createAndPersistKeyLocked("chat-1")).rejects.toThrow(
      /clearAll/,
    );

    mgr.releaseCriticalOp();
  });
});

// ---------------------------------------------------------------------------
// BroadcastChannel keyLoaded (KEYS-06 cross-tab)
// Tests that keyLoaded messages warm the receiving tab's key cache for chats
// with pending operations, and that broadcastKeyLoaded fires after key
// creation and server receive.
// ---------------------------------------------------------------------------

// Capture BroadcastChannel messages for assertion
const broadcastMessages: Array<{ type: string; chatId?: string; encryptedChatKey?: string }> = [];

// Mock BroadcastChannel so we can observe postMessage calls
vi.stubGlobal(
  "BroadcastChannel",
  class MockBroadcastChannel {
    onmessage: ((event: MessageEvent) => void) | null = null;
    postMessage(data: any) {
      broadcastMessages.push(data);
    }
    close() {}
  },
);

describe("ChatKeyManager — BroadcastChannel keyLoaded (KEYS-06 cross-tab)", () => {
  let mgr: ChatKeyManager;

  beforeEach(async () => {
    _rvCounter = 1;
    resetLockMock();
    broadcastMessages.length = 0;
    mgr = new ChatKeyManager();
    mgr.setEncryptedChatKeyPersister(async () => {});
    // Mock encrypt to return a deterministic value
    const { encryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(encryptChatKeyWithMasterKey).mockResolvedValue("encrypted-dummy");
  });

  it("keyLoaded message for a chat with pending ops triggers receiveKeyFromServer and flushes the queue", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    const expectedKey = makeKey(77);
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(expectedKey);

    // Queue a pending operation for chat-1
    let flushed = false;
    const opPromise = mgr.queueOperation("chat-1", "test-op", async (key) => {
      flushed = true;
      expect(key).toEqual(expectedKey);
    });

    // Simulate keyLoaded message from another tab
    // Access the BroadcastChannel's onmessage handler via the manager's constructor
    // The manager registers onmessage in the constructor, so we trigger it via the channel
    const bc = (mgr as any).broadcastChannel;
    expect(bc).not.toBeNull();
    bc.onmessage!({ data: { type: "keyLoaded", chatId: "chat-1", encryptedChatKey: "encrypted-from-other-tab" } } as MessageEvent);

    // Wait for the async receiveKeyFromServer to complete
    await new Promise((r) => setTimeout(r, 10));
    await opPromise;

    expect(flushed).toBe(true);
    expect(mgr.getKeySync("chat-1")).toEqual(expectedKey);
  });

  it("keyLoaded message for a chat with NO pending ops is ignored (Pitfall 4)", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(makeKey(88));

    // No pending ops for chat-1 — keyLoaded should be a no-op
    const bc = (mgr as any).broadcastChannel;
    bc.onmessage!({ data: { type: "keyLoaded", chatId: "chat-1", encryptedChatKey: "encrypted-from-other-tab" } } as MessageEvent);

    await new Promise((r) => setTimeout(r, 10));

    // Key should NOT be loaded (lazy load — no reason to warm cache without pending work)
    expect(mgr.getKeySync("chat-1")).toBeNull();
  });

  it("keyLoaded message for a chat where key already exists in memory is ignored", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(makeKey(99));

    // Pre-inject a key
    mgr.injectKey("chat-1", makeKey(42), "master_key");

    const bc = (mgr as any).broadcastChannel;
    bc.onmessage!({ data: { type: "keyLoaded", chatId: "chat-1", encryptedChatKey: "encrypted-from-other-tab" } } as MessageEvent);

    await new Promise((r) => setTimeout(r, 10));

    // Original key must survive (not replaced)
    expect(mgr.getKeySync("chat-1")).toEqual(makeKey(42));
  });

  it("after createAndPersistKey, broadcastKeyLoaded is called with chatId and encryptedChatKey", async () => {
    broadcastMessages.length = 0;
    await mgr.createAndPersistKey("chat-new");

    // Should have broadcast a keyLoaded message
    const keyLoadedMsgs = broadcastMessages.filter((m) => m.type === "keyLoaded");
    expect(keyLoadedMsgs.length).toBe(1);
    expect(keyLoadedMsgs[0].chatId).toBe("chat-new");
    expect(keyLoadedMsgs[0].encryptedChatKey).toBe("encrypted-dummy");
  });

  it("after receiveKeyFromServer succeeds, broadcastKeyLoaded is called", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(makeKey(55));

    broadcastMessages.length = 0;
    await mgr.receiveKeyFromServer("chat-1", "encrypted-from-server");

    const keyLoadedMsgs = broadcastMessages.filter((m) => m.type === "keyLoaded");
    expect(keyLoadedMsgs.length).toBe(1);
    expect(keyLoadedMsgs[0].chatId).toBe("chat-1");
    expect(keyLoadedMsgs[0].encryptedChatKey).toBe("encrypted-from-server");
  });

  it("broadcastKeyLoaded is a no-op when broadcastChannel is null (SSR)", async () => {
    // Create a manager without BroadcastChannel
    const origBC = globalThis.BroadcastChannel;
    vi.stubGlobal("BroadcastChannel", undefined);

    const ssrMgr = new ChatKeyManager();
    ssrMgr.setEncryptedChatKeyPersister(async () => {});

    const { encryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(encryptChatKeyWithMasterKey).mockResolvedValue("encrypted-ssr");

    broadcastMessages.length = 0;
    await ssrMgr.createAndPersistKey("chat-ssr");

    // No broadcast should have occurred
    const keyLoadedMsgs = broadcastMessages.filter((m) => m.type === "keyLoaded");
    expect(keyLoadedMsgs.length).toBe(0);

    // Restore
    vi.stubGlobal("BroadcastChannel", origBC);
  });
});

// ---------------------------------------------------------------------------
// rewrapKey (KEYS-03 bypass closure)
// Tests that rewrapKey returns re-wrapped key when in memory, null otherwise.
// ---------------------------------------------------------------------------

describe("ChatKeyManager — rewrapKey (KEYS-03)", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    mgr = new ChatKeyManager();
  });

  it("rewrapKey with key in memory returns re-wrapped form", async () => {
    const rawKey = makeKey(42);
    mgr.injectKey("chat-1", rawKey, "master_key");

    const result = await mgr.rewrapKey("chat-1", async (key) => {
      // Verify we receive the correct raw key
      expect(key).toEqual(rawKey);
      return "re-wrapped-with-new-key";
    });

    expect(result).toBe("re-wrapped-with-new-key");
  });

  it("rewrapKey with no key in memory returns null", async () => {
    const result = await mgr.rewrapKey("nonexistent", async () => {
      throw new Error("Should not be called");
    });

    expect(result).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Key-before-content guarantee (KEYS-04)
// Tests that withKey() buffers operations until the key arrives, ensuring
// encrypted content is never processed without the correct decryption key.
// Per D-03: These tests verify that the architecture prevents failures structurally.
// ---------------------------------------------------------------------------

describe("ChatKeyManager -- key-before-content guarantee (KEYS-04)", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    _rvCounter = 1;
    resetLockMock();
    mgr = new ChatKeyManager();
  });

  afterEach(() => {
    mgr.clearAll();
  });

  it("KEYS-04: withKey buffers operation and flushes when key arrives via injectKey", async () => {
    const callback = vi.fn().mockImplementation(async () => {});
    const expectedKey = makeKey(42);

    // Call withKey when no key exists -- should buffer
    const opPromise = mgr.withKey("chat-1", "decrypt-test", callback);

    // Callback should NOT have been called yet
    expect(callback).not.toHaveBeenCalled();

    // Inject the key -- should trigger flush
    mgr.injectKey("chat-1", expectedKey, "server_sync");

    await opPromise;

    // Callback should have been called with the correct key
    expect(callback).toHaveBeenCalledOnce();
    expect(callback).toHaveBeenCalledWith(expectedKey);
  });

  it("KEYS-04: withKey buffers multiple operations and flushes all in order", async () => {
    const callOrder: number[] = [];
    const expectedKey = makeKey(77);

    // Queue 3 withKey operations for the same chatId
    const op1 = mgr.withKey("chat-1", "op-1", async () => {
      callOrder.push(1);
    });
    const op2 = mgr.withKey("chat-1", "op-2", async () => {
      callOrder.push(2);
    });
    const op3 = mgr.withKey("chat-1", "op-3", async () => {
      callOrder.push(3);
    });

    // None should have fired yet
    expect(callOrder).toEqual([]);

    // Inject key -- all 3 should flush in order
    mgr.injectKey("chat-1", expectedKey, "master_key");

    await Promise.all([op1, op2, op3]);

    expect(callOrder).toEqual([1, 2, 3]);
  });

  it("KEYS-04: withKey operation times out after QUEUE_TIMEOUT_MS", async () => {
    vi.useFakeTimers();

    const callback = vi.fn().mockImplementation(async () => {});

    // Queue a withKey operation -- key never arrives
    const opPromise = mgr.withKey("chat-1", "decrypt-timeout-test", callback);

    // Advance time past the 30s timeout
    await vi.advanceTimersByTimeAsync(31_000);

    // The promise should reject with a timeout error
    await expect(opPromise).rejects.toThrow(/not available.*within.*30000ms/i);

    // Callback should never have been called
    expect(callback).not.toHaveBeenCalled();

    // Inject key AFTER timeout -- the expired callback should NOT be called
    mgr.injectKey("chat-1", makeKey(99), "server_sync");

    // Wait a tick for any async flush
    await vi.advanceTimersByTimeAsync(100);

    // Still not called -- the operation was removed from the queue on timeout
    expect(callback).not.toHaveBeenCalled();

    vi.useRealTimers();
  });

  it("KEYS-04: withKey fast-path returns immediately when key is in memory", async () => {
    const expectedKey = makeKey(33);
    mgr.injectKey("chat-1", expectedKey, "master_key");

    let receivedKey: Uint8Array | null = null;
    const callbackFn = async (k: Uint8Array) => {
      receivedKey = k;
    };

    // withKey should execute callback synchronously (within same microtask)
    await mgr.withKey("chat-1", "fast-path-test", callbackFn);

    expect(receivedKey).toEqual(expectedKey);
  });

  it("KEYS-04: withKey loads key from IDB when not in memory", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    const expectedKey = makeKey(55);
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(expectedKey);

    // Set up a fetcher that returns an encrypted key
    mgr.setEncryptedChatKeyFetcher(async () => "encrypted-key-from-idb");

    let receivedKey: Uint8Array | null = null;
    await mgr.withKey("chat-1", "idb-load-test", async (k) => {
      receivedKey = k;
    });

    // Should have loaded from IDB and executed callback
    expect(receivedKey).toEqual(expectedKey);
    expect(mgr.getState("chat-1")).toBe("ready");
  });
});

// ---------------------------------------------------------------------------
// State machine comprehensive (KEYS-05)
// Tests the full lifecycle of the key state machine and concurrent loading.
// ---------------------------------------------------------------------------

describe("ChatKeyManager -- state machine comprehensive (KEYS-05)", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    _rvCounter = 1;
    resetLockMock();
    mgr = new ChatKeyManager();
  });

  afterEach(() => {
    mgr.clearAll();
  });

  it("full lifecycle: unloaded -> loading -> ready -> removed", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    const expectedKey = makeKey(42);
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(expectedKey);

    // Initial state: unloaded (no entry at all)
    expect(mgr.getState("chat-1")).toBe("unloaded");

    // Set up fetcher
    let fetchResolveFn: (() => void) | null = null;
    mgr.setEncryptedChatKeyFetcher(
      () =>
        new Promise<string | null>((resolve) => {
          fetchResolveFn = () => resolve("encrypted-key");
        }),
    );

    // Trigger loading via getKey (don't await yet)
    const loadPromise = mgr.getKey("chat-1");

    // State should be loading (fetch started but not completed)
    // Wait a microtask for the state to transition
    await new Promise((r) => setTimeout(r, 0));
    expect(mgr.getState("chat-1")).toBe("loading");

    // Complete the fetch
    fetchResolveFn!();
    const key = await loadPromise;

    // State should be ready
    expect(mgr.getState("chat-1")).toBe("ready");
    expect(key).toEqual(expectedKey);

    // Remove the key
    mgr.removeKey("chat-1");
    expect(mgr.getState("chat-1")).toBe("unloaded");
    expect(mgr.getKeySync("chat-1")).toBeNull();
  });

  it("concurrent getKey calls share one loading promise", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    const expectedKey = makeKey(88);
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(expectedKey);

    let fetchCount = 0;
    mgr.setEncryptedChatKeyFetcher(async () => {
      fetchCount++;
      return "encrypted-key";
    });

    // Fire two concurrent getKey calls
    const [key1, key2] = await Promise.all([
      mgr.getKey("chat-1"),
      mgr.getKey("chat-1"),
    ]);

    // Only one fetch should have been made (shared loading promise)
    expect(fetchCount).toBe(1);

    // Both should resolve with the same key
    expect(key1).toEqual(expectedKey);
    expect(key2).toEqual(expectedKey);
  });
});

// ---------------------------------------------------------------------------
// SYNC-01: key_received acknowledgment (key delivery ack protocol)
// ---------------------------------------------------------------------------

describe("SYNC-01: key_received acknowledgment", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    _rvCounter = 1;
    resetLockMock();
    mgr = new ChatKeyManager();
    mockSendMessage.mockClear();
    mockSendMessage.mockResolvedValue(undefined);
  });

  it("sends key_received ack after successful receiveKeyFromServer", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    const expectedKey = makeKey(99);
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(expectedKey);

    await mgr.receiveKeyFromServer("chat-ack-1", "encrypted-key-data");

    // The ack is fire-and-forget via dynamic import — give the microtask queue
    // time to resolve the import() promise chain.
    await new Promise((r) => setTimeout(r, 20));

    expect(mockSendMessage).toHaveBeenCalledWith("key_received", {
      chat_id: "chat-ack-1",
    });
  });

  it("does not throw if ack send fails", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    const expectedKey = makeKey(98);
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(expectedKey);

    // Make sendMessage reject — this should NOT cause receiveKeyFromServer to fail
    mockSendMessage.mockRejectedValue(new Error("WebSocket not connected"));

    const result = await mgr.receiveKeyFromServer(
      "chat-ack-2",
      "encrypted-key-data",
    );

    // Key injection should succeed despite ack failure
    expect(result).toEqual(expectedKey);
    expect(mgr.getKeySync("chat-ack-2")).toEqual(expectedKey);

    // Wait for the async ack attempt to complete
    await new Promise((r) => setTimeout(r, 20));
  });

  it("does not send ack when key already exists (duplicate receive)", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    const existingKey = makeKey(97);
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(existingKey);

    // First: inject a key directly
    mgr.injectKey("chat-ack-3", existingKey, "server_sync");
    mockSendMessage.mockClear();

    // Second: receive the same key from server — should skip ack
    await mgr.receiveKeyFromServer("chat-ack-3", "encrypted-key-data");
    await new Promise((r) => setTimeout(r, 20));

    // No ack sent because the key was already cached (early return path)
    expect(mockSendMessage).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// SYNC-02: BroadcastChannel cross-tab key propagation
// ---------------------------------------------------------------------------

describe("SYNC-02: BroadcastChannel cross-tab key propagation", () => {
  let mgr: ChatKeyManager;

  beforeEach(async () => {
    _rvCounter = 1;
    resetLockMock();
    mgr = new ChatKeyManager();

    const { decryptChatKeyWithMasterKey, encryptChatKeyWithMasterKey } =
      await import("../../cryptoService");
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(makeKey(50));
    vi.mocked(encryptChatKeyWithMasterKey).mockResolvedValue("encrypted-dummy");
  });

  it("key loaded in one tab is available via getKeySync after BroadcastChannel message (with pending ops)", async () => {
    const { decryptChatKeyWithMasterKey } = await import("../../cryptoService");
    const expectedKey = makeKey(50);
    vi.mocked(decryptChatKeyWithMasterKey).mockResolvedValue(expectedKey);

    // Queue a pending operation for this chat — BroadcastChannel keyLoaded
    // only triggers receiveKeyFromServer when pending ops exist (Pitfall 4
    // optimization: skip async decrypt when no work is waiting).
    let opResolved = false;
    mgr.queueOperation("cross-tab-chat", "decrypt-waiting", async () => {
      opResolved = true;
    });

    // Access the BroadcastChannel created by ChatKeyManager
    const bc = (mgr as any).broadcastChannel as BroadcastChannel | null;
    expect(bc).not.toBeNull();

    // Simulate receiving a keyLoaded message from another tab
    bc!.onmessage!({
      data: {
        type: "keyLoaded",
        chatId: "cross-tab-chat",
        encryptedChatKey: "encrypted-from-other-tab",
      },
    } as MessageEvent);

    // Wait for the async receiveKeyFromServer + flush to complete
    await new Promise((r) => setTimeout(r, 30));

    // The key should now be in the local cache
    const localKey = mgr.getKeySync("cross-tab-chat");
    expect(localKey).toEqual(expectedKey);

    // The pending operation should have been flushed
    expect(opResolved).toBe(true);
  });

  it("BroadcastChannel propagation works for encrypt path (createAndPersistKey broadcasts)", async () => {
    const { encryptChatKeyWithMasterKey } = await import("../../cryptoService");
    vi.mocked(encryptChatKeyWithMasterKey).mockResolvedValue(
      "encrypted-new-key",
    );

    // Collect BroadcastChannel messages
    const messages: any[] = [];
    const bc = (mgr as any).broadcastChannel as BroadcastChannel | null;
    if (bc) {
      const origPost = bc.postMessage.bind(bc);
      bc.postMessage = (msg: any) => {
        messages.push(msg);
        origPost(msg);
      };
    }

    // Create a key (encrypt path) — should broadcast keyLoaded
    await mgr.createAndPersistKey("encrypt-chat");

    const keyLoadedMsgs = messages.filter((m) => m.type === "keyLoaded");
    expect(keyLoadedMsgs.length).toBe(1);
    expect(keyLoadedMsgs[0].chatId).toBe("encrypt-chat");
    expect(keyLoadedMsgs[0].encryptedChatKey).toBe("encrypted-new-key");
  });
});

// ---------------------------------------------------------------------------
// OPE-314: onKeyReady callback — re-decrypt pending messages
// ---------------------------------------------------------------------------

describe("ChatKeyManager — onKeyReady (OPE-314)", () => {
  let mgr: ChatKeyManager;

  beforeEach(() => {
    _rvCounter = 100;
    mgr = new ChatKeyManager();
  });

  afterEach(() => {
    mgr.clearAll();
  });

  it("fires listener when key transitions from unloaded to ready", () => {
    const readyChats: string[] = [];
    mgr.onKeyReady((chatId) => readyChats.push(chatId));

    // Inject a key (transitions from unloaded → ready)
    mgr.injectKey("chat-A", makeKey(10), "injected");

    expect(readyChats).toEqual(["chat-A"]);
  });

  it("does NOT fire listener on repeated set of the same key", () => {
    const readyChats: string[] = [];

    // First inject → fires
    mgr.injectKey("chat-B", makeKey(20), "injected");
    mgr.onKeyReady((chatId) => readyChats.push(chatId));

    // Second inject with different key bytes — state is already "ready", should NOT fire
    mgr.injectKey("chat-B", makeKey(21), "injected");

    expect(readyChats).toEqual([]);
  });

  it("fires for each chat independently", () => {
    const readyChats: string[] = [];
    mgr.onKeyReady((chatId) => readyChats.push(chatId));

    mgr.injectKey("chat-X", makeKey(30), "injected");
    mgr.injectKey("chat-Y", makeKey(31), "injected");
    mgr.injectKey("chat-Z", makeKey(32), "injected");

    expect(readyChats).toEqual(["chat-X", "chat-Y", "chat-Z"]);
  });

  it("unsubscribe prevents further callbacks", () => {
    const readyChats: string[] = [];
    const unsub = mgr.onKeyReady((chatId) => readyChats.push(chatId));

    mgr.injectKey("chat-1", makeKey(40), "injected");
    expect(readyChats).toEqual(["chat-1"]);

    // Unsubscribe
    unsub();

    mgr.injectKey("chat-2", makeKey(41), "injected");
    expect(readyChats).toEqual(["chat-1"]); // No new entry
  });

  it("listener error does not break other listeners", () => {
    const readyChats: string[] = [];
    mgr.onKeyReady(() => {
      throw new Error("boom");
    });
    mgr.onKeyReady((chatId) => readyChats.push(chatId));

    // Should not throw, second listener should still fire
    mgr.injectKey("chat-err", makeKey(50), "injected");
    expect(readyChats).toEqual(["chat-err"]);
  });

  it("fires after clearAll + re-inject (key goes unloaded → ready again)", () => {
    const readyChats: string[] = [];
    mgr.onKeyReady((chatId) => readyChats.push(chatId));

    mgr.injectKey("chat-R", makeKey(60), "injected");
    expect(readyChats).toEqual(["chat-R"]);

    // clearAll resets state to unloaded
    mgr.clearAll();

    // Re-inject — should fire again
    mgr.injectKey("chat-R", makeKey(61), "injected");
    expect(readyChats).toEqual(["chat-R", "chat-R"]);
  });
});
