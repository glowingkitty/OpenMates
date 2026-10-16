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
import { setActiveVoiceCallId } from "../voiceCallOwnership";
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

// contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.chat.transcripts,video-call.privacy
it('archives covered confirmed call rows while preserving provisional text and pending ciphertext', async () => {
  setActiveVoiceCallId('active-call');
  const rows = new Map<string, Record<string, unknown>>([
    ['confirmed', { chat_id: 'call-chat', status: 'synced', call_persistence_v1: { entries: [] } }],
    ['active-final', { chat_id: 'call-chat', status: 'synced', call_persistence_v1: { call_id: 'active-call', entries: [] } }],
    ['provisional', { chat_id: 'call-chat', status: 'streaming' }],
    ['queued', { chat_id: 'call-chat', status: 'sending', call_persistence_v1: { entries: [{ revision: 2, ciphertext: 'cipher' }] } }],
    ['pending-synced', { chat_id: 'call-chat', status: 'synced', call_persistence_v1: { entries: [{ revision: 2, ciphertext: 'cipher' }] } }],
    ['typed', { chat_id: 'call-chat', status: 'synced', call_persistence_v1: { typed_pending: true, entries: [] } }],
    ['other-chat', { chat_id: 'other-chat', status: 'synced' }],
  ]);
  let completedReads = 0;
  const deleted: string[] = [];
  const transaction = {
    oncomplete: null as (() => void) | null, onerror: null, onabort: null,
    objectStore: () => ({
      get(id: string) {
        const request = { result: rows.get(id), onsuccess: null as (() => void) | null };
        queueMicrotask(() => {
          request.onsuccess?.();
          if (++completedReads === rows.size) transaction.oncomplete?.();
        });
        return request;
      },
      delete(id: string) { deleted.push(id); },
    }),
  };
  vi.spyOn(chatDB, 'init').mockResolvedValue(undefined);
  vi.spyOn(chatDB, 'getTransaction').mockResolvedValue(transaction as unknown as IDBTransaction);
  expect(await chatDB.deleteCoveredMessagesForChat('call-chat', [...rows.keys()])).toBe(1);
  expect(deleted).toEqual(['confirmed']);
  setActiveVoiceCallId(null);
});
