import { writable } from 'svelte/store';
import type { TeamViewModel } from '../services/teamService';

/**
 * Writable store to track whether team features are enabled in settings.
 */
export const teamEnabled = writable<boolean>(true);

const ACTIVE_TEAM_ID_STORAGE_KEY = 'openmates:active-team-id';
export const TEAMS_UPDATED_EVENT = 'openmates:teams-updated';

function readActiveTeamId(): string | null {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(ACTIVE_TEAM_ID_STORAGE_KEY) || null;
}

export const activeTeamId = writable<string | null>(readActiveTeamId());
export const activeTeam = writable<TeamViewModel | null>(null);

activeTeamId.subscribe((teamId) => {
  if (typeof window === 'undefined') return;
  if (teamId) {
    window.localStorage.setItem(ACTIVE_TEAM_ID_STORAGE_KEY, teamId);
  } else {
    window.localStorage.removeItem(ACTIVE_TEAM_ID_STORAGE_KEY);
  }
});

export function setActiveTeamContext(team: TeamViewModel | null): void {
  activeTeam.set(team);
  activeTeamId.set(team?.team_id ?? null);
}

export function notifyTeamsUpdated(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(TEAMS_UPDATED_EVENT));
}
