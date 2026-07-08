// frontend/packages/ui/src/services/__tests__/chatSyncMessageKeyGuard.test.ts
// Regression coverage for sync message key gating.
// Server-synced encrypted messages must not enter IndexedDB when this device
// cannot load or verify the chat key. If storage is deferred, messages_v must
// stay retryable so later sync can recover once a valid key is available.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Message } from "../../types/chat";
import {
  filterPersistableSyncedMessagesWithSkipped,
  markSyncedMessagesDeferred,
} from "../chatSyncMessageKeyGuard";

const mocks = vi.hoisted(() => ({
  chatDB: {
    getChat: vi.fn(),
    updateChat: vi.fn(),
  },
  chatKeyManager: {
    getKeySync: vi.fn(),
    receiveKeyFromServer: vi.fn(),
    getKey: vi.fn(),
  },
  decryptWithChatKey: vi.fn(),
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: mocks.chatKeyManager,
}));
vi.mock("../encryption/MessageEncryptor", () => ({
  decryptWithChatKey: mocks.decryptWithChatKey,
}));

function encryptedMessage(chatId = "chat-1"): Message {
  return {
    chat_id: chatId,
    message_id: `${chatId}-message-1`,
    role: "assistant",
    status: "synced",
    created_at: 1782840000,
    encrypted_content: "encrypted-content",
  } as Message;
}

describe("filterPersistableSyncedMessagesWithSkipped", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.chatKeyManager.getKeySync.mockReturnValue(null);
    mocks.chatKeyManager.receiveKeyFromServer.mockResolvedValue(null);
    mocks.chatKeyManager.getKey.mockResolvedValue(null);
    mocks.chatDB.getChat.mockResolvedValue(null);
    mocks.decryptWithChatKey.mockResolvedValue(null);
  });

  it("defers encrypted synced messages when no usable chat key is available", async () => {
    mocks.chatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      encrypted_chat_key: "stored-encrypted-key",
    });

    const result = await filterPersistableSyncedMessagesWithSkipped(
      [encryptedMessage()],
      new Map([["chat-1", "incoming-encrypted-key"]]),
      "test sync",
    );

    expect(result.messages).toEqual([]);
    expect(result.skippedChatIds.has("chat-1")).toBe(true);
    expect(mocks.chatKeyManager.receiveKeyFromServer).toHaveBeenCalledWith(
      "chat-1",
      "incoming-encrypted-key",
    );
    expect(mocks.chatKeyManager.receiveKeyFromServer).toHaveBeenCalledWith(
      "chat-1",
      "stored-encrypted-key",
    );
    expect(mocks.decryptWithChatKey).not.toHaveBeenCalled();
  });

  it("keeps encrypted synced messages only when the loaded key decrypts a sample", async () => {
    const key = new Uint8Array([1, 2, 3]);
    const message = encryptedMessage();
    mocks.chatKeyManager.getKeySync.mockReturnValue(key);
    mocks.decryptWithChatKey.mockResolvedValue("hello");

    const result = await filterPersistableSyncedMessagesWithSkipped(
      [message],
      new Map(),
      "test sync",
    );

    expect(result.messages).toEqual([message]);
    expect(result.skippedChatIds.size).toBe(0);
    expect(mocks.decryptWithChatKey).toHaveBeenCalledWith(
      "encrypted-content",
      key,
    );
  });
});

describe("markSyncedMessagesDeferred", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("resets messages_v so skipped synced messages can be retried", async () => {
    mocks.chatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      messages_v: 12,
      encrypted_chat_key: "stored-encrypted-key",
    });

    await markSyncedMessagesDeferred("chat-1", "test sync");

    expect(mocks.chatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({ chat_id: "chat-1", messages_v: 0 }),
    );
  });
});
