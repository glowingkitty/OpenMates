<!--
  frontend/packages/ui/src/components/embeds/NewsSearchEmbedFullscreen.svelte
  
  Fullscreen view for News Search skill embeds.
  Uses UnifiedEmbedFullscreen as base with unified child embed loading.
  
  Shows:
  - Header with search query and "via {provider}" formatting (60px top margin, 40px bottom margin)
  - News article embeds in a grid (auto-responsive columns)
  - Consistent BasicInfosBar at the bottom (matches preview - "Search" + "Completed")
  - Top bar with share, copy, and minimize buttons
  
  Child embeds are automatically loaded by UnifiedEmbedFullscreen from embedIds prop.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import WebsiteEmbedPreview from '../web/WebsiteEmbedPreview.svelte';
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
  }
  
  let {
    query,
    provider,
    embedIds,
    results: resultsProp = [],
    onClose,
    embedId
  }: Props = $props();
  
  // Determine if mobile layout
  let isMobile = $derived(
    typeof window !== 'undefined' && window.innerWidth <= 500
  );
  
  // Get skill name from translations (matches preview)
  let skillName = $derived($text('embeds.search.text') || 'Search');
  
  // Get "via {provider}" text from translations
  let viaProvider = $derived(
    `${$text('embeds.via.text') || 'via'} ${provider}`
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
  
  // Handle share - opens share settings menu for this specific news search embed
  async function handleShare() {
    try {
      console.debug('[NewsSearchEmbedFullscreen] Opening share settings for news search embed:', {
        embedId,
        query,
        provider
      });

      // Check if we have embed_id for proper sharing
      if (!embedId) {
        console.warn('[NewsSearchEmbedFullscreen] No embed_id available - cannot create encrypted share link');
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.error('Unable to share this news search embed. Missing embed ID.');
        return;
      }

      // Import required modules
      const { navigateToSettings } = await import('../../../stores/settingsNavigationStore');
      const { settingsDeepLink } = await import('../../../stores/settingsDeepLinkStore');
      const { panelState } = await import('../../../stores/panelStateStore');

      // Set embed context with embed_id for proper encrypted sharing
      const embedContext = {
        type: 'news_search',
        embed_id: embedId,
        query: query,
        provider: provider
      };

      // Store embed context for SettingsShare
      (window as unknown as { __embedShareContext?: unknown }).__embedShareContext = embedContext;

      // Navigate to share settings
      navigateToSettings('shared/share', 'Share News Search', 'share', 'settings.share.share_news_search.text');
      
      // Also set settingsDeepLink to ensure Settings component navigates properly
      settingsDeepLink.set('shared/share');

      // Open settings panel
      panelState.openSettings();

      console.debug('[NewsSearchEmbedFullscreen] Opened share settings for news search embed');
    } catch (error) {
      console.error('[NewsSearchEmbedFullscreen] Error opening share settings:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to open share menu. Please try again.');
    }
  }
  
  // Handle opening search in provider
  function handleOpenInProvider() {
    const searchUrl = `https://search.brave.com/search?q=${encodeURIComponent(query)}`;
    window.open(searchUrl, '_blank', 'noopener,noreferrer');
  }
  
  // Handle article fullscreen (from WebsiteEmbedPreview)
  function handleArticleFullscreen(articleData: NewsSearchResult) {
    // For now, just open the article in a new tab
    // In the future, we could show a reader view fullscreen
    if (articleData.url) {
      window.open(articleData.url, '_blank', 'noopener,noreferrer');
    }
  }
</script>

<!-- 
  Pass skillName and showStatus to UnifiedEmbedFullscreen for consistent BasicInfosBar
  that matches the embed preview (shows "Search" + "Completed", not the query)
  
  Child embeds are loaded automatically via embedIds prop and passed to content snippet
  The childEmbedTransformer converts raw embed data to NewsSearchResult format
-->
<UnifiedEmbedFullscreen
  onShare={handleShare}
  appId="news"
  skillId="search"
  title=""
  {onClose}
  onOpen={handleOpenInProvider}
  skillIconName="search"
  status="finished"
  {skillName}
  showStatus={true}
  {embedIds}
  childEmbedTransformer={transformToNewsResult}
  legacyResults={resultsProp}
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
        <p>{$text('embeds.loading.text') || 'Loading...'}</p>
      </div>
    {:else if newsResults.length === 0}
      <div class="no-results">
        <p>{$text('embeds.no_results.text') || 'No search results available.'}</p>
      </div>
    {:else}
      <!-- News article embeds grid - responsive auto-fill columns -->
      <div class="article-embeds-grid" class:mobile={isMobile}>
        {#each newsResults as result}
          <WebsiteEmbedPreview
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

