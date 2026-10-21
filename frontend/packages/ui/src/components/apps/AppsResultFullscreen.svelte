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

  let { embedId, rootEmbedId = embedId, appId, teamId, onClose, exampleData, onSubmit, onSaveSearch, onCreateWorkflow, hydrateGraph = true }: {
    embedId: string; rootEmbedId?: string; appId: string; teamId?: string; onClose: () => void; exampleData?: SkillStoreExampleFullscreen;
    hydrateGraph?: boolean;
    onSubmit?: AppsResultsActionsContext['onSubmit'];
    onSaveSearch?: AppsResultsActionsContext['onSaveSearch'];
    onCreateWorkflow?: AppsResultsActionsContext['onCreateWorkflow'];
  } = $props();
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
  });
  let data = $state<EmbedData | null>(null);
  let decodedContent = $state<Record<string, unknown> | null>(null);
  let error = $state(false);
  let parentContent = $state<Record<string, unknown> | null>(null);
  const key = $derived(data && decodedContent ? resolveRegistryKey(data.type, decodedContent) : null);

  $effect(() => {
    // A cold Apps route can mount before session restoration publishes its
    // account. Loading at that point would permanently mistake it for a guest.
    if (!exampleData && (!$authStore.isInitialized || ($authStore.isAuthenticated && !$userProfile.user_id))) return;
    let cancelled = false;
    error = false;
    parentContent = null;
    void (async () => {
      try {
        if (exampleData) {
          decodedContent = appsResultPresentationContent(exampleData.decodedContent);
          data = { embed_id: embedId, type: 'app-skill-use', status: exampleData.decodedContent.status === 'error' ? 'error' : 'finished', content: JSON.stringify(exampleData.decodedContent), createdAt: Date.now(), updatedAt: Date.now() };
          return;
        }
        if (hydrateGraph) await getAppsResult(rootEmbedId, teamId);
        const resolved = await resolveEmbed(embedId);
        if (!resolved) throw new Error('RESULT_UNAVAILABLE');
        const decoded = await decodeToonContent(resolved.content);
        if (!cancelled) { data = resolved; decodedContent = decoded ? appsResultPresentationContent(decoded) : null; }
        const parentId = rootEmbedId !== embedId ? rootEmbedId : decoded?.parent_embed_id ?? resolved.parent_embed_id;
        if (typeof parentId === 'string' && parentId !== embedId) {
          try { const parent = await resolveEmbed(parentId); const content = parent ? await decodeToonContent(parent.content) : null; if (!cancelled) parentContent = content; }
          catch { /* The saved child remains usable when its parent is unavailable. */ }
        }
      } catch { if (!cancelled) error = true; }
    })();
    return () => { cancelled = true; };
  });
</script>

{#if (data?.status === 'error' && key !== 'app:business:search_trademarks') || data?.status === 'cancelled'}
  <UnifiedEmbedFullscreen {appId} {onClose} showShare={false} embedHeaderTitle={$text('apps_workspace.request_error')}>
    {#snippet content()}<p role="alert">{$text('apps_workspace.request_error')}</p>{/snippet}
  </UnifiedEmbedFullscreen>
{:else if data && decodedContent && key && hasFullscreenComponent(key)}
  {#await loadFullscreenComponent(key)}
    <UnifiedEmbedFullscreen {appId} {onClose} showShare={false} embedHeaderTitle={$text('common.loading')} />
  {:then Component}
    {#if Component}
      <Component data={{ decodedContent, embedData: data, attrs: {} }} {embedId} {onClose} showChatButton={false} />
    {:else}
      <UnifiedEmbedFullscreen {appId} {onClose} showShare={false} embedHeaderTitle={$text('apps_workspace.result_unavailable')} />
    {/if}
  {:catch}
    <UnifiedEmbedFullscreen {appId} {onClose} showShare={false} embedHeaderTitle={$text('apps_workspace.result_unavailable')} />
  {/await}
{:else}
  <UnifiedEmbedFullscreen {appId} {onClose} showShare={false} embedHeaderTitle={$text(error || (data && decodedContent) ? 'apps_workspace.result_unavailable' : 'common.loading')}>
    {#snippet content()}
      <p role="status">{$text(error || (data && decodedContent) ? 'apps_workspace.result_unavailable' : 'common.loading')}</p>
    {/snippet}
  </UnifiedEmbedFullscreen>
{/if}
