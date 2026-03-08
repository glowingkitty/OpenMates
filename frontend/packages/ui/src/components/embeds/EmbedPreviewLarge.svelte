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
  // Purpose: Render [!](embed:ref) using per-type EmbedPreviewLarge components
  // (WebsiteEmbedPreviewLarge, WebSearchEmbedPreviewLarge, etc.) based on appId,
  // with carousel/slideshow behavior for consecutive large preview nodes.
  //
  // Architecture: routes to per-type XxxEmbedPreviewLarge.svelte files, each of
  // which wraps EmbedReferencePreview in UnifiedEmbedPreviewLarge for full-width
  // large presentation. Per-type files can be individually customised over time.
  //
  // Carousel layout:
  //   - The FIRST card (carouselIndex === 0) is always rendered and acts as the
  //     carousel shell. It holds the left/right arrows for navigation.
  //   - When carouselIndex > 0 the card overlays on top of the first card using
  //     position: absolute; only the active card is shown (display: none for others).
  //   - The first card's content uses visibility: hidden (not display: none) when
  //     another card is active so the shell keeps its 350px height for the arrows.
  //
  // Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts

  import { getLucideIcon } from '../../utils/categoryUtils';
  import UnifiedEmbedPreviewLarge from './UnifiedEmbedPreviewLarge.svelte';
  import EmbedReferencePreview from './EmbedReferencePreview.svelte';

  // Per-type large preview imports
  import WebsiteEmbedPreviewLarge from './web/WebsiteEmbedPreviewLarge.svelte';
  import WebSearchEmbedPreviewLarge from './web/WebSearchEmbedPreviewLarge.svelte';
  import WebReadEmbedPreviewLarge from './web/WebReadEmbedPreviewLarge.svelte';
  import NewsSearchEmbedPreviewLarge from './news/NewsSearchEmbedPreviewLarge.svelte';
  import VideosSearchEmbedPreviewLarge from './videos/VideosSearchEmbedPreviewLarge.svelte';
  import MapsSearchEmbedPreviewLarge from './maps/MapsSearchEmbedPreviewLarge.svelte';
  import MapsLocationEmbedPreviewLarge from './maps/MapsLocationEmbedPreviewLarge.svelte';
  import ImagesSearchEmbedPreviewLarge from './images/ImagesSearchEmbedPreviewLarge.svelte';
  import ImageGenerateEmbedPreviewLarge from './images/ImageGenerateEmbedPreviewLarge.svelte';
  import ImageViewEmbedPreviewLarge from './images/ImageViewEmbedPreviewLarge.svelte';
  import ImageResultEmbedPreviewLarge from './images/ImageResultEmbedPreviewLarge.svelte';
  import EventsSearchEmbedPreviewLarge from './events/EventsSearchEmbedPreviewLarge.svelte';
  import HealthSearchEmbedPreviewLarge from './health/HealthSearchEmbedPreviewLarge.svelte';
  import ShoppingSearchEmbedPreviewLarge from './shopping/ShoppingSearchEmbedPreviewLarge.svelte';
  import TravelSearchEmbedPreviewLarge from './travel/TravelSearchEmbedPreviewLarge.svelte';
  import TravelStaysEmbedPreviewLarge from './travel/TravelStaysEmbedPreviewLarge.svelte';
  import TravelPriceCalendarEmbedPreviewLarge from './travel/TravelPriceCalendarEmbedPreviewLarge.svelte';
  import MathCalculateEmbedPreviewLarge from './math/MathCalculateEmbedPreviewLarge.svelte';
  import MathPlotEmbedPreviewLarge from './math/MathPlotEmbedPreviewLarge.svelte';
  import CodeGetDocsEmbedPreviewLarge from './code/CodeGetDocsEmbedPreviewLarge.svelte';
  import CodeEmbedPreviewLarge from './code/CodeEmbedPreviewLarge.svelte';
  import ReminderEmbedPreviewLarge from './reminder/ReminderEmbedPreviewLarge.svelte';
  import PdfViewEmbedPreviewLarge from './pdf/PdfViewEmbedPreviewLarge.svelte';
  import RecordingEmbedPreviewLarge from './audio/RecordingEmbedPreviewLarge.svelte';
  import DocsEmbedPreviewLarge from './docs/DocsEmbedPreviewLarge.svelte';
  import MailEmbedPreviewLarge from './mail/MailEmbedPreviewLarge.svelte';
  import SheetEmbedPreviewLarge from './sheets/SheetEmbedPreviewLarge.svelte';

  import {
    embedStore,
    embedRefIndexVersion,
  } from '../../services/embedStore';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';

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
    appId = null,
    carouselIndex,
    carouselTotal,
    runRef = '',
  }: Props = $props();

  // ── Carousel state ──────────────────────────────────────────────────────
  // carouselStateMap and getCarouselStore live in the <script module> block
  // so all instances share the same stores. See module script above.

  // All cards in a run share the same carousel store. The store key is the
  // first card's embedRef (runRef prop set by parse_message.ts Phase B).
  // Single cards (carouselTotal === 1) use their own embedRef as the key.
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

  // ── Responsive width detection ─────────────────────────────────────────
  // When the surrounding chat message container is too narrow (< 480px),
  // fall back to the regular (non-large) embed preview rendering.
  // Uses a ResizeObserver on the wrapper element to detect available width.
  const LARGE_MIN_WIDTH = 480;
  let wrapperElement = $state<HTMLElement | undefined>(undefined);
  let containerWidth = $state(Infinity);
  let useSmallFallback = $derived(containerWidth < LARGE_MIN_WIDTH);

  import { onMount, onDestroy } from 'svelte';
  let resizeObserver: ResizeObserver | null = null;

  onMount(() => {
    if (wrapperElement) {
      resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          containerWidth = entry.contentRect.width;
        }
      });
      resizeObserver.observe(wrapperElement);
    }
  });

  onDestroy(() => {
    resizeObserver?.disconnect();
  });

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

  // ── Embed type resolution ────────────────────────────────────────────────
  // Resolve the embed to determine appId + skillId so we can route to the
  // correct per-type large component. appId from parse-time props is used as
  // a fast hint; skillId is resolved asynchronously from embed store content.

  let resolvedEmbedId = $derived.by(() => {
    void $embedRefIndexVersion;
    return embedId || embedStore.resolveByRef(embedRef) || null;
  });

  let resolvedAppId = $state<string | null>(null);
  let resolvedSkillId = $state<string | null>(null);

  // Initialize resolvedAppId from prop on mount
  $effect(() => {
    if (resolvedAppId === null) {
      resolvedAppId = appId;
    }
  });

  $effect(() => {
    const currentEmbedId = resolvedEmbedId;
    if (!currentEmbedId) {
      resolvedAppId = appId;
      resolvedSkillId = null;
      return;
    }

    resolveEmbed(currentEmbedId).then(async (data) => {
      if (!data) return;
      // app_id is not in the EmbedData type; it's in decoded content (handled below).
      // Use unknown cast to access it if present at runtime (older embed records stored it at root level).
      const rootAppId = (data as unknown as Record<string, unknown>).app_id;
      if (rootAppId) resolvedAppId = rootAppId as string;
      if (data.content) {
        try {
          const decoded = await decodeToonContent(data.content);
          if (decoded?.skill_id) resolvedSkillId = decoded.skill_id as string;
          if (decoded?.app_id) resolvedAppId = decoded.app_id as string;
        } catch {
          // ignore decode errors; will fall through to generic fallback
        }
      }
    }).catch(() => {
      // ignore; will use appId hint
    });
  });

  /**
   * Map appId + skillId to the correct large preview component.
   * Returns null to use the generic UnifiedEmbedPreviewLarge fallback.
   */
  type LargeComponent =
    | typeof WebsiteEmbedPreviewLarge
    | typeof WebSearchEmbedPreviewLarge
    | typeof WebReadEmbedPreviewLarge
    | typeof NewsSearchEmbedPreviewLarge
    | typeof VideosSearchEmbedPreviewLarge
    | typeof MapsSearchEmbedPreviewLarge
    | typeof MapsLocationEmbedPreviewLarge
    | typeof ImagesSearchEmbedPreviewLarge
    | typeof ImageGenerateEmbedPreviewLarge
    | typeof ImageViewEmbedPreviewLarge
    | typeof ImageResultEmbedPreviewLarge
    | typeof EventsSearchEmbedPreviewLarge
    | typeof HealthSearchEmbedPreviewLarge
    | typeof ShoppingSearchEmbedPreviewLarge
    | typeof TravelSearchEmbedPreviewLarge
    | typeof TravelStaysEmbedPreviewLarge
    | typeof TravelPriceCalendarEmbedPreviewLarge
    | typeof MathCalculateEmbedPreviewLarge
    | typeof MathPlotEmbedPreviewLarge
    | typeof CodeGetDocsEmbedPreviewLarge
    | typeof CodeEmbedPreviewLarge
    | typeof ReminderEmbedPreviewLarge
    | typeof PdfViewEmbedPreviewLarge
    | typeof RecordingEmbedPreviewLarge
    | typeof DocsEmbedPreviewLarge
    | typeof MailEmbedPreviewLarge
    | typeof SheetEmbedPreviewLarge
    | null;

  let largeComponent = $derived.by((): LargeComponent => {
    const aid = resolvedAppId;
    const sid = resolvedSkillId;

    if (aid === 'web') {
      if (sid === 'search') return WebSearchEmbedPreviewLarge;
      if (sid === 'read') return WebReadEmbedPreviewLarge;
      return WebsiteEmbedPreviewLarge;
    }
    if (aid === 'news') return NewsSearchEmbedPreviewLarge;
    if (aid === 'videos') return VideosSearchEmbedPreviewLarge;
    if (aid === 'maps') {
      if (sid === 'location') return MapsLocationEmbedPreviewLarge;
      return MapsSearchEmbedPreviewLarge;
    }
    if (aid === 'images') {
      if (sid === 'generate' || sid === 'generate_draft') return ImageGenerateEmbedPreviewLarge;
      if (sid === 'view') return ImageViewEmbedPreviewLarge;
      if (sid === 'image_result') return ImageResultEmbedPreviewLarge;
      return ImagesSearchEmbedPreviewLarge;
    }
    if (aid === 'events') return EventsSearchEmbedPreviewLarge;
    if (aid === 'health') return HealthSearchEmbedPreviewLarge;
    if (aid === 'shopping') return ShoppingSearchEmbedPreviewLarge;
    if (aid === 'travel') {
      if (sid === 'search_stays') return TravelStaysEmbedPreviewLarge;
      if (sid === 'price_calendar') return TravelPriceCalendarEmbedPreviewLarge;
      return TravelSearchEmbedPreviewLarge;
    }
    if (aid === 'math') {
      if (sid === 'plot' || (!sid && !resolvedEmbedId)) return MathPlotEmbedPreviewLarge;
      return MathCalculateEmbedPreviewLarge;
    }
    if (aid === 'code') {
      if (sid === 'get_docs') return CodeGetDocsEmbedPreviewLarge;
      return CodeEmbedPreviewLarge;
    }
    if (aid === 'reminder') return ReminderEmbedPreviewLarge;
    if (aid === 'pdf') return PdfViewEmbedPreviewLarge;
    if (aid === 'audio' || aid === 'recording') return RecordingEmbedPreviewLarge;
    if (aid === 'docs') return DocsEmbedPreviewLarge;
    if (aid === 'mail') return MailEmbedPreviewLarge;
    if (aid === 'sheets') return SheetEmbedPreviewLarge;

    return null;
  });
