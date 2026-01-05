<!--
  frontend/packages/ui/src/components/embeds/ChildEmbedOverlay.svelte
  
  Reusable overlay container for child embed fullscreens.
  Used by parent fullscreens (WebSearch, VideosSearch, NewsSearch) to show
  child embed details on top of the parent without destroying/recreating the parent.
  
  Benefits of overlay pattern:
  - No re-animation when returning to parent (parent stays rendered beneath)
  - No re-loading of child embeds (parent keeps its state)
  - Scroll position preserved on parent
  - Instant close transition since parent is always visible
  
  Usage:
  ```svelte
  {#if selectedChild}
    <ChildEmbedOverlay>
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
  import type { Snippet } from 'svelte';
  
  /**
   * Props for the overlay container
   */
  interface Props {
    /** Child content to render in the overlay (typically a fullscreen component) */
    children: Snippet;
  }
  
  let { children }: Props = $props();
</script>

<!-- 
  Overlay container positioned absolutely on top of parent fullscreen
  z-index 101 is above UnifiedEmbedFullscreen's z-index 100
-->
<div class="child-embed-overlay">
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
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    /* Higher z-index than UnifiedEmbedFullscreen (which uses z-index: 100) */
    z-index: 101;
    /* Prevent scroll-through to parent content beneath */
    overflow: hidden;
  }
</style>

