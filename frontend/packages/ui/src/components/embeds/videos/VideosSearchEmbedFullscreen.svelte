<!--
  frontend/packages/ui/src/components/embeds/videos/VideosSearchEmbedFullscreen.svelte
  
  Fullscreen view for Videos Search skill embeds.
  Uses UnifiedEmbedFullscreen as base with unified child embed loading.
  
  Shows:
  - Header with search query and "via {provider}" formatting (60px top margin, 40px bottom margin)
  - Video embeds in a grid (auto-responsive columns)
  - Each video uses WebsiteEmbedPreview component
  - Consistent BasicInfosBar at the bottom (matches preview - "Search" + "Completed")
  - Top bar with share, copy, and minimize buttons
  
  Child embeds are automatically loaded by UnifiedEmbedFullscreen from embedIds prop.
  
  Video Fullscreen Navigation (Overlay Pattern):
  - Search results grid is ALWAYS rendered (base layer)
  - When a video result is clicked, VideoEmbedFullscreen renders as an OVERLAY on top
  - When VideoEmbedFullscreen is closed, overlay is removed revealing search results beneath
  
  Benefits of overlay approach:
  - No re-animation when returning to search results (they're already rendered beneath)
  - No re-loading of child embeds
  - Scroll position preserved on search results
  - Instant close transition since search results are always visible
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import WebsiteEmbedPreview from '../web/WebsiteEmbedPreview.svelte';
  import VideoEmbedFullscreen from './VideoEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  
  /**
   * Video search result interface (transformed from child embeds)
   */
  interface VideoSearchResult {
    embed_id: string;
    title?: string;
    url: string;
    thumbnail?: string;
    favicon?: string;
    description?: string;
  }
  
  /**
   * Props for videos search embed fullscreen
   * Child embeds are loaded automatically via UnifiedEmbedFullscreen
   */
  interface Props {
    /** Search query */
    query: string;
    /** Search provider (e.g., 'Brave Search') */
    provider: string;
    /** Pipe-separated embed IDs or array of embed IDs for child video embeds */
    embedIds?: string | string[];
    /** Legacy: Direct results (fallback if embedIds not provided) */
    results?: VideoSearchResult[];
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
    onNavigateNext
  }: Props = $props();
  
  // ============================================
  // State: Track which video is shown in fullscreen
  // ============================================
  
  /** Currently selected video for fullscreen view (null = show search results) */
  let selectedVideo = $state<VideoSearchResult | null>(null);
  
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
   * Transform raw embed content to VideoSearchResult format
   * Used by UnifiedEmbedFullscreen's childEmbedTransformer
   */
  function transformToVideoResult(embedId: string, content: Record<string, unknown>): VideoSearchResult {
    // Handle nested thumbnail and meta_url objects
    const thumbnail = content.thumbnail as Record<string, string> | undefined;
    const metaUrl = content.meta_url as Record<string, string> | undefined;
    
    return {
      embed_id: embedId,
      title: content.title as string | undefined,
      url: content.url as string,
      thumbnail: (content.thumbnail_original as string) || thumbnail?.original || thumbnail?.src,
      favicon: (content.meta_url_favicon as string) || metaUrl?.favicon,
      description: (content.description as string) || (content.snippet as string)
    };
  }
  
  /**
   * Transform legacy results to VideoSearchResult format (for backwards compatibility)
   */
  function transformLegacyResults(results: unknown[]): VideoSearchResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => {
      const thumbnail = r.thumbnail as Record<string, string> | undefined;
      const metaUrl = r.meta_url as Record<string, string> | undefined;
      
      return {
        embed_id: `legacy-${i}`,
        title: r.title as string | undefined,
        url: r.url as string,
        thumbnail: thumbnail?.original || thumbnail?.src,
        favicon: metaUrl?.favicon,
        description: (r.description as string) || (r.snippet as string)
      };
    });
  }
  
  /**
   * Get video results from context (children or legacy)
   * Children are cast to VideoSearchResult[] since we pass transformToVideoResult as transformer
   */
  function getVideoResults(ctx: ChildEmbedContext): VideoSearchResult[] {
    // Use loaded children if available (cast since transformer returns VideoSearchResult)
    if (ctx.children && ctx.children.length > 0) {
      return ctx.children as VideoSearchResult[];
    }
    // Fallback to legacy results
    if (ctx.legacyResults && ctx.legacyResults.length > 0) {
      return transformLegacyResults(ctx.legacyResults);
    }
    return [];
  }
  
  // Handle share - opens share settings menu for this specific videos search embed
  async function handleShare() {
    try {
      console.debug('[VideosSearchEmbedFullscreen] Opening share settings for videos search embed:', {
        embedId,
        query,
        provider
      });

      // Check if we have embed_id for proper sharing
      if (!embedId) {
        console.warn('[VideosSearchEmbedFullscreen] No embed_id available - cannot create encrypted share link');
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.error('Unable to share this videos search embed. Missing embed ID.');
        return;
      }

      // Import required modules
      const { navigateToSettings } = await import('../../../stores/settingsNavigationStore');
      const { settingsDeepLink } = await import('../../../stores/settingsDeepLinkStore');
      const { panelState } = await import('../../../stores/panelStateStore');

      // Set embed context with embed_id for proper encrypted sharing
      const embedContext = {
        type: 'videos_search',
        embed_id: embedId,
        query: query,
        provider: provider
      };

      // Store embed context for SettingsShare
      (window as unknown as { __embedShareContext?: unknown }).__embedShareContext = embedContext;

      // Navigate to share settings
      navigateToSettings('shared/share', 'Share Videos Search', 'share', 'settings.share.share_videos_search.text');
      
      // Also set settingsDeepLink to ensure Settings component navigates properly
      settingsDeepLink.set('shared/share');

      // Open settings panel
      panelState.openSettings();

      console.debug('[VideosSearchEmbedFullscreen] Opened share settings for videos search embed');
    } catch (error) {
      console.error('[VideosSearchEmbedFullscreen] Error opening share settings:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to open share menu. Please try again.');
    }
  }
  
  /**
   * Handle video click - shows the video in fullscreen mode
   * Uses VideoEmbedFullscreen for full video player experience
   */
  function handleVideoFullscreen(videoData: VideoSearchResult) {
    console.debug('[VideosSearchEmbedFullscreen] Opening video fullscreen:', {
      embedId: videoData.embed_id,
      url: videoData.url,
      title: videoData.title
    });
    selectedVideo = videoData;
  }
  
  /**
   * Handle closing the video fullscreen - returns to search results
   * Called when user clicks minimize button on VideoEmbedFullscreen
   */
  function handleVideoFullscreenClose() {
    console.debug('[VideosSearchEmbedFullscreen] Closing video fullscreen, returning to search results');
    selectedVideo = null;
  }
  
  /**
   * Handle closing the entire search fullscreen
   * Called when user closes the main VideosSearchEmbedFullscreen
   */
  function handleMainClose() {
    // If a video is open, first close it and return to search results
    if (selectedVideo) {
      selectedVideo = null;
    } else {
      // Otherwise, close the entire fullscreen
      onClose();
    }
  }
