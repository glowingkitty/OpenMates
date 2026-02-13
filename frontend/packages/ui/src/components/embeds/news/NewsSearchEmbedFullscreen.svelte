<!--
  frontend/packages/ui/src/components/embeds/news/NewsSearchEmbedFullscreen.svelte
  
  Fullscreen view for News Search skill embeds.
  Uses UnifiedEmbedFullscreen as base with unified child embed loading.
  
  Shows:
  - Header with search query and "via {provider}" formatting (60px top margin, 40px bottom margin)
  - News article embeds in a grid (auto-responsive columns)
  - Consistent BasicInfosBar at the bottom (matches preview - "Search" + "Completed")
  - Top bar with share, copy, and minimize buttons
  
  Child embeds are automatically loaded by UnifiedEmbedFullscreen from embedIds prop.
  
  News Article Fullscreen Navigation (Overlay Pattern):
  - Search results grid is ALWAYS rendered (base layer)
  - When a news article is clicked, NewsEmbedFullscreen renders as an OVERLAY on top
  - When NewsEmbedFullscreen is closed, overlay is removed revealing search results beneath
  
  Benefits of overlay approach:
  - No re-animation when returning to search results (they're already rendered beneath)
  - No re-loading of child embeds
  - Scroll position preserved on search results
  - Instant close transition since search results are always visible
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import NewsEmbedPreview from './NewsEmbedPreview.svelte';
  import NewsEmbedFullscreen from './NewsEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  
  /**
   * News search result interface (transformed from child embeds)
   */
  interface NewsSearchResult {
    embed_id: string;
    title?: string;
    url: string;
    favicon_url?: string;
    thumbnail?: string;
    description?: string;
  }
  
  /**
   * Props for news search embed fullscreen
   * Child embeds are loaded automatically via UnifiedEmbedFullscreen
   */
  interface Props {
    /** Search query */
    query: string;
    /** Search provider (e.g., 'Brave Search') */
    provider: string;
    /** Pipe-separated embed IDs or array of embed IDs for child news embeds */
    embedIds?: string | string[];
    /** Legacy: Search results (fallback if embedIds not provided) */
    results?: NewsSearchResult[];
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing (from embed:{embed_id} contentRef) */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button to restore chat visibility (ultra-wide forceOverlayMode) */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button to restore chat visibility */
    onShowChat?: () => void;
  }
  
  let {
    query,
    provider,
    embedIds,
    results: resultsProp = [],
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat
  }: Props = $props();
  
  // Debug: Log what props NewsSearchEmbedFullscreen receives
  $effect(() => {
    console.debug('[NewsSearchEmbedFullscreen] 📰 Props received:', {
      query,
      provider,
      embedIds,
      embedIds_type: typeof embedIds,
      embedIds_length: Array.isArray(embedIds) ? embedIds.length : (typeof embedIds === 'string' ? embedIds.length : 0),
      resultsProp_length: resultsProp?.length || 0,
      resultsProp_sample: resultsProp?.slice(0, 2),
      embedId
    });
  });
  
  // ============================================
  // State: Track which article is shown in fullscreen
  // ============================================
  
  /** Currently selected article for fullscreen view (null = show search results) */
  let selectedArticle = $state<NewsSearchResult | null>(null);
  
  // Determine if mobile layout
  let isMobile = $derived(
    typeof window !== 'undefined' && window.innerWidth <= 500
  );
  
  // Get skill name from translations (matches preview)
  let skillName = $derived($text('embeds.search') || 'Search');
  
  // Get "via {provider}" text from translations
  let viaProvider = $derived(
    `${$text('embeds.via') || 'via'} ${provider}`
  );
  
  /**
   * Transform raw embed content to NewsSearchResult format
   * Used by UnifiedEmbedFullscreen's childEmbedTransformer
   */
  function transformToNewsResult(embedId: string, content: Record<string, unknown>): NewsSearchResult {
    // Handle nested meta_url and thumbnail objects
    const metaUrl = content.meta_url as Record<string, string> | undefined;
    const thumbnail = content.thumbnail as Record<string, string> | undefined;
    
    return {
      embed_id: embedId,
      title: content.title as string | undefined,
      url: content.url as string,
      favicon_url: (content.favicon_url as string) || metaUrl?.favicon,
      thumbnail: thumbnail?.original,
      description: (content.description as string) || (content.snippet as string)
    };
  }
  
  /**
   * Transform legacy results to NewsSearchResult format (for backwards compatibility)
   */
  function transformLegacyResults(results: unknown[]): NewsSearchResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => {
      const metaUrl = r.meta_url as Record<string, string> | undefined;
      const thumbnail = r.thumbnail as Record<string, string> | undefined;
      
      return {
        embed_id: `legacy-${i}`,
        title: r.title as string | undefined,
        url: r.url as string,
        favicon_url: (r.favicon_url as string) || metaUrl?.favicon,
        thumbnail: thumbnail?.original,
        description: (r.description as string) || (r.snippet as string)
      };
    });
  }
  
  /**
   * Get news results from context (children or legacy)
   * Children are cast to NewsSearchResult[] since we pass transformToNewsResult as transformer
   */
  function getNewsResults(ctx: ChildEmbedContext): NewsSearchResult[] {
    // Use loaded children if available (cast since transformer returns NewsSearchResult)
    if (ctx.children && ctx.children.length > 0) {
      return ctx.children as NewsSearchResult[];
    }
    // Fallback to legacy results
    if (ctx.legacyResults && ctx.legacyResults.length > 0) {
      return transformLegacyResults(ctx.legacyResults);
    }
    return [];
  }
  
  // Share is handled by UnifiedEmbedFullscreen's built-in share handler
  // which uses currentEmbedId, appId, and skillId to construct the embed
  // share context and properly opens the settings panel (including on mobile).
  
  /**
   * Handle article click - shows the article in fullscreen mode
   * Uses NewsEmbedFullscreen for full article view experience
   */
  function handleArticleFullscreen(articleData: NewsSearchResult) {
    console.debug('[NewsSearchEmbedFullscreen] Opening article fullscreen:', {
      embedId: articleData.embed_id,
      url: articleData.url,
      title: articleData.title
    });
    selectedArticle = articleData;
  }
  
  /**
   * Handle closing the article fullscreen - returns to search results
   * Called when user clicks minimize button on NewsEmbedFullscreen
   */
  function handleArticleFullscreenClose() {
    console.debug('[NewsSearchEmbedFullscreen] Closing article fullscreen, returning to search results');
    selectedArticle = null;
  }
  
  /**
   * Handle closing the entire search fullscreen
   * Called when user closes the main NewsSearchEmbedFullscreen
   */
  function handleMainClose() {
    // If an article is open, first close it and return to search results
    if (selectedArticle) {
      selectedArticle = null;
    } else {
      // Otherwise, close the entire fullscreen
      onClose();
    }
  }
