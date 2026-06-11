<!--
  frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedPreview.svelte

  Preview component for Images Search skill embeds (images/search).
  Uses UnifiedEmbedPreview as base and provides search-specific details content.

  Design: Matches WebSearchEmbedPreview layout with images at top,
  query + "via {provider}" text, and favicon row with source count below.

  Architecture: See docs/architecture/embeds.md
  The parent embed content stores query, provider, result_count, preview metadata,
  and embed_ids. Chat previews stay metadata-only; fullscreen loads child embeds
  when the user explicitly opens it.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import { getParentPreviewResultState, normalizeEmbedIdList } from '../embedPreviewHydration';

  /**
   * Single image search result (child embed content schema).
   * Matches fields written by backend/apps/images/skills/search_skill.py
   */
  interface ImageResult {
    title?: string;
    source_page_url?: string;
    image_url?: string;
    thumbnail_url?: string;
    source?: string;
    favicon_url?: string;
  }

  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query */
    query: string;
    /** Search provider (e.g., 'Brave', 'SerpAPI Google Lens') */
    provider: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Image results array (for preview thumbnails) */
    results?: unknown;
    /** Parent-level result_count for metadata-only legacy previews */
    resultCount?: number;
    /** Child IDs indicate legacy results exist even when preview metadata is absent */
    childEmbedIds?: string[] | string;
    /** JSON fallback for TOON transports that flatten nested arrays poorly */
    previewResultsJson?: string;
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    status: statusProp,
    results: resultsProp = [],
    resultCount: resultCountProp,
    childEmbedIds: childEmbedIdsProp,
    previewResultsJson: previewResultsJsonProp = '',
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // Local reactive state — updated via handleEmbedDataUpdated callback
  let localQuery    = $state('');
  let localProvider = $state('Brave');
  let localStatus   = $state<'processing' | 'finished' | 'error'>('processing');
  let localResults  = $state<ImageResult[]>([]);
  let localTaskId   = $state<string | undefined>(undefined);

  $effect(() => {
    localQuery       = queryProp       || '';
    localProvider    = providerProp    || 'Brave';
    localStatus      = statusProp      || 'processing';
    localResults     = normalizePreviewResults(resultsProp, previewResultsJsonProp);
    localTaskId      = taskIdProp;
  });

  let query     = $derived(localQuery);
  let provider  = $derived(localProvider);
  let status    = $derived(localStatus);
  let results   = $derived(localResults);
  let childEmbedIds = $derived(normalizeEmbedIdList(childEmbedIdsProp));
  let taskId    = $derived(localTaskId);

  const skillIconName = 'search';
  let skillName = $derived($text('common.search'));

  // Min image width at 30px strip height — images are landscape-ish (avg ~4:3 ratio).
  // At 30px height a 4:3 image is ~40px wide. Container ~300px wide → ~7 fit.
  // Cap count to avoid loading dozens of images that will never be visible.
  const THUMB_MAX_COUNT = 10;

  // Show thumbnails that have a URL — cap count to what fits in the strip
  let previewThumbnails = $derived(
    results
      .filter(r => r.thumbnail_url || r.image_url)
      .slice(0, THUMB_MAX_COUNT)
  );

  // Extract unique favicons from results (first 3 unique sources, like WebSearchEmbedPreview)
  let faviconResults = $derived(
    (() => {
      const seen = new Set<string>();
      const favicons: { url: string; source: string }[] = [];
      for (const r of results) {
        const fav = r.favicon_url;
        if (fav && !seen.has(fav) && favicons.length < 3) {
          seen.add(fav);
          favicons.push({ url: fav, source: r.source || '' });
        }
      }
      return favicons;
    })()
  );

  let remainingCount = $derived(
    (() => {
      const totalUniqueSources = new Set(results.map(r => r.source).filter(Boolean)).size;
      return Math.max(0, totalUniqueSources - faviconResults.length);
    })()
  );

  let resultState = $derived(getParentPreviewResultState({
    status,
    previewResultCount: results.length,
    resultCount: resultCountProp,
    childEmbedIds,
  }));

  function proxyUrl(url: string | undefined): string | undefined {
    if (!url) return undefined;
    return proxyImage(url, MAX_WIDTH_PREVIEW_THUMBNAIL);
  }

  function parsePreviewResultsJson(value: unknown): ImageResult[] {
    if (typeof value !== 'string' || !value.trim()) return [];
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed as ImageResult[] : [];
    } catch {
      return [];
    }
  }

  function normalizePreviewResults(resultsValue: unknown, fallbackJson: unknown): ImageResult[] {
    if (Array.isArray(resultsValue) && resultsValue.length > 0) {
      return resultsValue as ImageResult[];
    }
    return parsePreviewResultsJson(fallbackJson);
  }

  /**
   * Handle embed data updates from server (processing -> finished transition).
   * UnifiedEmbedPreview calls this when an embedUpdated event arrives.
   *
   * CRITICAL: Preview mount must not hydrate child image embeds. The parent embed
   * may include lightweight preview_results/preview_thumbnails; otherwise the
   * preview renders metadata only and fullscreen loads child embeds on demand.
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }
    if (data.decodedContent) {
      const c = data.decodedContent as Record<string, unknown>;
      if (c.query)    localQuery    = c.query    as string;
      if (c.provider) localProvider = c.provider as string;
      const previewResults = normalizePreviewResults(
        c.results || c.preview_results || c.preview_thumbnails,
        c.preview_results_json
      );
      if (previewResults.length > 0) {
        localResults = previewResults;
      }
    }
  }

</script>

<UnifiedEmbedPreview
  {id}
  appId="images"
  skillId="search"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  showStatus={true}
  showSkillIcon={true}
  hasFullWidthImage={status === 'finished' && previewThumbnails.length > 0}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="images-search-details">
      {#if status === 'error'}
        <div class="search-error">
          <span class="error-title">{$text('embeds.image_search.error_title') || 'Search failed'}</span>
          <span class="error-message">{$text('embeds.image_search.error') || 'Could not load results'}</span>
        </div>
      {:else if status === 'finished' && previewThumbnails.length > 0}
        <!-- Image thumbnails at top (full-width, fills available space) -->
        <div class="thumbnail-strip" data-testid="images-search-thumbnail-strip">
          {#each previewThumbnails as result, i (i)}
            <img
              src={proxyUrl(result.image_url || result.thumbnail_url)}
              alt={result.title || ''}
              class="thumb-img"
              data-testid="images-search-thumbnail"
              use:handleImageError
            />
          {/each}
        </div>
        <!-- Bottom section: query text + favicons (below thumbnails) -->
        <div class="results-footer">
          <span class="search-query">{query}</span>
          <span class="search-provider">{$text('embeds.via')} {provider}</span>
          {#if faviconResults.length > 0}
            <div class="search-results-info">
              <div class="favicon-row">
                {#each faviconResults as fav, i (fav.url)}
                  <img
                    src={proxyUrl(fav.url)}
                    alt={fav.source}
                    class="favicon"
                    style:z-index={faviconResults.length - i}
                    use:handleImageError
                  />
                {/each}
              </div>
              {#if remainingCount > 0}
                <span class="remaining-count">+ {remainingCount} {$text('embeds.image_search.more_results') || 'more'}</span>
              {/if}
            </div>
          {/if}
        </div>
      {:else if status === 'finished'}
        <!-- Finished but no thumbnails. Legacy parents with child IDs have results,
             just no parent preview thumbnails yet. -->
        <div class="text-content">
          <span class="search-query">{query}</span>
          <span class="search-provider">{$text('embeds.via')} {provider}</span>
          {#if resultState === 'missing_preview_metadata'}
            <span class="preview-metadata-missing" data-testid="images-search-preview-metadata-missing-message">
              {$text('embeds.search_preview_open_to_view_results')}
            </span>
          {/if}
        </div>
      {:else}
        <!-- Processing: show query + provider -->
        <div class="text-content">
          {#if query}
            <span class="search-query">{query}</span>
            <span class="search-provider">{$text('embeds.via')} {provider}</span>
          {:else}
            <div class="skeleton-lines">
              <div class="skeleton-line long"></div>
              <div class="skeleton-line short"></div>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .images-search-details {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-sizing: border-box;
  }

  /* Text content (processing or no thumbnails) */
  .text-content {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    padding: var(--spacing-8) var(--spacing-10);
    overflow: hidden;
  }

  .search-query {
    font-size: var(--font-size-p);
    font-weight: 600;
    color: var(--color-grey-90, #1a1a1a);
    line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }

  .search-provider {
    font-size: var(--font-size-small);
    color: var(--color-grey-70, #555);
    line-height: 1.4;
  }

  .preview-metadata-missing {
    font-size: var(--font-size-xs);
    font-weight: 500;
    color: var(--color-grey-60);
    font-style: italic;
  }

  /* Horizontal thumbnail strip — fixed 30px height, images sized to fit */
  .thumbnail-strip {
    display: flex;
    flex-direction: row;
    gap: var(--spacing-1);
    width: 100%;
    height: 30px;
    flex-shrink: 0;
    overflow: hidden;
  }

  .thumb-img {
    height: 30px;
    width: auto;
    flex-shrink: 0;
    object-fit: cover;
    display: block;
  }

  /* Results footer: query text + favicon row (shown below thumbnails) */
  .results-footer {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    padding: var(--spacing-5) var(--spacing-10) var(--spacing-4);
    flex-shrink: 0;
  }

  .results-footer .search-query {
    font-size: var(--font-size-small);
    font-weight: 600;
    line-clamp: 2;
    -webkit-line-clamp: 2;
  }

  .results-footer .search-provider {
    font-size: var(--font-size-xxs);
  }

  .search-results-info {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: var(--spacing-4);
    margin-top: var(--spacing-1);
  }

  /* Favicon row — overlapping circles like WebSearchEmbedPreview */
  .favicon-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    height: 19px;
    min-width: 42px;
  }

  .favicon {
    width: 19px;
    height: 19px;
    border-radius: 50%;
    object-fit: cover;
    border: 1.5px solid var(--color-grey-0, #fff);
    background: var(--color-grey-10, #f5f5f5);
    flex-shrink: 0;
    display: block;
    margin-left: -6px;
  }

  .favicon:first-child {
    margin-left: 0;
  }

  /* .ds-loading-text base styles are generated from
     frontend/packages/ui/src/tokens/sources/components/loading.yml */

  .remaining-count {
    font-size: var(--font-size-small);
    color: var(--color-grey-70, #555);
    font-weight: 500;
    white-space: nowrap;
  }

  /* Error state — styled like WebSearchEmbedPreview */
  .search-error {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    padding: var(--spacing-6) var(--spacing-8);
    background: var(--color-error-5, #fff5f5);
    border: 1px solid var(--color-error-20, #f5c0c0);
    border-radius: var(--radius-5);
    margin: var(--spacing-6);
  }

  .error-title {
    font-size: var(--font-size-small);
    font-weight: 600;
    color: var(--color-error-70, #b04a4a);
  }

  .error-message {
    font-size: var(--font-size-xs);
    color: var(--color-error-50, #c06060);
    line-height: 1.4;
  }

  /* Skeleton lines */
  .skeleton-lines {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
  }

  .skeleton-line {
    height: 12px;
    background: var(--color-grey-15, #f0f0f0);
    border-radius: var(--radius-1);
    animation: pulse 1.5s ease-in-out infinite;
  }

  .skeleton-line.long  { width: 80%; }
  .skeleton-line.short { width: 50%; }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50%       { opacity: 1; }
  }

  /* Dark mode */
  :global(.dark) .search-query    { color: var(--color-grey-20, #ddd); }
  :global(.dark) .search-provider { color: var(--color-grey-50, #888); }
  :global(.dark) .skeleton-line   { background: var(--color-grey-80, #333); }
  :global(.dark) .remaining-count { color: var(--color-grey-50, #888); }
  :global(.dark) .favicon { border-color: var(--color-grey-85, #222); background: var(--color-grey-80, #333); }

  :global(.dark) .search-error {
    background: var(--color-error-95, #2a1515);
    border-color: var(--color-error-80, #4a2020);
  }

  :global(.dark) .error-title {
    color: var(--color-error-40, #d07a7a);
  }

  :global(.dark) .error-message {
    color: var(--color-error-50, #c06060);
  }
</style>
