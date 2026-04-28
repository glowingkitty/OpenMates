// frontend/packages/ui/src/services/db/__tests__/encryptChatForStorage.test.ts
// Tests for the isFromSync guard in encryptChatForStorage.
//
// Root cause this guards against:
//  - During phased sync after logout/login, encryptChatForStorage was called
//    for existing chats with no available key. It fell through to
//    createKeyForNewChat(), generating a NEW random key that overwrote the
//    original, making all existing messages permanently undecryptable.
//
// The fix: when isFromSync=true, Step 4 (key creation) is skipped and the
// chat is stored without a key. The correct key arrives later via
// receiveKeyFromServer().

import { describe, it, expect, beforeEach, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — must be set up before importing the module under test
// ---------------------------------------------------------------------------

// Mock cryptoService
const mockDecryptChatKeyWithMasterKey = vi.fn();
const mockEncryptChatKeyWithMasterKey = vi.fn();
vi.mock("../../cryptoService", () => ({
  encryptChatKeyWithMasterKey: (...args: unknown[]) =>
    mockEncryptChatKeyWithMasterKey(...args),
  decryptChatKeyWithMasterKey: (...args: unknown[]) =>
    mockDecryptChatKeyWithMasterKey(...args),
}));

// Mock ChatKeyManager
const mockGetKeySync = vi.fn();
const mockInjectKey = vi.fn();
const mockCreateKeyForNewChat = vi.fn();
const mockComputeKeyFingerprint = vi.fn().mockReturnValue("abcd1234");
vi.mock("../../encryption/ChatKeyManager", () => ({
  chatKeyManager: {
    getKeySync: (...args: unknown[]) => mockGetKeySync(...args),
    injectKey: (...args: unknown[]) => mockInjectKey(...args),
    createKeyForNewChat: (...args: unknown[]) => mockCreateKeyForNewChat(...args),
    onKeyReady: vi.fn(() => () => {}),
  },
  computeKeyFingerprint: (...args: unknown[]) =>
    mockComputeKeyFingerprint(...args),
}));

// Mock signupState stores (used by addChat guard)
vi.mock("../../../stores/signupState", () => ({
  forcedLogoutInProgress: { subscribe: vi.fn((cb: (v: boolean) => void) => { cb(false); return () => {}; }) },
  isLoggingOut: { subscribe: vi.fn((cb: (v: boolean) => void) => { cb(false); return () => {}; }) },
}));

// Mock svelte/store get()
vi.mock("svelte/store", () => ({
  get: () => false,
  writable: (initial: unknown) => ({
    subscribe: vi.fn((cb: (v: unknown) => void) => {
      cb(initial);
      return () => {};
    }),
    set: vi.fn(),
    update: vi.fn(),
  }),
  derived: () => ({
    subscribe: vi.fn(() => () => {}),
  }),
  readable: (initial: unknown) => ({
    subscribe: vi.fn((cb: (v: unknown) => void) => {
      cb(initial);
      return () => {};
    }),
  }),
}));

import { encryptChatForStorage } from "../chatCrudOperations";
import type { Chat } from "../../../types/chat";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeChat(overrides: Partial<Chat> = {}): Chat {
  return {
    chat_id: "test-chat-123",
    encrypted_title: null,
    encrypted_icon: null,
    encrypted_category: null,
    encrypted_chat_key: null,
    messages_v: 1,
    title_v: 1,
    draft_v: 0,
    encrypted_draft_md: null,
    encrypted_draft_preview: null,
    last_edited_overall_timestamp: 1000,
    unread_count: 0,
    created_at: 1000,
    updated_at: 1000,
    ...overrides,
  } as Chat;
}

function makeDbInstance() {
  return {
    db: null,
    CHATS_STORE_NAME: "chats",
    init: vi.fn().mockResolvedValue(undefined),
    getTransaction: vi.fn(),
    getChat: vi.fn().mockResolvedValue(null),
    getEncryptedChatKey: vi.fn().mockResolvedValue(null),
  };
}

const fakeKey = new Uint8Array(32).fill(42);

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("encryptChatForStorage — isFromSync guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: no key found anywhere
    mockGetKeySync.mockReturnValue(null);
    mockDecryptChatKeyWithMasterKey.mockResolvedValue(null);
    mockEncryptChatKeyWithMasterKey.mockResolvedValue(null);
    mockCreateKeyForNewChat.mockReturnValue(fakeKey);
  });

  it("creates a new key for a genuinely new chat (isFromSync=false, default)", async () => {
    const db = makeDbInstance();
    const chat = makeChat();

    mockEncryptChatKeyWithMasterKey.mockResolvedValue("encrypted-key-base64");

    const result = await encryptChatForStorage(db as any, chat);

    // Step 4 should have been called — this IS a new chat
    expect(mockCreateKeyForNewChat).toHaveBeenCalledWith("test-chat-123");
    expect(result.encrypted_chat_key).toBe("encrypted-key-base64");
    expect(result.key_fingerprint).toBe("abcd1234");
  });

  it("NEVER creates a new key when isFromSync=true (sync guard)", async () => {
    const db = makeDbInstance();
    const chat = makeChat();

    const result = await encryptChatForStorage(db as any, chat, {
      isFromSync: true,
    });

    // Step 4 must NOT be called — this is a synced chat
    expect(mockCreateKeyForNewChat).not.toHaveBeenCalled();
    // Chat should be returned without key_fingerprint (no key was loaded)
    expect(result.encrypted_chat_key).toBeNull();
  });

  it("uses existing key from ChatKeyManager even when isFromSync=true", async () => {
    const db = makeDbInstance();
    const chat = makeChat();

    // Key already in ChatKeyManager (Step 1 succeeds)
    mockGetKeySync.mockReturnValue(fakeKey);
    mockEncryptChatKeyWithMasterKey.mockResolvedValue("encrypted-existing");

    const result = await encryptChatForStorage(db as any, chat, {
      isFromSync: true,
    });

    // Should use existing key, not create a new one
    expect(mockCreateKeyForNewChat).not.toHaveBeenCalled();
    expect(result.encrypted_chat_key).toBe("encrypted-existing");
    expect(result.key_fingerprint).toBe("abcd1234");
  });

  it("decrypts server-provided encrypted_chat_key during sync (Step 2)", async () => {
    const db = makeDbInstance();
    const chat = makeChat({ encrypted_chat_key: "server-encrypted-key" });

    // Step 2: server key decrypts successfully and injectKey accepts it
    mockDecryptChatKeyWithMasterKey.mockResolvedValue(fakeKey);
    mockInjectKey.mockReturnValue(true);
    mockEncryptChatKeyWithMasterKey.mockResolvedValue("re-encrypted");

    const result = await encryptChatForStorage(db as any, chat, {
      isFromSync: true,
    });

    // Should decrypt and inject the server key
    expect(mockDecryptChatKeyWithMasterKey).toHaveBeenCalledWith(
      "server-encrypted-key",
    );
    expect(mockInjectKey).toHaveBeenCalledWith(
      "test-chat-123",
      fakeKey,
      "master_key",
    );
    expect(mockCreateKeyForNewChat).not.toHaveBeenCalled();
    // Should preserve the original server-encrypted key
    expect(result.encrypted_chat_key).toBe("server-encrypted-key");
  });

  it("does NOT overwrite IDB key when server key is rejected by injectKey (step 2 regression)", async () => {
    // Regression: aac318eee added injectKey guard for memory but forgot to gate
    // the IDB write. When injectKey returns false (key conflict), the server's
    // encrypted_chat_key must NOT be saved to IDB — it would corrupt decryption
    // after the next page reload.
    const db = makeDbInstance();
    const chat = makeChat({ encrypted_chat_key: "server-encrypted-key-wrong" });

    // Step 2: server key decrypts but injectKey REJECTS it (conflict with loaded key)
    mockDecryptChatKeyWithMasterKey
      .mockResolvedValueOnce(new Uint8Array(32).fill(99)) // server key (rejected)
      .mockResolvedValueOnce(fakeKey); // IDB key (accepted in step 3)
    mockInjectKey
      .mockReturnValueOnce(false) // step 2 rejection
      .mockReturnValueOnce(true); // step 3 acceptance

    // Step 3: IDB has the correct key
    db.getChat.mockResolvedValue({
      chat_id: "test-chat-123",
      encrypted_chat_key: "idb-correct-key",
    });

    const result = await encryptChatForStorage(db as any, chat, {
      isFromSync: true,
    });

    expect(mockCreateKeyForNewChat).not.toHaveBeenCalled();
    // IDB key must win — server's wrong key must NOT appear here
    expect(result.encrypted_chat_key).toBe("idb-correct-key");
    expect(result.encrypted_chat_key).not.toBe("server-encrypted-key-wrong");
  });

  it("does NOT store a conflicting server key when a different key is already cached", async () => {
    const db = makeDbInstance();
    const chat = makeChat({ encrypted_chat_key: "server-encrypted-key-wrong" });
    const incomingWrongKey = new Uint8Array(32).fill(99);

    mockGetKeySync.mockReturnValue(fakeKey);
    mockDecryptChatKeyWithMasterKey.mockResolvedValue(incomingWrongKey);
    db.getChat.mockResolvedValue({
      chat_id: "test-chat-123",
      encrypted_chat_key: "idb-correct-key",
    });

    const result = await encryptChatForStorage(db as any, chat, {
      isFromSync: true,
    });

    expect(mockCreateKeyForNewChat).not.toHaveBeenCalled();
    expect(result.encrypted_chat_key).toBe("idb-correct-key");
    expect(result.encrypted_chat_key).not.toBe("server-encrypted-key-wrong");
    expect(result.key_fingerprint).toBe("abcd1234");
  });

  it("falls back to IDB key during sync (Step 3)", async () => {
    const db = makeDbInstance();
    const chat = makeChat(); // No encrypted_chat_key from server

    // Step 3: IDB has the key and injectKey accepts it
    db.getChat.mockResolvedValue({
      chat_id: "test-chat-123",
      encrypted_chat_key: "idb-encrypted-key",
    });
    mockDecryptChatKeyWithMasterKey.mockResolvedValue(fakeKey);
    mockInjectKey.mockReturnValue(true);

    await encryptChatForStorage(db as any, chat, {
      isFromSync: true,
    });

    expect(mockDecryptChatKeyWithMasterKey).toHaveBeenCalledWith(
      "idb-encrypted-key",
    );
    expect(mockInjectKey).toHaveBeenCalledWith(
      "test-chat-123",
      fakeKey,
      "master_key",
    );
    expect(mockCreateKeyForNewChat).not.toHaveBeenCalled();
  });

  it("returns early without key when all steps fail during sync", async () => {
    const db = makeDbInstance();
    const chat = makeChat(); // No server key
    db.getChat.mockResolvedValue(null); // No IDB key

    const consoleSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    const result = await encryptChatForStorage(db as any, chat, {
      isFromSync: true,
    });

    // Must NOT create a key
    expect(mockCreateKeyForNewChat).not.toHaveBeenCalled();

    // Should log the sync guard warning
    expect(consoleSpy).toHaveBeenCalledWith(
      expect.stringContaining("SYNC GUARD"),
    );

    // Chat returned without key data
    expect(result.encrypted_chat_key).toBeNull();

    consoleSpy.mockRestore();
  });

  it("skips encryption for public chats regardless of isFromSync", async () => {
    const db = makeDbInstance();
    const demoChat = makeChat({ chat_id: "demo-welcome" });

    const result = await encryptChatForStorage(db as any, demoChat, {
      isFromSync: true,
    });

    expect(mockCreateKeyForNewChat).not.toHaveBeenCalled();
    expect(mockGetKeySync).not.toHaveBeenCalled();
    expect(result.chat_id).toBe("demo-welcome");
  });
});
