<!--
  frontend/packages/ui/src/components/embeds/videos/VideoEmbedFullscreen.svelte
  
  Fullscreen view for Video URL embeds (YouTube, etc.).
  Uses UnifiedEmbedFullscreen as base and provides video-specific content.
  
  This component:
  1. Shows video thumbnail preview image (780px max width)
  2. Shows play button overlay on thumbnail
  3. When play is clicked, signals ActiveChat to start VideoIframe
  4. Shows video metadata (title, channel, duration, view count)
  5. Shows "Open on YouTube" button
  6. Shows PiP button (when video is playing)
  7. Shows "Tip Creator" button
  
  The VideoIframe component lives in ActiveChat (not here).
  This separation allows the iframe to persist when this fullscreen view closes (for PiP).
  
  Data Flow:
  - Receives metadata from VideoEmbedPreview via props (already fetched, no re-fetch needed)
  - Falls back to extracting video ID and fetching if metadata not provided
-->

<script lang="ts">
  import { onDestroy, tick } from 'svelte';
  import { get } from 'svelte/store';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { videoIframeStore } from '../../../stores/videoIframeStore';
  import { text } from '@repo/ui';
  
  // Import VideoMetadata type from preview component
  import type { VideoMetadata } from './VideoEmbedPreview.svelte';
  
  // ===========================================
  // Constants: Preview Server Image Proxy
  // ===========================================
  
  // Preview server base URL for image proxying
  // This ensures user privacy by not making direct requests to YouTube/Google CDN
  const PREVIEW_SERVER = 'https://preview.openmates.org';
  // Max width for fullscreen thumbnail (2x for retina displays on 780px container)
  const FULLSCREEN_IMAGE_MAX_WIDTH = 1560;
  
  /**
   * Props for video embed fullscreen
   */
  interface Props {
    /** Video URL */
    url: string;
    /** Video title */
    title?: string;
    /** Close handler */
    onClose: () => void;
    /** Optional: Video ID (for restoration from PiP) */
    videoId?: string;
    /** Optional: Flag indicating this was opened from PiP (video already playing) */
    restoreFromPip?: boolean;
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
    /** Metadata passed from VideoEmbedPreview (already fetched from preview server) */
    metadata?: VideoMetadata;
  }
  
  let {
    url,
    title,
    onClose,
    videoId: propVideoId,
    restoreFromPip = false,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat,
    metadata
  }: Props = $props();
  
  // ===========================================
  // State: Video Information
  // ===========================================
  
  // Use metadata from preview if available, otherwise extract from URL
  // Priority: metadata props > direct props > extracted from URL
  let videoId = $state(metadata?.videoId || propVideoId || '');
  // Raw thumbnail URL (direct YouTube CDN) - will be proxied for display
  let rawThumbnailUrl = $state(metadata?.thumbnailUrl || '');
  let displayTitle = $state(metadata?.title || title || 'YouTube Video');
  let channelName = $state(metadata?.channelName || '');
  let channelId = $state(metadata?.channelId || '');
  let rawChannelThumbnail = $state(metadata?.channelThumbnail || '');  // Channel profile picture URL
  let description = $state(metadata?.description || '');
  let duration = $state(metadata?.duration);
  let viewCount = $state(metadata?.viewCount);
  let likeCount = $state(metadata?.likeCount);
  let publishedAt = $state(metadata?.publishedAt);
  
  // DEBUG: Log received metadata to verify data flow
  $effect(() => {
    console.debug('[VideoEmbedFullscreen] Component initialized with metadata:', {
      hasMetadataProp: !!metadata,
      videoId,
      title: displayTitle?.substring(0, 50),
      channelName,
      channelId,
      description: description?.substring(0, 50),
      duration: duration?.formatted,
      viewCount,
      likeCount,
      publishedAt,
      hasThumbnail: !!rawThumbnailUrl,
      hasChannelThumbnail: !!rawChannelThumbnail
    });
  });
  
  // Track whether video is playing (iframe is active)
  // Subscribe to videoIframeStore to check if video is playing
  let isVideoPlaying = $state(false);
  
  // Subscribe to videoIframeStore to track if video is playing
  $effect(() => {
    const unsubscribe = videoIframeStore.subscribe((state) => {
      // Video is playing if store is active and has matching videoId
      isVideoPlaying = state.isActive && state.videoId === videoId;
    });
    return unsubscribe;
  });
  
  // Generate YouTube embed URL with privacy settings
  // Uses youtube-nocookie.com (privacy-enhanced mode) to minimize cookie tracking
  let embedUrl = $derived(
    videoId
      ? // Use privacy-enhanced mode (youtube-nocookie.com) to minimize cookie tracking
        // URL parameters:
        // - modestbranding=1: Reduces YouTube branding
        // - rel=0: Don't show related videos from other channels
        // - iv_load_policy=3: Don't show video annotations
        // - fs=1: Allow fullscreen (user preference)
        // - autoplay=1: Start playing when iframe loads (user clicked play button)
        // - enablejsapi=0: Disable JavaScript API to reduce tracking
        `https://www.youtube-nocookie.com/embed/${videoId}?modestbranding=1&rel=0&iv_load_policy=3&fs=1&autoplay=1&enablejsapi=0`
      : ''
  );
  
  // Proxied thumbnail URL through preview server for privacy
  // This prevents users' browsers from making direct requests to YouTube/Google CDN
  let thumbnailUrl = $derived.by(() => {
    if (!rawThumbnailUrl) return '';
    return `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(rawThumbnailUrl)}&max_width=${FULLSCREEN_IMAGE_MAX_WIDTH}`;
  });
  
  // Proxied channel thumbnail URL (29x29px display, 58px for retina)
  const CHANNEL_THUMBNAIL_MAX_WIDTH = 58;
  let channelThumbnailUrl = $derived.by(() => {
    if (!rawChannelThumbnail) return '';
    return `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(rawChannelThumbnail)}&max_width=${CHANNEL_THUMBNAIL_MAX_WIDTH}`;
  });
  
  // ===========================================
  // URL Processing Effect
  // ===========================================
  
  // Process URL to extract video information (fallback when metadata not provided)
  $effect(() => {
    if (url) {
      try {
        // If we have metadata, use it (already set in initial state)
        if (metadata) {
          console.debug('[VideoEmbedFullscreen] Using metadata from preview:', {
            videoId: metadata.videoId,
            title: metadata.title?.substring(0, 50),
            channelName: metadata.channelName,
            duration: metadata.duration?.formatted
          });
          return;
        }
        
        // If videoId was provided as prop (from PiP restoration), use it
        // Otherwise, extract from URL
        if (propVideoId) {
          // Use provided videoId and generate raw thumbnail URL (will be proxied)
          videoId = propVideoId;
          rawThumbnailUrl = `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg`;
        } else {
          // YouTube URL patterns - extract video ID from URL
          const youtubeMatch = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)/);
          if (youtubeMatch) {
            videoId = youtubeMatch[1];
            rawThumbnailUrl = `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg`;
            if (!title) {
              displayTitle = 'YouTube Video';
            }
          }
        }
      } catch (e) {
        console.debug('[VideoEmbedFullscreen] Error parsing URL:', e);
      }
    }
    
    // Update displayTitle if title prop changes (but not if we have metadata)
    if (title && !metadata?.title) {
      displayTitle = title;
    }
  });
  
  // If restoring from PiP, the video is already playing
  // Just exit PiP mode to show it in fullscreen position
  $effect(() => {
    if (restoreFromPip && videoId) {
      console.debug('[VideoEmbedFullscreen] Restoring from PiP - exiting PiP mode');
      videoIframeStore.exitPipMode();
    }
  });
  
  // ===========================================
  // Formatting Helpers
  // ===========================================
  
  /**
   * Format a number with K/M/B suffix for compact display
   * e.g., 1500000 -> "1.5M"
   */
  function formatCompactNumber(count: number): string {
    if (count >= 1_000_000_000) {
      return `${(count / 1_000_000_000).toFixed(1)}B`;
    }
    if (count >= 1_000_000) {
      return `${(count / 1_000_000).toFixed(1)}M`;
    }
    if (count >= 1_000) {
      return `${(count / 1_000).toFixed(1)}K`;
    }
    return `${count}`;
  }
  
  /**
   * Format view count with localized number formatting using translations
   * e.g., 1500000 -> "1.5M views" (translated)
   */
  function formatViewCount(count: number | undefined): string {
    if (!count) return '';
    const formattedCount = formatCompactNumber(count);
    return $text('embeds.video_views', { count: formattedCount });
  }
  
  /**
   * Format like count with localized number formatting using translations
   * e.g., 68030 -> "68K likes" (translated)
   */
  function formatLikeCount(count: number | undefined): string {
    if (!count) return '';
    const formattedCount = formatCompactNumber(count);
    return $text('embeds.video_likes', { count: formattedCount });
  }
  
  /**
   * Format published date as relative time using translations
   * e.g., "2 years ago" (translated)
   */
  function formatPublishedDate(dateStr: string | undefined): string {
    if (!dateStr) return '';
    
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
      
      if (diffDays < 1) return $text('embeds.date_today');
      if (diffDays === 1) return $text('embeds.date_yesterday');
      if (diffDays < 7) return $text('embeds.date_days_ago', { count: diffDays });
      if (diffDays < 30) return $text('embeds.date_weeks_ago', { count: Math.floor(diffDays / 7) });
      if (diffDays < 365) return $text('embeds.date_months_ago', { count: Math.floor(diffDays / 30) });
      return $text('embeds.date_years_ago', { count: Math.floor(diffDays / 365) });
    } catch {
      return '';
    }
  }
  
  /**
   * Format upload date as localized date string
   * Used for the BasicInfosBar status text (same format as VideoEmbedPreview)
   */
  function formatUploadDate(isoDateString: string | undefined): string {
    if (!isoDateString) return '';
    
    try {
      const date = new Date(isoDateString);
      // Use browser locale for date formatting
      return date.toLocaleDateString(undefined, { 
        month: 'short', 
        day: 'numeric', 
        year: 'numeric' 
      });
    } catch {
      return '';
    }
  }
  
  // ===========================================
  // BasicInfosBar Derived Values (match VideoEmbedPreview format)
  // ===========================================
  
  // Shortened video title for BasicInfosBar (truncate if too long)
  let shortenedTitle = $derived.by(() => {
    const titleToShorten = displayTitle || $text('embeds.youtube_video');
    // Max ~30 chars for preview layout in the info bar
    const maxLength = 30;
    if (titleToShorten.length <= maxLength) return titleToShorten;
    return titleToShorten.substring(0, maxLength - 1) + '…';
  });
  
  // Formatted upload date for BasicInfosBar
  let formattedUploadDate = $derived(formatUploadDate(publishedAt));
  
  // Custom status text for BasicInfosBar: "17:08, Jan 6, 2026" (duration + date)
  // Shown as the second line in BasicInfosBar (same format as VideoEmbedPreview)
  let customStatusText = $derived.by(() => {
    const parts: string[] = [];
    if (duration?.formatted) {
      parts.push(duration.formatted);
    }
    if (formattedUploadDate) {
      parts.push(formattedUploadDate);
    }
    return parts.length > 0 ? parts.join(', ') : undefined;
  });
  
  // ===========================================
  // Event Handlers
  // ===========================================
  
  // Handle play button click - signals ActiveChat to start VideoIframe
  function handlePlayClick() {
    if (!videoId || !embedUrl) {
      console.warn('[VideoEmbedFullscreen] Cannot play: missing videoId or embedUrl');
      return;
    }
    
    console.debug('[VideoEmbedFullscreen] Play button clicked, starting video', {
      videoId,
      embedUrl,
      thumbnailUrl,
      title: displayTitle
    });
    
    // Signal store to play video - this will trigger ActiveChat to render VideoIframe
    videoIframeStore.playVideo({
      url,
      title: displayTitle,
      videoId,
      embedUrl,
      thumbnailUrl
    });
  }
  
  // Handle tip creator - opens tip settings menu
  async function handleTipCreator() {
    if (!url || !videoId) {
      console.warn('[VideoEmbedFullscreen] Cannot tip: missing URL or video ID');
      return;
    }
    
    try {
      // Import tip store and settings navigation
      const { tipStore } = await import('../../../stores/tipStore');
      const { navigateToSettings } = await import('../../../stores/settingsNavigationStore');
      const { panelState } = await import('../../../stores/panelStateStore');
      
      // Set tip data in store (videoUrl will be used to fetch channel ID)
      tipStore.setTipData({
        videoUrl: url,
        contentType: 'video'
      });
      
      // Navigate to tip settings
      navigateToSettings('shared/tip', $text('embeds.tip_creator'), 'tip', 'embeds.tip_creator');
      
      // Open settings panel if not already open
      panelState.openSettings();
      
      console.debug('[VideoEmbedFullscreen] Opened tip settings for video:', videoId);
    } catch (error) {
      console.error('[VideoEmbedFullscreen] Error opening tip settings:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to open tip menu. Please try again.');
    }
  }
  
  // Handle copy - copies video URL to clipboard with notification
  async function handleCopy() {
    try {
      if (url) {
        await navigator.clipboard.writeText(url);
        console.debug('[VideoEmbedFullscreen] Copied video URL to clipboard');
        // Show success notification
        const { notificationStore } = await import('../../../stores/notificationStore');
        notificationStore.success('Video URL copied to clipboard');
      }
    } catch (error) {
      console.error('[VideoEmbedFullscreen] Failed to copy URL:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to copy URL to clipboard');
    }
  }
  
  // Share is handled by UnifiedEmbedFullscreen's built-in share handler
  // which uses currentEmbedId, appId, and skillId to construct the embed
  // share context and properly opens the settings panel (including on mobile).
  
  // Handle entering picture-in-picture mode
  // This uses CSS-based transitions - no DOM movement
  async function handleEnterPip() {
    // Check if video is playing
    const state = get(videoIframeStore);
    
    if (!state.isActive || !state.videoId) {
      console.warn('[VideoEmbedFullscreen] Cannot enter PiP: video not playing');
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Please play the video first to enter picture-in-picture mode');
      return;
    }
    
    try {
      console.debug('[VideoEmbedFullscreen] Entering PiP mode');
      
      // Signal store to enter PiP mode - this triggers CSS transition in VideoIframe
      videoIframeStore.enterPipMode();
      
      // Wait for CSS transition to start
      await tick();
      
      // Close this fullscreen view - VideoIframe will persist in PiP mode
      onClose();
    } catch (error) {
      console.error('[VideoEmbedFullscreen] Error entering PiP mode:', error);
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to enter picture-in-picture mode');
    }
  }
  
  // Wrapper for onClose that handles cleanup
  // When user explicitly closes (not entering PiP), we should fade out and close the video
  function handleClose() {
    // Check if we're in PiP mode - if so, don't close the video
    const state = get(videoIframeStore);
    if (state.isPipMode) {
      console.debug('[VideoEmbedFullscreen] Closing fullscreen, video stays in PiP');
      onClose();
      return;
    }
    
    // User is closing the fullscreen view AND the video
    // Use fade-out animation for smooth UX
    if (state.isActive) {
      console.debug('[VideoEmbedFullscreen] Closing fullscreen with video fade-out');
      videoIframeStore.closeWithFadeOut(300);
    }
    onClose();
  }
  
  // Cleanup on component destroy
  // Only close video if NOT in PiP mode (PiP should persist)
  onDestroy(() => {
    const state = get(videoIframeStore);
    if (!state.isPipMode) {
      console.debug('[VideoEmbedFullscreen] Component destroying, not in PiP - video would close');
      // Note: We don't close here to avoid closing when switching views
      // The close is handled by handleClose when user explicitly closes
    } else {
      console.debug('[VideoEmbedFullscreen] Component destroying, in PiP - video persists');
    }
  });
