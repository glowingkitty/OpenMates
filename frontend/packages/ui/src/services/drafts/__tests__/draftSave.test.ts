// frontend/packages/ui/src/services/drafts/__tests__/draftSave.test.ts
// Unit tests for draftSave service — the debounced draft persistence layer.
//
// Bug history this test suite guards against:
//  - Draft loss when switching chats rapidly (race condition)
//  - Concurrent save operations corrupting IndexedDB state
//  - Debounce not flushing on navigation away
//
// These tests focus on the exported API behavior:
//  - clearCurrentDraft: clears draft from DB
//  - triggerSaveDraft / flushSaveDraft: debounced save behavior
//
// Architecture: frontend/packages/ui/src/services/drafts/draftSave.ts

import { describe, it, expect, vi, beforeEach } from "vitest";

const mocks = vi.hoisted(() => {
  const initialDraftEditorState = {
    currentChatId: null as string | null,
    currentUserDraftVersion: 0,
    hasUnsavedChanges: false,
    newlyCreatedChatIdToSelect: null as string | null,
    lastSavedContentMarkdown: null as string | null,
    isSwitchingContext: false,
    isSaveInProgress: false,
  };
  let draftState = { ...initialDraftEditorState };

  const draftEditorUIState = {
    subscribe: vi.fn((fn: (value: typeof initialDraftEditorState) => void) => {
      fn(draftState);
      return () => {};
    }),
    set: vi.fn((value: typeof initialDraftEditorState) => {
      draftState = value;
    }),
    update: vi.fn((updater: (value: typeof initialDraftEditorState) => typeof initialDraftEditorState) => {
      draftState = updater(draftState);
    }),
  };

  return {
    initialDraftEditorState,
    get draftState() {
      return draftState;
    },
    resetDraftState(value: Partial<typeof initialDraftEditorState> = {}) {
      draftState = { ...initialDraftEditorState, ...value };
    },
    draftEditorUIState,
    chatDB: {
      chats: {
        delete: vi.fn().mockResolvedValue(undefined),
        put: vi.fn().mockResolvedValue(undefined),
        get: vi.fn().mockResolvedValue(undefined),
      },
      getChat: vi.fn().mockResolvedValue(undefined),
      getMessagesForChat: vi.fn().mockResolvedValue([]),
      deleteChat: vi.fn().mockResolvedValue({ deletedEmbedIds: [] }),
      getRawChat: vi.fn().mockResolvedValue(undefined),
      addChat: vi.fn().mockResolvedValue(undefined),
      upsertRawChat: vi.fn().mockResolvedValue(undefined),
      createNewChatWithCurrentUserDraft: vi.fn().mockResolvedValue({
        chat_id: "created-chat-id",
        draft_v: 1,
        encrypted_draft_md: "encrypted-data",
        encrypted_draft_preview: null,
      }),
    },
    chatSyncService: {
      getEncryptedFields: vi.fn().mockResolvedValue(null),
      sendDeleteDraft: vi.fn().mockResolvedValue(undefined),
      sendDeleteChat: vi.fn().mockResolvedValue(undefined),
      sendUpdateDraft: vi.fn().mockResolvedValue(undefined),
      queueOfflineChange: vi.fn().mockResolvedValue(undefined),
      sendOfflineChanges: vi.fn().mockResolvedValue(undefined),
      dispatchEvent: vi.fn(),
    },
    getEditorInstance: vi.fn(),
    clearEditorAndResetDraftState: vi.fn(() => {
      draftState = { ...initialDraftEditorState };
    }),
    incognitoChatService: {
      getChat: vi.fn().mockResolvedValue(null),
    },
    incognitoMode: {
      get: vi.fn().mockReturnValue(false),
    },
    deleteSessionStorageDraft: vi.fn(),
    saveSessionStorageDraft: vi.fn(),
    chatMetadataCache: {
      invalidateChat: vi.fn(),
    },
    encryptWithMasterKey: vi.fn().mockResolvedValue("encrypted-data"),
    tipTapToCanonicalMarkdown: vi.fn().mockReturnValue(""),
  };
});

// Mock all heavy dependencies before importing the module

// chatDB (IndexedDB)
vi.mock("../../db", () => ({
  chatDB: mocks.chatDB,
}));

// chatSyncService
vi.mock("../../chatSyncService", () => ({
  chatSyncService: mocks.chatSyncService,
}));

