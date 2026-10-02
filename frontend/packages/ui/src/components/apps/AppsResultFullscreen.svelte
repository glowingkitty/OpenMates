<script lang="ts">
  import { text } from '../../i18n/translations';
  import { authStore } from '../../stores/authStore';
  import { userProfile } from '../../stores/userProfile';
  import { resolveEmbed, decodeToonContent, type EmbedData } from '../../services/embedResolver';
  import { getAppsResult } from '../../services/appsWorkspaceResultsService';
  import { appsResultPresentationContent } from '../../utils/appsResultRequestFields';
  import { resolveRegistryKey, hasFullscreenComponent, loadFullscreenComponent } from '../../services/embedFullscreenResolver';
  import UnifiedEmbedFullscreen from '../embeds/UnifiedEmbedFullscreen.svelte';
  import type { SkillStoreExampleFullscreen } from '../../stores/skillStoreExampleFullscreenStore';

  let { embedId, rootEmbedId = embedId, appId, teamId, onClose, exampleData }: {
    embedId: string; rootEmbedId?: string; appId: string; teamId?: string; onClose: () => void; exampleData?: SkillStoreExampleFullscreen;
  } = $props();
  let data = $state<EmbedData | null>(null);
  let decodedContent = $state<Record<string, unknown> | null>(null);
  let error = $state(false);
  const key = $derived(data && decodedContent ? resolveRegistryKey(data.type, decodedContent) : null);

  $effect(() => {
    // A cold Apps route can mount before session restoration publishes its
    // account. Loading at that point would permanently mistake it for a guest.
    if (!exampleData && (!$authStore.isInitialized || ($authStore.isAuthenticated && !$userProfile.user_id))) return;
    let cancelled = false;
    error = false;
    void (async () => {
      try {
        if (exampleData) {
          decodedContent = appsResultPresentationContent(exampleData.decodedContent);
          data = { embed_id: embedId, type: 'app-skill-use', status: exampleData.decodedContent.status === 'error' ? 'error' : 'finished', content: JSON.stringify(exampleData.decodedContent), createdAt: Date.now(), updatedAt: Date.now() };
          return;
        }
        await getAppsResult(rootEmbedId, teamId);
        const resolved = await resolveEmbed(embedId);
        if (!resolved) throw new Error('RESULT_UNAVAILABLE');
        const decoded = await decodeToonContent(resolved.content);
        if (!cancelled) { data = resolved; decodedContent = decoded ? appsResultPresentationContent(decoded) : null; }
      } catch { if (!cancelled) error = true; }
    })();
    return () => { cancelled = true; };
  });
</script>

{#if data?.status === 'error' || data?.status === 'cancelled'}
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
