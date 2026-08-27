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
    upsertRawChat: vi.fn().mockResolvedValue(undefined),
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

describe("sendUpdateDraftImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.state.handlers.clear();
    mocks.state.statusSubscribers.splice(0);
    mocks.state.currentStatus = "connected";
    mocks.webSocketService.sendMessage.mockResolvedValue(undefined);
    mocks.chatDB.getChat.mockResolvedValue({ chat_id: "chat-1", draft_v: 3 });
    mocks.chatDB.clearCurrentUserChatDraft.mockResolvedValue({ chat_id: "chat-1" });
    mocks.chatDB.getRawChat.mockResolvedValue({
      chat_id: "chat-1",
      encrypted_draft_md: null,
      encrypted_draft_preview: null,
    });
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("resolves after the matching draft update receipt arrives", async () => {
    const receipt = sendUpdateDraftImpl({} as never, "chat-1", "cipher-md", "cipher-preview", 1);

    expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith("update_draft", {
      chat_id: "chat-1",
      encrypted_draft_md: "cipher-md",
      encrypted_draft_preview: "cipher-preview",
      draft_v: 1,
    });

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
});

describe("sendDeleteDraftImpl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.state.handlers.clear();
    mocks.state.statusSubscribers.splice(0);
    mocks.state.currentStatus = "connected";
    mocks.webSocketService.sendMessage.mockResolvedValue(undefined);
    mocks.chatDB.getChat.mockResolvedValue({ chat_id: "chat-1", draft_v: 3 });
    mocks.chatDB.clearCurrentUserChatDraft.mockResolvedValue({ chat_id: "chat-1" });
    mocks.chatDB.getRawChat.mockResolvedValue({
      chat_id: "chat-1",
      encrypted_draft_md: null,
      encrypted_draft_preview: null,
    });
  });

  // contract-test: supporting surface=gui.web assertions=drafts.persistence.local-first-encrypted
  it("logs failed background draft deletion without showing a user error notification", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const deletion = sendDeleteDraftImpl({} as never, "chat-1");

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
});
