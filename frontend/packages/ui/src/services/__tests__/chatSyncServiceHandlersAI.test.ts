// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersAI.test.ts
// Regression coverage for AI websocket embed handlers.
// These tests focus on event ordering races between embed_update and
// send_embed_data, where the UI can otherwise stay on a loading preview.
// Keep mocks narrow so handler behavior remains visible.

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";
import {
  handleAIBackgroundResponseCompletedImpl,
  handleAITypingStartedImpl,
  handleEmbedUpdateImpl,
} from "../chatSyncServiceHandlersAI";

const mockChatDB = vi.hoisted(() => ({
  getChat: vi.fn(),
  updateChat: vi.fn(),
  getMessage: vi.fn(),
  getMessagesForChat: vi.fn(),
}));

const mockEmbedStore = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  removeFromMemoryCache: vi.fn(),
}));

const mockAiTypingStore = vi.hoisted(() => ({
  clearTyping: vi.fn(),
  setTyping: vi.fn(),
}));

const mockChatKeyManager = vi.hoisted(() => ({
  getKeySync: vi.fn(),
  getKey: vi.fn(),
  receiveKeyFromServer: vi.fn(),
  computeKeyFingerprint: vi.fn(() => "raw-key-fingerprint"),
}));

const mockEncryptWithChatKey = vi.hoisted(() => vi.fn());
const mockEncryptChatKeyWithMasterKey = vi.hoisted(() => vi.fn());
const mockEncryptedChatKeyMatchesRawKey = vi.hoisted(() => vi.fn());
const mockAddCandidateKey = vi.hoisted(() => vi.fn());
const mockSendEncryptedStoragePackage = vi.hoisted(() => vi.fn());
const mockChatMetadataCache = vi.hoisted(() => ({
  invalidateChat: vi.fn(),
}));
const mockChatListCache = vi.hoisted(() => ({
  invalidateLastMessage: vi.fn(),
  upsertChat: vi.fn(),
}));

vi.mock("../db", () => ({
  chatDB: mockChatDB,
}));

vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: mockChatKeyManager,
  computeKeyFingerprint: mockChatKeyManager.computeKeyFingerprint,
}));

vi.mock("../chatKeyConsistency", () => ({
  encryptedChatKeyMatchesRawKey: mockEncryptedChatKeyMatchesRawKey,
}));

vi.mock("../db/chatCrudOperations", () => ({
  addCandidateKey: mockAddCandidateKey,
}));

vi.mock("../encryption/MessageEncryptor", () => ({
  encryptWithChatKey: mockEncryptWithChatKey,
  decryptWithChatKey: vi.fn(),
  encryptArrayWithChatKey: vi.fn(),
  decryptArrayWithChatKey: vi.fn(),
}));

vi.mock("../encryption/MetadataEncryptor", () => ({
  encryptChatKeyWithMasterKey: mockEncryptChatKeyWithMasterKey,
  decryptChatKeyWithMasterKey: vi.fn(),
  encryptWithMasterKey: vi.fn(),
  generateEmbedKey: vi.fn(),
  deriveEmbedKeyFromChatKey: vi.fn(),
  encryptWithEmbedKey: vi.fn(),
  wrapEmbedKeyWithMasterKey: vi.fn(),
  wrapEmbedKeyWithChatKey: vi.fn(),
}));

vi.mock("../chatSyncServiceHandlersChatUpdates", () => ({
  flushPendingMessagesForChat: vi.fn(),
}));

vi.mock("../chatSyncServiceHandlersAppSettings", () => ({
  flushPendingSystemMessagesForChat: vi.fn(),
}));

vi.mock("../chatSyncServiceSenders", () => ({
  sendEncryptedStoragePackage: mockSendEncryptedStoragePackage,
}));

vi.mock("../incognitoChatService", () => ({
  incognitoChatService: {
    getChat: vi.fn(async () => null),
  },
}));

