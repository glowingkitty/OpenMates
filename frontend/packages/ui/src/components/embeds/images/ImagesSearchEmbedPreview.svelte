<!--
  frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedPreview.svelte

  Preview component for Images Search skill embeds (images/search).
  Uses UnifiedEmbedPreview as base and provides search-specific details content.

  Details content structure:
  - Processing: query text + "via {provider}" + skeleton
  - Finished: 3-4 thumbnail images as a mini-mosaic (proxied via preview.openmates.org)
  - Error: error message

  Architecture: See docs/architecture/embeds.md
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

  // Show first 4 thumbnails in the mosaic
  const MAX_PREVIEW_THUMBNAILS = 4;
  let previewThumbnails = $derived(
    results.slice(0, MAX_PREVIEW_THUMBNAILS).filter(r => r.thumbnail_url || r.image_url)
  );

  let remainingCount = $derived(Math.max(0, results.length - MAX_PREVIEW_THUMBNAILS));


  function proxyUrl(url: string | undefined): string | undefined {
    if (!url) return undefined;
    return proxyImage(url);
  }

  /**
   * Handle embed data updates from server (processing -> finished transition).
   * UnifiedEmbedPreview calls this when an embedUpdated event arrives.
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }
    if (data.decodedContent) {
      const c = data.decodedContent as Record<string, unknown>;
      if (c.query)    localQuery    = c.query    as string;
      if (c.provider) localProvider = c.provider as string;
      if (Array.isArray(c.results)) localResults = c.results as ImageResult[];
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
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="search-preview">
      {#if status === 'error'}
        <div class="error-state">
          <span class="error-icon">!</span>
          <span class="error-text">{$text('embeds.image_search.error')}</span>
        </div>
      {:else if status === 'finished' && previewThumbnails.length > 0}
        <!-- Thumbnail mosaic -->
        <div class="thumbnail-mosaic" class:single={previewThumbnails.length === 1}>
          {#each previewThumbnails as result, i (i)}
            <div class="thumb-slot">
              <img
                src={proxyUrl(result.thumbnail_url || result.image_url)}
                alt={result.title || ''}
                class="thumb-img"
                use:handleImageError
              />
            </div>
          {/each}
          {#if remainingCount > 0}
            <div class="more-badge">+{remainingCount}</div>
          {/if}
        </div>
      {:else}
        <!-- Processing or no results yet: show query -->
        <div class="query-content">
          {#if query}
            <span class="query-text">{query}</span>
            <span class="via-text">{$text('embeds.via')} {provider}</span>
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
  .search-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-sizing: border-box;
  }

  /* Query content (processing state) */
  .query-content {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 16px 20px;
    overflow: hidden;
  }

  .query-text {
    font-size: 14px;
    color: var(--color-grey-70, #555);
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    word-break: break-word;
  }

  .via-text {
    font-size: 12px;
    font-weight: 600;
    color: var(--color-grey-50, #888);
    line-height: 1.4;
  }

  /* Thumbnail mosaic (finished state) */
  .thumbnail-mosaic {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    width: 100%;
    height: 100%;
    overflow: hidden;
    position: relative;
    gap: 1px;
    background: var(--color-grey-20, #eee);
  }

  .thumbnail-mosaic.single {
    grid-template-columns: 1fr;
    grid-template-rows: 1fr;
  }

  .thumb-slot {
    overflow: hidden;
    background: var(--color-grey-15, #f5f5f5);
  }

  .thumb-img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  /* "+N more" overlay badge */
  .more-badge {
    position: absolute;
    bottom: 8px;
    right: 8px;
    background: rgba(0, 0, 0, 0.6);
    color: #fff;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 7px;
    border-radius: 10px;
    backdrop-filter: blur(4px);
  }

  /* Skeleton lines */
  .skeleton-lines {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 16px 20px;
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

  /* Error state */
  .error-state {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px;
    background: var(--color-error-5, #fff5f5);
    border-radius: 6px;
    margin: 12px;
  }

  .error-icon {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--color-error-20, #f5c0c0);
    color: var(--color-error-70, #b04a4a);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    font-weight: 700;
    flex-shrink: 0;
  }

  .error-text {
    font-size: 13px;
    color: var(--color-error-70, #b04a4a);
    line-height: 1.4;
  }

  /* Dark mode */
  :global(.dark) .query-text     { color: var(--color-grey-40, #aaa); }
  :global(.dark) .via-text       { color: var(--color-grey-50, #888); }
  :global(.dark) .skeleton-line  { background: var(--color-grey-80, #333); }
  :global(.dark) .thumb-slot     { background: var(--color-grey-85, #222); }
  :global(.dark) .thumbnail-mosaic { background: var(--color-grey-85, #222); }

  :global(.dark) .error-state {
    background: var(--color-error-95, #2a1515);
  }

  :global(.dark) .error-text {
    color: var(--color-error-40, #d07a7a);
  }
</style>
