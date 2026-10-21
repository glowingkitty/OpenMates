<script lang="ts">
  import { getAppsResult, type AppsResultItem } from '../../services/appsWorkspaceResultsService';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import AppsEmbedPreview from './AppsEmbedPreview.svelte';
  let { result, appId, teamId, onOpen, onLabel }: {
    result: AppsResultItem; appId: string; teamId?: string;
    onOpen: (embedId: string, rootId: string) => void;
    onLabel: (rootId: string, title: string) => void;
  } = $props();
  let childIds = $state<string[]>([]);
  $effect(() => {
    const rootId = result.embedId; void result.status;
    let cancelled = false;
    void (async () => {
      try {
        await getAppsResult(rootId, teamId);
        const root = await resolveEmbed(rootId);
        const content = root ? await decodeToonContent(root.content) : null;
        if (!content || cancelled) return;
        childIds = Array.isArray(content.embed_ids) ? content.embed_ids.filter((id): id is string => typeof id === 'string').slice(0, 40) : [];
        const title = content.request_text ?? content.query ?? content.title;
        if (typeof title === 'string' && title.trim()) onLabel(rootId, title);
      } catch { /* Pending local result remains visible and retryable. */ }
    })();
    return () => { cancelled = true; };
  });
</script>

<div class="result-group" data-testid={'apps-result-open-' + result.embedId}>
  {#each childIds.length ? childIds : [result.embedId] as embedId (embedId)}
    <div class="result-card"><AppsEmbedPreview {embedId} {appId} skillId={result.skillId}
      status={result.status} {teamId} onFullscreen={() => onOpen(result.embedId, result.embedId)} /></div>
  {/each}
</div>

<style>
  .result-group { display: flex; flex: 0 0 auto; gap: var(--spacing-12); }
  .result-card { flex: 0 0 18.75rem; width: 18.75rem; }
</style>
