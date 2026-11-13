import { get } from 'svelte/store';
import { authStore } from '../stores/authState';
import { userProfile } from '../stores/userProfile';
import { ProjectFilePrivacy } from './projectFilePrivacy';
import type { AppsRequestDeps } from './rustCore/apps/rustAppsRequest';

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

/** Interpret first; only an accepted execution produces a retained fullscreen result (policy: Rust `apps` unit). */
export async function runAppsWorkspaceRequest(options: AppsWorkspaceRequestOptions): Promise<AppsWorkspaceRequestResult> {
  const { runRustAppsWorkspaceRequest } = await import('./rustCore/apps/rustAppsRequest');
  const deps: AppsRequestDeps = { identityGeneration: () => identityGeneration, requestPrivacy };
  return runRustAppsWorkspaceRequest(options, deps);
}
