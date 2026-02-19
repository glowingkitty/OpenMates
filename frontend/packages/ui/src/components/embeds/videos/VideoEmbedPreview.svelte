<!--
  frontend/packages/ui/src/components/embeds/videos/VideoEmbedPreview.svelte
  
  Preview component for Video URL embeds (YouTube, etc.).
  Uses UnifiedEmbedPreview as base and provides video-specific details content.
  
  Features:
  - Receives ALL metadata as props (loaded from IndexedDB embed store)
  - NO fetch requests to preview server (except for image URL proxying)
  - Displays video thumbnail in details section (full width)
  - Channel info displayed in BasicInfosBar:
    - Line 1: Channel thumbnail (circular, 29x29px) + shortened video title (font-size 16px)
    - Line 2: Duration + upload date (e.g., "17:08, Jan 6, 2026") (font-size 16px)
  - Proxies all thumbnails through preview server for privacy
  - Passes metadata to fullscreen view
  
  Details content structure:
  - Processing: URL hostname
  - Finished: video thumbnail (clean, no overlays)
  - Error: hostname with error styling
  
  BasicInfosBar content (for finished state):
  - faviconUrl: channel thumbnail (circular)
  - skillName: shortened video title
  - customStatusText: duration + upload date
  
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
  
  // Raw thumbnail URL: use prop or construct from video ID.
  // When a full API fetch was performed, `thumbnail` is the best available resolution
  // (maxres > high > medium > default) as stored by createYouTubeEmbed().
  // When no API fetch was performed (static embed / no credits), `thumbnail` is null
  // and we fall back to hqdefault.jpg — guaranteed to exist for every YouTube video.
  // maxresdefault.jpg only exists for HD uploads, so using it as a fallback causes
  // unnecessary 404s and a visible delay before the onerror fallback fires.
  let rawThumbnailUrl = $derived.by(() => {
    if (thumbnail) {
      return thumbnail;
    }
    // Fallback: construct thumbnail URL from video ID using hqdefault (always available)
    if (effectiveVideoId) {
      return `https://img.youtube.com/vi/${effectiveVideoId}/hqdefault.jpg`;
    }
    return '';
  });
  
  // Thumbnail URL: try the privacy-proxy first, fall back to direct CDN if it fails.
  // The proxy (preview.openmates.org) may be unavailable for unauthenticated users or
  // during development; the direct YouTube CDN URL is always the reliable fallback.
  // onerror below implements the two-step retry so the image always renders.
  let thumbnailUrl = $derived(rawThumbnailUrl
    ? `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(rawThumbnailUrl)}&max_width=${PREVIEW_IMAGE_MAX_WIDTH}`
    : '');

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
  
  // Custom status text for BasicInfosBar: "17:08, Jan 6, 2026" (duration + date)
  // Shown as the second line in BasicInfosBar (font-size 16px)
  let customStatusText = $derived.by(() => {
    const parts: string[] = [];
    if (effectiveDuration?.formatted) {
      parts.push(effectiveDuration.formatted);
    }
    if (formattedUploadDate) {
      parts.push(formattedUploadDate);
    }
    return parts.length > 0 ? parts.join(', ') : undefined;
  });
  
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
  skillName={shortenedTitle}
  {taskId}
  {isMobile}
  onFullscreen={handleFullscreen}
  onStop={handleStop}
  showStatus={true}
  showSkillIcon={false}
  hasFullWidthImage={true}
  faviconUrl={channelThumbnailUrl || undefined}
  faviconIsCircular={true}
  {customStatusText}
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
        <!-- Finished state: show video thumbnail only (channel info is displayed in BasicInfosBar) -->
        {#if effectiveVideoId && thumbnailUrl}
          <!-- Video thumbnail (clean, no overlays - channel info moved to BasicInfosBar) -->
          <div class="video-thumbnail-container">
            <img 
              src={thumbnailUrl} 
              alt={displayTitle}
              class="video-thumbnail"
              loading="lazy"
              onerror={(e) => {
                // Two-step fallback: proxy → direct CDN → hide.
                // Step 1: if the proxied URL failed, retry with the direct CDN URL.
                // Step 2: if the direct CDN URL also fails, hide the image.
                const img = e.target as HTMLImageElement;
                if (rawThumbnailUrl && img.src !== rawThumbnailUrl) {
                  // Proxy failed — retry directly from the YouTube CDN
                  img.src = rawThumbnailUrl;
                } else {
                  // Direct CDN also failed — hide image, show fallback below
                  img.style.display = 'none';
                }
              }}
            />
          </div>
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
  
  /* When thumbnail is present, fill the available space */
  .video-details:has(.video-thumbnail-container) {
    gap: 0;
  }
  
  /* Mobile layout: top-aligned content */
  .video-details.mobile {
    justify-content: flex-start;
  }
  
  /* Video thumbnail container - full width, fills available height in details section */
  /* Channel info (title, duration, date) is displayed in BasicInfosBar below */
  .video-thumbnail-container {
    height: 100%;
  }
  
  .video-thumbnail {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
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
