<!--
  frontend/packages/ui/src/components/embeds/videos/VideoEmbedPreview.svelte
  
  Preview component for Video URL embeds (YouTube, etc.).
  Uses UnifiedEmbedPreview as base and provides video-specific details content.
  
  Features:
  - Auto-fetches metadata from preview server when not provided
  - Displays video thumbnail (clean, no overlays)
  - Info bar below thumbnail:
    - Line 1: Channel thumbnail (29x29px round) + shortened video title
    - Line 2: Duration + upload date (e.g., "29:26, Jul 31, 2025")
  - Proxies all thumbnails through preview server for privacy
  - Passes fetched metadata to fullscreen view for consistent display
  
  Details content structure:
  - Processing: URL hostname
  - Finished: video thumbnail, info bar with channel thumb + title + duration + date
  - Error: hostname with error styling
  
  Data Flow:
  - Preview server fetches video metadata including channel thumbnail (requires separate YouTube API call)
  - Both video and channel metadata are cached server-side for 24 hours
  - All metadata (title, description, thumbnails, duration, channel info) is passed to fullscreen view
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  
  // ===========================================
  // Types
  // ===========================================
  
  /**
   * Metadata response from preview server /api/v1/youtube endpoint
   * Includes video metadata and channel thumbnail (profile picture)
   */
  interface YouTubeMetadataResponse {
    video_id: string;
    url: string;
    title?: string;
    description?: string;
    channel_name?: string;
    channel_id?: string;
    channel_thumbnail?: string;  // Channel profile picture URL (fetched separately from channels.list API)
    thumbnails: {
      default?: string;
      medium?: string;
      high?: string;
      standard?: string;
      maxres?: string;
    };
    duration: {
      total_seconds: number;
      formatted: string;
    };
    view_count?: number;
    like_count?: number;
    published_at?: string;
  }
  
  /**
   * Metadata passed to fullscreen when user clicks to open
   * Contains the effective values (props or fetched from preview server)
   */
  export interface VideoMetadata {
    videoId: string;
    title?: string;
    description?: string;
    channelName?: string;
    channelId?: string;
    channelThumbnail?: string;  // Channel profile picture URL
    thumbnailUrl?: string;
    duration?: {
      totalSeconds: number;
      formatted: string;
    };
    viewCount?: number;
    likeCount?: number;
    publishedAt?: string;
  }
  
  /**
   * Props for video embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Video URL */
    url: string;
    /** Video title (if not provided, will be fetched from preview server) */
    title?: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen - receives fetched metadata so fullscreen can display it */
    onFullscreen?: (metadata: VideoMetadata) => void;
  }
  
  // ===========================================
  // Props and State
  // ===========================================
  
  let {
    id,
    url,
    title,
    status,
    taskId,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // State for fetched metadata (when props are not provided)
  let fetchedTitle = $state<string | undefined>(undefined);
  let fetchedDescription = $state<string | undefined>(undefined);
  let fetchedChannelName = $state<string | undefined>(undefined);
  let fetchedChannelId = $state<string | undefined>(undefined);
  let fetchedChannelThumbnail = $state<string | undefined>(undefined);  // Channel profile picture
  let fetchedThumbnailUrl = $state<string | undefined>(undefined);
  let fetchedDuration = $state<{ totalSeconds: number; formatted: string } | undefined>(undefined);
  let fetchedViewCount = $state<number | undefined>(undefined);
  let fetchedLikeCount = $state<number | undefined>(undefined);
  let fetchedPublishedAt = $state<string | undefined>(undefined);
  let fetchedVideoId = $state<string | undefined>(undefined);
  let isLoadingMetadata = $state(false);
  let metadataError = $state(false);
  
  // Track which URL we've fetched metadata for to avoid re-fetching
  let fetchedForUrl = $state<string | null>(null);
  
  // Map skillId to icon name
  const skillIconName = 'video';
  
  // Preview server base URL for image proxying
  const PREVIEW_SERVER = 'https://preview.openmates.org';
  // Max width for preview thumbnail (2x for retina displays)
  const PREVIEW_IMAGE_MAX_WIDTH = 640;
  
  // ===========================================
  // Video ID Extraction (Fallback)
  // ===========================================
  
  /**
   * Extract video ID from URL (used when metadata fetch fails or for immediate display)
   */
  function extractVideoId(videoUrl: string): string | null {
    if (!videoUrl) return null;
    
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
    
    return null;
  }
  
  // ===========================================
  // Metadata Fetching
  // ===========================================
  
  /**
   * Determine if we need to fetch metadata from the preview server.
   * We fetch when:
   * - No title is provided as prop
   * - The URL hasn't been fetched yet
   * - Not currently loading
   */
  let needsMetadataFetch = $derived.by(() => {
    // If we already have title from props, no need to fetch
    if (title) {
      return false;
    }
    // If we already fetched for this URL, no need to re-fetch
    if (fetchedForUrl === url) {
      return false;
    }
    // If currently loading, don't trigger another fetch
    if (isLoadingMetadata) {
      return false;
    }
    return true;
  });
  
  /**
   * Fetch metadata from the preview server when needed.
   * Uses the /api/v1/youtube endpoint which calls YouTube Data API v3.
   */
  async function fetchMetadata() {
    if (!url) return;
    
    isLoadingMetadata = true;
    metadataError = false;
    
    // CRITICAL: Mark this URL as fetched BEFORE the request to prevent infinite loops
    // Even if the fetch fails, we don't want to retry indefinitely
    const urlToFetch = url;
    fetchedForUrl = urlToFetch;
    
    console.debug('[VideoEmbedPreview] Fetching YouTube metadata for URL:', urlToFetch);
    
    try {
      // Use GET endpoint for simpler integration
      const response = await fetch(
        `https://preview.openmates.org/api/v1/youtube?url=${encodeURIComponent(urlToFetch)}`
      );
      
      if (!response.ok) {
        console.warn('[VideoEmbedPreview] Metadata fetch failed:', response.status, response.statusText);
        metadataError = true;
        return;
      }
      
      const data: YouTubeMetadataResponse = await response.json();
      
      // Store fetched values
      fetchedVideoId = data.video_id;
      fetchedTitle = data.title;
      fetchedDescription = data.description;
      fetchedChannelName = data.channel_name;
      fetchedChannelId = data.channel_id;
      fetchedChannelThumbnail = data.channel_thumbnail;  // Channel profile picture
      fetchedViewCount = data.view_count;
      fetchedLikeCount = data.like_count;
      fetchedPublishedAt = data.published_at;
      
      // Convert duration format
      if (data.duration) {
        fetchedDuration = {
          totalSeconds: data.duration.total_seconds,
          formatted: data.duration.formatted
        };
      }
      
      // Get best available thumbnail (prefer maxres > standard > high > medium > default)
      const thumbnails = data.thumbnails;
      fetchedThumbnailUrl = thumbnails.maxres || thumbnails.standard || thumbnails.high || thumbnails.medium || thumbnails.default;
      
      console.info('[VideoEmbedPreview] Successfully fetched YouTube metadata:', {
        videoId: data.video_id,
        title: data.title?.substring(0, 50) || 'No title',
        channelName: data.channel_name || 'Unknown',
        duration: data.duration?.formatted || 'Unknown',
        hasThumbnail: !!fetchedThumbnailUrl,
        hasChannelThumbnail: !!data.channel_thumbnail
      });
      
    } catch (error) {
      console.error('[VideoEmbedPreview] Error fetching YouTube metadata:', error);
      metadataError = true;
    } finally {
      isLoadingMetadata = false;
    }
  }
  
  // Trigger metadata fetch when needed
  $effect(() => {
    if (needsMetadataFetch) {
      fetchMetadata();
    }
  });
  
  // ===========================================
  // Derived Display Values
  // ===========================================
  
  // Video ID: fetched or extracted from URL
  let effectiveVideoId = $derived(fetchedVideoId || extractVideoId(url) || '');
  
  // Use prop values if provided, otherwise use fetched values
  let effectiveTitle = $derived(title || fetchedTitle);
  
  // Display title: use effective title or fall back to generic
  let displayTitle = $derived(effectiveTitle || 'YouTube Video');
  
  // Raw thumbnail URL (from YouTube CDN)
  let rawThumbnailUrl = $derived.by(() => {
    if (fetchedThumbnailUrl) {
      return fetchedThumbnailUrl;
    }
    // Fallback: construct thumbnail URL from video ID
    if (effectiveVideoId) {
      return `https://img.youtube.com/vi/${effectiveVideoId}/maxresdefault.jpg`;
    }
    return '';
  });
  
  // Proxied thumbnail URL through preview server for privacy
  // This prevents users' browsers from making direct requests to YouTube/Google CDN
  let thumbnailUrl = $derived.by(() => {
    if (!rawThumbnailUrl) return '';
    return `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(rawThumbnailUrl)}&max_width=${PREVIEW_IMAGE_MAX_WIDTH}`;
  });
  
  // Proxied channel thumbnail URL through preview server for privacy
  // Channel thumbnails are small circular profile pictures
  // Display size: 29x29px, request 2x for retina (58px)
  const CHANNEL_THUMBNAIL_MAX_WIDTH = 58;
  let channelThumbnailUrl = $derived.by(() => {
    if (!fetchedChannelThumbnail) return '';
    return `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(fetchedChannelThumbnail)}&max_width=${CHANNEL_THUMBNAIL_MAX_WIDTH}`;
  });
  
  // Get hostname for fallback display
  let hostname = $derived.by(() => {
    try {
      return new URL(url).hostname;
    } catch {
      return url;
    }
  });
  
  // Shortened video title (truncate if too long for preview info bar)
  let shortenedTitle = $derived.by(() => {
    const titleToShorten = effectiveTitle || 'YouTube Video';
    // Max ~30 chars for preview layout in the info bar
    const maxLength = 30;
    if (titleToShorten.length <= maxLength) return titleToShorten;
    return titleToShorten.substring(0, maxLength - 1) + '…';
  });
  
  /**
   * Format upload date as "Mon DD, YYYY" (e.g., "Jul 31, 2025")
   * Used for displaying video upload date in a compact format
   */
  function formatUploadDate(isoDateString: string | undefined): string {
    if (!isoDateString) return '';
    
    try {
      const date = new Date(isoDateString);
      // Format as "Mon DD, YYYY" (e.g., "Jul 31, 2025")
      return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric', 
        year: 'numeric' 
      });
    } catch {
      return '';
    }
  }
  
  // Formatted upload date (e.g., "Jul 31, 2025")
  let formattedUploadDate = $derived(formatUploadDate(fetchedPublishedAt));
  
  // Compute effective status: if we're loading metadata, show as processing
  // But only if the original status was 'finished' (don't override explicit processing state)
  let effectiveStatus = $derived.by(() => {
    if (isLoadingMetadata && status === 'finished') {
      return 'processing';
    }
    // If metadata fetch failed, still show as finished so user sees the thumbnail/link
    if (metadataError && status === 'finished') {
      return 'finished';
    }
    return status;
  });
  
  // ===========================================
  // Event Handlers
  // ===========================================
  
  /**
   * Handle fullscreen open - passes fetched metadata to fullscreen component
   * This ensures fullscreen displays the same data as the preview without re-fetching
   */
  function handleFullscreen() {
    if (!onFullscreen) return;
    
    // Pass the effective metadata values (props or fetched) to fullscreen
    // Note: Pass raw thumbnail URLs so fullscreen can proxy them at higher resolution
    const metadata: VideoMetadata = {
      videoId: effectiveVideoId,
      title: effectiveTitle,
      description: fetchedDescription,
      channelName: fetchedChannelName,
      channelId: fetchedChannelId,
      channelThumbnail: fetchedChannelThumbnail, // Raw URL - fullscreen will proxy at higher res
      thumbnailUrl: rawThumbnailUrl, // Raw URL - fullscreen will proxy at higher res
      duration: fetchedDuration,
      viewCount: fetchedViewCount,
      likeCount: fetchedLikeCount,
      publishedAt: fetchedPublishedAt
    };
    
    console.debug('[VideoEmbedPreview] Opening fullscreen with metadata:', {
      videoId: metadata.videoId,
      title: metadata.title?.substring(0, 50) || 'none',
      channelName: metadata.channelName || 'none',
      duration: metadata.duration?.formatted || 'none',
      hasThumbnail: !!metadata.thumbnailUrl,
      hasChannelThumbnail: !!metadata.channelThumbnail
    });
    
    onFullscreen(metadata);
  }
  
  // Handle stop button click (not applicable for videos, but included for consistency)
  async function handleStop() {
    // Videos don't have cancellable tasks, but we include this for API consistency
    console.debug('[VideoEmbedPreview] Stop requested (not applicable for videos)');
  }
  
  // Note: Context menu handling is now done by UnifiedEmbedPreview
  // This allows the embed context menu to work properly
  // The tip creator functionality is available in the fullscreen view instead
