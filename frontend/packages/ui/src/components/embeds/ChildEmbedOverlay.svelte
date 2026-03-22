<!--
  frontend/packages/ui/src/components/embeds/ChildEmbedOverlay.svelte
  
  Reusable overlay container for child embed fullscreens.
  Used by parent fullscreens (WebSearch, VideosSearch, NewsSearch) to show
  child embed details on top of the parent without destroying/recreating the parent.
  
  Benefits of overlay pattern:
  - No re-animation when returning to parent (parent stays rendered beneath)
  - No re-loading of child embeds (parent keeps its state)
  - Scroll position preserved on parent
  - Smooth close animation: child animates BEFORE being unmounted
  
  Closing Animation:
  - Parent passes onRequestClose which triggers isClosing state
  - Overlay waits for animation duration (300ms) before calling actual close
  - This allows the child's scale-down animation to play fully
  
  Usage:
  ```svelte
  {#if selectedChild}
    <ChildEmbedOverlay onRequestClose={handleChildClose}>
      <WebsiteEmbedFullscreen
        url={selectedChild.url}
        onClose={handleChildClose}
        ...
      />
    </ChildEmbedOverlay>
  {/if}
  ```
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import type { Snippet } from 'svelte';
  
  /**
   * Props for the overlay container
   */
  interface Props {
    /** Child content to render in the overlay (typically a fullscreen component) */
    children: Snippet;
  }
  
  let { children }: Props = $props();
  
  // Track animation state for opening
  let isAnimatingIn = $state(false);
  
  onMount(() => {
    // Trigger opening animation after mount
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        isAnimatingIn = true;
      });
    });
  });
</script>

<!-- 
  Overlay container positioned absolutely on top of parent fullscreen
  z-index 101 is above UnifiedEmbedFullscreen's z-index 100
  
  The inner content (child fullscreen) handles its own close animation
  via its handleClose function which uses overlayRef
-->
<div class="child-embed-overlay" class:animating-in={isAnimatingIn}>
  {@render children()}
</div>

<style>
  /* ===========================================
     Child Embed Overlay Container
     Positioned on top of parent fullscreen for smooth transitions
     =========================================== */
  
  .child-embed-overlay {
    /* Absolute positioning to overlay on top of parent fullscreen */
    position: absolute;
    /* Match the parent's margin to align properly */
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    /* Higher z-index than UnifiedEmbedFullscreen (which uses z-index: 100) */
    z-index: 101;
    /* Prevent scroll-through to parent content beneath */
    overflow: hidden;
    /* Fade-in animation for the overlay container */
    opacity: 0;
    transition: opacity 200ms ease-out;
  }
  
  .child-embed-overlay.animating-in {
    opacity: 1;
  }
</style>

