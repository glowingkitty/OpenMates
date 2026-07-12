// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersAppSettings.test.ts
// Regression coverage for app-settings-adjacent WebSocket handlers.
// These tests focus on pending AI response recovery after a browser leaves while
// streaming, where reconnect delivery must replace stale local assistant rows.

import { beforeEach, describe, expect, it, vi } from "vitest";
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
  it("claims, locally encrypts, persists, and fences exactly one sealed assistant completion", async () => {
    const handlers = new Map<string, (payload: unknown) => void>();
    mocks.webSocketService.on.mockImplementation((type: string, handler: (payload: unknown) => void) => {
      handlers.set(type, handler);
    });
    mocks.webSocketService.off.mockImplementation((type: string) => {
      handlers.delete(type);
    });
    mocks.webSocketService.sendMessage.mockImplementation(async (type: string) => {
      if (type === "recovery_job_claim") {
        handlers.get("recovery_job_claimed")?.({
          job_id: "job-1",
          state: "LEASED",
          lease_token: "lease-token",
          lease_generation: 2,
          sealed_payload: '{"v":1}',
          chat_id: "chat-1",
          turn_id: "turn-1",
          assistant_message_id: "assistant-1",
          chat_key_version: 1,
        });
      }
      if (type === "recovery_job_persist") {
        handlers.get("recovery_job_persisted")?.({
          job_id: "job-1",
          state: "TERMINAL",
          committed_messages_v: 3,
        });
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
    } as unknown as ChatSynchronizationService;

    await handleRecoveryJobsAvailableImpl(service, {
      jobs: [{
        job_id: "job-1",
        chat_id: "chat-1",
        turn_id: "turn-1",
        assistant_message_id: "assistant-1",
        chat_key_version: 1,
      }],
    });

    mocks.chatDB.getMessage.mockResolvedValue({ status: "synced" });
    await handleRecoveryJobsAvailableImpl(service, {
      jobs: [{
        job_id: "job-1",
        chat_id: "chat-1",
        turn_id: "turn-1",
        assistant_message_id: "assistant-1",
        chat_key_version: 1,
      }],
    });

    expect(mocks.chatDB.getEncryptedFields).toHaveBeenCalledOnce();
    expect(mocks.webSocketService.sendMessage).toHaveBeenNthCalledWith(
      2,
      "recovery_job_persist",
      expect.objectContaining({
        job_id: "job-1",
        lease_token: "lease-token",
        lease_generation: 2,
        expected_messages_v: 2,
      }),
    );
    expect(mocks.chatDB.saveMessage).toHaveBeenCalledTimes(1);
    expect(mocks.chatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({ messages_v: 3 }),
    );
  });
});
