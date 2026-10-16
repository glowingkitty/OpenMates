import { invalidateWorkspaceCaches } from '../workspaceCacheLifecycle';
beforeEach(() => invalidateWorkspaceCaches());
vi.mock('../generatedChatMetadataPersistence', () => ({ persistGeneratedChatMetadata: vi.fn(async (_db: unknown, baseline: any, patch: any, isCurrent: () => boolean, filterPatch: (patch: any) => any = (value) => value) => {
  if (!isCurrent()) return null;
  const updated = { ...baseline, ...filterPatch(patch) };
  await mockChatDB.updateChat(updated);
  return updated;
}) }));
// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersAI.test.ts
// Regression coverage for AI websocket embed handlers.
// These tests focus on event ordering races between embed_update and
// send_embed_data, where the UI can otherwise stay on a loading preview.
// Keep mocks narrow so handler behavior remains visible.

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";
import { noteChatMetadataTurn } from "../lateChatMetadataGuard";
import { hasQueuedProcessing } from "../queuedMessageLifecycle";
import { markAcknowledgedRecoveredEmbed, withCanonicalEmbedWrite } from "../canonicalEmbedWriteCoordinator";
import {
  clearPendingQueuedRevisionsImpl,
  clearProcessedEmbedsTracking,
  flushPendingFinalizedEmbedsForChat,
  handleAIBackgroundResponseCompletedImpl,
  handleAIMessageUpdateImpl,
  handleAITaskInitiatedImpl,
  handleAITaskCancelRequestedImpl,
  handleAIResponseStorageConfirmedImpl,
  handleAIResponseStorageFailedImpl,
  handleAITypingStartedImpl,
  handleAITypingEndedImpl,
  handleMessageQueuedImpl,
  handleQueuedHandoffPausedImpl,
  handleQueuedMessageStartedImpl,
  handleQueuedMessagesSnapshotImpl,
  handleQueuedMessageUpdatedImpl,
  handleAwaitingSubChatsCompletionImpl,
  handleChatCompressionCheckpointStoredImpl,
  persistClientEncryptedCompressionCheckpoint,
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

describe("context failure typing end", () => {
  beforeEach(() => vi.clearAllMocks());

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it("ends the matching task once without creating an assistant response", () => {
    const activeAITasks = new Map([["chat-1", { taskId: "task-1", userMessageId: "user-1" }]]);
    const service = { activeAITasks, dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    const payload = {
      chat_id: "chat-1", message_id: "task-1", task_id: "task-1",
      terminal_failure_code: "client_context_unavailable",
    };

    handleAITypingEndedImpl(service, payload);
    handleAITypingEndedImpl(service, payload);

    expect(activeAITasks.has("chat-1")).toBe(false);
    expect(mockAiTypingStore.clearTyping).toHaveBeenCalledWith("chat-1", "task-1");
    const ended = vi.mocked(service.dispatchEvent).mock.calls
      .map(([event]) => event as CustomEvent)
      .filter((event) => event.type === "aiTaskEnded");
    expect(ended).toHaveLength(1);
    expect(ended[0].detail).toEqual({
      chatId: "chat-1", taskId: "task-1", userMessageId: "user-1", status: "failed",
    });
    expect(mockChatDB.saveMessage).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it("leaves a replacement task and legacy typing ends alone", () => {
    const activeAITasks = new Map([["chat-1", { taskId: "task-2", userMessageId: "user-2" }]]);
    const service = { activeAITasks, dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;

    handleAITypingEndedImpl(service, {
      chat_id: "chat-1", message_id: "task-1", task_id: "task-1",
      terminal_failure_code: "client_context_unavailable",
    });
    handleAITypingEndedImpl(service, { chat_id: "chat-1", message_id: "task-2" });

    expect(activeAITasks.get("chat-1")?.taskId).toBe("task-2");
    expect(service.dispatchEvent).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: "aiTaskEnded" }),
    );
  });
});

const mockChatDB = vi.hoisted(() => ({
  getChat: vi.fn(),
  getAllChats: vi.fn(),
  getEncryptedChatKey: vi.fn(),
  updateChat: vi.fn(),
  saveMessage: vi.fn(),
  getMessage: vi.fn(),
  getMessagesForChat: vi.fn(),
  getMessageWindowForChat: vi.fn(),
  applyQueuedMessageRevision: vi.fn(),
  updateMessageRawFields: vi.fn(),
  addChat: vi.fn(),
  saveChatCompressionCheckpoint: vi.fn(),
  deleteCoveredMessagesForChat: vi.fn(),
}));
const mockIncognitoChatService = vi.hoisted(() => ({
  getChat: vi.fn(),
  getMessagesForChat: vi.fn(),
  updateMessage: vi.fn(),
}));

// A queued incognito case must not redirect subsequent private-chat handlers
// into volatile storage. clearAllMocks clears calls but keeps implementations.
beforeEach(() => {
  mockIncognitoChatService.getChat.mockReset().mockResolvedValue(null);
  mockIncognitoChatService.getMessagesForChat.mockReset().mockResolvedValue([]);
  mockIncognitoChatService.updateMessage.mockReset().mockResolvedValue(false);
});

describe("queued user message socket events", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearPendingQueuedRevisionsImpl();
    mockChatDB.applyQueuedMessageRevision.mockResolvedValue(true);
    mockChatDB.updateMessageRawFields.mockResolvedValue(undefined);
    mockChatDB.getMessage.mockImplementation(async (id: string) => ({
      message_id: id, chat_id: "chat-1", role: "user", status: "queued",
      queue_revision: 1, queue_mode: "follow_up",
    }));
    mockChatDB.getChat.mockResolvedValue(null);
    mockIncognitoChatService.getChat.mockResolvedValue(null);
    mockIncognitoChatService.getMessagesForChat.mockResolvedValue([]);
    mockIncognitoChatService.updateMessage.mockResolvedValue(false);
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.editing.stable-revision
  it("persists queue metadata and encrypted edit ACKs before notifying the UI", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    await handleMessageQueuedImpl(service, {
      chat_id: "chat-1", user_message_id: "message-1", active_task_id: "task-1",
      queue_mode: "follow_up", queue_revision: 1,
    });
    await handleQueuedMessageUpdatedImpl(service, {
      chat_id: "chat-1", message_id: "message-1", queue_mode: "steer",
      queue_revision: 2, encrypted_content: "new-cipher", encrypted_pii_mappings: null,
    });
    expect(mockChatDB.applyQueuedMessageRevision).toHaveBeenNthCalledWith(
      2, "chat-1", "message-1", 2, "steer", "new-cipher", null,
    );
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "queuedMessageUpdated" }));
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it("clears every queued row when one task starts for a combined batch", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    await handleQueuedMessageStartedImpl(service, {
      chat_id: "chat-1", message_ids: ["message-1", "message-2"],
    });
    expect(mockChatDB.updateMessageRawFields).toHaveBeenCalledTimes(2);
    expect(mockChatDB.updateMessageRawFields).toHaveBeenCalledWith("message-1", {
      status: "synced", queue_revision: undefined, queue_mode: undefined,
      queue_dispatch_status: "processing",
    });
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({
      type: "queuedMessageStarted", detail: { chat_id: "chat-1", message_id: "message-2" },
    }));
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it("does not resurrect a started row from a late queued snapshot", async () => {
    const row = { message_id: "message-1", chat_id: "chat-1", role: "user",
      status: "queued", queue_revision: 1, queue_mode: "follow_up",
      queue_dispatch_status: "queued" };
    mockChatDB.getMessage.mockImplementation(async () => ({ ...row }));
    mockChatDB.updateMessageRawFields.mockImplementation(async (_id: string, fields: Record<string, unknown>) => {
      Object.assign(row, fields);
    });
    mockChatDB.applyQueuedMessageRevision.mockImplementation(async () => row.queue_dispatch_status !== "processing");
    mockChatDB.getMessageWindowForChat.mockImplementation(async () => ({ messages: [{ ...row }] }));
    const service = { dispatchEvent: vi.fn(), requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn() } as unknown as ChatSynchronizationService;
    await handleQueuedMessageStartedImpl(service, { chat_id: "chat-1", message_ids: ["message-1"] });
    await handleQueuedMessagesSnapshotImpl(service, { chat_id: "chat-1", messages: [{
      message_id: "message-1", queue_mode: "follow_up", queue_revision: 1,
    }] });
    expect(row.status).toBe("synced");
    expect(row.queue_dispatch_status).toBe("processing");
    expect(service.dispatchEvent).not.toHaveBeenCalledWith(expect.objectContaining({
      type: "messageStatusChanged", detail: expect.objectContaining({ status: "queued" }),
    }));
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it("keeps a durable queued row pending when Redis returns an empty snapshot", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    await handleQueuedMessagesSnapshotImpl(service, { chat_id: "chat-1", messages: [] });
    expect(mockChatDB.updateMessageRawFields).not.toHaveBeenCalled();
    expect(service.dispatchEvent).not.toHaveBeenCalledWith(expect.objectContaining({
      type: "queuedMessageStarted",
    }));
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it("defers only an uncertain snapshot for the service's active send", async () => {
    const service = {
      deferUncertainQueuedSnapshotForActiveSend: vi.fn((chatId: string) => chatId === "chat-1"),
      requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn(),
    } as unknown as ChatSynchronizationService;
    await handleQueuedMessagesSnapshotImpl(service, {
      chat_id: "chat-1", messages: [], uncertain: true,
    });
    expect(service.requestChatContentBatch_FOR_HANDLERS_ONLY).not.toHaveBeenCalled();
    await handleQueuedMessagesSnapshotImpl(service, {
      chat_id: "chat-2", messages: [], uncertain: true,
    });
    expect(service.requestChatContentBatch_FOR_HANDLERS_ONLY).toHaveBeenCalledWith(["chat-2"]);
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it("fences a started turn before its encrypted row or delayed queue ACK arrives", async () => {
    mockChatDB.getMessage.mockResolvedValue(null);
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    await handleQueuedMessageStartedImpl(service, { chat_id: "chat-1", message_ids: ["message-1"] });
    await handleMessageQueuedImpl(service, {
      chat_id: "chat-1", user_message_id: "message-1", active_task_id: "task-1",
      queue_mode: "follow_up", queue_revision: 1,
    });
    await handleQueuedMessagesSnapshotImpl(service, { chat_id: "chat-1", messages: [{
      message_id: "message-1", queue_mode: "follow_up", queue_revision: 1,
    }] });
    expect(mockChatDB.applyQueuedMessageRevision).not.toHaveBeenCalled();
    expect(mockChatDB.updateMessageRawFields).not.toHaveBeenCalled();
    expect(service.dispatchEvent).not.toHaveBeenCalledWith(expect.objectContaining({ type: "messageQueued" }));
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it("marks a saved user row as paused when durable queue admission fails", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    await handleQueuedHandoffPausedImpl(service, {
      chat_id: "chat-1", message_id: "message-1",
      reason_code: "durable_queue_marker_unavailable", retryable: false,
    });
    expect(mockChatDB.updateMessageRawFields).toHaveBeenCalledWith("message-1", {
      status: "synced", queue_revision: undefined, queue_mode: undefined,
      queue_dispatch_status: "paused", queue_dispatch_mode: undefined,
    });
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({
      type: "queuedHandoffPaused",
    }));
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.steering.safe-boundary,chat-queued-followups.admission.synced
  it("moves a consumed Steer from processing to paused on exact failure receipt", async () => {
    const row = { message_id: "message-1", chat_id: "chat-1", role: "user",
      status: "queued", queue_revision: 2, queue_mode: "steer",
      queue_dispatch_status: "queued" };
    mockChatDB.getMessage.mockResolvedValue(row);
    mockChatDB.updateMessageRawFields.mockImplementation(async (_id: string, fields: Record<string, unknown>) => {
      Object.assign(row, fields);
    });
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    await handleQueuedMessageStartedImpl(service, { chat_id: "chat-1", message_ids: ["message-1"] });
    expect(row.queue_dispatch_status).toBe("processing");
    expect(hasQueuedProcessing("chat-1", "message-1")).toBe(true);
    await handleQueuedHandoffPausedImpl(service, { chat_id: "chat-1", message_id: "message-1",
      reason_code: "steer_failed", retryable: false });
    expect(row.queue_dispatch_status).toBe("paused");
    expect(hasQueuedProcessing("chat-1", "message-1")).toBe(false);
    await handleMessageQueuedImpl(service, { chat_id: "chat-1", user_message_id: "message-1",
      active_task_id: "older-task", queue_mode: "steer", queue_revision: 2 });
    expect(row.queue_dispatch_status).toBe("paused");
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced,chat-queued-followups.editing.stable-revision
  it("keeps incognito queue revisions and terminal pause in volatile storage", async () => {
    let row = { chat_id: "chat-1", message_id: "message-1", role: "user",
      status: "synced", content: "private turn", queue_revision: undefined as number | undefined,
      queue_mode: undefined as "follow_up" | "steer" | undefined,
      queue_dispatch_status: undefined as string | undefined };
    mockIncognitoChatService.getChat.mockResolvedValue({ chat_id: "chat-1", is_incognito: true });
    mockIncognitoChatService.getMessagesForChat.mockImplementation(async () => [row]);
    mockIncognitoChatService.updateMessage.mockImplementation(async (_chatId, _messageId, update) => {
      const next = update(row);
      if (!next) return false;
      row = next;
      return true;
    });
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    await handleMessageQueuedImpl(service, {
      chat_id: "chat-1", user_message_id: "message-1", active_task_id: "task-1",
      queue_mode: "follow_up", queue_revision: 1,
    });
    await handleQueuedMessageUpdatedImpl(service, {
      chat_id: "chat-1", message_id: "message-1", queue_mode: "steer", queue_revision: 2,
    });
    expect(row).toMatchObject({ content: "private turn", status: "queued",
      queue_mode: "steer", queue_revision: 2 });
    await handleQueuedHandoffPausedImpl(service, {
      chat_id: "chat-1", message_id: "message-1",
      reason_code: "volatile_predecessor_failed", retryable: false,
    });
    expect(row).toMatchObject({ content: "private turn", status: "synced",
      queue_dispatch_status: "paused", queue_mode: undefined });
    expect(mockChatDB.applyQueuedMessageRevision).not.toHaveBeenCalled();
    expect(mockChatDB.updateMessageRawFields).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chat-queued-followups.admission.synced
  it("clears an incognito queued row when its task starts", async () => {
    let row = { chat_id: "chat-1", message_id: "message-1", role: "user",
      status: "queued", queue_revision: 2, queue_mode: "steer",
      queue_dispatch_status: "queued" };
    mockIncognitoChatService.getChat.mockResolvedValue({ chat_id: "chat-1", is_incognito: true });
    mockIncognitoChatService.getMessagesForChat.mockImplementation(async () => [row]);
    mockIncognitoChatService.updateMessage.mockImplementation(async (_chatId, _messageId, update) => {
      const next = update(row);
      if (!next) return false;
      row = next;
      return true;
    });
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    await handleQueuedMessageStartedImpl(service, { chat_id: "chat-1", message_ids: ["message-1"] });
    expect(row).toMatchObject({ status: "synced", queue_dispatch_status: "processing",
      queue_mode: undefined });
    await handleQueuedHandoffPausedImpl(service, { chat_id: "chat-1", message_id: "message-1",
      reason_code: "volatile_predecessor_failed", retryable: false });
    expect(row).toMatchObject({ status: "synced", queue_dispatch_status: "paused",
      queue_mode: undefined });
    expect(hasQueuedProcessing("chat-1", "message-1")).toBe(false);
    expect(mockChatDB.updateMessageRawFields).not.toHaveBeenCalled();
  });
});

const mockEmbedStore = vi.hoisted(() => ({
  cancelProcessingEmbeds: vi.fn(() => []),
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
  subscribe: vi.fn((run: (value: string | null) => void) => {
    run(null);
    return () => {};
  }),
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
  addEventListener: vi.fn(),
  send: vi.fn(),
  sendMessage: vi.fn(),
  notifyDataActivity: vi.fn(),
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

vi.mock("../chatSyncService", () => ({
  chatSyncService: {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  },
}));

vi.mock("../directChatService", () => ({
  startDirectChatIdentityEnrollment: vi.fn(),
  unwrapTeamOrDirectChatKey: vi.fn(),
}));

vi.mock("../incognitoChatService", () => ({
  incognitoChatService: mockIncognitoChatService,
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
  aiTypingByChatStore: {
    subscribe: (run: (value: Record<string, unknown>) => void) => {
      run({});
      return () => {};
    },
  },
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
  it("keeps generated concise metadata when the full child report completes", async () => {
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
      chat_summary: "Concise generated child summary.",
    };
    mockChatDB.getChat.mockResolvedValue(childChat);
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;

    await handleSubChatCompletedImpl(service, {
      type: "sub_chat_completed",
      chat_id: "child-chat",
      parent_id: "parent-chat",
      summary: "Full detailed child report. ".repeat(1000),
    });

    expect(mockChatDB.updateChat).toHaveBeenCalledWith(expect.objectContaining({
      chat_summary: "Concise generated child summary.",
    }));
    expect(mockEncryptWithChatKey).not.toHaveBeenCalledWith(expect.stringContaining("Full detailed child report"), expect.anything());
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

describe("compression checkpoint source manifest", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockChatKeyManager.getKey.mockResolvedValue(null);
    mockChatDB.saveChatCompressionCheckpoint.mockResolvedValue(undefined);
    mockChatDB.deleteCoveredMessagesForChat.mockResolvedValue(1);
  });

  // contract-test: supporting surface=gui.web assertions=storage.compression.incremental-archive
  it("removes only covered local messages and does not persist the archival manifest", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    const checkpoint = {
      id: "checkpoint-1", chat_id: "chat-1", encrypted_summary: "ciphertext",
      compressed_up_to_timestamp: 200, compressed_message_count: 2,
      covered_message_ids: ["message-1"], created_at: 201,
    };
    await handleChatCompressionCheckpointStoredImpl(service, { chat_id: "chat-1", checkpoint });
    expect(mockChatDB.deleteCoveredMessagesForChat).toHaveBeenCalledWith("chat-1", ["message-1"]);
    expect(mockChatDB.saveChatCompressionCheckpoint).toHaveBeenCalledWith(
      expect.not.objectContaining({ covered_message_ids: expect.anything() }),
    );
    await handleChatCompressionCheckpointStoredImpl(service, {
      chat_id: "chat-1", checkpoint: { ...checkpoint, id: "legacy", covered_message_ids: null },
    });
    expect(mockChatDB.deleteCoveredMessagesForChat).toHaveBeenCalledTimes(1);
  });
});

describe("voice compression canonical storage", () => {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.compressed-context,video-call.privacy
  it("waits for encrypted server receipt and local persistence before acknowledging a new prefix", async () => {
    vi.clearAllMocks();
    mockChatDB.getChat.mockResolvedValue({ chat_id: "chat-1" });
    mockChatKeyManager.getKey.mockResolvedValue(new Uint8Array(32));
    mockEnsureChatKeySafeForWrite.mockResolvedValue(true);
    mockEncryptWithChatKey.mockResolvedValue("encrypted-checkpoint");
    const service = new EventTarget() as ChatSynchronizationService;
    const payload = { chat_id: "chat-1", task_id: "voice-task", summary_message_id: "checkpoint-voice",
      summary_content: "Private compressed context", compressed_message_count: 2,
      compressed_up_to_timestamp: 200, compressed_up_to_message_id: "covered-2", covered_message_ids: ["covered-1", "covered-2"] };
    let complete = false;
    const waiting = persistClientEncryptedCompressionCheckpoint(payload, service).then(() => { complete = true; });
    await vi.waitFor(() => expect(mockWebSocketService.sendMessage).toHaveBeenCalledOnce());
    expect(complete).toBe(false);
    const sent = mockWebSocketService.sendMessage.mock.calls[0][1];
    expect(sent).toMatchObject({ encrypted_summary: "encrypted-checkpoint" });
    expect(sent).not.toHaveProperty("summary_content");
    expect(sent).not.toHaveProperty("summary");
    await handleChatCompressionCheckpointStoredImpl(service, { chat_id: "chat-1", checkpoint: {
      id: payload.summary_message_id, chat_id: "chat-1", encrypted_summary: sent.encrypted_summary,
      summary: payload.summary_content, compressed_up_to_timestamp: 200, compressed_up_to_message_id: "covered-2",
      compressed_message_count: 2, created_at: 201, covered_message_ids: payload.covered_message_ids,
    } });
    await waiting;
    expect(complete).toBe(true);
    expect(mockChatDB.saveChatCompressionCheckpoint).toHaveBeenCalledWith(expect.not.objectContaining({ summary: expect.anything() }));
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

describe("async skill continuation task lifecycle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const finalChunk = (taskId: string, awaiting = false) => ({
    type: "ai_message_chunk" as const,
    chat_id: "chat-1",
    task_id: taskId,
    message_id: `assistant-${taskId}`,
    user_message_id: "user-1",
    full_content_so_far: "",
    sequence: 1,
    is_final_chunk: true,
    awaiting_async_skill_continuation: awaiting,
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it("keeps the turn active through an interim final and ignores a stale final after handoff", () => {
    const activeAITasks = new Map<string, { taskId: string; userMessageId: string }>();
    const service = { activeAITasks, dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    handleAITaskInitiatedImpl(service, { chat_id: "chat-1", ai_task_id: "task-1", user_message_id: "user-1", status: "processing_started" });
    service.dispatchEvent = vi.fn();

    handleAIMessageUpdateImpl(service, finalChunk("task-1", true));
    expect(activeAITasks.get("chat-1")?.taskId).toBe("task-1");
    expect(mockAiTypingStore.clearTyping).not.toHaveBeenCalled();
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "aiMessageChunk" }));
    expect(service.dispatchEvent).not.toHaveBeenCalledWith(expect.objectContaining({ type: "aiTaskEnded" }));

    handleAITaskInitiatedImpl(service, { chat_id: "chat-1", ai_task_id: "task-2", user_message_id: "user-1", status: "processing_started" });
    service.dispatchEvent = vi.fn();
    handleAIMessageUpdateImpl(service, finalChunk("task-1"));
    expect(activeAITasks.get("chat-1")?.taskId).toBe("task-2");
    expect(mockAiTypingStore.clearTyping).not.toHaveBeenCalled();
    expect(service.dispatchEvent).not.toHaveBeenCalledWith(expect.objectContaining({ type: "aiTaskEnded" }));

    handleAIMessageUpdateImpl(service, finalChunk("task-2"));
    expect(activeAITasks.has("chat-1")).toBe(false);
    expect(mockAiTypingStore.clearTyping).toHaveBeenCalledWith("chat-1", "assistant-task-2");
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "aiTaskEnded" }));
  });

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.turn-lifecycle
  it("still clears a pending continuation when its task is cancelled", async () => {
    const activeAITasks = new Map<string, { taskId: string; userMessageId: string }>();
    const service = { activeAITasks, dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    handleAITaskInitiatedImpl(service, { chat_id: "chat-1", ai_task_id: "task-1", user_message_id: "user-1", status: "processing_started" });
    handleAIMessageUpdateImpl(service, finalChunk("task-1", true));
    service.dispatchEvent = vi.fn();

    await handleAITaskCancelRequestedImpl(service, { task_id: "task-1", status: "revocation_sent" });
    expect(activeAITasks.has("chat-1")).toBe(false);
    expect(mockAiTypingStore.clearTypingForChat).toHaveBeenCalledWith("chat-1");
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "aiTaskEnded" }));
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

  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.turn-lifecycle,chats.completion.pending-delivery
  it("persists an interim background message without ending its pending continuation", async () => {
    mockChatDB.getChat.mockResolvedValue({
      chat_id: "chat-1", title: "Project read", messages_v: 1,
      last_edited_overall_timestamp: 100,
    });
    const activeAITasks = new Map([["chat-1", { taskId: "task-1", userMessageId: "user-1" }]]);
    const service = {
      activeAITasks, dispatchEvent: vi.fn(), sendCompletedAIResponse: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleAIBackgroundResponseCompletedImpl(service, {
      chat_id: "chat-1", message_id: "assistant-1", user_message_id: "user-1",
      task_id: "task-1", full_content: "Interim reference",
      awaiting_async_skill_continuation: true,
    });

    expect(mockChatDB.saveMessage).toHaveBeenCalledWith(expect.objectContaining({
      message_id: "assistant-1", content: "Interim reference",
    }));
    expect(activeAITasks.get("chat-1")?.taskId).toBe("task-1");
    expect(mockAiTypingStore.clearTyping).not.toHaveBeenCalled();
    expect(service.dispatchEvent).not.toHaveBeenCalledWith(expect.objectContaining({ type: "aiTaskEnded" }));
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

  // contract-test: direct surface=gui.web assertions=chats.completion.independent-metadata,chats.local-state.precedence
  it.each([false, true])("accepts version-bound late headers during a newer turn while preserving newer/manual edits (%s)", async (newerHeader) => {
    noteChatMetadataTurn("chat-1", "new-task", "new-user");
    const existingChat = {
      chat_id: "chat-1", encrypted_chat_key: "encrypted-chat-key",
      title_v: newerHeader ? 3 : 1, metadata_v: newerHeader ? 3 : 1,
      encrypted_title: newerHeader ? "manual-title" : "initial-title",
      encrypted_chat_summary: newerHeader ? "manual-summary" : null,
      encrypted_draft_md: "edited draft",
    };
    mockChatDB.getChat.mockResolvedValue(existingChat);
    mockChatDB.getMessagesForChat.mockResolvedValue([{ role: "user", message_id: "new-user", status: "synced" }]);
    const service = { activeAITasks: new Map([["chat-1", { taskId: "new-task" }]]), dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    await handlePostProcessingCompletedImpl(service, {
      chat_id: "chat-1", task_id: "old-task", user_message_id: "old-user",
      source_title_v: 1, source_metadata_v: 1,
      updated_chat_title: "Late title", chat_summary: "Late summary",
      follow_up_request_suggestions: ["Old chips"], new_chat_request_suggestions: [], chat_tags: [], harmful_response: 0,
    });
    expect(mockChatDB.updateChat).toHaveBeenCalledWith(expect.objectContaining({
      encrypted_title: newerHeader ? "manual-title" : "encrypted:Late title",
      encrypted_chat_summary: newerHeader ? "manual-summary" : "encrypted:Late summary",
      encrypted_draft_md: "edited draft",
    }));
    expect(mockEncryptArrayWithChatKey).not.toHaveBeenCalledWith(["Old chips"], expect.anything());
    expect(vi.mocked(service.dispatchEvent).mock.calls.some(([event]) => event.type === "postProcessingCompleted")).toBe(false);
    mockChatDB.updateChat.mockClear();
    await handlePostProcessingCompletedImpl(service, {
      chat_id: "chat-1", task_id: "old-task", user_message_id: "old-user",
      updated_chat_title: "Unversioned stale title", chat_summary: "Unversioned stale summary",
      follow_up_request_suggestions: ["Old chips"], new_chat_request_suggestions: [], chat_tags: [], harmful_response: 0,
    });
    expect(mockChatDB.updateChat).not.toHaveBeenCalled();
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

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.local-state.precedence,assistant-speech.preference.chat-scoped-default-off
  it("keeps a generated summary when only the speech preference advanced metadata", async () => {
    const existingChat = {
      chat_id: "chat-1",
      encrypted_title: "encrypted-title",
      encrypted_chat_summary: null,
      encrypted_auto_speak_response: "encrypted:true",
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
      follow_up_request_suggestions: [],
      new_chat_request_suggestions: [],
      chat_summary: "Generated summary from the completed response",
      share_cta_text: "",
      chat_tags: [],
      harmful_response: 0,
      top_recommended_apps_for_user: [],
      quick_tip_slugs: [],
      source_title_v: 3,
      source_metadata_v: 3,
    });

    expect(mockEncryptWithChatKey).toHaveBeenCalledWith(
      "Generated summary from the completed response",
      expect.any(Uint8Array),
    );
    expect(mockChatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-1",
        encrypted_chat_summary:
          "encrypted:Generated summary from the completed response",
        encrypted_auto_speak_response: "encrypted:true",
      }),
    );
    expect(mockSendPostProcessingMetadata).toHaveBeenCalledWith(
      service,
      "chat-1",
      "",
      [],
      "encrypted:Generated summary from the completed response",
      "",
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

  // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("treats a hashed-chat server broadcast as a refresh hint, without another v1 write", async () => {
    const embedId = "broadcast-parent-1";
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;

    await handleEmbedUpdateImpl(service, {
      type: "embed_update", event_for_client: "embed_update", embed_id: embedId,
      chat_id: "a".repeat(64), message_id: "", user_id_uuid: "",
      user_id_hash: "", status: "finished", child_embed_ids: ["child-1"],
    });

    expect(mockEmbedStore.get).not.toHaveBeenCalled();
    expect(mockEmbedStore.removeFromMemoryCache).toHaveBeenCalledWith(`embed:${embedId}`);
    expect(mockSendStoreEmbed).not.toHaveBeenCalled();
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({
      type: "embedUpdated", detail: expect.objectContaining({ embed_id: embedId, status: "finished" }),
    }));
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

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("does not recipher a parent whose finished v1 head was already acknowledged", async () => {
    const embedId = "recovered-parent-1";
    const existingEmbed = {
      embed_id: embedId, status: "processing", version_number: 1,
      content: "app_id: images\nskill_id: generate\nstatus: finished\nresult_count: 1",
      chat_id: "chat-1", message_id: "message-1", embed_ids: ["child-1"],
    };
    mockEmbedStore.get.mockResolvedValue(existingEmbed);
    await withCanonicalEmbedWrite(embedId, async (lease) => {
      markAcknowledgedRecoveredEmbed(lease, "chat-1", 1);
    });
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;

    await handleEmbedUpdateImpl(service, {
      type: "embed_update", event_for_client: "embed_update", embed_id: embedId,
      chat_id: "chat-1", message_id: "message-1", user_id_uuid: "user-1",
      user_id_hash: "hashed-user-1", status: "finished", child_embed_ids: ["child-1"],
    });

    expect(mockEmbedStore.removeFromMemoryCache).toHaveBeenCalledWith(`embed:${embedId}`);
    expect(mockEmbedStore.putEncrypted).not.toHaveBeenCalled();
    expect(mockSendStoreEmbed).not.toHaveBeenCalled();
    expect(existingEmbed.status).toBe("processing");
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({
      type: "embedUpdated", detail: expect.objectContaining({ embed_id: embedId, status: "finished" }),
    }));
  });

  // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("allows a newer producer version to continue through the final-content wait", async () => {
    const embedId = "versioned-parent-1";
    const existingEmbed = {
      embed_id: embedId, status: "processing", version_number: 2,
      content: "app_id: images\nskill_id: generate\nstatus: processing",
      chat_id: "chat-1", message_id: "message-1", embed_ids: [] as string[],
    };
    mockEmbedStore.get.mockResolvedValue(existingEmbed);
    await withCanonicalEmbedWrite(embedId, async (lease) => {
      markAcknowledgedRecoveredEmbed(lease, "chat-1", 1);
    });
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;

    await handleEmbedUpdateImpl(service, {
      type: "embed_update", event_for_client: "embed_update", embed_id: embedId,
      chat_id: "chat-1", message_id: "message-1", user_id_uuid: "user-1",
      user_id_hash: "hashed-user-1", status: "finished", child_embed_ids: ["child-2"],
    });

    expect(existingEmbed.embed_ids).toEqual(["child-2"]);
    expect(existingEmbed.status).toBe("processing");
    expect(service.dispatchEvent).toHaveBeenCalledWith(expect.objectContaining({
      type: "embedUpdated", detail: expect.objectContaining({
        embed_id: embedId, isWaitingForContent: true,
      }),
    }));
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

  // contract-test: supporting surface=gui.web assertions=app-skills.media.application-screenshot,chats.persistence.client-encrypted
  it.each([["application", false], ["app_skill_use", true]] as const)("keeps referenced application files independent while %s composites preserve inheritance", async (type, inherited) => {
    const parentKey = new Uint8Array([4, 5, 6]);
    mockChatDB.getChat.mockResolvedValue({ chat_id: "chat-1" });
    mockChatKeyManager.getKeySync.mockReturnValue(new Uint8Array([1, 2, 3]));
    mockChatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mockDeriveEmbedKeyFromChatKey.mockResolvedValue(parentKey);
    mockEncryptWithEmbedKey.mockImplementation(async value => `encrypted:${value}`);
    mockWrapEmbedKeyWithChatKey.mockResolvedValue("wrapped-chat-key");
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    for (const version of [1, 2]) {
      clearProcessedEmbedsTracking();
      await handleSendEmbedDataImpl(service, { type: "send_embed_data", payload: {
        embed_id: "parent-fixture", type, chat_id: "chat-1", message_id: "message-1", user_id: "user-1",
        status: "finished", version_number: version, embed_ids: ["independent-file"],
        content: JSON.stringify({ type, app_id: inherited ? "images" : "code", skill_id: inherited ? "generate" : "application",
          status: "finished", file_refs: [{ embed_id: "independent-file", path: "index.html" }],
          ...(version === 2 ? { latest_screenshot: { files: { preview: { s3_key: "fixture" } } } } : {}) }),
      } } as unknown as Parameters<typeof handleSendEmbedDataImpl>[1], undefined, { localOnly: true });
      const inheritedCalls = mockEmbedStore.setEmbedKeyInCache.mock.calls.filter(([id]) => id === "independent-file");
      expect(inheritedCalls.length > 0).toBe(inherited);
      expect(mockEmbedStore.putEncrypted).toHaveBeenCalled();
    }
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted
  it("stores anonymous embeds locally without invoking remote persistence", async () => {
    const chatKey = new Uint8Array([1, 2, 3]);
    const embedKey = new Uint8Array([4, 5, 6]);
    mockChatDB.getChat.mockResolvedValue({ chat_id: "client-controlled-chat-id" });
    mockChatKeyManager.getKeySync.mockReturnValue(chatKey);
    mockChatKeyManager.getKey.mockResolvedValue(chatKey);
    mockDeriveEmbedKeyFromChatKey.mockResolvedValue(embedKey);
    mockEncryptWithEmbedKey.mockImplementation(async (value: string) => `encrypted:${value}`);
    mockWrapEmbedKeyWithChatKey.mockResolvedValue("wrapped-chat-key");
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;

    await handleSendEmbedDataImpl(service, {
      type: "send_embed_data",
      event_for_client: "send_embed_data",
      payload: {
        embed_id: "embed-1",
        type: "app_skill_use",
        content: "app_id: news\nskill_id: search\nstatus: finished",
        status: "finished",
        chat_id: "client-controlled-chat-id",
        message_id: "message-1",
        user_id: "anonymous-user-1",
      },
    } as unknown as Parameters<typeof handleSendEmbedDataImpl>[1], undefined, { localOnly: true });

    expect(mockEmbedStore.putEncrypted).toHaveBeenCalledWith(
      "embed:embed-1",
      expect.objectContaining({ encrypted_content: expect.any(String) }),
      "app_skill_use",
      expect.any(String),
      expect.objectContaining({ app_id: "news", skill_id: "search" }),
      expect.any(Object),
    );
    expect(mockWrapEmbedKeyWithMasterKey).not.toHaveBeenCalled();
    expect(mockSendStoreEmbed).not.toHaveBeenCalled();
    expect(mockSendStoreEmbedKeys).not.toHaveBeenCalled();
    expect(mockSendStoreEmbedDiff).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("keeps queued anonymous embeds local when the chat shell arrives later", async () => {
    vi.useFakeTimers();
    try {
      const chatKey = new Uint8Array([1, 2, 3]);
      const embedKey = new Uint8Array([4, 5, 6]);
      mockChatDB.getChat.mockResolvedValueOnce(null);
      mockChatDB.getChat.mockResolvedValue({
        chat_id: "client-controlled-chat-id",
        is_anonymous: true,
        anonymous_encrypted_chat_key: "session-wrapper",
      });
      mockChatKeyManager.getKeySync.mockReturnValue(chatKey);
      mockChatKeyManager.getKey.mockResolvedValue(chatKey);
      mockDeriveEmbedKeyFromChatKey.mockResolvedValue(embedKey);
      mockEncryptWithEmbedKey.mockImplementation(async (value: string) => `encrypted:${value}`);
      mockWrapEmbedKeyWithChatKey.mockResolvedValue("wrapped-chat-key");
      const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;

      await handleSendEmbedDataImpl(service, {
        type: "send_embed_data",
        payload: {
          embed_id: "embed-1",
          type: "app_skill_use",
          content: "app_id: web\nskill_id: search\nstatus: finished",
          status: "finished",
          chat_id: "client-controlled-chat-id",
          message_id: "message-1",
          user_id: "anonymous-user-1",
        },
      } as unknown as Parameters<typeof handleSendEmbedDataImpl>[1], undefined, { localOnly: true });

      expect(mockEmbedStore.putEncrypted).not.toHaveBeenCalled();
      await flushPendingFinalizedEmbedsForChat(service, "client-controlled-chat-id");

      expect(mockEmbedStore.putEncrypted).toHaveBeenCalledWith(
        "embed:embed-1",
        expect.objectContaining({ encrypted_content: expect.any(String) }),
        "app_skill_use",
        expect.any(String),
        expect.objectContaining({ app_id: "web", skill_id: "search" }),
        expect.any(Object),
      );
      expect(mockSendStoreEmbed).not.toHaveBeenCalled();
      expect(mockSendStoreEmbedKeys).not.toHaveBeenCalled();
      expect(mockWrapEmbedKeyWithMasterKey).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
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
      undefined,
      expect.objectContaining({ embedId: "child-1" }),
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
      expect.objectContaining({ keys: expect.arrayContaining([
        expect.objectContaining({ key_type: "master" }),
        expect.objectContaining({ key_type: "chat" }),
      ]) }),
      expect.objectContaining({ embedId: "embed-1" }),
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
      expect.objectContaining({ keys: expect.arrayContaining([
        expect.objectContaining({ key_type: "master" }),
        expect.objectContaining({ key_type: "chat" }),
      ]) }),
      expect.objectContaining({ embedId: "embed-1" }),
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
        expect.objectContaining({ keys: expect.arrayContaining([
          expect.objectContaining({ key_type: "master" }),
          expect.objectContaining({ key_type: "chat" }),
        ]) }),
        expect.objectContaining({ embedId: "embed-1" }),
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
        expect.objectContaining({ keys: expect.arrayContaining([
          expect.objectContaining({ key_type: "master" }),
          expect.objectContaining({ key_type: "chat" }),
        ]) }),
        expect.objectContaining({ embedId: "embed-1" }),
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

const legacyScope = vi.hoisted(() => ({ identity: "personal-a", epoch: 1 }));
import * as legacyWorkspace from "../workspaceQueryCache";
import * as legacyAccounts from "../connectedAccountStorageService";
import { reservePersonalChatTurn, bindPersonalChatTurn, awaitPersonalChatPredecessor, clearPersonalChatTurnBarriers } from "../personalChatTurnBarrier";

describe("legacy canonical ACK turn settlement", () => {
  const chat = { chat_id: "legacy-chat", messages_v: 2, updated_at: 1, last_edited_overall_timestamp: 1 };
  const assistant = { message_id: "legacy-assistant", chat_id: chat.chat_id, role: "assistant", user_message_id: "legacy-user" };
  const canonical = () => ({ chat_id: chat.chat_id, messages_v: 7, messages: [{ ...assistant, encrypted_content: "ciphertext" }] });
  const ack = { chat_id: chat.chat_id, message_id: assistant.message_id, task_id: "already_processed" };
  const service = { unmarkMessageSyncing: vi.fn(), dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
  let entered: ReturnType<typeof vi.fn>;
  let queued: Promise<unknown>;
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(legacyWorkspace, "getWorkspaceCacheIdentity").mockImplementation(() => legacyScope.identity);
    vi.spyOn(legacyAccounts, "getConnectedAccountMutationEpoch").mockImplementation(() => legacyScope.epoch);
    legacyScope.identity = "personal-a"; legacyScope.epoch = 1;
    mockChatDB.getMessage.mockResolvedValue(assistant);
    mockChatDB.getChat.mockResolvedValue({ ...chat });
    mockChatDB.updateChat.mockResolvedValue(undefined);
    mockChatListCache.getCache.mockReturnValue(null);
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => canonical() })));
    const first = reservePersonalChatTurn(chat.chat_id, assistant.user_message_id);
    bindPersonalChatTurn(first, "real-preflight-turn");
    entered = vi.fn();
    queued = awaitPersonalChatPredecessor(reservePersonalChatTurn(chat.chat_id, "next-user")).then(entered, () => undefined);
  });
  afterEach(async () => { clearPersonalChatTurnBarriers(); await queued; vi.unstubAllGlobals(); });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced,chats.message.identity-idempotent
  it("blocks the reserved follow-up until exact canonical persistence, then releases once with the server version", async () => {
    let finish!: (data: unknown) => void;
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: () => new Promise((resolve) => { finish = resolve; }) })));
    const handling = handleAIResponseStorageConfirmedImpl(service, ack);
    await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
    expect(entered).not.toHaveBeenCalled(); finish(canonical()); await handling; await queued;
    expect(mockChatDB.updateChat).toHaveBeenCalledWith(expect.objectContaining({ messages_v: 7 }));
    expect(mockChatListCache.upsertChat).toHaveBeenCalledWith(expect.objectContaining({ messages_v: 7 }));
    expect(entered).toHaveBeenCalledExactlyOnceWith(7);
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => canonical() })));
    await handleAIResponseStorageConfirmedImpl(service, ack);
    expect(entered).toHaveBeenCalledTimes(1);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it.each(["wrong-chat", "wrong-message", "missing-row", "empty-content", "wrong-role", "wrong-canonical-user", "bad-version", "failed-fetch", "failed-local-apply", "wrong-local-user", "wrong-local-chat", "stale-workspace", "stale-epoch"])("keeps the follow-up fenced on %s", async (failure) => {
    const data = canonical();
    if (failure === "wrong-chat") data.chat_id = "other";
    if (failure === "wrong-message") data.messages[0].message_id = "other";
    if (failure === "missing-row") data.messages = [];
    if (failure === "empty-content") data.messages[0].encrypted_content = "";
    if (failure === "wrong-role") data.messages[0].role = "user";
    if (failure === "wrong-canonical-user") data.messages[0].user_message_id = "other";
    if (failure === "bad-version") data.messages_v = -1;
    if (failure === "failed-local-apply") mockChatDB.updateChat.mockRejectedValueOnce(new Error("local write failed"));
    if (failure === "wrong-local-user") mockChatDB.getMessage.mockResolvedValue({ ...assistant, user_message_id: "other" });
    if (failure === "wrong-local-chat") mockChatDB.getMessage.mockResolvedValue({ ...assistant, chat_id: "other" });
    vi.stubGlobal("fetch", vi.fn(async () => {
      if (failure === "failed-fetch") throw new Error("network unavailable");
      if (failure === "stale-workspace") legacyScope.identity = "personal-b";
      if (failure === "stale-epoch") legacyScope.epoch++;
      return { ok: true, json: async () => data };
    }));
    await handleAIResponseStorageConfirmedImpl(service, ack); await Promise.resolve();
    expect(entered).not.toHaveBeenCalled();
    if (failure !== "failed-local-apply") expect(mockChatDB.updateChat).not.toHaveBeenCalled();
    if (!["wrong-local-chat", "stale-workspace", "stale-epoch"].includes(failure)) {
      expect(mockPendingAIResponses.add).toHaveBeenCalledWith(ack.message_id, ack.chat_id);
      expect(mockPendingAIResponses.remove).not.toHaveBeenCalled();
      expect(service.dispatchEvent).not.toHaveBeenCalledWith(expect.objectContaining({ type: "aiResponseStorageConfirmed" }));
    }
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("preserves later call DB/cache versions while releasing the server fence", async () => {
    mockChatDB.getChat.mockResolvedValueOnce({ ...chat }).mockResolvedValue({ ...chat, messages_v: 12 });
    mockChatListCache.getCache.mockReturnValue([{ ...chat, messages_v: 14 }]);
    await handleAIResponseStorageConfirmedImpl(service, ack); await queued;
    expect(mockChatDB.updateChat).toHaveBeenCalledWith(expect.objectContaining({ messages_v: 12 }));
    expect(mockChatListCache.upsertChat).toHaveBeenCalledWith(expect.objectContaining({ messages_v: 14 }));
    expect(entered).toHaveBeenCalledExactlyOnceWith(7);
  });
});
