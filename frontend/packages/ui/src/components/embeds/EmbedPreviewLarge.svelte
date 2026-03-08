<script module lang="ts">
  // Module-level state shared across ALL instances of EmbedPreviewLarge.
  // Each carousel "run" (consecutive large embeds) shares a single writable
  // store keyed by the first card's embedRef (runRef). This MUST be module-level
  // so that all instances in the same run read/write the same store.
  import { writable } from 'svelte/store';

  const carouselStateMap = new Map<string, ReturnType<typeof writable<number>>>();

  function getCarouselStore(key: string) {
    if (!carouselStateMap.has(key)) {
      carouselStateMap.set(key, writable(0));
    }
    return carouselStateMap.get(key)!;
  }
</script>

<script lang="ts">
  // frontend/packages/ui/src/components/embeds/EmbedPreviewLarge.svelte
  //
  // Purpose: Render [!](embed:ref) and [](embed:ref) as visually highlighted
  // embed preview blocks. Uses EmbedReferencePreview to delegate to the standard
  // renderer pipeline — the same components used for inline skill embeds.
  //
  // Responsive behavior:
  //   - When container width ≤ 300px: compact card (300×200px standard layout)
  //   - When container width > 300px: expanded card (full-width × 350px)
  //   CSS container queries handle the switch automatically via the
  //   .embed-preview-large-container wrapper which sets container-type.
  //
  // Carousel layout (for consecutive runs of highlighted embeds):
  //   - The FIRST card (carouselIndex === 0) is always rendered as the "shell"
  //     and holds the left/right navigation arrows.
  //   - Non-first cards overlay on top using negative margin.
  //   - Only the active card is visible; others use display:none or visibility:hidden.
  //
  // Architecture: See docs/architecture/embeds.md for rendering pipeline.
  // Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts

  import { onMount } from 'svelte';
  import { getLucideIcon } from '../../utils/categoryUtils';
  import EmbedReferencePreview from './EmbedReferencePreview.svelte';
  import {
    embedStore,
    embedRefIndexVersion,
  } from '../../services/embedStore';

  const ChevronLeft = getLucideIcon('chevron-left');
  const ChevronRight = getLucideIcon('chevron-right');

  interface Props {
    embedRef: string;
    embedId?: string | null;
    appId?: string | null;
    carouselIndex: number;
    carouselTotal: number;
    /** embedRef of the first card in the run — shared carousel store key */
    runRef?: string;
  }

  let {
    embedRef,
    embedId = null,
    appId: _appId = null,
    carouselIndex,
    carouselTotal,
    runRef = '',
  }: Props = $props();

  // ── Carousel state ──────────────────────────────────────────────────────
  let runKey = $derived(
    runRef && runRef.length > 0 ? runRef : embedRef,
  );
  let carouselStore = $derived(getCarouselStore(runKey));

  let currentIndex = $state(0);
  $effect(() => {
    const unsub = carouselStore.subscribe((value) => {
      currentIndex = value;
    });
    return unsub;
  });

  let isVisible = $derived(currentIndex === carouselIndex);
  let isFirstCard = $derived(carouselIndex === 0);
  let hasMultiple = $derived(carouselTotal > 1);

  function handlePrevious(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    carouselStore.update((i) => (i - 1 + carouselTotal) % carouselTotal);
  }

  function handleNext(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    carouselStore.update((i) => (i + 1) % carouselTotal);
  }

  // ── Embed ID resolution ─────────────────────────────────────────────────
  let resolvedEmbedId = $derived.by(() => {
    void $embedRefIndexVersion;
    return embedId || embedStore.resolveByRef(embedRef) || null;
  });

  // ── Responsive layout detection via ResizeObserver ──────────────────────
  // Container queries drive the CSS, but we also need the JS-side shell
  // min-height to match. Instead of nesting container queries (which don't
  // work for self-sizing), we use a ResizeObserver to detect the actual
  // container width and set the shell min-height accordingly.
  let wrapperEl = $state<HTMLElement | null>(null);
  let isExpanded = $state(false);

  onMount(() => {
    if (!wrapperEl) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        isExpanded = entry.contentRect.width > 300;
      }
    });
    ro.observe(wrapperEl);
    return () => ro.disconnect();
  });

  let shellMinHeight = $derived(isExpanded ? 365 : 215);
</script>

{#if isFirstCard}
  <!-- First card: always-visible carousel shell -->
  <div
    bind:this={wrapperEl}
    class="embed-preview-large-wrapper"
    style="min-height: {shellMinHeight}px;"
  >
    <div class="embed-preview-large-container">
      <div
        class="embed-preview-large-content"
        class:embed-preview-large-content--hidden={!isVisible}
      >
        <EmbedReferencePreview {embedRef} embedId={resolvedEmbedId} variant="large" />
      </div>
    </div>

    {#if hasMultiple}
      <button
        class="carousel-arrow carousel-arrow-left"
        type="button"
        onclick={handlePrevious}
        aria-label="Previous"
      >
        <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
      </button>

      <button
        class="carousel-arrow carousel-arrow-right"
        type="button"
        onclick={handleNext}
        aria-label="Next"
      >
        <ChevronRight size={22} color="rgba(255,255,255,0.85)" />
      </button>
    {/if}
  </div>
{:else if hasMultiple}
  <!-- Non-first cards: absolute overlay -->
  <div
    class="embed-preview-large-wrapper embed-preview-large-overlay"
    class:embed-preview-large-overlay--hidden={!isVisible}
    style="margin-top: -{shellMinHeight}px;"
  >
    <div class="embed-preview-large-container">
      <EmbedReferencePreview {embedRef} embedId={resolvedEmbedId} variant="large" />
    </div>
  </div>
{/if}

<style>
  /* ── Shared wrapper ──────────────────────────────────────────────────────── */
  .embed-preview-large-wrapper {
    position: relative;
    width: 100%;
  }

  /* ── Container query context ─────────────────────────────────────────────
     Establishes a CSS container named "embed-preview" so that child components
     (UnifiedEmbedPreview) can use @container queries to switch between
     compact (≤300px) and expanded (>300px) layouts. */
  .embed-preview-large-container {
    container-type: inline-size;
    container-name: embed-preview;
    width: 100%;
  }


  .embed-preview-large-content {
    width: 100%;
  }

  .embed-preview-large-content--hidden {
    visibility: hidden;
  }

  /* ── Non-first cards: overlay ────────────────────────────────────────────── */
  /* margin-top is set dynamically via style binding based on isExpanded */
  .embed-preview-large-overlay {
    position: relative;
    z-index: 2;
  }

  .embed-preview-large-overlay--hidden {
    display: none;
  }

  /* ── Carousel arrows ─────────────────────────────────────────────────────── */
  .carousel-arrow {
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    padding: 0 !important;
    min-width: unset !important;
    width: 36px !important;
    height: 36px !important;
    border-radius: 50% !important;
    background-color: var(--color-grey-50) !important;
    opacity: 0.5;
    filter: none !important;
    margin: 0 !important;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: opacity 0.15s ease;
    z-index: 20;
    pointer-events: auto;
  }

  .carousel-arrow:hover {
    opacity: 0.75;
    scale: none !important;
  }

  .carousel-arrow:active {
    opacity: 0.9;
    scale: none !important;
    filter: none !important;
  }

  .carousel-arrow-left {
    left: 8px;
  }

  .carousel-arrow-right {
    right: 8px;
  }
</style>
