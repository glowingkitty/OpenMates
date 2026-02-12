<!--
  frontend/packages/ui/src/components/embeds/videos/VideosSearchEmbedFullscreen.svelte
  
  Fullscreen view for Videos Search skill embeds.
  Uses UnifiedEmbedFullscreen as base with unified child embed loading.
  
  Shows:
  - Header with search query and "via {provider}" formatting (60px top margin, 40px bottom margin)
  - Video embeds in a grid (auto-responsive columns)
  - Each video uses VideoEmbedPreview component (NOT WebsiteEmbedPreview)
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
  
  Video Data Flow:
  - Child embeds contain full video metadata (title, channelTitle, duration, viewCount, etc.)
  - VideoEmbedPreview receives all metadata as props (no additional fetch needed)
  - When clicked, VideoEmbedFullscreen receives metadata for proper display
-->

<script lang="ts">
  import UnifiedEmbedFullscreen, { type ChildEmbedContext } from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import VideoEmbedPreview from './VideoEmbedPreview.svelte';
  import VideoEmbedFullscreen from './VideoEmbedFullscreen.svelte';
  import type { VideoMetadata } from './VideoEmbedPreview.svelte';
  import { text } from '@repo/ui';
  
  /**
   * Video search result interface (transformed from child embeds)
   * Contains all video metadata needed for VideoEmbedPreview and VideoEmbedFullscreen
   * 
   * Field mapping from TOON-encoded embed content:
   * - title: video title
   * - url: YouTube URL
   * - channelTitle -> channelName: channel name
   * - meta_url_profile_image -> channelThumbnail: channel profile picture
   * - thumbnail_original -> thumbnail: video thumbnail URL
   * - duration: ISO 8601 duration string (e.g., "PT18M4S")
   * - viewCount: number of views
   * - likeCount: number of likes
   * - publishedAt: ISO 8601 date string
   * - description: video description
   */
  interface VideoSearchResult {
    embed_id: string;
    title?: string;
    url: string;
    /** Video thumbnail URL */
    thumbnail?: string;
    /** Channel profile picture URL */
    channelThumbnail?: string;
    /** Channel name */
    channelName?: string;
    /** Channel ID */
    channelId?: string;
    /** Video description */
    description?: string;
    /** Duration in seconds */
    durationSeconds?: number;
    /** Duration formatted (e.g., "17:08") */
    durationFormatted?: string;
    /** View count */
    viewCount?: number;
    /** Like count */
    likeCount?: number;
    /** Published date (ISO string) */
    publishedAt?: string;
    /** Video ID extracted from URL */
    videoId?: string;
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
   * Parse ISO 8601 duration string to seconds and formatted string
   * Example: "PT18M4S" -> { totalSeconds: 1084, formatted: "18:04" }
   * 
   * @param isoDuration - ISO 8601 duration string (e.g., "PT18M4S", "PT1H2M3S")
   * @returns Object with totalSeconds and formatted string, or undefined if invalid
   */
  function parseIsoDuration(isoDuration: string | undefined): { totalSeconds: number; formatted: string } | undefined {
    if (!isoDuration || typeof isoDuration !== 'string') return undefined;
    
    // Match ISO 8601 duration format: PT[hours]H[minutes]M[seconds]S
    const match = isoDuration.match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
    if (!match) return undefined;
    
    const hours = parseInt(match[1] || '0', 10);
    const minutes = parseInt(match[2] || '0', 10);
    const seconds = parseInt(match[3] || '0', 10);
    
    const totalSeconds = hours * 3600 + minutes * 60 + seconds;
    
    // Format as HH:MM:SS or MM:SS
    let formatted: string;
    if (hours > 0) {
      formatted = `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    } else {
      formatted = `${minutes}:${seconds.toString().padStart(2, '0')}`;
    }
    
    return { totalSeconds, formatted };
  }
  
  /**
   * Extract video ID from YouTube URL
   * Supports various YouTube URL formats (watch, youtu.be, embed, shorts)
   * 
   * @param videoUrl - YouTube URL
   * @returns Video ID or undefined
   */
  function extractVideoId(videoUrl: string): string | undefined {
    if (!videoUrl) return undefined;
    
    // YouTube URL patterns
    const patterns = [
      /(?:youtube\.com\/watch\?.*v=)([a-zA-Z0-9_-]{11})/,
      /(?:youtu\.be\/)([a-zA-Z0-9_-]{11})/,
      /(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
      /(?:youtube\.com\/v\/)([a-zA-Z0-9_-]{11})/,
      /(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})/,
    ];
    
    for (const pattern of patterns) {
      const match = videoUrl.match(pattern);
      if (match) {
        return match[1];
      }
    }
    
    return undefined;
  }
  
  /**
   * Transform raw embed content to VideoSearchResult format
   * Used by UnifiedEmbedFullscreen's childEmbedTransformer
   * 
   * Extracts ALL video metadata from TOON-encoded content for proper display
   * in VideoEmbedPreview and VideoEmbedFullscreen
   * 
   * Field mapping from TOON-encoded embed content:
   * - title: video title
   * - url: YouTube URL
   * - channelTitle -> channelName: channel name
   * - meta_url_profile_image -> channelThumbnail: channel profile picture
   * - thumbnail_original -> thumbnail: video thumbnail URL
   * - duration: ISO 8601 duration string (e.g., "PT18M4S") -> parsed to seconds/formatted
   * - viewCount: number of views
   * - likeCount: number of likes
   * - publishedAt: ISO 8601 date string
   * - description: video description
   */
  function transformToVideoResult(embedId: string, content: Record<string, unknown>): VideoSearchResult {
    // Handle nested thumbnail and meta_url objects (fallback for non-flattened data)
    const thumbnail = content.thumbnail as Record<string, string> | undefined;
    const metaUrl = content.meta_url as Record<string, string> | undefined;
    
    // Extract video URL
    const url = content.url as string || '';
    
    // Parse ISO 8601 duration to seconds and formatted string
    const duration = parseIsoDuration(content.duration as string | undefined);
    
    // Extract video ID from URL
    const videoId = extractVideoId(url);
    
    // DEBUG: Log transformed data for first few results
    console.debug(`[VideosSearchEmbedFullscreen] Transforming embed ${embedId}:`, {
      title: (content.title as string)?.substring(0, 40),
      channelTitle: content.channelTitle,
      meta_url_profile_image: content.meta_url_profile_image,
      duration: content.duration,
      parsedDuration: duration,
      viewCount: content.viewCount,
      likeCount: content.likeCount,
      publishedAt: content.publishedAt
    });
    
    return {
      embed_id: embedId,
      title: content.title as string | undefined,
      url: url,
      // Video thumbnail: prefer flattened format, fall back to nested
      thumbnail: (content.thumbnail_original as string) || thumbnail?.original || thumbnail?.src,
      // Channel profile picture: prefer TOON-flattened format
      channelThumbnail: (content.meta_url_profile_image as string) || metaUrl?.profile_image,
      // Channel name: from channelTitle field
      channelName: content.channelTitle as string | undefined,
      // Channel ID (if available)
      channelId: content.channelId as string | undefined,
      // Video description
      description: (content.description as string) || (content.snippet as string),
      // Duration: parsed from ISO 8601 format
      durationSeconds: duration?.totalSeconds,
      durationFormatted: duration?.formatted,
      // View and like counts
      viewCount: content.viewCount as number | undefined,
      likeCount: content.likeCount as number | undefined,
      // Published date (ISO string)
      publishedAt: content.publishedAt as string | undefined,
      // Video ID extracted from URL
      videoId: videoId
    };
  }
  
  /**
   * Transform legacy results to VideoSearchResult format (for backwards compatibility)
   */
  function transformLegacyResults(results: unknown[]): VideoSearchResult[] {
    return (results as Array<Record<string, unknown>>).map((r, i) => {
      const thumbnail = r.thumbnail as Record<string, string> | undefined;
      const metaUrl = r.meta_url as Record<string, string> | undefined;
      const url = r.url as string || '';
      const duration = parseIsoDuration(r.duration as string | undefined);
      const videoId = extractVideoId(url);
      
      return {
        embed_id: `legacy-${i}`,
        title: r.title as string | undefined,
        url: url,
        thumbnail: (r.thumbnail_original as string) || thumbnail?.original || thumbnail?.src,
        channelThumbnail: (r.meta_url_profile_image as string) || metaUrl?.profile_image,
        channelName: r.channelTitle as string | undefined,
        channelId: r.channelId as string | undefined,
        description: (r.description as string) || (r.snippet as string),
        durationSeconds: duration?.totalSeconds,
        durationFormatted: duration?.formatted,
        viewCount: r.viewCount as number | undefined,
        likeCount: r.likeCount as number | undefined,
        publishedAt: r.publishedAt as string | undefined,
        videoId: videoId
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
  
  // Share is handled by UnifiedEmbedFullscreen's built-in share handler
  // which uses currentEmbedId, appId, and skillId to construct the embed
  // share context and properly opens the settings panel (including on mobile).
  
  /**
   * Handle video click - shows the video in fullscreen mode
   * Uses VideoEmbedFullscreen for full video player experience
   * Passes all video metadata for proper display
   */
  function handleVideoFullscreen(videoData: VideoSearchResult, metadata: VideoMetadata) {
    console.debug('[VideosSearchEmbedFullscreen] Opening video fullscreen:', {
      embedId: videoData.embed_id,
      url: videoData.url,
      title: videoData.title,
      channelName: metadata.channelName,
      duration: metadata.duration?.formatted,
      viewCount: metadata.viewCount
    });
    selectedVideo = videoData;
    selectedVideoMetadata = metadata;
  }
  
  /** Metadata for the currently selected video (passed to VideoEmbedFullscreen) */
  let selectedVideoMetadata = $state<VideoMetadata | null>(null);
  
  /**
   * Handle closing the video fullscreen - returns to search results
   * Called when user clicks minimize button on VideoEmbedFullscreen
   */
  function handleVideoFullscreenClose() {
    console.debug('[VideosSearchEmbedFullscreen] Closing video fullscreen, returning to search results');
    selectedVideo = null;
    selectedVideoMetadata = null;
  }
  
  /**
   * Handle closing the entire search fullscreen
   * Called when user closes the main VideosSearchEmbedFullscreen
   */
  function handleMainClose() {
    // If a video is open, first close it and return to search results
    if (selectedVideo) {
      selectedVideo = null;
      selectedVideoMetadata = null;
    } else {
      // Otherwise, close the entire fullscreen
      onClose();
    }
  }
  
  /**
   * Create VideoMetadata object from VideoSearchResult for passing to VideoEmbedFullscreen
   * This converts the search result format to the metadata format expected by VideoEmbedFullscreen
   */
  function createVideoMetadata(result: VideoSearchResult): VideoMetadata {
    return {
      videoId: result.videoId || '',
      title: result.title,
      description: result.description,
      channelName: result.channelName,
      channelId: result.channelId,
      channelThumbnail: result.channelThumbnail,
      thumbnailUrl: result.thumbnail,
      duration: result.durationSeconds !== undefined || result.durationFormatted 
        ? { totalSeconds: result.durationSeconds || 0, formatted: result.durationFormatted || '' }
        : undefined,
      viewCount: result.viewCount,
      likeCount: result.likeCount,
      publishedAt: result.publishedAt
    };
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
  appId="videos"
  skillId="search"
  title=""
  onClose={handleMainClose}
  currentEmbedId={embedId}
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
  {showChatButton}
  {onShowChat}
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
      <!-- Uses VideoEmbedPreview for proper video display with channel info, duration, etc. -->
      <div class="video-embeds-grid" class:mobile={isMobile}>
        {#each videoResults as result}
          <VideoEmbedPreview
            id={result.embed_id}
            url={result.url}
            title={result.title}
            status="finished"
            isMobile={false}
            channelName={result.channelName}
            channelId={result.channelId}
            channelThumbnail={result.channelThumbnail}
            thumbnail={result.thumbnail}
            durationSeconds={result.durationSeconds}
            durationFormatted={result.durationFormatted}
            viewCount={result.viewCount}
            likeCount={result.likeCount}
            publishedAt={result.publishedAt}
            videoId={result.videoId}
            onFullscreen={(metadata) => handleVideoFullscreen(result, metadata)}
          />
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<!-- Video fullscreen overlay - rendered ON TOP when a video is selected -->
<!-- Uses ChildEmbedOverlay for consistent overlay positioning across all search fullscreens -->
<!-- Passes full metadata to VideoEmbedFullscreen for proper display (no additional fetch needed) -->
{#if selectedVideo}
  <ChildEmbedOverlay>
    <VideoEmbedFullscreen
      url={selectedVideo.url}
      title={selectedVideo.title}
      onClose={handleVideoFullscreenClose}
      embedId={selectedVideo.embed_id}
      videoId={selectedVideo.videoId}
      metadata={selectedVideoMetadata || createVideoMetadata(selectedVideo)}
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

