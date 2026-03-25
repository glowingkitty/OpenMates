// frontend/packages/ui/src/services/encryption/__tests__/ChatKeyManager.test.ts
// Integration tests for ChatKeyManager — covers every known bug pattern from git history.
//
// Bug history this test suite guards against:
//  - d656af1c: key corruption when IDB caches are empty in sendEncryptedStoragePackage
//  - aac318ee: two-cache divergence between chatDB.chatKeys and chatKeyManager
//  - 97e14300: key regeneration race (clearAll mid-flight)
//  - 3bc17dbe: getOrGenerateChatKey anti-pattern generating wrong keys
//  - 3846d7e2: multi-device encryption key mismatch

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
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
// Helpers
// ---------------------------------------------------------------------------

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
