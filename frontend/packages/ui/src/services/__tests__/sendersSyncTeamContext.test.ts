// frontend/packages/ui/src/services/__tests__/sendersSyncTeamContext.test.ts
// Verifies older-chat sync requests carry the exact active Team context.
// The backend uses this scope to bypass Personal cache indexes, while the
// echoed epoch lets the browser reject late responses after context switches.
// Spec: docs/specs/teams-v1/spec.yml

import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { activeTeamContext } from "../../stores/teamStore";
import { chatSyncActivity } from "../../stores/chatSyncActivityStore";

const { sendMessage, getOfflineChanges, addOfflineChange, info } = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  getOfflineChanges: vi.fn(),
  addOfflineChange: vi.fn(),
  info: vi.fn(),
}));

vi.mock("../websocketService", () => ({
  webSocketService: { sendMessage },
}));
vi.mock("../db", () => ({ chatDB: { getOfflineChanges, addOfflineChange } }));
vi.mock("../../stores/websocketStatusStore", () => ({
  websocketStatus: {
    subscribe: (run: (value: { status: string }) => void) => {
      run({ status: "connected" });
      return () => undefined;
    },
  },
}));
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
    chatSyncActivity.clear();
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 8 });
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

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("tracks a real offline replay send without a progress card", async () => {
    const changes = [{ change_id: "change-1" }];
    getOfflineChanges.mockResolvedValue(changes);
    sendMessage.mockResolvedValue(undefined);

    await sendOfflineChangesImpl();

    expect(sendMessage).toHaveBeenCalledWith("sync_offline_changes", { changes });
    expect(get(chatSyncActivity).active).toBe(true);
    expect(info).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("ends offline activity when the replay send fails", async () => {
    getOfflineChanges.mockResolvedValue([{ change_id: "change-1" }]);
    sendMessage.mockRejectedValue(new Error("socket closed"));

    await expect(sendOfflineChangesImpl()).rejects.toThrow("socket closed");

    expect(get(chatSyncActivity).active).toBe(false);
    expect(info).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("saves an offline change without a routine card", async () => {
    addOfflineChange.mockResolvedValue(undefined);

    await queueOfflineChangeImpl({} as never, { type: "update_title" } as never);

    expect(addOfflineChange).toHaveBeenCalledWith(
      expect.objectContaining({ change_id: expect.any(String) }),
    );
    expect(info).not.toHaveBeenCalled();
    expect(get(chatSyncActivity).active).toBe(false);
  });
});
