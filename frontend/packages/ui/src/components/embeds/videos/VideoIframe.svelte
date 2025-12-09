<!--
  frontend/packages/ui/src/components/embeds/videos/VideoIframe.svelte
  
  Standalone video iframe component that lives in ActiveChat.
  
  Architecture:
  - This component is wrapped by .video-iframe-fullscreen-container in ActiveChat
  - The parent container handles positioning (centered vs top-right for PiP)
  - This component handles the 16:9 aspect ratio and visual styling
  - Using position: absolute (in parent) ensures PiP moves with ActiveChat when settings open
  
  This component:
  1. Contains ONLY the iframe and an overlay (no thumbnail/play button - those are in VideoEmbedFullscreen)
  2. Auto-plays the video when mounted (user already clicked play in VideoEmbedFullscreen)
  3. Uses CSS classes for styling differences between fullscreen and PiP mode
  4. The overlay is activated in PiP mode to catch clicks and restore fullscreen
  
  The iframe is NEVER destroyed or reloaded during PiP transitions - only CSS changes.
  This ensures smooth, iOS-like picture-in-picture behavior.
-->

<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { videoIframeStore } from '../../../stores/videoIframeStore';
  
  /**
   * Props for video iframe
   */
  interface Props {
    /** Video ID (e.g., YouTube video ID) */
    videoId: string;
    /** Video title */
    title: string;
    /** Embed URL for the iframe (video will auto-play) */
    embedUrl: string;
    /** Whether the iframe is in PiP mode (controlled by parent via store) */
    isPipMode?: boolean;
    /** Callback when overlay is clicked in PiP mode (to restore fullscreen) */
    onPipOverlayClick?: () => void;
  }
  
  let {
    videoId,
    title,
    embedUrl,
    isPipMode = false,
    onPipOverlayClick
  }: Props = $props();
  
  // Reference to the iframe element
  let iframeElement: HTMLIFrameElement | null = $state(null);
  
  // Reference to the iframe wrapper element
  let iframeWrapperElement: HTMLDivElement | null = $state(null);
  
  // Debug: Log when component renders and when props change
  $effect(() => {
    console.debug('[VideoIframe] Component state:', {
      videoId,
      embedUrl,
      isPipMode,
      hasIframe: !!iframeElement,
      hasWrapper: !!iframeWrapperElement
    });
  });
  
  // Update store with iframe references when they become available
  // This allows other components to verify the iframe hasn't been recreated
  $effect(() => {
    if (iframeElement && iframeWrapperElement) {
      videoIframeStore.updateIframeRefs(iframeElement, iframeWrapperElement);
      console.debug('[VideoIframe] Updated store with iframe references');
    }
  });
  
  // Handle click on PiP overlay to restore fullscreen
  function handleOverlayClick(event: MouseEvent | KeyboardEvent) {
    event.preventDefault();
    event.stopPropagation();
    
    console.debug('[VideoIframe] PiP overlay clicked, requesting fullscreen restore');
    
    // Call the provided callback to restore fullscreen
    if (onPipOverlayClick) {
      onPipOverlayClick();
    } else {
      // Fallback: dispatch custom event for ActiveChat to handle
      const customEvent = new CustomEvent('videopip-restore-fullscreen', {
        detail: { videoId, title, embedUrl },
        bubbles: true
      });
      document.dispatchEvent(customEvent);
    }
  }
  
  // Cleanup on destroy - only clear refs, don't manipulate iframe
  onDestroy(() => {
    console.debug('[VideoIframe] Component destroying, clearing refs');
    // Don't clear the iframe src - let it stay for potential restoration
    // Just clear our references
    iframeElement = null;
    iframeWrapperElement = null;
  });
</script>

<!-- 
  The wrapper div contains the iframe and overlay.
  CSS classes control the position/size for fullscreen vs PiP mode.
  The isPipMode class triggers the CSS transition to top-right corner.
-->
<div 
  class="video-iframe-wrapper"
  class:pip-mode={isPipMode}
  bind:this={iframeWrapperElement}
>
  <!-- 
    The iframe element - loads and plays the video.
    CRITICAL: This iframe is never destroyed or recreated during PiP transitions.
    Only the wrapper's CSS changes to animate position/size.
  -->
  <iframe
    bind:this={iframeElement}
    src={embedUrl}
    title={title}
    class="video-iframe"
    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
    allowfullscreen
    referrerpolicy="strict-origin-when-cross-origin"
    loading="eager"
    frameborder="0"
  ></iframe>
  
  <!-- 
    Invisible overlay that covers the iframe in PiP mode.
    When clicked, it restores the fullscreen view.
    Only active (pointer-events: auto) in PiP mode.
  -->
  <div 
    class="pip-overlay"
    class:active={isPipMode}
    onclick={handleOverlayClick}
    onkeydown={(e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleOverlayClick(e);
      }
    }}
    role="button"
    tabindex={isPipMode ? 0 : -1}
    aria-label="Click to restore fullscreen video"
    title={isPipMode ? "Click to restore fullscreen" : ""}
  ></div>
</div>

<style>
  /*
   * Video iframe wrapper - contains the iframe and overlay.
   * 
   * The parent container (.video-iframe-fullscreen-container in ActiveChat)
   * handles the positioning for fullscreen vs PiP mode.
   * 
   * This wrapper just maintains the 16:9 aspect ratio and styles.
   */
  .video-iframe-wrapper {
    /* Relative positioning - parent container handles absolute positioning */
    position: relative;
    width: 100%;
    
    /* 16:9 aspect ratio using padding-bottom trick */
    padding-bottom: 56.25%;
    height: 0;
    
    /* Visual styling */
    border-radius: 16px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    
    /* Smooth transition for visual properties */
    transition: 
      border-radius 0.5s cubic-bezier(0.4, 0, 0.2, 1),
      box-shadow 0.5s cubic-bezier(0.4, 0, 0.2, 1),
      transform 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    
    /* Ensure wrapper is always visible */
    display: block;
    visibility: visible;
  }
  
  /*
   * PiP mode styles - different aspect ratio and visual adjustments.
   * Position is handled by parent container, this just handles the content sizing.
   */
  .video-iframe-wrapper.pip-mode {
    /* In PiP mode, use fixed height instead of aspect ratio padding */
    /* because parent container controls the size */
    padding-bottom: 0;
    height: 180px;
    
    /* PiP visual style */
    border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  }
  
  /* Hover effect for PiP mode */
  .video-iframe-wrapper.pip-mode:hover {
    transform: scale(1.05);
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.4);
  }
  
  /*
   * The iframe element - fills the wrapper and plays the video.
   */
  .video-iframe {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    border: none;
    display: block;
    visibility: visible;
  }
  
  /*
   * PiP overlay - invisible div that covers the iframe in PiP mode.
   * Catches clicks to restore fullscreen view.
   * 
   * Inactive by default (pointer-events: none).
   * Active when .active class is added (PiP mode).
   */
  .pip-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: transparent;
    z-index: 100; /* Above iframe */
    cursor: default;
    
    /* Inactive by default - clicks pass through to iframe */
    pointer-events: none;
    opacity: 0;
  }
  
  /*
   * Active overlay - catches clicks in PiP mode.
   */
  .pip-overlay.active {
    pointer-events: auto;
    cursor: pointer;
    opacity: 1;
  }
  
  /* Responsive adjustments for small screens */
  @media (max-width: 480px) {
    .video-iframe-wrapper.pip-mode {
      height: 135px;
    }
  }
</style>
