// frontend/packages/ui/src/services/__tests__/sendersSyncTeamContext.test.ts
// Verifies older-chat sync requests carry the exact active Team context.
// The backend uses this scope to bypass Personal cache indexes, while the
// echoed epoch lets the browser reject late responses after context switches.
// Spec: docs/specs/teams-v1/spec.yml

import { beforeEach, describe, expect, it, vi } from "vitest";
import { activeTeamContext } from "../../stores/teamStore";
import { userProfile } from "../../stores/userProfile";
import { consumeOfflineSyncBatch } from "../offlineSyncBatch";
import { websocketStatus } from "../../stores/websocketStatusStore";
import { invalidateWorkspaceCaches } from "../workspaceCacheLifecycle";

const { sendMessage, getOfflineChanges, getRawChat, addOfflineChange, info } = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  getOfflineChanges: vi.fn(),
  getRawChat: vi.fn(),
  addOfflineChange: vi.fn(),
  info: vi.fn(),
}));

vi.mock("../websocketService", () => ({
  webSocketService: { sendMessage },
}));
vi.mock("../db", () => ({ chatDB: { getOfflineChanges, getRawChat, addOfflineChange } }));
vi.mock("../../stores/notificationStore", () => ({
  notificationStore: { info },
}));

import {
  sendLoadMoreChatsImpl,
  queueOfflineChangeImpl,
  sendOfflineChangesImpl,
  sendSyncMetadataChatsImpl,
} from "../sendersSync";

