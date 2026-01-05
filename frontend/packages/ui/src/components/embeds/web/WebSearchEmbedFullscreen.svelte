<!--
  frontend/packages/ui/src/components/embeds/web/WebSearchEmbedFullscreen.svelte
  
  Fullscreen view for Web Search skill embeds.
  Uses UnifiedEmbedFullscreen as base with unified child embed loading.
  
  Shows:
  - Header with search query and "via {provider}" formatting (60px top margin, 40px bottom margin)
  - Website embeds in a grid (auto-responsive columns)
  - Consistent BasicInfosBar at the bottom (matches preview - "Search" + "Completed")
  - Top bar with share and minimize buttons
  
  Child embeds are automatically loaded by UnifiedEmbedFullscreen from embedIds prop.
  
  Website Fullscreen Navigation (Overlay Pattern):
  - Search results grid is ALWAYS rendered (base layer)
  - When a website result is clicked, WebsiteEmbedFullscreen renders as an OVERLAY on top
  - When WebsiteEmbedFullscreen is closed, overlay is removed revealing search results beneath
  
  Benefits of overlay approach:
  - No re-animation when returning to search results (they're already rendered beneath)
  - No re-loading of child embeds
  - Scroll position is preserved on search results
  - Instant "close" transition since search results are always visible
  
  Supports both contexts:
  - Embed context: receives embedIds for child embed loading
  - Skill preview context: receives previewData from skillPreviewService (legacy)
  - Direct results: receives results array directly (legacy fallback)
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import WebsiteEmbedPreview from './WebsiteEmbedPreview.svelte';
  import WebsiteEmbedFullscreen from './WebsiteEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import type { WebSearchSkillPreviewData } from '../../../types/appSkills';
  
  /**
   * Web search result interface (transformed from child embeds)
   * Contains all data needed to display website in both preview and fullscreen
   */
  interface WebSearchResult {
    embed_id: string;
    title?: string;
    url: string;
    favicon_url?: string;
    preview_image_url?: string;
    snippet?: string;
    /** Additional description (may be longer than snippet) */
    description?: string;
    /** Snippets array for fullscreen view */
    snippets?: string[];
  }
  
  /**
   * Props for web search embed fullscreen
   * Child embeds are loaded automatically via UnifiedEmbedFullscreen
   */
  interface Props {
    /** Search query (direct format) */
    query?: string;
    /** Search provider (e.g., 'Brave Search') (direct format) */
    provider?: string;
    /** Pipe-separated embed IDs or array of embed IDs for child website embeds */
    embedIds?: string | string[];
    /** Legacy: Search results (direct format, used if embedIds not provided) */
    results?: WebSearchResult[];
    /** Legacy: Skill preview data (skill preview context) */
    previewData?: WebSearchSkillPreviewData;
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing (from embed:{embed_id} contentRef) */
    embedId?: string;
  }
  
  let {
    query: queryProp,
    provider: providerProp,
    embedIds,
    results: resultsProp,
    previewData,
    onClose,
    embedId
  }: Props = $props();
  
  // ============================================
  // State: Track which website is shown in fullscreen
  // ============================================
  
  /** Currently selected website for fullscreen view (null = show search results) */
  let selectedWebsite = $state<WebSearchResult | null>(null);
  
  // Extract values from either previewData (skill preview context) or direct props (embed context)
  let query = $derived(previewData?.query || queryProp || '');
  let provider = $derived(previewData?.provider || providerProp || 'Brave Search');
  // Legacy results from previewData or direct results prop (used as fallback)
  let legacyResults = $derived(previewData?.results || resultsProp || []);
  
  // Get skill name from translations (matches preview)
  let skillName = $derived($text('embeds.search.text') || 'Search');
  
  // Get "via {provider}" text from translations
  let viaProvider = $derived(
    `${$text('embeds.via.text') || 'via'} ${provider}`
  );
  
  /**
   * Transform raw embed content to WebSearchResult format
   * Used by UnifiedEmbedFullscreen's childEmbedTransformer
   * Extracts all available fields for both preview and fullscreen views
   */
  function transformToWebResult(embedId: string, content: Record<string, unknown>): WebSearchResult {
    return {
      embed_id: embedId,
      title: content.title as string | undefined,
      url: content.url as string,
      favicon_url: (content.favicon_url || content.meta_url_favicon) as string | undefined,
      preview_image_url: (content.preview_image_url || content.thumbnail_original || content.image) as string | undefined,
      snippet: (content.snippet as string) || (content.description as string),
      description: content.description as string | undefined,
      snippets: content.snippets as string[] | undefined
    };
  }
  
  /**
   * Transform legacy results to WebSearchResult format (for backwards compatibility)
   */
  function transformLegacyResults(results: unknown[]): WebSearchResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => ({
      embed_id: `legacy-${i}`,
      title: r.title as string | undefined,
      url: r.url as string,
      favicon_url: (r.favicon_url || r.meta_url_favicon) as string | undefined,
      preview_image_url: (r.preview_image_url || r.thumbnail_original || r.image) as string | undefined,
      snippet: (r.snippet as string) || (r.description as string),
      description: r.description as string | undefined,
      snippets: r.snippets as string[] | undefined
    }));
  }
  
  /**
   * Get web results from context (children or legacy)
   * Children are cast to WebSearchResult[] since we pass transformToWebResult as transformer
   */
  function getWebResults(ctx: ChildEmbedContext): WebSearchResult[] {
    // Use loaded children if available (cast since transformer returns WebSearchResult)
    if (ctx.children && ctx.children.length > 0) {
      return ctx.children as WebSearchResult[];
    }
    // Fallback to legacy results
    if (ctx.legacyResults && ctx.legacyResults.length > 0) {
      return transformLegacyResults(ctx.legacyResults);
    }
    return [];
  }
  
  /**
   * Handle website click - shows the website in fullscreen mode
   * Instead of opening in new tab, we display WebsiteEmbedFullscreen
   */
  function handleWebsiteFullscreen(websiteData: WebSearchResult) {
    console.debug('[WebSearchEmbedFullscreen] Opening website fullscreen:', {
      embedId: websiteData.embed_id,
      url: websiteData.url,
      title: websiteData.title
    });
    selectedWebsite = websiteData;
  }
  
  /**
   * Handle closing the website fullscreen - returns to search results
   * Called when user clicks minimize button on WebsiteEmbedFullscreen
   */
  function handleWebsiteFullscreenClose() {
    console.debug('[WebSearchEmbedFullscreen] Closing website fullscreen, returning to search results');
    selectedWebsite = null;
  }
  
  /**
   * Handle closing the entire search fullscreen
   * Called when user closes the main WebSearchEmbedFullscreen
   */
  function handleMainClose() {
    // If a website is open, first close it and return to search results
    if (selectedWebsite) {
      selectedWebsite = null;
    } else {
      // Otherwise, close the entire fullscreen
      onClose();
    }
  }

  // Handle share - opens share settings menu for this specific web search embed
  async function handleShare() {
    try {
      console.debug('[WebSearchEmbedFullscreen] Opening share settings for web search embed:', {
        embedId,
        query,
        provider
      });

      // Check if we have embed_id for proper sharing
      if (!embedId) {
        console.warn('[WebSearchEmbedFullscreen] No embed_id available - cannot create encrypted share link');
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.error('Unable to share this web search embed. Missing embed ID.');
        return;
      }

      // Import required modules
      const { navigateToSettings } = await import('../../../stores/settingsNavigationStore');
      const { settingsDeepLink } = await import('../../../stores/settingsDeepLinkStore');
      const { panelState } = await import('../../../stores/panelStateStore');

      // Set embed context with embed_id for proper encrypted sharing
      const embedContext = {
        type: 'web_search',
        embed_id: embedId,
        query: query,
        provider: provider
      };

      // Store embed context for SettingsShare
      (window as unknown as { __embedShareContext?: unknown }).__embedShareContext = embedContext;

      // Navigate to share settings
      navigateToSettings('shared/share', 'Share Web Search', 'share', 'settings.share.share_web_search.text');
      
      // Also set settingsDeepLink to ensure Settings component navigates properly
      settingsDeepLink.set('shared/share');

      // Open settings panel
      panelState.openSettings();

      console.debug('[WebSearchEmbedFullscreen] Opened share settings for web search embed');
    } catch (error) {
      console.error('[WebSearchEmbedFullscreen] Error opening share settings:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to open share menu. Please try again.');
    }
  }
