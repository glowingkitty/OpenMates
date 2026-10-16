/**
 * Recovery request-correlation tests.
 *
 * Verifies that delayed WebSocket frames from an earlier recovery attempt cannot
 * complete or abort a newer retry for the same sealed completion job.
 */

import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
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
  },
  deriveChatCompletionRecoveryKeypair: vi.fn(),
  openChatCompletionRecoveryEnvelope: vi.fn(),
  openRecoveryOutputEnvelope: vi.fn(),
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../userDB", () => ({ userDB: { getUserProfile: vi.fn() } }));
vi.mock("../../stores/notificationStore", () => ({ notificationStore: { chatMessage: vi.fn() } }));
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

const {
  handleRecoveryJobsAvailableImpl, handleRecoveryOutputsAvailableImpl,
  prepareRecoveryLifecycleImpl, resetRecoveryLifecycleImpl,
} = await import("../chatSyncServiceHandlersRecovery.ts");

const { getEncryptedFields } = await import("../db/chatKeyManagement.ts");
const { recordRecoveryFinalTimestamp } = await import("../recoveryAssistantTimestamp.ts");
const { decryptWithChatKey } = await import("../encryption/MessageEncryptor.ts");

describe("recovery job request correlation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    let requestCounter = 0;
    vi.spyOn(globalThis.crypto, "randomUUID").mockImplementation(
      () => `recovery-request-${requestCounter += 1}`,
    );
    vi.spyOn(document, "hasFocus").mockReturnValue(true);
    globalThis.window = globalThis;
    mocks.chatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mocks.ensureChatKeySafeForWrite.mockResolvedValue(true);
    mocks.chatDB.getEncryptedFields.mockResolvedValue({
      encrypted_content: "encrypted-content",
      encrypted_sender_name: "encrypted-sender",
      encrypted_category: "encrypted-category",
      encrypted_model_name: "encrypted-model",
    });
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.completion.lease-fenced
  it("stops an in-flight claim on blur and retries once after duplicate ACK and fresh discovery", async () => {
    const handlers = new Map();
    const originalVisibility = Object.getOwnPropertyDescriptor(document, "visibilityState");
    let focused = true;
    Object.defineProperty(document, "visibilityState", {
      configurable: true, get: () => "visible",
    });
    vi.mocked(document.hasFocus).mockImplementation(() => focused);
    mocks.webSocketService.on.mockImplementation((type, handler) => handlers.set(type, handler));
    mocks.webSocketService.off.mockImplementation((type) => handlers.delete(type));
    const service = {
      hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
      requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined),
      dispatchEvent: vi.fn(),
    };
    const job = {
      job_id: "foreground-job", chat_id: "chat-1", turn_id: "turn-1",
      assistant_message_id: "assistant-1", chat_key_version: 1,
    };
    mocks.chatDB.getChat.mockResolvedValue({ chat_id: "chat-1", user_id: "user-1", messages_v: 2 });
    try {
      const firstAttempt = handleRecoveryJobsAvailableImpl(service, { jobs: [job] });
      await vi.advanceTimersByTimeAsync(0);
      expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
        "recovery_job_claim", expect.objectContaining({ job_id: job.job_id }),
      );
      focused = false;
      window.dispatchEvent(new Event("blur"));
      expect(mocks.webSocketService.sendMessage).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(120_000);
      expect(mocks.webSocketService.sendMessage).toHaveBeenCalledTimes(1);
      focused = true;
      window.dispatchEvent(new Event("focus"));
      await handleRecoveryJobsAvailableImpl(service, { jobs: [job] });
      expect(mocks.webSocketService.sendMessage).toHaveBeenCalledTimes(1);
      handlers.get("native_client_lifecycle_ack")?.({ is_foreground: true });
      await handleRecoveryJobsAvailableImpl(service, { jobs: [job] });
      handlers.get("native_client_lifecycle_ack")?.({ is_foreground: true });
      handlers.get("recovery_outputs_discovery_complete")?.({ status: "failed" });
      expect(mocks.webSocketService.sendMessage).toHaveBeenCalledTimes(1);
      handlers.get("recovery_outputs_discovery_complete")?.({ status: "completed" });
      await firstAttempt;
      await vi.advanceTimersByTimeAsync(0);
      expect(mocks.webSocketService.sendMessage).toHaveBeenCalledTimes(2);
    } finally {
      if (originalVisibility) Object.defineProperty(document, "visibilityState", originalVisibility);
    }
  });

  afterEach(() => {
    resetRecoveryLifecycleImpl();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("re-registers the first foreground barrier after logout without retaining prior jobs", async () => {
    const handlers = new Map();
    let focused = false;
    vi.mocked(document.hasFocus).mockImplementation(() => focused);
    mocks.webSocketService.on.mockImplementation((type, handler) => handlers.set(type, handler));
    mocks.webSocketService.off.mockImplementation((type) => handlers.delete(type));
    mocks.chatDB.getChat.mockResolvedValue({ chat_id: "chat-new", user_id: "user-new", messages_v: 2 });
    const service = {
      hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
      requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined),
      dispatchEvent: vi.fn(),
    };
    const oldJob = {
      job_id: "old-account-job", chat_id: "chat-old", turn_id: "turn-old",
      assistant_message_id: "assistant-old", chat_key_version: 1,
    };
    const newJob = {
      job_id: "new-account-job", chat_id: "chat-new", turn_id: "turn-new",
      assistant_message_id: "assistant-new", chat_key_version: 1,
    };
    prepareRecoveryLifecycleImpl(service);
    handlers.get("native_client_lifecycle_ack")?.({ is_foreground: false });
    await handleRecoveryJobsAvailableImpl(service, { jobs: [oldJob] });
    focused = true;
    handlers.get("native_client_lifecycle_ack")?.({ is_foreground: true });
    await handleRecoveryJobsAvailableImpl(service, { jobs: [oldJob] });
    handlers.get("recovery_outputs_discovery_complete")?.({ status: "completed" });
    void handleRecoveryOutputsAvailableImpl(service, { outputs: [{
      record_id: "old-output", root_chat_id: "chat-old", target_chat_id: "chat-old",
      turn_id: "turn-old", subject_id: "assistant-old", output_kind: "message",
      output_version: 1, chat_key_version: 1, message_role: "assistant",
    }] });
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalled();
    resetRecoveryLifecycleImpl();
    expect(handlers.has("native_client_lifecycle_ack")).toBe(false);
    expect(handlers.has("recovery_outputs_discovery_complete")).toBe(false);
    focused = false;
    prepareRecoveryLifecycleImpl(service);
    focused = true;
    window.dispatchEvent(new Event("focus"));
    handlers.get("native_client_lifecycle_ack")?.({ is_foreground: true });
    await handleRecoveryJobsAvailableImpl(service, { jobs: [newJob] });
    handlers.get("recovery_outputs_discovery_complete")?.({ status: "completed" });
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.webSocketService.sendMessage).toHaveBeenCalledTimes(1);
    expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "recovery_job_claim", expect.objectContaining({ job_id: newJob.job_id }),
    );
    expect(mocks.chatDB.getChat).not.toHaveBeenCalledWith("chat-old");
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("notifies the exact task when a resumed recovery claim is already terminal", async () => {
    const handlers = new Map();
    mocks.webSocketService.on.mockImplementation((type, handler) => handlers.set(type, handler));
    mocks.webSocketService.off.mockImplementation((type) => handlers.delete(type));
    mocks.webSocketService.sendMessage.mockImplementation(async (type, payload) => {
      if (type !== "recovery_job_claim") return;
      queueMicrotask(() => handlers.get("recovery_job_claimed")?.({
        request_id: payload.request_id, job_id: "job-terminal", state: "TERMINAL",
        chat_id: "chat-terminal", turn_id: "user-terminal",
        assistant_message_id: "assistant-terminal", chat_key_version: 1,
      }));
    });
    mocks.chatDB.getChat.mockResolvedValue({ chat_id: "chat-terminal", user_id: "owner" });
    const activeAITasks = new Map([["chat-terminal", {
      taskId: "assistant-terminal", userMessageId: "user-terminal",
    }]]);
    const service = {
      dispatchEvent: vi.fn(), activeAITasks,
      hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
      requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined),
    };
    await handleRecoveryJobsAvailableImpl(service, { jobs: [{
      job_id: "job-terminal", chat_id: "chat-terminal", turn_id: "user-terminal",
      assistant_message_id: "assistant-terminal", chat_key_version: 1,
    }] });
    expect(service.requestChatContentBatch_FOR_HANDLERS_ONLY).toHaveBeenCalledWith(["chat-terminal"]);
    expect(activeAITasks.has("chat-terminal")).toBe(false);
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({
      type: "aiTaskEnded", detail: {
        chatId: "chat-terminal", taskId: "assistant-terminal",
        userMessageId: "user-terminal", status: "completed",
      },
    }));
  });

  // contract-test: direct surface=gui.web assertions=chats.completion.lease-fenced,chats.message.identity-idempotent
  it("ignores delayed claim and persist frames from an earlier attempt", async () => {
    const handlers = new Map();
    let claimAttempts = 0;
    let persistAttempts = 0;
    let firstClaimRequestId;
    let secondClaimRequestId;
    let firstPersistRequestId;
    let secondPersistRequestId;
    const sendClaimed = (requestId) => {
      handlers.get("recovery_job_claimed")?.({
        job_id: "job-1",
        request_id: requestId,
        state: "LEASED",
        lease_token: "lease-token",
        lease_generation: 2,
        sealed_payload: '{"v":1}',
        chat_id: "chat-1",
        turn_id: "turn-1",
        assistant_message_id: "assistant-1",
        chat_key_version: 1,
      });
    };
    const sendPersisted = (requestId) => {
      handlers.get("recovery_job_persisted")?.({
        job_id: "job-1",
        request_id: requestId,
        state: "TERMINAL",
        committed_messages_v: 3,
      });
    };
    mocks.webSocketService.on.mockImplementation((type, handler) => {
      handlers.set(type, handler);
    });
    mocks.webSocketService.off.mockImplementation((type) => {
      handlers.delete(type);
    });
    mocks.webSocketService.sendMessage.mockImplementation(async (type, payload) => {
      if (type === "recovery_job_claim") {
        claimAttempts += 1;
        if (claimAttempts === 1) firstClaimRequestId = payload.request_id;
        else secondClaimRequestId = payload.request_id;
      }
      if (type === "recovery_job_persist") {
        persistAttempts += 1;
        if (persistAttempts === 1) firstPersistRequestId = payload.request_id;
        else secondPersistRequestId = payload.request_id;
      }
    });
    mocks.chatDB.getMessage.mockResolvedValue(undefined);
    mocks.chatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      user_id: "user-1",
      messages_v: 2,
    });
    mocks.deriveChatCompletionRecoveryKeypair.mockResolvedValue({ privateKey: "private-key" });
    mocks.openChatCompletionRecoveryEnvelope.mockResolvedValue(
      new TextEncoder().encode(JSON.stringify({
        assistant_message_id: "assistant-1",
        category: "general",
        chat_id: "chat-1",
        content: "Recovered response",
        job_id: "job-1",
        key_version: 1,
        model_name: "model-1",
        turn_id: "turn-1",
      })),
    );
    const service = {
      dispatchEvent: vi.fn(),
      hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
      requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined),
    };

    let recoverySettled = false;
    const recovery = handleRecoveryJobsAvailableImpl(service, {
      jobs: [{
        job_id: "job-1",
        chat_id: "chat-1",
        turn_id: "turn-1",
        assistant_message_id: "assistant-1",
        chat_key_version: 1,
      }],
    }).then(() => {
      recoverySettled = true;
    });

    await vi.advanceTimersByTimeAsync(20_000);
    sendClaimed(firstClaimRequestId);
    handlers.get("error")?.({
      code: "recovery_job_expired",
      job_id: "job-1",
      request_id: firstClaimRequestId,
      message: "Late error for the original claim.",
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(persistAttempts).toBe(0);

    await vi.advanceTimersByTimeAsync(61_000);
    expect(secondClaimRequestId).toEqual(expect.any(String));
    expect(secondClaimRequestId).not.toBe(firstClaimRequestId);
    expect(recoverySettled).toBe(false);
    sendClaimed(secondClaimRequestId);
    // The cold-cache final timestamp wait precedes the persistence request.
    await vi.advanceTimersByTimeAsync(2_000);
    expect(firstPersistRequestId).toEqual(expect.any(String));

    await vi.advanceTimersByTimeAsync(20_000);
    sendPersisted(firstPersistRequestId);
    handlers.get("error")?.({
      code: "stale_lease",
      job_id: "job-1",
      request_id: firstPersistRequestId,
      message: "Late error for the original persistence request.",
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(61_000);
    expect(secondPersistRequestId).toEqual(expect.any(String));
    expect(secondPersistRequestId).not.toBe(firstPersistRequestId);
    expect(recoverySettled).toBe(false);
    sendPersisted(secondPersistRequestId);
    await recovery;

    expect(mocks.chatDB.saveMessage).toHaveBeenCalledTimes(1);
    expect(claimAttempts).toBe(2);
    expect(persistAttempts).toBe(2);
    expect(mocks.chatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({ messages_v: 3 }),
    );
  });

  // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.completion.lease-fenced
  it.each(["root", "child"].flatMap((path) => [true, false, "zero", "invalid-content", "invalid-signature", "invalid-flag", "invalid-negative-count", "invalid-fraction-count"].map((thinking) => ({ path, thinking }))))(
    "recovers $path with observed thinking=$thinking using the owner chat key",
    async ({ path, thinking }) => {
      vi.useRealTimers();
      globalThis.crypto = webcrypto;
      const ownerKey = new Uint8Array(32).fill(7);
      const otherKey = new Uint8Array(32).fill(8);
      mocks.chatKeyManager.getKey.mockResolvedValue(ownerKey);
      mocks.chatKeyManager.getKeySync.mockReturnValue(ownerKey);
      mocks.chatDB.getEncryptedFields.mockImplementation((message, chatId) => getEncryptedFields({}, message, chatId));
      const handlers = new Map();
      mocks.webSocketService.on.mockImplementation((type, handler) => handlers.set(type, handler));
      mocks.webSocketService.off.mockImplementation((type) => handlers.delete(type));
      const metadata = thinking === true ? {
        thinking_content: "Observed provider reasoning", thinking_signature: "Observed provider signature",
        has_thinking: true, thinking_token_count: 19,
      } : thinking === "zero" ? { has_thinking: false, thinking_token_count: 0 }
        : thinking === "invalid-content" ? { thinking_content: 1 }
        : thinking === "invalid-signature" ? { thinking_signature: null }
        : thinking === "invalid-flag" ? { has_thinking: "true" }
        : thinking === "invalid-negative-count" ? { thinking_token_count: -1 }
        : thinking === "invalid-fraction-count" ? { thinking_token_count: 1.5 } : {};
      const invalid = typeof thinking === "string" && thinking.startsWith("invalid-");
      const content = { content: "Recovered response", category: "general", model_name: "model-1", ...metadata };
      const job = {
        job_id: "thinking-job", chat_id: "root-chat", turn_id: "thinking-turn",
        assistant_message_id: "thinking-message", chat_key_version: 1,
      };
      const output = {
        record_id: "thinking-record", root_chat_id: "root-chat", target_chat_id: "child-chat",
        turn_id: "thinking-turn", subject_id: "thinking-message", output_kind: "message",
        output_version: 1, chat_key_version: 1, message_role: "assistant",
      };
      mocks.chatDB.getChat.mockResolvedValue({ chat_id: "root-chat", user_id: "owner-1", messages_v: 2 });
      mocks.chatDB.getMessage.mockResolvedValue(undefined);
      mocks.deriveChatCompletionRecoveryKeypair.mockResolvedValue({ privateKey: "private-key" });
      mocks.openChatCompletionRecoveryEnvelope.mockResolvedValue(new TextEncoder().encode(JSON.stringify({
        ...content, ...job, key_version: 1,
      })));
      mocks.openRecoveryOutputEnvelope.mockResolvedValue(new TextEncoder().encode(JSON.stringify({
        ...output, content: { ...content, message_id: output.subject_id, role: "assistant" },
      })));
      mocks.webSocketService.sendMessage.mockImplementation(async (type, payload) => {
        const replies = {
          recovery_job_claim: ["recovery_job_claimed", {
            ...job, state: "LEASED", lease_token: "lease", lease_generation: 1, sealed_payload: '{"v":1}',
          }],
          recovery_job_persist: ["recovery_job_persisted", { job_id: job.job_id, state: "TERMINAL", committed_messages_v: 3 }],
          recovery_output_get: ["recovery_output_ready", {
            ...output, sealed_payload: '{"v":2}', messages_v: 2,
            encrypted_chat_key: "existing-owner-wrapped-key", encrypted_title: "existing-title",
          }],
          recovery_output_persist_message: ["recovery_output_persisted", {
            record_id: output.record_id, state: "ACKNOWLEDGED", committed_messages_v: 3,
          }],
        };
        const reply = replies[type];
        if (reply) queueMicrotask(() => handlers.get(reply[0])?.({ ...reply[1], request_id: payload.request_id }));
      });
      const service = {
        dispatchEvent: vi.fn(), hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
        requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined),
      };
      recordRecoveryFinalTimestamp({
        is_final_chunk: true, recovery_protocol_version: 1, chat_id: job.chat_id,
        message_id: job.assistant_message_id, user_message_id: job.turn_id,
        recovery_job_id: job.job_id, recovery_turn_id: job.turn_id, created_at: 1700000000,
      });
      if (path === "root") await handleRecoveryJobsAvailableImpl(service, { jobs: [job] });
      else await handleRecoveryOutputsAvailableImpl(service, { outputs: [output] });
      const event = path === "root" ? "recovery_job_persist" : "recovery_output_persist_message";
      const persist = mocks.webSocketService.sendMessage.mock.calls.find(([type]) => type === event)?.[1];
      if (invalid) {
        expect(persist).toBeUndefined();
        expect(mocks.chatDB.getEncryptedFields).not.toHaveBeenCalled();
        expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
        return;
      }
      expect(persist).toBeDefined();
      const message = persist.encrypted_assistant_message;
      expect(message).not.toHaveProperty("thinking_content");
      expect(message).not.toHaveProperty("thinking_signature");
      expect(mocks.chatDB.getEncryptedFields).toHaveBeenCalledWith(
        expect.objectContaining({ content: content.content, ...metadata }), path === "root" ? "root-chat" : "child-chat",
      );
      if (thinking === true) {
        expect(message).toMatchObject({ has_thinking: true, thinking_token_count: 19 });
        for (const field of ["thinking_content", "thinking_signature"]) {
          expect(await decryptWithChatKey(message[`encrypted_${field}`], ownerKey)).toBe(metadata[field]);
          expect(await decryptWithChatKey(message[`encrypted_${field}`], otherKey)).toBeNull();
        }
        expect(JSON.stringify(persist)).not.toContain(metadata.thinking_content);
        expect(JSON.stringify(persist)).not.toContain(metadata.thinking_signature);
      } else if (thinking === "zero") {
        expect(message).toMatchObject({ has_thinking: false, thinking_token_count: 0 });
        expect(message).not.toHaveProperty("encrypted_thinking_content");
        expect(message).not.toHaveProperty("encrypted_thinking_signature");
      } else {
        for (const field of ["has_thinking", "thinking_token_count", "encrypted_thinking_content", "encrypted_thinking_signature"]) {
          expect(message).not.toHaveProperty(field);
          expect(mocks.chatDB.saveMessage.mock.calls[0][0]).not.toHaveProperty(field);
        }
      }
      if (path === "child") expect(mocks.chatKeyManager.injectKey).toHaveBeenCalledWith("child-chat", ownerKey, "master_key");
    },
  );

  // contract-test: supporting surface=gui.web assertions=chats.local-state.precedence,chats.sync.key-gated-recovery
  it.each(["Proper bootstrap title", "Owner renamed title"])("hydrates only committed child metadata fields while preserving %s", async (title) => {
    vi.useRealTimers();
    globalThis.crypto = webcrypto;
    const key = new Uint8Array(32).fill(7);
    mocks.chatKeyManager.getKey.mockResolvedValue(key);
    mocks.chatKeyManager.getKeySync.mockReturnValue(key);
    mocks.deriveChatCompletionRecoveryKeypair.mockResolvedValue({ privateKey: "private-key" });
    const child = { chat_id: "child-chat", parent_id: "root-chat", user_id: "owner", title,
      encrypted_title: "existing-title-ciphertext", encrypted_category: "existing-category-ciphertext",
      category: "existing-category", metadata_v: 1, title_v: 1, messages_v: 2 };
    mocks.chatDB.getChat.mockImplementation(async (id) => id === "root-chat"
      ? { chat_id: "root-chat", user_id: "owner", messages_v: 2 } : child);
    const output = { record_id: "generated-metadata-record", root_chat_id: "root-chat", target_chat_id: "child-chat",
      turn_id: "turn", subject_id: "task:generated-metadata", output_kind: "summary", output_version: 1, chat_key_version: 1 };
    const content = { title: "Older generated title", summary: "Concise generated child findings", category: "generated-category",
      icon: "cpu", source_metadata_v: 0 };
    mocks.openRecoveryOutputEnvelope.mockResolvedValue(new TextEncoder().encode(JSON.stringify({ ...output, content })));
    const handlers = new Map();
    mocks.webSocketService.on.mockImplementation((type, handler) => handlers.set(type, handler));
    mocks.webSocketService.off.mockImplementation((type) => handlers.delete(type));
    mocks.webSocketService.sendMessage.mockImplementation(async (type, payload) => {
      const replies = {
        recovery_output_get: ["recovery_output_ready", { ...output, sealed_payload: '{"v":2}', messages_v: 2,
          metadata_v: 1, encrypted_chat_key: "wrapped-root-key", encrypted_title: child.encrypted_title }],
        recovery_output_persist_summary: ["recovery_output_summary_persisted", { record_id: output.record_id,
          state: "ACKNOWLEDGED", committed_metadata_v: 2, committed_title_v: 1, applied_fields: ["encrypted_chat_summary"] }],
      };
      const reply = replies[type];
      if (reply) queueMicrotask(() => handlers.get(reply[0])?.({ ...reply[1], request_id: payload.request_id }));
    });
    const service = { dispatchEvent: vi.fn(), hasCompletedInitialSync_FOR_HANDLERS_ONLY: true };
    await handleRecoveryOutputsAvailableImpl(service, { outputs: [output] });
    const updated = mocks.chatDB.updateChat.mock.calls.at(-1)?.[0];
    expect(updated).toMatchObject({ title, encrypted_title: child.encrypted_title,
      category: child.category, encrypted_category: child.encrypted_category,
      chat_summary: content.summary, metadata_v: 2, title_v: 1 });
    expect(updated.title).not.toBe(content.title);
    expect(await decryptWithChatKey(updated.encrypted_chat_summary, key)).toBe(content.summary);
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "chatUpdated" }));
  });

});
