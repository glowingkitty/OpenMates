<!--
  frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedFullscreen.svelte

  Fullscreen view for Images Search skill embeds (images/search).
  Uses UnifiedEmbedFullscreen as base with unified child embed loading.

  Shows:
  - Header with search query and "via {provider}"
  - Grid of ImageResultEmbedPreview cards loaded from child embeds
  - Drill-down: clicking a card opens ImageResultEmbedFullscreen overlay

  Architecture: Child embeds are loaded via embedIds + childEmbedTransformer,
  same pattern as events/news/travel search embeds.
  See docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import ImageResultEmbedPreview from './ImageResultEmbedPreview.svelte';
  import ImageResultEmbedFullscreen from './ImageResultEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { proxyImage } from '../../../utils/imageProxy';


  /**
   * Single image result (child embed content schema).
   * Matches fields written by backend/apps/images/skills/search_skill.py
   */
  interface ImageResult {
    /** Child embed ID (required for keying #each) */
    embed_id: string;
    title?: string;
    source_page_url?: string;
    image_url?: string;
    thumbnail_url?: string;
    source?: string;
    favicon_url?: string;
  }

  interface Props {
    /** Search query */
    query: string;
    /** Search provider (e.g., 'Brave', 'SerpAPI Google Lens') */
    provider: string;
    /** Pipe-separated embed IDs or array — loaded by UnifiedEmbedFullscreen */
    embedIds?: string | string[];
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Close handler */
    onClose: () => void;
    /** Optional: parent embed ID for sharing */
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
    /** Child embed ID to auto-open on mount (from inline badge click) */
    initialChildEmbedId?: string;
  }

  let {
    query: queryProp,
    provider: providerProp,
    embedIds,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    status: statusProp,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
    initialChildEmbedId
  }: Props = $props();

  // Local reactive state
  let localQuery    = $state('');
  let localProvider = $state('Brave');
  let embedIdsOverride = $state<string | string[] | undefined>(undefined);
  let embedIdsValue    = $derived(embedIdsOverride ?? embedIds);

  $effect(() => {
    localQuery    = queryProp    || '';
    localProvider = providerProp || 'Brave';
  });

  let query    = $derived(localQuery);
  let provider = $derived(localProvider);

  let embedHeaderTitle    = $derived(query);
  let embedHeaderSubtitle = $derived(`${$text('embeds.via')} ${provider}`);

  // Drill-down state
  /** Index of the currently selected result in allResults. -1 = closed */
  let selectedIndex = $state(-1);
  let allResults    = $state<ImageResult[]>([]);

  function handleResultClick(index: number) {
    selectedIndex = index;
  }

  function handleResultClose() {
    if (initialChildEmbedId) {
      onClose();
    } else {
      selectedIndex = -1;
    }
  }

  function handleMainClose() {
    if (selectedIndex >= 0 && !initialChildEmbedId) {
      selectedIndex = -1;
    } else {
      onClose();
    }
  }

  function handleResultPrevious() {
    if (selectedIndex > 0) selectedIndex -= 1;
  }

  function handleResultNext() {
    if (selectedIndex < allResults.length - 1) selectedIndex += 1;
  }

  let selectedResult = $derived(
    selectedIndex >= 0 ? allResults[selectedIndex] : undefined
  );

  /**
   * Transform raw decoded child embed content into a typed ImageResult.
   * Called once per child embed by UnifiedEmbedFullscreen.
   */
  function transformToImageResult(childEmbedId: string, content: Record<string, unknown>): ImageResult {
    return {
      embed_id:       childEmbedId,
      title:          content.title          as string | undefined,
      source_page_url: content.source_page_url as string | undefined,
      image_url:      content.image_url      as string | undefined,
      thumbnail_url:  content.thumbnail_url  as string | undefined,
      source:         content.source         as string | undefined,
      favicon_url:    content.favicon_url    as string | undefined,
    };
  }

  /**
   * Handle embed data updates (e.g. embed_ids arriving mid-stream).
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (data.decodedContent) {
      const c = data.decodedContent as Record<string, unknown>;
      if (c.query)    localQuery    = c.query    as string;
      if (c.provider) localProvider = c.provider as string;
      if (c.embed_ids) embedIdsOverride = c.embed_ids as string | string[];
    }
  }

  /** Proxy an external image URL */
  function proxyUrl(url: string | undefined): string | undefined {
    if (!url) return undefined;
    return proxyImage(url);
  }
</script>