</script>

<!--
  Carousel layout:
  - First card (carouselIndex === 0):
    - Wrapper is ALWAYS rendered (never hidden) so it serves as the persistent
      carousel shell holding the navigation arrows.
    - The embed content inside uses visibility:hidden when another slide is active
      so the shell retains its 350px height and the arrows stay positioned correctly.
  - Non-first cards (carouselIndex > 0):
    - Rendered as position:absolute overlays on top of the first card's shell.
    - display:none when not the active slide; visible otherwise.
    - Not rendered at all (via {#if}) when carouselTotal === 1 (no carousel).
-->

{#if isFirstCard}
  <!-- First card: always-visible carousel shell.
       bind:this for ResizeObserver width detection (responsive fallback). -->
  <div class="embed-preview-large-wrapper embed-preview-large-shell" class:embed-small-fallback={useSmallFallback} bind:this={wrapperElement}>
    <!-- Embed content: hidden (not removed) when another slide is active.
         When container is too narrow (< 480px), falls back to regular (non-large) preview. -->
    <div class="embed-preview-large-content" class:embed-preview-large-content--hidden={!isVisible}>
      {#if useSmallFallback}
        <!-- Small container fallback: render regular embed preview instead of large -->
        <EmbedReferencePreview {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === WebsiteEmbedPreviewLarge}
        <WebsiteEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === WebSearchEmbedPreviewLarge}
        <WebSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === WebReadEmbedPreviewLarge}
        <WebReadEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === NewsSearchEmbedPreviewLarge}
        <NewsSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === VideosSearchEmbedPreviewLarge}
        <VideosSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === MapsSearchEmbedPreviewLarge}
        <MapsSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === MapsLocationEmbedPreviewLarge}
        <MapsLocationEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === ImagesSearchEmbedPreviewLarge}
        <ImagesSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === ImageGenerateEmbedPreviewLarge}
        <ImageGenerateEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === ImageViewEmbedPreviewLarge}
        <ImageViewEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === ImageResultEmbedPreviewLarge}
        <ImageResultEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === EventsSearchEmbedPreviewLarge}
        <EventsSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === HealthSearchEmbedPreviewLarge}
        <HealthSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === ShoppingSearchEmbedPreviewLarge}
        <ShoppingSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === TravelSearchEmbedPreviewLarge}
        <TravelSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === TravelStaysEmbedPreviewLarge}
        <TravelStaysEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === TravelPriceCalendarEmbedPreviewLarge}
        <TravelPriceCalendarEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === MathCalculateEmbedPreviewLarge}
        <MathCalculateEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === MathPlotEmbedPreviewLarge}
        <MathPlotEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === CodeGetDocsEmbedPreviewLarge}
        <CodeGetDocsEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === CodeEmbedPreviewLarge}
        <CodeEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === ReminderEmbedPreviewLarge}
        <ReminderEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === PdfViewEmbedPreviewLarge}
        <PdfViewEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === RecordingEmbedPreviewLarge}
        <RecordingEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === DocsEmbedPreviewLarge}
        <DocsEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === MailEmbedPreviewLarge}
        <MailEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else if largeComponent === SheetEmbedPreviewLarge}
        <SheetEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
      {:else}
        <UnifiedEmbedPreviewLarge>
          <EmbedReferencePreview {embedRef} embedId={resolvedEmbedId} variant="large" />
        </UnifiedEmbedPreviewLarge>
      {/if}
    </div>

    <!-- Navigation arrows: always inside the first card shell.
         Hidden when using small fallback (regular preview). -->
    {#if hasMultiple && !useSmallFallback}
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
  <!-- Non-first cards: absolute overlay on top of the first card's shell.
       display:none when not the active slide. -->
  <div
    class="embed-preview-large-wrapper embed-preview-large-overlay"
    class:embed-preview-large-overlay--hidden={!isVisible}
    class:embed-small-fallback={useSmallFallback}
  >
    {#if useSmallFallback}
      <!-- Small container fallback: render regular embed preview instead of large -->
      <EmbedReferencePreview {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === WebsiteEmbedPreviewLarge}
      <WebsiteEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === WebSearchEmbedPreviewLarge}
      <WebSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === WebReadEmbedPreviewLarge}
      <WebReadEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === NewsSearchEmbedPreviewLarge}
      <NewsSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === VideosSearchEmbedPreviewLarge}
      <VideosSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === MapsSearchEmbedPreviewLarge}
      <MapsSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === MapsLocationEmbedPreviewLarge}
      <MapsLocationEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === ImagesSearchEmbedPreviewLarge}
      <ImagesSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === ImageGenerateEmbedPreviewLarge}
      <ImageGenerateEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === ImageViewEmbedPreviewLarge}
      <ImageViewEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === ImageResultEmbedPreviewLarge}
      <ImageResultEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === EventsSearchEmbedPreviewLarge}
      <EventsSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === HealthSearchEmbedPreviewLarge}
      <HealthSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === ShoppingSearchEmbedPreviewLarge}
      <ShoppingSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === TravelSearchEmbedPreviewLarge}
      <TravelSearchEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === TravelStaysEmbedPreviewLarge}
      <TravelStaysEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === TravelPriceCalendarEmbedPreviewLarge}
      <TravelPriceCalendarEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === MathCalculateEmbedPreviewLarge}
      <MathCalculateEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === MathPlotEmbedPreviewLarge}
      <MathPlotEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === CodeGetDocsEmbedPreviewLarge}
      <CodeGetDocsEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === CodeEmbedPreviewLarge}
      <CodeEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === ReminderEmbedPreviewLarge}
      <ReminderEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === PdfViewEmbedPreviewLarge}
      <PdfViewEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === RecordingEmbedPreviewLarge}
      <RecordingEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === DocsEmbedPreviewLarge}
      <DocsEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === MailEmbedPreviewLarge}
      <MailEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else if largeComponent === SheetEmbedPreviewLarge}
      <SheetEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
    {:else}
      <UnifiedEmbedPreviewLarge>
        <EmbedReferencePreview {embedRef} embedId={resolvedEmbedId} variant="large" />
      </UnifiedEmbedPreviewLarge>
    {/if}
  </div>
{/if}

