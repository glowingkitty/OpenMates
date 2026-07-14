// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersChatUpdates.test.ts
// Regression coverage for cross-device chat update handlers.
// New-chat shells created from websocket broadcasts must carry the local user
// owner ID so sealed completion recovery can derive and validate envelopes.
// The test keeps encryption and database collaborators mocked to isolate the
// broadcast-to-shell metadata contract.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";
import { handleNewChatMessageImpl } from "../chatSyncServiceHandlersChatUpdates";

const mocks = vi.hoisted(() => ({
  chatDB: {
    getChat: vi.fn(),
    addChat: vi.fn(),
    updateChat: vi.fn(),
    saveMessage: vi.fn(),
  },
  userDB: {
    getUserProfile: vi.fn(),
  },
  chatMetadataCache: {
    invalidateChat: vi.fn(),
  },
  chatListCache: {
    upsertChat: vi.fn(),
  },
  chatKeyManager: {
    getKeySync: vi.fn(),
    receiveKeyFromServer: vi.fn(),
    withKey: vi.fn(),
  },
  ensureChatKeySafeForWrite: vi.fn(),
  encryptWithChatKey: vi.fn(),
  decryptWithChatKey: vi.fn(),
  flushPendingSystemMessagesForChat: vi.fn(),
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../userDB", () => ({ userDB: mocks.userDB }));
vi.mock("../chatMetadataCache", () => ({ chatMetadataCache: mocks.chatMetadataCache }));
vi.mock("../chatListCache", () => ({ chatListCache: mocks.chatListCache }));
vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: mocks.chatKeyManager,
}));
vi.mock("../chatKeyWriteGuard", () => ({
  ensureChatKeySafeForWrite: mocks.ensureChatKeySafeForWrite,
}));
vi.mock("../encryption/MessageEncryptor", () => ({
  encryptWithChatKey: mocks.encryptWithChatKey,
  decryptWithChatKey: mocks.decryptWithChatKey,
}));
vi.mock("../chatSyncServiceHandlersAppSettings", () => ({
  flushPendingSystemMessagesForChat: mocks.flushPendingSystemMessagesForChat,
}));
vi.mock("../chatSyncServiceHandlersAI", () => ({
  flushPendingFinalizedEmbedsForChat: vi.fn(),
  flushPendingTypingStartedForChat: vi.fn(),
}));

describe("handleNewChatMessageImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.chatDB.getChat.mockResolvedValue(undefined);
    mocks.chatDB.addChat.mockResolvedValue(undefined);
    mocks.chatDB.updateChat.mockResolvedValue(undefined);
    mocks.chatDB.saveMessage.mockResolvedValue(undefined);
    mocks.userDB.getUserProfile.mockResolvedValue({ user_id: "user-1" });
    mocks.chatKeyManager.getKeySync.mockReturnValue(new Uint8Array([1, 2, 3]));
    mocks.chatKeyManager.withKey.mockImplementation(
      async (_chatId: string, _reason: string, callback: () => Promise<void>) => {
        await callback();
      },
    );
  });

  it("stores the current user id on new chat shells created from sync broadcasts", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;

    await handleNewChatMessageImpl(service, {
      chat_id: "chat-1",
      message_id: "message-1",
      content: "Hello from another device",
      role: "user",
      messages_v: 1,
      created_at: 100,
      last_edited_overall_timestamp: 100,
      encrypted_chat_key: "encrypted-chat-key",
    });

    expect(mocks.chatDB.addChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-1",
        user_id: "user-1",
      }),
      undefined,
      { isFromSync: true },
    );
    expect(mocks.chatDB.saveMessage).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: "message-1", chat_id: "chat-1" }),
    );
  });
});