</script>

<!-- 
  Overlay-based rendering approach for smooth transitions:
  - VideosSearchEmbedFullscreen (search results grid) is ALWAYS mounted
  - VideoEmbedFullscreen renders as an OVERLAY on top when a video is selected
  
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
  The childEmbedTransformer converts raw embed data to VideoSearchResult format
-->
<UnifiedEmbedFullscreen
  onShare={handleShare}
  appId="videos"
  skillId="search"
  title=""
  onClose={handleMainClose}
  skillIconName="search"
  status="finished"
  {skillName}
  showStatus={true}
  {embedIds}
  childEmbedTransformer={transformToVideoResult}
  legacyResults={resultsProp}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet content(ctx)}
    {@const videoResults = getVideoResults(ctx)}
    
    <!-- Header with search query and provider - 60px top margin, 40px bottom margin -->
    <div class="fullscreen-header">
      <div class="search-query">{query}</div>
      <div class="search-provider">{viaProvider}</div>
    </div>
    
    {#if ctx.isLoadingChildren}
      <div class="loading-state">
        <p>{$text('embeds.loading.text') || 'Loading...'}</p>
      </div>
    {:else if videoResults.length === 0}
      <div class="no-results">
        <p>{$text('embeds.no_results.text') || 'No search results available.'}</p>
      </div>
    {:else}
      <!-- Video embeds grid - responsive auto-fill columns -->
      <div class="video-embeds-grid" class:mobile={isMobile}>
        {#each videoResults as result}
          <WebsiteEmbedPreview
            id={result.embed_id}
            url={result.url}
            title={result.title}
            description={result.description}
            favicon={result.favicon}
            image={result.thumbnail}
            status="finished"
            isMobile={false}
            onFullscreen={() => handleVideoFullscreen(result)}
          />
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<!-- Video fullscreen overlay - rendered ON TOP when a video is selected -->
<!-- Uses ChildEmbedOverlay for consistent overlay positioning across all search fullscreens -->
{#if selectedVideo}
  <ChildEmbedOverlay>
    <VideoEmbedFullscreen
      url={selectedVideo.url}
      title={selectedVideo.title}
      onClose={handleVideoFullscreenClose}
      embedId={selectedVideo.embed_id}
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
     Video Embeds Grid - Responsive Layout
     =========================================== */
  
  .video-embeds-grid {
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
  .video-embeds-grid.mobile {
    grid-template-columns: 1fr;
  }
  
  /* Ensure each embed maintains proper size */
  .video-embeds-grid :global(.unified-embed-preview) {
    width: 100%;
    max-width: 320px;
    margin: 0 auto;
  }
</style>

