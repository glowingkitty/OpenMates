<!--
  frontend/packages/ui/src/components/embeds/videos/VideoIframe.svelte
  
  Standalone video iframe component that can exist independently of fullscreen view.
  This allows the iframe to persist when fullscreen closes (e.g., in PiP mode).
  
  The iframe is managed by the video PiP store and can be moved between containers
  without being destroyed or reloaded.
-->

<script lang="ts">
  import { onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import { videoPipStore } from '../../../stores/videoPipStore';
  
  /**
   * Props for video iframe
   */
  interface Props {
    /** Video ID (e.g., YouTube video ID) */
    videoId: string;
    /** Video title */
    title: string;
    /** Embed URL for the iframe */
    embedUrl: string;
    /** Whether this iframe is in PiP mode */
    isPip?: boolean;
    /** Optional: Existing iframe element (for restoration from PiP) */
    existingIframeElement?: HTMLIFrameElement | null;
    /** Optional: Existing iframe wrapper element (for restoration from PiP) */
    existingIframeWrapper?: HTMLDivElement | null;
  }
  
  let {
    videoId,
    title,
    embedUrl,
    isPip = false,
    existingIframeElement,
    existingIframeWrapper
  }: Props = $props();
  
  // Reference to the iframe element
  // If restoring from PiP, reuse existing iframe
  let iframeElement: HTMLIFrameElement | null = $state(existingIframeElement || null);
  
  // Reference to the iframe wrapper
  // If restoring from PiP, reuse existing wrapper
  let iframeWrapperElement: HTMLDivElement | null = $state(existingIframeWrapper || null);
  
  // If existing elements are provided (restoration from PiP), use them
  $effect(() => {
    if (existingIframeWrapper && !iframeWrapperElement) {
      iframeWrapperElement = existingIframeWrapper;
      console.debug('[VideoIframe] Reusing existing iframe wrapper from PiP');
    }
    if (existingIframeElement && !iframeElement) {
      iframeElement = existingIframeElement;
      console.debug('[VideoIframe] Reusing existing iframe element from PiP');
    }
  });
  
  // Register this iframe with the PiP store when it mounts
  $effect(() => {
    if (iframeElement && iframeWrapperElement && !isPip) {
      // Store iframe reference for potential PiP mode
      // The store will use this when entering PiP
      console.debug('[VideoIframe] Iframe mounted, ready for PiP');
    }
  });
  
  // Cleanup on destroy - but only if not in PiP mode or moved to PiP
  onDestroy(() => {
    // Check if iframe wrapper has been moved to PiP container
    if (iframeWrapperElement && iframeWrapperElement.parentNode) {
      const parent = iframeWrapperElement.parentNode as HTMLElement;
      if (parent.classList.contains('video-pip-container')) {
        console.debug('[VideoIframe] Skipping cleanup - iframe wrapper has been moved to PiP container');
        return;
      }
    }
    
    // Check PiP store
    try {
      const pipState = get(videoPipStore);
      if (pipState.isActive && pipState.iframeElement === iframeElement) {
        console.debug('[VideoIframe] Skipping cleanup - iframe is in PiP mode (store check)');
        return;
      }
    } catch (e) {
      // Store not available, continue
    }
    
    // Only cleanup if not in PiP mode
    if (!isPip && iframeElement) {
      console.debug('[VideoIframe] Cleaning up iframe');
      iframeElement.src = '';
      iframeElement.remove();
    } else {
      console.debug('[VideoIframe] Skipping cleanup - iframe is in PiP mode');
    }
  });
  
  // Expose iframe references for PiP store
  // These will be accessed by VideoEmbedFullscreen when entering PiP
  export function getIframeRefs() {
    return {
      iframeElement,
      iframeWrapperElement
    };
  }
</script>

{#if existingIframeWrapper}
  <!-- Reuse existing wrapper from PiP restoration -->
  <!-- The wrapper is already in the DOM at the correct location -->
  <!-- We don't render anything here - the wrapper already exists -->
  <!-- The $effect above will set our references -->
{:else}
  <!-- Create new wrapper and iframe -->
  <div class="video-iframe-wrapper" bind:this={iframeWrapperElement}>
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
  </div>
{/if}

<style>
  .video-iframe-wrapper {
    width: 100%;
    max-width: 780px; /* Match fullscreen max width */
    position: relative;
    padding-bottom: 56.25%; /* 16:9 aspect ratio */
    height: 0;
    border-radius: 16px;
    overflow: hidden;
    background-color: var(--color-grey-15);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  }
  
  /* When in PiP mode, override styles for smaller container */
  :global(.video-pip-container) .video-iframe-wrapper {
    max-width: 100%;
    border-radius: 0;
    box-shadow: none;
  }
  
  .video-iframe {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    border: none;
  }
</style>