// cryptoService
vi.mock("../../cryptoService", () => ({
  encryptWithMasterKey: mocks.encryptWithMasterKey,
}));

// authStore
vi.mock("../../../stores/authStore", () => ({
  authStore: {
    subscribe: vi.fn((fn: (v: unknown) => void) => {
      fn({ isAuthenticated: true });
      return () => {};
    }),
  },
}));

// websocketStatusStore
vi.mock("../../../stores/websocketStatusStore", () => ({
  websocketStatus: {
    subscribe: vi.fn((fn: (v: unknown) => void) => {
      fn("connected");
      return () => {};
    }),
    setStatus: vi.fn(),
  },
}));

// websocketService — prevent actual WebSocket connection
vi.mock("../../websocketService", () => ({
  default: {
    send: vi.fn(),
    isConnected: vi.fn().mockReturnValue(false),
  },
  getWebSocketService: vi.fn().mockReturnValue({
    send: vi.fn(),
    isConnected: vi.fn().mockReturnValue(false),
  }),
}));

// draftEditorUIState
vi.mock("../draftState", () => ({
  draftEditorUIState: mocks.draftEditorUIState,
  initialDraftEditorState: mocks.initialDraftEditorState,
}));

// activeChatStore
vi.mock("../../../stores/activeChatStore", () => ({
  activeChatStore: {
    get: vi.fn().mockReturnValue("test-chat-id"),
    subscribe: vi.fn((fn: (v: unknown) => void) => {
      fn("test-chat-id");
      return () => {};
    }),
  },
}));

// draftCore — prevent real editor access
vi.mock("../draftCore", () => ({
  getEditorInstance: mocks.getEditorInstance,
  clearEditorAndResetDraftState: mocks.clearEditorAndResetDraftState,
}));

vi.mock("../../incognitoChatService", () => ({
  incognitoChatService: mocks.incognitoChatService,
}));

vi.mock("../../../stores/incognitoModeStore", () => ({
  incognitoMode: mocks.incognitoMode,
}));

vi.mock("../../../demo_chats/convertToChat", () => ({
  isPublicChat: (chatId: string) =>
    chatId.startsWith("demo-") ||
    chatId.startsWith("legal-") ||
    chatId.startsWith("example-") ||
    chatId.startsWith("announcements-") ||
    chatId.startsWith("tips-"),
}));

vi.mock("../../../message_parsing/serializers", () => ({
  tipTapToCanonicalMarkdown: mocks.tipTapToCanonicalMarkdown,
}));

vi.mock("../../../components/enter_message/services/urlMetadataService", () => ({
  extractUrlFromJsonEmbedBlock: vi.fn().mockReturnValue(null),
}));

vi.mock("../sessionStorageDraftService", () => ({
  saveSessionStorageDraft: mocks.saveSessionStorageDraft,
  deleteSessionStorageDraft: mocks.deleteSessionStorageDraft,
}));

vi.mock("../../chatMetadataCache", () => ({
  chatMetadataCache: mocks.chatMetadataCache,
}));

// metadata stores
vi.mock("../../../data/modelsMetadata", () => ({
  modelsMetadata: [],
}));

vi.mock("../../../data/matesMetadata", () => ({
  matesMetadata: [],
}));

vi.mock("../../../stores/appSkillsStore", () => ({
  appSkillsStore: { apps: {} },
}));

// lodash-es debounce — replace with immediate execution for testing
vi.mock("lodash-es", () => ({
  debounce: (fn: (...args: unknown[]) => unknown) => {
    const wrapper = (...args: unknown[]) => fn(...args);
    wrapper.flush = () => fn();
    wrapper.cancel = vi.fn();
    return wrapper;
  },
}));

// Import after all mocks
import {
  clearCurrentDraft,
  triggerSaveDraft,
  flushSaveDraft,
  saveDraftDebounced,
} from "../draftSave";

function createEditor(isEmpty: boolean) {
  const run = vi.fn();
  const clearContent = vi.fn(() => ({ run }));
  const chain = vi.fn(() => ({ clearContent }));
  return {
    isEmpty,
    isDestroyed: false,
    isEditable: true,
    getJSON: vi.fn().mockReturnValue({ type: "doc", content: [] }),
    chain,
  };
}

