import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getKeyFromStorage: vi.fn(),
  decryptChatKeyWithMasterKey: vi.fn(),
  injectKey: vi.fn(),
  hasKey: vi.fn(),
  clearAll: vi.fn(),
  keys: new Map<string, Uint8Array>(),
  forcedLogout: false,
  teamId: null as string | null,
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
vi.mock("../../../stores/teamStore", () => ({
  getActiveTeamContextSnapshot: () => ({ teamId: mocks.teamId }),
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
  getCachedPinnedChatIds,
  loadChatKeysFromDatabase,
} from "../chatKeyManagement";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((fulfill) => { resolve = fulfill; });
  return { promise, resolve };
}

function chatWithKey(chatId: string, extra: Record<string, unknown> = {}) {
  return { chat_id: chatId, encrypted_chat_key: `encrypted-${chatId}`, messages_v: 2, title_v: 1, draft_v: 0, ...extra };
}

function databaseWithChats(chats: ReturnType<typeof chatWithKey>[]) {
  const request: { result: unknown; onsuccess?: (event: unknown) => void } = { result: null };
  let next = 0;
  const read = () => queueMicrotask(() => {
    request.result = next < chats.length ? { value: chats[next++], continue: read } : null;
    request.onsuccess?.({ target: request });
  });
  const db = {
    CHATS_STORE_NAME: "chats",
    getChat: vi.fn(),
    db: {
      transaction: () => ({
        objectStore: () => ({ openCursor: () => { read(); return request; } }),
      }),
    },
  };
  return db as unknown as Parameters<typeof loadChatKeysFromDatabase>[0];
}

function databaseWithChat(chatId: string) {
  return databaseWithChats([chatWithKey(chatId)]);
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
    mocks.teamId = null;
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

  // contract-test: supporting surface=gui.web assertions=sync.startup.recent-metadata-cap,sync.deletion.partial-window-not-authoritative
  it("bounds eager key unwrap while retaining versions and pins from the full cursor", async () => {
    const rows = Array.from({ length: 105 }, (_, index) =>
      chatWithKey(`parent-${index}`, {
        updated_at: index + 1,
        ...(index === 0 ? { pinned: true } : {}),
      }),
    );
    rows.splice(30, 0,
      chatWithKey("child", { last_edited_overall_timestamp: 1000, parent_id: "parent-104" }),
      chatWithKey("team-chat", { last_edited_overall_timestamp: 1000, team_id: "other-team", pinned: true }),
    );
    mocks.hasKey.mockImplementation(id => id === "parent-104");

    await loadChatKeysFromDatabase(databaseWithChats(rows));

    expect(mocks.decryptChatKeyWithMasterKey).toHaveBeenCalledTimes(99);
    expect(mocks.decryptChatKeyWithMasterKey).toHaveBeenCalledWith("encrypted-parent-5", masterKey);
    expect(mocks.decryptChatKeyWithMasterKey).not.toHaveBeenCalledWith("encrypted-parent-4", masterKey);
    expect(mocks.keys.has("child")).toBe(false);
    expect(mocks.keys.has("team-chat")).toBe(false);
    expect(getCachedChatVersionMap().size).toBe(107);
    expect(getCachedPinnedChatIds(null)).toEqual(["parent-0"]);
    expect(getCachedPinnedChatIds("other-team")).toEqual(["team-chat"]);
  });

  // contract-test: infrastructure
  it("loads a current chat key and caches its version", async () => {
    await loadChatKeysFromDatabase(databaseWithChat("current-chat"));

    expect(mocks.injectKey).toHaveBeenCalledExactlyOnceWith("current-chat", key, "bulk_init");
    expect(getCachedChatVersionMap().get("current-chat")?.messages_v).toBe(2);
  });
});
