// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersAI.test.ts
// Regression coverage for AI websocket embed handlers.
// These tests focus on event ordering races between embed_update and
// send_embed_data, where the UI can otherwise stay on a loading preview.
// Keep mocks narrow so handler behavior remains visible.

import { describe, expect, it, vi, beforeEach } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";
import {
  clearProcessedEmbedsTracking,
  flushPendingFinalizedEmbedsForChat,
  handleAIBackgroundResponseCompletedImpl,
  handleAIResponseStorageConfirmedImpl,
  handleAIResponseStorageFailedImpl,
  handleAITypingStartedImpl,
  handleAwaitingSubChatsCompletionImpl,
  handleEmbedUpdateImpl,
  handlePostProcessingCompletedImpl,
  handleSendEmbedDataImpl,
  handleSpawnSubChatsImpl,
  handleSubChatCompletedImpl,
} from "../chatSyncServiceHandlersAI";

const HASHED_CHAT_ID = "a".repeat(64);
const HASHED_MESSAGE_ID = "b".repeat(64);
const HASHED_USER_ID = "c".repeat(64);
const HASHED_EMBED_ID = "d".repeat(64);

const mockChatDB = vi.hoisted(() => ({
  getChat: vi.fn(),
  getAllChats: vi.fn(),
  getEncryptedChatKey: vi.fn(),
  updateChat: vi.fn(),
  saveMessage: vi.fn(),
  getMessage: vi.fn(),
  getMessagesForChat: vi.fn(),
  addChat: vi.fn(),
}));

const mockEmbedStore = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  putEncrypted: vi.fn(),
  getEmbedKey: vi.fn(),
  setEmbedKeyInCache: vi.fn(),
  setInMemoryOnly: vi.fn(),
  registerEmbedRef: vi.fn(),
  storeEmbedKeys: vi.fn(),
  removeFromMemoryCache: vi.fn(),
}));

const mockAiTypingStore = vi.hoisted(() => ({
  clearTyping: vi.fn(),
  clearTypingForChat: vi.fn(),
  setTyping: vi.fn(),
  subscribe: vi.fn((run: (value: unknown) => void) => {
    run(null);
    return () => {};
  }),
}));

const mockActiveChatStore = vi.hoisted(() => ({
  get: vi.fn(),
}));

const mockNotificationStore = vi.hoisted(() => ({
  chatMessage: vi.fn(),
}));

const mockUnreadMessagesStore = vi.hoisted(() => ({
  incrementUnread: vi.fn(),
}));
const mockPendingAIResponses = vi.hoisted(() => ({
  add: vi.fn(),
  remove: vi.fn(),
}));

const mockChatKeyManager = vi.hoisted(() => ({
  getKeySync: vi.fn(),
  getKey: vi.fn(),
  withKey: vi.fn(),
  receiveKeyFromServer: vi.fn(),
  injectKey: vi.fn(),
  computeKeyFingerprint: vi.fn(() => "raw-key-fingerprint"),
}));
const mockWebSocketService = vi.hoisted(() => ({
  on: vi.fn(),
  off: vi.fn(),
  send: vi.fn(),
  isConnected: vi.fn(() => true),
}));

const mockEncryptWithChatKey = vi.hoisted(() => vi.fn());
const mockEncryptArrayWithChatKey = vi.hoisted(() => vi.fn());
const mockEncryptWithMasterKey = vi.hoisted(() => vi.fn());
const mockEncryptChatKeyWithMasterKey = vi.hoisted(() => vi.fn());
const mockDeriveEmbedKeyFromChatKey = vi.hoisted(() => vi.fn());
const mockEncryptWithEmbedKey = vi.hoisted(() => vi.fn());
const mockWrapEmbedKeyWithMasterKey = vi.hoisted(() => vi.fn());
const mockWrapEmbedKeyWithChatKey = vi.hoisted(() => vi.fn());
const mockEncryptedChatKeyMatchesRawKey = vi.hoisted(() => vi.fn());
const mockEnsureChatKeySafeForWrite = vi.hoisted(() => vi.fn());
const mockAddCandidateKey = vi.hoisted(() => vi.fn());
const mockSendEncryptedStoragePackage = vi.hoisted(() => vi.fn());
const mockSendStoreEmbed = vi.hoisted(() => vi.fn());
const mockSendStoreEmbedKeys = vi.hoisted(() => vi.fn());
const mockSendStoreEmbedDiff = vi.hoisted(() => vi.fn());
const mockSendPostProcessingMetadata = vi.hoisted(() => vi.fn());
const mockComputeSHA256 = vi.hoisted(() => vi.fn());
const mockChatMetadataCache = vi.hoisted(() => ({
  invalidateChat: vi.fn(),
}));
const mockChatListCache = vi.hoisted(() => ({
  getCache: vi.fn(),
  invalidateLastMessage: vi.fn(),
  upsertChat: vi.fn(),
}));