</script>

<!-- 
  Overlay-based rendering approach for smooth transitions:
  - WebSearchEmbedFullscreen (search results grid) is ALWAYS mounted
  - WebsiteEmbedFullscreen renders as an OVERLAY on top when a website is selected
  
  Benefits of this approach:
  - No re-animation when returning to search results (already visible beneath)
  - No re-loading of child embeds
  - Scroll position is preserved on search results
  - Instant "close" transition since search results are already there
-->

<!-- Search results view - ALWAYS rendered (base layer) -->
<!-- 
  Pass skillName and showStatus to UnifiedEmbedFullscreen for consistent BasicInfosBar
  that matches the embed preview (shows "Search" + "Completed", not the query)
  
  Child embeds are loaded automatically via embedIds prop and passed to content snippet
  The childEmbedTransformer converts raw embed data to WebSearchResult format
-->
<UnifiedEmbedFullscreen
  appId="web"
  skillId="search"
  title=""
  onClose={handleMainClose}
  onShare={handleShare}
  skillIconName="search"
  status="finished"
  {skillName}
  showStatus={true}
  {embedIds}
  childEmbedTransformer={transformToWebResult}
  legacyResults={legacyResults}
>
  {#snippet content(ctx)}
    {@const webResults = getWebResults(ctx)}
    
    <!-- Header with search query and provider - 60px top margin, 40px bottom margin -->
    <div class="fullscreen-header">
      <div class="search-query">{query}</div>
      <div class="search-provider">{viaProvider}</div>
    </div>
    
    {#if ctx.isLoadingChildren}
      <div class="loading-state">
        <p>{$text('embeds.loading.text') || 'Loading...'}</p>
      </div>
    {:else if webResults.length === 0}
      <div class="no-results">
        <p>{$text('embeds.no_results.text') || 'No search results available.'}</p>
      </div>
    {:else}
      <!-- Website embeds grid - uses CSS container queries for responsive layout -->
      <!-- No JavaScript-based mobile detection; CSS handles responsive columns automatically -->
      <div class="website-embeds-grid">
        {#each webResults as result}
          <WebsiteEmbedPreview
            id={result.embed_id}
            url={result.url}
            title={result.title}
            description={result.snippet}
            favicon={result.favicon_url}
            image={result.preview_image_url}
            status="finished"
            isMobile={false}
            onFullscreen={() => handleWebsiteFullscreen(result)}
          />
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<!-- Website fullscreen overlay - rendered ON TOP when a website is selected -->
<!-- Uses ChildEmbedOverlay for consistent overlay positioning across all search fullscreens -->
{#if selectedWebsite}
  <ChildEmbedOverlay>
    <WebsiteEmbedFullscreen
      url={selectedWebsite.url}
      title={selectedWebsite.title}
      description={selectedWebsite.description || selectedWebsite.snippet}
      favicon={selectedWebsite.favicon_url}
      image={selectedWebsite.preview_image_url}
      snippets={selectedWebsite.snippets}
      onClose={handleWebsiteFullscreenClose}
      embedId={selectedWebsite.embed_id}
    />
  </ChildEmbedOverlay>
{/if}

<style>
  /* ===========================================
     Fullscreen Header - Query and Provider
     Uses container queries for responsive sizing
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
  
  /* Container query: smaller text on narrow containers */
  @container fullscreen (max-width: 500px) {
    .fullscreen-header {
      margin-top: 70px; /* More space for action buttons */
      margin-bottom: 24px;
    }
    
    .search-query {
      font-size: 20px;
    }
    
    .search-provider {
      font-size: 14px;
    }
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
     Website Embeds Grid - Responsive Layout
     Uses CSS container queries for container-based responsiveness
     (not viewport-based) so it works correctly in split views
     =========================================== */
  
  .website-embeds-grid {
    display: grid;
    gap: 16px;
    width: calc(100% - 20px);
    max-width: 1000px;
    margin: 0 auto;
    padding: 0 10px;
    padding-bottom: 120px; /* Space for bottom bar + gradient */
    /* Responsive: auto-fit columns with minimum 280px width */
    /* This naturally becomes single column when container is narrow */
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  }
  
  /* Container query: when fullscreen container is narrow (< 500px), single column */
  /* Uses container query on the 'fullscreen' container defined in UnifiedEmbedFullscreen */
  @container fullscreen (max-width: 500px) {
    .website-embeds-grid {
      grid-template-columns: 1fr;
    }
  }
  
  /* Ensure each embed maintains proper size */
  .website-embeds-grid :global(.unified-embed-preview) {
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
  }
</style>

