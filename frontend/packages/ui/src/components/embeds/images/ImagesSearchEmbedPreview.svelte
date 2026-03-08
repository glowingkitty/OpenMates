<!--
  frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedPreview.svelte

  Preview component for Images Search skill embeds (images/search).
  Uses UnifiedEmbedPreview as base and provides search-specific details content.

  Design: Matches WebSearchEmbedPreview layout with images at top,
  query + "via {provider}" text, and favicon row with source count below.

  Architecture: See docs/architecture/embeds.md
  The parent embed content stores query, provider, result_count, and embed_ids
  (child embed IDs) — NOT the actual image results array. To show thumbnail
  previews, this component must load child embeds and extract thumbnail_url
  from their decoded TOON content when results are not directly available.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { handleImageError } from '../../../utils/offlineImageHandler';
  import { proxyImage } from '../../../utils/imageProxy';

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
    results?: ImageResult[];
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    status: statusProp,
    results: resultsProp = [],
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
  /** Track whether child-embed loading is already in progress to avoid duplicates */
  let isLoadingChildren = $state(false);

  $effect(() => {
    localQuery       = queryProp       || '';
    localProvider    = providerProp    || 'Brave';
    localStatus      = statusProp      || 'processing';
    localResults     = resultsProp     || [];
    localTaskId      = taskIdProp;
  });

  let query     = $derived(localQuery);
  let provider  = $derived(localProvider);
  let status    = $derived(localStatus);
  let results   = $derived(localResults);
  let taskId    = $derived(localTaskId);

  const skillIconName = 'search';
  let skillName = $derived($text('app_skills.images.search'));

  // Show thumbnails that have a URL — render as many as fit in the row
  let previewThumbnails = $derived(
    results.filter(r => r.thumbnail_url || r.image_url)
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

  function proxyUrl(url: string | undefined): string | undefined {
    if (!url) return undefined;
    return proxyImage(url);
  }

  /**
   * Handle embed data updates from server (processing -> finished transition).
   * UnifiedEmbedPreview calls this when an embedUpdated event arrives.
   *
   * CRITICAL: The parent embed content stores embed_ids (child embed IDs) but NOT
   * the actual results array with image URLs. When status transitions to "finished"
   * and results is empty, we must load child embeds to extract thumbnail URLs.
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }
    if (data.decodedContent) {
      const c = data.decodedContent as Record<string, unknown>;
      if (c.query)    localQuery    = c.query    as string;
      if (c.provider) localProvider = c.provider as string;
      if (Array.isArray(c.results) && (c.results as unknown[]).length > 0) {
        localResults = c.results as ImageResult[];
      }

      // CRITICAL FIX: When status is "finished" and we have embed_ids but no results,
      // load child embeds asynchronously to get thumbnail URLs for the preview strip.
      if (data.status === 'finished' && (!c.results || !Array.isArray(c.results) || (c.results as unknown[]).length === 0)) {
        const embedIds = c.embed_ids;
        if (embedIds) {
          const childEmbedIds: string[] = typeof embedIds === 'string'
            ? (embedIds as string).split('|').filter((cid: string) => cid.length > 0)
            : Array.isArray(embedIds) ? (embedIds as string[]) : [];

          if (childEmbedIds.length > 0 && !isLoadingChildren) {
            console.debug(`[ImagesSearchEmbedPreview] Loading child embeds for thumbnails (${childEmbedIds.length} embed_ids)`);
            loadChildEmbedsForPreview(childEmbedIds);
          }
        }
      }
    }
  }

  /**
   * Load child embeds to extract thumbnail URLs for the preview strip.
   * Uses retry logic because child embeds might not be persisted yet.
   */
  async function loadChildEmbedsForPreview(childEmbedIds: string[]) {
    if (isLoadingChildren) return;
    isLoadingChildren = true;

    try {
      const { loadEmbedsWithRetry, decodeToonContent } = await import('../../../services/embedResolver');

      const childEmbeds = await loadEmbedsWithRetry(childEmbedIds, 5, 300);

      if (childEmbeds.length > 0) {
        const imageResults = await Promise.all(childEmbeds.map(async (embed) => {
          const content = embed.content ? await decodeToonContent(embed.content) : null;
          if (!content) return null;

          return {
            title:           (content.title as string) || '',
            source_page_url: (content.source_page_url as string) || '',
            image_url:       (content.image_url as string) || '',
            thumbnail_url:   (content.thumbnail_url as string) || '',
            source:          (content.source as string) || '',
            favicon_url:     (content.favicon_url as string) || '',
          } as ImageResult;
        }));

        const validResults = imageResults.filter(r => r !== null) as ImageResult[];
        if (validResults.length > 0) {
          localResults = validResults;
          console.debug(`[ImagesSearchEmbedPreview] Loaded ${validResults.length} image results from child embeds`);
        }
      }
    } catch (error) {
      console.warn('[ImagesSearchEmbedPreview] Error loading child embeds for preview:', error);
    } finally {
      isLoadingChildren = false;
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
        <div class="thumbnail-strip">
          {#each previewThumbnails as result, i (i)}
            <img
              src={proxyUrl(result.thumbnail_url || result.image_url)}
              alt={result.title || ''}
              class="thumb-img"
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
                <span class="remaining-count">+ {remainingCount} {$text('embeds.web_search.more_results') || 'more'}</span>
              {/if}
            </div>
          {/if}
        </div>
      {:else if status === 'finished'}
        <!-- Finished but no thumbnails: show query + provider -->
        <div class="text-content">
          <span class="search-query">{query}</span>
          <span class="search-provider">{$text('embeds.via')} {provider}</span>
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
    gap: 4px;
    padding: 16px 20px;
    overflow: hidden;
  }

  .search-query {
    font-size: 16px;
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
    font-size: 14px;
    color: var(--color-grey-70, #555);
    line-height: 1.4;
  }

  /* Horizontal thumbnail strip — fills available card space */
  .thumbnail-strip {
    display: flex;
    flex-direction: row;
    gap: 2px;
    width: 100%;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .thumb-img {
    height: 100%;
    flex-shrink: 0;
    object-fit: cover;
    display: block;
    min-width: 60px;
    max-width: 50%;
  }

  /* Results footer: query text + favicon row (shown below thumbnails) */
  .results-footer {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 10px 20px 8px;
    flex-shrink: 0;
  }

  .results-footer .search-query {
    font-size: 14px;
    font-weight: 600;
    line-clamp: 2;
    -webkit-line-clamp: 2;
  }

  .results-footer .search-provider {
    font-size: 12px;
  }

  .search-results-info {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    margin-top: 2px;
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

  .remaining-count {
    font-size: 14px;
    color: var(--color-grey-70, #555);
    font-weight: 500;
    white-space: nowrap;
  }

  /* Error state — styled like WebSearchEmbedPreview */
  .search-error {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 12px 16px;
    background: var(--color-error-5, #fff5f5);
    border: 1px solid var(--color-error-20, #f5c0c0);
    border-radius: 12px;
    margin: 12px;
  }

  .error-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-error-70, #b04a4a);
  }

  .error-message {
    font-size: 13px;
    color: var(--color-error-50, #c06060);
    line-height: 1.4;
  }

  /* Skeleton lines */
  .skeleton-lines {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .skeleton-line {
    height: 12px;
    background: var(--color-grey-15, #f0f0f0);
    border-radius: 4px;
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
