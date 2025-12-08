<!--
  frontend/packages/ui/src/components/embeds/videos/VideoEmbedFullscreen.svelte
  
  Fullscreen view for Video URL embeds (YouTube, etc.).
  Uses UnifiedEmbedFullscreen as base and provides video-specific content.
  
  Shows:
  - Video thumbnail preview image (780px max width)
  - "Open on YouTube" button
  - Video title and metadata
  - Basic infos bar at the bottom
-->

<script lang="ts">
  import { onDestroy, tick } from 'svelte';
  import { get } from 'svelte/store';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import VideoIframe from './VideoIframe.svelte';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  
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
    /** Optional: Flag to auto-play video (for restoration from PiP) */
    restoreFromPip?: boolean;
    /** Optional: Existing iframe element (for restoration from PiP) */
    iframeElement?: HTMLIFrameElement | null;
    /** Optional: Existing iframe wrapper element (for restoration from PiP) */
    iframeWrapperElement?: HTMLDivElement | null;
  }
  
  let {
    url,
    title,
    onClose,
    videoId: propVideoId,
    restoreFromPip = false,
    iframeElement: existingIframeElement,
    iframeWrapperElement: existingIframeWrapper
  }: Props = $props();
  
  // Extract video ID and thumbnail for YouTube URLs
  // Use propVideoId if provided (from PiP restoration), otherwise extract from URL
  let videoId = $state(propVideoId || '');
  let thumbnailUrl = $derived('');
  let displayTitle = $derived(title || 'YouTube Video');
  let hostname = $derived('');
  
  // State to track whether video should be shown in iframe
  // Only set to true when user clicks play button - iframe loads lazily
  // If restoring from PiP, auto-show the video (iframe already exists and is playing)
  let showVideo = $state(restoreFromPip || !!existingIframeElement);
  
  // Reference to the VideoIframe component instance
  let videoIframeComponent: VideoIframe | null = $state(null);
  
  // Generate YouTube embed URL with privacy settings
  // Uses youtube-nocookie.com (privacy-enhanced mode) to minimize cookie tracking
  // Now works with strict-origin-when-cross-origin referrer policy (fixes Error 153)
  // Only generated when showVideo is true to avoid loading until needed
  let embedUrl = $derived(
    showVideo && videoId
      ? // Use privacy-enhanced mode (youtube-nocookie.com) to minimize cookie tracking
        // This prevents YouTube from setting cookies unless user interacts with video
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
  
  // Process URL to extract video information
  $effect(() => {
    if (url) {
      try {
        const urlObj = new URL(url);
        hostname = urlObj.hostname;
        
        // If videoId was provided as prop (from PiP restoration), use it
        // Otherwise, extract from URL
        if (propVideoId) {
          // Use provided videoId and generate thumbnail
          videoId = propVideoId;
          thumbnailUrl = `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg`;
        } else {
          // YouTube URL patterns - extract video ID from URL
          const youtubeMatch = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([^&\n?#]+)/);
          if (youtubeMatch) {
            videoId = youtubeMatch[1];
            thumbnailUrl = `https://img.youtube.com/vi/${videoId}/maxresdefault.jpg`;
            if (!title) {
              displayTitle = 'YouTube Video';
            }
          }
        }
      } catch (e) {
        console.debug('[VideoEmbedFullscreen] Error parsing URL:', e);
        hostname = url;
      }
    }
  });
  
  // Auto-show video if restoring from PiP
  $effect(() => {
    if (restoreFromPip && videoId && !showVideo) {
      console.debug('[VideoEmbedFullscreen] Restoring from PiP, auto-showing video');
      showVideo = true;
    }
  });
  
  // Handle opening video on YouTube
  function handleOpenOnYouTube() {
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
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
      navigateToSettings('shared/tip', $text('settings.tip.tip_creator.text', { default: 'Tip Creator' }), 'tip', 'settings.tip.tip_creator.text');
      
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
  
  // Handle share - opens share menu (placeholder for now)
  function handleShare() {
    // TODO: Implement share functionality for video embeds
    console.debug('[VideoEmbedFullscreen] Share action (not yet implemented)');
  }
  
  // Handle play button click - loads video in iframe
  // This is the only way the iframe gets loaded - lazy loading for privacy
  function handlePlayClick() {
    console.debug('[VideoEmbedFullscreen] Play button clicked, loading video');
    showVideo = true;
  }
  
  // Flag to track if we're entering PiP (prevents cleanup)
  // Store this in a way that persists across component lifecycle
  let enteringPip = $state(false);
  
  // Handle entering picture-in-picture mode
  // Moves the VideoIframe component to PiP container without recreating it
  async function handleEnterPip() {
    if (!showVideo || !videoId || !embedUrl || !videoIframeComponent) {
      console.warn('[VideoEmbedFullscreen] Cannot enter PiP: video not loaded or iframe component missing');
      return;
    }
    
    try {
      // Set flag to prevent cleanup BEFORE storing in PiP store
      enteringPip = true;
      
      // Get iframe references from the VideoIframe component
      const { iframeElement, iframeWrapperElement } = videoIframeComponent.getIframeRefs();
      
      if (!iframeElement || !iframeWrapperElement) {
        console.warn('[VideoEmbedFullscreen] Cannot enter PiP: iframe refs not available');
        enteringPip = false;
        return;
      }
      
      // Import video PiP store
      const { videoPipStore } = await import('../../../stores/videoPipStore');
      
      // Store video state and iframe reference in PiP store
      // The iframe will be moved (not recreated) to maintain video playback
      videoPipStore.enterPip({
        url,
        title: displayTitle,
        videoId,
        embedUrl,
        iframeElement: iframeElement, // Store reference to move the actual iframe
        iframeWrapperElement: iframeWrapperElement // Store wrapper for positioning
      });
      
      console.debug('[VideoEmbedFullscreen] Entered PiP mode, storing iframe reference in PiP store');
      
      // Wait for store update to propagate and ActiveChat's effect to move the iframe
      await tick();
      await new Promise(resolve => setTimeout(resolve, 50));
      
      // Verify iframe has been moved before closing
      if (iframeWrapperElement && iframeWrapperElement.parentNode) {
        const parent = iframeWrapperElement.parentNode as HTMLElement;
        if (parent.classList.contains('video-pip-container')) {
          console.debug('[VideoEmbedFullscreen] Iframe confirmed moved to PiP container, closing fullscreen');
        } else {
          console.warn('[VideoEmbedFullscreen] Iframe not yet moved to PiP container, but proceeding with close');
        }
      }
      
      // Close fullscreen - the VideoIframe component will persist in PiP
      onClose();
    } catch (error) {
      console.error('[VideoEmbedFullscreen] Error entering PiP mode:', error);
      enteringPip = false; // Reset flag on error
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to enter picture-in-picture mode');
    }
  }
  
  // Clean up when fullscreen closes
  // Note: VideoIframe component handles its own cleanup, so we just reset state
  // If in PiP mode, the VideoIframe will persist in the PiP container
  async function cleanupYouTubeData() {
    // Check if we're entering PiP mode by checking the store
    try {
      const { videoPipStore } = await import('../../../stores/videoPipStore');
      const pipState = get(videoPipStore) as { isActive: boolean; iframeElement?: HTMLIFrameElement | null };
      if (pipState.isActive && videoIframeComponent) {
        const { iframeElement } = videoIframeComponent.getIframeRefs();
        if (pipState.iframeElement === iframeElement) {
          console.debug('[VideoEmbedFullscreen] Skipping cleanup - iframe is in PiP mode');
          return;
        }
      }
    } catch (e) {
      console.debug('[VideoEmbedFullscreen] Could not check PiP store:', e);
    }
    
    // Skip cleanup if we're entering PiP mode (local flag check)
    if (enteringPip) {
      console.debug('[VideoEmbedFullscreen] Skipping cleanup - entering PiP mode');
      enteringPip = false; // Reset flag
      return;
    }
    
    console.debug('[VideoEmbedFullscreen] Cleaning up - VideoIframe component will handle iframe cleanup');
    
    // Reset video state - VideoIframe component will be destroyed and clean up iframe
    showVideo = false;
  }
  
  // Wrapper for onClose that cleans up before closing
  // This is called when user explicitly closes (not when entering PiP)
  function handleClose() {
    cleanupYouTubeData();
    onClose();
  }
  
  // Cleanup on component destroy - ensures iframe is removed even if component
  // is destroyed without explicit close (e.g., navigation away)
  // BUT skip if iframe is in PiP mode
  onDestroy(async () => {
    console.debug('[VideoEmbedFullscreen] Component destroying, checking if cleanup needed');
    await cleanupYouTubeData();
  });
</script>

<UnifiedEmbedFullscreen
  appId="videos"
  skillId="video"
  title=""
  onClose={handleClose}
  onCopy={handleCopy}
  onShare={handleShare}
  skillIconName="video"
  status="finished"
  skillName={displayTitle}
  showSkillIcon={false}
  showStatus={false}
>
  {#snippet content()}
    <div class="video-container">
      <!-- Video iframe or thumbnail preview (780px max width) -->
      <!-- Iframe is only loaded when user clicks play button (showVideo = true) -->
      {#if showVideo && videoId && embedUrl}
        <!-- Video iframe component - separate from fullscreen view -->
        <!-- This allows the iframe to persist when fullscreen closes (e.g., in PiP mode) -->
        <!-- When restoring from PiP, pass existing iframe elements to reuse them -->
        <div class="video-iframe-container">
          <VideoIframe
            bind:this={videoIframeComponent}
            videoId={videoId}
            title={displayTitle}
            embedUrl={embedUrl}
            isPip={false}
            existingIframeElement={existingIframeElement}
            existingIframeWrapper={existingIframeWrapper}
          />
        </div>
      {:else if videoId && thumbnailUrl}
        <!-- Thumbnail with play button overlay -->
        <div class="video-thumbnail-wrapper">
          <img 
            src={thumbnailUrl} 
            alt={displayTitle}
            class="video-thumbnail"
            loading="lazy"
            onerror={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
          <!-- Play button overlay -->
          <button
            class="play-button-overlay"
            onclick={handlePlayClick}
            aria-label="Play video"
            type="button"
          >
            <span class="play-icon"></span>
          </button>
        </div>
      {:else}
        <!-- Fallback: show URL hostname if no thumbnail -->
        <div class="video-fallback">
          <div class="video-hostname">{hostname || url}</div>
        </div>
      {/if}
      
      <!-- Open on YouTube, PiP, and Tip buttons -->
      {#if url}
        <div class="button-container">
          <a 
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            class="open-on-youtube-button"
          >
            {$text('embeds.open_on_youtube.text') || 'Open on YouTube'}
          </a>
          <!-- Picture-in-Picture button - only shown when video is playing -->
          {#if showVideo && videoId && embedUrl}
            <button
              class="pip-button"
              onclick={handleEnterPip}
              type="button"
              aria-label="Enter picture-in-picture mode"
            >
              <span class="pip-icon"></span>
              <span class="pip-text">PiP</span>
            </button>
          {/if}
          <button
            class="tip-creator-button"
            onclick={handleTipCreator}
            type="button"
          >
            {$text('embeds.tip_creator.text') || 'Tip Creator'}
          </button>
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
    gap: 24px;
    width: 100%;
    margin-top: 80px;
  }
  
  /* Video thumbnail wrapper - 780px max width, centered */
  .video-thumbnail-wrapper {
    width: 100%;
    max-width: 780px;
    display: flex;
    justify-content: center;
    border-radius: 16px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    position: relative;
  }
  
  .video-thumbnail {
    width: 100%;
    height: auto;
    display: block;
    object-fit: contain;
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
  
  /* Video iframe container - 780px max width, centered */
  .video-iframe-container {
    width: 100%;
    max-width: 780px;
    display: flex;
    justify-content: center;
  }
  
  /* Fallback container for when no thumbnail is available */
  .video-fallback {
    width: 100%;
    max-width: 780px;
    display: flex;
    justify-content: center;
    padding: 40px;
  }
  
  .video-hostname {
    font-size: 16px;
    color: var(--color-grey-70);
    text-align: center;
  }
  
  /* Button container - centered */
  .button-container {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    width: 100%;
    max-width: 780px;
  }
  
  /* Open on YouTube button - styled as button but is an <a> link */
  .open-on-youtube-button {
    margin-top: -60px;
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
    margin-right: 10px;
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
  
  /* Tip creator button - styled similarly to Open on YouTube button */
  .tip-creator-button {
    margin-top: -60px;
    background-color: var(--color-button-secondary, var(--color-grey-20));
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
    color: var(--color-font-button, var(--color-grey-100));
    font-family: var(--button-font-family);
    font-size: var(--button-font-size);
    font-weight: var(--button-font-weight);
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
  
  /* Picture-in-Picture button - styled similarly to other buttons */
  .pip-button {
    margin-top: -60px;
    background-color: var(--color-button-secondary, var(--color-grey-20));
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
    gap: 8px;
    color: var(--color-font-button, var(--color-grey-100));
    font-family: var(--button-font-family);
    font-size: var(--button-font-size);
    font-weight: var(--button-font-weight);
    margin-right: 10px;
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
  
  /* PiP icon - using a simple picture-in-picture icon style */
  .pip-icon {
    width: 20px;
    height: 20px;
    display: block;
    position: relative;
  }
  
  .pip-icon::before,
  .pip-icon::after {
    content: '';
    position: absolute;
    border: 2px solid currentColor;
    border-radius: 2px;
  }
  
  .pip-icon::before {
    /* Main video frame */
    width: 16px;
    height: 12px;
    top: 0;
    left: 0;
  }
  
  .pip-icon::after {
    /* Small PiP frame */
    width: 8px;
    height: 6px;
    bottom: 0;
    right: 0;
    border-width: 1.5px;
  }
  
  .pip-text {
    font-size: var(--button-font-size);
  }
</style>
