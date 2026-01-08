<!--
  frontend/packages/ui/src/components/embeds/videos/VideoEmbedPreview.svelte
  
  Preview component for Video URL embeds (YouTube, etc.).
  Uses UnifiedEmbedPreview as base and provides video-specific details content.
  
  Features:
  - Receives ALL metadata as props (loaded from IndexedDB embed store)
  - NO fetch requests to preview server (except for image URL proxying)
  - Displays video thumbnail with info overlay:
    - Line 1: Channel thumbnail (29x29px round) + shortened video title
    - Line 2: Duration + upload date (e.g., "17:08, Jan 6, 2026")
  - Proxies all thumbnails through preview server for privacy
  - Passes metadata to fullscreen view
  
  Details content structure:
  - Processing: URL hostname
  - Finished: video thumbnail with info overlay (channel thumb + title + duration + date)
  - Error: hostname with error styling
  
  Data Flow:
  1. User sends YouTube URL in message
  2. Client fetches metadata from preview server, creates embed, syncs to server
  3. Embed data (with ALL metadata) stored in IndexedDB
  4. When rendering, data loaded from IndexedDB → passed as props → displayed
  5. NO additional preview server requests needed (except image proxying)
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  
  // ===========================================
  // Types
  // ===========================================
  
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
   * All metadata can be passed directly from decodedContent (stored in embed store)
   * or will be fetched from preview server if not provided
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Video URL */
    url: string;
    /** Video title */
    title?: string;
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen - receives fetched metadata so fullscreen can display it */
    onFullscreen?: (metadata: VideoMetadata) => void;
    // === Metadata from decodedContent (embed store) ===
    /** Channel name */
    channelName?: string;
    /** Channel ID */
    channelId?: string;
    /** Channel thumbnail URL (profile picture) */
    channelThumbnail?: string;
    /** Video thumbnail URL */
    thumbnail?: string;
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
    /** Video ID */
    videoId?: string;
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
    onFullscreen,
    // Metadata from decodedContent (embed store)
    channelName,
    channelId,
    channelThumbnail,
    thumbnail,
    durationSeconds,
    durationFormatted,
    viewCount,
    likeCount,
    publishedAt,
    videoId
  }: Props = $props();
  
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
  // Derived Display Values
  // ===========================================
  
  // Video ID: prop or extracted from URL
  let effectiveVideoId = $derived(videoId || extractVideoId(url) || '');
  
  // Display title: use prop or fall back to generic
  let displayTitle = $derived(title || 'YouTube Video');
  
  // Duration object from props
  let effectiveDuration = $derived.by(() => {
    if (durationSeconds !== undefined || durationFormatted) {
      return { 
        totalSeconds: durationSeconds || 0, 
        formatted: durationFormatted || '' 
      };
    }
    return undefined;
  });
  
  // Raw thumbnail URL: use prop or construct from video ID
  let rawThumbnailUrl = $derived.by(() => {
    if (thumbnail) {
      return thumbnail;
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
    if (!channelThumbnail) return '';
    return `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(channelThumbnail)}&max_width=${CHANNEL_THUMBNAIL_MAX_WIDTH}`;
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
    const titleToShorten = title || 'YouTube Video';
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
  let formattedUploadDate = $derived(formatUploadDate(publishedAt));
  
  // Status is passed directly from props - no fetching needed
  // Data is already loaded from IndexedDB (embed store)
  let effectiveStatus = $derived(status);
  
  // ===========================================
  // Event Handlers
  // ===========================================
  
  /**
   * Handle fullscreen open - passes metadata to fullscreen component
   * All data comes from props (loaded from IndexedDB embed store)
   */
  function handleFullscreen() {
    if (!onFullscreen) return;
    
    // Pass metadata values from props to fullscreen
    // Note: Pass raw thumbnail URLs so fullscreen can proxy them at higher resolution
    const metadata: VideoMetadata = {
      videoId: effectiveVideoId,
      title: title,
      channelName: channelName,
      channelId: channelId,
      channelThumbnail: channelThumbnail, // Raw URL - fullscreen will proxy at higher res
      thumbnailUrl: rawThumbnailUrl, // Raw URL - fullscreen will proxy at higher res
      duration: effectiveDuration,
      viewCount: viewCount,
      likeCount: likeCount,
      publishedAt: publishedAt
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
          {#if channelThumbnailUrl || shortenedTitle || effectiveDuration || formattedUploadDate}
            <div class="video-channel-info">
              <!-- Line 1: Channel thumbnail + shortened video title -->
              <div class="video-channel-row">
                {#if channelThumbnailUrl}
                  <img 
                    src={channelThumbnailUrl}
                    alt={channelName || 'Channel'}
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
              
              <!-- Line 2: Duration + upload date (e.g., "17:08, Jan 6, 2026") -->
              {#if effectiveDuration?.formatted || formattedUploadDate}
                <div class="video-meta-row">
                  {#if effectiveDuration?.formatted}
                    <span class="video-meta-item">{effectiveDuration.formatted}</span>
                  {/if}
                  {#if effectiveDuration?.formatted && formattedUploadDate}
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
  
  /* Channel info bar - overlays the thumbnail above the BasicInfosBar */
  /* Positioned at bottom: 60px to appear above the BasicInfosBar overlap area */
  /* Uses semi-transparent background for readability over the video thumbnail */
  .video-channel-info {
    position: absolute;
    bottom: 60px;
    left: 0;
    right: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 8px 10px 10px;
    background: linear-gradient(
      to top,
      rgba(0, 0, 0, 0.8) 0%,
      rgba(0, 0, 0, 0.6) 70%,
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
    bottom: 50px;
    padding: 6px 8px 8px;
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
