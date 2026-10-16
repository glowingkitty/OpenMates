/**
 * Deferred draft deletion survives a reload during post-admission context work.
 * The persisted message journal fences offline replay when tab-local holds vanish.
 * An unrelated offline change still travels while that exact chat is fenced.
 * Owner, Team and a newer encrypted local draft remain separate replay guards.
 * No browser socket or IndexedDB connection is needed for these ordering tests.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  owner: "user-1", api: "https://api.example/v1", pendingJournal: true,
  lookupFails: false, active: false, workspaceEpoch: 8,
  rows: [] as Array<Record<string, unknown>>,
  localDraft: null as string | null, editorUnsaved: false,
  sent: [] as Array<[string, unknown]>,
}));

vi.mock("../../stores/userProfile", () => ({
  userProfile: { subscribe: (run: (value: { user_id: string }) => void) => {
    run({ user_id: state.owner });
    return () => undefined;
  } },
}));
vi.mock("../../config/api", () => ({ getApiEndpoint: () => state.api }));
vi.mock("../db", () => ({ chatDB: {
  getTransaction: async () => {
    if (state.lookupFails) throw new Error("private journal lookup value");
    return { objectStore: () => ({ get: () => {
      const request = { result: state.pendingJournal
        ? { chat_id: "chat-1", pending_encrypted_turn_preflight_v1: "sealed" }
        : { chat_id: "chat-1" }, onsuccess: undefined as (() => void) | undefined };
      queueMicrotask(() => request.onsuccess?.());
      return request;
    } }) };
  },
  getOfflineChanges: async () => state.rows,
  getRawChat: async () => ({ chat_id: "chat-1", draft_v: state.localDraft ? 1 : 0,
    encrypted_draft_md: state.localDraft, encrypted_draft_preview: null }),
} }));
vi.mock("../draftContextDispatchBarrier", () => ({
  isDraftContextDispatchActive: () => state.active,
}));
vi.mock("../drafts/draftContext", () => ({
  resolveDraftChatContext: async () => ({ teamId: null, epoch: state.workspaceEpoch, committed: true }),
  isDraftChatContextCurrent: () => true,
}));
vi.mock("../drafts/draftState", () => ({ draftEditorUIState: {
  subscribe: (run: (value: { currentChatId: string; hasUnsavedChanges: boolean }) => void) => {
    run({ currentChatId: "chat-1", hasUnsavedChanges: state.editorUnsaved });
    return () => undefined;
  },
} }));
vi.mock("../websocketService", () => ({ webSocketService: {
  sendMessage: async (type: string, payload: unknown) => { state.sent.push([type, payload]); },
} }));
vi.mock("../../stores/websocketStatusStore", () => ({ websocketStatus: {
  subscribe: (run: (value: { status: string }) => void) => {
    run({ status: "connected" }); return () => undefined;
  },
} }));
vi.mock("../../stores/notificationStore", () => ({ notificationStore: { info: vi.fn() } }));

describe("durable deferred draft deletion", () => {
  beforeEach(() => {
    vi.resetModules();
    state.owner = "user-1";
    state.api = "https://api.example/v1";
    state.workspaceEpoch = 8;
    state.pendingJournal = true;
    state.lookupFails = false;
    state.active = false;
    state.rows = [];
    state.localDraft = null;
    state.editorUnsaved = false;
    state.sent = [];
  });

  // contract-test: direct surface=gui.web assertions=message-input.send.ownership,drafts.sync.version-authoritative
  it("keeps the delete behind context after a tab reload while replaying another change", async () => {
    const first = await import("../deferredDraftDeleteIntent");
    const change = { change_id: first.makeDeferredDraftDeleteId("turn-1", "message-1"),
      chat_id: "chat-1", type: "delete_draft", value: null, version_before_edit: 3 };
    state.rows.push(change, { change_id: "unrelated", chat_id: "chat-2", type: "title",
      value: "cipher", version_before_edit: 1 });
    first.holdDeferredDraftDelete(change.change_id);

    // A reload discards the hold, but not the IndexedDB intent or message journal.
    vi.resetModules();
    const { sendOfflineChangesImpl } = await import("../sendersSync");
    await sendOfflineChangesImpl();
    expect(state.sent).toHaveLength(1);
    expect((state.sent[0][1] as { changes: unknown[] }).changes).toEqual([state.rows[1]]);

    // Context completion clears the journal; a subsequent boot replays the intent.
    state.pendingJournal = false;
    state.workspaceEpoch = 22;
    state.rows = [change];
    vi.resetModules();
    const resumed = await import("../sendersSync");
    await resumed.sendOfflineChangesImpl();
    expect((state.sent[1][1] as { changes: unknown[] }).changes).toEqual([change]);
    const { consumeOfflineSyncBatch } = await import("../offlineSyncBatch");
    const batchId = (state.sent[1][1] as { batch_id: string }).batch_id;
    expect(consumeOfflineSyncBatch(batchId, [], { processed: 0, errors: 0, conflicts: 1 }))
      .toEqual({ successfulIds: [], retiredConflictIds: [change.change_id] });
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,drafts.sync.version-authoritative
  it("does not replay another account or API's intent or erase a fresh local draft", async () => {
    const first = await import("../deferredDraftDeleteIntent");
    const change = { change_id: first.makeDeferredDraftDeleteId("turn-1", "message-1"),
      chat_id: "chat-1", type: "delete_draft", value: null, version_before_edit: 3 };
    state.rows = [change];
    state.pendingJournal = false;
    state.owner = "user-2";
    const { sendOfflineChangesImpl } = await import("../sendersSync");
    await sendOfflineChangesImpl();
    expect(state.sent).toHaveLength(0);

    state.owner = "user-1";
    state.api = "https://other.example/v1";
    await sendOfflineChangesImpl();
    expect(state.sent).toHaveLength(0);

    state.api = "https://api.example/v1";
    state.editorUnsaved = true;
    await sendOfflineChangesImpl();
    expect(state.sent).toHaveLength(0);

    state.editorUnsaved = false;
    state.localDraft = "fresh-cipher";
    await sendOfflineChangesImpl();
    expect(state.sent).toHaveLength(0);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.sync.version-authoritative
  it("keeps a failed journal lookup queued and logs no private values", async () => {
    const helper = await import("../deferredDraftDeleteIntent");
    const change = { change_id: helper.makeDeferredDraftDeleteId("turn-1", "message-1"),
      chat_id: "chat-1", type: "delete_draft", value: null, version_before_edit: 3 };
    state.rows = [change, { change_id: "unrelated", chat_id: "chat-2", type: "title",
      value: "cipher", version_before_edit: 1 }];
    state.lookupFails = true;
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    try {
      const { sendOfflineChangesImpl } = await import("../sendersSync");
      await sendOfflineChangesImpl();
      expect((state.sent[0][1] as { changes: unknown[] }).changes).toEqual([state.rows[1]]);
      expect(warning).toHaveBeenCalledWith(
        "[ChatSyncService:Senders] Deferred draft journal lookup unavailable",
      );
    } finally { warning.mockRestore(); }
  });
});
