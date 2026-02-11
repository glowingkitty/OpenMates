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
    /** Extra snippets from backend TOON (pipe-delimited string or array) */
    extra_snippets?: string | string[];
    /** Page age from Brave Search - can be ISO date (page_age) or relative time (age) like "2 weeks ago" */
    page_age?: string;
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
    /** Processing status (direct format) */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Optional error message for debugging */
    errorMessage?: string;
    /** Legacy: Search results (direct format, used if embedIds not provided) */
    results?: WebSearchResult[];
    /** Legacy: Skill preview data (skill preview context) */
    previewData?: WebSearchSkillPreviewData;
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
    query: queryProp,
    provider: providerProp,
    embedIds,
    status: statusProp,
    errorMessage: errorMessageProp,
    results: resultsProp,
    previewData,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat
  }: Props = $props();
  
  // Debug: Log what props WebSearchEmbedFullscreen receives
  $effect(() => {
    console.debug('[WebSearchEmbedFullscreen] 🔎 Props received:', {
      query: queryProp || previewData?.query,
      provider: providerProp || previewData?.provider,
      embedIds,
      embedIds_type: typeof embedIds,
      embedIds_isArray: Array.isArray(embedIds),
      embedIds_length: Array.isArray(embedIds) ? embedIds.length : (typeof embedIds === 'string' ? embedIds.length : 0),
      embedIds_value: embedIds,
      status: statusProp || previewData?.status,
      hasPreviewData: !!previewData,
      previewDataResultsCount: previewData?.results?.length || 0,
      resultsPropCount: resultsProp?.length || 0,
      resultsProp_sample: resultsProp?.slice(0, 2),
      embedId
    });
  });
  
  // ============================================
  // State: Track which website is shown in fullscreen
  // ============================================
  
  /** Currently selected website for fullscreen view (null = show search results) */
  let selectedWebsite = $state<WebSearchResult | null>(null);
  
  // Local reactive state for embed data (allows updates via embedUpdated events)
  let localQuery = $state<string>(previewData?.query || queryProp || '');
  let localProvider = $state<string>(previewData?.provider || providerProp || 'Brave Search');
  let localEmbedIds = $state<string | string[] | undefined>(embedIds);
  let localResults = $state<unknown[]>(previewData?.results || resultsProp || []);
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>(
    (previewData?.status as 'processing' | 'finished' | 'error' | 'cancelled') || statusProp || 'finished'
  );
  let localErrorMessage = $state<string>(errorMessageProp || '');
  
  // Keep local state in sync with prop changes (e.g., navigation)
  $effect(() => {
    localQuery = previewData?.query || queryProp || '';
    localProvider = previewData?.provider || providerProp || 'Brave Search';
    localEmbedIds = embedIds;
    localResults = previewData?.results || resultsProp || [];
    localStatus = (previewData?.status as 'processing' | 'finished' | 'error' | 'cancelled') || statusProp || 'finished';
    localErrorMessage = errorMessageProp || '';
  });
  
  // Extract values from local state (single source of truth)
  let query = $derived(localQuery);
  let provider = $derived(localProvider);
  let embedIdsValue = $derived(localEmbedIds);
  // Legacy results from previewData or direct results prop (used as fallback)
  let legacyResults = $derived(localResults);
  let status = $derived(localStatus);
  let fullscreenStatus = $derived(status === 'cancelled' ? 'error' : status);
  let errorMessage = $derived(localErrorMessage || ($text('chat.an_error_occured.text') || 'Processing failed.'));
  
  // Get skill name from translations (matches preview)
  let skillName = $derived($text('embeds.search.text') || 'Search');
  
  // Get "via {provider}" text from translations
  let viaProvider = $derived(
    `${$text('embeds.via.text') || 'via'} ${provider}`
  );
  
  /**
   * Helper to extract nested field from content object
   * Supports both flat and nested formats (e.g., 'thumbnail.original' or 'thumbnail_original')
   */
  function getNestedField(obj: Record<string, unknown>, ...paths: string[]): string | undefined {
    for (const path of paths) {
      // Try nested path first (e.g., 'thumbnail.original')
      if (path.includes('.')) {
        const parts = path.split('.');
        let value: unknown = obj;
        for (const part of parts) {
          if (value && typeof value === 'object' && part in (value as Record<string, unknown>)) {
            value = (value as Record<string, unknown>)[part];
          } else {
            value = undefined;
            break;
          }
        }
        if (typeof value === 'string' && value) return value;
      } else {
        // Try flat path
        const value = obj[path];
        if (typeof value === 'string' && value) return value;
      }
    }
    return undefined;
  }

  /**
   * Transform raw embed content to WebSearchResult format
   * Used by UnifiedEmbedFullscreen's childEmbedTransformer
   * Extracts all available fields for both preview and fullscreen views
   * 
   * Backend saves nested objects like thumbnail.original and meta_url.favicon
   * This transformer handles both nested and flat field formats for compatibility
   */
  function transformToWebResult(embedId: string, content: Record<string, unknown>): WebSearchResult {
    // Extract nested fields - backend saves as thumbnail.original, meta_url.favicon
    const faviconUrl = getNestedField(content, 'meta_url.favicon', 'favicon_url', 'meta_url_favicon');
    const thumbnailUrl = getNestedField(content, 'thumbnail.original', 'preview_image_url', 'thumbnail_original', 'image');
    
    // Debug: Log raw content to see what fields are available
    console.debug('[WebSearchEmbedFullscreen] transformToWebResult raw content:', {
      embedId,
      contentKeys: Object.keys(content),
      thumbnail: content.thumbnail,
      meta_url: content.meta_url,
      extractedFavicon: faviconUrl,
      extractedThumbnail: thumbnailUrl,
      extra_snippets: content.extra_snippets,
      page_age: content.page_age
    });
    
    // Extract page age - prefer 'age' (relative time like "2 weeks ago") over 'page_age' (ISO date)
    // WebsiteEmbedFullscreen parses relative time strings for display
    const pageAge = (content.age as string) || (content.page_age as string) || undefined;
    
    const result: WebSearchResult = {
      embed_id: embedId,
      title: content.title as string | undefined,
      url: content.url as string,
      favicon_url: faviconUrl,
      preview_image_url: thumbnailUrl,
      snippet: (content.snippet as string) || (content.description as string),
      description: content.description as string | undefined,
      extra_snippets: content.extra_snippets as string | string[] | undefined,
      page_age: pageAge
    };
    
    console.debug('[WebSearchEmbedFullscreen] Transformed result:', {
      embedId,
      hasFavicon: !!result.favicon_url,
      hasThumbnail: !!result.preview_image_url,
      hasExtraSnippets: !!result.extra_snippets,
      pageAge: result.page_age
    });
    
    return result;
  }
  
  /**
   * Transform legacy results to WebSearchResult format (for backwards compatibility)
   * Handles both nested and flat field formats.
   * 
   * NOTE: Legacy results use synthetic 'legacy-X' IDs since they don't correspond
   * to actual embeds in IndexedDB. These IDs are handled specially by
   * UnifiedEmbedPreview to skip unnecessary embedStore lookups.
   * 
   * Also checks the 'favicon' field first (backend-processed format) before
   * trying nested paths (raw API format).
   */
  function transformLegacyResults(results: unknown[]): WebSearchResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => ({
      embed_id: `legacy-${i}`,
      title: r.title as string | undefined,
      url: r.url as string,
      // Check 'favicon' first (backend-processed format from ActiveChat),
      // then 'favicon_url', then nested 'meta_url.favicon' (raw API format)
      favicon_url: (r.favicon as string) || getNestedField(r, 'meta_url.favicon', 'favicon_url', 'meta_url_favicon'),
      preview_image_url: getNestedField(r, 'thumbnail.original', 'preview_image_url', 'thumbnail_original', 'image'),
      snippet: (r.snippet as string) || (r.description as string),
      description: r.description as string | undefined,
      extra_snippets: r.extra_snippets as string | string[] | undefined,
      // Extract page age - prefer 'age' (relative time) over 'page_age' (ISO date)
      page_age: (r.age as string) || (r.page_age as string) || undefined
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
      title: websiteData.title,
      extra_snippets: websiteData.extra_snippets,
      extra_snippets_type: typeof websiteData.extra_snippets,
      hasExtraSnippets: !!websiteData.extra_snippets,
      page_age: websiteData.page_age
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
   * Handle embed data updates during streaming or error transitions.
   * Updates local state so the fullscreen can render error details.
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    
    const content = data.decodedContent;
    if (typeof content.query === 'string') localQuery = content.query;
    if (typeof content.provider === 'string') localProvider = content.provider;
    if (content.embed_ids) {
      localEmbedIds = content.embed_ids as string | string[];
    }
    if (Array.isArray(content.results)) {
      localResults = content.results as unknown[];
    }
    if (typeof content.error === 'string') {
      localErrorMessage = content.error;
    }
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

  // Share is handled by UnifiedEmbedFullscreen's built-in share handler
  // which uses currentEmbedId, appId, and skillId to construct the embed
  // share context and properly opens the settings panel (including on mobile).
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
  skillIconName="search"
  status={fullscreenStatus}
  {skillName}
  showStatus={true}
  embedIds={embedIdsValue}
  childEmbedTransformer={transformToWebResult}
  legacyResults={legacyResults}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content(ctx)}
    {@const webResults = getWebResults(ctx)}
    
    <!-- Header with search query and provider - 60px top margin, 40px bottom margin -->
    <div class="fullscreen-header">
      <div class="search-query">{query}</div>
      <div class="search-provider">{viaProvider}</div>
    </div>
    
    <!-- Error state: show simplified error for debugging -->
    {#if status === 'error'}
      <div class="error-state">
        <div class="error-title">Search failed</div>
        <div class="error-message">{errorMessage}</div>
      </div>
    {:else}
      <!-- 
        Show results immediately if available (from children OR legacyResults).
        Only show loading state if we have NO results at all and are still loading.
        This ensures pre-loaded results from ActiveChat display immediately
        without waiting for the (redundant) child embed reload.
      -->
      {#if webResults.length === 0}
        {#if ctx.isLoadingChildren}
          <div class="loading-state">
            <p>{$text('embeds.loading.text') || 'Loading...'}</p>
          </div>
        {:else}
          <div class="no-results">
            <p>{$text('embeds.no_results.text') || 'No search results available.'}</p>
          </div>
        {/if}
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
      extra_snippets={selectedWebsite.extra_snippets}
      dataDate={selectedWebsite.page_age}
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
  
  /* Error state for fullscreen debugging */
  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 24px 16px;
    color: var(--color-font-secondary);
    text-align: center;
  }
  
  .error-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-error);
  }
  
  .error-message {
    font-size: 14px;
    line-height: 1.4;
    max-width: 520px;
    word-break: break-word;
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
  
  /* ===========================================
     Skill Icon Styling (skill-specific)
     Defines the search icon mask-image for BasicInfosBar
     Must be defined here since BasicInfosBar only provides
     base styling without skill-specific icon URLs
     =========================================== */
  
  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="search"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
    mask-image: url('@openmates/ui/static/icons/search.svg');
  }
</style>

