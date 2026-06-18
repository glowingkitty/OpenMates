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
vi.mock("../i18n/translations", () => ({
  text: vi.fn((key: string) => key),
}));
vi.mock("../stores/serverStatusStore", () => ({
  markDeviceReceivedFreeTestingCreditsFromNotification:
    mocks.markDeviceReceivedFreeTestingCreditsFromNotification,
}));

import { handlePendingAIResponseImpl } from "../chatSyncServiceHandlersAppSettings";

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
