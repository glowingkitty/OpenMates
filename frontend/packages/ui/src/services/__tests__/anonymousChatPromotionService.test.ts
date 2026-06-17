// frontend/packages/ui/src/services/__tests__/anonymousChatPromotionService.test.ts
// Unit tests for anonymous chat signup promotion. Promotion must re-wrap the
// existing anonymous per-chat key with the new account master key and upload the
// existing encrypted chat/messages through the normal WebSocket sync path.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mockAnonymousStorage = vi.hoisted(() => ({
  getAllChats: vi.fn(),
  getMessagesForChat: vi.fn(),
  clearAll: vi.fn(),
}));

const mockChatDB = vi.hoisted(() => ({
  init: vi.fn(),
  encryptMessageFields: vi.fn(),
  updateChat: vi.fn(),
  saveMessage: vi.fn(),
  deleteMessage: vi.fn(),
}));

const mockChatKeyManager = vi.hoisted(() => ({
  getKey: vi.fn(),
}));

const mockWebSocketService = vi.hoisted(() => ({
  sendMessage: vi.fn(),
}));

vi.mock("../anonymousChatStorage", () => ({ anonymousChatStorage: mockAnonymousStorage }));
vi.mock("../db", () => ({ chatDB: mockChatDB }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: mockChatKeyManager }));
vi.mock("../websocketService", () => ({ webSocketService: mockWebSocketService }));
vi.mock("../cryptoService", () => ({
  encryptChatKeyWithMasterKey: vi.fn(async () => "master-wrapped-existing-key"),
}));

function seedAnonymousChat() {
  mockAnonymousStorage.getAllChats.mockResolvedValue([
    {
      chat_id: "anonymous-source",
      encrypted_title: "encrypted-title-with-existing-key",
      encrypted_category: "encrypted-category-with-existing-key",
      encrypted_icon: "encrypted-icon-with-existing-key",
      anonymous_encrypted_chat_key: "anonymous-wrapped-existing-key",
      is_anonymous: true,
      messages_v: 3,
      title_v: 1,
      draft_v: 0,
      unread_count: 0,
      created_at: 10,
      updated_at: 12,
      last_edited_overall_timestamp: 12,
      source_demo_id: null,
    },
  ]);
  mockAnonymousStorage.getMessagesForChat.mockResolvedValue([
    {
      message_id: "anonymous-local-notice",
      chat_id: "anonymous-source",
      role: "system",
      content: "Free anonymous chats stay only on this device until you sign up.",
      status: "synced",
      created_at: 10,
      sender_name: "system",
    },
    {
      message_id: "anonymous-user",
      chat_id: "anonymous-source",
      role: "user",
      content: "Hello",
      status: "synced",
      created_at: 11,
      sender_name: "user",
    },
    {
      message_id: "anonymous-assistant",
      chat_id: "anonymous-source",
      role: "assistant",
      content: "Hi there",
      status: "synced",
      created_at: 12,
      sender_name: "assistant",
      model_name: "test-model",
    },
  ]);
}

describe("promoteAnonymousChatsAfterSignup", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    mockChatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mockChatDB.encryptMessageFields.mockImplementation(async (message) => ({
      ...message,
      content: undefined,
      sender_name: undefined,
      model_name: undefined,
      encrypted_content: `encrypted-content:${message.content}`,
      encrypted_sender_name: `encrypted-sender:${message.sender_name}`,
      encrypted_model_name: message.model_name ? `encrypted-model:${message.model_name}` : undefined,
    }));
    Object.assign(window, { dispatchEvent: vi.fn() });
  });

  it("uploads the existing anonymous chat and clears anonymous markers after success", async () => {
    seedAnonymousChat();
    const { promoteAnonymousChatsAfterSignup } = await import("../anonymousChatPromotionService");

    const result = await promoteAnonymousChatsAfterSignup();

    expect(result).toEqual({ promotedCount: 1, promotedChatIds: ["anonymous-source"] });
    expect(mockChatKeyManager.getKey).toHaveBeenCalledWith("anonymous-source");
    expect(mockWebSocketService.sendMessage).toHaveBeenCalledWith("encrypted_chat_metadata", expect.objectContaining({
      chat_id: "anonymous-source",
      encrypted_title: "encrypted-title-with-existing-key",
      encrypted_chat_key: "master-wrapped-existing-key",
      message_history: [
        expect.objectContaining({ message_id: "anonymous-user", role: "user", encrypted_content: "encrypted-content:Hello" }),
        expect.objectContaining({ message_id: "anonymous-assistant", role: "assistant", encrypted_content: "encrypted-content:Hi there" }),
      ],
    }));
    expect(JSON.stringify(mockWebSocketService.sendMessage.mock.calls[0])).not.toContain("anonymous-local-notice");
    expect(mockChatDB.updateChat).toHaveBeenCalledWith(expect.objectContaining({
      chat_id: "anonymous-source",
      encrypted_chat_key: "master-wrapped-existing-key",
      anonymous_encrypted_chat_key: null,
      is_anonymous: false,
      messages_v: 2,
    }));
    expect(mockChatDB.deleteMessage).toHaveBeenCalledWith("anonymous-local-notice");
    expect(mockAnonymousStorage.clearAll).toHaveBeenCalledTimes(1);
  });

  it("preserves anonymous storage when upload fails", async () => {
    seedAnonymousChat();
    mockWebSocketService.sendMessage.mockRejectedValueOnce(new Error("offline"));
    const { promoteAnonymousChatsAfterSignup } = await import("../anonymousChatPromotionService");

    await expect(promoteAnonymousChatsAfterSignup()).rejects.toThrow("offline");

    expect(mockChatDB.updateChat).not.toHaveBeenCalled();
    expect(mockChatDB.deleteMessage).not.toHaveBeenCalled();
    expect(mockAnonymousStorage.clearAll).not.toHaveBeenCalled();
  });
});
