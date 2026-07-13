// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersAppSettings.test.ts
// Regression coverage for app-settings-adjacent WebSocket handlers.
// These tests focus on pending AI response recovery after a browser leaves while
// streaming, where reconnect delivery must replace stale local assistant rows.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";

const mocks = vi.hoisted(() => ({
  chatDB: {
    getMessage: vi.fn(),
    getChat: vi.fn(),
    replaceMessageById: vi.fn(),
    saveMessage: vi.fn(),
    updateChat: vi.fn(),
    getEncryptedFields: vi.fn(),
  },
  chatKeyManager: {
    getKey: vi.fn(),
  },
  notificationStore: {
    addNotificationWithOptions: vi.fn(),
    addNotification: vi.fn(),
  },
  activeChatStore: {
    get: vi.fn(() => "chat-1"),
  },
  aiTypingStore: {
    clearTypingForChat: vi.fn(),
  },
  ensureChatKeySafeForWrite: vi.fn(),
  encryptWithChatKey: vi.fn(),
  markDeviceReceivedFreeTestingCreditsFromNotification: vi.fn(),
  webSocketService: {
    on: vi.fn(),
    off: vi.fn(),
    sendMessage: vi.fn(),
  },
  deriveChatCompletionRecoveryKeypair: vi.fn(),
  openChatCompletionRecoveryEnvelope: vi.fn(),
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: mocks.chatKeyManager,
}));
vi.mock("../../stores/notificationStore", () => ({
  notificationStore: mocks.notificationStore,
}));
vi.mock("../../stores/activeChatStore", () => ({
  activeChatStore: mocks.activeChatStore,
}));
vi.mock("../../stores/aiTypingStore", () => ({
  aiTypingStore: mocks.aiTypingStore,
}));
vi.mock("../chatKeyWriteGuard", () => ({
  ensureChatKeySafeForWrite: mocks.ensureChatKeySafeForWrite,
}));
vi.mock("../encryption/MessageEncryptor", () => ({
  encryptWithChatKey: mocks.encryptWithChatKey,
}));
vi.mock("../websocketService", () => ({
  webSocketService: mocks.webSocketService,
}));
vi.mock("../../utils/chatCompletionRecovery", () => ({
  deriveChatCompletionRecoveryKeypair: mocks.deriveChatCompletionRecoveryKeypair,
  openChatCompletionRecoveryEnvelope: mocks.openChatCompletionRecoveryEnvelope,
}));
vi.mock("../i18n/translations", () => ({
  text: vi.fn((key: string) => key),
}));
vi.mock("../stores/serverStatusStore", () => ({
  markDeviceReceivedFreeTestingCreditsFromNotification:
    mocks.markDeviceReceivedFreeTestingCreditsFromNotification,
}));

import {
  handlePendingAIResponseImpl,
} from "../chatSyncServiceHandlersAppSettings";
import { handleRecoveryJobsAvailableImpl } from "../chatSyncServiceHandlersRecovery";

afterEach(() => vi.useRealTimers());

describe("handlePendingAIResponseImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.chatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      messages_v: 1,
      last_edited_overall_timestamp: 100,
    });
    mocks.chatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mocks.chatDB.replaceMessageById.mockResolvedValue(true);
    mocks.chatDB.saveMessage.mockResolvedValue(undefined);
    mocks.chatDB.updateChat.mockResolvedValue(undefined);
    mocks.chatDB.getEncryptedFields.mockResolvedValue({
      encrypted_content: "encrypted-content",
      encrypted_sender_name: "encrypted-sender",
      encrypted_category: "encrypted-category",
      encrypted_model_name: "encrypted-model",
    });
    mocks.ensureChatKeySafeForWrite.mockResolvedValue(true);
  });

  it("replaces a stale streaming assistant row with the completed pending response", async () => {
    mocks.chatDB.getMessage.mockResolvedValue({
      message_id: "assistant-1",
      chat_id: "chat-1",
      role: "assistant",
      status: "streaming",
      content: "partial",
      created_at: 100,
    });
    const service = {
      dispatchEvent: vi.fn(),
      sendCompletedAIResponse: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handlePendingAIResponseImpl(service, {
      type: "ai_response",
      chat_id: "chat-1",
      message_id: "assistant-1",
      content: "partial completed response",
      user_id: "user-1",
      fired_at: 200,
      model_name: "Gemini 3 Flash",
      category: "general_knowledge",
    });

    expect(mocks.chatDB.replaceMessageById).toHaveBeenCalledWith(
      expect.objectContaining({
        message_id: "assistant-1",
        content: "partial completed response",
        status: "synced",
      }),
      {
        allowedExistingStatuses: ["streaming", "processing", "synced", "delivered"],
        expectedExistingRole: "assistant",
      },
    );
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
    expect(service.sendCompletedAIResponse).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: "assistant-1" }),
    );
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "chatUpdated" }),
    );
  });

  it("does not replace waiting_for_user local state", async () => {
    mocks.chatDB.getMessage.mockResolvedValue({
      message_id: "assistant-1",
      chat_id: "chat-1",
      role: "assistant",
      status: "waiting_for_user",
      content: "Buy credits to continue",
      created_at: 100,
    });
    const service = {
      dispatchEvent: vi.fn(),
      sendCompletedAIResponse: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handlePendingAIResponseImpl(service, {
      type: "ai_response",
      chat_id: "chat-1",
      message_id: "assistant-1",
      content: "Completed response",
      user_id: "user-1",
      fired_at: 200,
    });

    expect(mocks.chatDB.replaceMessageById).not.toHaveBeenCalled();
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();
    expect(service.sendCompletedAIResponse).not.toHaveBeenCalled();
    expect(service.dispatchEvent).not.toHaveBeenCalled();
  });
});


