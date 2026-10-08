import { derived, get, writable } from 'svelte/store';
import type { TeamViewModel } from '../services/teamService';
import { invalidateWorkspaceCaches } from '../services/workspaceCacheLifecycle';
import { userProfile } from './userProfile';

/**
 * Writable store to track whether team features are enabled in settings.
 */
export const teamEnabled = writable<boolean>(true);

const ACTIVE_TEAM_ID_STORAGE_KEY = 'openmates:active-team-id:v2';
const TEAM_RECENT_STORAGE_KEY = 'openmates:recent-teams:v1';
export const TEAMS_UPDATED_EVENT = 'openmates:teams-updated';
export const TEAM_CONTEXT_CHANGED_EVENT = 'openmates:team-context-changed';

export interface TeamContextSnapshot {
  team: TeamViewModel | null;
  teamId: string | null;
  epoch: number;
}

let currentAccountId: string | null = null;

function scopedStorageKey(prefix: string): string | null {
  return currentAccountId ? `${prefix}:${currentAccountId}` : null;
}

function readActiveTeamId(): string | null {
  const key = scopedStorageKey(ACTIVE_TEAM_ID_STORAGE_KEY);
  if (!key || typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(key) || null;
  } catch {
    // Storage preferences are optional; account boundaries must still complete.
    return null;
  }
}

currentAccountId = get(userProfile).user_id;
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
  const key = scopedStorageKey(ACTIVE_TEAM_ID_STORAGE_KEY);
  if (!key) return;
  try {
    if (teamId) {
      window.localStorage.setItem(key, teamId);
    } else {
      window.localStorage.removeItem(key);
    }
  } catch {
    // A blocked or full store must not interrupt cache invalidation and events.
  }
});

/** Account changes discard decrypted Team details before any new workspace can render. */
userProfile.subscribe((profile) => {
  const accountId = profile.user_id;
  if (accountId === currentAccountId) return;
  currentAccountId = accountId;
  const current = get(activeTeamContext);
  const teamId = readActiveTeamId();
  const next = { team: null, teamId, epoch: current.epoch + 1 };
  activeTeamContext.set(next);
  invalidateWorkspaceCaches();
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent<TeamContextSnapshot>(TEAM_CONTEXT_CHANGED_EVENT, { detail: next }));
  }
});

/** Recent Team IDs are local UI preferences; membership is always filtered by the current list. */
export function orderTeamsByRecent(teams: TeamViewModel[]): TeamViewModel[] {
  const key = scopedStorageKey(TEAM_RECENT_STORAGE_KEY);
  if (!key || typeof window === 'undefined') return teams;
  let recent: string[] = [];
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(key) ?? '[]');
    if (Array.isArray(parsed)) recent = parsed.filter((id): id is string => typeof id === 'string');
  } catch { /* A corrupt preference cannot affect Team membership. */ }
  const order = new Map(recent.map((id, index) => [id, index]));
  return [...teams].sort((a, b) => (order.get(a.team_id) ?? Infinity) - (order.get(b.team_id) ?? Infinity));
}

function rememberTeam(teamId: string): void {
  const key = scopedStorageKey(TEAM_RECENT_STORAGE_KEY);
  if (!key || typeof window === 'undefined') return;
  try {
    let recent: string[] = [];
    const parsed: unknown = JSON.parse(window.localStorage.getItem(key) ?? '[]');
    if (Array.isArray(parsed)) recent = parsed.filter((id): id is string => typeof id === 'string');
    window.localStorage.setItem(key, JSON.stringify([teamId, ...recent.filter((id) => id !== teamId)].slice(0, 20)));
  } catch { /* A local preference cannot interrupt a context switch. */ }
}

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
  if (teamId && contextChanged) rememberTeam(teamId);
  if (contextChanged) invalidateWorkspaceCaches();
  if (contextChanged && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent<TeamContextSnapshot>(TEAM_CONTEXT_CHANGED_EVENT, {
      detail: next,
    }));
  }
}

/** Keep the saved Team through startup until auth and feature availability are known. */
export function reconcileTeamContextAvailability(
  auth: { isInitialized: boolean; isAuthenticated: boolean },
  features: { initialized: boolean; disabledById: Record<string, true> | null },
): 'pending' | 'available' | 'unavailable' {
  if (!auth.isInitialized) return 'pending';
  if (!auth.isAuthenticated) {
    setActiveTeamContext(null);
    return 'unavailable';
  }
  if (!features.initialized) return 'pending';
  if (features.disabledById?.['platform:teams'] === true) {
    setActiveTeamContext(null);
    return 'unavailable';
  }
  return 'available';
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
