// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersCoreSync.test.ts
// Regression coverage for Phase 1a sync metadata handling.
// Phase 1a must use the shared merge policy so partial server/cache payloads
// cannot overwrite locally valid encrypted chat header metadata with nulls.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";
import { handlePhase1LastChatImpl } from "../chatSyncServiceHandlersCoreSync";

const mocks = vi.hoisted(() => ({
  existingChat: {
    chat_id: "chat-1",
    encrypted_title: "local-encrypted-title",
    encrypted_icon: "local-encrypted-icon",
    encrypted_category: "local-encrypted-category",
    encrypted_chat_key: "same-key",
    messages_v: 4,
    title_v: 1,
    draft_v: 0,
    unread_count: 0,
    created_at: 100,
    updated_at: 200,
    last_edited_overall_timestamp: 200,
  },
  chatDB: {
    init: vi.fn(),
    getChat: vi.fn(),
    addChat: vi.fn(),
    saveEncryptedNewChatSuggestions: vi.fn(),
  },
  userDB: {
    getUserProfile: vi.fn(),
  },
  chatListCache: {
    upsertChat: vi.fn(),
  },
  chatKeyManager: {
    getKey: vi.fn(),
    receiveKeyFromServer: vi.fn(),
    acceptServerKeyForMismatch: vi.fn(),
    removeKey: vi.fn(),
  },
  decryptWithChatKey: vi.fn(),
  phasedSyncState: {
    setRecentChats: vi.fn(),
    setResumeChatData: vi.fn(),
  },
  dailyInspirationStore: {
    markPhase1Empty: vi.fn(),
    setInspirations: vi.fn(),
  },
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../userDB", () => ({ userDB: mocks.userDB }));
vi.mock("../chatListCache", () => ({ chatListCache: mocks.chatListCache }));
vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: mocks.chatKeyManager,
}));
vi.mock("../encryption/MessageEncryptor", () => ({
  decryptWithChatKey: mocks.decryptWithChatKey,
}));
vi.mock("../../stores/phasedSyncStateStore", () => ({
  phasedSyncState: mocks.phasedSyncState,
}));
vi.mock("../../stores/dailyInspirationStore", () => ({
  dailyInspirationStore: mocks.dailyInspirationStore,
}));
vi.mock("../../stores/notificationStore", () => ({
  notificationStore: { error: vi.fn() },
}));
vi.mock("../../stores/activeChatStore", () => ({
  activeChatStore: { get: vi.fn(() => null) },
}));

describe("handlePhase1LastChatImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.chatDB.getChat.mockResolvedValue(mocks.existingChat);
    mocks.userDB.getUserProfile.mockResolvedValue({ user_id: "user-1" });
    mocks.chatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mocks.decryptWithChatKey.mockImplementation(async (ciphertext: string) => {
      if (ciphertext === "local-encrypted-title") return "Recovered title";
      if (ciphertext === "local-encrypted-icon") return "code";
      if (ciphertext === "local-encrypted-category") return "software";
      return null;
    });
  });

  it("preserves local encrypted header metadata when Phase 1a payload is partial", async () => {
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;

    await handlePhase1LastChatImpl(service, {
      chat_id: "chat-1",
      chat_details: {
        encrypted_title: null,
        encrypted_icon: null,
        encrypted_category: null,
        encrypted_chat_key: "same-key",
        messages_v: 4,
        title_v: 0,
      },
      messages: null,
      recent_chat_metadata: [],
      phase: "phase1",
    });

    expect(mocks.chatDB.addChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "chat-1",
        encrypted_title: "local-encrypted-title",
        encrypted_icon: "local-encrypted-icon",
        encrypted_category: "local-encrypted-category",
      }),
      undefined,
      { isFromSync: true, forceIncomingEncryptedChatKey: false },
    );
    expect(mocks.phasedSyncState.setResumeChatData).toHaveBeenCalledWith(
      expect.objectContaining({ chat_id: "chat-1" }),
      "Recovered title",
      "software",
      "code",
      true,
    );
  });
});
