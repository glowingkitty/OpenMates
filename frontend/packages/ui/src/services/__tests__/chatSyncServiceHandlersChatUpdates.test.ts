// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersChatUpdates.test.ts
// Regression coverage for cross-device chat update handlers.
// New-chat shells created from websocket broadcasts must carry the local user
// owner ID so sealed completion recovery can derive and validate envelopes.
// The test keeps encryption and database collaborators mocked to isolate the
// broadcast-to-shell metadata contract.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";
import {
  handleChatDraftUpdatedImpl,
  handleEncryptedChatMetadataImpl,
  handleChatMessageReceivedImpl,
  handleNewChatMessageImpl,
} from "../chatSyncServiceHandlersChatUpdates";

const mocks = vi.hoisted(() => ({
  chatDB: {
    getChat: vi.fn(),
    getRawChat: vi.fn(),
    upsertRawChat: vi.fn(),
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
    markDirty: vi.fn(),
  },
  chatKeyManager: {
    getKeySync: vi.fn(),
    receiveKeyFromServer: vi.fn(),
    withKey: vi.fn(),
  },
  activeChatStore: {
    get: vi.fn(),
  },
  notificationStore: {
    chatMessage: vi.fn(),
  },
  unreadMessagesStore: {
    incrementUnread: vi.fn(),
  },
  incognitoChatService: {
    getChat: vi.fn(),
    addMessage: vi.fn(),
    updateChat: vi.fn(),
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
vi.mock("../../stores/activeChatStore", () => ({
  activeChatStore: mocks.activeChatStore,
}));
vi.mock("../../stores/notificationStore", () => ({
  notificationStore: mocks.notificationStore,
}));
vi.mock("../../stores/unreadMessagesStore", () => ({
  unreadMessagesStore: mocks.unreadMessagesStore,
}));
vi.mock("../incognitoChatService", () => ({
  incognitoChatService: mocks.incognitoChatService,
}));

function setWindowHash(hash: string): void {
  if (!window.location) {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { hash },
      writable: true,
    });
    return;
  }

  window.location.hash = hash;
}

describe("handleNewChatMessageImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.chatDB.getChat.mockResolvedValue(undefined);
    mocks.chatDB.getRawChat.mockResolvedValue(undefined);
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
    mocks.activeChatStore.get.mockReturnValue(null);
    mocks.incognitoChatService.getChat.mockResolvedValue(null);
    setWindowHash("");
  });

  it("stores the current user id on new chat shells created from sync broadcasts", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    mocks.chatKeyManager.receiveKeyFromServer.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mocks.decryptWithChatKey.mockResolvedValue("Synced chat");

    await handleNewChatMessageImpl(service, {
      chat_id: "chat-1",
      message_id: "message-1",
      content: "Hello from another device",
      role: "user",
      messages_v: 1,
      created_at: 100,
      last_edited_overall_timestamp: 100,
      encrypted_chat_key: "encrypted-chat-key",
      encrypted_title: "encrypted-title",
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
    expect(mocks.chatDB.addChat.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.flushPendingSystemMessagesForChat.mock.invocationCallOrder[0],
    );
  });
});

describe("handleEncryptedChatMetadataImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.chatDB.getChat.mockResolvedValue(null);
    mocks.chatDB.addChat.mockResolvedValue(undefined);
    mocks.chatDB.updateChat.mockResolvedValue(undefined);
    mocks.userDB.getUserProfile.mockResolvedValue({ user_id: "user-1" });
    mocks.chatKeyManager.getKeySync.mockReturnValue(null);
    mocks.chatKeyManager.receiveKeyFromServer.mockResolvedValue(
      new Uint8Array([1, 2, 3]),
    );
    mocks.chatKeyManager.withKey.mockImplementation(
      async (
        _chatId: string,
        _reason: string,
        callback: (key: Uint8Array) => Promise<void>,
      ) => {
        await callback(new Uint8Array([1, 2, 3]));
      },
    );
  });

  it("creates a synced metadata-only shell when metadata arrives before the chat row", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    const chatHiddenListener = vi.fn();
    const windowChatUpdatedListener = vi.fn();
    window.addEventListener("chatHidden", chatHiddenListener);
    window.addEventListener("chatUpdated", windowChatUpdatedListener);

    try {
      await handleEncryptedChatMetadataImpl(service, {
        chat_id: "chat-metadata-only",
        encrypted_chat_key: "encrypted-chat-key",
        encrypted_title: "encrypted-title",
        encrypted_chat_summary: "encrypted-summary",
        encrypted_chat_category: "encrypted-category",
        encrypted_icon: "encrypted-icon",
        versions: {
          messages_v: 1,
          title_v: 2,
          metadata_v: 3,
          draft_v: 0,
        },
      });
    } finally {
      window.removeEventListener("chatHidden", chatHiddenListener);
      window.removeEventListener("chatUpdated", windowChatUpdatedListener);
    }

    expect(mocks.chatKeyManager.receiveKeyFromServer).toHaveBeenCalledWith(
      "chat-metadata-only",
      "encrypted-chat-key",
    );
    expect(mocks.chatDB.addChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-metadata-only",
        user_id: "user-1",
        encrypted_chat_key: "encrypted-chat-key",
        encrypted_title: "encrypted-title",
        encrypted_chat_summary: "encrypted-summary",
        encrypted_category: "encrypted-category",
        encrypted_icon: "encrypted-icon",
        messages_v: 1,
        title_v: 2,
        metadata_v: 3,
        is_metadata_only: true,
      }),
      undefined,
      { isFromSync: true },
    );
    expect(mocks.chatDB.updateChat).not.toHaveBeenCalled();
    expect(mocks.chatListCache.markDirty).toHaveBeenCalled();
    expect(mocks.chatMetadataCache.invalidateChat).toHaveBeenCalledWith("chat-metadata-only");
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: expect.objectContaining({
          chat_id: "chat-metadata-only",
          type: "metadata_updated",
        }),
      }),
    );
    expect(windowChatUpdatedListener).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: expect.objectContaining({
          chat_id: "chat-metadata-only",
          type: "metadata_updated",
        }),
      }),
    );
    expect(chatHiddenListener).not.toHaveBeenCalled();
  });

  it("merges summary broadcasts at the current metadata revision", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    mocks.chatDB.getChat.mockResolvedValue({
      chat_id: "chat-existing",
      encrypted_title: "encrypted-title",
      encrypted_chat_summary: "old-summary",
      encrypted_chat_key: "encrypted-chat-key",
      messages_v: 1,
      title_v: 2,
      metadata_v: 3,
      draft_v: 0,
      last_edited_overall_timestamp: 100,
      unread_count: 0,
      created_at: 100,
      updated_at: 100,
    });
    mocks.chatKeyManager.getKeySync.mockReturnValue(new Uint8Array([1, 2, 3]));
    mocks.decryptWithChatKey.mockResolvedValue("decrypts");

    await handleEncryptedChatMetadataImpl(service, {
      chat_id: "chat-existing",
      encrypted_chat_summary: "new-summary",
      versions: {
        messages_v: 1,
        title_v: 2,
        metadata_v: 3,
        draft_v: 0,
      },
    });

    expect(mocks.chatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-existing",
        encrypted_chat_summary: "new-summary",
        metadata_v: 3,
      }),
    );
    expect(mocks.chatDB.addChat).not.toHaveBeenCalled();
  });
});

describe("handleChatDraftUpdatedImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.chatDB.getChat.mockResolvedValue(undefined);
    mocks.chatDB.addChat.mockResolvedValue(undefined);
    mocks.chatDB.upsertRawChat.mockResolvedValue(undefined);
    mocks.chatDB.updateChat.mockResolvedValue(undefined);
  });

  it("stores IdeaBucket metadata on draft-only chats created from sync broadcasts", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    mocks.chatDB.getChat.mockRejectedValue(new Error("decrypted getChat must not run"));

    await handleChatDraftUpdatedImpl(service, {
      event: "chat_draft_updated",
      chat_id: "chat-ideabucket",
      data: {
        encrypted_draft_md: "encrypted-draft",
        encrypted_draft_preview: "encrypted-preview",
        ideabucket: true,
        ideabucket_processing_window_id: "bucket-1",
      },
      versions: { draft_v: 1 },
      last_edited_overall_timestamp: 100,
    });

    expect(mocks.chatDB.getChat).not.toHaveBeenCalled();
    expect(mocks.chatDB.getRawChat).toHaveBeenCalledWith("chat-ideabucket");
    expect(mocks.chatDB.upsertRawChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-ideabucket",
        ideabucket: true,
        ideabucket_processing_window_id: "bucket-1",
      }),
    );
    expect(mocks.chatListCache.upsertChat).toHaveBeenCalledWith(
      expect.objectContaining({ chat_id: "chat-ideabucket" }),
    );
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        detail: expect.objectContaining({
          chat_id: "chat-ideabucket",
          type: "draft",
          chat: expect.objectContaining({ chat_id: "chat-ideabucket" }),
        }),
      }),
    );
  });

  it("updates existing draft chats from raw metadata without creating replacement keys", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    mocks.chatDB.getRawChat.mockResolvedValue({
      chat_id: "chat-existing-draft",
      encrypted_title: null,
      encrypted_draft_md: "old-draft",
      encrypted_draft_preview: "old-preview",
      messages_v: 0,
      title_v: 0,
      draft_v: 1,
      unread_count: 0,
      created_at: 90,
      updated_at: 90,
      last_edited_overall_timestamp: 90,
    });

    await handleChatDraftUpdatedImpl(service, {
      event: "chat_draft_updated",
      chat_id: "chat-existing-draft",
      data: {
        encrypted_draft_md: "new-draft",
        encrypted_draft_preview: "new-preview",
      },
      versions: { draft_v: 2 },
      last_edited_overall_timestamp: 100,
    });

    expect(mocks.chatDB.updateChat).not.toHaveBeenCalled();
    expect(mocks.chatDB.upsertRawChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-existing-draft",
        encrypted_draft_md: "new-draft",
        encrypted_draft_preview: "new-preview",
        draft_v: 2,
      }),
    );
  });

  it("ignores stale draft broadcasts when local draft version is newer", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    mocks.chatDB.getRawChat.mockResolvedValue({
      chat_id: "chat-existing-draft",
      encrypted_title: null,
      encrypted_draft_md: "newer-local-draft",
      encrypted_draft_preview: "newer-local-preview",
      messages_v: 0,
      title_v: 0,
      draft_v: 3,
      unread_count: 0,
      created_at: 90,
      updated_at: 90,
      last_edited_overall_timestamp: 90,
    });

    await handleChatDraftUpdatedImpl(service, {
      event: "chat_draft_updated",
      chat_id: "chat-existing-draft",
      data: {
        encrypted_draft_md: "stale-remote-draft",
        encrypted_draft_preview: "stale-remote-preview",
      },
      versions: { draft_v: 2 },
      last_edited_overall_timestamp: 100,
    });

    expect(mocks.chatDB.upsertRawChat).not.toHaveBeenCalled();
    expect(mocks.chatMetadataCache.invalidateChat).not.toHaveBeenCalled();
    expect(mocks.chatListCache.upsertChat).not.toHaveBeenCalled();
    expect(service.dispatchEvent).not.toHaveBeenCalled();
  });
});