describe("sendersSync Team context", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    websocketStatus.setStatus("connected");
    userProfile.update((profile) => ({ ...profile, user_id: "user-1" }));
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 8 });
    getRawChat.mockImplementation(async (chatId: string) => ({
      chat_id: chatId, team_id: "team-1", messages_v: 1,
    }));
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local
  it("scopes older-chat pagination to the active Team epoch", async () => {
    await sendLoadMoreChatsImpl({} as never, 100, 20);

    expect(sendMessage).toHaveBeenCalledWith("load_more_chats", {
      offset: 100,
      limit: 20,
      team_id: "team-1",
      context_epoch: 8,
    });
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local
  it("scopes metadata-only chat sync to the active Team epoch", async () => {
    await sendSyncMetadataChatsImpl({} as never, ["chat-1"]);

    expect(sendMessage).toHaveBeenCalledWith("sync_metadata_chats", {
      existing_chat_ids: ["chat-1"],
      team_id: "team-1",
      context_epoch: 8,
    });
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases,teams.context.full-switch-local
  it("sends a versioned Team offline batch bound to its account and epoch", async () => {
    const changes = [{ change_id: "change-1", chat_id: "chat-1", team_id: "team-1",
      type: "draft", value: "cipher", version_before_edit: 2 }];
    getOfflineChanges.mockResolvedValue(changes);
    sendMessage.mockResolvedValue(undefined);

    await sendOfflineChangesImpl();

    expect(sendMessage).toHaveBeenCalledWith("sync_offline_changes", {
      changes, batch_id: expect.any(String),
    });
    const batchId = sendMessage.mock.calls[0][1].batch_id as string;
    expect(info).toHaveBeenCalledWith("Attempting to sync 1 offline change(s)...");
    userProfile.update((profile) => ({ ...profile, user_id: "user-2" }));
    expect(consumeOfflineSyncBatch(batchId, ["change-1"])).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("cancels its versioned batch when replay send fails", async () => {
    getOfflineChanges.mockResolvedValue([{ change_id: "change-1", chat_id: "chat-1",
      team_id: "team-1", type: "draft", value: "cipher", version_before_edit: 2 }]);
    sendMessage.mockRejectedValue(new Error("socket closed"));

    await expect(sendOfflineChangesImpl()).rejects.toThrow("socket closed");

    const batchId = sendMessage.mock.calls[0][1].batch_id as string;
    expect(consumeOfflineSyncBatch(batchId, ["change-1"])).toBeNull();
    expect(info).toHaveBeenCalledWith("Attempting to sync 1 offline change(s)...");
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("saves a scoped offline draft change with a queue notice", async () => {
    addOfflineChange.mockResolvedValue(undefined);

    await queueOfflineChangeImpl({} as never, { chat_id: "chat-1", team_id: "team-1",
      type: "draft", value: "cipher", version_before_edit: 2 });

    expect(addOfflineChange).toHaveBeenCalledWith(
      expect.objectContaining({ change_id: expect.any(String), chat_id: "chat-1",
        team_id: "team-1", type: "draft", version_before_edit: 2 }),
    );
    expect(info).toHaveBeenCalledWith("Change saved offline. Will sync when reconnected.", 3000);
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local
  it("rejects a queued Team draft when the workspace epoch changes during lookup", async () => {
    let finishLookup!: (chat: unknown) => void;
    getRawChat.mockReturnValueOnce(new Promise((resolve) => { finishLookup = resolve; }));
    const pending = queueOfflineChangeImpl({} as never, { chat_id: "chat-1", team_id: "team-1",
      type: "draft", value: "cipher", version_before_edit: 2 });
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 9 });
    finishLookup({ chat_id: "chat-1", team_id: "team-1", messages_v: 1 });
    await expect(pending).rejects.toThrow("Draft workspace changed");
    expect(addOfflineChange).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,drafts.sync.version-authoritative
  it.each(["account", "Team epoch", "cache", "socket"])("retains the whole batch when %s changes after an earlier row lookup", async (kind) => {
    getOfflineChanges.mockResolvedValue([1, 2].map((order) => ({ change_id: `change-${order}`,
      chat_id: "chat-1", team_id: "team-1", type: "draft", value: `cipher-${order}`,
      version_before_edit: order, queue_order: order })));
    let finish!: (value: unknown) => void;
    getRawChat.mockResolvedValueOnce({ chat_id: "chat-1", team_id: "team-1", messages_v: 1 });
    getRawChat.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    const sending = sendOfflineChangesImpl();
    await vi.waitFor(() => expect(getRawChat).toHaveBeenCalledTimes(2));
    if (kind === "account") userProfile.update((profile) => ({ ...profile, user_id: "user-2" }));
    if (kind === "Team epoch") activeTeamContext.set({ team: null, teamId: "team-1", epoch: 9 });
    if (kind === "cache") invalidateWorkspaceCaches();
    if (kind === "socket") { websocketStatus.setStatus("disconnected"); websocketStatus.setStatus("connected"); }
    finish({ chat_id: "chat-1", team_id: "team-1", messages_v: 1 });
    await sending;
    expect(sendMessage).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
  it("sends durable edit order rather than UUID key order and keeps encrypted previews", async () => {
    const changes = [3, 2, 1].map((order) => ({ change_id: `change-${4 - order}`,
      chat_id: "chat-1", team_id: "team-1", type: "draft", value: `cipher-${order}`,
      encrypted_draft_preview: `preview-${order}`, version_before_edit: order, queue_order: order }));
    getOfflineChanges.mockResolvedValue(changes);
    sendMessage.mockResolvedValue(undefined);
    await sendOfflineChangesImpl();
    const payload = sendMessage.mock.calls[0][1];
    expect(payload.changes.map((change: { queue_order: number }) => change.queue_order)).toEqual([1, 2, 3]);
    expect(payload.changes[2].encrypted_draft_preview).toBe("preview-3");
    consumeOfflineSyncBatch(payload.batch_id, changes.map((change) => change.change_id));
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,drafts.persistence.local-first-encrypted
  it.each(["account", "cache"])("does not enqueue an old draft after %s changes during lookup", async (kind) => {
    let finish!: (value: unknown) => void;
    getRawChat.mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    const queuing = queueOfflineChangeImpl({} as never, { chat_id: "chat-1", team_id: "team-1",
      type: "draft", value: "old-account-cipher", version_before_edit: 2 });
    if (kind === "account") userProfile.update((profile) => ({ ...profile, user_id: "user-2" }));
    else invalidateWorkspaceCaches();
    finish({ chat_id: "chat-1", team_id: "team-1", messages_v: 1 });
    if (kind === "account") await expect(queuing).rejects.toThrow("Draft workspace changed");
    else await queuing;
    expect(addOfflineChange).not.toHaveBeenCalled();
    expect(info).not.toHaveBeenCalled();
  });
});