</script>

<!-- 
  Overlay-based rendering approach for smooth transitions:
  - NewsSearchEmbedFullscreen (search results grid) is ALWAYS mounted
  - NewsEmbedFullscreen renders as an OVERLAY on top when an article is selected
  
  Benefits of this approach:
  - No re-animation when returning to search results (already visible beneath)
  - No re-loading of child embeds
  - Scroll position is preserved on search results
  - Instant close transition since search results are already there
-->

<!-- Search results view - ALWAYS rendered (base layer) -->
<!-- 
  Pass skillName and showStatus to UnifiedEmbedFullscreen for consistent BasicInfosBar
  that matches the embed preview (shows "Search" + "Completed", not the query)
  
  Child embeds are loaded automatically via embedIds prop and passed to content snippet
  The childEmbedTransformer converts raw embed data to NewsSearchResult format
-->
<UnifiedEmbedFullscreen
  appId="news"
  skillId="search"
  title=""
  onClose={handleMainClose}
  currentEmbedId={embedId}
  skillIconName="search"
  status="finished"
  {skillName}
  showStatus={true}
  {embedIds}
  childEmbedTransformer={transformToNewsResult}
  legacyResults={resultsProp}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content(ctx)}
    {@const newsResults = getNewsResults(ctx)}
    
    <!-- Header with search query and provider - 60px top margin, 40px bottom margin -->
    <div class="fullscreen-header">
      <div class="search-query">{query}</div>
      <div class="search-provider">{viaProvider}</div>
    </div>
    
    {#if ctx.isLoadingChildren}
      <div class="loading-state">
        <p>{$text('embeds.loading') || 'Loading...'}</p>
      </div>
    {:else if newsResults.length === 0}
      <div class="no-results">
        <p>{$text('embeds.no_results') || 'No search results available.'}</p>
      </div>
    {:else}
      <!-- News article embeds grid - responsive auto-fill columns -->
      <div class="article-embeds-grid" class:mobile={isMobile}>
        {#each newsResults as result}
          <NewsEmbedPreview
            id={result.embed_id}
            url={result.url}
            title={result.title}
            description={result.description}
            favicon={result.favicon_url}
            image={result.thumbnail}
            status="finished"
            isMobile={false}
            onFullscreen={() => handleArticleFullscreen(result)}
          />
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<!-- Article fullscreen overlay - rendered ON TOP when an article is selected -->
<!-- Uses ChildEmbedOverlay for consistent overlay positioning across all search fullscreens -->
{#if selectedArticle}
  <ChildEmbedOverlay>
    <NewsEmbedFullscreen
      url={selectedArticle.url}
      title={selectedArticle.title}
      description={selectedArticle.description}
      favicon={selectedArticle.favicon_url}
      thumbnail={selectedArticle.thumbnail}
      onClose={handleArticleFullscreenClose}
      embedId={selectedArticle.embed_id}
    />
  </ChildEmbedOverlay>
{/if}

<style>
  /* ===========================================
     Fullscreen Header - Query and Provider
     =========================================== */
  
  .fullscreen-header {
    margin-top: 60px;
    margin-bottom: 40px;
    padding: 0 16px;
    text-align: center;
  }
  
  .search-query {
    font-size: 24px;
    font-weight: 600;
    color: var(--color-font-primary);
    line-height: 1.3;
    word-break: break-word;
    /* Limit to 3 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  
  .search-provider {
    font-size: 16px;
    color: var(--color-font-secondary);
    margin-top: 8px;
  }
  
  /* ===========================================
     Loading and No Results States
     =========================================== */
  
  .loading-state,
  .no-results {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: 16px;
  }
  
  /* ===========================================
     Article Embeds Grid - Responsive Layout
     =========================================== */
  
  .article-embeds-grid {
    display: grid;
    gap: 16px;
    width: calc(100% - 20px);
    max-width: 1000px;
    margin: 0 auto;
    padding: 0 10px;
    padding-bottom: 120px; /* Space for bottom bar + gradient */
    /* Responsive: auto-fit columns with minimum 280px width */
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  }
  
  /* Mobile: single column (stacked) */
  .article-embeds-grid.mobile {
    grid-template-columns: 1fr;
  }
  
  /* Ensure each embed maintains proper size */
  .article-embeds-grid :global(.unified-embed-preview) {
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
  }
</style>

