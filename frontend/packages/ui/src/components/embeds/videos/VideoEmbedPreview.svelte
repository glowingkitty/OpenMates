<!--
  frontend/packages/ui/src/components/embeds/videos/VideoEmbedPreview.svelte
  
  Preview component for Video URL embeds (YouTube, etc.).
  Uses UnifiedEmbedPreview as base and provides video-specific details content.
  
  Features:
  - Auto-fetches metadata from preview server when not provided
  - Displays title, description, channel name, channel thumbnail (profile picture), and video thumbnail
  - Shows video duration and relative upload date (e.g., "2 years ago")
  - Proxies all thumbnails through preview server for privacy
  - Passes fetched metadata to fullscreen view for consistent display
  
  Details content structure:
  - Processing: URL hostname
  - Finished: video thumbnail with duration badge, channel info row (thumbnail + name), meta row (duration + upload date)
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
  
  /**
   * Format relative time from ISO date string (e.g., "2 years ago", "3 months ago")
   * Used for displaying video upload date in a human-readable format
   */
  function formatRelativeTime(isoDateString: string | undefined): string {
    if (!isoDateString) return '';
    
    try {
      const date = new Date(isoDateString);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
      
      if (diffDays < 1) return 'Today';
      if (diffDays === 1) return 'Yesterday';
      if (diffDays < 7) return `${diffDays} days ago`;
      if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
      if (diffDays < 365) return `${Math.floor(diffDays / 30)} months ago`;
      return `${Math.floor(diffDays / 365)} years ago`;
    } catch {
      return '';
    }
  }
  
  // Derived relative upload date
  let relativeUploadDate = $derived(formatRelativeTime(fetchedPublishedAt));
  
  // Shortened channel name (truncate if too long for preview)
  let shortenedChannelName = $derived.by(() => {
    if (!fetchedChannelName) return '';
    // Max ~25 chars for preview layout
    const maxLength = 25;
    if (fetchedChannelName.length <= maxLength) return fetchedChannelName;
    return fetchedChannelName.substring(0, maxLength - 1) + '…';
  });
  
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
        <!-- Finished state: show thumbnail with duration overlay and channel info -->
        {#if effectiveVideoId && thumbnailUrl}
          <!-- Video thumbnail with duration badge -->
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
            <!-- Duration overlay -->
            {#if fetchedDuration}
              <div class="video-duration-badge">{fetchedDuration.formatted}</div>
            {/if}
          </div>
          
          <!-- Channel info below thumbnail: channel thumbnail + name, duration + upload date -->
          {#if (channelThumbnailUrl && shortenedChannelName) || (fetchedDuration && relativeUploadDate)}
            <div class="video-channel-info">
              <!-- Line 1: Channel thumbnail + shortened channel name -->
              {#if channelThumbnailUrl || shortenedChannelName}
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
                  {#if shortenedChannelName}
                    <span class="video-channel-name">{shortenedChannelName}</span>
                  {/if}
                </div>
              {/if}
              
              <!-- Line 2: Duration + upload date -->
              {#if fetchedDuration || relativeUploadDate}
                <div class="video-meta-row">
                  {#if fetchedDuration}
                    <span class="video-meta-item">{fetchedDuration.formatted}</span>
                  {/if}
                  {#if fetchedDuration && relativeUploadDate}
                    <span class="video-meta-separator">•</span>
                  {/if}
                  {#if relativeUploadDate}
                    <span class="video-meta-item">{relativeUploadDate}</span>
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
  
  /* When thumbnail is present, use flex layout to share space with channel info */
  .video-details:has(.video-thumbnail-container) {
    gap: 0;
    /* Channel info at bottom will take its natural height, thumbnail takes the rest */
  }
  
  /* Mobile layout: top-aligned content */
  .video-details.mobile {
    justify-content: flex-start;
  }
  
  /* Video thumbnail container - full width and height */
  .video-thumbnail-container {
    position: relative;
    width: 100%;
    height: 100%;
    border-radius: 8px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    flex: 1;
    min-height: 0;
  }
  
  .video-thumbnail {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  
  /* Duration badge overlay - bottom right of thumbnail */
  .video-duration-badge {
    position: absolute;
    bottom: 6px;
    right: 6px;
    background: rgba(0, 0, 0, 0.8);
    color: var(--color-grey-100);
    font-size: 11px;
    font-weight: 500;
    padding: 2px 5px;
    border-radius: 3px;
    font-family: var(--font-mono, monospace);
    letter-spacing: 0.3px;
  }
  
  /* ===========================================
     Channel Info Section (below thumbnail)
     =========================================== */
  
  .video-channel-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px 4px 2px;
    min-height: 0;
    flex-shrink: 0;
  }
  
  /* Line 1: Channel thumbnail + name */
  .video-channel-row {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  
  /* Circular channel thumbnail (profile picture) - 29x29px (58px for retina) */
  .video-channel-thumbnail {
    width: 29px;
    height: 29px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
    background-color: var(--color-grey-20);
  }
  
  .video-channel-name {
    font-size: 12px;
    color: var(--color-grey-80);
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }
  
  /* Line 2: Duration + upload date */
  .video-meta-row {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 11px;
    color: var(--color-grey-60);
    line-height: 1.2;
  }
  
  .video-meta-item {
    white-space: nowrap;
  }
  
  .video-meta-separator {
    color: var(--color-grey-40);
  }
  
  /* Mobile adjustments for channel info */
  .video-details.mobile .video-channel-info {
    padding: 4px 2px 0;
    gap: 1px;
  }
  
  .video-details.mobile .video-channel-thumbnail {
    width: 24px;
    height: 24px;
  }
  
  .video-details.mobile .video-channel-name {
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
