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
import { inspectDraftContent } from "../draftContent";
import { activeTeamContext } from "../../../stores/teamStore";

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
  const draftSubscribers = new Set<(value: typeof initialDraftEditorState) => void>();
  let accountId = "draft-test-user";
  const profileSubscribers = new Set<(value: { user_id: string }) => void>();

  const draftEditorUIState = {
    subscribe: vi.fn((fn: (value: typeof initialDraftEditorState) => void) => {
      draftSubscribers.add(fn);
      fn(draftState);
      return () => { draftSubscribers.delete(fn); };
    }),
    set: vi.fn((value: typeof initialDraftEditorState) => {
      draftState = value;
      draftSubscribers.forEach((fn) => fn(draftState));
    }),
    update: vi.fn((updater: (value: typeof initialDraftEditorState) => typeof initialDraftEditorState) => {
      draftState = updater(draftState);
      draftSubscribers.forEach((fn) => fn(draftState));
    }),
  };

  return {
    profileSubscribe: vi.fn((fn: (value: { user_id: string }) => void) => {
      profileSubscribers.add(fn);
      fn({ user_id: accountId });
      return () => { profileSubscribers.delete(fn); };
    }),
    setAccountId(next: string) {
      accountId = next;
      profileSubscribers.forEach(fn => fn({ user_id: accountId }));
    },
    initialDraftEditorState,
    get draftState() {
      return draftState;
    },
    resetDraftState(value: Partial<typeof initialDraftEditorState> = {}) {
      draftState = { ...initialDraftEditorState, ...value };
      draftSubscribers.forEach((fn) => fn(draftState));
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
      deleteDraftOnlyChat: vi.fn().mockResolvedValue({ deleted: true, deletedEmbedIds: [] }),
      deleteChat: vi.fn().mockResolvedValue({ deletedEmbedIds: [] }),
      getRawChat: vi.fn().mockResolvedValue(undefined),
      addChat: vi.fn().mockResolvedValue(undefined),
      saveChatDraftFields: vi.fn(async (chatId, fields) => ({ chat_id: chatId, ...fields })),
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
      invalidateChat: vi.fn(), invalidateDraftProjection: vi.fn(),
    },
    encryptWithMasterKey: vi.fn().mockResolvedValue("encrypted-data"),
    tipTapToCanonicalMarkdown: vi.fn().mockReturnValue(""),
    deferDebounce: false,
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

vi.mock("../../../stores/userProfile", () => ({
  userProfile: {
    subscribe: mocks.profileSubscribe,
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

// lodash-es debounce — immediate by default, with a controllable pending call
// for the recording race that begins before capture.
vi.mock("lodash-es", () => ({
  debounce: (fn: (...args: unknown[]) => unknown) => {
    let lastResult: unknown;
    let pendingArgs: unknown[] | null = null;
    const wrapper = (...args: unknown[]) => {
      if (mocks.deferDebounce) {
        pendingArgs = args;
        return;
      }
      lastResult = fn(...args);
      return lastResult;
    };
    wrapper.flush = () => {
      if (pendingArgs) {
        const args = pendingArgs;
        pendingArgs = null;
        lastResult = fn(...args);
      }
      return lastResult;
    };
    wrapper.cancel = vi.fn(() => { pendingArgs = null; });
    return wrapper;
  },
}));

// Import after all mocks
import {
  clearCurrentDraft,
  triggerSaveDraft,
  flushSaveDraft,
  flushSaveDraftAndWaitForIdle,
  saveDraftDebounced,
  protectEmptyRecordingDraft,
} from "../draftSave";

function createEditor(isEmpty: boolean) {
  const run = vi.fn();
  const clearContent = vi.fn(() => ({ run }));
  const chain = vi.fn(() => ({ clearContent }));
  return {
    isEmpty,
    isDestroyed: false,
    isEditable: true,
    state: { doc: { type: "doc" } },
    getJSON: vi.fn().mockReturnValue(isEmpty
      ? { type: "doc", content: [] }
      : { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "draft" }] }] }),
    chain,
  };
}

describe("draftSave", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.setAccountId("draft-test-user");
    mocks.deferDebounce = false;
    activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
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
    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle,teams.context.full-switch-local
    it("preserves a committed Team chat when its local message window is empty", async () => {
      const editor = createEditor(true);
      activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "team-chat" });
      mocks.chatDB.getChat.mockResolvedValue({ chat_id: "team-chat", team_id: "team-1", messages_v: 1, draft_v: 0 });
      mocks.chatDB.getMessagesForChat.mockResolvedValue([]);

      await clearCurrentDraft();

      expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("team-chat");
      expect(mocks.chatDB.deleteDraftOnlyChat).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.sendDeleteChat).not.toHaveBeenCalled();
    });
    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle,teams.context.full-switch-local
    it("does not delete a newer same-chat draft with identical content after send", async () => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "team-chat", hasUnsavedChanges: true });
      const submittedDoc = editor.state.doc;
      editor.state.doc = { type: "doc" }; // Same content, new immutable ProseMirror document.

      await clearCurrentDraft({
        editor: editor as never,
        document: submittedDoc as never,
        chatId: "team-chat",
      });

      expect(mocks.chatSyncService.sendDeleteDraft).not.toHaveBeenCalled();
      expect(editor.chain).not.toHaveBeenCalled();
      expect(mocks.draftState.hasUnsavedChanges).toBe(true);
    });
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

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle,teams.context.full-switch-local
    it("preserves newer text typed while a sent draft deletion is delayed", async () => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "team-chat", hasUnsavedChanges: true });
      mocks.chatDB.getChat.mockResolvedValue({ chat_id: "team-chat" });
      mocks.chatDB.getMessagesForChat.mockResolvedValue([{ message_id: "sent-message" }]);

      let finishDeletion!: () => void;
      mocks.chatSyncService.sendDeleteDraft.mockImplementationOnce(() => new Promise<void>((resolve) => {
        finishDeletion = resolve;
      }));
      const clearing = clearCurrentDraft();
      await vi.waitFor(() => expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("team-chat"));

      editor.getJSON.mockReturnValue({
        type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "new message" }] }],
      });
      editor.state.doc = { type: "newer doc" };
      finishDeletion();
      await clearing;

      expect(editor.chain).not.toHaveBeenCalled();
      expect(mocks.draftState.hasUnsavedChanges).toBe(true);
      expect(mocks.draftState.currentChatId).toBe("team-chat");
      expect(mocks.chatDB.deleteDraftOnlyChat).not.toHaveBeenCalled();
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
    it("clears the unchanged live draft after delayed deletion", async () => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "team-chat", currentUserDraftVersion: 3, hasUnsavedChanges: true });
      mocks.chatDB.getChat.mockResolvedValue({ chat_id: "team-chat" });
      mocks.chatDB.getMessagesForChat.mockResolvedValue([{ message_id: "sent-message" }]);

      let finishDeletion!: () => void;
      mocks.chatSyncService.sendDeleteDraft.mockImplementationOnce(() => new Promise<void>((resolve) => {
        finishDeletion = resolve;
      }));
      const clearing = clearCurrentDraft();
      await vi.waitFor(() => expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("team-chat"));
      finishDeletion();
      await clearing;

      expect(editor.chain).toHaveBeenCalledTimes(1);
      expect(mocks.draftState.hasUnsavedChanges).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted,teams.context.full-switch-local
    it("keeps a newer persisted draft version after delayed deletion", async () => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "team-chat", currentUserDraftVersion: 3, hasUnsavedChanges: true });
      mocks.chatDB.getChat.mockResolvedValue({ chat_id: "team-chat" });
      mocks.chatDB.getMessagesForChat.mockResolvedValue([{ message_id: "sent-message" }]);

      let finishDeletion!: () => void;
      mocks.chatSyncService.sendDeleteDraft.mockImplementationOnce(() => new Promise<void>((resolve) => {
        finishDeletion = resolve;
      }));
      const clearing = clearCurrentDraft();
      await vi.waitFor(() => expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("team-chat"));
      mocks.draftEditorUIState.update((state) => ({
        ...state, currentUserDraftVersion: 4, hasUnsavedChanges: true,
      }));
      finishDeletion();
      await clearing;

      expect(editor.chain).not.toHaveBeenCalled();
      expect(mocks.draftState.currentUserDraftVersion).toBe(4);
      expect(mocks.draftState.hasUnsavedChanges).toBe(true);
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle,teams.context.full-switch-local
    it("does not delete a draft-only chat when a new draft appears during the message read", async () => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "team-draft-only", currentUserDraftVersion: 2 });
      mocks.chatDB.getChat.mockResolvedValue({ chat_id: "team-draft-only" });

      let finishMessageRead!: (messages: []) => void;
      mocks.chatDB.getMessagesForChat.mockImplementationOnce(() => new Promise<[]>((resolve) => {
        finishMessageRead = resolve;
      }));
      const clearing = clearCurrentDraft();
      await vi.waitFor(() => expect(mocks.chatDB.getMessagesForChat).toHaveBeenCalledWith("team-draft-only"));
      editor.state.doc = { type: "new draft" };
      mocks.draftEditorUIState.update((state) => ({
        ...state, currentUserDraftVersion: 3, hasUnsavedChanges: true,
      }));
      finishMessageRead([]);
      await clearing;

      expect(mocks.chatDB.deleteDraftOnlyChat).not.toHaveBeenCalled();
      expect(editor.chain).not.toHaveBeenCalled();
      expect(mocks.draftState.currentUserDraftVersion).toBe(3);
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle,teams.context.full-switch-local
    it("does not clear a replacement editor even when its document matches", async () => {
      const editor = createEditor(false);
      const replacement = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "team-chat", hasUnsavedChanges: true });
      mocks.chatDB.getChat.mockResolvedValue({ chat_id: "team-chat" });
      mocks.chatDB.getMessagesForChat.mockResolvedValue([{ message_id: "sent-message" }]);

      let finishDeletion!: () => void;
      mocks.chatSyncService.sendDeleteDraft.mockImplementationOnce(() => new Promise<void>((resolve) => {
        finishDeletion = resolve;
      }));
      const clearing = clearCurrentDraft();
      await vi.waitFor(() => expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("team-chat"));
      mocks.getEditorInstance.mockReturnValue(replacement);
      finishDeletion();
      await clearing;

      expect(replacement.chain).not.toHaveBeenCalled();
      expect(mocks.draftState.hasUnsavedChanges).toBe(true);
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
    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
    it("deletes an already restored whitespace draft", async () => {
      const editor = createEditor(false);
      editor.getJSON.mockReturnValue({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "  \n " }] }] });
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({
        currentChatId: "auth-draft-chat",
        currentUserDraftVersion: 3,
        lastSavedContentMarkdown: "  \n ",
      });
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("  \n ");

      await saveDraftDebounced("auth-draft-chat", editor as never);

      expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("auth-draft-chat");
      expect(mocks.encryptWithMasterKey).not.toHaveBeenCalled();
    });

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
        currentUserDraftVersion: 0,
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
      expect(mocks.chatDB.deleteDraftOnlyChat).not.toHaveBeenCalled();
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

    // contract-test: supporting surface=gui.web assertions=drafts.navigation.includes-draft-only,drafts.draft-only.lifecycle
    it("defers explicit empty flush until the active context switch finishes", async () => {
      const contextSwitchFlushDelayMs = 550;
      vi.useFakeTimers();
      try {
        const editor = createEditor(true);
        mocks.getEditorInstance.mockReturnValue(editor);
        mocks.resetDraftState({
          currentChatId: "auth-draft-chat",
          isSwitchingContext: true,
          currentUserDraftVersion: 3,
          lastSavedContentMarkdown: "Known restored draft",
        });

        const result = flushSaveDraft(editor as never, "auth-draft-chat");

        expect(result).toBeUndefined();
        expect(mocks.chatSyncService.sendDeleteDraft).not.toHaveBeenCalled();

        mocks.resetDraftState({
          currentChatId: "auth-draft-chat",
          isSwitchingContext: false,
          currentUserDraftVersion: 3,
          lastSavedContentMarkdown: "Known restored draft",
        });
        await vi.advanceTimersByTimeAsync(contextSwitchFlushDelayMs);

        expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("auth-draft-chat");
      } finally {
        vi.useRealTimers();
      }
    });

    // contract-test: supporting surface=gui.web assertions=drafts.navigation.includes-draft-only,drafts.draft-only.lifecycle
    it("does not reset a newer draft context after stale chat cleanup finishes", async () => {
      const editor = createEditor(true);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "stale-empty-chat" });
      mocks.chatSyncService.sendDeleteDraft.mockImplementationOnce(async () => {
        mocks.draftEditorUIState.update((state) => ({
          ...state,
          currentChatId: "restored-draft-chat",
          currentUserDraftVersion: 1,
        }));
      });
      mocks.chatDB.getChat.mockResolvedValueOnce(undefined);

      await clearCurrentDraft();

      expect(mocks.clearEditorAndResetDraftState).not.toHaveBeenCalled();
      expect(mocks.draftState.currentChatId).toBe("restored-draft-chat");
    });
  });

  describe("new-chat draft activation", () => {
    // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
    it.each([
      ["inline math", { type: "doc", content: [{ type: "paragraph", content: [{ type: "inlineMath", attrs: { latex: "x + 1" } }] }] }],
      ["block math", { type: "doc", content: [{ type: "blockMath", attrs: { latex: "x^2" } }] }],
      ["horizontal rule", { type: "doc", content: [{ type: "horizontalRule" }] }],
    ])("preserves a %s-only draft", async (_label, content) => {
      const editor = createEditor(false);
      editor.getJSON.mockReturnValue(content);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("meaningful markdown");

      expect(inspectDraftContent(content).hasMeaningfulContent).toBe(true);
      await saveDraftDebounced(undefined, editor as never);

      expect(mocks.chatDB.createNewChatWithCurrentUserDraft).toHaveBeenCalledTimes(1);
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
    it("treats whitespace and hard breaks as an empty draft", () => {
      const content = { type: "doc", content: [{ type: "paragraph", content: [
        { type: "text", text: "  \n " }, { type: "hardBreak" },
      ] }] };
      expect(inspectDraftContent(content).hasMeaningfulContent).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
    it("does not create a draft for whitespace-only text", async () => {
      const editor = createEditor(false);
      editor.getJSON.mockReturnValue({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "   " }] }] });
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("   ");

      await saveDraftDebounced(undefined, editor as never);

      expect(mocks.chatDB.createNewChatWithCurrentUserDraft).not.toHaveBeenCalled();
      expect(mocks.encryptWithMasterKey).not.toHaveBeenCalled();
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle
    it("keeps a pending image in the composer without saving empty markdown", async () => {
      const editor = createEditor(false);
      editor.getJSON.mockReturnValue({ type: "doc", content: [{ type: "embed", attrs: { id: "image-1", type: "image", status: "uploading" } }] });
      mocks.getEditorInstance.mockReturnValue(editor);

      await saveDraftDebounced(undefined, editor as never);

      expect(mocks.chatDB.createNewChatWithCurrentUserDraft).not.toHaveBeenCalled();
      expect(mocks.chatSyncService.sendDeleteDraft).not.toHaveBeenCalled();
      expect(editor.chain().clearContent).not.toHaveBeenCalled();
    });

    // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
    it("still saves a mention-only draft", async () => {
      const editor = createEditor(false);
      editor.getJSON.mockReturnValue({ type: "doc", content: [{ type: "paragraph", content: [{ type: "mate", attrs: { id: "mate-1" } }] }] });
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("@mate");

      await saveDraftDebounced(undefined, editor as never);

      expect(mocks.chatDB.createNewChatWithCurrentUserDraft).toHaveBeenCalledTimes(1);
    });

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

    // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted,drafts.sync.version-authoritative
    it.each([false, true])("keeps a rejected local draft unsaved and retries beyond the winning version (cleared=%s)", async (cleared) => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("Local edit still needs saving");
      mocks.resetDraftState({ currentChatId: "draft-race", lastSavedContentMarkdown: "old", hasUnsavedChanges: true });
      mocks.chatDB.getRawChat.mockResolvedValueOnce({ chat_id: "draft-race", draft_v: 1,
        encrypted_draft_md: "old-cipher", encrypted_draft_preview: "old-preview" });
      const winner = { chat_id: "draft-race", draft_v: cleared ? 0 : 3,
        cleared_draft_v: cleared ? 3 : 0,
        encrypted_draft_md: cleared ? null : "winning-cipher",
        encrypted_draft_preview: cleared ? null : "winning-preview" };
      mocks.chatDB.saveChatDraftFields.mockResolvedValueOnce(winner);
      await saveDraftDebounced("draft-race", editor as never);
      expect(mocks.draftState.hasUnsavedChanges).toBe(true);
      expect(mocks.draftState.lastSavedContentMarkdown).toBe("old");
      expect(mocks.chatSyncService.sendUpdateDraft).not.toHaveBeenCalled();
      mocks.chatDB.getRawChat.mockResolvedValueOnce(winner);
      await saveDraftDebounced("draft-race", editor as never);
      expect(mocks.chatDB.saveChatDraftFields).toHaveBeenLastCalledWith("draft-race",
        expect.objectContaining({ draft_v: 4, encrypted_draft_md: "encrypted-data" }));
      expect(mocks.draftState.hasUnsavedChanges).toBe(false);
      expect(mocks.draftState.lastSavedContentMarkdown).toBe("Local edit still needs saving");
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
      mocks.chatDB.getRawChat.mockResolvedValueOnce({
        chat_id: "late-created-chat-id", messages_v: 0, draft_v: 1,
        encrypted_title: null, encrypted_draft_md: "encrypted-data",
        encrypted_draft_preview: "encrypted-data",
      });
      finishPersistence({
        chat_id: "late-created-chat-id",
        draft_v: 1,
        encrypted_draft_md: "encrypted-data",
        encrypted_draft_preview: "encrypted-data",
      });
      await savePromise;

      expect(mocks.chatDB.deleteDraftOnlyChat).toHaveBeenCalledWith("late-created-chat-id");
      expect(mocks.draftState.newlyCreatedChatIdToSelect).toBeNull();
      expect(mocks.draftState.isSaveInProgress).toBe(false);
    });

    // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle,teams.context.full-switch-local
    it("clears a stale draft without deleting a committed Team chat with an empty local window", async () => {
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("Draft saved during Team switch");
      let finishPersistence!: (chat: Record<string, unknown>) => void;
      mocks.chatDB.createNewChatWithCurrentUserDraft.mockImplementationOnce(
        () => new Promise((resolve) => { finishPersistence = resolve; }),
      );
      const saving = saveDraftDebounced(undefined, editor as never);
      await vi.waitFor(() => expect(mocks.chatDB.createNewChatWithCurrentUserDraft).toHaveBeenCalledTimes(1));
      activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
      mocks.chatDB.getRawChat.mockResolvedValueOnce({
        chat_id: "committed-team-chat", team_id: "team-1", messages_v: 2,
        draft_v: 1, encrypted_draft_md: "encrypted-data", encrypted_draft_preview: null,
      });
      mocks.chatDB.getMessagesForChat.mockResolvedValue([]);
      finishPersistence({ chat_id: "committed-team-chat", team_id: "team-1", messages_v: 2,
        draft_v: 1, encrypted_draft_md: "encrypted-data", encrypted_draft_preview: null });
      await saving;
      expect(mocks.chatDB.deleteDraftOnlyChat).not.toHaveBeenCalled();
      expect(mocks.chatDB.saveChatDraftFields).toHaveBeenCalledWith("committed-team-chat", expect.objectContaining({
        encrypted_draft_md: null,
      }));
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

  describe("recording-owned empty draft saves", () => {
    // contract-test: supporting surface=gui.web assertions=message-input.audio.editable-transcript,drafts.draft-only.lifecycle
    it("holds a queued empty save from before recording capture, then permits ordinary cleanup after release", async () => {
      const editor = createEditor(true);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "recording-chat" });
      mocks.deferDebounce = true;
      triggerSaveDraft("recording-chat", editor as never);

      const release = protectEmptyRecordingDraft(editor as never, "recording-chat", () => true);
      await saveDraftDebounced.flush();
      expect(mocks.chatSyncService.sendDeleteDraft).not.toHaveBeenCalled();
      expect(mocks.draftState.currentChatId).toBe("recording-chat");

      release();
      mocks.deferDebounce = false;
      await saveDraftDebounced("recording-chat", editor as never);
      expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("recording-chat");
    });

    // contract-test: supporting surface=gui.web assertions=message-input.audio.editable-transcript,drafts.draft-only.lifecycle
    it("holds an empty save that entered before capture and resumes from async lookup", async () => {
      const editor = createEditor(true);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: "recording-chat" });
      let finishLookup!: () => void;
      mocks.incognitoChatService.getChat.mockImplementationOnce(() => new Promise((resolve) => {
        finishLookup = () => resolve(null);
      }));

      const saving = saveDraftDebounced("recording-chat", editor as never);
      await vi.waitFor(() => expect(mocks.incognitoChatService.getChat).toHaveBeenCalledTimes(1));
      const release = protectEmptyRecordingDraft(editor as never, "recording-chat", () => true);
      finishLookup();
      await saving;

      expect(mocks.chatSyncService.sendDeleteDraft).not.toHaveBeenCalled();
      expect(mocks.draftState.currentChatId).toBe("recording-chat");
      release();
    });

    // contract-test: supporting surface=gui.web assertions=message-input.audio.editable-transcript,drafts.draft-only.lifecycle
    it("does not hold another chat or editor's empty draft cleanup", async () => {
      const protectedEditor = createEditor(true);
      const otherEditor = createEditor(true);
      const release = protectEmptyRecordingDraft(protectedEditor as never, "recording-chat", () => true);

      mocks.getEditorInstance.mockReturnValue(protectedEditor);
      mocks.resetDraftState({ currentChatId: "prior-chat" });
      await saveDraftDebounced("prior-chat", protectedEditor as never);
      expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("prior-chat");

      mocks.chatSyncService.sendDeleteDraft.mockClear();
      mocks.getEditorInstance.mockReturnValue(otherEditor);
      mocks.resetDraftState({ currentChatId: "recording-chat" });
      await saveDraftDebounced("recording-chat", otherEditor as never);
      expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith("recording-chat");
      release();
    });
  });

  describe("flushSaveDraft", () => {
    // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
    it("is callable and triggers immediate save", () => {
      expect(() => flushSaveDraft()).not.toThrow();
    });

    // contract-test: direct surface=gui.web assertions=chat-queued-followups.editing.stable-revision,chat-queued-followups.editing.cancel
    it("opens a queued edit after an empty independent draft is cleared", async () => {
      const chatId = "queued-empty-draft-chat";
      const editor = createEditor(true);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: chatId });
      mocks.chatDB.getChat.mockResolvedValue({ chat_id: chatId, messages_v: 2, draft_v: 0 });

      await expect(flushSaveDraftAndWaitForIdle(editor as never, chatId)).resolves.toBe(true);
      expect(mocks.chatSyncService.sendDeleteDraft).toHaveBeenCalledWith(chatId);
      expect(mocks.draftState).toMatchObject({
        currentChatId: chatId, currentUserDraftVersion: 0, hasUnsavedChanges: false,
      });
      expect(mocks.chatDB.deleteDraftOnlyChat).not.toHaveBeenCalled();
    });

    // contract-test: direct surface=gui.web assertions=chat-queued-followups.editing.cancel
    it("does not open a queued edit when empty draft deletion fails", async () => {
      const chatId = "queued-empty-draft-delete-failure";
      const editor = createEditor(true);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: chatId });
      mocks.chatSyncService.sendDeleteDraft.mockRejectedValueOnce(new Error("draft deletion failed"));

      await expect(flushSaveDraftAndWaitForIdle(editor as never, chatId)).resolves.toBe(false);
      expect(mocks.draftState.hasUnsavedChanges).toBe(true);
    });

    // contract-test: direct surface=gui.web assertions=chat-queued-followups.editing.cancel,chat-queued-followups.editing.stable-revision
    it("drains an active save and its matching resave before queued text replaces the draft", async () => {
      const chatId = "queued-edit-chat";
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: chatId, hasUnsavedChanges: true });
      mocks.chatDB.getRawChat.mockResolvedValue({ chat_id: chatId, draft_v: 1, encrypted_draft_md: "previous" });
      mocks.tipTapToCanonicalMarkdown.mockImplementation((json: { content?: Array<{ content?: Array<{ text?: string }> }> }) =>
        json.content?.[0]?.content?.[0]?.text ?? "");

      let releaseEncryption!: () => void;
      mocks.encryptWithMasterKey.mockImplementationOnce(() => new Promise<string>((resolve) => {
        releaseEncryption = () => resolve("encrypted-independent-draft");
      }));
      let releaseTransport!: () => void;
      mocks.chatSyncService.sendUpdateDraft.mockImplementationOnce(() => new Promise<void>((resolve) => {
        releaseTransport = resolve;
      }));
      const activeSave = flushSaveDraft(editor as never, chatId);
      await vi.waitFor(() => expect(mocks.draftState.isSaveInProgress).toBe(true));
      // A second save request while encryption owns the lock asks for a delayed
      // resave. The queued editor must not replace this same live draft yet.
      await flushSaveDraft(editor as never, chatId);

      vi.useFakeTimers();
      try {
        const drain = flushSaveDraftAndWaitForIdle(editor as never, chatId);
        releaseEncryption();
        // The server receipt remains pending even after encrypted local commit.
        // Queued edit may open now, and that old sender must never resave its
        // later queued text when the receipt eventually arrives.
        expect(await drain).toBe(true);

        editor.getJSON.mockReturnValue({
          type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "queued content" }] }],
        });
        releaseTransport();
        await activeSave;
        await vi.advanceTimersByTimeAsync(1_500);
        expect(mocks.encryptWithMasterKey.mock.calls.map((call) => call[0])).toEqual([
          "draft", "draft", "draft", "draft",
        ]);
        expect(mocks.chatDB.saveChatDraftFields).toHaveBeenCalledTimes(1);
      } finally {
        vi.useRealTimers();
      }
    });

    // contract-test: direct surface=gui.web assertions=video-call.chat.typed-input,video-call.privacy,drafts.draft-only.lifecycle
    it("waits for a concurrently edited call draft's local commit without waiting for receipts or suppressing autosave", async () => {
      const chatId = "voice-draft";
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: chatId, hasUnsavedChanges: true });
      mocks.chatDB.getRawChat.mockResolvedValue({ chat_id: chatId, draft_v: 1, encrypted_draft_md: "previous" });
      mocks.tipTapToCanonicalMarkdown.mockImplementation((json: { content?: Array<{ content?: Array<{ text?: string }> }> }) =>
        json.content?.[0]?.content?.[0]?.text ?? "");
      let releaseEncryption!: () => void;
      mocks.encryptWithMasterKey.mockImplementation(async (text: string) => `encrypted:${text}`);
      mocks.encryptWithMasterKey.mockImplementationOnce(() => new Promise<string>(resolve => {
        releaseEncryption = () => resolve("encrypted:draft");
      }));
      let releaseTransport!: () => void;
      mocks.chatSyncService.sendUpdateDraft.mockImplementationOnce(() => new Promise<void>(resolve => {
        releaseTransport = resolve;
      }));
      let commitLatest!: () => void;
      mocks.chatDB.saveChatDraftFields.mockImplementationOnce(async (id, fields) => ({ chat_id: id, ...fields }))
        .mockImplementationOnce((id, fields) => new Promise(resolve => {
          commitLatest = () => resolve({ chat_id: id, ...fields });
        }));
      const activeSave = flushSaveDraft(editor as never, chatId);
      await vi.waitFor(() => expect(mocks.draftState.isSaveInProgress).toBe(true));
      editor.getJSON.mockReturnValue({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "captured Project mention" }] }] });
      await flushSaveDraft(editor as never, chatId); // An ordinary resave is pending behind encryption.
      let settled = false;
      const ready = flushSaveDraftAndWaitForIdle(editor as never, chatId, { suppressQueuedEditResaves: false })
        .then(result => { settled = true; return result; });
      releaseEncryption();
      await vi.waitFor(() => expect(commitLatest).toBeTypeOf("function"));
      expect(settled).toBe(false);
      expect(mocks.chatDB.saveChatDraftFields).toHaveBeenLastCalledWith(chatId, expect.objectContaining({ encrypted_draft_md: "encrypted:captured Project mention" }));
      vi.useFakeTimers();
      try {
        commitLatest();
        expect(await ready).toBe(true);
        expect(mocks.draftState.lastSavedContentMarkdown).toBe("captured Project mention");
        // The first receipt is still pending. Keeping ordinary resaves enabled
        // must persist later edits when that active sender finally completes.
        editor.getJSON.mockReturnValue({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "later ordinary edit" }] }] });
        releaseTransport();
        await activeSave;
        await vi.advanceTimersByTimeAsync(1_500);
        expect(mocks.chatDB.saveChatDraftFields).toHaveBeenLastCalledWith(chatId, expect.objectContaining({ encrypted_draft_md: "encrypted:later ordinary edit" }));
      } finally { vi.useRealTimers(); }
    });

    // contract-test: direct surface=gui.web assertions=video-call.privacy,video-call.chat.typed-input,drafts.draft-only.lifecycle
    it.each(["editor", "account"])("rejects call draft readiness when its %s changes during an active save", async (change) => {
      const chatId = `voice-draft-${change}`;
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: chatId, hasUnsavedChanges: true });
      mocks.chatDB.getRawChat.mockResolvedValue({ chat_id: chatId, draft_v: 1, encrypted_draft_md: "previous" });
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("draft");
      let releaseEncryption!: () => void;
      mocks.encryptWithMasterKey.mockImplementationOnce(() => new Promise<string>(resolve => {
        releaseEncryption = () => resolve("encrypted:draft");
      }));
      const activeSave = flushSaveDraft(editor as never, chatId);
      await vi.waitFor(() => expect(mocks.draftState.isSaveInProgress).toBe(true));
      const ready = flushSaveDraftAndWaitForIdle(editor as never, chatId, { suppressQueuedEditResaves: false });
      if (change === "account") mocks.setAccountId("replacement-account");
      else {
        mocks.getEditorInstance.mockReturnValue(createEditor(false));
        mocks.resetDraftState({ currentChatId: chatId, isSaveInProgress: true });
      }
      expect(await ready).toBe(false);
      releaseEncryption();
      await activeSave;
    });

    // contract-test: direct surface=gui.web assertions=chat-queued-followups.editing.cancel,teams.context.full-switch-local
    it("aborts the queued edit drain when its Team context changes during an active save", async () => {
      const chatId = "queued-team-chat";
      const editor = createEditor(false);
      mocks.getEditorInstance.mockReturnValue(editor);
      mocks.resetDraftState({ currentChatId: chatId, hasUnsavedChanges: true });
      mocks.chatDB.getRawChat.mockResolvedValue({ chat_id: chatId, draft_v: 1, encrypted_draft_md: "previous" });
      mocks.tipTapToCanonicalMarkdown.mockReturnValue("draft");
      activeTeamContext.set({ team: null, teamId: "team-a", epoch: 1 });

      let releaseEncryption!: () => void;
      mocks.encryptWithMasterKey.mockImplementationOnce(() => new Promise<string>((resolve) => {
        releaseEncryption = () => resolve("encrypted-independent-draft");
      }));
      const activeSave = flushSaveDraft(editor as never, chatId);
      await vi.waitFor(() => expect(mocks.draftState.isSaveInProgress).toBe(true));
      const drain = flushSaveDraftAndWaitForIdle(editor as never, chatId);
      activeTeamContext.set({ team: null, teamId: "team-b", epoch: 2 });
      expect(await drain).toBe(false);
      releaseEncryption();
      await activeSave;
    });
  });
});
