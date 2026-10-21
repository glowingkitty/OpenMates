import { get } from 'svelte/store';
import { appsResultRequestFields } from '../utils/appsResultRequestFields';
import { getApiEndpoint } from '../config/api';
// Read state without loading authentication actions during shared embed SSR.
import { authStore } from '../stores/authState';
import { userProfile } from '../stores/userProfile';
import { activeTeamContext } from '../stores/teamStore';
import { notificationStore } from '../stores/notificationStore';
import { text } from '../i18n/translations';
import type { AppsRequestContext } from './appsWorkspaceRequestService';

export interface AppsSavedSearch {
  id: string;
  skill_id: string;
  parameters: Record<string, unknown>;
  query?: string;
  title?: string;
  saved_at: number;
}
export interface AppsRecommendation {
  id: string;
  skill_id: string;
  created_at: number;
  expires_at: number;
  result: Record<string, unknown>;
  input?: Record<string, unknown>;
  request_text?: string;
  title?: string;
}
export interface AppsLibrary {
  app_id: string;
  daily_searches_enabled: boolean;
  saved_searches: AppsSavedSearch[];
  recommendations: AppsRecommendation[];
  recommendations_expires_at?: number | null;
  first_save?: boolean;
}

export const emptyAppsLibrary = (appId: string): AppsLibrary => ({
  app_id: appId, daily_searches_enabled: true, saved_searches: [], recommendations: [],
});

let ownerGeneration = 0;
let lastOwner = { userId: get(userProfile).user_id, authenticated: get(authStore).isAuthenticated,
  teamId: get(activeTeamContext).teamId, epoch: get(activeTeamContext).epoch };
function trackOwner(): void {
  const team = get(activeTeamContext);
  const next = { userId: get(userProfile).user_id, authenticated: get(authStore).isAuthenticated,
    teamId: team.teamId, epoch: team.epoch };
  if (Object.keys(next).some(key => next[key as keyof typeof next] !== lastOwner[key as keyof typeof lastOwner])) ownerGeneration++;
  lastOwner = next;
}
userProfile.subscribe(trackOwner);
authStore.subscribe(trackOwner);
activeTeamContext.subscribe(trackOwner);

async function libraryRequest(appId: string, suffix: string, teamId?: string, body?: Record<string, unknown>, signal?: AbortSignal): Promise<AppsLibrary> {
  const profile = get(userProfile);
  const userId = profile.user_id;
  if (!get(authStore).isAuthenticated || !userId) throw new Error('signup_required');
  const owner = ownerGeneration;
  if ((get(activeTeamContext).teamId ?? undefined) !== teamId) throw new Error('account_context_changed');
  const params = new URLSearchParams(teamId ? { team_id: teamId } : {});
  const url = getApiEndpoint(`/v1/apps/workspace/library/${encodeURIComponent(appId)}${suffix}${!body && params.size ? `?${params}` : ''}`);
  const response = await fetch(url, {
    credentials: 'include', signal, cache: 'no-store',
    ...(body ? { method: suffix === '/settings' ? 'PATCH' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...body, expected_user_id: userId, ...(teamId ? { team_id: teamId } : {}) }) } : {}),
  });
  const result = await response.json();
  if (owner !== ownerGeneration || get(userProfile).user_id !== userId || !get(authStore).isAuthenticated ||
      (get(activeTeamContext).teamId ?? undefined) !== teamId) throw new Error('account_context_changed');
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'library_unavailable');
  return { ...result, recommendations: freshAppsRecommendations(result.recommendations ?? []) };
}

/** Expiry is checked in the server as well; sleeping tabs also filter on wake. */
export function freshAppsRecommendations(items: AppsRecommendation[], now = Date.now()): AppsRecommendation[] {
  const seconds = Math.floor(now / 1000);
  return items.filter(item => item.created_at <= seconds && item.created_at > seconds - 86400 && item.expires_at > seconds);
}

export const getAppsLibrary = (appId: string, teamId?: string, signal?: AbortSignal) => libraryRequest(appId, '', teamId, undefined, signal);
export async function getPublicAppsRecommendations(appId: string, signal?: AbortSignal): Promise<AppsRecommendation[]> {
  const language = typeof navigator !== 'undefined' && navigator.language.startsWith('de') ? 'de' : 'en';
  const response = await fetch(getApiEndpoint('/v1/apps/workspace/public/' + encodeURIComponent(appId) + '?language=' + language), {
    credentials: 'omit', cache: 'no-store', signal,
  });
  if (!response.ok) return [];
  const result = await response.json();
  return freshAppsRecommendations(Array.isArray(result.recommendations) ? result.recommendations : []);
}
export const saveAppsSearch = (appId: string, skillId: string, parameters: Record<string, unknown>, query: string, teamId?: string) =>
  libraryRequest(appId, '/saved-searches', teamId, { skill_id: skillId, parameters, query, title: query.slice(0, 200) });
export const setAppsDailySearches = (appId: string, enabled: boolean, teamId?: string) =>
  libraryRequest(appId, '/settings', teamId, { daily_searches_enabled: enabled });

/** Match native skill arguments, independent of JSON object key order. */
export function isAppsSearchSaved(library: AppsLibrary | null | undefined, context: AppsRequestContext): boolean {
  if (!library || !context.skill_id || !context.input) return false;
  const stableParameters = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(stableParameters);
    if (!value || typeof value !== 'object') return value;
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, child]) => [key, stableParameters(child)]));
  };
  const parameters = JSON.stringify(stableParameters(context.input));
  return library.saved_searches.some(search => search.skill_id === context.skill_id && JSON.stringify(stableParameters(search.parameters)) === parameters);
}

export function appsSearchQuery(context: AppsRequestContext): string {
  for (const candidate of [context.result?.request_text, context.result?.query, appsResultRequestFields(context.input).query, context.result?.title]) {
    if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
  }
  return get(text)('apps_workspace.saved_search');
}

/** Shared first-save notice for searches saved in Apps or from chat results. */
export async function saveAppsSearchWithNotice(appId: string, context: AppsRequestContext, query = appsSearchQuery(context), teamId?: string): Promise<AppsLibrary> {
  if (!context.skill_id || !context.input) throw new Error('search_context_unavailable');
  const owner = ownerGeneration;
  const library = await saveAppsSearch(appId, context.skill_id, context.input, query, teamId);
  const tr = get(text);
  if (library.first_save && library.daily_searches_enabled) {
    const noticeId = notificationStore.addNotificationWithOptions('info', {
      message: tr('apps_workspace.daily_search_notice'),
      messageSecondary: tr('apps_workspace.daily_search_notice_details'),
      duration: 0,
      actionLabel: tr('apps_workspace.daily_search_ok'),
      onAction: () => undefined,
      secondaryActionLabel: tr('apps_workspace.daily_search_turn_off'),
      onSecondaryAction: () => { if (owner !== ownerGeneration) return; void setAppsDailySearches(appId, false, teamId).then(() => {
        notificationStore.removeNotification(noticeId);
        window.dispatchEvent(new CustomEvent('appsWorkspaceLibraryUpdated', { detail: { appId, teamId } }));
      }).catch(() => { if (owner === ownerGeneration) notificationStore.error(tr('apps_workspace.library_error')); }); },
    });
  }
  window.dispatchEvent(new CustomEvent('appsWorkspaceLibraryUpdated', { detail: { appId, teamId } }));
  return library;
}