</script>

<UnifiedEmbedPreview
  {id}
  appId="videos"
  skillId="video"
  {skillIconName}
  status={effectiveStatus}
  skillName={displayTitle}
  {taskId}
  {isMobile}
  onFullscreen={handleFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
  hasFullWidthImage={true}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div 
      class="video-details" 
      class:mobile={isMobileLayout}
    >
      {#if effectiveStatus === 'processing'}
        <!-- Processing state: show hostname only -->
        <div class="video-hostname">{hostname}</div>
      {:else if effectiveStatus === 'finished'}
        <!-- Finished state: show thumbnail (no duration badge - shown in info bar) and channel info -->
        {#if effectiveVideoId && thumbnailUrl}
          <!-- Video thumbnail (clean, no overlays) -->
          <div class="video-thumbnail-container">
            <img 
              src={thumbnailUrl} 
              alt={displayTitle}
              class="video-thumbnail"
              loading="lazy"
              onerror={(e) => {
                // Try fallback thumbnail quality (also proxied)
                const img = e.target as HTMLImageElement;
                if (img.src.includes('maxresdefault')) {
                  const fallbackRaw = `https://img.youtube.com/vi/${effectiveVideoId}/hqdefault.jpg`;
                  img.src = `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(fallbackRaw)}&max_width=${PREVIEW_IMAGE_MAX_WIDTH}`;
                } else {
                  img.style.display = 'none';
                }
              }}
            />
          </div>
          
          <!-- Info bar below thumbnail: channel thumbnail + title, duration + upload date -->
          {#if channelThumbnailUrl || shortenedTitle || fetchedDuration || formattedUploadDate}
            <div class="video-channel-info">
              <!-- Line 1: Channel thumbnail + shortened video title -->
              <div class="video-channel-row">
                {#if channelThumbnailUrl}
                  <img 
                    src={channelThumbnailUrl}
                    alt={fetchedChannelName || 'Channel'}
                    class="video-channel-thumbnail"
                    loading="lazy"
                    onerror={(e) => {
                      // Hide if thumbnail fails to load
                      (e.target as HTMLImageElement).style.display = 'none';
                    }}
                  />
                {/if}
                <span class="video-title-text">{shortenedTitle}</span>
              </div>
              
              <!-- Line 2: Duration + upload date (e.g., "29:26, Jul 31, 2025") -->
              {#if fetchedDuration || formattedUploadDate}
                <div class="video-meta-row">
                  {#if fetchedDuration}
                    <span class="video-meta-item">{fetchedDuration.formatted}</span>
                  {/if}
                  {#if fetchedDuration && formattedUploadDate}
                    <span class="video-meta-separator">,</span>
                  {/if}
                  {#if formattedUploadDate}
                    <span class="video-meta-item">{formattedUploadDate}</span>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
        {:else}
          <!-- Fallback: show URL path -->
          <div class="video-url-fallback">
            {#if hostname}
              <div class="video-hostname">{hostname}</div>
            {/if}
            {#if url}
              {@const urlObj = new URL(url)}
              {@const path = urlObj.pathname + urlObj.search + urlObj.hash}
              {#if path !== '/'}
                <div class="video-path">{path}</div>
              {/if}
            {/if}
          </div>
        {/if}
      {:else}
        <!-- Error state -->
        <div class="video-error">{hostname || url}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ===========================================
     Video Details Content
     =========================================== */
  
  .video-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    height: 100%;
  }
  
  /* Desktop layout: vertically centered content (only for text, not images) */
  .video-details:not(.mobile):not(:has(.video-thumbnail-container)) {
    justify-content: center;
  }
  
  /* When thumbnail is present, use relative positioning for channel info overlay */
  .video-details:has(.video-thumbnail-container) {
    gap: 0;
    position: relative;
    /* Channel info will be positioned absolutely at the bottom */
  }
  
  /* Mobile layout: top-aligned content */
  .video-details.mobile {
    justify-content: flex-start;
  }
  
  /* Video thumbnail container - full width and fills all available height */
  /* The thumbnail extends into the BasicInfosBar area to fill rounded corners */
  .video-thumbnail-container {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    overflow: hidden;
    background-color: var(--color-grey-15);
  }
  
  .video-thumbnail {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  
  /* ===========================================
     Info Bar Section (below thumbnail)
     Shows: channel thumbnail + title, duration + date
     =========================================== */
  
  /* Channel info bar - overlays the bottom of the thumbnail */
  /* Uses semi-transparent background for readability over the video thumbnail */
  .video-channel-info {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px 8px 4px;
    background: linear-gradient(
      to top,
      rgba(0, 0, 0, 0.75) 0%,
      rgba(0, 0, 0, 0.5) 60%,
      rgba(0, 0, 0, 0) 100%
    );
    z-index: 1;
  }
  
  /* Line 1: Channel thumbnail + name */
  .video-channel-row {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  
  /* Circular channel thumbnail (profile picture) - 29x29px (58px for retina) */
  /* Has subtle border for visibility on dark gradient background */
  .video-channel-thumbnail {
    width: 29px;
    height: 29px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
    background-color: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  }
  
  /* Video title text in info bar - white text for readability on dark gradient */
  .video-title-text {
    font-size: 12px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.95);
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
  }
  
  /* Line 2: Duration + upload date - lighter text on dark gradient */
  .video-meta-row {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: rgba(255, 255, 255, 0.75);
    line-height: 1.2;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
  }

  .video-meta-item {
    white-space: nowrap;
  }

  .video-meta-separator {
    color: rgba(255, 255, 255, 0.5);
  }
  
  /* Mobile adjustments for channel info overlay */
  .video-details.mobile .video-channel-info {
    padding: 4px 6px 2px;
    gap: 1px;
  }

  .video-details.mobile .video-channel-thumbnail {
    width: 24px;
    height: 24px;
  }

  .video-details.mobile .video-title-text {
    font-size: 11px;
  }

  .video-details.mobile .video-meta-row {
    font-size: 10px;
    gap: 3px;
  }
  
  /* Video hostname (for processing state) */
  .video-hostname {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
  }
  
  .video-details.mobile .video-hostname {
    font-size: 12px;
  }
  
  /* Video URL fallback (when no thumbnail) */
  .video-url-fallback {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  
  .video-path {
    font-size: 12px;
    color: var(--color-grey-60);
    line-height: 1.3;
    word-break: break-all;
  }
  
  /* Error state */
  .video-error {
    font-size: 14px;
    color: var(--color-error);
    line-height: 1.3;
  }
</style>
