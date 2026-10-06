// frontend/packages/ui/src/stores/__tests__/teamStore.test.ts
// Verifies the atomic browser context boundary for Personal and Team data.
// A context switch must update the selected Team and epoch together so chat
// sync can reject stale responses without briefly exposing another context.
// Spec: docs/specs/teams-v1/spec.yml

import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import {
  activeTeamContext,
  orderTeamsByRecent,
  setActiveTeamContext,
  TEAM_CONTEXT_CHANGED_EVENT,
} from "../teamStore";
import type { TeamViewModel } from "../../services/teamService";
import { userProfile } from "../userProfile";

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
    vi.restoreAllMocks();
    userProfile.update(profile => ({ ...profile, user_id: null }));
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

  // contract-test: direct surface=gui.web assertions=teams.context.full-switch-local
  it("keeps Team recency and selected context within the current account", () => {
    userProfile.update(profile => ({ ...profile, user_id: 'account-a' }));
    setActiveTeamContext(team('team-a'));
    setActiveTeamContext(team('team-b'));
    expect(orderTeamsByRecent([team('team-a'), team('team-b')]).map(value => value.team_id))
      .toEqual(['team-b', 'team-a']);

    userProfile.update(profile => ({ ...profile, user_id: 'account-b' }));
    expect(get(activeTeamContext)).toMatchObject({ teamId: null, team: null });
    expect(orderTeamsByRecent([team('team-a'), team('team-b')]).map(value => value.team_id))
      .toEqual(['team-a', 'team-b']);

    userProfile.update(profile => ({ ...profile, user_id: 'account-a' }));
    expect(get(activeTeamContext)).toMatchObject({ teamId: 'team-b', team: null });
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
  it("completes a context switch when local storage refuses writes", () => {
    userProfile.update(profile => ({ ...profile, user_id: 'account-a' }));
    const startingEpoch = get(activeTeamContext).epoch;
    const listener = vi.fn();
    window.addEventListener(TEAM_CONTEXT_CHANGED_EVENT, listener);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Storage blocked', 'SecurityError');
    });

    try {
      expect(() => setActiveTeamContext(team('team-a'))).not.toThrow();
      expect(get(activeTeamContext)).toMatchObject({ teamId: 'team-a', epoch: startingEpoch + 1 });
      expect(listener).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener(TEAM_CONTEXT_CHANGED_EVENT, listener);
    }
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
  it("clears the prior account context when local storage refuses reads", () => {
    userProfile.update(profile => ({ ...profile, user_id: 'account-a' }));
    setActiveTeamContext(team('team-a'));
    const startingEpoch = get(activeTeamContext).epoch;
    const listener = vi.fn();
    window.addEventListener(TEAM_CONTEXT_CHANGED_EVENT, listener);
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('Storage blocked', 'SecurityError');
    });

    try {
      expect(() => userProfile.update(profile => ({ ...profile, user_id: 'account-b' }))).not.toThrow();
      expect(get(activeTeamContext)).toMatchObject({ team: null, teamId: null, epoch: startingEpoch + 1 });
      expect(listener).toHaveBeenCalledOnce();
    } finally {
      window.removeEventListener(TEAM_CONTEXT_CHANGED_EVENT, listener);
    }
  });
});
