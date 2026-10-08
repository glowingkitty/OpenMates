/**
 * sendersDrafts.test.ts -- WebSocket draft sender receipt contracts.
 *
 * Covers encrypted draft update acknowledgement handling without opening a real
 * socket or IndexedDB connection. The tests focus on races between pending draft
 * receipts and WebSocket connection status churn.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

type Handler = (payload: unknown) => void | Promise<void>;
type WebSocketState = { status: string; lastMessage: string | null; error: string | null };

const mocks = vi.hoisted(() => {
  const state = {
    handlers: new Map<string, Handler[]>(),
    statusSubscribers: [] as Array<(state: WebSocketState) => void>,
    currentStatus: "connected",
  };

  const webSocketService = {
    sendMessage: vi.fn().mockResolvedValue(undefined),
    on: vi.fn((messageType: string, handler: Handler) => {
      const handlers = state.handlers.get(messageType) ?? [];
      handlers.push(handler);
      state.handlers.set(messageType, handlers);
    }),
    off: vi.fn((messageType: string, handler: Handler) => {
      const handlers = state.handlers.get(messageType) ?? [];
      state.handlers.set(
        messageType,
        handlers.filter((candidate) => candidate !== handler),
      );
    }),
  };
  const chatDB = {
    getChat: vi.fn().mockResolvedValue({ chat_id: "chat-1", draft_v: 3 }),
    clearCurrentUserChatDraft: vi.fn().mockResolvedValue({ chat_id: "chat-1" }),
    getRawChat: vi.fn().mockResolvedValue({
      chat_id: "chat-1",
      encrypted_draft_md: null,
      encrypted_draft_preview: null,
    }),
    getMessagesForChat: vi.fn().mockResolvedValue([]),
    upsertRawChat: vi.fn().mockResolvedValue(undefined),
    setTeamDraftPendingSync: vi.fn(),
    addOfflineChange: vi.fn().mockResolvedValue(undefined),
  };
  const notificationStore = { error: vi.fn() };
  const chatMetadataCache = { invalidateChat: vi.fn() };

  const websocketStatus = {
    subscribe: vi.fn((subscriber: (state: WebSocketState) => void) => {
      state.statusSubscribers.push(subscriber);
      subscriber({ status: state.currentStatus, lastMessage: null, error: null });
      return () => {
        const index = state.statusSubscribers.indexOf(subscriber);
        if (index >= 0) state.statusSubscribers.splice(index, 1);
      };
    }),
  };

  return {
    chatDB,
    notificationStore,
    chatMetadataCache,
    state,
    webSocketService,
    websocketStatus,
    emitReceipt(payload: unknown) {
      for (const handler of state.handlers.get("draft_update_receipt") ?? []) {
        void handler(payload);
      }
    },
    emitDeleteReceipt(payload: unknown) {
      for (const handler of state.handlers.get("draft_delete_receipt") ?? []) {
        void handler(payload);
      }
    },
    emitStatus(status: string) {
      state.currentStatus = status;
      const snapshot = { status, lastMessage: null, error: null };
      for (const subscriber of [...state.statusSubscribers]) {
        subscriber(snapshot);
      }
    },
  };
});

vi.mock("../websocketService", () => ({
  webSocketService: mocks.webSocketService,
}));

vi.mock("../../stores/websocketStatusStore", () => ({
  websocketStatus: mocks.websocketStatus,
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../../stores/notificationStore", () => ({
  notificationStore: mocks.notificationStore,
}));
vi.mock("../chatMetadataCache", () => ({
  chatMetadataCache: mocks.chatMetadataCache,
}));

import { sendDeleteDraftImpl, sendUpdateDraftImpl } from "../sendersDrafts";
import { activeTeamContext } from "../../stores/teamStore";
import { promoteDeferredTeamDraft } from "../drafts/draftContext";
import type { DraftChatContext } from "../drafts/draftContext";

function configureTeamIntentStore(): void {
  mocks.chatDB.setTeamDraftPendingSync.mockImplementation(async (
    chatId, teamId, pending, guard, expected,
  ) => {
    const chat = await mocks.chatDB.getRawChat(chatId);
    if (!chat || chat.team_id !== teamId || !guard() ||
      (expected && (chat.team_draft_pending_sync !== expected.kind ||
        (expected.cipher !== undefined && chat.encrypted_draft_md !== expected.cipher) ||
        (expected.version !== undefined && (chat.draft_v ?? 0) !== expected.version)))) return null;
    const updated = { ...chat, team_draft_pending_sync: pending,
      cleared_draft_v: expected?.clearedDraftVersion === undefined
        ? chat.cleared_draft_v
        : Math.max(chat.cleared_draft_v ?? 0, expected.clearedDraftVersion) };
    await mocks.chatDB.upsertRawChat(updated);
    return updated;
  });
}

describe("sendUpdateDraftImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    configureTeamIntentStore();
    mocks.state.handlers.clear();
    mocks.state.statusSubscribers.splice(0);
    mocks.state.currentStatus = "connected";
    activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
    mocks.webSocketService.sendMessage.mockResolvedValue(undefined);
    mocks.chatDB.getChat.mockResolvedValue({ chat_id: "chat-1", draft_v: 3 });
    mocks.chatDB.clearCurrentUserChatDraft.mockResolvedValue({ chat_id: "chat-1" });
    mocks.chatDB.getRawChat.mockResolvedValue({
      chat_id: "chat-1",
      encrypted_draft_md: null,
      encrypted_draft_preview: null,
    });
    mocks.chatDB.getMessagesForChat.mockResolvedValue([]);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("resolves after the matching draft update receipt arrives", async () => {
    const receipt = sendUpdateDraftImpl({} as never, "chat-1", "cipher-md", "cipher-preview", 1);

    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith("update_draft", {
      chat_id: "chat-1",
      encrypted_draft_md: "cipher-md",
      encrypted_draft_preview: "cipher-preview",
      draft_v: 1,
    }));

    mocks.emitReceipt({ chat_id: "chat-1", draft_v: 1, success: true });

    await expect(receipt).resolves.toBeUndefined();
    expect(mocks.webSocketService.off).toHaveBeenCalledWith("draft_update_receipt", expect.any(Function));
    expect(mocks.state.statusSubscribers).toHaveLength(0);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("queues pending draft receipts when the WebSocket reconnects before acknowledgement", async () => {
    const service = {
      queueOfflineChange: vi.fn().mockResolvedValue(undefined),
      sendOfflineChanges: vi.fn().mockResolvedValue(undefined),
    };
    const receipt = sendUpdateDraftImpl(service as never, "chat-1", "cipher-md", null, 1);

    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith("update_draft", expect.any(Object)));
    mocks.emitStatus("reconnecting");

    await expect(receipt).resolves.toBeUndefined();
    expect(mocks.webSocketService.off).toHaveBeenCalledWith("draft_update_receipt", expect.any(Function));
    expect(mocks.state.statusSubscribers).toHaveLength(0);
    expect(service.queueOfflineChange).toHaveBeenCalledWith({
      chat_id: "chat-1",
      type: "draft",
      value: "cipher-md",
      version_before_edit: 0,
    });
    expect(service.sendOfflineChanges).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.persistence.local-first-encrypted
  it("sends a committed Team member draft with Team scope and waits for its receipt", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    mocks.chatDB.getRawChat.mockResolvedValue({ chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      draft_v: 1, encrypted_draft_md: "cipher-md" });
    const receipt = sendUpdateDraftImpl({} as never, "chat-1", "cipher-md", null, 1);
    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "update_draft", expect.objectContaining({ chat_id: "chat-1", team_id: "team-1", encrypted_draft_md: "cipher-md" }),
    ));
    mocks.emitReceipt({ chat_id: "chat-1", team_id: "team-1", draft_v: 1, success: true });
    await expect(receipt).resolves.toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,drafts.persistence.local-first-encrypted
  it("keeps an uncommitted Team draft local and rejects a stale workspace", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    mocks.chatDB.getRawChat.mockResolvedValueOnce({ chat_id: "chat-1", team_id: "team-1", messages_v: 0 });
    await expect(sendUpdateDraftImpl({} as never, "chat-1", "cipher-md", null, 1)).resolves.toBeUndefined();
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalled();

    mocks.chatDB.getRawChat.mockResolvedValueOnce({ chat_id: "chat-1", team_id: "team-1", messages_v: 1 });
    activeTeamContext.set({ team: null, teamId: "team-2", epoch: 2 });
    await expect(sendUpdateDraftImpl({} as never, "chat-1", "cipher-md", null, 1)).rejects.toThrow("active workspace");
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.persistence.local-first-encrypted
  it("promotes the latest private draft after the first optimistic Team message confirms", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    let storedChat = { chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      team_chat_pending_commit: true,
      draft_v: 2, encrypted_draft_md: "latest-member-cipher", encrypted_draft_preview: "preview-cipher" };
    mocks.chatDB.getRawChat.mockImplementation(async () => storedChat);
    mocks.chatDB.upsertRawChat.mockImplementation(async (chat) => { storedChat = chat; });
    await sendUpdateDraftImpl({} as never, "chat-1", "older-member-cipher", null, 1);
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalled();
    expect(storedChat).toEqual(expect.objectContaining({ team_draft_pending_sync: "update" }));

    storedChat = { ...storedChat, team_chat_pending_commit: false };

    const service = { sendUpdateDraft: vi.fn().mockResolvedValue(undefined),
      queueOfflineChange: vi.fn().mockResolvedValue(undefined) };
    await promoteDeferredTeamDraft(service as never, "chat-1");
    expect(service.sendUpdateDraft).toHaveBeenCalledWith(
      "chat-1", "latest-member-cipher", "preview-cipher", 2,
      { teamId: "team-1", epoch: 1, committed: true },
    );
    expect(service.queueOfflineChange).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.persistence.local-first-encrypted
  it("promotes when the first-message ACK commits during the pending-intent write", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    const committed = { chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      team_chat_pending_commit: false, team_draft_pending_sync: "update",
      draft_v: 2, encrypted_draft_md: "latest-cipher", encrypted_draft_preview: "latest-preview" };
    mocks.chatDB.getRawChat.mockResolvedValueOnce({ ...committed, team_chat_pending_commit: true });
    mocks.chatDB.getRawChat.mockResolvedValue(committed);
    mocks.chatDB.setTeamDraftPendingSync.mockResolvedValue(committed);
    const service = { sendUpdateDraft: vi.fn().mockResolvedValue(undefined),
      queueOfflineChange: vi.fn().mockResolvedValue(undefined) };
    await sendUpdateDraftImpl(service as never, "chat-1", "older-cipher", null, 1);
    await vi.waitFor(() => expect(service.sendUpdateDraft).toHaveBeenCalledWith(
      "chat-1", "latest-cipher", "latest-preview", 2,
      { teamId: "team-1", epoch: 1, committed: true },
    ));
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,drafts.persistence.local-first-encrypted
  it("promotes a persisted Team draft after switching away and back without the first ACK", async () => {
    let storedChat = { chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      team_chat_pending_commit: false, team_draft_pending_sync: "update",
      draft_v: 2, encrypted_draft_md: "private-cipher", encrypted_draft_preview: "private-preview" };
    mocks.chatDB.getRawChat.mockImplementation(async () => storedChat);
    mocks.chatDB.upsertRawChat.mockImplementation(async (chat) => { storedChat = chat; });
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    activeTeamContext.set({ team: null, teamId: null, epoch: 2 });
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 3 });
    const service = { sendUpdateDraft: vi.fn().mockResolvedValue(undefined),
      queueOfflineChange: vi.fn().mockResolvedValue(undefined) };
    await promoteDeferredTeamDraft(service as never, "chat-1");
    expect(service.sendUpdateDraft).toHaveBeenCalledWith("chat-1", "private-cipher", "private-preview", 2,
      { teamId: "team-1", epoch: 3, committed: true });
    expect(storedChat).toEqual(expect.objectContaining({ team_draft_pending_sync: undefined }));
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,drafts.sync.version-authoritative
  it("cancels an old promotion when delete begins before its database read completes", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    const chat = { chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      team_chat_pending_commit: false, team_draft_pending_sync: "update",
      draft_v: 2, encrypted_draft_md: "old-cipher", encrypted_draft_preview: "old-preview" };
    let finishRead!: (value: typeof chat) => void;
    mocks.chatDB.getRawChat.mockImplementationOnce(() => new Promise((resolve) => { finishRead = resolve; }));
    mocks.chatDB.getRawChat.mockResolvedValue(chat);
    const promotionService = { sendUpdateDraft: vi.fn(), queueOfflineChange: vi.fn() };
    const promotion = promoteDeferredTeamDraft(promotionService as never, "chat-1");
    await vi.waitFor(() => expect(mocks.chatDB.getRawChat).toHaveBeenCalledTimes(1));
    const deletion = sendDeleteDraftImpl({ dispatchEvent: vi.fn() } as never, "chat-1");
    finishRead(chat);
    await promotion;
    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "delete_draft", expect.objectContaining({ chatId: "chat-1", team_id: "team-1" }),
    ));
    mocks.emitDeleteReceipt({ chat_id: "chat-1", success: true });
    await deletion;
    expect(promotionService.sendUpdateDraft).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.sync.version-authoritative
  it("sends delete after an already-started promotion completes", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    const chat = { chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      team_chat_pending_commit: false, team_draft_pending_sync: "update",
      draft_v: 2, encrypted_draft_md: "old-cipher", encrypted_draft_preview: "old-preview" };
    mocks.chatDB.getRawChat.mockResolvedValue(chat);
    let finishUpdate!: () => void;
    const updateGate = new Promise<void>((resolve) => { finishUpdate = resolve; });
    const promotionService = { sendUpdateDraft: vi.fn(() => updateGate), queueOfflineChange: vi.fn() };
    const promotion = promoteDeferredTeamDraft(promotionService as never, "chat-1");
    await vi.waitFor(() => expect(promotionService.sendUpdateDraft).toHaveBeenCalledTimes(1));
    const deletion = sendDeleteDraftImpl({ dispatchEvent: vi.fn() } as never, "chat-1");
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalledWith("delete_draft", expect.anything());
    finishUpdate();
    await promotion;
    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "delete_draft", expect.objectContaining({ chatId: "chat-1", team_id: "team-1" }),
    ));
    mocks.emitDeleteReceipt({ chat_id: "chat-1", success: true });
    await deletion;
  });

  // contract-test: direct surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.sync.version-authoritative
  it("orders an ordinary newer Team update after an older deferred promotion", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    let storedChat = { chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      team_chat_pending_commit: false, team_draft_pending_sync: "update",
      draft_v: 2, encrypted_draft_md: "old-cipher", encrypted_draft_preview: "old-preview" };
    let finishOldRead!: (value: typeof storedChat) => void;
    mocks.chatDB.getRawChat.mockImplementationOnce(() => new Promise((resolve) => { finishOldRead = resolve; }));
    mocks.chatDB.getRawChat.mockImplementation(async () => storedChat);
    mocks.chatDB.upsertRawChat.mockImplementation(async (chat) => { storedChat = chat; });
    const service = { sendUpdateDraft: vi.fn((...args: [string, string | null, string | null | undefined,
      number, DraftChatContext]) => sendUpdateDraftImpl(service as never, ...args)),
      queueOfflineChange: vi.fn().mockResolvedValue(undefined) };
    const promotion = promoteDeferredTeamDraft(service as never, "chat-1");
    await vi.waitFor(() => expect(mocks.chatDB.getRawChat).toHaveBeenCalledTimes(1));
    const oldSnapshot = { ...storedChat };
    storedChat = { ...storedChat, draft_v: 3, encrypted_draft_md: "new-cipher",
      encrypted_draft_preview: "new-preview" };
    const ordinary = sendUpdateDraftImpl(service as never, "chat-1", "new-cipher", "new-preview", 3);
    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "update_draft", expect.objectContaining({ encrypted_draft_md: "new-cipher", draft_v: 3 }),
    ));
    mocks.emitReceipt({ chat_id: "chat-1", draft_v: 3, success: true });
    await ordinary;
    finishOldRead(oldSnapshot);
    await promotion;
    expect(mocks.webSocketService.sendMessage.mock.calls.map((call) =>
      (call[1] as { encrypted_draft_md: string }).encrypted_draft_md)).toEqual(["new-cipher"]);
  });

  // contract-test: direct surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.sync.version-authoritative
  it("leaves a fresh Team draft intact when deferred delete reaches its final check", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    let storedChat = { chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      team_chat_pending_commit: false, team_draft_pending_sync: "delete",
      draft_v: 0, encrypted_draft_md: null as string | null,
      encrypted_draft_preview: null as string | null };
    let readCount = 0;
    let finishFinalRead!: (value: typeof storedChat) => void;
    mocks.chatDB.getRawChat.mockImplementation(() => {
      readCount++;
      if (readCount === 3) return new Promise((resolve) => { finishFinalRead = resolve; });
      return Promise.resolve(storedChat);
    });
    const service = { sendDeleteDraft: vi.fn((id: string, context: DraftChatContext) =>
      sendDeleteDraftImpl(service as never, id, context)) };
    const promotion = promoteDeferredTeamDraft(service as never, "chat-1");
    await vi.waitFor(() => expect(readCount).toBe(3));
    storedChat = { ...storedChat, draft_v: 1, encrypted_draft_md: "fresh-cipher",
      encrypted_draft_preview: "fresh-preview" };
    const ordinary = sendUpdateDraftImpl({} as never, "chat-1", "fresh-cipher", "fresh-preview", 1);
    finishFinalRead(storedChat);
    await promotion;
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalledWith("delete_draft", expect.anything());
    expect(mocks.chatDB.clearCurrentUserChatDraft).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "update_draft", expect.objectContaining({ encrypted_draft_md: "fresh-cipher" }),
    ));
    mocks.emitReceipt({ chat_id: "chat-1", draft_v: 1, success: true });
    await ordinary;
    expect(storedChat.encrypted_draft_md).toBe("fresh-cipher");
  });

  // contract-test: direct surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.sync.version-authoritative
  it("delivers a fresh update after an already-dispatched deferred delete", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    let storedChat = { chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      team_chat_pending_commit: false, team_draft_pending_sync: "delete",
      draft_v: 0, encrypted_draft_md: null as string | null,
      encrypted_draft_preview: null as string | null };
    mocks.chatDB.getRawChat.mockImplementation(async () => storedChat);
    mocks.chatDB.upsertRawChat.mockImplementation(async (chat) => { storedChat = chat; });
    const service = { sendDeleteDraft: vi.fn((id: string, context: DraftChatContext) =>
      sendDeleteDraftImpl(service as never, id, context)) };
    const promotion = promoteDeferredTeamDraft(service as never, "chat-1");
    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "delete_draft", expect.objectContaining({ chatId: "chat-1", team_id: "team-1" }),
    ));
    storedChat = { ...storedChat, encrypted_draft_md: "fresh-cipher",
      encrypted_draft_preview: "fresh-preview", draft_v: 1 };
    const ordinary = sendUpdateDraftImpl({} as never, "chat-1", "fresh-cipher", "fresh-preview", 1);
    expect(mocks.webSocketService.sendMessage).toHaveBeenCalledTimes(1);
    mocks.emitDeleteReceipt({ chat_id: "chat-1", success: true, draft_v: 4 });
    await promotion;
    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "update_draft", expect.objectContaining({ encrypted_draft_md: "fresh-cipher" }),
    ));
    mocks.emitReceipt({ chat_id: "chat-1", draft_v: 1, success: true });
    await ordinary;
    expect(mocks.chatDB.clearCurrentUserChatDraft).not.toHaveBeenCalled();
    expect(storedChat.encrypted_draft_md).toBe("fresh-cipher");
  });
});

describe("sendDeleteDraftImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    configureTeamIntentStore();
    mocks.state.handlers.clear();
    mocks.state.statusSubscribers.splice(0);
    mocks.state.currentStatus = "connected";
    activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
    mocks.webSocketService.sendMessage.mockResolvedValue(undefined);
    mocks.chatDB.getChat.mockResolvedValue({ chat_id: "chat-1", draft_v: 3 });
    mocks.chatDB.clearCurrentUserChatDraft.mockResolvedValue({ chat_id: "chat-1" });
    mocks.chatDB.getRawChat.mockResolvedValue({
      chat_id: "chat-1",
      encrypted_draft_md: null,
      encrypted_draft_preview: null,
    });
    mocks.chatDB.getMessagesForChat.mockResolvedValue([]);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("logs failed background draft deletion without showing a user error notification", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const deletion = sendDeleteDraftImpl({ dispatchEvent: vi.fn() } as never, "chat-1");

    await vi.waitFor(() => {
      expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith("delete_draft", { chatId: "chat-1" });
    });
    mocks.emitDeleteReceipt({ chat_id: "chat-1", success: false });

    await expect(deletion).resolves.toBeUndefined();
    expect(mocks.notificationStore.error).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalledWith(
      "[ChatSyncService:Senders] Failed to delete draft for chat chat-1:",
      expect.any(Error),
    );
    warnSpy.mockRestore();
  });

  // contract-test: supporting surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.sync.version-authoritative
  it("deletes a committed Team member draft with Team scope and receipt", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    mocks.chatDB.getRawChat.mockResolvedValue({ chat_id: "chat-1", team_id: "team-1", messages_v: 1,
      encrypted_draft_md: null, encrypted_draft_preview: null });
    const deletion = sendDeleteDraftImpl({ dispatchEvent: vi.fn() } as never, "chat-1");
    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "delete_draft", { chatId: "chat-1", team_id: "team-1" },
    ));
    mocks.emitDeleteReceipt({ chat_id: "chat-1", team_id: "team-1", success: true, draft_v: 4 });
    await expect(deletion).resolves.toBeUndefined();
    expect(mocks.chatDB.upsertRawChat).toHaveBeenCalledWith(expect.objectContaining({ cleared_draft_v: 4 }));
  });

  // contract-test: supporting surface=gui.web assertions=teams.collaboration.realtime-team-sync,drafts.sync.version-authoritative
  it("defers a first-send draft delete until the matching Team message commits", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    let storedChat = { chat_id: "chat-1", team_id: "team-1",
      messages_v: 1, team_chat_pending_commit: true, encrypted_draft_md: null, encrypted_draft_preview: null };
    mocks.chatDB.getRawChat.mockImplementation(async () => storedChat);
    mocks.chatDB.upsertRawChat.mockImplementation(async (chat) => { storedChat = chat; });
    await sendDeleteDraftImpl({ dispatchEvent: vi.fn() } as never, "chat-1");
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalled();
    expect(storedChat).toEqual(expect.objectContaining({ team_draft_pending_sync: "delete" }));
    storedChat = { ...storedChat, team_chat_pending_commit: false };
    const service = { sendDeleteDraft: vi.fn((id: string, context: DraftChatContext) =>
      sendDeleteDraftImpl(service as never, id, context)) };
    const promotion = promoteDeferredTeamDraft(service as never, "chat-1");
    await vi.waitFor(() => expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith(
      "delete_draft", expect.objectContaining({ chatId: "chat-1", team_id: "team-1" }),
    ));
    mocks.emitDeleteReceipt({ chat_id: "chat-1", success: true, draft_v: 4 });
    await promotion;
    expect(storedChat).toEqual(expect.objectContaining({ team_draft_pending_sync: undefined }));
    expect(storedChat).toEqual(expect.objectContaining({ cleared_draft_v: 4 }));
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,drafts.sync.version-authoritative
  it("persists the offline Team delete before clearing the local draft shell", async () => {
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
    mocks.state.currentStatus = "disconnected";
    const committedChat = { chat_id: "chat-1", team_id: "team-1", messages_v: 1, draft_v: 3 };
    mocks.chatDB.getRawChat.mockResolvedValueOnce(committedChat);
    let finishRead!: (chat: typeof committedChat) => void;
    mocks.chatDB.getRawChat.mockImplementationOnce(() => new Promise((resolve) => { finishRead = resolve; }));
    const queueOfflineChange = vi.fn(async (change) => {
      const row = await mocks.chatDB.getRawChat(change.chat_id);
      expect(row).toEqual(committedChat);
      expect(mocks.chatDB.clearCurrentUserChatDraft).not.toHaveBeenCalled();
    });
    const deletion = sendDeleteDraftImpl({ dispatchEvent: vi.fn(), queueOfflineChange } as never, "chat-1");
    await vi.waitFor(() => expect(queueOfflineChange).toHaveBeenCalledWith(expect.objectContaining({
      chat_id: "chat-1", team_id: "team-1", type: "delete_draft", version_before_edit: 3,
    })));
    expect(mocks.chatDB.clearCurrentUserChatDraft).not.toHaveBeenCalled();
    finishRead(committedChat);
    await deletion;
    expect(mocks.chatDB.clearCurrentUserChatDraft).toHaveBeenCalledWith("chat-1");
  });
});
