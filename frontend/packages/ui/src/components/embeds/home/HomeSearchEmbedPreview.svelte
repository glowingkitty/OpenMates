<!--
  frontend/packages/ui/src/components/embeds/home/HomeSearchEmbedPreview.svelte

  Preview component for Home Search skill embeds.
  Uses UnifiedEmbedPreview as base and provides skill-specific details content.

  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives query, provider, results directly

  Details content structure:
  - Processing: query text + "via Multi" (searching multiple housing providers)
  - Finished: query text + listing count + first 3 listing thumbnails

  NOTE: Real-time updates when embed status changes from 'processing' to 'finished'
  are handled by UnifiedEmbedPreview, which subscribes to embedUpdated events.
  This component implements the onEmbedDataUpdated callback to update its
  specific data (query, provider, results) when notified by the parent.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';
  import { chatSyncService } from '../../../services/chatSyncService';
  import { handleImageError } from '../../../utils/offlineImageHandler';

  /**
   * Home listing result interface for preview display.
   * Shows listing thumbnails and count in the finished state.
   */
  interface HomeListingResult {
    title?: string;
    image_url?: string;
    price_label?: string;
    provider?: string;
  }

  /**
   * Props for home search embed preview.
   * Supports both skill preview data format and direct embed format.
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Search query / city name (direct format) */
    query?: string;
    /** Provider label (direct format) */
    provider?: string;
    /** List of provider names that contributed results */
    providers?: string[];
    /** Processing status (direct format) */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Search results (for finished state) */
    results?: HomeListingResult[];
    /** Task ID for cancellation of entire AI response */
    taskId?: string;
    /** Skill task ID for cancellation of just this skill */
    skillTaskId?: string;
    /** Skill preview data (skill preview context) */
    previewData?: {
      query?: string;
      provider?: string;
      status?: string;
      results?: unknown[];
      task_id?: string;
      skill_task_id?: string;
    };
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen: () => void;
  }

  let {
    id,
    query: queryProp,
    provider: providerProp,
    providers: providersProp,
    status: statusProp,
    results: resultsProp,
    taskId: taskIdProp,
    skillTaskId: skillTaskIdProp,
    previewData,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // Local reactive state for embed data
  let localQuery = $state<string>('');
  let localProvider = $state<string>('Multi');
  let localProviders = $state<string[]>([]);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let localResults = $state<HomeListingResult[]>([]);
  let localTaskId = $state<string | undefined>(undefined);
  let localSkillTaskId = $state<string | undefined>(undefined);
  let isLoadingChildren = $state(false);
  let storeResolved = $state(false);

  // Initialize local state from props
  $effect(() => {
    if (!storeResolved) {
      if (previewData) {
        localQuery = previewData.query || '';
        localProvider = previewData.provider || 'Multi';
        localProviders = (previewData as Record<string, unknown>).providers as string[] || [];
        localStatus = (previewData.status as typeof localStatus) || 'processing';
        localResults = (previewData.results as HomeListingResult[]) || [];
        localTaskId = previewData.task_id;
        localSkillTaskId = previewData.skill_task_id;
      } else {
        localQuery = queryProp || '';
        localProvider = providerProp || 'Multi';
        localProviders = providersProp || [];
        localStatus = statusProp || 'processing';
        localResults = resultsProp || [];
        localTaskId = taskIdProp;
        localSkillTaskId = skillTaskIdProp;
      }
    }
  });

  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let providers = $derived(localProviders);
  let status = $derived(localStatus);
  let results = $derived(localResults);
  let taskId = $derived(localTaskId);
  let skillTaskId = $derived(localSkillTaskId);

  /**
   * Handle embed data updates from UnifiedEmbedPreview.
   * Called when the parent component receives and decodes updated embed data.
   */
  async function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    console.debug(`[HomeSearchEmbedPreview] Received embed data update for ${id}:`, {
      status: data.status,
      hasContent: !!data.decodedContent
    });

    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    if (data.status !== 'processing') {
      storeResolved = true;
    }

    const content = data.decodedContent;
    if (content) {
      if (typeof content.query === 'string') localQuery = content.query;
      if (typeof content.provider === 'string') localProvider = content.provider;
      if (Array.isArray(content.providers)) localProviders = content.providers as string[];
      if (typeof content.skill_task_id === 'string') localSkillTaskId = content.skill_task_id;

      if (content.results && Array.isArray(content.results)) {
        localResults = content.results as HomeListingResult[];
      }

      // Load child embeds when finished with embed_ids but no results
      if (data.status === 'finished' && (!content.results || !Array.isArray(content.results) || content.results.length === 0)) {
        const embedIds = content.embed_ids;
        if (embedIds) {
          const childEmbedIds: string[] = typeof embedIds === 'string'
            ? (embedIds as string).split('|').filter((id: string) => id.length > 0)
            : Array.isArray(embedIds) ? (embedIds as string[]) : [];

          if (childEmbedIds.length > 0 && !isLoadingChildren) {
            isLoadingChildren = true;
            loadChildEmbedsForPreview(childEmbedIds);
          }
        }
      }
    }
  }

  /**
   * Load child embeds to extract listing data for preview display.
   * Uses retry logic because child embeds might not be persisted yet.
   */
  async function loadChildEmbedsForPreview(childEmbedIds: string[]) {
    try {
      const { loadEmbedsWithRetry, decodeToonContent } = await import('../../../services/embedResolver');
      const childEmbeds = await loadEmbedsWithRetry(childEmbedIds, 5, 300);

      if (childEmbeds.length > 0) {
        const loadedResults = await Promise.all(childEmbeds.map(async (embed) => {
          const content = embed.content ? await decodeToonContent(embed.content) : null;
          if (!content) return null;

          return {
            title: content.title as string || '',
            image_url: content.image_url as string || undefined,
            price_label: content.price_label as string || undefined,
            provider: content.provider as string || undefined
          } as HomeListingResult;
        }));

        const validResults = loadedResults.filter(r => r !== null) as HomeListingResult[];
        if (validResults.length > 0) {
          localResults = validResults;
        }
      }
    } catch (error) {
      console.warn('[HomeSearchEmbedPreview] Error loading child embeds:', error);
    } finally {
      isLoadingChildren = false;
    }
  }

  let skillName = $derived($text('common.search'));
  const skillIconName = 'home';

  // "via {provider}" subtitle — use providers list when available for multi-source display
  let viaProvider = $derived.by(() => {
    const via = $text('embeds.via');
    if (providers.length > 0) {
      if (providers.length <= 2) {
        return `${via} ${providers.join(', ')}`;
      }
      return `${via} ${providers[0]}, ${providers[1]} +${providers.length - 2}`;
    }
    if (provider && provider !== 'Multi') {
      return `${via} ${provider}`;
    }
    return '';
  });

  /**
   * Flatten nested results structure from backend if needed.
   * Backend returns results as [{ id: X, results: [...] }] for multi-query searches.
   */
  function flattenResults(rawResults: unknown[]): HomeListingResult[] {
    if (!rawResults || rawResults.length === 0) return [];

    const firstItem = rawResults[0] as Record<string, unknown>;
    if (firstItem && 'results' in firstItem && Array.isArray(firstItem.results)) {
      const flattened: HomeListingResult[] = [];
      for (const entry of rawResults as Array<{ id?: string; results?: unknown[] }>) {
        if (entry.results && Array.isArray(entry.results)) {
          for (const rawResult of entry.results as Array<Record<string, unknown>>) {
            flattened.push({
              title: rawResult.title as string || '',
              image_url: rawResult.image_url as string || undefined,
              price_label: rawResult.price_label as string || undefined,
              provider: rawResult.provider as string || undefined
            });
          }
        }
      }
      return flattened;
    }

    return (rawResults as Array<Record<string, unknown>>).map(r => ({
      title: r.title as string || '',
      image_url: r.image_url as string || undefined,
      price_label: r.price_label as string || undefined,
      provider: r.provider as string || undefined
    }));
  }

  let flatResults = $derived(flattenResults(results));

  // Get first 3 results with images for thumbnail display
  let imageResults = $derived(
    flatResults?.filter(r => r.image_url).slice(0, 3) || []
  );

  let remainingCount = $derived(
    Math.max(0, (flatResults?.length || 0) - imageResults.length)
  );

  /**
   * Handle stop button click — cancels this specific skill, not the entire AI response.
   */
  async function handleStop() {
    if (status !== 'processing') return;

    if (skillTaskId) {
      try {
        await chatSyncService.sendCancelSkill(skillTaskId, id);
      } catch (error) {
        console.error(`[HomeSearchEmbedPreview] Failed to cancel skill:`, error);
      }
    } else if (taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
      } catch (error) {
        console.error(`[HomeSearchEmbedPreview] Failed to cancel task:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="home"
  skillId="search"
  skillIconName={skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="home-search-details" class:mobile={isMobileLayout}>
      <!-- Query text (city name) -->
      <div class="search-query">{query}</div>

      <!-- Provider subtitle -->
      <div class="search-provider">{viaProvider}</div>

      {#if status === 'error'}
        <div class="search-error">
          <div class="search-error-title">{$text('common.search')} failed</div>
        </div>
      {:else if status === 'finished'}
        <div class="search-results-info">
          {#if flatResults.length === 0}
            {#if isLoadingChildren}
              <span class="no-results-text">{$text('common.loading')}</span>
            {:else}
              <span class="no-results-text">{$text('embeds.search_no_results')}</span>
            {/if}
          {:else}
            <!-- Listing thumbnails row -->
            {#if imageResults.length > 0}
              <div class="thumbnail-row">
                {#each imageResults as result, index}
                  {#if result.image_url}
                    <img
                      src={proxyImage(result.image_url, MAX_WIDTH_PREVIEW_THUMBNAIL)}
                      alt=""
                      class="listing-thumbnail"
                      style="z-index: {imageResults.length - index};"
                      loading="lazy"
                      crossorigin="anonymous"
                      onerror={(e) => { handleImageError(e.currentTarget as HTMLImageElement); }}
                    />
                  {/if}
                {/each}
              </div>
            {/if}

            {#if remainingCount > 0}
              <span class="remaining-count">
                {$text('embeds.more_results').replace('{count}', String(remainingCount))}
              </span>
            {/if}
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .home-search-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }

  .home-search-details:not(.mobile) {
    justify-content: center;
  }

  .home-search-details.mobile {
    justify-content: flex-start;
  }

  .search-query {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  .home-search-details.mobile .search-query {
    font-size: 14px;
    -webkit-line-clamp: 4;
    line-clamp: 4;
  }

  .search-provider {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }

  .home-search-details.mobile .search-provider {
    font-size: 12px;
  }

  .search-results-info {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 4px;
  }

  .home-search-details.mobile .search-results-info {
    margin-top: 2px;
  }

  .no-results-text {
    font-size: 13px;
    font-weight: 500;
    color: var(--color-grey-60);
    font-style: italic;
  }

  .search-error {
    margin-top: 6px;
    padding: 8px 10px;
    border-radius: 12px;
    background-color: rgba(var(--color-error-rgb), 0.08);
    border: 1px solid rgba(var(--color-error-rgb), 0.3);
  }

  .search-error-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-error);
  }

  /* Listing thumbnail row: overlapping rounded squares */
  .thumbnail-row {
    display: flex;
    align-items: center;
    position: relative;
    height: 32px;
    min-width: 60px;
  }

  .listing-thumbnail {
    width: 32px;
    height: 32px;
    border-radius: 8px;
    border: 2px solid var(--color-grey-0);
    background-color: var(--color-grey-30);
    object-fit: cover;
    margin-left: -8px;
    position: relative;
  }

  .listing-thumbnail:first-child {
    margin-left: 0;
  }

  .remaining-count {
    font-size: 14px;
    color: var(--color-grey-70);
    font-weight: 500;
  }

  .home-search-details.mobile .remaining-count {
    font-size: 12px;
  }

  /* Skill icon styling for home */
  :global(.unified-embed-preview .skill-icon[data-skill-icon="home"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/home.svg');
    mask-image: url('@openmates/ui/static/icons/home.svg');
  }

  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="home"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/home.svg');
    mask-image: url('@openmates/ui/static/icons/home.svg');
  }
</style>
