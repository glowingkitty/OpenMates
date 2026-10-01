<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../i18n/translations';
  import { resolveEmbed, decodeToonContent, type EmbedData } from '../../services/embedResolver';
  import { getAppsResult } from '../../services/appsWorkspaceResultsService';
  import { resolveRegistryKey, hasFullscreenComponent, loadFullscreenComponent } from '../../services/embedFullscreenResolver';
  import UnifiedEmbedFullscreen from '../embeds/UnifiedEmbedFullscreen.svelte';
  import type { SkillStoreExampleFullscreen } from '../../stores/skillStoreExampleFullscreenStore';

  let { embedId, appId, teamId, onClose, exampleData }: {
    embedId: string; appId: string; teamId?: string; onClose: () => void; exampleData?: SkillStoreExampleFullscreen;
  } = $props();
  let data = $state<EmbedData | null>(null);
  let decodedContent = $state<Record<string, unknown> | null>(null);
  let error = $state(false);
  const key = $derived(data && decodedContent ? resolveRegistryKey(data.type, decodedContent) : null);

  onMount(() => {
    let cancelled = false;
    void (async () => {
      try {
        if (exampleData) {
          decodedContent = exampleData.decodedContent;
          data = { embed_id: embedId, type: 'app-skill-use', status: 'finished', content: JSON.stringify(decodedContent), createdAt: Date.now(), updatedAt: Date.now() };
          return;
        }
        await getAppsResult(embedId, teamId);
        const resolved = await resolveEmbed(embedId);
        if (!resolved) throw new Error('RESULT_UNAVAILABLE');
        const decoded = await decodeToonContent(resolved.content);
        if (!cancelled) { data = resolved; decodedContent = decoded; }
      } catch { if (!cancelled) error = true; }
    })();
    return () => { cancelled = true; };
  });
</script>

{#if data && decodedContent && key && hasFullscreenComponent(key)}
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
