<!--
  frontend/packages/ui/src/components/embeds/models3d/Model3DSearchEmbedPreview.svelte

  Parent preview for models3d.search. It renders only lightweight parent
  preview metadata and never hydrates child embeds during chat rendering.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import { extractSearchResultsFromContent, getParentPreviewResultState, normalizeEmbedIdList } from '../embedPreviewHydration';

  interface Model3DResultPreview {
    title?: string;
    provider?: string;
    preview_image_url?: string;
    thumbnail_url?: string;
    source_page_url?: string;
  }

  interface Props {
    id: string;
    query?: string;
    provider?: string;
    status: 'processing' | 'finished' | 'error';
    results?: unknown;
    resultCount?: number;
    childEmbedIds?: string[] | string;
    previewResultsJson?: string;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    query = '',
    provider = 'Printables',
    status,
    results = [],
    resultCount,
    childEmbedIds = [],
    previewResultsJson = '',
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  const skillName = $text('app_skills.models3d.search');
  const THUMB_MAX_COUNT = 5;

  function parsePreviewResultsJson(value: unknown): Model3DResultPreview[] {
    if (typeof value !== 'string' || !value.trim()) return [];
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed as Model3DResultPreview[] : [];
    } catch {
      return [];
    }
  }

  function normalizePreviewResults(resultsValue: unknown, fallbackJson: unknown): Model3DResultPreview[] {
    if (Array.isArray(resultsValue) && resultsValue.length > 0) return resultsValue as Model3DResultPreview[];
    const extracted = extractSearchResultsFromContent(
      { results_toon: resultsValue },
      ['results', 'preview_results', 'preview_thumbnails'],
    );
    if (extracted.length > 0) return extracted as Model3DResultPreview[];
    return parsePreviewResultsJson(fallbackJson);
  }

  function proxyUrl(url: string | undefined): string {
    return proxyImage(url, MAX_WIDTH_PREVIEW_THUMBNAIL);
  }

  let previewResults = $derived(normalizePreviewResults(results, previewResultsJson));
  let childIds = $derived(normalizeEmbedIdList(childEmbedIds));
  let resultState = $derived(getParentPreviewResultState({
    status,
    previewResultCount: previewResults.length,
    resultCount,
    childEmbedIds: childIds,
  }));
  let thumbnails = $derived(
    previewResults
      .filter((result) => result.preview_image_url || result.thumbnail_url)
      .slice(0, THUMB_MAX_COUNT)
  );
  let displayCount = $derived(resultCount ?? previewResults.length ?? childIds.length);

  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (!data.decodedContent) return;
    const content = data.decodedContent;
    if (typeof content.query === 'string') query = content.query;
    if (typeof content.provider === 'string') provider = content.provider;
    if (typeof content.result_count === 'number') resultCount = content.result_count;
    results = content.results || content.preview_results || content.preview_thumbnails || [];
    if (typeof content.preview_results_json === 'string') previewResultsJson = content.preview_results_json;
  }

  function handleStop() {
    // Search results are synchronous and not cancellable.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="models3d"
  skillId="search"
  skillIconName="search"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={true}
  showSkillIcon={true}
  hasFullWidthImage={status === 'finished' && thumbnails.length > 0}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="models3d-search-preview" data-testid="models3d-search-preview">
      {#if status === 'finished' && thumbnails.length > 0}
        <div class="thumbnail-strip" aria-hidden="true">
          {#each thumbnails as result}
            <img src={proxyUrl(result.preview_image_url || result.thumbnail_url)} alt="" loading="lazy" />
          {/each}
        </div>
      {/if}
      <div class="search-copy">
        <div class="query">{query || skillName}</div>
        <div class="meta">
          {#if resultState === 'no-results'}
            {$text('embeds.models3d.search.no_results')}
          {:else if resultState === 'open-to-view'}
            {$text('embeds.models3d.search.open_to_view')}
          {:else}
            {$text('embeds.models3d.search.results_count', { values: { count: displayCount } })} · {$text('embeds.via')} {provider}
          {/if}
        </div>
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .models3d-search-preview {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    width: 100%;
    min-height: 100%;
  }

  .thumbnail-strip {
    display: flex;
    gap: 4px;
    width: 100%;
    height: 74px;
    overflow: hidden;
    border-radius: 18px;
    background: var(--color-grey-10);
  }

  .thumbnail-strip img {
    flex: 1 1 0;
    min-width: 0;
    object-fit: cover;
  }

  .search-copy {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .query {
    color: var(--color-font-primary);
    font-size: var(--font-size-sm);
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .meta {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }
</style>
