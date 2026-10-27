import { get } from 'svelte/store';
import { getApiEndpoint } from '../config/api';
import { authStore } from '../stores/authState';
import { activeTeamContext } from '../stores/teamStore';
import { userProfile } from '../stores/userProfile';
import { anonymousChatStorage } from './anonymousChatStorage';
import { executeAppsSkill, getAppsSkillDetails } from './appsWorkspaceService';
import { validateSkillInput, type SkillSchema } from '../components/apps/appsSkillFormUtils';
import { ProjectFilePrivacy } from './projectFilePrivacy';
import { mapAppsRequestText } from './appsWorkspaceRequestPrivacy';
import { rankAppsWorkspaceImageResults } from './appsWorkspaceImageRankingService';
import { prepareAppsRequestAttachments } from './appsWorkspaceAttachmentService';
import { retainAppsResult } from './appsWorkspaceResultsService';

let identityGeneration = 0;
let lastAuth = get(authStore).isAuthenticated;
let lastUser = get(userProfile).user_id;
authStore.subscribe(state => {
  if (state.isAuthenticated !== lastAuth) identityGeneration++;
  lastAuth = state.isAuthenticated;
});
userProfile.subscribe(profile => {
  if (profile.user_id !== lastUser) identityGeneration++;
  lastUser = profile.user_id;
});

import type { AppsRequestContext, AppsRequestHandoff } from './appsWorkspaceContext';
export { APPS_RESULTS_ACTIONS_CONTEXT, APPS_RESULTS_SAVE_CONTEXT } from './appsWorkspaceContext';
export type { AppsRequestContext, AppsRequestHandoff, AppsResultsActionsContext, AppsResultsSaveContext } from './appsWorkspaceContext';
export interface AppsWorkspaceRequestOptions {
  appId: string; text: string; guest: boolean; teamId?: string; signal?: AbortSignal;
  locale?: string; timezone?: string; requestId?: string; context?: AppsRequestContext; attachments?: File[];
  onAccepted?: (result: { embedId: string; skillId: string; input: Record<string, unknown> }) => void | Promise<void>;
  onChat?: (request: AppsRequestHandoff) => Promise<void>;
  onWorkflow?: (request: AppsRequestHandoff) => Promise<void>;
}
export interface AppsWorkspaceRequestResult {
  action: 'execute' | 'chat' | 'workflow'; requestId: string; skillId?: string;
  input?: Record<string, unknown>; embedId?: string; reason?: string;
}

/** Reuse the client-owned reversible privacy boundary; originals never enter model requests. */
async function requestPrivacy(authenticated: boolean) {
  // Privacy stores participate in chat sync; defer their imports until a request
  // so importing the root page cannot create a chat/store initialization cycle.
  const [{ personalDataStore }, { getActivePIIMappingsForRewrite }] = await Promise.all([
    import('../stores/personalDataStore'), import('../stores/embedPIIStore'),
  ]);
  if (!await personalDataStore.waitForPrivacyMutations()) throw new Error('privacy_settings_not_saved');
  const settings = get(personalDataStore.settings);
  const entries = get(personalDataStore.enabledEntries);
  const ownerMappings = authenticated && settings.masterEnabled ? getActivePIIMappingsForRewrite().map(mapping => ({ ...mapping })) : [];
  const receipt = JSON.stringify({ settings, entries });
  const privacy = new ProjectFilePrivacy({
    enabled: settings.masterEnabled,
    detection: {
      disabledCategories: new Set(Object.entries(settings.categories).filter(([, enabled]) => !enabled).map(([category]) => category)),
      personalDataEntries: entries.map(entry => ({ id: entry.id, textToHide: entry.textToHide, replaceWith: entry.replaceWith,
        type: entry.type === 'address' ? 'ADDRESS' as const : undefined,
        additionalTexts: entry.type === 'address' && entry.addressLines
          ? [entry.addressLines.street, entry.addressLines.city].filter(Boolean) : undefined })),
    },
    mappings: ownerMappings,
    preserveMappedTokens: true,
    // This operation's token map is RAM-only; native args are restored locally.
    save: async () => {},
  });
  return {
    protect: (text: string) => privacy.redactText(text),
    restore: (text: string) => privacy.restoreText(text),
    assertCurrent: () => {
      if (receipt !== JSON.stringify({ settings: get(personalDataStore.settings), entries: get(personalDataStore.enabledEntries) })) throw new Error('privacy_context_changed');
    },
  };
}