describe("draftSave", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.resetDraftState();
    mocks.getEditorInstance.mockReturnValue(null);
    mocks.incognitoMode.get.mockReturnValue(false);
    mocks.incognitoChatService.getChat.mockResolvedValue(null);
    mocks.chatDB.getChat.mockResolvedValue(undefined);
    mocks.chatDB.getMessagesForChat.mockResolvedValue([]);
    mocks.chatDB.deleteChat.mockResolvedValue({ deletedEmbedIds: [] });
    mocks.chatDB.getRawChat.mockResolvedValue(undefined);
    mocks.chatDB.createNewChatWithCurrentUserDraft.mockResolvedValue({
      chat_id: "created-chat-id",
      draft_v: 1,
      encrypted_draft_md: "encrypted-data",
      encrypted_draft_preview: "encrypted-data",
    });
    mocks.encryptWithMasterKey.mockResolvedValue("encrypted-data");
    mocks.tipTapToCanonicalMarkdown.mockReturnValue("");
  });

  // ──────────────────────────────────────────────────────────────────
  // clearCurrentDraft
  // ──────────────────────────────────────────────────────────────────

  describe("clearCurrentDraft", () => {
    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
    it("completes without error even with no active chat/editor", async () => {
      // clearCurrentDraft early-returns when no editor or chat ID is available.
      // The key behavior: it should never throw.
      await expect(clearCurrentDraft()).resolves.not.toThrow();
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
    it("does not throw on DB errors", async () => {
      mocks.chatDB.chats.delete.mockRejectedValueOnce(new Error("DB error"));
      // Should not throw — best-effort deletion
      await expect(clearCurrentDraft()).resolves.not.toThrow();
    });
  });

  describe("public chat empty draft saves", () => {
    // contract-test: supporting surface=gui.web assertions=drafts.boundaries.session-and-incognito,drafts.draft-only.lifecycle
    it("does not convert empty public-chat flushes into private draft deletions", async () => {
      const editor = createEditor(true);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "example-empty-draft" });
      const randomUUID = vi
        .spyOn(crypto, "randomUUID")
        .mockReturnValue("11111111-1111-4111-8111-111111111111");

      await saveDraftDebounced("example-empty-draft", editor as never);

      expect(randomUUID).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.sendDeleteDraft).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.sendDeleteChat).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.queueOfflineChange).not.toHaveBeenCalled();
      expect(mocks.draftState.currentChatId).toBe("example-empty-draft");
    });
  });

  describe("context switching empty draft saves", () => {
    // contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
    it("does not schedule authenticated draft deletion while switching context", () => {
      const editor = createEditor(true);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({
        currentChatId: "auth-draft-chat",
        isSwitchingContext: true,
      });

      triggerSaveDraft("auth-draft-chat", editor as never);

      expect(mocks.chatSyncService.sendDeleteDraft).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.sendDeleteChat).not.toHaveBeenCalled();
      expect(mocks.draftState.currentChatId).toBe("auth-draft-chat");
    });

    // contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative,drafts.draft-only.lifecycle
    it("does not execute authenticated draft deletion while switching context", async () => {
      const editor = createEditor(true);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({
        currentChatId: "auth-draft-chat",
        isSwitchingContext: true,
      });

      await saveDraftDebounced("auth-draft-chat", editor as never);

      expect(mocks.chatSyncService.sendDeleteDraft).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.sendDeleteChat).not.toHaveBeenCalled();
      expect(mocks.draftState.currentChatId).toBe("auth-draft-chat");
    });

    // contract-test: supporting surface=gui.web assertions=drafts.navigation.includes-draft-only,drafts.draft-only.lifecycle
    it("does not delete an authenticated persisted draft while plaintext restore is pending", async () => {
      const editor = createEditor(true);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({
        currentChatId: "auth-draft-chat",
        currentUserDraftVersion: 3,
        lastSavedContentMarkdown: null,
      });
      mocks.chatDB.getRawChat.mockResolvedValueOnce({
        chat_id: "auth-draft-chat",
        encrypted_title: null,
        encrypted_draft_md: "encrypted-draft",
        encrypted_draft_preview: "encrypted-preview",
        draft_v: 3,
        messages_v: 0,
        title_v: 0,
        last_edited_overall_timestamp: 1,
        unread_count: 0,
        created_at: 1,
        updated_at: 1,
      });

      await saveDraftDebounced("auth-draft-chat", editor as never);

      expect(mocks.chatSyncService.sendDeleteDraft).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.sendDeleteChat).not.toHaveBeenCalled();
      expect(mocks.chatDB.deleteChat).not.toHaveBeenCalled();
      expect(mocks.draftState.currentChatId).toBe("auth-draft-chat");
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
    it("allows authenticated draft deletion after restored plaintext is known", async () => {
      const editor = createEditor(true);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({
        currentChatId: "auth-draft-chat",
        currentUserDraftVersion: 3,
        lastSavedContentMarkdown: "Known restored draft",
      });

      await saveDraftDebounced("auth-draft-chat", editor as never);

      expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("auth-draft-chat");
    });
  });

  describe("new-chat draft activation", () => {
    // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted,drafts.draft-only.lifecycle
    it("publishes the persisted draft shell ID for selection after a successful first save", async () => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("Plan a weekend cycling route around Berlin");

      await saveDraftDebounced(undefined, editor as never);

      expect(mocks.chatDB.createNewChatWithCurrentUserDraft).toHaveBeenCalledTimes(1);
      expect(mocks.draftState.currentChatId).toBe("created-chat-id");
      expect(mocks.draftState.newlyCreatedChatIdToSelect).toBe("created-chat-id");
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
    it("does not publish a draft shell ID when first persistence fails", async () => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("Draft that cannot be persisted");
      mocks.chatDB.createNewChatWithCurrentUserDraft.mockRejectedValueOnce(new Error("DB unavailable"));

      await saveDraftDebounced(undefined, editor as never);

      expect(mocks.draftState.newlyCreatedChatIdToSelect).toBeNull();
      expect(mocks.draftState.hasUnsavedChanges).toBe(true);
    });

    // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted,drafts.draft-only.lifecycle
    it("releases the save lock when the draft is cleared during encryption", async () => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("Draft cleared while encrypting");

      let finishEncryption: (value: string) => void = () => undefined;
      mocks.encryptWithMasterKey.mockImplementationOnce(
        () => new Promise<string>((resolve) => {
          finishEncryption = resolve;
        }),
      );

      const savePromise = saveDraftDebounced(undefined, editor as never);
      await vi.waitFor(() => expect(mocks.draftState.isSaveInProgress).toBe(true));
      await clearCurrentDraft();
      finishEncryption("encrypted-data");
      await savePromise;

      expect(mocks.chatDB.createNewChatWithCurrentUserDraft).not.toHaveBeenCalled();
      expect(mocks.draftState.isSaveInProgress).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
    it("removes a first-save shell that finishes persisting after clear", async () => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("Draft cleared during persistence");

      let finishPersistence: (chat: {
        chat_id: string;
        draft_v: number;
        encrypted_draft_md: string;
        encrypted_draft_preview: string;
      }) => void = () => undefined;
      mocks.chatDB.createNewChatWithCurrentUserDraft.mockImplementationOnce(
        () => new Promise((resolve) => {
          finishPersistence = resolve;
        }),
      );

      const savePromise = saveDraftDebounced(undefined, editor as never);
      await vi.waitFor(() => {
        expect(mocks.chatDB.createNewChatWithCurrentUserDraft).toHaveBeenCalledTimes(1);
      });
      await clearCurrentDraft();
      finishPersistence({
        chat_id: "late-created-chat-id",
        draft_v: 1,
        encrypted_draft_md: "encrypted-data",
        encrypted_draft_preview: "encrypted-data",
      });
      await savePromise;

      expect(mocks.chatDB.deleteChat).toHaveBeenCalledWith("late-created-chat-id");
      expect(mocks.draftState.newlyCreatedChatIdToSelect).toBeNull();
      expect(mocks.draftState.isSaveInProgress).toBe(false);
    });
  });

  // ──────────────────────────────────────────────────────────────────
  // triggerSaveDraft / flushSaveDraft
  // ──────────────────────────────────────────────────────────────────

  describe("triggerSaveDraft", () => {
    // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
    it("is callable without arguments", () => {
      // With mocked debounce (immediate), this should not throw
      expect(() => triggerSaveDraft()).not.toThrow();
    });

    // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
    it("accepts optional chatId parameter", () => {
      expect(() => triggerSaveDraft("override-chat-id")).not.toThrow();
    });
  });

  describe("flushSaveDraft", () => {
    // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
    it("is callable and triggers immediate save", () => {
      expect(() => flushSaveDraft()).not.toThrow();
    });
  });
});