<style>
  /* ── Shared wrapper ──────────────────────────────────────────────────────── */
  .embed-preview-large-wrapper {
    position: relative;
    width: 100%;
  }

  /* ── First card: carousel shell ─────────────────────────────────────────── */
  /* Always visible. min-height matches the large card height (350px) +
     translateY overflow (15px) so arrows are
     always correctly positioned even when the first card's content is hidden. */
  .embed-preview-large-shell {
    min-height: 365px;
  }

  /* When container is small enough for fallback, reduce shell height to
     match the regular (non-large) embed preview height */
  .embed-preview-large-shell.embed-small-fallback {
    min-height: unset;
  }

  /* Hide the first card's embed content (not the shell) when another slide is active.
     visibility:hidden keeps the element in the flow, preserving the shell height. */
  .embed-preview-large-content {
    width: 100%;
  }

  .embed-preview-large-content--hidden {
    visibility: hidden;
  }

  /* ── Non-first cards: absolute overlay ──────────────────────────────────── */
  /* Positioned absolutely on top of the first card shell. The shell's
     position:relative establishes the containing block, but since TipTap renders
     each EmbedPreviewLarge as a sibling node, we rely on the natural DOM stacking.
     top:0 aligns with the top of the shell (which is the previous sibling). */
  .embed-preview-large-overlay {
    /* Overlay is stacked directly after the shell in the DOM flow.
       Use negative margin-top to visually overlap the shell. The shell keeps its
       height via min-height so the total layout space is the shell's 365px. */
    margin-top: calc(-365px);
    /* Ensure the overlay sits above the (now invisible) shell content */
    position: relative;
    z-index: 2;
  }

  /* When in small fallback mode, don't overlap as the height is different */
  .embed-preview-large-overlay.embed-small-fallback {
    margin-top: 0;
  }

  .embed-preview-large-overlay--hidden {
    display: none;
  }

  /* ── Carousel arrows ─────────────────────────────────────────────────────── */
  /* Positioned absolute within the shell. top/bottom span the card area (350px)
     positioned to span the card area. */
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
