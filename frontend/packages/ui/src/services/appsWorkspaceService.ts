import { getApiEndpoint } from '../config/api';
import { get } from 'svelte/store';
import { authStore } from '../stores/authState';
import { userProfile } from '../stores/userProfile';
import { anonymousChatStorage } from './anonymousChatStorage';
import type { AppsSkillDetails, AppsSkillGuestEligibility, AppsSkillResponse } from '../types/appsWorkspace';

type FreeUsageStatus = { active?: boolean; can_send_text?: boolean; reason?: string | null } | null | undefined;
export type AppsSkillExecuteOptions = {
  guest: boolean;
  teamId?: string;
  signal?: AbortSignal;
  metadata?: AppsSkillDetails;
  /** Persist the accepted task before polling so a reload can resume it. */
  onTaskSubmitted?: (taskId: string) => Promise<void>;
};

const detailsCache = new Map<string, Promise<AppsSkillDetails>>();
const pendingExecutions = new Map<string, Promise<AppsSkillResponse>>();
const acceptedExecutions = new Map<string, AppsSkillResponse>();
let authGeneration = 0;
let authObserved = false;
let lastAuthenticated = false;
authStore.subscribe(state => {
  if (authObserved && state.isAuthenticated !== lastAuthenticated) authGeneration += 1;
  lastAuthenticated = state.isAuthenticated;
  authObserved = true;
});
let profileObserved = false;
let lastUserId: string | null = null;
userProfile.subscribe(profile => {
  if (profileObserved && profile.user_id !== lastUserId) authGeneration += 1;
  lastUserId = profile.user_id;
  profileObserved = true;
});
const pollIntervalMs = 2000;
const pollTimeoutMs = 10 * 60 * 1000;

function errorDetail(body: unknown, status: number): string {
  const response = body && typeof body === 'object' ? body as Record<string, unknown> : {};
  const detail = response.detail ?? response.error;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => typeof item === 'object' && item && 'msg' in item ? String(item.msg) : String(item)).join('; ');
  if (detail && typeof detail === 'object') {
    const item = detail as Record<string, unknown>;
    return String(item.message ?? item.code ?? `HTTP ${status}`);
  }
  return `HTTP ${status}`;
}

async function readJson(response: Response): Promise<unknown> {
  try { return await response.json(); } catch { return {}; }
}

type ExecutionIdentity = { userId: string | null; anonymousId: string | null; authGeneration: number };

function captureExecutionIdentity(guest: boolean, expectedUserId?: string): ExecutionIdentity {
  const authenticated = get(authStore).isAuthenticated;
  const userId = get(userProfile).user_id;
  if (guest) {
    if (authenticated) throw new Error('account_context_changed');
    return { userId: null, anonymousId: anonymousChatStorage.getAnonymousId(), authGeneration };
  }
  if (!authenticated || !userId || (expectedUserId && expectedUserId !== userId)) throw new Error('account_context_changed');
  return { userId, anonymousId: null, authGeneration };
}

function assertExecutionIdentity(identity: ExecutionIdentity): void {
  if (authGeneration !== identity.authGeneration || get(authStore).isAuthenticated !== Boolean(identity.userId)
    || get(userProfile).user_id !== identity.userId && identity.userId !== null
    || identity.anonymousId !== null && anonymousChatStorage.getAnonymousId() !== identity.anonymousId) {
    throw new Error('account_context_changed');
  }
}

/** Public details are loaded only when a skill opens; failures are never cached. */
export function getAppsSkillDetails(appId: string, skillId: string, signal?: AbortSignal): Promise<AppsSkillDetails> {
  const key = `${appId}/${skillId}`;
  // Private mail metadata must be admitted by the server for every account.
  if (appId === 'mail' && skillId === 'search') return fetchDetails(appId, skillId, signal);
  // A caller-specific abort must not cancel a shared cached request.
  if (signal) return fetchDetails(appId, skillId, signal);
  const cached = detailsCache.get(key);
  if (cached) return cached;
  const request = fetchDetails(appId, skillId).catch(error => {
    detailsCache.delete(key);
    throw error;
  });
  detailsCache.set(key, request);
  return request;
}