vi.mock("../chatMetadataCache", () => ({
  chatMetadataCache: mockChatMetadataCache,
}));

vi.mock("../chatListCache", () => ({
  chatListCache: mockChatListCache,
}));

vi.mock("../embedStore", () => ({
  embedStore: mockEmbedStore,
}));

vi.mock("../../stores/aiTypingStore", () => ({
  aiTypingStore: mockAiTypingStore,
}));

describe("handleAIBackgroundResponseCompletedImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not send legacy persistence for epoch-one recovery completions", async () => {
    const activeAITasks = new Map([["chat-1", { taskId: "task-1" }]]);
    const service = {
      activeAITasks,
      dispatchEvent: vi.fn(),
      sendCompletedAIResponse: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleAIBackgroundResponseCompletedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      user_message_id: "user-message-1",
      task_id: "task-1",
      full_content: "Recovered content",
      recovery_job_id: "job-1",
      recovery_protocol_version: 1,
    });

    expect(service.sendCompletedAIResponse).not.toHaveBeenCalled();
    expect(activeAITasks.has("chat-1")).toBe(false);
    expect(mockAiTypingStore.clearTyping).toHaveBeenCalledWith(
      "chat-1",
      "assistant-1",
    );
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "aiTaskEnded" }),
    );
  });
});

