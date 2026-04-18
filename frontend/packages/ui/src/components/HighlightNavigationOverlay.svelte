<!--
  HighlightNavigationOverlay.svelte

  Floating up/down buttons anchored to the currently focused highlight.
  Visible only when: overlayVisible === true AND there is more than one
  highlight in the chat. Parent (ActiveChat) owns the anchoring — it computes
  the DOMRect of the currently-focused highlight and passes it here.
-->
<script lang="ts">
  import { onMount, tick } from 'svelte';
  import {
    highlightNavigationStore,
    hasMultipleHighlights,
    jumpPrev,
    jumpNext,
    hideOverlay,
  } from '../stores/highlightNavigationStore';

  interface Props {
    /** DOMRect of the currently-focused highlight. Parent recomputes on
     *  jumpRequestId change and passes the fresh rect. */
    anchorRect: DOMRect | null;
  }

  let { anchorRect }: Props = $props();

  let top = $state(0);
  let left = $state(0);

  async function recompute() {
    await tick();
    if (!anchorRect) return;
    const vw = window.innerWidth;
    left = Math.min(vw - 60, anchorRect.right + 12);
    top = anchorRect.top + anchorRect.height / 2;
  }

  $effect(() => {
    // Re-run whenever anchorRect changes identity (parent hands a fresh one).
    void anchorRect;
    recompute();
  });

  onMount(() => {
    function onResize() { recompute(); }
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onResize, true);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onResize, true);
    };
  });

  let visible = $derived(
    $highlightNavigationStore.overlayVisible && $hasMultipleHighlights && !!anchorRect,
  );
</script>

{#if visible}
  <div
    class="highlight-nav-overlay"
    style="--nav-left: {left}px; --nav-top: {top}px;"
    data-testid="highlight-navigation-overlay"
  >
    <button
      type="button"
      class="nav-btn"
      data-testid="highlight-nav-prev"
      onclick={jumpPrev}
      aria-label="Previous highlight"
    >▲</button>
    <button
      type="button"
      class="nav-btn"
      data-testid="highlight-nav-next"
      onclick={jumpNext}
      aria-label="Next highlight"
    >▼</button>
    <button
      type="button"
      class="nav-btn nav-btn-close"
      data-testid="highlight-nav-close"
      onclick={hideOverlay}
      aria-label="Close highlight navigation"
    >×</button>
  </div>
{/if}

<style>
  .highlight-nav-overlay {
    position: fixed;
    left: var(--nav-left);
    top: var(--nav-top);
    transform: translateY(-50%);
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-5);
    box-shadow: var(--shadow-md);
    padding: 4px;
    z-index: var(--z-index-popover);
  }
  .nav-btn {
    all: unset;
    width: 32px;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    border-radius: var(--radius-3);
    font-size: 14px;
    color: var(--color-grey-100);
    background: var(--color-highlight-yellow, rgba(255, 213, 0, 0.4));
  }
  .nav-btn:hover { background: var(--color-highlight-yellow-solid, #ffd500); }
  .nav-btn-close {
    background: var(--color-grey-20);
    font-size: 18px;
  }
  .nav-btn-close:hover { background: var(--color-grey-30); }
</style>
