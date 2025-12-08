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
  import { onDestroy } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
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
  
  // Reference to the iframe element for cleanup
  // If restoring from PiP, reuse the existing iframe element
  let iframeElement: HTMLIFrameElement | null = $state(existingIframeElement || null);
  
  // Reference to the iframe wrapper for moving the iframe
  // If restoring from PiP, reuse the existing wrapper element
  // This will be bound to the DOM element in the template
  let iframeWrapperElementRef: HTMLDivElement | null = $state(existingIframeWrapper || null);
  
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
  let enteringPip = $state(false);
  
  // Handle entering picture-in-picture mode
  // Moves the existing iframe to PiP container without recreating it
  async function handleEnterPip() {
    // Use the ref if it exists, otherwise use existingIframeWrapper
    const wrapperElement = iframeWrapperElementRef || existingIframeWrapper;
    
    if (!showVideo || !videoId || !embedUrl || !iframeElement || !wrapperElement) {
      console.warn('[VideoEmbedFullscreen] Cannot enter PiP: video not loaded or iframe missing');
      return;
    }
    
    try {
      // Set flag to prevent cleanup
      enteringPip = true;
      
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
        iframeWrapperElement: wrapperElement // Store wrapper for positioning
      });
      
      console.debug('[VideoEmbedFullscreen] Entered PiP mode, moving iframe to PiP container');
      
      // Close fullscreen (cleanup will be skipped due to enteringPip flag)
      // The iframe will be moved to PiP container in ActiveChat
      onClose();
    } catch (error) {
      console.error('[VideoEmbedFullscreen] Error entering PiP mode:', error);
      enteringPip = false; // Reset flag on error
      const { notificationStore } = await import('../../../stores/notificationStore');
      notificationStore.error('Failed to enter picture-in-picture mode');
    }
  }
  
  // Clean up YouTube iframe and all related data when fullscreen closes
  // This ensures no YouTube scripts or data persist after closing
  // Note: This is NOT called when entering PiP mode (PiP handles the iframe)
  function cleanupYouTubeData() {
    // Skip cleanup if we're entering PiP mode
    if (enteringPip) {
      console.debug('[VideoEmbedFullscreen] Skipping cleanup - entering PiP mode');
      enteringPip = false; // Reset flag
      return;
    }
    
    console.debug('[VideoEmbedFullscreen] Cleaning up YouTube iframe and data');
    
    // Unload iframe by removing src - this stops all YouTube scripts and connections
    if (iframeElement) {
      // Clear the src first to stop any ongoing requests
      iframeElement.src = '';
      // Remove the iframe from DOM to completely disconnect it
      iframeElement.remove();
      iframeElement = null;
    }
    
    // Reset video state - this removes the iframe from DOM
    showVideo = false;
    
    // Note about cookies:
    // - Third-party cookies (from youtube.com) cannot be deleted from JavaScript
    //   due to browser security restrictions (cross-origin policy)
    // - Using youtube-nocookie.com (privacy-enhanced mode) minimizes cookie usage
    // - Cookies are isolated to YouTube's domain and cannot access our site's data
    // - Removing the iframe stops all active connections and prevents further tracking
    // - Users can clear cookies manually via browser settings if desired
    console.debug('[VideoEmbedFullscreen] Iframe removed. Note: Third-party YouTube cookies cannot be cleared from JavaScript due to browser security restrictions.');
  }
  
  // Wrapper for onClose that cleans up before closing
  // This is called when user explicitly closes (not when entering PiP)
  function handleClose() {
    cleanupYouTubeData();
    onClose();
  }
  
  // Cleanup on component destroy - ensures iframe is removed even if component
  // is destroyed without explicit close (e.g., navigation away)
  onDestroy(() => {
    console.debug('[VideoEmbedFullscreen] Component destroying, cleaning up YouTube data');
    cleanupYouTubeData();
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
        <!-- Video iframe with maximum security settings -->
        <!-- Iframe is unloaded when fullscreen closes to remove all YouTube data -->
        <!-- Uses privacy-enhanced mode (youtube-nocookie.com) to minimize cookie tracking -->
        <!-- Error 153 is fixed by using strict-origin-when-cross-origin referrer policy -->
        <!-- YouTube requires referrer info to verify embedding context, but we still maintain privacy -->
        <!-- Privacy-enhanced mode prevents cookies unless user interacts with video -->
        <!-- Iframe wrapper - will be moved to PiP container when entering PiP -->
        {#if !existingIframeWrapper}
          <!-- Create new wrapper if not restoring from PiP -->
          <div class="video-iframe-wrapper" bind:this={iframeWrapperElementRef}>
            <iframe
              bind:this={iframeElement}
              src={embedUrl}
              title={displayTitle}
              class="video-iframe"
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              allowfullscreen
              referrerpolicy="strict-origin-when-cross-origin"
              loading="eager"
              frameborder="0"
            ></iframe>
          </div>
        {:else}
          <!-- Reuse existing wrapper when restoring from PiP -->
          <!-- The wrapper is already in the DOM, just needs to be styled correctly -->
          <div class="video-iframe-wrapper" bind:this={iframeWrapperElementRef}>
            <!-- iframe is already inside, just ensure wrapper has correct styles -->
          </div>
        {/if}
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
  
  /* Video iframe wrapper - 780px max width, centered, 16:9 aspect ratio */
  .video-iframe-wrapper {
    width: 100%;
    max-width: 780px;
    position: relative;
    padding-bottom: 56.25%; /* 16:9 aspect ratio */
    height: 0;
    border-radius: 16px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }
  
  .video-iframe {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    border: none;
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
