import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("$app/environment", () => ({ browser: false }));
vi.mock("../db/newChatSuggestions", () => ({}));
vi.mock("../db/pendingEmbedQueue", () => ({ putPendingEmbedOperation: vi.fn() }));
vi.mock("../db/appSettingsMemories", () => ({}));
vi.mock("../db/chatKeyManagement", () => ({}));
vi.mock("../db/messageOperations", () => ({}));
vi.mock("../db/chatCrudOperations", () => ({}));
vi.mock("../db/offlineChangesAndUpdates", () => ({}));
vi.mock("../db/quotaRecovery", () => ({ writeWithQuotaRetry: vi.fn() }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: {} }));
vi.mock("../../stores/notificationStore", () => ({ notificationStore: {} }));
vi.mock("../cryptoService", () => ({ getKeyFromStorage: async () => null }));
vi.mock("../../stores/signupState", () => ({
  forcedLogoutInProgress: {}, isLoggingOut: {},
  setForcedLogoutInProgress: vi.fn(), lastResumeTimestamp: 0, RESUME_ORPHAN_GRACE_MS: 3000,
}));

import { chatDB } from "../db";
import { setForcedLogoutInProgress } from "../../stores/signupState";

async function checkRows(rows: Record<string, unknown>[]): Promise<void> {
  let finish!: () => void;
  const completed = new Promise<void>((resolve) => { finish = resolve; });
  const request: { result: unknown; onsuccess?: () => void } = { result: null };
  let index = 0;
  const cursor = {
    get value() { return rows[index]; },
    continue() { index++; advance(); },
  };
  function advance() {
    request.result = index < rows.length ? cursor : null;
    queueMicrotask(() => request.onsuccess?.());
  }
  const db = {
    transaction: () => ({ objectStore: () => ({ openCursor: () => { advance(); return request; } }) }),
    close: finish,
  };
  vi.stubGlobal("indexedDB", {
    open: () => {
      const openRequest: { onsuccess?: (event: unknown) => void } = {};
      queueMicrotask(() => openRequest.onsuccess?.({ target: { result: db } }));
      return openRequest;
    },
  });
  await (chatDB as unknown as { _runOrphanKeyCheck(): Promise<void> })._runOrphanKeyCheck();
  await completed;
}

describe("anonymous database startup", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key: string) => key === "openmates_chats_db_initialized" ? "true" : null),
      setItem: vi.fn(),
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  // contract-test: supporting surface=gui.web assertions=billing.anonymous.local-only-content,auth.session.isolation
  it("preserves anonymous rows when generic startup runs before the anonymous storage facade", async () => {
    await checkRows([{ chat_id: "anonymous-local", is_anonymous: true, anonymous_encrypted_chat_key: "tab-wrapped" }]);
    expect(setForcedLogoutInProgress).not.toHaveBeenCalled();
    expect(localStorage.setItem).not.toHaveBeenCalledWith("openmates_needs_cleanup", "true");
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.isolation
  it("still detects account-owned orphan rows alongside anonymous rows", async () => {
    await checkRows([{ is_anonymous: true }, { chat_id: "account-chat", encrypted_chat_key: "account-wrapped" }]);
    expect(setForcedLogoutInProgress).toHaveBeenCalledOnce();
    expect(localStorage.setItem).toHaveBeenCalledWith("openmates_needs_cleanup", "true");
  });
});
