<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../i18n/translations';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import AppsEmbedPreview from './AppsEmbedPreview.svelte';
  let { embedId, appId, skillId, onOpen }: {
    embedId: string; appId: string; skillId: string; onOpen: (id: string, rootId: string) => void;
  } = $props();
  let ids = $state<string[]>([]);
  let loading = $state(true);
  let empty = $state(false);
  let error = $state(false);
  onMount(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await resolveEmbed(embedId);
        if (!data) throw new Error('RESULT_UNAVAILABLE');
        const content = await decodeToonContent(data.content);
        if (!content) throw new Error('RESULT_UNAVAILABLE');
        if (cancelled) return;
        ids = Array.isArray(content.embed_ids) ? content.embed_ids.filter((id): id is string => typeof id === 'string') : [];
        empty = ids.length === 0 && content.result_count === 0;
        if (!empty && !ids.length) ids = [embedId];
      } catch { if (!cancelled) error = true; }
      finally { if (!cancelled) loading = false; }
    })();
    return () => { cancelled = true; };
  });
</script>

<section data-testid="apps-inline-results" aria-label={$text('apps_workspace.results')} aria-live="polite">
  {#if loading}<p role="status">{$text('common.loading')}</p>
  {:else if error}<p role="alert">{$text('apps_workspace.result_unavailable')}</p>
  {:else if empty}<p role="status">{$text('apps_workspace.no_results')}</p>
  {:else}
    <div class="inline-grid" data-testid="apps-inline-results-grid">
      {#each ids as id (id)}
        <div data-testid={`apps-inline-result-${id}`}><AppsEmbedPreview embedId={id} {appId} {skillId} onFullscreen={() => onOpen(id, embedId)} /></div>
      {/each}
    </div>
  {/if}
</section>

<style>
  section { width: 100%; margin-top: var(--spacing-8); min-width: 0; }
  .inline-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 18.75rem), 1fr)); gap: var(--spacing-4); justify-items: center; }
  .inline-grid > div { min-width: 0; max-width: 100%; }
</style>