/** Interpret first; only an accepted execution produces a retained fullscreen result. */
export async function runAppsWorkspaceRequest(options: AppsWorkspaceRequestOptions): Promise<AppsWorkspaceRequestResult> {
  const text = options.text.trim();
  if (!text) throw new Error('request_required');
  const requestId = options.requestId ?? crypto.randomUUID();
  const userId = get(userProfile).user_id;
  const authenticated = get(authStore).isAuthenticated;
  const generation = identityGeneration;
  const team = get(activeTeamContext);
  if ((options.teamId ?? null) !== team.teamId) throw new Error('team_context_changed');
  const anonymousId = options.guest ? anonymousChatStorage.getAnonymousId() : null;
  let assertPrivacy = () => {};
  const assertIdentity = () => {
    if (generation !== identityGeneration || get(userProfile).user_id !== userId || get(authStore).isAuthenticated !== authenticated || (anonymousId !== null && anonymousChatStorage.getAnonymousId() !== anonymousId)) throw new Error('account_context_changed');
    const currentTeam = get(activeTeamContext);
    if (currentTeam.teamId !== team.teamId || currentTeam.epoch !== team.epoch) throw new Error('team_context_changed');
    if (options.signal?.aborted) throw options.signal.reason ?? new DOMException('Aborted', 'AbortError');
    assertPrivacy();
  };
  assertIdentity();
  const requestBase = { app_id: options.appId, text, request_id: requestId,
    timezone: options.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC',
    locale: options.locale ?? (typeof navigator !== 'undefined' ? navigator.language : 'en'),
    ...(options.teamId ? { team_id: options.teamId } : {}),
    ...(authenticated && userId ? { expected_user_id: userId } : {}) };
  const bytes = (value: unknown) => new TextEncoder().encode(JSON.stringify(value)).byteLength;
  if (bytes(requestBase) > 24 * 1024) throw new Error('request_too_large');
  const handoffLargeContext = async (): Promise<AppsWorkspaceRequestResult> => {
    assertIdentity();
    if (!options.onChat) throw new Error('chat_handoff_unavailable');
    await options.onChat({ text, context: options.context, attachments: options.attachments, reason: 'result_context_too_large' });
    return { action: 'chat', requestId, reason: 'result_context_too_large' };
  };
  if (options.context && bytes({ ...requestBase, context: options.context }) > 24 * 1024) return handoffLargeContext();
  if (options.attachments?.length && (options.guest || options.attachments.some(file => !file.type.startsWith('image/') && !file.type.startsWith('audio/')))) {
    if (!options.onChat) throw new Error('chat_handoff_unavailable');
    assertIdentity();
    await options.onChat({ text, context: options.context, attachments: options.attachments });
    return { action: 'chat', requestId };
  }
  const privacy = await requestPrivacy(authenticated);
  assertPrivacy = privacy.assertCurrent;
  assertIdentity();
  const protectedBase = { ...requestBase, text: privacy.protect(text) };
  const protectedContext = options.context ? mapAppsRequestText(options.context, privacy.protect) : undefined;
  const prepared = options.attachments?.length ? await prepareAppsRequestAttachments(options.attachments, { signal: options.signal, chatId: options.context?.chat_id, assertCurrent: assertIdentity }) : null;
  assertIdentity();
  const protectedAttachments = prepared?.attachments.map(({ input, ...descriptor }) => ({ ...mapAppsRequestText(descriptor, privacy.protect), ...(input ? { input } : {}) }));
  const nonAssetBody = { ...protectedBase, ...(prepared ? { attachments: protectedAttachments } : {}), ...(protectedContext ? { context: protectedContext } : {}) };
  if (bytes(nonAssetBody) > 24 * 1024) {
    if (options.context && bytes({ ...requestBase, ...(prepared ? { attachments: prepared.attachments } : {}) }) <= 24 * 1024) return handoffLargeContext();
    throw new Error('request_too_large');
  }
  const response = await fetch(getApiEndpoint('/v1/apps/workspace/interpret'), {
    method: 'POST', credentials: 'include', signal: options.signal,
    headers: { 'Content-Type': 'application/json', ...(options.guest ? { 'X-OpenMates-Anonymous-ID': anonymousChatStorage.getAnonymousId() } : {}) },
    body: JSON.stringify({ ...nonAssetBody, ...(prepared ? { assets: prepared.assets } : {}) }),
  });
  const body = await response.json();
  assertIdentity();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'interpretation_failed');
  if (!['execute', 'chat', 'workflow'].includes(body.action)) throw new Error('invalid_interpretation');
  const result: AppsWorkspaceRequestResult = { action: body.action, requestId, reason: body.reason };
  if (body.action === 'workflow' && options.attachments?.length) {
    if (!options.onChat) throw new Error('chat_handoff_unavailable');
    assertIdentity();
    await options.onChat({ text, context: options.context, attachments: options.attachments, reason: 'workflow_attachments_require_chat' });
    return { ...result, action: 'chat', reason: 'workflow_attachments_require_chat' };
  }
  if (body.action !== 'execute') {
    const handoff = body.action === 'chat' ? options.onChat : options.onWorkflow;
    if (!handoff) throw new Error(`${body.action}_handoff_unavailable`);
    assertIdentity();
    await handoff({ text, context: options.context, attachments: options.attachments, reason: body.reason });
    return result;
  }
  if (typeof body.skill_id !== 'string' || !body.skill_id || !body.input || typeof body.input !== 'object' || Array.isArray(body.input)) throw new Error('invalid_interpretation');
  const nativeInput = mapAppsRequestText(body.input as Record<string, unknown>, privacy.restore);
  const metadata = await getAppsSkillDetails(options.appId, body.skill_id, options.signal);
  assertIdentity();
  if (validateSkillInput(metadata.input_schema as SkillSchema, nativeInput).length) throw new Error('invalid_native_input');
  let acceptedNotified = false;
  const notifyAccepted = async (embedId: string) => {
    assertIdentity();
    if (acceptedNotified) return;
    acceptedNotified = true;
    await options.onAccepted?.({ embedId, skillId: body.skill_id, input: nativeInput });
  };
  assertIdentity();
  let responseBody = await executeAppsSkill(options.appId, body.skill_id, nativeInput, {
    guest: options.guest, teamId: options.teamId, signal: options.signal, assertContext: assertIdentity, metadata,
    onTaskSubmitted: async taskId => {
      assertIdentity();
      const embedId = await retainAppsResult({ appId: options.appId, skillId: body.skill_id, input: nativeInput,
        response: { task_id: taskId, status: 'processing' }, guest: options.guest, teamId: options.teamId, requestId, requestText: text, newRequest: true, persistence: 'background' });
      await notifyAccepted(embedId);
    },
  });
  assertIdentity();
  if (prepared && Object.keys(prepared.assets).length) responseBody = await rankAppsWorkspaceImageResults(responseBody, { appId: options.appId, text, prepareModelText: privacy.protect, expectedUserId: userId ?? undefined, assets: prepared.assets, teamId: options.teamId, signal: options.signal, assertCurrent: assertIdentity });
  assertIdentity();
  const embedId = await retainAppsResult({ appId: options.appId, skillId: body.skill_id, input: nativeInput,
    response: responseBody, guest: options.guest, teamId: options.teamId, requestId, requestText: text, newRequest: true, persistence: 'background' });
  await notifyAccepted(embedId);
  return { ...result, skillId: body.skill_id, input: nativeInput, embedId };
}
