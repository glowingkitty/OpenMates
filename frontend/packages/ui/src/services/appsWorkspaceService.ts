import { getApiEndpoint } from '../config/api';
import { get } from 'svelte/store';
import { authStore } from '../stores/authState';
import { userProfile } from '../stores/userProfile';
import { anonymousChatStorage } from './anonymousChatStorage';
import type { AppsSkillDetails, AppsSkillGuestEligibility, AppsSkillResponse } from '../types/appsWorkspace';
import type { RustAppsSkillExecution } from './rustCore/apps/rustAppsSkillExecution';

let rustApps: Promise<RustAppsSkillExecution> | null = null;
/** Skill execution policy lives in the shared Worker `apps` unit; this shell only supplies platform identity. */
function rustAppsExecution(): Promise<RustAppsSkillExecution> {
  rustApps ??= import('./rustCore/apps/rustAppsSkillExecution').then(module => module.createRustAppsSkillExecution({
    apiEndpoint: getApiEndpoint, anonymousId: () => anonymousChatStorage.getAnonymousId(), authGeneration: () => authGeneration,
    captureIdentity: captureExecutionIdentity, assertIdentity: assertExecutionIdentity,
  }));
  return rustApps;
}

type FreeUsageStatus = { active?: boolean; can_send_text?: boolean; reason?: string | null } | null | undefined;
export type AppsSkillExecuteOptions = {
  guest: boolean;
  teamId?: string;
  signal?: AbortSignal;
  metadata?: AppsSkillDetails;
  /** Recheck caller account/Team ownership immediately before provider dispatch. */
  assertContext?: () => void;
  /** Persist the accepted task before polling so a reload can resume it. */
  onTaskSubmitted?: (taskId: string) => Promise<void>;
};

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
  return rustAppsExecution().then(apps => apps.getAppsSkillDetails(appId, skillId, signal));
}

/** Mirrors the CLI's quick, inline anonymous restriction before a provider request. */
export function canRunGuestAppsSkill(metadata: AppsSkillDetails, status: FreeUsageStatus): AppsSkillGuestEligibility {
  if (!metadata.execution_available) return { allowed: false, reason: metadata.unavailable_reason ?? 'skill_unavailable' };
  if (!metadata.anonymous_allowed || metadata.execution_mode !== 'sync') return { allowed: false, reason: 'signup_required' };
  if (!status || status.active !== true || status.can_send_text === false) return { allowed: false, reason: status?.reason ?? 'free_usage_unavailable' };
  return { allowed: true, reason: null };
}

/** Request-specific quote and current budget check. This endpoint never dispatches a skill. */
export function getAnonymousAppsSkillAvailability(
  appId: string, skillId: string, input: Record<string, unknown>, signal?: AbortSignal,
): Promise<AppsSkillGuestEligibility> {
  return rustAppsExecution().then(apps => apps.getAnonymousAppsSkillAvailability(appId, skillId, input, signal));
}

/** Resume one already accepted job; this never dispatches or bills the skill again. */
export function pollAppsSkillTask(taskId: string, options: { signal?: AbortSignal; expectedUserId?: string } = {}): Promise<unknown> {
  return rustAppsExecution().then(apps => apps.pollAppsSkillTask(taskId, options));
}

/** Direct REST dispatch; the Rust core owns de-duplication, polling and failure mapping. */
export async function executeAppsSkill(appId: string, skillId: string, input: Record<string, unknown>, options: AppsSkillExecuteOptions): Promise<AppsSkillResponse> {
  return (await rustAppsExecution()).executeAppsSkill(appId, skillId, input, options);
}