async function fetchDetails(appId: string, skillId: string, signal?: AbortSignal): Promise<AppsSkillDetails> {
  const url = getApiEndpoint(`/v1/apps/${encodeURIComponent(appId)}/skills/${encodeURIComponent(skillId)}/details`);
  // Public catalog responses allow wildcard CORS, which browsers reject for
  // credentialed requests. Mail search is the one user-gated catalog entry and
  // must keep its session so its backend allowlist remains authoritative.
  const credentials = appId === 'mail' && skillId === 'search' ? 'include' : 'omit';
  const requestAuthGeneration = authGeneration;
  const response = await fetch(url, { credentials, signal });
  const body = await readJson(response);
  if (credentials === 'include' && requestAuthGeneration !== authGeneration) throw new Error('account_context_changed');
  if (!response.ok) throw new Error(errorDetail(body, response.status));
  return body as AppsSkillDetails;
}

/** Mirrors the CLI's quick, inline anonymous restriction before a provider request. */
export function canRunGuestAppsSkill(metadata: AppsSkillDetails, status: FreeUsageStatus): AppsSkillGuestEligibility {
  if (!metadata.execution_available) return { allowed: false, reason: metadata.unavailable_reason ?? 'skill_unavailable' };
  if (!metadata.anonymous_allowed || metadata.execution_mode !== 'sync') return { allowed: false, reason: 'signup_required' };
  if (!status || status.active !== true || status.can_send_text === false) return { allowed: false, reason: status?.reason ?? 'free_usage_unavailable' };
  return { allowed: true, reason: null };
}

/** Request-specific quote and current budget check. This endpoint never dispatches a skill. */
export async function getAnonymousAppsSkillAvailability(
  appId: string, skillId: string, input: Record<string, unknown>, signal?: AbortSignal,
): Promise<AppsSkillGuestEligibility> {
  const url = getApiEndpoint(`/v1/anonymous/apps/${encodeURIComponent(appId)}/skills/${encodeURIComponent(skillId)}/availability`);
  const response = await fetch(url, {
    method: 'POST', cache: 'no-store', signal,
    headers: { 'Content-Type': 'application/json', 'X-OpenMates-Anonymous-ID': anonymousChatStorage.getAnonymousId() },
    body: JSON.stringify(input),
  });
  const body = await readJson(response) as Record<string, unknown>;
  if (!response.ok) return { allowed: false, reason: errorDetail(body, response.status) };
  return { allowed: body.allowed === true, reason: typeof body.reason === 'string' ? body.reason : null };
}

function failedSkillResponse(body: AppsSkillResponse): string | null {
  if (body.success === false) return body.error || 'skill_failed';
  const data = body.data && typeof body.data === 'object' ? body.data as Record<string, unknown> : null;
  if (data?.success === false || typeof data?.error === 'string') return String(data.error || 'skill_failed');
  return null;
}

async function pollTask(taskId: string, signal?: AbortSignal, identity?: ExecutionIdentity): Promise<unknown> {
  const started = Date.now();
  while (Date.now() - started < pollTimeoutMs) {
    if (identity) assertExecutionIdentity(identity);
    if (signal?.aborted) throw signal.reason ?? new DOMException('Aborted', 'AbortError');
    const response = await fetch(getApiEndpoint(`/v1/tasks/${encodeURIComponent(taskId)}`), { credentials: 'include', signal });
    const body = await readJson(response) as Record<string, unknown>;
    if (identity) assertExecutionIdentity(identity);
    if (!response.ok && response.status < 500) throw new Error(`Task ${taskId}: ${errorDetail(body, response.status)}`);
    if (response.ok && body.status === 'completed') return body.result;
    if (response.ok && body.status === 'failed') throw new Error(`Task ${taskId}: ${String(body.error ?? 'task_failed')}`);
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => { signal?.removeEventListener('abort', onAbort); resolve(); }, pollIntervalMs);
      function onAbort() { clearTimeout(timer); reject(signal?.reason ?? new DOMException('Aborted', 'AbortError')); }
      signal?.addEventListener('abort', onAbort, { once: true });
    });
  }
  throw new Error(`Task ${taskId} is still processing; retain its ID to reopen the result.`);
}