describe("handleAITypingStartedImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockChatKeyManager.getKeySync.mockReturnValue(new Uint8Array([1, 2, 3]));
    mockChatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mockChatKeyManager.receiveKeyFromServer.mockResolvedValue(
      new Uint8Array([1, 2, 3]),
    );
    mockEncryptedChatKeyMatchesRawKey.mockResolvedValue(true);
    mockAddCandidateKey.mockResolvedValue(undefined);
    mockEncryptWithChatKey.mockImplementation(async (value: string) =>
      `encrypted:${value}`,
    );
    mockSendEncryptedStoragePackage.mockResolvedValue(undefined);
    mockChatDB.getMessage.mockResolvedValue({
      message_id: "user-message-1",
      chat_id: "chat-1",
      role: "user",
      content: "hello",
      created_at: 1000,
    });
    mockChatDB.getMessagesForChat.mockResolvedValue([]);
  });

  it("preserves the existing encrypted chat key wrapper during metadata updates", async () => {
    const existingChat = {
      chat_id: "chat-1",
      encrypted_chat_key: "canonical-wrapper",
      title_v: 0,
      waiting_for_metadata: true,
      updated_at: 1000,
    };
    mockChatDB.getChat.mockResolvedValue(existingChat);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleAITypingStartedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      user_message_id: "user-message-1",
      category: "general_knowledge",
      icon_names: ["help-circle"],
      title: "New chat",
    });

    expect(mockEncryptChatKeyWithMasterKey).not.toHaveBeenCalled();
    expect(mockChatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-1",
        encrypted_chat_key: "canonical-wrapper",
      }),
    );
  });

  it("does not replace a local encrypted chat key wrapper with a different payload wrapper", async () => {
    const existingChat = {
      chat_id: "chat-1",
      encrypted_chat_key: "canonical-wrapper",
      title_v: 0,
      waiting_for_metadata: true,
      updated_at: 1000,
    };
    mockChatDB.getChat.mockResolvedValue(existingChat);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleAITypingStartedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      user_message_id: "user-message-1",
      category: "general_knowledge",
      icon_names: ["help-circle"],
      title: "New chat",
      encrypted_chat_key: "payload-wrapper",
    });

    expect(mockChatKeyManager.receiveKeyFromServer).not.toHaveBeenCalled();
    expect(mockEncryptChatKeyWithMasterKey).not.toHaveBeenCalled();
    expect(mockEncryptedChatKeyMatchesRawKey).toHaveBeenCalledWith(
      "canonical-wrapper",
      expect.any(Uint8Array),
      expect.any(Function),
    );
    expect(mockChatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-1",
        encrypted_chat_key: "canonical-wrapper",
      }),
    );
  });

  it("stores the server-provided encrypted chat key wrapper when missing locally", async () => {
    const existingChat = {
      chat_id: "chat-1",
      title_v: 0,
      waiting_for_metadata: true,
      updated_at: 1000,
    };
    mockChatDB.getChat.mockResolvedValue(existingChat);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleAITypingStartedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      user_message_id: "user-message-1",
      category: "general_knowledge",
      icon_names: ["help-circle"],
      title: "New chat",
      encrypted_chat_key: "server-wrapper",
    });

    expect(mockEncryptChatKeyWithMasterKey).not.toHaveBeenCalled();
    expect(mockEncryptedChatKeyMatchesRawKey).toHaveBeenCalledWith(
      "server-wrapper",
      expect.any(Uint8Array),
      expect.any(Function),
    );
    expect(mockChatDB.updateChat).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        chat_id: "chat-1",
        encrypted_chat_key: "server-wrapper",
      }),
    );
    expect(mockChatDB.updateChat.mock.invocationCallOrder[0]).toBeLessThan(
      mockEncryptedChatKeyMatchesRawKey.mock.invocationCallOrder[0],
    );
    expect(mockChatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-1",
        encrypted_chat_key: "server-wrapper",
      }),
    );
  });

  it("receives the server key and blocks metadata encryption when the hydrated wrapper does not match", async () => {
    mockChatKeyManager.getKeySync
      .mockReturnValueOnce(null)
      .mockReturnValue(new Uint8Array([1, 2, 3]));
    mockEncryptedChatKeyMatchesRawKey.mockResolvedValue(false);
    const existingChat = {
      chat_id: "chat-1",
      title_v: 0,
      waiting_for_metadata: true,
      updated_at: 1000,
    };
    mockChatDB.getChat.mockResolvedValue(existingChat);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleAITypingStartedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      user_message_id: "user-message-1",
      category: "general_knowledge",
      icon_names: ["help-circle"],
      title: "New chat",
      encrypted_chat_key: "server-wrapper",
    });

    expect(mockChatKeyManager.receiveKeyFromServer).toHaveBeenCalledWith(
      "chat-1",
      "server-wrapper",
    );
    expect(mockChatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-1",
        encrypted_chat_key: "server-wrapper",
      }),
    );
    expect(mockEncryptedChatKeyMatchesRawKey).toHaveBeenCalledWith(
      "server-wrapper",
      expect.any(Uint8Array),
      expect.any(Function),
    );
    expect(mockEncryptWithChatKey).not.toHaveBeenCalled();
    expect(mockSendEncryptedStoragePackage).not.toHaveBeenCalled();
  });
});

describe("handleEmbedUpdateImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps placeholder embeds processing until final content arrives", async () => {
    const existingEmbed = {
      embed_id: "embed-1",
      status: "processing",
      content: "app_id: web\nskill_id: search\nstatus: processing",
      chat_id: "chat-1",
      message_id: "message-1",
      embed_ids: [] as string[],
    };
    mockEmbedStore.get.mockResolvedValue(existingEmbed);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleEmbedUpdateImpl(service, {
      type: "embed_update",
      event_for_client: "embed_update",
      embed_id: "embed-1",
      chat_id: "chat-1",
      message_id: "message-1",
      user_id_uuid: "user-1",
      user_id_hash: "hashed-user-1",
      status: "finished",
      child_embed_ids: ["child-1"],
    });

    expect(existingEmbed.status).toBe("processing");
    expect(existingEmbed.embed_ids).toEqual(["child-1"]);
    expect(mockEmbedStore.put).not.toHaveBeenCalled();
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "embedUpdated",
        detail: expect.objectContaining({
          embed_id: "embed-1",
          status: "finished",
          isWaitingForContent: true,
        }),
      }),
    );
  });
});