vi.mock("../db", () => ({
  chatDB: mockChatDB,
}));

vi.mock("../pendingAIResponses", () => ({
  addPendingAIResponse: mockPendingAIResponses.add,
  removePendingAIResponse: mockPendingAIResponses.remove,
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

vi.mock("../chatKeyWriteGuard", () => ({
  ensureChatKeySafeForWrite: mockEnsureChatKeySafeForWrite,
}));

vi.mock("../../message_parsing/utils", () => ({
  computeSHA256: mockComputeSHA256,
}));

vi.mock("../encryption/MessageEncryptor", () => ({
  encryptWithChatKey: mockEncryptWithChatKey,
  decryptWithChatKey: vi.fn(),
  encryptArrayWithChatKey: mockEncryptArrayWithChatKey,
  decryptArrayWithChatKey: vi.fn(),
}));

vi.mock("../encryption/MetadataEncryptor", () => ({
  encryptChatKeyWithMasterKey: mockEncryptChatKeyWithMasterKey,
  decryptChatKeyWithMasterKey: vi.fn(),
  encryptWithMasterKey: mockEncryptWithMasterKey,
  generateEmbedKey: vi.fn(),
  deriveEmbedKeyFromChatKey: mockDeriveEmbedKeyFromChatKey,
  encryptWithEmbedKey: mockEncryptWithEmbedKey,
  wrapEmbedKeyWithMasterKey: mockWrapEmbedKeyWithMasterKey,
  wrapEmbedKeyWithChatKey: mockWrapEmbedKeyWithChatKey,
}));

vi.mock("../chatSyncServiceHandlersChatUpdates", () => ({
  flushPendingMessagesForChat: vi.fn(),
}));

vi.mock("../chatSyncServiceHandlersAppSettings", () => ({
  flushPendingSystemMessagesForChat: vi.fn(),
}));

vi.mock("../chatSyncServiceSenders", () => ({
  sendEncryptedStoragePackage: mockSendEncryptedStoragePackage,
  sendStoreEmbedImpl: mockSendStoreEmbed,
  sendStoreEmbedKeysImpl: mockSendStoreEmbedKeys,
  sendStoreEmbedDiffImpl: mockSendStoreEmbedDiff,
  sendPostProcessingMetadataImpl: mockSendPostProcessingMetadata,
}));

vi.mock("../websocketService", () => ({
  webSocketService: mockWebSocketService,
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

vi.mock("../../stores/activeChatStore", () => ({
  activeChatStore: mockActiveChatStore,
}));

vi.mock("../../stores/notificationStore", () => ({
  notificationStore: mockNotificationStore,
}));

vi.mock("../../stores/unreadMessagesStore", () => ({
  unreadMessagesStore: mockUnreadMessagesStore,
}));

vi.mock("../../stores/userProfile", () => ({
  userProfile: {
    subscribe: (run: (value: { user_id: string }) => void) => {
      run({ user_id: "user-1" });
      return () => {};
    },
  },
}));

describe("sub-chat lifecycle metadata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockChatDB.getChat.mockResolvedValue(null);
    mockChatDB.addChat.mockResolvedValue(undefined);
    mockChatKeyManager.getKeySync.mockReturnValue(new Uint8Array([1, 2, 3]));
    mockChatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mockEncryptWithChatKey.mockImplementation(async (value: string) => `encrypted:${value}`);
    mockEncryptChatKeyWithMasterKey.mockResolvedValue("encrypted-parent-key");
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
  it("persists complete spawn-time title and category metadata before first render", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    const payload = {
      type: "spawn_sub_chats" as const,
      chat_id: "parent-chat",
      sub_chats: [{
        id: "child-chat",
        user_message_id: "",
        prompt: "Investigate the EU AI Act legal obligations for open-source model providers.",
        title: "EU AI Act legal obligations",
        category: "legal_law",
        icon: "scale",
      }],
    };

    await handleSpawnSubChatsImpl(service, payload);

    expect(mockChatDB.addChat).toHaveBeenCalledWith(expect.objectContaining({
      chat_id: "child-chat",
      title: "EU AI Act legal obligations",
      encrypted_title: "encrypted:EU AI Act legal obligations",
      encrypted_category: "encrypted:legal_law",
      encrypted_icon: "encrypted:scale",
    }));
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
  it("does not persist protocol-only tool JSON as a visible child summary", async () => {
    const childChat = {
      chat_id: "child-chat",
      parent_id: "parent-chat",
      is_sub_chat: true,
      encrypted_title: "encrypted-title",
      messages_v: 1,
      title_v: 0,
      unread_count: 0,
      created_at: 1,
      updated_at: 1,
      last_edited_overall_timestamp: 1,
      chat_summary: null,
    };
    mockChatDB.getChat.mockResolvedValue(childChat);
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;

    await handleSubChatCompletedImpl(service, {
      type: "sub_chat_completed",
      chat_id: "child-chat",
      parent_id: "parent-chat",
      summary: '```json\n{"type":"app_skill_use","app_id":"web","skill_id":"search"}\n```',
    });

    expect(mockChatDB.updateChat).toHaveBeenCalledWith(expect.objectContaining({
      chat_summary: null,
    }));
    expect(mockEncryptWithChatKey).not.toHaveBeenCalledWith(expect.stringContaining("app_skill_use"), expect.anything());
  });

  // contract-test: direct surface=gui.web assertions=chats.local-state.precedence,chats.surface.semantic-parity
  it("stops showing the parent as processing while it waits for child chats", () => {
    const activeAITasks = new Map([
      ["parent-chat", { taskId: "parent-task", userMessageId: "user-message" }],
    ]);
    const service = {
      activeAITasks,
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    handleAwaitingSubChatsCompletionImpl(service, {
      type: "awaiting_sub_chats_completion",
      chat_id: "parent-chat",
      task_id: "parent-task",
      message_id: "parent-task",
    });

    expect(activeAITasks.has("parent-chat")).toBe(false);
    expect(mockAiTypingStore.clearTypingForChat).toHaveBeenCalledWith("parent-chat");
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "aiTaskEnded" }));
  });
});

describe("handleAIResponseStorageFailedImpl", () => {
  // contract-test: direct surface=gui.web assertions=chats.completion.pending-delivery,chats.message.identity-idempotent
  it("unmarks, queues, and retries the exact assistant response once", async () => {
    const service = {
      unmarkMessageSyncing: vi.fn(),
      dispatchEvent: vi.fn(),
      sendCompletedAIResponse: vi.fn(),
    } as unknown as ChatSynchronizationService;
    const message = { message_id: "assistant-1", chat_id: "chat-1" };
    mockChatDB.getMessage.mockResolvedValue(message);

    await handleAIResponseStorageFailedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      task_id: "retry-task-1",
    });

    expect(service.unmarkMessageSyncing).toHaveBeenCalledWith("assistant-1");
    expect(mockPendingAIResponses.add).toHaveBeenCalledWith("assistant-1", "chat-1");
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "aiResponseStorageFailed" }),
    );
    expect(service.sendCompletedAIResponse).toHaveBeenCalledWith(message);

    await handleAIResponseStorageFailedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      task_id: "retry-task-2",
    });
    expect(service.sendCompletedAIResponse).toHaveBeenCalledTimes(1);

    mockChatDB.getChat.mockResolvedValue(null);
    await handleAIResponseStorageConfirmedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      task_id: "websocket-direct",
    });
  });

  // contract-test: direct surface=gui.web assertions=chats.completion.pending-delivery,chats.message.identity-idempotent
  it("removes the retry entry only after durable storage confirmation", async () => {
    const service = {
      unmarkMessageSyncing: vi.fn(),
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;
    mockChatDB.getChat.mockResolvedValue(null);

    await handleAIResponseStorageConfirmedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      task_id: "websocket-direct",
    });

    expect(service.unmarkMessageSyncing).toHaveBeenCalledWith("assistant-1");
    expect(mockPendingAIResponses.remove).toHaveBeenCalledWith("assistant-1");
  });
});

describe("handleAIBackgroundResponseCompletedImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/");
    mockChatDB.saveMessage.mockResolvedValue(undefined);
    mockChatDB.updateChat.mockResolvedValue(undefined);
    mockActiveChatStore.get.mockReturnValue(null);
  });

  // contract-test: direct surface=gui.web assertions=chats.completion.recovery-takeover,chats.completion.lease-fenced
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
    expect(activeAITasks.has("chat-1")).toBe(true);
    expect(mockAiTypingStore.clearTyping).not.toHaveBeenCalled();
    expect(service.dispatchEvent).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: "aiTaskEnded" }),
    );
  });

  // contract-test: direct surface=gui.web assertions=chats.completion.pending-delivery,chats.local-state.precedence
  it("does not notify when the completed background response is for the visibly open chat", async () => {
    const chat = {
      chat_id: "chat-1",
      title: "Open chat",
      messages_v: 1,
      last_edited_overall_timestamp: 100,
    };
    mockChatDB.getChat.mockResolvedValue(chat);
    mockActiveChatStore.get.mockReturnValue(null);
    window.location.hash = "#chat-id=chat-1";
    const service = {
      activeAITasks: new Map([["chat-1", { taskId: "task-1" }]]),
      dispatchEvent: vi.fn(),
      sendCompletedAIResponse: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleAIBackgroundResponseCompletedImpl(service, {
      chat_id: "chat-1",
      message_id: "assistant-1",
      user_message_id: "user-message-1",
      task_id: "task-1",
      full_content: "Visible chat response",
      category: "general_knowledge",
    });

    expect(mockChatDB.saveMessage).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: "assistant-1", chat_id: "chat-1" }),
    );
    expect(mockUnreadMessagesStore.incrementUnread).not.toHaveBeenCalled();
    expect(mockNotificationStore.chatMessage).not.toHaveBeenCalled();
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
    mockEnsureChatKeySafeForWrite.mockImplementation(async (
      chatId: string,
      chatKey: Uint8Array,
    ) => {
      const currentChat = await mockChatDB.getChat(chatId) as {
        encrypted_chat_key?: unknown;
      } | null;
      const wrapper = currentChat?.encrypted_chat_key;
      return typeof wrapper === "string"
        ? mockEncryptedChatKeyMatchesRawKey(
            wrapper,
            chatKey,
            mockChatKeyManager.computeKeyFingerprint,
          )
        : true;
    });
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

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
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

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
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

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
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

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
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

describe("handlePostProcessingCompletedImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockChatDB.updateChat.mockResolvedValue(undefined);
    mockChatKeyManager.withKey.mockImplementation(
      async (
        _chatId: string,
        _reason: string,
        callback: (key: Uint8Array) => Promise<void>,
      ) => {
        await callback(new Uint8Array([1, 2, 3]));
      },
    );
    mockEnsureChatKeySafeForWrite.mockResolvedValue(true);
    mockEncryptWithChatKey.mockImplementation(async (value: string) =>
      `encrypted:${value}`,
    );
    mockEncryptArrayWithChatKey.mockImplementation(async (values: string[]) =>
      `encrypted-array:${values.join(",")}`,
    );
    mockEncryptWithMasterKey.mockImplementation(async (value: string) =>
      `encrypted-master:${value}`,
    );
    mockSendPostProcessingMetadata.mockResolvedValue(undefined);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.local-state.precedence
  it("does not overwrite a newer manual summary with stale generated post-processing", async () => {
    const existingChat = {
      chat_id: "chat-1",
      encrypted_title: "encrypted-title",
      encrypted_chat_summary: "manual-summary",
      encrypted_chat_key: "encrypted-chat-key",
      messages_v: 2,
      title_v: 3,
      metadata_v: 4,
      last_edited_overall_timestamp: 100,
      unread_count: 0,
      created_at: 100,
      updated_at: 200,
    };
    mockChatDB.getChat.mockResolvedValue(existingChat);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handlePostProcessingCompletedImpl(service, {
      chat_id: "chat-1",
      task_id: "task-1",
      follow_up_request_suggestions: ["Follow up"],
      new_chat_request_suggestions: [],
      chat_summary: "Generated summary from the old response baseline",
      share_cta_text: "",
      chat_tags: ["Berlin"],
      harmful_response: 0,
      top_recommended_apps_for_user: [],
      quick_tip_slugs: [],
      source_title_v: 3,
      source_metadata_v: 3,
    });

    expect(mockEncryptWithChatKey).not.toHaveBeenCalledWith(
      "Generated summary from the old response baseline",
      expect.any(Uint8Array),
    );
    expect(mockChatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-1",
        encrypted_chat_summary: "manual-summary",
        encrypted_follow_up_request_suggestions: "encrypted-array:Follow up",
        encrypted_chat_tags: "encrypted-array:Berlin",
      }),
    );
    expect(mockSendPostProcessingMetadata).toHaveBeenCalledWith(
      service,
      "chat-1",
      "encrypted-array:Follow up",
      [],
      "",
      "encrypted-array:Berlin",
      "",
      "",
      "",
      "",
      "encrypted-chat-key",
    );
  });
});

