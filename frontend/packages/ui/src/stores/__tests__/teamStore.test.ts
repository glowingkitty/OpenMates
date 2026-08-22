// frontend/packages/ui/src/stores/__tests__/teamStore.test.ts
// Verifies the atomic browser context boundary for Personal and Team data.
// A context switch must update the selected Team and epoch together so chat
// sync can reject stale responses without briefly exposing another context.
// Spec: docs/specs/teams-v1/spec.yml

import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import {
  activeTeamContext,
  setActiveTeamContext,
  TEAM_CONTEXT_CHANGED_EVENT,
} from "../teamStore";
import type { TeamViewModel } from "../../services/teamService";

function team(teamId: string): TeamViewModel {
  return {
    team_id: teamId,
    name: teamId,
    description: "",
    role: "owner",
    status: "active",
    profileImageMetadata: {},
    zeroBalance: 0,
    createdAt: 0,
    updatedAt: 0,
    encrypted: { team_id: teamId },
  };
}

describe("teamStore", () => {
  beforeEach(() => {
    setActiveTeamContext(null);
    window.localStorage.clear();
  });

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local
  it("publishes one atomic snapshot for each logical context switch", () => {
    const listener = vi.fn();
    window.addEventListener(TEAM_CONTEXT_CHANGED_EVENT, listener);
    const startingEpoch = get(activeTeamContext).epoch;

    setActiveTeamContext(team("team-a"));

    expect(get(activeTeamContext)).toMatchObject({
      teamId: "team-a",
      epoch: startingEpoch + 1,
      team: { team_id: "team-a" },
    });
    expect(listener).toHaveBeenCalledTimes(1);
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toMatchObject({
      teamId: "team-a",
      epoch: startingEpoch + 1,
    });

    window.removeEventListener(TEAM_CONTEXT_CHANGED_EVENT, listener);
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
  it("hydrates the selected Team without creating a false context epoch", () => {
    setActiveTeamContext(team("team-a"));
    const selectedEpoch = get(activeTeamContext).epoch;

    setActiveTeamContext({ ...team("team-a"), name: "Hydrated team" });

    expect(get(activeTeamContext)).toMatchObject({
      teamId: "team-a",
      epoch: selectedEpoch,
      team: { name: "Hydrated team" },
    });
  });
});
