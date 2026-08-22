// frontend/packages/ui/src/services/__tests__/sendersSyncTeamContext.test.ts
// Verifies older-chat sync requests carry the exact active Team context.
// The backend uses this scope to bypass Personal cache indexes, while the
// echoed epoch lets the browser reject late responses after context switches.
// Spec: docs/specs/teams-v1/spec.yml

import { beforeEach, describe, expect, it, vi } from "vitest";
import { activeTeamContext } from "../../stores/teamStore";

const { sendMessage } = vi.hoisted(() => ({ sendMessage: vi.fn() }));

vi.mock("../websocketService", () => ({
  webSocketService: { sendMessage },
}));

import {
  sendLoadMoreChatsImpl,
  sendSyncMetadataChatsImpl,
} from "../sendersSync";

describe("sendersSync Team context", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
});