describe("handleChatMessageReceivedImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.chatDB.saveMessage.mockResolvedValue(undefined);
    mocks.chatDB.updateChat.mockResolvedValue(undefined);
    mocks.chatKeyManager.getKeySync.mockReturnValue(new Uint8Array([1, 2, 3]));
    mocks.incognitoChatService.getChat.mockResolvedValue(null);
    setWindowHash("");
  });

  it("notifies for assistant broadcasts when the visible chat is different from stale active state", async () => {
    const chat = {
      chat_id: "chat-a",
      title: "Chat A",
      category: "science",
      messages_v: 1,
      last_edited_overall_timestamp: 100,
      updated_at: 100,
    };
    mocks.chatDB.getChat.mockResolvedValue(chat);
    mocks.activeChatStore.get.mockReturnValue("chat-a");
    setWindowHash("#chat-id=chat-b");
    const service = {
      activeAITasks: new Map([["chat-a", { taskId: "assistant-1" }]]),
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleChatMessageReceivedImpl(service, {
      event: "chat_message_added",
      chat_id: "chat-a",
      message: {
        message_id: "assistant-1",
        chat_id: "chat-a",
        role: "assistant",
        content: "# Hello **world** [link](https://example.com)",
        status: "synced",
        created_at: 100,
        encrypted_content: "",
      },
      versions: { messages_v: 2 },
      last_edited_overall_timestamp: 101,
    });

    expect(mocks.chatDB.saveMessage).toHaveBeenCalledWith(
      expect.objectContaining({ message_id: "assistant-1", role: "assistant" }),
    );
    expect(mocks.unreadMessagesStore.incrementUnread).toHaveBeenCalledWith("chat-a");
    expect(mocks.notificationStore.chatMessage).toHaveBeenCalledWith(
      "chat-a",
      "Chat A",
      "Hello world link",
      undefined,
      "science",
    );
  });

  it("clears draft-only shell fields when a synced message arrives", async () => {
    const chat = {
      chat_id: "chat-ideabucket-processed",
      encrypted_title: null,
      encrypted_draft_md: "stale-draft",
      encrypted_draft_preview: "stale-preview",
      messages_v: 0,
      title_v: 0,
      draft_v: 1,
      last_edited_overall_timestamp: 100,
      updated_at: 100,
    };
    mocks.chatDB.getChat.mockResolvedValue(chat);
    mocks.activeChatStore.get.mockReturnValue(null);
    const service = {
      activeAITasks: new Map(),
      dispatchEvent: vi.fn(),
    } as unknown as ChatSynchronizationService;

    await handleChatMessageReceivedImpl(service, {
      event: "chat_message_added",
      chat_id: "chat-ideabucket-processed",
      message: {
        message_id: "message-1",
        chat_id: "chat-ideabucket-processed",
        role: "user",
        content: "Processed IdeaBucket text",
        status: "synced",
        created_at: 100,
        encrypted_content: "",
      },
      versions: { messages_v: 1 },
      last_edited_overall_timestamp: 101,
    });

    expect(mocks.chatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-ideabucket-processed",
        encrypted_draft_md: null,
        encrypted_draft_preview: null,
        draft_v: 0,
        messages_v: 1,
      }),
    );
    expect(mocks.chatMetadataCache.invalidateChat).toHaveBeenCalledWith(
      "chat-ideabucket-processed",
    );
    expect(mocks.chatListCache.markDirty).toHaveBeenCalled();
  });
});
