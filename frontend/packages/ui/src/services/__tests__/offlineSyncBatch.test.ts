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

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
  it("retires the sole opted-in stale delete when every other row succeeds", () => {
    const id = beginOfflineSyncBatch(["accepted-draft", "deferred-delete"], ["deferred-delete"]);
    expect(consumeOfflineSyncBatch(id!, ["accepted-draft"], {
      processed: 1, errors: 0, conflicts: 1,
    })).toEqual({ successfulIds: ["accepted-draft"], retiredConflictIds: ["deferred-delete"] });

    const single = beginOfflineSyncBatch(["deferred-delete"], ["deferred-delete"]);
    expect(consumeOfflineSyncBatch(single!, [], {
      processed: 0, errors: 0, conflicts: 1,
    })).toEqual({ successfulIds: [], retiredConflictIds: ["deferred-delete"] });
  });

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative,teams.context.full-switch-local
  it("keeps ambiguous, ordinary, unknown and stale-scope conflicts queued", () => {
    const cases = [
      { ids: ["ordinary-title", "deferred-delete"], opt: ["deferred-delete"],
        successes: ["ordinary-title"], counts: { processed: 1, errors: 1, conflicts: 1 } },
      { ids: ["ordinary-title", "deferred-delete"], opt: ["deferred-delete"],
        successes: [], counts: { processed: 0, errors: 0, conflicts: 1 } },
      { ids: ["ordinary-title", "deferred-delete"], opt: ["deferred-delete"],
        successes: ["ordinary-title", "outsider"], counts: { processed: 1, errors: 0, conflicts: 1 } },
      { ids: ["ordinary-title", "deferred-delete"], opt: ["deferred-delete"],
        successes: ["ordinary-title", "ordinary-title"], counts: { processed: 1, errors: 0, conflicts: 1 } },
      { ids: ["ordinary-title"], opt: ["deferred-delete"],
        successes: [], counts: { processed: 0, errors: 0, conflicts: 1 } },
    ];
    for (const sample of cases) {
      const id = beginOfflineSyncBatch(sample.ids, sample.opt);
      expect(consumeOfflineSyncBatch(id!, sample.successes, sample.counts)?.retiredConflictIds).toEqual([]);
    }

    const accountBatch = beginOfflineSyncBatch(["deferred-delete"], ["deferred-delete"]);
    userProfile.update((profile) => ({ ...profile, user_id: "member-2" }));
    expect(consumeOfflineSyncBatch(accountBatch!, [], {
      processed: 0, errors: 0, conflicts: 1,
    })).toBeNull();
    userProfile.update((profile) => ({ ...profile, user_id: "member-1" }));
    const teamBatch = beginOfflineSyncBatch(["deferred-delete"], ["deferred-delete"]);
    activeTeamContext.set({ team: null, teamId: "team-1", epoch: 2 });
    expect(consumeOfflineSyncBatch(teamBatch!, [], {
      processed: 0, errors: 0, conflicts: 1,
    })).toBeNull();

    const freshBatch = beginOfflineSyncBatch(["deferred-delete"], ["deferred-delete"]);
    expect(consumeOfflineSyncBatch("stale-batch", [], {
      processed: 0, errors: 0, conflicts: 1,
    })).toBeNull();
    expect(consumeOfflineSyncBatch(freshBatch!, [], {
      processed: 0, errors: 0, conflicts: 1,
    })?.retiredConflictIds).toEqual(["deferred-delete"]);
  });
});
