<script lang="ts">
  // frontend/packages/ui/src/components/embeds/EmbedPreviewLarge.svelte
  //
  // Purpose: Render [!](embed:ref) using per-type EmbedPreviewLarge components
  // (WebsiteEmbedPreviewLarge, WebSearchEmbedPreviewLarge, etc.) based on appId,
  // with carousel behavior for consecutive large preview nodes.
  //
  // Architecture: routes to per-type XxxEmbedPreviewLarge.svelte files, each of
  // which wraps EmbedReferencePreview in UnifiedEmbedPreviewLarge for full-width
  // large presentation. Per-type files can be individually customised over time.
  // Tests: frontend/packages/ui/src/message_parsing/__tests__/parse_message.test.ts

  import { writable } from 'svelte/store';
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
  import EventsSearchEmbedPreviewLarge from './events/EventsSearchEmbedPreviewLarge.svelte';
  import HealthSearchEmbedPreviewLarge from './health/HealthSearchEmbedPreviewLarge.svelte';
  import ShoppingSearchEmbedPreviewLarge from './shopping/ShoppingSearchEmbedPreviewLarge.svelte';
  import TravelSearchEmbedPreviewLarge from './travel/TravelSearchEmbedPreviewLarge.svelte';
  import TravelStaysEmbedPreviewLarge from './travel/TravelStaysEmbedPreviewLarge.svelte';
  import TravelPriceCalendarEmbedPreviewLarge from './travel/TravelPriceCalendarEmbedPreviewLarge.svelte';
  import MathCalculateEmbedPreviewLarge from './math/MathCalculateEmbedPreviewLarge.svelte';
  import CodeGetDocsEmbedPreviewLarge from './code/CodeGetDocsEmbedPreviewLarge.svelte';
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
  }

  let {
    embedRef,
    embedId = null,
    appId = null,
    carouselIndex,
    carouselTotal,
  }: Props = $props();

  // ── Carousel state ──────────────────────────────────────────────────────
  const carouselStateMap = new Map<string, ReturnType<typeof writable<number>>>();

  function getCarouselStore(runKey: string) {
    if (!carouselStateMap.has(runKey)) {
      carouselStateMap.set(runKey, writable(0));
    }
    return carouselStateMap.get(runKey)!;
  }

  let runKey = $derived(
    carouselIndex === 0 ? embedRef : `_run_${embedRef.replace(/-[a-zA-Z0-9]{3}$/, '')}_${carouselTotal}`,
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
  let dotIndices = $derived(Array.from({ length: carouselTotal }, (_, i) => i));

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
      // Use appId hint from parse-time when embed not yet resolved
      resolvedAppId = appId;
      resolvedSkillId = null;
      return;
    }

    resolveEmbed(currentEmbedId).then(async (data) => {
      if (!data) return;
      // appId from store (may be more accurate than parse-time hint)
      if (data.app_id) resolvedAppId = data.app_id as string;
      // Decode content to get skill_id
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
    | typeof EventsSearchEmbedPreviewLarge
    | typeof HealthSearchEmbedPreviewLarge
    | typeof ShoppingSearchEmbedPreviewLarge
    | typeof TravelSearchEmbedPreviewLarge
    | typeof TravelStaysEmbedPreviewLarge
    | typeof TravelPriceCalendarEmbedPreviewLarge
    | typeof MathCalculateEmbedPreviewLarge
    | typeof CodeGetDocsEmbedPreviewLarge
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
      // website embed (no skill — direct type)
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
    if (aid === 'math') return MathCalculateEmbedPreviewLarge;
    if (aid === 'code') return CodeGetDocsEmbedPreviewLarge;
    if (aid === 'reminder') return ReminderEmbedPreviewLarge;
    if (aid === 'pdf') return PdfViewEmbedPreviewLarge;
    if (aid === 'audio' || aid === 'recording') return RecordingEmbedPreviewLarge;
    if (aid === 'docs') return DocsEmbedPreviewLarge;
    if (aid === 'mail') return MailEmbedPreviewLarge;
    if (aid === 'sheets') return SheetEmbedPreviewLarge;

    // Generic fallback: use EmbedReferencePreview inside UnifiedEmbedPreviewLarge
    return null;
  });
</script>

{#if isVisible || isFirstCard}
  <div class="embed-preview-large-wrapper" class:embed-preview-large-wrapper--hidden={!isVisible}>
    {#if largeComponent === WebsiteEmbedPreviewLarge}
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
    {:else if largeComponent === CodeGetDocsEmbedPreviewLarge}
      <CodeGetDocsEmbedPreviewLarge {embedRef} embedId={resolvedEmbedId} />
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
      <!-- Generic fallback for embed types without a dedicated large component -->
      <UnifiedEmbedPreviewLarge>
        <EmbedReferencePreview {embedRef} embedId={resolvedEmbedId} variant="large" />
      </UnifiedEmbedPreviewLarge>
    {/if}

    {#if isFirstCard && hasMultiple}
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

      <div class="embed-preview-large-dots" aria-hidden="true">
        {#each dotIndices as i}
          <span class="dot" class:dot--active={i === currentIndex}></span>
        {/each}
      </div>
    {/if}
  </div>
{/if}

<style>
  .embed-preview-large-wrapper {
    position: relative;
    width: 100%;
  }

  .embed-preview-large-wrapper--hidden {
    display: none;
  }

  .embed-preview-large-dots {
    display: flex;
    justify-content: center;
    gap: 5px;
    margin-top: 4px;
    margin-bottom: 2px;
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-grey-40);
    transition: background 0.2s ease, transform 0.2s ease;
  }

  .dot--active {
    background: var(--color-font-primary);
    transform: scale(1.2);
  }

  .carousel-arrow {
    position: absolute;
    top: 8px;
    bottom: 26px;
    padding: 0 !important;
    min-width: unset !important;
    width: 40px !important;
    height: auto !important;
    border-radius: 0 !important;
    background-color: transparent !important;
    filter: none !important;
    margin: 0 !important;
    border: none;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background-color 0.15s ease;
    z-index: 20;
    pointer-events: auto;
  }

  .carousel-arrow:hover {
    background-color: rgba(255, 255, 255, 0.1) !important;
    scale: none !important;
  }

  .carousel-arrow:active {
    background-color: rgba(255, 255, 255, 0.18) !important;
    scale: none !important;
    filter: none !important;
  }

  .carousel-arrow-left {
    left: 0;
    border-radius: 0 10px 10px 0 !important;
  }

  .carousel-arrow-right {
    right: 0;
    border-radius: 10px 0 0 10px !important;
  }
</style>
