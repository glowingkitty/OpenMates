<script module lang="ts">
  // Module-level state shared across ALL instances of EmbedPreviewLarge.
  // Each carousel "run" (consecutive large embeds) shares a single writable
  // store keyed by the first card's embedRef (runRef). This MUST be module-level
  // so that all instances in the same run read/write the same store.
  import { writable } from 'svelte/store';

  const carouselStateMap = new Map<string, ReturnType<typeof writable<number>>>();
  const shellHeightMap = new Map<string, ReturnType<typeof writable<number>>>();

  function getCarouselStore(key: string) {
    if (!carouselStateMap.has(key)) {
      carouselStateMap.set(key, writable(0));
    }
    return carouselStateMap.get(key)!;
  }

  /** Shared shell height per carousel run — first card writes, others read. */
  function getShellHeightStore(key: string) {
    if (!shellHeightMap.has(key)) {
      shellHeightMap.set(key, writable(215));
    }
    return shellHeightMap.get(key)!;
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
  //   - When container width ≤ 400px: compact card (300×200px standard layout)
  //   - When container width > 400px: expanded card (full-width × 350px)
  //   CSS container queries handle the switch automatically via the
  //   .embed-preview-large-container wrapper which sets container-type.
  //
  // Carousel layout (for consecutive runs of highlighted embeds):
  //   - The FIRST card (carouselIndex === 0) is always rendered as the "shell"
  //     and holds the left/right navigation arrows.
  //   - Non-first cards overlay on top via position:absolute + translateY.
  //   - All cards stay mounted; visibility crossfades via opacity for smooth transitions.
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
  let shellHeightStore = $derived(getShellHeightStore(runKey));

  let currentIndex = $state(0);
  $effect(() => {
    const unsub = carouselStore.subscribe((value) => {
      currentIndex = value;
    });
    return unsub;
  });

  /** Shell height written by the first card, read by overlay cards for translateY. */
  let sharedShellHeight = $state(215);
  $effect(() => {
    const unsub = shellHeightStore.subscribe((value) => {
      sharedShellHeight = value;
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

  function handleDotClick(e: MouseEvent, index: number) {
    e.preventDefault();
    e.stopPropagation();
    carouselStore.set(index);
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

  // First card's measured rendered height — published to overlays so their
  // translateY matches the actual rendered shell precisely.
  let measuredShellHeight = $state(0);

  onMount(() => {
    if (!wrapperEl) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        isExpanded = entry.contentRect.width > 400;
        const el = entry.target as HTMLElement;
        // Include margin-bottom in the measurement so overlay translateY
        // accounts for the flow gap created by the dots spacing margin
        // (which collapses through the TipTap node-view wrapper div).
        const mb = parseFloat(getComputedStyle(el).marginBottom) || 0;
        measuredShellHeight = el.offsetHeight + mb;
      }
    });
    ro.observe(wrapperEl);
    return () => ro.disconnect();
  });

  let shellMinHeight = $derived(isExpanded ? 365 : 215);

  // First card publishes its actual rendered height so overlay cards can match
  // the translateY precisely. Falls back to shellMinHeight before measurement.
  $effect(() => {
    if (isFirstCard) {
      shellHeightStore.set(measuredShellHeight || shellMinHeight);
    }
  });

</script>

{#if isFirstCard}
  <!-- First card: always-visible carousel shell -->
  <div
    bind:this={wrapperEl}
    class="embed-preview-large-wrapper"
    class:embed-preview-large-wrapper--has-dots={hasMultiple}
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
        class="nav-arrow nav-arrow-left"
        type="button"
        onclick={handlePrevious}
        aria-label="Previous"
      >
        <ChevronLeft size={22} color="rgba(255,255,255,0.85)" />
      </button>

      <button
        class="nav-arrow nav-arrow-right"
        type="button"
        onclick={handleNext}
        aria-label="Next"
      >
        <ChevronRight size={22} color="rgba(255,255,255,0.85)" />
      </button>

      <div class="carousel-dots" role="tablist" aria-label="Carousel position">
        {#each Array(carouselTotal) as _, i}
          <button
            class="carousel-dot"
            class:carousel-dot--active={currentIndex === i}
            type="button"
            role="tab"
            aria-selected={currentIndex === i}
            aria-label={`Go to slide ${i + 1} of ${carouselTotal}`}
            onclick={(e) => handleDotClick(e, i)}
          ></button>
        {/each}
      </div>
    {/if}
  </div>
{:else if hasMultiple}
  <!-- Non-first cards: zero-height anchor keeps overlays out of document flow.
       The overlay is position:absolute inside, painted over the shell via
       transform, so it contributes 0px to the carousel's flow height. -->
  <div class="embed-preview-large-overlay-anchor">
    <div
      class="embed-preview-large-overlay"
      class:embed-preview-large-overlay--hidden={!isVisible}
      style="transform: translateY(-{sharedShellHeight}px);"
    >
      <div class="embed-preview-large-container">
        <EmbedReferencePreview {embedRef} embedId={resolvedEmbedId} variant="large" />
      </div>
    </div>
  </div>
{/if}

<style>
  /* ── Shared wrapper ──────────────────────────────────────────────────────── */
  .embed-preview-large-wrapper {
    position: relative;
    width: 100%;
  }

  /* Reserve space below the carousel for the floating pagination dots.
     This MUST be on the shell (not on an overlay), because the shell
     contains the absolutely-positioned dots and its min-height can exceed
     the overlay heights — if so, the overlay's margin-bottom would sit
     *inside* the shell's height and never create actual spacing. */
  .embed-preview-large-wrapper--has-dots {
    margin-bottom: 24px;
  }

  /* ── Container query context ─────────────────────────────────────────────
     Establishes a CSS container named "embed-preview" so that child components
     (UnifiedEmbedPreview) can use @container queries to switch between
     compact (≤400px) and expanded (>400px) layouts. */
  .embed-preview-large-container {
    container-type: inline-size;
    container-name: embed-preview;
    width: 100%;
  }


  .embed-preview-large-content {
    width: 100%;
    opacity: 1;
    transition: opacity var(--duration-normal) var(--easing-default);
  }

  .embed-preview-large-content--hidden {
    opacity: 0;
    pointer-events: none;
  }

  /* ── Non-first cards: out-of-flow overlay ─────────────────────────────────
     The anchor is 0px tall in flow so overlays never affect the carousel's
     flow height — only the shell does. The overlay is position:absolute
     inside the anchor and uses transform to slide over the shell. */
  .embed-preview-large-overlay-anchor {
    height: 0;
    overflow: visible;
    position: relative;
  }

  .embed-preview-large-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    z-index: var(--z-index-raised-2);
    opacity: 1;
    transition: opacity var(--duration-normal) var(--easing-default);
  }

  .embed-preview-large-overlay--hidden {
    opacity: 0;
    pointer-events: none;
  }

  /* ── Pagination dots ─────────────────────────────────────────────────────── */
  .carousel-dots {
    position: absolute;
    bottom: -8px;
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    gap: 6px;
    padding: 6px 10px;
    border-radius: 999px;
    background-color: rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    z-index: var(--z-index-dropdown-2);
    pointer-events: auto;
  }

  .carousel-dot {
    width: 7px;
    height: 7px;
    padding: 0 !important;
    min-width: unset !important;
    border: none;
    border-radius: 50% !important;
    background-color: rgba(255, 255, 255, 0.45) !important;
    cursor: pointer;
    transition: background-color var(--duration-fast) var(--easing-default),
                width var(--duration-fast) var(--easing-default);
    margin: 0 !important;
    filter: none !important;
  }

  .carousel-dot:hover {
    background-color: rgba(255, 255, 255, 0.7) !important;
    scale: none !important;
  }

  .carousel-dot--active {
    width: 18px;
    border-radius: 999px !important;
    background-color: rgba(255, 255, 255, 0.95) !important;
  }

  /* ── Navigation arrows (matches ChatHeader .nav-arrow style) ────────────── */
  .nav-arrow {
    position: absolute;
    top: 0;
    bottom: 0;
    padding: 0 !important;
    min-width: unset !important;
    width: 40px !important;
    height: 100% !important;
    border-radius: 0 !important;
    background-color: transparent !important;
    filter: none !important;
    margin: 0 !important;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background-color var(--duration-fast) var(--easing-default);
    z-index: var(--z-index-dropdown-2);
    pointer-events: auto;
    flex-shrink: 0;
  }

  .nav-arrow:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
    scale: none !important;
  }

  .nav-arrow:active {
    background-color: rgba(255, 255, 255, 0.18) !important;
    scale: none !important;
    filter: none !important;
  }

  .nav-arrow-left {
    left: 0;
    border-radius: 0 10px 10px 0 !important;
  }

  .nav-arrow-right {
    right: 0;
    border-radius: var(--radius-4) 0 0 10px !important;
  }
</style>
