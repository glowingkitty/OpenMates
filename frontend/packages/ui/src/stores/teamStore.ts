import { derived, get, writable } from 'svelte/store';
import type { TeamViewModel } from '../services/teamService';

/**
 * Writable store to track whether team features are enabled in settings.
 */
export const teamEnabled = writable<boolean>(true);

const ACTIVE_TEAM_ID_STORAGE_KEY = 'openmates:active-team-id';
export const TEAMS_UPDATED_EVENT = 'openmates:teams-updated';
export const TEAM_CONTEXT_CHANGED_EVENT = 'openmates:team-context-changed';

export interface TeamContextSnapshot {
  team: TeamViewModel | null;
  teamId: string | null;
  epoch: number;
}

function readActiveTeamId(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(ACTIVE_TEAM_ID_STORAGE_KEY) || null;
}

const initialTeamId = readActiveTeamId();
export const activeTeamContext = writable<TeamContextSnapshot>({
  team: null,
  teamId: initialTeamId,
  epoch: 0,
});
export const activeTeamId = derived(activeTeamContext, (context) => context.teamId);
export const activeTeam = derived(activeTeamContext, (context) => context.team);

activeTeamContext.subscribe(({ teamId }) => {
  if (typeof window === 'undefined') return;
  if (teamId) {
    window.localStorage.setItem(ACTIVE_TEAM_ID_STORAGE_KEY, teamId);
  } else {
    window.localStorage.removeItem(ACTIVE_TEAM_ID_STORAGE_KEY);
  }
});

export function setActiveTeamContext(team: TeamViewModel | null): void {
  const current = get(activeTeamContext);
  const teamId = team?.team_id ?? null;
  const contextChanged = current.teamId !== teamId;
  const next = {
    team,
    teamId,
    epoch: contextChanged ? current.epoch + 1 : current.epoch,
  };
  activeTeamContext.set(next);
  if (contextChanged && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent<TeamContextSnapshot>(TEAM_CONTEXT_CHANGED_EVENT, {
      detail: next,
    }));
  }
}

export function getActiveTeamContextSnapshot(): TeamContextSnapshot {
  return get(activeTeamContext);
}

export function isActiveTeamContext(teamId: string | null, epoch?: number): boolean {
  const active = get(activeTeamContext);
  return active.teamId === teamId && (epoch === undefined || active.epoch === epoch);
}

export function notifyTeamsUpdated(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(TEAMS_UPDATED_EVENT));
}
