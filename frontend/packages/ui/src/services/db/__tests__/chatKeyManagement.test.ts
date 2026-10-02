import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getKeyFromStorage: vi.fn(),
  decryptChatKeyWithMasterKey: vi.fn(),
  injectKey: vi.fn(),
  hasKey: vi.fn(),
  clearAll: vi.fn(),
  keys: new Map<string, Uint8Array>(),
  forcedLogout: false,
}));

vi.mock("../../cryptoService", () => ({
  getKeyFromStorage: mocks.getKeyFromStorage,
  decryptChatKeyWithMasterKey: mocks.decryptChatKeyWithMasterKey,
}));
vi.mock("../../encryption/ChatKeyManager", () => ({
  chatKeyManager: {
    injectKey: mocks.injectKey,
    hasKey: mocks.hasKey,
    clearAll: mocks.clearAll,
  },
}));
vi.mock("../../../stores/signupState", () => ({
  forcedLogoutInProgress: {
    subscribe: (callback: (value: boolean) => void) => {
      callback(mocks.forcedLogout);
      return () => {};
    },
  },
}));

import {
  clearAllChatKeys,
  getCachedChatVersionMap,
  loadChatKeysFromDatabase,
} from "../chatKeyManagement";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((fulfill) => { resolve = fulfill; });
  return { promise, resolve };
}

function databaseWithChat(chatId: string) {
  const request: { result: unknown; onsuccess?: (event: unknown) => void } = {
    result: null,
  };
  const chat = {
    chat_id: chatId,
    encrypted_chat_key: `encrypted-${chatId}`,
    messages_v: 2,
    title_v: 1,
    draft_v: 0,
  };
  const cursor = {
    value: chat,
    continue: () => queueMicrotask(() => {
      request.result = null;
      request.onsuccess?.({ target: request });
    }),
  };
  const db = {
    CHATS_STORE_NAME: "chats",
    getChat: vi.fn(),
    db: {
      transaction: () => ({
        objectStore: () => ({ openCursor: () => {
          queueMicrotask(() => {
            request.result = cursor;
            request.onsuccess?.({ target: request });
          });
          return request;
        } }),
      }),
    },
  };
  return db as unknown as Parameters<typeof loadChatKeysFromDatabase>[0];
}

describe("bulk chat key loading across logout", () => {
  const key = new Uint8Array(32).fill(7);
  const masterKey = { id: "master" };

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.keys.clear();
    mocks.injectKey.mockImplementation((chatId: string, chatKey: Uint8Array) => {
      mocks.keys.set(chatId, chatKey);
    });
    mocks.clearAll.mockImplementation(() => mocks.keys.clear());
    mocks.forcedLogout = false;
    mocks.hasKey.mockReturnValue(false);
    mocks.getKeyFromStorage.mockResolvedValue(masterKey);
    mocks.decryptChatKeyWithMasterKey.mockResolvedValue(key);
    clearAllChatKeys(databaseWithChat("setup"));
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // contract-test: direct surface=gui.web assertions=auth.secrets.lifecycle
  it("drops a decrypted key when logout clears keys during decryption", async () => {
    const pendingDecrypt = deferred<Uint8Array>();
    mocks.decryptChatKeyWithMasterKey.mockReturnValue(pendingDecrypt.promise);

    const load = loadChatKeysFromDatabase(databaseWithChat("old-chat"));
    await vi.waitFor(() => expect(mocks.decryptChatKeyWithMasterKey).toHaveBeenCalled());
    mocks.forcedLogout = true;
    clearAllChatKeys(databaseWithChat("old-chat"));
    pendingDecrypt.resolve(key);
    await load;

    expect(mocks.injectKey).not.toHaveBeenCalled();
    expect(mocks.keys.size).toBe(0);
    expect(getCachedChatVersionMap().size).toBe(0);
  });

  // contract-test: direct surface=gui.web assertions=auth.secrets.lifecycle
  it("ignores an old scheduled retry after logout and a new login", async () => {
    vi.useFakeTimers();
    mocks.getKeyFromStorage.mockResolvedValueOnce(null).mockResolvedValue(masterKey);
    await loadChatKeysFromDatabase(databaseWithChat("old-chat"));

    mocks.forcedLogout = true;
    clearAllChatKeys(databaseWithChat("old-chat"));
    mocks.forcedLogout = false;
    await loadChatKeysFromDatabase(databaseWithChat("new-chat"));
    await vi.advanceTimersByTimeAsync(500);

    expect(mocks.injectKey).toHaveBeenCalledExactlyOnceWith("new-chat", key, "bulk_init");
    expect(mocks.decryptChatKeyWithMasterKey).toHaveBeenCalledExactlyOnceWith("encrypted-new-chat", masterKey);
  });

  // contract-test: infrastructure
  it("loads a current chat key and caches its version", async () => {
    await loadChatKeysFromDatabase(databaseWithChat("current-chat"));

    expect(mocks.injectKey).toHaveBeenCalledExactlyOnceWith("current-chat", key, "bulk_init");
    expect(getCachedChatVersionMap().get("current-chat")?.messages_v).toBe(2);
  });
});