describe("handleRecoveryJobsAvailableImpl", () => {
  it("persists an available recovery job even when the assistant row is locally synced", async () => {
    const handlers = new Map<string, (payload: unknown) => void>();
    let claimRequestId: string | undefined;
    let persistRequestId: string | undefined;
    mocks.webSocketService.on.mockImplementation((type: string, handler: (payload: unknown) => void) => {
      handlers.set(type, handler);
    });
    mocks.webSocketService.off.mockImplementation((type: string) => {
      handlers.delete(type);
    });
    mocks.webSocketService.sendMessage.mockImplementation(async (
      type: string,
      payload: Record<string, unknown>,
    ) => {
      if (type === "recovery_job_claim") {
        claimRequestId = payload.request_id as string;
      }
      if (type === "recovery_job_persist") {
        persistRequestId = payload.request_id as string;
      }
    });
    mocks.chatDB.getMessage.mockResolvedValue({ status: "synced" });
    mocks.chatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      user_id: "user-1",
      messages_v: 2,
    });
    mocks.chatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mocks.ensureChatKeySafeForWrite.mockResolvedValue(true);
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
    mocks.chatDB.getEncryptedFields.mockResolvedValue({
      encrypted_content: "encrypted-content",
      encrypted_sender_name: "encrypted-sender",
      encrypted_category: "encrypted-category",
      encrypted_model_name: "encrypted-model",
    });
    const service = {
      dispatchEvent: vi.fn(),
      hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
      requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined),
    } as unknown as ChatSynchronizationService;

    const recovery = handleRecoveryJobsAvailableImpl(service, {
      jobs: [{
        job_id: "job-1",
        chat_id: "chat-1",
        turn_id: "turn-1",
        assistant_message_id: "assistant-1",
        chat_key_version: 1,
      }],
    });
    await vi.waitFor(() => {
      expect(claimRequestId).toEqual(expect.any(String));
    });
    handlers.get("recovery_job_claimed")?.({
      job_id: "job-1",
      request_id: claimRequestId,
      state: "LEASED",
      lease_token: "lease-token",
      lease_generation: 2,
      sealed_payload: '{"v":1}',
      chat_id: "chat-1",
      turn_id: "turn-1",
      assistant_message_id: "assistant-1",
      chat_key_version: 1,
    });
    await vi.waitFor(() => {
      expect(persistRequestId).toEqual(expect.any(String));
    });
    handlers.get("recovery_job_persisted")?.({
      job_id: "job-1",
      request_id: persistRequestId,
      state: "TERMINAL",
      committed_messages_v: 3,
    });
    await recovery;

    expect(mocks.chatDB.getEncryptedFields).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: "assistant-1", content: "Recovered response" }),
      "chat-1",
    );
    expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "recovery_job_persist",
      expect.objectContaining({
        job_id: "job-1",
        lease_token: "lease-token",
        lease_generation: 2,
      }),
    );
    expect(mocks.chatDB.saveMessage).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: "assistant-1", status: "synced" }),
    );
  });

  it("waits for the chat shell and key before claiming an early recovery job", async () => {
    vi.useFakeTimers();
    const handlers = new Map<string, (payload: unknown) => void>();
    let hydrated = false;
    let claimRequestId: string | undefined;
    let persistRequestId: string | undefined;
    mocks.webSocketService.on.mockImplementation((type: string, handler: (payload: unknown) => void) => {
      handlers.set(type, handler);
    });
    mocks.webSocketService.off.mockImplementation((type: string) => {
      handlers.delete(type);
    });
    mocks.webSocketService.sendMessage.mockImplementation(async (
      type: string,
      payload: Record<string, unknown>,
    ) => {
      if (type === "recovery_job_claim") {
        claimRequestId = payload.request_id as string;
      }
      if (type === "recovery_job_persist") {
        persistRequestId = payload.request_id as string;
      }
    });
    mocks.chatDB.getChat.mockImplementation(async () => (hydrated ? {
      chat_id: "chat-1",
      user_id: "user-1",
      messages_v: 2,
    } : undefined));
    mocks.chatKeyManager.getKey.mockImplementation(async () => (
      hydrated ? new Uint8Array([1, 2, 3]) : null
    ));
    mocks.ensureChatKeySafeForWrite.mockResolvedValue(true);
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
    mocks.chatDB.getEncryptedFields.mockResolvedValue({
      encrypted_content: "encrypted-content",
      encrypted_sender_name: "encrypted-sender",
      encrypted_category: "encrypted-category",
      encrypted_model_name: "encrypted-model",
    });
    const service = {
      dispatchEvent: vi.fn(),
      hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
      requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined),
    } as unknown as ChatSynchronizationService;

    const recovery = handleRecoveryJobsAvailableImpl(service, {
      jobs: [{
        job_id: "job-1",
        chat_id: "chat-1",
        turn_id: "turn-1",
        assistant_message_id: "assistant-1",
        chat_key_version: 1,
      }],
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(service.requestChatContentBatch_FOR_HANDLERS_ONLY).toHaveBeenCalledWith(["chat-1"]);
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalledWith(
      "recovery_job_claim",
      expect.anything(),
    );

    hydrated = true;
    await vi.advanceTimersByTimeAsync(250);
    await vi.waitFor(() => {
      expect(claimRequestId).toEqual(expect.any(String));
    });
    handlers.get("recovery_job_claimed")?.({
      job_id: "job-1",
      request_id: claimRequestId,
      state: "LEASED",
      lease_token: "lease-token",
      lease_generation: 2,
      sealed_payload: '{"v":1}',
      chat_id: "chat-1",
      turn_id: "turn-1",
      assistant_message_id: "assistant-1",
      chat_key_version: 1,
    });
    await vi.waitFor(() => {
      expect(persistRequestId).toEqual(expect.any(String));
    });
    handlers.get("recovery_job_persisted")?.({
      job_id: "job-1",
      request_id: persistRequestId,
      state: "TERMINAL",
      committed_messages_v: 3,
    });
    await recovery;

    expect(mocks.chatDB.saveMessage).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: "assistant-1", status: "synced" }),
    );
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "chatUpdated" }),
    );
  });

  it("does not let one pending recovery job block another available job", async () => {
    const handlers = new Map<string, Set<(payload: unknown) => void>>();
    const emit = (type: string, payload: unknown) => {
      for (const handler of Array.from(handlers.get(type) ?? [])) handler(payload);
    };
    const claimRequests: Record<string, string> = {};
    const persistRequests: Record<string, string> = {};
    mocks.webSocketService.on.mockImplementation((type: string, handler: (payload: unknown) => void) => {
      const set = handlers.get(type) ?? new Set();
      set.add(handler);
      handlers.set(type, set);
    });
    mocks.webSocketService.off.mockImplementation((type: string, handler: (payload: unknown) => void) => {
      handlers.get(type)?.delete(handler);
    });
    mocks.webSocketService.sendMessage.mockImplementation(async (
      type: string,
      payload: Record<string, unknown>,
    ) => {
      if (type === "recovery_job_claim") {
        claimRequests[payload.job_id as string] = payload.request_id as string;
      }
      if (type === "recovery_job_persist") {
        persistRequests[payload.job_id as string] = payload.request_id as string;
      }
    });
    mocks.chatDB.getMessage.mockResolvedValue(undefined);
    mocks.chatDB.getChat.mockImplementation(async (chatId: string) => ({
      chat_id: chatId,
      user_id: "user-1",
      messages_v: 1,
    }));
    mocks.chatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mocks.ensureChatKeySafeForWrite.mockResolvedValue(true);
    mocks.deriveChatCompletionRecoveryKeypair.mockResolvedValue({ privateKey: "private-key" });
    mocks.openChatCompletionRecoveryEnvelope.mockResolvedValue(
      new TextEncoder().encode(JSON.stringify({
        assistant_message_id: "assistant-2",
        category: "general",
        chat_id: "chat-2",
        content: "Recovered response",
        job_id: "job-2",
        key_version: 1,
        model_name: "model-1",
        turn_id: "turn-2",
      })),
    );
    mocks.chatDB.getEncryptedFields.mockResolvedValue({
      encrypted_content: "encrypted-content",
      encrypted_sender_name: "encrypted-sender",
      encrypted_category: "encrypted-category",
      encrypted_model_name: "encrypted-model",
    });
    const service = {
      dispatchEvent: vi.fn(),
      hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
      requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined),
    } as unknown as ChatSynchronizationService;

    const recovery = handleRecoveryJobsAvailableImpl(service, {
      jobs: [
        {
          job_id: "job-1",
          chat_id: "chat-1",
          turn_id: "turn-1",
          assistant_message_id: "assistant-1",
          chat_key_version: 1,
        },
        {
          job_id: "job-2",
          chat_id: "chat-2",
          turn_id: "turn-2",
          assistant_message_id: "assistant-2",
          chat_key_version: 1,
        },
      ],
    });
    await vi.waitFor(() => {
      expect(claimRequests["job-1"]).toEqual(expect.any(String));
      expect(claimRequests["job-2"]).toEqual(expect.any(String));
    });

    emit("recovery_job_claimed", {
      job_id: "job-2",
      request_id: claimRequests["job-2"],
      state: "LEASED",
      lease_token: "lease-token",
      lease_generation: 1,
      sealed_payload: '{"v":1}',
      chat_id: "chat-2",
      turn_id: "turn-2",
      assistant_message_id: "assistant-2",
      chat_key_version: 1,
    });
    await vi.waitFor(() => {
      expect(persistRequests["job-2"]).toEqual(expect.any(String));
    });
    emit("recovery_job_persisted", {
      job_id: "job-2",
      request_id: persistRequests["job-2"],
      state: "TERMINAL",
      committed_messages_v: 2,
    });
    await vi.waitFor(() => {
      expect(mocks.chatDB.saveMessage).toHaveBeenCalledWith(
        expect.objectContaining({ message_id: "assistant-2", chat_id: "chat-2" }),
      );
    });

    emit("error", {
      code: "recovery_job_not_found",
      job_id: "job-1",
      request_id: claimRequests["job-1"],
      message: "Unrelated stale job failed after the target job persisted.",
    });
    await recovery;
    expect(mocks.chatDB.saveMessage).toHaveBeenCalledTimes(1);
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "chatUpdated" }),
    );
  });

  it("ignores delayed claim and persist frames from an earlier recovery attempt", async () => {
    vi.useFakeTimers();
    let requestCounter = 0;
    vi.spyOn(crypto, "randomUUID").mockImplementation(
      () => `recovery-request-${requestCounter += 1}` as `${string}-${string}-${string}-${string}-${string}`,
    );
    const handlers = new Map<string, (payload: unknown) => void>();
    let claimAttempts = 0;
    let persistAttempts = 0;
    let firstClaimRequestId: string | undefined;
    let secondClaimRequestId: string | undefined;
    let firstPersistRequestId: string | undefined;
    let secondPersistRequestId: string | undefined;
    const sendClaimed = (requestId: string) => {
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
    const sendPersisted = (requestId: string) => {
      handlers.get("recovery_job_persisted")?.({
        job_id: "job-1",
        request_id: requestId,
        state: "TERMINAL",
        committed_messages_v: 3,
      });
    };
    mocks.webSocketService.on.mockImplementation((type: string, handler: (payload: unknown) => void) => {
      handlers.set(type, handler);
    });
    mocks.webSocketService.off.mockImplementation((type: string) => {
      handlers.delete(type);
    });
    mocks.webSocketService.sendMessage.mockImplementation(async (
      type: string,
      payload: Record<string, unknown>,
    ) => {
      if (type === "recovery_job_claim") {
        claimAttempts += 1;
        if (claimAttempts === 1) {
          firstClaimRequestId = payload.request_id as string;
        } else {
          secondClaimRequestId = payload.request_id as string;
        }
      }
      if (type === "recovery_job_persist") {
        persistAttempts += 1;
        if (persistAttempts === 1) {
          firstPersistRequestId = payload.request_id as string;
        } else {
          secondPersistRequestId = payload.request_id as string;
        }
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
    } as unknown as ChatSynchronizationService;

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
    sendClaimed(firstClaimRequestId!);
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
    sendClaimed(secondClaimRequestId!);
    await vi.advanceTimersByTimeAsync(0);

    await vi.advanceTimersByTimeAsync(20_000);
    sendPersisted(firstPersistRequestId!);
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
    sendPersisted(secondPersistRequestId!);
    await recovery;

    expect(mocks.chatDB.getEncryptedFields).toHaveBeenCalledOnce();
    expect(mocks.webSocketService.sendMessage).toHaveBeenNthCalledWith(
      4,
      "recovery_job_persist",
      expect.objectContaining({
        job_id: "job-1",
        lease_token: "lease-token",
        lease_generation: 2,
        expected_messages_v: 2,
      }),
    );
    expect(mocks.chatDB.saveMessage).toHaveBeenCalledTimes(1);
    expect(claimAttempts).toBe(2);
    expect(persistAttempts).toBe(2);
    expect(mocks.chatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({ messages_v: 3 }),
    );
  });
});
