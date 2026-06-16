// frontend/packages/ui/src/services/__tests__/anonymousChatPromotionService.test.ts
// Unit tests for anonymous chat signup promotion. The real service touches
// IndexedDB, chat-key persistence, WebSocket dispatch, and encrypted metadata,
// so these tests mock those boundaries and verify the promotion contract.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mockAnonymousStorage = vi.hoisted(() => ({
  getAllChats: vi.fn(),
  getMessagesForChat: vi.fn(),
  clearAll: vi.fn(),
}));

const mockChatDB = vi.hoisted(() => ({
  init: vi.fn(),
  encryptMessageFields: vi.fn(),
  addChat: vi.fn(),
  saveMessage: vi.fn(),
  deleteChat: vi.fn(),
}));

const mockChatKeyManager = vi.hoisted(() => ({
  createAndPersistKey: vi.fn(),
}));

const mockWebSocketService = vi.hoisted(() => ({
  sendMessage: vi.fn(),
}));

vi.mock("../anonymousChatStorage", () => ({ anonymousChatStorage: mockAnonymousStorage }));
vi.mock("../db", () => ({ chatDB: mockChatDB }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: mockChatKeyManager }));
vi.mock("../websocketService", () => ({ webSocketService: mockWebSocketService }));
vi.mock("../cryptoService", () => ({
  encryptWithChatKey: vi.fn(async (value: string) => `encrypted:${value}`),
}));

function seedAnonymousChat() {
  mockAnonymousStorage.getAllChats.mockResolvedValue([
    {
      chat_id: "anonymous-source",
      title: "Anonymous title",
      category: "ai",
      icon: "bot",
      created_at: 10,
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
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("promoted-chat-id")
      .mockReturnValueOnce("promoted-user-message")
      .mockReturnValueOnce("promoted-assistant-message");
    mockChatKeyManager.createAndPersistKey.mockResolvedValue({
      chatKey: new Uint8Array([1, 2, 3]),
      encryptedChatKey: "wrapped-chat-key",
    });
    mockChatDB.encryptMessageFields.mockImplementation(async (message) => ({
      ...message,
      content: undefined,
      sender_name: undefined,
      model_name: undefined,
      encrypted_content: `encrypted-content:${message.content}`,
      encrypted_sender_name: `encrypted-sender:${message.sender_name}`,
      encrypted_model_name: message.model_name ? `encrypted-model:${message.model_name}` : undefined,
    }));
  });

  it("saves promoted chats, uploads encrypted history, and clears anonymous storage", async () => {
    seedAnonymousChat();
    const { promoteAnonymousChatsAfterSignup } = await import("../anonymousChatPromotionService");

    const result = await promoteAnonymousChatsAfterSignup();

    expect(result).toEqual({ promotedCount: 1, promotedChatIds: ["promoted-chat-id"] });
    expect(mockChatDB.addChat).toHaveBeenCalledWith(expect.objectContaining({
      chat_id: "promoted-chat-id",
      encrypted_title: "encrypted:Anonymous title",
      encrypted_chat_key: "wrapped-chat-key",
      messages_v: 2,
      title_v: 1,
    }));
    expect(mockChatDB.saveMessage).toHaveBeenCalledTimes(2);
    expect(mockWebSocketService.sendMessage).toHaveBeenCalledWith("encrypted_chat_metadata", expect.objectContaining({
      chat_id: "promoted-chat-id",
      encrypted_chat_key: "wrapped-chat-key",
      message_history: [
        expect.objectContaining({ role: "user", encrypted_content: "encrypted-content:Hello" }),
        expect.objectContaining({ role: "assistant", encrypted_content: "encrypted-content:Hi there" }),
      ],
    }));
    expect(mockAnonymousStorage.clearAll).toHaveBeenCalledTimes(1);
  });

  it("rolls back local promoted chats and preserves anonymous storage when upload fails", async () => {
    seedAnonymousChat();
    mockWebSocketService.sendMessage.mockRejectedValueOnce(new Error("offline"));
    const { promoteAnonymousChatsAfterSignup } = await import("../anonymousChatPromotionService");

    await expect(promoteAnonymousChatsAfterSignup()).rejects.toThrow("offline");

    expect(mockChatDB.deleteChat).toHaveBeenCalledWith("promoted-chat-id");
    expect(mockAnonymousStorage.clearAll).not.toHaveBeenCalled();
  });
});