describe("handleEmbedUpdateImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // contract-test: direct surface=gui.web assertions=chats.surface.semantic-parity,chats.local-state.precedence
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

describe("handleSendEmbedDataImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearProcessedEmbedsTracking();
    mockEmbedStore.get.mockResolvedValue(null);
    mockEmbedStore.getEmbedKey.mockResolvedValue(null);
    mockChatListCache.getCache.mockReturnValue(null);
    mockEnsureChatKeySafeForWrite.mockResolvedValue(true);
    mockComputeSHA256.mockImplementation(async (value: string) => {
      if (value === "chat-1") return HASHED_CHAT_ID;
      if (value === "message-1") return HASHED_MESSAGE_ID;
      if (value === "user-1") return HASHED_USER_ID;
      if (value === "embed-1") return HASHED_EMBED_ID;
      return `hashed:${value}`;
    });
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("stores already-encrypted Directus fallback embeds without waiting for raw chat keys", async () => {
    const hashedChatId = "a".repeat(64);
    const hashedMessageId = "b".repeat(64);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleSendEmbedDataImpl(service, {
      type: "send_embed_data",
      event_for_client: "send_embed_data",
      payload: {
        embed_id: "embed-directus-fallback",
        type: "encrypted-recording-type",
        content: "encrypted-recording-content",
        text_preview: "encrypted-preview",
        status: "finished",
        chat_id: hashedChatId,
        message_id: hashedMessageId,
        user_id: "user-1",
        createdAt: 123,
        updatedAt: 124,
        already_encrypted: true,
        embed_keys: [
          {
            hashed_embed_id: "hashed-embed",
            key_type: "chat",
            hashed_chat_id: hashedChatId,
            encrypted_embed_key: "wrapped-key",
            hashed_user_id: "hashed-user",
            created_at: 123,
          },
        ],
      },
    } as unknown as Parameters<typeof handleSendEmbedDataImpl>[1]);

    expect(mockChatDB.getChat).not.toHaveBeenCalled();
    expect(mockChatKeyManager.getKeySync).not.toHaveBeenCalled();
    expect(mockEmbedStore.storeEmbedKeys).toHaveBeenCalledWith([
      expect.objectContaining({
        hashed_embed_id: "hashed-embed",
        hashed_chat_id: hashedChatId,
        encrypted_embed_key: "wrapped-key",
      }),
    ]);
    expect(mockEmbedStore.putEncrypted).toHaveBeenCalledWith(
      "embed:embed-directus-fallback",
      expect.objectContaining({
        embed_id: "embed-directus-fallback",
        encrypted_content: "encrypted-recording-content",
        hashed_chat_id: hashedChatId,
        hashed_message_id: hashedMessageId,
      }),
      "encrypted-recording-type",
    );
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "embedUpdated",
        detail: expect.objectContaining({
          embed_id: "embed-directus-fallback",
          type: "encrypted-recording-type",
          status: "finished",
          isProcessing: false,
        }),
      }),
    );
  });

  // contract-test: direct surface=gui.web assertions=code-run.artifacts.chat-bound-versioned
  it("persists child embeds with inherited parent deletion indexes", async () => {
    const chatKey = new Uint8Array([1, 2, 3]);
    const parentEmbedKey = new Uint8Array([4, 5, 6]);
    const parentIndexes = {
      hashed_chat_id: "parent-chat-hash",
      hashed_message_id: "parent-message-hash",
      hashed_user_id: "parent-user-hash",
    };
    mockChatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      encrypted_chat_key: "encrypted-chat-key",
    });
    mockChatKeyManager.getKeySync.mockReturnValue(chatKey);
    mockChatKeyManager.getKey.mockResolvedValue(chatKey);
    mockEmbedStore.getEmbedKey.mockResolvedValue(parentEmbedKey);
    mockEncryptWithEmbedKey.mockImplementation(async (value: string) =>
      `encrypted:${value}`,
    );
    mockSendStoreEmbed.mockResolvedValue(undefined);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleSendEmbedDataImpl(service, {
      type: "send_embed_data",
      event_for_client: "send_embed_data",
      payload: {
        embed_id: "child-1",
        type: "file-file",
        content: JSON.stringify({ app_id: "file", skill_id: "file" }),
        status: "finished",
        chat_id: "chat-1",
        message_id: "incorrect-parent-embed-id",
        user_id: "user-1",
        parent_embed_id: "parent-1",
        createdAt: 123,
        updatedAt: 124,
      },
    }, parentIndexes);

    expect(mockEmbedStore.putEncrypted).toHaveBeenCalledWith(
      "embed:child-1",
      expect.objectContaining({
        parent_embed_id: "parent-1",
        ...parentIndexes,
      }),
      "file-file",
      expect.any(String),
      expect.objectContaining({ app_id: "file", skill_id: "file" }),
      expect.any(Object),
    );
    expect(mockSendStoreEmbed).toHaveBeenCalledWith(
      service,
      expect.objectContaining({
        parent_embed_id: "parent-1",
        ...parentIndexes,
      }),
    );
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
  it("accepts finalized send_embed_data refreshes for existing finished embeds", async () => {
    const chatKey = new Uint8Array([1, 2, 3]);
    const embedKey = new Uint8Array([4, 5, 6]);
    mockEmbedStore.get.mockResolvedValue({
      embed_id: "embed-1",
      status: "finished",
      version_number: 1,
      content: "status: finished\nfilename: stale.pdf",
    });
    mockChatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      encrypted_chat_key: "encrypted-chat-key",
    });
    mockChatKeyManager.getKeySync.mockReturnValue(chatKey);
    mockChatKeyManager.getKey.mockResolvedValue(chatKey);
    mockDeriveEmbedKeyFromChatKey.mockResolvedValue(embedKey);
    mockEncryptWithEmbedKey.mockImplementation(async (value: string) =>
      `encrypted:${value}`,
    );
    mockWrapEmbedKeyWithMasterKey.mockResolvedValue("wrapped-master-key");
    mockWrapEmbedKeyWithChatKey.mockResolvedValue("wrapped-chat-key");
    mockSendStoreEmbed.mockResolvedValue(undefined);
    mockSendStoreEmbedKeys.mockResolvedValue(undefined);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleSendEmbedDataImpl(service, {
      type: "send_embed_data",
      event_for_client: "send_embed_data",
      payload: {
        embed_id: "embed-1",
        type: "pdf",
        content: "app_id: pdf\nskill_id: read\nembed_ref: refreshed-pdf-A1b\nstatus: finished\nfilename: refreshed.pdf\nscreenshot_url: https://example.invalid/page.png",
        text_preview: "Refreshed PDF",
        status: "finished",
        chat_id: "chat-1",
        message_id: "message-1",
        user_id: "user-1",
        version_number: 1,
        createdAt: 123,
        updatedAt: 124,
      },
    });

    expect(mockEmbedStore.putEncrypted).toHaveBeenCalledWith(
      "embed:embed-1",
      expect.objectContaining({
        embed_id: "embed-1",
        encrypted_content: expect.stringContaining("refreshed.pdf"),
        status: "finished",
      }),
      "pdf",
      expect.stringContaining("refreshed.pdf"),
      expect.objectContaining({ app_id: "pdf", skill_id: "read" }),
      {
        skipEmbedRefRegistration: true,
        deferChildEmbedRefRegistration: true,
      },
    );
    expect(mockEmbedStore.registerEmbedRef).toHaveBeenCalledWith(
      "refreshed-pdf-A1b",
      "embed-1",
      "pdf",
      "pdf",
      "read",
    );
    expect(mockEmbedStore.putEncrypted.mock.invocationCallOrder[0]).toBeLessThan(
      mockEmbedStore.registerEmbedRef.mock.invocationCallOrder[0],
    );
    expect(mockEmbedStore.registerEmbedRef).toHaveBeenCalledTimes(1);
    expect(mockSendStoreEmbed).toHaveBeenCalledWith(
      service,
      expect.objectContaining({
        embed_id: "embed-1",
        status: "finished",
      }),
    );
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "embedUpdated",
        detail: expect.objectContaining({
          embed_id: "embed-1",
          type: "pdf",
          status: "finished",
          isProcessing: false,
        }),
      }),
    );
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
  it("stores Finance owner PII mappings as sidecar data without syncing them in store_embed", async () => {
    const chatKey = new Uint8Array([1, 2, 3]);
    const embedKey = new Uint8Array([4, 5, 6]);
    mockChatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      encrypted_chat_key: "encrypted-chat-key",
    });
    mockChatKeyManager.getKeySync.mockReturnValue(chatKey);
    mockChatKeyManager.getKey.mockResolvedValue(chatKey);
    mockDeriveEmbedKeyFromChatKey.mockResolvedValue(embedKey);
    mockEncryptWithEmbedKey.mockImplementation(async (value: string) =>
      `encrypted:${value}`,
    );
    mockWrapEmbedKeyWithMasterKey.mockResolvedValue("wrapped-master-key");
    mockWrapEmbedKeyWithChatKey.mockResolvedValue("wrapped-chat-key");
    mockSendStoreEmbed.mockResolvedValue(undefined);
    mockSendStoreEmbedKeys.mockResolvedValue(undefined);
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleSendEmbedDataImpl(service, {
      type: "send_embed_data",
      event_for_client: "send_embed_data",
      payload: {
        embed_id: "embed-1",
        type: "app_skill_use",
        content: "app_id: finance\nskill_id: check_accounts\nstatus: finished\noverview_transactions[1]{counterparty_placeholder}:\n  [MERCHANT_SOFTWARE_001]",
        text_preview: "Finance overview",
        status: "finished",
        chat_id: "chat-1",
        message_id: "message-1",
        user_id: "user-1",
        createdAt: 123,
        updatedAt: 124,
        owner_pii_mappings: [
          {
            placeholder: "[MERCHANT_SOFTWARE_001]",
            original: "SaaS Vendor Ltd",
            type: "COUNTERPARTY",
          },
        ],
      },
    });

    expect(mockEmbedStore.put).toHaveBeenCalledWith(
      "embed_pii:embed-1",
      expect.objectContaining({
        embed_id: "embed-1",
        pii_mappings: [
          {
            placeholder: "[MERCHANT_SOFTWARE_001]",
            original: "SaaS Vendor Ltd",
            type: "COUNTERPARTY",
          },
        ],
      }),
      "code-code",
    );
    expect(mockEmbedStore.putEncrypted).toHaveBeenCalledWith(
      "embed:embed-1",
      expect.objectContaining({
        embed_id: "embed-1",
        encrypted_content: expect.not.stringContaining("SaaS Vendor Ltd"),
      }),
      "app_skill_use",
      expect.not.stringContaining("SaaS Vendor Ltd"),
      expect.objectContaining({ app_id: "finance", skill_id: "check_accounts" }),
      {
        skipEmbedRefRegistration: true,
        deferChildEmbedRefRegistration: true,
      },
    );
    expect(mockSendStoreEmbed).toHaveBeenCalledWith(
      service,
      expect.not.objectContaining({ owner_pii_mappings: expect.anything() }),
    );
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("flushes queued finalized embeds that arrived with hashed chat IDs", async () => {
    vi.useFakeTimers();
    try {
      const chatKey = new Uint8Array([1, 2, 3]);
      const embedKey = new Uint8Array([4, 5, 6]);
      const localChat = {
        chat_id: "chat-1",
        encrypted_chat_key: "encrypted-chat-key",
      };
      mockChatDB.getChat.mockImplementation(async (chatId: string) =>
        chatId === "chat-1" ? localChat : null,
      );
      mockChatDB.getAllChats.mockResolvedValue([localChat]);
      mockChatListCache.getCache.mockReturnValue([localChat]);
      mockChatKeyManager.getKeySync.mockImplementation((chatId: string) =>
        chatId === "chat-1" ? chatKey : null,
      );
      mockChatKeyManager.getKey.mockImplementation(async (chatId: string) =>
        chatId === "chat-1" ? chatKey : null,
      );
      mockDeriveEmbedKeyFromChatKey.mockResolvedValue(embedKey);
      mockEncryptWithEmbedKey.mockImplementation(async (value: string) =>
        `encrypted:${value}`,
      );
      mockWrapEmbedKeyWithMasterKey.mockResolvedValue("wrapped-master-key");
      mockWrapEmbedKeyWithChatKey.mockResolvedValue("wrapped-chat-key");
      mockSendStoreEmbed.mockResolvedValue(undefined);
      mockSendStoreEmbedKeys.mockResolvedValue(undefined);
      const service = {
        dispatchEvent: vi.fn(),
      } as unknown as ChatSynchronizationService;

      await handleSendEmbedDataImpl(service, {
        type: "send_embed_data",
        event_for_client: "send_embed_data",
        payload: {
          embed_id: "embed-1",
          type: "pdf",
          content: JSON.stringify({ app_id: "pdf", skill_id: "read" }),
          text_preview: "Test PDF",
          status: "finished",
          chat_id: HASHED_CHAT_ID,
          message_id: "message-1",
          user_id: "user-1",
          createdAt: 123,
          updatedAt: 124,
        },
      });

      expect(mockEmbedStore.putEncrypted).not.toHaveBeenCalled();

      await flushPendingFinalizedEmbedsForChat(service, HASHED_CHAT_ID);

      expect(mockChatKeyManager.getKey).toHaveBeenCalledWith("chat-1");
      expect(mockEmbedStore.putEncrypted).toHaveBeenCalledWith(
        "embed:embed-1",
        expect.objectContaining({
          embed_id: "embed-1",
          encrypted_content: "encrypted:{\"app_id\":\"pdf\",\"skill_id\":\"read\"}",
          hashed_chat_id: HASHED_CHAT_ID,
          hashed_message_id: HASHED_MESSAGE_ID,
          status: "finished",
        }),
        "pdf",
        JSON.stringify({ app_id: "pdf", skill_id: "read" }),
        expect.objectContaining({ app_id: "pdf", skill_id: "read" }),
        {
          skipEmbedRefRegistration: true,
          deferChildEmbedRefRegistration: true,
        },
      );
      expect(mockSendStoreEmbed).toHaveBeenCalledWith(
        service,
        expect.objectContaining({
          embed_id: "embed-1",
          hashed_chat_id: HASHED_CHAT_ID,
          hashed_message_id: HASHED_MESSAGE_ID,
          hashed_user_id: HASHED_USER_ID,
        }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("flushes hashed queued finalized embeds when the raw chat shell is created", async () => {
    vi.useFakeTimers();
    try {
      const chatKey = new Uint8Array([1, 2, 3]);
      const embedKey = new Uint8Array([4, 5, 6]);
      const localChat = {
        chat_id: "chat-1",
        encrypted_chat_key: "encrypted-chat-key",
      };
      mockChatDB.getChat.mockImplementation(async (chatId: string) =>
        chatId === "chat-1" ? localChat : null,
      );
      mockChatDB.getAllChats.mockResolvedValue([localChat]);
      mockChatListCache.getCache.mockReturnValue([localChat]);
      mockChatKeyManager.getKeySync.mockImplementation((chatId: string) =>
        chatId === "chat-1" ? chatKey : null,
      );
      mockChatKeyManager.getKey.mockImplementation(async (chatId: string) =>
        chatId === "chat-1" ? chatKey : null,
      );
      mockDeriveEmbedKeyFromChatKey.mockResolvedValue(embedKey);
      mockEncryptWithEmbedKey.mockImplementation(async (value: string) =>
        `encrypted:${value}`,
      );
      mockWrapEmbedKeyWithMasterKey.mockResolvedValue("wrapped-master-key");
      mockWrapEmbedKeyWithChatKey.mockResolvedValue("wrapped-chat-key");
      mockSendStoreEmbed.mockResolvedValue(undefined);
      mockSendStoreEmbedKeys.mockResolvedValue(undefined);
      const service = {
        dispatchEvent: vi.fn(),
      } as unknown as ChatSynchronizationService;

      await handleSendEmbedDataImpl(service, {
        type: "send_embed_data",
        event_for_client: "send_embed_data",
        payload: {
          embed_id: "embed-1",
          type: "pdf",
          content: JSON.stringify({ app_id: "pdf", skill_id: "read" }),
          text_preview: "Test PDF",
          status: "finished",
          chat_id: HASHED_CHAT_ID,
          message_id: "message-1",
          user_id: "user-1",
          createdAt: 123,
          updatedAt: 124,
        },
      });

      expect(mockEmbedStore.putEncrypted).not.toHaveBeenCalled();

      await flushPendingFinalizedEmbedsForChat(service, "chat-1");

      expect(mockEmbedStore.putEncrypted).toHaveBeenCalledWith(
        "embed:embed-1",
        expect.objectContaining({
          embed_id: "embed-1",
          encrypted_content: "encrypted:{\"app_id\":\"pdf\",\"skill_id\":\"read\"}",
          hashed_chat_id: HASHED_CHAT_ID,
          hashed_message_id: HASHED_MESSAGE_ID,
          status: "finished",
        }),
        "pdf",
        JSON.stringify({ app_id: "pdf", skill_id: "read" }),
        expect.objectContaining({ app_id: "pdf", skill_id: "read" }),
        {
          skipEmbedRefRegistration: true,
          deferChildEmbedRefRegistration: true,
        },
      );
      expect(mockSendStoreEmbed).toHaveBeenCalledWith(
        service,
        expect.objectContaining({
          embed_id: "embed-1",
          hashed_chat_id: HASHED_CHAT_ID,
          hashed_message_id: HASHED_MESSAGE_ID,
          hashed_user_id: HASHED_USER_ID,
        }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,drafts.boundaries.session-and-incognito
  it("stores finalized server incognito embeds in memory without durable persistence", async () => {
    const service = {
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleSendEmbedDataImpl(service, {
      type: "send_embed_data",
      event_for_client: "send_embed_data",
      payload: {
        embed_id: "embed-1",
        type: "app-skill-use",
        content: "app_id: images\nskill_id: search\nstatus: finished",
        text_preview: "Image search results",
        status: "finished",
        chat_id: "incognito",
        message_id: "message-1",
        user_id: "user-1",
        createdAt: 123,
        updatedAt: 124,
      },
    });

    expect(mockEmbedStore.setInMemoryOnly).toHaveBeenCalledWith(
      "embed:embed-1",
      expect.objectContaining({
        embed_id: "embed-1",
        status: "finished",
        content: "app_id: images\nskill_id: search\nstatus: finished",
        chat_id: "incognito",
      }),
    );
    expect(mockEmbedStore.putEncrypted).not.toHaveBeenCalled();
    expect(mockSendStoreEmbed).not.toHaveBeenCalled();
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "embedUpdated",
        detail: expect.objectContaining({
          embed_id: "embed-1",
          type: "app-skill-use",
          status: "finished",
          isProcessing: false,
        }),
      }),
    );
  });
});