<UnifiedEmbedFullscreen
  appId="images"
  skillId="search"
  skillIconName="search"
  {embedHeaderTitle}
  {embedHeaderSubtitle}
  showSkillIcon={true}
  onClose={handleMainClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToImageResult}
  onChildrenLoaded={(children) => { allResults = children as ImageResult[]; }}
  {initialChildEmbedId}
  onAutoOpenChild={(index, children) => {
    allResults = children as ImageResult[];
    selectedIndex = index;
  }}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet content(ctx)}
    {@const imageResults = ctx.children as ImageResult[]}
    {@const isLoadingChildren = ctx.isLoadingChildren}
    <div class="images-grid-container">
      {#if isLoadingChildren && (!imageResults || imageResults.length === 0)}
        <!-- Loading skeleton grid -->
        <div class="images-grid">
          {#each Array.from({ length: 8 }, (__, idx) => idx) as i (i)}
            <div class="result-skeleton">
              <div class="skeleton-image"></div>
              <div class="skeleton-title"></div>
            </div>
          {/each}
        </div>
      {:else if imageResults && imageResults.length > 0}
        <div class="images-grid">
          {#each imageResults as result, i (result.embed_id)}
            <button
              class="result-card"
              onclick={() => handleResultClick(i)}
              aria-label={result.title || 'Image result'}
            >
              <ImageResultEmbedPreview
                title={result.title}
                sourceDomain={result.source}
                thumbnailUrl={proxyUrl(result.thumbnail_url || result.image_url)}
                faviconUrl={result.favicon_url}
              />
            </button>
          {/each}
        </div>
      {:else}
        <!-- Empty state -->
        <div class="empty-state">
          <span class="empty-icon clickable-icon icon_image"></span>
          <p class="empty-text">{$text('embeds.image_search.error')}</p>
        </div>
      {/if}

    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

{#if selectedResult}
  <ChildEmbedOverlay>
    <ImageResultEmbedFullscreen
      title={selectedResult.title}
      sourceDomain={selectedResult.source}
      sourcePageUrl={selectedResult.source_page_url}
      imageUrl={proxyUrl(selectedResult.image_url || selectedResult.thumbnail_url)}
      thumbnailUrl={proxyUrl(selectedResult.thumbnail_url || selectedResult.image_url)}
      faviconUrl={selectedResult.favicon_url}
      embedId={selectedResult.embed_id}
      hasPreviousEmbed={selectedIndex > 0}
      hasNextEmbed={selectedIndex < allResults.length - 1}
      onNavigatePrevious={handleResultPrevious}
      onNavigateNext={handleResultNext}
      onClose={handleResultClose}
    />
  </ChildEmbedOverlay>
{/if}

<style>
  .images-grid-container {
    width: 100%;
    height: 100%;
    overflow-y: auto;
    padding: 20px;
    box-sizing: border-box;
  }

  .images-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
  }

  /* Result card button - clickable image card */
  .result-card {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    text-align: left;
    border-radius: 10px;
    overflow: hidden;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }

  .result-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  }

  /* Skeleton loading state */
  .result-skeleton {
    border-radius: 10px;
    overflow: hidden;
    background: var(--color-grey-10, #f5f5f5);
  }

  .skeleton-image {
    width: 100%;
    aspect-ratio: 4/3;
    background: var(--color-grey-15, #ebebeb);
    animation: pulse 1.5s ease-in-out infinite;
  }

  .skeleton-title {
    height: 12px;
    margin: 8px 10px;
    background: var(--color-grey-15, #ebebeb);
    border-radius: 4px;
    animation: pulse 1.5s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50%       { opacity: 1; }
  }

  /* Empty state */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 48px 24px;
    gap: 12px;
  }

  .empty-icon {
    width: 40px;
    height: 40px;
    background: var(--color-grey-40, #aaa) !important;
  }

  .empty-text {
    font-size: 14px;
    color: var(--color-grey-50, #888);
    margin: 0;
    text-align: center;
  }

  /* Dark mode */
  :global(.dark) .result-skeleton,
  :global(.dark) .skeleton-image,
  :global(.dark) .skeleton-title {
    background: var(--color-grey-85, #222);
  }

  :global(.dark) .result-card:hover {
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  }

  :global(.dark) .empty-text {
    color: var(--color-grey-50, #888);
  }

  @container fullscreen (max-width: 500px) {
    .images-grid {
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
      gap: 8px;
    }

    .images-grid-container {
      padding: 12px;
    }
  }
</style>
