import { beforeEach, describe, expect, it } from "vitest";
import { get } from "svelte/store";
import { activeTeamContext } from "../../stores/teamStore";
import { userProfile } from "../../stores/userProfile";
import { beginOfflineSyncBatch, consumeOfflineSyncBatch } from "../offlineSyncBatch";

describe("offline draft sync batch acknowledgements", () => {
  beforeEach(() => {
    userProfile.update((profile) => ({ ...profile, user_id: "member-1" }));
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 1 });
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,drafts.sync.version-authoritative
  it("removes only successful submitted changes and ignores old workspace receipts", () => {
    const first = beginOfflineSyncBatch(["team-draft", "team-delete"]);
    expect(first).toBeTruthy();
    expect(consumeOfflineSyncBatch(first!, ["team-draft", "unsent-personal"])).toEqual(["team-draft"]);

    const second = beginOfflineSyncBatch(["team-delete"]);
    activeTeamContext.set({ team: null, teamId: "team-2", epoch: 2 });
    expect(consumeOfflineSyncBatch(second!, ["team-delete"])).toBeNull();

    const third = beginOfflineSyncBatch(["other-team-draft"]);
    expect(consumeOfflineSyncBatch(second!, ["team-delete"])).toBeNull();
    expect(consumeOfflineSyncBatch(third!, ["other-team-draft"])).toEqual(["other-team-draft"]);
    expect(get(activeTeamContext).teamId).toBe("team-2");
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,drafts.sync.version-authoritative
  it("does not acknowledge a prior account's queued draft after account change", () => {
    const oldBatch = beginOfflineSyncBatch(["old-account-draft"]);
    userProfile.update((profile) => ({ ...profile, user_id: "member-2" }));
    expect(consumeOfflineSyncBatch(oldBatch!, ["old-account-draft"])).toBeNull();
  });
});
