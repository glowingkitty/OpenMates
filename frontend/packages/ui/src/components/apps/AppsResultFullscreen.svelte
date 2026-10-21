<script lang="ts">
  import { setContext, untrack } from 'svelte';
  import { APPS_RESULTS_ACTIONS_CONTEXT, APPS_RESULTS_SAVE_CONTEXT, type AppsResultsSaveContext, type AppsRequestContext, type AppsResultsActionsContext } from '../../services/appsWorkspaceContext';
  import { text } from '../../i18n/translations';
  import { authStore } from '../../stores/authStore';
  import { userProfile } from '../../stores/userProfile';
  import { resolveEmbed, decodeToonContent, type EmbedData } from '../../services/embedResolver';
  import { getAppsResult, appsResultSaveStates, appsResultSaveKey, retryAppsResultSave } from '../../services/appsWorkspaceResultsService';
  import { appsResultPresentationContent } from '../../utils/appsResultRequestFields';
  import { resolveRegistryKey, hasFullscreenComponent, loadFullscreenComponent } from '../../services/embedFullscreenResolver';
  import UnifiedEmbedFullscreen from '../embeds/UnifiedEmbedFullscreen.svelte';
  import type { SkillStoreExampleFullscreen } from '../../stores/skillStoreExampleFullscreenStore';
  import { notificationStore } from '../../stores/notificationStore';

  let { embedId, rootEmbedId = embedId, appId, teamId, onClose, exampleData, presentationData, onSubmit, onSaveSearch, onCreateWorkflow, isSearchSaved, hydrateGraph = true }: {
    embedId: string; rootEmbedId?: string; appId: string; teamId?: string; onClose: () => void; exampleData?: SkillStoreExampleFullscreen;
    hydrateGraph?: boolean;
    presentationData?: { type: string; content: Record<string, unknown>; parent: Record<string, unknown> };
    onSubmit?: AppsResultsActionsContext['onSubmit'];
    onSaveSearch?: AppsResultsActionsContext['onSaveSearch'];
    onCreateWorkflow?: AppsResultsActionsContext['onCreateWorkflow'];
    isSearchSaved?: AppsResultsActionsContext['isSearchSaved'];
  } = $props();
  // Project account publications to primitive identity/readiness values. Credits,
  // profile metadata, and redundant auth updates must not remount the composer.
  const authenticated = $derived($authStore.isAuthenticated);
  const ownerId = $derived(authenticated ? $userProfile.user_id || null : null);
  const authReady = $derived($authStore.isInitialized && (!authenticated || ownerId !== null));
  const saveState = $derived($userProfile.user_id ? $appsResultSaveStates[appsResultSaveKey($userProfile.user_id, teamId, rootEmbedId)] : undefined);
  setContext<AppsResultsSaveContext>(APPS_RESULTS_SAVE_CONTEXT, {
    get state() { return exampleData ? undefined : saveState; },
    retry: async () => { try { await retryAppsResultSave(rootEmbedId, teamId); } catch { /* The outbox retains its truthful error state for retry. */ } },
  });
  function enrichContext(context: AppsRequestContext): AppsRequestContext {
    return { ...context, skill_id: typeof decodedContent?.skill_id === 'string' ? decodedContent.skill_id : typeof parentContent?.skill_id === 'string' ? parentContent.skill_id : context.skill_id,
      input: (parentContent?.input && typeof parentContent.input === 'object' ? parentContent.input as Record<string, unknown> : undefined) ?? (decodedContent?.input && typeof decodedContent.input === 'object' ? decodedContent.input as Record<string, unknown> : context.input),
      chat_id: typeof decodedContent?.chat_id === 'string' ? decodedContent.chat_id : typeof data?.chat_id === 'string' ? data.chat_id : typeof parentContent?.chat_id === 'string' ? parentContent.chat_id : context.chat_id,
      result: { ...parentContent, ...decodedContent, ...context.result } };
  }
  if (untrack(() => onSubmit)) setContext<AppsResultsActionsContext>(APPS_RESULTS_ACTIONS_CONTEXT, {
    onSubmit: (text, attachments, context) => onSubmit!(text, attachments, enrichContext(context)),
    get onSaveSearch() { return onSaveSearch ? (context) => onSaveSearch!(enrichContext(context)) : undefined; },
    get onCreateWorkflow() { return onCreateWorkflow ? (context) => onCreateWorkflow!(enrichContext(context)) : undefined; },
    get isSearchSaved() { return isSearchSaved ? (context) => isSearchSaved!(enrichContext(context)) : undefined; },
  });
  let data = $state<EmbedData | null>(null);
  let decodedContent = $state<Record<string, unknown> | null>(null);
  let error = $state(false);
  let parentContent = $state<Record<string, unknown> | null>(null);
  const key = $derived(data && decodedContent ? resolveRegistryKey(data.type, decodedContent) : null);
  let Renderer = $state<Awaited<ReturnType<typeof loadFullscreenComponent>>>(null);
  let reportedError = '';
  $effect(() => {
    const selectedKey = key;
    let cancelled = false;
    Renderer = null;
    if (selectedKey && hasFullscreenComponent(selectedKey)) {
      void loadFullscreenComponent(selectedKey).then(component => {
        if (cancelled) return;
        if (component) Renderer = component;
        else error = true;
      }).catch(() => { if (!cancelled) error = true; });
    }
    return () => { cancelled = true; };
  });
  $effect(() => {
    const failed = (data?.status === 'error' && key !== 'app:business:search_trademarks') || data?.status === 'cancelled';
    const unavailable = Boolean(data && decodedContent && (!key || !hasFullscreenComponent(key)));
    if (!error && !failed && !unavailable) return;
    const identity = appId + ':' + embedId;
    if (reportedError === identity) return;
    reportedError = identity;
    untrack(() => {
      notificationStore.error($text(failed ? 'apps_workspace.request_error' : 'apps_workspace.result_unavailable'));
      onClose();
    });
  });

  $effect(() => {
    const request = { appId, embedId, rootEmbedId, teamId, hydrateGraph, exampleData, presentationData };
    const ready = authReady;
    // Owner changes invalidate private results even when the route is unchanged.
    void authenticated; void ownerId;
    let cancelled = false;
    error = false;
    data = null;
    decodedContent = null;
    parentContent = null;
    // Clear previous-owner content while session restoration is incomplete.
    if (!request.exampleData && !request.presentationData && !ready) return;
    // Store reads inside hydration do not define this view's lifetime. Capture
    // the route first, then fence all async writes with the existing cleanup.
    untrack(() => { void (async ({ embedId, rootEmbedId, teamId, hydrateGraph, exampleData, presentationData }) => {
      try {
        if (presentationData) {
          parentContent = presentationData.parent;
          decodedContent = presentationData.content;
          data = { embed_id: embedId, type: presentationData.type, status: 'finished', content: JSON.stringify(presentationData.content), createdAt: Date.now(), updatedAt: Date.now() };
          return;
        }
        if (exampleData) {
          decodedContent = appsResultPresentationContent(exampleData.decodedContent);
          data = { embed_id: embedId, type: 'app-skill-use', status: exampleData.decodedContent.status === 'error' ? 'error' : 'finished', content: JSON.stringify(exampleData.decodedContent), createdAt: Date.now(), updatedAt: Date.now() };
          return;
        }
        if (hydrateGraph) await getAppsResult(rootEmbedId, teamId);
        const resolved = await resolveEmbed(embedId);
        if (!resolved) throw new Error('RESULT_UNAVAILABLE');
        const decoded = await decodeToonContent(resolved.content);
        if (!decoded) throw new Error('RESULT_UNAVAILABLE');
        if (!cancelled) { data = resolved; decodedContent = appsResultPresentationContent(decoded); }
        const parentId = rootEmbedId !== embedId ? rootEmbedId : decoded?.parent_embed_id ?? resolved.parent_embed_id;
        if (typeof parentId === 'string' && parentId !== embedId) {
          try { const parent = await resolveEmbed(parentId); const content = parent ? await decodeToonContent(parent.content) : null; if (!cancelled) parentContent = content; }
          catch { /* The saved child remains usable when its parent is unavailable. */ }
        }
      } catch { if (!cancelled) error = true; }
    })(request); });
    return () => { cancelled = true; };
  });
</script>

{#if Renderer && data && decodedContent && !error}
  <Renderer data={{ decodedContent, embedData: data, attrs: {} }} {embedId} {onClose} showChatButton={false} />
{:else}
  <UnifiedEmbedFullscreen {appId} {onClose} showShare={false} embedHeaderTitle={$text('common.loading')} />
{/if}