/** Resume one already accepted job; this never dispatches or bills the skill again. */
export function pollAppsSkillTask(taskId: string, options: { signal?: AbortSignal; expectedUserId?: string } = {}): Promise<unknown> {
  const identity = captureExecutionIdentity(false, options.expectedUserId);
  return pollTask(taskId, options.signal, identity);
}

function acceptedTaskIds(envelope: AppsSkillResponse): string[] {
  const data = envelope.data && typeof envelope.data === 'object' ? envelope.data as Record<string, unknown> : envelope;
  return typeof data.task_id === 'string' ? [data.task_id] : Array.isArray(data.task_ids) ? data.task_ids.filter((item): item is string => typeof item === 'string') : [];
}

async function resolveAsyncResponse(envelope: AppsSkillResponse, options: AppsSkillExecuteOptions, identity: ExecutionIdentity): Promise<AppsSkillResponse> {
  const ids = acceptedTaskIds(envelope);
  if (!ids.length) return envelope;
  for (const id of ids) {
    assertExecutionIdentity(identity);
    await options.onTaskSubmitted?.(id);
    assertExecutionIdentity(identity);
  }
  const results = await Promise.all(ids.map(id => pollTask(id, options.signal, identity)));
  return { ...envelope, data: results.length === 1 ? results[0] : results };
}

/** Direct REST dispatch, with one in-flight operation per identical input. */
export async function executeAppsSkill(appId: string, skillId: string, input: Record<string, unknown>, options: AppsSkillExecuteOptions): Promise<AppsSkillResponse> {
  const identity = captureExecutionIdentity(options.guest);
  const key = JSON.stringify([identity.userId, identity.anonymousId, identity.authGeneration, appId, skillId, input, options.guest, options.teamId ?? null]);
  const pending = pendingExecutions.get(key);
  if (pending) return pending;
  const accepted = acceptedExecutions.get(key);
  const operation = (accepted ? resolveAsyncResponse(accepted, options, identity) : executeOnce(appId, skillId, input, options, key, identity))
    .then(result => { assertExecutionIdentity(identity); acceptedExecutions.delete(key); return result; })
    .finally(() => pendingExecutions.delete(key));
  pendingExecutions.set(key, operation);
  return operation;
}

async function executeOnce(appId: string, skillId: string, input: Record<string, unknown>, options: AppsSkillExecuteOptions, key: string, identity: ExecutionIdentity): Promise<AppsSkillResponse> {
  const metadata = options.metadata ?? await getAppsSkillDetails(appId, skillId, options.signal);
  if (metadata.app_id !== appId || metadata.skill_id !== skillId || !metadata.execution_available) throw new Error(metadata.unavailable_reason ?? 'skill_unavailable');
  if (options.guest) {
    if (!metadata.anonymous_allowed || metadata.execution_mode !== 'sync') throw new Error('signup_required');
    const eligibility = await getAnonymousAppsSkillAvailability(appId, skillId, input, options.signal);
    if (!eligibility.allowed) throw new Error(eligibility.reason ?? 'signup_required');
  }
  assertExecutionIdentity(identity);
  const base = options.guest ? '/v1/anonymous/apps' : '/v1/apps';
  const url = new URL(getApiEndpoint(`${base}/${encodeURIComponent(appId)}/skills/${encodeURIComponent(skillId)}`));
  if (!options.guest && options.teamId) url.searchParams.set('team_id', options.teamId);
  const response = await fetch(url.toString(), {
    method: 'POST', credentials: 'include', signal: options.signal,
    headers: {
      'Content-Type': 'application/json',
      ...(options.guest ? { 'X-OpenMates-Anonymous-ID': anonymousChatStorage.getAnonymousId() } : {}),
    },
    body: JSON.stringify(input),
  });
  const body = await readJson(response) as AppsSkillResponse;
  assertExecutionIdentity(identity);
  if (!response.ok) throw new Error(errorDetail(body, response.status));
  const failure = failedSkillResponse(body);
  if (failure) throw new Error(failure);
  if (!options.guest && acceptedTaskIds(body).length) acceptedExecutions.set(key, body);
  const resolved = options.guest ? body : await resolveAsyncResponse(body, options, identity);
  const asyncFailure = failedSkillResponse(resolved);
  if (asyncFailure) throw new Error(asyncFailure);
  return resolved;
}