</script>

<UnifiedEmbedFullscreen
  appId="videos"
  skillId="video"
  title=""
  onClose={handleClose}
  onCopy={handleCopy}
  currentEmbedId={embedId}
  skillIconName="video"
  status="finished"
  skillName={shortenedTitle}
  faviconUrl={channelThumbnailUrl || undefined}
  faviconIsCircular={true}
  showSkillIcon={false}
  showStatus={true}
  {customStatusText}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="video-container">
      <!-- Video thumbnail with play button -->
      <!-- Only show thumbnail when video is NOT playing -->
      {#if !isVideoPlaying && videoId && thumbnailUrl}
        <div class="video-thumbnail-wrapper">
          <img 
            src={thumbnailUrl} 
            alt={displayTitle}
            class="video-thumbnail"
            loading="lazy"
            crossorigin="anonymous"
            onerror={(e) => {
              // Try fallback thumbnail quality (also proxied)
              const img = e.target as HTMLImageElement;
              if (img.src.includes('maxresdefault')) {
                const fallbackRaw = `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`;
                img.src = `${PREVIEW_SERVER}/api/v1/image?url=${encodeURIComponent(fallbackRaw)}&max_width=${FULLSCREEN_IMAGE_MAX_WIDTH}`;
              } else {
                img.style.display = 'none';
              }
            }}
          />
          <!-- Play button overlay -->
          <button
            class="play-button-overlay"
            onclick={handlePlayClick}
            aria-label={$text('embeds.video_play')}
            type="button"
          >
            <span class="play-icon"></span>
          </button>
        </div>
        <!-- Action buttons - positioned below thumbnail -->
        {#if url}
          <div class="button-container">
            <!-- Tip Creator button - positioned left to the play on YouTube button -->
            <button
              class="tip-creator-button"
              onclick={handleTipCreator}
              type="button"
              aria-label={$text('embeds.tip_creator')}
            >
              <span class="clickable-icon icon_volunteering"></span>
            </button>
            <a 
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              class="open-on-youtube-button"
            >
              {$text('embeds.open_on_youtube')}
            </a>
            <!-- Picture-in-Picture button - only shown when video is playing -->
            {#if isVideoPlaying && videoId && embedUrl}
              <button
                class="pip-button"
                onclick={handleEnterPip}
                type="button"
                aria-label={$text('embeds.video_pip')}
              >
                <span class="clickable-icon icon_pip"></span>
              </button>
            {/if}
          </div>
        {/if}
      {:else if isVideoPlaying}
        <!-- Video is playing - VideoIframe shows the actual video -->
        <!-- This spacer maintains layout so buttons stay below the video -->
        <div class="video-playing-spacer"></div>
        
        <!-- Action buttons when video is playing -->
        {#if url}
          <div class="button-container">
            <!-- Tip Creator button -->
            <button
              class="tip-creator-button"
              onclick={handleTipCreator}
              type="button"
              aria-label={$text('embeds.tip_creator')}
            >
              <span class="clickable-icon icon_volunteering"></span>
            </button>
            <a 
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              class="open-on-youtube-button"
            >
              {$text('embeds.open_on_youtube')}
            </a>
            <!-- Picture-in-Picture button -->
            {#if videoId && embedUrl}
              <button
                class="pip-button"
                onclick={handleEnterPip}
                type="button"
                aria-label={$text('embeds.video_pip')}
              >
                <span class="clickable-icon icon_pip"></span>
              </button>
            {/if}
          </div>
        {/if}
      {/if}
      
      <!-- Views and likes - displayed below the buttons with icons -->
      {#if (viewCount || likeCount) && !isVideoPlaying}
        <div class="video-stats-row">
          {#if viewCount}
            <span class="stat-item">
              <span class="stat-icon icon_visibility"></span>
              {formatViewCount(viewCount)}
            </span>
          {/if}
          {#if viewCount && likeCount}
            <span class="stat-separator">•</span>
          {/if}
          {#if likeCount}
            <span class="stat-item">
              <span class="stat-icon icon_thumb_up"></span>
              {formatLikeCount(likeCount)}
            </span>
          {/if}
        </div>
      {/if}
      
      <!-- Video title - displayed prominently below stats -->
      {#if displayTitle && !isVideoPlaying}
        <div class="video-title-row">
          {#if channelThumbnailUrl}
            <img 
              src={channelThumbnailUrl}
              alt={channelName || 'Channel'}
              class="title-channel-thumbnail"
              loading="lazy"
              crossorigin="anonymous"
              onerror={(e) => {
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
          {/if}
          <h2 class="video-title">{displayTitle}</h2>
        </div>
      {/if}
      
      <!-- Video metadata info: channel name, upload date -->
      {#if (channelName || publishedAt) && !isVideoPlaying}
        <div class="video-metadata">
          <div class="video-meta-line">
            {#if channelName}
              <span class="meta-text">{$text('embeds.video_by')} {channelName}</span>
            {/if}
            {#if channelName && publishedAt}
              <span class="meta-separator">,</span>
            {/if}
            {#if publishedAt}
              <span class="meta-text">{formatPublishedDate(publishedAt)} {$text('embeds.video_uploaded')}</span>
            {/if}
          </div>
        </div>
      {/if}
      
      <!-- Video description - truncated -->
      {#if description && !isVideoPlaying}
        <div class="video-description">
          <p class="description-text">{description}</p>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ===========================================
     Video Fullscreen - Layout
     =========================================== */
  
  .video-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
    width: 100%;
    margin-top: 20px;
  }
  
  /* ===========================================
     Video Thumbnail with Play Button
     =========================================== */
  
  .video-thumbnail-wrapper {
    position: relative;
    width: 100%;
    max-width: 780px;
    aspect-ratio: 16 / 9;
    border-radius: 16px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    margin-top: 60px;
  }
  
  .video-thumbnail {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  
  /* Play button overlay - centered on thumbnail */
  .play-button-overlay {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    background: rgba(0, 0, 0, 0.7);
    border: none;
    border-radius: 50%;
    width: 80px;
    height: 80px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: all 0.2s ease-in-out;
    padding: 0;
    z-index: 10;
  }
  
  .play-button-overlay:hover {
    background: rgba(0, 0, 0, 0.85);
    transform: translate(-50%, -50%) scale(1.1);
  }
  
  .play-button-overlay:active {
    transform: translate(-50%, -50%) scale(0.95);
  }
  
  .play-icon {
    width: 48px;
    height: 48px;
    display: block;
    background-image: url('@openmates/ui/static/icons/play.svg');
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    filter: brightness(0) invert(1); /* Make icon white */
    pointer-events: none;
  }
  
  
  /* ===========================================
     Video Title with Channel Thumbnail
     =========================================== */
  
  .video-title-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    margin: 8px 0;
    max-width: 780px;
    width: 100%;
  }
  
  /* Channel thumbnail next to title (29x29px, round) */
  .title-channel-thumbnail {
    width: 29px;
    height: 29px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
    background-color: var(--color-grey-20);
  }
  
  .video-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-font-primary);
    margin: 0;
    text-align: left;
    line-height: 1.4;
    /* Limit to 2 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  
  /* ===========================================
     Video Metadata Info
     =========================================== */
  
  .video-metadata {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    font-size: 14px;
    color: var(--color-grey-60);
    margin-top: 4px;
    max-width: 780px;
    width: 100%;
  }
  
  /* Meta line: "by {channel}, {date} uploaded" */
  .video-meta-line {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 14px;
    color: var(--color-grey-60);
  }
  
  .meta-text {
    color: var(--color-grey-60);
  }
  
  .meta-separator {
    color: var(--color-grey-50);
  }
  
  /* ===========================================
     Video Stats (Views/Likes) - Below Buttons
     =========================================== */
  
  .video-stats-row {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    font-size: 13px;
    color: var(--color-grey-60);
    margin-top: 16px;
  }
  
  .stat-item {
    display: flex;
    align-items: center;
    gap: 4px;
    color: var(--color-grey-60);
  }
  
  .stat-icon {
    width: 16px;
    height: 16px;
    background-color: var(--color-grey-60);
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: contain;
    mask-size: contain;
  }
  
  .stat-separator {
    color: var(--color-grey-40);
  }
  
  /* ===========================================
     Video Description
     =========================================== */
  
  .video-description {
    max-width: 780px;
    width: 100%;
    margin-top: 16px;
    padding: 0 16px;
    box-sizing: border-box;
  }
  
  .description-text {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.5;
    margin: 0;
    /* Limit to 4 lines with ellipsis */
    display: -webkit-box;
    -webkit-line-clamp: 4;
    line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
    white-space: pre-wrap;
  }
  
  /* ===========================================
     Video Playing Spacer
     =========================================== */
  
  /* When video is playing, this spacer maintains the layout height
     so buttons stay positioned below the video iframe.
     The actual video is rendered by VideoIframe in ActiveChat. */
  .video-playing-spacer {
    width: 100%;
    max-width: 780px;
    aspect-ratio: 16 / 9;
    /* Transparent - the actual video is shown by VideoIframe */
  }
  
  /* ===========================================
     Action Buttons
     =========================================== */
  
  /* Button container - centered below thumbnail */
  .button-container {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    width: 100%;
    max-width: 780px;
    margin-top: 16px;
  }
  
  /* Open on YouTube button - styled as button but is an <a> link */
  .open-on-youtube-button {
    /* Apply button styles from buttons.css */
    background-color: var(--color-button-primary);
    padding: 6px 25px;
    border-radius: 20px;
    border: none;
    filter: drop-shadow(0px 4px 4px rgba(0, 0, 0, 0.25));
    cursor: pointer;
    transition: all 0.15s ease-in-out;
    min-width: 112px;
    height: 41px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--color-font-button);
    font-family: var(--button-font-family);
    font-size: var(--button-font-size);
    font-weight: var(--button-font-weight);
    text-decoration: none;
  }
  
  .open-on-youtube-button:hover {
    background-color: var(--color-button-primary-hover);
    scale: 1.02;
  }
  
  .open-on-youtube-button:active {
    background-color: var(--color-button-primary-pressed);
    scale: 0.98;
    filter: none;
  }
  
  /* Tip creator button - rounded button with icon only */
  .tip-creator-button {
    background-color: var(--color-button-secondary, var(--color-grey-20));
    padding: 0;
    border-radius: 20px;
    border: none;
    filter: drop-shadow(0px 4px 4px rgba(0, 0, 0, 0.25));
    cursor: pointer;
    transition: all 0.15s ease-in-out;
    width: 41px;
    height: 41px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  
  .tip-creator-button:hover {
    background-color: var(--color-button-secondary-hover, var(--color-grey-30));
    scale: 1.02;
  }
  
  .tip-creator-button:active {
    background-color: var(--color-button-secondary-pressed, var(--color-grey-40));
    scale: 0.98;
    filter: none;
  }
  
  /* Picture-in-Picture button - rounded button with icon only */
  .pip-button {
    background-color: var(--color-button-secondary, var(--color-grey-20));
    padding: 0;
    border-radius: 20px;
    border: none;
    filter: drop-shadow(0px 4px 4px rgba(0, 0, 0, 0.25));
    cursor: pointer;
    transition: all 0.15s ease-in-out;
    width: 41px;
    height: 41px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }
  
  .pip-button:hover {
    background-color: var(--color-button-secondary-hover, var(--color-grey-30));
    scale: 1.02;
  }
  
  .pip-button:active {
    background-color: var(--color-button-secondary-pressed, var(--color-grey-40));
    scale: 0.98;
    filter: none;
  }
  
  /* Icon sizing within buttons */
  .tip-creator-button .clickable-icon,
  .pip-button .clickable-icon {
    width: 20px;
    height: 20px;
  }
</style>
