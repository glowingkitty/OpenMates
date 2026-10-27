/** Exercise the actual sealed completion handler through correlated claims and CAS replies. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  refreshRecoveryChatVersion: vi.fn(),
  notifyError: vi.fn(),
  failTurn: vi.fn(),
  chatDB: {
    getMessage: vi.fn(),
    getChat: vi.fn(),
    saveMessage: vi.fn(),
    updateChat: vi.fn(),
    getEncryptedFields: vi.fn(),
  },
  chatKeyManager: {
    getKey: vi.fn(),
    getKeySync: vi.fn(),
    injectKey: vi.fn(),
    onKeyReady: vi.fn(() => () => undefined),
  },
  ensureChatKeySafeForWrite: vi.fn(),
  webSocketService: {
    on: vi.fn(),
    off: vi.fn(),
    sendMessage: vi.fn(),
    getConnectionForSend: vi.fn(),
    requestForegroundRecoveryDiscovery: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  },
  deriveChatCompletionRecoveryKeypair: vi.fn(),
  openChatCompletionRecoveryEnvelope: vi.fn(),
  openRecoveryOutputEnvelope: vi.fn(),
}));

vi.mock("../chatRecoveryVersionRefresh", () => ({ refreshRecoveryChatVersion: mocks.refreshRecoveryChatVersion }));
vi.mock("../personalChatTurnBarrier", async importOriginal => ({
  ...await importOriginal(), failMatchingPersonalChatTurn: mocks.failTurn,
}));
vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../userDB", () => ({ userDB: { getUserProfile: vi.fn() } }));
vi.mock("../../stores/notificationStore", () => ({ notificationStore: { chatMessage: vi.fn(), error: mocks.notifyError } }));
vi.mock("../../stores/unreadMessagesStore", () => ({ unreadMessagesStore: { incrementUnread: vi.fn() } }));
vi.mock("../chatNotificationVisibility", () => ({ isChatVisiblyActive: vi.fn(() => true) }));
vi.mock("../embedDiffStore", () => ({ reconstructEncryptedVersionRows: vi.fn() }));
vi.mock("../recoveryEmbedSource", () => ({ historySourceFromSealedEmbed: vi.fn() }));
vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: mocks.chatKeyManager,
}));
vi.mock("../chatKeyWriteGuard", () => ({
  ensureChatKeySafeForWrite: mocks.ensureChatKeySafeForWrite,
}));
vi.mock("../websocketService", () => ({
  webSocketService: mocks.webSocketService,
}));
vi.mock("../../utils/chatCompletionRecovery", () => ({
  deriveChatCompletionRecoveryKeypair: mocks.deriveChatCompletionRecoveryKeypair,
  openChatCompletionRecoveryEnvelope: mocks.openChatCompletionRecoveryEnvelope,
  openRecoveryOutputEnvelope: mocks.openRecoveryOutputEnvelope,
}));

const { handleRecoveryJobsAvailableImpl, resetRecoveryLifecycleImpl } = await import("../chatSyncServiceHandlersRecovery.ts");

describe("browser completion compare-and-swap races", () => {
  beforeEach(() => {
    vi.clearAllMocks(); mocks.refreshRecoveryChatVersion.mockReset(); vi.useFakeTimers();
    let requestCounter = 0;
    vi.spyOn(globalThis.crypto, "randomUUID").mockImplementation(() => `cas-request-${++requestCounter}`);
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    vi.spyOn(console, "error").mockImplementation(() => {});
    globalThis.window = globalThis;
    mocks.chatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mocks.ensureChatKeySafeForWrite.mockResolvedValue(true);
    mocks.chatDB.getEncryptedFields.mockResolvedValue({ encrypted_content: "same-ciphertext" });
  });
  afterEach(() => { resetRecoveryLifecycleImpl(); vi.useRealTimers(); vi.restoreAllMocks(); });

  async function recover({ conflicts = 2, code = "version_conflict", refresh, mutateWrite, finishPaused = false } = {}) {
    const handlers = new Map();
    mocks.webSocketService.on.mockImplementation((type, handler) => handlers.set(type, handler));
    mocks.webSocketService.off.mockImplementation(type => handlers.delete(type));
    const originalChat = { chat_id: "chat-1", user_id: "owner", team_id: "team", messages_v: 7 };
    const callerChat = { ...originalChat };
    mocks.chatDB.getChat.mockResolvedValue({ ...originalChat }).mockResolvedValueOnce(callerChat);
    mocks.chatDB.getMessage.mockResolvedValue(undefined);
    let connection = {};
    mocks.webSocketService.getConnectionForSend.mockImplementation(() => connection);
    const replaceConnection = () => { connection = {}; };
    let refreshCount = 0;
    mocks.refreshRecoveryChatVersion.mockImplementation(async captured => {
      refreshCount += 1;
      if (refresh) return refresh({ captured, callerChat, originalChat, replaceConnection });
      return { ...originalChat, messages_v: refreshCount + 2 };
    });
    mocks.deriveChatCompletionRecoveryKeypair.mockResolvedValue({ privateKey: "private-key" });
    mocks.openChatCompletionRecoveryEnvelope.mockResolvedValue(new TextEncoder().encode(JSON.stringify({
      job_id: "job-1", chat_id: "chat-1", turn_id: "turn-1", assistant_message_id: "assistant-1",
      key_version: 1, content: "Fixture reply", category: null, model_name: null,
    })));
    const writes = [];
    mocks.webSocketService.sendMessage.mockImplementation(async (type, payload) => {
      if (type === "recovery_job_claim") queueMicrotask(() => handlers.get("recovery_job_claimed")?.({
        ...payload, state: "LEASED", lease_token: "lease", lease_generation: 2, sealed_payload: "{}",
        chat_id: "chat-1", turn_id: "turn-1", assistant_message_id: "assistant-1", chat_key_version: 1,
      }));
      if (type === "recovery_job_persist") {
        writes.push(payload);
        if (writes.length === 1) mutateWrite?.(callerChat, { replaceConnection });
        queueMicrotask(() => writes.length <= conflicts
          ? handlers.get("error")?.({ job_id: payload.job_id, request_id: payload.request_id, code })
          : handlers.get("recovery_job_persisted")?.({ job_id: payload.job_id, request_id: payload.request_id,
            state: "TERMINAL", committed_messages_v: 5 }));
      }
    });
    const service = { dispatchEvent: vi.fn(), hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
      requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined) };
    const pending = handleRecoveryJobsAvailableImpl(service, { jobs: [{ job_id: "job-1", chat_id: "chat-1",
      turn_id: "turn-1", assistant_message_id: "assistant-1", chat_key_version: 1, created_at: 1 }] });
    await vi.advanceTimersByTimeAsync(0);
    // An acknowledged write correctly waits for fresh foreground discovery.
    if (finishPaused) resetRecoveryLifecycleImpl();
    await pending;
    return { writes, service };
  }

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.completion.lease-fenced,chats.message.identity-idempotent
  it("persists the same sealed reply after optimistic drift then a concurrent call-end append", async () => {
    const { writes } = await recover();
    expect(mocks.chatDB.saveMessage).toHaveBeenCalledTimes(1);
    expect(writes.map(write => write.expected_messages_v)).toEqual([7, 3, 4]);
    const withoutRequestAndCounter = ({ request_id: _requestId, expected_messages_v: _version, ...sealed }) => sealed;
    for (const write of writes) expect(withoutRequestAndCounter(write)).toEqual(withoutRequestAndCounter(writes[0]));
    expect(new Set(writes.map(write => write.request_id)).size).toBe(3);
    expect(mocks.chatDB.getEncryptedFields).toHaveBeenCalledTimes(1);
    expect(mocks.failTurn).not.toHaveBeenCalled();
    expect(mocks.notifyError).not.toHaveBeenCalled();
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("fails the turn after exactly four conflicting writes and three authoritative refreshes", async () => {
    const { writes } = await recover({ conflicts: 4 });
    expect(writes.map(write => write.expected_messages_v)).toEqual([7, 3, 4, 5]);
    expect(mocks.refreshRecoveryChatVersion).toHaveBeenCalledTimes(3);
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
    expect(mocks.failTurn).toHaveBeenCalledWith("chat-1", "turn-1", expect.objectContaining({ code: "version_conflict" }));
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("never retries a non-version lease failure", async () => {
    const { writes } = await recover({ code: "stale_lease" });
    expect(writes).toHaveLength(1);
    expect(mocks.refreshRecoveryChatVersion).not.toHaveBeenCalled();
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
    expect(mocks.failTurn).toHaveBeenCalledWith("chat-1", "turn-1", expect.objectContaining({ code: "stale_lease" }));
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it.each([null, { chat_id: "other", messages_v: 3 }, ...[-1, 0.5, true, "4", Number.MAX_SAFE_INTEGER + 1].map(messages_v => ({ chat_id: "chat-1", messages_v }))])("fails closed on invalid authoritative refresh %j", async refreshed => {
    const { writes } = await recover({ refresh: async () => refreshed });
    expect(writes).toHaveLength(1);
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
    expect(mocks.failTurn).toHaveBeenCalledWith("chat-1", "turn-1", expect.objectContaining({ code: "version_conflict" }));
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("preserves a refresh rejection rather than guessing a counter", async () => {
    const denied = new Error("fixture read rejected");
    const { writes } = await recover({ refresh: async () => { throw denied; } });
    expect(writes).toHaveLength(1);
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
    expect(mocks.failTurn).toHaveBeenCalledWith("chat-1", "turn-1", denied);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("keeps captured owner/team/chat scope despite caller mutation during writes and refreshes", async () => {
    let count = 0;
    const { writes } = await recover({ mutateWrite: caller => Object.assign(caller, {
      chat_id: "changed-chat", user_id: "changed-owner", team_id: "changed-team",
    }), refresh: async ({ captured, callerChat, originalChat }) => {
      expect(captured).toMatchObject({ chat_id: "chat-1", user_id: "owner", team_id: "team" });
      callerChat.user_id = "another-owner";
      return { ...originalChat, messages_v: ++count + 2, user_id: "untrusted-refreshed-owner" };
    } });
    expect(writes.map(write => write.expected_messages_v)).toEqual([7, 3, 4]);
    expect(mocks.chatDB.saveMessage).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it.each(["session", "socket", "foreground"].flatMap(kind => ["write", "refresh"].map(stage => ({ kind, stage }))))("stops after $kind authority changes during an awaited $stage", async ({ kind, stage }) => {
    const revoke = ({ replaceConnection }) => {
      if (kind === "session") resetRecoveryLifecycleImpl();
      if (kind === "socket") replaceConnection();
      if (kind === "foreground") {
        vi.mocked(document.hasFocus).mockReturnValue(false);
        window.dispatchEvent(new Event("blur"));
      }
    };
    const { writes } = await recover({
      conflicts: stage === "write" ? 0 : 2,
      finishPaused: stage === "write" && kind === "foreground",
      mutateWrite: stage === "write" ? (_caller, authority) => revoke(authority) : undefined,
      refresh: async ({ originalChat, replaceConnection }) => {
        revoke({ replaceConnection });
        return { ...originalChat, messages_v: 3 };
      },
    });
    expect(writes).toHaveLength(1);
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
  });
});
